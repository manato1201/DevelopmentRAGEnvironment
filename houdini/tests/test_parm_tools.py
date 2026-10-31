"""get_parm_schema / try_parameter / validate_network（houdini_tools.py）のテスト。標準の unittest。
Houdini は使わず、hou の代わりに最小の偽物（ノード・パラメータ・テンプレート）で動かす。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import sys
import threading
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import houdini_tools as ht  # noqa: E402
import tutorial_review as tr  # noqa: E402


class Kind(str):
    def name(self) -> str:
        return str(self)


class Template:
    def __init__(self, name, label, type_name, default=0, lo=0, hi=10, items=(), labels=(), n=1, hidden=False, children=()):
        self._a = dict(name=name, label=label, type=Kind(type_name), default=default, lo=lo, hi=hi,
                       items=list(items), labels=list(labels), n=n, hidden=hidden, children=list(children))

    def type(self): return self._a["type"]
    def name(self): return self._a["name"]
    def label(self): return self._a["label"]
    def numComponents(self): return self._a["n"]
    def defaultValue(self):
        value = self._a["default"]
        if isinstance(value, tuple) or self._a["type"] in ("Menu", "Toggle"):
            return value
        return (value,)  # hou は 1成分でもタプルで返す
    def minValue(self): return self._a["lo"]
    def maxValue(self): return self._a["hi"]
    def menuItems(self): return self._a["items"]
    def menuLabels(self): return self._a["labels"]
    def isHidden(self): return self._a["hidden"]
    def parmTemplates(self): return self._a["children"]
    def dataType(self): return {"Int": "int", "Float": "float"}.get(str(self._a["type"]), "string")
    def stringType(self): return self._a.get("string_type")
    def clone(self):
        import copy

        twin = Template.__new__(Template)
        twin._a = copy.deepcopy(self._a)
        return twin

    def setName(self, name): self._a["name"] = name
    def setLabel(self, label): self._a["label"] = label
    def setDefaultValue(self, value): self._a["default"] = value


class Parm:
    def __init__(self, tpl, value, keyframed=False):
        self._tpl, self.value, self._kf = tpl, value, keyframed

    def name(self): return self._tpl.name()
    def eval(self): return self.value
    def set(self, v): self.value = v
    def keyframes(self): return [object()] if self._kf else []
    def parmTemplate(self): return self._tpl
    def setExpression(self, expression, language=None): self.expression = expression
    def tuple(self): return getattr(self, "_tuple", None) or ParmTuple([self], self._tpl)
    def pressButton(self):
        self.pressed = getattr(self, "pressed", 0) + 1
        if getattr(self, "on_press", None):
            self.on_press()


class StringParm(Parm):
    """$HIP を含む文字列。eval() は展開後、unexpandedString() は書いたまま。"""

    def eval(self): return self.value.replace("$HIP", "C:/proj")
    def unexpandedString(self): return self.value


class ParmTuple:
    """hou.ParmTuple の代わり: 成分のパラメータを並べ、まとめて set できる。"""

    def __init__(self, parms, tpl=None):
        self._parms = list(parms)
        self._tpl = tpl

    def name(self): return self._tpl.name() if self._tpl is not None else self._parms[0].name()
    def parmTemplate(self): return self._tpl if self._tpl is not None else self._parms[0].parmTemplate()
    def __iter__(self): return iter(self._parms)
    def __len__(self): return len(self._parms)
    def set(self, values):
        for parm, value in zip(self._parms, values):
            parm.set(value)


class Group:
    """hou.ParmTemplateGroup の代わり。"""

    def __init__(self, templates): self._t = list(templates)
    def entries(self): return list(self._t)
    def append(self, template): self._t.append(template)


class Geo:
    def __init__(self, points, prims=0, size=(1.0, 1.0, 1.0)):
        self.points, self.prims, self.size = points, prims, size

    def intrinsicValue(self, key): return self.points if key == "pointcount" else self.prims
    def boundingBox(self): return types.SimpleNamespace(sizevec=lambda: self.size)


class Node:
    def __init__(self, path, type_name="box", category="Sop"):
        self._path, self._type, self._cat = path, type_name, category
        self._parms: dict[str, Parm] = {}
        self._tuples: dict[str, list[Parm]] = {}
        self._tpls: list[Template] = []
        self.parent_node = None
        self.kids: list["Node"] = []
        self.out: list["Node"] = []
        self.errs: list[str] = []
        self.warns: list[str] = []
        self.cooks = 0
        self.geo_fn = lambda: Geo(0)
        self.laid_out = 0
        self.display_set = False
        self._tuple_tpls: dict[str, Template] = {}

    def add_parm(self, tpl, value, keyframed=False, top=True):
        parm = Parm(tpl, value, keyframed)
        self._parms[tpl.name()] = parm
        if top:
            self._tpls.append(tpl)
        return parm

    def add_tuple(self, tpl, values):
        comps = [Parm(Template(f"{tpl.name()}{'xyz'[i]}", tpl.label(), str(tpl.type())), v) for i, v in enumerate(values)]
        pt = ParmTuple(comps, tpl)
        for comp in comps:
            comp._tuple = pt
            self._parms[comp.name()] = comp
        self._tuples[tpl.name()] = comps
        if tpl not in self._tpls:
            self._tpls.append(tpl)

    def path(self): return self._path
    def name(self): return self._path.rsplit("/", 1)[-1]
    def type(self): return types.SimpleNamespace(name=lambda: self._type, category=lambda: types.SimpleNamespace(name=lambda: self._cat))
    def parm(self, name): return self._parms.get(name)
    def parmTuple(self, name):
        if name in self._tuples:
            return ParmTuple(self._tuples[name], self._tuple_tpl(name))
        if name in self._parms and name not in self._comp_names():
            return ParmTuple([self._parms[name]], self._parms[name].parmTemplate())
        return None  # 実物は、単独のパラメータも長さ1のタプル
    def _comp_names(self): return {c.name() for comps in self._tuples.values() for c in comps}
    def _tuple_tpl(self, name):
        return next((t for t in self._tpls if t.name() == name), self._tuples[name][0].parmTemplate())

    def parms(self): return list(self._parms.values())
    def parmTemplateGroup(self): return Group(self._tpls)
    def setParmTemplateGroup(self, group):
        known = set(self._parms) | set(self._tuples)
        self._tpls = group.entries()
        for t in self._tpls:
            if t.name() in known or t.type() in ("Folder", "FolderSet"):
                continue
            default = t.defaultValue()
            default = default if isinstance(default, tuple) else (default,)
            if t._a["n"] > 1:
                self.add_tuple(t, default)
            else:
                self.add_parm(t, default[0], top=False)
    def children(self): return tuple(self.kids)
    def layoutChildren(self): self.laid_out += 1
    def relativePathTo(self, other):
        up = len(self._path.split("/")) - len(other.path().split("/"))
        return "/".join([".."] * up)
    def setDisplayFlag(self, on): self.display_set = on
    def setRenderFlag(self, on): pass
    def cook(self, force=False): self.cooks += 1
    def errors(self): return list(self.errs)
    def warnings(self): return list(self.warns)
    def geometry(self): return self.geo_fn()
    def outputs(self): return list(self.out)
    def parent(self): return self.parent_node
    def allSubChildren(self):
        out = []
        for k in self.kids:
            out.append(k)
            out.extend(k.allSubChildren())
        return out


SANDBOX = "/obj/ai_tutorial_1"


def make_world():
    hou = types.ModuleType("hou")
    hou.parmData = types.SimpleNamespace(Int="int", Float="float", String="string")
    hou.parmTemplateType = types.SimpleNamespace(Ramp="Ramp")
    hou.exprLanguage = types.SimpleNamespace(Hscript="hscript")
    hou.stringParmType = types.SimpleNamespace(FileReference="FileReference")
    hou._frame = [1.0]
    hou.frame = lambda: hou._frame[0]
    hou.setFrame = lambda f: hou._frame.__setitem__(0, f)
    nodes: dict[str, Node] = {}
    sandbox = Node(SANDBOX, "subnet", "Object")
    nodes[SANDBOX] = sandbox

    def add(rel, type_name="box", category="Sop", parent=None):
        node = Node(f"{SANDBOX}/{rel}", type_name, category)
        host = parent or sandbox
        node.parent_node = host
        host.kids.append(node)
        nodes[node.path()] = node
        return node

    hou.node = lambda path: nodes.get(path)
    return hou, sandbox, add, nodes


def make_executor(hou, sandbox):
    ex = ht.HoudiniToolExecutor.__new__(ht.HoudiniToolExecutor)
    ex._hou = hou
    ex.sandbox_path = SANDBOX
    ex.step_log = []
    ex.doc_client = None
    ex._log_path = None
    ex._lock = threading.Lock()
    ex.step_screenshots = []
    return ex


class ToolDefinitionTest(unittest.TestCase):
    def test_new_tools_are_listed_before_the_finishing_pair(self) -> None:
        names = [t["name"] for t in ht.HOUDINI_TOOLS]
        self.assertEqual(names[-2:], ["finish_tutorial", "confirm_tutorial"])
        for tool in ("get_parm_schema", "try_parameter", "validate_network"):
            self.assertIn(tool, names)
            self.assertLess(names.index(tool), names.index("finish_tutorial"))
        by_name = {t["name"]: t for t in ht.HOUDINI_TOOLS}
        self.assertEqual(by_name["try_parameter"]["input_schema"]["required"], ["node", "parm", "values"])
        self.assertEqual(by_name["validate_network"]["input_schema"]["properties"], {})
        self.assertEqual(len({t["name"] for t in ht.HOUDINI_TOOLS}), len(names), "tool names are unique")


class ParmSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.ex = make_executor(self.hou, self.sandbox)
        self.scatter = self.add("scatter1", "scatter::2.0")
        folder_inner = [
            Template("npts", "Force Total Count", "Int", default=1000, lo=0, hi=10000),
            Template("relax", "Relax Iterations", "Int", default=10, lo=0, hi=50),
        ]
        sub = Template("distribution", "Distribution", "Folder", children=folder_inner)
        self.scatter._tpls = []
        self.scatter.add_parm(folder_inner[0], 1000, top=False)
        self.scatter.add_parm(folder_inner[1], 10, top=False)
        self.scatter._tpls.append(Template("tabs", "", "FolderSet", children=[sub]))
        self.scatter.add_parm(Template("usedensity", "Use Density", "Toggle", default=False), 0)
        self.scatter.add_parm(Template("method", "Generate By", "Menu", default=0, items=["0", "1"], labels=["Random", "Poisson Disk"]), 0)
        self.scatter.add_tuple(Template("seedoffset", "Seed Offset", "Float", default=(0.0, 0.0, 0.0), lo=-1, hi=1, n=3), (0.0, 0.0, 0.0))
        self.scatter._tpls.append(Template("hidden1", "Hidden", "Float", hidden=True))
        self.scatter._tpls.append(Template("sep", "", "Separator"))
        self.scatter._tpls.append(Template("go", "Go", "Button"))

    def run_tool(self, **args) -> str:
        return self.ex._tool_get_parm_schema({"node": "scatter1", **args})

    def test_name_label_folder_default_range_and_current_value(self) -> None:
        out = self.run_tool()
        self.assertIn("全 5 件", out, "folders are walked; hidden / separator / button are not parameters")
        self.assertIn("npts  『Force Total Count』 int / 場所: Distribution / 既定 1000 / 範囲 0〜10000 / 現在 1000", out)
        self.assertIn("relax  『Relax Iterations』", out)
        self.assertNotIn("hidden1", out)
        self.assertNotIn("sep", out.replace("seedoffset", ""))
        self.assertNotIn("Go", out)

    def test_menu_choices_and_toggle(self) -> None:
        out = self.run_tool(filter="generate")
        self.assertIn("method  『Generate By』 menu", out)
        self.assertIn("選択肢 0=Random, 1=Poisson Disk", out)
        self.assertIn("'generate' に一致 1 件 / 全 5 件", out)

    def test_tuple_shows_components_and_current_tuple(self) -> None:
        out = self.run_tool(filter="seed")
        self.assertIn("seedoffset  『Seed Offset』 float3", out)
        self.assertIn("現在 (0, 0, 0)", out)

    def test_filter_without_match_and_limit(self) -> None:
        self.assertIn("一致するパラメータがありません（全 5 件）", self.run_tool(filter="zzz"))
        out = self.run_tool(limit=2)
        self.assertIn("他 3 件省略", out)
        self.assertEqual(out.count("\n  "), 2)

    def test_outside_the_sandbox_is_refused_like_every_tool(self) -> None:
        with self.assertRaises(ht.SandboxViolation):
            self.ex._tool_get_parm_schema({"node": "/obj/other"})


class TryParameterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        sys.modules["hou"] = self.hou  # _coerce_scalar は import hou する
        self.addCleanup(sys.modules.pop, "hou", None)
        self.ex = make_executor(self.hou, self.sandbox)
        self.scatter = self.add("scatter1", "scatter::2.0")
        self.npts = self.scatter.add_parm(Template("npts", "Count", "Int", default=100), 100)
        self.scatter.geo_fn = lambda: Geo(int(self.npts.value), 0, (2.0, 0.0, 2.0))
        self.merge = self.add("merge1", "merge")
        self.merge.geo_fn = lambda: Geo(int(self.npts.value) + 8, 1, (3.0, 1.0, 3.0))

    def run_tool(self, **args) -> str:
        return self.ex._tool_try_parameter({"node": "scatter1", "parm": "npts", "values": [10, 100, 1000], **args})

    def test_each_value_is_cooked_and_reported_then_the_original_is_restored(self) -> None:
        self.npts.value = 250
        out = self.run_tool()
        self.assertIn("値=10 → 点 10 / プリミティブ 0 / サイズ (2, 0, 2)", out)
        self.assertIn("値=1000 → 点 1000", out)
        self.assertIn("元の値 250", out)
        self.assertEqual(self.npts.value, 250, "the experiment leaves the parameter as it was")
        self.assertGreaterEqual(self.scatter.cooks, 4, "one cook per value plus one after restoring")

    def test_observe_another_node(self) -> None:
        out = self.run_tool(observe="merge1")
        self.assertIn("結果を見たノード: merge1", out)
        self.assertIn("値=10 → 点 18 / プリミティブ 1 / サイズ (3, 1, 3)", out)

    def test_errors_are_reported_per_value_and_do_not_stop_the_rest(self) -> None:
        self.scatter.errs = []
        original_cook = self.scatter.cook

        def cook(force=False):
            original_cook(force)
            self.scatter.errs = ["Invalid point count"] if self.npts.value == 0 else []

        self.scatter.cook = cook
        out = self.run_tool(values=[0, 50])
        self.assertIn("値=0 → エラー: Invalid point count", out)
        self.assertIn("値=50 → 点 50", out)
        self.assertEqual(self.npts.value, 100)

    def test_restores_even_when_setting_a_value_raises(self) -> None:
        real_set = self.npts.set

        def set_value(v):
            if v == 999:
                raise RuntimeError("bad")
            real_set(v)

        self.npts.set = set_value
        with self.assertRaises(RuntimeError):
            self.run_tool(values=[5, 999])
        self.assertEqual(self.npts.value, 100, "the first value was undone by the finally block")

    def test_value_count_is_validated(self) -> None:
        self.assertIn("2〜5 個", self.run_tool(values=[1]))
        self.assertIn("2〜5 個", self.run_tool(values=list(range(6))))
        self.assertIn("2〜5 個", self.run_tool(values="10 20"))
        self.assertEqual(self.npts.value, 100)

    def test_refused_when_it_cannot_restore_or_would_be_slow(self) -> None:
        self.scatter.add_parm(Template("animated", "Animated", "Float"), 1.0, keyframed=True)
        self.assertIn("式かキーフレーム", self.run_tool(parm="animated"))
        self.scatter.add_parm(Template("ramp1", "Ramp", "Ramp"), 0)
        self.assertIn("ランプ", self.run_tool(parm="ramp1"))
        pyro = self.add("pyrosolver1", "pyrosolver::2.0", "Dop")
        pyro.add_parm(Template("res", "Res", "Float"), 1.0)
        out = self.ex._tool_try_parameter({"node": "pyrosolver1", "parm": "res", "values": [1, 2]})
        self.assertIn("シミュレーション系", out)
        self.assertIn("見つかりません", self.run_tool(parm="nope"))

    def test_string_parameter_is_restored_unexpanded(self) -> None:
        tpl = Template("file", "File", "String", default="")
        parm = StringParm(tpl, "$HIP/geo/a.bgeo")
        self.scatter._parms["file"] = parm
        self.scatter._tpls.append(tpl)
        out = self.run_tool(parm="file", values=["x.bgeo", "y.bgeo"])
        self.assertIn("値=x.bgeo → 点", out)
        self.assertEqual(parm.value, "$HIP/geo/a.bgeo", "the raw text ($HIP) is put back, not the expanded path")
        self.assertIn("元の値 $HIP/geo/a.bgeo", out)

    def test_tuple_parameter(self) -> None:
        self.scatter.add_tuple(Template("size", "Size", "Float", n=3), (1.0, 1.0, 1.0))
        out = self.run_tool(parm="size", values=["1 1 1", "2 2 2", "3 3"])
        self.assertIn("値=2 2 2 → 点 100", out)
        self.assertIn("値=3 3 → エラー: size は 3 成分です", out)
        self.assertEqual([p.value for p in self.scatter._tuples["size"]], [1.0, 1.0, 1.0], "restored")

    def test_execute_runs_it_as_a_normal_tool_and_the_review_counts_it(self) -> None:
        out, is_error = self.ex.execute("try_parameter", {"node": "scatter1", "parm": "npts", "values": [10, 20]})
        self.assertFalse(is_error)
        self.assertEqual(tr.count_verified_experiments(self.ex.step_log), 1)
        bad = [{"tool": "try_parameter", "is_error": False, "result": "値=0 → エラー: x"}]
        self.assertEqual(tr.count_verified_experiments(bad), 0, "a run whose values all failed is not an experiment")
        self.assertEqual(tr.count_verified_experiments([{"tool": "try_parameter", "is_error": True, "result": "x"}]), 0)


class ValidateNetworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.ex = make_executor(self.hou, self.sandbox)
        self.geo = self.add("geo1", "geo", "Object")
        self.box = self.add("geo1/box1", "box", "Sop", parent=self.geo)
        self.xform = self.add("geo1/xform1", "xform", "Sop", parent=self.geo)
        self.box.out = [self.xform]

    def test_a_single_chain_is_ok(self) -> None:
        out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証OK"), out)
        self.assertIn("ノード 3 個", out)

    def test_multiple_ends_are_reported_with_the_fix(self) -> None:
        extra = self.add("geo1/sphere1", "sphere", "Sop", parent=self.geo)
        out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証NG"), out)
        self.assertIn("geo1 の中で末端が2個あります（geo1/xform1, geo1/sphere1）", out)
        self.assertIn("Merge", out)
        self.box.out.append(extra)  # 結んでも、末端は xform1 と sphere1 のまま
        extra.out = [self.xform]
        self.assertTrue(self.ex._tool_validate_network({}).startswith("検証OK"))

    def test_sop_networks_inside_dop_solvers_are_not_flagged(self) -> None:
        solver = self.add("geo1/sopsolver1", "sopsolver", "Dop", parent=self.geo)
        self.add("geo1/sopsolver1/prev_frame", "null", "Sop", parent=solver)
        self.add("geo1/sopsolver1/input1", "null", "Sop", parent=solver)
        out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証OK"), out)

    def test_errors_and_warnings_are_listed_and_sims_are_not_cooked(self) -> None:
        self.xform.errs = ["Input geometry is empty"]
        self.box.warns = ["Unused parameter"]
        solver = self.add("geo1/pyrosolver1", "pyrosolver::2.0", "Sop", parent=self.geo)
        solver.out = [self.xform]
        out = self.ex._tool_validate_network({})
        self.assertIn("[エラー] geo1/xform1: Input geometry is empty", out)
        self.assertIn("[警告] geo1/box1: Unused parameter", out)
        self.assertEqual(solver.cooks, 0, "simulation nodes are not cooked here")
        self.assertGreaterEqual(self.box.cooks, 1)

    def test_empty_sandbox(self) -> None:
        self.sandbox.kids.clear()
        self.assertIn("検証NG", self.ex._tool_validate_network({}))


class PromptTest(unittest.TestCase):
    def test_system_prompt_tells_the_model_about_the_new_tools(self) -> None:
        try:
            import tutorial_agent
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(str(exc)) from exc
        template = tutorial_agent._SYSTEM_PROMPT_TEMPLATE
        for word in ("get_parm_schema", "try_parameter", "validate_network"):
            self.assertIn(word, template)
        self.assertIn("get_parm_schema", tutorial_agent._LOOKUP_TOOLS, "repeated lookups count toward the 'stop researching' nudge")
        import lesson_design
        self.assertIn("try_parameter", lesson_design.TEACHING_RULES, "the teaching rules and the system prompt agree on how to run experiments")


if __name__ == "__main__":
    unittest.main()
