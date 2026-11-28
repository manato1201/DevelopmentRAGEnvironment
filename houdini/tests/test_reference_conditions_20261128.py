"""Reference の「同じ結果にする条件」（2026-11-28）のテスト。

実証実験の参加者が、Reference の Vellum Solver の例を作り直しても、同じ結果にならなかった（板の大きさ・位置、出力と入力のつなぎ方、
見るフレームが、説明の文に無かった）。撮影のネットワークを実機で書き出した条件を、説明に付けて出す。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HOUDINI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOUDINI / "python_panels"))
sys.path.insert(0, str(HOUDINI.parent / "scripts"))

import reference_conditions as rc  # noqa: E402
import reference_data as rd  # noqa: E402

VELLUM = {"frame": 40, "sim": True, "display": "final", "note": "板（布）を球の上に落とす",
          "nodes": [
              {"name": "cloth", "type": "grid", "label": "Grid", "parms": [{"name": "size", "label": "Size", "where": "", "value": "2, 2"},
                                                                          {"name": "t", "label": "Center", "where": "", "value": "0, 1.0, 0"}], "inputs": []},
              {"name": "ball", "type": "sphere", "label": "Sphere", "parms": [{"name": "type", "label": "Primitive Type", "where": "", "value": "Polygon Mesh"}], "inputs": []},
              {"name": "constraints", "type": "vellumconstraints", "label": "Vellum Constraints", "parms": [],
               "inputs": [{"index": 0, "label": "Vellum Geometry", "from": "cloth", "output": 0, "output_label": "Output 1"}]},
              {"name": "solver", "type": "vellumsolver", "label": "Vellum Solver", "parms": [],
               "inputs": [{"index": 0, "label": "Vellum Geometry", "from": "constraints", "output": 0, "output_label": "Vellum Geometry"},
                          {"index": 1, "label": "Constraint Geometry", "from": "constraints", "output": 1, "output_label": "Constraint Geometry"},
                          {"index": 2, "label": "Collision Geometry", "from": "ball", "output": 0, "output_label": "Output 1"}]},
              {"name": "scene", "type": "merge", "label": "Merge", "parms": [],
               "inputs": [{"index": 0, "from": "cloth"}, {"index": 1, "from": "ball"}]},
              {"name": "final", "type": "merge", "label": "Merge", "parms": [],
               "inputs": [{"index": 0, "from": "solver"}, {"index": 1, "from": "ball"}]},
          ], "lights": [], "tab_hidden": []}


class ConditionsHtmlTest(unittest.TestCase):
    def test_everything_needed_to_rebuild_is_written(self) -> None:
        text = rc.html_block(VELLUM)
        for must in ("<b>Size</b>", "2, 2", "<b>Center</b>", "0, 1.0, 0", "Polygon Mesh",
                     "2 番目の出力（Constraint Geometry） → 2 番目の入力（Constraint Geometry）",
                     "1 番目の出力（Output 1） → 3 番目の入力（Collision Geometry）",
                     "表示フラグを <code>final</code>", "40 フレーム目を見る", "パラメータは初期値のまま"):
            self.assertIn(must, text)

    def test_a_merge_only_for_the_before_image_is_set_aside(self) -> None:
        text = rc.html_block(VELLUM)
        main, _, aside = text.partition("適用前の画像を並べるためだけのノード")
        self.assertNotIn("<code>scene</code>", main)
        self.assertIn("scene（Merge）", aside)

    def test_old_nodes_are_flagged_with_their_replacement(self) -> None:
        cond = {"frame": 1, "display": "node", "tab_hidden": ["Mountain（mountain::2.0）"],
                "nodes": [{"name": "node", "type": "mountain::2.0", "label": "Mountain", "hidden": True,
                           "replacement": "Attribute Noise（attribnoise::2.0）", "parms": [], "inputs": []}]}
        text = rc.html_block(cond)
        self.assertIn("Tab メニューに出ない古いノード", text)
        self.assertIn("Attribute Noise（attribnoise::2.0）", text)

    def test_bad_input_is_ignored_and_text_is_escaped(self) -> None:
        self.assertEqual(rc.html_block(None), "")
        self.assertEqual(rc.html_block({"nodes": []}), "")
        self.assertEqual(rc.html_block({"nodes": [{"name": "x"}]}), "", "a node without a type")
        text = rc.html_block({"display": "a", "nodes": [{"name": "a", "type": "null", "label": "<script>"}]})
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)


class EntryTest(unittest.TestCase):
    def test_sanitize_keeps_conditions_and_the_detail_shows_them(self) -> None:
        entry = rd.sanitize_entry({"what": "布を動かす", "example": "例", "conditions": VELLUM})
        self.assertEqual(entry["conditions"]["frame"], 40)
        html_text = rd.entry_html({"kind": "node", "key": "sop/vellumsolver", "label": "Vellum Solver"}, entry)
        self.assertIn("同じ結果にする条件", html_text)
        self.assertNotIn("conditions", rd.sanitize_entry({"what": "x", "conditions": "bad"}))

    def test_publish_attaches_the_dumped_conditions(self) -> None:
        import publish_reference as pr

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"sop/vellumsolver": VELLUM, "sop/broken": {"error": "x"}}), encoding="utf-8")
            targets = [{"item": {"kind": "node", "key": "sop/vellumsolver"}, "entry": {"what": "x"}},
                       {"item": {"kind": "node", "key": "sop/broken"}, "entry": {"what": "y"}},
                       {"item": {"kind": "node", "key": "sop/none"}, "entry": None}]
            self.assertEqual(pr.attach_conditions(targets, path), 1)
            self.assertEqual(targets[0]["entry"]["conditions"]["display"], "final")
            self.assertNotIn("conditions", targets[1]["entry"])
            self.assertEqual(pr.attach_conditions(targets, Path(tmp) / "missing.json"), 0)


class RecipeTest(unittest.TestCase):
    def test_shelf_tools_use_the_nodes_the_tools_really_place(self) -> None:
        sys.path.insert(0, str(HOUDINI.parent / "scripts" / "reference_capture"))
        from recipes import RECIPES

        by_key = {r["key"]: r for r in RECIPES}
        self.assertEqual(by_key["shelf/geometry_mountain"]["type"], ["attribnoise::2.0"])
        self.assertEqual(by_key["shelf/geometry_twist"]["type"], ["bend"])
        self.assertEqual(by_key["shelf/geometry_knife"]["type"], ["clip::2.0"])
        old = {"mountain::2.0", "twist", "knife"}
        for recipe in RECIPES:
            if recipe["key"].startswith(("shelf/", "vex/")):
                specs = [recipe.get("input") or {}] + list(recipe.get("inputs") or [])
                types = set(recipe["type"] if isinstance(recipe["type"], list) else [recipe["type"]])
                for spec in specs:
                    types |= {spec.get("type", "")} | {s.get("type", "") for s in spec.get("after") or []}
                self.assertFalse(types & old, recipe["key"])


class WiringDiagramTest(unittest.TestCase):
    """Reference のノード図を、ポートの位置どおりに描く（2026-11-28）。"""

    def test_ports_follow_the_real_order_and_helpers_are_left_out(self) -> None:
        sys.path.insert(0, str(HOUDINI.parent / "scripts" / "reference_capture"))
        import wiring_diagram as wd

        cond = json.loads(json.dumps(VELLUM))
        for n in cond["nodes"]:
            n["input_labels"] = ["Vellum Geometry", "Constraint Geometry", "Collision Geometry"] if "vellum" in n["type"] else []
            n["output_labels"] = ["Vellum Geometry", "Constraint Geometry", "Collision Geometry"] if "vellum" in n["type"] else ["Output 1"]
            n["multi_input"] = n["type"] == "merge"
        nodes, pos, width, height = wd.layout(cond)
        names = [n["name"] for n in nodes]
        self.assertNotIn("scene", names, "the merge only for the before image is not drawn")
        self.assertLess(pos["cloth"][1], pos["constraints"][1])
        self.assertLess(pos["constraints"][1], pos["solver"][1])
        x, _y, w = pos["solver"]
        xs = [wd._port_x(x, w, i, 3) for i in range(3)]
        self.assertEqual(xs, sorted(xs))
        self.assertGreaterEqual(xs[1] - xs[0], wd.SLOT, "each port has room for its name")

    def test_it_draws_a_png(self) -> None:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
        sys.path.insert(0, str(HOUDINI.parent / "scripts" / "reference_capture"))
        import wiring_diagram as wd

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "node.png"
            self.assertTrue(wd.render(VELLUM, out))
            self.assertGreater(out.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
