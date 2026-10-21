"""tutorial_agent.context_hint_for（トピック → 検索で優先する章）のテスト。実行: uv run python -m unittest discover -s houdini/tests -v"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import tutorial_agent as ta  # noqa: E402


class ContextHintTest(unittest.TestCase):
    def test_sop_is_always_first(self) -> None:
        for topic in ("岩を散らす", "Pyroで炎のシミュレーション", "APEXでリグを作る", "Solarisでマテリアル", ""):
            self.assertEqual(ta.context_hint_for(topic)[0], "SOP", topic)

    def test_domains(self) -> None:
        self.assertEqual(ta.context_hint_for("岩を散らす"), ["SOP"])
        self.assertIn("DOP", ta.context_hint_for("炎・煙のシミュレーション", "Pyroを使うこと"))
        self.assertIn("APEX", ta.context_hint_for("キャラクターのリグ"))
        self.assertIn("APEX", ta.context_hint_for("autorig", target_model="rig.fbx"))
        self.assertIn("LOP", ta.context_hint_for("Solarisでライティング"))
        self.assertIn("COP", ta.context_hint_for("Copernicusでノイズ"))
        self.assertIn("VOP", ta.context_hint_for("VOPでシェーダを作る"))
        self.assertIn("VEX", ta.context_hint_for("Attribute Wrangleで点を動かす"))
        self.assertIn("TOP", ta.context_hint_for("PDGで一括処理"))

    def test_deterministic_and_no_duplicates(self) -> None:
        a = ta.context_hint_for("Pyroの煙と爆発と炎")
        self.assertEqual(a, ta.context_hint_for("Pyroの煙と爆発と炎"))
        self.assertEqual(len(a), len(set(a)))

    def test_word_boundaries_avoid_false_hits(self) -> None:
        # "top" in English / "stop" / "desktop" must not select the TOP context; "rigid" is not "rig"
        self.assertNotIn("TOP", ta.context_hint_for("stop motion on the desktop, top view"))
        self.assertNotIn("APEX", ta.context_hint_for("rigid body"))


if __name__ == "__main__":
    unittest.main()
