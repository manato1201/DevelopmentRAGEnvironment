"""reference_author（Reference の説明を AI で作る共通部分）のテスト（2026-11-19）。AI・通信は、偽物に差し替える。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_reference_author.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import reference_author as ra  # noqa: E402
import reference_data as rd  # noqa: E402

ITEM = {"kind": "node", "key": "sop/scatter", "name": "scatter", "label": "Scatter", "context": "sop"}
ANSWER = json.dumps({"what": "点を散らす", "use": "植生", "example": "", "example_point": "", "when": "密度を決める"})


class MakeEntryTest(unittest.TestCase):
    def test_make_entry_builds_the_prompt_from_the_given_material_and_limits_the_call(self) -> None:
        calls = []

        def complete(system, user, **options):
            calls.append((system, user, options))
            return ANSWER, {"input_tokens": 5000, "output_tokens": 900}

        entry, usage, docs_n, refs_n = ra.make_entry({}, complete, ITEM, references=[{"title": "T", "source": "S", "excerpt": "x"}], docs=["Scatter は、点を散らします。"])
        self.assertEqual(entry["what"], "点を散らす")
        self.assertEqual((usage["output_tokens"], docs_n, refs_n), (900, 1, 1))
        system, user, options = calls[0]
        self.assertIn("項目: Scatter（ノード）", user)
        self.assertIn("点を散らします", user)
        self.assertEqual(options, {"max_tokens": rd.REFERENCE_MAX_TOKENS, "effort": rd.REFERENCE_EFFORT})

    def test_an_unreadable_answer_gives_none_and_an_exception_is_not_swallowed(self) -> None:
        with self.assertRaises(ra.UnreadableAnswer) as caught:
            ra.make_entry({}, lambda s, u, **kw: ("すみません", None), ITEM, references=[], docs=[])
        self.assertEqual(caught.exception.text, "すみません", "the raw reply is kept for diagnosis")

        def boom(s, u, **kw):
            raise RuntimeError("予算を使い切りました")

        with self.assertRaises(RuntimeError):
            ra.make_entry({}, boom, ITEM, references=[], docs=[])

    def test_without_given_material_it_fetches_docs_and_references(self) -> None:
        with mock.patch.object(ra, "fetch_docs", lambda cfg, item: ["資料"]), \
                mock.patch.object(ra, "fetch_reference_items", lambda base_dir, **kw: [{"title": "scatter tips", "excerpt": "x", "tags": ["YouTube"], "published": "2026-11-18", "source": "S", "url": "https://e.com"}]):
            captured = []
            ra.make_entry({"local_bridge_dir": "x"}, lambda s, u, **kw: (captured.append(u) or ANSWER, {}), ITEM)
        self.assertIn("資料", captured[0])
        self.assertIn("scatter tips", captured[0])

    def test_fetch_docs_takes_the_node_page_first_then_search_results(self) -> None:
        class FakeClient:
            def __init__(self, cfg): pass

            def docs_get(self, ns, file, offset=0, max_chars=0):
                self.page = file
                FakeClient.asked = (ns, file, max_chars)
                return {"status": "ok", "text": "【Houdini 22 / SOP / scatter】 本体"} if file == "Scatter [SOP]" else {"status": "error"}

            def docs_search(self, ns, query, limit=8):
                return {"texts": ["近い資料", "  "]}

        with mock.patch("rag_client.RAGClient", FakeClient):
            texts = ra.fetch_docs({"tutorial_rag_namespace": "houdini22"}, ITEM)
        self.assertEqual(texts, ["【Houdini 22 / SOP / scatter】 本体", "近い資料"])
        self.assertEqual(FakeClient.asked[1:], ("Scatter [SOP]", ra.PAGE_CHARS))
        with mock.patch("rag_client.RAGClient", FakeClient):
            vex = ra.fetch_docs({}, {"kind": "vex", "key": "vex/chf", "label": "chf", "name": "chf", "context": "vex"})
        self.assertEqual(vex, ["近い資料"], "VEX has no node page: search only")

    def test_fetch_docs_returns_empty_when_the_search_fails(self) -> None:
        self.assertEqual(ra.fetch_docs({"cf_url": "https://example.invalid"}, ITEM), [])
        self.assertEqual(ra.fetch_docs({}, ITEM), [])

    def test_save_made_keeps_the_label_and_the_counts(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(ra.save_made(d, ITEM, {"what": "点を散らす"}, 2, 1))
            saved = json.loads(rd.entry_path(d, "node", "sop/scatter").read_text(encoding="utf-8"))
            self.assertEqual((saved["what"], saved["label"], saved["docs_found"], saved["references"]), ("点を散らす", "Scatter", 2, 1))
            self.assertEqual(rd.load_entry(d, "node", "sop/scatter")["what"], "点を散らす")
            self.assertFalse(ra.save_made("", ITEM, {"what": "x"}, 0, 0))


if __name__ == "__main__":
    unittest.main()
