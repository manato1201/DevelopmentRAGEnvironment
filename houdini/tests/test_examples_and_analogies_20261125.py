"""修正リストの A25（手順ごとの、お手本の画面）と A27（Maya・Blender でいうと）のテスト（2026-11-25）。

  ・A25: 生成のときに撮った、手順ごとのビューポート・ネットワークの画像を、Guide の手順の下に出す。画像のパスは、案内のファイルに書かない
  ・A27: 手で書いた対応表（tool_analogies）を、Guide の「作る手順」と Reference の説明に出す。表の 44 件は、hython 22.0.506 で実在を確かめた
"""
from __future__ import annotations

import json
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

import guide_mode as gm  # noqa: E402
import tool_analogies as ta  # noqa: E402


class AnalogyTableTest(unittest.TestCase):
    def test_versions_namespaces_and_reference_keys_are_normalized(self) -> None:
        self.assertEqual(ta._base("scatter::2.0"), "scatter")
        self.assertEqual(ta._base("kinefx::jointdeform"), "jointdeform")
        self.assertEqual(ta._base("kinefx::skeletonblend::3.0"), "skeletonblend")
        self.assertEqual(ta._base("sop/kinefx--jointdeform"), "jointdeform")
        self.assertIn("Instance on Points", ta.for_node("copytopoints::2.0")["blender"])
        self.assertIn("Armature", ta.for_node("kinefx::jointdeform")["blender"])

    def test_unknown_nodes_and_other_kinds_give_nothing(self) -> None:
        self.assertIsNone(ta.for_node("nosuchnode"))
        self.assertIsNone(ta.for_node(""))
        self.assertIsNone(ta.for_item({"kind": "vex", "key": "vex/noise"}))
        self.assertIsNotNone(ta.for_item({"kind": "node", "key": "sop/scatter"}))
        self.assertIsNotNone(ta.for_item({"kind": "node", "key": "dop/staticobject"}))
        self.assertIsNone(ta.for_item({"kind": "node", "key": "cop/scatter"}), "the context must match")

    def test_every_entry_has_both_tools_and_the_html_escapes_and_says_it_is_only_close(self) -> None:
        for key, (maya, blender) in ta._TABLE.items():
            self.assertTrue(maya.strip() and blender.strip(), key)
        block = ta.html_block({"maya": "<b>x</b>", "blender": "y"})
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", block)
        self.assertIn("近いもの", block)
        self.assertIn("同じではありません", block)
        self.assertEqual(ta.html_block(None), "")

    def test_the_guide_shows_it_only_on_create_steps(self) -> None:
        import guide_view as gv

        create = {"guide": {"steps": [{"tool": "create_node", "node": "pts", "node_path": "g/pts", "node_type": "scatter::2.0", "tab_label": "ネットワーク"}]}}
        html_text = gv.render_step_html(create["guide"], 0)
        self.assertIn("ほかのツールでいうと", html_text)
        self.assertIn("Distribute Points on Faces", html_text)
        parm = {"steps": [{"tool": "set_parameter", "node": "pts", "node_path": "g/pts", "node_type": "scatter::2.0", "tab_label": "パラメータ"}]}
        self.assertNotIn("ほかのツールでいうと", gv.render_step_html(parm, 0))

    def test_the_reference_entry_shows_it(self) -> None:
        import reference_data as rd

        page = rd.entry_html({"kind": "node", "key": "sop/copytopoints", "label": "Copy to Points", "context": "sop"}, None)
        self.assertIn("ほかのツールでいうと", page)
        self.assertNotIn("ほかのツールでいうと", rd.entry_html({"kind": "vex", "key": "vex/noise", "label": "noise", "context": "vex"}, None))


class ExampleShotsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.view = self.dir / "step_002_viewport.png"
        self.view.write_bytes(b"png")
        self.record = [
            {"step": 1, "tool": "create_node", "result": "「Box」ノード（box）を作り、名前を b にする",
             "guide": {"node": "b", "node_path": "g/b", "node_type": "box", "node_label": "Box"}, "viewport": "", "network": ""},
            {"step": 2, "tool": "set_parameter", "result": "b のパラメータを設定",
             "guide": {"node": "b", "node_path": "g/b", "parms": [{"name": "sizex", "label": "Size", "old": "1", "new": "2"}]},
             "viewport": str(self.view), "network": str(self.dir / "missing.png")},
        ]

    def test_shots_are_keyed_by_step_and_only_existing_files_are_shown(self) -> None:
        self.assertEqual(gm.shots_by_step(self.record + ["x", {"step": "3"}]), {2: {"viewport": str(self.view), "network": str(self.dir / "missing.png")}})
        guide = gm.guide_from_result(types.SimpleNamespace(markdown="", sandbox_path="/obj/ai_tutorial_1", step_screenshots=self.record, title="t", level="basic"))
        steps = guide["steps"]
        self.assertEqual(gm.step_shots(guide, steps[0]), [])
        self.assertEqual(gm.step_shots(guide, steps[1]), [("結果（ビューポート）", str(self.view))], "a missing file is not shown")

    def test_paths_are_not_written_and_are_found_again_on_load(self) -> None:
        guide = gm.guide_from_result(types.SimpleNamespace(markdown="", sandbox_path="", step_screenshots=self.record, title="t", level=""))
        guide_path = self.dir / "box-lesson_20261125_guide.json"
        gm.write_guide(guide_path, guide)
        self.assertNotIn(gm.SHOTS_KEY, json.loads(guide_path.read_text(encoding="utf-8")))
        self.assertNotIn(str(self.view), guide_path.read_text(encoding="utf-8"))
        self.assertEqual(gm.screenshots_path_for(guide_path).name, "box-lesson_20261125_screenshots.json")
        gm.screenshots_path_for(guide_path).write_text(json.dumps(self.record), encoding="utf-8")
        loaded = gm.load_guide(guide_path)
        self.assertEqual(gm.step_shots(loaded, loaded["steps"][1]), [("結果（ビューポート）", str(self.view))])

    def test_an_old_guide_without_screenshots_still_loads(self) -> None:
        guide_path = self.dir / "old_guide.json"
        gm.write_guide(guide_path, gm.build_guide(self.record))
        loaded = gm.load_guide(guide_path)
        self.assertEqual(loaded[gm.SHOTS_KEY], {})


try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class ShotStripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_the_guide_shows_the_example_under_the_step_and_hides_it_when_there_is_none(self) -> None:
        import guide_view as gv
        from PySide6.QtGui import QColor, QImage

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        png = str(Path(tmp.name) / "v.png")
        image = QImage(640, 360, QImage.Format_RGB32)
        image.fill(QColor("#335577"))
        image.save(png)
        state: dict = {}
        for patch in (mock.patch.object(gv, "_state_get", lambda key, default=None: state.get(key, default)),
                      mock.patch.object(gv, "_state_set", lambda key, value: state.__setitem__(key, value)),
                      mock.patch.object(gv, "hou", None)):
            patch.start()
            self.addCleanup(patch.stop)
        widget = gv.GuideWidget(lambda: {})
        self.addCleanup(widget.deleteLater)
        widget._guide = {"title": "t", "steps": [{"step": 1, "tool": "cook_node", "node": "b", "tab_label": "ビューポート"},
                                                {"step": 2, "tool": "cook_node", "node": "b", "tab_label": "ビューポート"}],
                         gm.SHOTS_KEY: {1: {"viewport": png, "network": png}}}
        widget._index = 0
        widget._render()
        self.assertFalse(widget._shots_box.isHidden())
        pictures = widget._shots.findChildren(gv._ShotLabel)
        self.assertEqual(len(pictures), 2)
        self.assertLessEqual(pictures[0].pixmap().width(), gv.px(gv.ShotStrip.WIDTH))
        with mock.patch.object(gv.QDesktopServices, "openUrl") as opened:
            pictures[0].clicked.emit()
        self.assertTrue(opened.call_args.args[0].toLocalFile().endswith("v.png"))
        widget._index = 1
        widget._render()
        self.assertTrue(widget._shots_box.isHidden())


if __name__ == "__main__":
    unittest.main()
