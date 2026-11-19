"""ci_check_namespaces.py の検査(違反を、実際に検知して失敗にできること)。

2026-11-19: localRAG/ は gitignore 済みで、CI の checkout には無い。検査は「見つかりません(スキップ)」で成功を返すだけになり、
違反を検知できるかどうかを、CI は何も確かめていなかった。一時フォルダに localRAG/ を再現して、検知の論理そのものを検査する。
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import ci_check_namespaces as chk  # noqa: E402
from auto_index import NAMESPACES  # noqa: E402


def run(vault: Path) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = chk.main(vault)
    return code, buf.getvalue()


class NamespaceCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        # Windows では、一時フォルダの後片付けで失敗することがあるので、無視する
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.vault = Path(self._tmp.name) / "localRAG"
        self.vault.mkdir()

    def test_only_known_namespaces_pass(self) -> None:
        for name in NAMESPACES:
            (self.vault / name).mkdir()
        code, out = run(self.vault)
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)

    def test_an_unknown_namespace_folder_fails(self) -> None:
        (self.vault / "bogus_ns").mkdir()
        code, out = run(self.vault)
        self.assertEqual(code, 1)
        self.assertIn("bogus_ns", out)  # どのフォルダが違反かを、出力で示す

    def test_a_markdown_file_directly_under_the_vault_fails(self) -> None:
        # 'default' namespace に混ざる抜け道(governance の対象外になる)
        (self.vault / "stray.md").write_text("# メモ", encoding="utf-8")
        code, out = run(self.vault)
        self.assertEqual(code, 1)
        self.assertIn("stray.md", out)

    def test_hidden_and_underscore_entries_are_ignored(self) -> None:
        (self.vault / "_backup").mkdir()
        (self.vault / ".obsidian").mkdir()
        code, _ = run(self.vault)
        self.assertEqual(code, 0)

    def test_non_markdown_files_are_ignored(self) -> None:
        (self.vault / "note.txt").write_text("x", encoding="utf-8")
        code, _ = run(self.vault)
        self.assertEqual(code, 0)

    def test_both_kinds_of_violation_are_reported_together(self) -> None:
        (self.vault / "bogus_ns").mkdir()
        (self.vault / "stray.md").write_text("x", encoding="utf-8")
        code, out = run(self.vault)
        self.assertEqual(code, 1)
        self.assertIn("bogus_ns", out)
        self.assertIn("stray.md", out)

    def test_a_missing_vault_is_skipped_not_failed(self) -> None:
        # CI の環境(localRAG/ が無い)では、スキップして成功になる。この挙動は、意図して残している
        code, out = run(Path(self._tmp.name) / "no_such_dir")
        self.assertEqual(code, 0)
        self.assertIn("スキップ", out)


if __name__ == "__main__":
    unittest.main()
