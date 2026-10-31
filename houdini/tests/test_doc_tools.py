"""doc_tools.py（生成の途中でドキュメントを引く search_docs / get_doc）と、エージェントへの組み込みのテスト。
標準の unittest。Houdini・Claude・ネットワークは使わない（Worker の応答は差し込みの関数で作る）。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import doc_tools as dt  # noqa: E402

NS = "shared:houdini22"


def worker_search_reply(*hits: tuple[str, str, int]) -> dict:
    """Worker の /search と同じ形（texts: 見出し＋「[i] ファイル: …」、sources: file/namespace/score）。"""
    texts = [f"検索結果（{len(hits)} 件）:"]
    sources = []
    for i, (file, body, score) in enumerate(hits, start=1):
        texts.append(f"\n[{i}] ファイル: {file}\n{body}")
        sources.append({"file": file, "namespace": NS, "difficulty": None, "score": score})
    return {"texts": texts, "sources": sources, "status": "ok"}


class FakeWorker:
    def __init__(self, replies: dict[str, object]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, payload: dict) -> dict:
        self.calls.append((path, payload))
        reply = self.replies[path]
        if isinstance(reply, Exception):
            raise reply
        return reply(payload) if callable(reply) else reply  # type: ignore[return-value]


def make_client(worker: FakeWorker, initial: list[dict] | None = None, hint: list[str] | None = None) -> dt.DocClient:
    sources = list(initial or [])
    return dt.DocClient("https://example.test", "key", NS, sources, context_hint=hint, post=worker)


class ToolDefinitionTest(unittest.TestCase):
    def test_definitions_match_names_and_schema(self) -> None:
        self.assertEqual([t["name"] for t in dt.DOC_TOOLS], list(dt.DOC_TOOL_NAMES))
        by_name = {t["name"]: t for t in dt.DOC_TOOLS}
        self.assertEqual(by_name["search_docs"]["input_schema"]["required"], ["query"])
        self.assertEqual(by_name["get_doc"]["input_schema"]["required"], ["file"])
        for tool in dt.DOC_TOOLS:
            self.assertEqual(tool["input_schema"]["type"], "object")
            self.assertGreater(len(tool["description"]), 40)

    def test_prompt_section_names_both_tools_and_the_citation_rule(self) -> None:
        for word in ("search_docs", "get_doc", "sources_used", "確かめていません"):
            self.assertIn(word, dt.DOC_TOOLS_SECTION)


class SearchTest(unittest.TestCase):
    def test_results_are_numbered_after_the_initial_sources_and_registered(self) -> None:
        worker = FakeWorker({"/search": worker_search_reply(
            ("nodes/scatter.md", "Scatter creates points.", 100),
            ("nodes/copytopoints.md", "Copy to Points stamps.", 80),
        )})
        initial = [{"file": f"a{i}.md", "namespace": NS} for i in range(1, 7)]
        client = make_client(worker, initial)
        out = client.search("scatter")
        self.assertIn("[7] nodes/scatter.md", out)
        self.assertIn("[8] nodes/copytopoints.md", out)
        self.assertIn("Scatter creates points.", out)
        self.assertEqual(len(client.sources), 8)
        self.assertEqual(client.sources[6]["file"], "nodes/scatter.md")
        self.assertEqual(client.sources[6]["score"], 100)
        self.assertTrue(client.sources[6]["fetched"])
        self.assertEqual(client.initial_source_count, 6)
        self.assertEqual(client.searches, 1)

    def test_a_page_already_in_sources_keeps_its_number(self) -> None:
        worker = FakeWorker({"/search": worker_search_reply(("a2.md", "body", 90))})
        client = make_client(worker, [{"file": "a1.md"}, {"file": "a2.md"}])
        out = client.search("x")
        self.assertIn("[2] a2.md", out)
        self.assertEqual(len(client.sources), 2)

    def test_chunks_of_one_page_are_merged_and_long_text_is_cut(self) -> None:
        worker = FakeWorker({"/search": worker_search_reply(
            ("p.md", "first   part\nwith  spaces", 100),
            ("p.md", "second part " + "x" * 2000, 90),
        )})
        client = make_client(worker)
        out = client.search("p")
        self.assertEqual(out.count("p.md"), 1, "one entry per page")
        self.assertIn("first part with spaces … second part", out)
        self.assertTrue(out.rstrip().endswith("…"))
        self.assertLess(len(out), dt.EXCERPT_CHARS + 300)

    def test_request_is_pinned_to_the_namespace_and_carries_the_context_hint(self) -> None:
        worker = FakeWorker({"/search": worker_search_reply(("p.md", "b", 1))})
        client = make_client(worker, hint=["dynamics"])
        client.search("  vellum  ", limit=99)
        path, payload = worker.calls[0]
        self.assertEqual(path, "/search")
        self.assertEqual(payload["namespaces"], [NS])
        self.assertEqual(payload["query"], "vellum")
        self.assertEqual(payload["limit"], dt.SEARCH_MAX_LIMIT)
        self.assertEqual(payload["context"], ["dynamics"])
        worker2 = FakeWorker({"/search": worker_search_reply(("p.md", "b", 1))})
        make_client(worker2).search("q", limit="bad")  # type: ignore[arg-type]
        self.assertEqual(worker2.calls[0][1]["limit"], dt.SEARCH_DEFAULT_LIMIT)
        self.assertNotIn("context", worker2.calls[0][1])

    def test_no_hits_and_empty_query(self) -> None:
        worker = FakeWorker({"/search": {"texts": ["（アクセス可能なnamespaceがありません）"], "sources": [], "status": "ok"}})
        client = make_client(worker)
        self.assertIn("一致するドキュメントはありません", client.search("zzz"))
        self.assertEqual(client.sources, [])
        with self.assertRaises(dt.DocToolError):
            client.search("   ")

    def test_the_model_cannot_choose_the_namespace(self) -> None:
        worker = FakeWorker({"/search": worker_search_reply(("p.md", "b", 1))})
        client = make_client(worker)
        client.search("q")
        self.assertNotIn("namespace", worker.calls[0][1])  # 単数形のキーは存在しない。複数形は固定値
        self.assertEqual(worker.calls[0][1]["namespaces"], [NS])


class GetDocTest(unittest.TestCase):
    def test_header_numbering_and_continuation_hint(self) -> None:
        worker = FakeWorker({"/docs/get": {
            "status": "ok", "file": "nodes/vellum.md", "text": "T" * 10, "totalChars": 25000,
            "offset": 0, "nextOffset": 8000, "chunkCount": 30,
        }})
        client = make_client(worker, [{"file": "a.md"}])
        out = client.get("nodes/vellum.md")
        self.assertIn("[2] nodes/vellum.md（全 25,000 文字のうち 0〜10 文字目）", out)
        self.assertIn('get_doc(file="nodes/vellum.md", offset=8000)', out)
        self.assertEqual(client.reads, 1)
        path, payload = worker.calls[0]
        self.assertEqual(path, "/docs/get")
        self.assertEqual(payload["namespace"], NS)
        self.assertEqual(payload["maxChars"], dt.GET_DOC_CHARS)

    def test_last_page_has_no_continuation_and_offset_is_passed(self) -> None:
        worker = FakeWorker({"/docs/get": {"status": "ok", "text": "tail", "totalChars": 8004, "offset": 8000, "nextOffset": None}})
        out = make_client(worker).get("p.md", offset=8000)
        self.assertNotIn("続きがあります", out)
        self.assertEqual(worker.calls[0][1]["offset"], 8000)
        self.assertIn("8,000〜8,004 文字目", out)

    def test_errors_and_empty_file(self) -> None:
        worker = FakeWorker({"/docs/get": dt.DocToolError("404: not found。近い名前: nodes/scatter.md")})
        client = make_client(worker)
        with self.assertRaises(dt.DocToolError) as ctx:
            client.get("scatter")
        self.assertIn("nodes/scatter.md", str(ctx.exception))
        with self.assertRaises(dt.DocToolError):
            client.get("")


class CallLimitTest(unittest.TestCase):
    def test_total_calls_are_capped(self) -> None:
        worker = FakeWorker({"/search": worker_search_reply(("p.md", "b", 1)), "/docs/get": {"text": "t", "totalChars": 1}})
        client = make_client(worker)
        for i in range(dt.MAX_DOC_CALLS):
            (client.search if i % 2 == 0 else client.get)("p.md" if i % 2 else "q")
        with self.assertRaises(dt.DocToolError) as ctx:
            client.search("one more")
        self.assertIn("上限", str(ctx.exception))
        self.assertEqual(len(worker.calls), dt.MAX_DOC_CALLS, "the capped call never reaches the Worker")


class RealHttpPathTest(unittest.TestCase):
    """差し込みの post を使わない経路（本番）。通信は rag_client.post_json を1か所で使い、失敗は画面・モデルに出せる文になる。"""

    def _client(self) -> dt.DocClient:
        return dt.DocClient("https://w.example.test/", "key-123", NS, [])

    def test_request_goes_through_rag_client_with_the_key(self) -> None:
        with mock.patch.object(dt, "post_json", return_value=worker_search_reply(("p.md", "b", 1))) as post:
            self._client().search("scatter")
        url, payload = post.call_args.args[:2]
        self.assertEqual(url, "https://w.example.test/search", "no double slash")
        self.assertEqual(payload["namespaces"], [NS])
        self.assertEqual(post.call_args.kwargs["api_key"], "key-123")
        self.assertEqual(post.call_args.kwargs["timeout"], dt.HTTP_TIMEOUT_SEC)

    def test_http_errors_carry_the_workers_message_and_suggestions(self) -> None:
        body = json.dumps({"error": "見つかりません", "suggestions": ["nodes/scatter.md"]}).encode("utf-8")
        exc = urllib.error.HTTPError("https://x", 404, "nf", {}, io.BytesIO(body))  # type: ignore[arg-type]
        with mock.patch.object(dt, "post_json", side_effect=exc):
            with self.assertRaises(dt.DocToolError) as ctx:
                self._client().get("scatter")
        self.assertIn("見つかりません", str(ctx.exception))
        self.assertIn("nodes/scatter.md", str(ctx.exception))

    def test_network_errors_become_tool_errors(self) -> None:
        with mock.patch.object(dt, "post_json", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(dt.DocToolError) as ctx:
                self._client().search("q")
        self.assertIn("接続できません", str(ctx.exception))
        with mock.patch.object(dt, "post_json", side_effect=TimeoutError("timed out")):
            with self.assertRaises(dt.DocToolError):
                self._client().search("q")


class NamespaceHelpersTest(unittest.TestCase):
    """Docs タブが使う純粋関数（Qt なしで確かめられる）。"""

    def test_default_namespace_prefers_the_setting_then_the_newest_houdini(self) -> None:
        nss = ["shared:houdini21", "shared:houdini22", "shared:notes", "personal:me"]
        self.assertEqual(dt.pick_default_namespace(nss, "houdini21"), "shared:houdini21")
        self.assertEqual(dt.pick_default_namespace(nss, "shared:houdini21"), "shared:houdini21")
        self.assertEqual(dt.pick_default_namespace(nss, ""), "shared:houdini22")
        self.assertEqual(dt.pick_default_namespace(nss, "houdini99"), "shared:houdini22", "unknown setting falls back")
        self.assertEqual(dt.pick_default_namespace(["shared:notes", "personal:me"], ""), "shared:notes")
        self.assertEqual(dt.pick_default_namespace(["shared:houdini9", "shared:houdini10"], ""), "shared:houdini10", "numeric, not alphabetical")
        self.assertEqual(dt.pick_default_namespace([], "houdini22"), "")

    def test_shared_first(self) -> None:
        self.assertEqual(dt.sort_namespaces(["personal:a", "shared:z", "shared:b"]), ["shared:b", "shared:z", "personal:a"])

    def test_list_excerpt_is_short(self) -> None:
        self.assertEqual(dt.excerpt_for_list(["a", "b"]), "a … b")
        self.assertTrue(dt.excerpt_for_list(["x" * 500]).endswith("…"))
        self.assertLessEqual(len(dt.excerpt_for_list(["x" * 500])), 91)


class ExecutorDispatchTest(unittest.TestCase):
    def _executor(self, client):
        import houdini_tools

        ex = houdini_tools.HoudiniToolExecutor.__new__(houdini_tools.HoudiniToolExecutor)
        ex.step_log = []
        ex.doc_client = client
        ex._log_path = None
        ex._lock = threading.Lock()
        ex.step_screenshots = []
        return houdini_tools, ex

    def test_doc_tools_never_run_on_the_houdini_main_thread(self) -> None:
        worker = FakeWorker({"/search": worker_search_reply(("p.md", "body", 1))})
        houdini_tools, ex = self._executor(make_client(worker))
        with mock.patch.object(houdini_tools, "_run_in_main_thread", side_effect=AssertionError("main thread used")):
            out, is_error = ex.execute("search_docs", {"query": "scatter"})
        self.assertFalse(is_error)
        self.assertIn("[1] p.md", out)
        self.assertEqual(ex.step_log[-1]["tool"], "search_docs")

    def test_errors_become_tool_errors_not_exceptions(self) -> None:
        worker = FakeWorker({"/docs/get": dt.DocToolError("404: missing"), "/search": RuntimeError("boom")})
        _, ex = self._executor(make_client(worker))
        out, is_error = ex.execute("get_doc", {"file": "x.md"})
        self.assertTrue(is_error)
        self.assertIn("404: missing", out)
        out, is_error = ex.execute("search_docs", {"query": "q"})
        self.assertTrue(is_error)
        self.assertIn("ドキュメントの取得に失敗", out)
        out, is_error = ex.execute("search_docs", {})
        self.assertTrue(is_error, "a missing query is a tool error")

    def test_without_a_client_the_tools_say_they_are_unavailable(self) -> None:
        _, ex = self._executor(None)
        out, is_error = ex.execute("search_docs", {"query": "q"})
        self.assertTrue(is_error)
        self.assertIn("使えません", out)


class AgentWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import tutorial_agent
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"tutorial_agent をimportできません: {exc}") from exc
        cls.ta = tutorial_agent

    def _agent(self, with_client: bool):
        agent = self.ta.TutorialAgent.__new__(self.ta.TutorialAgent)
        agent._model = "test"
        agent._rag_name = "houdini22"
        agent._reference_blocks = []
        agent._reference_names = []
        agent._requirements = ""
        agent._target_model = ""
        agent.executor = mock.Mock(sandbox_path="/obj/x")
        agent._doc_client = make_client(FakeWorker({})) if with_client else None
        agent._feedback_sections = lambda topic: ""  # type: ignore[method-assign]
        return agent

    def test_tools_and_prompt_include_the_doc_tools_only_when_enabled(self) -> None:
        on_system, on_tools, _ = self._agent(True)._build_initial_prompt("岩", [], "basic")
        names = [t["name"] for t in on_tools]
        self.assertEqual(names[-2:], ["search_docs", "get_doc"])
        self.assertIn("cache_control", on_tools[-1], "the cache marker stays on the last tool")
        self.assertEqual(sum("cache_control" in t for t in on_tools), 1)
        self.assertIn("search_docs / get_doc", on_system[0]["text"])

        off_system, off_tools, _ = self._agent(False)._build_initial_prompt("岩", [], "basic")
        self.assertNotIn("search_docs", [t["name"] for t in off_tools])
        self.assertNotIn("search_docs / get_doc", off_system[0]["text"])
        self.assertEqual(off_tools[-1]["name"], "confirm_tutorial")

    def test_environment_switch_for_the_comparison_runs(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RAG_TUTORIAL_DOC_TOOLS", None)
            self.assertTrue(self.ta.doc_tools_default())
        for off in ("0", "false", "OFF", "no"):
            with mock.patch.dict(os.environ, {"RAG_TUTORIAL_DOC_TOOLS": off}):
                self.assertFalse(self.ta.doc_tools_default(), off)
        with mock.patch.dict(os.environ, {"RAG_TUTORIAL_DOC_TOOLS": "1"}):
            self.assertTrue(self.ta.doc_tools_default())

    def test_cited_rate_only_counts_what_was_asked(self) -> None:
        sources = [{"cited": True}, {"cited": False}, {"cited": False}, {"cited": True}]
        self.assertEqual(self.ta._cited_rate(sources, True), 0.5)
        self.assertEqual(self.ta._cited_rate(sources, False), -1, "aborted runs were never asked")
        self.assertEqual(self.ta._cited_rate([], True), -1)

    def test_metrics_separate_initial_and_fetched_sources(self) -> None:
        agent = self._agent(True)
        agent._model = "claude-sonnet-5"
        agent.executor = mock.Mock(step_log=[
            {"tool": "search_docs", "input": {}, "result": "", "is_error": False},
            {"tool": "cook_node", "input": {}, "result": "cook 成功", "is_error": False},
        ])
        result = self.ta.TutorialResult()
        result.completed = True
        result.sources = [
            {"file": "a", "cited": True}, {"file": "b", "cited": False},   # 最初の検索
            {"file": "c", "cited": True}, {"file": "d", "cited": False},   # 途中で引いた
        ]
        result.rag_initial_count = 2
        result.doc_tools_enabled = True
        result.doc_searches, result.doc_reads = 3, 1
        result.rag_extraction_rate = 0.5
        m = agent._collect_metrics(result, "岩")
        self.assertTrue(m["doc_tools"])
        self.assertEqual((m["doc_searches"], m["doc_reads"]), (3, 1))
        self.assertEqual((m["rag_initial_sources"], m["rag_fetched_sources"]), (2, 2))
        self.assertEqual(m["rag_initial_extraction_rate"], 0.5)
        self.assertEqual(m["rag_fetched_cited"], 1)
        self.assertEqual(m["rag_extraction_rate"], 0.5)
        self.assertEqual(m["tool_calls"], 2)
        self.assertEqual(m["cook_calls"], 1)


if __name__ == "__main__":
    unittest.main()
