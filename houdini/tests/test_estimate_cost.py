"""scripts/estimate_generation_cost.py の計算のテスト。実行: uv run python -m unittest discover -s houdini/tests -v"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import estimate_generation_cost as ec  # noqa: E402


def write_run(d: Path, stem: str, **over) -> None:
    metrics = {"completed": True, "cost_usd": 0.30, "input_tokens": 2_000, "output_tokens": 10_000,
               "level": "advanced", "iterations": 40, "elapsed_seconds": 120, "lesson_plan": True}
    metrics.update(over)
    (d / f"{stem}_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")


class EstimateTest(unittest.TestCase):
    def test_load_skips_incomplete_and_free_runs_and_reads_script_usage(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            write_run(d, "ok")
            write_run(d, "aborted", completed=False)
            write_run(d, "nocost", cost_usd=0)
            (d / "ok_video_script.json").write_text(json.dumps({
                "usage": {"input_tokens": 6_000, "output_tokens": 2_000},
                "intro": {"narration": "あ" * 100}, "steps": [{"narration": "い" * 200}],
            }), encoding="utf-8")
            runs = ec.load_runs(d)
            self.assertEqual([r["name"] for r in runs], ["ok"])
            r = runs[0]
            self.assertEqual(r["tutorial_tokens"], 12_000)
            self.assertEqual(r["script_tokens"], 8_000)
            self.assertTrue(r["script_measured"])
            self.assertEqual(r["tts_chars"], 300)

    def test_assumed_script_tokens_when_not_measured(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            write_run(d, "x")
            r = ec.load_runs(d)[0]
            self.assertFalse(r["script_measured"])
            self.assertEqual(r["script_tokens"], ec.ASSUMED_SCRIPT_INPUT + ec.ASSUMED_SCRIPT_OUTPUT)
            self.assertEqual(r["tts_chars"], ec.ASSUMED_TTS_CHARS)

    def test_recommendation_covers_the_requested_runs_with_margin_and_headroom(self) -> None:
        runs = [{"tutorial_tokens": 12_000, "tutorial_cost": 0.30, "script_tokens": 8_000, "script_cost": 0.05,
                 "tts_chars": 3_000}] * 3
        s = ec.summarize(runs)
        self.assertEqual(s["tokens_mean"], 20_000)
        rec = ec.recommend(s, generations=10, margin=1.5, testers=10)
        self.assertEqual(rec["grant_tokens"], 350_000)  # 20,000 x 10 x 1.5 + 45,000 = 345,000 -> 10,000 単位に丸め
        self.assertGreaterEqual(rec["grant_tokens"], 20_000 * 10 + ec.RESERVATION_HEADROOM)
        self.assertAlmostEqual(rec["per_tester_typical_usd"], 3.5)
        self.assertGreater(rec["per_tester_worst_usd"], rec["per_tester_typical_usd"] * 0.9)
        self.assertEqual(rec["total_typical_usd"], rec["per_tester_typical_usd"] * 10)
        self.assertEqual(rec["tts_chars_per_tester"], 30_000)

    def test_main_prints_and_fails_without_records(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(ec.main(["--dir", t]), 1)
            write_run(Path(t), "a")
            self.assertEqual(ec.main(["--dir", t, "--runs", "5", "--testers", "3"]), 0)


if __name__ == "__main__":
    unittest.main()
