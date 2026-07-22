#!/usr/bin/env python3
"""
audit_report.py — 監査ログ（logs/rag_audit.jsonl）から応答速度・エラー率を集計する

外部通知（Slack等）は行わない。定期的に手動実行するか、cron/タスクスケジューラで
標準出力をログファイルにリダイレクトして確認する運用を想定している。

Usage:
    uv run python scripts/audit_report.py
    uv run python scripts/audit_report.py --log-path logs/rag_audit.jsonl --warn-ms 15000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * pct))
    return sorted_values[idx]


def report(log_path: Path, warn_ms: int) -> None:
    if not log_path.exists():
        print(f"監査ログが見つかりません: {log_path}")
        sys.exit(1)

    records: list[dict] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not records:
        print("監査ログにレコードがありません。")
        return

    searches = [r for r in records if r.get("action") == "search"]
    total = len(searches)
    allowed_true = [r for r in searches if r.get("allowed") is True]
    allowed_false = [r for r in searches if r.get("allowed") is False]
    error_rate = (len(allowed_false) / total * 100) if total else 0.0

    latencies = sorted(r["latency_ms"] for r in searches if isinstance(r.get("latency_ms"), (int, float)))
    slow = [l for l in latencies if l > warn_ms]

    print(f"=== 監査ログレポート（{log_path}） ===")
    print(f"総検索件数:      {total}")
    print(f"成功:            {len(allowed_true)}  ({100 - error_rate:.1f}%)")
    print(f"失敗/拒否:       {len(allowed_false)}  ({error_rate:.1f}%)")
    print()
    if latencies:
        print(f"レイテンシ  p50: {_percentile(latencies, 0.50):.0f}ms  "
              f"p95: {_percentile(latencies, 0.95):.0f}ms  "
              f"max: {latencies[-1]:.0f}ms")
        print(f"目標値（{warn_ms}ms）超過: {len(slow)} 件 ({len(slow) / len(latencies) * 100:.1f}%)")
    else:
        print("レイテンシ記録なし")

    if allowed_false:
        print()
        print("--- 失敗/拒否の内訳（namespace別） ---")
        by_ns: dict[str, int] = {}
        for r in allowed_false:
            ns = r.get("namespace") or "(不明)"
            by_ns[ns] = by_ns.get(ns, 0) + 1
        for ns, count in sorted(by_ns.items(), key=lambda x: -x[1]):
            print(f"  {ns}: {count} 件")


def main() -> None:
    parser = argparse.ArgumentParser(description="監査ログから応答速度・エラー率を集計する")
    parser.add_argument("--log-path", default="logs/rag_audit.jsonl", help="監査ログのパス")
    parser.add_argument("--warn-ms", type=int, default=15000, help="応答速度の目標値（ミリ秒）")
    args = parser.parse_args()
    report(Path(args.log_path), args.warn_ms)


if __name__ == "__main__":
    main()
