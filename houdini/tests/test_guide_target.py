"""Guide が、手順の指すノードと「別のオブジェクト」を出さないこと（2026-11-17 の実証実験の指摘）のテスト。

最初の4つ（Repro）は、直す前の動きを再現するもの。直す前は、すべて失敗した（報告書に記録）。
Houdini は偽物（guide_fakes.py）。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_guide_target.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import guide_mode as gm  # noqa: E402
from guide_fakes import make_world  # noqa: E402

SANDBOX = "/obj/ai_tutorial_20261117_171700"
OLD_SANDBOX = "/obj/ai_tutorial_20261116_120000"


def wrangle_step(**over):
    step = {
        "tool": "set_parameter", "tab": "parm", "node": "vortex_points", "node_path": "geo1/vortex_points",
        "node_type": "attribwrangle", "node_label": "Attribute Wrangle",
        "parms": [{"name": "class", "label": "Run Over", "old": "0", "new": "2", "where": ""}],
    }
    step.update(over)
    return step


class ReproWrongObjectTest(unittest.TestCase):
    """直す前の動き: 別のオブジェクトが選ばれていた。"""

    def test_create_step_does_not_select_another_node_of_the_same_type(self):
        """scatter2 を作る手順で、すでにある scatter1 を「操作するノード」として出していた（種類が同じというだけで）。"""
        world = make_world({"/obj/geo1/scatter1": "scatter::2.0"}, pwd="/obj/geo1")
        step = {"tool": "create_node", "tab": "network", "node": "scatter2", "node_path": "geo1/scatter2",
                "node_type": "scatter::2.0", "node_label": "Scatter"}
        messages = gm.apply_step(world.hou, step)
        self.assertEqual(world.hou.selectedNodes(), [], "an existing node must not be shown for a node that is still to be made")
        self.assertTrue(any("まだありません" in m for m in messages), messages)

    def test_the_same_name_in_an_older_sandbox_is_not_picked(self):
        """前の生成のサンドボックスにも同じ名前のノードがあると、そちらが選ばれていた。"""
        world = make_world({
            f"{OLD_SANDBOX}/geo1/vortex_points": "attribwrangle",   # /obj の中で先に見つかる
            "/obj/geo1/vortex_points": "attribwrangle",
        }, pwd="/obj")
        gm.apply_step(world.hou, wrangle_step())
        shown = [n.path() for n in world.hou.selectedNodes()]
        self.assertEqual(shown, ["/obj/geo1/vortex_points"])

    def test_the_network_is_switched_before_the_node_is_made_current(self):
        """先にノードを選び、あとでネットワークを切り替えていた。切り替えのあとに選ばないと、パラメータ画面がずれる。"""
        world = make_world({"/obj/geo1/vortex_points": "attribwrangle"}, pwd="/obj")
        gm.apply_step(world.hou, wrangle_step())
        calls = [c[0] for c in world.log]
        self.assertIn("setPwd", calls)
        self.assertLess(calls.index("setPwd"), calls.index("setCurrent"))

    def test_a_pinned_parameter_pane_is_released(self):
        """パラメータのペインがピンで固定されていると、選んだノードに追従せず、別のノードのパラメータが出ていた。"""
        world = make_world({"/obj/geo1/vortex_points": "attribwrangle"}, pwd="/obj/geo1", parm_pinned=True)
        gm.apply_step(world.hou, wrangle_step())
        self.assertFalse(world.parm.pinned)


class ResolveTargetTest(unittest.TestCase):
    def test_the_exact_path_wins_over_a_same_named_node_elsewhere(self):
        world = make_world({
            "/obj/geo2/vortex_points": "attribwrangle",
            "/obj/geo1/vortex_points": "attribwrangle",
        }, pwd="/obj/geo2")
        hit = gm.resolve_step_target(world.hou, wrangle_step())
        self.assertEqual((hit.node.path(), hit.how), ("/obj/geo1/vortex_points", "path"))

    def test_a_node_with_the_right_name_but_another_type_is_not_accepted(self):
        world = make_world({"/obj/geo1/vortex_points": "null"}, pwd="/obj/geo1")
        hit = gm.resolve_step_target(world.hou, wrangle_step())
        self.assertIsNone(hit.node)
        self.assertIn("種類", hit.note)

    def test_sandbox_mode_reads_the_sandbox_copy(self):
        world = make_world({
            f"{SANDBOX}/geo1/vortex_points": "attribwrangle",
            "/obj/geo1/vortex_points": "attribwrangle",
        }, pwd="/obj")
        hit = gm.resolve_step_target(world.hou, wrangle_step(), sandbox_path=SANDBOX, mode="sandbox")
        self.assertEqual(hit.node.path(), f"{SANDBOX}/geo1/vortex_points")
        own = gm.resolve_step_target(world.hou, wrangle_step(), sandbox_path=SANDBOX, mode="own")
        self.assertEqual(own.node.path(), "/obj/geo1/vortex_points")

    def test_auto_prefers_the_learners_node_then_falls_back_to_the_sandbox_and_says_so(self):
        world = make_world({f"{SANDBOX}/geo1/vortex_points": "attribwrangle"}, pwd="/obj")
        hit = gm.resolve_step_target(world.hou, wrangle_step(), sandbox_path=SANDBOX)
        self.assertEqual(hit.node.path(), f"{SANDBOX}/geo1/vortex_points")
        self.assertEqual(hit.where, "sandbox")
        self.assertIn("サンドボックス", hit.note)

    def test_auto_does_not_jump_to_the_sandbox_for_a_node_to_be_created(self):
        world = make_world({f"{SANDBOX}/geo1/vortex_points": "attribwrangle", "/obj/geo1": "geo"}, pwd="/obj")
        step = wrangle_step(tool="create_node", tab="network", parms=[])
        hit = gm.resolve_step_target(world.hou, step, sandbox_path=SANDBOX)
        self.assertIsNone(hit.node)
        self.assertEqual(hit.container.path(), "/obj/geo1", "the network where the node is to be made is still shown")

    def test_another_name_of_the_same_type_is_offered_only_when_it_is_the_only_one_in_the_expected_network(self):
        world = make_world({"/obj/geo1/wrangle1": "attribwrangle"}, pwd="/obj/geo1")
        hit = gm.resolve_step_target(world.hou, wrangle_step())
        self.assertEqual((hit.node.path(), hit.how), ("/obj/geo1/wrangle1", "type"))
        self.assertIn("名前が違う", hit.note)
        world = make_world({"/obj/geo1/wrangle1": "attribwrangle", "/obj/geo1/wrangle2": "attribwrangle"}, pwd="/obj/geo1")
        hit = gm.resolve_step_target(world.hou, wrangle_step())
        self.assertIsNone(hit.node)
        self.assertIn("wrangle1", hit.note)
        self.assertIn("wrangle2", hit.note)

    def test_the_learner_may_have_put_it_one_level_off_and_a_unique_name_is_still_found(self):
        world = make_world({"/obj/mygeo/vortex_points": "attribwrangle"}, pwd="/obj")
        hit = gm.resolve_step_target(world.hou, wrangle_step())
        self.assertEqual((hit.node.path(), hit.how), ("/obj/mygeo/vortex_points", "name"))

    def test_two_candidates_with_the_same_name_are_not_guessed(self):
        world = make_world({"/obj/a/vortex_points": "attribwrangle", "/obj/b/vortex_points": "attribwrangle"}, pwd="/obj")
        hit = gm.resolve_step_target(world.hou, wrangle_step())
        self.assertIsNone(hit.node)
        self.assertIn("/obj/a/vortex_points", hit.note)
        self.assertIn("/obj/b/vortex_points", hit.note)

    def test_a_name_match_is_not_used_when_the_search_was_cut_short(self):
        """探索の上限に達したときは、見つかった 1 つが「唯一」とは言えない。当て推量で選ばず、理由を出す。"""
        world = make_world({"/obj/mygeo/vortex_points": "attribwrangle", "/obj/zz/a": "null", "/obj/zz/b": "null", "/obj/zz/c": "null"}, pwd="/obj")
        old = gm._MAX_SEARCH
        gm._MAX_SEARCH = 3
        try:
            hit = gm.resolve_step_target(world.hou, wrangle_step())
        finally:
            gm._MAX_SEARCH = old
        self.assertIsNone(hit.node)
        self.assertIn("上限", hit.note)

    def test_the_reason_is_given_when_nothing_is_found(self):
        world = make_world({}, pwd="/obj")
        hit = gm.resolve_step_target(world.hou, wrangle_step())
        self.assertIsNone(hit.node)
        self.assertIn("/obj/geo1/vortex_points", hit.note)
        self.assertIn("見つかりません", hit.note)


class ApplyStepTest(unittest.TestCase):
    def test_apply_shows_the_node_and_verifies_it(self):
        world = make_world({"/obj/geo1/vortex_points": "attribwrangle"}, pwd="/obj")
        messages = gm.apply_step(world.hou, wrangle_step())
        node = world.hou.node("/obj/geo1/vortex_points")
        self.assertTrue(node.current)
        self.assertEqual(world.editor.pwd().path(), "/obj/geo1")
        self.assertTrue(any("/obj/geo1/vortex_points" in m for m in messages), messages)
        self.assertEqual(world.parm.shown, 1)
        self.assertIsNone(gm.verify_shown(world.hou, node))

    def test_verify_reports_a_mismatch(self):
        world = make_world({"/obj/geo1/vortex_points": "attribwrangle", "/obj/geo1/other": "null"}, pwd="/obj/geo1")
        node = world.hou.node("/obj/geo1/vortex_points")
        world.hou.node("/obj/geo1/other").setCurrent(True, clear_all_selected=True)
        self.assertIn("選ばれていません", gm.verify_shown(world.hou, node))

    def test_a_parameter_step_tells_the_tab_and_the_item(self):
        world = make_world({"/obj/geo1/vortex_points": "attribwrangle"}, pwd="/obj")
        step = wrangle_step(parms=[{"name": "class", "label": "Run Over", "old": "0", "new": "2", "where": "Sourcing > Emission"}])
        messages = gm.apply_step(world.hou, step)
        text = "\n".join(messages)
        self.assertIn("パラメータのタブ: Sourcing > Emission", text)
        self.assertIn("項目: Run Over", text)

    def test_a_missing_node_for_a_create_step_moves_to_the_network_where_it_is_made(self):
        world = make_world({"/obj/geo1": "geo"}, pwd="/obj")
        step = {"tool": "create_node", "tab": "network", "node": "scatter1", "node_path": "geo1/scatter1",
                "node_type": "scatter::2.0", "node_label": "Scatter"}
        messages = gm.apply_step(world.hou, step)
        self.assertEqual(world.editor.pwd().path(), "/obj/geo1")
        self.assertTrue(any("まだありません" in m and "/obj/geo1" in m for m in messages), messages)


if __name__ == "__main__":
    unittest.main()
