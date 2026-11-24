"""生成の完了・失敗の処理が、途中で例外を出しても、ボタンが無効のまま残らないこと（2026-11-24）。
「チュートリアル生成のあと、タブ以外が効かなくなる」への備え（docs/reports/pilot-fix-list-2026-11-24.md の B2）。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_generation_guard_ui.py -v
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

import panel_debug  # noqa: E402


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class GenerationGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        import tutorial_view as tv

        self.tv = tv
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = {"local_bridge_dir": self.tmp.name, "cf_url": "", "cf_api_key": ""}
        self.panel = tv.TutorialGeneratePanel(lambda: cfg)
        self.addCleanup(self.panel.deleteLater)
        panel_debug.clear()

    def _generating(self) -> None:
        """生成を始めた直後の状態（ボタンは無効、注意書きは出ている）。"""
        for btn in (self.panel._generate_btn, self.panel._save_btn, self.panel._discard_btn, self.panel._delete_sandbox_btn, self.panel._followup_btn):
            btn.setEnabled(False)
        self.panel._set_busy(True)

    def test_the_busy_banner_is_hidden_until_generation_and_goes_away_when_it_ends(self) -> None:
        self.assertTrue(self.panel._busy_banner.isHidden())
        self.panel._set_busy(True)
        self.assertFalse(self.panel._busy_banner.isHidden())
        self.panel._on_failed("接続できません")
        self.assertTrue(self.panel._busy_banner.isHidden())
        self.assertTrue(self.panel._generate_btn.isEnabled())

    def test_an_exception_in_the_done_handler_still_gives_the_buttons_back(self) -> None:
        self._generating()
        result = types.SimpleNamespace(markdown="# x", claude_quota_known=False)
        with mock.patch.object(self.tv.token_usage, "record_usage", side_effect=RuntimeError("記録できない")):
            self.panel._on_done(result)  # 例外は、ここで止まる（画面には出ない）
        self.assertTrue(self.panel._generate_btn.isEnabled(), "生成ボタンが、無効のまま残らない")
        self.assertTrue(self.panel._save_btn.isEnabled())
        self.assertTrue(self.panel._busy_banner.isHidden())
        self.assertIn("後処理でエラー", self.panel._status.text())
        self.assertIn("RuntimeError", panel_debug.as_text(), "デバッグの記録に残る")

    def test_an_exception_in_the_chain_handler_still_gives_the_generate_button_back(self) -> None:
        self._generating()
        bad = (types.SimpleNamespace(), types.SimpleNamespace(markdown="x", level="basic", claude_quota_known=False))
        with mock.patch.object(self.tv.token_usage, "record_usage", side_effect=OSError("disk")):
            self.panel._on_chain_done([bad])
        self.assertTrue(self.panel._generate_btn.isEnabled())
        self.assertTrue(self.panel._busy_banner.isHidden())
        self.assertIn("OSError", panel_debug.as_text())

    def test_a_normal_failure_is_logged_with_start_and_end(self) -> None:
        self._generating()
        self.panel._on_failed("x")
        text = panel_debug.as_text()
        self.assertIn("_on_failed: 開始", text)
        self.assertIn("_on_failed: 終了", text)


if __name__ == "__main__":
    unittest.main()
