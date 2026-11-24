"""Reference の「公式ドキュメントへのリンク」が、生きているか確かめる（2026-11-24）。開発側の道具。通信する（SideFX のサイトへ、HEAD を 1 件ずつ）。

  uv run python scripts/check_reference_links.py [--kind node,vex,apex] [--only sop/scatter,...] [--workers 4]

保存してある説明の項目について、画面の「公式ドキュメント」のリンク（reference_data の doc_url）を調べる。シェルフツールは、ページが無く、
検索へのリンクなので、対象外。見つからない（404）リンクは、一覧にする（画面では、リンク先が無いと分かる前に、押せてしまうため）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts"))

import reference_data as rd  # noqa: E402
from check_reference_quality import DEFAULT_CONFIG, load_saved  # noqa: E402

USER_AGENT = "RAGReel-reference-link-check/1.0"


def url_status(url: str, timeout: float = 15.0) -> int:
    """HEAD の結果（HTTP の番号）。通信できなければ 0。"""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 -- 固定の公式サイトの URL だけ
            return int(res.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def doc_url_for(kind: str, key: str) -> str | None:
    item = rd.find_item(kind, key)
    if item and item.get("doc_url") and kind != "shelf":
        return str(item["doc_url"])
    return None


def main(argv: list[str] | None = None) -> int:
    import time

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", default="node,vex,apex")
    parser.add_argument("--only", default="")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args(argv)
    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    base_dir = str(os.environ.get("RAGREEL_BRIDGE_DIR") or cfg.get("local_bridge_dir") or "")
    items = load_saved(base_dir, {k.strip() for k in args.kind.split(",") if k.strip()}, {k.strip() for k in args.only.split(",") if k.strip()})
    targets = [(i["kind"], i["key"], doc_url_for(i["kind"], i["key"])) for i in items]
    targets = [t for t in targets if t[2]]

    def check(target):
        time.sleep(0.15)  # 相手のサイトに、続けて何百回も叩かない
        return target, url_status(target[2])

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(check, targets))
    dead = [(t, s) for t, s in results if s not in (200, 301, 302)]
    for (kind, key, url), status in dead:
        print(f"  {'通信できず' if status == 0 else status}  {key}  {url}")
    print(f"リンク {len(results)} 件 / 生きている {len(results) - len(dead)} 件 / 見つからない・通信できない {len(dead)} 件")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
