"""panel_nav（画面構成・別ウィンドウで開く）と、パネル本体の画面構成・リンク表示の検査。

・前半は、Qt も Houdini も要らない（偽の hou で確かめる）
・後半は、PySide6 がある環境でだけ（無ければ飛ばす）。Qt はオフスクリーン。通信は止める。

2026-11-17 の実証実験の感想: 「タブを切り替えると別のタブが見られず、並行して見られない」「接続などの設定のタブが、
ほかのタブと同じ重さで目立つ」。ふだん使わない画面は、右上の歯車メニューに移した。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini.tests.test_panel_nav -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import panel_nav as nav  # noqa: E402
import panel_paths as pp  # noqa: E402


class VisibleSubPagesTest(unittest.TestCase):
    def test_everyone_sees_history_and_connection_only_setup_users_see_the_rest(self) -> None:
        self.assertEqual(nav.visible_sub_pages(False), ["history", "connection"])
        self.assertEqual(nav.visible_sub_pages(True), ["history", "connection", "settings", "debug"])

    def test_the_everyday_tabs_do_not_include_the_rarely_used_screens(self) -> None:
        keys = [key for key, _label in nav.MAIN_TABS]
        for rare in ("history", "connection", "settings", "debug"):
            self.assertNotIn(rare, keys)
        for everyday in ("guide", "tutorial", "chat", "docs"):
            self.assertIn(everyday, keys)

    def test_titles(self) -> None:
        self.assertEqual(nav.sub_page_title("connection"), "接続・アカウント")
        self.assertEqual(nav.sub_page_title("nope"), "nope")


class FakeHou:
    """open_in_new_window が使う hou の部分だけの偽物。"""

    class paneTabType:  # noqa: N801
        PythonPanel = "PythonPanel"

    def __init__(self, interfaces: dict, fail_on: str = "") -> None:
        self.created: list[str] = []
        self.activated: list[object] = []
        outer = self
        self.fail_on = fail_on

        class Tab:
            def setActiveInterface(self, interface):  # noqa: N802
                if outer.fail_on == "activate":
                    raise RuntimeError("cannot activate")
                outer.activated.append(interface)

        class Desktop:
            def createFloatingPaneTab(self, tab_type):  # noqa: N802
                if outer.fail_on == "create":
                    raise RuntimeError("no desktop")
                outer.created.append(tab_type)
                return Tab()

        class Ui:
            def curDesktop(self):  # noqa: N802
                return Desktop()

        class Pypanel:
            def interfaceByName(self, name):  # noqa: N802
                return interfaces.get(name)

        self.ui = Ui()
        self.pypanel = Pypanel()


class OpenInNewWindowTest(unittest.TestCase):
    def test_opens_a_floating_python_panel_with_the_installed_interface(self) -> None:
        hou = FakeHou({"RAGReelTutorial": "iface"})
        self.assertEqual(nav.open_in_new_window(hou), (True, ""))
        self.assertEqual(hou.created, ["PythonPanel"])
        self.assertEqual(hou.activated, ["iface"])

    def test_falls_back_to_the_developer_interface_name(self) -> None:
        hou = FakeHou({"RAGChatBot": "dev"})
        self.assertTrue(nav.open_in_new_window(hou)[0])
        self.assertEqual(hou.activated, ["dev"])

    def test_missing_interface_gives_a_reason_and_creates_nothing(self) -> None:
        hou = FakeHou({})
        ok, reason = nav.open_in_new_window(hou)
        self.assertFalse(ok)
        self.assertIn("install", reason)
        self.assertEqual(hou.created, [])

    def test_hou_errors_become_a_reason_not_an_exception(self) -> None:
        for fail in ("create", "activate"):
            ok, reason = nav.open_in_new_window(FakeHou({"RAGReelTutorial": "i"}, fail_on=fail))
            self.assertFalse(ok, fail)
            self.assertIn("RuntimeError", reason)

    def test_outside_houdini_it_says_so(self) -> None:
        with mock.patch.dict(sys.modules, {"hou": None}):
            ok, reason = nav.open_in_new_window()
        self.assertFalse(ok)
        self.assertIn("Houdini", reason)

    def test_the_manual_steps_mention_the_split_pane_menu(self) -> None:
        self.assertIn("Split left/right", nav.PARALLEL_VIEW_HELP)  # 公式ドキュメント（Panes）の、ペインのメニューの項目名
        self.assertIn("New floating panel", nav.PARALLEL_VIEW_HELP)
        self.assertIn("別ウィンドウ", nav.PARALLEL_VIEW_HELP)


try:
    import panel_widgets
    import rag_chatbot as rc
    from PySide6.QtWidgets import QApplication, QLabel, QStackedWidget
    HAVE_QT = True
except ImportError:  # PySide6 が無い環境
    rc = None
    HAVE_QT = False


class _SilentWorker:
    """接続確認のスレッドの代わり（通信しない）。"""

    class _Signal:
        def connect(self, *_args) -> None:
            pass

    def __init__(self, *_args) -> None:
        self.result = self.user_info = self.growth_info = self._Signal()

    def isRunning(self) -> bool:  # noqa: N802
        return False

    def start(self) -> None:
        pass


@unittest.skipUnless(HAVE_QT, "PySide6 がありません")
class PanelLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store: dict = {}
        self.opened: list[str] = []
        cfg = {"mode": "cloudflare", "cf_url": "", "cf_api_key": "", "cf_namespaces": "", "local_port": 8766,
               "local_bridge_dir": str(Path(self._tmp.name) / "data"), "llm_backend": "claude"}
        patches = [
            mock.patch.object(rc, "_load_config", lambda: dict(cfg)),
            mock.patch.object(rc, "_save_config", lambda c: None),
            mock.patch.object(rc, "_ui_state_get", lambda key, default=None: self.store.get(key, default)),
            mock.patch.object(rc, "_ui_state_set", lambda key, value: self.store.__setitem__(key, value)),
            mock.patch.object(panel_widgets, "_STATE_PATH", Path(self._tmp.name) / "ui.json"),
            mock.patch.object(rc, "_ConnectionCheckWorker", _SilentWorker),
            mock.patch.object(rc.QDesktopServices, "openUrl", lambda url: self.opened.append(url.toString()) or True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.panel = rc.RAGChatbotPanel()
        self.addCleanup(self.panel.deleteLater)
        self.panel.show()

    def visible_tab_names(self) -> list[str]:
        tabs = self.panel._tabs
        return [tabs.tabText(i) for i in range(tabs.count()) if tabs.isTabVisible(i)]

    # ── 画面構成 ────────────────────────────────────────────────────────────

    def test_only_the_everyday_tabs_are_in_the_tab_bar(self) -> None:
        self.assertEqual(self.visible_tab_names(), ["はじめに", "Chat", "Docs", "Guide", "Tutorial", "動画"])

    def test_rarely_used_screens_are_in_the_gear_menu_not_the_tab_bar(self) -> None:
        names = [self.panel._tabs.tabText(i) for i in range(self.panel._tabs.count())]
        for rare in ("History", "接続", "設定", "デバッグ"):
            self.assertNotIn(rare, names)
        self.assertEqual(set(self.panel._sub_actions), {"history", "connection", "settings", "debug"})
        self.assertGreaterEqual(len(self.panel._gear_menu.actions()), 6)  # 4 画面 + 区切り + 別ウィンドウ + 並べて見る方法

    def test_settings_and_debug_are_hidden_from_ordinary_users(self) -> None:
        self.panel._role = "member"
        self.panel._apply_role_visibility()
        self.assertTrue(self.panel._sub_actions["connection"].isVisible())
        self.assertFalse(self.panel._sub_actions["settings"].isVisible())
        self.assertFalse(self.panel._sub_actions["debug"].isVisible())
        self.panel._show_sub("settings")
        self.assertEqual(self.panel._main_stack.currentIndex(), 0, "設定者でなければ、設定の画面は開かない")
        self.panel._role = "admin"
        self.panel._apply_role_visibility()
        self.assertTrue(self.panel._sub_actions["settings"].isVisible())
        self.assertTrue(self.panel._sub_actions["debug"].isVisible())

    def test_open_a_sub_page_and_come_back(self) -> None:
        self.panel._show_sub("connection")
        self.assertEqual(self.panel._main_stack.currentIndex(), 1)
        self.assertEqual(self.panel._sub_title.text(), "接続・アカウント")
        self.assertIs(self.panel._sub_stack.currentWidget(), self.panel._sub_wrappers["connection"])
        self.panel._show_main()
        self.assertEqual(self.panel._main_stack.currentIndex(), 0)
        self.assertEqual(self.panel._current_sub, "")

    def test_losing_the_setup_role_closes_the_settings_page(self) -> None:
        self.panel._role = "admin"
        self.panel._apply_role_visibility()
        self.panel._show_sub("settings")
        self.assertEqual(self.panel._current_sub, "settings")
        self.panel._role = "member"
        self.panel._apply_role_visibility()
        self.assertEqual(self.panel._main_stack.currentIndex(), 0)

    def test_clicking_the_connection_lamp_opens_the_connection_page(self) -> None:
        self.panel._conn_lamp.clicked.emit()
        self.assertEqual(self.panel._current_sub, "connection")

    def test_opening_a_video_from_history_returns_to_the_tab_screen(self) -> None:
        self.panel._show_sub("history")
        self.panel._on_open_video("x", Path(self._tmp.name) / "x.webm")
        self.assertEqual(self.panel._main_stack.currentIndex(), 0)
        self.assertIs(self.panel._tabs.currentWidget(), self.panel._video_tab_wrapper)

    def test_the_pilot_tab_stays_a_tab_and_follows_the_checkbox(self) -> None:
        self.assertFalse(self.panel._tabs.isTabVisible(self.panel._pilot_tab_idx))
        self.panel._show_sub("connection")
        self.panel._pilot_checkbox.setChecked(True)
        self.assertTrue(self.panel._tabs.isTabVisible(self.panel._pilot_tab_idx))
        self.assertEqual(self.panel._main_stack.currentIndex(), 0)

    # ── 保存先 ──────────────────────────────────────────────────────────────

    def test_save_folder_field_is_on_the_connection_page_for_everyone(self) -> None:
        edit = self.panel._bridge_dir_edit
        self.assertTrue(self.panel._sub_wrappers["connection"].isAncestorOf(edit))
        self.assertEqual(edit.placeholderText(), str(pp.default_data_dir()))
        self.assertIn("いまの保存先", self.panel._data_dir_note.text())

    def test_saving_tells_the_config_writer_only_when_the_folder_was_edited(self) -> None:
        """触っていない保存先は、ファイルの値を守る（インストーラーが入れた値）。画面で変えた・空にしたときは、その値を書く。"""
        calls: list[dict] = []
        with mock.patch.object(rc, "_save_config", lambda c, **kw: calls.append(kw)):
            self.panel._on_save_settings()
            self.panel._bridge_dir_edit.setText("")
            self.panel._on_save_settings()
        self.assertEqual(calls[0], {})
        self.assertEqual(calls[1], {"dir_edited": True})

    # ── リンク ──────────────────────────────────────────────────────────────

    def labels_with_links(self) -> list[QLabel]:
        return [w for w in self.panel._chat_inner.findChildren(QLabel) if "<a " in w.text()]

    def test_urls_in_an_answer_are_clickable_and_open_in_the_browser(self) -> None:
        self.panel._add_rag_bubble("詳しくは https://www.sidefx.com/docs/houdini/ を見てください。", "")
        label = self.labels_with_links()[0]
        self.assertIn('href="https://www.sidefx.com/docs/houdini/"', label.text())
        self.assertFalse(label.openExternalLinks(), "Qt 任せにせず、URL を検査してから開く")
        label.linkActivated.emit("https://www.sidefx.com/docs/houdini/")
        self.assertEqual(self.opened, ["https://www.sidefx.com/docs/houdini/"])

    def test_dangerous_links_are_never_opened(self) -> None:
        for url in ("javascript:alert(1)", "file:///C:/Windows/win.ini", "data:text/html,x", "ftp://a.example/"):
            self.assertFalse(rc.open_external_url(url), url)
        self.assertEqual(self.opened, [])

    def test_a_javascript_link_in_an_answer_is_not_a_link(self) -> None:
        self.panel._add_rag_bubble("[押して](javascript:alert(1)) <a href='javascript:x'>y</a>", "")
        self.assertEqual(self.labels_with_links(), [])

    def test_node_names_get_official_doc_links_under_the_answer(self) -> None:
        self.panel._add_rag_bubble("Pyro Solver で煙を作り、Attribute Wrangle で速度を足します。", "")
        texts = " ".join(w.text() for w in self.labels_with_links())
        self.assertIn("https://www.sidefx.com/docs/houdini/nodes/sop/pyrosolver.html", texts)
        self.assertIn("https://www.sidefx.com/docs/houdini/nodes/sop/attribwrangle.html", texts)
        self.assertIn("公式ドキュメント", texts)

    def test_an_answer_without_nodes_or_urls_has_no_link_row(self) -> None:
        self.panel._add_rag_bubble("こんにちは。今日は、いい天気です。", "")
        self.assertEqual(self.labels_with_links(), [])

    def test_the_explain_line_under_an_answer_is_plain_text(self) -> None:
        """サーバーが返した用語に <b> や <img> が入っていても、書式として解釈しない。"""
        self.panel._add_rag_bubble("答えです", "", explain={"level": "basic", "introduced": ["<b>x</b>", "<img src='file:///c:/a.png'>"]})
        label = next(w for w in self.panel._chat_inner.findChildren(QLabel) if "説明レベル" in w.text())
        self.assertEqual(label.textFormat(), rc.Qt.PlainText)

    def test_user_and_system_messages_stay_plain_text(self) -> None:
        self.panel._add_bubble("<b>太字</b> https://a.example/ を見て", is_user=True)
        bubble = self.panel._chat_inner.findChildren(rc.ChatBubble)[-1]
        self.assertEqual(bubble.text(), "<b>太字</b> https://a.example/ を見て")
        self.assertEqual(bubble.textFormat(), rc.Qt.PlainText)


if __name__ == "__main__":
    unittest.main()
