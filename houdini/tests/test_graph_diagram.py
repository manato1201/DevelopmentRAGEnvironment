"""graph_diagram.py（保存したグラフ → ネットワーク図のモデル）と、台本への images の書き込みのテスト。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import graph_diagram as gd  # noqa: E402
import video_script as vs  # noqa: E402

BLACK_HOLE = {
    "sandbox": "/obj/ai_tutorial_1",
    "nodes": [
        {"id": "geo1", "kind": "geo", "label": "geo1", "position": [0, -6], "params": {}},
        {"id": "geo1/emit", "kind": "attribwrangle", "label": "emit", "position": [-5.0, -2.0], "parent": "geo1"},
        {"id": "geo1/emit/attribvop1", "kind": "attribvop", "label": "attribvop1", "position": [0, 0], "parent": "geo1/emit"},
        {"id": "geo1/swirl", "kind": "attribwrangle", "label": "swirl", "position": [-5.0, -4.0], "parent": "geo1"},
        {"id": "geo1/horizon", "kind": "sphere", "label": "horizon", "position": [1.0, -2.0], "parent": "geo1"},
        {"id": "geo1/merge1", "kind": "merge", "label": "merge1", "position": [-2.0, -7.0], "parent": "geo1"},
    ],
    "edges": [
        {"source": "geo1/emit", "target": "geo1/swirl", "targetInput": 0},
        {"source": "geo1/swirl", "target": "geo1/merge1", "targetInput": 0},
        {"source": "geo1/horizon", "target": "geo1/merge1", "targetInput": 1},
        {"source": "geo1/emit", "target": "geo1/emit/attribvop1", "targetInput": 0},  # 別の階層への接続は図に出さない
    ],
}


class GraphDiagramTest(unittest.TestCase):
    def test_picks_the_working_network_and_its_connections(self) -> None:
        label, model = gd.graph_to_model(BLACK_HOLE)
        self.assertEqual(label, "/obj/ai_tutorial_1/geo1")
        self.assertEqual({n["name"] for n in model}, {"emit", "swirl", "horizon", "merge1"})
        by_name = {n["name"]: n for n in model}
        self.assertEqual(by_name["swirl"]["inputs"], [("geo1/emit", 0)])
        self.assertEqual(sorted(by_name["merge1"]["inputs"]), [("geo1/horizon", 1), ("geo1/swirl", 0)])
        self.assertTrue(by_name["merge1"]["display"], "the terminal node is the displayed one")
        self.assertFalse(by_name["emit"]["display"])
        self.assertEqual(by_name["emit"]["type"], "attribwrangle")

    def test_prefers_a_shallow_network_over_a_big_subnet(self) -> None:
        nodes = [
            {"id": "geo1", "kind": "geo"},
            {"id": "geo1/import", "kind": "fbx", "parent": "geo1"},
            {"id": "geo1/rig", "kind": "autorig", "parent": "geo1"},
        ] + [{"id": f"geo1/rig/n{i}", "kind": "null", "parent": "geo1/rig"} for i in range(40)]
        self.assertEqual(gd.pick_container({"nodes": nodes}), "geo1")
        _label, model = gd.graph_to_model({"nodes": nodes, "edges": []})
        self.assertEqual({n["name"] for n in model}, {"import", "rig"})

    def test_single_child_containers_are_a_fallback(self) -> None:
        graph = {"nodes": [{"id": "a", "kind": "geo"}, {"id": "a/b", "kind": "box", "parent": "a"}]}
        self.assertEqual(gd.pick_container(graph), "a")

    def test_top_level_nodes_when_nothing_is_nested(self) -> None:
        graph = {"sandbox": "/obj/x", "nodes": [{"id": "box1", "kind": "box"}, {"id": "xform1", "kind": "xform"}],
                 "edges": [{"source": "box1", "target": "xform1", "targetInput": 0}]}
        label, model = gd.graph_to_model(graph)
        self.assertEqual(label, "/obj/x")
        self.assertEqual(len(model), 2)
        self.assertEqual(model[1]["inputs"], [("box1", 0)])

    def test_empty_and_malformed_graphs_give_nothing(self) -> None:
        self.assertEqual(gd.graph_to_model({}), ("", []))
        self.assertEqual(gd.graph_to_model({"nodes": [{"kind": "box"}, "x", None]}), ("", []))
        bad_position = {"nodes": [{"id": "a", "position": "oops"}]}
        _label, model = gd.graph_to_model(bad_position)
        self.assertEqual(model[0]["x"], 0.0)

    def test_node_count_is_capped(self) -> None:
        graph = {"nodes": [{"id": f"n{i}", "kind": "null"} for i in range(200)]}
        _label, model = gd.graph_to_model(graph)
        self.assertEqual(len(model), gd.MAX_NODES)

    def test_model_feeds_the_layer_assignment_shape(self) -> None:
        """screen_capture._assign_layers が読むキー（path / inputs / x / name）が揃っている。"""
        _label, model = gd.graph_to_model(BLACK_HOLE)
        for entry in model:
            for key in ("path", "name", "type", "color", "display", "render", "bypass", "error", "x", "inputs"):
                self.assertIn(key, entry)


class ScriptImagesTest(unittest.TestCase):
    def _steps(self, tmp: Path) -> list[dict]:
        img = tmp / "s.png"
        img.write_bytes(b"png")
        return [{"step": 1, "tool": "create_node", "result": "「Box」ノード（box）を作り、名前を box1 にする",
                 "tool_result": "ok", "viewport": str(img), "network": str(img)}]

    def test_images_are_written_into_the_script(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "t.md"
            md.write_text("---\ntitle: T\n---\n## 概要\n\n箱を作ります。\n\n## 手順\n\n1. 箱を作る\n", encoding="utf-8")
            diagram = tmp / "t_node_diagram.png"
            diagram.write_bytes(b"png")
            path, _msg = vs.prepare_script_file(md, self._steps(tmp), None, {"node_diagram": str(diagram), "empty": ""})
            assert path is not None
            script = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(script["images"], {"node_diagram": str(diagram)})

    def test_no_images_means_no_images_key(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "t.md"
            md.write_text("---\ntitle: T\n---\n## 概要\n\n箱を作ります。\n", encoding="utf-8")
            path, _msg = vs.prepare_script_file(md, self._steps(tmp), None)
            assert path is not None
            self.assertNotIn("images", json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
