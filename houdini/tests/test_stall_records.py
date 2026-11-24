"""生成が止まったとき、どこで止まったかを、監査ログから分けられること（2026-11-25）。
・メインスレッドの空きを待った時間（wait_s）と、ツール本体の時間を分ける
・ツールのあとの画面撮影は、始まりも記録する（capture_start）。終わりの記録（capture）が無ければ、撮影で止まった
・scripts/analyze_generation_logs.py が、上限に近い回・止まった回を数える
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "houdini" / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

import houdini_tools as ht  # noqa: E402
from test_parm_tools import make_executor, make_world  # noqa: E402


class StallRecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        hou, sandbox, _add, _nodes = make_world()
        self.ex = make_executor(hou, sandbox)
        self.ex._log_path = Path(self.tmp.name) / "audit.jsonl"
        self.ex._capture_step_screenshot = lambda *a, **k: None  # 撮影は、しない（このテストでは、記録だけを見る）

    def _events(self) -> list[dict]:
        return [json.loads(line) for line in self.ex._log_path.read_text(encoding="utf-8").splitlines()]

    def test_a_busy_main_thread_is_recorded_as_wait(self) -> None:
        def slow_dispatch(fn):
            time.sleep(0.6)  # Houdini が、別の処理で塞がっている
            return fn()

        self.ex._tool_slowtool = lambda args: "ok"
        with mock.patch.object(ht, "_run_in_main_thread", slow_dispatch):
            self.ex.execute("slowtool", {})
        call = next(e for e in self._events() if e.get("event") == "tool_call")
        self.assertGreaterEqual(call["wait_s"], 0.5)

    def test_no_wait_is_not_recorded(self) -> None:
        self.ex._tool_quick = lambda args: "ok"
        self.ex.execute("quick", {})
        call = next(e for e in self._events() if e.get("event") == "tool_call")
        self.assertNotIn("wait_s", call)

    def test_the_capture_start_is_recorded_for_tools_that_take_a_picture(self) -> None:
        self.ex._tool_create_node = lambda args: "作成しました"
        self.ex.execute("create_node", {"node_type": "box"})
        kinds = [e.get("event") for e in self._events()]
        self.assertEqual(kinds[:2], ["tool_call", "capture_start"])


class AnalyzerTest(unittest.TestCase):
    def test_runs_near_the_limit_and_stalled_runs_are_counted(self) -> None:
        import analyze_generation_logs as ag

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            near = [{"event": "api_call"}] * 70 + [{"event": "tool_call", "tool": "cook_node", "elapsed_s": 2}]
            stalled = [{"event": "api_call"}, {"event": "tool_call", "tool": "validate_network", "elapsed_s": 700, "is_error": False}]
            for name, events in (("ai_tutorial_1", near), ("ai_tutorial_2", stalled)):
                (folder / f"{name}.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n", encoding="utf-8")
            first = ag.summarize(folder / "ai_tutorial_1.jsonl")
            self.assertEqual((first["api"], first["tools"], first["slow"]), (70, 1, 0))
            second = ag.summarize(folder / "ai_tutorial_2.jsonl")
            self.assertEqual(second["slowest"], ("validate_network", 700.0))
            self.assertEqual(second["slow"], 1)
            self.assertEqual(ag.main([str(folder)]), 0)
            self.assertEqual(ag.main([str(folder / "none")]), 1)


if __name__ == "__main__":
    unittest.main()
