"""
notion_to_corpus.py — Notion全DBをGemini Semantic Retrieval Corpusへ同期

使い方:
    uv run python scripts/notion_to_corpus.py --init          # 初回: コーパス作成 + 全件投入
    uv run python scripts/notion_to_corpus.py --sync          # 差分更新（変更ページのみ）
    uv run python scripts/notion_to_corpus.py --query "柚子塩らーめん"       # テスト検索
    uv run python scripts/notion_to_corpus.py --query "VEX" --db tool_docs  # DB絞り込み検索
    uv run python scripts/notion_to_corpus.py --reset         # コーパス削除して再初期化

必要な環境変数 (.env):
    NOTION_API_KEY
    GEMINI_API_KEY

初回実行後に表示される CORPUS_NAME を GAS スクリプトプロパティ
GEMINI_CORPUS_NAME に設定してください。
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

import requests

# 環境変数から読む（.envは使わない）
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

DB_IDS = {
    "tool_docs":  os.environ.get("DB_TOOL_DOCS",  "249e442a-47dd-4a8d-95a8-8b856fb91ef6"),
    "game_info":  os.environ.get("DB_GAME_INFO",  "f201f73c-45dc-44cb-b8d7-a7be81b3644c"),
    "research":   os.environ.get("DB_RESEARCH",   "714d4d4a-6a85-4aa1-845c-32dc3e1a2b1f"),
    "team_notes": os.environ.get("DB_TEAM_NOTES", "f898bf03-8c9f-40e0-9e1b-a28432703d69"),
    "afuri":      os.environ.get("DB_AFURI",      "a74822790ec34768bdef0917abae3e6f"),
    "braintq":    os.environ.get("DB_BRAINTQ",    "847b7db0f29f4190bee9f7ae7dd15514"),
    "fourteen":   os.environ.get("DB_FOURTEEN",   "475cf278492a45ac90cbe4b8f11df1f5"),
}

GEMINI_BASE    = "https://generativelanguage.googleapis.com/v1beta"
CORPUS_DISPLAY = "Cloud RAG Knowledge Base"
STATE_FILE     = Path(__file__).parent / ".corpus_state.json"

NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type":   "application/json",
}

# ─────────────────────────────────────────────
# 状態管理
# ─────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# ─────────────────────────────────────────────
# Gemini Retrieval API ヘルパー
# ─────────────────────────────────────────────

def gemini_req(method: str, path: str, payload: dict = None, retries: int = 4):
    url = f"{GEMINI_BASE}/{path}?key={GEMINI_API_KEY}"
    for attempt in range(retries):
        try:
            if method == "GET":
                res = requests.get(url, timeout=30)
            elif method == "POST":
                res = requests.post(url, json=payload, timeout=30)
            elif method == "DELETE":
                res = requests.delete(url, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
        except requests.RequestException as e:
            print(f"  リクエストエラー: {e}")
            return None

        if res.status_code in (200, 201):
            return res.json() if res.text else {}
        if res.status_code == 429 and attempt < retries - 1:
            wait = 2 ** attempt + 1
            print(f"  レート制限 429 — {wait}秒待機...")
            time.sleep(wait)
            continue
        if res.status_code == 204:  # DELETE成功
            return {}
        print(f"  Gemini APIエラー {res.status_code}: {res.text[:300]}")
        return None
    return None

# ─────────────────────────────────────────────
# コーパス管理
# ─────────────────────────────────────────────

def get_or_create_corpus() -> str | None:
    state = load_state()
    if "corpus_name" in state:
        return state["corpus_name"]

    # 既存コーパスを確認
    result = gemini_req("GET", "corpora")
    for c in (result or {}).get("corpora", []):
        if c.get("displayName") == CORPUS_DISPLAY:
            print(f"既存コーパスを使用: {c['name']}")
            state["corpus_name"] = c["name"]
            save_state(state)
            return c["name"]

    # 新規作成
    print("コーパスを新規作成中...")
    result = gemini_req("POST", "corpora", {"display_name": CORPUS_DISPLAY})
    if not result:
        return None
    corpus_name = result["name"]
    print(f"  作成完了: {corpus_name}")
    state["corpus_name"] = corpus_name
    save_state(state)
    return corpus_name

def delete_corpus(corpus_name: str):
    print(f"コーパスを削除: {corpus_name}")
    gemini_req("DELETE", corpus_name)

# ─────────────────────────────────────────────
# ドキュメント・チャンク管理
# ─────────────────────────────────────────────

def list_existing_docs(corpus_name: str) -> dict[str, str]:
    """display_name → doc_name のマップを返す"""
    docs = {}
    page_token = None
    while True:
        path = f"{corpus_name}/documents?pageSize=100"
        if page_token:
            path += f"&pageToken={page_token}"
        result = gemini_req("GET", path)
        if not result:
            break
        for doc in result.get("documents", []):
            docs[doc["displayName"]] = doc["name"]
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return docs

def delete_document(doc_name: str):
    gemini_req("DELETE", doc_name)

def upsert_page(corpus_name: str, page_data: dict, existing_docs: dict) -> bool:
    """Notionページ1件をドキュメント+チャンクとしてupsert"""
    display_name = f"{page_data['db']}:{page_data['notion_page_id']}"

    # 既存ドキュメントを削除（再投入のため）
    if display_name in existing_docs:
        delete_document(existing_docs[display_name])
        time.sleep(0.3)

    # ドキュメント作成
    doc_result = gemini_req("POST", f"{corpus_name}/documents", {
        "display_name": display_name,
        "custom_metadata": [
            {"key": "db",             "string_value": page_data["db"]},
            {"key": "notion_page_id", "string_value": page_data["notion_page_id"]},
            {"key": "title",          "string_value": page_data["title"][:100]},
        ]
    })
    if not doc_result:
        return False
    time.sleep(0.3)

    # チャンク作成（title + summary + tags を連結した本文）
    chunk_result = gemini_req("POST", f"{doc_result['name']}/chunks", {
        "data": {"string_value": page_data["text"][:2000]},
        "custom_metadata": [
            {"key": "db",    "string_value": page_data["db"]},
            {"key": "title", "string_value": page_data["title"][:100]},
        ]
    })
    time.sleep(0.3)
    return chunk_result is not None

# ─────────────────────────────────────────────
# Notion 取得
# ─────────────────────────────────────────────

def fetch_notion_pages(db_id: str) -> list:
    pages, payload = [], {"page_size": 100}
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    while True:
        res = requests.post(url, headers=NOTION_HEADERS, json=payload, timeout=30)
        if res.status_code != 200:
            print(f"  Notion APIエラー {res.status_code}: {res.text[:100]}")
            break
        data = res.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
        time.sleep(0.3)
    return pages

def extract_page_data(page: dict, db_key: str) -> dict | None:
    """NotionページをCorpus投入用データに変換"""
    props = page.get("properties", {})

    # タイトル
    title_raw = props.get("title", {})
    title = "".join(t.get("plain_text", "") for t in title_raw.get("title", []))
    if not title:
        return None  # タイトルなし → スキップ

    # summary
    summary_raw = props.get("summary", {})
    summary = "".join(t.get("plain_text", "") for t in summary_raw.get("rich_text", []))

    # tags
    tags = [t.get("name", "") for t in props.get("tags", {}).get("multi_select", [])]

    # source_url
    source_url = props.get("source_url", {}).get("url", "") or ""

    # 埋め込み用テキスト（title + summary + tags + url）
    parts = [f"# {title}"]
    if summary:
        parts.append(summary)
    if tags:
        parts.append(f"タグ: {', '.join(tags)}")
    if source_url:
        parts.append(f"参照: {source_url}")

    return {
        "title":          title,
        "text":           "\n".join(parts),
        "db":             db_key,
        "notion_page_id": page["id"],
        "last_edited":    page.get("last_edited_time", ""),
    }

# ─────────────────────────────────────────────
# 同期メイン
# ─────────────────────────────────────────────

def sync_all(force: bool = False):
    corpus_name = get_or_create_corpus()
    if not corpus_name:
        print("ERROR: コーパスを取得/作成できませんでした")
        sys.exit(1)

    state = load_state()
    synced = state.get("synced_pages", {})  # {page_id: last_edited_time}

    print(f"\nコーパス: {corpus_name}")
    print("既存ドキュメントを取得中...")
    existing_docs = list_existing_docs(corpus_name)
    print(f"  既存: {len(existing_docs)}件")

    total_ok = total_skip = total_err = 0

    for db_key, db_id in DB_IDS.items():
        print(f"\n[{db_key}] Notionページを取得中...")
        pages = fetch_notion_pages(db_id)
        print(f"  {len(pages)}ページ")

        for page in pages:
            page_id   = page["id"]
            last_edit = page.get("last_edited_time", "")

            # 差分スキップ
            if not force and synced.get(page_id) == last_edit:
                total_skip += 1
                continue

            data = extract_page_data(page, db_key)
            if not data:
                continue

            label = data["title"][:50]
            print(f"  → {label}")
            ok = upsert_page(corpus_name, data, existing_docs)

            if ok:
                synced[page_id] = last_edit
                total_ok += 1
            else:
                total_err += 1

    state["synced_pages"] = synced
    state["last_sync"]    = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"\n{'='*50}")
    print(f"同期完了  更新:{total_ok}件  スキップ:{total_skip}件  エラー:{total_err}件")
    print(f"{'='*50}")
    print(f"\n★ GASスクリプトプロパティに以下を設定してください:")
    print(f"  GEMINI_CORPUS_NAME = {corpus_name}")

# ─────────────────────────────────────────────
# テスト検索
# ─────────────────────────────────────────────

def test_query(query: str, db_key: str = None, limit: int = 5):
    corpus_name = get_or_create_corpus()
    payload = {"query": query, "resultsCount": limit}
    if db_key and db_key != "all":
        payload["metadataFilters"] = [{
            "key": "db",
            "conditions": [{"operation": "EQUAL", "stringValue": db_key}]
        }]

    print(f'\nクエリ: "{query}"  DB: {db_key or "all（全DB）"}')
    print("-" * 50)
    result = gemini_req("POST", f"{corpus_name}:query", payload)
    if not result or not result.get("relevantChunks"):
        print("  ヒットなし")
        return

    for i, chunk in enumerate(result["relevantChunks"]):
        score = chunk.get("chunkRelevanceScore", 0)
        data  = chunk.get("chunk", {})
        text  = data.get("data", {}).get("stringValue", "")[:120]
        meta  = {m["key"]: m.get("stringValue", "") for m in data.get("customMetadata", [])}
        print(f"[{i+1}] score={score:.3f}  db={meta.get('db','')}  title={meta.get('title','')}")
        print(f"     {text}...")
        print()

# ─────────────────────────────────────────────
# エントリポイント
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Notion → Gemini Corpus 同期ツール")
    parser.add_argument("--init",       action="store_true", help="コーパス作成 + 全件投入（初回）")
    parser.add_argument("--sync",       action="store_true", help="差分同期（変更ページのみ）")
    parser.add_argument("--reset",      action="store_true", help="コーパスを削除して状態リセット")
    parser.add_argument("--query",      type=str,            help="テスト検索クエリ")
    parser.add_argument("--db",         type=str, default=None, help="絞り込みDBキー（query時）")
    parser.add_argument("--limit",      type=int, default=5,    help="取得件数（デフォルト: 5）")
    parser.add_argument("--gemini-key", type=str, default=None, help="Gemini APIキー（環境変数 GEMINI_API_KEY の代わりに指定）")
    parser.add_argument("--notion-key", type=str, default=None, help="Notion APIキー（環境変数 NOTION_API_KEY の代わりに指定）")
    args = parser.parse_args()

    # CLI引数が指定された場合はグローバル変数を上書き
    global GEMINI_API_KEY, NOTION_API_KEY, NOTION_HEADERS
    if args.gemini_key:
        GEMINI_API_KEY = args.gemini_key
    if args.notion_key:
        NOTION_API_KEY = args.notion_key
        NOTION_HEADERS["Authorization"] = f"Bearer {NOTION_API_KEY}"

    if not GEMINI_API_KEY:
        print("ERROR: Gemini APIキーが未設定です。")
        print("  --gemini-key YOUR_KEY を付けるか、環境変数 GEMINI_API_KEY を設定してください。")
        sys.exit(1)
    if not NOTION_API_KEY:
        print("ERROR: Notion APIキーが未設定です。")
        print("  --notion-key YOUR_KEY を付けるか、環境変数 NOTION_API_KEY を設定してください。")
        sys.exit(1)

    if args.reset:
        state = load_state()
        corpus_name = state.get("corpus_name")
        if corpus_name:
            delete_corpus(corpus_name)
        STATE_FILE.unlink(missing_ok=True)
        print("リセット完了。--init で再初期化してください。")
    elif args.init:
        sync_all(force=True)
    elif args.sync:
        sync_all(force=False)
    elif args.query:
        test_query(args.query, args.db, args.limit)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
