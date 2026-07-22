#!/usr/bin/env python3
"""
rag_local_bridge.py — Local RAG HTTP Bridge（認証・アクセス制御対応版）

RAGService（このリポジトリ内で完結する検索エンジン）+ Claude API を
Unity/Houdini 向け HTTP API として公開する薄いブリッジ。
外部リポジトリ（mcp-rag-server）への依存はなし。

Usage:
    python scripts/rag_local_bridge.py [--port 8766]

Env:
    ANTHROPIC_API_KEY  必須（.env 非使用）

認証:
    全エンドポイント（/health, /admin, /ui を除く）は X-API-Key ヘッダーが必要。
    管理者 API は is_admin=True のキーが必要。

    初回セットアップ:
        python scripts/auth_manager.py create-admin --name "Admin"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ─── デフォルト設定 ─────────────────────────────────────────────────────────────
DEFAULT_PORT    = 8766
# 完成条件の目標応答速度（Claude/Gemini呼び出し込み）を超えたらコンソールに警告を出す
_LATENCY_WARN_MS = int(os.environ.get("RAG_LATENCY_WARN_MS", "15000"))
GRAPH_EXPORT_SCRIPT = Path(__file__).parent / "rag_graph_export.py"
CLAUDE_MODEL    = "claude-haiku-4-5-20251001"
GEMINI_MODEL    = "gemini-2.5-flash"
_LLM_BACKEND: str = os.environ.get("RAG_LLM_BACKEND", "claude")  # "claude" | "gemini"
SYSTEM_PROMPT   = (
    "あなたはゲーム開発チームの知識ベースを持つ AI アシスタントです。"
    "日本語で簡潔に回答してください（目安: 400 文字以内）。"
    "重要な点のみ箇条書きでまとめてください。"
    "回答中で参照した情報は必ず [1][2] のように番号で明記してください。"
)

# namespace 権限チェックが必要な /api/knowledge/* パス
# （/crawl と /rollback は対象外 — 定期クロールは既存登録に対する更新のみ、
# ロールバックはjournal記録済みの操作を取り消すだけで新規書き込み先を選ばないため）
_NS_SCOPED_KNOWLEDGE_PATHS = {
    "/api/knowledge/import/url",
    "/api/knowledge/import/youtube",
    "/api/knowledge/import/file",
    "/api/knowledge/import/qa_csv",
    "/api/knowledge/faq",
    "/api/knowledge/sources",
}

# auth_manager をインポート（同ディレクトリにある）
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))
try:
    from auth_manager import AuthManager, VALID_NAMESPACES
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False
    print("[bridge] 警告: auth_manager が見つかりません。認証なしで動作します。", flush=True)

try:
    from audit_logger import RAGAuditLogger
    _AUDIT_AVAILABLE = True
except ImportError:
    _AUDIT_AVAILABLE = False

try:
    from pep import RAGPolicyEnforcementPoint
    _PEP_AVAILABLE = True
except ImportError:
    _PEP_AVAILABLE = False

try:
    from score_engine import UnderstandingScoreEngine
    _SCORE_AVAILABLE = True
except ImportError:
    _SCORE_AVAILABLE = False

try:
    from knowledge_manager import KnowledgeManager, KnowledgeError
    _KB_AVAILABLE = True
except ImportError:
    _KB_AVAILABLE = False

# static ファイルディレクトリ
_STATIC_DIR = _SCRIPTS_DIR / "static"

# PEP シングルトン（モジュールレベル）
_pep = RAGPolicyEnforcementPoint() if _PEP_AVAILABLE else None

# スコアエンジン シングルトン（モジュールレベル）
_score_engine = UnderstandingScoreEngine(Path(__file__).parent.parent / "data" / "auth.db") if _SCORE_AVAILABLE else None


def _score_label(result: dict) -> str:
    """
    検索ヒットのスコア表示ラベルを返す。
    RRF マージ後の similarity（≒0.016）を %表示すると誤解を招くため、
    ベクトル由来はコサイン類似度、BM25 のみ由来はキーワード一致と表示する。
    """
    vs = result.get("vector_similarity")
    if vs is not None:
        return f"類似度: {vs * 100:.2f}%"
    if result.get("bm25_score") is not None:
        return "キーワード一致"
    return f"類似度: {result.get('similarity', 0) * 100:.2f}%"


# ─── RAG クライアント ────────────────────────────────────────────────────────────
class LocalRAGClient:
    """
    RAGService を直接 import して呼び出すクライアント。

    以前は mcp-rag-server を別プロセス（stdio JSON-RPC 2.0）として起動して
    いたが、検索エンジン一式（document_processor / embedding_generator /
    vector_database / rag_service）をこのリポジトリに取り込んだことで、
    プロセス内で直接呼び出せるようになった。外部リポジトリへの依存はゼロ。

    search_structured() は構造化データ（ファイルパス・スコア種別・
    コンテキスト/全文フラグ付き）をそのまま返す。以前は事前に番号付き
    テキストへ整形してから namespace フィルタリングしていたが、フィルタ
    後に「歯抜けの [1][3] のような番号」が LLM に渡ってしまい、引用番号
    と実際のソース番号がずれるバグがあった。フィルタ確定後に番号を振る
    ことで、引用抽出（extractionRate）の整合性を保証している。
    """

    def __init__(self, server_dir: Path) -> None:
        self.server_dir = server_dir  # 互換性のため保持（_handle_graph 等で参照）
        self._rag_service = None
        self._lock = threading.Lock()

    def start(self) -> None:
        from rag_service import create_rag_service_from_env
        self._rag_service = create_rag_service_from_env()
        print("[bridge] RAGService 起動完了（ローカル直接呼び出し）", flush=True)

    def stop(self) -> None:
        self._rag_service = None

    def is_alive(self) -> bool:
        return self._rag_service is not None

    def search_structured(self, query: str, limit: int = 5) -> list[dict]:
        if self._rag_service is None:
            raise RuntimeError("RAGService が起動していません")
        with self._lock:
            if self._rag_service.get_document_count() == 0:
                return []
            return self._rag_service.search(query, limit, with_context=True, context_size=1)

    def get_document_count(self) -> int:
        if self._rag_service is None:
            return 0
        with self._lock:
            return self._rag_service.get_document_count()


# ─── namespace フィルタリング ────────────────────────────────────────────────────

def _extract_namespace_from_path(file_path: str) -> str | None:
    """
    ファイルパスから namespace を推定する。
    例: ".../localRAG/tool_docs/article.md" → "tool_docs"
    """
    parts = Path(file_path).parts
    for ns in VALID_NAMESPACES if _AUTH_AVAILABLE else []:
        if ns in parts:
            return ns
    return None


def _group_by_file(results: list[dict]) -> dict[str, list[dict]]:
    """検索結果をファイルパスごとにまとめ、チャンク順に並べる。"""
    groups: dict[str, list[dict]] = {}
    for r in results:
        groups.setdefault(r["file_path"], []).append(r)
    for fp in groups:
        groups[fp].sort(key=lambda x: x["chunk_index"])
    return groups


def _filter_groups_by_namespace(groups: dict[str, list[dict]], allowed: list[str]) -> dict[str, list[dict]]:
    """allowed namespaces でファイルグループを絞り込む。namespace 不明のファイルは通過させる。"""
    if not allowed:
        return {}
    out: dict[str, list[dict]] = {}
    for fp, items in groups.items():
        ns = _extract_namespace_from_path(fp)
        if ns is None or ns in allowed:
            out[fp] = items
    return out


def _build_context_and_sources(groups: dict[str, list[dict]], limit: int) -> tuple[list[str], list[dict]]:
    """
    namespace フィルタ確定後のファイルグループから、LLM に渡す番号付きコンテキストと
    同じ番号順のソースリストを組み立てる。両者のインデックス（1始まり）は必ず一致する。
    """
    items_by_file = list(groups.items())[:limit]
    if not items_by_file:
        return ["（関連ドキュメントが見つかりませんでした）"], []

    texts = [f"検索結果（{len(items_by_file)} 件）:"]
    sources: list[dict] = []

    for i, (file_path, chunks) in enumerate(items_by_file):
        file_name = os.path.basename(file_path)
        texts.append(f"\n[{i + 1}] ファイル: {file_name}")
        max_score: float | None = None
        saw_vector_hit = False
        for r in chunks:
            is_context = r.get("is_context", False)
            is_full_document = r.get("is_full_document", False)
            if is_full_document:
                texts.append(f"\n+++ ドキュメント全文（チャンク {r['chunk_index']}) +++\n{r['content']}")
            elif is_context:
                texts.append(f"\n--- 前後のコンテキスト（チャンク {r['chunk_index']}) ---\n{r['content']}")
            else:
                texts.append(
                    f"\n=== 検索ヒット（チャンク {r['chunk_index']}, {_score_label(r)}) ===\n{r['content']}"
                )
                vs = r.get("vector_similarity")
                if vs is not None:
                    saw_vector_hit = True
                    max_score = vs if max_score is None else max(max_score, vs)

        ns = _extract_namespace_from_path(file_path)
        sources.append({
            "title": file_name,
            "db": ns or "local",
            "score": round(max_score, 4) if max_score is not None else 0.0,
            "score_type": "vector" if saw_vector_hit else "keyword",
        })

    return texts, sources


def _parse_extraction(answer: str, total: int) -> tuple[int, list[bool]]:
    """回答中の [1][2] 形式の引用番号を解析し、(引用件数, 各ソースの引用有無) を返す。"""
    cited_nums: set[int] = set()
    for m in re.finditer(r"\[(\d+)\]", answer):
        n = int(m.group(1))
        if 1 <= n <= total:
            cited_nums.add(n)
    cited_flags = [(i + 1) in cited_nums for i in range(total)]
    return len(cited_nums), cited_flags


# ─── Claude API 呼び出し ─────────────────────────────────────────────────────────
def _call_claude(context_texts: list[str], query: str, history: list[dict]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "ANTHROPIC_API_KEY 環境変数が設定されていません。"

    context = "\n\n".join(context_texts) if context_texts else "（参考ドキュメントなし）"
    messages: list[dict] = [
        {"role": "user",      "content": f"以下の参考ドキュメントを確認しました。\n\n{context}"},
        {"role": "assistant", "content": "参考ドキュメントを確認しました。ご質問にお答えします。"},
    ]
    for h in history[-6:]:
        role = "assistant" if h.get("role") in ("bot", "assistant") else "user"
        text = h.get("text", h.get("content", ""))
        if text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": query})

    # 1024 だと箇条書きの長い回答が途中で切れる（引用番号を明記させる分、応答が長くなりやすい）
    payload = json.dumps({
        "model": CLAUDE_MODEL, "max_tokens": 2048,
        "system": SYSTEM_PROMPT, "messages": messages,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]


def _call_gemini(context_texts: list[str], query: str, history: list[dict]) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return "GEMINI_API_KEY 環境変数が設定されていません。"

    contents = []
    for h in history[-12:]:
        role = "user" if h.get("role") not in ("bot", "assistant") else "model"
        text = h.get("text", h.get("content", ""))
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})

    context = "\n\n".join(context_texts) if context_texts else "（参考ドキュメントなし）"
    user_msg = f"以下の参考ドキュメントを参照して質問に答えてください。\n\n{context}\n\n質問: {query}"
    contents.append({"role": "user", "parts": [{"text": user_msg}]})

    payload = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
    }, ensure_ascii=False).encode("utf-8")

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={api_key}")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["candidates"][0]["content"]["parts"][0]["text"]


# ─── 静的ファイル読み込み ────────────────────────────────────────────────────────

def _read_static(filename: str) -> bytes | None:
    path = _STATIC_DIR / filename
    if path.exists():
        return path.read_bytes()
    return None


# ─── HTTP ハンドラ ────────────────────────────────────────────────────────────────
class BridgeHandler(BaseHTTPRequestHandler):

    mcp:  LocalRAGClient   # start() 後にセット
    auth: "AuthManager | None" = None  # 認証マネージャー
    audit: "RAGAuditLogger | None" = None  # 監査ロガー
    kb:   "KnowledgeManager | None" = None  # ナレッジ登録・更新

    def log_message(self, fmt: str, *args) -> None:
        pass

    # ── 共通ユーティリティ ──────────────────────────────────────────────────────

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code: int, html: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _get_api_key(self) -> str:
        return self.headers.get("X-API-Key", "")

    def _authenticate(self) -> dict | None:
        """API キーを検証してユーザー dict を返す。認証不要時は None。"""
        if not _AUTH_AVAILABLE or self.auth is None:
            # 認証モジュールなし → 全アクセス許可（開発用）
            return {"id": "anonymous", "display_name": "Anonymous",
                    "allowed_namespaces": VALID_NAMESPACES if _AUTH_AVAILABLE else [],
                    "is_admin": True}
        key = self._get_api_key()
        return self.auth.validate_key(key)

    def _require_auth(self) -> dict | None:
        """認証必須。失敗時は 401 を返して None を返す。"""
        user = self._authenticate()
        if user is None:
            self._send_json(401, {"error": "認証が必要です。X-API-Key ヘッダーを設定してください。"})
        return user

    def _require_admin(self) -> dict | None:
        """管理者認証必須。失敗時は 403 を返して None を返す。"""
        user = self._require_auth()
        if user is None:
            return None
        if not user.get("is_admin"):
            self._send_json(403, {"error": "管理者権限が必要です。"})
            return None
        return user

    def _log(self, user: dict | None, endpoint: str, query: str = None,
             namespaces: list = None, status: int = 200) -> None:
        if self.auth:
            uid = user["id"] if user else None
            ip  = self.client_address[0]
            self.auth.log_access(uid, endpoint, query, namespaces, status, ip)

    # ── CORS プリフライト ────────────────────────────────────────────────────────
    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()

    # ── GET ─────────────────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        # 認証不要エンドポイント
        if path == "/health":
            self._handle_health()
            return
        if path == "/admin":
            html = _read_static("admin.html")
            if html:
                self._send_html(200, html)
            else:
                self._send_json(404, {"error": "admin.html not found"})
            return
        if path == "/ui":
            html = _read_static("user_ui.html")
            if html:
                self._send_html(200, html)
            else:
                self._send_json(404, {"error": "user_ui.html not found"})
            return

        # 認証必須エンドポイント
        if path == "/graph":
            user = self._require_auth()
            if user:
                self._handle_graph(user)
            return
        if path == "/api/me":
            user = self._require_auth()
            if user:
                safe = {k: v for k, v in user.items() if k != "api_key_hash"}
                self._send_json(200, safe)
            return
        if path == "/api/users":
            user = self._require_admin()
            if user:
                self._send_json(200, {"users": self.auth.list_users()})
            return
        if path == "/api/logs":
            user = self._require_admin()
            if user:
                logs = self.auth.get_logs(limit=200)
                self._send_json(200, {"logs": logs})
            return
        if path == "/api/namespaces":
            user = self._require_auth()
            if user:
                self._send_json(200, {
                    "all": VALID_NAMESPACES if _AUTH_AVAILABLE else [],
                    "allowed": user.get("allowed_namespaces", []),
                })
            return
        if path == "/api/llm-backend":
            self._send_json(200, {"backend": _LLM_BACKEND})
            return

        if path == "/api/knowledge/sources":
            user = self._require_auth()
            if user and self._kb_ready():
                self._send_json(200, {"sources": self.kb.list_sources()})
            return
        if path == "/api/knowledge/history":
            user = self._require_auth()
            if user and self._kb_ready():
                from urllib.parse import urlparse, parse_qs
                params = parse_qs(urlparse(self.path).query)
                limit = int(params.get("limit", [50])[0])
                self._send_json(200, {"history": self.kb.history(limit)})
            return

        if path == "/admin/audit":
            admin = self._require_admin()
            if admin is None:
                return
            if self.audit is None:
                self._send_json(503, {"error": "audit logger not available"})
                return
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(self.path).query)
            limit  = int(params.get("limit", [100])[0])
            records = self.audit.get_recent(limit)
            self._send_json(200, {"records": records, "count": len(records)})
            return

        if path.startswith("/api/score"):
            # GET /api/score?user_id=xxx  → 全スコア取得
            if _score_engine is None:
                self._send_json(503, {"error": "score engine not available"})
                return
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(self.path).query)
            uid = params.get("user_id", [""])[0]
            if not uid:
                self._send_json(400, {"error": "user_id required"})
                return
            scores = _score_engine.get_all_scores(uid)
            self._send_json(200, {"user_id": uid, "scores": scores})
            return

        self._send_json(404, {"error": "Not found"})

    def _handle_health(self) -> None:
        alive = self.mcp.is_alive()
        count = self.mcp.get_document_count() if alive else 0
        self._send_json(200 if alive else 503, {
            "status": "ok" if alive else "error",
            "server": "rag-service-local",
            "total_chunks": count,
            "auth_enabled": _AUTH_AVAILABLE and self.auth is not None,
        })

    def _handle_graph(self, user: dict) -> None:
        try:
            result = subprocess.run(
                ["uv", "run", "python", str(GRAPH_EXPORT_SCRIPT)],
                cwd=str(Path(__file__).parent.parent),
                capture_output=True, text=True, timeout=90,
            )
            if result.returncode != 0:
                self._send_json(500, {"status": "error", "message": result.stderr.strip()})
                return
            data = json.loads(result.stdout)
            # ユーザーの allowed_namespaces でノードをフィルタ
            allowed = user.get("allowed_namespaces", [])
            if allowed:
                data["nodes"] = [n for n in data.get("nodes", []) if n.get("db") in allowed]
                node_ids = {n["id"] for n in data["nodes"]}
                data["edges"] = [e for e in data.get("edges", [])
                                  if e["source"] in node_ids and e["target"] in node_ids]
            data["status"] = "ok"
            self._log(user, "/graph")
            self._send_json(200, data)
        except subprocess.TimeoutExpired:
            self._send_json(504, {"status": "error", "message": "graph export timed out"})
        except Exception as exc:
            self._send_json(500, {"status": "error", "message": str(exc)})

    # ── ナレッジ登録・更新 ────────────────────────────────────────────────────────

    def _kb_ready(self) -> bool:
        """KnowledgeManager が使えるか確認。使えなければ 503 を返す。"""
        if self.kb is None:
            self._send_json(503, {"error": "ナレッジ管理機能が利用できません（knowledge_manager 未初期化）"})
            return False
        return True

    def _check_ns_permission(self, user: dict, namespace: str) -> bool:
        """
        ユーザーが namespace への書き込み権限を持つか。持たなければ 403。
        admin は常に許可（PEPの admin ロールと同じ扱い）。admin 以外は
        allowed_namespaces が空、または対象 namespace を含まない場合は拒否する
        （fail-closed）。
        """
        if user.get("is_admin"):
            return True
        allowed = user.get("allowed_namespaces", [])
        if namespace not in allowed:
            self._send_json(403, {"error": f"このnamespaceへの権限がありません: {namespace}"})
            return False
        return True

    def _handle_knowledge_post(self, user: dict, path: str) -> None:
        if not self._kb_ready():
            return
        body = self._read_body()
        ns = body.get("namespace", "")

        if path in _NS_SCOPED_KNOWLEDGE_PATHS and not self._check_ns_permission(user, ns):
            return

        try:
            if path == "/api/knowledge/import/url":
                op = self.kb.import_url(body.get("url", ""), ns)
            elif path == "/api/knowledge/import/youtube":
                op = self.kb.import_youtube(body.get("url", ""), ns)
            elif path == "/api/knowledge/import/file":
                import base64
                data = base64.b64decode(body.get("data_base64", ""))
                op = self.kb.import_file_bytes(body.get("filename", "upload.txt"), data, ns)
            elif path == "/api/knowledge/import/qa_csv":
                op = self.kb.import_qa_csv(body.get("csv", ""), ns)
            elif path == "/api/knowledge/faq":
                op = self.kb.add_faq(body.get("question", ""), body.get("answer", ""), ns)
            elif path == "/api/knowledge/sources":
                op = self.kb.add_source(body.get("url", ""), ns,
                                        int(body.get("interval_hours", 24)))
            elif path == "/api/knowledge/crawl":
                source_id = body.get("source_id")
                if source_id:
                    op = self.kb.crawl_source(source_id)
                    op = {"results": [op] if op else [], "message": "更新しました" if op else "変更はありませんでした"}
                else:
                    results = self.kb.crawl_due(force=True)
                    op = {"results": results}
            elif path == "/api/knowledge/rollback":
                op = self.kb.rollback(body.get("op_id"))
            else:
                self._send_json(404, {"error": "Not found"})
                return

            self._log(user, path, body.get("url") or body.get("question"), [ns] if ns else None, 200)
            self._send_json(200, {"ok": True, "result": op})
        except KnowledgeError as e:
            self._log(user, path, None, [ns] if ns else None, 400)
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            self._log(user, path, None, [ns] if ns else None, 500)
            self._send_json(500, {"error": f"ナレッジ操作でエラーが発生しました: {e}"})

    # ── POST ─────────────────────────────────────────────────────────────────────
    def do_POST(self) -> None:
        path = self.path.split("?")[0]

        if path.startswith("/api/knowledge/"):
            user = self._require_auth()
            if user:
                self._handle_knowledge_post(user, path)
            return

        if path == "/query":
            user = self._require_auth()
            if user:
                self._handle_query(user)
            return

        if path == "/search":
            user = self._require_auth()
            if user:
                self._handle_search(user)
            return

        # 管理者 API
        if path == "/api/users":
            user = self._require_admin()
            if user:
                self._handle_create_user()
            return

        # /api/users/{id}/regenerate
        if path.startswith("/api/users/") and path.endswith("/regenerate"):
            user = self._require_admin()
            if user:
                target_id = path.split("/api/users/")[1].replace("/regenerate", "")
                new_key = self.auth.regenerate_key(target_id)
                if new_key:
                    self._send_json(200, {"api_key": new_key,
                                          "message": "このAPIキーは一度だけ表示されます。"})
                else:
                    self._send_json(404, {"error": "ユーザーが見つかりません"})
            return

        if path == "/api/llm-backend":
            global _LLM_BACKEND
            data = self._read_body()
            backend = data.get("backend", "claude")
            if backend not in ("claude", "gemini"):
                self._send_json(400, {"error": "backend must be 'claude' or 'gemini'"})
                return
            _LLM_BACKEND = backend
            self._send_json(200, {"backend": _LLM_BACKEND})
            return

        if path == "/api/score":
            # 理解度スコア更新エンドポイント
            # POST body: {"user_id": "xxx", "topic": "SOP", "success": true}
            # Returns: {"user_id": "xxx", "topic": "SOP", "new_score": 0.6, "query_context": {...}}
            if _score_engine is None:
                self._send_json(503, {"error": "score engine not available"})
                return
            data    = self._read_body()
            uid     = data.get("user_id", "")
            topic   = data.get("topic", "general")
            success = bool(data.get("success", True))
            if not uid:
                self._send_json(400, {"error": "user_id required"})
                return
            new_score = _score_engine.update_score(uid, topic, success)
            query_ctx = _score_engine.build_rag_query(uid, {"topic": topic, "query": data.get("query", "")})
            self._send_json(200, {"user_id": uid, "topic": topic, "new_score": new_score, "query_context": query_ctx})
            return

        self._send_json(404, {"error": "Not found"})

    def _handle_query(self, user: dict) -> None:
        body       = self._read_body()
        query: str = body.get("query", "").strip()
        history    = body.get("history", [])
        limit: int = int(body.get("limit", 5))

        if not query:
            self._send_json(400, {"error": "query は必須です"})
            return
        if not self.mcp.is_alive():
            self._send_json(503, {"error": "RAGService が起動していません"})
            return

        allowed = user.get("allowed_namespaces", [])

        # PEP: ロールに基づいて名前空間を絞り込む
        if _pep and user:
            user_role = "admin" if user.get("is_admin") else "developer"
            requested_ns = user.get("allowed_namespaces", [])
            effective_ns = _pep.filter_namespaces(user_role, requested_ns)
        else:
            effective_ns = allowed  # fallback: 元のまま

        t_start = time.time()

        try:
            if self.mcp.get_document_count() == 0:
                self._send_json(200, {
                    "answer": "インデックスにドキュメントが存在しません。"
                              "`uv run python scripts/rag_cli.py index` でドキュメントをインデックス化してください。",
                    "sources": [], "status": "ok", "namespaces": effective_ns,
                    "extractionRate": 0, "extractionDetail": "0/0",
                })
                return

            results = self.mcp.search_structured(query, limit * 3)  # 多めに取得してフィルタ
            groups  = _group_by_file(results)

            # namespace フィルタリング（PEP で絞り込まれた effective_ns を使用）
            if effective_ns:
                groups = _filter_groups_by_namespace(groups, effective_ns)

            texts, sources = _build_context_and_sources(groups, limit)

            if _LLM_BACKEND == "gemini":
                answer = _call_gemini(texts, query, history)
            else:
                answer = _call_claude(texts, query, history)

            cited_count, cited_flags = _parse_extraction(answer, len(sources))
            for src, cited in zip(sources, cited_flags):
                src["cited"] = cited
            extraction_rate = round(cited_count / len(sources) * 100) if sources else 0

            self._log(user, "/query", query, allowed, 200)
            if self.audit:
                self.audit.log({
                    "session_id":   user.get("id"),
                    "user_role":    "admin" if user.get("is_admin") else "user",
                    "action":       "search",
                    "namespace":    ",".join(allowed) if allowed else None,
                    "query":        query,
                    "result_count": len(sources),
                    "latency_ms":   int((time.time() - t_start) * 1000),
                    "allowed":      True,
                })
            self._send_json(200, {"answer": answer, "sources": sources,
                                  "status": "ok", "namespaces": effective_ns,
                                  "extractionRate": extraction_rate,
                                  "extractionDetail": f"{cited_count}/{len(sources)}"})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._log(user, "/query", query, allowed, 502)
            if self.audit:
                self.audit.log({
                    "session_id":   user.get("id"),
                    "user_role":    "admin" if user.get("is_admin") else "user",
                    "action":       "search",
                    "namespace":    ",".join(allowed) if allowed else None,
                    "query":        query,
                    "result_count": 0,
                    "latency_ms":   int((time.time() - t_start) * 1000),
                    "allowed":      False,
                })
            self._send_json(502, {"error": f"Claude API エラー: {detail}"})
        except Exception as exc:
            self._log(user, "/query", query, allowed, 500)
            self._send_json(500, {"error": str(exc)})

    def _handle_search(self, user: dict) -> None:
        """
        LLM を介さない生の RAG 検索。tutorial_agent（チュートリアル生成）が
        RAG コンテキストの取得に使う。

        body: {"query": str, "limit": int, "namespaces": ["houdini21", ...]}
        namespaces はホワイトリスト指定（省略時は namespace フィルタなし）。
        指定された場合はユーザーの allowed_namespaces との積集合に絞る。
        """
        body       = self._read_body()
        query: str = body.get("query", "").strip()
        limit: int = int(body.get("limit", 6))
        requested  = body.get("namespaces") or []

        if not query:
            self._send_json(400, {"error": "query は必須です"})
            return
        if not self.mcp.is_alive():
            self._send_json(503, {"error": "RAGService が起動していません"})
            return

        allowed = user.get("allowed_namespaces", [])
        try:
            results = self.mcp.search_structured(query, limit * 3)  # 多めに取得してフィルタ
            groups  = _group_by_file(results)
            if requested and _AUTH_AVAILABLE:
                effective = [ns for ns in requested if not allowed or ns in allowed]
                groups = _filter_groups_by_namespace(groups, effective)
            texts, sources = _build_context_and_sources(groups, limit)
            self._log(user, "/search", query, requested or allowed, 200)
            if self.audit:
                self.audit.log({
                    "session_id":   user.get("id"),
                    "user_role":    "admin" if user.get("is_admin") else "user",
                    "action":       "raw_search",
                    "namespace":    ",".join(requested) if requested else None,
                    "query":        query,
                    "result_count": len(sources),
                    "latency_ms":   0,
                    "allowed":      True,
                })
            self._send_json(200, {"texts": texts, "sources": sources, "status": "ok"})
        except Exception as exc:
            self._log(user, "/search", query, requested or allowed, 500)
            self._send_json(500, {"error": str(exc)})

    def _handle_create_user(self) -> None:
        body = self._read_body()
        name = body.get("display_name", "").strip()
        ns   = body.get("allowed_namespaces", [])
        is_admin = bool(body.get("is_admin", False))
        if not name:
            self._send_json(400, {"error": "display_name は必須です"})
            return
        try:
            uid, key = self.auth.create_user(name, ns, is_admin=is_admin)
            self._send_json(201, {"user_id": uid, "api_key": key,
                                  "message": "このAPIキーは一度だけ表示されます。"})
        except ValueError as e:
            self._send_json(400, {"error": str(e)})

    # ── DELETE / PUT ─────────────────────────────────────────────────────────────
    def do_DELETE(self) -> None:
        path = self.path.split("?")[0]
        if path.startswith("/api/knowledge/sources/"):
            user = self._require_auth()
            if user and self._kb_ready():
                source_id = path.split("/api/knowledge/sources/")[-1]
                ok = self.kb.delete_source(source_id)
                self._send_json(200 if ok else 404,
                                {"ok": ok, "message": "削除しました" if ok else "見つかりません"})
            return
        if path.startswith("/api/users/"):
            user = self._require_admin()
            if user:
                target_id = path.split("/api/users/")[-1]
                ok = self.auth.delete_user(target_id)
                self._send_json(200 if ok else 404,
                                {"ok": ok, "message": "削除しました" if ok else "見つかりません"})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_PUT(self) -> None:
        path = self.path.split("?")[0]
        if path.startswith("/api/users/"):
            user = self._require_admin()
            if user:
                target_id = path.split("/api/users/")[-1]
                body = self._read_body()
                if "allowed_namespaces" in body:
                    try:
                        self.auth.update_namespaces(target_id, body["allowed_namespaces"])
                    except ValueError as e:
                        self._send_json(400, {"error": str(e)})
                        return
                if "display_name" in body:
                    self.auth.update_display_name(target_id, body["display_name"])
                self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "Not found"})


# ─── エントリポイント ─────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Local RAG HTTP Bridge v2")
    parser.add_argument("--port",    type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-auth", action="store_true",
                        help="認証を無効化（開発用）")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[bridge] 警告: ANTHROPIC_API_KEY が未設定です。", file=sys.stderr)

    mcp = LocalRAGClient(Path(__file__).parent.parent)
    mcp.start()
    BridgeHandler.mcp = mcp

    # ナレッジ登録・更新マネージャーをセット
    if _KB_AVAILABLE:
        kb = KnowledgeManager(mcp._rag_service)
        BridgeHandler.kb = kb
        print("[bridge] ナレッジ管理有効: /api/knowledge/*", flush=True)

        # 定期クロール: 10分ごとに期限が来た登録URLを再取得（RAG_AUTO_CRAWL=0 で無効化）
        if os.environ.get("RAG_AUTO_CRAWL", "1") != "0":
            def _crawl_loop() -> None:
                while True:
                    time.sleep(600)
                    try:
                        results = kb.crawl_due()
                        updated = [r for r in results if r.get("updated")]
                        if updated:
                            print(f"[bridge] 定期クロール: {len(updated)} 件更新", flush=True)
                    except Exception as e:
                        print(f"[bridge] 定期クロールエラー: {e}", flush=True)
            threading.Thread(target=_crawl_loop, daemon=True, name="kb-crawl").start()
            print("[bridge] 定期クロール有効（10分間隔で更新チェック）", flush=True)
    else:
        BridgeHandler.kb = None

    # 監査ロガーをセット
    if _AUDIT_AVAILABLE:
        _audit_logger = RAGAuditLogger(Path(__file__).parent.parent / "logs" / "rag_audit.jsonl")
        BridgeHandler.audit = _audit_logger
        print("[bridge] 監査ログ有効: logs/rag_audit.jsonl", flush=True)
    else:
        BridgeHandler.audit = None

    # 認証マネージャーをセット
    if _AUTH_AVAILABLE and not args.no_auth:
        auth = AuthManager()
        BridgeHandler.auth = auth
        users = auth.list_users()
        print(f"[bridge] 認証有効: {len(users)} ユーザー登録済み", flush=True)
        if not users:
            print("[bridge] ★ ユーザーが未登録です。以下のコマンドで管理者を作成してください:", flush=True)
            print("[bridge]   python scripts/auth_manager.py create-admin --name 'Admin'", flush=True)
    else:
        BridgeHandler.auth = None
        print("[bridge] 認証無効（開発モード）", flush=True)

    server = HTTPServer(("localhost", args.port), BridgeHandler)
    print(f"[bridge] http://localhost:{args.port} で待機中", flush=True)
    print(f"[bridge] 管理画面: http://localhost:{args.port}/admin", flush=True)
    print(f"[bridge] ユーザー画面: http://localhost:{args.port}/ui", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] 停止中...", flush=True)
    finally:
        mcp.stop()
        server.server_close()


if __name__ == "__main__":
    main()
