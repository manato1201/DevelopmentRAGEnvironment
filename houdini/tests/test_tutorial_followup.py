"""tutorial_followup（生成したチュートリアルへの追加指示 → 次の生成の必須条件）のテスト（2026-11-18）。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_tutorial_followup.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import tutorial_followup as tf  # noqa: E402

MD = "\n".join([
    "# タイトル",
    "",
    "## 概要",
    "黒背景の中に、コアと軌道と粒の 3 層で光を作る。",
    "層ごとに属性をそろえる。",
    "",
    "## 手順",
    "### 章1 位置づけ：3層を作る",
    "本文",
    "### 章2 比べる：1本化構成",
    "本文",
    "### 章1 位置づけ：3層を作る",  # 重複
    "## TIPS",
    "### TIPS の見出し",
])


class CleanInstructionTest(unittest.TestCase):
    def test_whitespace_is_joined_and_long_text_is_cut(self) -> None:
        self.assertEqual(tf.clean_instruction("  炎を\n青く  して "), "炎を 青く して")
        self.assertEqual(len(tf.clean_instruction("あ" * 2000)), tf.MAX_INSTRUCTION_CHARS)
        self.assertEqual(tf.clean_instruction("   "), "")
        self.assertEqual(tf.clean_instruction(None), "")


class DigestTest(unittest.TestCase):
    def test_overview_and_unique_step_headings(self) -> None:
        digest = tf.digest_of(MD)
        self.assertIn("概要: 黒背景の中に、コアと軌道と粒の 3 層で光を作る。 層ごとに属性をそろえる。", digest)
        self.assertIn("1. 章1 位置づけ：3層を作る / 2. 章2 比べる：1本化構成", digest)
        self.assertEqual(digest.count("章1 位置づけ"), 1, "重複した見出しは 1 回")

    def test_no_overview_or_headings_gives_empty(self) -> None:
        self.assertEqual(tf.digest_of("本文だけ"), "")
        self.assertEqual(tf.digest_of(""), "")

    def test_digest_is_bounded(self) -> None:
        big = "## 概要\n" + "あ" * 5000 + "\n" + "\n".join(f"### 見出し{i} " + "い" * 200 for i in range(200))
        self.assertLessEqual(len(tf.digest_of(big)), tf.MAX_DIGEST_CHARS)

    def test_heading_count_is_capped(self) -> None:
        many = "\n".join(f"### h{i}" for i in range(200))
        self.assertNotIn("41. ", tf.digest_of(many))


class BuildRequirementsTest(unittest.TestCase):
    def test_empty_instruction_gives_nothing(self) -> None:
        self.assertEqual(tf.build_requirements("元の条件", "炎", "題", MD, "  "), "")

    def test_contains_the_instruction_the_topic_the_title_and_the_digest(self) -> None:
        text = tf.build_requirements("", "参考画像に近いエネルギー", "3層の光", MD, "光を青にして、粒を倍にする")
        self.assertIn("【続きの生成】", text)
        self.assertIn("「3層の光」", text)
        self.assertIn("題材: 参考画像に近いエネルギー", text)
        self.assertIn("追加指示: 光を青にして、粒を倍にする", text)
        self.assertIn("章2 比べる", text)

    def test_the_original_requirements_come_first(self) -> None:
        text = tf.build_requirements("Scatter を必ず使う", "炎", "題", MD, "青く")
        self.assertTrue(text.startswith("Scatter を必ず使う\n\n【続きの生成】"))

    def test_title_falls_back_to_the_topic(self) -> None:
        self.assertIn("「炎」", tf.build_requirements("", "炎", "", MD, "青く"))

    def test_a_missing_digest_is_said_so(self) -> None:
        self.assertIn("要点を取り出せませんでした", tf.build_requirements("", "炎", "題", "", "青く"))


if __name__ == "__main__":
    unittest.main()
