"""rag_local_bridge の「検索は、利用者の権限(namespace)を越えない」(2026-11-10)。

直した穴:
  - /search: namespaces を省略すると、絞り込みが丸ごと省かれ、全 namespace(他人の個人ノートを含む)が見えた
  - /query : 許可された namespace が 1 つも無い(PEP が空を返す)と、`if effective_ns:` で絞り込みが省かれ、全部が見えた
  - namespace を判定できないファイルが、全員に見えた
実行: uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import rag_local_bridge as bridge  # noqa: E402

ALL = ["tool_docs", "game_info", "research", "team_notes", "personal_notes", "houdini21"]


def chunk(path: str, text: str) -> dict:
    return {"file_path": path, "chunk_index": 0, "content": text, "metadata": {},
            "vector_similarity": 0.5, "is_context": False, "is_full_document": False}


RESULTS = [
    chunk("/data/localRAG/tool_docs/public.md", "TOOLDOC-MARK"),
    chunk("/data/localRAG/research/paper.md", "RESEARCH-MARK"),
    chunk("/data/localRAG/personal_notes/diary.md", "PERSONAL-MARK"),
    chunk("/data/localRAG/team_notes/plan.md", "TEAM-MARK"),
    chunk("/data/misc/stray/no_namespace.md", "STRAY-MARK"),
]

USERS = {
    "k-tool": {"id": "u1", "display_name": "tool only", "allowed_namespaces": ["tool_docs"], "is_admin": False},
    "k-none": {"id": "u2", "display_name": "nothing", "allowed_namespaces": [], "is_admin": False},
    "k-admin": {"id": "u3", "display_name": "admin", "allowed_namespaces": ALL, "is_admin": True},
}


class FakeAuth:
    def validate_key(self, key: str):
        return USERS.get(key)

    def log_access(self, *a, **k) -> None:
        pass


class StubMcp:
    def is_alive(self) -> bool:
        return True

    def get_document_count(self) -> int:
        return len(RESULTS)

    def search_structured(self, query: str, limit: int = 5):
        return [dict(r) for r in RESULTS]


class PureFunctionTests(unittest.TestCase):
    def test_unknown_namespace_files_are_hidden_unless_admin(self) -> None:
        groups = bridge._group_by_file([dict(r) for r in RESULTS])
        out = bridge._filter_groups_by_namespace(groups, ["tool_docs"])
        self.assertEqual([Path(p).name for p in out], ["public.md"])
        admin = bridge._filter_groups_by_namespace(groups, ALL, include_unknown=True)
        self.assertIn("/data/misc/stray/no_namespace.md", admin)
        self.assertNotIn("/data/misc/stray/no_namespace.md", bridge._filter_groups_by_namespace(groups, ALL))

    def test_empty_allowed_returns_nothing(self) -> None:
        groups = bridge._group_by_file([dict(r) for r in RESULTS])
        self.assertEqual(bridge._filter_groups_by_namespace(groups, []), {})
        self.assertEqual(bridge._filter_groups_by_namespace(groups, [], include_unknown=True), {})

    def test_resolve_search_namespaces(self) -> None:
        resolve = bridge._resolve_search_namespaces
        self.assertEqual(resolve(USERS["k-tool"], None), ["tool_docs"], "省略 = 許可の全部")
        self.assertEqual(resolve(USERS["k-tool"], ["research"]), [], "許可に無い namespace は要求できない")
        self.assertEqual(resolve(USERS["k-tool"], ["tool_docs", "research"]), ["tool_docs"])
        self.assertEqual(resolve(USERS["k-none"], None), [], "何も許可されていなければ空(全部ではない)")
        self.assertEqual(resolve(USERS["k-none"], ["tool_docs"]), [])
        self.assertEqual(set(resolve(USERS["k-admin"], None)), set(ALL))


class HandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._saved = (bridge.BridgeHandler.mcp if hasattr(bridge.BridgeHandler, "mcp") else None,
                      bridge.BridgeHandler.auth, bridge.BridgeHandler.audit, bridge._call_claude)
        bridge.BridgeHandler.mcp = StubMcp()
        bridge.BridgeHandler.auth = FakeAuth()
        bridge.BridgeHandler.audit = None
        # LLM は呼ばない: 受け取った検索結果の文章をそのまま回答として返す(何が渡されたかを検査できる)
        bridge._call_claude = lambda texts, query, history: "\n".join(texts) + " [1]"
        os.environ["RAG_LLM_BACKEND"] = "claude"
        bridge._LLM_BACKEND = "claude"
        cls.server = HTTPServer(("127.0.0.1", 0), bridge.BridgeHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        bridge.BridgeHandler.mcp, bridge.BridgeHandler.auth, bridge.BridgeHandler.audit, bridge._call_claude = cls._saved

    def post(self, path: str, key: str, body: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", path, body=json.dumps(body).encode(),
                     headers={"Content-Type": "application/json", "X-API-Key": key})
        res = conn.getresponse()
        data = json.loads(res.read() or b"{}")
        conn.close()
        return res.status, data

    def search_text(self, key: str, **body) -> str:
        status, data = self.post("/search", key, {"query": "q", **body})
        self.assertEqual(status, 200, data)
        return "\n".join(data["texts"])

    def query_text(self, key: str, **body) -> str:
        status, data = self.post("/query", key, {"query": "q", **body})
        self.assertEqual(status, 200, data)
        return data["answer"]

    # ---- /search
    def test_search_without_namespaces_is_limited_to_the_users_permission(self) -> None:
        text = self.search_text("k-tool")  # namespaces を省略(以前はここで全部が見えた)
        self.assertIn("TOOLDOC-MARK", text)
        for leaked in ("RESEARCH-MARK", "PERSONAL-MARK", "TEAM-MARK", "STRAY-MARK"):
            self.assertNotIn(leaked, text)

    def test_search_cannot_request_a_namespace_it_has_no_permission_for(self) -> None:
        text = self.search_text("k-tool", namespaces=["personal_notes", "research"])
        for leaked in ("TOOLDOC-MARK", "RESEARCH-MARK", "PERSONAL-MARK"):
            self.assertNotIn(leaked, text)

    def test_search_with_no_permission_returns_nothing(self) -> None:
        text = self.search_text("k-none")
        for leaked in ("TOOLDOC-MARK", "RESEARCH-MARK", "PERSONAL-MARK", "TEAM-MARK", "STRAY-MARK"):
            self.assertNotIn(leaked, text)

    def test_admin_still_sees_everything(self) -> None:
        text = self.search_text("k-admin")
        for mark in ("TOOLDOC-MARK", "RESEARCH-MARK", "PERSONAL-MARK", "TEAM-MARK", "STRAY-MARK"):
            self.assertIn(mark, text)

    # ---- /query
    def test_query_with_no_permission_gets_no_documents(self) -> None:
        answer = self.query_text("k-none")  # 以前は PEP が空を返しても絞り込みが省かれ、全部が見えた
        for leaked in ("TOOLDOC-MARK", "RESEARCH-MARK", "PERSONAL-MARK", "TEAM-MARK", "STRAY-MARK"):
            self.assertNotIn(leaked, answer)

    def test_query_is_limited_to_the_users_permission(self) -> None:
        answer = self.query_text("k-tool")
        self.assertIn("TOOLDOC-MARK", answer)
        for leaked in ("RESEARCH-MARK", "PERSONAL-MARK", "TEAM-MARK", "STRAY-MARK"):
            self.assertNotIn(leaked, answer)

    def test_query_admin_sees_everything(self) -> None:
        answer = self.query_text("k-admin")
        for mark in ("TOOLDOC-MARK", "RESEARCH-MARK", "PERSONAL-MARK", "STRAY-MARK"):
            self.assertIn(mark, answer)

    def test_no_key_is_401(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/search", body=b'{"query":"q"}', headers={"Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()


if __name__ == "__main__":
    unittest.main()
