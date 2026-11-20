"""reference_remote（Reference の説明を、Cloudflare から取る・置く）のテスト（2026-11-19）。通信は、opener で差し替える（実際には呼ばない）。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_reference_remote.py -v
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import reference_remote as rr  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeServer:
    """opener として渡す。呼ばれたパスと本文・ヘッダーを記録し、パスごとの応答を返す。"""

    def __init__(self, routes: dict, fail: bool = False) -> None:
        self.routes, self.fail, self.calls = routes, fail, []

    def __call__(self, req, timeout):
        path = req.full_url.split("example.invalid", 1)[1]
        self.calls.append((path, req.data, dict(req.header_items())))
        if self.fail:
            raise urllib.error.URLError("offline")
        body = self.routes[path.split("?")[0]]
        return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))


INDEX = {"status": "ok", "items": [{"kind": "node", "key": "sop/scatter", "title": "Scatter", "version": 2, "mediaCount": 1}]}
ENTRY = {"status": "ok", "kind": "node", "key": "sop/scatter", "title": "Scatter", "version": 2, "entry": {"what": "点を散らす"},
         "media": [{"id": "node/sop/scatter/after.png", "type": "image", "role": "after", "label": "後"}]}


class RemoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"cf_url": "https://example.invalid/", "cf_api_key": "k-test", "local_bridge_dir": self.tmp.name}

    def test_index_is_cached_for_an_hour_and_falls_back_when_offline(self) -> None:
        server = FakeServer({"/reference/index": INDEX})
        first = rr.fetch_index(self.cfg, now=1000.0, opener=server)
        self.assertEqual(list(first), ["node|sop/scatter"])
        self.assertEqual(rr.fetch_index(self.cfg, now=1000.0 + 3000, opener=server), first)
        self.assertEqual(len(server.calls), 1, "no second request inside the hour")
        self.assertEqual(len(rr.fetch_index(self.cfg, now=1000.0 + 4000, opener=FakeServer({"/reference/index": INDEX}), force=False)), 1)
        offline = FakeServer({}, fail=True)
        self.assertEqual(rr.fetch_index(self.cfg, now=1000.0 + 99999, opener=offline), first, "an old saved list is used when offline")
        self.assertEqual(rr.load_cached_index(self.cfg), first)

    def test_requests_carry_the_key_and_a_user_agent_and_use_post(self) -> None:
        server = FakeServer({"/reference/index": INDEX})
        rr.fetch_index(self.cfg, opener=server)
        path, data, headers = server.calls[0]
        self.assertEqual(path, "/reference/index")
        self.assertEqual(headers.get("Authorization"), "Bearer k-test")
        self.assertIn("User-agent", headers)
        self.assertIsNotNone(data, "POST has a body")

    def test_no_url_or_no_folder_does_not_raise(self) -> None:
        self.assertEqual(rr.fetch_index({}, opener=FakeServer({})), {})
        self.assertEqual(rr.fetch_index({"cf_url": "https://example.invalid"}, opener=FakeServer({"/reference/index": INDEX}))["node|sop/scatter"]["version"], 2)
        self.assertIsNone(rr.fetch_entry({}, "node", "sop/scatter", opener=FakeServer({})))
        self.assertIsNone(rr.fetch_media({}, "a.png"))

    def test_garbage_index_is_ignored(self) -> None:
        for body in (b"not json", b"[]", b'{"items": [1, null, {"kind": "node"}]}'):
            self.assertEqual(rr.fetch_index(self.cfg, opener=FakeServer({"/reference/index": body}), force=True), {})

    def test_entry_is_saved_and_reused_while_the_version_is_the_same(self) -> None:
        server = FakeServer({"/reference/entry": ENTRY})
        record = rr.fetch_entry(self.cfg, "node", "sop/scatter", version=2, opener=server)
        self.assertEqual(record["entry"]["what"], "点を散らす")
        self.assertEqual(record["version"], 2)
        self.assertEqual(json.loads(server.calls[0][1]), {"kind": "node", "key": "sop/scatter"})
        again = rr.fetch_entry(self.cfg, "node", "sop/scatter", version=2, opener=server)
        self.assertEqual(again, record)
        self.assertEqual(len(server.calls), 1)
        rr.fetch_entry(self.cfg, "node", "sop/scatter", version=3, opener=server)  # 版が上がったので、取り直す
        self.assertEqual(len(server.calls), 2)
        offline = rr.fetch_entry(self.cfg, "node", "sop/scatter", version=9, opener=FakeServer({}, fail=True))
        self.assertEqual(offline["entry"]["what"], "点を散らす", "the saved one is used when offline")
        self.assertIsNone(rr.fetch_entry(self.cfg, "node", "sop/none", version=1, opener=FakeServer({}, fail=True)))

    def test_a_missing_entry_is_none(self) -> None:
        def not_found(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"error": "none"}'))

        self.assertIsNone(rr.fetch_entry(self.cfg, "node", "sop/x", version=1, opener=not_found))

    def test_media_is_saved_once(self) -> None:
        server = FakeServer({"/reference/media": b"\x89PNGdata"})
        path = rr.fetch_media(self.cfg, "node/sop/scatter/after.png", opener=server)
        self.assertEqual(path.read_bytes(), b"\x89PNGdata")
        self.assertEqual(rr.fetch_media(self.cfg, "node/sop/scatter/after.png", opener=server), path)
        self.assertEqual(len(server.calls), 1)
        self.assertEqual(json.loads(server.calls[0][1]), {"id": "node/sop/scatter/after.png"})
        self.assertIsNone(rr.fetch_media(self.cfg, "x/y.png", opener=FakeServer({}, fail=True)))
        self.assertTrue(str(path).startswith(self.tmp.name), "never writes outside the folder")
        evil = rr.media_path(self.cfg, "../../../evil.png")
        self.assertTrue(str(evil.resolve()).startswith(str(Path(self.tmp.name).resolve())), "a path-like id cannot escape the cache folder")

    def test_prune_cache_removes_media_no_entry_uses_and_keeps_the_total_under_the_cap(self) -> None:
        server = FakeServer({"/reference/entry": ENTRY, "/reference/media": b"x" * 100})
        rr.fetch_entry(self.cfg, "node", "sop/scatter", version=2, opener=server)
        used = rr.fetch_media(self.cfg, "node/sop/scatter/after.png", opener=server)
        old = rr.media_path(self.cfg, "node/sop/scatter/after.old.png")
        old.write_bytes(b"old")  # 説明が更新されて、どの説明からも使われなくなった画像
        self.assertEqual(rr.prune_cache(self.cfg), 1)
        self.assertTrue(used.is_file())
        self.assertFalse(old.exists())
        self.assertEqual(rr.prune_cache(self.cfg), 0, "nothing more to remove")
        self.assertEqual(rr.prune_cache(self.cfg, max_bytes=10), 1, "over the cap: the used one goes too")
        self.assertFalse(used.exists())
        self.assertTrue(rr.load_cached_entry(self.cfg, "node", "sop/scatter"), "the text entry is kept")
        self.assertEqual(rr.prune_cache({}), 0)
        self.assertEqual(rr.prune_cache({"local_bridge_dir": self.tmp.name + "/none"}), 0)

    def test_delete_entry_asks_the_worker_to_unpublish(self) -> None:
        server = FakeServer({"/admin/reference/delete": {"status": "ok", "deleted": 1}})
        self.assertEqual(rr.delete_entry(self.cfg, "node", "sop/transform", opener=server)["deleted"], 1)
        self.assertEqual(server.calls[0][0], "/admin/reference/delete")
        self.assertEqual(json.loads(server.calls[0][1]), {"kind": "node", "key": "sop/transform"})

    def test_publish_sends_the_entry_and_the_media(self) -> None:
        server = FakeServer({"/admin/reference/put": {"status": "ok", "version": 1}, "/admin/reference/media_put": {"status": "ok", "bytes": 3}})
        result = rr.publish_entry(self.cfg, "node", "sop/scatter", "Scatter", {"what": "x"}, [{"id": "a.png", "role": "after"}], opener=server)
        self.assertEqual(result["version"], 1)
        sent = json.loads(server.calls[0][1])
        self.assertEqual((sent["kind"], sent["key"], sent["title"], sent["entry"]), ("node", "sop/scatter", "Scatter", {"what": "x"}))
        rr.publish_media(self.cfg, "node/sop/scatter/after.png", b"abc", opener=server)
        path, data, headers = server.calls[1]
        self.assertEqual(path, "/admin/reference/media_put?id=node/sop/scatter/after.png")
        self.assertEqual(data, b"abc")
        self.assertEqual(headers.get("Content-type"), "application/octet-stream")

    def test_error_text_prefers_the_worker_message(self) -> None:
        err = urllib.error.HTTPError("u", 403, "x", {}, io.BytesIO('{"error": "管理者権限が必要です"}'.encode("utf-8")))
        self.assertEqual(rr.error_text(err), "管理者権限が必要です")
        self.assertEqual(rr.error_text(urllib.error.HTTPError("u", 502, "x", {}, io.BytesIO(b"<html>"))), "HTTP 502")
        self.assertIn("接続できません", rr.error_text(urllib.error.URLError("dns")))


if __name__ == "__main__":
    unittest.main()
