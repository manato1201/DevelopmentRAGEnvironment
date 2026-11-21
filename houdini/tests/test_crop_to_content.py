"""screen_capture.crop_to_content（画像の余白の切り詰め。2026-11-22）のテスト。

動画で、実画面のパラメータ・コードが、枠の半分ほどの大きさでしか映らず、文字が読めなかった。
原因: 2560x1440 などの画像の中身が左上の 3 割ほどで、残りは背景の色だった。背景と違う画素の範囲だけを切り出す。
PySide6 が無い環境では、飛ばす。  実行: uv run --with PySide6 python -m unittest houdini/tests/test_crop_to_content.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))
sys.modules.setdefault("hou", types.ModuleType("hou"))

import screen_capture as sc  # noqa: E402

try:
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402
except ImportError:
    QImage = None

BG = QColor(47, 47, 49)


def canvas(width: int, height: int):
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(BG)
    return image


def draw_box(image, x: int, y: int, w: int, h: int, color=QColor(240, 240, 240)):
    painter = QPainter(image)
    painter.fillRect(x, y, w, h, color)
    painter.end()


@unittest.skipIf(QImage is None, "PySide6 is not installed")
class CropToContentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_content_in_a_corner_is_cut_out_with_a_margin(self) -> None:
        image = canvas(2560, 1440)
        draw_box(image, 100, 80, 900, 300)  # 左上に、パラメータの行がある
        x, y, w, h = sc.content_rect(image, pad=24)
        self.assertEqual((x, y), (76, 56))
        self.assertEqual((w, h), (948, 348))
        cropped = sc.crop_to_content(image)
        self.assertEqual((cropped.width(), cropped.height()), (948, 348))
        self.assertLess(cropped.width() * cropped.height(), 2560 * 1440 * 0.1, "the text now fills most of the picture")

    def test_the_background_colour_is_found_from_the_borders(self) -> None:
        # 背景が明るい色でも、同じ
        image = QImage(1000, 800, QImage.Format_ARGB32)
        image.fill(QColor(250, 250, 250))
        draw_box(image, 400, 300, 200, 100, QColor(20, 20, 20))
        x, y, w, h = sc.content_rect(image, pad=0)
        self.assertEqual((x, y, w, h), (400, 300, 200, 100))

    def test_a_single_colour_image_is_left_alone(self) -> None:
        image = canvas(800, 600)
        self.assertIsNone(sc.content_rect(image))
        self.assertIs(sc.crop_to_content(image), image)

    def test_an_image_that_is_all_content_is_not_cropped(self) -> None:
        image = canvas(800, 600)
        draw_box(image, 10, 10, 780, 580)
        self.assertIs(sc.crop_to_content(image), image, "less than 8% would be cut: keep the original")

    def test_a_tiny_part_is_not_enlarged_too_much(self) -> None:
        image = canvas(2560, 1440)
        draw_box(image, 1200, 700, 40, 20)
        cropped = sc.crop_to_content(image, min_width=480, min_height=270)
        self.assertEqual((cropped.width(), cropped.height()), (480, 270), "grown to the minimum size around the part")

    def test_the_minimum_size_stays_inside_the_image(self) -> None:
        image = canvas(1000, 600)
        draw_box(image, 0, 0, 30, 20)  # 隅
        cropped = sc.crop_to_content(image, min_width=480, min_height=270)
        self.assertEqual((cropped.width(), cropped.height()), (480, 270))
        # 隅の中身が、切り出しに入っている（外にはみ出して、中身が切れていない）
        self.assertEqual(QColor(cropped.pixel(5, 5)).red(), 240)

    def test_faint_noise_is_not_content(self) -> None:
        image = canvas(1200, 800)
        draw_box(image, 700, 500, 5, 5, QColor(50, 50, 52))  # 背景との差が、許容の範囲（各色 10 以下）
        self.assertIsNone(sc.content_rect(image))

    def test_shrink_saved_image_rewrites_the_file_only_when_it_helps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "card.png"
            image = canvas(2560, 1440)
            draw_box(image, 80, 60, 1200, 400)
            image.save(str(path), "PNG")
            self.assertTrue(sc.shrink_saved_image(path))
            after = QImage(str(path))
            self.assertLess(after.width(), 2560)
            self.assertLess(after.height(), 1440)
            self.assertFalse(sc.shrink_saved_image(path), "already tight: unchanged the second time")
            self.assertFalse(sc.shrink_saved_image(Path(tmp) / "missing.png"))


if __name__ == "__main__":
    unittest.main()
