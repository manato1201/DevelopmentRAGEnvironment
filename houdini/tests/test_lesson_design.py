"""lesson_design.py / tutorial_review.py / TutorialAgent の組み立て部分のテスト（標準の unittest。Houdini・Claude・ネットワークは使わない）。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import lesson_design as ld  # noqa: E402
import tutorial_review as tr  # noqa: E402
import video_script as vs  # noqa: E402

GOOD_PLAN = {
    "goal": "岩が散らばった地面ができている",
    "learn": ["スキャッターの役目", "コピーで形を増やす考え方"],
    "concepts": [{"term": "スキャッター", "plain": "面の上にランダムに点を置くノードです"}],
    "mental_model": "地面に種をまく作業に似ています。種の位置が点で、あとで岩を置きます。",
    "chapters": [
        {"title": "地面を作る", "why": "岩を置く土台が要る", "build": "Grid", "checkpoint": "平らな面が見える", "check_with": "viewport"},
        {"title": "点を散らす", "why": "岩の位置を決める", "build": "Scatter", "checkpoint": "点が100個ほどある", "check_with": "inspect_geometry"},
    ],
    "experiments": [{"target": "scatter.npts", "change": "100 → 500", "effect": "点が増えて密になる"}],
    "polish": "岩の大きさをランダムにする",
    "mistakes": ["点が見えないときは表示フラグを確認する"],
    "next_lesson": "岩の種類を増やす方法",
}

FULL_FINISH = {
    "title": "T", "slug": "t", "overview": "概要です",
    "steps": (
        "1. Grid を作る。岩を置く土台になるため\n✅ 確認ポイント: 平らな面が見えれば正しい\n"
        "2. Scatter で点を散らす。岩の位置を決めるため\n✅ 確認ポイント: 点の数が100個前後"
    ),
    "pitfalls": "点が見えないときは表示フラグを確認します",
    "learn": "- スキャッターの役目\n- コピーの考え方",
    "concepts": "- **スキャッター**: 面の上にランダムに点を置くノードです。種まきのようなものです",
    "experiments": "- scatter.npts: 100 → 500 で点が増える\n- scatter.seed: 1 → 2 で並びが変わる",
    "polish": "岩の大きさをランダムにして自然に見せる",
    "next_lesson": "岩の種類を増やす方法を学ぶと、今回の配置が活きます",
}

LOG = [
    {"tool": "create_node", "result": "ok"},
    {"tool": "cook_node", "result": "cook 成功"},
    {"tool": "inspect_geometry", "result": "点 100"},
    {"tool": "set_parameter", "result": "ok"},
    {"tool": "cook_node", "result": "cook 成功"},
    {"tool": "set_parameter", "result": "ok"},
    {"tool": "cook_node", "result": "cook 成功"},
]


class ValidatePlanTest(unittest.TestCase):
    def test_good_plan_is_kept(self) -> None:
        plan = ld.validate_plan(GOOD_PLAN)
        assert plan is not None
        self.assertEqual(len(plan["chapters"]), 2)
        self.assertEqual(plan["concepts"][0]["term"], "スキャッター")
        self.assertEqual(plan["experiments"][0]["target"], "scatter.npts")

    def test_single_chapter_is_rejected(self) -> None:
        bad = {**GOOD_PLAN, "chapters": GOOD_PLAN["chapters"][:1]}
        self.assertIsNone(ld.validate_plan(bad))

    def test_garbage_is_rejected(self) -> None:
        self.assertIsNone(ld.validate_plan(None))
        self.assertIsNone(ld.validate_plan({"chapters": "x"}))
        self.assertIsNone(ld.parse_plan_json("説明だけ"))

    def test_limits_are_applied(self) -> None:
        many = {**GOOD_PLAN, "chapters": GOOD_PLAN["chapters"] * 5, "learn": ["あ"] * 9}
        plan = ld.validate_plan(many)
        assert plan is not None
        self.assertLessEqual(len(plan["chapters"]), ld.MAX_CHAPTERS)
        self.assertLessEqual(len(plan["learn"]), 4)

    def test_parse_accepts_code_fence(self) -> None:
        text = "```json\n" + json.dumps(GOOD_PLAN, ensure_ascii=False) + "\n```"
        self.assertIsNotNone(ld.validate_plan(ld.parse_plan_json(text)))


class DesignLessonTest(unittest.TestCase):
    def test_success(self) -> None:
        plan, message, _ = ld.design_lesson(lambda s, u: (json.dumps(GOOD_PLAN, ensure_ascii=False), {"input_tokens": 5}), "岩の散布", "basic")
        self.assertIsNotNone(plan)
        self.assertIn("2章", message)

    def test_retry_then_fallback(self) -> None:
        calls: list[int] = []

        def broken(system: str, user: str) -> tuple[str, dict]:
            calls.append(1)
            return "JSONではありません", {}

        plan, message, _ = ld.design_lesson(broken, "岩の散布", "basic")
        self.assertIsNone(plan)
        self.assertEqual(len(calls), 2)
        self.assertIn("設計なしで続けます", message)

    def test_exception_never_propagates(self) -> None:
        def boom(system: str, user: str) -> tuple[str, dict]:
            raise RuntimeError("接続できません")

        plan, message, _ = ld.design_lesson(boom, "岩の散布", "basic")
        self.assertIsNone(plan)
        self.assertIn("設計なしで続けます", message)

    def test_no_backend(self) -> None:
        plan, message, _ = ld.design_lesson(None, "岩の散布", "basic")
        self.assertIsNone(plan)
        self.assertIn("設計なし", message)

    def test_prompt_carries_level_and_prior_summary(self) -> None:
        prompt = ld.build_plan_prompt("岩の散布", "advanced", "岩は10個", ["参考の本文"], "前の要約です", True, "model.fbx")
        for needle in ("レッスン3", "岩は10個", "前の要約です", "参考の本文", "model.fbx", "参考画像"):
            self.assertIn(needle, prompt)


class PlanSectionTest(unittest.TestCase):
    def test_section_with_plan_has_chapters_and_rules(self) -> None:
        plan = ld.validate_plan(GOOD_PLAN)
        text = ld.plan_section(plan, "applied")
        self.assertIn("レッスン2", text)
        self.assertIn("章1「地面を作る」", text)
        self.assertIn("教え方のルール", text)
        self.assertIn("✅ 確認ポイント", text)

    def test_section_without_plan_still_teaches(self) -> None:
        text = ld.plan_section(None, "basic")
        self.assertIn("レッスン1", text)
        self.assertIn("教え方のルール", text)
        self.assertNotIn("レッスンの設計", text)

    def test_fallback_marks_experiments_as_unverified(self) -> None:
        fb = ld.fallback_fields(ld.validate_plan(GOOD_PLAN))
        self.assertIn("予想", fb["experiments"])
        self.assertIn("スキャッター", fb["concepts"])
        self.assertNotIn("pitfalls", fb)
        self.assertEqual(ld.fallback_fields(None), {})


class ReviewTest(unittest.TestCase):
    def test_full_lesson_scores_100(self) -> None:
        report = tr.review_finish(FULL_FINISH, LOG)
        self.assertEqual(report["score"], 100, report["missing"])
        self.assertEqual(report["missing"], [])

    def test_build_log_only_scores_low(self) -> None:
        bare = {"title": "T", "slug": "t", "overview": "o", "steps": "1. Grid を作る\n2. Scatter を作る"}
        report = tr.review_finish(bare, [])
        self.assertLess(report["score"], 20)
        self.assertGreaterEqual(len(report["missing"]), 7)

    def test_experiment_must_actually_be_run(self) -> None:
        no_run = [e for e in LOG if e["tool"] != "set_parameter"]
        report = tr.review_finish(FULL_FINISH, no_run)
        self.assertFalse(report["checks"]["experiments_done"])
        self.assertTrue(report["checks"]["experiments_written"])

    def test_failed_cook_does_not_count_as_experiment(self) -> None:
        log = [
            {"tool": "cook_node", "result": "ok"},
            {"tool": "set_parameter", "result": "ok"},
            {"tool": "cook_node", "result": "[エラー] 失敗"},
            {"tool": "set_parameter", "result": "ok"},
            {"tool": "cook_node", "result": "[エラー] 失敗"},
        ]
        self.assertEqual(tr.count_verified_experiments(log), 0)

    def test_experiments_counted(self) -> None:
        self.assertEqual(tr.count_verified_experiments(LOG), 2)

    def test_gap_message_lists_missing_and_empty_when_complete(self) -> None:
        self.assertEqual(tr.finish_gap_message(FULL_FINISH), "")
        message = tr.finish_gap_message({"steps": "1. 作る"})
        for key in ("learn", "concepts", "experiments", "polish", "next_lesson"):
            self.assertIn(f"`{key}`", message)
        self.assertIn("✅", message)

    def test_summarize(self) -> None:
        self.assertIn("100/100", tr.summarize(tr.review_finish(FULL_FINISH, LOG)))


class AgentAssemblyTest(unittest.TestCase):
    """TutorialAgent に組み込んだ部分（プロンプト・Markdown）。import できない環境では飛ばす。"""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import tutorial_agent
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"tutorial_agent をimportできません: {exc}") from exc
        cls.ta = tutorial_agent

    def _agent(self):
        agent = self.ta.TutorialAgent.__new__(self.ta.TutorialAgent)
        agent._model = "test"
        agent.executor = None
        return agent

    def test_template_formats_with_lesson_section(self) -> None:
        text = self.ta._SYSTEM_PROMPT_TEMPLATE.format(
            sandbox_path="/obj/x", kb_label="kb", rag_context="r", common_node_types="c", level="basic",
            level_instruction="L", prior_level_summary="", lesson_section=ld.plan_section(None, "basic"),
            reference_section="", requirements_section="", domain_sections="",
        )
        self.assertIn("教え方のルール", text)

    def test_level_instructions_are_a_learning_path(self) -> None:
        self.assertEqual(set(self.ta._LEVEL_INSTRUCTIONS), {"basic", "applied", "advanced"})
        self.assertIn("レッスン1", self.ta._LEVEL_INSTRUCTIONS["basic"])
        self.assertIn("レッスン3", self.ta._LEVEL_INSTRUCTIONS["advanced"])

    def test_markdown_orders_lesson_sections_for_the_video(self) -> None:
        result = self.ta.TutorialResult()
        result.completed = True
        result.title = "T"
        md = self._agent()._assemble_markdown("岩", dict(FULL_FINISH), result)
        order = [md.index(f"## {h}") for h in (
            "概要", "このレッスンで学ぶこと", "先に知っておく考え方", "手順",
            "パラメータを動かして確かめよう", "仕上げ", "コード・ノード構成", "ハマりポイント", "次のレッスン", "参考",
        )]
        self.assertEqual(order, sorted(order))

    def test_markdown_without_lesson_fields_keeps_old_shape(self) -> None:
        result = self.ta.TutorialResult()
        result.completed = True
        md = self._agent()._assemble_markdown("岩", {"title": "T", "steps": "1. a"}, result)
        self.assertNotIn("このレッスンで学ぶこと", md)
        self.assertIn("## 手順", md)

    def test_video_script_sees_lesson_sections_as_slides_with_templates(self) -> None:
        result = self.ta.TutorialResult()
        result.completed = True
        md = self._agent()._assemble_markdown("岩", dict(FULL_FINISH), result)
        headings = [h for h, _ in vs.extra_sections(md)]
        for h in ("このレッスンで学ぶこと", "先に知っておく考え方", "パラメータを動かして確かめよう", "仕上げ", "次のレッスン"):
            self.assertIn(h, headings)
            template = vs._template_section(h)
            self.assertGreaterEqual(len(template["narration"]), 20)
            self.assertFalse(vs.looks_like_code(template["narration"]))

    def test_finish_gate_asks_for_missing_then_stops_nagging(self) -> None:
        import houdini_tools

        ex = houdini_tools.HoudiniToolExecutor.__new__(houdini_tools.HoudiniToolExecutor)
        ex._pending_finish = None
        ex._finish_drafts = []
        bare = {"title": "T", "slug": "t", "overview": "o", "steps": "1. 作る"}
        first = ex._tool_finish_tutorial(dict(bare))
        self.assertIn("書き足しが必要", first)
        self.assertIn("`concepts`", first)
        second = ex._tool_finish_tutorial(dict(bare))
        self.assertIn("書き足しが必要", second)
        third = ex._tool_finish_tutorial(dict(bare))  # 3回目以降は催促しない（無限ループ防止）
        self.assertNotIn("書き足しが必要", third)
        self.assertIsNotNone(ex._pending_finish)

    def test_finish_gate_silent_when_complete(self) -> None:
        import houdini_tools

        ex = houdini_tools.HoudiniToolExecutor.__new__(houdini_tools.HoudiniToolExecutor)
        ex._pending_finish = None
        ex._finish_drafts = []
        self.assertNotIn("書き足しが必要", ex._tool_finish_tutorial(dict(FULL_FINISH)))

    def test_finish_schema_has_lesson_fields(self) -> None:
        import houdini_tools

        finish = next(t for t in houdini_tools.HOUDINI_TOOLS if t["name"] == "finish_tutorial")
        props = finish["input_schema"]["properties"]
        for key in tr.LESSON_FIELDS:
            self.assertIn(key, props)
        self.assertEqual(finish["input_schema"]["required"], ["title", "slug", "overview", "steps"])


if __name__ == "__main__":
    unittest.main()
