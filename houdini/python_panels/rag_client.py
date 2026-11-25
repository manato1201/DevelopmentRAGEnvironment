"""
rag_client.py — RAG クライアント（Cloudflare Worker / ローカルブリッジ）と、設定の移行

rag_chatbot.py（Qt のパネル）から切り出した、Qt に依存しない部分。標準ライブラリだけで動くので、
Houdini の外（単体テスト）でも読み込める。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Iterator

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


def error_message(exc: BaseException) -> str:
    """通信の例外を、画面に出せる短い文にする。Worker が返した {"error": …} があれば、それを使う。"""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            if isinstance(body, dict) and body.get("error"):
                message = str(body["error"])
                suggestions = body.get("suggestions")
                if suggestions:
                    message += "（近い名前: " + " / ".join(str(x) for x in suggestions) + "）"
                return message[:300]
        except Exception:  # noqa: BLE001 -- 本文が読めなければ、ステータスだけ
            pass
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"接続できません: {exc.reason}"
    return str(exc)[:300] or exc.__class__.__name__


def get_json(url: str, timeout: int = 5) -> dict:
    """
    JSON を GET して dict を返す低レベルヘルパー。
    ヘルスチェック用。timeout は 5 秒（ブリッジ未起動時に UI が固まらないよう短く設定）。
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _sse_payload(data: list[str]) -> dict | None:
    """SSE の data 行（複数行は改行でつなぐ）を JSON の dict にする。JSON でない・dict でないときは None。"""
    try:
        payload = json.loads("\n".join(data))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def iter_sse(lines) -> "Iterator[tuple[str, dict]]":
    """Server-Sent Events（Worker の /query/stream）を、(イベント名, データ) の組にして返す。
    lines は bytes の行の並び（urlopen の応答をそのまま渡せる）。データが JSON でない行は、飛ばす。"""
    event, data = "message", []
    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        line = line.rstrip("\r\n")
        if not line:  # 空行: 1 つのイベントの終わり
            payload = _sse_payload(data) if data else None
            if payload is not None:
                yield event, payload
            event, data = "message", []
            continue
        if line.startswith(":"):  # コメント（接続を保つための ping など）
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "event":
            event = value
        elif name == "data":
            data.append(value)
    payload = _sse_payload(data) if data else None  # 最後の空行が無いまま、閉じられたとき
    if payload is not None:
        yield event, payload


def post_stream(url: str, body: dict, api_key: str = "", timeout: int = 90,
                on_sources: "Callable[[list], None] | None" = None, on_delta: "Callable[[str], None] | None" = None) -> dict:
    """/query/stream に POST し、出典（sources）と本文の続き（delta）を、届いた順に呼び出し元へ渡す。完成した応答（done）を返す。
    Worker が JSON で返したとき（外部ツールを使う質問など）は、その JSON を返す。途中の失敗（error）は、例外にする。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": _USER_AGENT, "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if "text/event-stream" not in str(resp.headers.get("Content-Type", "")):
            return json.loads(resp.read())
        for event, payload in iter_sse(resp):
            if event == "sources" and on_sources is not None:
                on_sources(list(payload.get("sources") or []))
            elif event == "delta" and on_delta is not None:
                on_delta(str(payload.get("text") or ""))
            elif event == "done":
                return payload
            elif event == "error":
                raise RuntimeError(str(payload.get("error") or "回答の生成に失敗しました"))
    raise RuntimeError("回答が途中で切れました（通信が切れた可能性があります）")


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
        explain: str | None = None,
        answer_mode: str | None = None,
        on_sources: "Callable[[list], None] | None" = None,
        on_delta: "Callable[[str], None] | None" = None,
    ) -> dict:
        """
        RAG にクエリを送る。モードに応じてエンドポイントとリクエスト形式を切り替える。

        on_sources・on_delta を渡すと（Cloudflare モード）、/query/stream で受け取る。検索で見つかった出典を、回答より先に
        on_sources へ、回答の本文を、届いた分ずつ on_delta へ渡す（待ち時間を短く感じさせる。2026-11-25、実証実験の A3）。
        返り値は、/query と同じ形。/query/stream が無い Worker（HTTP 404）では、/query に戻す。
        history は会話コンテキストとして送る（Gemini / Claude のマルチターン対話用）。

        image_b64（VLM入力）は Cloudflare モードでのみ有効。{"image":{"mimeType","data"}} を
        受け取ると、検索コンテキストに加えて画像自体も Gemini に見せて回答する。
        Local モードは未対応のため、渡されても無視する。

        context は作業場所のヒント（"sop" など）。あれば、その章の資料の順位が上がる。
        """
        if self.cfg["mode"] == "cloudflare":
            base = _cf_base(self.cfg)
            if not base:
                raise RuntimeError("Cloudflare の URL が未設定です（右上のメニュー（≡）の「接続・アカウント」で入力してください）")
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
            if explain in ("auto", "basic", "applied", "advanced"):
                body["explain"] = explain  # 説明のレベル。auto（おまかせ）は、質問に使った専門用語の蓄積から決まる（成長）
            if answer_mode in ("open", "grounded"):
                body["answerMode"] = answer_mode  # 答え方。open（既定）= 資料を最優先に、足りないところは「（推測）」と明示して答える / grounded = 資料だけ
            api_key = self.cfg.get("cf_api_key", "")
            if on_sources is not None or on_delta is not None:
                try:
                    return post_stream(f"{base}/query/stream", body, api_key=api_key, on_sources=on_sources, on_delta=on_delta)
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
            return post_json(f"{base}/query", body, api_key=api_key)
        else:
            port = self.cfg["local_port"]
            local_body: dict = {"query": query, "history": history, "limit": 5}
            if answer_mode in ("open", "grounded"):
                local_body["answerMode"] = answer_mode
            return post_json(f"http://localhost:{port}/query", local_body)

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

    # ── ドキュメントの閲覧（Docs タブ。Cloudflare モードのみ。Worker の /docs/list・/docs/get・/search） ──

    def _docs(self, path: str, body: dict, timeout: int = 30) -> dict:
        base = _cf_base(self.cfg)
        if self.cfg["mode"] != "cloudflare" or not base:
            raise RuntimeError("Docs は、Cloudflare モードで、Worker の URL と APIキーを設定すると使えます")
        return post_json(f"{base}{path}", body, timeout=timeout, api_key=self.cfg.get("cf_api_key", ""))

    def docs_namespaces(self) -> list[str]:
        """読めるナレッジ（namespace）の一覧。"""
        return [str(n) for n in (self._docs("/me/namespaces", {}, timeout=10).get("namespaces") or [])]

    def docs_list(self, namespace: str, query: str = "", limit: int = 50, offset: int = 0) -> dict:
        """ドキュメント名の一覧（名前の部分一致）。{"files": [...], "total": 件数}。"""
        return self._docs("/docs/list", {"namespace": namespace, "query": query, "limit": limit, "offset": offset})

    def docs_search(self, namespace: str, query: str, limit: int = 8) -> dict:
        """意味＋全文の検索（/search）。1つのナレッジに絞る。応答は {"texts": [...], "sources": [...]}。"""
        return self._docs("/search", {"query": query, "limit": limit, "namespaces": [namespace]}, timeout=60)

    def docs_get(self, namespace: str, file: str, offset: int = 0, max_chars: int = 20000) -> dict:
        """1ドキュメントの本文（長いときは offset から max_chars 文字）。{"text", "totalChars", "nextOffset"}。"""
        return self._docs("/docs/get", {"namespace": namespace, "file": file, "offset": offset, "maxChars": max_chars})

    def growth(self) -> dict:
        """自分の習熟度（Cloudflare モードのみ）。/me/growth の応答。失敗は例外。"""
        base = _cf_base(self.cfg)
        if self.cfg["mode"] != "cloudflare" or not base:
            return {}
        return post_json(f"{base}/me/growth", {}, timeout=10, api_key=self.cfg.get("cf_api_key", ""))

    def growth_reset(self) -> bool:
        """自分の用語の記録を消す（Cloudflare モードのみ）。"""
        base = _cf_base(self.cfg)
        if self.cfg["mode"] != "cloudflare" or not base:
            return False
        return post_json(f"{base}/me/growth/reset", {}, timeout=10, api_key=self.cfg.get("cf_api_key", "")).get("status") == "ok"

    def _pilot(self, path: str, body: dict) -> dict:
        """実証実験の課題 API（Cloudflare モードのみ）。失敗は例外（APIキーが無効・事前アンケート前など）。"""
        base = _cf_base(self.cfg)
        if self.cfg["mode"] != "cloudflare" or not base:
            raise RuntimeError("Cloudflare モードで、URL と APIキーを設定してください")
        return post_json(f"{base}{path}", body, timeout=15, api_key=self.cfg.get("cf_api_key", ""))

    def pilot_plan(self) -> dict:
        """自分の次の課題（/pilot/plan）。{"profile": False} なら、事前アンケートがまだ。"""
        return self._pilot("/pilot/plan", {})

    def pilot_profile(self, answers: dict) -> dict:
        """事前アンケートを送る（/pilot/profile）。応答は plan と同じ。"""
        return self._pilot("/pilot/profile", answers)

    def pilot_session_start(self, kind: str) -> dict:
        """課題を始める（/pilot/session/start）。kind は "fixed"（固定課題）か "free"（自由課題）。"""
        return self._pilot("/pilot/session/start", {"kind": kind})

    def pilot_session_end(self, payload: dict) -> dict:
        """課題を終える（/pilot/session/end）。到達・自己申告のミス・cook エラーのノード数・課題後アンケートを送る。"""
        return self._pilot("/pilot/session/end", payload)

    def pilot_session_reset(self, session_id: str) -> dict:
        """計測中・終えた課題を破棄して、やり直す（/pilot/session/reset）。次の回を始めたあとの、前の回は、サーバーが断る。"""
        return self._pilot("/pilot/session/reset", {"sessionId": session_id})

    def pilot_basics(self, step: int, total: int) -> dict:
        """基本操作の練習（Guide の組み込み）の進み具合を送る（/pilot/basics。2026-11-26）。事前アンケートの前は {"recorded": False}。"""
        return self._pilot("/pilot/basics", {"step": int(step), "total": int(total)})

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

    def pin(self, memory_id, pinned: bool) -> bool:
        """
        Cloudflare モードのみ有効。回答をお気に入り(ブックマーク)に登録・解除する（/memory/pin）。
        Local モードは保存先がないため常に False（呼び出し側は、ボタンを出さない）。
        """
        if self.cfg["mode"] != "cloudflare":
            return False
        base = _cf_base(self.cfg)
        try:
            mid = int(memory_id)
        except (TypeError, ValueError):
            return False
        if not base:
            return False
        try:
            post_json(f"{base}/memory/pin", {"id": mid, "pinned": bool(pinned)}, timeout=15, api_key=self.cfg.get("cf_api_key", ""))
            return True
        except Exception:
            return False


# GAS（Google Apps Script）を使っていた頃の設定キー。Cloudflare へ移行したので、
# 読み込み時に取り除く（設定ファイルに残っていても無視する）。
LEGACY_KEYS = (
    "gas_url", "gas_api_key", "gas_db_key",
    "tutorial_rag_mode", "tutorial_claude_backend",
)


# チュートリアル生成の既定のモデル（2026-11-25）。以前の既定 claude-sonnet-5 は、effort（思考の深さ）を送らないため、
# 実証実験（11/24・25、20 回の生成）で、1 回あたりの出力が中央値 65k トークン・API の往復が 78 回（上限 80）になり、約 2 ドルかかった。
# 同じ単価の claude-sonnet-5-5（effort: medium）は、手元の同じ種類の題材（Basic の RBD など）で 0.2〜0.4 ドルだった。
# モデルの選択は「設定」（設定者だけ）にしかないので、参加者は、以前の既定のまま動いていた → 設定を 1 回だけ移す。
OLD_DEFAULT_TUTORIAL_MODEL = "claude-sonnet-5"
DEFAULT_TUTORIAL_MODEL = "claude-sonnet-5-5"
MODEL_MIGRATION_KEY = "tutorial_model_migrated"


def migrate_config(cfg: dict) -> dict:
    """旧設定（GAS 時代）を新設定へ変換する。mode "cloud" は "cloudflare" に読み替える。
    チュートリアル生成のモデルが、以前の既定（claude-sonnet-5）のままなら、1 回だけ新しい既定に移す（印を残すので、
    そのあとで設定者が claude-sonnet-5 を選び直したときは、そのまま）。"""
    out = dict(cfg)
    if out.get("mode") not in ("cloudflare", "local"):
        out["mode"] = "cloudflare" if out.get("mode") == "cloud" else "cloudflare"
    for key in LEGACY_KEYS:
        out.pop(key, None)
    if not out.get(MODEL_MIGRATION_KEY):
        if out.get("tutorial_model") in (None, "", OLD_DEFAULT_TUTORIAL_MODEL):
            out["tutorial_model"] = DEFAULT_TUTORIAL_MODEL
        out[MODEL_MIGRATION_KEY] = "2026-11-25"
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
