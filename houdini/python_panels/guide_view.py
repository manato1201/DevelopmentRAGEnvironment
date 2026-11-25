"""
guide_view.py — Guide タブ: 保存したチュートリアルを、手順ごとに案内する（2026-11-03）

手順を1つずつ表示し、「見るタブ」「操作するノード」「変えるパラメータ（場所つき）」「使うショートカット」を示す。
「この手順を案内」を押すと、Houdini の画面を動かす: 見るタブを前面に出し、操作するノードを選んで画面に収め、短い表示を出す。
Houdini の画面の部品を消したり、色や設定を書き換えたりはしない（示すだけ）。

案内データは、チュートリアルの保存時に `<名前>_guide.json` として書かれる（tutorial_view.py / guide_mode.py）。
Houdini の外（hou が無い環境）では、手順の表示だけできる。

2026-11-17（実証実験の指摘）:
  ・ショートカットは、最初の手順だけ出し、あとは折りたたむ（ボタンで開く。設定は覚える）。
  ・パスは省略しない（長いときは折り返す）。いまのネットワークの階層を、常に表示する。
  ・チェックボックス・メニューは、表示名で言う（「Run Over を Detail (only once) にする」）。変えるパラメータは、タブ・項目・前の値つき。
  ・手順の冒頭に、作業する部分と、そのノードの目的を出す。消す手順は「消す」と言う。
  ・チュートリアルの生成が終わったら、このタブへ自動で切り替えて、最新の手順を読み込む（announce_generated / announce_saved）。
  ・手順だけの小さな別ウィンドウ（ほかのタブと並べて見るため）。
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Callable

import basics_guide
import display_isolation
import guide_mode
import houdini_terms
import tool_analogies
import guide_shortcuts
import panel_paths
import threading

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap, QTextOption
from panel_actions import action_button, button_qss, px, type_font, type_qss
from panel_widgets import CollapsibleBox
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

try:
    import hou  # type: ignore[import-not-found]
except ImportError:  # Houdini の外（テスト・単体確認）
    hou = None  # type: ignore[assignment]

_SECTION_TITLES = (("prerequisites", "前提条件"), ("tips", "TIPS"), ("challenge", "自分でやってみよう"))


_PARM_BG, _PARM_BAR = "#13301f", "#4ade80"  # 変えるパラメータの帯（背景・左の線）
_WORK_STYLE = "background-color:#1e3a5f;color:#e0f2fe;padding:4px"
_DELETE_STYLE = "background-color:#5f1e1e;color:#fee2e2;padding:4px"
_TAB_BASE_TEXT = "Guide"
_TAB_NEW_TEXT = "Guide ●"
_AUTO_SWITCH_KEY = "guide_auto_switch"
_SHORTCUTS_KEY = "guide_shortcuts_open"
_PARM_FOCUS_KEY = "guide_parm_focus"
_MODE_KEY = "guide_target_mode"
_PILOT_KEY = "pilot_enabled"  # 「実証実験に参加する」（rag_chatbot）。入っているときだけ、練習の進み具合を送る
_BASICS_SENT_KEY = "basics_sent_step"  # 送った手順の最大（同じ手順を何度も送らない）


def report_basics_progress(cfg: dict, step: int, total: int, post=None) -> bool:
    """基本操作の練習の進み具合を、実証実験の記録に送る（2026-11-26）。実験に参加していない・Cloudflare でない・
    もう送った手順なら、送らない。送ったら True。送信は別スレッドで、失敗しても画面は止めない（次に進んだときに、また送る）。"""
    if not bool(_state_get(_PILOT_KEY, False)) or (cfg or {}).get("mode") != "cloudflare":
        return False
    sent = int(_state_get(_BASICS_SENT_KEY, 0) or 0)
    if step <= sent:
        return False

    def send() -> None:
        try:
            if post is not None:
                result = post(step, total)
            else:
                from rag_client import RAGClient

                result = RAGClient(cfg).pilot_basics(step, total)
            if (result or {}).get("recorded"):  # 事前アンケートの前（記録されない）なら、覚えない（登録したあとに、また送る）
                _state_set(_BASICS_SENT_KEY, max(step, int(_state_get(_BASICS_SENT_KEY, 0) or 0)))
        except Exception:  # noqa: BLE001 -- 送れなくても、練習は続けられる
            pass

    if post is not None:
        send()  # テスト用（同じスレッドで送る）
    else:
        threading.Thread(target=send, daemon=True).start()
    return True


def _connection_lines(step: dict) -> list[str]:
    """つなぐ線を、全部（省略しない）。入力の番号・名前があれば添える。"""
    pairs = [c for c in (step.get("connections") or []) if isinstance(c, dict)]
    if not pairs and step.get("from") and step.get("to"):
        pairs = [{"from": step["from"], "to": step["to"]}]
    lines = []
    for c in pairs:
        extra = ""
        port = c.get("input")
        if isinstance(port, int) and port > 0:
            extra = f"（{port + 1}番目の入力）"
        elif isinstance(port, str) and port:
            extra = f"（入力: {port}）"
        lines.append(f"{c.get('from')} → {c.get('to')}{extra}")
    return lines


def render_step_html(guide: dict, index: int, step_override: dict | None = None, show_shortcuts: bool = True) -> str:
    """手順 index（0始まり）の案内を、表示用の HTML にする。
    step_override: 値の言い換えの情報（guide_mode.attach_parm_info）を付けた、その手順のコピー。
    show_shortcuts: False のとき、ショートカットの一覧は出さない（折りたたみ。ボタンで開く）。"""
    steps = guide.get("steps") or []
    if not steps:
        return ""
    step = step_override or steps[max(0, min(index, len(steps) - 1))]
    esc = html.escape
    sandbox = str(guide.get("sandbox_path") or "")
    places = guide_mode.step_places(step, sandbox)
    rows = []
    work = str(step.get("work") or "")
    if work:
        style = _DELETE_STYLE if work.startswith("【消す】") else _WORK_STYLE
        rows.append(f"<p style='{style}'><b>{esc(work)}</b></p>")
    elif step.get("tool") == "delete_node" and step.get("node"):
        rows.append(f"<p style='{_DELETE_STYLE}'><b>【消す】{esc(step['node'])} を削除する</b></p>")
    rows.append(f"<p style='font-size:13px'><b>{esc(step.get('instruction') or step.get('hint') or '')}</b></p>")
    if step.get("purpose"):
        rows.append(f"<p>このノードの目的: {esc(step['purpose'])}</p>")
    lines = _connection_lines(step) if step.get("tool") == "connect_nodes" else []
    if step.get("hint") and not (lines and len(lines) > 1):  # 複数の線は、下に1本ずつ出すので、まとめた文は出さない
        rows.append(f"<p>{esc(step['hint'])}</p>")
    node_bits = []
    if step.get("node"):
        label = step.get("node_label") or step.get("node_type") or ""
        node_bits.append(f"操作するノード: <b>{esc(places['node'])}</b>" + (f"（{esc(label)}）" if label else ""))
    if places["network"]:
        node_bits.append(f"作業するネットワーク（階層）: <b>{esc(places['network'])}</b>")
    elif step.get("tool") == "create_node" and step.get("node"):
        node_bits.append(f"作業するネットワーク（階層）: <b>{esc(guide_mode.OWN_ROOT)}</b>（Object レベル）")
    if places["sandbox_node"]:
        node_bits.append(f"<span style='color:#94a3b8'>生成したサンドボックスの実物（見本）: {esc(places['sandbox_node'])}</span>")
    node_bits.append(f"見るタブ: <b>{esc(step.get('tab_label') or '')}</b>")
    rows.append("<p>" + "<br>".join(node_bits) + "</p>")
    if step.get("tool") == "create_node" and step.get("node_type"):
        rows.append(tool_analogies.html_block(tool_analogies.for_node(str(step["node_type"]))))  # Maya・Blender でいうと（A27。無ければ空）
    if guide.get("builtin") == basics_guide.KEY:  # 基本操作の練習では、手順に出てくる用語の意味を添える（2026-11-26）
        rows.append(houdini_terms.html_block(houdini_terms.terms_in(f"{step.get('instruction') or ''} {step.get('hint') or ''}")))
    if lines:
        rows.append(f"<p>つなぐ線（{len(lines)}本）:</p><ul>" + "".join(f"<li>{esc(line)}</li>" for line in lines) + "</ul>")
    parms = step.get("parms") or []
    if parms:
        cards = []
        for p in parms:
            d = guide_mode.describe_parm_change(p, p.get("_info"))
            old = f"前の値: {esc(d['old_text'])} → " if d["old_text"] != "" else ""
            name = f"（内部名: <code>{esc(d['name'])}</code>）" if d["name"] else ""
            cut = ""
            if d["kind"] != "code" and len(str(p.get("new") or "")) >= 60:
                cut = "<br><span style='color:#f59e0b'>値が長いため、記録は60文字までです。続きは手順書で確かめてください</span>"
            # 変える項目は、色つきの帯で強調する（Houdini のパラメータ画面には、項目を光らせる API が無いので、この画面で強調する）
            cards.append(
                f"<table width='100%' cellspacing='0' cellpadding='0' style='margin-top:6px'><tr>"
                f"<td width='5' bgcolor='{_PARM_BAR}'></td>"
                f"<td bgcolor='{_PARM_BG}' style='padding:6px 8px'>"
                f"<b style='color:#bbf7d0'>{esc(d['action'])}</b><br>"
                f"パラメータのタブ: <b>{esc(d['where_text'])}</b>、項目: <b>{esc(d['label'])}</b>{name}<br>"
                f"{old}新しい値: <b>{esc(d['new_text'])}</b>{cut}"
                f"</td></tr></table>"
            )
        rows.append("<p style='margin-bottom:0'>変えるパラメータ:</p>" + "".join(cards))
    shortcuts = step.get("shortcuts") or []
    if shortcuts and show_shortcuts:
        rows.append("<p>使うショートカット（Houdini の標準のキー）:</p>")
        groups: dict[str, list[dict]] = {}
        for s in shortcuts:
            groups.setdefault(str(s.get("group") or ""), []).append(s)  # 以前の案内データはグループが無い（まとめて1つ）
        for group, items in groups.items():
            if group:
                rows.append(f"<p style='margin:.5em 0 0'><b>{esc(group)}</b></p>")
            rows.append("<ul>" + "".join(f"<li><code>{esc(s['keys'])}</code> … {esc(s['what'])}</li>" for s in items) + "</ul>")
    elif shortcuts:
        rows.append("<p style='color:#94a3b8'>ショートカットは、下の「ショートカットを表示」で開けます（最初の手順だけ、自動で出します）</p>")
    return "".join(rows)


def shortcuts_visible(index: int, user_open: bool) -> bool:
    """ショートカットの一覧を出すか。最初の手順は必ず出す。あとは、利用者が開いているときだけ。"""
    return index == 0 or bool(user_open)


def render_cheatsheet_html(query: str = "") -> str:
    """ショートカット一覧（全部）。query があれば、キー・操作・グループの名前で絞る。"""
    esc = html.escape
    sections = guide_shortcuts.cheatsheet(query)
    if not sections:
        return f"<p>「{esc(query)}」に合うショートカットはありません。</p>"
    total = sum(len(rows) for _group, rows in sections)
    parts = [f"<p><b>ショートカット一覧</b>（{total}個。Houdini の標準のキー）</p>"]
    for group, rows in sections:
        parts.append(f"<p style='margin:.6em 0 0'><b>{esc(group)}</b></p><ul>")
        parts += [f"<li><code>{esc(r['keys'])}</code> … {esc(r['what'])}</li>" for r in rows]
        parts.append("</ul>")
    used = sorted({r["source"] for _g, rows in sections for r in rows})
    parts.append("<p style='color:#94a3b8'>出典（SideFX 公式ドキュメント）: " + "、".join(
        f"{esc(guide_shortcuts.SOURCES[k][0])} {esc(guide_shortcuts.SOURCES[k][1])}" for k in used if k in guide_shortcuts.SOURCES
    ) + "。ホットキーを変えている場合は、合わないことがあります。</p>")
    return "".join(parts)


def render_sections_html(guide: dict) -> str:
    """手順書の、前提条件・TIPS・自分でやってみよう（あれば）。"""
    esc = html.escape
    parts = []
    for key, title in _SECTION_TITLES:
        body = str(guide.get(key) or "").strip()
        if body:
            parts.append(f"<p><b>{esc(title)}</b></p><p>{esc(body).replace(chr(10), '<br>')}</p>")
    return "".join(parts)


def _state_get(key: str, default=None):
    try:
        from panel_widgets import ui_state_get

        return ui_state_get(key, default)
    except Exception:  # noqa: BLE001 -- 設定が読めなくても、画面は動く
        return default


def _state_set(key: str, value) -> None:
    try:
        from panel_widgets import ui_state_set

        ui_state_set(key, value)
    except Exception:  # noqa: BLE001
        pass


def dedupe_messages(messages: list[str]) -> list[str]:
    """同じ行を、1回だけにする（順番は保つ）。複数行の文は、行ごとに見る。案内のメッセージが、同じ行を繰り返して長くならないように。"""
    seen: set[str] = set()
    out: list[str] = []
    for message in messages:
        for line in str(message).splitlines():
            if line and line not in seen:
                seen.add(line)
                out.append(line)
    return out


_STATUS_MAX_LINES = 4


def compact_messages(messages: list[str]) -> list[str]:
    """案内のメッセージを、短くする（2026-11-19）。同じ行は 1 回に。「示したノード: …」が 3 行以上あるとき（つなぐ手順は、両端のノードを全部言う）は、
    1 行にまとめる。実機で、この行が 14 行並んで、手順の説明の欄を押しつぶしていた。"""
    lines = dedupe_messages(messages)
    shown = [ln for ln in lines if ln.startswith("示したノード:")]
    if len(shown) > 2:
        names = []
        for ln in shown:
            path = ln.split(":", 1)[1].strip().split("（", 1)[0]
            names.append(path.rsplit("/", 1)[-1])
        summary = f"示したノード: {len(shown)}個（{'、'.join(names[:3])}{' ほか' if len(names) > 3 else ''}）"
        out: list[str] = []
        placed = False
        for ln in lines:
            if ln in shown:
                if not placed:
                    out.append(summary)
                    placed = True
            else:
                out.append(ln)
        lines = out
    return lines


def locate_in_tabs(widget: QWidget):
    """widget を中に含む、タブ（QTabWidget）とそのページの番号。見つからなければ None。"""
    node = widget
    while node is not None:
        stack = node.parentWidget()
        if isinstance(stack, QStackedWidget) and isinstance(stack.parentWidget(), QTabWidget):
            tabs = stack.parentWidget()
            index = tabs.indexOf(node)
            if index >= 0:
                return tabs, index
        node = node.parentWidget()
    return None


def _guide_in(tabs: QTabWidget):
    return tabs.findChild(GuideWidget)


def announce_generated(source: QWidget, guide: dict, label: str, switch: bool | None = None) -> str:
    """生成が終わった直後に、Guide タブへ最新の手順を読み込み、切り替える（または、タブに印を付ける）。
    source: 生成した側の画面部品（同じタブの中にあるもの）。戻り値: 画面に出す1文（Guide タブが見つからなければ ""）。"""
    host = locate_in_tabs(source)
    if host is None:
        return ""
    tabs, source_index = host
    widget = _guide_in(tabs)
    if widget is None:
        return ""
    widget.load_generated(guide, label)
    return widget.announce(switch, from_index=source_index)


def announce_saved(source: QWidget, guide_path, switch: bool | None = None) -> str:
    """保存で案内データが書かれたとき: 一覧を更新して、保存したものを選ぶ（生成直後の仮の手順は、これに置き換わる）。"""
    host = locate_in_tabs(source)
    if host is None:
        return ""
    tabs, source_index = host
    widget = _guide_in(tabs)
    if widget is None:
        return ""
    widget.select_saved(Path(guide_path))
    return widget.announce(switch, saved=True, from_index=source_index)


class _ShotLabel(QLabel):
    """押すと、元の大きさの画像を開く画像（お手本の画面）。"""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ShotStrip(QWidget):
    """手順ごとの、お手本の画面（生成のときに撮った、この手順のあとのビューポートとネットワーク。2026-11-25、A25）。
    画像が無い手順では、隠れる。押すと、元の大きさで開く。"""

    WIDTH = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(px(6))
        self._cache: dict[str, QPixmap] = {}  # 見せる・隠すは、外の折りたたみ（Guide の _shots_box）が決める

    def _pixmap(self, path: str) -> QPixmap | None:
        if path not in self._cache:
            image = QPixmap(path)
            if image.isNull():
                return None
            self._cache[path] = image.scaledToWidth(px(self.WIDTH), Qt.SmoothTransformation)
            if len(self._cache) > 40:  # 長い手順書でも、覚えすぎない
                self._cache.pop(next(iter(self._cache)))
        return self._cache[path]

    def show_shots(self, shots: list[tuple[str, str]]) -> int:
        """[(見出し, パス)] を並べる。並べた枚数を返す（0 なら隠す）。"""
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        shown = 0
        for label, path in shots:
            image = self._pixmap(path)
            if image is None:
                continue
            box = QVBoxLayout()
            caption = QLabel(label)
            caption.setStyleSheet(type_qss("caption", "#94a3b8"))
            picture = _ShotLabel()
            picture.setPixmap(image)
            picture.setCursor(Qt.PointingHandCursor)
            picture.setToolTip("押すと、元の大きさで開きます")
            picture.clicked.connect(lambda p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
            box.addWidget(caption)
            box.addWidget(picture)
            self._row.addLayout(box)
            shown += 1
        self._row.addStretch()
        return shown


class GuideStepWindow(QWidget):
    """手順だけの、小さな別ウィンドウ。Houdini の主ウィンドウの上に重なり、ほかのタブ（Chat・Docs など）を見ながら手順を読める。"""

    def __init__(self, owner: "GuideWidget") -> None:
        super().__init__(owner.window(), Qt.Tool)
        self._owner = owner
        self.setWindowTitle("Guide — 手順")
        self.resize(420, 520)
        root = QVBoxLayout(self)
        nav = QHBoxLayout()
        self._prev = QPushButton("◀ 前へ")
        self._next = QPushButton("次へ ▶")
        self._pos = QLabel("")
        self._pos.setAlignment(Qt.AlignCenter)
        self._prev.clicked.connect(lambda: owner._go(-1))
        self._next.clicked.connect(lambda: owner._go(1))
        nav.addWidget(self._prev)
        nav.addWidget(self._pos, stretch=1)
        nav.addWidget(self._next)
        root.addLayout(nav)
        self._where = QLabel("")
        self._where.setWordWrap(True)
        self._where.setStyleSheet("color:#94a3b8;font-size:11px;")
        root.addWidget(self._where)
        self.view = QTextBrowser()
        _wrap_anywhere(self.view)
        root.addWidget(self.view, stretch=1)

    def update_step(self, html_text: str, pos: str, can_prev: bool, can_next: bool, where: str) -> None:
        self.view.setHtml(html_text)
        self._pos.setText(pos)
        self._prev.setEnabled(can_prev)
        self._next.setEnabled(can_next)
        self._where.setText(where)


def _wrap_anywhere(view: QTextBrowser) -> None:
    """長いパスを、途中で切らず、折り返して全部見せる。"""
    option = view.document().defaultTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    view.document().setDefaultTextOption(option)


class GuideWidget(QWidget):
    """Guide タブに埋め込む完成ウィジェット。rag_chatbot.py の _build_guide_tab() から作られる。"""

    def __init__(self, cfg_getter: Callable[[], dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._guide: dict | None = None
        self._index = 0
        self._paths: list[Path | None] = []  # 保存済みのパス。生成直後の仮の手順（未保存）は None
        self._transient: tuple[str, dict] | None = None  # 生成直後の手順（保存すると、保存したものに置き換わる）
        self._popup: GuideStepWindow | None = None
        self._where_text = ""
        self._build_ui()

    # ── 画面 ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """上から「チュートリアル → いまの場所 → 手順の移動 → 手順 → 案内の結果 → 主ボタン → 折りたたみ（前提・設定）」。
        Tutorial タブと同じ文字の大きさ（type_qss）・主ボタン（button_qss）にそろえた（2026-11-18）。"""
        # 置かれた場所が狭い・低いと、部品が重なって読めなくなる。全体をスクロールできる枠に入れて、足りないときは、スクロールで見せる
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(6))

        bar = QHBoxLayout()
        self._combo = QComboBox()
        self._combo.setToolTip("保存したチュートリアル。保存したときに、案内データも一緒に作られます。生成した直後のものは、保存前でも、先頭に出ます")
        self._combo.currentIndexChanged.connect(self._on_pick)
        self._refresh_btn = action_button("refresh", "チュートリアルの一覧を更新", self.refresh)
        bar.addWidget(self._combo, stretch=1)
        bar.addWidget(self._refresh_btn)
        root.addLayout(bar)

        # どの階層にいるか（いまのネットワークと、この手順の作業場所）。常に出す。場所が違うときは、色を変える
        self._where = QLabel("")
        self._where.setWordWrap(True)
        self._where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._set_where_style(True)
        root.addWidget(self._where)

        nav = QHBoxLayout()
        self._prev_btn = QPushButton("◀ 前へ")
        self._next_btn = QPushButton("次へ ▶")
        self._pos = QLabel("")
        self._pos.setAlignment(Qt.AlignCenter)
        self._pos.setStyleSheet(type_qss("heading", "#e2e8f0"))
        self._prev_btn.clicked.connect(lambda: self._go(-1))
        self._next_btn.clicked.connect(lambda: self._go(1))
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._pos, stretch=1)
        nav.addWidget(self._next_btn)
        root.addLayout(nav)

        # 手順（主役。いちばん広く取る）
        self._step_view = QTextBrowser()
        self._step_view.setOpenLinks(False)
        self._step_view.setFont(type_font("body"))
        self._step_view.setMinimumHeight(px(200))  # 説明の欄は、いちばん広く取る（ほかの部品に押しつぶされない）
        _wrap_anywhere(self._step_view)
        self._step_view.setToolTip("語をダブルクリックすると、Reference で探します")
        root.addWidget(self._step_view, stretch=1)
        # お手本の画面（この手順のあと、生成のときに撮ったもの。A25）。折りたためる。画像の無い手順では隠れる
        self._shots = ShotStrip()
        self._shots_box = CollapsibleBox("お手本の画面（この手順のあと。押すと大きく開く）", self._shots, collapsed=False,
                                         state_key="guide_shots", left_align=True)
        self._shots_box.hide()
        root.addWidget(self._shots_box)
        try:
            import reference_view  # 循環を避けるため、ここで読む（reference_view も guide_view を使う）

            # 語をダブルクリックで調べる（A20）。用語の一覧にある語は、ここで意味を出す（タブを切り替えない）。無い語は Reference で探す
            reference_view.TermLookup.install(self._step_view, lambda message: self._set_status([message]), on_term=self._show_term)
        except Exception:  # noqa: BLE001 -- 付けられなくても、案内はできる
            pass

        # 注意（お手本のパスを指している、など）。小さい文字に埋もれないよう、目立つ枠で出す（A26）
        self._warn = QLabel("")
        self._warn.setWordWrap(True)
        self._warn.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._warn.setStyleSheet(f"{type_qss('body', '#fff7ed')}font-weight:bold;background:#7c2d12;border:{px(2)}px solid #f97316;"
                                 f"border-radius:{px(4)}px;padding:{px(6)}px {px(8)}px;")
        self._warn.setVisible(False)
        root.addWidget(self._warn)

        # ダブルクリックした用語の意味（用語の一覧から。2026-11-26）。手順を移ると消える
        self._term = QLabel("")
        self._term.setWordWrap(True)
        self._term.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._term.setStyleSheet(f"{type_qss('body', '#e0f2fe')}background:#0c4a6e;border-radius:{px(4)}px;padding:{px(6)}px {px(8)}px;")
        self._term.setVisible(False)
        root.addWidget(self._term)

        # 案内した結果（Houdini の画面を動かしたあとの、短い報告）
        self._status = QLabel("")
        self._status.setStyleSheet(type_qss("caption", "#94a3b8"))
        self._status.setWordWrap(True)
        self._status_lines: list[str] = []
        root.addWidget(self._status)

        # 主な操作: 「この手順を案内」（主ボタン）と、移るたびの自動案内
        actions = QHBoxLayout()
        self._apply_btn = QPushButton("この手順を案内")
        self._apply_btn.setStyleSheet(button_qss("primary"))
        self._apply_btn.setToolTip("見るタブを前面に出し、操作するノードを選んで画面に収めます。パラメータを変える手順では、その項目の位置へ合わせます")
        self._apply_btn.clicked.connect(lambda _checked=False: self._apply())
        self._auto = QCheckBox("手順を移るたびに自動で案内")
        self._ref_btn = QPushButton("ノードの説明")
        self._ref_btn.setToolTip("この手順のノードの「何をする・使いどころ・実例」を、Reference タブで開きます")
        self._ref_btn.clicked.connect(self._open_reference)
        self._terms_btn = QPushButton("用語の一覧")
        self._terms_btn.setCheckable(True)
        self._terms_btn.setToolTip("ノード・表示フラグ・SOP・属性など、Houdini の画面と考え方の基本の言葉を、まとめて見ます。もう一度押すと、前提条件・TIPS に戻ります")
        self._terms_btn.toggled.connect(self._on_terms_toggled)
        actions.addWidget(self._apply_btn)
        actions.addWidget(self._ref_btn)
        actions.addWidget(self._terms_btn)
        actions.addWidget(self._auto, stretch=1)
        root.addLayout(actions)

        # お手本と自分のネットワークの行き来・作業場所へ戻る・Chat に聞く（2026-11-25。実証実験の A16〜A18）
        # 真似て、お手本と同じ名前で作ると、「自動」は自分の方を示す。お手本を見たいときは「お手本を見る」で、サンドボックスの実物へ
        self._home: dict | None = None
        swap = QHBoxLayout()
        self._example_btn = QPushButton("お手本を見る")
        self._example_btn.setToolTip("この手順のノードを、生成したサンドボックスの実物（お手本）で示します。同じ名前で真似て作っていても、お手本の方へ行きます")
        self._example_btn.clicked.connect(lambda _checked=False: self._apply("sandbox"))
        self._mine_btn = QPushButton("自分のを見る")
        self._mine_btn.setToolTip("この手順のノードを、/obj の自分のネットワークで示します")
        self._mine_btn.clicked.connect(lambda _checked=False: self._apply("own"))
        self._home_btn = QPushButton("作業場所に戻る")
        self._home_btn.setToolTip("Guide が画面を動かす前に、自分のネットワークで開いていた階層と、選んでいたノードへ戻ります")
        self._home_btn.clicked.connect(self._go_home)
        self._ask_btn = QPushButton("この手順を Chat に聞く")
        self._ask_btn.setToolTip("この手順の作業と目的を添えて、Chat に「何をしているか・うまくいかないときに確かめること」を聞きます")
        self._ask_btn.clicked.connect(self._ask_chat)
        for button in (self._example_btn, self._mine_btn, self._home_btn, self._ask_btn):
            swap.addWidget(button)
        swap.addStretch()
        root.addLayout(swap)

        # 前提条件・TIPS（折りたたむ。ショートカット一覧を開くと、ここに出る）
        self._extra_view = QTextBrowser()
        self._extra_view.setOpenLinks(False)
        self._extra_view.setFont(type_font("body"))
        self._extra_view.setMinimumHeight(px(120))
        _wrap_anywhere(self._extra_view)
        self._extra_box = CollapsibleBox("前提条件・TIPS", self._extra_view, collapsed=True, state_key="guide_extra", left_align=True)
        root.addWidget(self._extra_box)

        # 案内の設定（折りたたむ。ふだんは触らないもの）
        self._mode = QComboBox()
        for label, key in (("自動（自分のネットワーク → 無ければ、生成したサンドボックス）", "auto"),
                           ("自分のネットワークだけ", "own"), ("生成したサンドボックス（実物）だけ", "sandbox")):
            self._mode.addItem(label, key)
        saved_mode = str(_state_get(_MODE_KEY, "auto") or "auto")
        self._mode.setCurrentIndex(max(0, self._mode.findData(saved_mode)))
        self._mode.setToolTip("手順が指すノードを、どこから探すか。自動は、まず /obj の自分のネットワーク。無ければ、生成時のサンドボックスの実物を示します")
        self._mode.currentIndexChanged.connect(self._on_mode_changed)

        self._auto_switch = QCheckBox("生成が終わったら、自動でこのタブに切り替える")
        self._auto_switch.setChecked(bool(_state_get(_AUTO_SWITCH_KEY, True)))
        self._auto_switch.toggled.connect(lambda on: _state_set(_AUTO_SWITCH_KEY, bool(on)))

        self._parm_focus = QCheckBox("パラメータ画面を、この手順の項目の位置に合わせる")
        self._parm_focus.setChecked(bool(_state_get(_PARM_FOCUS_KEY, True)))
        self._parm_focus.setToolTip("値を変える手順で、パラメータ画面のタブを切り替え、その項目が中央に来るようスクロールし、キーボードの焦点を当てます")
        self._parm_focus.toggled.connect(lambda on: _state_set(_PARM_FOCUS_KEY, bool(on)))

        self._sc_btn = QPushButton("ショートカットを表示")
        self._sc_btn.setCheckable(True)
        self._sc_btn.setChecked(bool(_state_get(_SHORTCUTS_KEY, False)))
        self._sc_btn.setToolTip("手順ごとのショートカットの一覧を、開く・たたむ。最初の手順は、自動で開きます。選んだ状態は、覚えておきます")
        self._sc_btn.toggled.connect(self._on_shortcuts_toggled)
        self._sheet_btn = QPushButton("ショートカット一覧")
        self._sheet_btn.setCheckable(True)
        self._sheet_btn.setToolTip("Houdini の標準のショートカットを、全部見る（キーや操作で絞れます）。もう一度押すと、手順書の前提・TIPS に戻ります")
        self._sheet_btn.toggled.connect(self._on_sheet_toggled)
        self._popup_btn = QPushButton("手順だけ別ウィンドウ")
        self._popup_btn.setToolTip("手順だけの小さなウィンドウを出します。Chat など、ほかのタブを見ながら手順を読めます")
        self._popup_btn.clicked.connect(self._open_popup)
        self._sheet_filter = QLineEdit()
        self._sheet_filter.setPlaceholderText("キーや操作で絞る（例: Space・パラメータ・タイムライン）")
        self._sheet_filter.setClearButtonEnabled(True)
        self._sheet_filter.setVisible(False)
        self._sheet_filter.textChanged.connect(self._render_sheet)
        self._restore_btn = QPushButton("ほかのオブジェクトの表示を元に戻す")
        self._restore_btn.setToolTip("案内・生成のあいだ、手順が指すもの以外の表示を切っています。切ったものを、元の状態に戻します")
        self._restore_btn.clicked.connect(self._restore_display)

        settings = QWidget()
        form = QVBoxLayout(settings)
        form.setContentsMargins(px(4), 0, 0, 0)
        form.setSpacing(px(4))
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("案内する場所:"))
        mode_row.addWidget(self._mode, stretch=1)
        form.addLayout(mode_row)
        form.addWidget(self._auto_switch)
        form.addWidget(self._parm_focus)
        more = QHBoxLayout()
        more.addWidget(self._sc_btn)
        more.addWidget(self._sheet_btn)
        more.addWidget(self._popup_btn)
        more.addStretch()
        form.addLayout(more)
        form.addWidget(self._sheet_filter)
        form.addWidget(self._restore_btn)
        self._settings_box = CollapsibleBox("案内の設定", settings, collapsed=True, state_key="guide_settings", left_align=True)
        root.addWidget(self._settings_box)

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._update_where)

        self._set_enabled(False)

    def _set_where_style(self, severity) -> None:
        """いまのネットワークと、この手順の場所のずれに合わせた色（A26）。
        同じ: ふつう / 名前だけ違う・分からない: 琥珀の帯 / 深さが違う（本当の階層ミス）: 赤の太い枠と大きな文字。
        以前の呼び方（True = 同じ、False = 違う）も受ける。"""
        if severity is True:
            severity = "same"
        elif severity is False:
            severity = "name"
        if severity == "level":
            style = (f"{type_qss('body', '#fff7ed')}font-weight:bold;background:#7c2d12;border:{px(2)}px solid #f97316;"
                     f"border-radius:{px(4)}px;padding:{px(6)}px {px(8)}px;")
        else:
            same = severity == "same"
            style = (f"{type_qss('caption', '#cbd5e1' if same else '#fde68a')}background:{'#1e293b' if same else '#422006'};"
                     f"border-radius:{px(4)}px;padding:{px(4)}px {px(6)}px;")
        self._where.setStyleSheet(style)

    # ── ショートカット ────────────────────────────────────────────────────────

    def _on_shortcuts_toggled(self, on: bool) -> None:
        _state_set(_SHORTCUTS_KEY, bool(on))
        self._render()

    def _on_sheet_toggled(self, on: bool) -> None:
        if on and self._terms_btn.isChecked():
            self._terms_btn.setChecked(False)  # 一覧は、どちらか 1 つ
        self._show_list("ショートカット一覧" if on else None)

    def _on_terms_toggled(self, on: bool) -> None:
        if on and self._sheet_btn.isChecked():
            self._sheet_btn.setChecked(False)
        self._show_list("用語の一覧" if on else None)

    def _show_list(self, title: str | None) -> None:
        """下の折りたたみに、ショートカット一覧・用語の一覧を出す。title が None なら、前提条件・TIPS に戻す（ほかの一覧が開いていなければ）。"""
        if title is None and (self._sheet_btn.isChecked() or self._terms_btn.isChecked()):
            return
        self._sheet_filter.setVisible(title is not None)
        self._sheet_filter.setPlaceholderText("用語で絞る（例: フラグ・属性・SOP）" if title == "用語の一覧"
                                              else "キーや操作で絞る（例: Space・パラメータ・タイムライン）")
        self._extra_box.set_title(title or "前提条件・TIPS")
        if title is not None:
            self._extra_box.set_collapsed(False)  # 一覧を、すぐ見られるように開く
            self._render_sheet()
        else:
            self._sheet_filter.clear()
            self._extra_view.setHtml(render_sections_html(self._guide) if self._guide else "")

    def _render_sheet(self) -> None:
        if self._sheet_btn.isChecked():
            self._extra_view.setHtml(render_cheatsheet_html(self._sheet_filter.text()))
        elif self._terms_btn.isChecked():
            self._extra_view.setHtml(houdini_terms.html_list(self._sheet_filter.text()))

    def _show_term(self, entry: dict) -> None:
        """ダブルクリックした語の意味を出す（用語の一覧にある語だけ）。"""
        self._term.setText(houdini_terms.one_line(entry) + "（ほかの言葉は「用語の一覧」）")
        self._term.setVisible(True)

    def _set_enabled(self, has_guide: bool) -> None:
        self._prev_btn.setEnabled(has_guide)
        self._next_btn.setEnabled(has_guide)
        self._apply_btn.setEnabled(has_guide and hou is not None)
        self._auto.setEnabled(has_guide and hou is not None)
        for button in (self._example_btn, self._mine_btn, self._home_btn):
            button.setEnabled(has_guide and hou is not None)
        self._ask_btn.setEnabled(has_guide)
        self._restore_btn.setEnabled(hou is not None and display_isolation.pending() > 0)

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt
        super().showEvent(event)
        if not self._paths:
            self.refresh()
        self._set_tab_mark(False)
        if hou is not None:
            self._timer.start()
        self._update_where()

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt
        super().hideEvent(event)
        self._timer.stop()

    # ── 読み込み ─────────────────────────────────────────────────────────────

    def _tutorials_dir(self) -> Path | None:
        bridge_dir = (self._cfg_getter() or {}).get("local_bridge_dir", "")
        return Path(bridge_dir) / "localRAG" / "tutorials" if bridge_dir else None

    def _fill_combo(self, found: list[tuple[str, Path]], select: int = 0) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        self._paths = []
        if self._transient is not None:
            self._combo.addItem("（生成直後・未保存）" + self._transient[0])
            self._paths.append(None)
        for name, path in found:
            self._combo.addItem(name)
            self._paths.append(path)
        # 組み込みの「基本操作の練習」（AI を使わない。いつも最後に出す。basics_guide.py）
        self._combo.addItem(basics_guide.LABEL)
        self._paths.append(basics_guide.KEY)
        self._combo.blockSignals(False)
        self._combo.setCurrentIndex(select if 0 <= select < len(self._paths) else 0)

    def refresh(self) -> None:
        directory = self._tutorials_dir()
        found = guide_mode.list_guides(directory)
        if self._transient is not None and any(name == self._transient[0] for name, _p in found):
            self._transient = None  # 同じ手順が保存されたので、保存したものに置き換える
        self._fill_combo(found)
        if not found and self._transient is None:
            # 保存したチュートリアルがまだ無い（はじめての人）: 基本操作の練習を開く
            self._load(len(self._paths) - 1)
            self._status.setText(("保存したチュートリアルは、まだありません。まず、基本操作の練習から始められます" if directory is not None
                                  else panel_paths.SAVE_DIR_MISSING))
            return
        if not self._paths:
            self._guide = None
            self._step_view.setHtml("")
            self._extra_view.setHtml("")
            self._pos.setText("")
            self._set_enabled(False)
            self._status.setText(
                "案内できるチュートリアルがありません。Tutorial タブで生成して保存すると、ここに出ます"
                if directory is not None else panel_paths.SAVE_DIR_MISSING
            )
            return
        self._load(0)

    def _on_pick(self, index: int) -> None:
        if 0 <= index < len(self._paths):
            self._load(index)

    def _load(self, index: int) -> None:
        path = self._paths[index]
        if path == basics_guide.KEY:
            guide = basics_guide.build()
        elif path is None and self._transient is not None:
            guide = self._transient[1]
        else:
            guide = guide_mode.load_guide(path) if path is not None else None
        if guide is None:
            self._guide = None
            self._set_enabled(False)
            self._status.setText("案内データを読み込めませんでした")
            return
        self._guide, self._index = guide, 0
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(index)
        self._combo.blockSignals(False)
        if self._sheet_btn.isChecked() or self._terms_btn.isChecked():
            self._render_sheet()
        else:
            self._extra_view.setHtml(render_sections_html(guide))
        self._set_enabled(True)
        if path == basics_guide.KEY:
            note = "基本操作の練習です。/obj に practice_geo を作って、手を動かしながら覚えます。「この手順を案内」で、見る場所を示します"
        elif path is None:
            note = "生成した直後の手順です（まだ保存していません）。保存は Tutorial タブの「保存」から"
        else:
            note = "手順を1つずつ示します。「この手順を案内」で、Houdini の画面を動かします" if hou is not None else "Houdini の外なので、手順の表示だけできます"
        self._status.setText(note)
        self._render()

    # ── 生成が終わったときの通知（tutorial_view から） ─────────────────────────────

    def load_generated(self, guide: dict, label: str) -> None:
        """生成した直後の手順（保存前）を、先頭に読み込む。"""
        self._transient = (label, guide)
        found = guide_mode.list_guides(self._tutorials_dir())
        self._fill_combo(found)
        self._load(0)

    def select_saved(self, path: Path) -> None:
        """保存した案内データを選ぶ（一覧を更新する）。生成直後の手順を、保存したものに置き換えたときは、見ていた手順の位置を保つ。"""
        found = guide_mode.list_guides(self._tutorials_dir())
        data = guide_mode.load_guide(path)
        replaced_transient = False
        if data is not None and self._transient is not None and guide_mode.guide_label(data, path) == self._transient[0]:
            self._transient = None
            replaced_transient = True
        keep_index = self._index if replaced_transient and self._guide is not None else 0
        self._fill_combo(found)
        for i, p in enumerate(self._paths):
            if p is not None and Path(p) == Path(path):
                self._load(i)
                self._restore_index(keep_index)
                return
        if self._paths:
            self._load(0)

    def open_basics(self) -> str:
        """基本操作の練習を開く（課題タブの「基本操作の練習を開く」から）。Guide タブへ切り替える。画面に出す 1 文を返す。"""
        if not self._paths:
            self.refresh()
        if basics_guide.KEY in self._paths:
            index = self._paths.index(basics_guide.KEY)
            if self._guide is None or self._guide.get("builtin") != basics_guide.KEY:
                self._load(index)
        host = locate_in_tabs(self)
        if host is not None:
            host[0].setCurrentIndex(host[1])
        return "Guide タブで、基本操作の練習を開きました"

    def _restore_index(self, index: int) -> None:
        """読み込み直したあとで、見ていた手順の位置へ戻す（手順の数が変わっていれば、範囲に収める）。"""
        if self._guide is None or not index:
            return
        self._index = max(0, min(index, len(self._guide["steps"]) - 1))
        self._render()

    def auto_switch_enabled(self) -> bool:
        return self._auto_switch.isChecked()

    def announce(self, switch: bool | None = None, saved: bool = False, from_index: int | None = None) -> str:
        """Guide タブへ切り替える（設定がオンのとき）。切り替えないときは、タブの名前に印を付ける。画面に出す1文を返す。
        自動（switch を渡さない）のとき、利用者が、生成したタブ（from_index）ではなく別のタブにいるなら、切り替えない
        （Chat で入力している途中などを、壊さないため）。印だけ付ける。"""
        host = locate_in_tabs(self)
        do_switch = self.auto_switch_enabled() if switch is None else switch
        if host is None:
            return ""
        tabs, index = host
        elsewhere = switch is None and from_index is not None and tabs.currentIndex() not in (from_index, index)
        if do_switch and elsewhere:
            self._set_tab_mark(True)
            return "Guide タブに最新の手順を読み込みました（別のタブを開いていたので、切り替えていません。タブの「" + _TAB_NEW_TEXT + "」が目印です）"
        if do_switch:
            tabs.setCurrentIndex(index)
            self._set_tab_mark(False)
            return "Guide タブに切り替えて、最新の手順を読み込みました" if not saved else "Guide タブの手順を、保存したものに更新しました"
        self._set_tab_mark(True)
        return f"Guide タブに最新の手順を読み込みました（タブの「{_TAB_NEW_TEXT}」が目印です）" if not saved else "Guide タブの手順を、保存したものに更新しました"

    def _set_tab_mark(self, new: bool) -> None:
        host = locate_in_tabs(self)
        if host is None:
            return
        tabs, index = host
        text = _TAB_NEW_TEXT if new else _TAB_BASE_TEXT
        if tabs.tabText(index) in (_TAB_BASE_TEXT, _TAB_NEW_TEXT):
            tabs.setTabText(index, text)
            tabs.setTabToolTip(index, "新しい手順が読み込まれました" if new else "")

    # ── 手順の移動と案内 ─────────────────────────────────────────────────────

    def _sandbox_path(self) -> str:
        return str((self._guide or {}).get("sandbox_path") or "")

    def _mode_key(self) -> str:
        return str(self._mode.currentData() or "auto")

    def _on_mode_changed(self, _i: int) -> None:
        _state_set(_MODE_KEY, self._mode_key())
        self._render()

    def step_brief(self) -> dict | None:
        """Chat の「質問の例」に使う、いま見ている手順の要点（question_hints.suggest の guide_step）。案内が無ければ None。"""
        steps = (self._guide or {}).get("steps") or []
        if not steps:
            return None
        step = steps[max(0, min(self._index, len(steps) - 1))]
        return {"index": self._index, "total": len(steps), "title": str(self._guide.get("title") or ""),
                "instruction": str(step.get("instruction") or ""), "node": str(step.get("node") or ""),
                "node_label": str(step.get("node_label") or ""), "purpose": str(step.get("purpose") or "")}

    def _current_step(self) -> dict:
        step = self._guide["steps"][self._index]
        try:
            return guide_mode.attach_parm_info(hou, step, self._sandbox_path(), self._mode_key())
        except Exception:  # noqa: BLE001 -- 値の言い換えができなくても、数字のまま出す
            return step

    def _render(self) -> None:
        if self._guide is None:
            return
        steps = self._guide["steps"]
        self._pos.setText(f"手順 {self._index + 1} / {len(steps)}")
        self._term.setVisible(False)
        if self._guide.get("builtin") == basics_guide.KEY:
            report_basics_progress(self._cfg_getter() or {}, self._index + 1, len(steps))
        page = render_step_html(self._guide, self._index, self._current_step(), shortcuts_visible(self._index, self._sc_btn.isChecked()))
        self._step_view.setHtml(page)
        self._shots_box.setVisible(self._shots.show_shots(guide_mode.step_shots(self._guide, steps[self._index])) > 0)
        self._prev_btn.setEnabled(self._index > 0)
        self._next_btn.setEnabled(self._index < len(steps) - 1)
        self._update_where()
        if self._popup is not None and self._popup.isVisible():
            self._popup.update_step(page, self._pos.text(), self._index > 0, self._index < len(steps) - 1, self._where_text)

    def _update_where(self) -> None:
        """どの階層にいるか。いまのネットワークと、この手順の作業場所を並べて出す（Houdini の外では、手順の場所だけ）。"""
        expected = ""
        if self._guide is not None:
            expected = guide_mode.step_places(self._guide["steps"][self._index], self._sandbox_path())["network"]
        text = ""
        severity = "same"
        if hou is not None:
            try:
                current = guide_mode.current_network_path(hou)
                text, _same = guide_mode.location_status(current, expected)
                severity = guide_mode.location_severity(current, expected)
                if severity == "level":
                    text = f"⚠ 階層が違います\n{text}\n{guide_mode.level_hint(current, expected)}"
                elif severity == "name":
                    text += "\n（名前の違う、自分の作業場所なら、そのままで構いません）"
            except Exception:  # noqa: BLE001 -- 階層が読めなくても、手順の表示は止めない
                text, severity = "", "same"
            self._restore_btn.setEnabled(display_isolation.pending() > 0)
        if not text:
            text = f"この手順の作業場所: {expected}" if expected else "Houdini の外なので、いまの階層は分かりません"
        self._where_text = text
        self._where.setText(text)
        self._set_where_style(severity)
        if self._popup is not None and self._popup.isVisible():
            self._popup._where.setText(text)

    def _go(self, delta: int) -> None:
        if self._guide is None:
            return
        self._index = max(0, min(self._index + delta, len(self._guide["steps"]) - 1))
        self._render()
        if self._auto.isChecked():
            self._apply()

    def _apply(self, mode: str | None = None) -> None:
        """この手順を案内する。mode: "sandbox"（お手本）/ "own"（自分）を、この 1 回だけ使う。None なら、設定の「案内する場所」。"""
        if self._guide is None or hou is None:
            return
        mode = mode or self._mode_key()
        try:
            place = guide_mode.remember_place(hou)  # 自分の作業場所にいれば、動かす前の場所を覚える（「作業場所に戻る」用）
            if place is not None:
                self._home = place
        except Exception:  # noqa: BLE001 -- 覚えられなくても、案内はする
            pass
        step = self._guide["steps"][self._index]
        try:
            messages = guide_mode.apply_step(hou, step, self._sandbox_path(), mode)
        except Exception as exc:  # noqa: BLE001 -- 案内に失敗しても、パネルは止めない
            messages = [f"案内に失敗しました（{exc}）"]
        if mode != "sandbox":
            try:
                messages = guide_mode.sandbox_references(hou) + list(messages)  # 自分のネットワークが、お手本を指していたら、先に知らせる（A26）
            except Exception:  # noqa: BLE001
                pass
        self._set_status(messages)
        self._update_where()
        if step.get("tool") == "set_parameter" and self._parm_focus.isChecked():
            # パラメータ画面がノードに追従するのを待ってから、項目の位置に合わせる（すぐだと、前のノードのままのことがある）
            index = self._index
            QTimer.singleShot(250, lambda: self._highlight_parms(index, step, mode))

    def _go_home(self) -> None:
        """Guide が画面を動かす前の、自分の作業場所へ戻る（A17）。"""
        if hou is None:
            return
        try:
            message = guide_mode.return_to_place(hou, self._home)
        except Exception as exc:  # noqa: BLE001
            message = f"作業場所に戻れませんでした（{exc}）"
        self._set_status([message])
        self._update_where()

    def _ask_chat(self) -> None:
        """この手順のことを、Chat に聞く（A18。同じパネルの Chat タブで送る）。"""
        brief = self.step_brief()
        if brief is None:
            return
        try:
            import question_hints

            query = question_hints.guide_step_question(brief, stuck=True)
        except Exception as exc:  # noqa: BLE001
            self._set_status([f"質問を作れませんでした（{exc}）"])
            return
        try:
            import panel_bus

            panel = panel_bus.panel_of(self)
        except Exception:  # noqa: BLE001
            panel = None
        if panel is None or not hasattr(panel, "ask_chat"):
            self._set_status(["Chat タブが見つかりません"])
            return
        self._set_status([panel.ask_chat(query)])

    def _highlight_parms(self, index: int, step: dict, mode: str | None = None) -> None:
        """パラメータ画面を、この手順の項目の位置に合わせる。待っているあいだに手順が変わっていたら、何もしない。"""
        if hou is None or self._guide is None or index != self._index:
            return
        try:
            import screen_capture

            hit = guide_mode.resolve_step_target(hou, step, self._sandbox_path(), mode or self._mode_key())
            messages = guide_mode.highlight_parms(hou, step, hit.node, screen_capture.reveal_parm_tabs)
        except Exception:  # noqa: BLE001 -- 合わせられなくても、案内は済んでいる
            messages = []
        if messages:
            self._set_status(self._status_lines + messages)

    def _set_status(self, messages: list[str]) -> None:
        """案内の結果を、短く出す（compact_messages）。全文は、ツールチップに残す。手順の説明の欄を、押しつぶさないため、
        出すのは最大 _STATUS_MAX_LINES 行まで。"""
        warnings = [m for m in messages if str(m).startswith(("注意", "⚠"))]
        self._warn.setText("\n".join(f"⚠ {str(m).lstrip('⚠ ')}" for m in warnings))
        self._warn.setVisible(bool(warnings))
        messages = [m for m in messages if m not in warnings]
        lines = compact_messages(messages)
        self._status_lines = lines
        shown = lines[:_STATUS_MAX_LINES]
        if len(lines) > _STATUS_MAX_LINES:
            shown.append(f"…ほか {len(lines) - _STATUS_MAX_LINES} 行（マウスを載せると全部出ます）")
        self._status.setText("\n".join(shown))
        self._status.setToolTip("\n".join(lines))

    def goto_step(self, index: int) -> bool:
        """指定の手順（0 始まり）を開く（Reference タブの「使っている場所」から）。自動で案内する設定のときは、Houdini の画面も動かす。範囲外は False。"""
        if self._guide is None or not (0 <= index < len(self._guide["steps"])):
            return False
        self._index = index
        self._render()
        if self._auto.isChecked():
            self._apply()
        return True

    def _open_reference(self) -> None:
        """この手順のノードを、Reference タブで開く（reference_view.open_item_for_step）。"""
        if self._guide is None:
            return
        try:
            import reference_view

            message = reference_view.open_item_for_step(self, self._guide["steps"][self._index])
        except ImportError:
            message = "Reference タブが見つかりません"
        self._set_status([message])

    def _restore_display(self) -> None:
        """案内・生成のあいだに切った、ほかのオブジェクトの表示を、元に戻す。"""
        if hou is None:
            return
        self._set_status([guide_mode.restore_display(hou)])
        self._restore_btn.setEnabled(display_isolation.pending() > 0)

    def _open_popup(self) -> None:
        if self._popup is None:
            self._popup = GuideStepWindow(self)
        self._popup.show()
        self._popup.raise_()
        self._render()
