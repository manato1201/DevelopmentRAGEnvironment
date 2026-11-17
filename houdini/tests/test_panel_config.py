"""rag_chatbot の設定ファイルの読み書き（_load_config / _save_config）の検査。Qt はオフスクリーン。PySide6 が無ければ飛ばす。

2026-11-17 の実証実験: 保存先（local_bridge_dir）が空のまま、「保存先未設定」で、チュートリアルを保存できなかった。
・空・空白・キー欠け・BOM つき・壊れた・空ファイルの、どの設定ファイルでも、パネルは既定の保存先を使う
・設定ファイルを保存するときは、途中で壊れない（0 バイトのファイルを作らない）
・パネルを開いたまま install.cmd を実行しても、インストーラーが入れた保存先を、古い手元の値で消さない

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini.tests.test_panel_config -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

try:
    import rag_chatbot as rc
    HAVE_QT = True
except ImportError:  # PySide6 が無い環境
    rc = None
    HAVE_QT = False

import panel_paths as pp  # noqa: E402


@unittest.skipUnless(HAVE_QT, "PySide6 がありません")
class ConfigFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.path = self.tmp / "home" / ".houdini" / "rag_chatbot_config.json"
        self.default_dir = self.tmp / "Documents" / "RAGReelTutorial"
        for patcher in (
            mock.patch.object(rc, "_CONFIG_PATH", self.path),
            mock.patch.object(pp, "default_data_dir", lambda: self.default_dir),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, raw: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(raw)

    def test_every_kind_of_empty_or_odd_file_still_gets_a_save_folder(self) -> None:
        cases = {
            "no file": None,
            "empty string": b'{"local_bridge_dir": ""}',
            "whitespace": b'{"local_bridge_dir": "   "}',
            "null": b'{"local_bridge_dir": null}',
            "missing key": b'{"mode": "cloudflare"}',
            "bom": b'\xef\xbb\xbf{"mode": "cloudflare"}',
            "broken json": b'{"local_bridge_dir": ',
            "empty file": b"",
            "json null": b"null",
            "json array": b"[]",
        }
        for name, raw in cases.items():
            with self.subTest(name):
                if self.path.exists():
                    self.path.unlink()
                if raw is not None:
                    self.write(raw)
                cfg = rc._load_config()
                self.assertEqual(Path(cfg["local_bridge_dir"]), self.default_dir)
                self.assertTrue(self.default_dir.is_dir())

    def test_a_bom_file_keeps_its_other_values(self) -> None:
        """BOM つきの設定は、以前は丸ごと捨てられていた（URL・キーも空になる）。"""
        self.write(b'\xef\xbb\xbf{"cf_url": "https://w.example", "cf_api_key": "K"}')
        cfg = rc._load_config()
        self.assertEqual(cfg["cf_url"], "https://w.example")
        self.assertEqual(cfg["cf_api_key"], "K")

    def test_a_configured_folder_is_kept_as_is(self) -> None:
        self.write(json.dumps({"local_bridge_dir": "D:/my/folder"}).encode("utf-8"))
        self.assertEqual(rc._load_config()["local_bridge_dir"], "D:/my/folder")

    def test_local_mode_does_not_get_the_default(self) -> None:
        self.write(json.dumps({"mode": "local", "local_bridge_dir": ""}).encode("utf-8"))
        self.assertEqual(rc._load_config()["local_bridge_dir"], "")

    def test_save_is_atomic_and_writes_valid_json_without_bom(self) -> None:
        rc._save_config({"mode": "cloudflare", "cf_url": "https://w.example", "local_bridge_dir": "D:/d"})
        raw = self.path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(json.loads(raw)["cf_url"], "https://w.example")
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name], "一時ファイルが残らない")

    def test_a_failed_save_does_not_destroy_the_existing_file(self) -> None:
        self.write(json.dumps({"cf_url": "https://keep.example"}).encode("utf-8"))
        with self.assertRaises(TypeError):
            rc._save_config({"mode": "cloudflare", "bad": object()})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["cf_url"], "https://keep.example")

    def test_a_stale_panel_does_not_erase_the_installers_save_folder(self) -> None:
        """パネルを開いたまま install.cmd を実行 → パネルで保存、の流れで、保存先が空に戻っていた。"""
        stale = {"mode": "cloudflare", "local_bridge_dir": ""}  # install 前に読んだ手元の設定
        self.write(json.dumps({"mode": "cloudflare", "local_bridge_dir": "D:/Installed"}).encode("utf-8"))
        rc._save_config(stale)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["local_bridge_dir"], "D:/Installed")
        self.assertEqual(stale["local_bridge_dir"], "D:/Installed", "手元の設定にも反映する")

    def test_clearing_the_folder_on_purpose_is_saved_as_empty(self) -> None:
        """画面で、保存先を空にして保存したとき（=自動に戻す）は、ファイルにある古い値で上書きしない。"""
        self.write(json.dumps({"mode": "cloudflare", "local_bridge_dir": "D:/Old"}).encode("utf-8"))
        cfg = {"mode": "cloudflare", "local_bridge_dir": ""}
        rc._save_config(cfg, dir_edited=True)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["local_bridge_dir"], "")
        self.assertEqual(cfg["local_bridge_dir"], "")

    def test_a_broken_file_is_kept_as_a_copy_before_it_is_replaced(self) -> None:
        """壊れた設定ファイルを、保存で上書きするとき、手で直せるように、元の中身を残す。"""
        self.write(b'{"cf_api_key": "K", ')
        rc._save_config({"mode": "cloudflare", "local_bridge_dir": "D:/d"})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["mode"], "cloudflare")
        self.assertEqual((self.path.parent / (self.path.name + ".broken")).read_bytes(), b'{"cf_api_key": "K", ')

    def test_a_folder_typed_by_the_user_is_saved(self) -> None:
        self.write(json.dumps({"local_bridge_dir": "D:/Installed"}).encode("utf-8"))
        rc._save_config({"mode": "cloudflare", "local_bridge_dir": "E:/Mine"})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["local_bridge_dir"], "E:/Mine")


if __name__ == "__main__":
    unittest.main()
