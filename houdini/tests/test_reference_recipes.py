"""撮影レシピ（scripts/reference_capture/recipes.py）の形と、ノード図の描画のテスト（2026-11-20）。Houdini は使わない（hython で撮るのは、実機の確認）。

実行（リポジトリのルートで）:  uv run --with PySide6 --with pillow python -m unittest houdini/tests/test_reference_recipes.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts" / "reference_capture"))
sys.modules.setdefault("hou", types.ModuleType("hou"))

from recipes import RECIPES  # noqa: E402


class RecipeShapeTest(unittest.TestCase):
    def test_keys_are_unique_and_well_formed(self) -> None:
        keys = [r["key"] for r in RECIPES]
        self.assertEqual(len(keys), len(set(keys)))
        for recipe in RECIPES:
            self.assertRegex(recipe["key"], r"^[a-z0-9]+/[a-z0-9_]+$")
            self.assertEqual(recipe["kind"], "node")
            self.assertTrue(recipe["type"][0].split("::")[0] == recipe["key"].split("/")[1] or recipe["key"] == "sop/xform", recipe["key"])

    def test_every_recipe_has_a_source_and_valid_parts(self) -> None:
        for recipe in RECIPES:
            self.assertIsInstance(recipe["type"], list, recipe["key"])
            specs = recipe.get("inputs") or [recipe["input"]]
            self.assertTrue(specs, recipe["key"])
            for spec in specs:
                self.assertIn("type", spec)
                for step in spec.get("after") or []:
                    self.assertIn("type", step)
            self.assertIsInstance(recipe["parms"], dict)
            sweep = recipe.get("sweep")
            if sweep:
                self.assertTrue({"parm", "from", "to"} <= set(sweep), recipe["key"])
                self.assertNotEqual(sweep["from"], sweep["to"], f"{recipe['key']}: a sweep that does not move shows nothing")

    def test_a_sweep_on_an_input_names_a_node_that_the_chain_builds(self) -> None:
        """"node": "in1" は 2 番目の入力の元のノード、"in1_0" はそのあとの 1 つ目（hython_shot.build_chain の名前）。"""
        import re

        for recipe in RECIPES:
            name = (recipe.get("sweep") or {}).get("node")
            if not name:
                continue
            match = re.fullmatch(r"in(\d+)(?:_(\d+))?", name)
            self.assertTrue(match, f"{recipe['key']}: {name}")
            inputs = recipe.get("inputs") or [recipe["input"]]
            spec = inputs[int(match.group(1))]
            if match.group(2) is not None:
                self.assertLess(int(match.group(2)), len(spec.get("after") or []), f"{recipe['key']}: {name} is not in the chain")

    def test_keep_names_only_values_the_recipe_sets(self) -> None:
        for recipe in RECIPES:
            for name in recipe.get("keep") or []:
                self.assertIn(name, recipe.get("parms") or {}, f"{recipe['key']}: keep {name} is not a value of the recipe")

    def test_at_least_a_dozen_recipes_cover_the_common_nodes(self) -> None:
        self.assertGreaterEqual(len(RECIPES), 15)


class NodeImageTest(unittest.TestCase):
    def test_the_node_figure_draws_chains_and_several_inputs(self) -> None:
        try:
            import capture
        except ImportError as exc:  # pillow が無い環境
            self.skipTest(str(exc))
        recipe = next(r for r in RECIPES if r["key"] == "sop/copytopoints")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "node.png"
            self.assertTrue(capture.render_node_image(recipe, path))
            self.assertGreater(path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
