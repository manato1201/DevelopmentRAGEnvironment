"""
reference_view.py — Reference タブ: ノード・VEX・APEX・シェルフツールの「何をする・使いどころ・実例」（2026-11-19）

  ・上段: 種類（ノード / VEX / APEX / シェルフ）、検索、「このチュートリアルで使ったものだけ」
  ・中段: 一覧。チュートリアル（Guide に読み込んだもの）で使ったものには「●」が付き、先頭に並ぶ
  ・下段: 詳細（何をする・どんなもの / どういったものに使うか / 実例 / 実例のポイント / 使いどころ / HoudiniReference の関連）
  ・「説明を作る」: SideFX 公式のドキュメント（RAG）と HoudiniReference の抜粋を材料に、AI が日本語でまとめる。保存され、次からは、すぐ出る
  ・Guide の「ノードの説明」から、その手順のノードの項目が開く（open_item_for_step）

データと文章は reference_data.py（Qt なし）。通信（ドキュメントの取得・HoudiniReference・AI）は、別スレッド（_EntryWorker）。
適用前後の動画（5〜6 秒）・ノード画面は、まだ無い（詳細の下に「今後追加します」と出す）。
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Callable

import reference_data as rd
from panel_actions import button_qss, px, type_font, type_qss
from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

_REFERENCE_CACHE_NAME = "_houdinireference_items.json"
_REFERENCE_MAX_AGE_SECONDS = 24 * 3600
_USED_MARK = "● "
_MAX_LIST = 200


def fetch_reference_items(base_dir: str, now: float | None = None, opener: Callable | None = None) -> list[dict]:
    """HoudiniReference の項目（Tips・動画・ニュース）。1 日は、保存したものを使う。取れなければ、古い保存か、空。例外は投げない。
    出典・利用条件は、それぞれの元のページにある（HoudiniReference の README）。ここでは、題名・出典・日付・短い抜粋・URL だけを使う。"""
    path = Path(base_dir) / "localRAG" / "reference" / _REFERENCE_CACHE_NAME if base_dir else None
    now = time.time() if now is None else now
    cached: list[dict] = []
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached = [i for i in (data.get("items") or []) if isinstance(i, dict)]
            if cached and now - float(data.get("fetched_at", 0)) < _REFERENCE_MAX_AGE_SECONDS:
                return cached
        except (OSError, ValueError, AttributeError, TypeError):
            cached = []
    try:
        open_url = opener or (lambda url: urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "RAGReelTutorial/1.0"}), timeout=15))
        with open_url(rd.HOUDINI_REFERENCE_URL) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = [i for i in (payload.get("items") or []) if isinstance(i, dict)]
    except Exception:  # noqa: BLE001 -- 通信できなくても、説明は作れる（参考が、空になるだけ）
        return cached
    if path is not None and items:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"fetched_at": now, "items": items}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return items


class _EntryWorker(QThread):
    """1 項目の説明を作る（公式ドキュメントの取得 → HoudiniReference → AI）。別スレッド。"""

    done = Signal(object, object)   # (項目の内容 dict, 関連の項目 list)
    failed = Signal(str)

    def __init__(self, cfg: dict, complete: Callable | None, item: dict, parent=None) -> None:
        super().__init__(parent)
        self._cfg, self._complete, self._item = dict(cfg), complete, dict(item)

    def run(self) -> None:
        try:
            if self._complete is None:
                self.failed.emit("AI に接続できません（接続・アカウントで、URL と API キーを確かめてください）")
                return
            base_dir = str(self._cfg.get("local_bridge_dir") or "")
            label = self._item.get("label") or self._item.get("name") or ""
            references = rd.match_reference_items(fetch_reference_items(base_dir), label, self._item.get("kind", ""))
            docs = self._fetch_docs(label)
            system, user = rd.build_prompt(self._item.get("kind", ""), label, docs, references)
            text, _usage = self._complete(system, user)
            entry = rd.parse_entry(text)
            if entry is None:
                self.failed.emit("AI の返事を読み取れませんでした。もう一度、「説明を作る」を押してください")
                return
            if base_dir:
                rd.save_entry(base_dir, self._item["kind"], self._item["key"], entry,
                              {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "docs_found": len(docs), "references": len(references)})
            self.done.emit(entry, references)
        except Exception as exc:  # noqa: BLE001 -- 画面に理由を出す。パネルは止めない
            self.failed.emit(f"説明を作れませんでした（{str(exc)[:120]}）")

    def _fetch_docs(self, label: str) -> list[str]:
        """公式ドキュメント（RAG の Houdini のナレッジ）から、この項目の資料を取る。取れなければ、空（AI は、資料なしと分かった上で書く）。"""
        try:
            from rag_client import RAGClient
            from tutorial_agent import resolve_rag_name

            client = RAGClient(self._cfg)
            namespace = f"shared:{resolve_rag_name(str(self._cfg.get('tutorial_rag_namespace') or ''))}"
            result = client.docs_search(namespace, f"{label} {rd.KIND_LABELS.get(self._item.get('kind', ''), '')}", limit=4)
            return [str(t) for t in (result.get("texts") or []) if str(t).strip()]
        except Exception:  # noqa: BLE001
            return []


class ReferenceWidget(QWidget):
    """Reference タブ。rag_chatbot.py の _build_reference_tab() から作られる。"""

    def __init__(self, cfg_getter: Callable[[], dict], complete_getter: Callable[[], Callable | None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._complete_getter = complete_getter or (lambda: None)
        self._kind = "node"
        self._items: list[dict] = []
        self._used: dict[str, set[str]] = {k: set() for k, _ in rd.KINDS}
        self._current: dict | None = None
        self._references: list[dict] = []
        self._reference_items: list[dict] | None = None
        self._worker: _EntryWorker | None = None
        self._build_ui()
        self._reload()

    # ── 画面 ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(px(6))

        kinds = QHBoxLayout()
        kinds.setSpacing(px(4))
        self._kind_group = QButtonGroup(self)
        self._kind_buttons: dict[str, QPushButton] = {}
        for key, label in rd.KINDS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._kind)
            btn.clicked.connect(lambda _c=False, k=key: self._set_kind(k))
            self._kind_group.addButton(btn)
            self._kind_buttons[key] = btn
            kinds.addWidget(btn)
        root.addLayout(kinds)

        self._search = QLineEdit()
        self._search.setClearButtonEnabled(True)
        self._search.setPlaceholderText("名前で探す（例: scatter・attribwrangle）")
        self._search.textChanged.connect(self._reload)
        root.addWidget(self._search)

        row = QHBoxLayout()
        self._used_only = QCheckBox("このチュートリアルで使ったものだけ")
        self._used_only.toggled.connect(self._reload)
        self._create_custom = QPushButton("この名前で作る")
        self._create_custom.setToolTip("一覧に無い名前（シェルフツールなど）を、この名前で、公式ドキュメントから探して説明を作ります")
        self._create_custom.clicked.connect(self._on_custom)
        row.addWidget(self._used_only)
        row.addStretch()
        row.addWidget(self._create_custom)
        root.addLayout(row)

        split = QSplitter(Qt.Vertical)
        self._list = QListWidget()
        self._list.setFont(type_font("body"))
        self._list.currentRowChanged.connect(self._on_row)
        split.addWidget(self._list)
        self._detail = QTextBrowser()
        self._detail.setOpenLinks(False)
        self._detail.setFont(type_font("body"))
        self._detail.anchorClicked.connect(self._on_link)
        self._detail.setMinimumHeight(px(160))
        split.addWidget(self._detail)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(px(6))
        self._make_btn = QPushButton("説明を作る")
        self._make_btn.setStyleSheet(button_qss("primary"))
        self._make_btn.setEnabled(False)
        self._make_btn.setToolTip("公式のドキュメントと HoudiniReference の抜粋を元に、AI が日本語でまとめます（保存され、次からは、すぐ出ます）")
        self._make_btn.clicked.connect(self._on_make)
        self._doc_btn = QPushButton("公式ドキュメントを開く")
        self._doc_btn.setEnabled(False)
        self._doc_btn.clicked.connect(self._on_open_doc)
        actions.addWidget(self._make_btn)
        actions.addWidget(self._doc_btn)
        actions.addStretch()
        root.addLayout(actions)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(type_qss("caption", "#94a3b8"))
        root.addWidget(self._status)

    # ── 一覧 ─────────────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt
        super().showEvent(event)
        self._pull_used()  # タブを開くたびに、Guide のチュートリアルで使ったものを、読み直す
        self._reload()

    def _guide(self) -> dict | None:
        """同じタブの中の Guide に、いま読み込まれているチュートリアル。"""
        try:
            import guide_view

            host = guide_view.locate_in_tabs(self)
            if host is None:
                return None
            widget = guide_view._guide_in(host[0])
            return getattr(widget, "_guide", None) if widget is not None else None
        except Exception:  # noqa: BLE001
            return None

    def _pull_used(self) -> None:
        self._used = rd.used_items(self._guide())

    def _set_kind(self, kind: str) -> None:
        self._kind = kind
        self._search.setPlaceholderText(
            "シェルフツールの名前を入れて、「この名前で作る」（例: Billowy Smoke）" if kind == "shelf" else "名前で探す（例: scatter・attribwrangle）")
        self._reload()

    def _reload(self, *_args) -> None:
        query = self._search.text()
        items = rd.search(self._kind, query, limit=2000)
        used_keys = self._used.get(self._kind, set())
        if self._used_only.isChecked():
            items = [i for i in items if i["key"] in used_keys]
        items.sort(key=lambda i: 0 if i["key"] in used_keys else 1)  # 使ったものを先頭に（並びの順は、そのまま）
        self._items = items[:_MAX_LIST]
        self._list.blockSignals(True)
        self._list.clear()
        for item in self._items:
            mark = _USED_MARK if item["key"] in used_keys else ""
            ctx = f"  [{item['context'].upper()}]" if item["kind"] in ("node", "apex") else ""
            row = QListWidgetItem(f"{mark}{item['label']}{ctx}")
            if mark:
                row.setToolTip("このチュートリアルで使いました")
            self._list.addItem(row)
        self._list.blockSignals(False)
        self._create_custom.setVisible(bool(query.strip()) and (self._kind == "shelf" or not self._items))
        total = len(rd.catalog(self._kind))
        shown = len(self._items)
        if self._kind == "shelf" and not query.strip():
            self._status.setText("シェルフツールは、名前を入れて「この名前で作る」を押してください（公式ドキュメントから、探して説明を作ります）")
        else:
            used_n = len(used_keys)
            self._status.setText(f"{shown} 件を表示（全 {total} 件）" + (f" / このチュートリアルで使ったもの: {used_n} 件" if used_n else ""))
        if self._items:
            self._list.setCurrentRow(0)
        else:
            self._current = None
            self._detail.setHtml("")
            self._make_btn.setEnabled(False)
            self._doc_btn.setEnabled(False)

    # ── 詳細 ─────────────────────────────────────────────────────────────────

    def _on_row(self, row: int) -> None:
        if 0 <= row < len(self._items):
            self._show(self._items[row])

    def _show(self, item: dict, entry: dict | None = None) -> None:
        self._current = item
        base_dir = str(self._cfg_getter().get("local_bridge_dir") or "")
        if entry is None and base_dir:
            entry = rd.load_entry(base_dir, item["kind"], item["key"])
        references = self._references_for(item)
        used = item["key"] in self._used.get(item["kind"], set())
        self._detail.setHtml(rd.entry_html(item, entry, references, used))
        self._make_btn.setEnabled(self._worker is None or not self._worker.isRunning())
        self._make_btn.setText("説明を作り直す" if entry else "説明を作る")
        self._doc_btn.setEnabled(bool(item.get("doc_url")))

    def _references_for(self, item: dict) -> list[dict]:
        """保存してある HoudiniReference の項目から、関係するもの（通信はしない。取得は、説明を作るとき）。"""
        if self._reference_items is None:
            base_dir = str(self._cfg_getter().get("local_bridge_dir") or "")
            path = Path(base_dir) / "localRAG" / "reference" / _REFERENCE_CACHE_NAME if base_dir else None
            try:
                data = json.loads(path.read_text(encoding="utf-8")) if path else {}
                self._reference_items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
            except (OSError, ValueError, AttributeError):
                self._reference_items = []
        return rd.match_reference_items(self._reference_items, item.get("label", ""), item.get("kind", ""))

    def show_item(self, kind: str, key: str, label: str = "") -> None:
        """指定の項目を開く（Guide の「ノードの説明」から）。一覧に無いときは、名前から作った項目にする。"""
        self._set_kind_button(kind)
        self._kind = kind
        self._search.blockSignals(True)
        self._search.setText("")
        self._search.blockSignals(False)
        self._pull_used()
        self._used_only.blockSignals(True)
        self._used_only.setChecked(False)
        self._used_only.blockSignals(False)
        self._reload()
        item = rd.find_item(kind, key) or rd.custom_item(kind, label or key.split("/")[-1])
        for row, candidate in enumerate(self._items):
            if candidate["key"] == item["key"]:
                self._list.setCurrentRow(row)
                return
        self._show(item)

    def _set_kind_button(self, kind: str) -> None:
        button = self._kind_buttons.get(kind)
        if button is not None:
            button.setChecked(True)

    # ── 操作 ─────────────────────────────────────────────────────────────────

    def _on_custom(self) -> None:
        item = rd.custom_item(self._kind, self._search.text())
        if item["name"]:
            self._show(item)
            self._on_make()

    def _on_make(self) -> None:
        if self._current is None or (self._worker is not None and self._worker.isRunning()):
            return
        item = self._current
        self._make_btn.setEnabled(False)
        self._status.setText(f"「{item['label']}」の説明を作っています（数秒〜十数秒）…")
        self._worker = _EntryWorker(self._cfg_getter(), self._complete_getter(), item, self)
        self._worker.done.connect(lambda entry, refs, it=item: self._on_made(it, entry, refs))
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_made(self, item: dict, entry: dict, references: list) -> None:
        self._reference_items = None  # 取得した HoudiniReference の保存を、次の表示で読み直す
        self._status.setText("説明を作りました（保存しました。次からは、すぐ出ます）")
        if self._current is not None and self._current["key"] == item["key"]:
            self._show(item, entry)
        else:
            self._make_btn.setEnabled(self._current is not None)

    def _on_failed(self, message: str) -> None:
        self._status.setText(message)
        self._make_btn.setEnabled(self._current is not None)

    def _on_open_doc(self) -> None:
        if self._current and str(self._current.get("doc_url") or "").startswith("https://"):
            QDesktopServices.openUrl(QUrl(self._current["doc_url"]))

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)


def open_item_for_step(source: QWidget, step: dict) -> str:
    """Guide の手順のノードを、Reference タブで開く。戻り値: 画面に出す 1 文（Reference タブが無いときは、その旨）。"""
    node_type = str((step or {}).get("node_type") or "")
    if not node_type:
        return "この手順には、説明するノードがありません"
    try:
        import guide_view

        host = guide_view.locate_in_tabs(source)
        if host is None:
            return "Reference タブが見つかりません"
        tabs = host[0]
        widget = tabs.findChild(ReferenceWidget)
        if widget is None:
            return "Reference タブが見つかりません"
        base = rd.base_type(node_type).lower()
        hit = None
        for kind in ("node", "apex"):
            for item in rd.search(kind, base, limit=60):
                if item["name"].split("--")[-1].lower() == base:
                    hit = item
                    break
            if hit:
                break
        label = str(step.get("node_label") or base)
        tabs.setCurrentIndex(tabs.indexOf(_page_of(tabs, widget)))
        if hit:
            widget.show_item(hit["kind"], hit["key"], hit["label"])
        else:
            widget.show_item("node", f"node/{rd.slug(base)}", label)
        return f"Reference タブで「{label}」を開きました"
    except Exception as exc:  # noqa: BLE001
        return f"Reference タブを開けませんでした（{exc}）"


def _page_of(tabs, widget: QWidget) -> QWidget:
    """tabs の中で、widget を含むページ（タブに登録されているウィジェット）。"""
    node = widget
    while node is not None and tabs.indexOf(node) < 0:
        node = node.parentWidget()
    return node if node is not None else widget
