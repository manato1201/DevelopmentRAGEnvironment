"""gallery_upload.py の「分けて送る」経路（90MB を超える動画）のテスト（2026-11-18）。

実機で、1080p30 の長い動画が「Payload Too Large」で投稿できなかった。90MB を超える動画は、ギャラリーの
POST /api/videos/uploads → PUT parts/n → POST complete で、パートごとに送る。偽のギャラリーを立てて確かめる
（Worker 側は、RAGReel/cloudflare/ragreel-gallery/test/chunked_upload.test.js）。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_gallery_chunked.py -v
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import gallery_upload as gu  # noqa: E402

TOKEN = "UPLOAD-TOKEN"


class _Gallery(BaseHTTPRequestHandler):
    """ragreel-gallery Worker の、分けて送る経路の代役。"""

    log: list[tuple[str, str]] = []
    parts: dict[int, bytes] = {}
    completed: dict | None = None
    aborted = False
    manifest: list[dict] = []
    fail_part_times = 0  # 最初の N 回の PUT を 503 にする
    fail_part_status = 503
    complete_status = 200
    part_size = 5

    def log_message(self, *args) -> None:
        pass

    def _send(self, status: int, payload) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _auth(self) -> bool:
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_POST(self) -> None:  # noqa: N802
        body = self._body()
        _Gallery.log.append(("POST", self.path))
        if not self._auth():
            return
        if self.path == "/api/videos/uploads":
            return self._send(200, {"ok": True, "uploadId": "up1", "partSize": _Gallery.part_size})
        if self.path == "/api/videos/uploads/up1/complete":
            if _Gallery.complete_status != 200:
                return self._send(_Gallery.complete_status, {"error": "complete failed"})
            _Gallery.completed = json.loads(body)
            _Gallery.manifest = [_Gallery.completed["entry"]]
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_PUT(self) -> None:  # noqa: N802
        body = self._body()
        _Gallery.log.append(("PUT", self.path))
        if not self._auth():
            return
        url = urlsplit(self.path)
        if _Gallery.fail_part_times > 0:
            _Gallery.fail_part_times -= 1
            return self._send(_Gallery.fail_part_status, {"error": "temporary"})
        pieces = url.path.split("/")
        if pieces[:4] == ["", "api", "videos", "uploads"] and len(pieces) == 7 and pieces[5] == "parts":
            number = int(pieces[6])
            if parse_qs(url.query).get("id") != ["cloudrag_1"]:
                return self._send(400, {"error": "invalid id"})
            _Gallery.parts[number] = body
            return self._send(200, {"ok": True, "partNumber": number, "etag": f"e{number}"})
        self._send(404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        _Gallery.log.append(("DELETE", self.path))
        if not self._auth():
            return
        if self.path.startswith("/api/videos/uploads/up1"):
            _Gallery.aborted = True
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/manifest.json":
            return self._send(200, _Gallery.manifest)
        self._send(404, {"error": "not found"})


class ChunkedUploadTest(unittest.TestCase):
    def setUp(self) -> None:
        _Gallery.log, _Gallery.parts, _Gallery.completed = [], {}, None
        _Gallery.aborted, _Gallery.manifest = False, []
        _Gallery.fail_part_times, _Gallery.fail_part_status, _Gallery.complete_status = 0, 503, 200
        _Gallery.part_size = 5
        self.server = HTTPServer(("127.0.0.1", 0), _Gallery)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.entry = {"id": "cloudrag_1", "title": "長い動画"}
        folder = self.out / "videos" / "cloudrag_1"
        folder.mkdir(parents=True)
        self.video = bytes(range(256)) * 4  # 1024 バイト
        (folder / "video.webm").write_bytes(self.video)
        (folder / "thumb.png").write_bytes(b"PNG-THUMB")
        (folder / "metadata.json").write_text(json.dumps({"id": "cloudrag_1", "rag_sources": []}), encoding="utf-8")
        # 小さい動画でも、分けて送る経路・小さいパートで確かめる
        for patch in (
            mock.patch.object(gu, "SINGLE_UPLOAD_BYTES", 100),
            mock.patch.object(gu, "_MIN_PART_BYTES", 1),
            mock.patch.object(gu.time, "sleep", lambda _s: None),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def upload(self, **kw) -> int:
        return gu.upload_entry(self.url, kw.pop("token", TOKEN), self.out, self.entry, **kw)

    def test_a_video_over_the_single_limit_is_sent_in_parts_and_published(self) -> None:
        sent = self.upload()
        self.assertEqual(sent, len(self.video) + len(b"PNG-THUMB"))
        self.assertEqual(sorted(_Gallery.parts), list(range(1, 206)))  # 1024 / 5 = 204.8 → 205 パート
        self.assertEqual(b"".join(_Gallery.parts[n] for n in sorted(_Gallery.parts)), self.video)
        done = _Gallery.completed
        self.assertEqual(done["id"], "cloudrag_1")
        self.assertEqual([p["partNumber"] for p in done["parts"]], list(range(1, 206)))
        self.assertEqual(base64.b64decode(done["thumbnail_base64"]), b"PNG-THUMB")
        self.assertEqual(done["entry"], self.entry)
        self.assertEqual(done["metadata"]["id"], "cloudrag_1")
        self.assertFalse(_Gallery.aborted)

    def test_rag_sources_are_filled_from_the_script_only_when_empty(self) -> None:
        sources = [{"file": "Pyro Solver", "cited": True}]
        self.upload(sources=sources)
        self.assertEqual(_Gallery.completed["metadata"]["rag_sources"], [{"file": "Pyro Solver", "cited": True}])

    def test_progress_reaches_the_total(self) -> None:
        seen: list[tuple[int, int]] = []
        self.upload(progress=lambda sent, total: seen.append((sent, total)))
        total = len(self.video) + len(b"PNG-THUMB")
        self.assertEqual(seen[-1], (total, total))
        self.assertTrue(all(b >= a for (a, _), (b, _) in zip(seen, seen[1:])), "進み具合は、戻らない")

    def test_a_video_at_or_below_the_single_limit_still_uses_the_single_post(self) -> None:
        with mock.patch.object(gu, "SINGLE_UPLOAD_BYTES", 10_000), mock.patch.object(gu, "_upload_chunked") as chunked:
            with mock.patch.object(gu, "_connection", side_effect=gu.GalleryUploadError("single post path")):
                with self.assertRaises(gu.GalleryUploadError):
                    self.upload()
        chunked.assert_not_called()

    def test_a_temporary_failure_of_a_part_is_retried(self) -> None:
        _Gallery.fail_part_times = 2  # 最初の 2 回の PUT が 503
        self.upload()
        self.assertEqual(len(_Gallery.parts), 205)
        self.assertEqual(sum(1 for m, _p in _Gallery.log if m == "PUT"), 207)

    def test_a_part_that_keeps_failing_aborts_the_upload_and_reports(self) -> None:
        _Gallery.fail_part_times = 99
        with self.assertRaises(gu.GalleryUploadError) as ctx:
            self.upload()
        self.assertIn("503", str(ctx.exception))
        self.assertTrue(_Gallery.aborted, "途中の分を、ギャラリーに捨てさせる")
        self.assertIsNone(_Gallery.completed)

    def test_a_client_error_on_a_part_is_not_retried(self) -> None:
        _Gallery.fail_part_times, _Gallery.fail_part_status = 99, 413
        with self.assertRaises(gu.GalleryUploadError) as ctx:
            self.upload()
        self.assertIn("大きすぎ", str(ctx.exception))
        self.assertEqual(sum(1 for m, _p in _Gallery.log if m == "PUT"), 1)
        self.assertTrue(_Gallery.aborted)

    def test_a_failing_complete_aborts_and_reports(self) -> None:
        _Gallery.complete_status = 500
        with self.assertRaises(gu.GalleryUploadError):
            self.upload()
        self.assertTrue(_Gallery.aborted)
        self.assertEqual(_Gallery.manifest, [])

    def test_a_wrong_token_fails_at_the_start_with_no_parts_sent(self) -> None:
        with self.assertRaises(gu.GalleryUploadError) as ctx:
            self.upload(token="wrong")
        self.assertIn("認証エラー", str(ctx.exception))
        self.assertEqual(_Gallery.parts, {})

    def test_the_server_part_size_is_used_within_limits(self) -> None:
        _Gallery.part_size = 400
        self.upload()
        self.assertEqual(sorted(_Gallery.parts), [1, 2, 3])
        self.assertEqual([len(_Gallery.parts[n]) for n in (1, 2, 3)], [400, 400, 224])

    def test_a_video_over_the_hard_limit_is_refused_before_any_request(self) -> None:
        with mock.patch.object(gu, "MAX_UPLOAD_BYTES", 500):
            with self.assertRaises(gu.GalleryUploadError) as ctx:
                self.upload()
        self.assertIn("大きすぎ", str(ctx.exception))
        self.assertEqual(_Gallery.log, [])

    def test_upload_missing_sends_a_big_video_and_counts_it(self) -> None:
        (self.out / "manifest.json").write_text(json.dumps([self.entry]), encoding="utf-8")
        result = gu.upload_missing(self.url, TOKEN, self.out)
        self.assertEqual(result["uploaded"], ["cloudrag_1"])
        self.assertEqual(result["failed"], [])


if __name__ == "__main__":
    unittest.main()
