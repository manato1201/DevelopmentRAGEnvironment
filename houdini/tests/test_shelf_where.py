"""shelf_where.py（シェルフツールの「操作する場所」の図）と、撮影の動き（GIF）まわりのテスト（2026-11-24）。

実行（リポジトリのルートで）:  uv run --with pillow --with PySide6 python -m unittest houdini/tests/test_shelf_where.py -v
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "reference_capture"))
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
if "hou" not in sys.modules:
    sys.modules["hou"] = types.ModuleType("hou")  # capture.py は、空の hou を差し込む（screen_capture の読み込みのため）

try:
    import shelf_where as sw
    from PIL import Image
except ImportError:  # PySide6・Pillow が無い環境では、飛ばす
    sw = None

from recipe_common import CREATE_SWEEPS, create_sweep  # noqa: E402
from recipes import RECIPES  # noqa: E402

INFO = {
    "label": "Vellum Cloth", "icon": "SHELF_vellum_cloth", "shelf": {"name": "vellum", "label": "Vellum"},
    "set": {"name": "shelf_set_2", "label": "Lights, Camera, Action"},
    "tabs": [{"name": "collisions", "label": "Collisions"}, {"name": "vellum", "label": "Vellum"}, {"name": "mpm", "label": "MPM"}],
    "tools": [{"name": "a", "label": "Surface Collider", "icon": "SHELF_x"}, {"name": "b", "label": "Vellum Cloth", "icon": "SHELF_vellum_cloth"}],
}


class PureTest(unittest.TestCase):
    @unittest.skipIf(sw is None, "PySide6 / Pillow が無い")
    def test_icon_names_become_zip_members(self) -> None:
        self.assertEqual(sw.icon_member("SOP_mountain"), "SOP/mountain.svg")
        self.assertEqual(sw.icon_member("SHELF_smoke_heavy"), "SHELF/smoke_heavy.svg")
        self.assertEqual(sw.icon_member(""), "")
        self.assertEqual(sw.icon_member("nounderscore"), "")

    @unittest.skipIf(sw is None, "PySide6 / Pillow が無い")
    def test_the_button_window_is_centered_on_the_tool_and_stays_inside(self) -> None:
        tools = [{"name": f"t{i}", "label": f"T{i}"} for i in range(30)]
        window, before, after = sw.window_of(tools, "t15", 10)
        self.assertEqual(len(window), 10)
        self.assertIn("t15", [t["name"] for t in window])
        self.assertTrue(before and after)
        first, before, after = sw.window_of(tools, "t0", 10)
        self.assertEqual(first[0]["name"], "t0")
        self.assertFalse(before)
        last, before, after = sw.window_of(tools, "t29", 10)
        self.assertEqual(last[-1]["name"], "t29")
        self.assertFalse(after)
        few, before, after = sw.window_of(tools[:4], "t2", 10)
        self.assertEqual(len(few), 4)
        self.assertEqual((before, after), (False, False))

    @unittest.skipIf(sw is None, "PySide6 / Pillow が無い")
    def test_the_location_image_is_drawn_even_without_the_icon_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "where.png"
            self.assertTrue(sw.render(INFO, path, zip_path=Path(tmp) / "missing.zip"))
            with Image.open(path) as image:
                self.assertEqual(image.width, sw.WIDTH)
                self.assertGreater(image.height, 200)

    def test_every_create_recipe_has_a_sweep_that_moves(self) -> None:
        creates = [r for r in RECIPES if r.get("create")]
        self.assertGreaterEqual(len(creates), 22)
        for r in creates:
            if r.get("graph"):  # つなぎ方を書くもの（LOP など）は、まわりを 1 周する動き
                continue
            sweep = r.get("sweep")
            self.assertTrue(sweep, f"{r['key']}: 置くだけで形ができるものにも、動き（GIF）を付ける")
            self.assertNotEqual(sweep["from"], sweep["to"], r["key"])
            if not r.get("cop"):  # COP は、recipes_cop.py に、それぞれの動かす値がある
                self.assertEqual(sweep, create_sweep(r["type"][0]), r["key"])
        self.assertIsNone(create_sweep("nosuchnode"))
        self.assertIn("box", CREATE_SWEEPS)

    @unittest.skipIf(sw is None, "PySide6 / Pillow が無い")
    def test_a_toggle_gif_alternates_before_and_after(self) -> None:
        import capture

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            Image.new("RGB", (960, 540), (40, 40, 50)).save(tmp_path / "before.png")
            Image.new("RGB", (960, 540), (200, 80, 80)).save(tmp_path / "after.png")
            self.assertTrue(capture.make_toggle_gif(tmp_path / "before.png", tmp_path / "after.png", tmp_path / "clip.gif"))
            with Image.open(tmp_path / "clip.gif") as gif:
                self.assertEqual(gif.n_frames, 2)
                self.assertEqual(gif.width, capture.GIF_WIDTH)
            capture.fill_toggle_gifs(tmp_path.parent, {"nothing/here"})  # 該当なし: 何も壊さない


if __name__ == "__main__":
    unittest.main()
