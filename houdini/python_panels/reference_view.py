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

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Callable

import reference_data as rd
import reference_remote as rr
from panel_actions import button_qss, px, type_font, type_qss
from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QMovie, QTextDocument
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
_INDEX_REFRESH_SECONDS = 60
_STILL_ROLES = ("before", "after", "node")
_MOVIE_SUFFIXES = (".gif", ".webp")
_VIDEO_SUFFIXES = (".webm", ".mp4")


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


class _IndexWorker(QThread):
    """Cloudflare の、説明のある項目の一覧（版つき）を取る。別スレッド。"""

    done = Signal(object)

    def __init__(self, cfg: dict, force: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._cfg, self._force = dict(cfg), force

    def run(self) -> None:
        try:
            self.done.emit(rr.fetch_index(self._cfg, force=self._force))
        except Exception:  # noqa: BLE001
            self.done.emit({})


class _EntryFetchWorker(QThread):
    """1 項目の説明と、その画像・動画を、Cloudflare から取って、端末に保存する。別スレッド。"""

    done = Signal(object, object)   # (説明の記録 dict または None, {メディアの id: 保存したパス})

    def __init__(self, cfg: dict, item: dict, version: int | None, parent=None) -> None:
        super().__init__(parent)
        self._cfg, self._item, self._version = dict(cfg), dict(item), version

    def run(self) -> None:
        paths: dict[str, str] = {}
        record = None
        try:
            record = rr.fetch_entry(self._cfg, self._item["kind"], self._item["key"], self._version)
            for media in ((record or {}).get("media") or [])[:6]:
                path = rr.fetch_media(self._cfg, str(media.get("id") or ""))
                if path is not None:
                    paths[str(media["id"])] = str(path)
        except Exception:  # noqa: BLE001
            pass
        self.done.emit(record, paths)


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
            references = rd.match_reference_items(fetch_reference_items(base_dir), label, self._item.get("kind", ""))
            docs = self._fetch_docs(label)
            system, user = rd.build_prompt(self._item.get("kind", ""), label, docs, references)
            # 短い要約なので、出力の上限と思考の深さを抑える（費用と時間を、減らす）
            text, usage = self._complete(system, user, max_tokens=rd.REFERENCE_MAX_TOKENS, effort=rd.REFERENCE_EFFORT)
            entry = rd.parse_entry(text)
            if entry is None:
                self.failed.emit("AI の返事を読み取れませんでした。もう一度、「説明を作る」を押してください")
                return
            if base_dir:
                rd.save_entry(base_dir, self._item["kind"], self._item["key"], entry,
                              {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "docs_found": len(docs), "references": len(references)})
            self.done.emit(entry, references, usage or {})
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
        self._remote: dict[str, dict] = rr.load_cached_index(self._cfg_getter() or {})  # Cloudflare にある説明の一覧（保存してあるもの。最新は、タブを開いたときに取る）
        self._index_worker: _IndexWorker | None = None
        self._index_at = 0.0
        self._fetch_worker: _EntryFetchWorker | None = None
        self._fetch_tried: set[tuple[str, str, int]] = set()
        self._movie: QMovie | None = None
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
        self._described_only = QCheckBox("説明のあるものだけ")
        self._described_only.setChecked(not self._author())  # 開発者は、説明の無いものも見て、作る
        self._described_only.setToolTip("Cloudflare に、説明が置いてある項目だけを、一覧に出します（通信できないときは、全部）")
        self._described_only.toggled.connect(self._reload)
        self._create_custom = QPushButton("この名前で作る")
        self._create_custom.setToolTip("一覧に無い名前（シェルフツールなど）を、この名前で、公式ドキュメントから探して説明を作ります")
        self._create_custom.clicked.connect(self._on_custom)
        self._create_custom.setVisible(False)
        row.addWidget(self._used_only)
        row.addWidget(self._described_only)
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
        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(px(4))
        detail_layout.addWidget(self._detail, stretch=1)
        self._clip = QLabel()  # 適用の動き（GIF）。あるときだけ出す
        self._clip.setAlignment(Qt.AlignCenter)
        self._clip.setVisible(False)
        detail_layout.addWidget(self._clip)
        self._clip_btn = QPushButton("適用の動画を開く")
        self._clip_btn.setVisible(False)
        self._clip_btn.clicked.connect(self._on_open_clip)
        detail_layout.addWidget(self._clip_btn)
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
        self._refresh_index()
        self._reload()

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
        self._index_worker = _IndexWorker(self._cfg_getter() or {}, force=force, parent=self)
        self._index_worker.done.connect(self._on_index)
        self._index_worker.start()

    def _on_index(self, index: dict) -> None:
        if not isinstance(index, dict) or not index:
            return  # 取れなかった（保存したものを、そのまま使う）
        changed = index != self._remote
        self._remote = index
        if changed:
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

    def _reload(self, *_args) -> None:
        query = self._search.text()
        items = rd.search(self._kind, query, limit=100000, extra=rd.remote_items(self._kind, self._remote))  # 絞り込み（使ったもの・説明のあるもの）は、ここから後で行うので、先に切らない
        used_keys = self._used.get(self._kind, set())
        if self._used_only.isChecked():
            items = [i for i in items if i["key"] in used_keys]
        if self._described_only.isChecked() and self._remote:
            items = [i for i in items if rr.index_key(i["kind"], i["key"]) in self._remote]
        items.sort(key=lambda i: 0 if i["key"] in used_keys else 1)  # 使ったものを先頭に（並びの順は、そのまま）
        self._items = items[:_MAX_LIST]
        self._list.blockSignals(True)
        self._list.clear()
        for item in self._items:
            mark = _USED_MARK if item["key"] in used_keys else ""
            if item["kind"] in ("node", "apex"):
                ctx = f"  [{item['context'].upper()}]"
            elif item["kind"] == "shelf" and item.get("context"):
                ctx = f"  [{item['context']}]"
            else:
                ctx = ""
            row = QListWidgetItem(f"{mark}{item['label']}{ctx}")
            if mark:
                row.setToolTip("このチュートリアルで使いました")
            self._list.addItem(row)
        self._list.blockSignals(False)
        self._create_custom.setVisible(self._author() and bool(query.strip()) and (self._kind == "shelf" or not self._items))
        total = len(rd.catalog(self._kind))
        shown = len(self._items)
        used_n = len(used_keys)
        described_n = sum(1 for i in rd.catalog(self._kind) if rr.index_key(i["kind"], i["key"]) in self._remote)
        if self._kind == "shelf" and total == 0:
            self._status.setText("シェルフツールの一覧は、Houdini の中で開くと出ます")
        else:
            self._status.setText(f"{shown} 件を表示（全 {total} 件、説明あり {described_n} 件）" + (f" / このチュートリアルで使ったもの: {used_n} 件" if used_n else ""))
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
        cfg = self._cfg_getter() or {}
        base_dir = str(cfg.get("local_bridge_dir") or "")
        author = self._author()
        meta = self._remote.get(rr.index_key(item["kind"], item["key"]))
        record = None
        loading = False
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
            entry = (record or {}).get("entry")
        if entry is None and author and base_dir:
            entry = rd.load_entry(base_dir, item["kind"], item["key"])  # 開発者: 自分で作った（まだ公開していない）説明
        references = self._references_for(item)
        used = item["key"] in self._used.get(item["kind"], set())
        steps = rd.used_steps(self._guide(), item.get("kind", ""), item.get("key", ""))
        media_block = self._prepare_media(cfg, record)
        self._detail.setHtml(rd.entry_html(item, entry, references, used, steps, media=media_block, author=author, loading=loading))
        self._make_btn.setEnabled(self._worker is None or not self._worker.isRunning())
        self._make_btn.setText("説明を作り直す" if entry else "説明を作る")
        self._doc_btn.setEnabled(bool(item.get("doc_url")))

    def _start_fetch(self, item: dict, version: int) -> None:
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        self._fetch_tried.add((item["kind"], item["key"], version))  # 取れなくても、同じ版で何度も取りに行かない（このセッションでは）
        self._fetch_worker = _EntryFetchWorker(self._cfg_getter() or {}, item, version, parent=self)
        self._fetch_worker.done.connect(lambda record, paths, it=item: self._on_fetched(it, record))
        self._fetch_worker.start()

    def _on_fetched(self, item: dict, record: dict | None) -> None:
        if self._current is not None and self._current["key"] == item["key"] and self._current["kind"] == item["kind"]:
            self._show(item)  # 保存されたので、表示し直す
        elif record is None:
            self._status.setText("説明を取得できませんでした（通信を確かめてください）")

    def _prepare_media(self, cfg: dict, record: dict | None) -> str:
        """保存してある画像・動画を、詳細に出せる形にする。静止画は HTML の <img>（QTextDocument に登録）、GIF は動き、動画はボタン。"""
        self._set_clip(None, "")
        if not record:
            return ""
        document = self._detail.document()
        sources: dict[str, str] = {}
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
                    document.addResource(QTextDocument.ImageResource, QUrl(url), image)
                    sources[media_id] = url
            elif media.get("role") == "clip" and clip_path is None and suffix in _MOVIE_SUFFIXES + _VIDEO_SUFFIXES:
                clip_path, clip_is_video = path, suffix in _VIDEO_SUFFIXES
        if clip_path is not None:
            self._set_clip(clip_path, "video" if clip_is_video else "movie")
        return rd.media_html(record.get("media"), sources)

    def _set_clip(self, path: Path | None, mode: str) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        self._clip.clear()
        self._clip.setVisible(False)
        self._clip_btn.setVisible(False)
        self._clip_path = path
        if path is None:
            return
        if mode == "video":
            self._clip_btn.setVisible(True)
            return
        movie = QMovie(str(path))
        if not movie.isValid():
            return
        movie.jumpToFrame(0)
        size = movie.currentImage().size()
        if size.width() > 0:
            width = min(px(420), size.width())
            movie.setScaledSize(size.scaled(width, width * 10, Qt.KeepAspectRatio))
        self._movie = movie
        self._clip.setMovie(movie)
        self._clip.setVisible(True)
        movie.start()

    def _on_open_clip(self) -> None:
        path = getattr(self, "_clip_path", None)
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

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
        self._worker = _EntryWorker(self._cfg_getter(), self._complete_getter(), item, self)
        self._worker.done.connect(lambda entry, refs, usage, it=item: self._on_made(it, entry, refs, usage))
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

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

        host = guide_view.locate_in_tabs(source)
        if host is None:
            return "Guide タブが見つかりません"
        tabs = host[0]
        guide = guide_view._guide_in(tabs)
        if guide is None or not guide.goto_step(index):
            return "Guide に、その手順がありません（チュートリアルを読み込み直したかもしれません）"
        tabs.setCurrentIndex(tabs.indexOf(_page_of(tabs, guide)))
        return f"Guide の手順 {index + 1} を開きました"
    except Exception as exc:  # noqa: BLE001
        return f"Guide を開けませんでした（{exc}）"


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
