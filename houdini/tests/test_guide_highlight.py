"""Guide の、パラメータ画面を項目の位置に合わせる・ほかのオブジェクトの表示を切る・戻す（2026-11-18）のテスト。

Houdini には、パラメータを光らせる API が無い。代わりに、項目のタブを前面にし（reveal）、ParameterEditor.scrollTo で中央に寄せ、
moveFocusTo で焦点を当てる。偽の hou で、その呼び出しを確かめる（実機では、まだ確かめていない）。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_guide_highlight.py -v
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))

import display_isolation as di  # noqa: E402
import guide_mode as gm  # noqa: E402


class FakeParmPane:
    def __init__(self, fail_scroll: bool = False, fail_focus: bool = False) -> None:
        self.scrolled: list = []
        self.focused: list = []
        self._fail_scroll, self._fail_focus = fail_scroll, fail_focus

    def isCurrentTab(self):
        return True

    def scrollTo(self, parms, position=None):
        if self._fail_scroll:
            raise RuntimeError("scrollTo failed")
        self.scrolled.append((list(parms), position))

    def moveFocusTo(self, parm):
        if self._fail_focus:
            raise RuntimeError("moveFocusTo failed")
        self.focused.append(parm)


class FakeNode:
    def __init__(self, parms: dict[str, object]) -> None:
        self._parms = parms

    def parm(self, name):
        return self._parms.get(name)

    def parmTuple(self, name):
        return None


def make_hou(pane) -> types.SimpleNamespace:
    pane_type = object()
    return types.SimpleNamespace(
        paneTabType=types.SimpleNamespace(Parm=pane_type),
        scrollPosition=types.SimpleNamespace(Center="CENTER"),
        ui=types.SimpleNamespace(paneTabOfType=lambda t, i=0: pane if (t is pane_type and not i) else None),
    )


STEP = {"tool": "set_parameter", "node": "pyro", "parms": [{"name": "sourcevolume1", "label": "Source Volume"}, {"name": "x"}, {"label": "no-name"}]}


class HighlightParmsTest(unittest.TestCase):
    def test_scrolls_to_the_parms_at_the_center_and_focuses_the_first(self) -> None:
        pane = FakeParmPane()
        node = FakeNode({"sourcevolume1": "P1", "x": "P2"})
        revealed: list = []
        messages = gm.highlight_parms(make_hou(pane), STEP, node, lambda n, names: revealed.append(list(names)))
        self.assertEqual(revealed, [["sourcevolume1", "x"]])
        self.assertEqual(pane.scrolled, [(["P1", "P2"], "CENTER")])
        self.assertEqual(pane.focused, ["P1"])
        self.assertTrue(messages)
        self.assertIn("sourcevolume1", messages[0])

    def test_missing_parms_are_skipped(self) -> None:
        pane = FakeParmPane()
        messages = gm.highlight_parms(make_hou(pane), STEP, FakeNode({"x": "P2"}))
        self.assertEqual(pane.scrolled, [(["P2"], "CENTER")])
        self.assertTrue(messages)

    def test_nothing_to_do_without_names_node_or_pane(self) -> None:
        pane = FakeParmPane()
        self.assertEqual(gm.highlight_parms(make_hou(pane), {"tool": "set_parameter", "parms": []}, FakeNode({})), [])
        self.assertEqual(gm.highlight_parms(make_hou(pane), STEP, None), [])
        self.assertEqual(gm.highlight_parms(make_hou(None), STEP, FakeNode({"x": "P2"})), [])
        self.assertEqual(gm.highlight_parms(make_hou(pane), STEP, FakeNode({})), [])  # どの項目も、ノードに無い
        self.assertEqual(pane.scrolled, [])

    def test_a_failing_scroll_still_tries_the_focus_and_never_raises(self) -> None:
        pane = FakeParmPane(fail_scroll=True)
        messages = gm.highlight_parms(make_hou(pane), STEP, FakeNode({"x": "P2"}))
        self.assertEqual(pane.focused, ["P2"])
        self.assertTrue(messages)

    def test_both_failing_gives_no_message_and_does_not_raise(self) -> None:
        pane = FakeParmPane(fail_scroll=True, fail_focus=True)
        self.assertEqual(gm.highlight_parms(make_hou(pane), STEP, FakeNode({"x": "P2"})), [])

    def test_a_failing_reveal_does_not_stop_the_scroll(self) -> None:
        pane = FakeParmPane()

        def boom(node, names):
            raise RuntimeError("reveal failed")

        messages = gm.highlight_parms(make_hou(pane), STEP, FakeNode({"x": "P2"}), boom)
        self.assertTrue(messages)
        self.assertEqual(len(pane.scrolled), 1)

    def test_an_older_houdini_without_the_scroll_enum_still_scrolls(self) -> None:
        pane = FakeParmPane()
        hou = make_hou(pane)
        hou.scrollPosition = None
        gm.highlight_parms(hou, STEP, FakeNode({"x": "P2"}))
        self.assertEqual(pane.scrolled, [(["P2"], None)])


class Obj:
    def __init__(self, path: str, displayed: bool = True) -> None:
        self._path, self.displayed = path, displayed
        self.isDisplayFlagSet = lambda: self.displayed
        self.setDisplayFlag = lambda on: setattr(self, "displayed", bool(on))

    def path(self) -> str:
        return self._path


class IsolateDisplayTest(unittest.TestCase):
    def setUp(self) -> None:
        di.reset()
        self.addCleanup(di.reset)
        self.mine, self.other, self.sandbox = Obj("/obj/tornado"), Obj("/obj/geo1"), Obj("/obj/ai_tutorial_1", displayed=False)
        nodes = {o.path(): o for o in (self.mine, self.other, self.sandbox)}
        self.hou = types.SimpleNamespace(node=lambda p: types.SimpleNamespace(children=lambda: list(nodes.values())) if p == "/obj" else nodes.get(p))

    def test_other_objects_are_turned_off_and_the_target_object_stays_on(self) -> None:
        note = gm.isolate_display(self.hou, ["/obj/tornado/vortex"])
        self.assertTrue(self.mine.displayed)
        self.assertFalse(self.other.displayed)
        self.assertIn("1個", note)
        self.assertIn("geo1", note)

    def test_the_target_object_is_turned_on_if_it_was_off(self) -> None:
        gm.isolate_display(self.hou, ["/obj/ai_tutorial_1/energy/core"])
        self.assertTrue(self.sandbox.displayed)
        self.assertFalse(self.mine.displayed)
        self.assertFalse(self.other.displayed)

    def test_no_note_when_nothing_was_turned_off(self) -> None:
        gm.isolate_display(self.hou, ["/obj/tornado/a"])
        self.assertEqual(gm.isolate_display(self.hou, ["/obj/tornado/b"]), "")

    def test_paths_outside_obj_do_nothing(self) -> None:
        self.assertEqual(gm.isolate_display(self.hou, ["/out/x", ""]), "")
        self.assertTrue(self.other.displayed)

    def test_restore_puts_back_what_was_turned_off(self) -> None:
        gm.isolate_display(self.hou, ["/obj/tornado/a"])
        self.assertEqual(di.pending(), 1)
        self.assertIn("1個", gm.restore_display(self.hou))
        self.assertTrue(self.other.displayed)
        self.assertEqual(gm.restore_display(self.hou), "戻すものはありません")

    def test_apply_step_isolates_when_the_node_is_found(self) -> None:
        import guide_fakes

        world = guide_fakes.make_world(
            {"/obj/tornado": "geo", "/obj/tornado/vortex": "attribwrangle", "/obj/other": "geo"}, pwd="/obj/tornado")
        for path in ("/obj/tornado", "/obj/other"):  # 偽のノードに、表示フラグを足す
            node = world.hou.node(path)
            node.displayed = True
            node.isDisplayFlagSet = lambda n=node: n.displayed
            node.setDisplayFlag = lambda on, n=node: setattr(n, "displayed", bool(on))
        step = {"tool": "set_parameter", "node": "vortex", "node_path": "/obj/tornado/vortex", "parms": []}
        messages = gm.apply_step(world.hou, step, "", "own")
        self.assertFalse(world.hou.node("/obj/other").displayed)
        self.assertTrue(world.hou.node("/obj/tornado").displayed)
        self.assertTrue(any("表示を切りました" in m for m in messages), messages)


if __name__ == "__main__":
    unittest.main()
