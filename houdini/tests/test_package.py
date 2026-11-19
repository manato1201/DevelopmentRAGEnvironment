"""配布用の zip の作成と、install.ps1（導入・更新・削除）のテスト。Houdini は要らない（フォルダを一時の場所に向ける）。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_houdini_package as bhp  # noqa: E402

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def _decode(data: bytes) -> str:
    """コンソールの出力を読む。Windows の OEM のコードページ（日本語環境は cp932）。読めなければ UTF-8。"""
    try:
        import ctypes

        codepage = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        return data.decode(codepage, errors="replace")
    except Exception:  # noqa: BLE001 -- Windows 以外・取れないとき
        return data.decode("utf-8", errors="replace")


class BuildTest(unittest.TestCase):
    def test_zip_contains_every_panel_module_and_the_installer(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            target = bhp.build("9.9.9", Path(t))
            with zipfile.ZipFile(target) as z:
                names = set(z.namelist())
                for module in ("rag_chatbot", "tutorial_view", "tutorial_agent", "houdini_tools", "video_script",
                               "lesson_design", "tutorial_review", "graph_diagram", "video_progress", "screen_capture", "doc_tools", "display_isolation", "tutorial_followup", "guide_view", "guide_mode", "guide_shortcuts", "trial_pruning",
                               "panel_paths", "panel_nav", "node_links", "node_link_data"):
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

    def test_pypanel_is_listed_in_both_menus(self) -> None:
        """実証実験で「Misc に見つからない」「Python Panel メニューに無い」と言われた。ペインのタブのメニューと、Windows メニューの両方に出す。"""
        interface = ET.parse(ROOT / "houdini" / "package" / "RAGReelTutorial.pypanel").getroot().find("interface")
        assert interface is not None
        self.assertIsNotNone(interface.find("includeInPaneTabMenu"), "New Pane Tab Type のメニュー用")
        self.assertIsNotNone(interface.find("includeInToolbarMenu"), "Windows > Python Panel のメニュー用")

    def _load_loader(self):
        interface = ET.parse(ROOT / "houdini" / "package" / "RAGReelTutorial.pypanel").getroot().find("interface")
        assert interface is not None
        namespace: dict = {}
        exec(compile(interface.findtext("script") or "", "pypanel", "exec"), namespace)  # noqa: S102 -- 配布する定義そのもの
        return namespace["onCreateInterface"]

    def test_loader_passes_the_panel_through_when_the_import_works(self) -> None:
        fake = types.ModuleType("rag_chatbot")
        fake.onCreateInterface = lambda: "PANEL"  # type: ignore[attr-defined]
        with mock.patch.dict(sys.modules, {"rag_chatbot": fake}):
            self.assertEqual(self._load_loader()(), "PANEL")

    def test_loader_shows_the_reason_when_the_import_fails(self) -> None:
        """import rag_chatbot が失敗したとき、素のトレースバックだけでなく、原因の手がかり（環境変数・探した場所）を出す。"""
        try:
            from PySide6 import QtWidgets
        except ImportError:
            self.skipTest("PySide6 がありません")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with mock.patch.dict(sys.modules, {"rag_chatbot": None}), mock.patch.dict(os.environ, {"RAGREEL_TUTORIAL_HOME": "C:/nowhere"}):
            widget = self._load_loader()()
        text = widget.toPlainText()
        self.assertIn("RAGREEL_TUTORIAL_HOME = C:/nowhere", text)
        self.assertIn("rag_chatbot.py exists = False", text)
        self.assertIn("rag_chatbot", text)


# install.ps1 / install.cmd は、Windows の Houdini 用の導入スクリプト(%USERPROFILE% の Documents\houdini<版> や cmd /c を使う)。
# Linux の CI にも pwsh は入っているが、Windows 以外では前提(パス・cmd)が成り立たず 31 件が落ちるので、Windows だけで動かす。
@unittest.skipUnless(POWERSHELL and sys.platform == "win32", "Windows の PowerShell がありません")
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

    def run_ps(self, *extra: str, data: Path | None = None, houdini_root: Path | None = None) -> subprocess.CompletedProcess:
        """install.ps1 を、一時フォルダだけを向けて動かす。本物の Documents・設定ファイル・Houdini の入っている場所は、見ない。

        PowerShell の出力は、Windows の OEM のコードページ（日本語環境では cp932）なので、その文字コードで読む。"""
        raw = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.pkg / "install.ps1"),
             "-DocumentsDir", str(self.docs), "-InstallDir", str(self.install), "-ConfigPath", str(self.config),
             "-DataDir", str(data or self.data), "-HoudiniInstallRoot", str(houdini_root or (self.tmp / "NoHoudiniHere")),
             "-NoPrompt", *extra],
            capture_output=True, timeout=120,
        )
        return subprocess.CompletedProcess(raw.args, raw.returncode, _decode(raw.stdout), _decode(raw.stderr))

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
        self.assertEqual(cfg["mode"], "cloudflare")
        # without a save folder the panel cannot save anything, so the installer sets one (and creates it)
        self.assertEqual(cfg["local_bridge_dir"], str(self.data))
        self.assertTrue(self.data.is_dir())
        # the previous config was backed up
        self.assertEqual(len(list(self.config.parent.glob("rag_chatbot_config.json.backup_*"))), 1)
        # the key is never echoed
        self.assertNotIn("KEY123", r.stdout)

    def test_an_existing_save_folder_is_kept(self) -> None:
        mine = self.tmp / "MyOwnFolder"
        mine.mkdir()
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"local_bridge_dir": str(mine)}), encoding="utf-8")
        self.assertEqual(self.run_ps().returncode, 0)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["local_bridge_dir"], str(mine))
        self.assertFalse(self.data.exists())

    def test_a_folder_whose_parent_exists_is_kept_even_if_not_created_yet(self) -> None:
        mine = self.tmp / "NotYet"  # 1 つ上（tmp）はある。保存のときに、パネルが作る
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({"local_bridge_dir": str(mine)}), encoding="utf-8")
        self.assertEqual(self.run_ps().returncode, 0)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["local_bridge_dir"], str(mine))

    def test_reinstall_is_idempotent_and_updates_files(self) -> None:
        self.assertEqual(self.run_ps().returncode, 0)
        (self.install / "python" / "rag_chatbot.py").write_text("# stale", encoding="utf-8")
        r = self.run_ps()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual((self.install / "python" / "rag_chatbot.py").read_text(encoding="utf-8"), "# stale")
        pkgs = list((self.docs / "houdini22.0" / "packages").glob("*.json"))
        self.assertEqual(len(pkgs), 1)

    def test_reinstall_with_the_same_config_does_not_pile_up_backups(self) -> None:
        # 設定が変わらないのに、実行のたびに、API キーの入った控えが増えてはいけない
        self.assertEqual(self.run_ps("-CloudflareUrl", "https://a.example", "-ApiKey", "KEY1").returncode, 0)
        before = self.config.read_bytes()
        for _ in range(3):
            self.assertEqual(self.run_ps().returncode, 0)
        self.assertEqual(self.config.read_bytes(), before)
        backups = list(self.config.parent.glob("rag_chatbot_config.json.backup_*"))
        self.assertEqual(len(backups), 0, "変わっていない設定の控えは作らない（初回は、元のファイルが無かったので 0）")

    def test_backups_are_pruned_to_the_latest_few(self) -> None:
        self.config.parent.mkdir(parents=True)
        for i in range(6):
            (self.config.parent / f"rag_chatbot_config.json.backup_2026010{i}_000000").write_text("{}", encoding="utf-8")
        self.config.write_text(json.dumps({"cf_url": "https://changed.example"}), encoding="utf-8")
        self.assertEqual(self.run_ps().returncode, 0)
        backups = sorted(p.name for p in self.config.parent.glob("rag_chatbot_config.json.backup_*"))
        self.assertEqual(len(backups), 3, backups)
        self.assertNotIn("rag_chatbot_config.json.backup_20260100_000000", backups)

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

    # ── 実証実験（2026-11-17）で見つかった不具合の再現と、導入の見直し ─────────────────

    def _config_after(self, raw: bytes) -> tuple[subprocess.CompletedProcess, dict]:
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(raw)
        r = self.run_ps()
        data = self.config.read_bytes()
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"), "BOM なしで書く（Python の json が読めない）")
        return r, json.loads(data.decode("utf-8"))

    def test_every_odd_config_still_ends_with_a_save_folder(self) -> None:
        """保存先が「空・空白だけ・null・欠け」でも、BOM つき・空ファイル・壊れた JSON・{ } でない JSON でも、導入は止まらず、保存先が入る。

        変更前は、空白だけの値がそのまま残り、空のファイル・null・配列の設定ファイルでは、導入が失敗して設定が空のままだった。"""
        cases = {
            "empty string": b'{"local_bridge_dir": ""}',
            "whitespace": b'{"local_bridge_dir": "   "}',
            "null": b'{"local_bridge_dir": null}',
            "missing key": b'{"mode": "cloudflare"}',
            "bom": b'\xef\xbb\xbf{"local_bridge_dir": ""}',
            "broken json": b'{"local_bridge_dir": ',
            "empty file": b"",
            "json null": b"null",
            "json array": b"[]",
        }
        for name, raw in cases.items():
            with self.subTest(name):
                r, cfg = self._config_after(raw)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(cfg["local_bridge_dir"], str(self.data))
                self.assertEqual(cfg["mode"], "cloudflare")
                self.assertTrue(self.data.is_dir())
                shutil.rmtree(self.data, ignore_errors=True)

    def test_a_bom_config_keeps_its_other_values(self) -> None:
        r, cfg = self._config_after(b'\xef\xbb\xbf{"local_port": 9999, "cf_url": "https://old.example"}')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(cfg["local_port"], 9999)
        self.assertEqual(cfg["cf_url"], "https://old.example")

    def test_a_path_from_another_pc_is_replaced(self) -> None:
        """開発者の PC の設定をコピーしたときの、別の PC のパス（1 つ上のフォルダも無い）は、使えない。"""
        other = "C:/Users/someone_else_xyz/Desktop/DevelopmentRAGEnvironment"
        r, cfg = self._config_after(json.dumps({"local_bridge_dir": other}).encode("utf-8"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(cfg["local_bridge_dir"], str(self.data))
        self.assertIn("別の PC", r.stdout)

    def test_an_unwritable_data_dir_does_not_stop_the_install(self) -> None:
        blocker = self.tmp / "blocker"
        blocker.write_text("x", encoding="utf-8")
        r = self.run_ps(data=blocker / "RAGReelTutorial")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("保存先", r.stdout)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8")).get("local_bridge_dir", ""), "")

    def test_self_diagnosis_lists_what_was_written_without_showing_secrets(self) -> None:
        r = self.run_ps("-CloudflareUrl", "https://secret-host.example.workers.dev", "-ApiKey", "KEY123SECRET")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout
        for expected in ("導入の結果（自己診断", "rag_chatbot.py（パネル本体）", "パネル定義", "Houdini 21.0 への登録",
                         "Houdini 22.0 への登録", "設定ファイル", "接続先の URL（cf_url）", "API キー（cf_api_key）",
                         "保存先（local_bridge_dir）", "診断: 問題は見つかりませんでした"):
            self.assertIn(expected, out)
        self.assertIn("入っています", out)
        self.assertNotIn("KEY123SECRET", out)
        self.assertNotIn("secret-host", out)
        report = (self.install / "install_report.txt").read_text(encoding="utf-8-sig")
        self.assertIn("Houdini 22.0 への登録", report)
        self.assertNotIn("KEY123SECRET", report)
        self.assertNotIn("secret-host", report)

    def test_self_diagnosis_says_when_the_url_and_key_are_empty(self) -> None:
        r = self.run_ps()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"\[注意\].*接続先の URL.*空です")
        self.assertRegex(r.stdout, r"\[注意\].*API キー.*空です")

    def test_houdini_installed_but_never_started_gets_its_folder_created(self) -> None:
        """Houdini 本体はあるのに、Documents\\houdiniXX.X が無い（一度も起動していない）。以前は、ここで導入が止まった。"""
        shutil.rmtree(self.docs / "houdini21.0")
        shutil.rmtree(self.docs / "houdini22.0")
        root = self.tmp / "Side Effects Software"
        (root / "Houdini 22.0.504").mkdir(parents=True)
        r = self.run_ps(houdini_root=root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.docs / "houdini22.0" / "packages" / "ragreel_tutorial.json").exists())
        self.assertIn("Houdini 22.0.504", r.stdout)
        self.assertIn("houdini22.0 に登録済み", r.stdout)

    def test_the_version_option_accepts_22_22_0_and_a_full_build_number(self) -> None:
        for given in ("22", "22.0", "22.0.504", "houdini22.0"):
            with self.subTest(given):
                shutil.rmtree(self.docs / "houdini22.0" / "packages", ignore_errors=True)
                r = self.run_ps("-HoudiniVersion", given)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertTrue((self.docs / "houdini22.0" / "packages" / "ragreel_tutorial.json").exists())
                self.assertFalse((self.docs / "houdini21.0" / "packages").exists())

    def test_an_explicit_version_creates_the_folder_when_houdini_was_never_started(self) -> None:
        shutil.rmtree(self.docs / "houdini22.0")
        r = self.run_ps("-HoudiniVersion", "22.0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.docs / "houdini22.0" / "packages" / "ragreel_tutorial.json").exists())
        self.assertFalse((self.docs / "houdini21.0" / "packages").exists())

    def test_versions_before_21_are_skipped_with_a_message(self) -> None:
        (self.docs / "houdini20.5").mkdir()
        r = self.run_ps()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.docs / "houdini20.5" / "packages").exists(), "PySide6 が無い版には、登録しない")
        self.assertIn("houdini20.5", r.stdout)
        self.assertIn("対象外", r.stdout)

    def test_the_failure_message_is_concrete_when_nothing_is_found(self) -> None:
        shutil.rmtree(self.docs / "houdini21.0")
        shutil.rmtree(self.docs / "houdini22.0")
        r = self.run_ps()
        self.assertNotEqual(r.returncode, 0)
        out = r.stdout + r.stderr
        for expected in ("探した場所", "-HoudiniVersion 22.0", "hou.homeHoudiniDirectory()"):
            self.assertIn(expected, out)

    def test_install_cmd_explains_when_run_without_the_other_files(self) -> None:
        """zip の中から install.cmd だけを開くと、install.ps1 が無い。分かる言葉で止める。"""
        lone = self.tmp / "lone"
        lone.mkdir()
        shutil.copy(self.pkg / "install.cmd", lone / "install.cmd")
        raw = subprocess.run(["cmd", "/c", "echo.|", str(lone / "install.cmd")], capture_output=True, timeout=60)
        self.assertNotEqual(raw.returncode, 0)
        self.assertIn("Extract", _decode(raw.stdout))

    def test_the_zip_ships_a_readme_and_the_installer_mentions_the_new_menu(self) -> None:
        names = set(zipfile.ZipFile(self.tmp / "dist" / "RAGReelTutorial-1.2.3.zip").namelist())
        self.assertIn("README.txt", names)
        r = self.run_ps()
        self.assertIn("Python Panel", r.stdout)
        self.assertIn("import rag_chatbot", r.stdout)


if __name__ == "__main__":
    unittest.main()
