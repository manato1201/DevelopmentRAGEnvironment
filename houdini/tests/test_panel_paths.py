"""panel_paths（生成物の保存先の決め方）の検査。標準の unittest。Qt・Houdini は要らない。

2026-11-17 の実証実験で、保存先（local_bridge_dir）が未設定のまま、チュートリアルを保存できなかった件の再発防止。

実行（リポジトリのルートで）:  uv run python -m unittest houdini.tests.test_panel_paths -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import panel_paths as pp  # noqa: E402


class IsBlankTest(unittest.TestCase):
    def test_blank_values(self) -> None:
        for value in ("", "   ", "\t\n", None, 0, [], {}):
            self.assertTrue(pp.is_blank(value), repr(value))

    def test_real_values(self) -> None:
        for value in ("C:/x", " D:/y ", "relative/dir"):
            self.assertFalse(pp.is_blank(value), repr(value))


class ResolveTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_unset_uses_and_creates_the_default_folder(self) -> None:
        """未設定でも、利用者を困らせず、既定の場所を自動で使う（実験で起きた不具合の再現）。"""
        target = self.tmp / "Documents" / "RAGReelTutorial"
        for blank in ("", "   ", None):
            cfg = {"mode": "cloudflare", "local_bridge_dir": blank}
            result = pp.resolve_data_dir(cfg, target)
            self.assertEqual(result["source"], "default", repr(blank))
            self.assertEqual(Path(result["path"]), target)
            self.assertTrue(target.is_dir())

    def test_missing_key_is_unset(self) -> None:
        result = pp.resolve_data_dir({"mode": "cloudflare"}, self.tmp / "d")
        self.assertEqual(result["source"], "default")

    def test_apply_writes_the_default_into_the_config(self) -> None:
        cfg = {"mode": "cloudflare", "local_bridge_dir": ""}
        pp.apply_default_data_dir(cfg, self.tmp / "d")
        self.assertEqual(Path(cfg["local_bridge_dir"]), self.tmp / "d")

    def test_a_configured_value_is_kept_and_not_created(self) -> None:
        elsewhere = self.tmp / "other" / "pc" / "folder"
        cfg = {"mode": "cloudflare", "local_bridge_dir": str(elsewhere)}
        result = pp.apply_default_data_dir(cfg, self.tmp / "d")
        self.assertEqual(result["source"], "config")
        self.assertEqual(cfg["local_bridge_dir"], str(elsewhere))
        self.assertFalse(elsewhere.exists(), "設定済みの場所は、勝手に作らない")
        self.assertFalse((self.tmp / "d").exists())

    def test_local_mode_never_uses_the_default(self) -> None:
        """Local モードの local_bridge_dir は、ブリッジのあるプロジェクトの場所。既定の保存先に置き換えない。"""
        cfg = {"mode": "local", "local_bridge_dir": ""}
        result = pp.apply_default_data_dir(cfg, self.tmp / "d")
        self.assertEqual(result["source"], "none")
        self.assertEqual(cfg["local_bridge_dir"], "")
        self.assertFalse((self.tmp / "d").exists())

    def test_unwritable_default_reports_an_error_without_raising(self) -> None:
        blocker = self.tmp / "file_not_folder"
        blocker.write_text("x", encoding="utf-8")
        cfg = {"mode": "cloudflare", "local_bridge_dir": ""}
        result = pp.apply_default_data_dir(cfg, blocker / "RAGReelTutorial")
        self.assertEqual(result["source"], "none")
        self.assertTrue(result["error"])
        self.assertEqual(cfg["local_bridge_dir"], "")

    def test_whitespace_only_is_normalised_to_empty_when_no_default_is_possible(self) -> None:
        blocker = self.tmp / "f"
        blocker.write_text("x", encoding="utf-8")
        cfg = {"mode": "cloudflare", "local_bridge_dir": "   "}
        pp.apply_default_data_dir(cfg, blocker / "x")
        self.assertEqual(cfg["local_bridge_dir"], "")

    def test_default_folder_is_documents_ragreeltutorial(self) -> None:
        self.assertEqual(pp.default_data_dir().name, "RAGReelTutorial")
        self.assertEqual(pp.default_data_dir().parent, pp.documents_dir())


class ChooseToSaveTest(unittest.TestCase):
    AUTO = Path("C:/Users/x/Documents/RAGReelTutorial")

    def test_a_stale_empty_value_does_not_erase_the_installers_value(self) -> None:
        self.assertEqual(pp.choose_to_save("", "D:/Data", self.AUTO), "D:/Data")

    def test_a_stale_auto_default_does_not_erase_the_installers_value(self) -> None:
        self.assertEqual(pp.choose_to_save(str(self.AUTO), "D:/Data", self.AUTO), "D:/Data")

    def test_a_value_typed_by_the_user_wins(self) -> None:
        self.assertEqual(pp.choose_to_save("E:/Mine", "D:/Data", self.AUTO), "E:/Mine")

    def test_nothing_on_disk_keeps_the_memory_value(self) -> None:
        self.assertEqual(pp.choose_to_save("E:/Mine", "", self.AUTO), "E:/Mine")
        self.assertEqual(pp.choose_to_save("", None, self.AUTO), "")


if __name__ == "__main__":
    unittest.main()
