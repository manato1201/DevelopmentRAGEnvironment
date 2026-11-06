"""guide_mode.py（案内モード）のテスト。Houdini は偽物（fake hou）で、標準の unittest。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
Qt の画面も確かめるとき:     uv run --with PySide6 python -m unittest houdini/tests/test_guide_mode.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import guide_mode as gm  # noqa: E402
import guide_shortcuts as gs  # noqa: E402


# ── 偽の Houdini ───────────────────────────────────────────────────────────

class FakeType:
    def __init__(self, name, label, category="Sop"):
        self._name, self._label, self._category = name, label, category

    def name(self): return self._name
    def description(self): return self._label
    def category(self): return types.SimpleNamespace(name=lambda: self._category)


class FakeNode:
    def __init__(self, path, type_name="null", label="Null"):
        self._path = path
        self._type = FakeType(type_name, label)
        self.children_nodes: list[FakeNode] = []
        self.parent_node = None
        self.current = False
        self.selected = False

    def name(self): return self._path.rsplit("/", 1)[-1]
    def path(self): return self._path
    def type(self): return self._type
    def parent(self): return self.parent_node
    def allSubChildren(self):
        out = []
        for c in self.children_nodes:
            out.append(c)
            out += c.allSubChildren()
        return out

    def setCurrent(self, on, clear_all_selected=False):
        self.current = on
        self.selected = on

    def setSelected(self, on, clear_all_selected=False):
        self.selected = on


class FakeEditor:
    def __init__(self, pwd):
        self._pwd = pwd
        self.shown = 0
        self.homed = 0
        self.flashes: list[str] = []

    def pwd(self): return self._pwd
    def setPwd(self, node): self._pwd = node
    def homeToSelection(self): self.homed += 1
    def setIsCurrentTab(self): self.shown += 1
    def flashMessage(self, image, message, duration): self.flashes.append(message)


class FakePane:
    def __init__(self): self.shown = 0
    def setIsCurrentTab(self): self.shown += 1


def make_hou(with_spreadsheet=True):
    obj = FakeNode("/obj", "obj", "Object")
    geo = FakeNode("/obj/geo1", "geo", "Geometry")
    grid = FakeNode("/obj/geo1/grid1", "grid", "Grid")
    scatter = FakeNode("/obj/geo1/scatter1", "scatter::2.0", "Scatter")
    obj.children_nodes = [geo]
    geo.parent_node = obj
    geo.children_nodes = [grid, scatter]
    grid.parent_node = scatter.parent_node = geo
    editor = FakeEditor(geo)
    parm, viewer, sheet = FakePane(), FakePane(), FakePane()
    nodes = {n.path(): n for n in (obj, geo, grid, scatter)}
    tabs = {"NetworkEditor": editor, "Parm": parm, "SceneViewer": viewer}
    pane_types = {name: name for name in ("NetworkEditor", "Parm", "SceneViewer")}
    if with_spreadsheet:
        tabs["DetailsViewer"] = sheet
        pane_types["DetailsViewer"] = "DetailsViewer"
    helped: list = []
    hou = types.SimpleNamespace(
        paneTabType=types.SimpleNamespace(**pane_types),
        ui=types.SimpleNamespace(paneTabOfType=lambda t: tabs.get(t), displayNodeHelp=lambda nt: helped.append(nt)),
        node=lambda path: nodes.get(path),
        selectedNodes=lambda: [n for n in nodes.values() if n.selected],
    )
    hou.fake = types.SimpleNamespace(editor=editor, parm=parm, viewer=viewer, sheet=sheet, geo=geo, grid=grid, scatter=scatter, helped=helped)
    return hou


# ── 手順の記録（generation 時の step_screenshots） ──────────────────────────────

STEPS = [
    {"step": 1, "tool": "create_node", "result": "Object レベルに「Geometry」ノードを作り、名前を geo1 にする。この中で作業する",
     "guide": {"node": "geo1", "node_path": "geo1", "node_type": "geo", "node_label": "Geometry"}, "viewport": "x.png"},
    {"step": 2, "tool": "create_node", "result": "「Scatter」ノード（scatter::2.0）を作り、名前を scatter1 にする",
     "guide": {"node": "scatter1", "node_path": "geo1/scatter1", "node_type": "scatter::2.0", "node_label": "Scatter"}},
    {"step": 3, "tool": "connect_nodes", "result": "grid1 の出力を、scatter1 の入力につなぐ",
     "guide": {"node": "scatter1", "from": "grid1", "to": "scatter1", "node_type": "scatter::2.0"}},
    {"step": 4, "tool": "set_parameter", "result": "scatter1 のパラメータを設定: Force Total Count を 500",
     "guide": {"node": "scatter1", "node_type": "scatter::2.0", "node_label": "Scatter",
               "parms": [{"name": "npts", "label": "Force Total Count", "old": "1000", "new": "500", "where": "Distribution"}]}},
    {"step": 5, "tool": "cook_node", "result": "scatter1 を評価（cook）して、エラーが出ないことを確認する", "guide": {"node": "scatter1"}},
    {"step": 6, "tool": "inspect_geometry", "result": "調べる"},
]


class BuildGuideTest(unittest.TestCase):
    def test_steps_carry_tab_node_parms_and_shortcuts(self):
        guide = gm.build_guide(STEPS, "岩の散布", "basic")
        steps = guide["steps"]
        self.assertEqual(len(steps), 5, "tools without a tab (inspect_geometry) are skipped")
        self.assertEqual([s["tab"] for s in steps], ["network", "network", "network", "parm", "viewport"])
        create = steps[1]
        self.assertEqual(create["node"], "scatter1")
        self.assertIn("Tab を押し", create["hint"])
        self.assertIn("Scatter", create["hint"])
        self.assertIn("Tab", [s["keys"] for s in create["shortcuts"]])
        param = steps[3]
        self.assertEqual(param["parms"][0]["where"], "Distribution")
        self.assertIn("1000 → 500", param["hint"])
        self.assertIn("場所: Distribution", param["hint"])
        connect = steps[2]
        self.assertIn("grid1 の出力から、scatter1 の入力へ", connect["hint"])
        self.assertIn("Y を押しながら線をまたいでドラッグ", [s["keys"] for s in connect["shortcuts"]])
        self.assertEqual(guide["level"], "basic")

    def test_every_step_shortcut_comes_from_the_confirmed_table(self):
        table = {(r["keys"], r["what"], r["group"]) for r in gs.SHORTCUTS}
        for step in gm.build_guide(STEPS)["steps"]:
            self.assertGreaterEqual(len(step["shortcuts"]), 6, step["tool"])
            for item in step["shortcuts"]:
                self.assertIn((item["keys"], item["what"], item["group"]), table)
        # 画面を見る手順（cook）には、ビューポート・タイムラインのキーを出す
        cook = gm.build_guide(STEPS)["steps"][4]["shortcuts"]
        self.assertEqual({"ビューポート", "タイムライン", "ペイン（タブ）の切り替え"}, {c["group"] for c in cook})

    def test_old_records_without_guide_are_read_from_the_instruction(self):
        old = [{k: v for k, v in s.items() if k != "guide"} for s in STEPS]
        steps = gm.build_guide(old)["steps"]
        self.assertEqual(steps[0]["node"], "geo1")
        self.assertEqual(steps[1]["node"], "scatter1")
        self.assertEqual(steps[1]["node_type"], "scatter::2.0")
        self.assertEqual((steps[2]["from"], steps[2]["to"]), ("grid1", "scatter1"))
        self.assertEqual(steps[3]["node"], "scatter1")
        self.assertEqual(steps[3]["parms"][0]["label"], "Force Total Count")
        self.assertEqual(steps[4]["node"], "scatter1")

    def test_extras_are_kept_only_when_present(self):
        guide = gm.build_guide(STEPS, extras={"tips": "コツ", "challenge": ""})
        self.assertEqual(guide["tips"], "コツ")
        self.assertNotIn("challenge", guide)

    def test_sections_come_from_the_markdown(self):
        md = "---\ntitle: T\n---\n## 概要\nあ\n\n## 前提条件\n- Houdini 22\n\n## 手順\n1. a\n\n## TIPS\n- G で寄る\n\n## 自分でやってみよう\n点が300個以上\n"
        found = gm.sections_from_markdown(md)
        self.assertIn("Houdini 22", found["prerequisites"])
        self.assertIn("G で寄る", found["tips"])
        self.assertIn("300個", found["challenge"])


class RecordedAtGenerationTest(unittest.TestCase):
    """生成時（houdini_tools）に、案内データが手順の記録へ入ること。"""

    def setUp(self):
        import test_parm_tools as tp

        self.hou, self.sandbox, self.add, self.nodes = tp.make_world()
        self.ex = tp.make_executor(self.hou, self.sandbox)
        self.scatter = self.add("geo1/scatter1", "scatter::2.0")
        self.scatter.type = lambda: types.SimpleNamespace(name=lambda: "scatter::2.0", description=lambda: "Scatter")  # 偽の型に表示名を足す
        inner = tp.Template("npts", "Force Total Count", "Int", default=1000, lo=0, hi=10000)
        folder = tp.Template("distribution", "Distribution", "Folder", children=[inner])
        self.scatter._tpls = []
        self.scatter.add_parm(inner, 1000, top=False)
        self.scatter._tpls.append(tp.Template("tabs", "", "FolderSet", children=[folder]))

    def test_set_parameter_step_records_node_and_parm_location(self):
        changes = [{"name": "npts", "label": "Force Total Count", "old": "1000", "new": "500", "code": False}]
        guide = self.ex._step_guide("set_parameter", {"node": "geo1/scatter1"}, self.scatter.path(), changes)
        self.assertEqual((guide["node"], guide["node_type"]), ("scatter1", "scatter::2.0"))
        self.assertEqual(guide["parms"][0], {"name": "npts", "label": "Force Total Count", "old": "1000", "new": "500", "where": "Distribution"})

    def test_code_parms_do_not_copy_the_code(self):
        changes = [{"name": "npts", "label": "VEXpression", "old": "", "new": "int n = 3;", "code": True}]
        guide = self.ex._step_guide("set_parameter", {}, self.scatter.path(), changes)
        self.assertNotIn("int n", guide["parms"][0]["new"])

    def test_connect_and_delete_steps(self):
        guide = self.ex._step_guide("connect_nodes", {"from_node": "geo1/grid1", "to_node": "geo1/scatter1"}, self.scatter.path(), None)
        self.assertEqual((guide["from"], guide["to"]), ("grid1", "scatter1"))
        guide = self.ex._step_guide("delete_node", {"node": "geo1/old1"}, None, None)
        self.assertEqual(guide, {"node": "old1"})

    def test_a_failing_lookup_returns_an_empty_guide(self):
        self.ex._hou = None
        self.assertEqual(self.ex._step_guide("cook_node", {}, "/obj/x", None), {})

    def test_the_video_engine_does_not_get_the_guide(self):
        import tempfile
        from unittest import mock

        import video_factory_bridge as vfb

        steps = [{"step": 1, "tool": "create_node", "result": "x", "guide": {"node": "a"}, "viewport": None, "network": None}]
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "t.md"
            md.write_text("x", encoding="utf-8")
            exe = tmp / "engine.exe"
            exe.write_text("", encoding="utf-8")
            with mock.patch.object(vfb.subprocess, "Popen") as popen:
                vfb.launch_video_generation(md, md.with_suffix(".json"), "/obj/x", steps, str(exe))
            self.assertTrue(popen.called)
            written = json.loads((tmp / "t_screenshots.json").read_text(encoding="utf-8"))
            self.assertEqual(written[0]["tool"], "create_node")
            self.assertNotIn("guide", written[0])
            self.assertIn("guide", steps[0], "the caller's records are not modified")


class StorageTest(unittest.TestCase):
    def test_write_load_and_list(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "rock.md"
            path = gm.guide_path_for(md)
            self.assertEqual(path.name, "rock_guide.json")
            gm.write_guide(path, gm.build_guide(STEPS, "岩の散布", "applied"))
            (tmp / "broken_guide.json").write_text("{not json", encoding="utf-8")
            (tmp / "empty_guide.json").write_text(json.dumps({"steps": []}), encoding="utf-8")
            loaded = gm.load_guide(path)
            self.assertEqual(len(loaded["steps"]), 5)
            listed = gm.list_guides(tmp)
            self.assertEqual(len(listed), 1, "broken and empty files are not listed")
            self.assertIn("岩の散布", listed[0][0])
            self.assertIn("applied", listed[0][0])
            self.assertEqual(gm.list_guides(None), [])
            self.assertEqual(gm.list_guides(tmp / "missing"), [])
            self.assertIsNone(gm.load_guide(tmp / "nothing.json"))


class HoudiniActionsTest(unittest.TestCase):
    def test_show_tab_brings_the_pane_forward(self):
        hou = make_hou()
        ok, message = gm.show_tab(hou, "parm")
        self.assertTrue(ok)
        self.assertEqual(hou.fake.parm.shown, 1)
        self.assertIn("パラメータ", message)

    def test_show_tab_explains_when_the_pane_is_missing(self):
        hou = make_hou(with_spreadsheet=False)
        ok, message = gm.show_tab(hou, "spreadsheet")
        self.assertFalse(ok)
        self.assertIn("見つかりません", message)
        self.assertIn("＋", message)

    def test_find_node_prefers_name_then_type(self):
        hou = make_hou()
        node, how = gm.find_node(hou, "scatter1", "scatter::2.0")
        self.assertEqual((node.path(), how), ("/obj/geo1/scatter1", "name"))
        node, how = gm.find_node(hou, "scatter9", "scatter::2.0")
        self.assertEqual((node.path(), how), ("/obj/geo1/scatter1", "type"), "a learner's differently numbered node is still found")
        self.assertEqual(gm.find_node(hou, "nothing", "mountain::2.0"), (None, ""))

    def test_show_nodes_selects_frames_and_flashes(self):
        hou = make_hou()
        found, missing = gm.show_nodes(hou, [("scatter1", ""), ("ghost", "")])
        self.assertEqual((found, missing), (["scatter1"], ["ghost"]))
        self.assertTrue(hou.fake.scatter.current)
        self.assertEqual(hou.fake.editor.homed, 1)
        self.assertIn("scatter1", hou.fake.editor.flashes[0])

    def test_show_nodes_never_touches_other_nodes(self):
        hou = make_hou()
        gm.show_nodes(hou, [("scatter1", "")])
        self.assertFalse(hou.fake.grid.selected)
        self.assertFalse(hou.fake.grid.current)

    def test_apply_step_per_tool(self):
        steps = gm.build_guide(STEPS)["steps"]
        hou = make_hou()
        messages = gm.apply_step(hou, steps[3])  # set_parameter
        self.assertEqual(hou.fake.parm.shown, 1)
        self.assertTrue(any("示したノード: scatter1" in m for m in messages))
        hou = make_hou()
        gm.apply_step(hou, steps[2])  # connect: 両方を選ぶ
        self.assertTrue(hou.fake.grid.selected and hou.fake.scatter.selected)
        hou = make_hou()
        gm.apply_step(hou, steps[4])  # cook
        self.assertEqual(hou.fake.viewer.shown, 1)

    def test_apply_step_for_a_node_not_built_yet(self):
        hou = make_hou()
        step = {"tool": "create_node", "node": "mountain1", "node_type": "mountain::2.0", "node_label": "Mountain", "tab": "network"}
        messages = gm.apply_step(hou, step)
        self.assertTrue(any("まだありません" in m and "Mountain" in m for m in messages))
        self.assertEqual(hou.fake.editor.shown, 1)

    def test_a_failing_houdini_call_does_not_raise(self):
        hou = make_hou()
        hou.ui.paneTabOfType = lambda t: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertFalse(gm.show_tab(hou, "network")[0])
        self.assertEqual(gm.show_nodes(hou, [("scatter1", "")])[0], ["scatter1"], "the node is still selected without a network pane")


class SelectedNodeTest(unittest.TestCase):
    def test_info_and_query(self):
        hou = make_hou()
        self.assertIsNone(gm.selected_node_info(hou))
        hou.fake.scatter.setCurrent(True)
        info = gm.selected_node_info(hou)
        self.assertEqual((info["label"], info["type_name"], info["name"]), ("Scatter", "scatter::2.0", "scatter1"))
        self.assertEqual(gm.doc_query(info), "Scatter node")
        self.assertEqual(gm.doc_query({"label": "Attribute Wrangle", "type_name": "attribwrangle"}), "Attribute Wrangle attribwrangle node")
        self.assertEqual(gm.doc_query({"label": "Foo", "type_name": "labs::foo_bar::1.0"}), "Foo foo_bar node")

    def test_open_help(self):
        hou = make_hou()
        hou.fake.scatter.setCurrent(True)
        info = gm.selected_node_info(hou)
        self.assertTrue(gm.open_node_help(hou, info)[0])
        self.assertEqual(hou.fake.helped, [hou.fake.scatter.type()])
        hou.ui.displayNodeHelp = lambda nt: (_ for _ in ()).throw(RuntimeError("no help"))
        self.assertFalse(gm.open_node_help(hou, info)[0])


class GuideViewTest(unittest.TestCase):
    """Qt が無い環境では飛ばす（描画の HTML は guide_view の関数）。"""

    @classmethod
    def setUpClass(cls):
        try:
            import guide_view
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"guide_view をimportできません: {exc}") from exc
        cls.gv = guide_view

    def test_step_html_shows_node_parms_tab_and_shortcuts(self):
        guide = gm.build_guide(STEPS, "t")
        text = self.gv.render_step_html(guide, 3)
        for word in ("scatter1", "Force Total Count", "1000", "500", "場所: Distribution", "パラメータ", "Ctrl + Z", "ラダー"):
            self.assertIn(word, text)
        self.assertEqual(self.gv.render_step_html({"steps": []}, 0), "")
        self.assertIn("&lt;", self.gv.render_step_html({"steps": [{"instruction": "<b>x</b>", "tab_label": "t"}]}, 0), "text is escaped")

    def test_sections_html(self):
        text = self.gv.render_sections_html({"tips": "G で寄る", "challenge": "300個以上", "prerequisites": ""})
        self.assertIn("TIPS", text)
        self.assertIn("自分でやってみよう", text)
        self.assertNotIn("前提条件", text)


class ShortcutTableTest(unittest.TestCase):
    """ショートカットの表（guide_shortcuts.py）。公式ドキュメントで確かめたものだけ、出典つきで。"""

    def test_every_row_has_a_group_a_source_and_text(self):
        for row in gs.SHORTCUTS:
            self.assertIn(row["group"], gs.GROUPS, row["id"])
            self.assertIn(row["source"], gs.SOURCES, row["id"])
            self.assertTrue(row["keys"].strip() and row["what"].strip(), row["id"])
        ids = [r["id"] for r in gs.SHORTCUTS]
        self.assertEqual(len(ids), len(set(ids)), "ids are unique")
        for name, (title, url) in gs.SOURCES.items():
            self.assertTrue(url.startswith("https://www.sidefx.com/docs/houdini/"), name)

    def test_there_are_many_more_than_before(self):
        self.assertGreaterEqual(len(gs.SHORTCUTS), 70)
        for group in gs.GROUPS:
            self.assertTrue([r for r in gs.SHORTCUTS if r["group"] == group], group)

    def test_keys_that_could_not_be_confirmed_are_not_listed(self):
        keys = [r["keys"] for r in gs.SHORTCUTS]
        self.assertNotIn("L", keys, "layout key: not in the docs")
        for unconfirmed in ("Ctrl + C", "Ctrl + V", "Ctrl + X", "Ctrl + Shift + Z", "F2"):
            self.assertNotIn(unconfirmed, keys, unconfirmed)
        # Delete は、公式に書かれているのは「付箋・ネットワークボックス」だけ。ノードの削除のキーとしては載せない
        for row in gs.SHORTCUTS:
            if "Delete" in row["keys"]:
                self.assertEqual(row["group"], gs.GROUP_ORGANIZE, row["id"])
                self.assertEqual(row["source"], "organize", row["id"])
                self.assertTrue("ボックス" in row["what"] or "付箋" in row["what"], row["id"])

    def test_each_tool_has_a_list_and_only_known_ids(self):
        for tool, ids in gs.TOOL_IDS.items():
            self.assertGreaterEqual(len(ids), 6, tool)
            self.assertEqual(len(ids), len(set(ids)), tool)
            for i in ids:
                self.assertIn(i, gs.BY_ID, (tool, i))
        self.assertEqual(set(gs.TOOL_IDS), set(gm.TOOL_TAB), "every guided tool has shortcuts")
        for i in gs.CODE_PARM_IDS:
            self.assertIn(i, gs.BY_ID)

    def test_for_step(self):
        create = gs.for_step("create_node")
        self.assertEqual(create[0]["keys"], "Tab")
        self.assertEqual(gs.for_step("nothing"), [])
        plain = [r["keys"] for r in gs.for_step("set_parameter")]
        code = [r["keys"] for r in gs.for_step("set_parameter", code=True)]
        self.assertNotIn("欄をクリックして Alt + E", plain)
        self.assertIn("欄をクリックして Alt + E", code, "code parameters also get the external editor key")
        self.assertEqual(len(code), len(plain) + 1)

    def test_code_parameter_steps_get_the_editor_key(self):
        steps = [{"step": 1, "tool": "set_parameter", "result": "w のパラメータを設定: VEXpression を x",
                  "guide": {"node": "w", "parms": [{"name": "snippet", "label": "VEXpression", "old": "", "new": "（コード。手順書を見る）", "where": ""}]}}]
        keys = [s["keys"] for s in gm.build_guide(steps)["steps"][0]["shortcuts"]]
        self.assertIn("欄をクリックして Alt + E", keys)

    def test_organizing_shortcuts_are_there(self):
        """ネットワークボックス・付箋・整列など、ネットワークを整理するキー。"""
        organize = {r["id"]: r for r in gs.SHORTCUTS if r["group"] == gs.GROUP_ORGANIZE}
        self.assertGreaterEqual(len(organize), 15)
        expected = {
            "net_box": "Shift + O", "net_note": "Shift + P", "org_minimize": "Shift + J", "org_restore": "Shift + K",
            "org_shrink": "Shift + M", "net_align": "Shift + A を押しながらドラッグ", "org_distribute": "Alt + A を押しながらドラッグ",
            "org_color": "C", "org_shape": "Z", "org_delete_all": "Shift + Delete",
        }
        for rid, keys in expected.items():
            self.assertEqual(organize[rid]["keys"], keys, rid)
        steps = gm.build_guide(STEPS)["steps"]
        connect = next(s for s in steps if s["tool"] == "connect_nodes")
        self.assertIn(gs.GROUP_ORGANIZE, {c["group"] for c in connect["shortcuts"]}, "tidy-up keys appear after wiring")
        self.assertIn("Shift + O", [c["keys"] for c in connect["shortcuts"]])
        self.assertEqual([g for g, _ in gs.cheatsheet("ボックス")][:2], [gs.GROUP_ORGANIZE], "the box can be found by searching")

    def test_cheatsheet_groups_and_filters(self):
        everything = gs.cheatsheet()
        self.assertEqual([g for g, _ in everything], list(gs.GROUPS))
        self.assertEqual(sum(len(rows) for _g, rows in everything), len(gs.SHORTCUTS))
        found = gs.cheatsheet("space")
        self.assertTrue(found and all("space" in (r["keys"] + r["what"] + r["group"]).lower() for _g, rows in found for r in rows))
        self.assertEqual([g for g, _ in gs.cheatsheet("タイムライン")], ["タイムライン"], "the group name is searched too")
        self.assertEqual(gs.cheatsheet("ZZZ存在しない"), [])
        self.assertEqual(gs.cheatsheet("ctrl+z")[0][1][0]["id"], "undo", "spaces and case are ignored")


class CheatSheetViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import guide_view
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"guide_view をimportできません: {exc}") from exc
        cls.gv = guide_view

    def test_step_html_has_group_headings(self):
        text = self.gv.render_step_html(gm.build_guide(STEPS)["steps"] and gm.build_guide(STEPS), 2)
        for word in ("ネットワークエディタ", "ペイン（タブ）の切り替え", "共通", "Y を押しながら線をまたいでドラッグ"):
            self.assertIn(word, text)

    def test_old_guides_without_groups_still_render(self):
        guide = {"steps": [{"instruction": "x", "tab_label": "t", "shortcuts": [{"keys": "Tab", "what": "メニュー"}]}]}
        text = self.gv.render_step_html(guide, 0)
        self.assertIn("<code>Tab</code>", text)

    def test_the_cheat_sheet_button_swaps_the_lower_pane_and_filters(self):
        import os
        import tempfile

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            gm.write_guide(Path(d) / "t_guide.json", gm.build_guide(STEPS, "t", "basic", {"tips": "G で寄る"}))
            widget = self.gv.GuideWidget(lambda: {"local_bridge_dir": ""})
            widget._tutorials_dir = lambda: Path(d)
            widget.refresh()
            self.assertIn("G で寄る", widget._extra_view.toPlainText(), "the tutorial's own sections first")
            widget._sheet_btn.setChecked(True)
            self.assertFalse(widget._sheet_filter.isHidden())
            self.assertIn("ショートカット一覧", widget._extra_view.toPlainText())
            self.assertNotIn("G で寄る", widget._extra_view.toPlainText())
            widget._sheet_filter.setText("タイムライン")
            text = widget._extra_view.toPlainText()
            self.assertIn("順方向", text)
            self.assertNotIn("ネットワークエディタ", text.split("出典")[0])
            widget._sheet_btn.setChecked(False)
            self.assertTrue(widget._sheet_filter.isHidden())
            self.assertEqual(widget._sheet_filter.text(), "")
            self.assertIn("G で寄る", widget._extra_view.toPlainText(), "back to the tutorial's sections")

    def test_cheatsheet_html(self):
        text = self.gv.render_cheatsheet_html()
        self.assertIn(f"{len(gs.SHORTCUTS)}個", text)
        for word in ("Hotkey quick reference", "Network editor shortcuts", "https://www.sidefx.com/docs/houdini/start/hotkeys.html", "ホットキーを変えている場合"):
            self.assertIn(word, text)
        filtered = self.gv.render_cheatsheet_html("タイムライン")
        self.assertIn("再生", filtered)
        self.assertNotIn("ネットワークエディタ", filtered.split("出典")[0])
        self.assertIn("合うショートカットはありません", self.gv.render_cheatsheet_html("ZZZ存在しない"))
        self.assertIn("&lt;", self.gv.render_cheatsheet_html("<script>") or "&lt;", "the query is escaped")


if __name__ == "__main__":
    unittest.main()
