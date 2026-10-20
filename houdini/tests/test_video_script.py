"""video_script.py のテスト（標準の unittest。Houdini・Claude・ネットワークは使わない）。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import video_script as vs  # noqa: E402

CODE_RESULT = (
    'emit のパラメータを設定: Run Over を 0、VEXpression を int n = 30000;\nfloat rin = chf("inner_radius");\n'
    "for (int i = 0; i < n; i++) {\n    addpoint(0, set(0, 0, 0));\n}"
)


def make_steps(tmp: Path) -> list[dict]:
    img = tmp / "step.png"
    img.write_bytes(b"png")
    return [
        {"step": 1, "tool": "create_node", "result": "Object レベルに「Geometry」ノードを作り、名前を geo1 にする。この中で作業する",
         "tool_result": "ok", "viewport": str(img), "network": str(img)},
        {"step": 2, "tool": "create_node", "result": "「Attribute Wrangle」ノード（attribwrangle）を作り、名前を emit にする",
         "tool_result": "ok", "viewport": None, "network": str(img)},
        {"step": 3, "tool": "set_parameter", "result": CODE_RESULT, "tool_result": CODE_RESULT, "viewport": str(img), "network": str(img)},
        {"step": 4, "tool": "connect_nodes", "result": "emit の出力を、merge1 の入力につなぐ", "tool_result": "ok", "viewport": None, "network": str(img)},
        {"step": 5, "tool": "cook_node", "result": "merge1 を評価（cook）して、エラーが出ないことを確認する", "tool_result": "ok",
         "viewport": str(img), "network": None},
    ]


GOOD_STEP = "ここでは、点を作るための準備をします。ジオメトリノードは、形を作るための作業場所です。まず、この中に入って作業を始めましょう。"


def good_model(steps: list[dict]) -> dict:
    return {
        "intro": {"narration": "この動画では、点をたくさん並べて、円盤の形を作ります。はじめての方でも、順番にやれば大丈夫です。",
                  "points": ["点で円盤を作る", "ノードのつなぎ方を知る", "三つ目は使われない"]},
        "steps": [{"step": s["step"], "heading": f"手順{s['step']}の見出し", "narration": GOOD_STEP, "points": ["短い文"]} for s in steps],
        "structure": {"narration": "ここまでの流れを、上から下へ順に見てみましょう。点を作って、まとめて、結果を確かめています。"},
        "outro": {"narration": "お疲れさまでした。次は、数字を変えて、形がどう変わるかを試してみましょう。", "points": ["数字を変えてみる"]},
    }


class UsableSteps(unittest.TestCase):
    def test_keeps_only_steps_with_an_image_and_a_sentence(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            steps.append({"step": 6, "tool": "x", "result": "操作", "viewport": str(Path(d) / "missing.png"), "network": None})
            steps.append({"step": 7, "tool": "x", "result": "   ", "viewport": str(Path(d) / "step.png"), "network": None})
            self.assertEqual([s["step"] for s in vs.usable_steps(steps)], [1, 2, 3, 4, 5])


class CodeDetection(unittest.TestCase):
    def test_code_and_prose(self):
        for code in ('float rin = chf("a");', "@P.y += sin(@P.x);", "for (int i = 0; i < n; i++) { a(); }", "```vex\nint a = 1;\n```"):
            self.assertTrue(vs.looks_like_code(code), code)
        for prose in ("点を円盤の形に並べます。", "n = 30000 個の点を作ります。", "Run Over を Detail にします。"):
            self.assertFalse(vs.looks_like_code(prose), prose)


class CleanNarration(unittest.TestCase):
    def test_strips_markdown_and_newlines(self):
        self.assertEqual(vs.clean_narration("**ここでは**、点を作ります。\nつぎに、色を付けます。" + "あ" * 20, 300, 10),
                         "ここでは、点を作ります。 つぎに、色を付けます。" + "あ" * 20)

    def test_rejects_code_too_short_and_english_heavy(self):
        self.assertIsNone(vs.clean_narration("float r = rand(i); int n = 5;", 300))
        self.assertIsNone(vs.clean_narration("短い。", 300, 40))
        self.assertIsNone(vs.clean_narration("This is an English sentence about attribute wrangle nodes.", 300))
        self.assertIsNone(vs.clean_narration(123, 300))  # type: ignore[arg-type]

    def test_cuts_at_a_sentence_end_or_rejects(self):
        text = "一つ目の文です。" * 20
        cut = vs.clean_narration(text, 50, 10)
        self.assertIsNotNone(cut)
        self.assertLessEqual(len(cut), 50)
        self.assertTrue(cut.endswith("。"))
        self.assertIsNone(vs.clean_narration("あ" * 100, 50, 10))  # no sentence end to cut at

    def test_english_terms_become_katakana(self):
        out = vs.clean_narration("Attribute Wrangleノードは、VEXを書くための場所です。" + "あ" * 20, 300, 10)
        self.assertIn("アトリビュートラングル", out)
        self.assertIn("ベックス", out)
        self.assertNotIn("Wrangle", out)

    def test_points_and_heading(self):
        self.assertEqual(vs.clean_points(["a", "b", "c"]), ["a", "b"])
        self.assertEqual(vs.clean_points(["float a = 1;", "ok"]), ["ok"])
        self.assertEqual(vs.clean_points("not a list"), [])
        self.assertTrue(len(vs.clean_points(["あ" * 100])[0]) <= vs.POINT_MAX_CHARS)
        self.assertEqual(vs.clean_heading("float a = 1;"), "")
        self.assertTrue(len(vs.clean_heading("あ" * 60)) <= 24)


class Assemble(unittest.TestCase):
    def test_all_valid_is_claude(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            script, source, notes = vs.assemble_script(good_model(steps), steps, "ブラックホール", "概要の文です。")
            self.assertEqual(source, "claude")
            self.assertEqual(notes, [])
            self.assertEqual([s["step"] for s in script["steps"]], [1, 2, 3, 4, 5])
            self.assertEqual(len(script["intro"]["points"]), 2)  # at most 2 on-screen lines
            self.assertIn("structure", script)
            self.assertEqual(script["version"], vs.SCRIPT_VERSION)

    def test_invalid_step_is_replaced_by_the_template(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            model = good_model(steps)
            model["steps"][2]["narration"] = 'float rin = chf("a"); for (int i = 0; i < n; i++) { a(); }'  # code read aloud
            script, source, notes = vs.assemble_script(model, steps, "t", "")
            self.assertEqual(source, "claude+template")
            self.assertEqual(len(notes), 1)
            step3 = script["steps"][2]
            self.assertFalse(vs.looks_like_code(step3["narration"]))
            self.assertIn("プログラム", step3["narration"])

    def test_no_model_output_gives_a_complete_template_script(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            script, source, _ = vs.assemble_script(None, steps, "ブラックホール", "点を並べて円盤を作ります。詳しくは本文。")
            self.assertEqual(source, "template")
            self.assertEqual(len(script["steps"]), 5)
            for s in script["steps"]:
                self.assertTrue(s["narration"].strip(), s)
                self.assertFalse(vs.looks_like_code(s["narration"]), s)
                self.assertNotIn("n = 30000", s["narration"])
            self.assertIn("ブラックホール", script["intro"]["narration"])
            self.assertTrue(script["outro"]["narration"])

    def test_template_never_reads_code(self):
        with tempfile.TemporaryDirectory() as d:
            code_step = make_steps(Path(d))[2]
            t = vs._template_step(code_step)
            self.assertNotIn("VEXpression", t["narration"])
            self.assertNotIn("addpoint", t["narration"])
            self.assertTrue(all(not vs.looks_like_code(p) for p in t["points"]))

    def test_template_explains_node_creation(self):
        with tempfile.TemporaryDirectory() as d:
            t = vs._template_step(make_steps(Path(d))[1])
            self.assertIn("アトリビュートラングル", t["narration"])
            self.assertIn("emit", t["narration"])
            self.assertIn("ノードは", t["narration"])


class ExtraSections(unittest.TestCase):
    MD = """---
title: x
---

## 概要

本文

## 手順

### 1. a

## コード・ノード構成

ノード一覧

## ハマりポイント

setpointattrib に float 変数を渡すと Ambiguous call エラーになります。

## 応用・発展のヒント

pow(u,3) に変えると密集度が変わる。

## 参考

利用率: 0%
"""

    def test_finds_only_the_sections_the_engine_does_not_handle(self):
        found = vs.extra_sections(self.MD)
        self.assertEqual([h for h, _ in found], ["ハマりポイント", "応用・発展のヒント"])
        self.assertIn("Ambiguous call", found[0][1])

    def test_template_never_reads_the_expert_text(self):
        for heading, body in vs.extra_sections(self.MD):
            t = vs._template_section(heading)
            self.assertNotIn("setpointattrib", t["narration"])
            self.assertNotIn("pow(", t["narration"])
            self.assertFalse(vs.looks_like_code(t["narration"]))
            self.assertGreaterEqual(len(t["narration"]), vs.STEP_NARRATION_MIN)
            self.assertNotEqual(body[:20], t["narration"][:20])

    def test_model_sections_are_used_and_bad_ones_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            model = good_model(steps)
            model["sections"] = [
                {"match": "ハマりポイント", "heading": "つまずきやすいところ",
                 "narration": "数字を入れるときに、型が合わないと、エラーになることがあります。エラーの文をよく読むと、直し方が分かります。",
                 "points": ["エラーの文を読む"]},
                {"match": "応用・発展のヒント", "heading": "試してみよう", "narration": "pow(u, 3); float r = 1;", "points": []},
            ]
            script, source, notes = vs.assemble_script(model, steps, "t", "", vs.extra_sections(self.MD))
            secs = {s["match"]: s for s in script["sections"]}
            self.assertEqual(secs["ハマりポイント"]["heading"], "つまずきやすいところ")
            self.assertIn("エラーの文", secs["ハマりポイント"]["narration"])
            self.assertEqual(secs["応用・発展のヒント"]["heading"], "もっと試してみよう")  # replaced by the template
            self.assertTrue(any("応用" in n for n in notes))
            self.assertEqual(source, "claude")

    def test_prompt_includes_the_sections(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            user = vs.build_user_prompt("t", "excerpt", steps, vs.extra_sections(self.MD))
            self.assertIn("## ハマりポイント", user)
            self.assertIn("その他の節", user)


class ModelJson(unittest.TestCase):
    def test_extracts_json_from_fenced_or_chatty_output(self):
        self.assertEqual(vs.parse_model_json('前置き\n```json\n{"a": 1}\n```\n後書き'), {"a": 1})
        self.assertIsNone(vs.parse_model_json("JSONではない"))
        self.assertIsNone(vs.parse_model_json('{"a": '))
        self.assertIsNone(vs.parse_model_json("[1, 2]"))


class BuildScript(unittest.TestCase):
    MD = "---\ntitle: テスト用チュートリアル\n---\n\n## 概要\n\nBoxを作って色を付けます。\n\n## 手順\n\n### 1. 準備\n作業します。\n\n## コード・ノード構成\n\nサンドボックス: /obj/x\n- `geo1/emit` : attribwrangle (snippet=int n = 1;)\n"

    def test_excerpt_drops_frontmatter_and_node_dump(self):
        title, summary, excerpt = vs.tutorial_excerpt(self.MD)
        self.assertEqual(title, "テスト用チュートリアル")
        self.assertEqual(summary, "Boxを作って色を付けます。")
        self.assertIn("準備", excerpt)
        self.assertNotIn("サンドボックス", excerpt)
        self.assertNotIn("title:", excerpt)

    def test_uses_claude_output_and_passes_the_steps_without_code_for_reading(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            seen = {}

            def complete(system, user):
                seen["system"], seen["user"] = system, user
                return "```json\n" + json.dumps(good_model(steps), ensure_ascii=False) + "\n```", {"input_tokens": 100, "output_tokens": 200}

            script, message, usage = vs.build_script(self.MD, steps, complete)
            self.assertEqual(script["source"], "claude")
            self.assertIn("Claudeが書いた台本", message)
            self.assertEqual(usage["output_tokens"], 200)
            self.assertIn("初めて", seen["system"])
            self.assertIn("読み上げ・転記は禁止", seen["user"])  # code is only given as material
            self.assertIn('"step": 3', seen["user"])

    def test_retries_once_on_unreadable_output(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            calls = []

            def complete(system, user):
                calls.append(1)
                return ("読めない出力", {}) if len(calls) == 1 else (json.dumps(good_model(steps), ensure_ascii=False), {})

            script, _, _ = vs.build_script(self.MD, steps, complete)
            self.assertEqual(len(calls), 2)
            self.assertEqual(script["source"], "claude")

    def test_api_failure_and_no_client_fall_back_to_the_template(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))

            def boom(system, user):
                raise RuntimeError("429 予算超過")

            script, message, _ = vs.build_script(self.MD, steps, boom)
            self.assertEqual(script["source"], "template")
            self.assertIn("失敗", message)
            script2, message2, _ = vs.build_script(self.MD, steps, None)
            self.assertEqual(script2["source"], "template")
            self.assertIn("接続できない", message2)

    def test_no_usable_steps_means_no_script(self):
        script, message, _ = vs.build_script(self.MD, [], None)
        self.assertIsNone(script)
        self.assertIn("手順が無い", message)


class PrepareFile(unittest.TestCase):
    def test_writes_the_file_the_engine_reads(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = tmp / "sample_20261019.md"
            md.write_text(BuildScript.MD, encoding="utf-8")
            steps = make_steps(tmp)
            path, message = vs.prepare_script_file(md, steps, lambda s, u: (json.dumps(good_model(steps), ensure_ascii=False), {}))
            self.assertEqual(path, tmp / "sample_20261019_video_script.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            # The contract with RAGReel (engine/src/ingest/houdini_script.h)
            self.assertEqual(data["version"], 1)
            self.assertIn(data["source"], ("claude", "claude+template", "template"))
            self.assertIsInstance(data["intro"]["narration"], str)
            for s in data["steps"]:
                self.assertIsInstance(s["step"], int)
                self.assertIsInstance(s["narration"], str)
                self.assertLessEqual(len(s["points"]), 2)
            self.assertIn("台本", message)

    def test_never_raises(self):
        path, message = vs.prepare_script_file(Path("Z:/no/such/file.md"), [], None)
        self.assertIsNone(path)
        self.assertIn("台本", message)


if __name__ == "__main__":
    unittest.main()
