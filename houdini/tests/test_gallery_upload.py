"""gallery_upload.py（動画をギャラリーへアップロード）のテスト。偽のギャラリーを立てて検証する。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import gallery_upload as gu  # noqa: E402

TOKEN = "UPLOAD-TOKEN"


class _Gallery(BaseHTTPRequestHandler):
    """ragreel-gallery Worker の、POST /api/videos と GET /manifest.json の代役。"""

    uploads: list[dict] = []
    manifest: list[dict] = []
    status_override: int | None = None

    def log_message(self, *args) -> None:
        pass

    def _send(self, status: int, payload) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/manifest.json":
            self._send(200, _Gallery.manifest)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if _Gallery.status_override:
            return self._send(_Gallery.status_override, {"error": "boom"})
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"error": "unauthorized"})
        if self.path != "/api/videos":
            return self._send(404, {"error": "not found"})
        message = BytesParser(policy=HTTP).parsebytes(
            b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
        )
        fields: dict[str, object] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            payload = part.get_payload(decode=True)
            fields[name] = payload if part.get_filename() else payload.decode("utf-8")
        entry = json.loads(fields["entry"])
        if entry["id"] != fields["id"]:
            return self._send(400, {"error": "entry.id does not match id"})
        _Gallery.uploads.append({"fields": fields, "length": length})
        _Gallery.manifest = [entry] + [e for e in _Gallery.manifest if e["id"] != entry["id"]]
        self._send(200, {"ok": True, "id": entry["id"]})


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        _Gallery.uploads = []
        _Gallery.manifest = []
        _Gallery.status_override = None
        self.server = HTTPServer(("127.0.0.1", 0), _Gallery)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name) / "output"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def add_video(self, vid: str, size: int = 1000, created: str = "2026-10-01T00:00:00", thumb: bool = True) -> dict:
        folder = self.output / "videos" / vid
        folder.mkdir(parents=True)
        (folder / "video.webm").write_bytes(bytes(i % 251 for i in range(size)))
        if thumb:
            (folder / "thumb.png").write_bytes(b"\x89PNG-fake")
        entry = {
            "id": vid, "title": f"動画 {vid}", "created_at": created,
            "video_path": f"videos/{vid}/video.webm", "thumbnail_path": f"videos/{vid}/thumb.png",
        }
        (folder / "metadata.json").write_text(json.dumps({"id": vid, "chapters": []}), encoding="utf-8")
        manifest_path = self.output / "manifest.json"
        entries = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
        entries.insert(0, entry)
        manifest_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        return entry


class UploadEntryTest(_Case):
    def test_sends_id_entry_metadata_video_and_thumbnail_with_bearer(self) -> None:
        entry = self.add_video("cloudrag_1", size=3 * 256 * 1024 + 17)  # チャンクをまたぐ大きさ
        gu.upload_entry(self.url, TOKEN, self.output, entry)

        self.assertEqual(len(_Gallery.uploads), 1)
        fields = _Gallery.uploads[0]["fields"]
        self.assertEqual(fields["id"], "cloudrag_1")
        self.assertEqual(json.loads(fields["entry"])["title"], "動画 cloudrag_1", "Japanese survives")
        self.assertEqual(json.loads(fields["metadata"])["id"], "cloudrag_1")
        self.assertEqual(fields["video"], (self.output / "videos/cloudrag_1/video.webm").read_bytes())
        self.assertEqual(fields["thumbnail"], b"\x89PNG-fake")

    def test_thumbnail_is_optional_and_metadata_falls_back_to_the_entry(self) -> None:
        entry = self.add_video("v1", thumb=False)
        (self.output / "videos/v1/metadata.json").unlink()
        gu.upload_entry(self.url, TOKEN, self.output, entry)
        fields = _Gallery.uploads[0]["fields"]
        self.assertNotIn("thumbnail", fields)
        self.assertEqual(json.loads(fields["metadata"])["id"], "v1")

    def test_wrong_token_is_reported_as_an_auth_error(self) -> None:
        entry = self.add_video("v1")
        with self.assertRaises(gu.GalleryUploadError) as ctx:
            gu.upload_entry(self.url, "WRONG", self.output, entry)
        self.assertIn("認証エラー", str(ctx.exception))
        self.assertEqual(_Gallery.uploads, [])

    def test_server_error_and_missing_settings_and_missing_file(self) -> None:
        entry = self.add_video("v1")
        _Gallery.status_override = 500
        with self.assertRaises(gu.GalleryUploadError) as ctx:
            gu.upload_entry(self.url, TOKEN, self.output, entry)
        self.assertIn("HTTP 500", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))
        with self.assertRaises(gu.GalleryUploadError):
            gu.upload_entry("", TOKEN, self.output, entry)
        with self.assertRaises(gu.GalleryUploadError):
            gu.upload_entry(self.url, "", self.output, entry)
        (self.output / "videos/v1/video.webm").unlink()
        with self.assertRaises(gu.GalleryUploadError) as ctx2:
            gu.upload_entry(self.url, TOKEN, self.output, entry)
        self.assertIn("見つかりません", str(ctx2.exception))

    def test_oversized_video_is_refused_before_sending(self) -> None:
        entry = self.add_video("big", size=5000)
        with mock.patch.object(gu, "MAX_UPLOAD_BYTES", 1000):
            with self.assertRaises(gu.GalleryUploadError) as ctx:
                gu.upload_entry(self.url, TOKEN, self.output, entry)
        self.assertIn("大きすぎ", str(ctx.exception))
        self.assertEqual(_Gallery.uploads, [])

    def test_unreachable_gallery_is_reported(self) -> None:
        entry = self.add_video("v1")
        with self.assertRaises(gu.GalleryUploadError) as ctx:
            gu.upload_entry("http://127.0.0.1:1", TOKEN, self.output, entry, timeout=3)
        self.assertIn("接続できませんでした", str(ctx.exception))

    def test_a_bad_url_is_reported(self) -> None:
        entry = self.add_video("v1")
        with self.assertRaises(gu.GalleryUploadError):
            gu.upload_entry("not a url", TOKEN, self.output, entry)


class UploadMissingTest(_Case):
    def test_uploads_only_what_the_gallery_lacks_oldest_first(self) -> None:
        self.add_video("old", created="2026-09-01T00:00:00")
        self.add_video("have", created="2026-09-15T00:00:00")
        self.add_video("new", created="2026-10-01T00:00:00")
        _Gallery.manifest = [{"id": "have"}]
        messages: list[str] = []

        result = gu.upload_missing(self.url, TOKEN, self.output, progress=messages.append)

        self.assertEqual(result["uploaded"], ["old", "new"])
        self.assertEqual(result["skipped"], ["have"])
        self.assertEqual(result["failed"], [])
        self.assertEqual([u["fields"]["id"] for u in _Gallery.uploads], ["old", "new"])
        self.assertEqual(len(messages), 2)
        # もう一度やると、何も送らない（やり直しても重複しない）
        again = gu.upload_missing(self.url, TOKEN, self.output)
        self.assertEqual((again["uploaded"], sorted(again["skipped"])), ([], ["have", "new", "old"]))
        self.assertIn("2 本をアップロード", gu.describe_result(result))

    def test_only_ids_limits_the_targets(self) -> None:
        self.add_video("a")
        self.add_video("b")
        result = gu.upload_missing(self.url, TOKEN, self.output, only_ids={"b"})
        self.assertEqual(result["uploaded"], ["b"])

    def test_one_failure_does_not_stop_the_rest_but_an_auth_error_does(self) -> None:
        self.add_video("a", created="2026-09-01T00:00:00")
        self.add_video("b", created="2026-09-02T00:00:00")
        (self.output / "videos/a/video.webm").unlink()  # a は動画が無い
        result = gu.upload_missing(self.url, TOKEN, self.output)
        self.assertEqual(result["uploaded"], ["b"])
        self.assertEqual(result["failed"][0][0], "a")
        self.assertIn("1 本が失敗", gu.describe_result(result))

        self.add_video("c", created="2026-09-03T00:00:00")
        _Gallery.manifest = []
        bad = gu.upload_missing(self.url, "WRONG", self.output)
        self.assertEqual([f[0] for f in bad["failed"]], ["a", "b"], "stops at the first auth error; c is never tried")


class FindLocalEntryTest(_Case):
    def test_matches_by_file_name_then_by_size(self) -> None:
        entry = self.add_video("cloudrag_20261021_210954531_3408", size=1234)
        self.assertEqual(
            gu.find_local_entry(self.output, Path("C:/x/phase2_cloudrag_20261021_210954531_3408.webm"))["id"],
            entry["id"],
        )
        other = Path(self._tmp.name) / "renamed.webm"
        other.write_bytes(bytes(1234))
        self.assertEqual(gu.find_local_entry(self.output, other)["id"], entry["id"], "same size")
        different = Path(self._tmp.name) / "different.webm"
        different.write_bytes(bytes(99))
        self.assertIsNone(gu.find_local_entry(self.output, different))
        self.assertIsNone(gu.find_local_entry(Path(self._tmp.name) / "nowhere", other))

    def test_a_broken_manifest_is_treated_as_empty(self) -> None:
        self.output.mkdir()
        (self.output / "manifest.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(gu.read_local_manifest(self.output), [])


class StreamAndProgressTest(_Case):
    """実機で RecursionError になった（数十MBの動画を、小さな単位で読むと、入れ子が深くなった）不具合の再発防止と、進み具合。"""

    def test_a_large_body_read_in_small_pieces_does_not_recurse_and_is_intact(self) -> None:
        folder = self.output / "videos" / "big"
        folder.mkdir(parents=True)
        data = bytes(i % 251 for i in range(6 * 1024 * 1024))  # 8KB ずつ読むと、約800回（以前は、数千回で落ちた）
        (folder / "video.webm").write_bytes(data * 3)  # 18MB → 約2,300回の read
        stream = gu._MultipartStream([("id", "big")], [("video", folder / "video.webm", "video.webm", "video/webm")])
        reads = 0
        total = bytearray()
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            reads += 1
            total += chunk
        self.assertGreater(reads, 2000)
        self.assertEqual(len(total), stream.length, "Content-Length matches what is actually sent")
        self.assertIn(data * 3, bytes(total))

    def test_read_all_and_odd_sizes(self) -> None:
        entry = self.add_video("v1", size=1000)
        video, _, _ = gu.entry_files(self.output, entry)
        for size in (1, 7, 255, 4096, 10_000_000):
            stream = gu._MultipartStream([("id", "v1")], [("video", video, "video.webm", "video/webm")])
            out = b""
            while chunk := stream.read(size):
                out += chunk
            self.assertEqual(len(out), stream.length, size)
        stream = gu._MultipartStream([("id", "v1")], [("video", video, "video.webm", "video/webm")])
        self.assertEqual(len(stream.read()), stream.length, "read() with no size returns everything")

    def test_progress_is_monotonic_and_ends_at_the_total(self) -> None:
        entry = self.add_video("v1", size=3 * 1024 * 1024)
        seen: list[tuple[int, int]] = []
        sent = gu.upload_entry(self.url, TOKEN, self.output, entry, progress=lambda a, b: seen.append((a, b)))
        self.assertGreater(len(seen), 3)
        values = [a for a, _ in seen]
        self.assertEqual(values, sorted(values))
        self.assertEqual(seen[-1][0], seen[-1][1])
        self.assertEqual(seen[-1][1], sent)
        self.assertEqual(len(_Gallery.uploads), 1)

    def test_upload_missing_reports_overall_percent_across_videos(self) -> None:
        self.add_video("a", size=2 * 1024 * 1024, created="2026-09-01T00:00:00")
        self.add_video("b", size=1 * 1024 * 1024, created="2026-09-02T00:00:00")
        self.add_video("have", size=500_000, created="2026-09-03T00:00:00")
        _Gallery.manifest = [{"id": "have"}]
        calls: list[tuple[int, int, str]] = []
        result = gu.upload_missing(self.url, TOKEN, self.output, on_bytes=lambda d, t, label: calls.append((d, t, label)))
        self.assertEqual(result["uploaded"], ["a", "b"])
        total = calls[0][1]
        self.assertTrue(all(t == total for _, t, _ in calls), "one fixed total (what will be sent)")
        self.assertLess(total, 3 * 1024 * 1024 + 20_000, "the video the gallery already has is not counted")
        self.assertEqual(calls[0][0], 0)
        done = [d for d, _, _ in calls]
        self.assertEqual(done, sorted(done))
        self.assertEqual(done[-1], total, "ends at 100%")
        self.assertTrue(any("動画 b" in label for _, _, label in calls), "the title of the video being sent is reported")

    def test_a_failed_upload_does_not_break_the_progress_total(self) -> None:
        self.add_video("a", size=1000, created="2026-09-01T00:00:00")
        _Gallery.status_override = 500
        calls: list[tuple[int, int, str]] = []
        result = gu.upload_missing(self.url, TOKEN, self.output, on_bytes=lambda d, t, label: calls.append((d, t, label)))
        self.assertEqual(result["uploaded"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertTrue(all(d <= t for d, t, _ in calls))


class GalleryEnvTest(unittest.TestCase):
    def test_env_is_given_to_the_engine_only_when_complete_and_enabled(self) -> None:
        cfg = {"gallery_url": " https://g.example.workers.dev ", "gallery_token": " T ", "gallery_auto_upload": True}
        self.assertEqual(gu.gallery_env(cfg), {"GALLERY_UPLOAD_URL": "https://g.example.workers.dev", "GALLERY_UPLOAD_TOKEN": "T"})
        self.assertEqual(gu.gallery_env({**cfg, "gallery_auto_upload": False}), {})
        self.assertEqual(gu.gallery_env({**cfg, "gallery_token": ""}), {})
        self.assertEqual(gu.gallery_env({"gallery_url": "https://x"}), {})
        self.assertEqual(gu.gallery_env({}), {})


if __name__ == "__main__":
    unittest.main()
