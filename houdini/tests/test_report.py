"""評価の集計（tutorial_feedback.build_report / report_csv）のテスト。Qt・Houdini は読み込まない。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import csv
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import tutorial_feedback as fb  # noqa: E402


def entry(key, rating=0, model="claude-sonnet-5-5", level="basic", domain="particles", tags=(), note="", metrics=None):
    return {
        "key": key, "path": f"/x/{key}.md", "title": key, "level": level, "model": model, "domain": domain,
        "metrics": {"iterations": 40, "cost_usd": 0.2, "cook_errors": 0, "completed": True} if metrics is None else metrics,
        "rating": rating, "tags": list(tags), "note": note, "status": "",
    }


class BuildReportTest(unittest.TestCase):
    def test_kpis(self):
        entries = [entry("a", 1), entry("b", -1), entry("c", 1), entry("d"), entry("e")]
        k = fb.build_report(entries)["kpis"]
        self.assertEqual((k["total"], k["rated"], k["unrated"], k["good"], k["bad"]), (5, 3, 2, 2, 1))
        self.assertAlmostEqual(k["good_rate"], 2 / 3)
        self.assertAlmostEqual(k["coverage"], 3 / 5)
        self.assertAlmostEqual(k["total_cost"], 1.0)

    def test_empty(self):
        r = fb.build_report([])
        self.assertEqual(r["sections"], [])
        self.assertIsNone(r["kpis"]["good_rate"])
        self.assertIsNone(r["kpis"]["coverage"])
        self.assertEqual(r["warnings"], [])

    def test_good_rate_hidden_when_few_ratings(self):
        # 1件だけの評価で「100%」と出さない
        entries = [entry("a", 1, model="m1")] + [entry(f"b{i}", 0, model="m1") for i in range(5)]
        row = fb.build_report(entries)["sections"][0]["rows"][0]
        self.assertEqual((row["total"], row["rated"]), (6, 1))
        self.assertIsNone(row["good_rate"])

    def test_good_rate_shown_from_the_minimum(self):
        entries = [entry(f"a{i}", 1 if i else -1, model="m1") for i in range(fb.MIN_RATED_FOR_RATE)]
        row = fb.build_report(entries)["sections"][0]["rows"][0]
        self.assertAlmostEqual(row["good_rate"], (fb.MIN_RATED_FOR_RATE - 1) / fb.MIN_RATED_FOR_RATE)

    def test_unknown_rows_are_relabelled_and_flagged(self):
        entries = [entry("old", 0, model="", level="", domain="", metrics={}), entry("new", 1)]
        report = fb.build_report(entries)
        rows = {s["id"]: s["rows"] for s in report["sections"]}
        unknown = [r for r in rows["model"] if r["unknown"]]
        self.assertEqual([r["key"] for r in unknown], [fb.UNKNOWN_LABEL])
        self.assertNotIn("（不明）", [r["key"] for s in report["sections"] for r in s["rows"]])
        self.assertTrue(any("未記録" in w for w in report["warnings"]))

    def test_warnings_for_low_coverage_and_few_ratings(self):
        entries = [entry("a", 1)] + [entry(f"n{i}") for i in range(9)]
        warnings = fb.build_report(entries)["warnings"]
        self.assertTrue(any("1 / 10" in w for w in warnings))
        self.assertTrue(any(str(fb.ENOUGH_RATED) in w for w in warnings))

    def test_no_warning_when_well_covered(self):
        entries = [entry(f"a{i}", 1 if i % 3 else -1) for i in range(fb.ENOUGH_RATED + 5)]
        self.assertEqual(fb.build_report(entries)["warnings"], [])

    def test_tag_section_only_from_tagged_entries(self):
        entries = [entry("a", 1, tags=["動画が良い"]), entry("b", -1, tags=["形が違う", "内容が浅い"]), entry("c")]
        tag_rows = {r["key"]: r for s in fb.build_report(entries)["sections"] if s["id"] == "tag" for r in s["rows"]}
        self.assertEqual(set(tag_rows), {"動画が良い", "形が違う", "内容が浅い"})

    def test_recent_bad_is_limited_and_needs_a_reason(self):
        entries = [entry(f"b{i}", -1, tags=["形が違う"]) for i in range(8)] + [entry("silent", -1)]
        recent = fb.build_report(entries)["recent_bad"]
        self.assertEqual(len(recent), 5)
        self.assertNotIn("silent", [r["title"] for r in recent])


class ReportCsvTest(unittest.TestCase):
    def test_csv_round_trip(self):
        entries = [entry("a", 1, model="m1"), entry("b", -1, model="m1"), entry("c", 1, model="m1"), entry("d", 0, model="m2")]
        text = fb.report_csv(fb.build_report(entries))
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], ["区分", *[label for _, label, _ in fb.REPORT_COLUMNS]])
        model_rows = {r[1]: r for r in rows[1:] if r[0] == "モデル別"}
        self.assertEqual(model_rows["m1"][2:4], ["3", "3"])           # 件数・評価
        self.assertEqual(model_rows["m2"][4], "")                      # 評価が無い行の好評率は空欄
        self.assertTrue(all(len(r) == len(rows[0]) for r in rows))


class ResendTest(unittest.TestCase):
    """送信の取りこぼし防止: 送信済みの印・未送信の一覧・起動時の再送。"""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def make(self, name, rating=1):
        md = self.dir / f"{name}.md"
        md.write_text("---\ntitle: t\ndifficulty: basic\n---\n## 概要\nx\n", encoding="utf-8")
        if rating:
            fb.save_feedback(md, rating, [], "")
        return md

    def test_new_rating_is_pending_until_marked(self):
        a, b = self.make("a"), self.make("b", rating=0)
        self.assertEqual(fb.pending_uploads(self.dir), [a])  # 評価の無いものは対象外
        self.assertTrue(fb.mark_uploaded(a))
        self.assertEqual(fb.pending_uploads(self.dir), [])
        self.assertTrue(fb.read_feedback(a)["uploaded_at"])

    def test_resaving_a_rating_makes_it_pending_again(self):
        a = self.make("a")
        fb.mark_uploaded(a)
        fb.save_feedback(a, -1, ["形が違う"], "")
        self.assertEqual(fb.pending_uploads(self.dir), [a])

    def test_mark_is_ignored_if_the_rating_changed_while_sending(self):
        a = self.make("a")
        old = fb.read_feedback(a)["rated_at"]
        fb.save_feedback(a, -1, [], "")
        data = fb._read_json(fb.feedback_path(a))
        data["rated_at"] = "2099-01-01T00:00:00"   # 付け直した評価（時刻が違う）
        fb._write_json(fb.feedback_path(a), data)
        self.assertFalse(fb.mark_uploaded(a, old))
        self.assertEqual(fb.pending_uploads(self.dir), [a])

    def test_resend_sends_all_and_marks_them(self):
        paths = [self.make(n) for n in ("a", "b", "c")]
        calls = []
        result = fb.resend_pending(self.dir, "https://x", "k", uploader=lambda u, k, p: (calls.append(p["tutorialKey"]) or True, "ok"))
        self.assertEqual((result["sent"], result["remaining"]), (3, 0))
        self.assertEqual(sorted(calls), ["a", "b", "c"])
        self.assertEqual(fb.pending_uploads(self.dir), [])
        # 2回目は、送るものが無い
        again = fb.resend_pending(self.dir, "https://x", "k", uploader=lambda *a: self.fail("nothing to send"))
        self.assertEqual(again["sent"], 0)
        self.assertEqual(len(paths), 3)

    def test_resend_stops_at_the_first_failure(self):
        for n in ("a", "b", "c"):
            self.make(n)
        calls = []

        def flaky(url, key, payload):
            calls.append(payload["tutorialKey"])
            return (len(calls) == 1, "x")   # 1件目だけ成功し、2件目で失敗

        result = fb.resend_pending(self.dir, "https://x", "k", uploader=flaky)
        self.assertEqual(len(calls), 2, "停止したあとは、叩かない")
        self.assertEqual((result["sent"], result["remaining"]), (1, 2))

    def test_resend_without_a_destination_does_nothing(self):
        self.make("a")
        result = fb.resend_pending(self.dir, "", "", uploader=lambda *a: self.fail("must not send"))
        self.assertTrue(result["skipped"])
        self.assertEqual(result["remaining"], 1)

    def test_report_counts_unsent_and_warns(self):
        a, b = self.make("a"), self.make("b")
        fb.mark_uploaded(a)
        report = fb.build_report(fb.list_entries(self.dir))
        self.assertEqual(report["kpis"]["unsent"], 1)
        self.assertTrue(any("未送信" in w for w in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
