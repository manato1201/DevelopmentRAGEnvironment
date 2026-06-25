#!/usr/bin/env python3
"""
rss_to_rag.py — RSS/Web収集 → Markdown → RAG vault パイプライン

Research-Collector のフィード定義を使い、記事を本文ごと取得して
localRAG vault に Markdown として保存する。
auto_index.py または document_pipeline.py index でインデックス化できる。

Usage:
    python scripts/rss_to_rag.py --source all
    python scripts/rss_to_rag.py --source zenn_qiita --max-per-feed 10
    python scripts/rss_to_rag.py --source papers --namespace research
    python scripts/rss_to_rag.py --source unity_ue --index
    python scripts/rss_to_rag.py --source all --dry-run

Sources:
    all         全ソース（下記すべて）
    zenn_qiita  Zenn / Qiita (Unity, Unreal, HLSL, gamedev, Houdini タグ)
    unity_ue    Unity / Unreal Engine 公式ブログ
    cedec       CEDEC YouTube
    papers      arXiv + Semantic Scholar

Requirements:
    feedparser  (pip install feedparser)
    markitdown  (mcp-rag-server venv 内、またはグローバルに pip install markitdown)
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rss_to_rag")

# ─── パス設定 ────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent
_VAULT_DIR = _PROJECT_ROOT / "localRAG"
_MCP_RAG_DIR = _PROJECT_ROOT.parent / "mcp-rag-server"
_SEEN_FILE = _HERE / ".rss_to_rag_seen.json"   # 処理済みURL追跡（プロジェクト内）

# ─── フィード定義 ────────────────────────────────────────────────────────────────

ZENN_QIITA_FEEDS: list[tuple[str, str]] = [
    # (feed_url, namespace)
    ("https://zenn.dev/topics/unity/feed",        "tool_docs"),
    ("https://zenn.dev/topics/unrealengine/feed", "tool_docs"),
    ("https://zenn.dev/topics/directx/feed",      "tool_docs"),
    ("https://zenn.dev/topics/hlsl/feed",         "tool_docs"),
    ("https://zenn.dev/topics/gamedev/feed",      "tool_docs"),
    ("https://zenn.dev/topics/houdini/feed",      "tool_docs"),
    ("https://qiita.com/tags/unity/feed",         "tool_docs"),
    ("https://qiita.com/tags/unrealengine/feed",  "tool_docs"),
    ("https://qiita.com/tags/directx12/feed",     "tool_docs"),
    ("https://qiita.com/tags/hlsl/feed",          "tool_docs"),
    ("https://qiita.com/tags/gamedev/feed",       "tool_docs"),
]

UNITY_UE_FEEDS: list[tuple[str, str]] = [
    ("https://blog.unity.com/feed",               "tool_docs"),
    ("https://www.unrealengine.com/en-US/rss",    "tool_docs"),
]

CEDEC_YOUTUBE_RSS = (
    "https://www.youtube.com/feeds/videos.xml"
    "?channel_id=UCmHaPXvwn9_4pMNAV6ewgoA"
)

ARXIV_QUERIES = [
    "retrieval augmented generation tutorial generation",
    "LLM step by step instruction generation",
    "developer documentation usage behavior",
    "software documentation maintenance outdated",
    "DCC tool learning curve creative software",
    "Houdini procedural generation learning",
]

SEMANTIC_SCHOLAR_QUERIES = [
    "RAG retrieval augmented generation documentation",
    "LLM tutorial generation step by step",
    "developer documentation usage behavior",
    "DCC tool learning curve creative software",
]

# ─── Namespace 定義 ──────────────────────────────────────────────────────────────
VALID_NAMESPACES = ["tool_docs", "game_info", "research", "team_notes", "personal_notes"]


# ─── 処理済み URL 管理 ───────────────────────────────────────────────────────────

def _load_seen() -> set[str]:
    if _SEEN_FILE.exists():
        try:
            return set(json.loads(_SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _save_seen(seen: set[str]) -> None:
    _SEEN_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# ─── HTML → Markdown 変換 ────────────────────────────────────────────────────────

class _StripHTMLParser(HTMLParser):
    """markitdown が使えない場合のフォールバック: HTML タグを除去してプレーンテキスト化。"""
    SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "form"}

    def __init__(self):
        super().__init__()
        self.result: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if self._skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4"):
            level = int(tag[1])
            self.result.append("\n" + "#" * level + " ")
        elif tag in ("p", "br", "li"):
            self.result.append("\n")
        elif tag == "a":
            pass  # リンクテキストだけ残す

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if not self._skip_depth:
            self.result.append(data)

    def get_text(self) -> str:
        text = "".join(self.result)
        # 連続空行を2行に圧縮
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def _html_to_md_fallback(html: str) -> str:
    p = _StripHTMLParser()
    p.feed(html)
    return p.get_text()


def _fetch_url_content(url: str, timeout: int = 20) -> tuple[str, str]:
    """
    URL を取得して (markdown_text, method) を返す。
    method は "markitdown" / "fallback" / "failed" のいずれか。
    """
    # まず markitdown を試す
    try:
        import markitdown as _md
        result = _md.MarkItDown().convert(url)
        text = result.markdown.replace("\x00", "").strip()
        if text:
            return text, "markitdown"
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"markitdown failed for {url}: {e}")

    # フォールバック: urllib で HTML 取得 → 簡易除去
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        text = _html_to_md_fallback(html)
        return text, "fallback"
    except Exception as e:
        logger.debug(f"HTTP fetch failed for {url}: {e}")
        return "", "failed"


# ─── Vault 書き出し ──────────────────────────────────────────────────────────────

def _safe_stem(title: str, url_hash: str, max_len: int = 50) -> str:
    """ファイル名に使えるステムを生成する。"""
    stem = re.sub(r"[^\w\-]", "_", title)[:max_len] if title else ""
    return f"{stem}_{url_hash}" if stem else url_hash


def _make_frontmatter(
    title: str,
    url: str,
    source: str,
    platform: str,
    namespace: str,
    published_at: Optional[datetime.datetime],
    fetch_method: str,
) -> str:
    today = datetime.date.today().isoformat()
    pub = published_at.strftime("%Y-%m-%d") if published_at else today
    return (
        "---\n"
        f"title: \"{title.replace(chr(34), chr(39))}\"\n"
        f"url: {url}\n"
        f"source: {source}\n"
        f"platform: {platform}\n"
        f"namespace: {namespace}\n"
        f"published: {pub}\n"
        f"fetched: {today}\n"
        f"fetch_method: {fetch_method}\n"
        "status: active\n"
        "tags: [rss, auto-collected]\n"
        "---\n\n"
    )


def write_to_vault(
    article: dict,
    namespace: str,
    vault_dir: Path,
    dry_run: bool = False,
) -> bool:
    """
    1記事を vault に Markdown ファイルとして書き出す。
    Returns True if written, False if skipped/failed.
    """
    url   = article["url"]
    title = article.get("title", "")
    platform = article.get("platform", "unknown")
    source   = article.get("source_type", "web")
    pub      = article.get("published_at")

    # YouTube など動画は本文取得不可 → メタデータのみ
    is_video = "youtube.com" in url or "youtu.be" in url

    if is_video:
        content = f"# {title}\n\n[動画リンク]({url})\n"
        method  = "metadata_only"
    else:
        content, method = _fetch_url_content(url)
        if not content:
            logger.warning(f"  [スキップ] 本文取得失敗: {title[:60]}")
            return False

    stem     = _safe_stem(title, article["url_hash"])
    out_dir  = vault_dir / namespace
    out_path = out_dir / f"{stem}.md"

    frontmatter = _make_frontmatter(title, url, source, platform, namespace, pub, method)
    full_text   = frontmatter + f"# {title}\n\n" + content

    if dry_run:
        logger.info(f"  [DRY-RUN] → {out_path.relative_to(vault_dir)}  ({method})")
        return True

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_text, encoding="utf-8")
    logger.info(f"  → {out_path.relative_to(vault_dir)}  ({method}, {len(content)}文字)")
    return True


# ─── RSS 収集 ────────────────────────────────────────────────────────────────────

def _collect_rss_feeds(
    feeds: list[tuple[str, str]],
    max_per_feed: int,
    seen: set[str],
    ns_override: Optional[str],
) -> list[dict]:
    try:
        import feedparser
    except ImportError:
        logger.error("feedparser が未インストールです: pip install feedparser")
        return []

    articles = []
    for feed_url, default_ns in feeds:
        try:
            feed = feedparser.parse(feed_url)
            entries = feed.entries[:max_per_feed]
            logger.info(f"  RSS {feed_url[:60]}: {len(entries)} 件")
            for entry in entries:
                url = entry.get("link", "")
                if not url:
                    continue
                h = _url_hash(url)
                if h in seen:
                    continue
                seen.add(h)
                pub = None
                for attr in ("published_parsed", "updated_parsed"):
                    val = getattr(entry, attr, None)
                    if val:
                        try:
                            pub = datetime.datetime(*val[:6], tzinfo=datetime.timezone.utc)
                            break
                        except Exception:
                            pass
                articles.append({
                    "url":          url,
                    "title":        entry.get("title", ""),
                    "source_type":  "rss",
                    "platform":     urllib.parse.urlparse(feed_url).netloc,
                    "published_at": pub,
                    "url_hash":     h,
                    "namespace":    ns_override or default_ns,
                })
        except Exception as e:
            logger.warning(f"  RSS 取得失敗 {feed_url}: {e}")
    return articles


def _collect_arxiv(max_per_query: int, seen: set[str], ns: str) -> list[dict]:
    articles = []
    api = "https://export.arxiv.org/api/query"
    for query in ARXIV_QUERIES:
        params = urllib.parse.urlencode({
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_per_query,
            "sortBy": "relevance",
        })
        try:
            req = urllib.request.Request(
                f"{api}?{params}",
                headers={"User-Agent": "rss-to-rag/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml = resp.read().decode("utf-8")
        except Exception as e:
            logger.warning(f"  arXiv 取得失敗 '{query[:40]}': {e}")
            time.sleep(1)
            continue

        for m in re.finditer(r"<entry>(.*?)</entry>", xml, re.DOTALL):
            entry = m.group(1)
            url_m = re.search(r"<id>(.*?)</id>", entry)
            title_m = re.search(r"<title[^>]*>(.*?)</title>", entry, re.DOTALL)
            if not url_m or not title_m:
                continue
            url   = url_m.group(1).strip()
            title = re.sub(r"\s+", " ", title_m.group(1)).strip()
            h = _url_hash(url)
            if h in seen:
                continue
            seen.add(h)
            pub_m = re.search(r"<published>(.*?)</published>", entry)
            pub   = None
            if pub_m:
                try:
                    pub = datetime.datetime.strptime(pub_m.group(1)[:10], "%Y-%m-%d")
                    pub = pub.replace(tzinfo=datetime.timezone.utc)
                except Exception:
                    pass
            # 著者
            authors = re.findall(r"<name>(.*?)</name>", entry)
            author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            articles.append({
                "url":          url,
                "title":        title,
                "source_type":  "paper",
                "platform":     "arxiv",
                "published_at": pub,
                "url_hash":     h,
                "namespace":    ns,
                "authors":      author_str,
            })
        logger.info(f"  arXiv '{query[:40]}': 収集済み")
        time.sleep(3)
    return articles


def _collect_semantic_scholar(max_per_query: int, seen: set[str], ns: str) -> list[dict]:
    articles = []
    api = "https://api.semanticscholar.org/graph/v1/paper/search"
    for query in SEMANTIC_SCHOLAR_QUERIES:
        params = urllib.parse.urlencode({
            "query":  query,
            "limit":  max_per_query,
            "fields": "title,authors,year,externalIds,openAccessPdf",
        })
        try:
            req = urllib.request.Request(
                f"{api}?{params}",
                headers={"User-Agent": "rss-to-rag/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            logger.warning(f"  S2 取得失敗 '{query[:40]}': {e}")
            time.sleep(1)
            continue

        for paper in data.get("data", []):
            ext = paper.get("externalIds") or {}
            pdf = paper.get("openAccessPdf") or {}
            url = (
                f"https://doi.org/{ext['DOI']}" if ext.get("DOI")
                else pdf.get("url")
                or (f"https://www.semanticscholar.org/paper/{paper['paperId']}"
                    if paper.get("paperId") else None)
            )
            if not url:
                continue
            h = _url_hash(url)
            if h in seen:
                continue
            seen.add(h)
            authors_list = paper.get("authors") or []
            author_str = ", ".join(a.get("name", "") for a in authors_list[:3])
            if len(authors_list) > 3:
                author_str += " et al."
            year = paper.get("year")
            pub  = datetime.datetime(int(year), 1, 1, tzinfo=datetime.timezone.utc) if year else None
            articles.append({
                "url":          url,
                "title":        paper.get("title", ""),
                "source_type":  "paper",
                "platform":     "semantic_scholar",
                "published_at": pub,
                "url_hash":     h,
                "namespace":    ns,
                "authors":      author_str,
            })
        logger.info(f"  S2 '{query[:40]}': 収集済み")
        time.sleep(1)
    return articles


# ─── インデックス化 ──────────────────────────────────────────────────────────────

def run_index() -> bool:
    if not _MCP_RAG_DIR.exists():
        logger.error(f"mcp-rag-server が見つかりません: {_MCP_RAG_DIR}")
        return False
    logger.info("インデックス化を実行中...")
    result = subprocess.run(
        ["uv", "run", "python", "-m", "src.cli", "index", "--incremental"],
        cwd=str(_MCP_RAG_DIR),
    )
    return result.returncode == 0


# ─── メイン処理 ─────────────────────────────────────────────────────────────────

def run(
    source: str,
    max_per_feed: int,
    namespace_override: Optional[str],
    vault_dir: Path,
    dry_run: bool,
    do_index: bool,
    fetch_delay: float,
) -> None:
    seen = _load_seen()
    logger.info(f"処理済み URL: {len(seen)} 件（スキップ対象）")

    articles: list[dict] = []

    if source in ("all", "zenn_qiita"):
        logger.info("=== Zenn / Qiita 収集 ===")
        articles.extend(_collect_rss_feeds(ZENN_QIITA_FEEDS, max_per_feed, seen, namespace_override))

    if source in ("all", "unity_ue"):
        logger.info("=== Unity / UE ブログ収集 ===")
        articles.extend(_collect_rss_feeds(UNITY_UE_FEEDS, max_per_feed, seen, namespace_override))

    if source in ("all", "cedec"):
        logger.info("=== CEDEC YouTube 収集 ===")
        cedec_feeds = [(CEDEC_YOUTUBE_RSS, namespace_override or "research")]
        articles.extend(_collect_rss_feeds(cedec_feeds, max_per_feed, seen, namespace_override))

    if source in ("all", "papers"):
        logger.info("=== 論文収集（arXiv） ===")
        articles.extend(_collect_arxiv(max_per_feed, seen, namespace_override or "research"))
        logger.info("=== 論文収集（Semantic Scholar） ===")
        articles.extend(_collect_semantic_scholar(max_per_feed, seen, namespace_override or "research"))

    logger.info(f"\n合計 {len(articles)} 件を処理します")

    ok_count = 0
    skip_count = 0
    new_seen: set[str] = set()

    for i, article in enumerate(articles, 1):
        title = article.get("title", "")[:60]
        logger.info(f"[{i}/{len(articles)}] {title}")

        ns = article.get("namespace") or namespace_override or "research"
        success = write_to_vault(article, ns, vault_dir, dry_run=dry_run)

        if success:
            ok_count += 1
            new_seen.add(article["url_hash"])
        else:
            skip_count += 1

        # レート制限対策
        if not dry_run and i < len(articles):
            time.sleep(fetch_delay)

    logger.info(f"\n完了: 書き込み {ok_count} 件 / スキップ {skip_count} 件")

    if not dry_run and new_seen:
        seen |= new_seen
        _save_seen(seen)
        logger.info(f"処理済みURLを更新: 合計 {len(seen)} 件")

    if do_index and not dry_run:
        ok = run_index()
        logger.info("インデックス化: " + ("完了" if ok else "失敗"))


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RSS/Web収集 → Markdown → RAG vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source", "-s",
        choices=["all", "zenn_qiita", "unity_ue", "cedec", "papers"],
        default="all",
        help="収集ソース（デフォルト: all）",
    )
    parser.add_argument(
        "--max-per-feed", "-m",
        type=int, default=5,
        help="フィードあたりの最大取得件数（デフォルト: 5）",
    )
    parser.add_argument(
        "--namespace", "-n",
        choices=VALID_NAMESPACES,
        default=None,
        help="namespace を強制指定（デフォルト: ソースに応じて自動）",
    )
    parser.add_argument(
        "--vault",
        default=str(_VAULT_DIR),
        help=f"vault ディレクトリ（デフォルト: {_VAULT_DIR}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には書き込まず、処理予定を表示",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="vault 書き込み後にインデックス化を実行",
    )
    parser.add_argument(
        "--delay",
        type=float, default=1.5,
        help="記事間の待機秒数（レート制限対策、デフォルト: 1.5）",
    )
    parser.add_argument(
        "--reset-seen",
        action="store_true",
        help="処理済みURLリストをリセット（全件再取得）",
    )

    args = parser.parse_args()

    if args.reset_seen and _SEEN_FILE.exists():
        _SEEN_FILE.unlink()
        logger.info("処理済みURLリストをリセットしました")

    run(
        source=args.source,
        max_per_feed=args.max_per_feed,
        namespace_override=args.namespace,
        vault_dir=Path(args.vault),
        dry_run=args.dry_run,
        do_index=args.index,
        fetch_delay=args.delay,
    )


if __name__ == "__main__":
    main()
