"""panel_info.py（出典と採用比率・ユーザー表示の文面。Qt に依存しない）のテスト。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import panel_info as pi  # noqa: E402


def src(file, cited, count=0, ns="shared:houdini22"):
    return {"file": file, "namespace": ns, "cited": cited, "citationCount": count}


class SummarizeSourcesTest(unittest.TestCase):
    def test_used_and_unused_with_ratio(self):
        info = pi.summarize_sources([src("a.md", True, 2), src("b.md", True, 1), src("c.md", False), src("d.md", False), src("e.md", False)])
        self.assertEqual(info["state"], "cited")
        self.assertEqual((info["used"], info["total"]), (2, 5))
        self.assertIn("回答で使った資料 2件", info["summary"])
        self.assertIn("採用 40%", info["summary"])
        self.assertIn("[1] a.md（houdini22・引用2回）", info["html"])
        self.assertIn("[2] b.md（houdini22）", info["html"], "a single citation is not annotated")
        self.assertIn("回答では使わなかった資料: [3] c.md ／ [4] d.md ／ [5] e.md", info["html"])
        self.assertNotIn("shared:", info["html"])

    def test_no_citation_is_a_warning(self):
        info = pi.summarize_sources([src("a.md", False), src("b.md", False)])
        self.assertEqual(info["state"], "none")
        self.assertIn("引用がありません", info["summary"])
        self.assertIn("出典を示さずに答えている可能性", info["html"])
        self.assertIn("[1] a.md", info["html"])

    def test_local_bridge_has_no_citation_info(self):
        info = pi.summarize_sources([{"title": "ガイド"}, {"title": "メモ"}])
        self.assertEqual(info["state"], "plain")
        self.assertEqual(info["summary"], "参照した資料: 2件")
        self.assertNotIn("%", info["summary"], "no ratio without citation info")
        self.assertIn("[2] メモ", info["html"])

    def test_empty_and_personal_namespace_and_many_unused(self):
        self.assertEqual(pi.summarize_sources([])["state"], "empty")
        self.assertEqual(pi.summarize_sources(None)["summary"], "")
        self.assertIn("自分用", pi.summarize_sources([src("m.md", True, 1, "personal:abc")])["html"])
        many = pi.summarize_sources([src("u.md", True, 1)] + [src(f"x{i}.md", False) for i in range(7)])
        self.assertIn("ほか2件", many["html"])

    def test_file_names_are_escaped(self):
        info = pi.summarize_sources([src("<img src=x onerror=1>.md", True, 1)])
        self.assertNotIn("<img", info["html"])
        self.assertIn("&lt;img", info["html"])


class FormatUserTest(unittest.TestCase):
    def test_roles_and_states(self):
        shown = pi.format_user({"displayName": "田中", "role": "admin", "userIdShort": "ab12cd"})
        self.assertEqual(shown["text"], "ユーザー: 田中（管理者）")
        self.assertIn("ab12cd", shown["tooltip"])
        self.assertEqual(shown["role"], "admin")
        self.assertEqual(pi.format_user({"displayName": "", "role": "member"})["text"], "ユーザー: （名前なし）（一般ユーザー）")
        self.assertEqual(pi.format_user(None)["text"], "ユーザー: 未確認")
        self.assertIn("認証できません", pi.format_user({"error": "HTTP Error 401"})["text"])
        self.assertIn("ローカル", pi.format_user(None, "local")["text"])


if __name__ == "__main__":
    unittest.main()
