#!/usr/bin/env python3
"""
sync_houdini21_db.py — Notion houdini21DB → LocalRAG 同期スクリプト

Notion の houdini21DB（80ページ）を取得し、localRAG/houdini21/ に
Markdown ファイルとして書き出す。auto_index.py が差分を検知して
ChromaDB（namespace: houdini21）に自動インデックス化する。

Usage:
    python scripts/sync_houdini21_db.py [--index]

Env:
    NOTION_API_KEY   必須

Options:
    --index     同期後に auto_index.py を即時実行してインデックスも更新
    --dry-run   ファイルを書き出さず、取得ページ数だけ表示
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ─── 設定 ─────────────────────────────────────────────────────────────────────
# houdini21DB のページID（Notion DB ページ）
HOUDINI21_DB_ID = "731bf1bfe6b24d14a7b84b8ad5bdd402"

_PROJECT_ROOT = Path(__file__).parent.parent
_OUTPUT_DIR   = _PROJECT_ROOT / "localRAG" / "houdini21"

_NOTION_VERSION = "2022-06-28"
_NOTION_BASE    = "https://api.notion.com/v1"

# ブロックタイプ → Markdown プレフィックスのマッピング
_BLOCK_PREFIX = {
    "heading_1": "# ",
    "heading_2": "## ",
    "heading_3": "### ",
    "paragraph": "",
    "bulleted_list_item": "- ",
    "numbered_list_item": "1. ",
    "quote": "> ",
    "callout": "> ",
}


# ─── Notion API ヘルパー ────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = __import__("os").environ.get("NOTION_API_KEY", "")
    if not key:
        print("[sync] エラー: 環境変数 NOTION_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)
    return key


def _notion_request(url: str, method: str = "GET", body: dict | None = None, api_key: str = "") -> dict:
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization",  f"Bearer {api_key}")
    req.add_header("Notion-Version", _NOTION_VERSION)
    req.add_header("Content-Type",   "application/json")

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt
                print(f"[sync] Rate limit hit. {wait}秒待機...", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"リトライ上限に達しました: {url}")


def _query_database(db_id: str, api_key: str) -> list[dict]:
    """データベース内の全ページを取得（ページネーション対応）"""
    pages: list[dict] = []
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp   = _notion_request(f"{_NOTION_BASE}/databases/{db_id}/query", "POST", body, api_key)
        pages += resp.get("results", [])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return pages


def _get_page_blocks(page_id: str, api_key: str) -> list[dict]:
    """ページのブロック一覧を取得（ページネーション対応）"""
    blocks: list[dict] = []
    cursor = None
    while True:
        url = f"{_NOTION_BASE}/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        resp   = _notion_request(url, api_key=api_key)
        blocks += resp.get("results", [])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return blocks


# ─── 変換ヘルパー ────────────────────────────────────────────────────────────────

def _rich_text_to_plain(rich_text: list[dict]) -> str:
    return "".join(t.get("plain_text", "") for t in rich_text)


def _blocks_to_markdown(blocks: list[dict]) -> str:
    lines: list[str] = []
    in_code_block = False

    for b in blocks:
        btype = b.get("type", "")
        inner = b.get(btype, {})
        rich  = inner.get("rich_text", [])
        text  = _rich_text_to_plain(rich)

        if btype == "code":
            lang  = inner.get("language", "")
            code  = text
            lines.append(f"```{lang}")
            lines.append(code)
            lines.append("```")
        elif btype == "divider":
            lines.append("---")
        elif btype == "table_row":
            cells = [_rich_text_to_plain(c) for c in inner.get("cells", [])]
            lines.append("| " + " | ".join(cells) + " |")
        elif btype in _BLOCK_PREFIX:
            prefix = _BLOCK_PREFIX[btype]
            if text:
                lines.append(f"{prefix}{text}")
        # child_page, image, embed などはスキップ

    return "\n".join(lines)


def _safe_filename(title: str) -> str:
    """ファイル名として安全な文字列に変換"""
    title = re.sub(r'[\\/:*?"<>|]', "_", title)
    title = title.strip().replace(" ", "_")
    return title[:100] or "untitled"


def _extract_page_title(page: dict) -> str:
    props = page.get("properties", {})
    for key in ("title", "Name", "名前"):
        if key in props:
            rt = props[key].get("title", [])
            if rt:
                return _rich_text_to_plain(rt)
    return page.get("id", "untitled")


def _extract_page_tags(page: dict) -> list[str]:
    props = page.get("properties", {})
    tags_prop = props.get("tags", {})
    if tags_prop.get("type") == "multi_select":
        return [opt.get("name", "") for opt in tags_prop.get("multi_select", [])]
    return []


# ─── メイン ─────────────────────────────────────────────────────────────────────

def sync(dry_run: bool = False, run_index: bool = False) -> None:
    api_key = _get_api_key()

    print(f"[sync] houdini21DB ({HOUDINI21_DB_ID}) を取得中...", flush=True)
    pages = _query_database(HOUDINI21_DB_ID, api_key)
    print(f"[sync] {len(pages)} ページ取得", flush=True)

    if dry_run:
        for p in pages:
            title = _extract_page_title(p)
            tags  = _extract_page_tags(p)
            print(f"  [{', '.join(tags)}] {title}")
        return

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 既存ファイルを把握しておく（削除されたページを検出するため）
    existing_files = {f.stem: f for f in _OUTPUT_DIR.glob("*.md")}
    synced_stems:  set[str] = set()

    for i, page in enumerate(pages, 1):
        title    = _extract_page_title(page)
        tags     = _extract_page_tags(page)
        page_id  = page["id"]
        last_edited = page.get("last_edited_time", "")
        stem     = _safe_filename(title)

        # コンテンツ取得
        try:
            blocks = _get_page_blocks(page_id, api_key)
        except Exception as e:
            print(f"[sync] [{i}/{len(pages)}] スキップ (取得エラー): {title} — {e}", flush=True)
            continue

        body_md = _blocks_to_markdown(blocks)

        # Markdown ファイルのヘッダー（メタデータ）
        tag_str = ", ".join(tags)
        md_content = (
            f"---\n"
            f"source: notion/houdini21/{page_id}\n"
            f"title: {title}\n"
            f"tags: {tag_str}\n"
            f"last_edited: {last_edited}\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"{body_md}\n"
        )

        out_path = _OUTPUT_DIR / f"{stem}.md"
        out_path.write_text(md_content, encoding="utf-8")
        synced_stems.add(stem)
        print(f"[sync] [{i}/{len(pages)}] 書き出し: {stem}.md  ({len(body_md)} chars)", flush=True)

        # Notion API レート制限対策（1秒に3リクエスト以内）
        if i % 10 == 0:
            time.sleep(0.5)

    # 削除されたページのファイルを削除
    for stem, fpath in existing_files.items():
        if stem not in synced_stems:
            fpath.unlink()
            print(f"[sync] 削除: {fpath.name}（Notionから消えたページ）", flush=True)

    print(f"\n[sync] 完了: {len(synced_stems)} ファイル → {_OUTPUT_DIR}", flush=True)

    if run_index:
        import subprocess
        index_script = Path(__file__).parent / "auto_index.py"
        if index_script.exists():
            print("[sync] auto_index.py を実行中...", flush=True)
            subprocess.run([sys.executable, str(index_script), "--once"], check=True)
        else:
            print("[sync] auto_index.py が見つかりません。手動でインデックス化してください。", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Notion houdini21DB → LocalRAG 同期")
    parser.add_argument("--dry-run", action="store_true", help="ページ一覧を表示のみ（書き出さない）")
    parser.add_argument("--index",   action="store_true", help="同期後に auto_index.py を実行")
    args = parser.parse_args()
    sync(dry_run=args.dry_run, run_index=args.index)


if __name__ == "__main__":
    main()
