"""
docs_view.py — Docs タブ: ナレッジベースに入っているドキュメントを、パネルの中で探して読む（2026-10-31）

以前ここにあった「Graph タブ」（ドキュメント同士の関係図）は、生成の質にも学習にもつながらず、使われていなかったので、
この閲覧タブに置き換えた。チュートリアル生成が参照するドキュメント（Houdini の公式マニュアルなど）を、
生成の出典 [n] と同じ名前で開いて、中身を確かめられる。

  ・上段: ナレッジの選択 / 検索語 / 「意味で検索」（/search。関連度の高い順） / 「名前で絞る」（/docs/list。名前の部分一致）
  ・左: 結果の一覧（クリックで本文を開く）
  ・右: 本文（長いときは「続きを読む」で追加）

Cloudflare モードだけで使える（Worker の /docs/list・/docs/get・/search）。通信は QThread で行い、画面は止めない。
"""

from __future__ import annotations

from typing import Callable

from doc_tools import excerpt_for_list, parse_search_hits, pick_default_namespace, sort_namespaces
from rag_client import RAGClient, error_message
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
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

LIST_PAGE = 50          # 「名前で絞る」の1回の件数
SEARCH_LIMIT = 8        # 「意味で検索」の件数
READ_CHARS = 20000      # 本文の1回の取得量
# 実行中の仕事。パネルが閉じられて DocsWidget が壊れても、QThread が動いている間は壊さない
# （"QThread: Destroyed while thread is still running" で Houdini ごと落ちるのを防ぐ）。
_RUNNING_JOBS: set = set()


class _Job(QThread):
    """関数を別スレッドで1回実行して、結果かエラー文を返す。"""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 -- 画面にはエラー文だけ出す
            self.failed.emit(error_message(exc))


class DocsWidget(QWidget):
    """Docs タブに埋め込む完成ウィジェット。rag_chatbot.py の _build_docs_tab() から作られる。"""

    def __init__(self, cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._loaded_namespaces = False
        self._alive = True        # 閉じられた後に届いた結果で、壊れた画面を触らない
        self._generation = 0       # 新しい操作を始めたら増やす。古い結果は捨てる
        self._list_mode = ""       # "list" | "search" | ""
        self._list_offset = 0
        self._list_total = 0
        self._doc_file = ""
        self._doc_text = ""
        self._doc_next: int | None = None
        self._open_top_hit = False  # 「選択中のノードを調べる」から検索したとき、先頭の結果を自動で開く
        self._node_info: dict | None = None
        self._build_ui()

    # ── 公開 ─────────────────────────────────────────────────────────────────

    def set_connection(self, cfg: dict) -> None:
        """接続設定が変わったとき（設定タブで保存・モード切り替え）に、パネルから呼ばれる。"""
        self._cfg = cfg
        self._loaded_namespaces = False
        if self.isVisible():
            self._load_namespaces()

    def open_document(self, file: str, namespace: str | None = None) -> None:
        """名前を指定して、本文を開く（チャットの /doc などから使う）。"""
        if namespace:
            index = self._ns.findText(namespace)
            if index >= 0:
                self._ns.setCurrentIndex(index)
        self._open(file)

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt
        self._alive = False
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt
        super().showEvent(event)
        if not self._loaded_namespaces:
            self._load_namespaces()

    # ── 画面 ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        bar = QHBoxLayout()
        self._ns = QComboBox()
        self._ns.setMinimumWidth(150)
        self._ns.setToolTip("読むナレッジ。チュートリアル生成が参照するのは shared:houdini<バージョン>")
        self._query = QLineEdit()
        self._query.setPlaceholderText("ノード名・用語（例: rbd fracture / copy to points）")
        self._query.returnPressed.connect(self._on_search)
        self._search_btn = QPushButton("意味で検索")
        self._search_btn.setToolTip("意味と文字の両方で探して、関連度の高い順に出します（Claude とは別の、検索だけの処理です）")
        self._search_btn.clicked.connect(self._on_search)
        self._list_btn = QPushButton("名前で絞る")
        self._list_btn.setToolTip("ドキュメント名に、この語を含むものを並べます。空のまま押すと、全部を名前順に出します")
        self._list_btn.clicked.connect(self._on_list)
        self._node_btn = QPushButton("選択中のノードを調べる")
        self._node_btn.setToolTip("Houdini のネットワークエディタで選んでいるノードの説明を、ナレッジから探して開きます")
        self._node_btn.clicked.connect(self._on_selected_node)
        self._help_btn = QPushButton("公式ヘルプ")
        self._help_btn.setToolTip("Houdini 自身のヘルプ（そのノードのマニュアルのページ）を開きます")
        self._help_btn.setVisible(False)
        self._help_btn.clicked.connect(self._on_open_help)
        bar.addWidget(self._ns)
        bar.addWidget(self._query, stretch=1)
        bar.addWidget(self._search_btn)
        bar.addWidget(self._list_btn)
        bar.addWidget(self._node_btn)
        bar.addWidget(self._help_btn)
        root.addLayout(bar)

        self._status = QLabel("ナレッジのドキュメントを探して読めます。検索語を入れて「意味で検索」を押してください")
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._results = QListWidget()
        self._results.setWordWrap(True)
        self._results.itemClicked.connect(self._on_item)
        self._more_btn = QPushButton("さらに表示")
        self._more_btn.clicked.connect(self._on_more_list)
        self._more_btn.setVisible(False)
        left_layout.addWidget(self._results, stretch=1)
        left_layout.addWidget(self._more_btn)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._doc_title = QLabel("")
        self._doc_title.setStyleSheet("font-weight:bold;")
        self._doc_title.setWordWrap(True)
        self._reader = QTextBrowser()
        self._reader.setOpenExternalLinks(True)
        self._next_btn = QPushButton("続きを読む")
        self._next_btn.clicked.connect(self._on_next)
        self._next_btn.setVisible(False)
        right_layout.addWidget(self._doc_title)
        right_layout.addWidget(self._reader, stretch=1)
        right_layout.addWidget(self._next_btn)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, stretch=1)

    # ── 通信（QThread） ───────────────────────────────────────────────────────

    def _client(self) -> RAGClient:
        return RAGClient(self._cfg)

    def _run(self, fn: Callable[[], object], on_done: Callable[[object], None], busy: str) -> None:
        self._generation += 1
        generation = self._generation
        self._status.setText(busy)
        self._set_busy(True)
        job = _Job(fn)
        _RUNNING_JOBS.add(job)

        def finished(result: object) -> None:
            if self._alive and generation == self._generation:
                self._set_busy(False)
                on_done(result)

        def failed(message: str) -> None:
            if self._alive and generation == self._generation:
                self._set_busy(False)
                self._status.setText(f"エラー: {message}")

        job.done.connect(finished)
        job.failed.connect(failed)
        job.finished.connect(lambda: _RUNNING_JOBS.discard(job))
        job.start()

    def _set_busy(self, busy: bool) -> None:
        for button in (self._search_btn, self._list_btn, self._node_btn, self._more_btn, self._next_btn):
            button.setEnabled(not busy)

    def _namespace(self) -> str:
        return self._ns.currentText().strip()

    # ── ナレッジの一覧 ────────────────────────────────────────────────────────

    def _load_namespaces(self) -> None:
        self._loaded_namespaces = True
        if self._cfg.get("mode") != "cloudflare":
            self._status.setText("Docs は、Cloudflare モードで、Worker の URL と APIキーを設定すると使えます（接続タブ）")
            return
        client = self._client()
        self._run(client.docs_namespaces, self._on_namespaces, "ナレッジの一覧を取得しています…")

    def _on_namespaces(self, result: object) -> None:
        namespaces = sort_namespaces([str(n) for n in (result or [])])  # type: ignore[union-attr]
        self._ns.clear()
        self._ns.addItems(namespaces)
        default = pick_default_namespace(namespaces, str(self._cfg.get("tutorial_rag_namespace", "")))
        if default:
            self._ns.setCurrentText(default)
            self._status.setText("検索語を入れて「意味で検索」を押してください。名前の一部が分かるときは「名前で絞る」")
        else:
            self._status.setText("読めるナレッジがありません（APIキーの権限を確認してください）")

    # ── 検索・一覧 ────────────────────────────────────────────────────────────

    def _on_search(self) -> None:
        query = self._query.text().strip()
        namespace = self._namespace()
        if not namespace:
            self._status.setText("ナレッジを選んでください")
            return
        if not query:
            self._status.setText("検索語を入れてください（名前の一覧だけ見たいときは「名前で絞る」）")
            return
        client = self._client()
        self._run(
            lambda: client.docs_search(namespace, query, SEARCH_LIMIT),
            lambda data: self._on_search_done(data, query),
            f"「{query}」を検索しています…",
        )

    def _on_search_done(self, data: object, query: str) -> None:
        hits = parse_search_hits(data if isinstance(data, dict) else {})
        self._list_mode = "search"
        self._more_btn.setVisible(False)
        self._results.clear()
        for file, score, excerpts in hits:
            label = f"{file}" + (f"   （関連度 {score}）" if score is not None else "")
            item = QListWidgetItem(f"{label}\n{excerpt_for_list(excerpts)}")
            item.setData(Qt.UserRole, file)
            item.setToolTip(" … ".join(excerpts)[:600])
            self._results.addItem(item)
        self._status.setText(
            f"「{query}」: {len(hits)} 件。クリックで本文を開きます" if hits else f"「{query}」に一致するドキュメントはありませんでした"
        )
        if self._open_top_hit and hits:
            self._open_top_hit = False
            self._open(hits[0][0])
        else:
            self._open_top_hit = False

    def _on_selected_node(self) -> None:
        """Houdini で選んでいるノードの説明を探す（先頭の結果を自動で開く）。"""
        try:
            import hou  # type: ignore[import-not-found]
        except ImportError:
            self._status.setText("Houdini の中でだけ使えます")
            return
        import guide_mode

        info = guide_mode.selected_node_info(hou)
        if info is None:
            self._status.setText("ネットワークエディタで、調べたいノードを1つ選んでから押してください")
            return
        self._node_info = info
        self._help_btn.setVisible(True)
        self._query.setText(guide_mode.doc_query(info))
        self._open_top_hit = True
        self._on_search()

    def _on_open_help(self) -> None:
        if not self._node_info:
            return
        try:
            import hou  # type: ignore[import-not-found]
            import guide_mode
        except ImportError:
            return
        _ok, message = guide_mode.open_node_help(hou, self._node_info)
        self._status.setText(message)

    def _on_list(self) -> None:
        namespace = self._namespace()
        if not namespace:
            self._status.setText("ナレッジを選んでください")
            return
        self._list_mode = "list"
        self._list_offset = 0
        self._results.clear()
        self._fetch_list(namespace, self._query.text().strip(), 0)

    def _on_more_list(self) -> None:
        if self._list_mode == "list":
            self._fetch_list(self._namespace(), self._query.text().strip(), self._list_offset)

    def _fetch_list(self, namespace: str, query: str, offset: int) -> None:
        client = self._client()
        self._run(
            lambda: client.docs_list(namespace, query, LIST_PAGE, offset),
            lambda data: self._on_list_done(data, query, offset),
            "一覧を取得しています…",
        )

    def _on_list_done(self, data: object, query: str, offset: int) -> None:
        data = data if isinstance(data, dict) else {}
        files = [str(f) for f in (data.get("files") or [])]
        self._list_total = int(data.get("total") or 0)
        self._list_offset = offset + len(files)
        for file in files:
            item = QListWidgetItem(file)
            item.setData(Qt.UserRole, file)
            self._results.addItem(item)
        self._more_btn.setVisible(self._list_offset < self._list_total)
        shown = self._results.count()
        what = f"名前に「{query}」を含む" if query else "全部の"
        self._status.setText(f"{what}ドキュメント: {self._list_total} 件中 {shown} 件を表示。クリックで本文を開きます")

    # ── 本文 ─────────────────────────────────────────────────────────────────

    def _on_item(self, item: QListWidgetItem) -> None:
        file = item.data(Qt.UserRole)
        if file:
            self._open(str(file))

    def _open(self, file: str) -> None:
        namespace = self._namespace()
        if not namespace:
            return
        client = self._client()
        self._doc_file, self._doc_text, self._doc_next = file, "", None
        self._doc_title.setText(file)
        self._reader.clear()
        self._next_btn.setVisible(False)
        self._run(
            lambda: client.docs_get(namespace, file, 0, READ_CHARS),
            lambda data: self._on_doc_done(data, append=False),
            f"「{file}」を開いています…",
        )

    def _on_next(self) -> None:
        if self._doc_next is None or not self._doc_file:
            return
        client, namespace, file, offset = self._client(), self._namespace(), self._doc_file, self._doc_next
        self._run(
            lambda: client.docs_get(namespace, file, offset, READ_CHARS),
            lambda data: self._on_doc_done(data, append=True),
            "続きを取得しています…",
        )

    def _on_doc_done(self, data: object, append: bool) -> None:
        data = data if isinstance(data, dict) else {}
        text = str(data.get("text") or "")
        total = int(data.get("totalChars") or 0)
        nxt = data.get("nextOffset")
        self._doc_next = int(nxt) if nxt is not None else None
        scroll = self._reader.verticalScrollBar().value() if append else 0
        self._doc_text = self._doc_text + text if append else text
        self._render_text(self._doc_text)
        self._reader.verticalScrollBar().setValue(scroll)
        read = len(self._doc_text)
        self._doc_title.setText(f"{self._doc_file}   （{read:,} / {total:,} 文字）")
        self._next_btn.setVisible(self._doc_next is not None)
        self._status.setText("続きがあります。「続きを読む」で追加します" if self._doc_next is not None else "最後まで表示しました")

    def _render_text(self, text: str) -> None:
        try:
            self._reader.setMarkdown(text)
        except Exception:  # noqa: BLE001 -- Markdown に直せない形でも、文字は読めるように
            self._reader.setPlainText(text)
