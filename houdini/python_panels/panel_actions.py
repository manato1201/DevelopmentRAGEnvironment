"""
panel_actions.py — パネルで共通に使う「アイコン 1 つ = 操作 1 つ」の部品（PySide6）

  ui_scale()          … 画面の拡大率（96dpi を 1.0）。4K・拡大表示でも、文字と部品の大きさを揃えるために使う。
  px(n)               … 96dpi での n ピクセルを、いまの拡大率に直した整数。
  pt_qss(qss)         … スタイルシートの font-size:Npx を、font-size:Mpt に直す（pt は OS の拡大に追従する）。
  normalize_fonts(w)  … ウィジェット以下のスタイルシートの px フォントを pt に揃える（パネルを作ったあとに 1 回呼ぶ）。
  type_qss(role)      … 文字の大きさの 4 段階（heading / body / caption / code）を、pt のスタイルシートにする。
  type_font(role)     … 同じ 4 段階の QFont（パネルの本文のフォントを決めるのに使う）。
  button_qss(kind)    … ボタンの役割（primary = 主 / secondary = 副 / danger = 危険）ごとのスタイルシート。
  make_icon(name)     … 線画アイコン（QIcon）。Web のチャット画面と同じ 1 セット。
  action_button(...)  … アイコンだけのボタン（QToolButton）。名前はツールチップと読み上げ用の名前に出す。
  Speaker             … 読み上げ（QtTextToSpeech）。無い環境では available=False で、ボタンを出さない。

実機の Houdini は Qt の高解像度対応を使わないことがあり、px 指定は画面の大きさに追従せず、pt 指定は追従する。
その混在が「解像度で文字や画面の縮尺が変わる」原因なので、フォントは pt に、部品の寸法は px(n) に揃える。
"""

from __future__ import annotations

import re
import time

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QToolButton, QWidget

try:  # Houdini 同梱の PySide に QtSvg が無い場合は、文字のアイコンで代用する
    from PySide6.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover - 環境依存
    QSvgRenderer = None  # type: ignore[assignment]

# Web のチャット画面(chatUi.ts の ICON_PATHS)と同じ、16x16 の線画。
ICON_PATHS: dict[str, str] = {
    "copy": "M5.5 5.5h7v8h-7zM3.5 10.5v-8h7",
    "thumbUp": "M2.5 7.5h2.5v6H2.5zM5 7.5l2.5-5c1.2 0 1.8.8 1.5 2L8.6 6.5h3.9a1 1 0 011 1.2l-.9 4.8a1 1 0 01-1 .8H5",
    "thumbDown": "M2.5 8.5h2.5v-6H2.5zM5 8.5l2.5 5c1.2 0 1.8-.8 1.5-2l-.4-2h3.9a1 1 0 001-1.2l-.9-4.8a1 1 0 00-1-.8H5",
    "share": "M4.5 9.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM11.5 5a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM11.5 14a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM6 8.2l4-2.4M6 7.8l4 2.4",
    "speaker": "M2.5 6.5h2.5L8.5 3.5v9L5 9.5H2.5zM10.8 5.8a3 3 0 010 4.4M12.5 4a5.5 5.5 0 010 8",
    "refresh": "M13 8a5 5 0 10-1.6 3.7M13 3v3.5h-3.5",
    "bookmark": "M4 2.5h8v11L8 10.5l-4 3z",
    "docSearch": "M3.5 2h5l2.5 2.5V7M3.5 2v11h4M9.5 12a2 2 0 100-4 2 2 0 000 4zM11 11.5l2 2",
    # 全体を表示(四隅の枠)。Houdini パネルのノードグラフ用。Web 側では使っていない。
    "fit": "M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4",
    # 歯車(パネルの右上のメニュー。ふだん使わない画面と、別ウィンドウで開く操作をまとめる)
    "gear": "M8 5.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4",
    # メニュー（横線 3 本）。パネルの右上のメニュー。Houdini のペイン自身の歯車（設定）と紛らわしかったので、歯車をやめて、これにした（2026-11-18）
    "menu": "M2.5 4h11M2.5 8h11M2.5 12h11",
    # 本 + 虫めがね。Chat の「関連情報を確認中…」（panel_thinking.py）
    "bookSearch": "M2 3.5c1.5-.7 3.4-.7 4.8.2v8.4c-1.4-.9-3.3-.9-4.8-.2zM6.8 3.7c1.3-.8 3-.9 4.2-.4M10.5 12.2a2.3 2.3 0 100-4.6 2.3 2.3 0 000 4.6zM12.2 11.9l2 2",
    # 本（開いた本）。「はじめに」タブのアイコン
    "book": "M8 3.5C6.7 2.7 4.6 2.5 2.5 2.7v9.8c2.1-.2 4.2 0 5.5.8 1.3-.8 3.4-1 5.5-.8V2.7c-2.1-.2-4.2 0-5.5.8zM8 3.5v9.8",
    "back": "M9.5 3.5L5 8l4.5 4.5M5 8h8",
}
# SVG が使えないときの代用文字（絵文字は使わない）
_FALLBACK_TEXT = {
    "copy": "⧉", "thumbUp": "+", "thumbDown": "−", "share": "⇪", "speaker": "♪",
    "refresh": "↻", "bookmark": "★", "docSearch": "≡", "fit": "⛶", "gear": "…", "back": "←", "menu": "≡", "book": "?", "bookSearch": "…",
}

COLOR_NORMAL = "#cbd5e1"
COLOR_ACTIVE = {"thumbUp": "#4ade80", "thumbDown": "#f87171", "bookmark": "#fbbf24", "speaker": "#5eead4"}

_PX_FONT = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)px")


def ui_scale() -> float:
    """画面の拡大率。96dpi を 1.0 とする(4K・150% 表示なら 1.5〜2.0)。取れないときは 1.0。"""
    try:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 1.0
        return min(3.0, max(1.0, screen.logicalDotsPerInch() / 96.0))
    except Exception:
        return 1.0


def px(n: float) -> int:
    """96dpi での n ピクセルを、いまの拡大率に直した整数。"""
    return max(1, int(round(n * ui_scale())))


TEXT_SCALES: tuple[tuple[float, str], ...] = ((1.0, "標準"), (1.15, "やや大きい"), (1.3, "大きい"), (1.5, "とても大きい"))
TEXT_SCALE_KEY = "text_scale"


_TEXT_SCALE_CACHE: dict[str, float] = {}
_TEXT_SCALE_TTL = 5.0  # 秒。文字の大きさを決めるたびに設定ファイルを読まないように、少しのあいだ覚えておく


def text_scale() -> float:
    """利用者が選んだ文字の倍率（メニュー ≡ →「文字の大きさ」。2026-11-25、実証実験の A24「文字が小さい」）。既定は 1.0。
    パネルを作るときに読む（変えたら、パネルを開き直すと反映）。読んだ値は _TEXT_SCALE_TTL 秒だけ覚える。"""
    now = time.monotonic()
    if now - _TEXT_SCALE_CACHE.get("at", -1e9) < _TEXT_SCALE_TTL:
        return _TEXT_SCALE_CACHE["value"]
    try:
        from panel_widgets import ui_state_get

        value = min(2.0, max(0.8, float(ui_state_get(TEXT_SCALE_KEY, 1.0) or 1.0)))
    except Exception:  # noqa: BLE001 -- 読めなければ標準
        value = 1.0
    _TEXT_SCALE_CACHE.update(value=value, at=now)
    return value


def set_text_scale(value: float) -> None:
    """文字の倍率を保存する（次にパネルを作るときから使う）。"""
    from panel_widgets import ui_state_set

    ui_state_set(TEXT_SCALE_KEY, float(value))
    _TEXT_SCALE_CACHE.clear()


def pt_qss(qss: str) -> str:
    """font-size:Npx を font-size:Mpt に直す(96dpi では 1px = 0.75pt)。pt は OS の拡大に追従する。文字の倍率（text_scale）も掛ける。"""
    scale = text_scale()
    return _PX_FONT.sub(lambda m: "font-size:%.1fpt" % (float(m.group(1)) * 0.75 * scale), qss)


def normalize_fonts(root: QWidget) -> int:
    """root 以下のスタイルシートの px フォントを pt に揃える。直したウィジェットの数を返す。"""
    changed = 0
    for widget in [root, *root.findChildren(QWidget)]:
        qss = widget.styleSheet()
        if qss and _PX_FONT.search(qss):
            widget.setStyleSheet(pt_qss(qss))
            changed += 1
    return changed


# ─── 文字の大きさ（タイプスケール）─────────────────────────────────────────────────
# チュートリアル生成の画面は、文字の大きさをこの 4 段階だけにする（個別に font-size を書かない）。
# 単位は pt。pt は OS の拡大に追従するので、4K・拡大表示でも 4 段階の比率が崩れない。
TYPE_SCALE: dict[str, float] = {"heading": 11.0, "body": 10.0, "caption": 9.0, "code": 9.0}
_TYPE_EXTRA: dict[str, str] = {
    "heading": "font-weight:bold;",
    "code": "font-family:Consolas,'Cascadia Mono',monospace;",
}
COLOR_TEXT = "#e2e8f0"      # 見出し・状態の読み出し
COLOR_MUTED = "#94a3b8"     # 補足
COLOR_ACCENT = "#7dd3fc"    # 選んだもの・進行中の案内


def type_qss(role: str, color: str = "") -> str:
    """役割（heading / body / caption / code）の文字の大きさを、スタイルシートの断片にする。color を渡せば文字色も付ける。"""
    if role not in TYPE_SCALE:
        raise KeyError(f"unknown type role: {role}")
    qss = f"font-size:{TYPE_SCALE[role] * text_scale():.1f}pt;{_TYPE_EXTRA.get(role, '')}"
    return qss + (f"color:{color};" if color else "")


def type_font(role: str) -> QFont:
    """役割の QFont（point サイズ指定）。"""
    if role not in TYPE_SCALE:
        raise KeyError(f"unknown type role: {role}")
    font = QFont()
    font.setPointSizeF(TYPE_SCALE[role] * text_scale())
    if role == "heading":
        font.setBold(True)
    if role == "code":
        font.setFamilies(["Consolas", "Cascadia Mono", "monospace"])
    return font


def button_qss(kind: str = "secondary") -> str:
    """ボタンの役割ごとの見た目。primary = 主（生成・保存）、secondary = 副（OS 標準の見た目のまま）、danger = 危険（破棄・削除）。
    余白・角丸は px(n) なので、拡大率に追従する（文字の pt と比率が変わらない）。"""
    pad = f"padding:{px(5)}px {px(14)}px;border-radius:{px(4)}px;min-height:{px(18)}px;"
    if kind == "primary":
        return (
            f"QPushButton{{background:#2563eb;color:#fff;border:none;font-weight:bold;{pad}}}"
            "QPushButton:hover{background:#3b82f6;}"
            "QPushButton:pressed{background:#1d4ed8;}"
            "QPushButton:disabled{background:#1e293b;color:#64748b;}"
        )
    if kind == "danger":
        return (
            f"QPushButton{{background:transparent;color:#fca5a5;border:1px solid #7f1d1d;{pad}}}"
            "QPushButton:hover{background:#450a0a;border-color:#b91c1c;}"
            "QPushButton:disabled{color:#64748b;border-color:#334155;}"
        )
    return ""


def make_icon(name: str, color: str = COLOR_NORMAL, size: int = 16) -> QIcon:
    """線画アイコン。size は 96dpi での大きさで、いまの拡大率で描く(高解像度でもぼやけない)。"""
    path = ICON_PATHS.get(name)
    if path is None or QSvgRenderer is None:
        return QIcon()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="%s" '
        'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="%s"/></svg>' % (color, path)
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    side = px(size)
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def set_active(btn: QToolButton, on: bool) -> None:
    """押した状態を、アイコンの色で示す(名前はツールチップに残るので、色だけには頼らない)。"""
    name = btn.property("actionIcon") or "copy"
    icon = make_icon(name, COLOR_ACTIVE.get(name, COLOR_NORMAL) if on else COLOR_NORMAL)
    if not icon.isNull():
        btn.setIcon(icon)


def action_button(name: str, tooltip: str, on_click=None, checkable: bool = False, parent: QWidget | None = None) -> QToolButton:
    """アイコンだけのボタン。名前はツールチップとアクセシブル名に出す。checkable のときは、押した状態を色で示す。"""
    btn = QToolButton(parent)
    btn.setAutoRaise(True)
    btn.setCheckable(checkable)
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setProperty("actionIcon", name)
    btn.setFixedSize(px(28), px(28))
    btn.setIconSize(QSize(px(16), px(16)))
    icon = make_icon(name)
    if icon.isNull():
        btn.setText(_FALLBACK_TEXT.get(name, "?"))
    else:
        btn.setIcon(icon)
    if checkable:
        btn.toggled.connect(lambda on, b=btn: set_active(b, on))
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def speech_available() -> bool:
    """読み上げ(QtTextToSpeech)が使えるか。使えない環境では、読み上げボタンを出さない。"""
    try:
        from PySide6 import QtTextToSpeech  # noqa: F401
        return True
    except Exception:
        return False


class Speaker:
    """読み上げ。もう一度 toggle すると止まる。QtTextToSpeech が無ければ、何もしない(available=False)。"""

    def __init__(self) -> None:
        self.available = speech_available()
        self._engine = None

    def toggle(self, text: str) -> bool:
        """読み上げを始めたら True、止めたら False を返す。"""
        if not self.available:
            return False
        from PySide6.QtTextToSpeech import QTextToSpeech

        if self._engine is None:
            self._engine = QTextToSpeech()
        if self._engine.state() == QTextToSpeech.State.Speaking:
            self._engine.stop()
            return False
        self._engine.say(re.sub(r"\[\d+\]", "", text))
        return True
