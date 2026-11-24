"""scripts/audit_reference.py（説明を本物の Houdini と突き合わせる点検）のテスト（2026-11-20）。Houdini は使わない（書き出した結果の形を、手で作る）。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_audit_reference.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_reference as ar  # noqa: E402
import reference_data as rd  # noqa: E402

PARMS = {
    "sop/mountain": {"type": "mountain::2.0", "names": ["Height", "Noise Type", "Fractal Depth", "Roughness", "Perlin Noise", "height"]},
    "sop/missing": None,
    "__node_types__": ["scatter", "Scatter", "Grid"],
}


class UnknownTermsTest(unittest.TestCase):
    def test_a_name_that_is_not_a_real_parameter_is_found(self) -> None:
        entry = {"what": "「Fractal type」を選ぶ", "example_point": "「Max octaves」と「Roughness」を調整する"}
        self.assertEqual(ar.unknown_terms(entry, PARMS["sop/mountain"]["names"]), ["Fractal type", "Max octaves"])

    def test_real_names_pass_whatever_the_case_or_spacing(self) -> None:
        entry = {"what": "「noise type」と『Fractal  Depth』と「Perlin Noise」"}
        self.assertEqual(ar.unknown_terms(entry, PARMS["sop/mountain"]["names"]), [])

    def test_japanese_terms_and_other_nodes_are_not_parameter_claims(self) -> None:
        entry = {"what": "「入れ物」として使う", "use": "「Scatter」ノードの前に置く。「grid」も使う。「Null という名前のノード」"}
        self.assertEqual(ar.unknown_terms(entry, PARMS["sop/mountain"]["names"], PARMS["__node_types__"]), [])

    def test_text_outside_quotes_is_not_checked(self) -> None:
        self.assertEqual(ar.unknown_terms({"what": "Fractal type を選ぶ"}, ["Height"]), [])


class EntryProblemsTest(unittest.TestCase):
    def test_node_entries_are_checked_against_the_dump(self) -> None:
        self.assertEqual(ar.entry_problems("node", "sop/mountain", {"what": "「Height」を上げる"}, PARMS), [])
        bad = ar.entry_problems("node", "sop/mountain", {"what": "「Lacunarity」を上げる"}, PARMS)
        self.assertEqual(len(bad), 1)
        self.assertIn("Lacunarity", bad[0])

    def test_a_node_type_that_does_not_exist_in_houdini_is_a_problem(self) -> None:
        self.assertIn("ありません", ar.entry_problems("node", "sop/missing", {"what": "x"}, PARMS)[0])

    def test_without_a_dump_or_with_an_unknown_key_nothing_passes(self) -> None:
        self.assertTrue(ar.entry_problems("node", "sop/mountain", {"what": "x"}, None))
        self.assertTrue(ar.entry_problems("node", "sop/other", {"what": "x"}, PARMS))

    def test_apex_and_shelf_are_audited_too_since_2026_11_24(self) -> None:
        """前: APEX・シェルフは、点検の対象外で、何でも通った。後: node と同じく、本物の Houdini との突き合わせが要る（test_reference_expansion_20261124.py に詳しい）。"""
        self.assertTrue(ar.entry_problems("apex", "apex/x", {"what": "「anything」"}, None), "突き合わせの結果が無ければ、通らない")
        self.assertTrue(ar.entry_problems("shelf", "shelf/x", {"what": "x"}, None))

    def test_a_vex_function_must_exist(self) -> None:
        parms = {"__vex__": {"vex/chf": True, "vex/nope": False}}
        self.assertEqual(ar.entry_problems("vex", "vex/chf", {"what": "x"}, parms), [])
        self.assertIn("ありません", ar.entry_problems("vex", "vex/nope", {"what": "x"}, parms)[0])
        self.assertTrue(ar.entry_problems("vex", "vex/other", {"what": "x"}, parms), "not checked yet: not published")
        self.assertTrue(ar.entry_problems("vex", "vex/chf", {"what": "x"}, None))


class PromptTest(unittest.TestCase):
    def test_real_parameter_names_and_the_verified_steps_go_into_the_prompt(self) -> None:
        system, user = rd.build_prompt("node", "Mountain", [], [], parm_names=["height", "Noise Type", "Roughness"], verified="1. grid を作る")
        self.assertLess(user.index("Noise Type"), user.index("height"), "display names come first")
        self.assertIn("実在するパラメータ名", user)
        self.assertIn("1. grid を作る", user)
        self.assertIn("検証済みの手順", system)
        _s, plain = rd.build_prompt("node", "Mountain", [], [])
        self.assertNotIn("実在するパラメータ名", plain)
        self.assertNotIn("検証済みの手順", plain)

    def test_the_list_is_bounded(self) -> None:
        _s, user = rd.build_prompt("node", "X", [], [], parm_names=[f"Name {i:04d}" for i in range(500)])
        self.assertLessEqual(user.count("Name 0"), rd.MAX_PARM_NAMES)


class BatchTest(unittest.TestCase):
    def test_a_made_entry_with_a_fake_name_is_not_saved(self) -> None:
        import tempfile

        import build_reference_entries as bre

        item = {"kind": "node", "key": "sop/mountain", "name": "mountain", "label": "Mountain", "context": "sop"}
        rest = '"use": "地形の凸凹を作るときに使います。", "example": "grid につなぎます。", "example_point": "凸凹の変化を見てください。", "when": "山や丘を手早く作りたいときに向いています。"'
        answers = ['{"what": "Mountain は、「Fractal type」を選んで凸凹を作るノードです。", ' + rest + '}',
                   '{"what": "Mountain は、「Height」を上げて凸凹を作るノードです。", ' + rest + '}']
        with tempfile.TemporaryDirectory() as d:
            cfg = {"local_bridge_dir": d}
            from unittest import mock

            with mock.patch.object(bre.ra, "fetch_docs", lambda c, i: ["資料"]), mock.patch.object(bre.ra, "fetch_reference_items", lambda *a, **k: []):
                with mock.patch.object(bre, "complete_in_thread", lambda c: (lambda s, u, **kw: (answers[0], {}))):
                    result = bre.make_one(cfg, item, PARMS)
                self.assertFalse(result["ok"])
                self.assertIn("Fractal type", result["why"])
                self.assertIsNone(rd.load_entry(d, "node", "sop/mountain"), "not saved")
                with mock.patch.object(bre, "complete_in_thread", lambda c: (lambda s, u, **kw: (answers[1], {}))):
                    self.assertTrue(bre.make_one(cfg, item, PARMS)["ok"])
                self.assertEqual(rd.load_entry(d, "node", "sop/mountain")["what"], "Mountain は、「Height」を上げて凸凹を作るノードです。")
                self.assertFalse(bre.make_one(cfg, {**item, "key": "sop/missing"}, PARMS)["ok"], "a node type that does not exist is skipped")

    def test_the_verified_steps_come_from_the_capture_recipe(self) -> None:
        import build_reference_entries as bre

        text = bre.verified_steps("sop/mountain")
        self.assertIn("grid", text)
        self.assertIn("height = 1.2", text)
        self.assertEqual(bre.verified_steps("sop/merge"), "")  # レシピが無い項目は、空
        self.assertIn("置く", bre.verified_steps("sop/box"))  # 形を作るノード（create）は、入力なしの文になる


if __name__ == "__main__":
    unittest.main()
