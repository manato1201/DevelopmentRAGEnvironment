"""Guide の表記（2026-11-17 の指摘（3）（4））と、生成後の自動切り替えのテスト。Houdini は偽物（guide_fakes.py）。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_guide_display.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import guide_mode as gm  # noqa: E402
from guide_fakes import FakeTemplate, make_world  # noqa: E402

SANDBOX = "/obj/ai_tutorial_20261117_171700"

RUN_OVER = FakeTemplate("class", "Run Over", "Menu", items=("points", "prims", "detail"), labels=("Points", "Primitives", "Detail (only once)"))
ENABLE = FakeTemplate("enable", "Enable", "Toggle")
SIZE = FakeTemplate("size", "Size", "Float")

PARM_STEPS = [
    {"step": 1, "tool": "create_node", "result": "「Attribute Wrangle」ノード（attribwrangle）を作り、名前を vortex_points にする",
     "guide": {"node": "vortex_points", "node_path": "tornado/vortex_points", "node_type": "attribwrangle", "node_label": "Attribute Wrangle"}},
    {"step": 2, "tool": "set_parameter", "result": "vortex_points のパラメータを設定: Run Over を 2",
     "guide": {"node": "vortex_points", "node_path": "tornado/vortex_points", "node_type": "attribwrangle", "node_label": "Attribute Wrangle",
               "parms": [{"name": "class", "label": "Run Over", "old": "0", "new": "2", "where": "Sourcing > Emission"},
                         {"name": "enable", "label": "Enable", "old": "1", "new": "0", "where": ""},
                         {"name": "size", "label": "Size", "old": "1", "new": "4.5", "where": "Shape"}]}},
    {"step": 3, "tool": "delete_node", "result": "不要になった old_null を削除する", "guide": {"node": "old_null", "node_path": "tornado/old_null"}},
    {"step": 4, "tool": "connect_nodes", "result": "6本のノードをつなぐ: a → b、b → c ほか4本",
     "guide": {"node": "g", "node_path": "tornado/g", "from": "a", "to": "g",
               "connections": [{"from": f"n{i}", "to": f"n{i + 1}", "input": 0} for i in range(9)]}},
]

MD = """---
title: 炎の竜巻
---
## 概要
あ

## 作る前に: 使うノードと、できること

1. ctrl_seed / ctrl_temp（attribcreate）: 公開値を detail 属性として運ぶ「入口」
2. vortex_points（attribwrangle, detail）: 螺旋状に点を撒き v / density を付ける
3. pyrosolver1（SOP Pyro Solver）: 4つのソースを注入して燃焼計算

## 手順
...

## コード・ノード構成

サンドボックス: `/obj/ai_tutorial_20261117_171700`
"""


class ValueLabelTest(unittest.TestCase):
    def test_menu_value_is_told_by_its_label(self):
        info = gm.parm_value_info(RUN_OVER)
        d = gm.describe_parm_change({"name": "class", "label": "Run Over", "old": "0", "new": "2", "where": ""}, info)
        self.assertEqual(d["action"], "Run Over を Detail (only once) にする")
        self.assertIn("Detail (only once)", d["new_text"])
        self.assertIn("Points", d["old_text"], "the value before is also told by its label")

    def test_string_menu_uses_the_token(self):
        info = gm.parm_value_info(RUN_OVER)
        self.assertEqual(gm.menu_label_for(info, "prims"), "Primitives")

    def test_toggle_is_on_or_off_with_a_verb(self):
        info = gm.parm_value_info(ENABLE)
        off = gm.describe_parm_change({"name": "enable", "label": "Enable", "old": "1", "new": "0"}, info)
        self.assertEqual(off["action"], "Enable をオフにする（チェックを外す。無効にする）")
        self.assertEqual((off["old_text"], off["new_text"]), ("オン", "オフ"))
        on = gm.describe_parm_change({"name": "enable", "label": "Enable", "old": "0", "new": "1"}, info)
        self.assertIn("オンにする（チェックを入れる）", on["action"])

    def test_without_template_info_the_number_stays_a_number(self):
        d = gm.describe_parm_change({"name": "class", "label": "Run Over", "old": "0", "new": "2"}, None)
        self.assertEqual(d["action"], "Run Over を 2 にする")
        self.assertEqual(d["old_text"], "0")
        out_of_range = gm.describe_parm_change({"name": "class", "label": "Run Over", "old": "0", "new": "9"}, gm.parm_value_info(RUN_OVER))
        self.assertEqual(out_of_range["action"], "Run Over を 9 にする")

    def test_clearing_a_value_says_clear(self):
        d = gm.describe_parm_change({"name": "group", "label": "Group", "old": "grp1", "new": ""}, None)
        self.assertIn("空にする（入っている内容を消す）", d["action"])
        self.assertEqual(d["old_text"], "grp1")

    def test_code_parameters_do_not_copy_the_code(self):
        d = gm.describe_parm_change({"name": "snippet", "label": "VEXpression", "old": "", "new": "（コード。手順書を見る）"}, None)
        self.assertIn("手順書のコード", d["action"])

    def test_where_text(self):
        self.assertEqual(gm.parm_where_text("Sourcing > Emission"), "Sourcing > Emission")
        self.assertIn("タブの外", gm.parm_where_text(""))

    def test_template_info_is_read_from_the_node_or_the_node_type(self):
        templates = {"attribwrangle": [RUN_OVER, ENABLE, SIZE]}
        world = make_world({"/obj/tornado/vortex_points": "attribwrangle"}, pwd="/obj/tornado", templates=templates)
        step = gm.build_guide(PARM_STEPS)["steps"][1]
        out = gm.attach_parm_info(world.hou, step)
        self.assertEqual(out["parms"][0]["_info"]["kind"], "menu")
        self.assertEqual(out["parms"][1]["_info"]["kind"], "toggle")
        self.assertEqual(out["parms"][2]["_info"]["kind"], "other")
        self.assertNotIn("_info", step["parms"][0], "the recorded step is not modified")
        # ノードがまだ無い（学習者がまだ作っていない）ときは、ノードの種類から引く
        world = make_world({"/obj/dummy": "attribwrangle"}, pwd="/obj", templates=templates)
        out = gm.attach_parm_info(world.hou, step)
        self.assertEqual(out["parms"][0]["_info"]["kind"], "menu")
        self.assertEqual(gm.attach_parm_info(None, step)["parms"][0].get("_info"), None, "no Houdini: numbers are kept")


class PurposeTest(unittest.TestCase):
    def test_purposes_come_from_the_nodes_section_of_the_markdown(self):
        purposes = gm.purposes_from_markdown(MD)
        self.assertEqual(purposes["ctrl_seed"], "公開値を detail 属性として運ぶ「入口」")
        self.assertEqual(purposes["ctrl_temp"], purposes["ctrl_seed"])
        self.assertIn("螺旋状に点を撒き", purposes["vortex_points"])
        self.assertIn("燃焼計算", purposes["pyrosolver1"])
        self.assertEqual(gm.purposes_from_markdown("## 手順\n1. a: b"), {}, "no nodes section: nothing is guessed")

    def test_steps_carry_the_purpose_and_a_recorded_one_wins(self):
        guide = gm.build_guide(PARM_STEPS, purposes=gm.purposes_from_markdown(MD))
        self.assertIn("螺旋状", guide["steps"][0]["purpose"])
        self.assertEqual(guide["steps"][2]["purpose"], "", "a node without a purpose is left empty (reported, not invented)")
        recorded = [{"step": 1, "tool": "cook_node", "result": "x を評価", "guide": {"node": "vortex_points", "purpose": "記録された目的"}}]
        self.assertEqual(gm.build_guide(recorded, purposes={"vortex_points": "別"})["steps"][0]["purpose"], "記録された目的")

    def test_sandbox_and_purposes_are_read_back_for_older_guides(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "fire.md").write_text(MD, encoding="utf-8")
            gm.write_guide(tmp / "fire_guide.json", gm.build_guide(PARM_STEPS, "炎"))
            loaded = gm.load_guide(tmp / "fire_guide.json")
            self.assertEqual(loaded["sandbox_path"], SANDBOX)
            self.assertIn("螺旋状", loaded["steps"][0]["purpose"])

    def test_guide_from_result(self):
        result = types.SimpleNamespace(markdown=MD, sandbox_path=SANDBOX, step_screenshots=PARM_STEPS, title="炎の竜巻", level="applied")
        guide = gm.guide_from_result(result)
        self.assertEqual(guide["sandbox_path"], SANDBOX)
        self.assertEqual(len(guide["steps"]), 4)
        self.assertIn("螺旋状", guide["steps"][1]["purpose"])


class WordingTest(unittest.TestCase):
    def setUp(self):
        self.guide = gm.build_guide(PARM_STEPS, "炎", "applied", {"sandbox_path": SANDBOX}, gm.purposes_from_markdown(MD))
        self.steps = self.guide["steps"]

    def test_the_work_headline_says_which_part_is_worked_on(self):
        self.assertEqual(self.steps[0]["work"], "【作業する部分】/obj/tornado の中に、新しいノード「Attribute Wrangle」（名前: vortex_points）を作る")
        self.assertEqual(self.steps[1]["work"], "【作業する部分】/obj/tornado/vortex_points のパラメータを変える")

    def test_a_delete_step_says_delete(self):
        self.assertTrue(self.steps[2]["work"].startswith("【消す】/obj/tornado/old_null"))
        self.assertIn("【消す】", self.steps[2]["hint"])
        self.assertIn("削除", self.steps[2]["hint"])

    def test_nothing_is_cut_with_an_ellipsis(self):
        connect = self.steps[3]
        self.assertEqual(len(connect["connections"]), 9)
        for i in range(9):
            self.assertIn(f"n{i} → n{i + 1}", connect["instruction"])
            self.assertIn(f"n{i} → n{i + 1}", connect["hint"])
        self.assertNotIn("ほか", connect["instruction"] + connect["hint"])
        long_path = "tornado/" + "very_long_group_name/" * 6 + "node"
        step = gm.build_guide([{"step": 1, "tool": "cook_node", "result": "x", "guide": {"node": "node", "node_path": long_path}}])["steps"][0]
        self.assertIn(long_path, step["work"])

    def test_the_location_status(self):
        self.assertEqual(gm.location_status("/obj/a", "/obj/a"), ("いまのネットワーク: /obj/a（この手順の場所と同じ）", True))
        text, same = gm.location_status("/obj/a", "/obj/b")
        self.assertFalse(same)
        self.assertIn("/obj/a", text)
        self.assertIn("/obj/b", text)
        self.assertIn("違います", text)
        self.assertEqual(gm.location_status("", "")[1], True)

    def test_the_sandbox_prefix_matches_the_generator(self):
        import houdini_tools

        self.assertEqual(gm.SANDBOX_PREFIX, houdini_tools.HoudiniToolExecutor.SANDBOX_PREFIX)


class ViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import guide_view
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"guide_view をimportできません: {exc}") from exc
        cls.gv = guide_view

    def setUp(self):
        self.guide = gm.build_guide(PARM_STEPS, "炎", "applied", {"sandbox_path": SANDBOX}, gm.purposes_from_markdown(MD))

    def test_parameter_step_shows_tab_item_before_value_and_label(self):
        step = gm.attach_parm_info(make_world({"/obj/tornado/vortex_points": "attribwrangle"},
                                              templates={"attribwrangle": [RUN_OVER, ENABLE, SIZE]}).hou, self.guide["steps"][1])
        text = self.gv.render_step_html(self.guide, 1, step)
        for word in ("パラメータのタブ: <b>Sourcing &gt; Emission</b>", "項目: <b>Run Over</b>", "Run Over を Detail (only once) にする",
                     "Enable をオフにする", "前の値: オン → 新しい値: <b>オフ</b>", "前の値: 1 → 新しい値: <b>4.5</b>",
                     "このノードの目的: 螺旋状に点を撒き", "/obj/tornado/vortex_points", f"{SANDBOX}/tornado/vortex_points",
                     "【作業する部分】", "作業するネットワーク（階層）: <b>/obj/tornado</b>"):
            self.assertIn(word, text)

    def test_connect_step_lists_every_line(self):
        text = self.gv.render_step_html(self.guide, 3)
        self.assertIn("つなぐ線（9本）", text)
        self.assertEqual(text.count("→"), 9 + 9, "the instruction and the list both carry the nine lines")
        self.assertNotIn("ほか", text)

    def test_delete_step_is_marked(self):
        text = self.gv.render_step_html(self.guide, 2)
        self.assertIn("【消す】/obj/tornado/old_null", text)

    def test_shortcuts_are_folded_after_the_first_step(self):
        self.assertTrue(self.gv.shortcuts_visible(0, False))
        self.assertFalse(self.gv.shortcuts_visible(1, False))
        self.assertTrue(self.gv.shortcuts_visible(1, True))
        shown = self.gv.render_step_html(self.guide, 0)
        folded = self.gv.render_step_html(self.guide, 1, show_shortcuts=False)
        self.assertIn("使うショートカット", shown)
        self.assertNotIn("使うショートカット", folded)
        self.assertIn("ショートカットを表示", folded)
        self.assertNotIn("Ctrl + Z", folded)
        self.assertIn("Ctrl + Z", shown)

    def test_the_old_call_without_options_still_shows_shortcuts(self):
        self.assertIn("使うショートカット", self.gv.render_step_html(self.guide, 3))


class WidgetFlowTest(unittest.TestCase):
    """Guide タブの画面（Qt。画面なしで動かす）と、生成後の自動切り替え。"""

    @classmethod
    def setUpClass(cls):
        try:
            import guide_view
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"guide_view をimportできません: {exc}") from exc
        cls.gv = guide_view
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.state: dict = {}
        patchers = [
            mock.patch.object(self.gv, "hou", None),  # 他のテストが、偽の hou を差し込んでいても、ここでは Houdini の外

            mock.patch.object(self.gv, "_state_get", lambda key, default=None: self.state.get(key, default)),
            mock.patch.object(self.gv, "_state_set", lambda key, value: self.state.__setitem__(key, value)),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

        self.tabs = QTabWidget()
        self.source = QWidget()  # Tutorial タブの中の部品の代わり
        wrapper = QWidget()
        QVBoxLayout(wrapper).addWidget(self.source)
        self.tabs.addTab(QLabel("chat"), "Chat")
        self.guide_widget = self.gv.GuideWidget(lambda: {"local_bridge_dir": ""})
        self.guide_widget._tutorials_dir = lambda: self.dir
        self.tabs.addTab(self.guide_widget, "Guide")
        self.tabs.addTab(wrapper, "Tutorial")
        self.tabs.setCurrentIndex(2)
        self.tabs.show()
        self.addCleanup(self.tabs.close)
        self.guide = gm.build_guide(PARM_STEPS, "炎の竜巻", "applied", {"sandbox_path": SANDBOX})

    def test_generation_switches_to_the_guide_tab_and_loads_the_newest_steps(self):
        note = self.gv.announce_generated(self.source, self.guide, gm.guide_label(self.guide))
        self.assertEqual(self.tabs.currentIndex(), 1)
        self.assertIn("Guide タブに切り替えて", note)
        self.assertEqual(self.tabs.tabText(1), "Guide")
        self.assertTrue(self.guide_widget._combo.itemText(0).startswith("（生成直後・未保存）炎の竜巻"))
        self.assertIn("手順 1 / 4", self.guide_widget._pos.text())
        self.assertIn("まだ保存していません", self.guide_widget._status.text())
        self.assertIn("使うショートカット", self.guide_widget._step_view.toPlainText(), "the first step shows the shortcuts")

    def test_when_switching_is_off_the_tab_gets_a_mark_until_it_is_opened(self):
        self.guide_widget._auto_switch.setChecked(False)
        self.assertFalse(self.state[self.gv._AUTO_SWITCH_KEY], "the choice is remembered")
        note = self.gv.announce_generated(self.source, self.guide, "x")
        self.assertEqual(self.tabs.currentIndex(), 2, "stays on the Tutorial tab")
        self.assertEqual(self.tabs.tabText(1), "Guide ●")
        self.assertIn("●", note)
        self.tabs.setCurrentIndex(1)
        self.assertEqual(self.tabs.tabText(1), "Guide", "the mark is cleared when the tab is opened")

    def test_generation_does_not_pull_the_user_away_from_another_tab(self):
        """生成が終わったとき、利用者が Chat など別のタブで作業中なら、勝手に切り替えない（入力中の画面を壊さない）。印だけ付ける。"""
        self.tabs.setCurrentIndex(0)
        note = self.gv.announce_generated(self.source, self.guide, "x")
        self.assertEqual(self.tabs.currentIndex(), 0)
        self.assertEqual(self.tabs.tabText(1), "Guide ●")
        self.assertIn("別のタブ", note)
        self.assertIn("手順 1 / 4", self.guide_widget._pos.text(), "手順は、読み込んでおく")

    def test_an_explicit_switch_still_switches_from_another_tab(self):
        self.tabs.setCurrentIndex(0)
        self.gv.announce_generated(self.source, self.guide, "x", switch=True)
        self.assertEqual(self.tabs.currentIndex(), 1)

    def test_saving_keeps_the_step_the_user_is_on(self):
        """保存で、生成直後の手順が、保存したものに置き換わっても、いま見ている手順の位置を、先頭に戻さない。"""
        label = gm.guide_label(self.guide)
        self.gv.announce_generated(self.source, self.guide, label)
        self.guide_widget._go(1)
        self.guide_widget._go(1)
        path = self.dir / "fire_guide.json"
        gm.write_guide(path, self.guide)
        self.gv.announce_saved(self.source, path, switch=False)
        self.assertIn("手順 3 / 4", self.guide_widget._pos.text())

    def test_saving_replaces_the_unsaved_steps_with_the_saved_file(self):
        label = gm.guide_label(self.guide)
        self.gv.announce_generated(self.source, self.guide, label)
        self.tabs.setCurrentIndex(2)  # 利用者は、Tutorial タブに戻って「保存」を押す
        path = self.dir / "fire_guide.json"
        gm.write_guide(path, self.guide)
        note = self.gv.announce_saved(self.source, path, switch=False)
        self.assertIn("保存したものに更新", note)
        self.assertEqual(self.guide_widget._combo.count(), 2, "the saved guide and the built-in basics practice")
        self.assertNotIn("未保存", self.guide_widget._combo.itemText(0))
        self.assertEqual(self.tabs.currentIndex(), 2, "saving does not move the user away from the Tutorial tab")

    def test_no_guide_tab_means_no_error(self):
        from PySide6.QtWidgets import QWidget

        lone = QWidget()
        self.assertEqual(self.gv.announce_generated(lone, self.guide, "x"), "")

    def test_shortcut_setting_is_remembered_and_folds_later_steps(self):
        self.gv.announce_generated(self.source, self.guide, "x")
        widget = self.guide_widget
        self.assertFalse(widget._sc_btn.isChecked())
        widget._go(1)
        self.assertNotIn("使うショートカット（", widget._step_view.toPlainText())
        widget._sc_btn.setChecked(True)
        self.assertTrue(self.state[self.gv._SHORTCUTS_KEY])
        self.assertIn("使うショートカット（", widget._step_view.toPlainText())
        widget._go(-1)
        self.assertIn("使うショートカット（", widget._step_view.toPlainText())

    def test_the_popup_window_follows_the_steps(self):
        self.gv.announce_generated(self.source, self.guide, "x")
        widget = self.guide_widget
        widget._open_popup()
        self.assertIn("手順 1 / 4", widget._popup._pos.text())
        widget._go(1)
        self.assertIn("手順 2 / 4", widget._popup._pos.text())
        self.assertIn("パラメータのタブ", widget._popup.view.toPlainText())
        widget._popup.close()

    def test_the_hierarchy_line_is_always_shown(self):
        self.gv.announce_generated(self.source, self.guide, "x")
        self.assertIn("この手順の作業場所: /obj/tornado", self.guide_widget._where.text(), "outside Houdini: the step's own place")
        with mock.patch.object(self.gv, "hou", make_world({"/obj/tornado/vortex_points": "attribwrangle", "/obj/other": "subnet"}, pwd="/obj/other").hou):
            self.guide_widget._update_where()
            text = self.guide_widget._where.text()
        self.assertIn("いまのネットワーク: /obj/other", text)
        self.assertIn("違います", text)

    def test_apply_uses_the_sandbox_path_and_mode_of_the_guide(self):
        world = make_world({f"{SANDBOX}/tornado/vortex_points": "attribwrangle"}, pwd="/obj")
        self.gv.announce_generated(self.source, self.guide, "x")
        self.guide_widget._go(1)
        with mock.patch.object(self.gv, "hou", world.hou):
            self.guide_widget._apply()
        self.assertIn(f"{SANDBOX}/tornado/vortex_points", self.guide_widget._status.text())
        self.assertTrue(world.hou.node(f"{SANDBOX}/tornado/vortex_points").current)


class TutorialViewHookTest(WidgetFlowTest):
    """tutorial_view.py の、生成完了・保存の処理から、Guide タブへ渡ること。"""

    def setUp(self):
        try:
            import tutorial_view
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"tutorial_view をimportできません: {exc}") from exc
        self.tv = tutorial_view
        super().setUp()
        self.result = types.SimpleNamespace(markdown=MD, sandbox_path=SANDBOX, step_screenshots=PARM_STEPS, title="炎の竜巻", level="applied",
                                            graph={"nodes": []}, file_basename=lambda: "fire", metrics=None)

    # 親クラスのテストは、ここでは繰り返さない
    test_generation_switches_to_the_guide_tab_and_loads_the_newest_steps = None
    test_when_switching_is_off_the_tab_gets_a_mark_until_it_is_opened = None
    test_saving_replaces_the_unsaved_steps_with_the_saved_file = None
    test_no_guide_tab_means_no_error = None
    test_shortcut_setting_is_remembered_and_folds_later_steps = None
    test_the_popup_window_follows_the_steps = None
    test_the_hierarchy_line_is_always_shown = None
    test_apply_uses_the_sandbox_path_and_mode_of_the_guide = None

    def test_done_hook_loads_and_switches(self):
        note = self.tv.TutorialGeneratePanel._announce_guide(self.source, self.result)
        self.assertIn("Guide タブに切り替えて", note)
        self.assertEqual(self.tabs.currentIndex(), 1)
        self.assertIn("手順 1 / 4", self.guide_widget._pos.text())

    def test_done_hook_never_raises(self):
        broken = types.SimpleNamespace(markdown=None, step_screenshots=object())
        self.assertEqual(self.tv.TutorialGeneratePanel._announce_guide(self.source, broken), "")

    def test_saved_file_carries_the_sandbox_and_the_purposes_and_the_guide_tab_follows(self):
        paths = self.tv.TutorialGeneratePanel._write_result(self.result, self.dir)
        self.assertIsNotNone(paths)
        data = json.loads((self.dir / "fire_guide.json").read_text(encoding="utf-8"))
        self.assertEqual(data["sandbox_path"], SANDBOX)
        self.assertIn("螺旋状", data["steps"][0]["purpose"])
        self.tv.TutorialGeneratePanel._announce_guide(self.source, self.result)
        self.tabs.setCurrentIndex(2)
        note = self.tv.TutorialGeneratePanel._announce_guide_saved(self.source, paths[0], switch=False)
        self.assertIn("保存したものに更新", note)
        self.assertEqual(self.guide_widget._combo.count(), 2, "the saved guide and the built-in basics practice")


if __name__ == "__main__":
    unittest.main()
