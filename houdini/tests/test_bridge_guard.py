"""scripts/bridge_guard.py と rag_local_bridge の Host / Origin 検査のテスト。
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

import bridge_guard as g  # noqa: E402


class GuardFunctionTests(unittest.TestCase):
    def setUp(self) -> None:
        for k in (g.ALLOWED_HOSTS_ENV, g.CORS_ORIGINS_ENV):
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        self.setUp()

    def test_host_only(self) -> None:
        self.assertEqual(g.host_only("localhost:8766"), "localhost")
        self.assertEqual(g.host_only("127.0.0.1:8766"), "127.0.0.1")
        self.assertEqual(g.host_only("[::1]:8766"), "::1")
        self.assertEqual(g.host_only("LocalHost"), "localhost")

    def test_loopback_hosts_allowed_others_not(self) -> None:
        self.assertTrue(g.host_allowed("localhost:8766"))
        self.assertTrue(g.host_allowed("127.0.0.1:8766"))
        self.assertTrue(g.host_allowed("[::1]:8766"))
        self.assertFalse(g.host_allowed("evil.example:8766"))
        self.assertFalse(g.host_allowed(""))

    def test_extra_host_via_env(self) -> None:
        os.environ[g.ALLOWED_HOSTS_ENV] = "rag.internal"
        self.assertTrue(g.host_allowed("rag.internal:8766"))

    def test_origin_rules(self) -> None:
        host = "localhost:8766"
        self.assertTrue(g.origin_allowed(None, host))  # Unity / curl / CI
        self.assertTrue(g.origin_allowed("http://localhost:8766", host))  # 同一オリジン
        self.assertFalse(g.origin_allowed("http://evil.example", host))
        self.assertFalse(g.origin_allowed("null", host))
        self.assertFalse(g.origin_allowed("", host))
        self.assertFalse(g.origin_allowed("http://localhost:9999", host))  # ポート違い

    def test_cors_allowlist(self) -> None:
        os.environ[g.CORS_ORIGINS_ENV] = "http://localhost:3000"
        self.assertTrue(g.origin_allowed("http://localhost:3000", "localhost:8766"))
        self.assertEqual(
            g.cors_headers_for("http://localhost:3000")["Access-Control-Allow-Origin"],
            "http://localhost:3000")
        self.assertEqual(g.cors_headers_for("http://evil.example"), {})
        self.assertEqual(g.cors_headers_for(None), {})

    def test_check_request_only_unsafe_methods_check_origin(self) -> None:
        host = "localhost:8766"
        self.assertIsNone(g.check_request("GET", host, "http://evil.example"))
        self.assertIsNotNone(g.check_request("POST", host, "http://evil.example"))
        self.assertIsNotNone(g.check_request("DELETE", host, "null"))
        self.assertIsNone(g.check_request("POST", host, None))
        self.assertIsNotNone(g.check_request("GET", "evil.example", None))


class BridgeHandlerTests(unittest.TestCase):
    """実ハンドラを起動して HTTP で確認する(認証モジュールは未設定=anonymous でない状態)。"""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import rag_local_bridge as bridge
        except Exception as e:  # 依存(chromadb 等)が無い環境では飛ばす
            raise unittest.SkipTest(f"rag_local_bridge を読み込めない: {e}")
        bridge.BridgeHandler.auth = None
        bridge.BridgeHandler.allow_anonymous = False
        cls.server = HTTPServer(("127.0.0.1", 0), bridge.BridgeHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        for k in (g.ALLOWED_HOSTS_ENV, g.CORS_ORIGINS_ENV):
            os.environ.pop(k, None)

    def request(self, method: str, path: str, headers: dict | None = None, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=h)
        res = conn.getresponse()
        res.read()
        out = (res.status, {k.lower(): v for k, v in res.getheaders()})
        conn.close()
        return out

    def test_foreign_host_refused(self) -> None:
        status, _ = self.request("GET", "/ui", {"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_foreign_origin_post_refused_before_auth(self) -> None:
        status, _ = self.request("POST", "/query", {"Origin": "http://evil.example"}, {"q": "x"})
        self.assertEqual(status, 403)

    def test_null_origin_post_refused(self) -> None:
        status, _ = self.request("POST", "/query", {"Origin": "null"}, {"q": "x"})
        self.assertEqual(status, 403)

    def test_post_without_origin_reaches_auth(self) -> None:
        # Unity / curl 等は Origin なし。ガードは通り、認証層(fail-closed)で 401 になる。
        status, _ = self.request("POST", "/query", {}, {"q": "x"})
        self.assertEqual(status, 401)

    def test_same_origin_post_reaches_auth(self) -> None:
        status, _ = self.request(
            "POST", "/query", {"Origin": f"http://127.0.0.1:{self.port}"}, {"q": "x"})
        self.assertEqual(status, 401)

    def test_no_wildcard_cors_on_response(self) -> None:
        _, headers = self.request("POST", "/query", {"Origin": "http://evil.example"}, {"q": "x"})
        self.assertNotIn("access-control-allow-origin", headers)

    def test_preflight_from_foreign_origin_gets_no_cors(self) -> None:
        status, headers = self.request("OPTIONS", "/query", {"Origin": "http://evil.example"})
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertLess(status, 300)

    def test_preflight_from_allowlisted_origin(self) -> None:
        os.environ[g.CORS_ORIGINS_ENV] = "http://localhost:3000"
        _, headers = self.request("OPTIONS", "/query", {"Origin": "http://localhost:3000"})
        self.assertEqual(headers.get("access-control-allow-origin"), "http://localhost:3000")

    def test_allowlisted_origin_post_reaches_auth(self) -> None:
        os.environ[g.CORS_ORIGINS_ENV] = "http://localhost:3000"
        status, headers = self.request("POST", "/query", {"Origin": "http://localhost:3000"}, {"q": "x"})
        self.assertEqual(status, 401)
        self.assertEqual(headers.get("access-control-allow-origin"), "http://localhost:3000")


if __name__ == "__main__":
    unittest.main()
