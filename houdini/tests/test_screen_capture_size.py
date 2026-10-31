"""screen_capture.py の画像サイズ（2026-10-31: 文字がつぶれないよう解像度を上げた）のテスト。

・fit_pane_size は純粋な関数（Qt も hou も不要）。
・描き直す図・カードが RENDER_SCALE 倍の画素で出ることは、PySide6 がある環境でだけ確かめる（無ければ飛ばす）。
  hou は偽物で差し替える（描画の関数は hou を読まない）。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
Qt の描画も確かめるとき:     uv run --with PySide6 python -m unittest houdini/tests/test_screen_capture_size.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))
sys.modules.setdefault("hou", types.ModuleType("hou"))  # screen_capture は import hou する。純粋な部分だけ使うので偽物でよい

import screen_capture as sc  # noqa: E402

try:
    from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
except ImportError:  # Qt が無い環境では、描画のテストを飛ばす
    QImage = None

GRAPH = {
    "sandbox": "/obj/ai_tutorial_1",
    "nodes": [
        {"id": "geo1", "kind": "geo", "label": "geo1", "position": [0, 0]},
        {"id": "geo1/box1", "kind": "box", "label": "box1", "position": [0, 0], "parent": "geo1"},
        {"id": "geo1/xform1", "kind": "xform", "label": "xform1", "position": [0, -2], "parent": "geo1"},
    ],
    "edges": [{"source": "geo1/box1", "target": "geo1/xform1", "targetInput": 0}],
}


class FitPaneSizeTest(unittest.TestCase):
    def test_native_size_is_kept_when_in_range(self) -> None:
        self.assertEqual(sc.fit_pane_size(1920, 1080), (1920, 1080))
        self.assertEqual(sc.fit_pane_size(1280, 400), (1280, 400))
        self.assertEqual(sc.fit_pane_size(3840, 2000), (3840, 2000))

    def test_high_resolution_pane_is_not_shrunk_to_1280(self) -> None:
        """以前は 1280x720 に縮めていた。2560 幅の画面は、そのまま残す。"""
        self.assertEqual(sc.fit_pane_size(2560, 1440), (2560, 1440))

    def test_narrow_pane_is_enlarged_to_the_minimum_width(self) -> None:
        self.assertEqual(sc.fit_pane_size(640, 360), (1280, 720))
        self.assertEqual(sc.fit_pane_size(613, 332), (1280, 693))

    def test_huge_pane_is_capped(self) -> None:
        self.assertEqual(sc.fit_pane_size(7680, 4320), (3840, 2160))

    def test_degenerate_sizes_are_returned_unchanged(self) -> None:
        self.assertEqual(sc.fit_pane_size(0, 100), (0, 100))
        self.assertEqual(sc.fit_pane_size(100, 0), (100, 0))

    def test_defaults(self) -> None:
        self.assertEqual((sc.VIEWPORT_WIDTH, sc.VIEWPORT_HEIGHT), (1920, 1080))
        self.assertEqual((sc.CLIP_WIDTH, sc.CLIP_HEIGHT), (960, 540))
        self.assertGreaterEqual(sc.RENDER_SCALE, 2)


@unittest.skipIf(QImage is None, "PySide6 がありません")
class RenderedImageSizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def _size(self, path: Path) -> tuple[int, int]:
        image = QImage(str(path))
        self.assertFalse(image.isNull(), f"{path} が読めません")
        return image.width(), image.height()

    def test_graph_diagram_is_rendered_at_double_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "g.png"
            self.assertTrue(sc.render_graph_diagram(GRAPH, out))
            self.assertEqual(self._size(out), (1280 * sc.RENDER_SCALE, 720 * sc.RENDER_SCALE))

    def test_parameter_card_is_rendered_at_double_resolution(self) -> None:
        changes = [{"label": "Size X", "name": "sizex", "old": "1", "new": "0.15", "code": False}]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "card.png"
            self.assertTrue(sc.render_parameter_card(out, "/obj/geo1", "box1", "Box", changes))
            self.assertEqual(self._size(out), (1280 * sc.RENDER_SCALE, 720 * sc.RENDER_SCALE))

    def test_composed_parameter_screen_is_rendered_at_double_resolution(self) -> None:
        pane = QImage(2400, 1500, QImage.Format_ARGB32)  # 高解像度のパラメータ画面（切り出し結果）の代わり
        pane.fill(QColor("#444444"))
        changes = [{"label": "Size X", "name": "sizex", "old": "1", "new": "0.15", "code": False}]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "pane.png"
            self.assertTrue(sc._compose_parameter_screen(out, pane, "/obj/geo1", "box1", changes, 1280, 720, None))
            self.assertEqual(self._size(out), (1280 * sc.RENDER_SCALE, 720 * sc.RENDER_SCALE))


if __name__ == "__main__":
    unittest.main()
