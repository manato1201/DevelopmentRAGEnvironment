#!/usr/bin/env python3
"""
rag_local_bridge.py — Local RAG HTTP Bridge

mcp-rag-server (JSON-RPC stdio) + Claude API を
Unity/Houdini 向け HTTP API として公開する薄いブリッジ。

Usage:
    python scripts/rag_local_bridge.py [--port 8766] [--mcp-dir PATH]

Env:
    ANTHROPIC_API_KEY  必須（.env 非使用）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ─── デフォルト設定 ─────────────────────────────────────────────────────────────
DEFAULT_PORT = 8766
DEFAULT_MCP_DIR = str(Path(__file__).parent.parent.parent / "mcp-rag-server")
GRAPH_EXPORT_SCRIPT = Path(__file__).parent / "rag_graph_export.py"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
SYSTEM_PROMPT = (
    "あなたはゲーム開発チームの知識ベースを持つ AI アシスタントです。"
    "日本語で簡潔に回答してください（目安: 400 文字以内）。"
    "重要な点のみ箇条書きでまとめてください。"
)


# ─── MCP クライアント ────────────────────────────────────────────────────────────
class MCPClient:
    """mcp-rag-server (stdio JSON-RPC 2.0) の薄いラッパー"""

    def __init__(self, server_dir: Path) -> None:
        self.server_dir = server_dir
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._id = 0

    # ── 内部ユーティリティ ──────────────────────────────────────────────────────
    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def _recv(self) -> dict:
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError("mcp-rag-server が予期せず終了しました")
        return json.loads(line)

    # ── ライフサイクル ──────────────────────────────────────────────────────────
    def start(self) -> None:
        """サーバープロセスを起動して MCP ハンドシェイクを行う"""
        self._proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "src.main"],
            cwd=str(self.server_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

        # initialize → capabilities response を受け取る
        self._send({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "rag-local-bridge", "version": "1.0"},
            },
        })
        self._recv()  # initialize response（capabilities）

        # notifications/initialized は通知のみ — response なし
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        print("[bridge] mcp-rag-server 起動完了", flush=True)

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc = None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ── ツール呼び出し ──────────────────────────────────────────────────────────
    def search(self, query: str, limit: int = 5) -> list[str]:
        """search ツールを呼び出して content テキストのリストを返す"""
        with self._lock:
            self._send({
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {
                    "name": "search",
                    "arguments": {
                        "query": query,
                        "limit": limit,
                        "with_context": True,
                    },
                },
            })
            resp = self._recv()

        content = resp.get("result", {}).get("content", [])
        return [c["text"] for c in content if c.get("type") == "text"]

    def get_document_count(self) -> int:
        with self._lock:
            self._send({
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": "get_document_count", "arguments": {}},
            })
            resp = self._recv()

        content = resp.get("result", {}).get("content", [])
        if content:
            for word in content[0].get("text", "").split():
                if word.isdigit():
                    return int(word)
        return 0


# ─── Claude API 呼び出し ─────────────────────────────────────────────────────────
def _call_claude(context_texts: list[str], query: str, history: list[dict]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "ANTHROPIC_API_KEY 環境変数が設定されていません。"

    context = "\n\n".join(context_texts) if context_texts else "（参考ドキュメントなし）"

    messages: list[dict] = [
        {"role": "user", "content": f"以下の参考ドキュメントを確認しました。\n\n{context}"},
        {"role": "assistant", "content": "参考ドキュメントを確認しました。ご質問にお答えします。"},
    ]

    # 直近 3 往復（6 メッセージ）の会話履歴を注入
    for h in history[-6:]:
        role = "assistant" if h.get("role") in ("bot", "assistant") else "user"
        text = h.get("text", h.get("content", ""))
        if text:
            messages.append({"role": role, "content": text})

    messages.append({"role": "user", "content": query})

    payload = json.dumps(
        {
            "model": CLAUDE_MODEL,
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    return data["content"][0]["text"]


def _extract_sources(texts: list[str]) -> list[dict]:
    """search 結果テキストからファイル名を抽出してソースリストを作る"""
    sources = []
    seen: set[str] = set()
    for t in texts:
        for line in t.splitlines():
            if "ファイル:" in line:
                fname = line.split("ファイル:")[-1].strip()
                if fname and fname not in seen:
                    seen.add(fname)
                    sources.append({"title": fname, "db": "local", "score": 0})
    return sources


# ─── HTTP ハンドラ ────────────────────────────────────────────────────────────────
class BridgeHandler(BaseHTTPRequestHandler):

    mcp: MCPClient  # クラス変数として start() 後にセット

    def log_message(self, fmt: str, *args) -> None:  # noqa: ANN002
        pass  # デフォルトのアクセスログを抑制

    # ── 共通ユーティリティ ──────────────────────────────────────────────────────
    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── CORS プリフライト ────────────────────────────────────────────────────────
    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET /health ──────────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        if self.path == "/health":
            alive = self.mcp.is_alive()
            count = self.mcp.get_document_count() if alive else 0
            self._send_json(200 if alive else 503, {
                "status": "ok" if alive else "error",
                "server": "mcp-rag-server",
                "total_chunks": count,
            })
        elif self.path == "/graph":
            self._handle_graph()
        else:
            self._send_json(404, {"status": "error", "message": "Not found"})

    def _handle_graph(self) -> None:
        """ChromaDB グラフデータを返す（rag_graph_export.py を uv run で実行）"""
        try:
            result = subprocess.run(
                [
                    "uv", "run",
                    "--directory", str(self.mcp.server_dir),
                    "python", str(GRAPH_EXPORT_SCRIPT),
                    str(self.mcp.server_dir),
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
            if result.returncode != 0:
                self._send_json(500, {
                    "status": "error",
                    "message": result.stderr.strip() or "graph export failed",
                })
                return
            data = json.loads(result.stdout)
            data["status"] = "ok"
            self._send_json(200, data)
        except subprocess.TimeoutExpired:
            self._send_json(504, {"status": "error", "message": "graph export timed out"})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"status": "error", "message": str(exc)})

    # ── POST /query ──────────────────────────────────────────────────────────────
    def do_POST(self) -> None:
        if self.path != "/query":
            self._send_json(404, {"status": "error", "message": "Not found"})
            return

        body = self._read_body()
        query: str = body.get("query", "").strip()
        history: list[dict] = body.get("history", [])
        limit: int = int(body.get("limit", 5))

        if not query:
            self._send_json(400, {"status": "error", "message": "query は必須です"})
            return

        if not self.mcp.is_alive():
            self._send_json(503, {"status": "error", "message": "mcp-rag-server が起動していません"})
            return

        try:
            texts = self.mcp.search(query, limit)
            answer = _call_claude(texts, query, history)
            sources = _extract_sources(texts)
            self._send_json(200, {"answer": answer, "sources": sources, "status": "ok"})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._send_json(502, {"status": "error", "message": f"Claude API エラー: {detail}"})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"status": "error", "message": str(exc)})


# ─── エントリポイント ─────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Local RAG HTTP Bridge")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"ポート番号（デフォルト: {DEFAULT_PORT}）")
    parser.add_argument("--mcp-dir", default=DEFAULT_MCP_DIR, help="mcp-rag-server のディレクトリ")
    args = parser.parse_args()

    mcp_dir = Path(args.mcp_dir)
    if not mcp_dir.exists():
        print(f"[bridge] エラー: mcp-rag-server ディレクトリが見つかりません: {mcp_dir}", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[bridge] 警告: ANTHROPIC_API_KEY が設定されていません。/query は失敗します。", file=sys.stderr)

    mcp = MCPClient(mcp_dir)
    mcp.start()
    BridgeHandler.mcp = mcp

    server = HTTPServer(("localhost", args.port), BridgeHandler)
    print(f"[bridge] http://localhost:{args.port} で待機中 (Ctrl+C で停止)", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] 停止中...", flush=True)
    finally:
        mcp.stop()
        server.server_close()


if __name__ == "__main__":
    main()
