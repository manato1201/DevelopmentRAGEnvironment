"""用語の一覧（houdini_terms）・初心者への練習の勧め・練習の記録のテスト（2026-11-26）。

  ・Guide の手順の語をダブルクリックすると、用語の一覧にある語は、その場で意味を出す（無い語は、これまでどおり Reference で探す）
  ・基本操作の練習の手順には、その手順に出てくる用語を添える。Guide の「用語の一覧」で、まとめて見られる
  ・課題タブ: 初心者（経験 1 年未満か、自己評価「初心者」）で、練習も固定課題もまだの人に、練習を勧める
  ・練習の進み具合は、実証実験に参加しているときだけ、/pilot/basics に送る（同じ手順は 2 回送らない）
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))
sys.modules.setdefault("hou", types.ModuleType("hou"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import basics_guide as bg  # noqa: E402
import houdini_terms as ht  # noqa: E402
import pilot_task as pt  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None


class TermsTest(unittest.TestCase):
    def test_every_entry_is_complete_and_names_are_unique(self) -> None:
        names: dict[str, str] = {}
        for entry in ht.ENTRIES:
            self.assertTrue(entry["term"] and entry["meaning"], entry)
            self.assertLessEqual(len(entry["meaning"]), 120, "short, plain words: " + entry["term"])
            for name in [entry["term"], *entry["aliases"]]:
                key = ht._norm(name)
                self.assertNotIn(key, names, f"{name} is used by {names.get(key)} too")
                names[key] = entry["term"]
            for number in entry["steps"]:
                self.assertTrue(1 <= number <= len(bg.build()["steps"]), entry["term"])

    def test_lookup_takes_aliases_brackets_and_particles(self) -> None:
        self.assertEqual(ht.lookup("表示フラグ")["term"], "表示フラグ")
        self.assertEqual(ht.lookup("「表示フラグ」を")["term"], "表示フラグ")
        self.assertEqual(ht.lookup("display flag")["term"], "表示フラグ")
        self.assertEqual(ht.lookup("Attribute")["term"], "属性")
        self.assertEqual(ht.lookup("線を")["term"], "線")
        self.assertEqual(ht.lookup("/obj")["term"], "Object")
        self.assertIsNone(ht.lookup("Scatter"), "node names go to Reference")
        self.assertIsNone(ht.lookup(""))
        self.assertIsNone(ht.lookup("ノード" * 10), "a long selection is a sentence, not a term")
        self.assertIsNone(ht.lookup("点線の多い図"), "one-letter terms only at the start of a short selection")

    def test_terms_in_text_skip_other_meanings_and_parts_of_longer_words(self) -> None:
        terms = [e["term"] for e in ht.terms_in("Tab を押して「Geometry」と入力して Enter")]
        self.assertNotIn("入力", terms, "typing is not the input connector")
        terms = [e["term"] for e in ht.terms_in("ネットワークエディタで、表示フラグを付ける")]
        self.assertEqual(terms, ["ネットワークエディタ", "表示フラグ"], "no ネットワーク inside ネットワークエディタ")
        self.assertEqual([e["term"] for e in ht.terms_in("file_output と practice_geo")], [], "no words inside names")
        self.assertEqual(len(ht.terms_in("ノード パラメータ 属性 SOP DOP VEX", limit=3)), 3)

    def test_every_basics_step_explains_some_terms_and_html_is_escaped(self) -> None:
        for step in bg.build()["steps"]:
            self.assertTrue(ht.terms_in(f"{step['instruction']} {step['hint']}"), step["step"])
        self.assertIn("&lt;b&gt;", ht.html_block([{"term": "<b>", "meaning": "x"}]))
        self.assertEqual(ht.html_block([]), "")
        self.assertIn("表示フラグ", ht.html_list("フラグ"))
        self.assertNotIn("属性", ht.html_list("フラグ"))
        self.assertIn("合う用語はありません", ht.html_list("zzz"))
        self.assertIn("基本操作の練習: 手順 6・10", ht.html_list("表示フラグ"))

    def test_the_basics_page_shows_the_terms_but_generated_steps_do_not(self) -> None:
        import guide_view as gv

        guide = bg.build()
        self.assertIn("この手順の用語", gv.render_step_html(guide, 5))
        generated = {"steps": [dict(guide["steps"][5])]}
        self.assertNotIn("この手順の用語", gv.render_step_html(generated, 0))


class BasicsNoteTest(unittest.TestCase):
    def test_only_beginners_who_have_not_started_get_the_button(self) -> None:
        text, button = pt.basics_note({"basics": {"beginner": True, "recommend": True, "step": 0, "total": 0}})
        self.assertTrue(button)
        self.assertIn("基本操作の練習", text)
        text, _ = pt.basics_note({"basics": {"beginner": True, "recommend": True, "step": 5, "total": 12}})
        self.assertIn("5 / 12", text)
        self.assertEqual(pt.basics_note({"basics": {"beginner": True, "recommend": False, "done": True}}), ("基本操作の練習: 終えました。", False))
        self.assertEqual(pt.basics_note({"basics": {"beginner": False, "recommend": False}}), ("", False))
        self.assertEqual(pt.basics_note({}), ("", False), "an old server sends nothing")


class ReportProgressTest(unittest.TestCase):
    def _run(self, state: dict, cfg: dict, step: int, recorded: bool = True):
        import guide_view as gv

        sent: list = []

        def post(s, t):
            sent.append((s, t))
            return {"recorded": recorded}

        with mock.patch.object(gv, "_state_get", lambda key, default=None: state.get(key, default)), \
                mock.patch.object(gv, "_state_set", lambda key, value: state.__setitem__(key, value)):
            did = gv.report_basics_progress(cfg, step, 12, post=post)
        return did, sent

    def test_it_sends_only_new_steps_while_in_the_pilot(self) -> None:
        cf = {"mode": "cloudflare"}
        self.assertEqual(self._run({}, cf, 3), (False, []), "not in the pilot")
        state = {"pilot_enabled": True}
        self.assertEqual(self._run(state, {"mode": "local"}, 3), (False, []), "local mode has no server")
        self.assertEqual(self._run(state, cf, 3), (True, [(3, 12)]))
        self.assertEqual(state["basics_sent_step"], 3)
        self.assertEqual(self._run(state, cf, 2), (False, []), "going back sends nothing")
        self.assertEqual(self._run(state, cf, 4, recorded=False), (True, [(4, 12)]))
        self.assertEqual(state["basics_sent_step"], 3, "not remembered before the pre-survey (sent again later)")


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class WidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _guide(self):
        import guide_view as gv

        state: dict = {}
        for patch in (mock.patch.object(gv, "_state_get", lambda key, default=None: state.get(key, default)),
                      mock.patch.object(gv, "_state_set", lambda key, value: state.__setitem__(key, value)),
                      mock.patch.object(gv, "hou", None)):
            patch.start()
            self.addCleanup(patch.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        widget = gv.GuideWidget(lambda: {})
        self.addCleanup(widget.deleteLater)
        widget._tutorials_dir = lambda: Path(tmp.name)
        return gv, widget

    def test_the_terms_list_and_the_shortcut_sheet_take_turns(self) -> None:
        _gv, widget = self._guide()
        widget.refresh()
        widget._terms_btn.setChecked(True)
        self.assertEqual(widget._extra_box.title(), "用語の一覧")
        self.assertIn("表示フラグ", widget._extra_view.toPlainText())
        widget._sheet_filter.setText("属性")
        self.assertIn("属性", widget._extra_view.toPlainText())
        self.assertNotIn("表示フラグ", widget._extra_view.toPlainText())
        widget._sheet_btn.setChecked(True)
        self.assertFalse(widget._terms_btn.isChecked())
        self.assertEqual(widget._extra_box.title(), "ショートカット一覧")
        widget._sheet_btn.setChecked(False)
        self.assertEqual(widget._extra_box.title(), "前提条件・TIPS")
        self.assertTrue(widget._sheet_filter.isHidden())

    def test_a_double_clicked_term_is_explained_here_and_cleared_on_the_next_step(self) -> None:
        import reference_view

        _gv, widget = self._guide()
        widget.refresh()
        lookup = reference_view.TermLookup(widget._step_view, lambda m: None, on_term=widget._show_term)
        with mock.patch.object(reference_view.TermLookup, "selected_text", staticmethod(lambda _w: "表示フラグ")), \
                mock.patch.object(reference_view, "search_term") as searched:
            lookup._lookup(widget._step_view)
        searched.assert_not_called()
        self.assertFalse(widget._term.isHidden())
        self.assertIn("右端の青い部分", widget._term.text())
        widget._go(1)
        self.assertTrue(widget._term.isHidden())
        with mock.patch.object(reference_view.TermLookup, "selected_text", staticmethod(lambda _w: "Scatter")), \
                mock.patch.object(reference_view, "search_term", return_value="探しました") as searched:
            lookup._lookup(widget._step_view)
        searched.assert_called_once()

    def test_the_pilot_panel_recommends_and_opens_the_practice(self) -> None:
        import guide_view as gv
        import pilot_panel
        from PySide6.QtWidgets import QTabWidget

        _gv, guide = self._guide()
        panel = pilot_panel.PilotTaskPanel(lambda: {"mode": "cloudflare"}, progress_path=Path(tempfile.mkdtemp()) / "p.json")
        tabs = QTabWidget()
        self.addCleanup(tabs.deleteLater)
        tabs.addTab(panel, "課題")
        tabs.addTab(guide, "Guide")
        plan = {"profile": True, "pid": 1, "round": 3, "canStart": True, "basics": {"beginner": True, "recommend": True, "step": 0, "total": 0},
                "fixed": {"taskId": "rbd", "label": "RBD（剛体・破壊のシミュレーション）", "condition": "system", "done": False, "active": False, "optional": False, "locked": False},
                "free": {"taskId": "free", "label": "自分の作りたいもの", "condition": "system", "done": False, "active": False, "optional": True, "locked": True},
                "criterion": "x", "history": []}
        panel._apply_plan(plan)
        self.assertFalse(panel._basics_box.isHidden())
        self.assertFalse(panel._basics_btn.isHidden())
        self.assertEqual(panel._header.text(), "第3回（参加者 P01）")
        panel._basics_btn.click()
        self.assertEqual(tabs.currentIndex(), 1)
        self.assertEqual(guide._guide["builtin"], bg.KEY)
        self.assertIn("基本操作の練習を開きました", panel._message.text())
        plan["basics"] = {"beginner": False}
        panel._apply_plan(plan)
        self.assertTrue(panel._basics_box.isHidden())


if __name__ == "__main__":
    unittest.main()
