"""video_progress.py（動画生成の進捗）のテスト。実行: uv run python -m unittest discover -s houdini/tests -v"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import video_progress as vp  # noqa: E402

LOG_START = (
    "Run ID: 1\nNarration engine: ...\nLoading Houdini tutorial markdown: C:/x.md\n"
)
LOG_SPLIT = (
    LOG_START
    + "Beginner script applied (16 step text(s), source=claude)\nSplit into 22 slides\n"
)
LOG_NARRATION = (
    LOG_SPLIT + "Synthesizing scripted narration (22 slides, 1405 chars)...\n"
)


class ProgressFromLogTest(unittest.TestCase):
    def test_stages_advance_monotonically_through_a_real_run(self) -> None:
        text = ""
        seen: list[int] = []
        steps = [
            "",
            LOG_START,
            LOG_SPLIT,
            LOG_NARRATION,
            LOG_NARRATION + "Narration progress: 1 / 20\n",
            LOG_NARRATION + "Narration progress: 10 / 20\n",
            LOG_NARRATION
            + "Narration progress: 20 / 20\nNarration synthesized: 259.6s\n",
            LOG_NARRATION
            + "Narration synthesized: 259.6s\nVideo duration: 261.1s (3916 frames)\nRendered frame 0 / 3916\n",
            LOG_NARRATION
            + "Narration synthesized: 259.6s\nRendered frame 1958 / 3916\n",
            LOG_NARRATION
            + "Narration synthesized: 259.6s\nRendered frame 3915 / 3916\n",
            LOG_NARRATION
            + "Rendered frame 3915 / 3916\nWrote phase2_x.webm (3916 frames, 261.1s)\n",
        ]
        for text in steps:
            seen.append(vp.progress_from_log(text).percent)
        self.assertEqual(seen, sorted(seen), seen)
        self.assertEqual(seen[-1], 100)
        self.assertGreaterEqual(seen[0], vp.ENGINE_START)
        self.assertLess(seen[-2], 100)

    def test_labels_and_stages(self) -> None:
        self.assertEqual(vp.progress_from_log("").stage, "start")
        self.assertEqual(vp.progress_from_log(LOG_START).label, "資料を読み込み中")
        p = vp.progress_from_log(LOG_NARRATION + "Narration progress: 10 / 20\n")
        self.assertEqual((p.stage, p.label), ("narration", "音声を作成中 10/20"))
        self.assertEqual(p.percent, 50)  # 30 + 40 * 10/20
        p = vp.progress_from_log(
            "Narration synthesized: 1s\nRendered frame 1958 / 3916\n"
        )
        self.assertEqual((p.stage, p.percent), ("render", 84))  # 70 + 28 * 0.5
        self.assertIn("1958/3916", p.label)

    def test_done_returns_the_file_name(self) -> None:
        p = vp.progress_from_log(
            "Rendered frame 3915 / 3916\nWrote phase2_cloudrag_1_ab.webm (3916 frames, 261.1s)\n"
        )
        self.assertTrue(p.done)
        self.assertEqual(p.webm, "phase2_cloudrag_1_ab.webm")
        self.assertEqual(p.percent, 100)

    def test_failure_is_flagged_but_keeps_the_percent(self) -> None:
        p = vp.progress_from_log(
            LOG_NARRATION + "Narration progress: 5 / 20\nERROR: cannot open file\n"
        )
        self.assertTrue(p.failed)
        self.assertEqual(p.stage, "failed")
        self.assertEqual(p.percent, 40)  # 30 + 40 * 5/20
        self.assertIn("cannot open file", p.label)

    def test_zero_totals_do_not_divide_by_zero(self) -> None:
        self.assertEqual(
            vp.progress_from_log(
                "Narration synthesized\nRendered frame 0 / 0\n"
            ).percent,
            vp.RENDER_START,
        )
        self.assertEqual(
            vp.progress_from_log("Narration progress: 0 / 0\n").percent,
            vp.NARRATION_START,
        )

    def test_single_text_narration_without_progress_lines(self) -> None:
        p = vp.progress_from_log("Synthesizing narration (2137 chars)...\n")
        self.assertEqual((p.stage, p.percent), ("narration", vp.NARRATION_START))

    def test_scripted_stage_percent_is_bounded_and_increasing(self) -> None:
        values = [vp.script_stage_percent(t) for t in (0, 5, 15, 30, 60, 300, 3600)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], 0)
        self.assertLess(values[-1], vp.SCRIPT_END)


if __name__ == "__main__":
    unittest.main()
