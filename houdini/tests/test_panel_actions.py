"""panel_actions(アイコンボタンと、4K・拡大表示への対応)の検査。Qt はオフスクリーンで動かす。

実行(リポジトリのルートで):  uv run python -m unittest houdini.tests.test_panel_actions -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

import panel_actions as pa  # noqa: E402

_app = QApplication.instance() or QApplication([])


class PtQssTest(unittest.TestCase):
    def test_px_font_becomes_pt(self) -> None:
        self.assertEqual(pa.pt_qss("color:#fff;font-size:12px;"), "color:#fff;font-size:9.0pt;")

    def test_pt_and_other_values_are_left_alone(self) -> None:
        qss = "font-size:9pt;padding:6px 10px;border-radius:8px;"
        self.assertEqual(pa.pt_qss(qss), qss)

    def test_normalize_fonts_rewrites_children(self) -> None:
        root = QWidget()
        label = QLabel("x", root)
        label.setStyleSheet("font-size:11px;color:#aaa;")
        self.assertEqual(pa.normalize_fonts(root), 1)
        self.assertNotIn("px", label.styleSheet().split("font-size")[1].split(";")[0])


class TypeScaleTest(unittest.TestCase):
    """チュートリアル生成の画面の文字の大きさ(タイプスケール)。pt で、4 段階だけ。"""

    def test_four_roles_in_pt_and_ordered(self) -> None:
        self.assertEqual(set(pa.TYPE_SCALE), {"heading", "body", "caption", "code"})
        self.assertGreater(pa.TYPE_SCALE["heading"], pa.TYPE_SCALE["body"])
        self.assertGreater(pa.TYPE_SCALE["body"], pa.TYPE_SCALE["caption"])
        for role in pa.TYPE_SCALE:
            qss = pa.type_qss(role, "#fff")
            self.assertIn("pt;", qss)
            self.assertNotIn("px", qss.split("font-size")[1].split(";")[0])
            self.assertAlmostEqual(pa.type_font(role).pointSizeF(), pa.TYPE_SCALE[role])

    def test_unknown_role_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            pa.type_qss("huge")

    def test_button_kinds(self) -> None:
        self.assertEqual(pa.button_qss("secondary"), "")  # 副は OS 標準の見た目のまま
        self.assertIn("background:#2563eb", pa.button_qss("primary"))
        self.assertIn("#7f1d1d", pa.button_qss("danger"))

    def test_generate_panel_has_no_px_fonts(self) -> None:
        """生成画面は、拡大率で文字がずれないよう、スタイルシートに px のフォントを書かない(動的に当てるものも含む)。"""
        import tempfile

        import tutorial_view as tv

        panel = tv.TutorialGeneratePanel(lambda: {"local_bridge_dir": tempfile.mkdtemp()})
        panel._set_video_bar(30, "描画")
        for widget in [panel, *panel.findChildren(QWidget)]:
            self.assertNotRegex(widget.styleSheet(), r"font-size\s*:\s*[\d.]+px", type(widget).__name__)


class ScaleTest(unittest.TestCase):
    def test_px_is_at_least_one_and_scales_up(self) -> None:
        self.assertGreaterEqual(pa.px(0), 1)
        self.assertGreaterEqual(pa.px(28), 28)  # 拡大率は 1.0 以上


class ActionButtonTest(unittest.TestCase):
    def test_every_icon_renders(self) -> None:
        for name in pa.ICON_PATHS:
            self.assertFalse(pa.make_icon(name).isNull(), name)

    def test_button_has_name_for_screen_readers(self) -> None:
        btn = pa.action_button("copy", "回答をコピー")
        self.assertEqual(btn.toolTip(), "回答をコピー")
        self.assertEqual(btn.accessibleName(), "回答をコピー")

    def test_checkable_button_changes_icon_when_toggled(self) -> None:
        btn = pa.action_button("thumbUp", "良い", checkable=True)
        before = btn.icon().pixmap(16, 16).toImage()
        btn.setChecked(True)
        after = btn.icon().pixmap(16, 16).toImage()
        self.assertNotEqual(before, after)

    def test_click_calls_back(self) -> None:
        hit: list[int] = []
        btn = pa.action_button("refresh", "再試行", lambda: hit.append(1))
        btn.click()
        self.assertEqual(hit, [1])


if __name__ == "__main__":
    unittest.main()
