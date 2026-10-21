"""rag_client.py（Cloudflare クライアントと設定の移行）のテスト。偽のサーバーを立てて検証する。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import rag_client as rc  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    calls: list[dict] = []
    reply: dict = {}
    status: int = 200

    def log_message(self, *args) -> None:  # テストの出力を汚さない
        pass

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else None
        _Handler.calls.append(
            {
                "method": self.command,
                "path": self.path,
                "body": body,
                "headers": dict(self.headers),
            }
        )
        data = json.dumps(_Handler.reply).encode("utf-8")
        self.send_response(_Handler.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _respond
    do_POST = _respond


class _ServerCase(unittest.TestCase):
    def setUp(self) -> None:
        _Handler.calls = []
        _Handler.reply = {"status": "ok"}
        _Handler.status = 200
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def cfg(self, **extra) -> dict:
        return {
            "mode": "cloudflare",
            "cf_url": self.url + "/",
            "cf_api_key": "KEY",
            "local_port": 1,
            **extra,
        }


class RAGClientTest(_ServerCase):
    def test_query_sends_bearer_user_agent_and_worker_shaped_body(self) -> None:
        _Handler.reply = {"answer": "A", "sources": [{"file": "f.md"}], "memoryId": 7}
        client = rc.RAGClient(
            self.cfg(cf_namespaces="houdini22, shared:houdini22,houdini22")
        )
        history = [{"role": "user", "text": "q1"}, {"role": "assistant", "text": "a1"}]
        result = client.query("hello", history, image_b64="QUJD", context="sop")

        self.assertEqual(result["memoryId"], 7)
        call = _Handler.calls[0]
        self.assertEqual((call["method"], call["path"]), ("POST", "/query"))
        self.assertEqual(call["headers"]["Authorization"], "Bearer KEY")
        self.assertTrue(call["headers"]["User-Agent"].startswith("HoudiniRAGPanel"))
        self.assertEqual(call["body"]["query"], "hello")
        self.assertEqual(
            call["body"]["history"][0],
            {"role": "user", "content": "q1"},
            "text -> content",
        )
        self.assertEqual(
            call["body"]["namespaces"],
            ["houdini22", "shared:houdini22"],
            "deduplicated",
        )
        self.assertEqual(call["body"]["context"], "sop")
        self.assertEqual(
            call["body"]["image"], {"mimeType": "image/png", "data": "QUJD"}
        )
        self.assertNotIn("apiKey", call["body"], "the key goes in the header only")

    def test_empty_namespaces_are_not_sent(self) -> None:
        rc.RAGClient(self.cfg(cf_namespaces="")).query("q", [])
        self.assertNotIn("namespaces", _Handler.calls[0]["body"])

    def test_query_without_url_fails_clearly(self) -> None:
        with self.assertRaises(RuntimeError):
            rc.RAGClient({"mode": "cloudflare", "cf_url": ""}).query("q", [])

    def test_health(self) -> None:
        self.assertTrue(rc.RAGClient(self.cfg()).health())
        self.assertEqual(_Handler.calls[0]["path"], "/health")
        _Handler.reply = {"status": "down"}
        self.assertFalse(rc.RAGClient(self.cfg()).health())
        self.assertFalse(rc.RAGClient(self.cfg(cf_url="")).health())
        self.assertFalse(rc.RAGClient(self.cfg(cf_url="http://127.0.0.1:1")).health())

    def test_rate_maps_up_down_to_numbers_and_needs_a_numeric_id(self) -> None:
        client = rc.RAGClient(self.cfg())
        self.assertTrue(client.rate(12, "up"))
        self.assertTrue(client.rate("13", "down"))
        self.assertEqual(_Handler.calls[0]["body"], {"id": 12, "rating": 1})
        self.assertEqual(_Handler.calls[1]["body"], {"id": 13, "rating": -1})
        self.assertEqual(_Handler.calls[0]["path"], "/memory/rate")
        self.assertFalse(client.rate("", "up"))
        self.assertFalse(client.rate("abc", "up"))
        _Handler.status = 404
        self.assertFalse(client.rate(99, "up"))

    def test_local_mode_rate_is_a_noop(self) -> None:
        self.assertTrue(rc.RAGClient({"mode": "local", "local_port": 1}).rate(1, "up"))
        self.assertEqual(_Handler.calls, [])


class MigrateConfigTest(unittest.TestCase):
    def test_legacy_cloud_mode_becomes_cloudflare_and_gas_keys_are_dropped(
        self,
    ) -> None:
        old = {
            "mode": "cloud",
            "gas_url": "https://script.google.com/x",
            "gas_api_key": "k",
            "gas_db_key": "all",
            "tutorial_rag_mode": "cloud",
            "tutorial_claude_backend": "gas",
            "cf_url": "https://a.workers.dev",
            "cf_api_key": "K",
            "local_port": 9000,
        }
        new = rc.migrate_config(old)
        self.assertEqual(new["mode"], "cloudflare")
        for key in rc.LEGACY_KEYS:
            self.assertNotIn(key, new)
        self.assertEqual(
            (new["cf_url"], new["cf_api_key"], new["local_port"]),
            ("https://a.workers.dev", "K", 9000),
        )
        self.assertIn("gas_url", old, "the input is not modified")

    def test_valid_modes_are_kept_and_unknown_ones_fall_back(self) -> None:
        self.assertEqual(rc.migrate_config({"mode": "local"})["mode"], "local")
        self.assertEqual(
            rc.migrate_config({"mode": "cloudflare"})["mode"], "cloudflare"
        )
        self.assertEqual(rc.migrate_config({"mode": "weird"})["mode"], "cloudflare")


class NormalizeGraphTest(unittest.TestCase):
    def test_worker_nodes_and_edges_get_the_fields_the_view_reads(self) -> None:
        data = {
            "nodes": [
                {"id": "n1", "label": "L", "namespace": "shared:houdini22", "size": 9},
                {"id": "n2", "label": "M", "namespace": ""},
            ],
            "edges": [{"source": "n1", "target": "n2", "weight": 0.8}],
            "status": "ok",
        }
        out = rc.normalize_cloudflare_graph(data)
        self.assertEqual(out["nodes"][0]["db"], "houdini22")
        self.assertEqual(out["nodes"][0]["chunk_count"], 9)
        self.assertEqual(out["nodes"][1]["db"], "")
        self.assertEqual(out["edges"][0]["score"], 0.8)
        self.assertEqual(out["status"], "ok")
        self.assertNotIn("db", data["nodes"][0], "the input is not modified")


if __name__ == "__main__":
    unittest.main()
