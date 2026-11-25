"""第 2 回の実証実験（2026-11-24・25）から足した修正のテスト（修正リストの A14〜A21。Houdini は偽物）。

  ・A14 手順書の不足: DOP の出力（file_output）のつなぎ忘れ・Tab メニューに出ないノードを、検証と提出で見つける
  ・A15 先につなぐ: つなぐ手順を、両端のノードができた直後へ移す（手順の数は変えない）
  ・A16〜A18 Guide: お手本／自分の切り替え、作業場所に戻る、この手順を Chat に聞く
  ・A19 ショートカット: パスを入れる欄の手順に、パスを貼る・落とすキー
  ・A20 用語をダブルクリックして、Reference で探す
  ・A21 プリセットのメニュー（Pyro Source の Initialize など）: 選ぶと、表示が先頭に戻る
実機（hython 22.0.506）でも、参加者の .hipnc で確かめた（修正リストの G）。
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))
sys.modules.setdefault("hou", types.ModuleType("hou"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import guide_mode as gm  # noqa: E402
import guide_shortcuts as gs  # noqa: E402
import houdini_tools as ht  # noqa: E402
import question_hints as qh  # noqa: E402
from guide_fakes import FakeTemplate, make_world  # noqa: E402
from test_parm_tools import make_executor, make_world as make_tool_world  # noqa: E402


# ── A14: 手順書が足りなくなる作り ─────────────────────────────────────────────

class _Type:
    def __init__(self, name, hidden=False, deprecated=False, new=None):
        self._n, self._h, self._d, self._new = name, hidden, deprecated, new

    def name(self): return self._n
    def description(self): return self._n.replace("_", " ").title()
    def category(self): return types.SimpleNamespace(name=lambda: "Dop")
    def hidden(self): return self._h
    def deprecated(self): return self._d
    def deprecationInfo(self): return {"new_type": self._new} if self._new else {}


class _Node:
    def __init__(self, path, type_obj, kids=()):
        self._p, self._t, self.kids, self.ins, self.outs, self.shown = path, type_obj, list(kids), [], [], None

    def path(self): return self._p
    def name(self): return self._p.rsplit("/", 1)[-1]
    def type(self): return self._t
    def children(self): return tuple(self.kids)
    def inputs(self): return tuple(self.ins)
    def outputs(self): return list(self.outs)
    def displayNode(self): return self.shown


def _wire(a, b):
    a.outs.append(b)
    b.ins.append(a)


class StructureIssuesTest(unittest.TestCase):
    def setUp(self) -> None:
        hou, sandbox, add, _nodes = make_tool_world()
        self.ex = make_executor(hou, sandbox)
        add("box1", "box", "Sop")  # 検証が「ノードが無い」で止まらないように
        sb = self.ex.sandbox_path
        self.output = _Node(f"{sb}/geo1/sim/file_output", _Type("output"))
        self.solver = _Node(f"{sb}/geo1/sim/solver", _Type("rbdsolver"))
        self.obj = _Node(f"{sb}/geo1/sim/pieces", _Type("rbdobject"))
        _wire(self.obj, self.solver)
        self.dop = _Node(f"{sb}/geo1/sim", _Type("dopnet"), [self.output, self.obj, self.solver])
        self.dop.shown = self.output

    def test_an_unconnected_output_dop_is_reported_with_the_fix(self) -> None:
        issues = self.ex._structure_issues([self.dop, self.output, self.solver, self.obj])
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("[シミュレーション] geo1/sim", issues[0])
        self.assertIn("シミュレーションは空", issues[0])
        self.assertIn("geo1/sim/solver を connect_nodes で geo1/sim/file_output の入力 0", issues[0])

    def test_a_connected_output_is_fine(self) -> None:
        _wire(self.solver, self.output)
        self.assertEqual(self.ex._structure_issues([self.dop, self.output, self.solver, self.obj]), [])

    def test_a_dangling_solver_beside_another_display_is_a_wiring_issue(self) -> None:
        self.dop.shown = self.solver  # 表示はソルバー。file_output は、つながっていない末端として残る
        issues = self.ex._structure_issues([self.dop])
        self.assertEqual(len(issues), 1)
        self.assertIn("[つなぎ] geo1/sim の中で末端が2個", issues[0])

    def test_a_node_hidden_from_the_tab_menu_names_the_replacement(self) -> None:
        old = _Node(f"{self.ex.sandbox_path}/geo1/sim/smoke", _Type("smokeobject", True, True, _Type("smokeobject_sparse")))
        issues = self.ex._structure_issues([old])
        self.assertEqual(len(issues), 1)
        self.assertIn("[Tab に出ない] geo1/sim/smoke", issues[0])
        self.assertIn("代わりに smokeobject_sparse", issues[0])
        self.assertEqual(ht.HoudiniToolExecutor._tab_hidden_note(_Type("box")), "")
        self.assertEqual(ht.HoudiniToolExecutor._tab_hidden_note(types.SimpleNamespace(name=lambda: "x")), "", "fakes without hidden() are fine")

    def test_validate_network_includes_the_structure_check(self) -> None:
        with mock.patch.object(ht.HoudiniToolExecutor, "_structure_issues", return_value=["[シミュレーション] x: 空"]):
            out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証NG"), out)
        self.assertIn("[シミュレーション] x: 空", out)

    def test_finish_is_held_back_while_the_structure_is_broken(self) -> None:
        ex = self.ex
        ex._finish_drafts, ex._pending_finish = [], None
        with mock.patch.object(ht.HoudiniToolExecutor, "_structure_issues", return_value=["[シミュレーション] geo1/sim: 空です"]), \
                mock.patch.object(ht.tutorial_review, "finish_gap_message", return_value=""), \
                mock.patch.object(ht.tutorial_review, "fidelity_gaps", return_value=[]), \
                mock.patch.object(ht.tutorial_review, "phantom_message", return_value=""), \
                mock.patch.object(ht.tutorial_review, "topic_unmet", return_value=[]), \
                mock.patch.object(ht.tutorial_review, "topic_gap_message", return_value=""):
            out = ex._tool_finish_tutorial({"title": "t", "steps": "s"})
        self.assertIn("まだ確定していません", out)
        self.assertIn("【手順書が足りなくなる作り】", out)
        self.assertIn("geo1/sim: 空です", out)


# ── A15: つなぐ手順を先に ──────────────────────────────────────────────────

def _create(name):
    return {"tool": "create_node", "node": name, "node_path": f"g/{name}"}


def _parm(name):
    return {"tool": "set_parameter", "node": name, "node_path": f"g/{name}"}


def _connect(*pairs):
    return {"tool": "connect_nodes", "node": pairs[-1][1], "from": pairs[0][0], "to": pairs[-1][1],
            "connections": [{"from": a, "to": b} for a, b in pairs]}


class ConnectEarlyTest(unittest.TestCase):
    def order(self, steps):
        return [(s["tool"].split("_")[0], s.get("node")) for s in gm.connect_early(steps)]

    def test_a_connection_moves_right_after_both_ends_exist(self) -> None:
        steps = [_create("a"), _create("b"), _parm("a"), _parm("b"), _connect(("a", "b"))]
        self.assertEqual(self.order(steps), [("create", "a"), ("create", "b"), ("connect", "b"), ("set", "a"), ("set", "b")])

    def test_grouped_connections_stay_one_step_after_the_last_end(self) -> None:
        steps = [_create("a"), _create("b"), _parm("a"), _create("c"), _parm("c"), _connect(("a", "b"), ("b", "c"))]
        out = gm.connect_early(steps)
        self.assertEqual(len(out), len(steps), "the number of steps does not change")
        self.assertEqual([s["tool"] for s in out][3:5], ["create_node", "connect_nodes"])
        self.assertEqual(len(out[4]["connections"]), 2)

    def test_connection_order_is_kept_and_nothing_moves_later(self) -> None:
        steps = [_create("a"), _create("b"), _create("m"), _parm("m"), _connect(("b", "m")), _connect(("a", "m"))]
        out = gm.connect_early(steps)
        connects = [s["from"] for s in out if s["tool"] == "connect_nodes"]
        self.assertEqual(connects, ["b", "a"], "merge input order is not swapped")
        self.assertLess(out.index(steps[4]), out.index(steps[3]))

    def test_ends_not_created_in_the_steps_use_the_other_end(self) -> None:
        steps = [_create("sim"), _create("solver"), _parm("solver"), _connect(("solver", "file_output"))]
        self.assertEqual(self.order(steps)[2], ("connect", "file_output"))

    def test_running_twice_changes_nothing(self) -> None:
        steps = [_create("a"), _parm("a"), _create("b"), _parm("b"), _connect(("a", "b"))]
        once = gm.connect_early(steps)
        self.assertEqual(gm.connect_early(once), once)

    def test_a_recreated_node_uses_its_latest_creation(self) -> None:
        steps = [_create("a"), _create("b"), {"tool": "delete_node", "node": "b"}, _parm("a"), _create("b"), _parm("a"), _connect(("a", "b"))]
        out = gm.connect_early(steps)
        self.assertEqual(out.index(steps[6]), 5, "after the second creation of b, not the first")


# ── A16・A17: お手本／自分、作業場所に戻る ───────────────────────────────────

class PlaceTest(unittest.TestCase):
    def test_the_own_workplace_is_remembered_and_restored(self) -> None:
        world = make_world({"/obj/pyro_geo/sphere1": "sphere", "/obj/ai_tutorial_1/geo1/sphere1": "sphere"}, pwd="/obj/pyro_geo")
        world.nodes["/obj/pyro_geo/sphere1"].selected = True
        place = gm.remember_place(world.hou)
        self.assertEqual(place, {"network": "/obj/pyro_geo", "selected": ["/obj/pyro_geo/sphere1"]})
        world.editor.setPwd(world.nodes["/obj/ai_tutorial_1/geo1"])  # Guide が、お手本へ動かした
        world.nodes["/obj/pyro_geo/sphere1"].selected = False
        message = gm.return_to_place(world.hou, place)
        self.assertIn("作業場所に戻りました: /obj/pyro_geo", message)
        self.assertEqual(world.editor.pwd().path(), "/obj/pyro_geo")
        self.assertTrue(world.nodes["/obj/pyro_geo/sphere1"].selected)

    def test_the_sandbox_and_obj_are_not_workplaces(self) -> None:
        for pwd in ("/obj", "/obj/ai_tutorial_1/geo1"):
            world = make_world({"/obj/ai_tutorial_1/geo1/a": "null"}, pwd=pwd)
            self.assertIsNone(gm.remember_place(world.hou), pwd)

    def test_nothing_to_return_to_and_a_deleted_place(self) -> None:
        world = make_world({"/obj/mine/a": "null"}, pwd="/obj")
        self.assertIn("戻る場所がまだありません", gm.return_to_place(world.hou, None))
        self.assertIn("見つかりません", gm.return_to_place(world.hou, {"network": "/obj/gone", "selected": []}))


# ── A18: この手順を Chat に聞く ──────────────────────────────────────────────

class StepQuestionTest(unittest.TestCase):
    def test_the_stuck_question_asks_for_how_and_what_to_check(self) -> None:
        step = {"index": 4, "title": "壊れる箱", "instruction": "rbd_sim の中に Bullet Solver を作る", "purpose": "破片を落とす"}
        text = qh.guide_step_question(step, stuck=True)
        self.assertIn("「壊れる箱」の手順 5", text)
        self.assertIn("作業: rbd_sim の中に Bullet Solver を作る", text)
        self.assertIn("目的: 破片を落とす", text)
        self.assertIn("詰まっています", text)
        self.assertIn("うまくいかないときに確かめること", text)
        self.assertNotIn("詰まっています", qh.guide_step_question(step))

    def test_a_step_without_an_instruction_names_the_node(self) -> None:
        self.assertIn("ノード: Box", qh.guide_step_question({"node_label": "Box"}))


# ── A19: パスを貼る・落とすキー ──────────────────────────────────────────────

class PathShortcutTest(unittest.TestCase):
    def test_path_keys_come_first_only_for_path_parameters(self) -> None:
        with_path = [s["keys"] for s in gs.for_step("set_parameter", path=True)]
        self.assertIn("Ctrl + C", with_path[0])
        self.assertIn("ドラッグ", with_path[1])
        plain = [s["keys"] for s in gs.for_step("set_parameter")]
        self.assertFalse(any("Ctrl + C" in k for k in plain))
        self.assertEqual(gs.for_step("connect_nodes", path=True), gs.for_step("connect_nodes"))

    def test_the_guide_adds_them_for_sop_path_parameters(self) -> None:
        record = [{"step": 1, "tool": "set_parameter", "result": "x",
                   "guide": {"node": "pieces", "node_path": "sim/pieces", "parms": [{"name": "soppath", "label": "SOP Path", "new": "/obj/g/out"}]}},
                  {"step": 2, "tool": "set_parameter", "result": "y",
                   "guide": {"node": "box1", "node_path": "g/box1", "parms": [{"name": "sizex", "label": "Size", "new": "2"}]}}]
        steps = gm.build_guide(record)["steps"]
        self.assertIn("Ctrl + C", steps[0]["shortcuts"][0]["keys"])
        self.assertFalse(any("Ctrl + C" in s["keys"] for s in steps[1]["shortcuts"]))


# ── A21: プリセットのメニュー ───────────────────────────────────────────────

class _PresetTemplate(FakeTemplate):
    def scriptCallback(self): return 'hou.node(".").hdaModule().set()'


INIT = _PresetTemplate("initialize", "Initialize", "Menu", items=("none", "sourceburn", "source"), labels=("Initialize\t↓", "Source Burn", "Source Smoke"))


class PresetMenuTest(unittest.TestCase):
    def test_a_preset_menu_is_recognized(self) -> None:
        self.assertTrue(gm.parm_value_info(INIT)["preset"])
        plain = FakeTemplate("class", "Run Over", "Menu", items=("points", "detail"), labels=("Points", "Detail"))
        self.assertFalse(gm.parm_value_info(plain)["preset"], "no callback")

    def test_the_guide_says_the_menu_goes_back_and_that_is_normal(self) -> None:
        d = gm.describe_parm_change({"label": "Initialize", "name": "initialize", "old": "0", "new": "2"}, gm.parm_value_info(INIT))
        self.assertEqual(d["kind"], "preset")
        self.assertIn("メニューから「Source Smoke」を選ぶ", d["action"])
        self.assertIn("「Initialize ↓」に戻ります。戻っても正常です", d["action"])
        self.assertEqual(d["old_text"], "Initialize ↓")

    def test_the_generator_runs_the_preset_like_the_ui_does(self) -> None:
        hou, sandbox, add, _nodes = make_tool_world()
        ex = make_executor(hou, sandbox)
        node = add("g/src", "pyrosource")
        values = {"initialize": "none", "attributes": "0"}

        class P:
            def __init__(self, name): self._n = name
            def name(self): return self._n
            def evalAsString(self): return values[self._n]
            def eval(self): return values[self._n]
            def set(self, v): values[self._n] = {0: "none", 2: "source"}.get(v, str(v))
            def parmTemplate(self): return INIT
            def isAtDefault(self): return False
            def pressButton(self):  # Houdini: スクリプトが、ほかの欄を変え、メニューを先頭に戻す
                values["attributes"] = "2"
                values["initialize"] = "none"

        parms = {"initialize": P("initialize"), "attributes": P("attributes")}
        node.parm = parms.get
        node.parms = lambda: list(parms.values())
        with mock.patch.object(ht.HoudiniToolExecutor, "_resolve", lambda self, path: node):
            out = ex._tool_set_parameter({"node": "g/src", "parm": "initialize", "value": 2})
        self.assertIn("プリセットのメニュー", out)
        self.assertIn("変わった欄: attributes", out)
        self.assertEqual(values["attributes"], "2")
        self.assertTrue(ex._last_parm_change["menu_info"]["preset"])


# ── Qt の画面: Guide のボタン・Chat への質問・用語の検索 ──────────────────────

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class GuideButtonsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        import guide_view

        self.gv = guide_view
        state: dict = {}
        for patch in (mock.patch.object(guide_view, "_state_get", lambda key, default=None: state.get(key, default)),
                      mock.patch.object(guide_view, "_state_set", lambda key, value: state.__setitem__(key, value))):
            patch.start()
            self.addCleanup(patch.stop)
        self.world = make_world({"/obj/mine/box1": "box", "/obj/ai_tutorial_1/g/box1": "box"}, pwd="/obj/mine")
        hou_patch = mock.patch.object(guide_view, "hou", self.world.hou)
        hou_patch.start()
        self.addCleanup(hou_patch.stop)
        self.widget = guide_view.GuideWidget(lambda: {})
        self.addCleanup(self.widget.deleteLater)
        self.widget._guide = {"title": "箱", "sandbox_path": "/obj/ai_tutorial_1",
                              "steps": [{"tool": "set_parameter", "node": "box1", "node_path": "g/box1", "instruction": "box1 の Size を 2 にする"}]}
        self.widget._index = 0
        self.widget._set_enabled(True)

    def test_example_and_mine_use_their_own_mode_once(self) -> None:
        with mock.patch.object(self.gv.guide_mode, "apply_step", return_value=["ok"]) as applied:
            self.widget._example_btn.click()
            self.widget._mine_btn.click()
            self.widget._apply_btn.click()
        self.assertEqual([c.args[3] for c in applied.call_args_list], ["sandbox", "own", "auto"])

    def test_the_workplace_before_a_jump_can_be_returned_to(self) -> None:
        with mock.patch.object(self.gv.guide_mode, "apply_step",
                               side_effect=lambda h, *a: (self.world.editor.setPwd(self.world.nodes["/obj/ai_tutorial_1/g"]), ["moved"])[1]):
            self.widget._example_btn.click()
        self.assertEqual(self.world.editor.pwd().path(), "/obj/ai_tutorial_1/g")
        self.widget._home_btn.click()
        self.assertEqual(self.world.editor.pwd().path(), "/obj/mine")
        self.assertIn("作業場所に戻りました", self.widget._status.text())

    def test_ask_chat_goes_to_the_panel(self) -> None:
        panel = mock.Mock()
        panel.ask_chat.return_value = "Chat タブで質問しました"
        with mock.patch("panel_bus.panel_of", return_value=panel):
            self.widget._ask_btn.click()
        query = panel.ask_chat.call_args.args[0]
        self.assertIn("作業: box1 の Size を 2 にする", query)
        self.assertIn("詰まっています", query)
        self.assertIn("Chat タブで質問しました", self.widget._status.text())
        with mock.patch("panel_bus.panel_of", return_value=None):
            self.widget._ask_btn.click()
        self.assertIn("Chat タブが見つかりません", self.widget._status.text())


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class ChatAskAndLookupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_ask_chat_switches_to_chat_and_sends(self) -> None:
        import tempfile

        import panel_widgets
        import rag_chatbot as rc
        from test_panel_nav import _SilentWorker

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"mode": "cloudflare", "cf_url": "", "cf_api_key": "", "cf_namespaces": "", "local_port": 8766,
               "local_bridge_dir": str(Path(tmp.name) / "data"), "llm_backend": "claude"}
        for patch in (mock.patch.object(rc, "_load_config", lambda: dict(cfg)), mock.patch.object(rc, "_save_config", lambda c: None),
                      mock.patch.object(rc, "_ui_state_get", lambda key, default=None: default),
                      mock.patch.object(rc, "_ui_state_set", lambda key, value: None),
                      mock.patch.object(panel_widgets, "_STATE_PATH", Path(tmp.name) / "ui.json"),
                      mock.patch.object(rc, "_ConnectionCheckWorker", _SilentWorker)):
            patch.start()
            self.addCleanup(patch.stop)
        panel = rc.RAGChatbotPanel()
        self.addCleanup(panel.deleteLater)
        panel._tabs.setCurrentIndex(panel._tabs.count() - 1)
        sent = []
        with mock.patch.object(type(panel), "_on_send", lambda self: sent.append(self._input.toPlainText())):
            message = panel.ask_chat("手順 3 で詰まっています")
        self.assertEqual(sent, ["手順 3 で詰まっています"])
        self.assertEqual(panel._tabs.currentIndex(), panel._chat_tab_idx)
        self.assertIn("Chat タブで質問しました", message)

    def test_a_double_clicked_word_is_searched_in_the_reference(self) -> None:
        import reference_view as rv
        from PySide6.QtWidgets import QLabel

        label = QLabel("Scatter ノードで点を置きます")
        self.addCleanup(label.deleteLater)
        messages = []
        lookup = rv.TermLookup.install(label, messages.append)
        with mock.patch.object(rv.TermLookup, "selected_text", staticmethod(lambda w: "Scatter")), \
                mock.patch.object(rv, "search_term", return_value="Reference で「Scatter」を開きました") as searched:
            lookup._lookup(label)
        searched.assert_called_once_with(label, "Scatter")
        self.assertEqual(messages, ["Reference で「Scatter」を開きました"])
        with mock.patch.object(rv.TermLookup, "selected_text", staticmethod(lambda w: "")), mock.patch.object(rv, "search_term") as searched:
            lookup._lookup(label)
        searched.assert_not_called()

    def test_search_term_picks_the_first_kind_with_hits(self) -> None:
        import reference_view as rv

        widget = mock.Mock()
        widget.SEARCH_KINDS = rv.ReferenceWidget.SEARCH_KINDS
        widget._remote = {}
        hits = {"node": [], "vex": [{"kind": "vex", "key": "vex/noise", "label": "noise"}]}
        with mock.patch.object(rv.rd, "search", side_effect=lambda kind, term, **k: hits.get(kind, [])), \
                mock.patch.object(rv.rd, "remote_items", return_value=[]):
            message = rv.ReferenceWidget.search_term(widget, "「noise」")
        widget._set_kind_button.assert_called_with("vex")
        widget.show_item.assert_called_once_with("vex", "vex/noise", "noise")
        self.assertIn("noise", message)
        with mock.patch.object(rv.rd, "search", return_value=[]), mock.patch.object(rv.rd, "remote_items", return_value=[]):
            self.assertIn("見つかりませんでした", rv.ReferenceWidget.search_term(widget, "ほげ"))


if __name__ == "__main__":
    unittest.main()


class SandboxReferenceTest(unittest.TestCase):
    """A26: 自分のネットワークが、お手本のノードを指していたら知らせる（実証実験の h7 と同じ形）。"""

    def _parm(self, name, value):
        return types.SimpleNamespace(name=lambda: name, unexpandedString=lambda: value)

    def test_a_path_into_the_example_is_reported(self) -> None:
        world = make_world({"/obj/sim_result/rbd_sim": "dopnet", "/obj/sim_result/merge1": "merge",
                            "/obj/ai_tutorial_1/fracture/assemble": "assemble"}, pwd="/obj/sim_result")
        world.nodes["/obj/sim_result/rbd_sim"].parms = lambda: [self._parm("objname1", "*"),
                                                                 self._parm("soppath", "/obj/ai_tutorial_1/fracture/assemble")]
        world.nodes["/obj/sim_result/merge1"].parms = lambda: [self._parm("note", "")]
        found = gm.sandbox_references(world.hou)
        self.assertEqual(len(found), 1)
        self.assertIn("/obj/sim_result/rbd_sim の「soppath」が、お手本（/obj/ai_tutorial_1/fracture/assemble）を指しています", found[0])
        self.assertIn("Ctrl+C", found[0])

    def test_only_the_own_workplace_is_checked(self) -> None:
        world = make_world({"/obj/ai_tutorial_1/g/a": "null"}, pwd="/obj/ai_tutorial_1/g")
        self.assertEqual(gm.sandbox_references(world.hou), [])


class TextScaleTest(unittest.TestCase):
    """A24: 文字の大きさ（メニュー ≡ →「文字の大きさ」）。"""

    def test_the_scale_multiplies_every_type_size(self) -> None:
        import panel_actions as pa

        self.addCleanup(pa._TEXT_SCALE_CACHE.clear)
        real_get = pa.text_scale

        def fresh():  # 覚えた値を使わず、毎回読む（下で、読む値を差し替えるため）
            pa._TEXT_SCALE_CACHE.clear()
            return real_get()

        patcher = mock.patch.object(pa, "text_scale", fresh)
        patcher.start()
        self.addCleanup(patcher.stop)

        with mock.patch("panel_widgets.ui_state_get", lambda key, default=None: 1.3 if key == pa.TEXT_SCALE_KEY else default):
            self.assertIn("font-size:13.0pt", pa.type_qss("body"))
            self.assertIn("font-size:11.7pt", pa.pt_qss("font-size:12px;"))
        with mock.patch("panel_widgets.ui_state_get", lambda key, default=None: default):
            self.assertIn("font-size:10.0pt", pa.type_qss("body"))
        with mock.patch("panel_widgets.ui_state_get", lambda key, default=None: "壊れた値"):
            self.assertEqual(pa.text_scale(), 1.0)
        with mock.patch("panel_widgets.ui_state_get", lambda key, default=None: 9):
            self.assertEqual(pa.text_scale(), 2.0, "capped")


class TutorialModelMigrationTest(unittest.TestCase):
    """費用: 以前の既定（claude-sonnet-5。effort を送らない）のままの設定を、1 回だけ claude-sonnet-5-5 に移す。"""

    def test_the_old_default_moves_once_and_a_later_choice_is_kept(self) -> None:
        import rag_client as rcl
        import tutorial_agent as ta

        moved = rcl.migrate_config({"mode": "cloudflare", "tutorial_model": "claude-sonnet-5"})
        self.assertEqual(moved["tutorial_model"], "claude-sonnet-5-5")
        self.assertTrue(moved[rcl.MODEL_MIGRATION_KEY])
        chosen = rcl.migrate_config({**moved, "tutorial_model": "claude-sonnet-5"})  # 設定者が、あとで選び直した
        self.assertEqual(chosen["tutorial_model"], "claude-sonnet-5")
        other = rcl.migrate_config({"mode": "cloudflare", "tutorial_model": "claude-opus-5-5"})
        self.assertEqual(other["tutorial_model"], "claude-opus-5-5", "a deliberate non-default choice is kept")
        self.assertEqual(ta.DEFAULT_MODEL, rcl.DEFAULT_TUTORIAL_MODEL)
        self.assertEqual(ta.effort_for(ta.DEFAULT_MODEL), "medium", "the default model gets an effort")


class TextScaleCacheTest(unittest.TestCase):
    def test_the_state_file_is_read_once_until_it_is_set_again(self) -> None:
        import panel_actions as pa

        pa._TEXT_SCALE_CACHE.clear()
        self.addCleanup(pa._TEXT_SCALE_CACHE.clear)
        reads = []
        saved = {}
        with mock.patch("panel_widgets.ui_state_get", lambda key, default=None: reads.append(key) or saved.get(key, default)), \
                mock.patch("panel_widgets.ui_state_set", lambda key, value: saved.__setitem__(key, value)):
            for _ in range(50):
                pa.type_qss("body")
            self.assertEqual(len(reads), 1, "not once per call")
            pa.set_text_scale(1.5)
            self.assertIn("font-size:15.0pt", pa.type_qss("body"), "a new choice is used right away")
