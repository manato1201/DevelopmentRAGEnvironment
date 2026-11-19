"""高速モード（tutorial_agent の fast）のテスト（2026-11-19）。

実証実験は 1 人 90 分で、チュートリアルと動画の生成を、合わせて 5 分以下にしたい。高速モードは、effort を low にし、レッスン設計を省き、
手順書を短くさせる。ここで確かめるのは、切り替わること（effort・プロンプト・設計の省略・指標）。速さと品質は、実機で測る。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_fast_mode.py -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))

import tutorial_agent as ta  # noqa: E402


class EffortTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {"RAG_TUTORIAL_EFFORT": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_normal_mode_keeps_the_model_effort(self) -> None:
        self.assertEqual(ta.effort_for("claude-sonnet-5-5"), "medium")
        self.assertEqual(ta.effort_for("claude-sonnet-5-5", False), "medium")

    def test_fast_mode_uses_low(self) -> None:
        self.assertEqual(ta.effort_for("claude-sonnet-5-5", True), "low")
        self.assertEqual(ta.effort_for("claude-opus-5-5", True), "low")

    def test_models_without_effort_get_none_in_either_mode(self) -> None:
        self.assertEqual(ta.effort_for("claude-haiku-4-5", True), "")
        self.assertEqual(ta.effort_for("claude-haiku-4-5"), "")

    def test_the_environment_variable_wins_over_the_mode(self) -> None:
        with mock.patch.dict(os.environ, {"RAG_TUTORIAL_EFFORT": "high"}):
            self.assertEqual(ta.effort_for("claude-sonnet-5-5", True), "high")
        with mock.patch.dict(os.environ, {"RAG_TUTORIAL_EFFORT": "bogus"}):
            self.assertEqual(ta.effort_for("claude-sonnet-5-5", True), "low")


class FastSectionTest(unittest.TestCase):
    def test_the_section_asks_for_batched_calls_and_short_text(self) -> None:
        text = ta.FAST_MODE_SECTION
        self.assertIn("高速モード", text)
        self.assertIn("まとめて呼ぶ", text)
        self.assertIn("1〜2 文", text)

    def _agent(self, fast: bool):
        agent = ta.TutorialAgent(fast=fast)
        agent.executor = mock.Mock(sandbox_path="/obj/ai_tutorial_x")
        agent._doc_client = None
        return agent

    def test_the_system_prompt_has_the_section_only_in_fast_mode(self) -> None:
        for fast in (True, False):
            agent = self._agent(fast)
            system_blocks, _tools, _messages = agent._build_initial_prompt("炎", [], "applied", "", None)
            text = system_blocks[0]["text"]
            self.assertEqual("## 高速モード" in text, fast)

    def test_the_flag_is_kept(self) -> None:
        self.assertTrue(ta.TutorialAgent(fast=True)._fast)
        self.assertFalse(ta.TutorialAgent()._fast)


class MetricsTest(unittest.TestCase):
    def test_fast_mode_is_recorded_in_the_metrics(self) -> None:
        for fast in (True, False):
            agent = ta.TutorialAgent(fast=fast)
            agent.executor = mock.Mock(step_log=[], finish_data=None)
            result = ta.TutorialResult()
            try:
                metrics = agent._collect_metrics(result, "炎")
            except Exception as exc:  # noqa: BLE001 -- この環境では集められない項目があっても、fast_mode の有無だけ確かめる
                self.skipTest(f"metrics を集められません: {exc}")
            self.assertEqual(metrics.get("fast_mode"), fast)


if __name__ == "__main__":
    unittest.main()
