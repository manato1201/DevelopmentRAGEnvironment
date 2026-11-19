"""Chat の「確認中…」の表示（panel_thinking.py）と、Guide の案内メッセージの短縮（guide_view.compact_messages）のテスト（2026-11-19）。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_thinking_and_status.py -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class ThinkingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        import panel_thinking as pt

        self.pt = pt

    def test_dot_colors_move_one_dot_at_a_time(self) -> None:
        a, i = self.pt.ACTIVE, self.pt.INACTIVE
        self.assertEqual(self.pt.dot_colors(0), [a, i, i])
        self.assertEqual(self.pt.dot_colors(1), [i, a, i])
        self.assertEqual(self.pt.dot_colors(2), [i, i, a])
        self.assertEqual(self.pt.dot_colors(3), [a, i, i])
        self.assertEqual(self.pt.dot_colors(5, 4), [i, a, i, i])
        self.assertEqual(self.pt.dot_colors(0, 0), [])  # 点が 0 個の指定でも落ちない

    def test_the_message_changes_with_the_waiting_time(self) -> None:
        self.assertEqual(self.pt.message_for(0), "関連情報を確認中")
        self.assertEqual(self.pt.message_for(5.9), "関連情報を確認中")
        self.assertEqual(self.pt.message_for(6), "回答を作成中")
        self.assertEqual(self.pt.message_for(60), "回答を作成中")
        self.assertEqual(self.pt.message_for(-3), "関連情報を確認中")

    def test_reduced_motion_from_the_environment(self) -> None:
        with mock.patch.dict(os.environ, {"RAGREEL_REDUCE_MOTION": "1"}):
            self.assertTrue(self.pt.reduced_motion())
        with mock.patch.dict(os.environ, {"RAGREEL_REDUCE_MOTION": ""}), mock.patch("panel_widgets.ui_state_get", lambda k, d=None: d):
            self.assertFalse(self.pt.reduced_motion())

    def test_the_row_animates_and_stops(self) -> None:
        with mock.patch.dict(os.environ, {"RAGREEL_REDUCE_MOTION": ""}), mock.patch("panel_widgets.ui_state_get", lambda k, d=None: d):
            row = self.pt.ThinkingRow()
        self.addCleanup(row.deleteLater)
        row.start()
        self.assertTrue(row.is_running())
        self.assertEqual(row.text(), "関連情報を確認中")
        row._on_tick()
        row._on_tick()
        self.assertEqual(row._dots.colors(), self.pt.dot_colors(2))
        row.stop()
        self.assertFalse(row.is_running())

    def test_the_text_changes_after_six_seconds(self) -> None:
        with mock.patch.dict(os.environ, {"RAGREEL_REDUCE_MOTION": ""}), mock.patch("panel_widgets.ui_state_get", lambda k, d=None: d):
            row = self.pt.ThinkingRow()
        self.addCleanup(row.deleteLater)
        row.start()
        for _ in range(17):  # 380ms × 17 = 6.46 秒
            row._on_tick()
        self.assertEqual(row.text(), "回答を作成中")
        row.stop()

    def test_with_reduced_motion_the_dots_do_not_move(self) -> None:
        with mock.patch.dict(os.environ, {"RAGREEL_REDUCE_MOTION": "1"}):
            row = self.pt.ThinkingRow()
        self.addCleanup(row.deleteLater)
        row.start()
        for _ in range(5):
            row._on_tick()
        self.assertTrue(row._dots.isHidden())
        self.assertEqual(row._dots.colors(), self.pt.dot_colors(0))
        self.assertTrue(row.text().endswith("…"))
        row.stop()


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class CompactMessagesTest(unittest.TestCase):
    def setUp(self) -> None:
        import guide_view as gv

        self.gv = gv

    def test_many_shown_nodes_become_one_line(self) -> None:
        paths = [f"/obj/ai_tutorial_1/energy/node{i}" for i in range(14)]
        messages = [f"示したノード: {p}（サンドボックス）" for p in paths] + ["サンドボックスの実物を示しました（見本です）", "いまのネットワーク: /obj/x"]
        out = self.gv.compact_messages(messages)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0], "示したノード: 14個（node0、node1、node2 ほか）")
        self.assertIn("サンドボックスの実物", out[1])

    def test_one_or_two_nodes_are_kept_as_they_are(self) -> None:
        messages = ["示したノード: /obj/a/b（自分のネットワーク）", "示したノード: /obj/a/c（自分のネットワーク）", "いまのネットワーク: /obj/a"]
        self.assertEqual(self.gv.compact_messages(messages), messages)

    def test_duplicates_are_removed_in_order(self) -> None:
        self.assertEqual(self.gv.compact_messages(["a", "b\na", "c", "b"]), ["a", "b", "c"])

    def test_empty(self) -> None:
        self.assertEqual(self.gv.compact_messages([]), [])


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class GuideStatusWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_the_status_is_short_and_keeps_the_full_text_in_the_tooltip(self) -> None:
        import guide_view as gv

        widget = gv.GuideWidget(lambda: {"local_bridge_dir": ""})
        self.addCleanup(widget.deleteLater)
        lines = [f"行{i}" for i in range(9)]
        widget._set_status(lines)
        shown = widget._status.text().splitlines()
        self.assertEqual(len(shown), gv._STATUS_MAX_LINES + 1)
        self.assertIn("ほか 5 行", shown[-1])
        self.assertEqual(widget._status.toolTip().splitlines(), lines)

    def test_the_step_view_keeps_a_minimum_height(self) -> None:
        import guide_view as gv

        widget = gv.GuideWidget(lambda: {"local_bridge_dir": ""})
        self.addCleanup(widget.deleteLater)
        self.assertGreaterEqual(widget._step_view.minimumHeight(), 200)


if __name__ == "__main__":
    unittest.main()
