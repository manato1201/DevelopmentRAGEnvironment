"""
update_node_links.py — Houdini 公式ドキュメントのノード一覧から、チャットの「ノードの公式ドキュメントへのリンク」の元データを作り直す（開発者用）

  python houdini/update_node_links.py            # houdini/python_panels/node_link_data.py を作り直す（ネットワークが要る）
  python houdini/update_node_links.py --check    # 何も書かず、いまのデータと公式の一覧の差だけ表示
  python houdini/update_node_links.py --verify 40   # 作ったデータから 40 件を選び、ページが実在するか（HTTP 200）確かめる

元にするのは、公式の各章の一覧ページ（https://www.sidefx.com/docs/houdini/nodes/<章>/index.html）。
一覧に載っているリンクだけを使うので、「推測で作った、存在しないページ」は入らない。
Houdini の新しい版でノードが増えたら、このスクリプトを実行して、node_link_data.py を作り直す（リンクは、公式の最新版のページを指す）。
"""

from __future__ import annotations

import argparse
import html
import random
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://www.sidefx.com/docs/houdini/nodes"
CONTEXTS = ("sop", "dop", "obj", "lop", "vop", "top", "chop", "cop2", "cop", "out", "apex")
TARGET = Path(__file__).resolve().parent / "python_panels" / "node_link_data.py"
_ITEM = re.compile(r'<a class="label-text node" href="([^"]+)">([^<]+)</a>')
_SAFE_SLUG = re.compile(r"[A-Za-z0-9_.\-]+")


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "RAGReel-node-links/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 -- 公式ドキュメントの固定の URL
        return response.read().decode("utf-8", errors="replace")


def parse_index(page: str) -> dict[str, str]:
    """一覧ページの HTML から {ページ名: 表示名}。同じ章の中のページ（href がファイル名だけ）に限る。"""
    found: dict[str, str] = {}
    for href, title in _ITEM.findall(page):
        if "/" in href or not href.endswith(".html"):
            continue
        found[href[: -len(".html")]] = html.unescape(title).strip()
    return found


def collect() -> dict[str, dict[str, str]]:
    return {context: parse_index(fetch(f"{BASE}/{context}/index.html")) for context in CONTEXTS}


def _is_safe_entry(slug: str, title: str) -> bool:
    """Python のソースに、そのまま書き出してよい名前か。公式サイトの文字が、ソースを壊したり、コードを混ぜたりしないように、
    ページ名は英数字と _ . - だけ、表示名は、引用符・バックスラッシュ・改行・制御文字を含まないものだけを通す。"""
    if not _SAFE_SLUG.fullmatch(slug) or not title.strip():
        return False
    return not any(ch in '"\\|' or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in title)


def render(data: dict[str, dict[str, str]], checked_on: str) -> str:
    lines = [
        '"""',
        "node_link_data.py — Houdini 公式ドキュメントのノード一覧（ページ名と表示名）。自動生成。手で直さない。",
        "",
        f"生成: houdini/update_node_links.py（{checked_on}）。元: {BASE}/<章>/index.html の一覧に載っているリンクだけ。",
        "形: 章ごとに、1 行 = 「ページ名|表示名」。URL は  BASE/<章>/<ページ名>.html  （名前空間つきは  apex--名前  のように -- でつながる）。",
        '"""',
        "",
        f'CHECKED_ON = "{checked_on}"',
        f'BASE = "{BASE}"',
        "",
        "NODES = {",
    ]
    for context in CONTEXTS:
        lines.append(f'    "{context}": """\\')
        for slug, title in sorted(data[context].items()):
            if _is_safe_entry(slug, title):
                lines.append(f"{slug}|{title}")
            else:
                print(f"飛ばしました（書き出せない文字を含む）: {context}/{slug!r}", file=sys.stderr)
        lines.append('""",')
    lines.append("}")
    return "\n".join(lines) + "\n"


def current() -> dict[str, dict[str, str]]:
    sys.path.insert(0, str(TARGET.parent))
    import importlib

    module = importlib.import_module("node_link_data")
    out: dict[str, dict[str, str]] = {}
    for context, block in module.NODES.items():
        out[context] = dict(line.split("|", 1) for line in block.splitlines() if "|" in line)
    return out


def head_status(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "RAGReel-node-links/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="差分の表示だけ")
    parser.add_argument("--verify", type=int, default=0, metavar="N", help="いまのデータから N 件を選び、ページが実在するか確かめる")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.verify:
        data = current()
        flat = [(c, slug) for c, nodes in data.items() for slug in nodes]
        random.seed(0)
        bad = 0
        for context, slug in random.sample(flat, min(args.verify, len(flat))):
            status = head_status(f"{BASE}/{context}/{slug}.html")
            if status != 200:
                bad += 1
                print(f"NG {status} {context}/{slug}")
        print(f"確認 {min(args.verify, len(flat))} 件、実在しないもの {bad} 件")
        return 1 if bad else 0

    latest = collect()
    if args.check:
        old = current()
        for context in CONTEXTS:
            added = sorted(set(latest[context]) - set(old.get(context, {})))
            removed = sorted(set(old.get(context, {})) - set(latest[context]))
            print(f"{context}: 追加 {len(added)} 件、削除 {len(removed)} 件")
        return 0

    import datetime

    TARGET.write_text(render(latest, datetime.date.today().isoformat()), encoding="utf-8")
    print(f"作りました: {TARGET}（{sum(len(v) for v in latest.values())} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
