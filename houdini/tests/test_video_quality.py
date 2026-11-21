"""動画の台本・素材の品質（2026-11-17。実証実験の「ワードと位置が合っているか」「対象が字幕に無い」「品質に差がありすぎる」
「参照した情報源の重複」「出典なし」）のテスト。video_script.py / video_factory_bridge.py / gallery_upload.py の純粋な部分。
Houdini・Claude・ネットワークは使わない（ギャラリーは、手元の偽物）。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_video_quality.py -v
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import gallery_upload as gu  # noqa: E402
import video_factory_bridge as vfb  # noqa: E402
import video_script as vs  # noqa: E402


def write_png(path: Path, width: int, height: int = 720) -> Path:
    """幅・高さだけが正しい、最小の PNG ヘッダ（品質チェッカーは、ヘッダしか読まない）。"""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\0\0\0\0")
    return path


# 実験で出た字幕。何を 4 にしたのかが、字幕に無い。
BAD_SUBTITLE = "4にすると、最大値は約0.998になりました。"

SET_ENTRY = {
    "step": 7, "tool": "set_parameter", "result": "noise1 のパラメータを設定: Element Size を 4",
    "tool_result": "geo1/noise1.elementsize = 4", "network_kind": "parameter",
}


class StepFactsTest(unittest.TestCase):
    def test_set_parameter_facts_from_the_instruction(self) -> None:
        facts = vs.step_facts(SET_ENTRY)
        self.assertEqual(facts["action"], "set")
        self.assertEqual(facts["node"], "noise1")
        self.assertEqual(facts["node_path"], "geo1/noise1", "the hierarchy comes from tool_result")
        self.assertEqual([(c["label"], c["new"]) for c in facts["changes"]], [("Element Size", "4")])

    def test_more_changes_are_counted(self) -> None:
        facts = vs.step_facts({"tool": "set_parameter", "result": "emit のパラメータを設定: A を 1、B を 2、C を 3 ほか2件"})
        self.assertEqual([c["label"] for c in facts["changes"]], ["A", "B", "C"])
        self.assertEqual(facts["more"], 2)

    def test_code_step_and_other_tools(self) -> None:
        code = vs.step_facts({"tool": "set_parameter", "result": "emit の「VEXpression」欄に、次のコードを入力する\nint n = 1;"})
        self.assertEqual((code["action"], code["node"], code["changes"][0]["label"]), ("code", "emit", "VEXpression"))
        delete = vs.step_facts({"tool": "delete_node", "result": "不要になった paper_blast を削除する"})
        self.assertEqual((delete["action"], delete["node"]), ("delete", "paper_blast"))
        connect = vs.step_facts({"tool": "connect_nodes", "result": "emit の出力を、merge1 の2番目の入力につなぐ"})
        self.assertEqual(connect["connect"][:2], ("emit", "merge1"))
        cook = vs.step_facts({"tool": "cook_node", "result": "merge1 を評価（cook）して、エラーが出ないことを確認する"})
        self.assertEqual((cook["action"], cook["node"]), ("cook", "merge1"))
        create = vs.step_facts({"tool": "create_node", "result": "「Attribute Wrangle」ノード（attribwrangle）を作り、名前を emit にする",
                                "tool_result": "作成しました: geo1/emit（タイプ: attribwrangle）"})
        self.assertEqual((create["action"], create["node"], create["node_path"]), ("create", "emit", "geo1/emit"))

    def test_recorded_changes_are_preferred(self) -> None:
        entry = dict(SET_ENTRY, changes=[{"label": "Run Over", "name": "class", "old": "2", "new": "detail", "tab": "Code"}])
        facts = vs.step_facts(entry)
        self.assertEqual((facts["changes"][0]["old"], facts["changes"][0]["tab"]), ("2", "Code"))


class DisplayValueTest(unittest.TestCase):
    def test_toggle_and_menu_use_labels_not_numbers(self) -> None:
        self.assertEqual(vs.display_value({"new": "1", "kind": "toggle"}), "オン")
        self.assertEqual(vs.display_value({"new": "0", "kind": "toggle"}), "オフ")
        self.assertEqual(vs.display_value({"new": "2", "kind": "menu", "menu_labels": ["Detail", "Primitives", "Points"]}), "Points")
        self.assertEqual(vs.display_value({"new": "0.8 0.8 0.8"}), "すべて0.8")
        self.assertEqual(vs.display_value({"new": "4"}), "4", "no kind information: the value is left as is")


class TargetInNarrationTest(unittest.TestCase):
    def test_before_the_subtitle_had_no_target(self) -> None:
        """前: 字幕「4にすると、…」には、ノード名もパラメータ名も無い（実験で確認した文）。"""
        facts = vs.step_facts(SET_ENTRY)
        self.assertEqual(vs.missing_targets(facts, BAD_SUBTITLE), ["noise1", "Element Size"])
        self.assertEqual(vs.dangling_value_sentences(BAD_SUBTITLE), [BAD_SUBTITLE.rstrip("。")])

    def test_after_a_target_sentence_is_put_first(self) -> None:
        facts = vs.step_facts(SET_ENTRY)
        spoken, shown, added = vs.ensure_target(BAD_SUBTITLE, BAD_SUBTITLE, facts, 320)
        self.assertTrue(added)
        self.assertTrue(shown.startswith("noise1の「Element Size」を、4にします。"))
        self.assertEqual(vs.missing_targets(facts, spoken, shown), [])
        self.assertEqual(vs.dangling_value_sentences(shown, ["noise1", "Element Size"]), [], "the value is no longer ambiguous")

    def test_nothing_is_added_when_the_target_is_already_named(self) -> None:
        facts = vs.step_facts(SET_ENTRY)
        text = "noise1の要素サイズ、Element Sizeを4にすると、模様が細かくなります。"
        self.assertEqual(vs.ensure_target(text, text, facts, 320), (text, text, False))

    def test_katakana_reading_counts_as_naming(self) -> None:
        facts = vs.step_facts({"tool": "set_parameter", "result": "emit のパラメータを設定: Run Over を 0"})
        self.assertEqual(vs.missing_targets(facts, "emitのランオーバーを変えます。"), [])

    def test_length_limit_drops_trailing_sentences_not_the_target(self) -> None:
        facts = vs.step_facts(SET_ENTRY)
        body = "".join(f"説明の{i}番目の文です。" for i in range(1, 30))
        spoken, shown, added = vs.ensure_target(body, body, facts, 120)
        self.assertTrue(added)
        self.assertLessEqual(len(spoken), 120)
        self.assertTrue(spoken.startswith("noise1の"))
        self.assertEqual(spoken.count("。"), shown.count("。"))

    def test_delete_says_delete(self) -> None:
        facts = vs.step_facts({"tool": "delete_node", "result": "不要になった paper_blast を削除する"})
        spoken, _shown, added = vs.ensure_target("整理して、流れを読みやすくします。", "整理して、流れを読みやすくします。", facts, 320)
        self.assertTrue(added)
        self.assertIn("paper_blastを消します。", spoken)

    def test_menu_value_is_said_by_label(self) -> None:
        entry = {"tool": "set_parameter", "result": "x のパラメータを設定: Run Over を 2", "changes": [
            {"label": "Run Over", "name": "class", "old": "0", "new": "2", "kind": "menu", "menu_labels": ["Detail", "Primitives", "Points"]}]}
        spoken, shown = vs.target_sentence(vs.step_facts(entry))
        self.assertIn("Detailから", shown.replace("「Run Over」を、", ""))
        self.assertIn("Pointsに変えます", shown)
        self.assertNotIn("2に", shown)


class SlideDetailTest(unittest.TestCase):
    def test_points_show_hierarchy_tab_and_before_after(self) -> None:
        entry = dict(SET_ENTRY, changes=[{"label": "Run Over", "name": "class", "old": "2", "new": "detail", "tab": "Code",
                                         "kind": "menu", "menu_labels": ["Detail", "Primitives", "Points"]}])
        points = vs.facts_points(vs.step_facts(entry))
        self.assertEqual(points, ["geo1/noise1 › Code › Run Over", "Points → detail"])
        self.assertTrue(all(len(p) <= vs.POINT_MAX_CHARS for p in points))

    def test_long_path_keeps_the_parameter_name(self) -> None:
        line = vs._fit_path_line(["tornado/stage_one/vortex_points_with_a_long_name", "Code", "Run Over"])
        self.assertLessEqual(len(line), vs.POINT_MAX_CHARS)
        self.assertTrue(line.endswith("Code › Run Over"))

    def test_delete_points_say_remove(self) -> None:
        points = vs.facts_points(vs.step_facts({"tool": "delete_node", "result": "不要になった paper_blast を削除する"}))
        self.assertIn("消す", points[0])

    def test_detail_block(self) -> None:
        entry = dict(SET_ENTRY, changes=[{"label": "Run Over", "name": "class", "old": "2", "new": "detail", "tab": "Code"}])
        detail = vs.step_detail(vs.step_facts(entry), "点ごとの繰り返しを避ける")
        self.assertEqual(detail["node_path"], "geo1/noise1")
        self.assertEqual(detail["location"], "Code › Run Over")
        self.assertEqual(detail["changes"][0]["old"], "2")
        self.assertEqual(detail["purpose"], "点ごとの繰り返しを避ける")


def make_step_files(tmp: Path, entry: dict, width: int = 2560) -> dict:
    net = write_png(tmp / f"step_{entry['step']:03d}_network.png", width)
    return dict(entry, network=str(net), viewport=str(write_png(tmp / f"step_{entry['step']:03d}_viewport.png", 1920, 1080)))


class AssembleKeepsTargetsTest(unittest.TestCase):
    def test_a_bad_model_narration_gets_its_target_and_detail(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), SET_ENTRY)
            model = {"steps": [{"step": 7, "heading": "細かさを変える", "narration": BAD_SUBTITLE + "ここで、模様の細かさが変わるのが分かります。",
                                "points": ["模様が細かくなる"], "purpose": "模様の細かさを決める"}]}
            script, source, notes = vs.assemble_script(model, [entry], "t", "")
            step = script["steps"][0]
            self.assertEqual(source, "claude")
            self.assertTrue(any("対象の名前" in n for n in notes))
            self.assertIn("noise1", step.get("subtitle", step["narration"]))
            self.assertEqual(step["points"][0], "geo1/noise1 › Element Size")
            self.assertEqual(step["detail"]["purpose"], "模様の細かさを決める")
            self.assertEqual(step["source"], "claude")

    CREATE_ENTRY = {
        "step": 3, "tool": "create_node", "result": "「Scatter」ノード（scatter）を作り、名前を scatter1 にする",
        "tool_result": "作成しました: geo1/scatter1（タイプ scatter）",
    }

    def _create_purpose(self, recorded, model_purpose=None, with_model=True):
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), dict(self.CREATE_ENTRY, **({} if recorded is None else {"purpose": recorded})))
            model = ({"steps": [{"step": 3, "heading": "点を散らす", "narration": "Scatterノード、scatter1を作ります。面の上に点をばらまいて、あとでコピーする位置を決めます。この点の数で、できあがりの密度が変わります。",
                                 "points": [], "purpose": model_purpose}]} if with_model else None)
            script, _source, _notes = vs.assemble_script(model, [entry], "t", "")
            return script["steps"][0]["detail"].get("purpose")

    def test_recorded_purpose_comes_first_for_created_nodes(self) -> None:
        """houdini_tools が記録した purpose（entry["purpose"]）を、モデルの purpose・定型文より先に使う。"""
        self.assertEqual(self._create_purpose("面に点を散らして、コピー先にする", "モデルの目的"), "面に点を散らして、コピー先にする")
        self.assertEqual(self._create_purpose("面に点を散らして、コピー先にする", with_model=False), "面に点を散らして、コピー先にする")

    def test_purpose_falls_back_to_the_old_order_when_nothing_is_recorded(self) -> None:
        for recorded in (None, "", "   ", None):
            self.assertEqual(self._create_purpose(recorded, "モデルの目的"), "モデルの目的")
        # 定型文（_NODE_HELP）。前は「、」の手前だけを取り、「スキャッターは」になっていた
        fallback = self._create_purpose(None, with_model=False)
        self.assertTrue(fallback)
        self.assertFalse(fallback.endswith("は"), fallback)
        self.assertEqual(vs._help_purpose("sphere"), "球の形を作るノードです")
        for odd in (5, ["x"], {"a": 1}):  # 型が違う記録でも、落ちない
            self.assertEqual(self._create_purpose(odd, "モデルの目的"), "モデルの目的")

    def test_template_steps_also_name_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), SET_ENTRY)
            script, source, _ = vs.assemble_script(None, [entry], "t", "")
            step = script["steps"][0]
            self.assertEqual(source, "template")
            self.assertEqual(vs.missing_targets(vs.step_facts(entry), step["narration"], step.get("subtitle", "")), [])
            self.assertEqual(step["source"], "template")

    def test_user_prompt_gives_the_model_the_target_and_changes(self) -> None:
        entry = dict(SET_ENTRY, changes=[{"label": "Run Over", "name": "class", "old": "0", "new": "2", "tab": "Code",
                                         "kind": "menu", "menu_labels": ["Detail", "Primitives", "Points"]}])
        prompt = vs.build_user_prompt("t", "本文", [entry])
        self.assertIn("対象ノード", prompt)
        self.assertIn("geo1/noise1", prompt)
        self.assertIn("Points", prompt, "the menu label is given, not just the number")

    def test_prompt_demands_targets_labels_and_delete_wording(self) -> None:
        prompt = vs.system_prompt("basic")
        for phrase in ("対象（ノード名と、変えるパラメータの表示名）を必ず言う", "数字で言わない", "「〇〇を消します」", '"purpose"'):
            self.assertIn(phrase, prompt)


class QualityCheckerTest(unittest.TestCase):
    def check(self, entry: dict, narration: str, **extra) -> list[str]:
        script = {"steps": [dict({"step": entry["step"], "narration": narration}, **extra)], "sources": [{"file": "a", "namespace": "n"}]}
        return [i["code"] for i in vs.check_video_quality(script, [entry])["issues"]]

    def test_good_step_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), SET_ENTRY)
            report = vs.check_video_quality(
                {"steps": [{"step": 7, "narration": "noise1のElement Sizeを4にします。"}], "sources": [{"file": "a", "namespace": "n"}]}, [entry])
            self.assertTrue(report["ok"], report)
            self.assertEqual((report["errors"], report["warnings"]), (0, 0))

    def test_the_experiment_subtitle_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), SET_ENTRY)
            codes = self.check(entry, BAD_SUBTITLE)
            self.assertIn("target_not_named", codes)
            self.assertIn("dangling_value", codes)
            report = vs.check_video_quality({"steps": [{"step": 7, "narration": BAD_SUBTITLE}], "sources": [{"file": "a"}]}, [entry])
            self.assertFalse(report["ok"])
            self.assertTrue(any("手順7" in line for line in vs.format_quality_report(report)))

    def test_missing_visual_and_parameter_view(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = dict(SET_ENTRY, network=str(Path(d) / "missing.png"), viewport=None)
            codes = self.check(entry, "noise1のElement Sizeを4にします。")
            self.assertIn("no_visual", codes)
            self.assertIn("no_target_view", codes)

    def test_small_image_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), SET_ENTRY, width=640)
            self.assertIn("image_small", self.check(entry, "noise1のElement Sizeを4にします。"))

    def test_unreadable_diagram_is_an_error_from_the_capture_meta(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), {"step": 3, "tool": "create_node", "result": "「Null」ノード（null）を作り、名前を out にする"})
            Path(entry["network"] + ".meta.json").write_text(
                json.dumps({"kind": "node_diagram", "name_pt": 3.8, "fits": False, "overview": False}), encoding="utf-8")
            self.assertIn("diagram_unreadable", self.check(entry, "outを作ります。"))
            Path(entry["network"] + ".meta.json").write_text(
                json.dumps({"kind": "node_diagram", "name_pt": 12.6, "fits": True, "overview": False}), encoding="utf-8")
            self.assertNotIn("diagram_unreadable", self.check(entry, "outを作ります。"))

    def test_code_steps_need_the_enlarged_card(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), {"step": 4, "tool": "set_parameter", "network_kind": "parameter",
                                              "result": "emit の「VEXpression」欄に、次のコードを入力する\nint n = 1;"})
            self.assertIn("code_not_enlarged", self.check(entry, "emitのVEXpressionに、コードを入力します。"))
            Path(entry["network"] + ".meta.json").write_text(json.dumps({"kind": "code_card", "lines_hidden": 5}), encoding="utf-8")
            codes = self.check(entry, "emitのVEXpressionに、コードを入力します。")
            self.assertNotIn("code_not_enlarged", codes)
            self.assertIn("code_hidden", codes)

    def test_delete_must_say_delete(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), {"step": 9, "tool": "delete_node", "result": "不要になった paper_blast を削除する"})
            self.assertIn("delete_wording", self.check(entry, "paper_blastを整理します。"))
            self.assertNotIn("delete_wording", self.check(entry, "paper_blastを消します。"))

    def test_numeric_choice_and_long_subtitle(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), dict(SET_ENTRY, changes=[
                {"label": "Keep Position", "name": "keeppos", "old": "0", "new": "1", "kind": "toggle"}]))
            self.assertIn("numeric_choice", self.check(entry, "noise1のKeep Positionを1にします。"))
            long = "noise1のElement Sizeを4にします。" + "あ" * 70 + "。"
            self.assertIn("subtitle_long", self.check(entry, long))

    def test_template_fallback_is_only_info_and_sources_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), SET_ENTRY)
            script = {"steps": [{"step": 7, "narration": "noise1のElement Sizeを4にします。", "source": "template"}], "sources": []}
            report = vs.check_video_quality(script, [entry])
            codes = {i["code"]: i["level"] for i in report["issues"]}
            self.assertEqual(codes["template_fallback"], "info")
            self.assertEqual(codes["sources_empty"], "warn")
            dup = {"steps": [], "sources": [{"file": "A", "namespace": "n"}, {"file": "a", "namespace": "N"}]}
            self.assertEqual([i["code"] for i in vs.check_video_quality(dup, [])["issues"]], ["sources_duplicate"])

    def test_issues_are_sorted_by_severity(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), SET_ENTRY, width=640)
            script = {"steps": [{"step": 7, "narration": BAD_SUBTITLE}], "sources": [{"file": "a"}]}
            levels = [i["level"] for i in vs.check_video_quality(script, [entry])["issues"]]
            self.assertEqual(levels, sorted(levels, key=lambda x: {"error": 0, "warn": 1, "info": 2}[x]))

    def test_broken_inputs_do_not_crash_the_checker(self) -> None:
        # 台本・手順の記録・画像の補足情報が壊れていても、品質チェックで台本の生成を止めない（check_video_quality は、build_script から呼ばれる）
        for script, steps in [
            (None, None), ({}, [{}]), ({"steps": ["x", 5], "sections": [None], "images": "abc"}, ["not a dict", None]),
            ({"steps": [{"step": 1}]}, [{"step": "a", "tool": "delete_node", "result": 5}, {"step": 2, "tool": "cook_node"}]),
            ({"sources": [None, "x", {"file": None}]}, []),
        ]:
            report = vs.check_video_quality(script, steps)  # type: ignore[arg-type]
            self.assertIn("ok", report)

    def test_corrupt_capture_meta_is_ignored_not_fatal(self) -> None:
        for meta in ('{"kind": "node_diagram", "name_pt": null}', '{"kind": "node_diagram", "name_pt": "abc"}',
                     '{"kind": "code_card", "lines_hidden": "x"}', "[1]", "broken"):
            with tempfile.TemporaryDirectory() as d:
                entry = make_step_files(Path(d), SET_ENTRY)
                Path(entry["network"] + ".meta.json").write_text(meta, encoding="utf-8")
                vs.check_step_quality(entry, None)  # 例外にならない

    def test_min_name_size_matches_the_capture_side(self) -> None:
        import types
        sys.modules.setdefault("hou", types.ModuleType("hou"))
        import screen_capture
        self.assertEqual(vs.MIN_NAME_PT, screen_capture.MIN_NAME_PT)

    def test_build_script_reports_quality_and_sources(self) -> None:
        md = (
            "---\ntitle: テスト\n---\n\n## 概要\n\n点を散らします。\n\n## 手順\n\n### 1. 作る\n\n## 参考\n\n"
            "- [1] ✅ 引用済み Shelf tools（houdini22shelfindex）\n- [2] ⬜ 未引用 Labs Fire Presets（houdini22）\n"
            "- [3] ⬜ 未引用 Shelf tools（houdini22shelfindex）\n"
        )
        with tempfile.TemporaryDirectory() as d:
            entry = make_step_files(Path(d), SET_ENTRY)
            script, message, _usage = vs.build_script(md, [entry], None)
            self.assertEqual([s["file"] for s in script["sources"]], ["Shelf tools", "Labs Fire Presets"])
            self.assertIn("quality", script)
            self.assertEqual(script["quality"]["errors"], 0)
            self.assertNotIn("要修正", message)


class SourcesTest(unittest.TestCase):
    MD = (
        "## 参考\n\n- [1] ✅ 引用済み Shelf tools（houdini22shelfindex）\n- [2] ⬜ 未引用 Labs Fire Presets（houdini22）\n"
        "- [3] ⬜ 未引用 Shelf tools（houdini22shelfindex）\n- [4] ⬜ 未引用 houdini22shelfindex（houdini22）\n"
        "- [5] ✅ 引用済み houdini22shelfindex（houdini22）\n\n## 次\n- [9] ⬜ 未引用 対象外（x）\n"
    )

    def test_before_the_same_document_appeared_twice(self) -> None:
        """前: 参考の行は、同じ資料の別の断片ごとに 1 行ずつ出ていた（Shelf tools、houdini22shelfindex が 2 件ずつ）。"""
        raw = vs.parse_md_sources(self.MD)
        self.assertEqual(len(raw), 5)
        self.assertEqual([r["title"] for r in raw].count("Shelf tools"), 2)

    def test_after_duplicates_are_merged_and_cited_wins(self) -> None:
        merged = vs.dedupe_sources(vs.parse_md_sources(self.MD))
        self.assertEqual([m["file"] for m in merged], ["Shelf tools", "Labs Fire Presets", "houdini22shelfindex"])
        self.assertEqual([m.get("cited") for m in merged], [True, False, True], "引用された断片が 1 つでもあれば、活用")
        self.assertEqual(merged[0]["numbers"], [1, 3])
        self.assertEqual(set(merged[0]) & {"file", "namespace", "similarity", "excerpt"}, {"file", "namespace", "similarity", "excerpt"})

    def test_interrupted_generation_has_no_cited_badge(self) -> None:
        merged = vs.dedupe_sources(vs.parse_md_sources("## 参考\n\n- [1] A（db）\n- [2] A（db）\n"))
        self.assertEqual(len(merged), 1)
        self.assertNotIn("cited", merged[0])

    def test_no_sources_section(self) -> None:
        self.assertEqual(vs.parse_md_sources("## 概要\n\nx\n"), [])
        self.assertEqual(vs.parse_md_sources("## 参考\n\n- （参考ドキュメントなし）\n"), [])


class BridgeManifestTest(unittest.TestCase):
    def test_pages_and_capture_meta_are_added_and_guide_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "step_003_network.png"
            for name in ("step_003_network.png", "step_003_network_p2.png", "step_003_network_p3.png"):
                (Path(d) / name).write_bytes(b"x")
            Path(str(base) + ".meta.json").write_text(json.dumps({"kind": "code_card", "pages": 3}), encoding="utf-8")
            entries = vfb.manifest_entries([
                {"step": 3, "network": str(base), "guide": {"x": 1}},
                {"step": 4, "network": str(Path(d) / "none.png")},
                {"step": 5, "network": None},
            ])
            self.assertNotIn("guide", entries[0])
            self.assertEqual([Path(p).name for p in entries[0]["network_pages"]], ["step_003_network_p2.png", "step_003_network_p3.png"])
            self.assertEqual(entries[0]["capture"]["kind"], "code_card")
            self.assertNotIn("network_pages", entries[1])
            self.assertNotIn("capture", entries[2])

    def test_the_video_gets_the_readable_diagram_instead_of_the_real_screen(self) -> None:
        """実画面は、ノードが小さく、動画では名前が読めなかった（2026-11-22）。動画には、読める大きさで描いた図を渡す。パラメータの画像は、そのまま。"""
        with tempfile.TemporaryDirectory() as d:
            raw, diagram, card = Path(d) / "s5_network.png", Path(d) / "s5_network_video.png", Path(d) / "s6_network.png"
            for path in (raw, diagram, card):
                path.write_bytes(b"x")
            entries = vfb.manifest_entries([
                {"step": 5, "network": str(raw), "network_kind": "network", "network_video": str(diagram)},
                {"step": 6, "network": str(card), "network_kind": "parameter", "network_video": str(diagram)},
                {"step": 7, "network": str(raw), "network_kind": "network", "network_video": str(Path(d) / "missing.png")},
                {"step": 8, "network": str(raw), "network_kind": "network", "network_video": None},
            ])
            self.assertEqual(entries[0]["network"], str(diagram), "the video uses the readable diagram")
            self.assertEqual(entries[1]["network"], str(card), "a parameter card is never swapped")
            self.assertEqual(entries[2]["network"], str(raw), "a missing diagram file falls back to the real screen")
            self.assertEqual(entries[3]["network"], str(raw))
            self.assertTrue(all("network_video" not in e for e in entries), "the engine does not need the extra key")

    def test_pages_are_found_even_when_the_file_name_has_glob_characters(self) -> None:
        """名前に [ ] があっても、2 枚目以降の画像を探せる（glob の記号として扱うと、見つからなかった）。"""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "step[3]_network.png"
            for name in ("step[3]_network.png", "step[3]_network_p2.png"):
                (Path(d) / name).write_bytes(b"x")
            entries = vfb.manifest_entries([{"step": 3, "network": str(base)}])
            self.assertEqual([Path(p).name for p in entries[0]["network_pages"]], ["step[3]_network_p2.png"])


class _FakeGallery(BaseHTTPRequestHandler):
    received: list[dict] = []

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        data = b"[]"
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        from email.parser import BytesParser
        from email.policy import HTTP

        body = self.rfile.read(int(self.headers["Content-Length"]))
        msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
        fields = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in msg.iter_parts()}
        _FakeGallery.received.append(fields)
        data = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class GallerySourcesTest(unittest.TestCase):
    SOURCES = [{"file": "Shelf tools", "namespace": "houdini22shelfindex", "cited": True, "similarity": 0, "excerpt": "", "numbers": [1, 3]}]

    def test_merge_only_when_rag_sources_is_empty(self) -> None:
        merged = json.loads(gu.merge_rag_sources(json.dumps({"id": "x", "rag_sources": []}), self.SOURCES))
        self.assertEqual(merged["rag_sources"], [{"file": "Shelf tools", "namespace": "houdini22shelfindex", "cited": True, "similarity": 0, "excerpt": ""}])
        missing = json.loads(gu.merge_rag_sources(json.dumps({"id": "x"}), self.SOURCES))
        self.assertEqual(len(missing["rag_sources"]), 1)
        existing = json.dumps({"rag_sources": [{"file": "engine's own"}]})
        self.assertEqual(gu.merge_rag_sources(existing, self.SOURCES), existing, "the engine's own sources are not overwritten")
        self.assertEqual(gu.merge_rag_sources("not json", self.SOURCES), "not json")
        self.assertEqual(gu.merge_rag_sources(json.dumps({"rag_sources": []}), []), json.dumps({"rag_sources": []}))

    def test_find_sources_from_the_script_next_to_the_tutorial(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tornado_video_script.json").write_text(json.dumps({"sources": self.SOURCES}), encoding="utf-8")
            entry = {"id": "cloudrag_1", "source_tutorial": "houdini-tutorial:tornado"}
            self.assertEqual(gu.find_script_sources(entry, [Path(d)])[0]["file"], "Shelf tools")
            self.assertEqual(gu.find_script_sources({"source_tutorial": "cloud-rag:houdini22"}, [Path(d)]), [])
            self.assertEqual(gu.find_script_sources(entry, [Path(d) / "elsewhere"]), [])
            # manifest の値に、フォルダの外を指す名前があっても、読まない
            outer = Path(d) / "outer"
            outer.mkdir()
            (Path(d) / "secret_video_script.json").write_text(json.dumps({"sources": self.SOURCES}), encoding="utf-8")
            for stem in ("../secret", "..\secret", "a/../../secret"):
                self.assertEqual(gu.find_script_sources({"source_tutorial": "houdini-tutorial:" + stem}, [outer]), [], stem)

    def test_upload_sends_sources_in_the_metadata(self) -> None:
        """前: エンジンの metadata.json は "rag_sources": [] で、そのまま送られ、ギャラリーが「出典なし」と出した。"""
        server = HTTPServer(("127.0.0.1", 0), _FakeGallery)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / "output"
                folder = out / "videos" / "cloudrag_1"
                folder.mkdir(parents=True)
                (folder / "video.webm").write_bytes(b"webm")
                (folder / "metadata.json").write_text(json.dumps({"id": "cloudrag_1", "rag_sources": []}), encoding="utf-8")
                entry = {"id": "cloudrag_1", "source_tutorial": "houdini-tutorial:tornado"}
                tut = Path(d) / "tutorials"
                tut.mkdir()
                (tut / "tornado_video_script.json").write_text(json.dumps({"sources": self.SOURCES}), encoding="utf-8")
                _FakeGallery.received.clear()
                gu.upload_entry(f"http://127.0.0.1:{server.server_port}", "tok", out, entry, sources=gu.find_script_sources(entry, [tut]))
                sent = json.loads(_FakeGallery.received[0]["metadata"].decode("utf-8"))
                self.assertEqual(sent["rag_sources"][0]["file"], "Shelf tools")
                self.assertTrue(sent["rag_sources"][0]["cited"])
                # 出典を渡さなければ、これまでどおり（空のまま）
                _FakeGallery.received.clear()
                gu.upload_entry(f"http://127.0.0.1:{server.server_port}", "tok", out, entry)
                self.assertEqual(json.loads(_FakeGallery.received[0]["metadata"].decode("utf-8"))["rag_sources"], [])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
