"""Reference タブ（reference_view）の画面と、HoudiniReference の取得・保存のテスト（2026-11-19）。
通信・AI は、偽物に差し替える（実際には呼ばない）。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_reference_view.py -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import reference_data as rd  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication, QTabWidget
except ImportError:
    QApplication = None

ITEMS = {"items": [
    {"title": "scatter tips for Houdini", "excerpt": "Scatter points", "tags": ["YouTube"], "published": "2026-11-18T00:00:00Z", "source": "Entagma", "url": "https://example.com/s"},
    {"title": "other", "excerpt": "x", "tags": [], "published": "2026-11-01T00:00:00Z"},
]}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FetchReferenceItemsTest(unittest.TestCase):
    def test_fetch_saves_then_reuses_the_cache_for_a_day(self) -> None:
        import reference_view as rv

        calls = []

        def opener(url):
            calls.append(url)
            return FakeResponse(json.dumps(ITEMS).encode("utf-8"))

        with tempfile.TemporaryDirectory() as d:
            now = 1_000_000.0
            first = rv.fetch_reference_items(d, now=now, opener=opener)
            second = rv.fetch_reference_items(d, now=now + 3600, opener=opener)
            self.assertEqual(len(first), 2)
            self.assertEqual(second, first)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0], rd.HOUDINI_REFERENCE_URL)
            third = rv.fetch_reference_items(d, now=now + 25 * 3600, opener=opener)  # 1 日たったので、取り直す
            self.assertEqual(len(calls), 2)
            self.assertEqual(third, first)

    def test_a_network_failure_falls_back_to_the_old_cache_or_nothing(self) -> None:
        import reference_view as rv

        def boom(_url):
            raise OSError("offline")

        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(rv.fetch_reference_items(d, opener=boom), [])
            path = Path(d) / "localRAG" / "reference" / "_houdinireference_items.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"fetched_at": 1.0, "items": ITEMS["items"]}), encoding="utf-8")
            self.assertEqual(len(rv.fetch_reference_items(d, now=10_000_000.0, opener=boom)), 2)

    def test_garbage_responses_are_ignored(self) -> None:
        import reference_view as rv

        with tempfile.TemporaryDirectory() as d:
            for body in (b"not json", b"[]", b'{"items": "x"}', b'{"items": [1, "a", null]}'):
                self.assertEqual(rv.fetch_reference_items(d, opener=lambda _u, b=body: FakeResponse(b)), [])

    def test_without_a_folder_nothing_is_saved_but_items_are_returned(self) -> None:
        import reference_view as rv

        self.assertEqual(len(rv.fetch_reference_items("", opener=lambda _u: FakeResponse(json.dumps(ITEMS).encode()))), 2)


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class ReferenceWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        import reference_view as rv

        self.rv = rv
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"local_bridge_dir": self.tmp.name, "cf_url": "", "cf_api_key": "", "tutorial_rag_namespace": ""}
        self.completed: list = []

        def complete(system, user):
            self.completed.append((system, user))
            return json.dumps({"what": "点を散らす", "use": "植生", "example": "", "example_point": "", "when": "密度を決める"}), {}

        self.complete = complete
        # 通信は、しない
        patcher = mock.patch.object(rv, "fetch_reference_items", lambda base_dir, **kw: ITEMS["items"])
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = mock.patch.object(rv._EntryWorker, "_fetch_docs", lambda self_, label: ["Scatter は、点を散らします。"])
        patcher2.start()
        self.addCleanup(patcher2.stop)
        self.widget = rv.ReferenceWidget(lambda: self.cfg, lambda: self.complete)
        self.addCleanup(self.widget.deleteLater)

    def _wait(self, widget) -> None:
        deadline = time.time() + 10
        while widget._worker is not None and widget._worker.isRunning() and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        for _ in range(20):
            self.app.processEvents()

    def test_the_list_starts_with_nodes_and_search_narrows_it(self) -> None:
        self.assertGreater(self.widget._list.count(), 100)
        self.widget._search.setText("scatter")
        self.assertEqual(self.widget._items[0]["key"], "sop/scatter")
        self.assertIn("Scatter", self.widget._list.item(0).text())

    def test_kinds_switch_the_list(self) -> None:
        self.widget._set_kind("vex")
        self.assertTrue(all(i["kind"] == "vex" for i in self.widget._items))
        self.widget._set_kind("apex")
        self.assertTrue(all(i["kind"] == "apex" for i in self.widget._items))
        self.widget._set_kind("shelf")
        self.assertEqual(self.widget._items, [])
        self.assertIn("この名前で作る", self.widget._status.text())

    def test_used_items_are_marked_and_come_first(self) -> None:
        self.widget._used = {"node": {"sop/merge"}, "vex": set(), "apex": set(), "shelf": set()}
        self.widget._reload()
        self.assertTrue(self.widget._list.item(0).text().startswith("● "))
        self.assertEqual(self.widget._items[0]["key"], "sop/merge")
        self.widget._used_only.setChecked(True)
        self.assertEqual([i["key"] for i in self.widget._items], ["sop/merge"])

    def test_make_creates_saves_and_shows_the_entry_then_the_cache_is_used(self) -> None:
        self.widget._search.setText("scatter")
        self.assertEqual(self.widget._current["key"], "sop/scatter")
        self.assertIn("説明を作る", self.widget._detail.toPlainText())
        self.widget._on_make()
        self._wait(self.widget)
        self.assertEqual(len(self.completed), 1)
        user = self.completed[0][1]
        self.assertIn("項目: Scatter（ノード）", user)
        self.assertIn("点を散らします", user)       # 公式の資料が、依頼に入る
        self.assertIn("scatter tips for Houdini", user)  # HoudiniReference の関連が、依頼に入る
        self.assertIn("点を散らす", self.widget._detail.toPlainText())
        self.assertIsNotNone(rd.load_entry(self.tmp.name, "node", "sop/scatter"))
        self.assertEqual(self.widget._make_btn.text(), "説明を作り直す")
        # 選び直すと、保存したものが出る（AI は、呼ばない）
        self.widget._search.setText("merge")
        self.widget._search.setText("scatter")
        self.assertIn("点を散らす", self.widget._detail.toPlainText())
        self.assertEqual(len(self.completed), 1)

    def test_no_ai_connection_shows_a_message(self) -> None:
        self.widget._complete_getter = lambda: None
        self.widget._search.setText("scatter")
        self.widget._on_make()
        self._wait(self.widget)
        self.assertIn("接続できません", self.widget._status.text())
        self.assertTrue(self.widget._make_btn.isEnabled())

    def test_a_bad_ai_answer_shows_a_message_and_saves_nothing(self) -> None:
        self.widget._complete_getter = lambda: (lambda s, u: ("すみません、分かりません", {}))
        self.widget._search.setText("scatter")
        self.widget._on_make()
        self._wait(self.widget)
        self.assertIn("読み取れません", self.widget._status.text())
        self.assertIsNone(rd.load_entry(self.tmp.name, "node", "sop/scatter"))

    def test_an_exception_from_the_ai_is_shown_not_raised(self) -> None:
        def boom(_s, _u):
            raise RuntimeError("予算を使い切りました")

        self.widget._complete_getter = lambda: boom
        self.widget._search.setText("scatter")
        self.widget._on_make()
        self._wait(self.widget)
        self.assertIn("予算", self.widget._status.text())

    def test_a_custom_shelf_tool_is_created_by_name(self) -> None:
        self.widget._set_kind("shelf")
        self.widget._search.setText("Billowy Smoke")
        self.assertFalse(self.widget._create_custom.isHidden())
        self.widget._on_custom()
        self._wait(self.widget)
        self.assertEqual(self.widget._current["key"], "shelf/billowy_smoke")
        self.assertIn("項目: Billowy Smoke（シェルフ）", self.completed[0][1])
        self.assertIsNotNone(rd.load_entry(self.tmp.name, "shelf", "shelf/billowy_smoke"))

    def test_show_item_opens_a_known_item_and_makes_one_for_an_unknown_name(self) -> None:
        self.widget.show_item("node", "sop/scatter")
        self.assertEqual(self.widget._current["key"], "sop/scatter")
        self.widget.show_item("node", "node/mystery_node", "Mystery Node")
        self.assertEqual(self.widget._current["label"], "Mystery Node")
        self.assertTrue(self.widget._current["custom"])

    def test_only_http_links_are_opened(self) -> None:
        from PySide6.QtCore import QUrl

        with mock.patch.object(self.rv.QDesktopServices, "openUrl") as opened:
            self.widget._on_link(QUrl("javascript:alert(1)"))
            self.widget._on_link(QUrl("file:///C:/Windows/System32/calc.exe"))
            opened.assert_not_called()
            self.widget._on_link(QUrl("https://example.com/x"))
            opened.assert_called_once()


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class GuideLinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_the_guide_button_opens_the_node_in_the_reference_tab_and_marks_used_items(self) -> None:
        import guide_view as gv
        import reference_view as rv

        guide = {"title": "t", "sandbox_path": "", "steps": [
            {"tool": "create_node", "node": "s1", "node_type": "scatter::2.0", "node_label": "Scatter", "instruction": "x", "tab": "network", "tab_label": "ネットワーク"},
            {"tool": "create_node", "node": "m1", "node_type": "merge", "instruction": "y", "tab": "network", "tab_label": "ネットワーク"},
        ]}
        with mock.patch.object(rv, "fetch_reference_items", lambda base_dir, **kw: []):
            tabs = QTabWidget()
            self.addCleanup(tabs.deleteLater)
            guide_widget = gv.GuideWidget(lambda: {"local_bridge_dir": ""})
            reference = rv.ReferenceWidget(lambda: {"local_bridge_dir": ""}, lambda: None)
            tabs.addTab(guide_widget, "Guide")
            tabs.addTab(reference, "Reference")
            guide_widget.load_generated(guide, "t")
            tabs.setCurrentIndex(0)
            guide_widget._open_reference()
            self.assertEqual(tabs.currentIndex(), 1)
            self.assertEqual(reference._current["key"], "sop/scatter")
            self.assertIn("Reference タブで", guide_widget._status.text())
            reference._pull_used()
            self.assertTrue({"sop/scatter", "sop/merge"} <= reference._used["node"])

    def test_a_step_without_a_node_says_so(self) -> None:
        import guide_view as gv
        import reference_view as rv

        widget = gv.GuideWidget(lambda: {"local_bridge_dir": ""})
        self.addCleanup(widget.deleteLater)
        self.assertEqual(rv.open_item_for_step(widget, {"tool": "cook_node"}), "この手順には、説明するノードがありません")
        self.assertEqual(rv.open_item_for_step(widget, {"node_type": "scatter"}), "Reference タブが見つかりません")


if __name__ == "__main__":
    unittest.main()
