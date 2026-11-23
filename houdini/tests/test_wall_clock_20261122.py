"""2026-11-22 の実機の記録（validate_network 1回が6264秒）を受けた、時間の上限のテスト。

  ・validate_network : cook の合計に上限を設け、超えたら残りを省略して、省略したノードを結果に書く（「OK」とは言わない）
  ・ノードごとの cook 秒数を、結果と step_log / 監査ログに残す
  ・エージェントのループ : 経過時間の上限で仕上げを促し、超えたら打ち切る（wrapup_stage の段階に乗せる）
遅かった原因そのものは未確認（小さな Vellum + File Cache のネットワークでは、hython 22.0.506 で再現しなかった）。
ここでは「遅いノードがあっても、上限で止まり、どのノードかが残る」ことだけを確かめる。
実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))
sys.modules.setdefault("hou", types.ModuleType("hou"))

import houdini_tools as ht  # noqa: E402
from test_generation_20261117 import LoopStub  # noqa: E402
from test_parm_tools import make_executor, make_world  # noqa: E402


class FakeClock:
    """time.monotonic の代わり。cook が「かかった秒数」を、実際に待たずに進める。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ValidateBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.ex = make_executor(self.hou, self.sandbox)
        self.clock = FakeClock()
        patcher = mock.patch.object(ht.time, "monotonic", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.geo = self.add("geo1", "geo", "Object")
        self.box = self.add("geo1/box1", "box", "Sop", parent=self.geo)
        self.xform = self.add("geo1/xform1", "xform", "Sop", parent=self.geo)
        self.box.out = [self.xform]

    def slow(self, node, seconds: float) -> None:
        """このノードの cook が、seconds 秒かかったことにする。"""
        def cook(force=False, _node=node):
            _node.cooks += 1
            self.clock.now += seconds
        node.cook = cook

    def test_a_fast_network_is_unchanged_and_says_nothing_extra(self) -> None:
        out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証OK"), out)
        self.assertNotIn("[未検証]", out)
        self.assertNotIn("[cook時間]", out)

    def test_over_budget_skips_the_rest_and_names_them_and_is_not_ok(self) -> None:
        self.slow(self.box, 90)  # 1個で上限（60秒）を超える
        out = self.ex._tool_validate_network({})
        self.assertFalse(out.startswith("検証OK"), out)
        self.assertTrue(out.startswith("検証未完了"), out)
        self.assertIn("[未検証]", out)
        self.assertIn("geo1/xform1", out, "the node that was not cooked is named")
        self.assertEqual(self.xform.cooks, 0)
        self.assertEqual(self.box.cooks, 1)
        self.assertIn("エラー・警告が無いとは言えません", out)

    def test_issues_found_so_far_still_win_and_the_skip_note_is_appended(self) -> None:
        self.slow(self.box, 90)
        self.box.warns = ["Unused parameter"]
        out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証NG"), out)
        self.assertIn("[警告] geo1/box1: Unused parameter", out)
        self.assertIn("[未検証]", out)

    def test_errors_of_skipped_nodes_are_still_read_without_cooking(self) -> None:
        """cook しなくても、前に cook したときの errors() は読める。"""
        self.slow(self.box, 90)
        self.xform.errs = ["Input geometry is empty"]
        out = self.ex._tool_validate_network({})
        self.assertIn("[エラー] geo1/xform1: Input geometry is empty", out)
        self.assertEqual(self.xform.cooks, 0)

    def test_shallow_nodes_are_cooked_first_so_asset_internals_are_the_ones_skipped(self) -> None:
        cloth = self.add("geo1/arm_cloth", "vellumconstraints::2.0", "Sop", parent=self.geo)  # 型名が "vellum" を含む: 単体では cook しない
        inner1 = self.add("geo1/arm_cloth/merge1", "merge", "Sop", parent=cloth)
        inner2 = self.add("geo1/arm_cloth/merge2", "merge", "Sop", parent=cloth)
        last = self.add("geo1/merge_final", "merge", "Sop", parent=self.geo)  # 作成順では、アセットの内部より後ろ
        for node in (self.box, self.xform, last, inner1, inner2):
            self.slow(node, 25)
        out = self.ex._tool_validate_network({})
        for shallow in (self.box, self.xform, last):
            self.assertEqual(shallow.cooks, 1, shallow.path())
        # 60秒の予算は、浅い3個（25秒 x 3 = 75秒）で尽きる。作成順なら merge_final は内部の後ろだが、浅い順に cook するので、内部が省略される
        self.assertEqual((inner1.cooks, inner2.cooks), (0, 0))
        self.assertIn("arm_cloth/merge1", out)
        self.assertIn("arm_cloth/merge2", out)
        self.assertNotIn("geo1/merge_final,", out.split("[未検証]")[1], "the user's own node is not among the skipped")

    def test_slow_nodes_are_reported_in_the_result_slowest_first(self) -> None:
        self.slow(self.box, 3.2)
        self.slow(self.xform, 7.5)
        out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証OK"), out)
        self.assertIn("[cook時間] 1秒以上かかったノード: geo1/xform1 7.5秒, geo1/box1 3.2秒", out)

    def test_per_node_seconds_reach_the_step_log_and_the_audit_log(self) -> None:
        self.slow(self.box, 90)
        with tempfile.TemporaryDirectory() as tmp:
            self.ex._log_path = Path(tmp) / "audit.jsonl"
            out, is_error = self.ex.execute("validate_network", {})
            records = [json.loads(line) for line in self.ex._log_path.read_text(encoding="utf-8").splitlines()]
        self.assertFalse(is_error)
        entry = self.ex.step_log[-1]
        self.assertEqual(entry["tool"], "validate_network")
        self.assertEqual(entry["cook_seconds"], {"geo1/box1": 90.0})
        self.assertEqual(entry["cook_skipped"], ["geo1/xform1"])
        self.assertEqual(entry["cooked"], 1)
        self.assertEqual(entry["cook_budget_s"], ht.HoudiniToolExecutor._VALIDATE_COOK_BUDGET_S)
        tool_call = next(r for r in records if r.get("event") == "tool_call")
        self.assertEqual(tool_call["cook_seconds"], {"geo1/box1": 90.0}, "the audit log carries it too")
        slow = [r for r in records if r.get("event") == "slow_cook"]
        self.assertEqual([(r["node"], r["elapsed_s"]) for r in slow], [("geo1/box1", 90.0)])
        self.assertIn("検証未完了", out)

    def test_the_extras_do_not_leak_into_the_next_tool_call(self) -> None:
        self.ex.execute("validate_network", {})
        self.assertIn("cook_seconds", self.ex.step_log[-1])
        self.ex.execute("no_such_tool", {})
        self.assertNotIn("cook_seconds", self.ex.step_log[-1])

    def test_a_long_list_of_skipped_nodes_is_cut_but_logged_in_full(self) -> None:
        self.slow(self.box, 90)
        for i in range(20):
            self.add(f"geo1/extra{i}", "null", "Sop", parent=self.geo)
        out, _ = self.ex.execute("validate_network", {})
        listed = ht.HoudiniToolExecutor._VALIDATE_LIST_MAX
        self.assertIn(f"ほか {21 - listed} 個", out)  # xform1 + extra0..19 = 21個を省略
        self.assertEqual(len(self.ex.step_log[-1]["cook_skipped"]), 21)

    def test_budget_is_a_class_constant_that_can_be_raised(self) -> None:
        self.slow(self.box, 90)
        with mock.patch.object(ht.HoudiniToolExecutor, "_VALIDATE_COOK_BUDGET_S", 600.0):
            out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証OK"), out)
        self.assertEqual(self.xform.cooks, 1)

    def test_simulation_nodes_are_still_not_cooked(self) -> None:
        solver = self.add("geo1/pyrosolver1", "pyrosolver::2.0", "Sop", parent=self.geo)
        solver.out = [self.xform]
        self.ex._tool_validate_network({})
        self.assertEqual(solver.cooks, 0)


class WrapupStageWallClockTest(unittest.TestCase):
    def test_elapsed_time_raises_the_stage_like_cost_does(self) -> None:
        import tutorial_agent as ta

        stage = lambda s: ta.wrapup_stage(10, 80, 0.0, 5.0, elapsed_s=s, wall_limit=1000.0)  # noqa: E731
        self.assertEqual([stage(s) for s in (0, 399, 400, 599, 600, 849, 850, 1200)], [0, 0, 1, 1, 2, 2, 3, 3])

    def test_without_a_wall_limit_the_old_arguments_behave_as_before(self) -> None:
        import tutorial_agent as ta

        self.assertEqual(ta.wrapup_stage(10, 80, 2.1, 5.0), 1)
        self.assertEqual(ta.wrapup_stage(10, 80, 0, 5.0, elapsed_s=99999, wall_limit=0), 0)

    def test_the_cost_and_time_ratios_do_not_add_up(self) -> None:
        import tutorial_agent as ta

        self.assertEqual(ta.wrapup_stage(10, 80, 1.0, 5.0, elapsed_s=300, wall_limit=1000.0), 0)  # 0.2 と 0.3: どちらも 0.4 未満


class AgentLoopWallClockTest(unittest.TestCase):
    """_run_loop は、ターンの区切りで経過時間を確かめる。時計は、LoopStub の API 呼び出しの中で進める。"""

    def stub_with_clock(self, seconds_per_call: float, script=lambda n: ("create_node", {})):
        stub = LoopStub(script)
        clock = FakeClock()
        original = stub.agent._call_api

        def api(system, tools, messages):
            clock.now += seconds_per_call
            return original(system, tools, messages)

        stub.agent._call_api = api
        return stub, clock

    def run_with(self, stub, clock, limit):
        with mock.patch.object(stub.ta.time, "monotonic", clock), mock.patch.object(stub.ta, "WALL_LIMIT_SECONDS", limit):
            return stub.run()

    def test_the_run_stops_when_the_wall_limit_is_passed(self) -> None:
        stub, clock = self.stub_with_clock(100.0)
        result = self.run_with(stub, clock, 1000.0)
        self.assertEqual(stub.calls, 11, "100秒 x 10回 = 1000秒ちょうどは、まだ超えていない。11回目のあと（1100秒）に止まる")
        self.assertIn("時間上限", result.abort_reason)
        events = [e for e in stub.agent.executor.events if e.get("event") == "wall_limit"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["limit_s"], 1000.0)

    def test_a_single_very_long_turn_is_caught_before_the_next_api_call(self) -> None:
        """6264秒のような、1回の呼び出しが長かった場合: そのターンのあとの確認で止まる。"""
        stub, clock = self.stub_with_clock(0.0)
        original = stub.agent.executor.execute

        def execute(name, args):
            clock.now += 6264.0
            return original(name, args)

        stub.agent.executor.execute = execute
        result = self.run_with(stub, clock, 2700.0)
        self.assertEqual(stub.calls, 1)
        self.assertIn("時間上限", result.abort_reason)

    def test_the_nudges_come_before_the_limit_using_the_same_stages(self) -> None:
        stub, clock = self.stub_with_clock(100.0)
        self.run_with(stub, clock, 1000.0)
        turns = [turn for turn, _ in stub.nudges()]
        self.assertEqual(turns, [4, 6, 9], stub.nudges())  # 400秒 / 600秒 / 850秒 → 段階 1 / 2 / 3
        self.assertIn("進捗", stub.nudges()[0][1])
        self.assertIn("新しい要素は足さず", stub.nudges()[1][1])

    def test_a_finished_run_is_not_cut_off(self) -> None:
        script = {1: ("create_node", {}), 2: ("finish_tutorial", {"title": "t"}), 3: ("confirm_tutorial", {"looks_correct": True})}
        stub, clock = self.stub_with_clock(500.0, lambda n: script.get(n, ("create_node", {})))
        result = self.run_with(stub, clock, 1000.0)
        self.assertEqual(result.abort_reason, "")
        self.assertIsNotNone(stub.agent.executor.finish_data)

    def test_zero_disables_the_wall_limit(self) -> None:
        stub, clock = self.stub_with_clock(1e6)
        result = self.run_with(stub, clock, 0.0)
        self.assertNotIn("時間上限", result.abort_reason)
        self.assertEqual(stub.calls, 80 + stub.ta.FINISH_RESERVE_ITERATIONS)

    def test_the_default_is_far_above_a_normal_run(self) -> None:
        import tutorial_agent as ta

        self.assertEqual(ta.WALL_LIMIT_SECONDS, 45 * 60.0)
        self.assertGreater(ta.WALL_LIMIT_SECONDS, 16 * 60, "the normal run in the 2026-11-22 log took about 16 minutes without the stuck call")


if __name__ == "__main__":
    unittest.main()
