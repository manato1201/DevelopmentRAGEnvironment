"""
notion_bulk_add.py — Notion DB への一括データ投入スクリプト

使い方:
    # YAMLリストから投入
    uv run python scripts/notion_bulk_add.py --input scripts/notion_bulk_input.yaml

    # ローカルMarkdownファイルから投入
    uv run python scripts/notion_bulk_add.py --input scripts/notion_bulk_input.yaml --mode md

    # ドライラン（実際には追加しない）
    uv run python scripts/notion_bulk_add.py --input scripts/notion_bulk_input.yaml --dry-run

必要な環境変数 (.env):
    NOTION_API_KEY  — Notion Integration Token
    GEMINI_API_KEY  — Google AI Studio API Key（要約自動生成用）

入力YAMLフォーマット (notion_bulk_input.yaml):
    - title: "Unity HDRP — ライトベイク入門"
      source_url: "https://docs.unity3d.com/..."
      tags: ["Unity", "Shader"]
      db: tool_docs        # tool_docs / game_info / research / team_notes
      summary: ""          # 空にするとGeminiで自動生成（URLまたはmd_pathが必要）
      md_path: ""          # ローカルMarkdownパス（summaryが空の場合に使用）
"""

import os
import sys
import json
import time
import argparse
import textwrap
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
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

NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type":   "application/json",
}

SUMMARY_PROMPT = textwrap.dedent("""\
    以下のドキュメントを100字以内で要約してください。
    専門用語はそのまま残してください。
    箇条書きや改行は使わず、1文で完結させてください。

    {text}
""")

# ─────────────────────────────────────────────
# Gemini — 要約生成
# ─────────────────────────────────────────────

def generate_summary(text: str) -> str:
    if not GEMINI_API_KEY:
        return ""
    # 長すぎる場合は先頭2000字で要約
    truncated = text[:2000] if len(text) > 2000 else text
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": SUMMARY_PROMPT.format(text=truncated)}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 200},
    }
    try:
        res = requests.post(url, json=payload, timeout=30)
        res.raise_for_status()
        data = res.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"  [warn] Gemini summary failed: {e}", file=sys.stderr)
        return ""


def fetch_page_text(url: str) -> str:
    """URLからテキストを取得（markdownへの変換はmarkitdownに委ねる）"""
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(url)
        return result.text_content[:3000]
    except ImportError:
        # markitdownなければrequestsでrawテキスト取得
        try:
            res = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            res.raise_for_status()
            # タグを粗くstrip
            import re
            text = re.sub(r"<[^>]+>", " ", res.text)
            text = re.sub(r"\s+", " ", text)
            return text[:3000]
        except Exception as e:
            print(f"  [warn] URL fetch failed: {e}", file=sys.stderr)
            return ""
    except Exception as e:
        print(f"  [warn] MarkItDown failed: {e}", file=sys.stderr)
        return ""

# ─────────────────────────────────────────────
# Notion — ページ作成
# ─────────────────────────────────────────────

def create_notion_page(
    db_key: str,
    title: str,
    summary: str,
    tags: list[str],
    source_url: str,
    collected_at: str,
    dry_run: bool = False,
) -> dict | None:
    db_id = DB_IDS.get(db_key)
    if not db_id:
        print(f"  [error] 不明なDBキー: {db_key}")
        return None

    properties: dict = {
        "title": {
            "title": [{"type": "text", "text": {"content": title}}]
        },
        "category": {
            "select": {"name": db_key}
        },
        "collected_at": {
            "date": {"start": collected_at}
        },
    }

    if summary:
        properties["summary"] = {
            "rich_text": [{"type": "text", "text": {"content": summary[:2000]}}]
        }

    if tags:
        properties["tags"] = {
            "multi_select": [{"name": t} for t in tags]
        }

    if source_url:
        properties["source_url"] = {"url": source_url}

    payload = {
        "parent": {"database_id": db_id},
        "properties": properties,
    }

    if dry_run:
        print(f"  [dry-run] → {db_key} / {title[:60]}")
        print(f"    summary: {summary[:80]}...")
        return {"id": "dry-run"}

    try:
        res = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json=payload,
            timeout=20,
        )
        res.raise_for_status()
        page = res.json()
        return page
    except requests.HTTPError as e:
        print(f"  [error] Notion API: {e} — {res.text[:200]}", file=sys.stderr)
        return None

# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def process_entry(entry: dict, today: str, dry_run: bool) -> bool:
    title      = entry.get("title", "").strip()
    db_key     = entry.get("db", "tool_docs").strip()
    tags       = entry.get("tags", [])
    source_url = entry.get("source_url", "").strip()
    summary    = entry.get("summary", "").strip()
    md_path    = entry.get("md_path", "").strip()
    collected  = entry.get("collected_at", today)

    if not title:
        print("  [skip] titleが空のエントリをスキップ")
        return False

    print(f"\n▶ {title[:70]}")

    # summaryが空の場合は自動生成
    if not summary:
        text = ""
        if md_path and Path(md_path).exists():
            text = Path(md_path).read_text(encoding="utf-8")[:3000]
            print(f"  [md] {md_path}")
        elif source_url:
            print(f"  [fetch] {source_url[:60]}...")
            text = fetch_page_text(source_url)

        if text and GEMINI_API_KEY:
            print("  [gemini] 要約生成中...")
            summary = generate_summary(text)
            if summary:
                print(f"  [summary] {summary[:80]}")
        else:
            print("  [warn] summaryを生成できません（GEMINI_API_KEYが未設定またはテキスト取得失敗）")

    page = create_notion_page(
        db_key=db_key,
        title=title,
        summary=summary,
        tags=tags,
        source_url=source_url,
        collected_at=collected,
        dry_run=dry_run,
    )

    if page:
        page_id = page.get("id", "?")
        print(f"  ✅ 追加完了: {page_id[:8]}...")
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Notion DBへ一括データ投入")
    parser.add_argument("--input", "-i", required=True, help="入力YAMLファイルパス")
    parser.add_argument("--dry-run", action="store_true", help="実際には追加しない")
    parser.add_argument("--delay", type=float, default=0.5, help="API呼び出し間隔（秒）")
    args = parser.parse_args()

    if not NOTION_API_KEY and not args.dry_run:
        print("[error] NOTION_API_KEY が設定されていません。.env を確認してください。")
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[error] 入力ファイルが見つかりません: {input_path}")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        entries = yaml.safe_load(f)

    if not isinstance(entries, list):
        print("[error] YAMLのルートはリスト形式にしてください")
        sys.exit(1)

    from datetime import date
    today = date.today().isoformat()

    print(f"{'[dry-run] ' if args.dry_run else ''}エントリ数: {len(entries)}")
    success, failed = 0, 0

    for entry in entries:
        ok = process_entry(entry, today, args.dry_run)
        if ok:
            success += 1
        else:
            failed += 1
        time.sleep(args.delay)

    print(f"\n完了: {success}件追加, {failed}件失敗")


if __name__ == "__main__":
    main()
