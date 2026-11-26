"""panel_motion(Chat の状態変化のばね)の検査。Qt はオフスクリーンで動かす。

実行(リポジトリのルートで):  uv run python -m unittest houdini.tests.test_panel_motion -v
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HOUDINI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOUDINI / "python_panels"))

try:
    from PySide6.QtWidgets import QApplication  # noqa: E402
except ImportError as exc:  # CI など PySide6 が入っていない環境では、このモジュール全体をスキップする
    raise unittest.SkipTest("PySide6 がありません") from exc

import panel_actions as pa  # noqa: E402
import panel_motion as pm  # noqa: E402
import token_usage as tu  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _settle(spring: pm.Spring, seconds: float = 3.0) -> None:
    for _ in range(int(seconds * 60)):
        spring.advance(1 / 60)


class StepTest(unittest.TestCase):
    def test_values_match_the_web_chat(self) -> None:
        """Web(chatUi.ts の DRMotion.SPRINGS)と同じ値であること。"""
        web = (HOUDINI.parent / "cloudflare-rag-poc" / "src" / "chatUi.ts").read_text(encoding="utf-8")
        for name, (k, c) in pm.SPRINGS.items():
            self.assertRegex(web, rf"{name}: \[{k}, {c}\]")
        self.assertIn(f"Q_SOFT_LIMIT = {pm.Q_SOFT_LIMIT}", web)
        self.assertIn(f"}}, {pm.COPY_REVERT_MS});", web)

    def test_spring_settles_on_target_with_overshoot(self) -> None:
        x, v, peak = 0.0, 0.0, 0.0
        for _ in range(240):
            x, v = pm.step(x, v, 1.0, 420, 18, 1 / 60)
            peak = max(peak, x)
        self.assertGreater(peak, 1.0)  # 弾む(減衰比 < 1)
        self.assertTrue(pm.at_rest(x, v, 1.0))

    def test_long_frame_is_capped(self) -> None:
        """固まったフレーム(1 秒)でも、1/30 秒ぶんしか進まない(飛ばない)。"""
        self.assertEqual(pm.step(0.0, 0.0, 1.0, 300, 20, 1.0), pm.step(0.0, 0.0, 1.0, 300, 20, 1 / 30))


class SpringTest(unittest.TestCase):
    def test_reduced_motion_jumps_and_ignores_kick(self) -> None:
        seen = []
        s = pm.Spring("limitShake", 0.0, seen.append, reduced=lambda: True)
        s.to(5.0)
        self.assertEqual(s.value, 5.0)
        self.assertFalse(s.running)
        s.kick(34)
        self.assertEqual(s.velocity, 0.0)
        self.assertEqual(seen, [5.0])

    def test_runs_until_rest_then_stops(self) -> None:
        s = pm.Spring("copyIcon", 0.0, reduced=lambda: False)
        s.to(1.0)
        self.assertTrue(s.running)
        _settle(s)
        self.assertEqual(s.value, 1.0)
        self.assertFalse(s.running)


class CopyFeedbackTest(unittest.TestCase):
    def test_check_icon_exists(self) -> None:
        self.assertIn("check", pa.ICON_PATHS)

    def test_copied_changes_tooltip_and_reverts(self) -> None:
        btn = pa.action_button("copy", "回答をコピー")
        fx = pm.CopyFeedback(btn, "回答をコピー")
        fx.copied()
        self.assertTrue(fx.done)
        self.assertEqual(btn.toolTip(), "コピーしました")
        self.assertEqual(btn.accessibleName(), "コピーしました")
        self.assertEqual(fx._revert.interval(), pm.COPY_REVERT_MS)
        fx._revert.stop()
        fx._reset()
        self.assertFalse(fx.done)
        self.assertEqual(btn.toolTip(), "回答をコピー")


class LetterLimitTest(unittest.TestCase):
    def test_states_by_length(self) -> None:
        ring = pm.LetterLimitRing()
        expected = [(0, "hidden"), (399, "hidden"), (400, "ok"), (719, "ok"), (720, "near"), (800, "near"), (801, "over")]
        for n, state in expected:
            ring.set_count(n)
            self.assertEqual(ring.state, state, n)
            self.assertEqual(ring.isHidden(), state == "hidden", n)
        self.assertEqual(ring.remaining, -1)
        self.assertIn("文脈には入りません", ring.toolTip())

    def test_crossing_the_limit_shakes_once(self) -> None:
        ring = pm.LetterLimitRing()
        ring._shake._reduced = ring._pop._reduced = ring._fill._reduced = lambda: False
        ring.set_count(790)
        self.assertEqual(ring._shake.velocity, 0.0)
        ring.set_count(801)
        self.assertEqual(ring._shake.velocity, 34)
        self.assertEqual(ring._pop.value, 1.25)
        ring._shake.jump(0.0)
        ring.set_count(802)  # 超えたまま: もう揺れない
        self.assertEqual(ring._shake.velocity, 0.0)
        self.assertEqual(ring._pop.value, 1.12)

    def test_first_show_does_not_animate_fill(self) -> None:
        ring = pm.LetterLimitRing()
        ring.set_count(600)
        self.assertAlmostEqual(ring._fill.value, 600 / 800)


class GaugeTest(unittest.TestCase):
    def test_first_value_is_instant_then_springs(self) -> None:
        g = tu.DonutGauge()
        g._arc._reduced = g._squash._reduced = lambda: False
        g.set_percent(70)
        self.assertEqual(g._arc.value, 70)
        g.set_percent(58)
        self.assertEqual(g._percent, 58)  # 数字はすぐに新しい値
        self.assertEqual(g._arc.value, 70)  # 円弧はこれから縮む
        self.assertEqual(g._squash.value, 0.7)
        _settle(g._arc)
        self.assertEqual(g._arc.value, 58)


class WiringTest(unittest.TestCase):
    def test_chat_uses_the_motion_parts_and_deploy_lists_the_module(self) -> None:
        src = (HOUDINI / "python_panels" / "rag_chatbot.py").read_text(encoding="utf-8")
        self.assertIn("_CopyFeedback(copy_btn", src)
        self.assertIn("copy_fx.copied()", src)
        self.assertRegex(src, re.compile(r"textChanged\.connect\(lambda: self\._q_limit\.set_count"))
        deploy = (HOUDINI / "deploy_panels.py").read_text(encoding="utf-8")
        self.assertIn('"panel_motion"', deploy)


if __name__ == "__main__":
    unittest.main()
