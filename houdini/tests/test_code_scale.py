"""コードのカードの、文字の拡大（screen_capture.code_scale）のテスト（2026-11-19）。
行が少ないコードは、カードの上のほうに小さく出て、残りが空いていた（2026-11-18 の動画）。収まる範囲で大きくする。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_code_scale.py -v
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
    from PySide6.QtGui import QGuiApplication, QImage
except ImportError:
    QImage = None


class CodeScaleTest(unittest.TestCase):
    def test_few_short_lines_are_enlarged_up_to_the_cap(self) -> None:
        self.assertEqual(sc.code_scale(4, 40, 100, 400.0), sc.CODE_SCALE_MAX)

    def test_a_long_line_limits_the_scale(self) -> None:
        # 100 桁に入る箱に、80 桁の行 → 1.25 倍まで
        self.assertAlmostEqual(sc.code_scale(4, 80, 100, 400.0), 1.25)

    def test_many_lines_limit_the_scale_by_height(self) -> None:
        # 高さ 300 に、10 行(28 × 10 + 24 = 304)→ 1.0（縮めない）
        self.assertEqual(sc.code_scale(10, 20, 100, 300.0), 1.0)
        self.assertAlmostEqual(
            sc.code_scale(5, 20, 100, 280.0), 280.0 / (5 * 28.0 + 24.0)
        )

    def test_never_below_one(self) -> None:
        self.assertEqual(sc.code_scale(50, 200, 100, 100.0), 1.0)

    def test_bad_inputs_give_one(self) -> None:
        for args in (
            (0, 10, 100, 100.0),
            (4, 0, 100, 100.0),
            (4, 10, 0, 100.0),
            (4, 10, 100, 0.0),
            (4, 10, 100, -5.0),
        ):
            self.assertEqual(sc.code_scale(*args), 1.0)


@unittest.skipIf(QImage is None, "PySide6 がありません")
class RenderedScaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def _render(self, code: str):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "step_001_network.png"
            pages = sc.render_code_cards(
                out,
                "/obj/geo1",
                "core_attr",
                "Attribute Wrangle",
                [],
                {"label": "VEXpression", "name": "snippet", "new": code, "tab": "Code"},
            )
            return pages, sc.read_capture_meta(out)

    def test_a_short_snippet_is_drawn_larger(self) -> None:
        pages, meta = self._render(
            'i@layer = 0;\nf@strength = chf("strength");\nv@Cd = set(1.0, 0.75, 0.35) * f@strength;'
        )
        self.assertEqual(len(pages), 1)
        self.assertGreater(meta["font_pt"], sc.CODE_FONT_PT)
        self.assertLessEqual(
            meta["font_pt"], round(sc.CODE_FONT_PT * sc.CODE_SCALE_MAX, 1)
        )

    def test_a_long_snippet_keeps_the_base_size(self) -> None:
        code = "\n".join(f"float v{i} = rand(@ptnum + {i});" for i in range(40))
        pages, meta = self._render(code)
        self.assertGreaterEqual(len(pages), 2)
        self.assertEqual(meta["font_pt"], sc.CODE_FONT_PT)


if __name__ == "__main__":
    unittest.main()


class ParamCardScaleTest(unittest.TestCase):
    def test_few_rows_are_enlarged_to_the_cap(self) -> None:
        self.assertEqual(sc.param_card_scale(1), sc.PARAM_SCALE_MAX)
        self.assertEqual(sc.param_card_scale(3), sc.PARAM_SCALE_MAX)

    def test_more_rows_get_a_smaller_scale_but_never_below_one(self) -> None:
        values = [sc.param_card_scale(n) for n in range(1, 9)]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertGreaterEqual(min(values), 1.0)
        self.assertLess(values[-1], sc.PARAM_SCALE_MAX)

    def test_cards_with_code_or_others_are_not_scaled(self) -> None:
        self.assertEqual(sc.param_card_scale(2, has_code=True), 1.0)
        self.assertEqual(sc.param_card_scale(2, has_others=True), 1.0)
        self.assertEqual(sc.param_card_scale(0), 1.0)


@unittest.skipIf(QImage is None, "PySide6 がありません")
class ParamCardRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_the_card_is_still_the_expected_size_when_scaled(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "card.png"
            ok = sc.render_parameter_card(out, "/obj/geo1", "orbit_src", "Sphere",
                                          [{"label": "Primitive Type", "name": "type", "old": "0", "new": "polymesh"}])
            self.assertTrue(ok)
            image = QImage(str(out))
            self.assertEqual((image.width(), image.height()), (1280 * sc.RENDER_SCALE, 720 * sc.RENDER_SCALE))
