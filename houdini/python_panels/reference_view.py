"""
reference_view.py — Reference タブ: ノード・VEX・APEX・シェルフツールの「何をする・使いどころ・実例」（2026-11-19）

  ・上段: 種類（ノード / VEX / APEX / シェルフ）、検索、「このチュートリアルで使ったものだけ」
  ・中段: 一覧。チュートリアル（Guide に読み込んだもの）で使ったものには「●」が付き、先頭に並ぶ
  ・下段: 詳細（何をする・どんなもの / どういったものに使うか / 実例 / 実例のポイント / 使いどころ / HoudiniReference の関連）
  ・説明は、開発側が作って Cloudflare に置いたものを、通信で取って読むだけ（reference_remote.py。人ごとに内容が違う・AI の費用が際限なくかかる、を避ける）。
    取った説明・画像は、端末にキャッシュする。説明のある項目は、「説明のあるものだけ」で絞れる（既定）
  ・適用前後・ノード画面の画像、適用の動き（GIF）も、同じく Cloudflare から（あるものだけ）
  ・開発者モード（設定 reference_author_mode、または環境変数 RAGREEL_REFERENCE_AUTHOR=1）のときだけ、「説明を作る」（AI で作る）が出る。
    SideFX 公式のドキュメント（RAG）と HoudiniReference の抜粋を材料に、AI が日本語でまとめる。公開は scripts/publish_reference.py
  ・シェルフツールの一覧は、Houdini（hou.shelves）から取る
  ・Guide の「ノードの説明」から、その手順のノードの項目が開く（open_item_for_step）

データと文章は reference_data.py（Qt なし）。通信は reference_remote.py（Qt なし）と、別スレッド（_IndexWorker・_EntryFetchWorker・_EntryWorker）。
"""

from __future__ import annotations

import html
import json
import os
import time
from pathlib import Path
from typing import Callable

import panel_bus
import reference_author as ra
import reference_data as rd
import reference_remote as rr
from reference_author import fetch_reference_items  # noqa: F401 -- 画面とテストが、この名前で使う（本体は reference_author）
from panel_actions import button_qss, px, type_font, type_qss
from PySide6.QtCore import QEvent, QObject, QSize, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QMovie, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

_USED_MARK = "● "
_MEDIA_MARK = "▶ "  # 撮影した画像・動きがある項目（一覧の頭に付ける）
_MAX_LIST = 200
_INDEX_REFRESH_SECONDS = 60
_STILL_ROLES = ("where", "before", "after", "node")
_MOVIE_SUFFIXES = (".gif", ".webp")
_VIDEO_SUFFIXES = (".webm", ".mp4")


_LIVE_THREADS: set = set()


def _start_detached(thread: QThread) -> None:
    """スレッドを開始し、画面（親）が先に消えても、終わるまで生かしておく。動いている QThread が壊れると、Houdini ごと落ちるため。"""
    _LIVE_THREADS.add(thread)
    thread.finished.connect(lambda t=thread: _LIVE_THREADS.discard(t))
    thread.start()


def _sharp_scaled(image: QImage, width: int, ratio: float = 1.0) -> QImage:
    """表示する幅に、なめらかに縮めた画像（2026-11-25）。
    QTextDocument に元の大きさのまま渡して width で縮めさせると、粗い縮め方になり、図の文字が潰れて読めなかった。
    先に SmoothTransformation で、表示の幅（高 DPI の画面では、その倍率ぶん大きく）に縮めておく。広げることは、しない。"""
    target = max(1, int(round(width * max(1.0, ratio))))
    if image.width() <= target:
        return image
    scaled = image.scaledToWidth(target, Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(max(1.0, ratio))
    return scaled


def houdini_shelf_tools() -> list[tuple[str, str, str]]:
    """Houdini のシェルフツール [(シェルフの名前, ツールの内部名, 表示名), ...]。Houdini の外（hou が無い）では、空。"""
    try:
        import hou  # type: ignore

        out = []
        for shelf in hou.shelves.shelves().values():
            label = shelf.label()
            for tool in shelf.tools():
                out.append((label, tool.name(), tool.label()))
        return out
    except Exception:  # noqa: BLE001
        return []


class _FitMovieLabel(QLabel):
    """GIF（動き）を、置かれた場所の大きさに合わせて縮めて出す（大きい元の絵でも、説明文を押しのけない。元より大きくはしない）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)  # 中身の大きさで、場所を要求しない
        self.setMinimumSize(px(40), px(40))
        self._native = QSize()

    def show_movie(self, movie: QMovie, native: QSize) -> None:
        self._native = native
        self.setMovie(movie)
        self._fit()

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        movie = self.movie()
        if movie is None or self._native.width() <= 0 or self.width() < 8 or self.height() < 8:
            return
        target = self._native.scaled(max(8, self.width() - 4), max(8, self.height() - 4), Qt.KeepAspectRatio)
        if target.width() > self._native.width():
            target = QSize(self._native)
        if movie.scaledSize() != target:
            movie.setScaledSize(target)


class _IndexWorker(QThread):
    """Cloudflare の、説明のある項目の一覧（版つき）を取る。別スレッド。"""

    done = Signal(object)

    def __init__(self, cfg: dict, force: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._cfg, self._force = dict(cfg), force

    def run(self) -> None:
        try:
            index = rr.fetch_index(self._cfg, force=self._force)
            try:
                rr.prune_cache(self._cfg)  # 端末の保存が増え続けないように、使われない画像を消す
            except Exception:  # noqa: BLE001
                pass
            self.done.emit(index)
        except Exception:  # noqa: BLE001
            self.done.emit({})


class _EntryFetchWorker(QThread):
    """1 項目の説明と、その画像・動画を、Cloudflare から取って、端末に保存する。別スレッド。結果は、保存したファイルから読む（終わったら finished）。"""

    def __init__(self, cfg: dict, item: dict, version: int | None, parent=None) -> None:
        super().__init__(parent)
        self._cfg, self._item, self._version = dict(cfg), dict(item), version

    def run(self) -> None:
        try:
            record = rr.fetch_entry(self._cfg, self._item["kind"], self._item["key"], self._version)
            for media in ((record or {}).get("media") or [])[:6]:
                rr.fetch_media(self._cfg, str(media.get("id") or ""))
        except Exception:  # noqa: BLE001 -- 取れなければ、保存が増えないだけ（画面は、取れなかったと伝える）
            pass


class _EntryWorker(QThread):
    """1 項目の説明を作る（公式ドキュメントの取得 → HoudiniReference → AI）。別スレッド。"""

    done = Signal(object, object, object)   # (項目の内容 dict, 関連の項目 list, 使ったトークン usage dict)
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
            references = rd.match_reference_items(fetch_reference_items(base_dir), label, self._item.get("kind", ""), aliases=rd.item_aliases(self._item), context=rd.item_context(self._item))
            docs = self._fetch_docs(label)  # テストが差し替える入口（本体は ra.fetch_docs）
            try:
                entry, usage, docs_found, refs_found = ra.make_entry(self._cfg, self._complete, self._item, references=references, docs=docs)
            except ra.UnreadableAnswer:
                self.failed.emit("AI の返事を読み取れませんでした。もう一度、「説明を作る」を押してください")
                return
            ra.save_made(base_dir, self._item, entry, docs_found, refs_found)
            self.done.emit(entry, references, usage)
        except Exception as exc:  # noqa: BLE001 -- 画面に理由を出す。パネルは止めない
            self.failed.emit(f"説明を作れませんでした（{str(exc)[:120]}）")

    def _fetch_docs(self, label: str) -> list[str]:
        return ra.fetch_docs(self._cfg, self._item)


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
        self._reference_items: list[dict] | None = None
        self._worker: _EntryWorker | None = None
        self._remote: dict[str, dict] = rr.load_cached_index(self._cfg_getter() or {})  # Cloudflare にある説明の一覧（保存してあるもの。最新は、タブを開いたときに取る）
        self._index_worker: _IndexWorker | None = None
        self._index_at = 0.0
        self._refresh_requested_at = 0.0  # 「再読み込み」を押した時刻（0 = 押していない）
        self._fetch_worker: _EntryFetchWorker | None = None
        self._fetch_tried: set[tuple[str, str, int]] = set()
        self._media_files: dict[str, Path] = {}  # 画像の id → 端末に保存した元の画像（押すと開く）
        self._movie: QMovie | None = None
        self._media_width = 0
        self._relayout = QTimer(self)
        self._relayout.setSingleShot(True)
        self._relayout.setInterval(150)
        self._relayout.timeout.connect(self._relayout_media)
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
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)  # 狭い場所でも、押しのけない
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

        row = QBoxLayout(QBoxLayout.LeftToRight)
        self._filter_row = row
        self._used_only = QCheckBox("このチュートリアルで使ったものだけ")
        self._used_only.toggled.connect(self._reload)
        self._described_only = QCheckBox("説明のあるものだけ")
        self._described_only.setChecked(not self._author())  # 開発者は、説明の無いものも見て、作る
        self._described_only.setToolTip("Cloudflare に、説明が置いてある項目だけを、一覧に出します（通信できないときは、全部）")
        self._described_only.toggled.connect(self._reload)
        self._media_only = QCheckBox("撮影のあるものだけ")
        self._media_only.setToolTip("適用前後の画像・ノード画面・動きが、置いてある項目だけを、一覧に出します（一覧の「▶」が付いたもの）")
        self._media_only.toggled.connect(self._reload)
        self._create_custom = QPushButton("この名前で作る")
        self._create_custom.setToolTip("一覧に無い名前（シェルフツールなど）を、この名前で、公式ドキュメントから探して説明を作ります")
        self._create_custom.clicked.connect(self._on_custom)
        self._create_custom.setVisible(False)
        row.addWidget(self._used_only)
        row.addWidget(self._described_only)
        row.addWidget(self._media_only)
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
        self._detail.setMinimumHeight(px(60))
        self._detail.document().setDefaultStyleSheet("a { color: #ffffff; text-decoration: underline; }")  # 青いリンクは、暗い背景で読みづらい
        self._detail.viewport().installEventFilter(self)  # 幅が変わったら、画像の大きさを合わせ直す
        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)
        # 説明（上）と、適用の動き（下）。境目をドラッグして、比率を変えられる（動きは、縮めて、隠すこともできる）
        self._detail_split = QSplitter(Qt.Vertical)
        self._detail_split.setHandleWidth(px(8))
        self._detail_split.setChildrenCollapsible(True)
        self._detail_split.addWidget(self._detail)
        self._clip_box = QWidget()
        clip_layout = QVBoxLayout(self._clip_box)
        clip_layout.setContentsMargins(0, px(2), 0, 0)
        clip_layout.setSpacing(px(4))
        self._clip = _FitMovieLabel()  # 適用の動き（GIF）。あるときだけ出す
        self._clip.setToolTip("上の境目をドラッグすると、大きさを変えられます")
        clip_layout.addWidget(self._clip, stretch=1)
        self._clip_btn = QPushButton("適用の動画を開く")
        self._clip_btn.clicked.connect(self._on_open_clip)
        clip_layout.addWidget(self._clip_btn)
        self._clip_box.setVisible(False)
        self._clip_btn.setVisible(False)
        self._detail_split.addWidget(self._clip_box)
        self._detail_split.setStretchFactor(0, 3)
        self._detail_split.setStretchFactor(1, 2)
        detail_layout.addWidget(self._detail_split)
        split.addWidget(detail_box)
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
        self._make_btn.setVisible(self._author())  # 開発者モードだけ（参加者は、Cloudflare の説明を読むだけ）
        self._doc_btn = QPushButton("公式ドキュメントを開く")
        self._doc_btn.setEnabled(False)
        self._doc_btn.clicked.connect(self._on_open_doc)
        self._refresh_btn = QPushButton("再読み込み")
        self._refresh_btn.setToolTip("Cloudflare から、説明の一覧と、いま見ている説明を取り直します（公開された修正が、すぐ反映されます。1 時間待たなくて済みます）")
        self._refresh_btn.clicked.connect(self._on_refresh)
        actions.addWidget(self._make_btn)
        actions.addWidget(self._doc_btn)
        actions.addWidget(self._refresh_btn)
        actions.addStretch()
        root.addLayout(actions)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(type_qss("caption", "#94a3b8"))
        root.addWidget(self._status)

    # ── 一覧 ─────────────────────────────────────────────────────────────────

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt
        if watched is self._detail.viewport() and event.type() == QEvent.Resize:
            self._relayout.start()  # 動いている間は待って、止まったら 1 回だけ
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt
        super().resizeEvent(event)
        wide = self.width() >= px(420)  # 狭い場所では、絞り込みのチェックを縦に並べる（横に並べると、はみ出す）
        self._filter_row.setDirection(QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom)

    def _relayout_media(self) -> None:
        """詳細欄の幅が変わったので、画像の大きさを合わせて、表示し直す（読んでいる位置は、保つ）。"""
        width = self._detail.viewport().width()
        if self._current is None or abs(width - self._media_width) < 24:
            return
        bar = self._detail.verticalScrollBar()
        position = bar.value()
        self._show(self._current)
        bar.setValue(min(position, bar.maximum()))

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt
        super().showEvent(event)
        self._pull_used()  # タブを開くたびに、Guide のチュートリアルで使ったものを、読み直す
        self._refresh_index()
        self._reload(keep_key=self._current_key())

    def _author(self) -> bool:
        """開発者モード（説明を AI で作れる）。設定 reference_author_mode、または環境変数 RAGREEL_REFERENCE_AUTHOR=1。"""
        try:
            cfg = self._cfg_getter() or {}
        except Exception:  # noqa: BLE001
            cfg = {}
        return bool(cfg.get("reference_author_mode")) or os.environ.get("RAGREEL_REFERENCE_AUTHOR", "") == "1"

    def _refresh_index(self, force: bool = False) -> None:
        """Cloudflare の、説明のある項目の一覧を取り直す（別スレッド。1 分に 1 回まで）。"""
        now = time.time()
        if (self._index_worker is not None and self._index_worker.isRunning()) or (not force and now - self._index_at < _INDEX_REFRESH_SECONDS):
            return
        self._index_at = now
        self._index_worker = _IndexWorker(self._cfg_getter() or {}, force=force)
        self._index_worker.done.connect(self._on_index)
        _start_detached(self._index_worker)

    def _on_refresh(self) -> None:
        """「再読み込み」: 一覧を、待ち時間（1 時間・1 分）を飛ばして取り直し、見ている説明も取り直す（公開した修正が、反映されない、をなくす）。"""
        cfg = self._cfg_getter() or {}
        self._fetch_tried.clear()  # 前に取れなかった版も、もう一度
        if self._current is not None:
            rr.drop_cached_entry(cfg, self._current["kind"], self._current["key"])  # 版が同じでも、取り直す
        self._refresh_requested_at = time.time()
        self._refresh_btn.setEnabled(False)
        self._status.setText("再読み込み中…")
        if self._index_worker is not None and self._index_worker.isRunning():
            self._index_worker.wait(3000)  # 取りかけの一覧があれば、終わるのを少し待つ（終わらなければ、次の再読み込みで）
        self._index_at = 0.0
        self._refresh_index(force=True)
        if self._current is not None:
            self._show(self._current)  # 説明を消したので、取り直しが始まる

    def _finish_refresh(self, index: dict) -> None:
        """「再読み込み」の結果を、画面の下に出す（通信できたか・何件か）。"""
        requested = self._refresh_requested_at
        self._refresh_requested_at = 0.0
        self._refresh_btn.setEnabled(True)
        reached = rr.index_fetched_at(self._cfg_getter() or {}) >= requested - 1
        if reached and index:
            self._status.setText(f"再読み込みしました（説明のある項目 {len(index)} 件）")
        else:
            self._status.setText("再読み込みできませんでした（通信を確かめてください）。保存してある説明を表示しています")
        # 見ている説明の取り直しは、_on_refresh が始めてある（終わると _after_fetch が、表示し直す）

    def _on_index(self, index: dict) -> None:
        refreshing = bool(self._refresh_requested_at)
        valid = isinstance(index, dict) and bool(index)  # 取れなかったときは、保存したものを、そのまま使う
        if valid and index != self._remote:
            self._remote = index
            self._pull_used()  # 公開済みの項目が増えると、使った印の照合も変わる
            self._reload(keep_key=self._current_key())  # 見ている項目を、動かさない
        if refreshing:
            self._finish_refresh(index if valid else {})  # 一覧の件数の表示より後に、結果を出す

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

    def _extra_nodes(self) -> list[dict]:
        """一覧データに無い、公開済みのノード（Mountain・Twist など）。使った印・手順への飛び先の照合に足す。"""
        return rd.remote_items("node", self._remote) + rd.remote_items("apex", self._remote)

    def _pull_used(self) -> None:
        self._used = rd.used_items(self._guide(), self._extra_nodes())

    def _ensure_shelf_tools(self) -> None:
        """シェルフツールの一覧を、Houdini から取る（初めて開くときだけ）。"""
        if not rd.catalog("shelf"):
            rd.set_shelf_tools(rd.shelf_items(houdini_shelf_tools()))

    def _set_kind(self, kind: str) -> None:
        self._kind = kind
        if kind == "shelf":
            self._ensure_shelf_tools()
        self._search.setPlaceholderText(
            "シェルフツールの名前を入れて、「この名前で作る」（例: Billowy Smoke）" if kind == "shelf" else "名前で探す（例: scatter・attribwrangle）")
        self._reload()

    def _has_media(self, item: dict) -> bool:
        """この項目に、撮影した画像・動きが置いてあるか（Cloudflare の一覧の mediaCount）。"""
        meta = self._remote.get(rr.index_key(item["kind"], item["key"]))
        try:
            return bool(meta) and int(meta.get("mediaCount") or 0) > 0
        except (TypeError, ValueError):
            return False

    def _current_key(self) -> tuple[str, str] | None:
        return (self._current["kind"], self._current["key"]) if self._current else None

    def _reload(self, *_args, keep_key: tuple[str, str] | None = None) -> None:
        query = self._search.text()
        items = rd.search(self._kind, query, limit=100000, extra=rd.remote_items(self._kind, self._remote))  # 絞り込み（使ったもの・説明のあるもの）は、ここから後で行うので、先に切らない
        used_keys = self._used.get(self._kind, set())
        if self._used_only.isChecked():
            items = [i for i in items if i["key"] in used_keys]
        if self._described_only.isChecked() and self._remote:
            items = [i for i in items if rr.index_key(i["kind"], i["key"]) in self._remote]
        if self._media_only.isChecked():
            items = [i for i in items if self._has_media(i)]
        items.sort(key=lambda i: 0 if i["key"] in used_keys else 1)  # 使ったものを先頭に（並びの順は、そのまま）
        self._items = items[:_MAX_LIST]
        self._list.blockSignals(True)
        self._list.clear()
        for item in self._items:
            mark = (_USED_MARK if item["key"] in used_keys else "") + (_MEDIA_MARK if self._has_media(item) else "")
            if item["kind"] in ("node", "apex"):
                ctx = f"  [{item['context'].upper()}]"
            elif item["kind"] == "shelf" and item.get("context"):
                ctx = f"  [{item['context']}]"
            else:
                ctx = ""
            row = QListWidgetItem(f"{mark}{item['label']}{ctx}")
            tips = (["このチュートリアルで使いました"] if item["key"] in used_keys else []) + (["撮影した画像・動きがあります"] if self._has_media(item) else [])
            if tips:
                row.setToolTip("\n".join(tips))
            self._list.addItem(row)
        self._list.blockSignals(False)
        self._create_custom.setVisible(self._author() and bool(query.strip()) and (self._kind == "shelf" or not self._items))
        total = len(rd.catalog(self._kind))
        shown = len(self._items)
        used_n = len(used_keys)
        described_n = sum(1 for i in rd.catalog(self._kind) if rr.index_key(i["kind"], i["key"]) in self._remote)
        media_n = sum(1 for i in rd.remote_items(self._kind, self._remote) + rd.catalog(self._kind) if self._has_media(i))
        if self._kind == "shelf" and total == 0:
            self._status.setText("シェルフツールの一覧は、Houdini の中で開くと出ます")
        else:
            self._status.setText(f"{shown} 件を表示（全 {total} 件、説明あり {described_n} 件・撮影あり {media_n} 件）" + (f" / このチュートリアルで使ったもの: {used_n} 件" if used_n else ""))
        if self._items:
            row = next((r for r, i in enumerate(self._items) if keep_key and (i["kind"], i["key"]) == keep_key), 0)
            self._list.setCurrentRow(row)
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
        cfg = self._cfg_getter() or {}
        base_dir = str(cfg.get("local_bridge_dir") or "")
        author = self._author()
        meta = self._remote.get(rr.index_key(item["kind"], item["key"]))
        record = None
        loading = False
        gave_up = False
        if entry is None and meta:
            record = rr.load_cached_entry(cfg, item["kind"], item["key"])
            version = int(meta.get("version") or 0)
            stale = record is None or int(record.get("version", -1)) != version
            missing = record is not None and any(
                not (rr.media_path(cfg, str(m.get("id") or "")) or Path("/nonexistent")).is_file() for m in (record.get("media") or [])[:6])
            tried = (item["kind"], item["key"], version) in self._fetch_tried
            if (stale or missing) and not tried:
                loading = record is None
                self._start_fetch(item, version)
            gave_up = record is None and tried  # 取りに行ったが、取れなかった
            entry = (record or {}).get("entry")
        if entry is None and author and base_dir:
            entry = rd.load_entry(base_dir, item["kind"], item["key"])  # 開発者: 自分で作った（まだ公開していない）説明
        references = self._references_for(item)
        used = item["key"] in self._used.get(item["kind"], set())
        steps = rd.used_steps(self._guide(), item.get("kind", ""), item.get("key", ""), self._extra_nodes())
        media_block = self._prepare_media(cfg, record)
        self._detail.setHtml(rd.entry_html(item, entry, references, used, steps, media=media_block, author=author, loading=loading))
        self._make_btn.setEnabled(self._worker is None or not self._worker.isRunning())
        self._make_btn.setText("説明を作り直す" if entry else "説明を作る")
        self._doc_btn.setEnabled(bool(item.get("doc_url")))
        if gave_up and entry is None:
            self._status.setText("説明を取得できませんでした（通信を確かめてください）")

    def _start_fetch(self, item: dict, version: int) -> None:
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return  # 終わったら（_after_fetch）、いま見ている項目で、やり直す
        self._fetch_tried.add((item["kind"], item["key"], version))  # 取れなくても、同じ版で何度も取りに行かない（このセッションでは）
        self._fetch_worker = _EntryFetchWorker(self._cfg_getter() or {}, item, version)
        self._fetch_worker.finished.connect(self._after_fetch)
        _start_detached(self._fetch_worker)

    def _after_fetch(self) -> None:
        """取得が終わった: いま見ている項目を、表示し直す（保存されたものが出る。取り終わるのを待っているうちに、別の項目に移っていたら、その項目の取得が始まる）。"""
        if self._current is not None:
            self._show(self._current)

    def _prepare_media(self, cfg: dict, record: dict | None) -> str:
        """保存してある画像・動画を、詳細に出せる形にする。静止画は HTML の <img>（QTextDocument に登録）、GIF は動き、動画はボタン。"""
        self._set_clip(None, "")
        if not record:
            return ""
        document = self._detail.document()
        sources: dict[str, str] = {}
        self._media_files = {}
        clip_path, clip_is_video = None, False
        for media in (record.get("media") or [])[:6]:
            media_id = str(media.get("id") or "")
            path = rr.media_path(cfg, media_id)
            if path is None or not path.is_file():
                continue
            suffix = Path(media_id).suffix.lower()
            if media.get("role") in _STILL_ROLES and suffix not in _MOVIE_SUFFIXES + _VIDEO_SUFFIXES:
                image = QImage(str(path))
                if not image.isNull():
                    url = f"refmedia:{media_id}"
                    image = _sharp_scaled(image, rd.media_display_width(str(media.get("role")), self._detail.viewport().width()), self.devicePixelRatioF())
                    document.addResource(QTextDocument.ImageResource, QUrl(url), image)
                    sources[media_id] = url
                    self._media_files[media_id] = path
            elif media.get("role") == "clip" and clip_path is None and suffix in _MOVIE_SUFFIXES + _VIDEO_SUFFIXES:
                clip_path, clip_is_video = path, suffix in _VIDEO_SUFFIXES
        if clip_path is not None:
            self._set_clip(clip_path, "video" if clip_is_video else "movie")
        self._media_width = self._detail.viewport().width()
        return rd.media_html(record.get("media"), sources, width=self._media_width)

    def _set_clip(self, path: Path | None, mode: str) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        self._clip.clear()
        self._clip.setVisible(False)
        self._clip_box.setVisible(False)
        self._clip_btn.setVisible(False)
        self._clip_path = path
        if path is None:
            return
        if mode == "video":
            self._clip_btn.setVisible(True)
            self._clip_box.setVisible(True)
            return
        movie = QMovie(str(path))
        if not movie.isValid():
            return
        movie.jumpToFrame(0)
        native = movie.currentImage().size()
        self._movie = movie
        self._clip.setVisible(True)
        self._clip_box.setVisible(True)
        self._clip.show_movie(movie, native)
        movie.start()

    def _on_open_clip(self) -> None:
        path = getattr(self, "_clip_path", None)
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _references_for(self, item: dict) -> list[dict]:
        """保存してある HoudiniReference の項目から、関係するもの（通信はしない。取得は、説明を作るとき）。"""
        if self._reference_items is None:
            base_dir = str(self._cfg_getter().get("local_bridge_dir") or "")
            path = Path(base_dir) / "localRAG" / "reference" / ra.REFERENCE_CACHE_NAME if base_dir else None
            try:
                data = json.loads(path.read_text(encoding="utf-8")) if path else {}
                self._reference_items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
            except (OSError, ValueError, AttributeError):
                self._reference_items = []
        return rd.match_reference_items(self._reference_items, item.get("label", ""), item.get("kind", ""), aliases=rd.item_aliases(item), context=rd.item_context(item))

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
        item = (rd.find_item(kind, key) or next((i for i in rd.remote_items(kind, self._remote) if i["key"] == key), None)
                or rd.custom_item(kind, label or key.split("/")[-1]))
        for row, candidate in enumerate(self._items):
            if candidate["key"] == item["key"]:
                self._list.setCurrentRow(row)
                return
        self._show(item)

    SEARCH_KINDS = ("node", "vex", "shelf", "apex")

    def search_term(self, term: str) -> str:
        """用語で探す（Chat・Guide の文で、ダブルクリックした語。2026-11-25、A20）。ノード → VEX → シェルフ → APEX の順に、
        当たる種類を選んで、検索欄に入れる。当たりが 1 件なら、その説明を開く。戻り値: 画面に出す 1 文。"""
        term = " ".join(str(term or "").split()).strip("「」『』（）()[]、。,.:：")
        if not term:
            return "調べる語がありません"
        for kind in self.SEARCH_KINDS:
            if kind == "shelf":
                self._ensure_shelf_tools()
            hits = rd.search(kind, term, limit=50, extra=rd.remote_items(kind, self._remote))
            if not hits:
                continue
            self._set_kind_button(kind)
            self._kind = kind
            self._used_only.setChecked(False)
            self._search.setText(term)  # 一覧を絞る（_reload）
            if len(hits) == 1 or hits[0]["label"].lower() == term.lower():
                self.show_item(kind, hits[0]["key"], hits[0]["label"])
                return f"Reference で「{hits[0]['label']}」を開きました"
            return f"Reference で「{term}」を探しました（{len(hits)} 件）"
        return f"Reference に「{term}」は見つかりませんでした（Chat で聞くと、説明が出ます）"

    def _set_kind_button(self, kind: str) -> None:
        button = self._kind_buttons.get(kind)
        if button is not None:
            button.setChecked(True)

    # ── 操作 ─────────────────────────────────────────────────────────────────

    def _on_custom(self) -> None:
        if not self._author():
            return
        item = rd.custom_item(self._kind, self._search.text())
        if item["name"]:
            self._show(item)
            self._on_make()

    def _on_make(self) -> None:
        if not self._author():
            return  # 参加者は、作れない（Cloudflare の説明を読むだけ）
        if self._current is None or (self._worker is not None and self._worker.isRunning()):
            return
        item = self._current
        self._make_btn.setEnabled(False)
        self._status.setText(f"「{item['label']}」の説明を作っています（数秒〜十数秒）…")
        self._worker = _EntryWorker(self._cfg_getter(), self._complete_getter(), item)
        self._worker.done.connect(lambda entry, refs, usage, it=item: self._on_made(it, entry, refs, usage))
        self._worker.failed.connect(self._on_failed)
        _start_detached(self._worker)

    def _on_made(self, item: dict, entry: dict, references: list, usage: dict | None = None) -> None:
        self._reference_items = None  # 取得した HoudiniReference の保存を、次の表示で読み直す
        self._status.setText("説明を作りました（保存しました。次からは、すぐ出ます）" + self._cost_note(usage))
        if self._current is not None and self._current["key"] == item["key"]:
            self._show(item, entry)
        else:
            self._make_btn.setEnabled(self._current is not None)

    def _cost_note(self, usage: dict | None) -> str:
        """使ったトークンと、概算の費用（設定のモデルの単価。Worker の予算の減りと同じ数え方ではないので、目安）。"""
        usage = usage or {}
        tokens_in = int(usage.get("input_tokens", 0) or 0) + int(usage.get("cache_creation_input_tokens", 0) or 0) + int(usage.get("cache_read_input_tokens", 0) or 0)
        tokens_out = int(usage.get("output_tokens", 0) or 0)
        if not (tokens_in or tokens_out):
            return ""
        try:
            from tutorial_agent import usage_cost_for

            cost = usage_cost_for(str(self._cfg_getter().get("tutorial_model") or ""), usage)
        except Exception:  # noqa: BLE001
            cost = 0.0
        return f" / 使ったトークン: 入力 {tokens_in:,}・出力 {tokens_out:,}" + (f"（約 ${cost:.3f}）" if cost else "")

    def _on_failed(self, message: str) -> None:
        self._status.setText(message)
        self._make_btn.setEnabled(self._current is not None)

    def _on_open_doc(self) -> None:
        if self._current and str(self._current.get("doc_url") or "").startswith("https://"):
            QDesktopServices.openUrl(QUrl(self._current["doc_url"]))

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
        elif url.scheme() == "refopen":  # 画像を押した: 元の大きさの画像を、OS の画像ビューアで開く（縮めた画像の文字が読めないとき）
            path = self._media_files.get(url.toString()[len("refopen:"):])
            if path is not None and Path(path).is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif url.scheme() == "step":  # このチュートリアルで使っている場所 → Guide のその手順へ
            try:
                index = int(url.path() or url.host())
            except ValueError:
                return
            self._status.setText(open_guide_step(self, index))


def open_guide_step(source: QWidget, index: int) -> str:
    """Guide タブへ切り替えて、指定の手順（0 始まり）を開く。戻り値: 画面に出す 1 文。"""
    try:
        import guide_view

        other = panel_bus.route(source, guide_view.GuideWidget, panel_bus.enabled())  # 別のパネルが見えていれば、そちらの Guide を開く
        host = guide_view.locate_in_tabs(other if other is not None else source)
        if host is None:
            return "Guide タブが見つかりません"
        tabs = host[0]
        guide = other if other is not None else guide_view._guide_in(tabs)
        if guide is None or not guide.goto_step(index):
            return "Guide に、その手順がありません（チュートリアルを読み込み直したかもしれません）"
        tabs.setCurrentIndex(tabs.indexOf(_page_of(tabs, guide)))
        return f"{'別のパネルの ' if other is not None else ''}Guide の手順 {index + 1} を開きました"
    except Exception as exc:  # noqa: BLE001
        return f"Guide を開けませんでした（{exc}）"


def open_item_for_step(source: QWidget, step: dict) -> str:
    """Guide の手順のノードを、Reference タブで開く。戻り値: 画面に出す 1 文（Reference タブが無いときは、その旨）。"""
    node_type = str((step or {}).get("node_type") or "")
    if not node_type:
        return "この手順には、説明するノードがありません"
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
    if hit:
        return open_item(source, hit["kind"], hit["key"], hit["label"], label)

    def remote_hit(widget):  # 一覧データに無い項目（Mountain など）。公開済みなら、その項目を開く
        return next((i for i in rd.remote_items("node", widget._remote) + rd.remote_items("apex", widget._remote) if i["name"].lower() == base), None)

    return open_item(source, "node", f"node/{rd.slug(base)}", label, label, fallback=remote_hit)


def search_term(source: QWidget, term: str) -> str:
    """Reference タブへ切り替えて、用語で探す（A20。別のパネルの Reference が見えていれば、そちらで）。戻り値: 画面に出す 1 文。"""
    try:
        found = _reference_target(source)
        if found is None:
            return "Reference タブが見つかりません"
        tabs, widget, _other = found
        tabs.setCurrentIndex(tabs.indexOf(_page_of(tabs, widget)))
        return widget.search_term(term)
    except Exception as exc:  # noqa: BLE001
        return f"Reference で探せませんでした（{exc}）"


def _reference_target(source: QWidget):
    """開く Reference タブ（別のパネルの Reference が見えていれば、そちら）。戻り値: (タブ, ReferenceWidget, 別のパネルか) / None。"""
    import guide_view

    other = panel_bus.route(source, ReferenceWidget, panel_bus.enabled())
    host = guide_view.locate_in_tabs(other if other is not None else source)
    if host is None:
        return None
    tabs = host[0]
    widget = other if other is not None else tabs.findChild(ReferenceWidget)
    return None if widget is None else (tabs, widget, other is not None)


class TermLookup(QObject):
    """文の欄（QLabel・QTextBrowser）で、語をダブルクリックすると、その語を Reference で探す（A20）。
    ダブルクリックで選ばれた語（Qt の標準の選択）を使う。日本語は、続いた文字のまとまりが選ばれる（「Scatter」「ノード」など）。
    install(widget, on_message) で付ける。on_message は、結果の 1 文を受け取る（パネルの下の欄に出す）。"""

    def __init__(self, source: QWidget, on_message: Callable[[str], None] | None = None) -> None:
        super().__init__(source)
        self._source = source
        self._on_message = on_message

    @staticmethod
    def selected_text(widget) -> str:
        try:
            if hasattr(widget, "textCursor"):
                return widget.textCursor().selectedText()
            return widget.selectedText()
        except Exception:  # noqa: BLE001
            return ""

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.MouseButtonDblClick:
            target = watched.parent() if watched.objectName() == "qt_scrollarea_viewport" else watched
            QTimer.singleShot(0, lambda w=target: self._lookup(w))  # 標準の処理で語が選ばれてから読む
        return False

    def _lookup(self, widget) -> None:
        term = self.selected_text(widget).strip()
        if not term or len(term) > 40:
            return
        message = search_term(self._source, term)
        if self._on_message is not None:
            self._on_message(message)

    @classmethod
    def install(cls, widget: QWidget, on_message: Callable[[str], None] | None = None) -> "TermLookup":
        lookup = cls(widget, on_message)
        widget.installEventFilter(lookup)
        viewport = getattr(widget, "viewport", None)
        if callable(viewport):
            viewport().installEventFilter(lookup)
        return lookup


def open_item(source: QWidget, kind: str, key: str, label: str = "", shown: str = "", fallback: Callable | None = None) -> str:
    """Reference タブへ切り替えて、項目（kind・key）を開く（Guide の「ノードの説明」・チャットの回答の絵から。2026-11-25 に open_item_for_step から分けた）。
    別のパネルの Reference が見えていれば、そちらで開く。fallback(widget) は、開く前に、項目を選び直すとき（戻り値 None なら、そのまま）。
    戻り値: 画面に出す 1 文。"""
    try:
        found = _reference_target(source)  # 別のパネルが見えていれば、そちらの Reference を開く
        if found is None:
            return "Reference タブが見つかりません"
        tabs, widget, other = found
        hit = fallback(widget) if fallback is not None else None
        tabs.setCurrentIndex(tabs.indexOf(_page_of(tabs, widget)))
        if hit:
            widget.show_item(hit["kind"], hit["key"], hit["label"])
        else:
            widget.show_item(kind, key, label)
        return f"{'別のパネルの ' if other else ''}Reference タブで「{shown or label or key}」を開きました"
    except Exception as exc:  # noqa: BLE001
        return f"Reference タブを開けませんでした（{exc}）"


# ── チャットの回答に添える絵（2026-11-25）────────────────────────────────────

class _FigureWorker(QThread):
    """回答の文から、絵を添える項目を選び（chat_figures）、その画像を、Cloudflare から取って、端末に保存する。別スレッド。
    結果: [{"kind", "key", "title", "images": [(役割, ファイルのパス), ...]}, ...]（画像の取れた項目だけ）。"""

    done = Signal(object)

    def __init__(self, cfg: dict, text: str, shelf_labels: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self._cfg, self._text, self._shelf_labels = dict(cfg), str(text or ""), dict(shelf_labels or {})

    def run(self) -> None:
        import chat_figures

        out = []
        try:
            index = rr.fetch_index(self._cfg)
            for item in chat_figures.figure_items(self._text, index, shelf_labels=self._shelf_labels):
                meta = index.get(rr.index_key(item["kind"], item["key"])) or {}
                record = rr.fetch_entry(self._cfg, item["kind"], item["key"], meta.get("version"))
                images = []
                for media in chat_figures.pick_media((record or {}).get("media")):
                    path = rr.fetch_media(self._cfg, str(media["id"]))
                    if path is not None:
                        images.append((str(media.get("role") or ""), str(path)))
                if images:
                    out.append({**item, "images": images})
        except Exception:  # noqa: BLE001 -- 絵が取れなくても、回答は、そのまま読める
            out = out or []
        self.done.emit(out)


def _shelf_labels() -> dict[str, str]:
    """シェルフツールのキー → Houdini の表示名（Billowy Smoke など）。初めてのときは、Houdini から取る（メインスレッドで呼ぶ。hou を使うため）。"""
    if not rd.catalog("shelf"):
        rd.set_shelf_tools(rd.shelf_items(houdini_shelf_tools()))
    return {item["key"]: item["label"] for item in rd.catalog("shelf")}


class _ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ChatFigureStrip(QWidget):
    """チャットの回答の下に出す、Reference の絵の並び（2026-11-25。実証実験の意見「回答に図があったほうがいい」）。
    回答に出てくるノード・VEX 関数・シェルフツールのうち、撮影した画像があるもの（最大 3 件）。押すと、Reference タブで、その項目を開く。
    絵が 1 つも無いときは、何も出さない（隠れたまま）。message は、画面の下に出す 1 文（開いた・開けなかった）。"""

    message = Signal(str)
    PAIR_WIDTH = 150
    SINGLE_WIDTH = 240

    def __init__(self, cfg: dict, text: str, parent: QWidget | None = None, start: bool = True) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 2, 6, 2)
        self._layout.setSpacing(4)
        self.hide()
        if start:
            worker = _FigureWorker(cfg, text, _shelf_labels())
            worker.done.connect(self.show_figures)  # 画面が先に消えたら、Qt が、つなぎを外す（メソッドへのつなぎ）
            _start_detached(worker)

    def show_figures(self, figures: list) -> None:
        if not figures:
            return
        import chat_figures

        head = QLabel("図（Reference の撮影画像。押すと、Reference タブで開きます）")
        head.setStyleSheet("color:#94a3b8;font-size:11px;")
        head.setWordWrap(True)
        self._layout.addWidget(head)
        for figure in figures:
            title = QLabel(f"<b>{html.escape(str(figure['title']))}</b>（{chat_figures.KIND_LABELS.get(figure['kind'], figure['kind'])}）")
            title.setStyleSheet("color:#e2e8f0;font-size:12px;")
            self._layout.addWidget(title)
            row = QHBoxLayout()
            row.setSpacing(6)
            images = figure.get("images") or []
            width = self.PAIR_WIDTH if len(images) > 1 else self.SINGLE_WIDTH
            shown = 0
            for role, path in images:
                image = QImage(path)
                if image.isNull():
                    continue
                if shown:
                    arrow = QLabel("→")  # 適用前 → 適用後
                    arrow.setStyleSheet("color:#94a3b8;")
                    row.addWidget(arrow)
                shown += 1
                cell = QVBoxLayout()
                cell.setSpacing(1)
                picture = _ClickLabel()
                picture.setPixmap(QPixmap.fromImage(_sharp_scaled(image, width, self.devicePixelRatioF())))
                picture.setCursor(Qt.PointingHandCursor)
                picture.setToolTip("Reference タブで開く")
                picture.clicked.connect(lambda f=figure: self._open(f))
                cell.addWidget(picture)
                caption = QLabel(chat_figures.ROLE_LABELS.get(role, role))
                caption.setStyleSheet("color:#94a3b8;font-size:10px;")
                cell.addWidget(caption)
                row.addLayout(cell)
            row.addStretch()
            self._layout.addLayout(row)
        self.show()

    def _open(self, figure: dict) -> None:
        self.message.emit(open_item(self, figure["kind"], figure["key"], figure["title"]))


def _page_of(tabs, widget: QWidget) -> QWidget:
    """tabs の中で、widget を含むページ（タブに登録されているウィジェット）。"""
    node = widget
    while node is not None and tabs.indexOf(node) < 0:
        node = node.parentWidget()
    return node if node is not None else widget
