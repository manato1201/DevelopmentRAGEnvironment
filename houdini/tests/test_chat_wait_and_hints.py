"""Chat の待ち時間と、質問の例（2026-11-25、実証実験の A3）のテスト。

  ・rag_client.iter_sse / post_stream / RAGClient.query(on_sources, on_delta) … /query/stream を受け取る（偽のサーバー）
  ・question_hints.suggest … 状況（Guide の手順・選んだノード・エラー）から、質問の例を作る
  ・RAGChatbotPanel … 先に見つかった資料・届いた分の回答を出し、完成した回答に置き換える。質問の例を押すと送る
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import question_hints as qh  # noqa: E402
import rag_client as rcl  # noqa: E402


def _sse(*events: tuple[str, dict]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in events).encode("utf-8")


class SseParseTest(unittest.TestCase):
    def test_events_come_in_order_and_broken_data_is_skipped(self) -> None:
        raw = _sse(("sources", {"sources": [{"file": "a.md"}]}), ("delta", {"text": "こん"})) + b": ping\n\nevent: delta\ndata: {broken\n\n" + _sse(("done", {"answer": "x"}))
        got = list(rcl.iter_sse(io.BytesIO(raw)))
        self.assertEqual([name for name, _ in got], ["sources", "delta", "done"])
        self.assertEqual(got[1][1], {"text": "こん"})

    def test_the_last_event_without_a_blank_line_is_kept(self) -> None:
        self.assertEqual(list(rcl.iter_sse([b"event: done", b'data: {"answer": "A"}'])), [("done", {"answer": "A"})])


class _Handler(BaseHTTPRequestHandler):
    paths: list[str] = []
    stream_status = 200
    stream_body = b""

    def log_message(self, *args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 -- http.server の名前
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        _Handler.paths.append(self.path)
        if self.path == "/query/stream":
            self.send_response(_Handler.stream_status)
            if _Handler.stream_status != 200:
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "not found"}')
                return
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.end_headers()
            self.wfile.write(_Handler.stream_body)
            return
        data = json.dumps({"answer": "まとめて", "sources": [], "memoryId": 1}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class StreamQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        _Handler.paths = []
        _Handler.stream_status = 200
        _Handler.stream_body = _sse(("sources", {"sources": [{"file": "pyro.md"}]}), ("delta", {"text": "Pyro は"}),
                                    ("delta", {"text": "煙です"}), ("done", {"answer": "Pyro は煙です", "sources": [{"file": "pyro.md", "cited": True}], "memoryId": 9}))
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.client = rcl.RAGClient({"mode": "cloudflare", "cf_url": f"http://127.0.0.1:{self.server.server_port}", "cf_api_key": "K", "local_port": 1})

    def test_sources_arrive_before_the_answer_and_the_done_result_is_returned(self) -> None:
        seen: list = []
        result = self.client.query("Pyro?", [], on_sources=lambda s: seen.append(("sources", s)), on_delta=lambda t: seen.append(("delta", t)))
        self.assertEqual(seen, [("sources", [{"file": "pyro.md"}]), ("delta", "Pyro は"), ("delta", "煙です")])
        self.assertEqual(result["memoryId"], 9)
        self.assertEqual(_Handler.paths, ["/query/stream"])

    def test_an_error_event_becomes_an_exception(self) -> None:
        _Handler.stream_body = _sse(("sources", {"sources": []}), ("error", {"error": "予算を超えました"}))
        with self.assertRaisesRegex(RuntimeError, "予算を超えました"):
            self.client.query("Pyro?", [], on_delta=lambda t: None)

    def test_a_stream_cut_before_done_is_an_error(self) -> None:
        _Handler.stream_body = _sse(("delta", {"text": "途中"}))
        with self.assertRaisesRegex(RuntimeError, "途中で切れました"):
            self.client.query("Pyro?", [], on_delta=lambda t: None)

    def test_an_old_worker_without_the_stream_falls_back_to_query(self) -> None:
        _Handler.stream_status = 404
        result = self.client.query("Pyro?", [], on_delta=lambda t: None)
        self.assertEqual(result["answer"], "まとめて")
        self.assertEqual(_Handler.paths, ["/query/stream", "/query"])

    def test_without_callbacks_the_plain_query_is_used(self) -> None:
        self.assertEqual(self.client.query("Pyro?", [])["answer"], "まとめて")
        self.assertEqual(_Handler.paths, ["/query"])


class QuestionHintsTest(unittest.TestCase):
    def test_nothing_known_gives_the_general_examples(self) -> None:
        hints = qh.suggest()
        self.assertEqual(len(hints), qh.MAX_HINTS)
        self.assertEqual([h["label"] for h in hints], [h["label"] for h in qh.GENERAL])

    def test_errors_come_first_then_the_guide_step_then_the_selected_node(self) -> None:
        step = {"index": 2, "total": 8, "title": "壊れる箱", "instruction": "RBD Material Fracture を作る", "node_label": "RBD Material Fracture",
                "purpose": "箱を割る"}
        hints = qh.suggest(step, selected=[{"label": "Box", "name": "/obj/geo1/box1"}],
                           errors=[{"label": "Bullet Solver", "name": "/obj/geo1/rbdbulletsolver1"}], limit=4)
        self.assertEqual([h["label"] for h in hints], ["Bullet Solver のエラーを直すには？", "手順 3は何をしている？",
                                                       "RBD Material Fr… の主なパラメータは？", "Box は何をするノード？"])
        self.assertIn("RBD Material Fracture を作る", hints[1]["query"])
        self.assertIn("目的: 箱を割る", hints[1]["query"])
        self.assertIn("「壊れる箱」", hints[1]["query"])
        self.assertIn("/obj/geo1/rbdbulletsolver1", hints[0]["query"])

    def test_at_most_the_limit_and_no_duplicates(self) -> None:
        hints = qh.suggest(None, selected=[{"label": "Scatter"}, {"label": "Scatter"}])
        self.assertEqual(len(hints), qh.MAX_HINTS)
        self.assertEqual(len({h["query"] for h in hints}), len(hints))
        self.assertTrue(all(len(h["label"]) <= 30 for h in qh.suggest({"instruction": "x" * 80, "node_label": "N" * 40})))


try:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except ImportError:  # pragma: no cover
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class PanelStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        import panel_widgets
        import rag_chatbot as rc
        from test_panel_nav import _SilentWorker

        self.rc = rc
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store: dict = {}
        cfg = {"mode": "cloudflare", "cf_url": "", "cf_api_key": "", "cf_namespaces": "", "local_port": 8766,
               "local_bridge_dir": str(Path(tmp.name) / "data"), "llm_backend": "claude"}
        for patch in (
            mock.patch.object(rc, "_load_config", lambda: dict(cfg)),
            mock.patch.object(rc, "_save_config", lambda c: None),
            mock.patch.object(rc, "_ui_state_get", lambda key, default=None: store.get(key, default)),
            mock.patch.object(rc, "_ui_state_set", lambda key, value: store.__setitem__(key, value)),
            mock.patch.object(panel_widgets, "_STATE_PATH", Path(tmp.name) / "ui.json"),
            mock.patch.object(rc, "_ConnectionCheckWorker", _SilentWorker),
            mock.patch.object(rc, "_REFERENCE_AVAILABLE", False),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.panel = rc.RAGChatbotPanel()
        self.addCleanup(self.panel.deleteLater)

    def _texts(self) -> list[str]:
        return [label.text() for label in self.panel._chat_inner.findChildren(QLabel) if not label.isHidden() or True]

    def test_early_sources_and_partial_answer_are_replaced_by_the_final_answer(self) -> None:
        panel = self.panel
        panel._show_thinking()
        panel._on_early_sources([{"file": "rbd_<intro>.md"}, {"file": "rbd_<intro>.md"}, {"title": "bullet.md"}])
        self.assertIn("先に見つかった資料", panel._early_sources.text())
        self.assertIn("rbd_&lt;intro&gt;.md", panel._early_sources.text())  # 名前はエスケープする
        panel._on_answer_delta("Bullet は")
        panel._on_answer_delta("剛体です")
        self.assertEqual(panel._stream_bubble.text(), "Bullet は剛体です")
        self.assertIsNone(panel._thinking_row)  # 回答が届き始めたら、「確認中」は消す
        panel._on_query_done({"answer": "Bullet は剛体のソルバーです", "sources": [{"file": "bullet.md", "cited": True}], "memoryId": 3})
        self.assertIsNone(panel._early_sources)
        self.assertIsNone(panel._stream_bubble)
        self.assertTrue(panel._send_btn.isEnabled())

    def test_an_error_clears_the_partial_answer(self) -> None:
        panel = self.panel
        panel._on_answer_delta("途中まで")
        panel._on_query_error("切れました")
        self.assertIsNone(panel._stream_bubble)

    def test_a_hint_button_sends_its_question(self) -> None:
        panel = self.panel
        panel._refresh_hints()
        buttons = panel._hints_box.findChildren(QPushButton)
        self.assertEqual(len(buttons), qh.MAX_HINTS)
        sent: list[str] = []
        with mock.patch.object(type(panel), "_on_send", lambda self: sent.append(self._input.toPlainText())):
            buttons[0].click()
        self.assertEqual(sent, [qh.GENERAL[0]["query"]])

    def test_the_hints_follow_the_guide_step(self) -> None:
        panel = self.panel
        guide = mock.Mock()
        guide.step_brief.return_value = {"index": 0, "instruction": "Box を作る", "node_label": "Box"}
        panel._guide_widget = guide
        panel._refresh_hints()
        labels = [b.text() for b in panel._hints_box.findChildren(QPushButton)]
        self.assertEqual(labels[0], "手順 1は何をしている？")

    def test_hints_can_be_turned_off(self) -> None:
        self.panel._cfg["chat_hints"] = False
        self.panel._refresh_hints()
        self.assertTrue(self.panel._hints_box.isHidden())


if __name__ == "__main__":
    unittest.main()
