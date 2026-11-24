"""scripts/check_reference_quality.py（説明の品質を、機械で確かめる道具）のテスト（2026-11-24）。Houdini・通信は使わない。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_check_reference_quality.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts"))

import check_reference_quality as crq  # noqa: E402
import reference_data as rd  # noqa: E402

GOOD = {
    "what": "Scatter は、面の上にランダムに点を置くノードです。",
    "use": "草や岩を置く元の点を作るときに使います。",
    "example": "grid の出力につなぎ、点の数を増やします。",
    "example_point": "点の密度の変化を見てください。",
    "when": "面の上に不規則な点を手早く作りたいときに向いています。規則正しく並べたい場合には向きません。",
}


def levels(found: list[tuple[str, str]]) -> list[str]:
    return [lv for lv, _ in found]


class CheckEntryTest(unittest.TestCase):
    def test_a_good_entry_has_no_issues(self) -> None:
        self.assertEqual(crq.check_entry("node", "sop/scatter", GOOD, {"label": "Scatter", "docs_found": 5}), [])

    def test_empty_required_fields_and_too_long_text_are_errors(self) -> None:
        bad = dict(GOOD, use="", when="あ" * (rd.MAX_FIELD_CHARS + 1))
        found = crq.check_entry("node", "sop/scatter", bad, {"label": "Scatter", "docs_found": 5})
        self.assertEqual(levels(found).count("error"), 2)

    def test_leftovers_and_non_japanese_are_errors(self) -> None:
        found = crq.check_entry("node", "sop/scatter", dict(GOOD, example="```vex\n@P```"), {"label": "Scatter", "docs_found": 5})
        self.assertIn("error", levels(found))
        english = {k: "English only text." for k in rd.SECTION_KEYS}
        self.assertTrue(any("日本語" in m for lv, m in crq.check_entry("node", "sop/scatter", english, {"label": "Scatter"}) if lv == "error"))

    def test_a_research_trail_in_a_required_field_is_an_error(self) -> None:
        """vex/pop（2026-11-24）: 「資料には載っていない」という説明が、公開の直前まで通っていた。"""
        leaked = dict(GOOD, what="VEX の関数としての「pop」は、資料には載っていません。")
        found = crq.check_entry("vex", "vex/pop", leaked, {"label": "pop", "docs_found": 5})
        self.assertTrue(any(lv == "error" and "調べた経過" in m for lv, m in found))
        other = dict(GOOD, example="詳しい例は、資料に載っていません。")
        found = crq.check_entry("node", "sop/scatter", other, {"label": "Scatter", "docs_found": 5})
        self.assertEqual([lv for lv, m in found if "調べた経過" in m], ["warn"])

    def test_todo_inside_a_word_is_not_a_leftover(self) -> None:
        """AutoDopNetwork の「toDo」を、TODO と見まちがえない（shelf/dynamics_vellumgrains、2026-11-24）。"""
        entry = dict(GOOD, example="少し待つと AutoDopNetwork が作られます。")
        self.assertEqual(crq.check_entry("node", "sop/scatter", entry, {"label": "Scatter", "docs_found": 5}), [])
        entry = dict(GOOD, example="TODO: あとで書く")
        self.assertIn("error", levels(crq.check_entry("node", "sop/scatter", entry, {"label": "Scatter", "docs_found": 5})))

    def test_audit_problems_are_errors(self) -> None:
        found = crq.check_entry("node", "sop/scatter", GOOD, {"label": "Scatter", "docs_found": 5}, ["「Foo」は、…にありません"])
        self.assertEqual(levels(found), ["error"])

    def test_a_missing_subject_name_is_a_warning_not_an_error(self) -> None:
        other = dict(GOOD, what="点を置くノードです。")
        found = crq.check_entry("node", "sop/scatter", other, {"label": "Scatter", "docs_found": 5})
        self.assertEqual(levels(found), ["warn"])
        self.assertIn("Scatter", found[0][1])

    def test_internal_names_and_apex_pages_count_as_the_subject(self) -> None:
        entry = dict(GOOD, what="GetParent は、関節の親を返すノードです。")
        self.assertEqual(crq.check_entry("apex", "apex/skel--GetParent", entry, {"label": "skel--GetParent", "docs_found": 6}), [])
        entry = dict(GOOD, what="pyro_billowysmoke で作ります。")
        self.assertEqual(crq.check_entry("shelf", "shelf/pyro_billowysmoke", entry, {"label": "Billowy Smoke", "docs_found": 5}), [])

    def test_no_docs_absolutes_and_thin_entries_are_warnings(self) -> None:
        found = crq.check_entry("node", "sop/scatter", dict(GOOD, use="必ず使います。"), {"label": "Scatter", "docs_found": 0})
        self.assertEqual(sorted(levels(found)), ["warn", "warn"])
        thin = dict(GOOD, example="", when="短い。")
        self.assertTrue(any("薄い" in m for _lv, m in crq.check_entry("node", "sop/scatter", thin, {"label": "Scatter", "docs_found": 5})))


class LoadAndRunTest(unittest.TestCase):
    def write(self, base: str, kind: str, key: str, entry: dict, **meta) -> None:
        path = rd.entry_path(base, kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**entry, **meta}, ensure_ascii=False), encoding="utf-8")

    def test_saved_entries_are_loaded_with_their_real_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "node", "sop/scatter", GOOD, label="Scatter", docs_found=5)
            self.write(tmp, "apex", "apex/skel--GetParent", GOOD, label="GetParent", docs_found=6)
            self.write(tmp, "shelf", "shelf/pyro_billowysmoke", GOOD, label="Billowy Smoke")
            items = crq.load_saved(tmp, {"node", "apex", "shelf", "vex"}, set())
            self.assertEqual(sorted(i["key"] for i in items), ["apex/skel--GetParent", "shelf/pyro_billowysmoke", "sop/scatter"])
            self.assertEqual(sorted(i["key"] for i in crq.load_saved(tmp, {"apex"}, {"apex/skel--GetParent"})), ["apex/skel--GetParent"])
            self.assertEqual(crq.load_saved(tmp, {"node"}, {"sop/other"}), [])

    def test_run_counts_errors_warnings_and_duplicates(self) -> None:
        items = [
            {"kind": "node", "key": "sop/scatter", "entry": GOOD, "meta": {"label": "Scatter", "docs_found": 5}},
            {"kind": "node", "key": "sop/copy_of_it", "entry": GOOD, "meta": {"label": "Scatter", "docs_found": 5}},
            {"kind": "node", "key": "sop/empty", "entry": dict(GOOD, use=""), "meta": {"label": "Scatter", "docs_found": 5}},
        ]
        report = crq.run(items, None)
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["errors_in"], 1)
        self.assertEqual(report["warns_in"], 1, "同じ「何をする」の項目は、注意")
        self.assertEqual(report["error"], 1)


if __name__ == "__main__":
    unittest.main()
