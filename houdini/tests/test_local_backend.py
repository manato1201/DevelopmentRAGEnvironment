"""rag_local_bridge の `local` バックエンド(LocalLLMHarness の窓口。2026-11-21)。

資料の抜粋をクラウド(Claude / Gemini)へ送らず、このPCの窓口(OpenAI 互換)で回答を作る。
  - 窓口は loopback の http だけ(資料が外へ出ない)。それ以外の URL は、送る前に断る
  - 文脈は 8K トークン前後なので、資料の文字数に上限を設け、後ろの資料から落とす
  - 利用者の権限(namespace)の絞り込みは、バックエンドによらず同じ
実行: uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rag_local_bridge as bridge  # noqa: E402
from test_namespace_isolation import FakeAuth, StubMcp  # noqa: E402


class FakeGateway:
    """窓口(OpenAI 互換)の代わり。受け取ったリクエストを記録する。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.auth: list[str | None] = []
        self.status = 200
        self.reply = "回答です [1]"
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                outer.auth.append(self.headers.get("Authorization"))
                if outer.status != 200:
                    out = json.dumps({"error": {"message": "context_length_exceeded: 入力が長すぎます"}}).encode()
                else:
                    out = json.dumps({"choices": [{"message": {"role": "assistant", "content": outer.reply}}]}).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class LocalBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gw = FakeGateway()
        self._saved = (bridge.LOCAL_LLM_URL, bridge.LOCAL_LLM_MODEL, bridge.LOCAL_CONTEXT_CHARS, os.environ.get("LLH_TOKEN"))
        bridge.LOCAL_LLM_URL = self.gw.url
        os.environ.pop("LLH_TOKEN", None)

    def tearDown(self) -> None:
        self.gw.stop()
        bridge.LOCAL_LLM_URL, bridge.LOCAL_LLM_MODEL, bridge.LOCAL_CONTEXT_CHARS, token = self._saved
        if token is None:
            os.environ.pop("LLH_TOKEN", None)
        else:
            os.environ["LLH_TOKEN"] = token

    def test_request_shape_and_answer(self) -> None:
        history = [{"role": "user", "text": "前の質問"}, {"role": "bot", "text": "前の回答"}]
        answer = bridge._call_local(["[1] ファイル: a.md\nCTX-MARK"], "新しい質問", history)
        self.assertEqual(answer, "回答です [1]")
        req = self.gw.requests[0]
        self.assertEqual(req["model"], "llh-main")
        self.assertEqual(req["llh"], {"task": "rag"})
        self.assertEqual(req["messages"][0], {"role": "system", "content": bridge.SYSTEM_PROMPT})
        self.assertIn("CTX-MARK", req["messages"][1]["content"])
        self.assertEqual([m["role"] for m in req["messages"][-3:]], ["user", "assistant", "user"])
        self.assertEqual(req["messages"][-1]["content"], "新しい質問")
        self.assertLessEqual(req["max_tokens"], 2048)

    def test_bearer_token_is_sent_only_when_set(self) -> None:
        bridge._call_local(["x"], "q", [])
        self.assertIsNone(self.gw.auth[-1])
        os.environ["LLH_TOKEN"] = "tok-123"
        bridge._call_local(["x"], "q", [])
        self.assertEqual(self.gw.auth[-1], "Bearer tok-123")

    def test_non_loopback_or_https_url_is_refused_before_sending(self) -> None:
        for bad in ("http://example.com/v1", "https://127.0.0.1/v1", "http://user:pw@127.0.0.1/v1", "ftp://127.0.0.1/v1"):
            bridge.LOCAL_LLM_URL = bad
            with self.assertRaises(RuntimeError, msg=bad) as cm:
                bridge._call_local(["秘密の資料"], "q", [])
            self.assertIn("loopback", str(cm.exception))
        self.assertEqual(self.gw.requests, [], "何も送られていない")

    def test_context_is_trimmed_from_the_back(self) -> None:
        bridge.LOCAL_CONTEXT_CHARS = 100
        texts = ["A" * 40, "B" * 40, "C" * 40]
        fitted = bridge._fit_local_context(texts, 100)
        self.assertEqual(fitted, ["A" * 40, "B" * 40], "入りきらない後ろの資料から落とす")
        self.assertEqual(bridge._fit_local_context(["X" * 500], 100), ["X" * 100], "先頭の 1 件は、切ってでも入れる")
        self.assertEqual(bridge._fit_local_context([], 100), [])

    def test_long_context_is_trimmed_in_the_request(self) -> None:
        bridge.LOCAL_CONTEXT_CHARS = 100
        bridge._call_local(["KEEP-" + "a" * 60, "DROP-" + "b" * 60], "q", [])
        sent = self.gw.requests[0]["messages"][1]["content"]
        self.assertIn("KEEP-", sent)
        self.assertNotIn("DROP-", sent)

    def test_gateway_error_message_is_shown(self) -> None:
        self.gw.status = 400
        with self.assertRaises(RuntimeError) as cm:
            bridge._call_local(["x"], "q", [])
        self.assertIn("context_length_exceeded", str(cm.exception))
        self.assertNotIn("Claude", str(cm.exception))

    def test_connection_refused_tells_how_to_start(self) -> None:
        self.gw.stop()
        with self.assertRaises(RuntimeError) as cm:
            bridge._call_local(["x"], "q", [])
        self.assertIn("llh serve", str(cm.exception))
        self.gw = FakeGateway()  # tearDown が止められるように

    def test_empty_answer_is_reported(self) -> None:
        self.gw.reply = ""
        answer = bridge._call_local(["x"], "q", [])
        self.assertIn("空", answer)


class LocalHandlerTests(unittest.TestCase):
    """/query と /api/llm-backend の通し。権限の絞り込みは、バックエンドが local でも同じ。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._saved = (bridge.BridgeHandler.mcp if hasattr(bridge.BridgeHandler, "mcp") else None,
                      bridge.BridgeHandler.auth, bridge.BridgeHandler.audit, bridge._LLM_BACKEND, bridge.LOCAL_LLM_URL)
        bridge.BridgeHandler.mcp = StubMcp()
        bridge.BridgeHandler.auth = FakeAuth()
        bridge.BridgeHandler.audit = None
        cls.gw = FakeGateway()
        bridge.LOCAL_LLM_URL = cls.gw.url
        bridge._LLM_BACKEND = "local"
        cls.server = HTTPServer(("127.0.0.1", 0), bridge.BridgeHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.gw.stop()
        (bridge.BridgeHandler.mcp, bridge.BridgeHandler.auth, bridge.BridgeHandler.audit,
         bridge._LLM_BACKEND, bridge.LOCAL_LLM_URL) = cls._saved

    def call(self, method: str, path: str, key: str, body: dict | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                     headers={"Content-Type": "application/json", "X-API-Key": key})
        res = conn.getresponse()
        data = json.loads(res.read() or b"{}")
        conn.close()
        return res.status, data

    def test_query_goes_to_gateway_and_keeps_namespace_isolation(self) -> None:
        self.gw.requests.clear()
        status, data = self.call("POST", "/query", "k-tool", {"query": "q"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["answer"], "回答です [1]")
        sent = json.dumps(self.gw.requests[0], ensure_ascii=False)
        self.assertIn("TOOLDOC-MARK", sent)
        for leaked in ("RESEARCH-MARK", "PERSONAL-MARK", "TEAM-MARK", "STRAY-MARK"):
            self.assertNotIn(leaked, sent, "権限の無い資料は、ローカルの LLM にも渡さない")

    def test_query_with_gateway_down_is_a_readable_error(self) -> None:
        saved = bridge.LOCAL_LLM_URL
        bridge.LOCAL_LLM_URL = "http://127.0.0.1:9/v1"
        try:
            status, data = self.call("POST", "/query", "k-tool", {"query": "q"})
        finally:
            bridge.LOCAL_LLM_URL = saved
        self.assertEqual(status, 500)
        self.assertIn("llh serve", data["error"])

    def test_backend_can_be_switched_to_local_and_back(self) -> None:
        for backend in ("claude", "gemini", "local"):
            status, data = self.call("POST", "/api/llm-backend", "k-admin", {"backend": backend})
            self.assertEqual((status, data), (200, {"backend": backend}))
        status, _ = self.call("POST", "/api/llm-backend", "k-admin", {"backend": "other"})
        self.assertEqual(status, 400)
        self.call("POST", "/api/llm-backend", "k-admin", {"backend": "local"})  # 他のテストのために戻す


if __name__ == "__main__":
    unittest.main()
