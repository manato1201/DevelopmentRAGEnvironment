"""説明のレベル（2026-10-27）: チュートリアルの「説明の書き方」、チャットの explain の送信、習熟度・説明レベルの表示の文面。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PANELS = Path(__file__).resolve().parents[1] / "python_panels"
sys.path.insert(0, str(PANELS))

import lesson_design as ld  # noqa: E402
import panel_info as pi  # noqa: E402
import rag_client as rc  # noqa: E402


class TutorialExplanationStyleTest(unittest.TestCase):
    def test_every_level_has_its_own_explanation_style(self):
        self.assertEqual(set(ld.EXPLANATION_STYLE), {"basic", "applied", "advanced"})
        styles = [ld.explanation_style(level) for level in ("basic", "applied", "advanced")]
        self.assertEqual(len(set(styles)), 3, "the three levels are explained differently")
        self.assertIn("初めて触る人", styles[0])
        self.assertIn("仕組み", styles[1])
        self.assertIn("設計判断", styles[2])
        self.assertEqual(ld.explanation_style("unknown"), styles[0], "unknown level falls back to basic")

    def test_explanation_gets_harder_as_levels_rise(self):
        basic, applied, advanced = (ld.EXPLANATION_STYLE[k] for k in ("basic", "applied", "advanced"))
        # basic: 用語を説明しながら・コードは出さない / applied: 基本用語は説明しない / advanced: 専門用語のまま・基本は省く
        self.assertIn("コード（VEX・式）は出しません", basic)
        self.assertIn("基本用語は、説明せずに使って", applied)
        self.assertIn("専門用語", advanced)
        self.assertIn("説明せず", advanced)
        self.assertIn("前のレッスンの内容は繰り返しません", advanced)

    def test_style_is_part_of_the_plan_prompt_and_the_agent_instruction(self):
        for level in ("basic", "applied", "advanced"):
            prompt = ld.build_plan_prompt("岩の散布", level)
            self.assertIn(ld.EXPLANATION_STYLE[level], prompt)
            for other in {"basic", "applied", "advanced"} - {level}:
                self.assertNotIn(ld.EXPLANATION_STYLE[other], prompt, "only the chosen level's style is given")
        import tutorial_agent as ta

        for level in ("basic", "applied", "advanced"):
            self.assertIn(ld.EXPLANATION_STYLE[level], ta._LEVEL_INSTRUCTIONS[level])
            title, _role = ld.LESSON_PATH[level]
            self.assertIn(title, ta._LEVEL_INSTRUCTIONS[level], "the build structure (lesson path) is kept")
        self.assertNotEqual(ta._LEVEL_INSTRUCTIONS["basic"], ta._LEVEL_INSTRUCTIONS["advanced"])


class ExplainClientTest(unittest.TestCase):
    def cfg(self, mode="cloudflare"):
        return {"mode": mode, "cf_url": "https://x.example", "cf_api_key": "k", "cf_namespaces": "", "local_port": 8766}

    def test_query_sends_explain_only_for_valid_values(self):
        for value in ("auto", "basic", "applied", "advanced"):
            with mock.patch.object(rc, "post_json", return_value={"answer": "a"}) as post:
                rc.RAGClient(self.cfg()).query("q", [], explain=value)
            self.assertEqual(post.call_args.args[1].get("explain"), value)
        for value in (None, "", "expert"):
            with mock.patch.object(rc, "post_json", return_value={"answer": "a"}) as post:
                rc.RAGClient(self.cfg()).query("q", [], explain=value)
            self.assertNotIn("explain", post.call_args.args[1])

    def test_local_mode_never_sends_explain(self):
        with mock.patch.object(rc, "post_json", return_value={"answer": "a"}) as post:
            rc.RAGClient(self.cfg("local")).query("q", [], explain="auto")
        self.assertNotIn("explain", post.call_args.args[1])

    def test_growth_calls(self):
        with mock.patch.object(rc, "post_json", return_value={"level": "applied"}) as post:
            self.assertEqual(rc.RAGClient(self.cfg()).growth(), {"level": "applied"})
        self.assertTrue(post.call_args.args[0].endswith("/me/growth"))
        self.assertEqual(post.call_args.kwargs.get("api_key"), "k")
        with mock.patch.object(rc, "post_json", return_value={"status": "ok"}) as post:
            self.assertTrue(rc.RAGClient(self.cfg()).growth_reset())
        self.assertTrue(post.call_args.args[0].endswith("/me/growth/reset"))
        self.assertEqual(rc.RAGClient(self.cfg("local")).growth(), {})
        self.assertFalse(rc.RAGClient(self.cfg("local")).growth_reset())


class DisplayTextTest(unittest.TestCase):
    def test_format_explain(self):
        self.assertEqual(pi.format_explain(None), "")
        self.assertEqual(pi.format_explain({}), "")
        self.assertEqual(pi.format_explain({"level": "basic", "mode": "fixed", "introduced": []}), "説明レベル: basic")
        text = pi.format_explain({"level": "applied", "mode": "auto", "introduced": ["PDG", "USD"]})
        self.assertEqual(text, "説明レベル: applied（おまかせ） ／ 紹介した用語: PDG、USD")

    def test_format_growth(self):
        self.assertEqual(pi.format_growth(None), "")
        text = pi.format_growth({"level": "basic", "score": 2.5, "termCount": 3, "nextAt": 6, "lowered": False, "knownTerms": [{"term": "SOP"}]})
        self.assertIn("習熟度: basic（用語 3個・2.5点）", text)
        self.assertIn("次のレベルまで あと 3.5点", text)
        self.assertIn("使いこなしている用語: SOP", text)
        top = pi.format_growth({"level": "advanced", "score": 30, "termCount": 20, "nextAt": None, "knownTerms": []})
        self.assertNotIn("次のレベルまで", top)
        lowered = pi.format_growth({"level": "basic", "score": 9, "termCount": 5, "nextAt": 6, "lowered": True, "knownTerms": []})
        self.assertIn("一段やさしく", lowered)
        self.assertIn("あと 0.0点", lowered, "never negative")

    def test_choices_match_the_worker(self):
        self.assertEqual([v for v, _ in pi.EXPLAIN_CHOICES], ["auto", "basic", "applied", "advanced"])


if __name__ == "__main__":
    unittest.main()
