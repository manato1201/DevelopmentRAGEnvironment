"""ビューポート画像の修正（2026-11-18）のテスト。

・display_isolation: /obj 直下の、ほかのオブジェクトの表示を切る・戻す（偽の hou）。
・screen_capture: 縦長のビューポートを 16:9 に切り出す矩形・境界ボックスを広げる倍率（純粋な関数）、切り出し（Qt がある環境だけ）。
・houdini_tools: create_node / set_parameter の結果をビューポートに映す（入力が要るのに、つながっていないノードは映さない）。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_viewport_isolation.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))
sys.modules.setdefault("hou", types.ModuleType("hou"))

import display_isolation as di  # noqa: E402
import screen_capture as sc  # noqa: E402

try:
    from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
except ImportError:
    QImage = None


class FakeObj:
    def __init__(self, path: str, displayed: bool = True, has_flag: bool = True) -> None:
        self._path, self.displayed, self._has_flag = path, displayed, has_flag
        if has_flag:
            self.isDisplayFlagSet = lambda: self.displayed
            self.setDisplayFlag = self._set

    def _set(self, on: bool) -> None:
        self.displayed = bool(on)

    def path(self) -> str:
        return self._path


class FakeHou:
    def __init__(self, nodes: list[FakeObj]) -> None:
        self.nodes = {n.path(): n for n in nodes}
        root = types.SimpleNamespace(children=lambda: list(self.nodes.values()))
        self._root = root

    def node(self, path: str):
        return self._root if path == "/obj" else self.nodes.get(path)


class DisplayIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        di.reset()
        self.addCleanup(di.reset)
        self.sandbox = FakeObj("/obj/ai_tutorial_1")
        self.mine = FakeObj("/obj/tornado")
        self.hidden = FakeObj("/obj/old", displayed=False)
        self.lop = FakeObj("/obj/stage", has_flag=False)
        self.hou = FakeHou([self.sandbox, self.mine, self.hidden, self.lop])

    def test_top_object_path(self) -> None:
        self.assertEqual(di.top_object_path("/obj/a/b/c"), "/obj/a")
        self.assertEqual(di.top_object_path("/obj/a"), "/obj/a")
        self.assertEqual(di.top_object_path("/obj"), "")
        self.assertEqual(di.top_object_path("/out/x"), "")
        self.assertEqual(di.top_object_path(""), "")

    def test_other_displayed_objects_are_turned_off_and_the_kept_one_stays(self) -> None:
        off = di.isolate(self.hou, ["/obj/ai_tutorial_1/energy/core"])
        self.assertEqual(off, ["/obj/tornado"])
        self.assertTrue(self.sandbox.displayed)
        self.assertFalse(self.mine.displayed)
        self.assertFalse(self.hidden.displayed)  # もともと切れているものは、触らない

    def test_nodes_without_a_display_flag_are_left_alone(self) -> None:
        di.isolate(self.hou, ["/obj/ai_tutorial_1"])
        self.assertEqual(di.pending(), 1)  # tornado だけ

    def test_restore_returns_only_what_was_turned_off(self) -> None:
        di.isolate(self.hou, ["/obj/ai_tutorial_1"])
        self.assertEqual(di.restore(self.hou), ["/obj/tornado"])
        self.assertTrue(self.mine.displayed)
        self.assertFalse(self.hidden.displayed)  # もともと切れていたものは、戻さない
        self.assertEqual(di.pending(), 0)

    def test_isolating_twice_keeps_the_first_state(self) -> None:
        di.isolate(self.hou, ["/obj/ai_tutorial_1"])
        di.isolate(self.hou, ["/obj/tornado"])  # 2 回目: 切れた tornado は戻らず、サンドボックスが切れる
        self.assertFalse(self.sandbox.displayed)
        self.assertEqual(sorted(di._saved), ["/obj/ai_tutorial_1", "/obj/tornado"])
        di.restore(self.hou)
        self.assertTrue(self.sandbox.displayed and self.mine.displayed)

    def test_show_turns_the_wanted_object_on(self) -> None:
        self.hidden.displayed = False
        self.assertTrue(di.show(self.hou, "/obj/old/geo/x"))
        self.assertTrue(self.hidden.displayed)
        self.assertFalse(di.show(self.hou, "/obj/stage"))  # フラグが無い
        self.assertFalse(di.show(self.hou, "/obj/missing"))

    def test_a_broken_hou_does_nothing(self) -> None:
        self.assertEqual(di.isolate(types.SimpleNamespace(node=lambda p: (_ for _ in ()).throw(RuntimeError("x"))), ["/obj/a"]), [])
        self.assertEqual(di.restore(self.hou), [])

    def test_restore_skips_deleted_nodes(self) -> None:
        di.isolate(self.hou, ["/obj/ai_tutorial_1"])
        del self.hou.nodes["/obj/tornado"]
        self.assertEqual(di.restore(self.hou), [])
        self.assertEqual(di.pending(), 0)


class CropRectTest(unittest.TestCase):
    def test_portrait_is_cropped_top_and_bottom_around_the_center(self) -> None:
        x, y, w, h = sc.crop_rect_for_aspect(1920, 2132)
        self.assertEqual((x, w), (0, 1920))
        self.assertEqual(h, 1080)
        self.assertEqual(y, (2132 - 1080) // 2)

    def test_wide_is_cropped_left_and_right(self) -> None:
        x, y, w, h = sc.crop_rect_for_aspect(3000, 1000)
        self.assertEqual((y, h), (0, 1000))
        self.assertEqual(w, 1778)
        self.assertEqual(x, (3000 - 1778) // 2)

    def test_16_9_is_unchanged(self) -> None:
        self.assertEqual(sc.crop_rect_for_aspect(1920, 1080), (0, 0, 1920, 1080))
        self.assertEqual(sc.crop_rect_for_aspect(1280, 720), (0, 0, 1280, 720))

    def test_bad_sizes_are_returned_whole(self) -> None:
        self.assertEqual(sc.crop_rect_for_aspect(0, 100), (0, 0, 0, 100))
        self.assertEqual(sc.crop_rect_for_aspect(100, 0), (0, 0, 100, 0))

    def test_crop_is_always_inside_the_image(self) -> None:
        for w, h in ((1920, 2132), (800, 3000), (3000, 800), (1000, 1000), (2000, 1100)):
            x, y, cw, ch = sc.crop_rect_for_aspect(w, h)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + cw, w)
            self.assertLessEqual(y + ch, h)


class FrameScaleTest(unittest.TestCase):
    def test_landscape_and_16_9_are_not_enlarged(self) -> None:
        self.assertEqual(sc.frame_scale(16 / 9), 1.0)
        self.assertEqual(sc.frame_scale(2.4), 1.0)

    def test_portrait_is_enlarged_so_the_subject_survives_the_crop(self) -> None:
        aspect = 1920 / 2132
        scale = sc.frame_scale(aspect)
        self.assertAlmostEqual(scale, (16 / 9) / aspect, places=3)
        self.assertGreater(scale, 1.9)

    def test_scale_is_capped(self) -> None:
        self.assertEqual(sc.frame_scale(0.2), sc._MAX_FRAME_SCALE)

    def test_unreadable_aspect_is_not_enlarged(self) -> None:
        self.assertEqual(sc.frame_scale(0), 1.0)
        self.assertEqual(sc.frame_scale(-1), 1.0)


@unittest.skipIf(QImage is None, "PySide6 がありません")
class CropToAspectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def _make(self, path: Path, w: int, h: int) -> None:
        image = QImage(w, h, QImage.Format_RGB32)
        image.fill(QColor(58, 58, 62))
        for y in range(h):  # 縦位置が分かるよう、行ごとに色を変える
            image.setPixelColor(0, y, QColor(y % 256, 0, 0))
        self.assertTrue(image.save(str(path), "PNG"))

    def test_portrait_image_becomes_16_9_and_keeps_the_center_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.png"
            self._make(path, 1920, 2132)
            self.assertTrue(sc.crop_to_aspect(path))
            image = QImage(str(path))
            self.assertEqual((image.width(), image.height()), (1920, 1080))
            top = (2132 - 1080) // 2
            self.assertEqual(image.pixelColor(0, 0).red(), top % 256)  # 中央の行から始まる

    def test_16_9_image_is_left_as_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.png"
            self._make(path, 1920, 1080)
            before = path.read_bytes()
            self.assertTrue(sc.crop_to_aspect(path))
            self.assertEqual(path.read_bytes(), before)

    def test_missing_file_returns_false(self) -> None:
        self.assertFalse(sc.crop_to_aspect(Path("no-such-file.png")))


class StepResultDisplayTest(unittest.TestCase):
    """create_node / set_parameter の結果を映す（houdini_tools._show_step_result）。"""

    def setUp(self) -> None:
        import houdini_tools as ht

        self.ht = ht
        self.shown: list[str] = []
        outer = self

        class Node:
            def __init__(self, path, category="Sop", min_inputs=0, inputs=()):
                self._path, self._cat, self._min, self._inputs = path, category, min_inputs, inputs
                self.type = lambda: types.SimpleNamespace(
                    category=lambda: types.SimpleNamespace(name=lambda: self._cat), minNumInputs=lambda: self._min)
                self.inputs = lambda: self._inputs
                self.setDisplayFlag = lambda on: outer.shown.append(path) if on else None
                self.setRenderFlag = lambda on: None

        self.Node = Node
        self.tools = ht.HoudiniToolExecutor.__new__(ht.HoudiniToolExecutor)

    def test_generator_node_is_shown(self) -> None:
        self.tools._show_step_result(self.Node("/obj/s/geo/sphere1", min_inputs=0))
        self.assertEqual(self.shown, ["/obj/s/geo/sphere1"])

    def test_node_with_a_connected_input_is_shown(self) -> None:
        self.tools._show_step_result(self.Node("/obj/s/geo/scatter1", min_inputs=1, inputs=(object(),)))
        self.assertEqual(self.shown, ["/obj/s/geo/scatter1"])

    def test_unconnected_node_that_needs_input_is_not_shown(self) -> None:
        self.tools._show_step_result(self.Node("/obj/s/geo/scatter1", min_inputs=1, inputs=(None,)))
        self.assertEqual(self.shown, [])

    def test_non_sop_is_not_touched(self) -> None:
        self.tools._show_step_result(self.Node("/obj/s/geo/dopnet1/x", category="Dop"))
        self.assertEqual(self.shown, [])

    def test_broken_node_does_not_raise(self) -> None:
        self.tools._show_step_result(object())


if __name__ == "__main__":
    unittest.main()
