"""node_links（回答の中の URL とノード名を、リンクにする）の検査。標準の unittest。Qt・Houdini・ネットワークは要らない。

2026-11-17 の実証実験の要望: チャットの回答の外部 URL をリンクにする／ノードについて聞いたら、公式ドキュメントへのリンクを出す。
ノードのページは、公式の一覧（node_link_data.py。houdini/update_node_links.py で作り直す）に載っているものだけをリンクにする。

実行（リポジトリのルートで）:  uv run python -m unittest houdini.tests.test_node_links -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import node_link_data as data  # noqa: E402
import node_links as nl  # noqa: E402

DOC = "https://www.sidefx.com/docs/houdini/nodes"


class SafeUrlTest(unittest.TestCase):
    def test_http_and_https_are_safe(self) -> None:
        for url in ("http://a.example/", "https://www.sidefx.com/docs/houdini/nodes/sop/scatter.html", "HTTPS://A.EXAMPLE/x?y=1#z"):
            self.assertTrue(nl.is_safe_url(url), url)

    def test_dangerous_schemes_are_not(self) -> None:
        for url in ("javascript:alert(1)", "JavaScript:alert(1)", "file:///C:/Windows/win.ini", "data:text/html,<b>x</b>",
                    "vbscript:x", "ftp://a.example/x", "mailto:a@example.com", "//a.example/x", "a.example/x", ""):
            self.assertFalse(nl.is_safe_url(url), url)

    def test_odd_urls_are_not(self) -> None:
        for url in ("https://", "https:///x", "https://a.example/x y", "https://a.example/\nx", "https://www.sidefx.com@evil.example/",
                    "https://" + "a" * 3000, None, 5):
            self.assertFalse(nl.is_safe_url(url), repr(url)[:40])

    def test_direction_control_characters_and_bad_ports_are_not_safe(self) -> None:
        # 右から左に並べ替える制御文字などで、表示の URL と、実際の行き先を、ずらせてしまう。ポートが数でないものも、使えない
        for url in ("https://a.example/‮exe.txt", "https://‮a.example/", "https://a.example/​x", "https://a.example /",
                    "https://a.example:99999/", "https://a.example:abc/"):
            self.assertFalse(nl.is_safe_url(url), repr(url))

    def test_linkify_does_not_link_a_markdown_url_with_control_characters(self) -> None:
        out = nl.linkify_html("[b](https://a.example/‮x) https://a.example:99999/")
        self.assertNotIn("<a ", out)


class LinkifyTest(unittest.TestCase):
    def test_a_url_becomes_a_link(self) -> None:
        out = nl.linkify_html("詳しくは https://www.sidefx.com/docs/houdini/ を見てください")
        self.assertIn('<a href="https://www.sidefx.com/docs/houdini/">', out)
        self.assertIn(">https://www.sidefx.com/docs/houdini/</span></a>", out)
        self.assertTrue(out.endswith("を見てください"))

    def test_japanese_punctuation_and_trailing_marks_are_not_part_of_the_url(self) -> None:
        cases = {
            "https://a.example/x。次": "https://a.example/x",
            "(https://a.example/x)です": "https://a.example/x",
            "「https://a.example/x」": "https://a.example/x",
            "see https://a.example/x, and": "https://a.example/x",
            "see https://a.example/x.": "https://a.example/x",
            "https://a.example/x?q=1&r=2": "https://a.example/x?q=1&r=2",
            "https://en.example/Foo_(bar)": "https://en.example/Foo_(bar)",
        }
        for text, url in cases.items():
            out = nl.linkify_html(text)
            self.assertIn(f'<a href="{url.replace("&", "&amp;")}">', out, text)

    def test_unsafe_schemes_are_never_links(self) -> None:
        for text in ("[click](javascript:alert(1))", "javascript:alert(1)", "[x](file:///C:/a)", "<a href='javascript:x'>y</a>"):
            out = nl.linkify_html(text)
            self.assertNotIn("<a ", out, text)
            self.assertNotIn("<", out, "リンクにならなかった分は、すべて文字として出る（タグにならない）")

    def test_html_in_the_answer_is_escaped(self) -> None:
        out = nl.linkify_html('<script>alert(1)</script> <b>x</b> "q" & https://a.example/?a=1&b=2')
        self.assertNotIn("<script>", out)
        self.assertNotIn("<b>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&amp;", out)

    def test_a_markdown_link_shows_the_real_host(self) -> None:
        out = nl.linkify_html("[公式ドキュメント](https://evil.example/x)")
        self.assertIn('<a href="https://evil.example/x">', out)
        self.assertIn(">公式ドキュメント</span></a>", out)
        self.assertIn("evil.example", out.split("</a>")[1], "見せかけに気づけるよう、ホスト名を添える")

    def test_newlines_are_kept_and_plain_text_is_unchanged(self) -> None:
        self.assertEqual(nl.linkify_html("1行目\n2行目"), "1行目<br>2行目")
        self.assertEqual(nl.linkify_html(""), "")
        self.assertEqual(nl.linkify_html(None), "")

    def test_a_quote_in_a_url_cannot_break_out_of_the_attribute(self) -> None:
        out = nl.linkify_html('https://a.example/x"onmouseover="alert(1)')
        self.assertNotIn('onmouseover="', out)


class DataTest(unittest.TestCase):
    """node_link_data.py（公式の一覧から作ったデータ）の形。"""

    def test_every_context_is_known_and_every_line_is_well_formed(self) -> None:
        self.assertEqual(set(data.NODES), set(nl.CONTEXT_ORDER))
        slug = re.compile(r"^[A-Za-z0-9_.\-]+$")
        total = 0
        for context, block in data.NODES.items():
            for line in block.splitlines():
                page, sep, title = line.partition("|")
                self.assertEqual(sep, "|", line)
                self.assertRegex(page, slug, f"{context}: {line}")
                self.assertTrue(title.strip(), line)
                total += 1
        self.assertGreater(total, 3000)

    def test_known_pages_exist_in_the_data(self) -> None:
        """実在を確認したページ（2026-11-17 に、公式サイトへ HEAD で HTTP 200 を確認）。"""
        for name, url in {
            "Attribute Wrangle": f"{DOC}/sop/attribwrangle.html",
            "Pyro Solver": f"{DOC}/sop/pyrosolver.html",
            "Scatter": f"{DOC}/sop/scatter.html",
            "Rig Pose": f"{DOC}/sop/kinefx--rigpose.html",
            "Pyro Solver (Sparse)": f"{DOC}/dop/pyrosolver_sparse.html",
        }.items():
            hit = nl.lookup(name)
            self.assertIsNotNone(hit, name)
            self.assertEqual(hit["url"], url, name)


class LookupTest(unittest.TestCase):
    def test_by_display_name_page_name_and_namespaced_name(self) -> None:
        self.assertEqual(nl.lookup("Pyro Solver")["url"], f"{DOC}/sop/pyrosolver.html")
        self.assertEqual(nl.lookup("pyro  solver")["url"], f"{DOC}/sop/pyrosolver.html")
        self.assertEqual(nl.lookup("attribwrangle")["url"], f"{DOC}/sop/attribwrangle.html")
        self.assertEqual(nl.lookup("kinefx::rigpose")["url"], f"{DOC}/sop/kinefx--rigpose.html")

    def test_context_is_preferred_when_given(self) -> None:
        self.assertEqual(nl.lookup("Merge")["context"], "sop")
        self.assertEqual(nl.lookup("Merge", "dop")["context"], "dop")
        self.assertEqual(nl.lookup("Merge", "dop")["url"], f"{DOC}/dop/merge.html")

    def test_unknown_names_are_not_guessed(self) -> None:
        for name in ("Tornado Maker 3000", "", "   ", "nothingxyz"):
            self.assertIsNone(nl.lookup(name), name)


class FindNodeLinksTest(unittest.TestCase):
    def docs(self, text: str) -> list[str]:
        return [link["url"] for link in nl.find_node_links(text) if link["kind"] == "doc"]

    def test_multi_word_names_in_an_answer(self) -> None:
        urls = self.docs("Pyro Solver で煙を作り、Attribute Wrangle で速度を足します。")
        self.assertEqual(urls, [f"{DOC}/sop/pyrosolver.html", f"{DOC}/sop/attribwrangle.html"])

    def test_order_of_appearance_and_no_duplicates(self) -> None:
        urls = self.docs("Attribute Wrangle を置く。次に Pyro Solver。もう一度 Attribute Wrangle。")
        self.assertEqual(urls, [f"{DOC}/sop/attribwrangle.html", f"{DOC}/sop/pyrosolver.html"])

    def test_single_words_need_a_node_mark(self) -> None:
        """Group・Merge・Null などは、ふつうの英単語と同じ。「ノード」などの印があるときだけ、ノード名とみなす。"""
        self.assertEqual(self.docs("Group を作る。Merge して Null で終える。"), [])
        self.assertEqual(self.docs("Scatter ノードで点を散らす"), [f"{DOC}/sop/scatter.html"])
        self.assertEqual(self.docs("`Scatter` で散らす"), [f"{DOC}/sop/scatter.html"])
        self.assertEqual(self.docs("「Scatter」で散らす"), [f"{DOC}/sop/scatter.html"])
        self.assertEqual(self.docs("the Scatter node scatters points"), [f"{DOC}/sop/scatter.html"])

    def test_page_names_in_backticks(self) -> None:
        urls = self.docs("`attribwrangle` と `kinefx::rigpose` を使います")
        self.assertEqual(urls, [f"{DOC}/sop/attribwrangle.html", f"{DOC}/sop/kinefx--rigpose.html"])

    def test_same_name_in_several_contexts_follows_the_text(self) -> None:
        self.assertEqual(self.docs("Merge ノード(SOP) を使う"), [f"{DOC}/sop/merge.html"])
        self.assertEqual(self.docs("Merge ノード (DOP) を使う"), [f"{DOC}/dop/merge.html"])
        self.assertEqual(self.docs("DOP の Merge ノードを使う"), [f"{DOC}/dop/merge.html"])
        self.assertEqual(self.docs("DOP ネットワークで Merge ノードを使う。DOP では…"), [f"{DOC}/dop/merge.html"])
        self.assertEqual(self.docs("Merge ノードを使う"), [f"{DOC}/sop/merge.html"], "手がかりが無いときは SOP")

    def test_names_with_parentheses_and_hyphens(self) -> None:
        self.assertEqual(self.docs("Pyro Solver (Sparse) を使う"), [f"{DOC}/dop/pyrosolver_sparse.html"])
        self.assertEqual(self.docs("Pyro Post-Process を使う"), [f"{DOC}/sop/pyropostprocess.html"])

    def test_unknown_node_becomes_a_search_link_not_a_guessed_page(self) -> None:
        links = nl.find_node_links("Tornado Maker ノードで竜巻を作る")
        self.assertEqual([link["kind"] for link in links], ["search"])
        self.assertEqual(links[0]["url"], "https://www.sidefx.com/search/?q=Tornado%20Maker")
        self.assertNotIn("nodes/", links[0]["url"])

    def test_generic_words_are_not_searched(self) -> None:
        self.assertEqual(nl.find_node_links("Houdini ノードと SOP ノードの違い。HDA ノードや VEX ノード。"), [])

    def test_no_nodes_no_links(self) -> None:
        self.assertEqual(nl.find_node_links("今日はいい天気です。"), [])
        self.assertEqual(nl.find_node_links(""), [])
        self.assertEqual(nl.find_node_links(None), [])

    def test_limits(self) -> None:
        names = [line.split("|", 1)[1] for line in data.NODES["sop"].splitlines() if line.count(" ") == 1 and "|" in line][:40]
        text = "、".join(names)
        self.assertLessEqual(len([link for link in nl.find_node_links(text) if link["kind"] == "doc"]), nl.MAX_DOC_LINKS)
        searches = nl.find_node_links("Aaa Bbb ノード、Ccc Ddd ノード、Eee Fff ノード、Ggg Hhh ノード、Iii Jjj ノード")
        self.assertLessEqual(len(searches), nl.MAX_SEARCH_LINKS)

    def test_every_link_is_safe(self) -> None:
        text = "Pyro Solver、Attribute Wrangle、Tornado Maker ノード、`attribwrangle`"
        for link in nl.find_node_links(text):
            self.assertTrue(nl.is_safe_url(link["url"]), link)


class LinkRowTest(unittest.TestCase):
    def test_row_has_docs_and_searches_in_separate_groups(self) -> None:
        links = nl.find_node_links("Pyro Solver と Tornado Maker ノード")
        out = nl.node_links_html(links)
        self.assertIn("公式ドキュメント", out)
        self.assertIn('href="https://www.sidefx.com/docs/houdini/nodes/sop/pyrosolver.html"', out)
        self.assertIn("検索", out)
        self.assertIn("https://www.sidefx.com/search/?q=Tornado%20Maker", out)

    def test_empty_when_there_is_nothing(self) -> None:
        self.assertEqual(nl.node_links_html([]), "")

    def test_unsafe_links_are_dropped(self) -> None:
        out = nl.node_links_html([{"kind": "doc", "name": "x", "label": "x", "url": "javascript:alert(1)"}])
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
