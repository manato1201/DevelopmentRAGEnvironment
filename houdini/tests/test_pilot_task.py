"""実証実験の課題まわり（pilot_task.py の部品と、rag_client の /pilot/* 呼び出し）のテスト。Qt・Houdini は読み込まない。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import pilot_task as pt  # noqa: E402
import rag_client  # noqa: E402


class FakeNode:
    def __init__(self, path, errors=(), children=(), raises=False):
        self._path, self._errors, self._children, self._raises = path, tuple(errors), list(children), raises

    def path(self):
        return self._path

    def errors(self):
        if self._raises:
            raise RuntimeError("node vanished")
        return self._errors

    def allSubChildren(self):
        return list(self._children)


class FakeHou:
    def __init__(self, roots):
        self._roots = roots

    def node(self, path):
        return self._roots.get(path)


def scene(*errored, extra=()):
    nodes = [FakeNode(p, errors=("Invalid source",)) for p in errored] + [FakeNode("/obj/ok1"), *extra]
    return FakeHou({"/obj": FakeNode("/obj", children=nodes)})


class ScanTest(unittest.TestCase):
    def test_only_errored_nodes(self):
        self.assertEqual(pt.scan_error_nodes(scene("/obj/a", "/obj/b")), {"/obj/a", "/obj/b"})

    def test_missing_roots_and_broken_nodes_are_skipped(self):
        hou = scene("/obj/a", extra=[FakeNode("/obj/gone", raises=True)])
        self.assertEqual(pt.scan_error_nodes(hou), {"/obj/a"})
        self.assertEqual(pt.scan_error_nodes(FakeHou({})), set())

    def test_scan_stops_at_the_limit(self):
        hou = FakeHou({"/obj": FakeNode("/obj", children=[FakeNode(f"/obj/n{i}", errors=("e",)) for i in range(50)])})
        self.assertEqual(len(pt.scan_error_nodes(hou, limit=10)), 10)


    def test_scan_gives_up_when_it_takes_too_long(self):
        # 巨大なシーンで画面を止めない: 時間の上限を超えたら、そこまでで打ち切る（0 件ではなく、見つけた分を返す）
        hou = FakeHou({"/obj": FakeNode("/obj", children=[FakeNode(f"/obj/n{i}", errors=("e",)) for i in range(1000)])})
        ticks = iter(range(10_000))
        found = pt.scan_error_nodes(hou, budget_sec=2.0, clock=lambda: next(ticks) * 1.0)
        self.assertGreater(len(found), 0)
        self.assertLess(len(found), 1000)


class SamplerTest(unittest.TestCase):
    def test_counts_distinct_nodes_that_were_ever_in_error(self):
        state = {"errored": ["/obj/a"]}

        class Hou:
            def node(self, path):
                return scene(*state["errored"]).node(path)

        sampler = pt.ErrorSampler(Hou())
        self.assertIsNone(sampler.count, "not measured before the first sample")
        self.assertEqual(sampler.sample(), 1)
        state["errored"] = []          # すぐ直された（採取の合間に消えた）
        self.assertEqual(sampler.sample(), 1, "a fixed error still counts: ever in error")
        state["errored"] = ["/obj/a", "/obj/b"]
        self.assertEqual(sampler.sample(), 2, "the same node is not counted twice")
        self.assertEqual(sampler.count, 2)
        sampler.reset()
        self.assertIsNone(sampler.count)

    def test_zero_is_different_from_unmeasured(self):
        sampler = pt.ErrorSampler(scene())
        sampler.sample()
        self.assertEqual(sampler.count, 0)
        outside = pt.ErrorSampler(None)
        self.assertFalse(outside.measurable)
        self.assertIsNone(outside.sample())
        self.assertIsNone(outside.count, "outside Houdini: not measurable → blank, not 0")


class ProgressTest(unittest.TestCase):
    """Houdini が閉じた・落ちたあとの再開: 途中経過を引き継ぎ、閉じていた時間は中断として数える。"""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = pt.ProgressStore(Path(self._dir.name) / "sub" / "progress.json")

    def test_save_and_load_for_the_same_session_only(self):
        self.assertIsNone(self.store.load("s1"), "nothing saved yet")
        self.store.save("s1", {"/obj/b", "/obj/a"}, 30, 1000.0)
        saved = self.store.load("s1")
        self.assertEqual(saved["errorPaths"], ["/obj/a", "/obj/b"])
        self.assertEqual((saved["pausedSec"], saved["lastSeen"]), (30, 1000.0))
        self.assertIsNone(self.store.load("other"), "another session's progress is not carried over")
        self.store.clear()
        self.assertIsNone(self.store.load("s1"))
        self.store.clear()  # 無くても、エラーにならない

    def test_broken_file_is_ignored(self):
        path = Path(self._dir.name) / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(pt.ProgressStore(path).load("s1"))

    def test_resume_counts_the_closed_time_as_paused(self):
        paths, paused = pt.resume_state({"sessionId": "s", "errorPaths": ["/obj/a"], "pausedSec": 60, "lastSeen": 1000.0}, 1000.0 + 600)
        self.assertEqual(paths, {"/obj/a"})
        self.assertEqual(paused, 660, "earlier pauses + the gap since the last sign of life")

    def test_short_gap_is_not_a_pause(self):
        # 採取の間隔（20秒）ぶんの空きは、閉じていたのではない
        self.assertEqual(pt.resume_state({"lastSeen": 1000.0, "pausedSec": 0}, 1015.0)[1], 0)
        self.assertEqual(pt.resume_state(None, 5.0), (set(), 0))

    def test_sampler_keeps_restored_nodes(self):
        sampler = pt.ErrorSampler(scene("/obj/new"))
        sampler.restore(["/obj/old"])
        sampler.sample()
        self.assertEqual(sampler.count, 2, "errors from before the restart still count")
        self.assertEqual(sampler.paths, ["/obj/new", "/obj/old"])


class PayloadTest(unittest.TestCase):
    def test_paused_time_is_sent(self):
        self.assertEqual(pt.build_end_payload("s", True, 0, 1, {}, "", 90)["pausedSec"], 90)
        self.assertEqual(pt.build_end_payload("s", True, 0, 1, {}, "")["pausedSec"], 0)
        self.assertEqual(pt.build_end_payload("s", True, 0, 1, {}, "", -5)["pausedSec"], 0)

    def test_end_payload_drops_unanswered_and_invalid(self):
        p = pt.build_end_payload("sid", True, 3, 4, {"difficulty": 2, "clarity": 0, "focus": 9, "reuse": 5}, "  メモ  ")
        self.assertEqual(p["survey"], {"difficulty": 2, "reuse": 5})
        self.assertEqual((p["sessionId"], p["reached"], p["cookErrorNodes"], p["selfMistakes"], p["comment"]), ("sid", True, 3, 4, "メモ"))

    def test_unanswered_stays_blank(self):
        p = pt.build_end_payload("sid", None, None, 0, {}, "")
        self.assertIsNone(p["reached"])
        self.assertIsNone(p["cookErrorNodes"])
        self.assertIsNone(p["selfMistakes"])
        self.assertEqual(p["survey"], {})

    def test_comment_is_limited(self):
        self.assertEqual(len(pt.build_end_payload("s", True, 0, 1, {}, "あ" * 5000)["comment"]), 1000)

    def test_profile_payload(self):
        p = pt.build_profile_payload(1.5, "初級", " CG専攻 ", "", "Blender")
        self.assertEqual(p["experienceYears"], 1.5)
        self.assertEqual(p["selfLevel"], "初級")
        self.assertEqual(p["background"], "CG専攻")
        self.assertEqual(pt.build_profile_payload(0, "不明", "", "", "")["selfLevel"], "")


class TextTest(unittest.TestCase):
    def test_survey_questions_hide_sources_when_docs_only(self):
        system = [q[0] for q in pt.survey_questions("system")]
        docs = [q[0] for q in pt.survey_questions("docs_only")]
        self.assertIn("sourceUseful", system)
        self.assertNotIn("sourceUseful", docs)
        self.assertEqual(len(system) - len(docs), 1)

    def test_history_line(self):
        line = pt.format_history_line({"round": 2, "kind": "fixed", "label": "RBD", "durationSec": 1800})
        self.assertEqual(line, "第2回 固定課題: RBD　30分")
        self.assertEqual(pt.format_history_line({"round": 1, "kind": "free", "label": "自分の作りたいもの", "durationSec": None}), "第1回 自由課題: 自分の作りたいもの")
        self.assertIn("1分", pt.format_history_line({"round": 1, "kind": "fixed", "label": "x", "durationSec": 5}))

    def test_elapsed(self):
        self.assertEqual(pt.format_elapsed(0), "0:00:00")
        self.assertEqual(pt.format_elapsed(3725), "1:02:05")
        self.assertEqual(pt.format_elapsed(-5), "0:00:00")

    def test_header(self):
        self.assertEqual(pt.format_plan_header({"round": 2, "pid": 3}), "第2回 / 3回（参加者 P03）")
        self.assertEqual(pt.format_plan_header({"round": 1, "pid": None}), "第1回 / 3回")
        self.assertIn("完了", pt.format_plan_header({"finished": True}))

    def test_docs_only_text_tells_not_to_use_the_system(self):
        self.assertIn("使わないでください", pt.CONDITION_TEXT["docs_only"])


class ClientTest(unittest.TestCase):
    CFG = {"mode": "cloudflare", "cf_url": "https://w.example/", "cf_api_key": "KEY"}

    def test_calls_the_right_endpoints(self):
        client = rag_client.RAGClient(dict(self.CFG))
        with mock.patch.object(rag_client, "post_json", return_value={"status": "ok"}) as post:
            client.pilot_plan()
            client.pilot_profile({"experienceYears": 1})
            client.pilot_session_start("fixed")
            client.pilot_session_end({"sessionId": "s"})
            client.pilot_session_reset("s")
        urls = [c.args[0] for c in post.call_args_list]
        self.assertEqual(urls, ["https://w.example/pilot/plan", "https://w.example/pilot/profile", "https://w.example/pilot/session/start", "https://w.example/pilot/session/end", "https://w.example/pilot/session/reset"])
        self.assertEqual(post.call_args_list[2].args[1], {"kind": "fixed"})
        self.assertEqual(post.call_args_list[4].args[1], {"sessionId": "s"})
        self.assertTrue(all(c.kwargs.get("api_key") == "KEY" for c in post.call_args_list))

    def test_not_available_in_local_mode(self):
        client = rag_client.RAGClient({"mode": "local", "local_port": 1, "cf_url": "", "cf_api_key": ""})
        with self.assertRaises(RuntimeError):
            client.pilot_plan()


if __name__ == "__main__":
    unittest.main()
