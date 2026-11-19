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


class OneShotOptionsTest(unittest.TestCase):
    """complete_text の、出力の上限と effort（Reference の説明を、短く・安くするための 1 回だけの指定）。"""

    def _post(self, model: str, **options) -> dict:
        import io
        import json

        agent = ta.TutorialAgent(model=model, cf_url="https://example.invalid", cf_api_key="x")
        sent: dict = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=0):
            sent.update(json.loads(req.data.decode("utf-8")))
            return Resp(json.dumps({"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 2}}).encode())

        with mock.patch.dict(os.environ, {"RAG_TUTORIAL_EFFORT": ""}), mock.patch.object(ta.urllib.request, "urlopen", fake_urlopen):
            text, usage = agent.complete_text("sys", "user", **options)
        self.assertEqual((text, usage["output_tokens"]), ("ok", 2))
        self.assertIsNone(agent.__dict__.get("_one_shot"))  # 次の呼び出しには、残らない
        return sent

    def test_limits_apply_to_that_one_call_only(self) -> None:
        body = self._post("claude-sonnet-5-5", max_tokens=1800, effort="low")
        self.assertEqual(body["max_tokens"], 1800)
        self.assertEqual(body["output_config"], {"effort": "low"})

    def test_defaults_are_unchanged_without_options(self) -> None:
        body = self._post("claude-sonnet-5-5")
        self.assertEqual(body["max_tokens"], ta.MAX_TOKENS_PER_TURN)
        self.assertEqual(body["output_config"], {"effort": "medium"})

    def test_a_model_without_effort_gets_none(self) -> None:
        self.assertNotIn("output_config", self._post("claude-haiku-4-5", effort="low"))

    def test_the_environment_variable_still_wins(self) -> None:
        import io
        import json

        agent = ta.TutorialAgent(model="claude-sonnet-5-5", cf_url="https://example.invalid", cf_api_key="x")
        sent: dict = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=0):
            sent.update(json.loads(req.data.decode("utf-8")))
            return Resp(json.dumps({"content": [], "usage": {}}).encode())

        with mock.patch.dict(os.environ, {"RAG_TUTORIAL_EFFORT": "high"}), mock.patch.object(ta.urllib.request, "urlopen", fake_urlopen):
            agent.complete_text("s", "u", effort="low")
        self.assertEqual(sent["output_config"], {"effort": "high"})


class UsageCostTest(unittest.TestCase):
    def test_cost_uses_the_model_price_and_falls_back_for_unknown_models(self) -> None:
        usage = {"input_tokens": 5000, "output_tokens": 1000}
        self.assertAlmostEqual(ta.usage_cost_for("claude-sonnet-5-5", usage), 0.02, places=6)
        self.assertAlmostEqual(ta.usage_cost_for("unknown-model", usage), ta.usage_cost_for(ta.DEFAULT_MODEL, usage), places=9)
        self.assertEqual(ta.usage_cost_for("claude-sonnet-5-5", {}), 0.0)


if __name__ == "__main__":
    unittest.main()
