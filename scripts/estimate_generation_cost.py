"""チュートリアル生成1回分のトークン・コストを、実測の記録から見積もり、テスターへ配る量を提案する。

使い方:
    uv run python scripts/estimate_generation_cost.py                     # localRAG/tutorials の記録を使う
    uv run python scripts/estimate_generation_cost.py --runs 10 --margin 1.5 --testers 12
    uv run python scripts/estimate_generation_cost.py --dir C:/path/to/tutorials

入力（各生成の隣に、生成時に自動で残る）:
    <名前>_metrics.json          生成の実測（input_tokens / output_tokens / cost_usd / cache_*）
    <名前>_video_script.json     動画の台本づくりで使ったトークン（"usage"。無ければ仮定値を使う）

重要: Worker の「Claude予算」は、**キャッシュを除く** input_tokens + output_tokens の合計を数える
（src/budget.ts / src/claude.ts）。実際の費用（cost_usd）は、キャッシュの読み書きを含むので、トークン数と
費用は比例しない。そこで、配る量は「予算（トークン）」で決め、費用は実測の「1トークンあたりの費用」で
換算して、上限の見積もりを出す。
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

# 台本づくり（video_script.py）の1回の呼び出し。実測が無いときの仮定値（入力は台本の指示＋本文＋手順の一覧）。
ASSUMED_SCRIPT_INPUT = 8_000
ASSUMED_SCRIPT_OUTPUT = 3_500
ASSUMED_SCRIPT_COST_USD = 0.065
# レッスン設計（lesson_design.py）の1回の呼び出し。仮定値。
ASSUMED_PLAN_TOKENS = 4_500
ASSUMED_PLAN_COST_USD = 0.025
# 1回の呼び出しで、Worker が「先に確保する」量の最大の目安（予算の残りがこれ未満だと、実際の使用が少なくても 429 になる）。
# max_tokens 16,000 ＋ 会話の大きさ（文字数/3 ＋ 画像1枚 1,600）。終盤の呼び出しで約 4 万。
RESERVATION_HEADROOM = 45_000
# 動画1本の読み上げ文字数（クラウド音声の上限の目安）
ASSUMED_TTS_CHARS = 3_500


def load_runs(directory: Path) -> list[dict]:
    runs = []
    for metrics_path in sorted(directory.glob("*_metrics.json")):
        try:
            m = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not m.get("completed", True) or not m.get("cost_usd"):
            continue
        stem = metrics_path.name[: -len("_metrics.json")]
        script_usage: dict = {}
        script_chars = 0
        script_path = directory / f"{stem}_video_script.json"
        if script_path.exists():
            try:
                script = json.loads(script_path.read_text(encoding="utf-8"))
                script_usage = script.get("usage") or {}
                script_chars = sum(
                    len(str(x.get("narration", "")))
                    for x in [script.get("intro") or {}, script.get("outro") or {}, script.get("structure") or {}]
                    + list(script.get("steps") or []) + list(script.get("sections") or [])
                )
            except (OSError, json.JSONDecodeError):
                pass
        counted = int(m.get("input_tokens", 0)) + int(m.get("output_tokens", 0))
        has_plan = bool(m.get("lesson_plan"))
        script_known = bool(script_usage)
        script_tokens = (
            int(script_usage.get("input_tokens", 0)) + int(script_usage.get("output_tokens", 0))
            if script_known else ASSUMED_SCRIPT_INPUT + ASSUMED_SCRIPT_OUTPUT
        )
        # 設計の呼び出しは、tutorial の input/output に既に含まれている（result へ加算している）。
        extra_plan = 0
        runs.append({
            "name": stem,
            "level": m.get("level", ""),
            "iterations": m.get("iterations", 0),
            "seconds": m.get("elapsed_seconds", 0),
            "tutorial_tokens": counted + extra_plan,
            "tutorial_cost": float(m.get("cost_usd", 0)),
            "script_tokens": script_tokens,
            "script_cost": ASSUMED_SCRIPT_COST_USD,
            "script_measured": script_known,
            "lesson_design": has_plan,
            "tts_chars": script_chars or ASSUMED_TTS_CHARS,
        })
    return runs


def summarize(runs: list[dict]) -> dict:
    """1回（チュートリアル＋台本）あたりの、平均・最大。"""
    if not runs:
        return {}
    per_run_tokens = [r["tutorial_tokens"] + r["script_tokens"] for r in runs]
    per_run_cost = [r["tutorial_cost"] + r["script_cost"] for r in runs]
    return {
        "count": len(runs),
        "tokens_mean": statistics.mean(per_run_tokens),
        "tokens_max": max(per_run_tokens),
        "cost_mean": statistics.mean(per_run_cost),
        "cost_max": max(per_run_cost),
        # 1トークンあたりの費用（キャッシュ込み）。実測の最大を使い、上限を保守的に見積もる。
        "usd_per_token_mean": sum(per_run_cost) / sum(per_run_tokens),
        "usd_per_token_max": max(c / t for c, t in zip(per_run_cost, per_run_tokens)),
        "tts_chars_mean": statistics.mean(r["tts_chars"] for r in runs),
    }


def recommend(summary: dict, generations: int, margin: float, testers: int) -> dict:
    """generations 回分を、margin 倍の余裕つきで賄う、1人あたりの予算（トークン）と費用。"""
    base = summary["tokens_mean"] * generations
    grant = math.ceil((base * margin + RESERVATION_HEADROOM) / 10_000.0) * 10_000  # 切り上げ（足りなくなる側に丸めない）
    typical_usd = summary["cost_mean"] * generations
    worst_usd = grant * summary["usd_per_token_max"]
    return {
        "generations": generations,
        "grant_tokens": grant,
        "per_tester_typical_usd": typical_usd,
        "per_tester_worst_usd": worst_usd,
        "total_typical_usd": typical_usd * testers,
        "total_worst_usd": worst_usd * testers,
        "tts_chars_per_tester": int(summary["tts_chars_mean"] * generations),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default="localRAG/tutorials", help="生成物（*_metrics.json）のフォルダ")
    parser.add_argument("--runs", type=int, default=10, help="1人に配る、生成の回数")
    parser.add_argument("--margin", type=float, default=1.5, help="余裕の倍率（やり直し・失敗の分）")
    parser.add_argument("--testers", type=int, default=10, help="テスターの人数")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    all_runs = load_runs(Path(args.dir))
    if not all_runs:
        print(f"記録（*_metrics.json）が見つかりません: {args.dir}", file=sys.stderr)
        return 1
    # レッスン設計つきの生成は、設計・実験・仕上げの分だけ重い。設計つきの記録があれば、現行の姿として、それだけで見積もる。
    runs = [r for r in all_runs if r["lesson_design"]] or all_runs

    print(f"{'生成':<46}{'レベル':<9}{'反復':>5}{'秒':>6}{'トークン(予算に数える)':>22}{'台本':>8}{'費用$':>8}")
    for r in all_runs:
        mark = "" if r["script_measured"] else "*"
        design = "設計" if r["lesson_design"] else "    "
        print(f"{r['name'][:44]:<46}{r['level']:<9}{r['iterations']:>5}{int(r['seconds']):>6}"
              f"{r['tutorial_tokens']:>20,}{design}{r['script_tokens']:>7,}{mark}{r['tutorial_cost'] + r['script_cost']:>8.3f}")
    print("  * 台本のトークンは仮定値（台本のJSONに実測が無い）。設計=レッスン設計つきの生成。\n")

    s = summarize(runs)
    basis = "レッスン設計つきの生成" if runs is not all_runs else "全ての生成"
    note = f"（{basis} {len(runs)}件が基準"
    if len(runs) < 5:
        note += "。件数が少ないので、実測が増えたら再計算してください"
    print(note + "）")
    print(f"1回（チュートリアル＋台本）あたり: 平均 {s['tokens_mean']:,.0f} トークン / ${s['cost_mean']:.3f}、"
          f"最大 {s['tokens_max']:,.0f} トークン / ${s['cost_max']:.3f}")
    print(f"1トークンあたりの費用: 平均 ${s['usd_per_token_mean'] * 1e6:.1f}/100万、最大 ${s['usd_per_token_max'] * 1e6:.1f}/100万 "
          f"（キャッシュの読み書きを含む実費）\n")

    r = recommend(s, args.runs, args.margin, args.testers)
    print(f"提案: 1人あたり「Claude予算」 {r['grant_tokens']:,} トークン"
          f"（{r['generations']}回分 × 余裕{args.margin}倍 ＋ 先確保の余裕 {RESERVATION_HEADROOM:,}）")
    print(f"  費用: 普通に使って 1人 ${r['per_tester_typical_usd']:.2f}、使い切った場合の上限の目安 1人 ${r['per_tester_worst_usd']:.2f}")
    print(f"  {args.testers}人: 普通 ${r['total_typical_usd']:.0f}、上限の目安 ${r['total_worst_usd']:.0f}")
    print(f"  音声: 1人あたり約 {r['tts_chars_per_tester']:,} 文字（鍵ごとの1日の上限は既定 50,000）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
