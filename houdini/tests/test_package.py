"""配布用の zip の作成と、install.ps1（導入・更新・削除）のテスト。Houdini は要らない（フォルダを一時の場所に向ける）。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_houdini_package as bhp  # noqa: E402

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


class BuildTest(unittest.TestCase):
    def test_zip_contains_every_panel_module_and_the_installer(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            target = bhp.build("9.9.9", Path(t))
            with zipfile.ZipFile(target) as z:
                names = set(z.namelist())
                for module in ("rag_chatbot", "tutorial_view", "tutorial_agent", "houdini_tools", "video_script",
                               "lesson_design", "tutorial_review", "graph_diagram", "video_progress", "screen_capture"):
                    self.assertIn(f"python/{module}.py", names)
                for name in ("install.ps1", "install.cmd", "VERSION", "houdini/python_panels/RAGReelTutorial.pypanel"):
                    self.assertIn(name, names)
                self.assertEqual(z.read("VERSION").decode().strip(), "9.9.9")
                # PowerShell 5.1 reads a Japanese script correctly only with a BOM
                self.assertTrue(z.read("install.ps1").startswith(b"\xef\xbb\xbf"))

    def test_every_module_in_the_deploy_script_is_packaged(self) -> None:
        """deploy_panels.py（開発者用）の MODULES と、配布 zip の中身がずれていないこと（登録漏れの再発防止）。"""
        sys.path.insert(0, str(ROOT / "houdini"))
        import deploy_panels

        packaged = {p.stem for p, a in bhp.collect_files() if a.startswith("python/")}
        self.assertEqual(set(deploy_panels.MODULES) - packaged, set())

    def test_pypanel_is_valid_xml_and_a_thin_loader(self) -> None:
        tree = ET.parse(PACKAGE_PYPANEL := ROOT / "houdini" / "package" / "RAGReelTutorial.pypanel")
        self.assertTrue(PACKAGE_PYPANEL.exists())
        interface = tree.getroot().find("interface")
        assert interface is not None
        self.assertEqual(interface.get("name"), "RAGReelTutorial")
        script = interface.findtext("script") or ""
        self.assertIn("import rag_chatbot", script)
        self.assertIn("def onCreateInterface", script)
        compile(script, "pypanel", "exec")  # 構文が正しい
        # Latin-1 の落とし穴（日本語を直接書くとHoudini 22で読めない）を避けるため、ASCII だけ
        script.encode("ascii")


@unittest.skipUnless(POWERSHELL, "PowerShell がありません")
class InstallScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bhp.build("1.2.3", self.tmp / "dist")
        self.pkg = self.tmp / "pkg"
        with zipfile.ZipFile(self.tmp / "dist" / "RAGReelTutorial-1.2.3.zip") as z:
            z.extractall(self.pkg)
        self.docs = self.tmp / "Documents"
        (self.docs / "houdini21.0").mkdir(parents=True)
        (self.docs / "houdini22.0").mkdir(parents=True)
        (self.docs / "houdini-notes").mkdir()  # 無関係のフォルダ
        self.install = self.tmp / "RAGReelTutorial"
        self.data = self.tmp / "MyData"
        self.config = self.tmp / "home" / ".houdini" / "rag_chatbot_config.json"

    def run_ps(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.pkg / "install.ps1"),
             "-DocumentsDir", str(self.docs), "-InstallDir", str(self.install), "-ConfigPath", str(self.config),
             "-DataDir", str(self.data),
             "-NoPrompt", *extra],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )

    def test_install_writes_package_files_and_config(self) -> None:
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"mode": "local", "local_port": 9999, "cf_url": "https://old.example"}), encoding="utf-8")
        r = self.run_ps("-CloudflareUrl", "https://new.example.workers.dev/", "-ApiKey", "KEY123", "-VideoExe", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        # files
        for name in ("rag_chatbot.py", "tutorial_view.py", "video_progress.py"):
            self.assertTrue((self.install / "python" / name).exists(), name)
        self.assertTrue((self.install / "houdini" / "python_panels" / "RAGReelTutorial.pypanel").exists())
        self.assertEqual((self.install / "VERSION").read_text().strip(), "1.2.3")

        # one package file per Houdini folder, none for unrelated folders
        for version in ("houdini21.0", "houdini22.0"):
            pkg = json.loads((self.docs / version / "packages" / "ragreel_tutorial.json").read_text(encoding="utf-8"))
            self.assertTrue(pkg["enable"])
            self.assertEqual(pkg["env"][0]["RAGREEL_TUTORIAL_HOME"], str(self.install).replace("\\", "/"))
            self.assertEqual(pkg["env"][1]["PYTHONPATH"], {"method": "append", "value": "$RAGREEL_TUTORIAL_HOME/python"})
            self.assertEqual(pkg["path"], "$RAGREEL_TUTORIAL_HOME/houdini")
        self.assertFalse((self.docs / "houdini-notes" / "packages").exists())

        # config merged, not replaced; written without a BOM (Python's json cannot read a BOM)
        raw = self.config.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        cfg = json.loads(raw.decode("utf-8"))
        self.assertEqual(cfg["local_port"], 9999, "existing settings are kept")
        self.assertEqual(cfg["cf_url"], "https://new.example.workers.dev", "trailing slash removed")
        self.assertEqual(cfg["cf_api_key"], "KEY123")
        self.assertEqual(cfg["tutorial_rag_mode"], "cloudflare")
        self.assertEqual(cfg["tutorial_claude_backend"], "cloudflare")
        # without a save folder the panel cannot save anything, so the installer sets one (and creates it)
        self.assertEqual(cfg["local_bridge_dir"], str(self.data))
        self.assertTrue(self.data.is_dir())
        # the previous config was backed up
        self.assertEqual(len(list(self.config.parent.glob("rag_chatbot_config.json.backup_*"))), 1)
        # the key is never echoed
        self.assertNotIn("KEY123", r.stdout)

    def test_an_existing_save_folder_is_kept(self) -> None:
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"local_bridge_dir": "D:/my/folder"}), encoding="utf-8")
        self.assertEqual(self.run_ps().returncode, 0)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["local_bridge_dir"], "D:/my/folder")
        self.assertFalse(self.data.exists())

    def test_reinstall_is_idempotent_and_updates_files(self) -> None:
        self.assertEqual(self.run_ps().returncode, 0)
        (self.install / "python" / "rag_chatbot.py").write_text("# stale", encoding="utf-8")
        r = self.run_ps()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual((self.install / "python" / "rag_chatbot.py").read_text(encoding="utf-8"), "# stale")
        pkgs = list((self.docs / "houdini22.0" / "packages").glob("*.json"))
        self.assertEqual(len(pkgs), 1)

    def test_version_option_limits_the_target(self) -> None:
        r = self.run_ps("-HoudiniVersion", "22.0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.docs / "houdini22.0" / "packages" / "ragreel_tutorial.json").exists())
        self.assertFalse((self.docs / "houdini21.0" / "packages").exists())

    def test_no_houdini_folder_fails_with_a_clear_message(self) -> None:
        shutil.rmtree(self.docs / "houdini21.0")
        shutil.rmtree(self.docs / "houdini22.0")
        r = self.run_ps()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Houdini", r.stdout + r.stderr)

    def test_video_exe_is_detected_from_the_option_and_written(self) -> None:
        exe = self.tmp / "RAGReel" / "video_factory_cloudrag_poc.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"MZ")
        r = self.run_ps("-VideoExe", str(exe))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cfg = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertTrue(cfg["video_factory_exe_path"].endswith("video_factory_cloudrag_poc.exe"))

    def test_uninstall_removes_packages_and_folder_but_keeps_the_config(self) -> None:
        self.assertEqual(self.run_ps("-CloudflareUrl", "https://x.example", "-ApiKey", "K").returncode, 0)
        r = self.run_ps("-Uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.install.exists())
        for version in ("houdini21.0", "houdini22.0"):
            self.assertFalse((self.docs / version / "packages" / "ragreel_tutorial.json").exists())
        self.assertTrue(self.config.exists())


if __name__ == "__main__":
    unittest.main()
