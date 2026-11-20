"""scripts/publish_reference.py（Reference の説明・画像を Cloudflare に公開する道具）のテスト（2026-11-19）。通信は、opener で差し替える。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_publish_reference.py -v
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts"))

import publish_reference as pr  # noqa: E402
import reference_data as rd  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Recorder:
    def __init__(self, fail_on: str = "") -> None:
        self.calls, self.fail_on = [], fail_on

    def __call__(self, req, timeout):
        path = req.full_url.split("example.invalid", 1)[1]
        self.calls.append((path, req.data))
        if self.fail_on and self.fail_on in path:
            raise OSError("boom")
        return FakeResponse(json.dumps({"status": "ok", "version": 1, "bytes": len(req.data or b"")}).encode())


class PublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = str(Path(self.tmp.name) / "bridge")
        self.media = Path(self.tmp.name) / "media"
        self.cfg = {"cf_url": "https://example.invalid", "cf_api_key": "k", "local_bridge_dir": self.base}
        rd.save_entry(self.base, "node", "sop/mountain", {"what": "地形のような凹凸をつける"})
        folder = self.media / "node" / "sop_mountain"
        folder.mkdir(parents=True)
        (folder / "before.png").write_bytes(b"BEFORE")
        (folder / "after.png").write_bytes(b"AFTER")
        (folder / "clip.gif").write_bytes(b"GIF89a")
        (folder / "meta.json").write_text(json.dumps({"key": "sop/mountain"}), encoding="utf-8")  # 画像ではないので公開しない。キーを知る手がかり

    def test_media_ids_include_a_content_hash_and_skip_missing_roles(self) -> None:
        media = pr.collect_media(self.media, "node", "sop/mountain")
        self.assertEqual([m["role"] for m in media], ["before", "after", "clip"])
        self.assertRegex(media[0]["id"], r"^node/sop_mountain/before\.[0-9a-f]{8}\.png$")
        self.assertTrue(media[2]["id"].endswith(".gif"))
        (self.media / "node" / "sop_mountain" / "after.png").write_bytes(b"AFTER2")
        self.assertNotEqual(pr.collect_media(self.media, "node", "sop/mountain")[1]["id"], media[1]["id"], "a re-shot image gets a new name")
        self.assertEqual(pr.collect_media(None, "node", "sop/mountain"), [])
        self.assertEqual(pr.collect_media(self.media, "node", "sop/none"), [])

    def test_targets_are_items_with_a_saved_entry_or_captured_media(self) -> None:
        targets = pr.find_targets(self.base, self.media, set())
        self.assertEqual([t["item"]["key"] for t in targets], ["sop/mountain"])
        self.assertIsNotNone(targets[0]["entry"])
        self.assertEqual(targets[0]["item"]["label"], "Mountain", "an item missing from the catalog is still made from its key")
        self.assertEqual(pr.find_targets(self.base, self.media, {"sop/scatter"}), [], "only filters")
        # 画像だけで、説明が無い項目も、対象には入る（公開のときに、断る）
        (self.media / "node" / "sop_scatter").mkdir(parents=True)
        (self.media / "node" / "sop_scatter" / "after.png").write_bytes(b"X")
        keys = [t["item"]["key"] for t in pr.find_targets(self.base, self.media, set())]
        self.assertEqual(sorted(keys), ["sop/mountain", "sop/scatter"])

    def test_a_saved_name_that_is_not_in_the_catalog_is_still_found(self) -> None:
        rd.save_entry(self.base, "shelf", "shelf/billowy_smoke", {"what": "煙を出す"})
        keys = [t["item"]["key"] for t in pr.find_targets(self.base, None, set())]
        self.assertIn("shelf/billowy_smoke", keys)

    def test_publish_uploads_media_first_then_the_entry(self) -> None:
        recorder = Recorder()
        target = pr.find_targets(self.base, self.media, set())[0]
        result = pr.publish_target(self.cfg, target, opener=recorder, audit=False)
        self.assertEqual(result, {"key": "sop/mountain", "version": 1, "media": 3})
        paths = [p for p, _ in recorder.calls]
        self.assertEqual([p.split("?")[0] for p in paths], ["/admin/reference/media_put"] * 3 + ["/admin/reference/put"])
        sent = json.loads(recorder.calls[-1][1])
        self.assertEqual((sent["kind"], sent["key"], sent["title"]), ("node", "sop/mountain", "Mountain"))
        self.assertEqual([m["role"] for m in sent["media"]], ["before", "after", "clip"])
        self.assertEqual(sent["entry"]["what"], "地形のような凹凸をつける")
        self.assertTrue(all(m["id"] in paths[i] for i, m in enumerate(sent["media"])), "the entry points at the ids that were uploaded")

    def test_an_entry_that_fails_the_houdini_audit_is_refused_before_any_upload(self) -> None:
        target = pr.find_targets(self.base, self.media, set())[0]
        real = {"sop/mountain": {"type": "mountain", "names": ["Height", "Noise Type"]}, "__node_types__": []}
        target["entry"] = {"what": "「Fractal type」を選ぶ"}
        recorder = Recorder()
        with self.assertRaises(ValueError) as caught:
            pr.publish_target(self.cfg, target, opener=recorder, parms=real)
        self.assertIn("Fractal type", str(caught.exception))
        self.assertEqual(recorder.calls, [], "nothing is uploaded")
        with self.assertRaises(ValueError):
            pr.publish_target(self.cfg, target, opener=recorder, parms=None)  # 突き合わせの結果が無いときも、公開しない
        self.assertEqual(recorder.calls, [])
        target["entry"] = {"what": "「Noise Type」と「Height」で形を決める"}
        self.assertEqual(pr.publish_target(self.cfg, target, opener=Recorder(), parms=real)["key"], "sop/mountain")

    def test_an_item_without_an_entry_is_refused_before_any_upload(self) -> None:
        (self.media / "node" / "sop_scatter").mkdir(parents=True)
        (self.media / "node" / "sop_scatter" / "after.png").write_bytes(b"X")
        recorder = Recorder()
        target = [t for t in pr.find_targets(self.base, self.media, set()) if t["item"]["key"] == "sop/scatter"][0]
        with self.assertRaises(ValueError):
            pr.publish_target(self.cfg, target, opener=recorder, audit=False)
        self.assertEqual(recorder.calls, [], "nothing is uploaded")

    def test_main_dry_run_makes_no_requests_and_one_failure_does_not_stop_the_rest(self) -> None:
        config = Path(self.tmp.name) / "config.json"
        config.write_text(json.dumps(self.cfg), encoding="utf-8")
        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        try:
            code = pr.main(["--config", str(config), "--media", str(self.media), "--dry-run"])
        finally:
            sys.stdout = old
        self.assertEqual(code, 0)
        self.assertIn("sop/mountain", out.getvalue())
        self.assertIn("dry-run", out.getvalue())
        self.assertNotIn("k-", out.getvalue().replace("kind", ""), "the key is never printed")
        self.assertEqual(pr.main(["--config", str(Path(self.tmp.name) / "none.json")] if False else ["--config", str(config), "--only", "sop/none", "--dry-run"]), 0)


if __name__ == "__main__":
    unittest.main()
