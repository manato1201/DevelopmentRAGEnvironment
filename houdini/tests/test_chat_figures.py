"""chat_figures.py（チャットの回答に、Reference の撮影画像を添える。2026-11-25）のテスト。Qt を使わない部分。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import chat_figures as cf  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:
    QApplication = None


def _meta(kind: str, key: str, title: str, media: int = 3) -> tuple[str, dict]:
    return f"{kind}|{key}", {"kind": kind, "key": key, "title": title, "version": 2, "mediaCount": media}


INDEX = dict([
    _meta("node", "sop/scatter", "Scatter"),
    _meta("node", "sop/attribwrangle", "Attribute Wrangle"),
    _meta("node", "sop/pyrosolver", "Pyro Solver"),
    _meta("node", "sop/copytopoints", "Copy to Points"),
    _meta("node", "sop/polybevel", "PolyBevel", media=0),  # 画像の無い項目は、添えない
    _meta("vex", "vex/noise", "noise"),
    _meta("vex", "vex/fit", "fit"),
    _meta("vex", "vex/point", "point"),
    _meta("shelf", "shelf/pyro_billowysmoke", "Billowy Smoke"),
    _meta("shelf", "shelf/pyro_fireball", "Fireball"),
    _meta("shelf", "shelf/sop_scatter_2_0", "Scatter"),
])


class FigureItemsTest(unittest.TestCase):
    def test_nodes_in_the_answer_that_have_pictures_are_chosen_in_order(self) -> None:
        text = "まず Scatter ノードで点を置き、Copy to Points で箱を並べます。PolyBevel ノードは画像がありません。"
        keys = [i["key"] for i in cf.figure_items(text, INDEX)]
        self.assertEqual(keys, ["sop/scatter", "sop/copytopoints"])

    def test_vex_calls_and_backticked_names_are_found(self) -> None:
        text = "Attribute Wrangle に `@P.y += noise(@P);` と書きます。値の範囲は `fit` で変えます。"
        keys = [i["key"] for i in cf.figure_items(text, INDEX)]
        self.assertEqual(keys, ["sop/attribwrangle", "vex/noise", "vex/fit"])

    def test_a_word_before_a_spaced_parenthesis_is_not_a_vex_call(self) -> None:
        self.assertEqual(cf.figure_items("point (点) の番号を見ます", INDEX), [])
        self.assertEqual(cf.figure_items("obj.point(0) と @P.point(1)", INDEX), [])

    def test_shelf_tools_need_two_words_or_a_tool_mark(self) -> None:
        self.assertEqual([i["key"] for i in cf.figure_items("Billowy Smoke を押すと、煙ができます", INDEX)], ["shelf/pyro_billowysmoke"])
        self.assertEqual(cf.figure_items("Fireball のような爆発", INDEX), [])
        self.assertEqual([i["key"] for i in cf.figure_items("Fireball ツールを押します", INDEX)], ["shelf/pyro_fireball"])

    def test_shelf_tools_are_found_by_the_houdini_label(self) -> None:
        """公開の一覧の名前は、内部名から作ったもの（Pyro Billowysmoke）。Houdini の表示名（Billowy Smoke）で探す。"""
        index = dict([_meta("shelf", "shelf/pyro_billowysmoke", "Pyro Billowysmoke")])
        text = "シェルフの Billowy Smoke を押します"
        self.assertEqual(cf.figure_items(text, index), [])
        got = cf.figure_items(text, index, shelf_labels={"shelf/pyro_billowysmoke": "Billowy Smoke"})
        self.assertEqual([(i["key"], i["title"]) for i in got], [("shelf/pyro_billowysmoke", "Billowy Smoke")])

    def test_a_shelf_tool_with_the_same_name_as_a_node_is_shown_once(self) -> None:
        keys = [i["key"] for i in cf.figure_items("Scatter ノード（Scatter ツール）で点を置きます", INDEX)]
        self.assertEqual(keys, ["sop/scatter"])

    def test_at_most_three_and_nothing_without_an_index(self) -> None:
        text = "Scatter ノード、Copy to Points、Pyro Solver、Attribute Wrangle と noise( を使います"
        self.assertEqual(len(cf.figure_items(text, INDEX)), cf.MAX_FIGURES)
        self.assertEqual(cf.figure_items(text, {}), [])
        self.assertEqual(cf.figure_items("", INDEX), [])


class PickMediaTest(unittest.TestCase):
    def test_before_and_after_come_as_a_pair(self) -> None:
        media = [{"id": "a/clip.1.gif", "role": "clip"}, {"id": "a/after.1.png", "role": "after"},
                 {"id": "a/node.1.png", "role": "node"}, {"id": "a/before.1.png", "role": "before"}]
        self.assertEqual([m["role"] for m in cf.pick_media(media)], ["before", "after"])

    def test_without_a_pair_one_picture_is_chosen(self) -> None:
        self.assertEqual([m["role"] for m in cf.pick_media([{"id": "a/after.png", "role": "after"}, {"id": "a/node.png", "role": "node"}])], ["after"])
        self.assertEqual([m["role"] for m in cf.pick_media([{"id": "s/where.png", "role": "where"}])], ["where"])

    def test_movies_and_broken_records_are_skipped(self) -> None:
        self.assertEqual(cf.pick_media([{"id": "a/clip.gif", "role": "clip"}, {"role": "after"}, "x"]), [])
        self.assertEqual(cf.pick_media(None), [])


@unittest.skipIf(QApplication is None, "PySide6 がありません")
class FigureStripTest(unittest.TestCase):
    """回答の下に出す絵の並び（reference_view.ChatFigureStrip）。通信はしない（start=False で、結果を直接渡す）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _png(self, folder: str, name: str) -> str:
        from PySide6.QtGui import QColor, QImage

        image = QImage(400, 225, QImage.Format_RGB32)
        image.fill(QColor("#336699"))
        path = str(Path(folder) / name)
        image.save(path)
        return path

    def test_nothing_is_shown_without_pictures(self) -> None:
        import reference_view as rv

        strip = rv.ChatFigureStrip({}, "", start=False)
        strip.show_figures([])
        self.assertTrue(strip.isHidden())

    def test_before_and_after_are_shown_and_a_click_opens_the_reference(self) -> None:
        import reference_view as rv

        with tempfile.TemporaryDirectory() as tmp:
            figures = [{"kind": "node", "key": "sop/scatter", "title": "Scatter",
                        "images": [("before", self._png(tmp, "b.png")), ("after", self._png(tmp, "a.png"))]},
                       {"kind": "shelf", "key": "shelf/pyro_fireball", "title": "Fireball", "images": [("where", self._png(tmp, "w.png"))]}]
            strip = rv.ChatFigureStrip({}, "", start=False)
            strip.show_figures(figures)
            self.assertFalse(strip.isHidden())
            texts = [label.text() for label in strip.findChildren(QLabel)]
            self.assertIn("適用前", texts)
            self.assertIn("適用後", texts)
            self.assertIn("操作する場所", texts)
            self.assertIn("→", texts)
            pictures = strip.findChildren(rv._ClickLabel)
            self.assertEqual(len(pictures), 3)
            self.assertLessEqual(pictures[0].pixmap().width(), rv.ChatFigureStrip.PAIR_WIDTH * 2)  # 縮めて出す（高 DPI でも、2 倍まで）
            messages = []
            strip.message.connect(messages.append)
            with mock.patch.object(rv, "open_item", return_value="開きました") as opened:
                pictures[0].clicked.emit()
            opened.assert_called_once()
            self.assertEqual(opened.call_args.args[1:4], ("node", "sop/scatter", "Scatter"))
            self.assertEqual(messages, ["開きました"])

    def test_the_worker_returns_only_items_whose_pictures_were_saved(self) -> None:
        import reference_view as rv

        index = dict([_meta("node", "sop/scatter", "Scatter"), _meta("node", "sop/copytopoints", "Copy to Points")])
        records = {"sop/scatter": {"media": [{"id": "node/sop_scatter/before.1.png", "role": "before"}, {"id": "node/sop_scatter/after.1.png", "role": "after"}]},
                   "sop/copytopoints": {"media": [{"id": "node/sop_copytopoints/after.1.png", "role": "after"}]}}
        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(rv.rr, "fetch_index", return_value=index),                 mock.patch.object(rv.rr, "fetch_entry", side_effect=lambda cfg, kind, key, version=None: records[key]),                 mock.patch.object(rv.rr, "fetch_media", side_effect=lambda cfg, mid: None if "copytopoints" in mid else Path(tmp) / mid.replace("/", "_")):
            worker = rv._FigureWorker({}, "Scatter ノードと、Copy to Points を使います")
            got = []
            worker.done.connect(got.append)
            worker.run()  # スレッドを立てずに、そのまま動かす
        self.assertEqual(len(got), 1)
        self.assertEqual([f["key"] for f in got[0]], ["sop/scatter"])  # 画像が取れなかった項目は、出さない
        self.assertEqual([role for role, _path in got[0][0]["images"]], ["before", "after"])


if __name__ == "__main__":
    unittest.main()
