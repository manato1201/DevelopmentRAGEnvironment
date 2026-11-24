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

from recipe_common import input_specs  # noqa: E402
from recipes import RECIPES  # noqa: E402


class RecipeShapeTest(unittest.TestCase):
    def test_keys_are_unique_and_well_formed(self) -> None:
        keys = [r["key"] for r in RECIPES]
        self.assertEqual(len(keys), len(set(keys)))
        for recipe in RECIPES:
            self.assertRegex(recipe["key"], r"^[a-z0-9]+/[a-z0-9_]+$")
            self.assertIn(recipe["kind"], ("node", "vex", "shelf"))
            if recipe["kind"] == "node":
                self.assertTrue(recipe["type"][0].split("::")[0] == recipe["key"].split("/")[1] or recipe["key"] == "sop/xform", recipe["key"])
            else:  # vex・shelf（2026-11-24）: キーの頭は種類名
                self.assertTrue(recipe["key"].startswith(recipe["kind"] + "/"), recipe["key"])

    def test_every_recipe_has_a_source_and_valid_parts(self) -> None:
        for recipe in RECIPES:
            self.assertIsInstance(recipe["type"], list, recipe["key"])
            specs = input_specs(recipe)  # create・graph は、入力の鎖を持たない
            self.assertTrue(specs or recipe.get("create") or recipe.get("graph"), recipe["key"])
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
            inputs = input_specs(recipe)
            spec = inputs[int(match.group(1))]
            if match.group(2) is not None:
                self.assertLess(int(match.group(2)), len(spec.get("after") or []), f"{recipe['key']}: {name} is not in the chain")

    def test_keep_names_only_values_the_recipe_sets(self) -> None:
        for recipe in RECIPES:
            for name in recipe.get("keep") or []:
                self.assertIn(name, recipe.get("parms") or {}, f"{recipe['key']}: keep {name} is not a value of the recipe")

    def test_vex_recipes_run_a_wrangler_and_say_what_to_look_at(self) -> None:
        """VEX のレシピ（2026-11-24）: attribwrangle の式を、説明の「例」にそのまま載せる。see は、絵の見どころ。"""
        vex = [r for r in RECIPES if r["kind"] == "vex"]
        self.assertGreaterEqual(len(vex), 70)
        for recipe in vex:
            self.assertEqual(recipe["type"], ["attribwrangle"], recipe["key"])
            self.assertTrue(str(recipe["parms"].get("snippet") or "").strip(), recipe["key"])
            self.assertTrue(str(recipe.get("see") or "").strip(), recipe["key"])
            name = recipe["key"].split("/")[1]
            self.assertIn(name, recipe["parms"]["snippet"], f"{recipe['key']}: the snippet must use the function it explains")

    def test_shelf_recipes_reuse_node_recipes_or_create_a_shape(self) -> None:
        node_keys = {r["key"] for r in RECIPES if r["kind"] == "node"}
        shelf = [r for r in RECIPES if r["kind"] == "shelf"]
        self.assertGreaterEqual(len(shelf), 30)
        from recipes_shelf import SHELF_FROM_NODE

        for node_key in SHELF_FROM_NODE.values():
            self.assertIn(node_key, node_keys)
        for recipe in shelf:
            if recipe.get("create"):
                self.assertNotIn("input", recipe, recipe["key"])
                self.assertNotIn("inputs", recipe, recipe["key"])
                self.assertTrue(recipe.get("sweep"), recipe["key"])  # 置くだけで形ができるものにも、動き（GIF）を付ける（2026-11-24。recipe_common.CREATE_SWEEPS）

    def test_simulation_recipes_set_the_frame_count_and_the_view(self) -> None:
        """sim = 進めるフレーム数、view = 構図の範囲（シミュレーションの箱は、煙より大きい）。sim のレシピだけが持つ。"""
        sims = [r for r in RECIPES if r.get("sim")]
        self.assertGreaterEqual(len(sims), 3)  # sop/pyrosolver と、シェルフの 2 件
        for r in sims:
            self.assertIsInstance(r["sim"], int, r["key"])
            self.assertGreater(r["sim"], 1, r["key"])
            view = r.get("view")
            self.assertTrue(view and all(a < b for a, b in zip(view["lo"], view["hi"])), r["key"])
            self.assertFalse(r.get("sweep"), r["key"])  # 動かす値と、シミュレーションは、一緒にしない
        for r in RECIPES:
            if not r.get("sim"):
                self.assertNotIn("view", r, r["key"])

    def test_graph_recipes_wire_earlier_nodes_and_name_the_shown_nodes(self) -> None:
        """graph = つなぎ方を書くレシピ。入力は、先に書いたノードだけ。node・before は、nodes の中の名前。lights を持つものは、lighting も持つ。"""
        graphs = [r for r in RECIPES if r.get("graph")]
        self.assertGreaterEqual(len(graphs), 6)  # Vellum 3・RBD 2・ライト 3 ほか
        for r in graphs:
            nodes = r["graph"]["nodes"]
            names = [n["name"] for n in nodes]
            self.assertEqual(len(names), len(set(names)), r["key"])
            self.assertIn(r["graph"]["node"], names, r["key"])
            self.assertIn(r["graph"].get("before", names[0]), names, r["key"])
            seen: set[str] = set()
            for n in nodes:
                for ref in n.get("inputs") or []:
                    if ref is not None:
                        self.assertIn(ref if isinstance(ref, str) else ref[0], seen, f"{r['key']}: {n['name']} の入力は、先に書く")
                seen.add(n["name"])
            self.assertNotIn("input", r, r["key"])
        for r in RECIPES:
            if r.get("lights"):
                self.assertTrue(r.get("lighting"), r["key"])
                self.assertTrue(r.get("graph"), r["key"])

    def test_the_constants_are_shared_not_copied(self) -> None:
        import recipe_common
        import recipes_more
        import recipes_vex

        self.assertIs(recipes_more.GRID_COARSE, recipe_common.GRID_COARSE)
        self.assertIs(recipes_vex.SPHERE, recipe_common.SPHERE)

    def test_primitive_vex_recipes_keep_the_run_over_value(self) -> None:
        by_key = {r["key"]: r for r in RECIPES}
        r = by_key["vex/setprimattrib"]
        self.assertEqual(r["parms"]["class"], 1)
        self.assertIn("class", r["keep"])

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
