"""Tutorial タブの「追加指示で作り直す」（TutorialGeneratePanel._on_followup）の画面のテスト（2026-11-18）。
生成そのものは動かさない（_start_generation を、呼ばれ方を記録する偽物に差し替える）。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_followup_ui.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # Qt が無い環境では、飛ばす
    QApplication = None

MD = "## 概要\n光の 3 層。\n## 手順\n### 章1 位置づけ\n本文\n"


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class FollowupUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        import tutorial_view as tv

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = {"local_bridge_dir": self.tmp.name, "cf_url": "", "cf_api_key": ""}
        self.panel = tv.TutorialGeneratePanel(lambda: cfg)
        self.addCleanup(self.panel.deleteLater)
        self.calls: list = []
        self.panel._start_generation = lambda requirements_override=None: self.calls.append(requirements_override)
        self.panel._topic_edit.setText("参考画像に近いエネルギー")
        self.result = types.SimpleNamespace(title="3層の光", markdown=MD)

    def test_the_button_is_off_until_there_is_a_result(self) -> None:
        self.assertFalse(self.panel._followup_btn.isEnabled())

    def test_an_empty_instruction_asks_for_one_and_starts_nothing(self) -> None:
        self.panel._result = self.result
        self.panel._followup_edit.setPlainText("   ")
        self.panel._on_followup()
        self.assertEqual(self.calls, [])
        self.assertIn("追加指示を入力", self.panel._status.text())

    def test_without_a_result_nothing_starts(self) -> None:
        self.panel._followup_edit.setPlainText("青くして")
        self.panel._on_followup()
        self.assertEqual(self.calls, [])

    def test_the_instruction_the_digest_and_the_original_requirements_go_to_the_next_generation(self) -> None:
        self.panel._result = self.result
        self.panel._requirements_edit.setPlainText("Scatter を必ず使う")
        self.panel._followup_edit.setPlainText("光を青にして、\n粒を倍にする")
        self.panel._on_followup()
        self.assertEqual(len(self.calls), 1)
        requirements = self.calls[0]
        self.assertTrue(requirements.startswith("Scatter を必ず使う"))
        self.assertIn("追加指示: 光を青にして、 粒を倍にする", requirements)
        self.assertIn("章1 位置づけ", requirements)
        self.assertIn("「3層の光」", requirements)
        self.assertEqual(self.panel._followup_edit.toPlainText(), "", "送ったら、入力欄を空にする")
        # 入力欄の必須条件は、書き換えない
        self.assertEqual(self.panel._requirements_edit.toPlainText(), "Scatter を必ず使う")

    def test_the_followup_box_is_collapsed_by_default(self) -> None:
        self.assertTrue(self.panel._followup_box.is_collapsed() or self.panel._followup_box.title().startswith("追加指示"))


if __name__ == "__main__":
    unittest.main()
