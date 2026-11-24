"""
reference_author.py — Reference の説明を、AI で作る（開発側）。画面（reference_view の「説明を作る」）とバッチ（scripts/build_reference_entries.py）の共通部分（2026-11-19）

  ・fetch_reference_items … HoudiniReference の項目（Tips・動画の題名と短い抜粋）。1 日は保存を使う
  ・fetch_docs            … SideFX 公式のドキュメント（RAG に入っている Houdini のナレッジ）から、その項目の資料
  ・make_entry            … 資料 + 参考 → AI（complete）→ 説明（5 つの欄）。保存は save_made

Qt にも Houdini にも依存しない（単体テストできる）。AI を呼ぶので、Claude の予算を使う（1 件 約 5,000 入力・約 1,000 出力トークン。推定）。
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Callable

import reference_data as rd

REFERENCE_CACHE_NAME = "_houdinireference_items.json"
REFERENCE_MAX_AGE_SECONDS = 24 * 3600
DOCS_PER_ITEM = 4
PAGE_CHARS = 4000  # 本体ページは、先頭のこれだけ（概要・使い方。空白を詰めると、2000 文字ほどの中身になる）


class UnreadableAnswer(ValueError):
    """AI の返事から、説明を読み取れなかった（text は、返事の本文。原因の確認用）。"""

    def __init__(self, text: str) -> None:
        super().__init__("AI の返事を読み取れませんでした")
        self.text = str(text or "")


def fetch_reference_items(base_dir: str, now: float | None = None, opener: Callable | None = None) -> list[dict]:
    """HoudiniReference の項目（Tips・動画・ニュース）。1 日は、保存したものを使う。取れなければ、古い保存か、空。例外は投げない。
    出典・利用条件は、それぞれの元のページにある（HoudiniReference の README）。ここでは、題名・出典・日付・短い抜粋・URL だけを使う。"""
    path = Path(base_dir) / "localRAG" / "reference" / REFERENCE_CACHE_NAME if base_dir else None
    now = time.time() if now is None else now
    cached: list[dict] = []
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached = [i for i in (data.get("items") or []) if isinstance(i, dict)]
            if cached and now - float(data.get("fetched_at", 0)) < REFERENCE_MAX_AGE_SECONDS:
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


def fetch_docs(cfg: dict, item: dict) -> list[str]:
    """公式ドキュメント（RAG の Houdini のナレッジ）から、この項目の資料を取る。取れなければ、空（AI は、資料なしと分かった上で書く）。
    ノード・APEX は、本体のページ（「<表示名> [SOP]」という名前）の先頭を、まず取る。そのあとに、検索で近い資料を足す。"""
    try:
        from rag_client import RAGClient
        from tutorial_agent import resolve_rag_name

        label = item.get("label") or item.get("name") or ""
        namespace = f"shared:{resolve_rag_name(str((cfg or {}).get('tutorial_rag_namespace') or ''))}"
        client = RAGClient(cfg)
        texts: list[str] = []
        context = str(item.get("context") or "").upper()
        if item.get("kind") in ("node", "apex") and label and context:
            try:
                page = client.docs_get(namespace, f"{label} [{context}]", offset=0, max_chars=PAGE_CHARS)
                if page.get("status") == "ok" and str(page.get("text") or "").strip():
                    texts.append(str(page["text"]))
            except Exception:  # noqa: BLE001 -- 本体のページが無い（取り込まれていない）ときは、検索だけ
                pass
        result = client.docs_search(namespace, f"{label} {rd.KIND_LABELS.get(item.get('kind', ''), '')}", limit=DOCS_PER_ITEM)
        return texts + [str(t) for t in (result.get("texts") or []) if str(t).strip()]
    except Exception:  # noqa: BLE001
        return []


def make_entry(cfg: dict, complete: Callable, item: dict, references: list[dict] | None = None,
               docs: list[str] | None = None, parm_names: list[str] | None = None, verified: str = "", facts: str = "") -> tuple[dict, dict, int, int]:
    """1 項目の説明を作る。戻り値: (説明, usage, 使った資料の数, 使った参考の数)。
    返事を読み取れなければ UnreadableAnswer、AI の例外は、そのまま出す（呼び出し側が、画面・ログに出す）。
    references・docs を渡すと、取得を省く（テスト・まとめて作るとき）。"""
    label = item.get("label") or item.get("name") or ""
    if references is None:
        references = rd.match_reference_items(fetch_reference_items(str((cfg or {}).get("local_bridge_dir") or "")), label, item.get("kind", ""), aliases=rd.item_aliases(item), context=rd.item_context(item))
    if docs is None:
        docs = fetch_docs(cfg, item)
    system, user = rd.build_prompt(item.get("kind", ""), label, docs, references, parm_names=parm_names, verified=verified, facts=facts)
    # 短い要約なので、出力の上限と思考の深さを抑える（費用と時間を、減らす）
    text, usage = complete(system, user, max_tokens=rd.REFERENCE_MAX_TOKENS, effort=rd.REFERENCE_EFFORT)
    entry = rd.parse_entry(text)
    if entry is None:
        raise UnreadableAnswer(text)
    return entry, usage or {}, len(docs), len(references)


def save_made(base_dir: str, item: dict, entry: dict, docs_found: int, references: int) -> bool:
    """作った説明を、端末に保存する（次からは、AI を呼ばない。公開は scripts/publish_reference.py）。"""
    if not base_dir:
        return False
    return rd.save_entry(base_dir, item["kind"], item["key"], entry,
                         {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "docs_found": docs_found, "references": references,
                          "label": str(item.get("label") or item.get("name") or "")})
