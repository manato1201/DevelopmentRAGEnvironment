"""実証実験の課題まわり（pilot_task.py の部品と、rag_client の /pilot/* 呼び出し）のテスト。Qt・Houdini は読み込まない。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import sys
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


class PayloadTest(unittest.TestCase):
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
        urls = [c.args[0] for c in post.call_args_list]
        self.assertEqual(urls, ["https://w.example/pilot/plan", "https://w.example/pilot/profile", "https://w.example/pilot/session/start", "https://w.example/pilot/session/end"])
        self.assertEqual(post.call_args_list[2].args[1], {"kind": "fixed"})
        self.assertTrue(all(c.kwargs.get("api_key") == "KEY" for c in post.call_args_list))

    def test_not_available_in_local_mode(self):
        client = rag_client.RAGClient({"mode": "local", "local_port": 1, "cf_url": "", "cf_api_key": ""})
        with self.assertRaises(RuntimeError):
            client.pilot_plan()


if __name__ == "__main__":
    unittest.main()
