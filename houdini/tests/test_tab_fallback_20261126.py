"""Tab メニューで手順のノードが見つからないときの対処（2026-11-26。実機の指摘「Tab で探しても出てこないノードがある」）のテスト。

  ・作る手順に「Tab で見つからないとき」（作るネットワークの種類・表示名・内部名）を出す。
  ・いま開いているネットワークの種類が違う（SOP の中で DOP のノードを探す）と、場所の帯で知らせる。
  ・「Tab で出ないときは作る」: 手順のとおりの種類と名前で、自分のネットワークに作る。お手本・鍵付きのアセット・種類の違う場所には作らない。
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

HOUDINI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOUDINI / "python_panels"))

import guide_mode as gm  # noqa: E402

SANDBOX = "/obj/ai_tutorial_1"
STEP = {"tool": "create_node", "node": "src", "node_path": "jelly/dop/src", "node_type": "vellumsource",
        "node_label": "Vellum Source", "node_category": "Dop"}


class _Type:
    def __init__(self, name, category, hidden=False):
        self._name, self._category, self._hidden = name, category, hidden

    def name(self): return self._name
    def category(self): return types.SimpleNamespace(name=lambda: self._category)
    def hidden(self): return self._hidden
    def deprecated(self): return False


class _Node:
    def __init__(self, world, path, type_name, category, child_category="", locked=False):
        self.world, self._path, self._type = world, path, _Type(type_name, category)
        self._child, self._locked, self.current = child_category, locked, False

    def path(self): return self._path
    def type(self): return self._type
    def childTypeCategory(self): return types.SimpleNamespace(name=lambda: self._child)
    def isInsideLockedHDA(self): return self._locked
    def node(self, name): return self.world.get(f"{self._path}/{name}")
    def moveToGoodPosition(self): pass
    def setCurrent(self, on, clear_all_selected=False): self.current = on

    def createNode(self, type_name, name):
        node = _Node(self.world, f"{self._path}/{name}", type_name, self._child)
        self.world[node.path()] = node
        return node


def _world():
    world: dict = {}
    for path, (type_name, category, child, locked) in {
        "/obj": ("obj", "Object", "Object", False),
        "/obj/jelly": ("geo", "Object", "Sop", False),
        "/obj/jelly/dop": ("dopnet", "Sop", "Dop", False),
        "/obj/jelly/solver": ("vellumsolver", "Sop", "Dop", True),
        f"{SANDBOX}/jelly/dop": ("dopnet", "Sop", "Dop", False),
        f"{SANDBOX}/jelly/dop/src": ("vellumsource", "Dop", "", False),
    }.items():
        world[path] = _Node(world, path, type_name, category, child, locked)
    return world, types.SimpleNamespace(node=lambda p: world.get(p))


class TabHelpTest(unittest.TestCase):
    def test_the_help_names_the_label_the_network_kind_and_the_button(self) -> None:
        text = gm.tab_help_html(STEP)
        self.assertIn("Vellum Source", text)
        self.assertIn("DOP", text)
        self.assertIn("vellumsource", text)
        self.assertIn("Tab で出ないときは作る", text)
        self.assertEqual(gm.tab_help_html({"tool": "connect_nodes"}), "")

    def test_a_wrong_network_kind_is_reported(self) -> None:
        self.assertIn("SOP", gm.category_mismatch("Sop", STEP))
        self.assertEqual(gm.category_mismatch("Dop", STEP), "")
        self.assertEqual(gm.category_mismatch("", STEP), "")
        self.assertEqual(gm.category_mismatch("Sop", {**STEP, "node_category": ""}), "")

    def test_older_guides_get_the_kind_from_the_example(self) -> None:
        _world_nodes, hou = _world()
        step = {k: v for k, v in STEP.items() if k != "node_category"}
        self.assertEqual(gm.fill_node_category(hou, step, SANDBOX)["node_category"], "Dop")
        self.assertNotIn("node_category", step, "元の手順は書き換えない")


class CreateStepNodeTest(unittest.TestCase):
    def test_it_creates_the_exact_type_in_my_network(self) -> None:
        world, hou = _world()
        message = gm.create_step_node(hou, STEP, "/obj/jelly/dop")
        self.assertIn("作りました: /obj/jelly/dop/src", message)
        self.assertEqual(world["/obj/jelly/dop/src"].type().name(), "vellumsource")
        self.assertTrue(world["/obj/jelly/dop/src"].current)
        self.assertIn("もうあります", gm.create_step_node(hou, STEP, "/obj/jelly/dop"))

    def test_it_refuses_the_wrong_places(self) -> None:
        world, hou = _world()
        self.assertIn("SOP", gm.create_step_node(hou, STEP, "/obj/jelly"))
        self.assertIn("鍵の掛かった", gm.create_step_node(hou, STEP, "/obj/jelly/solver"))
        self.assertIn("お手本", gm.create_step_node(hou, STEP, f"{SANDBOX}/jelly/dop"))
        self.assertIn("分かりません", gm.create_step_node(hou, STEP, ""))
        self.assertIn("作る手順ではありません", gm.create_step_node(hou, {"tool": "cook_node"}, "/obj/jelly/dop"))
        self.assertNotIn("/obj/jelly/src", world)


class _AssetNode:
    def __init__(self, world, path, label, locked=False, inside=False, editable=False):
        self.world, self._path, self._label = world, path, label
        self._locked, self._inside, self._editable = locked, inside, editable

    def path(self): return self._path
    def type(self): return types.SimpleNamespace(description=lambda: self._label)
    def isLockedHDA(self): return self._locked
    def isInsideLockedHDA(self): return self._inside
    def isEditableInsideLockedHDA(self): return self._editable
    def parent(self): return self.world.get(self._path.rsplit("/", 1)[0] or "/")


class LockedAssetTest(unittest.TestCase):
    """実機: お手本の Vellum Solver の中に入り、最初から入っている Vellum Source（sources/defaultsource）を、自分でも作ろうとした。"""

    def setUp(self) -> None:
        world: dict = {}
        for path, label, locked, inside, editable in (
            ("/", "root", False, False, False), ("/obj", "obj", False, False, False),
            ("/obj/jelly", "Geometry", False, False, False),
            ("/obj/jelly/arm_solver", "Vellum Solver", True, False, False),
            ("/obj/jelly/arm_solver/dopnet1", "DOP Network", False, True, False),
            ("/obj/jelly/arm_solver/dopnet1/sources", "Subnetwork", False, True, False),
            ("/obj/jelly/arm_solver/dopnet1/forces", "Subnetwork", False, True, True),
        ):
            world[path] = _AssetNode(world, path, label, locked, inside, editable)
        self.hou = types.SimpleNamespace(node=lambda p: world.get(p))

    def test_inside_the_solver_says_there_is_nothing_to_build(self) -> None:
        for path in ("/obj/jelly/arm_solver", "/obj/jelly/arm_solver/dopnet1/sources"):
            note = gm.asset_inside_note(self.hou, path)
            self.assertIn("「Vellum Solver」（/obj/jelly/arm_solver）の中身", note, path)
            self.assertIn("作る必要はありません", note)

    def test_my_own_network_and_the_editable_part_are_quiet(self) -> None:
        self.assertEqual(gm.asset_inside_note(self.hou, "/obj/jelly"), "")
        self.assertEqual(gm.asset_inside_note(self.hou, "/obj/jelly/arm_solver/dopnet1/forces"), "")
        self.assertEqual(gm.asset_inside_note(self.hou, "/obj/nothing"), "")


if __name__ == "__main__":
    unittest.main()
