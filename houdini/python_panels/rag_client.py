"""
rag_client.py — RAG クライアント（Cloudflare Worker / ローカルブリッジ）と、設定の移行

rag_chatbot.py（Qt のパネル）から切り出した、Qt に依存しない部分。標準ライブラリだけで動くので、
Houdini の外（単体テスト）でも読み込める。
"""

from __future__ import annotations

import json
import urllib.request

# Cloudflare は urllib 既定の User-Agent を bot として拒否する（error 1010）ため、明示する。
_USER_AGENT = "HoudiniRAGPanel/1.0"


def post_json(url: str, body: dict, timeout: int = 60, api_key: str = "") -> dict:
    """
    JSON を POST して dict を返す低レベルヘルパー。
    urllib のみを使うことで外部ライブラリへの依存をゼロにしている。
    timeout はデフォルト 60 秒（LLM の回答生成に時間がかかるため長めに設定）。
    api_key があれば Authorization: Bearer で送る（Cloudflare Worker 用）。
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def get_json(url: str, timeout: int = 5) -> dict:
    """
    JSON を GET して dict を返す低レベルヘルパー。
    ヘルスチェック用。timeout は 5 秒（ブリッジ未起動時に UI が固まらないよう短く設定）。
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _cf_base(cfg: dict) -> str:
    """Cloudflare Worker の URL（末尾の / を除く）。"""
    return str(cfg.get("cf_url", "")).strip().rstrip("/")


def _parse_namespaces(text: str) -> list[str]:
    """カンマ・空白区切りのナレッジ指定を、重複なしのリストにする（空なら空リスト）。"""
    out: list[str] = []
    for part in str(text or "").replace("、", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


class RAGClient:
    """
    Cloudflare / Local を透過的に扱う RAG クライアント。

    Cloudflare モード: POST {cf_url}/query（Authorization: Bearer <APIキー>）
      {"query": "...", "history": [{"role","content"}], "namespaces": [...], "context": "sop", "image": {...}}
      → {"answer", "sources": [{"file","namespace",...}], "memoryId": 数値, ...}

    Local モードのリクエスト body:
      {"query": "...", "history": [...], "limit": 5}
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def query(
        self,
        query: str,
        history: list[dict],
        image_b64: str | None = None,
        context: str | None = None,
    ) -> dict:
        """
        RAG にクエリを送る。モードに応じてエンドポイントとリクエスト形式を切り替える。
        history は会話コンテキストとして送る（Gemini / Claude のマルチターン対話用）。

        image_b64（VLM入力）は Cloudflare モードでのみ有効。{"image":{"mimeType","data"}} を
        受け取ると、検索コンテキストに加えて画像自体も Gemini に見せて回答する。
        Local モードは未対応のため、渡されても無視する。

        context は作業場所のヒント（"sop" など）。あれば、その章の資料の順位が上がる。
        """
        if self.cfg["mode"] == "cloudflare":
            base = _cf_base(self.cfg)
            if not base:
                raise RuntimeError("Cloudflare の URL が未設定です（設定タブで入力してください）")
            body: dict = {
                "query": query,
                # Worker は {role, content} 形式。パネルの履歴は {role, text}。
                "history": [
                    {"role": h.get("role", "user"), "content": h.get("text", h.get("content", ""))}
                    for h in history
                ],
            }
            namespaces = _parse_namespaces(self.cfg.get("cf_namespaces", ""))
            if namespaces:
                body["namespaces"] = namespaces
            if context:
                body["context"] = context
            if image_b64:
                body["image"] = {"mimeType": "image/png", "data": image_b64}
            return post_json(f"{base}/query", body, api_key=self.cfg.get("cf_api_key", ""))
        else:
            port = self.cfg["local_port"]
            return post_json(
                f"http://localhost:{port}/query",
                {"query": query, "history": history, "limit": 5},
            )

    def health(self) -> bool:
        """
        サーバーの疎通確認。例外が発生した場合は False を返す。
        Cloudflare: /health で {"status":"ok"} を確認。
        Local: /health エンドポイントで {"status":"ok"} を確認。
        """
        try:
            if self.cfg["mode"] == "cloudflare":
                base = _cf_base(self.cfg)
                if not base:
                    return False
                return get_json(f"{base}/health").get("status") == "ok"
            data = get_json(f"http://localhost:{self.cfg['local_port']}/health")
            return data.get("status") == "ok"
        except Exception:
            return False

    def whoami(self) -> dict:
        """
        どのユーザーで入っているか（Cloudflare モードのみ）。/me/namespaces の応答
        {"displayName", "role", "userIdShort", "namespaces"} を返す。失敗は例外（APIキーが無効など）。
        """
        base = _cf_base(self.cfg)
        if self.cfg["mode"] != "cloudflare" or not base:
            return {}
        return post_json(f"{base}/me/namespaces", {}, timeout=10, api_key=self.cfg.get("cf_api_key", ""))

    def rate(self, memory_id, rating: str) -> bool:
        """
        Cloudflare モードのみ有効。回答の履歴に 👍/👎 評価を送る（/memory/rate）。
        Local モードは評価先がないため常に True を返す（no-op）。
        rating: "up"（👍）| "down"（👎）
        """
        if self.cfg["mode"] != "cloudflare":
            return True
        base = _cf_base(self.cfg)
        try:
            mid = int(memory_id)
        except (TypeError, ValueError):
            return False
        if not base:
            return False
        try:
            post_json(
                f"{base}/memory/rate",
                {"id": mid, "rating": 1 if rating == "up" else -1},
                timeout=15,
                api_key=self.cfg.get("cf_api_key", ""),
            )
            return True
        except Exception:
            return False


# GAS（Google Apps Script）を使っていた頃の設定キー。Cloudflare へ移行したので、
# 読み込み時に取り除く（設定ファイルに残っていても無視する）。
LEGACY_KEYS = (
    "gas_url", "gas_api_key", "gas_db_key",
    "tutorial_rag_mode", "tutorial_claude_backend",
)


def migrate_config(cfg: dict) -> dict:
    """旧設定（GAS 時代）を新設定へ変換する。mode "cloud" は "cloudflare" に読み替える。"""
    out = dict(cfg)
    if out.get("mode") not in ("cloudflare", "local"):
        out["mode"] = "cloudflare" if out.get("mode") == "cloud" else "cloudflare"
    for key in LEGACY_KEYS:
        out.pop(key, None)
    return out


def normalize_cloudflare_graph(data: dict) -> dict:
    """
    Worker の /graph レスポンスを、描画側（NodeItem / RAGGraphScene）が読む形にする。
      ノード: namespace → db（色分け・詳細表示用）、size → chunk_count
      エッジ: weight → score（線の濃さ）
    """
    nodes = []
    for nd in data.get("nodes", []):
        nd = dict(nd)
        ns = str(nd.get("namespace", ""))
        # 色分けは "shared:tool_docs" の末尾（ナレッジ名）で行う
        nd.setdefault("db", ns.split(":", 1)[-1] if ns else "")
        if "size" in nd:
            nd.setdefault("chunk_count", nd["size"])
        nodes.append(nd)
    edges = []
    for ed in data.get("edges", []):
        ed = dict(ed)
        if "weight" in ed:
            ed.setdefault("score", ed["weight"])
        edges.append(ed)
    return {**data, "nodes": nodes, "edges": edges}
