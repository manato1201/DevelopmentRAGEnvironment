"""scripts/compare_tutorial_metrics.py（生成指標の集計）のテスト。標準の unittest。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import compare_tutorial_metrics as cm  # noqa: E402


def row(**kw) -> dict:
    base = {
        "completed": True,
        "iterations": 40,
        "cook_errors": 0,
        "confirm_rejections": 0,
        "cost_usd": 0.3,
        "elapsed_seconds": 100,
        "rag_extraction_rate": 0.0,
    }
    base.update(kw)
    return base


class SummarizeTest(unittest.TestCase):
    def test_old_metrics_without_the_flag_are_the_baseline(self) -> None:
        s = cm.summarize(
            [row(), row(doc_tools=False), row(doc_tools=True, doc_searches=4)]
        )
        self.assertEqual(s["なし(従来)"]["n"], 2)
        self.assertEqual(s["あり(doc_tools)"]["n"], 1)
        self.assertEqual(s["あり(doc_tools)"]["doc_searches"], 4)

    def test_unmeasured_citation_rates_are_left_out_of_the_mean(self) -> None:
        s = cm.summarize(
            [
                row(rag_extraction_rate=0.5),
                row(rag_extraction_rate=-1),
                row(rag_extraction_rate=0.0),
            ]
        )
        group = s["なし(従来)"]
        self.assertAlmostEqual(group["rag_extraction_rate"], 0.25)
        self.assertEqual(group["rag_extraction_rate_n"], 2)

    def test_booleans_average_as_rates_and_missing_keys_are_none(self) -> None:
        s = cm.summarize(
            [
                row(completed=True),
                row(completed=False),
                row(completed=True),
                row(completed=True),
            ]
        )
        group = s["なし(従来)"]
        self.assertAlmostEqual(group["completed"], 0.75)
        self.assertIsNone(group["doc_reads"])
        self.assertIsNone(group["rag_initial_extraction_rate"])

    def test_group_by_another_key(self) -> None:
        s = cm.summarize(
            [
                row(domain="particles"),
                row(domain="particles"),
                row(domain="copernicus"),
            ],
            by="domain",
        )
        self.assertEqual(
            {k: v["n"] for k, v in s.items()}, {"copernicus": 1, "particles": 2}
        )

    def test_render_has_a_row_per_group_and_dashes_for_missing(self) -> None:
        text = cm.render(cm.summarize([row()]), "doc_tools")
        self.assertIn("なし(従来)", text)
        self.assertIn("-", text.splitlines()[1])
        self.assertEqual(len(text.splitlines()), 2)

    def test_load_skips_broken_files(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "a_metrics.json").write_text(json.dumps(row()), encoding="utf-8")
            (d / "b_metrics.json").write_text("{broken", encoding="utf-8")
            (d / "c_metrics.json").write_text("[1, 2]", encoding="utf-8")
            (d / "other.json").write_text(json.dumps(row()), encoding="utf-8")
            rows = cm.load_metrics(d)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
