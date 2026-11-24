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
    {"title": "Scatter SOP tips for Houdini", "excerpt": "Scatter points", "tags": ["YouTube"], "published": "2026-11-18T00:00:00Z", "source": "Entagma", "url": "https://example.com/s"},
    {"title": "other", "excerpt": "x", "tags": [], "published": "2026-11-01T00:00:00Z"},
]}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# reference_view は panel_actions(PySide6)を読み込むので、PySide6 の無い環境(CI)ではこのクラスもスキップする。
@unittest.skipIf(QApplication is None, "PySide6 がありません")
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
        import panel_bus

        panel_bus._panels.clear()  # 前のテストが残した、見えているパネルに、移動を取られないように
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        import reference_view as rv

        self.rv = rv
        env = mock.patch.dict(os.environ, {"RAGREEL_REFERENCE_AUTHOR": "1"})  # 開発者モード（説明を AI で作る）。参加者の動きは、ParticipantTest
        env.start()
        self.addCleanup(env.stop)
        rd.set_shelf_tools([])
        self.addCleanup(rd.set_shelf_tools, [])
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"local_bridge_dir": self.tmp.name, "cf_url": "", "cf_api_key": "", "tutorial_rag_namespace": ""}
        self.completed: list = []

        def complete(system, user, **options):
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

    def _wait_refresh(self) -> None:
        deadline = time.time() + 10
        while not self.widget._refresh_btn.isEnabled() and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def test_reload_drops_the_saved_entry_and_reports_the_result(self) -> None:
        """「再読み込み」: 保存してある説明を消し、一覧を待ち時間なしで取り直し、結果を出す（公開した修正が、すぐ反映される）。"""
        import reference_remote as rr

        item = self.widget._items[0]
        self.widget._show(item)
        path = rr._entry_path(self.cfg, item["kind"], item["key"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entry": {"what": "古い説明"}, "media": [], "title": "t", "version": 1}), encoding="utf-8")
        index = {"node|sop/other": {"kind": "node", "key": "sop/other", "title": "t", "version": 1, "mediaCount": 0}}  # 見ている項目は、含めない（含めると、説明の取り直しの通信が走る）
        with mock.patch.object(rr, "fetch_index", lambda cfg, **kw: index), mock.patch.object(rr, "index_fetched_at", lambda cfg: time.time() + 5):
            self.widget._on_refresh()
            self.assertFalse(self.widget._refresh_btn.isEnabled(), "取っている間は、押せない")
            self._wait_refresh()
        self.assertTrue(self.widget._refresh_btn.isEnabled())
        self.assertIn("再読み込みしました", self.widget._status.text())
        self.assertIn("1 件", self.widget._status.text())
        self.assertFalse(path.exists(), "保存してあった古い説明は、消えている")

    def test_reload_says_so_when_the_server_cannot_be_reached(self) -> None:
        import reference_remote as rr

        self.widget._show(self.widget._items[0])
        with mock.patch.object(rr, "fetch_index", lambda cfg, **kw: {}), mock.patch.object(rr, "index_fetched_at", lambda cfg: 0.0):
            self.widget._on_refresh()
            self._wait_refresh()
        self.assertTrue(self.widget._refresh_btn.isEnabled(), "失敗しても、もう一度押せる")
        self.assertIn("再読み込みできませんでした", self.widget._status.text())

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
        self.assertEqual(self.widget._items, [])  # Houdini の外では、一覧が空
        self.assertIn("Houdini の中で開くと出ます", self.widget._status.text())

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
        self.assertIn("Scatter SOP tips for Houdini", user)  # HoudiniReference の関連が、依頼に入る
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
        self.widget._complete_getter = lambda: (lambda s, u, **kw: ("すみません、分かりません", {}))
        self.widget._search.setText("scatter")
        self.widget._on_make()
        self._wait(self.widget)
        self.assertIn("読み取れません", self.widget._status.text())
        self.assertIsNone(rd.load_entry(self.tmp.name, "node", "sop/scatter"))

    def test_an_exception_from_the_ai_is_shown_not_raised(self) -> None:
        def boom(_s, _u, **kw):
            raise RuntimeError("予算を使い切りました")

        self.widget._complete_getter = lambda: boom
        self.widget._search.setText("scatter")
        self.widget._on_make()
        self._wait(self.widget)
        self.assertIn("予算", self.widget._status.text())

    def test_a_custom_shelf_tool_is_created_by_name(self) -> None:
        self.widget._set_kind("shelf")
        self.widget._search.setText("Billowy Smoke")
        self.assertFalse(self.widget._create_custom.isHidden())  # 開発者モードだけ
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
        import panel_bus

        panel_bus._panels.clear()  # 前のテストが残した、見えているパネルに、移動を取られないように
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


GUIDE = {"title": "t", "sandbox_path": "", "steps": [
    {"tool": "create_node", "node": "s1", "node_type": "scatter::2.0", "node_label": "Scatter", "instruction": "散らす点を作る", "tab": "network", "tab_label": "ネットワーク"},
    {"tool": "create_node", "node": "m1", "node_type": "merge", "instruction": "まとめる", "tab": "network", "tab_label": "ネットワーク"},
    {"tool": "set_parm", "node": "s1", "node_type": "scatter::2.0", "instruction": "数を変える", "tab": "parameters", "tab_label": "パラメータ"},
]}


class UsedStepsTest(unittest.TestCase):
    def test_used_steps_lists_every_step_that_uses_the_item(self) -> None:
        steps = rd.used_steps(GUIDE, "node", "sop/scatter")
        self.assertEqual([i for i, _ in steps], [0, 2])
        self.assertIn("散らす", steps[0][1])
        self.assertEqual(rd.used_steps(GUIDE, "node", "sop/nothing"), [])
        self.assertEqual(rd.used_steps(None, "node", "sop/scatter"), [])

    def test_entry_html_links_each_step_and_states_the_cost_before_making(self) -> None:
        item = {"kind": "node", "key": "sop/scatter", "label": "Scatter"}
        html = rd.entry_html(item, None, None, True, [(0, "散らす"), (2, "数を変える")], author=True)
        self.assertIn('href="step:0"', html)
        self.assertIn('href="step:2"', html)
        self.assertIn("手順 3", html)
        self.assertIn("トークン", html)  # 説明を作る前に、AI を呼ぶ費用を伝える
        self.assertNotIn("step:", rd.entry_html(item, None, None, False, None))


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class JumpAndCostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import panel_bus

        panel_bus._panels.clear()  # 前のテストが残した、見えているパネルに、移動を取られないように
        cls.app = QApplication.instance() or QApplication([])

    def _tabs(self):
        import guide_view as gv
        import reference_view as rv

        tabs = QTabWidget()
        self.addCleanup(tabs.deleteLater)
        guide_widget = gv.GuideWidget(lambda: {"local_bridge_dir": ""})
        reference = rv.ReferenceWidget(lambda: {"local_bridge_dir": "", "tutorial_model": "claude-sonnet-5-5"}, lambda: None)
        tabs.addTab(guide_widget, "Guide")
        tabs.addTab(reference, "Reference")
        guide_widget.load_generated(GUIDE, "t")
        return tabs, guide_widget, reference

    def test_clicking_a_step_link_opens_that_step_in_guide(self) -> None:
        import reference_view as rv
        from PySide6.QtCore import QUrl

        with mock.patch.object(rv, "fetch_reference_items", lambda base_dir, **kw: []):
            tabs, guide_widget, reference = self._tabs()
            tabs.setCurrentIndex(1)
            reference.show_item("node", "sop/scatter")
            self.assertIn("手順 3", reference._detail.toPlainText())  # 使っている場所の一覧（リンク）が出ている
            reference._on_link(QUrl("step:2"))
            self.assertEqual(tabs.currentIndex(), 0)
            self.assertEqual(guide_widget._index, 2)
            reference._on_link(QUrl("step:99"))  # 範囲外は、何もせず文を出す
            self.assertIn("その手順がありません", reference._status.text())

    def test_goto_step_rejects_out_of_range(self) -> None:
        import reference_view as rv

        with mock.patch.object(rv, "fetch_reference_items", lambda base_dir, **kw: []):
            _tabs, guide_widget, _reference = self._tabs()
            self.assertFalse(guide_widget.goto_step(-1))
            self.assertFalse(guide_widget.goto_step(3))
            self.assertTrue(guide_widget.goto_step(1))
            self.assertEqual(guide_widget._index, 1)

    def test_cost_note_shows_tokens_and_dollars(self) -> None:
        import reference_view as rv

        with mock.patch.object(rv, "fetch_reference_items", lambda base_dir, **kw: []):
            _tabs, _guide, reference = self._tabs()
            note = reference._cost_note({"input_tokens": 5000, "output_tokens": 1000})
            self.assertIn("入力 5,000", note)
            self.assertIn("出力 1,000", note)
            self.assertIn("$0.020", note)  # 5000*2/1M + 1000*10/1M
            self.assertEqual(reference._cost_note({}), "")
            self.assertEqual(reference._cost_note(None), "")

    def test_make_passes_the_short_output_limits_and_shows_the_cost(self) -> None:
        import reference_view as rv

        seen: list = []

        def complete(system, user, **options):
            seen.append(options)
            return json.dumps({"what": "点を散らす", "use": "", "example": "", "example_point": "", "when": ""}), {"input_tokens": 5000, "output_tokens": 1000}

        with tempfile.TemporaryDirectory() as d, mock.patch.object(rv, "fetch_reference_items", lambda base_dir, **kw: []),                 mock.patch.dict(os.environ, {"RAGREEL_REFERENCE_AUTHOR": "1"}), mock.patch.object(rv._EntryWorker, "_fetch_docs", lambda self_, label: []):
            reference = rv.ReferenceWidget(lambda: {"local_bridge_dir": d, "tutorial_model": "claude-sonnet-5-5"}, lambda: complete)
            self.addCleanup(reference.deleteLater)
            reference._search.setText("scatter")
            reference._on_make()
            deadline = time.time() + 10
            while reference._worker is not None and reference._worker.isRunning() and time.time() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            for _ in range(20):
                self.app.processEvents()
            self.assertEqual(seen[0], {"max_tokens": rd.REFERENCE_MAX_TOKENS, "effort": rd.REFERENCE_EFFORT})
            self.assertIn("入力 5,000", reference._status.text())


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class ParticipantTest(unittest.TestCase):
    """参加者の画面: Cloudflare の説明を読むだけ（作れない）。通信は、偽物に差し替える。"""

    @classmethod
    def setUpClass(cls) -> None:
        import panel_bus

        panel_bus._panels.clear()  # 前のテストが残した、見えているパネルに、移動を取られないように
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        import reference_remote as rr
        import reference_view as rv
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QColor, QImage

        self.rr, self.rv = rr, rv
        env = mock.patch.dict(os.environ, {"RAGREEL_REFERENCE_AUTHOR": ""})
        env.start()
        self.addCleanup(env.stop)
        rd.set_shelf_tools([])
        self.addCleanup(rd.set_shelf_tools, [])
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"local_bridge_dir": self.tmp.name, "cf_url": "https://example.invalid", "cf_api_key": "k"}
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor("red"))
        data, buf = QByteArray(), QBuffer()
        buf.setBuffer(data)
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "PNG")
        self.png = bytes(data)
        self.requests: list[str] = []
        self.version = 1
        self.extra_keys: list[str] = []  # 追加で「説明あり」にする項目（切り替えのテスト用）
        self.entry_delay = 0.0
        self.offline_entries = False

        def fake_request(cfg, path, payload, timeout, opener, content_type="application/json"):
            self.requests.append(path)
            if path == "/reference/index":
                keys = ["sop/scatter"] + self.extra_keys
                return json.dumps({"status": "ok", "items": [{"kind": "node", "key": k, "title": k.split("/")[-1], "version": self.version, "mediaCount": 2} for k in keys]}).encode()
            if path == "/reference/entry":
                if self.offline_entries:
                    raise OSError("offline")
                time.sleep(self.entry_delay)
                what = "点を散らす" if payload["key"] == "sop/scatter" else f"{payload['key']} の説明"
                return json.dumps({"status": "ok", "title": "Scatter", "version": self.version, "entry": {"what": f"{what} v{self.version}"},
                                   "media": [{"id": "node/sop/scatter/after.png", "type": "image", "role": "after", "label": "後"},
                                             {"id": "node/sop/scatter/before.png", "type": "image", "role": "before", "label": "前"}]}).encode()
            if path == "/reference/media":
                return self.png
            raise AssertionError(path)

        for target in ("_request",):
            patcher = mock.patch.object(rr, target, fake_request)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(rv, "fetch_reference_items", lambda base_dir, **kw: [])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.widget = rv.ReferenceWidget(lambda: self.cfg, lambda: None)
        self.addCleanup(self.widget.deleteLater)
        self.addCleanup(self._wait_for_threads)  # 後片付けは、あとに登録したものから動く: 取得スレッドが終わってから、一時フォルダを消す

    def _wait_for_threads(self) -> None:
        for worker in (self.widget._index_worker, self.widget._fetch_worker):
            if worker is not None:
                worker.wait(10000)
        for _ in range(10):
            self.app.processEvents()

    def _settle(self, until=None) -> None:
        """スレッドが終わり、結果が画面に届くまで待つ。until（条件の関数）があれば、それが真になるまで（最大 15 秒。負荷の高い全体実行でも、揺れないように）。"""
        deadline = time.time() + 15
        while time.time() < deadline:
            busy = any(w is not None and w.isRunning() for w in (self.widget._index_worker, self.widget._fetch_worker))
            self.app.processEvents()
            if not busy and (until is None or until()):
                break
            time.sleep(0.01)
        for _ in range(20):
            self.app.processEvents()

    def test_participants_cannot_make_explanations(self) -> None:
        self.assertTrue(self.widget._make_btn.isHidden())
        self.assertTrue(self.widget._create_custom.isHidden())
        self.widget._search.setText("scatter")
        self.widget._on_make()
        self.assertIsNone(self.widget._worker, "nothing is started (no AI call)")
        self.widget._search.setText("Billowy Smoke")
        self.widget._on_custom()
        self.assertIsNone(self.widget._worker)

    def test_the_list_is_narrowed_to_items_with_an_explanation_once_the_index_arrives(self) -> None:
        self.assertGreater(self.widget._list.count(), 100, "before the index: everything is listed")
        self.widget._refresh_index(force=True)
        self._settle(lambda: bool(self.widget._remote))
        self.assertEqual([i["key"] for i in self.widget._items], ["sop/scatter"])
        self.assertIn("説明あり 1 件", self.widget._status.text())
        self.widget._described_only.setChecked(False)
        self.assertGreater(self.widget._list.count(), 100)

    def test_items_with_captured_media_are_marked_and_can_be_filtered(self) -> None:
        self.widget._remote = {"node|sop/scatter": {"kind": "node", "key": "sop/scatter", "title": "Scatter", "version": 1, "mediaCount": 4},
                               "node|sop/mountain": {"kind": "node", "key": "sop/mountain", "title": "Mountain", "version": 1, "mediaCount": 0}}
        self.widget._reload()
        rows = {i["key"]: self.widget._list.item(n).text() for n, i in enumerate(self.widget._items)}
        self.assertTrue(rows["sop/scatter"].startswith("▶ "), "has media: marked")
        self.assertFalse(rows["sop/mountain"].startswith("▶ "), "described only: not marked")
        self.assertIn("撮影あり 1 件", self.widget._status.text())
        self.widget._media_only.setChecked(True)
        self.assertEqual([i["key"] for i in self.widget._items], ["sop/scatter"])
        self.widget._media_only.setChecked(False)
        self.assertEqual(sorted(i["key"] for i in self.widget._items), ["sop/mountain", "sop/scatter"])

    def test_selecting_an_item_fetches_shows_and_caches_the_explanation_with_images(self) -> None:
        self.widget._refresh_index(force=True)
        self._settle(lambda: self.widget._current is not None)
        self.assertEqual(self.widget._current["key"], "sop/scatter")
        self._settle(lambda: "点を散らす v1" in self.widget._detail.toPlainText() and self.requests.count("/reference/media") >= 2)
        text = self.widget._detail.toPlainText()
        self.assertIn("点を散らす v1", text)
        self.assertIn("適用前", text)
        self.assertIn("適用後", text)
        self.assertEqual(self.requests.count("/reference/media"), 2)
        document = self.widget._detail.document()
        self.assertIn("refmedia:node/sop/scatter/after.png", self.widget._detail.toHtml())
        self.assertFalse(document.resource(3, self.rv.QUrl("refmedia:node/sop/scatter/after.png")) is None, "the image stays registered after setHtml")
        # 2 回目: 保存した版と同じなので、説明も画像も、通信しない
        before = len(self.requests)
        self.widget._show(self.widget._current)
        self._settle()
        self.assertEqual(len(self.requests), before)
        # 版が上がったら、取り直す
        self.version = 2
        self.widget._refresh_index(force=True)
        self._settle()
        self.widget._show(self.widget._current)
        self._settle()
        self.assertIn("点を散らす v2", self.widget._detail.toPlainText())

    def test_switching_items_while_a_fetch_is_running_still_loads_the_new_one(self) -> None:
        self.extra_keys = ["sop/subdivide"]
        self.entry_delay = 0.3
        self.widget._remote = {}
        self.widget._refresh_index(force=True)
        self._settle(lambda: len(self.widget._remote) == 2)
        self._settle(lambda: self.widget._fetch_worker is not None)
        keys = [i["key"] for i in self.widget._items]
        self.assertEqual(keys, ["sop/scatter", "sop/subdivide"])
        self.widget._list.setCurrentRow(1)  # 最初の取得が終わらないうちに、別の項目へ
        self._settle(lambda: "sop/subdivide の説明 v1" in self.widget._detail.toPlainText())
        self.assertIn("sop/subdivide の説明 v1", self.widget._detail.toPlainText(), "the second item is not left on 'loading'")

    def test_a_late_index_does_not_move_the_selection(self) -> None:
        self.extra_keys = ["sop/subdivide"]
        self.widget._described_only.setChecked(False)
        self.widget._search.setText("sub")
        self.assertEqual(self.widget._current["key"], "sop/subdivide")
        self.widget._on_index({"node|sop/subdivide": {"kind": "node", "key": "sop/subdivide", "title": "Subdivide", "version": 1, "mediaCount": 0},
                               "node|sop/scatter": {"kind": "node", "key": "sop/scatter", "title": "Scatter", "version": 1, "mediaCount": 0}})
        self.assertEqual(self.widget._current["key"], "sop/subdivide")
        self.assertEqual(self.widget._items[self.widget._list.currentRow()]["key"], "sop/subdivide")

    def test_a_failed_fetch_says_so_instead_of_claiming_there_is_no_explanation(self) -> None:
        self.offline_entries = True
        self.widget._refresh_index(force=True)
        self._settle(lambda: bool(self.widget._remote))
        self._settle(lambda: self.widget._fetch_worker is not None)
        self._settle()
        self.assertIn("取得できませんでした", self.widget._status.text())

    def test_guide_button_opens_a_published_node_that_the_catalog_lacks_and_it_is_marked_used(self) -> None:
        import guide_view as gv

        tabs = QTabWidget()
        self.addCleanup(tabs.deleteLater)
        guide_widget = gv.GuideWidget(lambda: {"local_bridge_dir": ""})
        tabs.addTab(guide_widget, "Guide")
        tabs.addTab(self.widget, "Reference")
        self.widget._remote = {"node|sop/mountain": {"kind": "node", "key": "sop/mountain", "title": "Mountain", "version": 1, "mediaCount": 0}}
        guide_widget.load_generated({"title": "t", "sandbox_path": "", "steps": [
            {"tool": "create_node", "node": "m1", "node_type": "mountain::2.0", "node_label": "Mountain", "instruction": "山にする", "tab": "network", "tab_label": "ネットワーク"}]}, "t")
        message = self.rv.open_item_for_step(guide_widget, guide_widget._guide["steps"][0])
        self.assertIn("Mountain", message)
        self.assertEqual(self.widget._current["key"], "sop/mountain", "not a made-up node/mountain item")
        self.assertIn("sop/mountain", self.widget._used["node"])
        self.assertIn("手順 1", self.widget._detail.toPlainText())

    def test_threads_outlive_the_widget_until_they_finish(self) -> None:
        self.widget._refresh_index(force=True)
        worker = self.widget._index_worker
        self.assertIn(worker, self.rv._LIVE_THREADS, "kept alive while running")
        self._settle(lambda: not worker.isRunning())
        deadline = time.time() + 5
        while worker in self.rv._LIVE_THREADS and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertNotIn(worker, self.rv._LIVE_THREADS, "released when finished")

    def test_a_published_item_missing_from_the_catalog_is_still_listed(self) -> None:
        self.widget._remote = {"node|sop/mountain": {"kind": "node", "key": "sop/mountain", "title": "Mountain", "version": 1, "mediaCount": 0}}
        self.widget._reload()
        self.assertEqual([i["key"] for i in self.widget._items], ["sop/mountain"])
        self.assertIn("Mountain", self.widget._list.item(0).text())
        self.assertTrue(self.widget._doc_btn.isEnabled())

    def test_an_item_without_an_explanation_says_so_and_still_offers_the_official_doc(self) -> None:
        self.widget._described_only.setChecked(False)
        self.widget._search.setText("merge")
        self._settle()
        self.assertIn("まだ用意していません", self.widget._detail.toPlainText())
        self.assertNotIn("説明を作る", self.widget._detail.toPlainText())
        self.assertTrue(self.widget._doc_btn.isEnabled())

    def test_when_offline_the_saved_explanation_is_still_shown(self) -> None:
        self.widget._refresh_index(force=True)
        self._settle()
        self._settle()
        with mock.patch.object(self.rr, "_request", side_effect=OSError("offline")):
            fresh = self.rv.ReferenceWidget(lambda: self.cfg, lambda: None)
            self.addCleanup(fresh.deleteLater)
            fresh._described_only.setChecked(True)
            fresh._reload()
            self.assertEqual([i["key"] for i in fresh._items], ["sop/scatter"], "the saved index is used")
            self.assertIn("点を散らす", fresh._detail.toPlainText())

    def test_shelf_tools_come_from_houdini(self) -> None:
        tools = [("Create", "box", "Box"), ("Lights and Cameras", "pointlight", "Point Light")]
        with mock.patch.object(self.rv, "houdini_shelf_tools", lambda: tools):
            self.widget._described_only.setChecked(False)
            self.widget._set_kind("shelf")
        self.assertEqual([i["label"] for i in self.widget._items], ["Box", "Point Light"])
        self.assertIn("[Lights and Cameras]", self.widget._list.item(1).text())
        self.assertIn("全 2 件", self.widget._status.text())

    def test_the_author_switch_comes_from_the_config_or_the_environment(self) -> None:
        self.assertFalse(self.widget._author())
        self.cfg["reference_author_mode"] = True
        self.assertTrue(self.widget._author())
        self.cfg["reference_author_mode"] = False
        with mock.patch.dict(os.environ, {"RAGREEL_REFERENCE_AUTHOR": "1"}):
            self.assertTrue(self.widget._author())


if __name__ == "__main__":
    unittest.main()
