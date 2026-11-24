"""チュートリアル生成の記録（監査ログ）を集計する（2026-11-25）。「止まりやすい」「試行回数が上限になりやすい」を、数字で確かめる。

  uv run python scripts/analyze_generation_logs.py [<フォルダ>]   （省略すると <保存先>/logs/tutorial_agent）

出すもの（1 回の生成 = 1 行）:
  ・API の往復の回数（上限は tutorial_agent.MAX_ITERATIONS）・ツールの呼び出しの数・エラーの数
  ・いちばん時間のかかったツールと秒数（Houdini の画面が止まる元。ツールは、Houdini のメインスレッドで動く）
  ・打ち切りの理由（abort の記録があれば）
最後に、上限に近かった回・止まった回の数をまとめる。個人の情報（質問の文・パス）は出さない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))

SLOW_SECONDS = 60.0    # これ以上のツールは「止まった」と数える
NEAR_LIMIT = 0.8       # 上限のこの割合以上の往復は「上限に近い」と数える


def summarize(path: Path) -> dict:
    """1 つの監査ログ（1 回の生成）を集計する。"""
    row = {"name": path.stem, "api": 0, "tools": 0, "errors": 0, "slowest": ("", 0.0), "slow": 0, "abort": ""}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("event")
        if kind == "api_call":
            row["api"] += 1
        elif kind == "tool_call":
            row["tools"] += 1
            row["errors"] += 1 if event.get("is_error") else 0
            seconds = float(event.get("elapsed_s") or 0)
            if seconds > row["slowest"][1]:
                row["slowest"] = (str(event.get("tool") or ""), seconds)
            row["slow"] += 1 if seconds >= SLOW_SECONDS else 0
        elif kind in ("abort", "aborted") or event.get("abort_reason"):
            row["abort"] = str(event.get("abort_reason") or event.get("reason") or kind)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", nargs="?", default="")
    args = parser.parse_args(argv)
    folder = Path(args.folder) if args.folder else None
    if folder is None:
        cfg_path = Path.home() / ".houdini" / "rag_chatbot_config.json"
        try:
            base = json.loads(cfg_path.read_text(encoding="utf-8")).get("local_bridge_dir") or ""
        except (OSError, ValueError):
            base = ""
        folder = Path(base) / "logs" / "tutorial_agent"
    files = sorted(folder.glob("ai_tutorial_*.jsonl"))
    if not files:
        print(f"記録がありません: {folder}")
        return 1
    try:
        from tutorial_agent import MAX_ITERATIONS
    except Exception:  # noqa: BLE001 -- PySide6 などが無い環境でも、集計はできるように
        MAX_ITERATIONS = 80
    rows = [summarize(f) for f in files]
    print(f"{'生成':<22} {'往復':>4} {'ツール':>5} {'エラー':>5}  いちばん遅いツール")
    for r in rows:
        mark = " ← 上限に近い" if r["api"] >= MAX_ITERATIONS * NEAR_LIMIT else ""
        mark += " ← 止まった" if r["slow"] else ""
        print(f"{r['name'][12:]:<22} {r['api']:>4} {r['tools']:>5} {r['errors']:>5}  {r['slowest'][0]} {r['slowest'][1]:.0f}秒{mark}"
              + (f"  打ち切り: {r['abort']}" if r["abort"] else ""))
    near = sum(1 for r in rows if r["api"] >= MAX_ITERATIONS * NEAR_LIMIT)
    stalled = sum(1 for r in rows if r["slow"])
    print(f"\n生成 {len(rows)} 回 / 往復が上限（{MAX_ITERATIONS}）の {NEAR_LIMIT:.0%} 以上: {near} 回 / {SLOW_SECONDS:.0f} 秒以上かかったツールがある回: {stalled} 回")
    return 0


if __name__ == "__main__":
    sys.exit(main())
