"""video_progress.upload_status: エンジンが動画をギャラリーへ自動アップロードした結果を、ログから読む（2026-11-18）。

実機の記録（energy-effect-layer-design_20261118_video_factory.log）の形をそのまま使う:
  Wrote phase2_….webm (…)
  Cloud gallery upload failed (video is still published locally): Gallery upload failed: … Payload Too Large -- <html>
  Published to local dashboard: …

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_upload_status.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import video_progress as vp  # noqa: E402

WROTE = "Wrote phase2_cloudrag_1.webm (41724 frames, 1390.8s)"
PUBLISHED = "Published to local dashboard: C:/x/output/videos/cloudrag_1/"


def log(*lines: str) -> str:
    return "\n".join(lines) + "\n"


class UploadStatusTest(unittest.TestCase):
    def test_pending_until_the_local_publish_line_appears(self) -> None:
        self.assertEqual(vp.upload_status(log(WROTE)), ("pending", ""))
        self.assertEqual(vp.upload_status(""), ("pending", ""))

    def test_failed_with_the_reason_from_the_real_log(self) -> None:
        text = log(
            WROTE,
            "Cloud gallery upload failed (video is still published locally): Gallery upload failed: Error transferring "
            "https://ragreel-gallery.example/api/videos - server replied: Payload Too Large -- <html>",
            PUBLISHED,
        )
        status, reason = vp.upload_status(text)
        self.assertEqual(status, "failed")
        self.assertIn("Payload Too Large", reason)
        self.assertLessEqual(len(reason), 200)

    def test_chunked_failure_reason_is_kept(self) -> None:
        text = log(
            WROTE,
            "Cloud gallery upload failed (video is still published locally): Gallery chunked upload failed at part 3: HTTP 503 x",
            PUBLISHED,
        )
        status, reason = vp.upload_status(text)
        self.assertEqual((status, "part 3" in reason), ("failed", True))

    def test_done(self) -> None:
        self.assertEqual(
            vp.upload_status(
                log(WROTE, "Cloud gallery upload: done (cloudrag_1)", PUBLISHED)
            ),
            ("done", ""),
        )

    def test_none_when_published_without_any_upload_line(self) -> None:
        self.assertEqual(vp.upload_status(log(WROTE, PUBLISHED)), ("none", ""))

    def test_failure_wins_over_an_earlier_done(self) -> None:
        text = log(
            "Cloud gallery upload: done (a)",
            "Cloud gallery upload failed (video is still published locally): boom",
            PUBLISHED,
        )
        self.assertEqual(vp.upload_status(text), ("failed", "boom"))

    def test_a_video_title_that_mentions_upload_does_not_count(self) -> None:
        self.assertEqual(
            vp.upload_status(
                log(WROTE, "slide: Cloud gallery upload is not here", PUBLISHED)
            ),
            ("none", ""),
        )


if __name__ == "__main__":
    unittest.main()
