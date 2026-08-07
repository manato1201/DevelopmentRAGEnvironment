"""
knowledge_manager.py — ナレッジ登録・更新マネージャー（Local RAG）

「ITリテラシーがなくても誰でもナレッジを育てられる」ための裏方モジュール。
rag_local_bridge.py の /api/knowledge/* エンドポイントから呼ばれる。

できること:
  登録: URL取り込み / ファイル(PDF・Word・Excel・PPT等) / FAQ手入力 /
        Q&A CSV一括 / YouTube字幕
  更新: 登録URLの定期クロール（差分のみ更新）/ 手動の今すぐ更新
  管理: 更新履歴（ジャーナル）/ ロールバック（直前の学習をなしにする）

データ配置:
  localRAG/<namespace>/_imported/   ← 取り込んだ Markdown（vault の一部として検索対象）
  data/knowledge/sources.json       ← 定期クロール対象のURL一覧
  data/knowledge/journal.json       ← 操作履歴（ロールバックの根拠）
  data/knowledge/backups/<op_id>/   ← 上書き前のバックアップ
  data/knowledge/uploads/           ← アップロードされた元ファイルの控え

ファイル変換は markitdown[all]（既存依存）を使う。YouTube URL も markitdown が
字幕を取得して Markdown 化してくれる。
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import os
import re
import secrets
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
from pep import RAGPolicyEnforcementPoint

# ナレッジ登録・更新で書き込みを許可する namespace の一覧。pep.py を正とする
# （auth_manager.VALID_NAMESPACES と同じ導出元）。書式チェックだけでは
# "my_made_up_ns" のような未知の namespace も通ってしまうため、既知の
# 一覧との突き合わせを行う。
_VALID_NAMESPACES = frozenset(RAGPolicyEnforcementPoint.NAMESPACE_PERMISSIONS.keys())
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

# ファイル名に使えない文字を除去した短いスラッグを作る
def _slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\-ぁ-んァ-ヶ一-龠]", "_", (text or "").strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] or "untitled"


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class KnowledgeError(Exception):
    """利用者にそのまま見せられる日本語メッセージを持つエラー。"""


class KnowledgeManager:
    def __init__(self, rag_service=None):
        self.rag_service = rag_service
        self.vault_dir = Path(os.environ.get("SOURCE_DIR") or (_REPO_ROOT / "localRAG")).resolve()
        self.processed_dir = os.environ.get("PROCESSED_DIR") or str(
            self.vault_dir / "_rag_dashboard" / ".processed"
        )
        self.data_dir = _REPO_ROOT / "data" / "knowledge"
        self.backup_dir = self.data_dir / "backups"
        self.upload_dir = self.data_dir / "uploads"
        for d in (self.data_dir, self.backup_dir, self.upload_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.sources_path = self.data_dir / "sources.json"
        self.journal_path = self.data_dir / "journal.json"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # 永続化ヘルパー                                                        #
    # ------------------------------------------------------------------ #

    def _load_json(self, path: Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return default

    def _save_json(self, path: Path, data) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _sources(self) -> list[dict]:
        return self._load_json(self.sources_path, [])

    def _journal(self) -> list[dict]:
        return self._load_json(self.journal_path, [])

    @staticmethod
    def _new_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)

    # ------------------------------------------------------------------ #
    # 変換（markitdown）                                                    #
    # ------------------------------------------------------------------ #

    def _convert_url(self, url: str) -> tuple[str, str]:
        """URL（Webページ/YouTube）を (title, markdown) に変換する。"""
        if not re.match(r"^https?://", url or ""):
            raise KnowledgeError("URLは http:// または https:// で始まる必要があります")
        try:
            import markitdown
            result = markitdown.MarkItDown().convert(url)
        except Exception as e:
            raise KnowledgeError(f"URLの取り込みに失敗しました: {e}")
        text = (result.markdown or "").replace("\x00", "").strip()
        if not text:
            raise KnowledgeError("ページからテキストを抽出できませんでした")
        title = (getattr(result, "title", None) or "").strip() or url
        return title, text

    def _convert_file(self, path: Path) -> str:
        try:
            import markitdown
            result = markitdown.MarkItDown().convert(str(path))
        except Exception as e:
            raise KnowledgeError(f"ファイルの変換に失敗しました（{path.name}）: {e}")
        text = (result.markdown or "").replace("\x00", "").strip()
        if not text:
            raise KnowledgeError(f"ファイルからテキストを抽出できませんでした（{path.name}）")
        return text

    # ------------------------------------------------------------------ #
    # vault への書き込みとインデックス                                       #
    # ------------------------------------------------------------------ #

    def _write_doc(self, namespace: str, filename: str, title: str,
                   body_md: str, source: str, op_id: str, op_type: str) -> Path:
        out_dir = self.vault_dir / namespace / "_imported"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        frontmatter = (
            "---\n"
            f"source: {source}\n"
            f"import_type: {op_type}\n"
            f"op_id: {op_id}\n"
            f"created: {datetime.date.today().isoformat()}\n"
            "status: active\n"
            "---\n\n"
        )
        if not body_md.lstrip().startswith("#"):
            body_md = f"# {title}\n\n{body_md}"
        out_path.write_text(frontmatter + body_md, encoding="utf-8")
        return out_path

    def _index(self) -> int:
        """差分インデックスを実行し、追加チャンク数を返す。"""
        if self.rag_service is None:
            return 0
        result = self.rag_service.index_documents(
            str(self.vault_dir), self.processed_dir, incremental=True
        )
        if not result.get("success"):
            raise KnowledgeError(f"インデックス化に失敗しました: {result.get('error', '不明')}")
        return int(result.get("document_count", 0))

    def _record_op(self, op_type: str, namespace: str, title: str,
                   created: list[Path], updated: list[dict], chunks: int,
                   op_id: str | None = None) -> dict:
        op = {
            "op_id": op_id or self._new_id(),
            "type": op_type,
            "timestamp": _now_iso(),
            "namespace": namespace,
            "title": title,
            "created": [str(p) for p in created],
            "updated": updated,          # [{"path": ..., "backup": ...}]
            "chunks": chunks,
            "status": "done",
        }
        journal = self._journal()
        journal.append(op)
        self._save_json(self.journal_path, journal[-500:])  # 直近500件まで保持
        return op

    def _check_namespace(self, namespace: str) -> str:
        ns = (namespace or "").strip()
        if not re.fullmatch(r"[\w\-]+", ns or ""):
            raise KnowledgeError("保存先（namespace）を選択してください")
        if ns not in _VALID_NAMESPACES:
            raise KnowledgeError(f"このnamespaceは使用できません: {ns}")
        return ns

    # ------------------------------------------------------------------ #
    # 登録系オペレーション                                                   #
    # ------------------------------------------------------------------ #

    def import_url(self, url: str, namespace: str) -> dict:
        """WebページのURLを取り込んで検索可能にする。"""
        ns = self._check_namespace(namespace)
        with self._lock:
            op_id = self._new_id()
            title, md = self._convert_url(url)
            fname = f"url_{_slug(title)}_{op_id}.md"
            path = self._write_doc(ns, fname, title, md, url, op_id, "url")
            chunks = self._index()
            return self._record_op("url", ns, title, [path], [], chunks, op_id)

    def import_youtube(self, url: str, namespace: str, transcript: str | None = None) -> dict:
        """
        YouTube動画の字幕を取り込んで検索可能にする。

        字幕（公式・自動生成）が無い動画は markitdown 単体では取り込めない
        （scripts/youtube_transcribe.py で音声からGemini/Whisperで文字起こしした
        テキストを取得できる）。transcript を渡した場合はmarkitdownでの字幕取得を
        スキップし、そのテキストをそのまま登録する。
        """
        if "youtube.com" not in (url or "") and "youtu.be" not in (url or ""):
            raise KnowledgeError("YouTubeのURLを入力してください（例: https://www.youtube.com/watch?v=...）")
        ns = self._check_namespace(namespace)
        with self._lock:
            op_id = self._new_id()
            transcript = (transcript or "").strip()
            if transcript:
                title, md = url, transcript
            else:
                try:
                    title, md = self._convert_url(url)
                except KnowledgeError as e:
                    raise KnowledgeError(
                        f"{e} — 字幕が無効になっている動画は取り込めません。"
                        "scripts/youtube_transcribe.py で音声から文字起こしし、"
                        "transcriptとして渡すことで取り込めます。"
                    )
            fname = f"youtube_{_slug(title)}_{op_id}.md"
            path = self._write_doc(ns, fname, title, md, url, op_id, "youtube")
            chunks = self._index()
            return self._record_op("youtube", ns, title, [path], [], chunks, op_id)

    def import_file_bytes(self, filename: str, data: bytes, namespace: str) -> dict:
        """アップロードされたファイル（PDF/Word/Excel/PPT/テキスト等）を取り込む。"""
        ns = self._check_namespace(namespace)
        if not data:
            raise KnowledgeError("ファイルの中身が空です")
        if len(data) > 50 * 1024 * 1024:
            raise KnowledgeError("ファイルが大きすぎます（上限 50MB）")
        safe_name = _slug(Path(filename).stem) + Path(filename).suffix.lower()
        with self._lock:
            op_id = self._new_id()
            upload_path = self.upload_dir / f"{op_id}_{safe_name}"
            upload_path.write_bytes(data)
            md = self._convert_file(upload_path)
            title = Path(filename).stem
            fname = f"file_{_slug(title)}_{op_id}.md"
            path = self._write_doc(ns, fname, title, md, filename, op_id, "file")
            chunks = self._index()
            return self._record_op("file", ns, title, [path], [], chunks, op_id)

    def add_faq(self, question: str, answer: str, namespace: str) -> dict:
        """FAQを1件手入力で登録する。"""
        ns = self._check_namespace(namespace)
        q, a = (question or "").strip(), (answer or "").strip()
        if not q or not a:
            raise KnowledgeError("質問と回答の両方を入力してください")
        with self._lock:
            op_id = self._new_id()
            body = f"# Q: {q}\n\n**質問:** {q}\n\n**回答:** {a}\n"
            fname = f"faq_{_slug(q)}_{op_id}.md"
            path = self._write_doc(ns, fname, f"Q: {q}", body, "faq", op_id, "faq")
            chunks = self._index()
            return self._record_op("faq", ns, f"Q: {q[:60]}", [path], [], chunks, op_id)

    def import_qa_csv(self, csv_text: str, namespace: str) -> dict:
        """Question,Answer 形式のCSVを一括登録する。1行=1FAQ。"""
        ns = self._check_namespace(namespace)
        if not (csv_text or "").strip():
            raise KnowledgeError("CSVの中身が空です")
        rows = list(csv.reader(io.StringIO(csv_text)))
        if not rows:
            raise KnowledgeError("CSVを読み取れませんでした")

        # ヘッダー検出: 1行目に question/answer（または 質問/回答）が含まれるか
        header = [c.strip().lower() for c in rows[0]]
        q_idx, a_idx, start = 0, 1, 0
        for i, col in enumerate(header):
            if col in ("question", "質問", "q"):
                q_idx = i
            if col in ("answer", "回答", "a"):
                a_idx = i
        if any(c in ("question", "質問", "q", "answer", "回答", "a") for c in header):
            start = 1
        if q_idx == a_idx:
            a_idx = q_idx + 1

        pairs = []
        for row in rows[start:]:
            if len(row) <= max(q_idx, a_idx):
                continue
            q, a = row[q_idx].strip(), row[a_idx].strip()
            if q and a:
                pairs.append((q, a))
        if not pairs:
            raise KnowledgeError(
                "有効なQ&A行が見つかりませんでした。1列目=質問、2列目=回答のCSVを用意してください"
            )
        if len(pairs) > 1000:
            raise KnowledgeError("一度に登録できるのは1000行までです")

        with self._lock:
            op_id = self._new_id()
            created = []
            for i, (q, a) in enumerate(pairs):
                body = f"# Q: {q}\n\n**質問:** {q}\n\n**回答:** {a}\n"
                fname = f"faq_{op_id}_{i:04d}_{_slug(q, 24)}.md"
                created.append(self._write_doc(ns, fname, f"Q: {q}", body, "qa_csv", op_id, "qa_csv"))
            chunks = self._index()
            return self._record_op("qa_csv", ns, f"Q&A CSV {len(pairs)}件", created, [], chunks, op_id)

    # ------------------------------------------------------------------ #
    # 定期クロール（登録URLの自動更新）                                       #
    # ------------------------------------------------------------------ #

    def list_sources(self) -> list[dict]:
        return self._sources()

    def add_source(self, url: str, namespace: str, interval_hours: int = 24) -> dict:
        """定期クロール対象のURLを登録する（初回の取り込みも行う）。"""
        ns = self._check_namespace(namespace)
        interval = max(1, min(int(interval_hours or 24), 24 * 30))
        sources = self._sources()
        if any(s["url"] == url and s["namespace"] == ns for s in sources):
            raise KnowledgeError("このURLは既に登録されています")
        src = {
            "id": self._new_id(),
            "url": url,
            "namespace": ns,
            "interval_hours": interval,
            "enabled": True,
            "last_crawled": None,
            "content_hash": None,
            "file": None,
            "title": url,
        }
        sources.append(src)
        self._save_json(self.sources_path, sources)
        # 初回取り込み
        self.crawl_source(src["id"])
        return [s for s in self._sources() if s["id"] == src["id"]][0]

    def delete_source(self, source_id: str) -> bool:
        sources = self._sources()
        remaining = [s for s in sources if s["id"] != source_id]
        if len(remaining) == len(sources):
            return False
        self._save_json(self.sources_path, remaining)
        return True

    def crawl_source(self, source_id: str) -> dict | None:
        """1つのURLソースをクロールし、内容が変わっていたら更新する。"""
        sources = self._sources()
        src = next((s for s in sources if s["id"] == source_id), None)
        if src is None:
            raise KnowledgeError("登録URLが見つかりません")

        title, md = self._convert_url(src["url"])
        content_hash = hashlib.sha256(md.encode("utf-8")).hexdigest()

        op = None
        with self._lock:
            src_list = self._sources()
            src = next((s for s in src_list if s["id"] == source_id), None)
            if src is None:
                return None
            if src.get("content_hash") == content_hash:
                # 変更なし → last_crawled だけ更新
                src["last_crawled"] = _now_iso()
                self._save_json(self.sources_path, src_list)
                return None

            op_id = self._new_id()
            old_file = Path(src["file"]) if src.get("file") else None
            if old_file and old_file.exists():
                # 差分更新: 旧内容をバックアップして同じファイルに上書き
                backup = self.backup_dir / op_id / old_file.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text(old_file.read_text(encoding="utf-8"), encoding="utf-8")
                self._write_doc(src["namespace"], old_file.name, title, md,
                                src["url"], op_id, "crawl_update")
                chunks = self._index()
                op = self._record_op("crawl_update", src["namespace"], title, [],
                                     [{"path": str(old_file), "backup": str(backup)}],
                                     chunks, op_id)
            else:
                # 初回取り込み
                fname = f"crawl_{_slug(title)}_{op_id}.md"
                path = self._write_doc(src["namespace"], fname, title, md,
                                       src["url"], op_id, "crawl")
                chunks = self._index()
                op = self._record_op("crawl", src["namespace"], title, [path], [], chunks, op_id)
                src["file"] = str(path)

            src["title"] = title
            src["content_hash"] = content_hash
            src["last_crawled"] = _now_iso()
            self._save_json(self.sources_path, src_list)
        return op

    def crawl_due(self, force: bool = False) -> list[dict]:
        """期限が来た（または force=True で全）ソースをクロールする。"""
        results = []
        for src in self._sources():
            if not src.get("enabled", True):
                continue
            if not force and src.get("last_crawled"):
                try:
                    last = datetime.datetime.fromisoformat(src["last_crawled"])
                    due = last + datetime.timedelta(hours=src.get("interval_hours", 24))
                    if datetime.datetime.now() < due:
                        continue
                except ValueError:
                    pass
            try:
                op = self.crawl_source(src["id"])
                results.append({"id": src["id"], "url": src["url"],
                                "updated": op is not None,
                                "op_id": op["op_id"] if op else None})
            except Exception as e:
                results.append({"id": src["id"], "url": src["url"],
                                "updated": False, "error": str(e)})
        return results

    # ------------------------------------------------------------------ #
    # 更新履歴・ロールバック                                                 #
    # ------------------------------------------------------------------ #

    def history(self, limit: int = 50) -> list[dict]:
        journal = self._journal()
        return list(reversed(journal[-limit:]))

    def rollback(self, op_id: str | None = None) -> dict:
        """
        指定した操作（省略時は直前の操作）を取り消す。
        - 作成されたファイル → 削除し、ベクトルDBからも除去
        - 上書きされたファイル → バックアップから復元して再インデックス
        """
        with self._lock:
            journal = self._journal()
            if op_id:
                op = next((o for o in journal if o["op_id"] == op_id), None)
                if op is None:
                    raise KnowledgeError(f"操作が見つかりません: {op_id}")
            else:
                op = next((o for o in reversed(journal) if o["status"] == "done"), None)
                if op is None:
                    raise KnowledgeError("取り消せる操作がありません")
            if op["status"] != "done":
                raise KnowledgeError("この操作は既に取り消し済みです")

            registry = None
            if self.rag_service is not None:
                registry = self.rag_service.document_processor.load_file_registry(self.processed_dir)

            def _remove_from_index(path_str: str) -> None:
                if self.rag_service is not None:
                    self.rag_service.vector_database.delete_by_file_path(path_str)
                if registry is not None:
                    registry.pop(path_str, None)

            removed, restored, errors = [], [], []

            for path_str in op.get("created", []):
                try:
                    _remove_from_index(path_str)
                    p = Path(path_str)
                    if p.exists():
                        p.unlink()
                    removed.append(path_str)
                except Exception as e:
                    errors.append(f"{path_str}: {e}")

            for item in op.get("updated", []):
                try:
                    _remove_from_index(item["path"])
                    backup = Path(item["backup"])
                    if backup.exists():
                        Path(item["path"]).write_text(
                            backup.read_text(encoding="utf-8"), encoding="utf-8")
                        restored.append(item["path"])
                except Exception as e:
                    errors.append(f"{item['path']}: {e}")

            if registry is not None:
                self.rag_service.document_processor.save_file_registry(self.processed_dir, registry)

            # 復元したファイルを再インデックス
            if restored and self.rag_service is not None:
                self._index()

            # クロールソースが指していたファイルを消した場合は参照をリセット
            if removed:
                sources = self._sources()
                changed = False
                for src in sources:
                    if src.get("file") in removed:
                        src["file"] = None
                        src["content_hash"] = None
                        changed = True
                if changed:
                    self._save_json(self.sources_path, sources)

            op["status"] = "rolled_back"
            op["rolled_back_at"] = _now_iso()
            self._save_json(self.journal_path, journal)

            return {
                "op_id": op["op_id"],
                "removed": len(removed),
                "restored": len(restored),
                "errors": errors,
            }
