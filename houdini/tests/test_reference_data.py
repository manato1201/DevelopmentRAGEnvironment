"""reference_data（リファレンスタブのデータと文章）のテスト（2026-11-19）。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_reference_data.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import reference_data as rd  # noqa: E402


class CatalogTest(unittest.TestCase):
    def test_kinds_and_sizes(self) -> None:
        self.assertEqual([k for k, _ in rd.KINDS], ["node", "vex", "apex", "shelf"])
        self.assertGreater(len(rd.catalog("node")), 1000)
        self.assertGreater(len(rd.catalog("apex")), 50)
        self.assertGreaterEqual(len(rd.catalog("vex")), 80)
        self.assertEqual(rd.catalog("shelf"), [])  # シェルフツールは、Houdini の中で登録される（set_shelf_tools）
        self.assertEqual(rd.catalog("nonsense"), [])

    def test_node_catalog_has_no_apex_and_apex_catalog_only_apex(self) -> None:
        self.assertFalse(any(i["context"] == "apex" for i in rd.catalog("node")))
        self.assertTrue(all(i["kind"] == "apex" and i["context"] == "apex" for i in rd.catalog("apex")))

    def test_items_have_a_key_a_label_and_an_official_doc_url(self) -> None:
        for kind in ("node", "vex", "apex"):
            for item in rd.catalog(kind)[:50]:
                self.assertTrue(item["key"].startswith(item["context"] + "/") or kind == "vex")
                self.assertTrue(item["label"])
                self.assertTrue(item["doc_url"].startswith("https://www.sidefx.com/docs/houdini/"))

    def test_private_pages_are_not_listed(self) -> None:
        self.assertFalse(any(i["name"].startswith("_") for i in rd.catalog("node")))

    def test_keys_are_unique(self) -> None:
        for kind in ("node", "vex", "apex"):
            keys = [i["key"] for i in rd.catalog(kind)]
            self.assertEqual(len(keys), len(set(keys)), kind)


class SearchTest(unittest.TestCase):
    def test_exact_match_comes_first(self) -> None:
        self.assertEqual(rd.search("node", "scatter")[0]["key"], "sop/scatter")
        self.assertEqual(rd.search("node", "merge")[0]["key"], "sop/merge")
        self.assertEqual(rd.search("vex", "chf")[0]["key"], "vex/chf")

    def test_case_and_spaces_are_ignored(self) -> None:
        self.assertEqual(rd.search("node", "  SCATTER ")[0]["key"], "sop/scatter")

    def test_empty_query_returns_the_head_of_the_list_within_the_limit(self) -> None:
        self.assertEqual(len(rd.search("node", "", limit=7)), 7)

    def test_no_hit(self) -> None:
        self.assertEqual(rd.search("node", "zzzzqqq"), [])

    def test_find_item(self) -> None:
        self.assertEqual(rd.find_item("node", "sop/scatter")["label"], "Scatter")
        self.assertIsNone(rd.find_item("node", "sop/zzz"))

    def test_custom_item_for_a_shelf_tool(self) -> None:
        item = rd.custom_item("shelf", "  Billowy   Smoke ")
        self.assertEqual(item["name"], "Billowy Smoke")
        self.assertEqual(item["kind"], "shelf")
        self.assertTrue(item["custom"])
        self.assertIn("Billowy%20Smoke", item["doc_url"])
        self.assertEqual(item["key"], "shelf/billowy_smoke")


class UsedItemsTest(unittest.TestCase):
    GUIDE = {"steps": [
        {"tool": "create_node", "node": "scatter1", "node_type": "scatter::2.0"},
        {"tool": "create_node", "node": "wr", "node_type": "attribwrangle"},
        {"tool": "set_parameter", "node": "wr", "node_type": "attribwrangle",
         "parms": [{"name": "snippet", "new": "f@a = chf(\"x\");\nv@Cd = set(1, 0, 0) * rand(@ptnum);"}]},
        {"tool": "set_parameter", "node": "s", "node_type": "scatter::2.0", "parms": [{"name": "npts", "new": "300"}]},
        {"tool": "create_node", "node": "ap", "node_type": "apex::Acos"},
        {"tool": "create_node", "node": "u", "node_type": "unknownnode9"},
    ]}

    def test_node_and_vex_are_found(self) -> None:
        used = rd.used_items(self.GUIDE)
        self.assertIn("sop/scatter", used["node"])
        self.assertIn("sop/attribwrangle", used["node"])
        self.assertTrue({"vex/chf", "vex/set", "vex/rand"} <= used["vex"])

    def test_a_plain_value_is_not_scanned_for_functions(self) -> None:
        used = rd.used_items({"steps": [{"tool": "set_parameter", "parms": [{"name": "x", "new": "rand(3)"}]}]})
        self.assertEqual(used["vex"], set())  # コードの欄（改行・; を含む）だけを見る

    def test_unknown_types_and_bad_data_are_ignored(self) -> None:
        used = rd.used_items(self.GUIDE)
        self.assertFalse(any("unknownnode9" in k for k in used["node"]))
        for bad in (None, {}, {"steps": None}, {"steps": ["x", None, 3]}, "text"):
            self.assertEqual(rd.used_items(bad), {k: set() for k, _ in rd.KINDS})


class ReferenceItemsTest(unittest.TestCase):
    ITEMS = [
        {"title": "VEX xyzdist: distance to a primitive", "excerpt": "How xyzdist works", "tags": ["Forum", "VEX"], "published": "2026-11-10T00:00:00Z", "source": "SideFX Forum", "url": "https://example.com/a"},
        {"title": "Vellum201 - Custom Constraints", "excerpt": "uses xyzdist in a wrangle", "tags": ["YouTube", "VEX"], "published": "2026-11-18T00:00:00Z", "source": "Entagma", "url": "javascript:alert(1)"},
        {"title": "Unrelated news", "excerpt": "nothing", "tags": ["Release notes"], "published": "2026-11-19T00:00:00Z"},
        "not a dict",
    ]

    def test_title_matches_beat_excerpt_matches(self) -> None:
        hits = rd.match_reference_items(self.ITEMS, "xyzdist", "vex")
        self.assertEqual([h["source"] for h in hits], ["SideFX Forum", "Entagma"])

    def test_short_or_empty_names_match_nothing(self) -> None:
        self.assertEqual(rd.match_reference_items(self.ITEMS, "ab", "vex"), [])
        self.assertEqual(rd.match_reference_items(self.ITEMS, "", "node"), [])

    def test_limit(self) -> None:
        many = [{"title": f"xyzdist tip {i}", "published": f"2026-11-{10 + i:02d}"} for i in range(10)]
        self.assertEqual(len(rd.match_reference_items(many, "xyzdist", "vex")), rd.MAX_REFERENCE_ITEMS)

    def test_none_items(self) -> None:
        self.assertEqual(rd.match_reference_items(None, "scatter", "node"), [])


class PromptAndParseTest(unittest.TestCase):
    def test_prompt_contains_the_item_docs_and_references_and_bounds_the_docs(self) -> None:
        system, user = rd.build_prompt("node", "Scatter", ["a" * 5000, "b" * 1400, "c" * 1400, "d" * 1400, "e" * 1400], [{"title": "t", "excerpt": "x" * 400}])
        self.assertIn("JSON", system)
        self.assertIn("項目: Scatter（ノード）", user)
        self.assertLess(len(user), 7500)
        self.assertNotIn("a" * 1501, user)

    def test_prompt_without_docs_says_so(self) -> None:
        _s, user = rd.build_prompt("vex", "chf", [], [])
        self.assertIn("資料が見つかりませんでした", user)
        self.assertIn("（なし）", user)

    def test_parse_a_clean_json(self) -> None:
        entry = rd.parse_entry('{"what": "点を散らす", "use": "植生", "example": "", "example_point": "", "when": "密度を決めるとき"}')
        self.assertEqual(entry["what"], "点を散らす")
        self.assertEqual(entry["when"], "密度を決めるとき")

    def test_parse_json_with_surrounding_text_and_fences(self) -> None:
        entry = rd.parse_entry('結果です\n```json\n{"what": "A", "use": "B"}\n```')
        self.assertEqual((entry["what"], entry["use"]), ("A", "B"))

    def test_parse_rejects_garbage_and_empty_entries(self) -> None:
        for bad in ("", "no json", "{not json}", "[]", '{"what": "", "use": ""}', None):
            self.assertIsNone(rd.parse_entry(bad))

    def test_fields_are_clipped_and_whitespace_normalized(self) -> None:
        entry = rd.parse_entry(json.dumps({"what": "あ" * 2000, "use": "a\n b   c"}))
        self.assertEqual(len(entry["what"]), rd.MAX_FIELD_CHARS)
        self.assertEqual(entry["use"], "a b c")


class CacheTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(rd.load_entry(d, "node", "sop/scatter"))
            self.assertTrue(rd.save_entry(d, "node", "sop/scatter", {"what": "散らす", "use": "植生"}, {"model": "m", "generated_at": "2026-11-19"}))
            loaded = rd.load_entry(d, "node", "sop/scatter")
            self.assertEqual(loaded["what"], "散らす")
            self.assertEqual(loaded["model"], "m")
            self.assertTrue(rd.entry_path(d, "node", "sop/scatter").is_relative_to(Path(d) / "localRAG" / "reference"))

    def test_hostile_keys_stay_inside_the_folder(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for key in ("../../evil", "..\\..\\evil", "/etc/passwd", "a/../../b"):
                path = rd.entry_path(d, "node", key)
                self.assertTrue(path.resolve().is_relative_to((Path(d) / "localRAG" / "reference").resolve()), key)

    def test_broken_or_empty_cache_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = rd.entry_path(d, "vex", "vex/chf")
            path.parent.mkdir(parents=True)
            path.write_text("{broken", encoding="utf-8")
            self.assertIsNone(rd.load_entry(d, "vex", "vex/chf"))
            path.write_text(json.dumps({"what": "", "use": ""}), encoding="utf-8")
            self.assertIsNone(rd.load_entry(d, "vex", "vex/chf"))

    def test_save_fails_quietly_when_the_folder_cannot_be_made(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            blocker = Path(d) / "localRAG"
            blocker.write_text("a file, not a folder", encoding="utf-8")
            self.assertFalse(rd.save_entry(d, "node", "sop/scatter", {"what": "x"}))


class HtmlTest(unittest.TestCase):
    ITEM = {"kind": "node", "key": "sop/scatter", "name": "scatter", "label": "Scatter", "context": "sop"}

    def test_sections_are_shown_in_order_and_empty_ones_are_skipped(self) -> None:
        text = rd.entry_html(self.ITEM, {"what": "点を散らす", "use": "", "when": "密度を決める"})
        self.assertLess(text.index("何をする・どんなもの"), text.index("使いどころ"))
        self.assertNotIn("どういったものに使うか", text)
        self.assertNotIn("今後追加", text)

    def test_text_is_escaped(self) -> None:
        text = rd.entry_html({**self.ITEM, "label": "<script>x</script>"}, {"what": "<img src=x onerror=alert(1)>"})
        self.assertNotIn("<script>", text)
        self.assertNotIn("<img", text)
        self.assertIn("&lt;img", text)

    def test_no_entry_asks_a_developer_to_create_one_and_tells_a_participant_it_is_not_ready(self) -> None:
        developer = rd.entry_html(self.ITEM, None, author=True)
        self.assertIn("説明を作る", developer)
        self.assertIn("トークン", developer)  # 作る前に、AI を呼ぶ費用を伝える
        participant = rd.entry_html(self.ITEM, None)
        self.assertNotIn("説明を作る", participant)
        self.assertIn("まだ用意していません", participant)
        self.assertIn("読み込んでいます", rd.entry_html(self.ITEM, None, loading=True))

    def test_media_html_places_before_after_and_node_images(self) -> None:
        media = [{"id": "a/before.png", "role": "before"}, {"id": "a/after.png", "role": "after"}, {"id": "a/node.png", "role": "node"},
                 {"id": "a/clip.gif", "role": "clip"}, {"id": "a/lost.png", "role": "after"}]
        sources = {"a/before.png": "refmedia:a/before.png", "a/after.png": "refmedia:a/after.png", "a/node.png": "refmedia:a/node.png", "a/clip.gif": "refmedia:a/clip.gif"}
        text = rd.media_html(media, sources)
        self.assertLess(text.index("適用前"), text.index("適用後"))
        self.assertIn("ノード画面", text)
        self.assertIn("refmedia:a/before.png", text)
        self.assertNotIn("clip.gif", text)  # 動きは、画面側が別に出す
        self.assertEqual(rd.media_html([{"id": "x.png", "role": "after"}], {}), "", "an image that could not be loaded is skipped")
        self.assertEqual(rd.media_html(None, None), "")
        html = rd.entry_html(self.ITEM, {"what": "x"}, media=text)
        self.assertLess(html.index("適用前"), html.index("何をする"))

    def test_remote_items_adds_published_items_missing_from_the_catalog(self) -> None:
        remote = {"node|sop/mountain": {"kind": "node", "key": "sop/mountain", "title": "Mountain", "version": 1},
                  "node|sop/scatter": {"kind": "node", "key": "sop/scatter", "title": "Scatter", "version": 1},
                  "vex|vex/chf": {"kind": "vex", "key": "vex/chf", "title": "chf", "version": 1}, "bad": 3}
        extra = rd.remote_items("node", remote)
        self.assertEqual([i["key"] for i in extra], ["sop/mountain"], "scatter is already in the catalog; other kinds are not mixed in")
        self.assertEqual((extra[0]["label"], extra[0]["context"]), ("Mountain", "sop"))
        self.assertTrue(extra[0]["doc_url"].endswith("/nodes/sop/mountain.html"))
        self.assertEqual(rd.search("node", "mountain", extra=extra)[0]["key"], "sop/mountain")
        self.assertEqual(rd.search("node", "mountain"), [], "without extra the catalog does not know it")
        self.assertEqual(rd.remote_items("node", None), [])

    def test_shelf_items_use_the_internal_name_as_key_and_skip_duplicates(self) -> None:
        items = rd.shelf_items([("Create", "box", "Box"), ("Lights", "rman_pxrrectlight", "Rect Light"), ("Other", "box", "Box"), ("Create", "", ""),
                                ("Terrain", "rect_light2", "Rect Light")])
        self.assertEqual([i["key"] for i in items], ["shelf/box", "shelf/rman_pxrrectlight", "shelf/rect_light2"], "the same label in two shelves stays two items")
        self.assertEqual(items[0]["context"], "Create")
        self.assertTrue(items[0]["doc_url"].startswith("https://www.sidefx.com/search/?q=Box"))
        rd.set_shelf_tools(items)
        try:
            self.assertEqual(len(rd.catalog("shelf")), 3)
            self.assertEqual(rd.search("shelf", "rect")[0]["label"], "Rect Light")
        finally:
            rd.set_shelf_tools([])

    def test_used_mark(self) -> None:
        self.assertIn("このチュートリアルで使いました", rd.entry_html(self.ITEM, {"what": "x"}, used=True))
        self.assertNotIn("このチュートリアルで使いました", rd.entry_html(self.ITEM, {"what": "x"}))

    def test_only_http_links_are_made(self) -> None:
        refs = [{"title": "ok", "url": "https://example.com/x", "source": "S"}, {"title": "bad", "url": "javascript:alert(1)", "source": "S"}]
        text = rd.entry_html(self.ITEM, {"what": "x"}, refs)
        self.assertIn('href="https://example.com/x"', text)
        self.assertNotIn("javascript:", text)


if __name__ == "__main__":
    unittest.main()
