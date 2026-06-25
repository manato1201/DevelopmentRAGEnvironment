#!/usr/bin/env python3
"""
document_pipeline.py — Claude 不要のドキュメント化・インデックス化パイプライン

ファイル変換（markitdown）→ heading ベースチャンキング → localRAG vault 出力
→ auto_index.py が差分インデックス化

Usage:
    # 単一ファイルを変換して vault に追加
    python scripts/document_pipeline.py add path/to/file.pdf --namespace tool_docs

    # ディレクトリ全体を処理
    python scripts/document_pipeline.py add path/to/dir/ --namespace research

    # 変換結果を確認だけ（実際には書き込まない）
    python scripts/document_pipeline.py add path/to/file.pdf --dry-run

    # 今すぐインデックス化も実行
    python scripts/document_pipeline.py add path/to/file.pdf --index

    # テンプレートを生成
    python scripts/document_pipeline.py template meeting --output notes/

    # インデックス化だけ実行
    python scripts/document_pipeline.py index

Supported file types:
    .md .txt .pdf .pptx .ppt .docx .doc .xlsx .xls .html
    （markitdown が対応していれば自動変換）
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ─── パス設定 ────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent
_MCP_RAG_DIR = _PROJECT_ROOT.parent / "mcp-rag-server"
_VAULT_DIR = _PROJECT_ROOT / "localRAG"

# ─── サポートする拡張子 ─────────────────────────────────────────────────────────
_DIRECT_READ = {".md", ".txt", ".markdown"}
_CONVERT_VIA_MARKITDOWN = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".html", ".htm"}
_ALL_SUPPORTED = _DIRECT_READ | _CONVERT_VIA_MARKITDOWN

# ─── namespaces ─────────────────────────────────────────────────────────────────
NAMESPACES = ["tool_docs", "game_info", "research", "team_notes", "personal_notes"]


# ─── チャンキング ────────────────────────────────────────────────────────────────

def chunk_by_headings(text: str, max_chunk: int = 800, overlap: int = 80) -> list[dict]:
    """
    Markdown の見出し（#, ##, ###）を区切りとしてチャンク分割する。
    見出しのない平文は段落ベースで分割する。
    各チャンクに heading パスを付与する（パンくずリスト相当）。

    Returns: [{"heading": "h1 > h2", "body": "...", "level": 2}, ...]
    """
    lines = text.splitlines(keepends=True)

    # 見出し行のインデックスを収集
    heading_pattern = re.compile(r"^(#{1,3})\s+(.+)")
    segments: list[tuple[int, int, str]] = []  # (line_index, level, title)

    for i, line in enumerate(lines):
        m = heading_pattern.match(line)
        if m:
            segments.append((i, len(m.group(1)), m.group(2).strip()))

    if not segments:
        # 見出しなし → 段落ベースで分割
        return _chunk_paragraphs(text, max_chunk, overlap)

    # 見出しごとにセクションを作る
    chunks: list[dict] = []
    heading_stack: list[tuple[int, str]] = []  # [(level, title), ...]

    for idx, (line_i, level, title) in enumerate(segments):
        end_line = segments[idx + 1][0] if idx + 1 < len(segments) else len(lines)
        body = "".join(lines[line_i:end_line]).strip()

        # パンくず更新
        heading_stack = [h for h in heading_stack if h[0] < level]
        heading_stack.append((level, title))
        heading_path = " > ".join(t for _, t in heading_stack)

        if len(body) <= max_chunk:
            chunks.append({"heading": heading_path, "body": body, "level": level})
        else:
            # 長すぎる場合はさらに段落で分割
            sub = _chunk_paragraphs(body, max_chunk, overlap)
            for i, s in enumerate(sub):
                s["heading"] = heading_path + (f" [{i+1}]" if len(sub) > 1 else "")
                s["level"] = level
            chunks.extend(sub)

    return chunks


def _chunk_paragraphs(text: str, max_chunk: int, overlap: int) -> list[dict]:
    """段落（空行区切り）でチャンク分割するフォールバック。"""
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[dict] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chunk:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append({"heading": "", "body": current, "level": 0})
            # overlap: 前のチャンクの末尾を引き継ぐ
            tail = current[-overlap:] if overlap and current else ""
            current = (tail + "\n\n" + para).strip() if tail else para

    if current:
        chunks.append({"heading": "", "body": current, "level": 0})

    return chunks


# ─── ファイル変換 ────────────────────────────────────────────────────────────────

def convert_to_markdown(file_path: Path) -> str:
    """ファイルを Markdown テキストに変換する（markitdown 使用）。"""
    ext = file_path.suffix.lower()

    if ext in _DIRECT_READ:
        return file_path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")

    if ext in _CONVERT_VIA_MARKITDOWN:
        try:
            import markitdown as _md
            result = _md.MarkItDown().convert(str(file_path))
            return result.markdown.replace("\x00", "")
        except ImportError:
            print("[警告] markitdown が未インストールです。mcp-rag-server 環境で実行してください。")
            sys.exit(1)
        except Exception as e:
            print(f"[警告] 変換失敗 ({file_path.name}): {e}")
            return ""

    print(f"[スキップ] 非対応の拡張子: {file_path.suffix}")
    return ""


# ─── Frontmatter 生成 ────────────────────────────────────────────────────────────

def _make_frontmatter(source_path: Path, namespace: str, chunk_index: int,
                      total_chunks: int, heading: str) -> str:
    today = datetime.date.today().isoformat()
    return (
        "---\n"
        f"source: {source_path.name}\n"
        f"namespace: {namespace}\n"
        f"chunk: {chunk_index + 1}/{total_chunks}\n"
        f"heading: \"{heading}\"\n"
        f"created: {today}\n"
        "status: active\n"
        "---\n\n"
    )


# ─── vault への書き込み ──────────────────────────────────────────────────────────

def process_file(
    file_path: Path,
    namespace: str,
    vault_dir: Path,
    max_chunk: int = 800,
    overlap: int = 80,
    dry_run: bool = False,
) -> int:
    """1ファイルを処理して vault に Markdown チャンクとして書き出す。"""
    print(f"  変換中: {file_path.name}")
    text = convert_to_markdown(file_path)
    if not text.strip():
        print(f"  [スキップ] テキストが空です: {file_path.name}")
        return 0

    chunks = chunk_by_headings(text, max_chunk, overlap)
    total = len(chunks)
    stem = re.sub(r"[^\w\-]", "_", file_path.stem)[:40]

    out_dir = vault_dir / namespace
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks):
        suffix = f"_{i:03d}" if total > 1 else ""
        out_name = f"{stem}{suffix}.md"
        out_path = out_dir / out_name

        frontmatter = _make_frontmatter(file_path, namespace, i, total, chunk["heading"])
        content = frontmatter + chunk["body"]

        if dry_run:
            print(f"    [DRY-RUN] → {out_path.relative_to(vault_dir)}")
            print(f"              heading: {chunk['heading'] or '(なし)'}")
            print(f"              文字数: {len(chunk['body'])}")
        else:
            out_path.write_text(content, encoding="utf-8")
            print(f"    → {out_path.relative_to(vault_dir)}  ({len(chunk['body'])}文字)")

    print(f"  完了: {total} チャンク{'（dry-run）' if dry_run else ''}")
    return total


def process_input(
    input_path: Path,
    namespace: str,
    vault_dir: Path,
    max_chunk: int = 800,
    overlap: int = 80,
    dry_run: bool = False,
) -> int:
    """ファイルまたはディレクトリを処理する。"""
    if input_path.is_file():
        if input_path.suffix.lower() not in _ALL_SUPPORTED:
            print(f"[エラー] 非対応のファイル形式です: {input_path.suffix}")
            return 0
        return process_file(input_path, namespace, vault_dir, max_chunk, overlap, dry_run)

    if input_path.is_dir():
        total = 0
        files = [f for f in sorted(input_path.rglob("*"))
                 if f.is_file() and f.suffix.lower() in _ALL_SUPPORTED]
        print(f"{len(files)} ファイルを検出")
        for f in files:
            total += process_file(f, namespace, vault_dir, max_chunk, overlap, dry_run)
        return total

    print(f"[エラー] パスが見つかりません: {input_path}")
    return 0


# ─── インデックス化 ──────────────────────────────────────────────────────────────

def run_index() -> bool:
    """mcp-rag-server の差分インデックス化を実行する。"""
    if not _MCP_RAG_DIR.exists():
        print(f"[エラー] mcp-rag-server が見つかりません: {_MCP_RAG_DIR}")
        return False

    print("インデックス化を実行中...")
    result = subprocess.run(
        ["uv", "run", "python", "-m", "src.cli", "index", "--incremental"],
        cwd=str(_MCP_RAG_DIR),
    )
    return result.returncode == 0


# ─── テンプレート ────────────────────────────────────────────────────────────────

_TEMPLATES = {
    "meeting": """\
---
source: meeting_{date}.md
namespace: team_notes
status: active
created: {date}
tags: [meeting]
---

# ミーティングメモ — {date}

## 参加者

-

## 議題

1.

## 決定事項

-

## アクションアイテム

| 担当 | タスク | 期限 |
|------|--------|------|
|      |        |      |

## メモ・補足

""",
    "research": """\
---
source: research_{date}.md
namespace: research
status: active
created: {date}
tags: [research]
---

# 調査メモ — {title}

## 概要

（何を調べたか・なぜ調べたか）

## 調査結果

### 分かったこと

-

### 参考資料

-

## 考察・次のアクション

""",
    "tool": """\
---
source: tool_{name}.md
namespace: tool_docs
status: active
created: {date}
tags: [tool]
---

# {name} — ツールドキュメント

## 概要

（何ができるツールか）

## インストール / セットアップ

```bash

```

## 基本的な使い方

### ユースケース 1

```

```

## 注意点・既知の問題

-

## 参考リンク

-
""",
    "knowledge": """\
---
source: knowledge_{date}.md
namespace: personal_notes
status: active
created: {date}
tags: [knowledge]
---

# {title}

## 要点

-

## 詳細

### 背景

### 仕組み

### 実例

## 関連情報

""",
}


def generate_template(kind: str, output_dir: Path) -> None:
    if kind not in _TEMPLATES:
        print(f"[エラー] テンプレート種類: {list(_TEMPLATES.keys())}")
        sys.exit(1)

    today = datetime.date.today().isoformat()
    content = _TEMPLATES[kind].format(date=today, title="タイトルをここに", name="ツール名")
    out = output_dir / f"template_{kind}_{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"テンプレートを生成しました: {out}")


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude 不要のドキュメント化・インデックス化パイプライン",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    # add コマンド
    add_p = sub.add_parser("add", help="ファイル/ディレクトリを vault に追加")
    add_p.add_argument("input", help="ファイルまたはディレクトリのパス")
    add_p.add_argument(
        "--namespace", "-n",
        choices=NAMESPACES,
        default="personal_notes",
        help=f"保存先 namespace（デフォルト: personal_notes）",
    )
    add_p.add_argument("--max-chunk", type=int, default=800, help="最大チャンク文字数（デフォルト: 800）")
    add_p.add_argument("--overlap", type=int, default=80, help="チャンク重複文字数（デフォルト: 80）")
    add_p.add_argument("--vault", default=str(_VAULT_DIR), help="vault ディレクトリのパス")
    add_p.add_argument("--dry-run", action="store_true", help="書き込まずに確認だけ")
    add_p.add_argument("--index", action="store_true", help="vault 追加後にインデックス化も実行")

    # index コマンド
    sub.add_parser("index", help="vault をインデックス化（差分）")

    # template コマンド
    tmpl_p = sub.add_parser("template", help="ドキュメントテンプレートを生成")
    tmpl_p.add_argument("kind", choices=list(_TEMPLATES.keys()), help="テンプレート種類")
    tmpl_p.add_argument("--output", "-o", default=".", help="出力ディレクトリ")

    # collect コマンド（rss_to_rag.py への委譲）
    collect_p = sub.add_parser("collect", help="RSS/Web から記事を収集して vault に追加")
    collect_p.add_argument(
        "--source", "-s",
        choices=["all", "zenn_qiita", "unity_ue", "cedec", "papers"],
        default="all",
        help="収集ソース（デフォルト: all）",
    )
    collect_p.add_argument("--max-per-feed", "-m", type=int, default=5, help="フィードあたりの最大取得件数")
    collect_p.add_argument("--namespace", "-n", choices=NAMESPACES, default=None, help="namespace 強制指定")
    collect_p.add_argument("--vault", default=str(_VAULT_DIR), help="vault ディレクトリ")
    collect_p.add_argument("--dry-run", action="store_true", help="書き込まずに確認")
    collect_p.add_argument("--index", action="store_true", help="収集後にインデックス化")
    collect_p.add_argument("--delay", type=float, default=1.5, help="記事間の待機秒数")
    collect_p.add_argument("--reset-seen", action="store_true", help="処理済みURLリストをリセット")

    args = parser.parse_args()

    if args.cmd == "add":
        input_path = Path(args.input)
        vault_dir = Path(args.vault)
        total = process_input(
            input_path, args.namespace, vault_dir,
            args.max_chunk, args.overlap, args.dry_run,
        )
        print(f"\n合計 {total} チャンクを処理しました")
        if args.index and not args.dry_run:
            ok = run_index()
            print("インデックス化 " + ("完了" if ok else "失敗"))

    elif args.cmd == "index":
        ok = run_index()
        sys.exit(0 if ok else 1)

    elif args.cmd == "template":
        generate_template(args.kind, Path(args.output))

    elif args.cmd == "collect":
        # rss_to_rag.py に処理を委譲
        rss_script = _HERE / "rss_to_rag.py"
        if not rss_script.exists():
            print(f"[エラー] {rss_script} が見つかりません")
            sys.exit(1)
        cmd = [sys.executable, str(rss_script)]
        cmd += ["--source", args.source]
        cmd += ["--max-per-feed", str(args.max_per_feed)]
        cmd += ["--delay", str(args.delay)]
        if args.namespace:
            cmd += ["--namespace", args.namespace]
        if args.vault:
            cmd += ["--vault", args.vault]
        if args.dry_run:
            cmd.append("--dry-run")
        if args.index:
            cmd.append("--index")
        if args.reset_seen:
            cmd.append("--reset-seen")
        import subprocess as _sp
        sys.exit(_sp.run(cmd).returncode)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
