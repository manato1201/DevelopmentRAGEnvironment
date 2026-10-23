#!/usr/bin/env python3
"""Markdown資料を、自己完結のHTML（ダーク／ライト対応・目次つき）に変換する。

使い方（リポジトリのルートで）:
    uv run --with markdown python scripts/build_docs_html.py            # 既定の資料をすべて
    uv run --with markdown python scripts/build_docs_html.py docs/x.md  # 指定した資料だけ

- 出力は、元の`.md`と同じフォルダの`.html`。**HTMLは直接編集しない**（このスクリプトで作り直す）。
- ```mermaid のブロックは、ブラウザ側でmermaid（CDN）が図にする。
- 相対リンクの`.md`は、変換対象（またはHTMLが既にあるもの）なら`.html`に付け替える。
- 外部ライブラリは`markdown`だけ。pyproject.tomlには入れていない（`uv run --with`で、その場で使う）。
"""

from __future__ import annotations

import html
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# 既定の変換対象。(パス, 分類)。分類は、ページ上部のバッジに出す。
LEARNING = [
    "README",
    "01-common-knowledge",
    "02-fundamentals",
    "03-specialized",
    "04-applied",
    "05-scripts",
    "06-maintenance-runbook",
]
DEFAULT_TARGETS: list[tuple[Path, str]] = [
    *[(DOCS / "learning" / f"{n}.md", "座学資料") for n in LEARNING],
    (DOCS / "user-manual.md", "取扱説明書"),
    (DOCS / "houdini-beginner-guide.md", "Houdini入門"),
    (DOCS / "houdini-video-script.md", "動画の台本と音声"),
    (DOCS / "houdini-lesson-design.md", "レッスン設計"),
    (DOCS / "houdini-distribution-plan.md", "配布計画"),
    (DOCS / "manual-houdini-tutorial.md", "取扱説明書（Houdini）"),
    (DOCS / "manual-ragreel.md", "取扱説明書（RAGReel）"),
    (DOCS / "operator-runbook.md", "運営者向け手順書"),
    (DOCS / "cost-and-quota.md", "費用と利用枠"),
    (DOCS / "mcp-integration-guide.md", "外部サービス連携（MCP）"),
    (DOCS / "houdini-tutorial-technical-report.md", "技術解説書（Houdini・動画）"),
    (DOCS / "cloudflare-rag-technical-report.md", "技術解説書（Cloudflare）"),
    (DOCS / "architecture-layering-plan.md", "設計案"),
    (DOCS / "cloudflare-vs-firebase-comparison.md", "比較資料"),
    (DOCS / "comparison-houdini-mcp.md", "比較資料（Houdini × AI）"),
    (DOCS / "security-audit-2026-10-22.md", "セキュリティ点検"),
]

CSS = """
  :root { color-scheme: light dark;
    --bg:#0f1117; --panel:#171a23; --border:#2a2e3a; --text:#e6e8ee; --muted:#9aa1b4;
    --accent:#7aa2ff; --code-bg:#12151d; --warn:#e0b050; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f7f8fb; --panel:#ffffff; --border:#e1e4ec; --text:#1b1e27; --muted:#5b6270;
      --accent:#3358d6; --code-bg:#f0f2f8; --warn:#9a6a00; } }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body { margin:0; background:var(--bg); color:var(--text); line-height:1.85;
    font-family:-apple-system,"Segoe UI","Hiragino Sans","Noto Sans JP","Yu Gothic",sans-serif; }
  .wrap { max-width:920px; margin:0 auto; padding:2rem 1.25rem 6rem; }
  .series { display:flex; flex-wrap:wrap; gap:.4rem; margin-bottom:1.2rem; }
  .series a { font-size:.8rem; padding:.2rem .7rem; border:1px solid var(--border);
    border-radius:999px; color:var(--muted); text-decoration:none; background:var(--panel); }
  .series a.current { color:var(--accent); border-color:var(--accent); font-weight:600; }
  header.hero { border-bottom:1px solid var(--border); padding-bottom:1.2rem; margin-bottom:1.6rem; }
  header.hero h1 { font-size:1.6rem; line-height:1.4; margin:.4rem 0 .6rem; }
  .badge { display:inline-block; background:var(--panel); border:1px solid var(--border);
    border-radius:999px; padding:.15rem .7rem; font-size:.78rem; color:var(--accent); margin-right:.4rem; }
  .meta { color:var(--muted); font-size:.85rem; }
  nav.toc { background:var(--panel); border:1px solid var(--border); border-radius:12px;
    padding:.9rem 1.2rem; margin-bottom:2rem; }
  nav.toc summary { cursor:pointer; font-weight:600; }
  nav.toc ol { margin:.6rem 0 0; padding-left:1.1rem; list-style:none; }
  nav.toc ol ol { margin:.1rem 0 .3rem; font-size:.92em; }
  nav.toc a { color:var(--accent); text-decoration:none; }
  nav.toc a:hover { text-decoration:underline; }
  main h2 { font-size:1.3rem; border-left:4px solid var(--accent); padding-left:.6rem;
    margin:2.6rem 0 1rem; line-height:1.5; }
  main h3 { font-size:1.08rem; margin:2rem 0 .6rem; }
  main h4 { font-size:1rem; margin:1.4rem 0 .4rem; color:var(--muted); }
  main a { color:var(--accent); }
  main p, main li { overflow-wrap:anywhere; }
  hr { border:none; border-top:1px solid var(--border); margin:2rem 0; }
  code { background:var(--code-bg); border:1px solid var(--border); border-radius:5px;
    padding:.08rem .35rem; font-size:.88em; font-family:"Cascadia Mono",Consolas,"SFMono-Regular",monospace; }
  pre { background:var(--code-bg); border:1px solid var(--border); border-radius:10px;
    padding:.9rem 1rem; overflow-x:auto; line-height:1.55; }
  pre code { background:none; border:none; padding:0; font-size:.86rem; }
  blockquote { margin:1.2rem 0; padding:.7rem 1.1rem; background:var(--panel);
    border:1px solid var(--border); border-left:4px solid var(--warn); border-radius:8px; color:var(--text); }
  blockquote p { margin:.4rem 0; }
  .table-scroll { overflow-x:auto; margin:1rem 0; }
  table { border-collapse:collapse; width:100%; font-size:.92rem; background:var(--panel); }
  th, td { border:1px solid var(--border); padding:.45rem .7rem; text-align:left; vertical-align:top; }
  th { background:var(--code-bg); white-space:nowrap; }
  main img { display:block; height:auto; width:min(1500px, 96vw); max-width:none; position:relative; left:50%;
    transform:translateX(-50%); margin:1.2rem 0 .4rem; border:1px solid var(--border); border-radius:12px; background:var(--panel); }
  main a:has(> img) { display:block; }
  @media print { main img { width:100%; left:0; transform:none; } }
  .mermaid { background:var(--panel); border:1px solid var(--border); border-radius:12px;
    padding:1rem; overflow-x:auto; text-align:center; margin:1.2rem 0; }
  ul, ol { padding-left:1.5rem; }
  .pager { display:flex; justify-content:space-between; gap:1rem; margin-top:3rem;
    padding-top:1.2rem; border-top:1px solid var(--border); font-size:.92rem; }
  .pager a { color:var(--accent); text-decoration:none; }
  footer { margin-top:2.5rem; color:var(--muted); font-size:.78rem; }
  #top { position:fixed; right:1rem; bottom:1rem; padding:.4rem .8rem; border-radius:999px;
    background:var(--panel); border:1px solid var(--border); color:var(--accent);
    text-decoration:none; font-size:.8rem; }
  @media (max-width:600px) { .wrap { padding:1.2rem .9rem 5rem; } header.hero h1 { font-size:1.35rem; } }
  @media print { .series, #top, nav.toc { display:none; } body { background:#fff; color:#000; } }
"""


def slugify(value: str, separator: str = "-") -> str:
    """GitHubに近い見出しID（日本語を残す）。資料内の`#...`リンクと揃える。"""
    value = re.sub(r"[`*_]", "", value.strip().lower())
    value = re.sub(r"[^\w\s-]", "", value)
    return re.sub(r"\s+", separator, value)


def dedent_list_fences(text: str) -> str:
    """リスト項目の中の、字下げされたコードブロックを、行頭のブロックに直す。

    python-markdownのfenced_codeは、行頭以外のフェンスを認識しない（GitHubは認識する）。
    直したあとは、コードブロックの前後で、リストが2つに分かれる（番号は、sane_listsで引き継がれる）。
    """
    out: list[str] = []
    lines = text.split("\n")
    i = 0
    fence_re = re.compile(r"^(\s+)(`{3,}|~{3,})(.*)$")
    while i < len(lines):
        m = fence_re.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        indent, fence, info = m.group(1), m.group(2), m.group(3)
        if out and out[-1].strip():
            out.append("")
        out.append(f"{fence}{info}")
        i += 1
        while i < len(lines) and not lines[i].strip().startswith(fence):
            line = lines[i]
            out.append(line[len(indent) :] if line.startswith(indent) else line.lstrip())
            i += 1
        out.append(fence)
        out.append("")
        i += 1  # 閉じのフェンス
    return "\n".join(out)


def toc_html(tokens: list[dict[str, Any]]) -> str:
    """見出し2・3だけの、入れ子の目次。"""

    def render(items: list[dict[str, Any]], depth: int) -> str:
        if not items or depth > 2:
            return ""
        out = ["<ol>"]
        for it in items:
            if it["name"] == "目次":  # 手書きの目次節は本文から外している
                continue
            out.append(f'<li><a href="#{it["id"]}">{html.escape(re.sub(r"<[^>]+>", "", it["name"]))}</a>')
            out.append(render(it.get("children", []), depth + 1))
            out.append("</li>")
        out.append("</ol>")
        return "".join(out)

    # 先頭の見出し1（タイトル）の子が、本文の見出し2
    top: list[dict[str, Any]] = []
    for t in tokens:
        if t["level"] == 1:
            top.extend(t.get("children", []))
        else:
            top.append(t)
    return render(top, 1)


def convert_one(src: Path, category: str, siblings: list[Path], converted: set[Path]) -> Path:
    text = src.read_text(encoding="utf-8")
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "nl2br"],
        extension_configs={"toc": {"slugify": slugify, "permalink": False}},
    )
    body = md.convert(dedent_list_fences(text))
    tokens: list[dict[str, Any]] = getattr(md, "toc_tokens", [])

    # タイトル: 最初の<h1>。本文からは外し、ヘッダに出す
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    title = re.sub(r"<[^>]+>", "", m.group(1)) if m else src.stem
    if m:
        body = body.replace(m.group(0), "", 1)

    # 本文に手書きの「目次」節があるときは、自動生成の目次と重なるので外す（次の見出し・区切り線まで）
    body = re.sub(r'<h2 id="目次">目次</h2>.*?(?=<h2 |<hr)', "", body, count=1, flags=re.S)

    # mermaid
    has_mermaid = 'class="language-mermaid"' in body
    body = re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda mm: f'<div class="mermaid">{mm.group(1)}</div>',
        body,
        flags=re.S,
    )
    # 横長の表は、横にスクロール
    body = body.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")

    # 相対リンクの.mdを.htmlへ（変換対象、またはHTMLが既にあるもの）
    def fix_href(mm: re.Match[str]) -> str:
        href = mm.group(1)
        if re.match(r"^(https?:|mailto:|#)", href):
            return mm.group(0)
        path, sep, frag = href.partition("#")
        if path.endswith(".md"):
            target = (src.parent / path).resolve()
            if target in converted or target.with_suffix(".html").exists():
                return f'href="{path[:-3]}.html{sep}{frag}"'
        return mm.group(0)

    body = re.sub(r'href="([^"]+)"', fix_href, body)

    # シリーズ（同じフォルダの資料）のナビゲーション
    series_html = ""
    pager_html = ""
    if len(siblings) > 1 and src in siblings:
        links = []
        for s in siblings:
            label = "目次" if s.stem == "README" else s.stem.split("-", 1)[0] if s.stem[:2].isdigit() else s.stem
            cls = ' class="current"' if s == src else ""
            links.append(f'<a{cls} href="{s.stem}.html">{html.escape(label)}</a>')
        series_html = f'<nav class="series" aria-label="シリーズ">{"".join(links)}</nav>'
        i = siblings.index(src)
        prev_l = f'<a href="{siblings[i - 1].stem}.html">← 前へ</a>' if i > 0 else "<span></span>"
        next_l = f'<a href="{siblings[i + 1].stem}.html">次へ →</a>' if i < len(siblings) - 1 else "<span></span>"
        pager_html = f'<div class="pager">{prev_l}{next_l}</div>'

    toc = toc_html(tokens)
    toc_block = f'<nav class="toc"><details open><summary>目次</summary>{toc}</details></nav>' if toc else ""
    mermaid_js = (
        '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>\n'
        "<script>mermaid.initialize({startOnLoad:true,"
        "theme:window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'default'});</script>"
        if has_mermaid
        else ""
    )

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap" id="page">
{series_html}
<header class="hero">
  <span class="badge">{html.escape(category)}</span>
  <h1>{html.escape(title)}</h1>
  <div class="meta">HTML生成: {date.today().isoformat()}（元: {html.escape(src.relative_to(ROOT).as_posix())}）</div>
</header>
{toc_block}
<main>
{body}
</main>
{pager_html}
<footer>このHTMLは <code>scripts/build_docs_html.py</code> が、元のMarkdownから生成した。直接編集せず、Markdownを直して再生成する。</footer>
</div>
<a id="top" href="#page">▲ 先頭へ</a>
{mermaid_js}
</body>
</html>
"""
    out = src.with_suffix(".html")
    out.write_text(page, encoding="utf-8", newline="\n")
    return out


def main(argv: list[str]) -> int:
    if argv:
        targets = [(Path(a).resolve(), "資料") for a in argv]
    else:
        targets = DEFAULT_TARGETS
    missing = [str(p) for p, _ in targets if not p.exists()]
    if missing:
        print("見つからない資料:", *missing, sep="\n  ")
        return 1
    converted = {p.resolve() for p, _ in targets}
    learning_dir = DOCS / "learning"
    siblings = [p for p, _ in targets if p.parent == learning_dir]
    for src, category in targets:
        out = convert_one(src.resolve(), category, siblings, converted)
        print(f"{out.relative_to(ROOT).as_posix()}  ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
