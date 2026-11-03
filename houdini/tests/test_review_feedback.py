"""初心者レビュー（2026-11-03）への対応: 前提条件・使う場面・段取り・TIPS・自分でやってみよう、動画の章のつなぎ。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import lesson_design as ld  # noqa: E402
import tutorial_review as tr  # noqa: E402
import video_script as vs  # noqa: E402
from test_lesson_design import FULL_FINISH, LOG  # noqa: E402
from test_video_script import good_model, make_steps  # noqa: E402

NEW_FIELDS = ("prerequisites", "use_cases", "roadmap", "tips", "challenge")

RAW_PLAN = {
    "chapters": [{"title": "a", "build": "b"}, {"title": "c", "why": "d"}],
    "prerequisites": ["ノードをつなげる人向け", "Houdini 22", "知っている人は章2から", "分からなければ入門を先に", "五つ目は切られる"],
    "use_cases": ["ゲームの地面に岩を散らすとき", "映像の背景", "三つ目", "四つ目は切られる"],
    "roadmap": [{"node": "Scatter", "does": "点を散らす"}, {"node": "", "does": "空のノード名"}, "壊れた項目", {"node": "Grid"}],
    "tips": ["Geometry Spreadsheet で点の数を見る", "効いている要素を1つずつ切る"],
    "challenge": "手本を見ずに、点が300個以上ある地面を作る",
}


class PlanFieldsTest(unittest.TestCase):
    def test_new_plan_fields_are_validated(self):
        plan = ld.validate_plan(RAW_PLAN)
        self.assertEqual(len(plan["prerequisites"]), 4)
        self.assertEqual(len(plan["use_cases"]), 3)
        self.assertEqual(plan["roadmap"], [{"node": "Scatter", "does": "点を散らす"}], "empty name, non-dict and no-role items are dropped")
        self.assertEqual(len(plan["tips"]), 2)
        self.assertIn("300個", plan["challenge"])

    def test_old_plans_without_the_fields_still_validate(self):
        plan = ld.validate_plan({"chapters": RAW_PLAN["chapters"]})
        for key in ("prerequisites", "use_cases", "roadmap", "tips"):
            self.assertEqual(plan[key], [])
        self.assertEqual(plan["challenge"], "")

    def test_plan_section_and_fallbacks_carry_them(self):
        plan = ld.validate_plan(RAW_PLAN)
        text = ld.plan_section(plan, "basic")
        for word in ("前提条件:", "使う場面:", "段取り（使うノード）: Scatter", "TIPS:", "自分でやってみよう:"):
            self.assertIn(word, text)
        fields = ld.fallback_fields(plan)
        self.assertEqual(set(NEW_FIELDS) & set(fields), set(NEW_FIELDS))
        self.assertIn("1. **Scatter**", fields["roadmap"])

    def test_plan_prompt_asks_for_them(self):
        for level in ("basic", "applied", "advanced"):
            prompt = ld.plan_system_prompt(level)
            for key in NEW_FIELDS:
                self.assertIn(f'"{key}"', prompt, level)

    def test_teaching_rules_require_them(self):
        for key in NEW_FIELDS:
            self.assertIn(key, ld.TEACHING_RULES)


class ReviewTest(unittest.TestCase):
    def test_weights_still_sum_to_100(self):
        self.assertEqual(sum(tr._WEIGHTS.values()), 100)

    def test_every_new_field_is_a_lesson_field_and_scored(self):
        for key in NEW_FIELDS:
            self.assertIn(key, tr.LESSON_FIELDS)
            self.assertIn(key, tr._WEIGHTS)
            without = dict(FULL_FINISH)
            without.pop(key)
            report = tr.review_finish(without, LOG)
            self.assertLess(report["score"], 100, key)
            self.assertIn(key, tr.missing_lesson_fields(without))

    def test_full_finish_still_scores_100(self):
        self.assertEqual(tr.review_finish(FULL_FINISH, LOG)["score"], 100)
        self.assertEqual(tr.finish_gap_message(FULL_FINISH), "")


class MarkdownOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tutorial_agent
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"tutorial_agent をimportできません: {exc}") from exc
        cls.ta = tutorial_agent

    def test_sections_come_in_reading_order(self):
        agent = self.ta.TutorialAgent.__new__(self.ta.TutorialAgent)
        agent._model = "test"
        agent.executor = None
        result = self.ta.TutorialResult()
        result.completed = True
        md = agent._assemble_markdown("岩", dict(FULL_FINISH), result)
        order = [md.index(f"## {h}") for h in (
            "概要", "前提条件", "どんな場面で使うか", "作る前に: 使うノードと、できること", "このレッスンで学ぶこと",
            "先に知っておく考え方", "手順", "パラメータを動かして確かめよう", "仕上げ", "TIPS", "コード・ノード構成",
            "ハマりポイント", "応用・発展のヒント", "自分でやってみよう", "次のレッスン", "参考",
        )]
        self.assertEqual(order, sorted(order))

    def test_video_sees_the_new_sections_with_templates(self):
        agent = self.ta.TutorialAgent.__new__(self.ta.TutorialAgent)
        agent._model = "test"
        agent.executor = None
        result = self.ta.TutorialResult()
        result.completed = True
        md = agent._assemble_markdown("岩", dict(FULL_FINISH), result)
        headings = [h for h, _ in vs.extra_sections(md)]
        for h in ("前提条件", "どんな場面で使うか", "作る前に: 使うノードと、できること", "TIPS", "自分でやってみよう"):
            self.assertIn(h, headings)
            template = vs._template_section(h)
            self.assertNotEqual(template["narration"], f"ここでは、「{vs.to_katakana(h)}」について、補足します。", f"{h} has its own template")
            self.assertGreaterEqual(len(template["narration"]), 20)
            self.assertFalse(vs.looks_like_code(template["narration"]))


class ChaptersTest(unittest.TestCase):
    def steps(self, tmp):
        return vs.usable_steps(make_steps(Path(tmp)))

    def model(self, steps, chapters):
        model = good_model(steps)
        model["chapters"] = chapters
        return model

    def test_chapters_mark_steps_and_add_bridges(self):
        with tempfile.TemporaryDirectory() as d:
            steps = self.steps(d)
            chapters = [
                {"from_step": 1, "title": "作業場所を作る", "bridge": "最初に、作業場所を用意します。"},
                {"from_step": 3, "title": "点を発生させる", "bridge": "ここまでで、入れ物ができました。次は、点を発生させます。"},
            ]
            script, _, _ = vs.assemble_script(self.model(steps, chapters), steps, "t", "")
            by_step = {s["step"]: s for s in script["steps"]}
            self.assertEqual(script["chapters"], [{"from_step": 1, "title": "作業場所を作る"}, {"from_step": 3, "title": "点を発生させる"}])
            self.assertTrue(by_step[3]["chapter_start"])
            self.assertTrue(by_step[3]["narration"].startswith("ここまでで、入れ物ができました。"))
            self.assertEqual(by_step[2]["chapter"], "作業場所を作る")
            self.assertEqual(by_step[5]["chapter"], "点を発生させる")
            self.assertFalse(by_step[2].get("chapter_start"))
            self.assertFalse(by_step[1]["narration"].startswith("最初に"), "the first chapter relies on the intro, no bridge")

    def test_invalid_or_single_chapters_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            steps = self.steps(d)
            single = [{"from_step": 1, "title": "全部", "bridge": "はじめます。はじめます。"}]
            bad = [{"from_step": 99, "title": "ない手順"}, {"from_step": "3", "title": "文字"}, "壊れた", {"from_step": 3, "title": ""}]
            for chapters in (single, bad, []):
                script, _, _ = vs.assemble_script(self.model(steps, chapters), steps, "t", "")
                self.assertNotIn("chapters", script)
                self.assertFalse(any("chapter" in s for s in script["steps"]))
            script, _, _ = vs.assemble_script(None, steps, "t", "")
            self.assertNotIn("chapters", script)

    def test_prompt_asks_for_chapters_and_the_new_sections(self):
        for level in ("basic", "applied", "advanced"):
            text = vs.system_prompt(level)
            self.assertIn('"chapters"', text)
            self.assertIn("前提条件", text)
            self.assertIn("TIPS", text)
            self.assertIn("自分でやってみよう", text)


if __name__ == "__main__":
    unittest.main()
