"""houdini_tools.normalize_escaped_newlines: 手順の本文の「バックスラッシュ + n」を、本当の改行に直す（2026-11-18）。

実機の記録（energy-effect-layer-design_20261118.md）で、手順の本文が 1 行のままで、「バックスラッシュ + n」が
119 個、そのまま出ていた。モデルが、改行を二重にエスケープして送ったため。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_escaped_newlines.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))

import houdini_tools as ht  # noqa: E402
from test_parm_tools import make_executor, make_world  # noqa: E402

BS = chr(92)  # バックスラッシュ
LIT = BS + "n"  # 2 文字の「改行」


class NormalizeTest(unittest.TestCase):
    def test_a_single_line_with_many_escaped_newlines_is_split(self) -> None:
        text = "### 章1" + LIT + "- 黒背景" + LIT + "- 光の粒" + LIT + "```" + LIT + "i@layer = 0;" + LIT + "```"
        out = ht.normalize_escaped_newlines(text)
        self.assertEqual(out.splitlines(), ["### 章1", "- 黒背景", "- 光の粒", "```", "i@layer = 0;", "```"])
        self.assertNotIn(BS, out)

    def test_real_text_is_left_alone(self) -> None:
        text = "### 章1\n- 黒背景\n- 光の粒\n"
        self.assertEqual(ht.normalize_escaped_newlines(text), text)

    def test_a_few_escapes_inside_real_text_are_code_and_stay(self) -> None:
        text = "\n".join(["手順", "```", 'printf("a' + LIT + '");', 'printf("b' + LIT + '");', 'printf("c' + LIT + '");', "```", "終わり"])
        self.assertEqual(ht.normalize_escaped_newlines(text), text)

    def test_fewer_than_three_escapes_are_left_alone(self) -> None:
        text = "1行目" + LIT + "2行目" + LIT + "3行目"
        self.assertEqual(ht.normalize_escaped_newlines(text), text)

    def test_non_strings_and_empty_are_returned_as_is(self) -> None:
        self.assertEqual(ht.normalize_escaped_newlines(""), "")
        self.assertIsNone(ht.normalize_escaped_newlines(None))
        self.assertEqual(ht.normalize_escaped_newlines(12), 12)


class FinishTutorialTest(unittest.TestCase):
    def test_the_draft_kept_by_finish_tutorial_has_real_newlines(self) -> None:
        hou, sandbox, add, nodes = make_world()
        ex = make_executor(hou, sandbox)
        ex._finish_drafts, ex._pending_finish, ex.step_log, ex.topic, ex.requirements = [], None, [], "", ""
        steps = "### 章1" + LIT + "a" + LIT + "b" + LIT + "c"
        ex._tool_finish_tutorial({"title": "t", "slug": "t", "overview": "o", "steps": steps, "pitfalls": "p" + LIT + "q" + LIT + "r" + LIT + "s", "n": 3})
        draft = ex.pending_finish
        self.assertEqual(draft["steps"].splitlines(), ["### 章1", "a", "b", "c"])
        self.assertEqual(draft["pitfalls"].splitlines(), ["p", "q", "r", "s"])
        self.assertEqual(draft["n"], 3)  # 文字でないものは、そのまま


if __name__ == "__main__":
    unittest.main()
