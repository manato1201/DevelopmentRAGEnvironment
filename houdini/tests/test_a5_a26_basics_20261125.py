"""修正リストの A5（進行ログは設定者だけ）・A26（階層ミスと注意を目立たせる）・A28（基本操作の練習）のテスト（2026-11-25）。"""
from __future__ import annotations

import os
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
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import basics_guide as bg  # noqa: E402
import guide_mode as gm  # noqa: E402
import guide_shortcuts as gs  # noqa: E402
from guide_fakes import make_world  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None


class FriendlyProgressTest(unittest.TestCase):
    def test_tool_lines_become_plain_words_and_long_lines_are_cut(self) -> None:
        import tutorial_view as tv

        self.assertEqual(tv.friendly_progress('[12/80] create_node({"node_type": "box"})'), "進んでいます: 12 / 80 回目（ノードを作る）")
        self.assertEqual(tv.friendly_progress("[81/80+予備] finish_tutorial({...})"), "進んでいます: 81 / 80 回目（仕上げの予備）（手順書を書く）")
        self.assertEqual(tv.friendly_progress("[3/80] mystery_tool({})"), "進んでいます: 3 / 80 回目（作業する）")
        self.assertEqual(tv.friendly_progress("レッスン設計: 5章"), "レッスン設計: 5章")
        self.assertTrue(tv.friendly_progress("あ" * 100).endswith("…"))
        self.assertEqual(tv.friendly_progress("  "), "")


class LocationSeverityTest(unittest.TestCase):
    def test_depth_differences_are_real_mistakes_and_names_are_not(self) -> None:
        self.assertEqual(gm.location_severity("/obj/geo1", "/obj/geo1"), "same")
        self.assertEqual(gm.location_severity("/obj/geo1", ""), "same")
        self.assertEqual(gm.location_severity("", "/obj/geo1"), "unknown")
        self.assertEqual(gm.location_severity("/obj/pyro_geo", "/obj/geo1"), "name")
        self.assertEqual(gm.location_severity("/obj", "/obj/geo1"), "level")
        self.assertEqual(gm.location_severity("/obj/geo1/dopnet1", "/obj/geo1"), "level")
        self.assertIn("Enter", gm.level_hint("/obj", "/obj/geo1"))
        self.assertIn("U を押す", gm.level_hint("/obj/geo1/dopnet1", "/obj/geo1"))


class BasicsGuideTest(unittest.TestCase):
    def test_every_step_is_complete_and_uses_only_checked_keys(self) -> None:
        guide = bg.build()
        steps = guide["steps"]
        self.assertGreaterEqual(len(steps), 10)
        known = {(r["keys"], r["what"]) for r in gs.SHORTCUTS}
        for step in steps:
            self.assertIn(step["tab"], gm.TAB_LABELS, step["step"])
            self.assertTrue(step["instruction"] and step["work"] and step["hint"], step["step"])
            self.assertTrue(step["shortcuts"], step["step"])
            for key in step["shortcuts"]:
                self.assertIn((key["keys"], key["what"]), known, "only keys from the checked table")
        tools = [s["tool"] for s in steps]
        for tool in ("create_node", "connect_nodes", "set_parameter", "cook_node"):
            self.assertIn(tool, tools, "the practice covers the four basic operations of the Guide")
        made = {s["node"]: s["node_type"] for s in steps if s["tool"] == "create_node"}
        self.assertEqual(made, {"practice_geo": "geo", "box1": "box", "transform1": "xform"})

    def test_it_renders_and_finds_the_learners_own_nodes(self) -> None:
        import guide_view as gv

        guide = bg.build()
        for index in range(len(guide["steps"])):
            self.assertTrue(gv.render_step_html(guide, index))
        world = make_world({"/obj/practice_geo/box1": "box", "/obj/practice_geo/transform1": "xform"}, pwd="/obj")
        hit = gm.resolve_step_target(world.hou, guide["steps"][8])  # Translate Y を変える手順
        self.assertEqual(hit.node.path(), "/obj/practice_geo/transform1")


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class WidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _guide_widget(self, hou_value=None):
        import guide_view as gv

        state: dict = {}
        for patch in (mock.patch.object(gv, "_state_get", lambda key, default=None: state.get(key, default)),
                      mock.patch.object(gv, "_state_set", lambda key, value: state.__setitem__(key, value)),
                      mock.patch.object(gv, "hou", hou_value)):
            patch.start()
            self.addCleanup(patch.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        widget = gv.GuideWidget(lambda: {})
        self.addCleanup(widget.deleteLater)
        widget._tutorials_dir = lambda: Path(tmp.name)
        return gv, widget

    def test_a_first_time_user_gets_the_basics_practice(self) -> None:
        _gv, widget = self._guide_widget()
        widget.refresh()
        self.assertEqual(widget._combo.count(), 1)
        self.assertEqual(widget._combo.currentText(), bg.LABEL)
        self.assertEqual(widget._guide["builtin"], bg.KEY)
        self.assertIn("基本操作の練習から", widget._status.text())
        self.assertTrue(widget._next_btn.isEnabled())

    def test_warnings_go_to_the_strong_box(self) -> None:
        _gv, widget = self._guide_widget()
        widget._set_status(["注意: /obj/sim の「soppath」が、お手本を指しています", "示したノード: /obj/a"])
        self.assertFalse(widget._warn.isHidden())
        self.assertIn("⚠ 注意: /obj/sim", widget._warn.text())
        self.assertNotIn("注意", widget._status.text())
        widget._set_status(["示したノード: /obj/a"])
        self.assertTrue(widget._warn.isHidden())

    def test_a_wrong_level_gets_the_red_band_and_the_fix(self) -> None:
        world = make_world({"/obj/geo1/box1": "box"}, pwd="/obj")
        _gv, widget = self._guide_widget(world.hou)
        widget._guide = {"steps": [{"tool": "create_node", "node": "box1", "node_path": "geo1/box1", "node_type": "box", "tab": "network"}]}
        widget._index = 0
        widget._update_where()
        self.assertIn("⚠ 階層が違います", widget._where.text())
        self.assertIn("Enter", widget._where.text())
        self.assertIn("#7c2d12", widget._where.styleSheet())
        world.editor.setPwd(world.nodes["/obj/geo1"])
        widget._update_where()
        self.assertNotIn("⚠", widget._where.text())
        self.assertNotIn("#7c2d12", widget._where.styleSheet())

    def test_the_raw_progress_log_is_for_setup_users_only(self) -> None:
        import tutorial_view as tv

        panel = tv.TutorialGeneratePanel(lambda: {"mode": "cloudflare", "local_bridge_dir": ""})
        self.addCleanup(panel.deleteLater)
        panel.set_developer_view(False)
        self.assertTrue(panel._log_box.isHidden())
        panel._on_progress('[5/80] connect_nodes({"from": "a"})')
        self.assertIn("ノードをつなぐ", panel._progress_line.text())
        self.assertFalse(panel._progress_line.isHidden())
        self.assertIn("connect_nodes", panel._progress_log.toPlainText(), "the log is still kept for the debug view")
        panel.set_developer_view(True)
        self.assertFalse(panel._log_box.isHidden())


if __name__ == "__main__":
    unittest.main()
