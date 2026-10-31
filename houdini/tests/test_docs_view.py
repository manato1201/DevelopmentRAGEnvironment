"""docs_view.py（Docs タブ）と、rag_client.py の docs_* / error_message のテスト。標準の unittest。

・純粋な部分（RAGClient の呼び出し・エラー文）は PySide6 なしで確かめる（ナレッジの選び方などは test_doc_tools.py）。
・画面の操作（検索 → 一覧 → 本文 → 続き）は PySide6 がある環境でだけ（無ければ飛ばす）。通信は偽の RAGClient で差し替える。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
Qt の画面も確かめるとき:     uv run --with PySide6 python -m unittest houdini/tests/test_docs_view.py -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import rag_client as rc  # noqa: E402

try:
    import docs_view as dv
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # Qt が無い環境
    dv = None
    HAVE_QT = False

CF_CFG = {"mode": "cloudflare", "cf_url": "https://w.example.test/", "cf_api_key": "k", "local_port": 8766}


class ClientCallsTest(unittest.TestCase):
    def _call(self, method: str, *args, **kwargs):
        with mock.patch.object(rc, "post_json", return_value={"ok": True}) as post:
            result = getattr(rc.RAGClient(CF_CFG), method)(*args, **kwargs)
        return post, result

    def test_paths_and_bodies(self) -> None:
        post, _ = self._call("docs_list", "shared:houdini22", "scatter", 10, 20)
        url, body = post.call_args.args[:2]
        self.assertEqual(url, "https://w.example.test/docs/list")
        self.assertEqual(body, {"namespace": "shared:houdini22", "query": "scatter", "limit": 10, "offset": 20})
        self.assertEqual(post.call_args.kwargs["api_key"], "k")

        post, _ = self._call("docs_get", "shared:houdini22", "a.md", 100, 5000)
        self.assertEqual(post.call_args.args[0], "https://w.example.test/docs/get")
        self.assertEqual(post.call_args.args[1], {"namespace": "shared:houdini22", "file": "a.md", "offset": 100, "maxChars": 5000})

        post, _ = self._call("docs_search", "shared:houdini22", "vellum", 4)
        self.assertEqual(post.call_args.args[0], "https://w.example.test/search")
        self.assertEqual(post.call_args.args[1]["namespaces"], ["shared:houdini22"], "search is pinned to one knowledge base")

    def test_namespaces(self) -> None:
        with mock.patch.object(rc, "post_json", return_value={"namespaces": ["shared:a", "personal:u"]}):
            self.assertEqual(rc.RAGClient(CF_CFG).docs_namespaces(), ["shared:a", "personal:u"])

    def test_local_mode_says_what_is_needed(self) -> None:
        client = rc.RAGClient({**CF_CFG, "mode": "local"})
        with self.assertRaises(RuntimeError) as ctx:
            client.docs_list("shared:houdini22")
        self.assertIn("Cloudflare", str(ctx.exception))


class ErrorMessageTest(unittest.TestCase):
    def _http_error(self, code: int, body: object) -> urllib.error.HTTPError:
        return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(json.dumps(body).encode("utf-8")))  # type: ignore[arg-type]

    def test_worker_error_text_and_suggestions_are_shown(self) -> None:
        exc = self._http_error(404, {"error": "見つかりません", "suggestions": ["nodes/scatter.md"]})
        self.assertEqual(rc.error_message(exc), "見つかりません（近い名前: nodes/scatter.md）")

    def test_unreadable_body_falls_back_to_the_status(self) -> None:
        exc = urllib.error.HTTPError("https://x", 502, "bad", {}, io.BytesIO(b"<html>"))  # type: ignore[arg-type]
        self.assertEqual(rc.error_message(exc), "HTTP 502")

    def test_connection_and_other_errors(self) -> None:
        self.assertIn("接続できません", rc.error_message(urllib.error.URLError("refused")))
        self.assertEqual(rc.error_message(RuntimeError("boom")), "boom")
        self.assertEqual(rc.error_message(RuntimeError("")), "RuntimeError")


class FakeClient:
    """RAGClient の代わり。Worker の応答を返すだけ。"""

    DOC = "# Scatter\n\n" + "points on a surface. " * 40

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def docs_namespaces(self):
        self.calls.append(("ns",))
        return ["personal:me", "shared:houdini21", "shared:houdini22"]

    def docs_search(self, namespace, query, limit=8):
        self.calls.append(("search", namespace, query))
        return {
            "texts": ["検索結果（2 件）:", "\n[1] ファイル: nodes/scatter.md\nScatter creates points.",
                      "\n[2] ファイル: nodes/copy.md\nCopy stamps."],
            "sources": [{"file": "nodes/scatter.md", "score": 100}, {"file": "nodes/copy.md", "score": 71}],
        }

    def docs_list(self, namespace, query="", limit=50, offset=0):
        self.calls.append(("list", namespace, query, offset))
        files = [f"doc{i:03d}.md" for i in range(120)]
        page = files[offset: offset + limit]
        return {"files": page, "total": len(files), "offset": offset}

    def docs_get(self, namespace, file, offset=0, max_chars=20000):
        self.calls.append(("get", namespace, file, offset))
        part = self.DOC[offset: offset + 300]
        end = offset + len(part)
        return {"text": part, "totalChars": len(self.DOC), "nextOffset": end if end < len(self.DOC) else None}


@unittest.skipUnless(HAVE_QT, "PySide6 が無いため、画面のテストを飛ばします")
class WidgetFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.fake = FakeClient()
        patcher = mock.patch.object(dv, "RAGClient", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.widget = dv.DocsWidget({**CF_CFG, "tutorial_rag_namespace": ""})
        self.addCleanup(self.widget.deleteLater)

    def _wait(self, condition, seconds: float = 5.0) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.01)
        self.fail("timed out waiting for the widget")

    def _idle(self) -> bool:
        return not dv._RUNNING_JOBS

    def test_namespaces_load_on_show_and_pick_the_newest_houdini(self) -> None:
        self.widget.show()
        self._wait(lambda: self.widget._ns.count() == 3 and self._idle())
        self.assertEqual(self.widget._ns.currentText(), "shared:houdini22")
        self.assertEqual(self.widget._ns.itemText(2), "personal:me", "personal knowledge comes last")

    def _ready(self) -> None:
        self.widget.show()
        self._wait(lambda: self.widget._ns.count() == 3 and self._idle())

    def test_search_fills_the_list_with_names_scores_and_excerpts(self) -> None:
        self._ready()
        self.widget._query.setText("scatter")
        self.widget._search_btn.click()
        self._wait(lambda: self.widget._results.count() == 2 and self._idle())
        first = self.widget._results.item(0)
        self.assertEqual(first.data(Qt.UserRole), "nodes/scatter.md")
        self.assertIn("関連度 100", first.text())
        self.assertIn("Scatter creates points.", first.text())
        self.assertIn(("search", "shared:houdini22", "scatter"), self.fake.calls)
        self.assertFalse(self.widget._more_btn.isVisible())

    def test_empty_search_does_not_call_the_server(self) -> None:
        self._ready()
        before = len(self.fake.calls)
        self.widget._search_btn.click()
        self.app.processEvents()
        self.assertEqual(len(self.fake.calls), before)
        self.assertIn("検索語", self.widget._status.text())

    def test_name_list_pages_with_show_more(self) -> None:
        self._ready()
        self.widget._list_btn.click()
        self._wait(lambda: self.widget._results.count() == dv.LIST_PAGE and self._idle())
        self.assertTrue(self.widget._more_btn.isVisible())
        self.assertIn("120 件中 50 件", self.widget._status.text())
        self.widget._more_btn.click()
        self._wait(lambda: self.widget._results.count() == 100 and self._idle())
        self.widget._more_btn.click()
        self._wait(lambda: self.widget._results.count() == 120 and self._idle())
        self.assertFalse(self.widget._more_btn.isVisible(), "no more to show")
        self.assertEqual(self.widget._results.item(119).text(), "doc119.md")

    def test_clicking_a_result_opens_the_text_and_continue_appends(self) -> None:
        self._ready()
        self.widget._query.setText("scatter")
        self.widget._search_btn.click()
        self._wait(lambda: self.widget._results.count() == 2 and self._idle())
        self.widget._on_item(self.widget._results.item(0))
        self._wait(lambda: "Scatter" in self.widget._reader.toPlainText() and self._idle())
        self.assertEqual(self.widget._doc_file, "nodes/scatter.md")
        self.assertTrue(self.widget._next_btn.isVisible())
        self.assertIn("300 /", self.widget._doc_title.text())
        first_len = len(self.widget._doc_text)
        self.widget._next_btn.click()
        self._wait(lambda: len(self.widget._doc_text) > first_len and self._idle())
        self.assertIn(("get", "shared:houdini22", "nodes/scatter.md", 300), self.fake.calls)
        while self.widget._doc_next is not None:
            self.widget._next_btn.click()
            before = len(self.widget._doc_text)
            self._wait(lambda: len(self.widget._doc_text) > before and self._idle())
        self.assertEqual(self.widget._doc_text, FakeClient.DOC)
        self.assertFalse(self.widget._next_btn.isVisible())
        self.assertIn("最後まで", self.widget._status.text())

    def test_errors_are_shown_not_raised(self) -> None:
        self._ready()
        self.fake.docs_get = mock.Mock(side_effect=urllib.error.URLError("refused"))  # type: ignore[method-assign]
        self.widget.open_document("x.md")
        self._wait(lambda: "エラー" in self.widget._status.text() and self._idle())
        self.assertIn("接続できません", self.widget._status.text())

    def test_local_mode_explains_and_makes_no_calls(self) -> None:
        widget = dv.DocsWidget({**CF_CFG, "mode": "local"})
        self.addCleanup(widget.deleteLater)
        widget.show()
        self.app.processEvents()
        self.assertIn("Cloudflare", widget._status.text())
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()
