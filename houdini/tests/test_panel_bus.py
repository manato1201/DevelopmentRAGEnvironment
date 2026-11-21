"""panel_bus（複数のパネルの間の連絡）のテスト（2026-11-21）。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_panel_bus.py -v
"""

from __future__ import annotations

import gc
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import panel_bus as bus  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication, QLabel, QTabWidget, QVBoxLayout, QWidget
except ImportError:
    QApplication = None


if QApplication is not None:
    class FakeGuide(QWidget):
        pass

    class FakeReference(QWidget):
        pass

    class FakePanel(QWidget):
        """タブ（Guide・Reference）を持つ、パネルの代わり。"""

        def __init__(self) -> None:
            super().__init__()
            layout = QVBoxLayout(self)
            self._tabs = QTabWidget()
            layout.addWidget(self._tabs)
            self.guide, self.reference = FakeGuide(), FakeReference()
            self._tabs.addTab(self.guide, "Guide")
            self._tabs.addTab(self.reference, "Reference")
            bus.register(self)


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class PanelBusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        bus._panels.clear()
        self.a, self.b = FakePanel(), FakePanel()
        self.a.show()
        self.b.show()

    def tearDown(self) -> None:
        for panel in (self.a, self.b):
            try:
                panel.close()
                panel.deleteLater()
            except RuntimeError:  # テストの中で、すでに消したもの
                pass
        bus._panels.clear()

    def test_a_panel_is_registered_once(self) -> None:
        bus.register(self.a)
        self.assertEqual(len(bus.live_panels()), 2)

    def test_the_source_panel_is_never_the_target(self) -> None:
        self.assertIs(bus.route(self.a.guide, FakeReference), self.b.reference)
        self.assertIs(bus.route(self.b.guide, FakeReference), self.a.reference)

    def test_without_another_panel_it_returns_none_so_the_caller_stays_in_its_own_panel(self) -> None:
        bus.unregister(self.b)
        self.assertIsNone(bus.route(self.a.guide, FakeReference))

    def test_a_hidden_panel_is_skipped(self) -> None:
        self.b.hide()  # 背面のペインタブ
        self.assertIsNone(bus.route(self.a.guide, FakeReference))

    def test_the_panel_already_showing_the_tab_comes_first(self) -> None:
        c = FakePanel()
        c.show()
        try:
            self.b._tabs.setCurrentWidget(self.b.guide)
            c._tabs.setCurrentWidget(c.reference)
            self.assertIs(bus.route(self.a.guide, FakeReference), c.reference)
            self.b._tabs.setCurrentWidget(self.b.reference)
            c._tabs.setCurrentWidget(c.guide)
            self.assertIs(bus.route(self.a.guide, FakeReference), self.b.reference)
        finally:
            c.close()

    def test_disabled_returns_none(self) -> None:
        self.assertIsNone(bus.route(self.a.guide, FakeReference, enabled=False))

    def test_a_widget_that_is_not_in_any_panel_is_routed_to_any_visible_panel(self) -> None:
        stray = QLabel("x")
        self.assertIsNone(bus.panel_of(stray))
        self.assertIn(bus.route(stray, FakeReference), (self.a.reference, self.b.reference))

    def test_a_closed_panel_disappears_without_an_error(self) -> None:
        b = self.b
        self.b = FakePanel()  # tearDown が閉じる用
        bus.unregister(b)
        del b
        gc.collect()
        self.assertTrue(all(p is not None for p in bus.live_panels()))

    def test_a_deleted_qt_object_does_not_break_routing(self) -> None:
        from shiboken6 import delete

        delete(self.b)
        self.assertIsNone(bus.route(self.a.guide, FakeReference))


class OpenStepAcrossPanelsTest(unittest.TestCase):
    """Guide ⇄ Reference の移動が、別のパネルを向く（reference_view の入口）。"""

    @classmethod
    def setUpClass(cls) -> None:
        if QApplication is None:
            raise unittest.SkipTest("PySide6 がありません")
        cls.app = QApplication.instance() or QApplication([])

    def test_open_guide_step_goes_to_the_other_panels_guide(self) -> None:
        import guide_view
        import reference_view as rv

        class StubGuide(guide_view.GuideWidget):
            def __init__(self) -> None:  # 本物の画面は作らない（中身は、移動の確認に要らない）
                QWidget.__init__(self)
                self.went: list[int] = []

            def hideEvent(self, event) -> None:  # noqa: N802 -- 本物は、タイマーを止める
                pass

            def showEvent(self, event) -> None:  # noqa: N802
                pass

            def goto_step(self, index: int) -> bool:
                self.went.append(index)
                return True

        class StubPanel(QWidget):
            def __init__(self) -> None:
                super().__init__()
                layout = QVBoxLayout(self)
                self._tabs = QTabWidget()
                layout.addWidget(self._tabs)
                self.guide = StubGuide()
                self.reference = QWidget()
                self._tabs.addTab(self.reference, "Reference")
                self._tabs.addTab(self.guide, "Guide")
                bus.register(self)

        bus._panels.clear()
        a, b = StubPanel(), StubPanel()
        a.show()
        b.show()
        try:
            a._tabs.setCurrentWidget(a.reference)
            b._tabs.setCurrentWidget(b.reference)
            message = rv.open_guide_step(a.reference, 4)
            self.assertEqual(b.guide.went, [4], "the step opens in the other panel")
            self.assertEqual(a.guide.went, [])
            self.assertIs(b._tabs.currentWidget(), b.guide, "and that panel jumps to its Guide tab")
            self.assertIs(a._tabs.currentWidget(), a.reference, "this panel stays where it was")
            self.assertIn("別のパネル", message)
        finally:
            a.close()
            b.close()
            bus._panels.clear()


if __name__ == "__main__":
    unittest.main()
