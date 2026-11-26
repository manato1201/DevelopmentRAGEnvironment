"""Guide タブの見直し（2026-11-26。実機の指摘「違うビューポートの画面を出している」「見づらい」）のテスト。

  ・お手本の画面: サンドボックスの形に合わせて撮れなかったビューポート（全体に合わせた = ほかのもの・格子だけ）は出さない。
    補足情報（<画像>.meta.json の framing）を読み、無い以前の画像は capture.log の時刻から求める。
  ・手順を移っても、前の見出し・画像が残って重ならない。ノード図は、ノードの範囲に寄せる。
  ・お手本（サンドボックス）を見ているときは、赤い「階層が違います」にしない。別のサンドボックスの中なら、それを言う。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

HOUDINI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOUDINI / "python_panels"))

import guide_mode as gm  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

SANDBOX = "/obj/ai_tutorial_20261120_140857"


def _touch(path: Path, at: float) -> None:
    path.write_bytes(b"png")
    os.utime(path, (at, at))


class ViewportShotTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_the_meta_decides(self) -> None:
        good, bad = self.dir / "step_002_viewport.png", self.dir / "step_001_viewport.png"
        for path, framing in ((good, "bounds"), (bad, "all")):
            path.write_bytes(b"png")
            Path(str(path) + ".meta.json").write_text(json.dumps({"kind": "viewport", "framing": framing}), encoding="utf-8")
        self.assertTrue(gm.viewport_shot_ok(good))
        self.assertFalse(gm.viewport_shot_ok(bad))

    def test_older_images_are_judged_from_the_capture_log(self) -> None:
        base = time.time() - 100
        lines = []
        for i, (offset, framing) in enumerate(((0.0, "all"), (5.0, "bounds"), (6.0, "all"))):
            stamp = datetime.fromtimestamp(base + offset).isoformat()
            lines.append(f"{stamp} [screen_capture] viewport framing: {framing} (1920x2138)")
            lines.append(f"{stamp} [screen_capture] network framing: focus /obj/x, 1 node(s) in view, 0 outside")
            _touch(self.dir / f"step_{i + 1:03d}_viewport.png", base + offset + 0.8)  # 画像は、構図の行の少しあとに書かれる
        (self.dir / "capture.log").write_text("\n".join(lines), encoding="utf-8")
        self.assertEqual([gm.viewport_framing(self.dir / f"step_{i:03d}_viewport.png") for i in (1, 2, 3)], ["all", "bounds", "all"])
        _touch(self.dir / "step_009_viewport.png", base + 60)  # 対応する行が無い（離れすぎ）: 分からない → 出す
        self.assertEqual(gm.viewport_framing(self.dir / "step_009_viewport.png"), "")
        self.assertTrue(gm.viewport_shot_ok(self.dir / "step_009_viewport.png"))

    def test_step_shots_drop_only_the_unframed_viewport(self) -> None:
        view, net = self.dir / "step_001_viewport.png", self.dir / "step_001_network.png"
        view.write_bytes(b"png")
        net.write_bytes(b"png")
        Path(str(view) + ".meta.json").write_text(json.dumps({"framing": "all"}), encoding="utf-8")
        guide = {gm.SHOTS_KEY: {1: {"viewport": str(view), "network": str(net)}}}
        self.assertEqual(gm.step_shots(guide, {"step": 1}), [("ノードのつながり", str(net))])


class WhereReportTest(unittest.TestCase):
    def places(self, rel: str) -> dict:
        return gm.step_places({"node_path": rel, "node": rel.rsplit("/", 1)[-1]}, SANDBOX)

    def test_the_example_location_is_not_a_level_error(self) -> None:
        places = self.places("fx_geo/path_circle")
        self.assertEqual(places["sandbox_network"], f"{SANDBOX}/fx_geo")
        text, severity = gm.where_report(f"{SANDBOX}/fx_geo", places, SANDBOX)
        self.assertEqual(severity, "example")
        self.assertIn("お手本", text)
        self.assertIn("/obj/fx_geo", text)
        self.assertNotIn("⚠", text)
        # Object レベルの手順: お手本の階層は、サンドボックスそのもの
        self.assertEqual(gm.where_report(SANDBOX, self.places("fx_geo"), SANDBOX)[1], "example")

    def test_inside_this_example_at_another_level_is_a_calm_note(self) -> None:
        text, severity = gm.where_report(f"{SANDBOX}/fx_geo", self.places("fx_geo"), SANDBOX)
        self.assertEqual(severity, "name")
        self.assertIn("作業場所に戻る", text)

    def test_another_sandbox_is_called_out(self) -> None:
        text, severity = gm.where_report("/obj/ai_tutorial_20261122_001652", self.places("fx_geo"), SANDBOX)
        self.assertEqual(severity, "level")
        self.assertIn("別のお手本", text)
        self.assertIn("いまのネットワーク: /obj/ai_tutorial_20261122_001652", text)

    def test_the_usual_cases_are_unchanged(self) -> None:
        places = self.places("geo1/box1")
        self.assertEqual(gm.where_report("/obj/geo1", places, SANDBOX)[1], "same")
        self.assertEqual(gm.where_report("/obj/mine", places, SANDBOX)[1], "name")
        text, severity = gm.where_report("/obj", places, SANDBOX)
        self.assertEqual(severity, "level")
        self.assertIn("⚠ 階層が違います", text)
        self.assertEqual(gm.where_report("", places, SANDBOX)[1], "unknown")


class StripAndLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _image(self, name: str, color: str, size=(640, 360)) -> str:
        from PySide6.QtGui import QColor, QImage

        image = QImage(size[0], size[1], QImage.Format_RGB32)
        image.fill(QColor(color))
        path = str(self.dir / name)
        image.save(path)
        return path

    def test_moving_between_steps_leaves_no_old_captions(self) -> None:
        import guide_view as gv
        from PySide6.QtWidgets import QLabel

        strip = gv.ShotStrip()
        self.addCleanup(strip.deleteLater)
        a, b = self._image("a.png", "#335577"), self._image("b.png", "#775533")
        for _ in range(3):
            strip.show_shots([("結果（ビューポート）", a), ("ノードのつながり", b)])
        self.app.processEvents()
        captions = [w for w in strip.findChildren(QLabel) if not isinstance(w, gv._ShotLabel) and w.parent() is strip]
        self.assertEqual(sorted(c.text() for c in captions), ["ノードのつながり", "結果（ビューポート）"])
        self.assertEqual(strip.show_shots([("ノードのつながり", b)]), 1)
        self.app.processEvents()
        self.assertEqual(len(strip.findChildren(gv._ShotLabel)), 1)

    def test_a_node_diagram_is_cropped_to_its_nodes(self) -> None:
        import guide_view as gv
        from PySide6.QtGui import QColor, QImage, QPainter

        image = QImage(2560, 1440, QImage.Format_RGB32)
        image.fill(QColor("#2f2f31"))
        painter = QPainter(image)
        painter.fillRect(0, 0, 2560, 80, QColor("#232325"))  # 上のパスの帯
        painter.fillRect(30, 20, 500, 40, QColor("#dddddd"))  # 帯の中の文字（範囲に入れない）
        painter.fillRect(1040, 670, 480, 180, QColor("#cccccc"))  # ノード
        painter.end()
        x, y, w, h = gv.diagram_content_rect(image)
        self.assertLess(w, 1000)
        self.assertGreater(y, 80)
        self.assertTrue(x <= 1040 and x + w >= 1520 and y <= 670 and y + h >= 850, (x, y, w, h))
        empty = QImage(640, 360, QImage.Format_RGB32)
        empty.fill(QColor("#2f2f31"))
        self.assertIsNone(gv.diagram_content_rect(empty))

    def test_buttons_are_grouped_and_examples_sit_below_them(self) -> None:
        import guide_view as gv

        state: dict = {}
        for patch in (mock.patch.object(gv, "_state_get", lambda key, default=None: state.get(key, default)),
                      mock.patch.object(gv, "_state_set", lambda key, value: state.__setitem__(key, value)),
                      mock.patch.object(gv, "hou", None)):
            patch.start()
            self.addCleanup(patch.stop)
        widget = gv.GuideWidget(lambda: {})
        self.addCleanup(widget.deleteLater)
        root = widget._step_view.parentWidget().layout()
        order = []
        for i in range(root.count()):
            item = root.itemAt(i)
            if item.widget() is not None:
                order.append(item.widget())
            elif item.layout() is not None:
                order.append([item.layout().itemAt(j).widget() for j in range(item.layout().count())])
        flat = [w for entry in order for w in (entry if isinstance(entry, list) else [entry])]
        self.assertLess(flat.index(widget._pos), flat.index(widget._where), "手順の移動が、場所の表示より上")
        self.assertLess(flat.index(widget._step_view), flat.index(widget._apply_btn))
        self.assertLess(flat.index(widget._apply_btn), flat.index(widget._shots_box), "お手本の画面は、ボタンの下")
        rows = [entry for entry in order if isinstance(entry, list)]
        move = next(r for r in rows if widget._apply_btn in r)
        self.assertTrue({widget._example_btn, widget._mine_btn, widget._home_btn} <= set(move))
        look = next(r for r in rows if widget._ref_btn in r)
        self.assertTrue({widget._terms_btn, widget._ask_btn, widget._auto} <= set(look))


if __name__ == "__main__":
    unittest.main()
