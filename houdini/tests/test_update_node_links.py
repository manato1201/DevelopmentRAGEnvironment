"""houdini/update_node_links.py（公式の一覧から node_link_data.py を作り直す開発者用の道具）の検査。ネットワークは使わない。

公式サイトの文字を、そのまま Python のソースに書き出す（Houdini の中で動くコードになる）ので、
変な文字（引用符・バックスラッシュ・改行）を含む名前が来ても、ソースが壊れたり、コードが混ざったりしないことを確かめる。

実行（リポジトリのルートで）:  uv run python -m unittest houdini.tests.test_update_node_links -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update_node_links as unl  # noqa: E402


def empty() -> dict[str, dict[str, str]]:
    return {context: {} for context in unl.CONTEXTS}


class ParseTest(unittest.TestCase):
    def test_only_pages_of_the_same_chapter_are_taken(self) -> None:
        page = (
            '<a class="label-text node" href="scatter.html">Scatter</a>'
            '<a class="label-text node" href="../sop/merge.html">Merge</a>'
            '<a class="label-text node" href="https://evil.example/x.html">X</a>'
            '<a class="label-text node" href="notes.txt">Notes</a>'
            '<a class="label-text node" href="a--b.html">Tom &amp; Jerry</a>'
        )
        self.assertEqual(
            unl.parse_index(page), {"scatter": "Scatter", "a--b": "Tom & Jerry"}
        )


class RenderTest(unittest.TestCase):
    def load(self, source: str) -> dict:
        namespace: dict = {}
        exec(compile(source, "node_link_data.py", "exec"), namespace)  # noqa: S102 -- 検査のため、書き出したソースを読み込む
        return namespace

    def test_the_output_is_a_module_that_round_trips(self) -> None:
        data = empty()
        data["sop"] = {"scatter": "Scatter", "attribwrangle": "Attribute Wrangle"}
        data["out"] = {"geometry": "Geometry"}
        namespace = self.load(unl.render(data, "2026-11-17"))
        self.assertEqual(namespace["CHECKED_ON"], "2026-11-17")
        self.assertEqual(
            set(namespace["NODES"]["sop"].splitlines()),
            {"scatter|Scatter", "attribwrangle|Attribute Wrangle"},
        )

    def test_odd_names_cannot_break_the_source_or_add_code(self) -> None:
        data = empty()
        data["sop"] = {
            "ok": "OK Node",
            "evil": 'x"""\nimport os\nos.system("calc")\n"""',
            "back": "ends with backslash\\",
            "line": "two\nlines",
            "bad/slug": "Slash",
            "": "No slug",
        }
        source = unl.render(data, "2026-11-17")
        namespace = self.load(source)  # 構文エラーにならない
        self.assertEqual(namespace["NODES"]["sop"].splitlines(), ["ok|OK Node"])
        self.assertNotIn("os.system", source)


if __name__ == "__main__":
    unittest.main()
