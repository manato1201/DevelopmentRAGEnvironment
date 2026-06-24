"""
localrag_to_notion.py — LocalRAG vault の Markdown を Notion DBに一括投入

ファイル名プレフィックス → Notion DB マッピング（--map で上書き可）:
  afuri*    → afuri
  braintq*  → braintq
  fourteen* → fourteen
  その他    → tool_docs

使い方:
    # ドライラン（実際には投入しない）
    uv run python scripts/localrag_to_notion.py --dry-run

    # 実行（APIキーを直接指定）
    uv run python scripts/localrag_to_notion.py --notion-key YOUR_KEY

    # 特定のフォルダのみ
    uv run python scripts/localrag_to_notion.py --notion-key KEY --folder personal_notes

    # カスタムマッピング追加
    uv run python scripts/localrag_to_notion.py --notion-key KEY --map tutorials:tool_docs
"""

import os
import re
import sys
import json
import time
import argparse
from pathlib import Path

# Windows でのコンソール文字化け対策
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import requests
import yaml

# .envは使わない
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")

VAULT_DIR = Path(__file__).parent.parent / "localRAG"

DB_IDS = {
    "tool_docs":  os.environ.get("DB_TOOL_DOCS",  "249e442a-47dd-4a8d-95a8-8b856fb91ef6"),
    "game_info":  os.environ.get("DB_GAME_INFO",  "f201f73c-45dc-44cb-b8d7-a7be81b3644c"),
    "research":   os.environ.get("DB_RESEARCH",   "714d4d4a-6a85-4aa1-845c-32dc3e1a2b1f"),
    "team_notes": os.environ.get("DB_TEAM_NOTES", "f898bf03-8c9f-40e0-9e1b-a28432703d69"),
    "afuri":      os.environ.get("DB_AFURI",      "a74822790ec34768bdef0917abae3e6f"),
    "braintq":    os.environ.get("DB_BRAINTQ",    "847b7db0f29f4190bee9f7ae7dd15514"),
    "fourteen":   os.environ.get("DB_FOURTEEN",   "475cf278492a45ac90cbe4b8f11df1f5"),
}

# デフォルトのファイル名プレフィックス → DB マッピング
DEFAULT_PREFIX_MAP = {
    "afuri":    "afuri",
    "braintq":  "braintq",
    "fourteen": "fourteen",
}

# ─────────────────────────────────────────────
# Markdown パーサー
# ─────────────────────────────────────────────

def parse_md(path: Path) -> dict | None:
    """Markdown ファイルをパースして {title, summary, tags, source_url, body} を返す"""
    text = path.read_text(encoding="utf-8")

    meta: dict = {}
    body = text

    # frontmatter 抽出
    if text.startswith("---"):
        try:
            end = text.index("---", 3)
            meta = yaml.safe_load(text[3:end]) or {}
            body = text[end + 3:].strip()
        except Exception:
            pass

    # rag_indexed: false のファイルはスキップ
    if str(meta.get("rag_indexed", "true")).lower() == "false":
        return None

    # タイトル（frontmatter > 本文 H1 > ファイル名）
    title = meta.get("title", "")
    if not title:
        h1 = re.search(r"^#\s+(.+)", body, re.MULTILINE)
        title = h1.group(1).strip() if h1 else path.stem.replace("_", " ")

    # タグ
    raw_tags = meta.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    tags = [str(t) for t in raw_tags]

    # source_url（frontmatter or 本文の最初のURL）
    source_url = str(meta.get("source_url", "") or "")
    if not source_url:
        url_match = re.search(r"https?://\S+", body)
        if url_match:
            source_url = url_match.group(0).rstrip(")")

    # summary（本文から最初の意味ある段落を 300字以内で）
    summary = str(meta.get("summary", "") or "")
    if not summary:
        # 見出し・空行・コードブロックを除いた最初の段落
        in_code = False
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped.startswith(">"):
                continue
            # Markdown の **bold** などを除去
            clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", stripped)
            clean = re.sub(r"`[^`]+`", "", clean)
            clean = clean.strip()
            if len(clean) > 20:
                summary = clean[:300]
                break

    return {
        "title":      title[:200],
        "summary":    summary[:500],
        "tags":       tags,
        "source_url": source_url,
        "body":       body,
        "file_path":  str(path),
    }


# ─────────────────────────────────────────────
# DB 判定
# ─────────────────────────────────────────────

def resolve_db(filename: str, prefix_map: dict) -> str:
    """ファイル名からターゲット DB キーを決定する"""
    stem = Path(filename).stem.lower()
    for prefix, db_key in prefix_map.items():
        if stem.startswith(prefix.lower()):
            return db_key
    return "tool_docs"


# ─────────────────────────────────────────────
# Notion 投入
# ─────────────────────────────────────────────

def get_headers() -> dict:
    return {
        "Authorization":  f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json",
    }


# Markdown コードフェンスの言語名 → Notion 許容値マッピング
_NOTION_LANG: dict[str, str] = {
    "csharp": "c#", "cs": "c#", "c#": "c#",
    "cpp": "c++", "c++": "c++",
    "js": "javascript", "javascript": "javascript",
    "ts": "typescript", "typescript": "typescript",
    "py": "python", "python": "python",
    "sh": "shell", "bash": "bash", "shell": "shell",
    "json": "json", "yaml": "yaml", "yml": "yaml",
    "sql": "sql", "html": "html", "css": "css",
    "go": "go", "rust": "rust", "java": "java",
    "kotlin": "kotlin", "swift": "swift", "ruby": "ruby",
    "php": "php", "scala": "scala", "lua": "lua",
    "markdown": "markdown", "md": "markdown",
    "xml": "xml", "powershell": "powershell", "ps1": "powershell",
    "plain text": "plain text", "plaintext": "plain text",
    "text": "plain text", "": "plain text",
}


def _notion_lang(raw: str) -> str:
    return _NOTION_LANG.get(raw.lower(), "plain text")


def clean_md(text: str) -> str:
    """Markdownの装飾記号を除去してプレーンテキスト化"""
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)  # **bold** / *italic*
    text = re.sub(r"`([^`]+)`", r"\1", text)                # `inline code`
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)   # [text](url)
    return text.strip()


def body_to_notion_blocks(body: str) -> list[dict]:
    """Markdown本文をNotionブロック配列に変換"""
    blocks = []
    in_code   = False
    code_lines: list[str] = []
    code_lang  = "plain text"

    for line in body.splitlines():
        stripped = line.rstrip()

        # ── コードブロック ──────────────────────────────
        if stripped.startswith("```"):
            if not in_code:
                in_code    = True
                code_lines = []
                code_lang  = stripped[3:].strip() or "plain text"
            else:
                in_code = False
                if code_lines:
                    code_text = "\n".join(code_lines)[:2000]
                    blocks.append({
                        "object": "block",
                        "type":   "code",
                        "code": {
                            "rich_text": [{"type": "text", "text": {"content": code_text}}],
                            "language":  _notion_lang(code_lang),
                        },
                    })
                code_lines = []
            continue
        if in_code:
            code_lines.append(stripped)
            continue

        # ── 水平線はスキップ ────────────────────────────
        if stripped in ("---", "***", "___"):
            continue

        # ── テーブル行 ──────────────────────────────────
        if stripped.startswith("|"):
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                continue  # |---|---| 区切り行
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if cells:
                text = " / ".join(clean_md(c) for c in cells)
                if text:
                    blocks.append({
                        "object": "block",
                        "type":   "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
                    })
            continue

        # ── 通常ブロック ────────────────────────────────
        if stripped.startswith("### "):
            btype, text = "heading_3", stripped[4:]
        elif stripped.startswith("## "):
            btype, text = "heading_2", stripped[3:]
        elif stripped.startswith("# "):
            btype, text = "heading_1", stripped[2:]
        elif stripped.startswith("- ") or stripped.startswith("* "):
            btype, text = "bulleted_list_item", stripped[2:]
        elif re.match(r"^\d+\. ", stripped):
            btype, text = "numbered_list_item", re.sub(r"^\d+\. ", "", stripped)
        elif stripped.startswith("> "):
            btype, text = "quote", stripped[2:]
        elif not stripped:
            continue
        else:
            btype, text = "paragraph", stripped

        text = clean_md(text)[:2000]
        if not text:
            continue

        blocks.append({
            "object": "block",
            "type":   btype,
            btype: {"rich_text": [{"type": "text", "text": {"content": text}}]},
        })

    return blocks


def find_existing_pages(db_id: str, title: str) -> list[str]:
    """同じタイトルの既存ページIDを返す"""
    res = requests.post(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        headers=get_headers(),
        json={"filter": {"property": "title", "title": {"equals": title}}},
        timeout=30,
    )
    if res.status_code != 200:
        return []
    return [p["id"] for p in res.json().get("results", [])]


def archive_page(page_id: str) -> None:
    """Notionページをアーカイブ（論理削除）"""
    requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=get_headers(),
        json={"archived": True},
        timeout=30,
    )
    time.sleep(0.2)


def append_blocks_to_page(page_id: str, blocks: list[dict]) -> bool:
    """100ブロックずつに分割して Notion ページに追記"""
    for i in range(0, len(blocks), 100):
        chunk = blocks[i : i + 100]
        res = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=get_headers(),
            json={"children": chunk},
            timeout=30,
        )
        if res.status_code not in (200, 201):
            print(f"     ❌ ブロック追加エラー {res.status_code}: {res.text[:200]}")
            return False
        time.sleep(0.3)
    return True


def create_notion_page(db_key: str, data: dict, dry_run: bool = False) -> bool:
    db_id = DB_IDS.get(db_key)
    if not db_id:
        print(f"  ⚠️  不明なDBキー: {db_key}")
        return False

    title   = data["title"]
    summary = data["summary"]
    tags    = data["tags"]
    url     = data["source_url"]
    body    = data.get("body", "")

    # 本文をNotionブロックに変換
    blocks = body_to_notion_blocks(body)

    print(f"  → [{db_key}] {title}  ({len(blocks)}ブロック, {len(body)}文字)")
    if dry_run:
        print(f"     summary: {summary[:80]}...")
        print(f"     tags: {tags}")
        return True

    # 既存の同名ページをアーカイブ（重複防止）
    existing = find_existing_pages(db_id, title)
    for eid in existing:
        archive_page(eid)
        print(f"     ♻️  既存ページをアーカイブ: {eid}")

    props: dict = {
        "title": {"title": [{"text": {"content": title}}]},
    }
    if summary:
        props["summary"] = {"rich_text": [{"text": {"content": summary}}]}
    if tags:
        props["tags"] = {"multi_select": [{"name": t} for t in tags[:10]]}
    if url:
        props["source_url"] = {"url": url}

    # 最初の100ブロックをページ作成時に同時送信
    payload: dict = {
        "parent":     {"database_id": db_id},
        "properties": props,
    }
    if blocks:
        payload["children"] = blocks[:100]

    res = requests.post(
        "https://api.notion.com/v1/pages",
        headers=get_headers(),
        json=payload,
        timeout=30,
    )

    if res.status_code not in (200, 201):
        print(f"     ❌ Notion エラー {res.status_code}: {res.text[:200]}")
        return False

    # 101ブロック以降は追記
    if len(blocks) > 100:
        page_id = res.json().get("id", "")
        if page_id:
            time.sleep(0.3)
            append_blocks_to_page(page_id, blocks[100:])

    return True


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def collect_files(folder: str | None) -> list[Path]:
    """Vault から対象 Markdown ファイルを収集（_ 始まりディレクトリを除外）"""
    root = VAULT_DIR / folder if folder else VAULT_DIR
    files = []
    for p in root.rglob("*.md"):
        # _ または . 始まりのディレクトリを除外
        if any(part.startswith(("_", ".")) for part in p.parts):
            continue
        files.append(p)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="LocalRAG Markdown を Notion に一括投入")
    parser.add_argument("--notion-key", type=str, default=None, help="Notion API キー")
    parser.add_argument("--dry-run",   action="store_true",    help="ドライラン（投入しない）")
    parser.add_argument("--folder",    type=str, default=None, help="対象フォルダ名（例: personal_notes）")
    parser.add_argument("--map",       type=str, nargs="*", default=[],
                        help="プレフィックス:DB マッピング追加（例: tutorials:tool_docs）")
    args = parser.parse_args()

    # API キー設定
    global NOTION_API_KEY
    if args.notion_key:
        NOTION_API_KEY = args.notion_key
    if not NOTION_API_KEY and not args.dry_run:
        print("ERROR: Notion APIキーが未設定です。--notion-key KEY を指定してください。")
        sys.exit(1)

    # プレフィックスマップ構築
    prefix_map = dict(DEFAULT_PREFIX_MAP)
    for entry in args.map:
        if ":" in entry:
            prefix, db = entry.split(":", 1)
            prefix_map[prefix.strip()] = db.strip()

    mode = "ドライラン" if args.dry_run else "実行"
    print(f"=== LocalRAG → Notion 移行 ({mode}) ===")
    print(f"Vault: {VAULT_DIR}")
    print(f"プレフィックスマップ: {prefix_map}")
    print()

    files = collect_files(args.folder)
    if not files:
        print("対象ファイルが見つかりませんでした。")
        sys.exit(0)

    print(f"対象ファイル: {len(files)} 件\n")

    ok = skip = err = 0
    for path in files:
        data = parse_md(path)
        if data is None:
            print(f"  SKIP (rag_indexed:false): {path.name}")
            skip += 1
            continue

        db_key = resolve_db(path.name, prefix_map)
        result = create_notion_page(db_key, data, dry_run=args.dry_run)

        if result:
            ok += 1
        else:
            err += 1

        if not args.dry_run:
            time.sleep(0.4)  # レート制限対策

    print()
    print("=" * 50)
    print(f"完了  投入: {ok}件  スキップ: {skip}件  エラー: {err}件")
    if args.dry_run:
        print("※ ドライランのため実際には投入していません。--dry-run を外して再実行してください。")
    else:
        print("\n次のステップ: GASエディタで syncNotionToSheets() を実行してください。")


if __name__ == "__main__":
    main()
