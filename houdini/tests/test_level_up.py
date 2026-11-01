"""レッスンの水準の引き上げ（2026-11-01）: レッスン設計・動画の台本が、レベル（basic / applied / advanced）で変わること。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import lesson_design as ld  # noqa: E402
import video_script as vs  # noqa: E402
from test_video_script import GOOD_STEP, good_model, make_steps  # noqa: E402

LEVELS = ("basic", "applied", "advanced")


class LessonPathTest(unittest.TestCase):
    def test_lesson_one_is_no_longer_an_introduction_for_absolute_beginners(self):
        title, role = ld.LESSON_PATH["basic"]
        self.assertIn("動かして理解", title)
        self.assertIn("基本操作", role)
        self.assertNotIn("初めて触る人", role)

    def test_lessons_climb_one_step(self):
        self.assertIn("実務で使える形", ld.LESSON_PATH["applied"][0])
        self.assertIn("設計を判断する", ld.LESSON_PATH["advanced"][0])
        advanced_role = ld.LESSON_PATH["advanced"][1]
        for word in ("比べ", "規模", "壊れ", "確かめていない性能"):
            self.assertIn(word, advanced_role)

    def test_teaching_rules_no_longer_pin_the_reader_to_beginners(self):
        self.assertNotIn("初心者", ld.TEACHING_RULES)


class PlanPromptTest(unittest.TestCase):
    def test_plan_prompt_differs_per_level_and_names_no_beginner(self):
        prompts = {level: ld.plan_system_prompt(level) for level in LEVELS}
        self.assertEqual(len(set(prompts.values())), 3)
        for level, text in prompts.items():
            self.assertNotIn("初めての人", text, level)
            self.assertNotIn("初心者", text, level)
            self.assertNotIn("@@", text, "every placeholder is filled")
        self.assertIn("基本用語は説明しない", prompts["basic"])
        self.assertIn("代わりの方法", prompts["applied"])
        self.assertIn("壊れる条件", prompts["advanced"])
        self.assertEqual(ld.plan_system_prompt("unknown"), prompts["basic"])
        self.assertEqual(ld.PLAN_SYSTEM_PROMPT, prompts["basic"])

    def test_design_lesson_sends_the_prompt_of_the_requested_level(self):
        sent = []

        def complete(system, user):
            sent.append(system)
            return "{}", {}

        for level in LEVELS:
            ld.design_lesson(complete, "岩", level)
        self.assertEqual(len(set(sent[::2])), 3, "one distinct system prompt per level")
        self.assertEqual(sent[0], ld.plan_system_prompt("basic"))
        self.assertEqual(sent[2], ld.plan_system_prompt("applied"))
        self.assertEqual(sent[4], ld.plan_system_prompt("advanced"))


class DecisionsTest(unittest.TestCase):
    RAW = {
        "chapters": [{"title": "a", "build": "b"}, {"title": "c", "why": "d"}],
        "decisions": [
            {"choice": "Scatter", "alternative": "手で置く", "criterion": "点の数が1000を超えたら Scatter"},
            {"choice": "", "alternative": "x", "criterion": "y"},
            {"choice": "選ぶだけ"},
            "壊れた項目",
        ],
    }

    def test_decisions_are_validated_and_shown(self):
        plan = ld.validate_plan(self.RAW)
        self.assertEqual(len(plan["decisions"]), 1, "empty choice, no alternative/criterion, non-dict are dropped")
        text = ld.plan_section(plan, "applied")
        self.assertIn("設計判断: Scatter", text)
        self.assertIn("手で置く", text)

    def test_plans_without_decisions_still_work(self):
        plan = ld.validate_plan({"chapters": self.RAW["chapters"]})
        self.assertEqual(plan["decisions"], [])
        self.assertNotIn("設計判断", ld.plan_section(plan, "basic"))

    def test_decisions_fall_back_into_concepts(self):
        fields = ld.fallback_fields(ld.validate_plan(self.RAW))
        self.assertIn("設計判断", fields["concepts"])


class VideoSystemPromptTest(unittest.TestCase):
    def test_prompt_differs_per_level_and_is_not_beginner_only(self):
        prompts = {level: vs.system_prompt(level) for level in LEVELS}
        self.assertEqual(len(set(prompts.values())), 3)
        for level, text in prompts.items():
            self.assertNotIn("入門講師", text, level)
            self.assertNotIn("Houdiniは初めて", text, level)
            self.assertNotIn("@@", text, level)
        self.assertIn("基本操作は分かる人", prompts["basic"])
        self.assertIn("設計の理由", prompts["applied"])
        self.assertIn("トレードオフ", prompts["advanced"])
        self.assertIn("用語の説明はしない", prompts["advanced"])
        self.assertIn("初めて出たときに一言", prompts["basic"])
        self.assertEqual(vs.system_prompt(""), prompts["basic"])
        self.assertEqual(vs.SYSTEM_PROMPT, prompts["basic"])

    def test_user_prompt_names_the_audience(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            for level, word in (("basic", "基本操作を知っている人向け"), ("applied", "実務でHoudiniを使う人向け"), ("advanced", "経験者向け")):
                text = vs.build_user_prompt("t", "excerpt", steps, [("つまずき", "本文")], level)
                self.assertIn(word, text)
                self.assertNotIn("初心者", text)

    def test_limits_grow_with_the_level(self):
        steps = [vs.limits_for(level)["step"] for level in LEVELS]
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(len(set(steps)), 3)
        self.assertEqual(vs.limits_for("")["step"], vs.STEP_NARRATION_MAX, "unknown level keeps the old limit")


class LevelFromMarkdownTest(unittest.TestCase):
    def test_reads_difficulty_from_frontmatter(self):
        for level in LEVELS:
            self.assertEqual(vs.level_from_md(f"---\ntitle: T\ndifficulty: {level}\n---\n本文"), level)
        self.assertEqual(vs.level_from_md("---\ntitle: T\ndifficulty: expert\n---\n本文"), "")
        self.assertEqual(vs.level_from_md("本文だけ"), "")
        self.assertEqual(vs.level_from_md("---\r\ndifficulty: applied\r\n---\r\n本文"), "applied")


class VideoScriptByLevelTest(unittest.TestCase):
    LONG = GOOD_STEP + ("ここで、設定を変えたときの違いを、数字で見比べます。" * 14)  # 400字より長い

    def model_with_long_steps(self, steps):
        model = good_model(steps)
        for item in model["steps"]:
            item["narration"] = self.LONG
        return model

    def test_longer_narration_survives_at_higher_levels(self):
        with tempfile.TemporaryDirectory() as d:
            steps = vs.usable_steps(make_steps(Path(d)))
            lengths = {}
            for level in LEVELS:
                script, _, _ = vs.assemble_script(self.model_with_long_steps(steps), steps, "t", "", None, level)
                lengths[level] = len(script["steps"][0]["narration"])
                self.assertLessEqual(lengths[level], vs.limits_for(level)["step"])
            self.assertLess(lengths["basic"], lengths["applied"])
            self.assertLess(lengths["applied"], lengths["advanced"])

    def test_script_records_its_level(self):
        with tempfile.TemporaryDirectory() as d:
            steps = vs.usable_steps(make_steps(Path(d)))
            for level in LEVELS:
                script, _, _ = vs.assemble_script(good_model(steps), steps, "t", "", None, level)
                self.assertEqual(script["level"], level)
            script, _, _ = vs.assemble_script(good_model(steps), steps, "t", "")
            self.assertNotIn("level", script, "a script without a level stays as before")

    def test_template_for_a_known_level_skips_beginner_basics(self):
        with tempfile.TemporaryDirectory() as d:
            steps = vs.usable_steps(make_steps(Path(d)))
            legacy, _, _ = vs.assemble_script(None, steps, "ブラックホール", "点を並べます。")
            leveled, _, _ = vs.assemble_script(None, steps, "ブラックホール", "点を並べます。", None, "basic")
            legacy_text = " ".join(s["narration"] for s in legacy["steps"]) + legacy["intro"]["narration"]
            leveled_text = " ".join(s["narration"] for s in leveled["steps"]) + leveled["intro"]["narration"]
            self.assertIn("Tabキー", legacy_text)
            self.assertIn("はじめての方", legacy_text)
            for beginner in ("Tabキー", "はじめての方", "作業場所です"):
                self.assertNotIn(beginner, leveled_text)

    def test_build_script_uses_the_level_in_the_markdown(self):
        md = "---\ntitle: T\ndifficulty: advanced\n---\n## 概要\nあ。\n"
        seen = {}

        def complete(system, user):
            seen["system"], seen["user"] = system, user
            return json.dumps({}), {}

        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            script, _, _ = vs.build_script(md, steps, complete)
            self.assertEqual(seen["system"], vs.system_prompt("advanced"))
            self.assertIn("経験者向け", seen["user"])
            self.assertEqual(script["level"], "advanced")
            vs.build_script(md, steps, complete, None, "basic")  # 明示した引数が優先
            self.assertEqual(seen["system"], vs.system_prompt("basic"))

    def test_prepare_script_file_passes_the_level(self):
        md_text = "---\ntitle: T\ndifficulty: applied\n---\n## 概要\nあ。\n"
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "sample.md"
            md.write_text(md_text, encoding="utf-8")
            steps = make_steps(tmp)
            path, _ = vs.prepare_script_file(md, steps, lambda s, u: (json.dumps(good_model(vs.usable_steps(steps)), ensure_ascii=False), {}))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["level"], "applied")


if __name__ == "__main__":
    unittest.main()
