"""開発機用の deploy_panels.py（リポジトリを直接読むパッケージの登録）のテスト（2026-11-26）。

以前は Documents/houdini<版>/python_panels へコピーしていて、コピーし忘れると古いまま動いた。
今はパッケージがリポジトリを指すので、コピーは要らない。Houdini は要らない（フォルダを一時の場所に向ける）。
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HOUDINI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOUDINI))

import deploy_panels as dp  # noqa: E402


class DevPackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.docs = Path(self._tmp.name) / "Documents"
        self.docs.mkdir()

    def run_main(self, *args: str) -> str:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(dp.main([*args, "--documents", str(self.docs)]), 0)
        return out.getvalue()

    def test_package_points_at_the_repository(self) -> None:
        data = dp.package_json()
        env = {k: v for item in data["env"] for k, v in item.items()}
        root = Path(env[dp.DEV_ENV])
        self.assertTrue((root / "houdini" / "python_panels" / "rag_chatbot.py").exists())
        self.assertEqual(env["PYTHONPATH"], {"method": "append", "value": "$RAGREEL_TUTORIAL_DEV/houdini/python_panels"})
        # path の下に、パネル定義とシェルフが、Houdini の読む形（python_panels/・toolbar/）である
        path = Path(data["path"].replace("$RAGREEL_TUTORIAL_DEV", str(root)))
        self.assertTrue((path / "python_panels" / "RAGReelTutorial.pypanel").exists())
        self.assertTrue((path / "toolbar" / "ragreel_tutorial.shelf").exists())

    def test_register_creates_the_missing_version_folder(self) -> None:
        out = self.run_main("22.0")
        pkg = self.docs / "houdini22.0" / "packages" / "ragreel_tutorial.json"
        self.assertTrue(pkg.exists())
        self.assertEqual(json.loads(pkg.read_text(encoding="utf-8")), dp.package_json())
        self.assertIn("作りました", out)
        self.assertIn("再起動", out)

    def test_old_copies_are_moved_aside_but_other_files_are_kept(self) -> None:
        house = self.docs / "houdini22.0"
        panels = house / "python_panels"
        (panels / "__pycache__").mkdir(parents=True)
        for name in ("rag_chatbot.py", "guide_view.py", "graph_view.py", "my_own_tool.py"):
            (panels / name).write_text("# old", encoding="utf-8")
        (panels / "default.pypanel").write_text('<pythonPanelDocument><interface name="RAGChatBot"/></pythonPanelDocument>', encoding="utf-8")
        (house / "toolbar").mkdir()
        (house / "toolbar" / "ragreel_tutorial.shelf").write_text("<shelfDocument/>", encoding="utf-8")
        (house / "toolbar" / "default.shelf").write_text("<shelfDocument/>", encoding="utf-8")

        self.run_main("22.0")

        remaining = sorted(p.name for p in panels.iterdir())
        self.assertEqual(remaining, ["my_own_tool.py"], "自分で置いたファイルは触らない")
        self.assertTrue((house / "toolbar" / "default.shelf").exists())
        self.assertFalse((house / "toolbar" / "ragreel_tutorial.shelf").exists(), "シェルフはパッケージから読むので、コピーは二重になる")
        backups = list(house.glob("python_panels_backup_*"))
        self.assertEqual(len(backups), 1)
        moved = {p.name for p in backups[0].iterdir()}
        self.assertTrue({"rag_chatbot.py", "guide_view.py", "graph_view.py", "default.pypanel", "__pycache__",
                         "toolbar_ragreel_tutorial.shelf"} <= moved)

    def test_a_pypanel_with_other_panels_is_not_moved(self) -> None:
        panels = self.docs / "houdini22.0" / "python_panels"
        panels.mkdir(parents=True)
        (panels / "default.pypanel").write_text(
            '<pythonPanelDocument><interface name="RAGChatBot"/><interface name="Mine"/></pythonPanelDocument>', encoding="utf-8")
        self.run_main("22.0")
        self.assertTrue((panels / "default.pypanel").exists())

    def test_check_writes_nothing(self) -> None:
        (self.docs / "houdini22.0" / "python_panels").mkdir(parents=True)
        (self.docs / "houdini22.0" / "python_panels" / "rag_chatbot.py").write_text("# old", encoding="utf-8")
        out = self.run_main("22.0", "21.0", "--check")
        self.assertIn("houdini22.0: 未登録", out)
        self.assertIn("以前のコピーが 1 件", out)
        self.assertIn("houdini21.0: フォルダなし", out)
        self.assertFalse((self.docs / "houdini22.0" / "packages").exists())
        self.assertFalse((self.docs / "houdini21.0").exists())

    def test_remove_only_removes_the_development_registration(self) -> None:
        installed = self.docs / "houdini21.0" / "packages" / "ragreel_tutorial.json"
        installed.parent.mkdir(parents=True)
        installed.write_text(json.dumps({"enable": True, "env": [{"RAGREEL_TUTORIAL_HOME": "C:/x"}], "path": "$RAGREEL_TUTORIAL_HOME/houdini"}),
                             encoding="utf-8")
        self.run_main("22.0")
        out = self.run_main("22.0", "21.0", "--remove")
        self.assertFalse((self.docs / "houdini22.0" / "packages" / "ragreel_tutorial.json").exists())
        self.assertTrue(installed.exists(), "配布版の登録は外さない")
        self.assertIn("配布版", out)

    def test_registering_over_the_installed_package_says_so(self) -> None:
        pkg = self.docs / "houdini22.0" / "packages" / "ragreel_tutorial.json"
        pkg.parent.mkdir(parents=True)
        pkg.write_text(json.dumps({"enable": True, "env": [{"RAGREEL_TUTORIAL_HOME": "C:/x"}]}), encoding="utf-8")
        out = self.run_main("22.0")
        self.assertIn("配布版の登録を、開発用に置き換えます", out)
        self.assertTrue(dp.describe_package(pkg).startswith("開発用"))

    def test_the_old_pypanel_option_is_accepted(self) -> None:
        out = self.run_main("houdini22.0", "--pypanel")
        self.assertTrue((self.docs / "houdini22.0" / "packages" / "ragreel_tutorial.json").exists())
        self.assertIn("--pypanel は不要", out)


if __name__ == "__main__":
    unittest.main()
