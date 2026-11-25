"""Reference の対応を増やしたこと（2026-11-24）のテスト: APEX・シェルフの点検、材料（事実）、対象の一覧、撮影のレシピ。

  ・説明を作る対象: ノード +184（SOP・DOP・LOP・VOP・COP（Copernicus）・OBJ・ROP）、VEX +116、APEX 85、シェルフツール 85、撮影つきノード +8（33 → 41）
  ・APEX・シェルフも、本物の Houdini と突き合わせて点検する（前は、対象外で、何でも通った）。
    APEX: レジストリ（apex.Registry）に在るか、説明の「」の英字が、本物のポート名・ほかの APEX ノードの名前か。
    シェルフ: hou.shelves.tools() に在るか、説明の「」の英字が、ツール・シェルフ・ノードの名前か。
Houdini は使わない（書き出した結果の形の偽物で確かめる）。実機の確認は、docs/reports/reference-expansion-2026-11-24.md。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_reference_expansion_20261124.py -v
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "reference_capture"))

import audit_reference as ar  # noqa: E402
import build_reference_entries as bre  # noqa: E402
import reference_data as rd  # noqa: E402
import reference_sets as sets  # noqa: E402
from recipes import RECIPES  # noqa: E402

PARMS = {
    "apex/skel--GetParent": {"type": "skel::GetParent", "names": ["GetParent", "geo", "joint", "parent", "skel--GetParent", "skel::GetParent"],
                             "ports": [{"direction": "input", "name": "geo", "type": "Geometry"}, {"direction": "input", "name": "joint", "type": "Int"},
                                       {"direction": "output", "name": "parent", "type": "Int"}]},
    "apex/Nope": None,
    "shelf/pyro_billowysmoke": {"type": "pyro_billowysmoke", "names": ["Billowy Smoke", "Legacy Pyro FX", "pyro_billowysmoke"], "label": "Billowy Smoke", "shelf": "Legacy Pyro FX"},
    "shelf/nope": None,
    "__node_types__": ["Pyro Source", "Scatter"],
    "__apex_names__": ["skel::AddJoint", "AddJoint", "Fit"],
    "__shelf_labels__": ["Flames", "Explosion"],
}


class ApexAndShelfAuditTest(unittest.TestCase):
    def test_real_port_names_pass_and_made_up_ones_are_found(self) -> None:
        self.assertEqual(ar.entry_problems("apex", "apex/skel--GetParent", {"what": "「geo」と「joint」を渡すと、「parent」が出る"}, PARMS), [])
        bad = ar.entry_problems("apex", "apex/skel--GetParent", {"what": "「geo」と「root」を渡す"}, PARMS)
        self.assertEqual(len(bad), 1)
        self.assertIn("root", bad[0])
        self.assertIn("ポート名", bad[0])

    def test_other_apex_nodes_may_be_named(self) -> None:
        self.assertEqual(ar.entry_problems("apex", "apex/skel--GetParent", {"when": "足すなら「AddJoint」や「Fit」を使う"}, PARMS), [])

    def test_an_apex_node_that_is_not_in_the_registry_is_a_problem(self) -> None:
        self.assertIn("ありません", ar.entry_problems("apex", "apex/Nope", {"what": "x"}, PARMS)[0])

    def test_shelf_tool_names_nodes_and_other_tools_may_be_named(self) -> None:
        entry = {"what": "「Billowy Smoke」は、シェルフ「Legacy Pyro FX」にあり、「Pyro Source」を作る。「Flames」も似ている"}
        self.assertEqual(ar.entry_problems("shelf", "shelf/pyro_billowysmoke", entry, PARMS), [])

    def test_a_shelf_explanation_that_quotes_a_parameter_name_is_found(self) -> None:
        """シェルフの説明は、作られるノードのパラメータ名を書かない。実際に、Tube の説明が「End Caps」「Radius」を挙げて、点検で落ちた。"""
        bad = ar.entry_problems("shelf", "shelf/pyro_billowysmoke", {"what": "「Radius」を変える"}, PARMS)
        self.assertEqual(len(bad), 1)
        self.assertIn("Radius", bad[0])

    def test_a_shelf_tool_that_does_not_exist_is_a_problem(self) -> None:
        self.assertIn("ありません", ar.entry_problems("shelf", "shelf/nope", {"what": "x"}, PARMS)[0])

    def test_without_the_dump_nothing_passes(self) -> None:
        self.assertTrue(ar.entry_problems("apex", "apex/skel--GetParent", {"what": "x"}, None))
        self.assertTrue(ar.entry_problems("shelf", "shelf/pyro_billowysmoke", {"what": "x"}, {}))


class SavedKeysTest(unittest.TestCase):
    def test_apex_file_names_are_mapped_back_to_the_real_keys(self) -> None:
        """保存した説明のファイル名は、キーを小文字にして、"/" と "-" を "_" にしたもの。そのままでは、本物のキー（apex/skel--GetParent）に戻せない。"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "localRAG" / "reference" / "apex"
            folder.mkdir(parents=True)
            for key in ("apex/skel--GetParent", "apex/Fit", "apex/IfBegin"):
                (folder / f"{rd.slug(key)}.json").write_text("{}", encoding="utf-8")
            keys = ar.saved_apex_keys(tmp, set())
            self.assertEqual(sorted(keys), ["apex/Fit", "apex/IfBegin", "apex/skel--GetParent"])
            self.assertEqual(ar.saved_apex_keys(tmp, {"apex/Fit"}), ["apex/Fit"])

    def test_shelf_file_names_become_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "localRAG" / "reference" / "shelf"
            folder.mkdir(parents=True)
            (folder / "shelf_dynamics_rbdobjects.json").write_text("{}", encoding="utf-8")
            self.assertEqual(ar.saved_shelf_keys(tmp, set()), ["shelf/dynamics_rbdobjects"])

    def test_no_folder_no_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual((ar.saved_apex_keys(tmp, set()), ar.saved_shelf_keys(tmp, set())), ([], []))


class FactsAndPromptTest(unittest.TestCase):
    def test_apex_facts_list_the_real_ports(self) -> None:
        text = bre.facts_for({"kind": "apex"}, PARMS["apex/skel--GetParent"])
        self.assertIn("skel::GetParent", text)
        self.assertIn("入力のポート: geo（Geometry）、joint（Int）", text)
        self.assertIn("出力のポート: parent（Int）", text)

    def test_shelf_facts_say_where_it_is_and_forbid_invented_operations_and_parameters(self) -> None:
        text = bre.facts_for({"kind": "shelf"}, PARMS["shelf/pyro_billowysmoke"])
        self.assertIn("Legacy Pyro FX", text)
        self.assertIn("パラメータの名前は書かない", text)
        self.assertIn("資料に書かれた操作", text)

    def test_nodes_and_missing_info_have_no_facts(self) -> None:
        self.assertEqual(bre.facts_for({"kind": "node"}, {"names": []}), "")
        self.assertEqual(bre.facts_for({"kind": "apex"}, None), "")

    def test_facts_reach_the_prompt_only_when_given(self) -> None:
        _system, user = rd.build_prompt("apex", "GetParent", ["資料"], [], parm_names=["geo"], facts="入力のポート: geo（Geometry）")
        self.assertIn("実機（Houdini 22）で確かめた事実", user)
        self.assertIn("入力のポート: geo（Geometry）", user)
        _system, user = rd.build_prompt("apex", "GetParent", ["資料"], [])
        self.assertNotIn("実機（Houdini 22）で確かめた事実", user)


class MakeOneGuardTest(unittest.TestCase):
    """AI を呼ぶ前に、存在しないもの・確かめていないものを止める（前は、呼んでから落として、118 件の費用が無駄になった）。"""

    def test_a_vex_function_that_was_not_checked_never_reaches_the_ai(self) -> None:
        from unittest import mock

        item = {"kind": "vex", "key": "vex/nope", "name": "nope", "label": "nope", "context": "vex"}
        with mock.patch.object(bre.ra, "make_entry") as made:
            for known in ({}, {"vex/nope": False}):
                result = bre.make_one({}, item, {"__vex__": known})
                self.assertFalse(result["ok"])
                self.assertEqual(result["usage"], {})
        made.assert_not_called()

    def test_a_checked_vex_function_is_made(self) -> None:
        from unittest import mock

        item = {"kind": "vex", "key": "vex/avg", "name": "avg", "label": "avg", "context": "vex"}
        entry = {"what": "avg は、数の並びの平均を返す VEX の関数です。", "use": "点の値をならすときに使います。", "example": "avg の結果を属性に入れます。",
                 "example_point": "平均の変化を見てください。", "when": "複数の値の中心を知りたいときに向いています。外れ値が多いときは向きません。"}
        with mock.patch.object(bre.ra, "make_entry", return_value=(entry, {}, 5, 0)) as made, mock.patch.object(bre.ra, "save_made", return_value=True):
            result = bre.make_one({}, item, {"__vex__": {"vex/avg": True}})
        made.assert_called_once()
        self.assertTrue(result["ok"], result)

    def test_missing_apex_and_shelf_items_stop_before_the_ai(self) -> None:
        from unittest import mock

        with mock.patch.object(bre.ra, "make_entry") as made:
            for kind, key in (("apex", "apex/Nope"), ("shelf", "shelf/nope")):
                result = bre.make_one({}, {"kind": kind, "key": key, "name": "x", "label": "x", "context": kind}, {key: None})
                self.assertFalse(result["ok"], key)
        made.assert_not_called()


class TargetListsTest(unittest.TestCase):
    def test_the_lists_have_no_duplicates(self) -> None:
        for name in ("EXTRA_NODES", "APEX_KEYS"):
            values = getattr(sets, name)
            self.assertEqual(len(values), len(set(values)), name)
        keys = [k for k, _label, _shelf in sets.SHELF_TOOLS]
        self.assertEqual(len(keys), len(set(keys)), "シェルフツールのキーは、重ならない（同じ名前のツールは、内部名で区別する）")

    def test_extra_nodes_are_new_and_well_formed(self) -> None:
        old = set(bre.COMMON_NODES)
        for key in sets.EXTRA_NODES:
            self.assertNotIn(key, old, key)
            self.assertRegex(key, r"^(sop|dop|lop|vop|cop|obj|out)/[a-z0-9_]+$")

    def test_apex_keys_are_all_in_the_catalog(self) -> None:
        catalog = {i["key"] for i in rd.catalog("apex")}
        self.assertEqual([k for k in sets.APEX_KEYS if k not in catalog], [])

    def test_shelf_keys_follow_the_panels_rule(self) -> None:
        """パネルは、Houdini のツールの内部名を slug にして、shelf/<slug> をキーにする（shelf_items）。同じ形でないと、画面の一覧と、公開した説明が、結びつかない。"""
        for key, label, shelf in sets.SHELF_TOOLS:
            self.assertEqual(key, "shelf/" + rd.slug(key.split("/", 1)[1]), key)
            self.assertTrue(label.strip() and shelf.strip(), key)
        panel = rd.shelf_items([(shelf, key.split("/", 1)[1], label) for key, label, shelf in sets.SHELF_TOOLS])
        self.assertEqual({i["key"] for i in panel}, {k for k, _l, _s in sets.SHELF_TOOLS})

    def test_select_items_sets(self) -> None:
        self.assertEqual({i["kind"] for i in bre.select_items("apex", set())}, {"apex"})
        self.assertEqual({i["kind"] for i in bre.select_items("shelf", set())}, {"shelf"})
        self.assertEqual(len(bre.select_items("apex", set())), len(sets.APEX_KEYS))
        self.assertEqual(len(bre.select_items("extra", set())), len(sets.EXTRA_NODES))
        everything = bre.select_items("all", set())
        self.assertEqual(len(everything), len({(i["kind"], i["key"]) for i in everything}), "全部の中に、重なりがない")
        self.assertEqual({i["kind"] for i in everything}, {"node", "vex", "apex", "shelf"})
        self.assertEqual([i["key"] for i in bre.select_items("apex", {"apex/Fit"})], ["apex/Fit"])

    def test_the_vex_list_has_no_duplicates_and_only_function_names(self) -> None:
        names = rd.VEX_FUNCTIONS
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n.isidentifier() for n in names))
        self.assertGreaterEqual(len(names), 200)
        for name in ("avg", "reflect", "vertexpoint", "re_find", "rgbtohsv", "nametopoint"):
            self.assertIn(name, names)


class RecipeTest(unittest.TestCase):
    NEW = ("sop/pointwrangle", "sop/polycap", "sop/polyexpand2d", "sop/polyfill", "sop/ray", "sop/skin", "sop/carve", "sop/convertline")

    def test_eight_recipes_were_added_to_the_capture_list(self) -> None:
        keys = [r["key"] for r in RECIPES if r["kind"] == "node"]  # VEX・シェルフのレシピ（2026-11-24）は、別に数える
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keys), 110)  # + 2026-11-25 の 2 回目の Heightfield 8・FLIP 1・POP 4  # + 2026-11-25 の VOP 15・LOP 5・COP 7・DOP 4・SOP 7  # 41 + 2026-11-24 の 2 回目に足した 15（recipes_more.py・recipes_sim.py）+ 3（recipes_dyn.py: Vellum・RBD・ライト）
        for key in self.NEW:
            self.assertIn(key, keys)

    def test_the_new_recipes_are_explained_nodes_and_have_notes(self) -> None:
        explained = set(bre.COMMON_NODES) | set(sets.EXTRA_NODES)
        by_key = {r["key"]: r for r in RECIPES}
        for key in self.NEW:
            self.assertIn(key, explained, key)
            self.assertTrue(by_key[key].get("note"), key)
            self.assertTrue(bre.verified_steps(key), "撮影のレシピが、説明の材料の文になる: " + key)

    def test_effective_values_only(self) -> None:
        """撮る前の検査で、効いていないと分かった値は、レシピに入れない（実機で落ちたもの: ray の lift、carve の domainu2 だけ（スイッチが要る））。"""
        by_key = {r["key"]: r for r in RECIPES}
        self.assertNotIn("lift", by_key["sop/ray"]["parms"])
        self.assertEqual(by_key["sop/ray"]["parms"], {"method": 0})
        self.assertEqual({"firstu", "secondu"} <= set(by_key["sop/carve"]["parms"]), True)
        self.assertEqual(by_key["sop/polyfill"]["input"]["after"][0]["parms"]["group"], "39 40 48 49", "穴は、板の真ん中（縁の切り欠きでは、埋めても、変わらない）")


class ApexInfoTest(unittest.TestCase):
    """dump_parms.py の apex_info（実機の apex.Registry の偽物で）。"""

    @classmethod
    def setUpClass(cls) -> None:
        sys.modules.setdefault("hou", types.ModuleType("hou"))
        spec = importlib.util.spec_from_file_location("dump_parms_for_test", ROOT / "scripts" / "reference_capture" / "dump_parms.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)  # __main__ ガードがあるので、main() は動かない

    class Registry:
        def __init__(self) -> None:
            self.sigs = {
                "skel::GetParent": (["geo Geometry", "joint Int"], ["parent Int"]),
                "Abs<Float>": (["val Float"], ["result Float"]),
                "IfBegin": (["condition Bool", "__spare__ "], ["scope ", "__spare__ "]),
            }

        def getSignature(self, name):
            ins, outs = self.sigs[name]
            class P:
                def __init__(self, text: str) -> None:
                    self.text = text

                def __repr__(self) -> str:
                    head, _, tail = self.text.partition(" ")
                    return f"<APEX_Parm '{head}' {tail}>"

            return types.SimpleNamespace(inputs=lambda: [P(t) for t in ins], outputs=lambda: [P(t) for t in outs])

    def test_page_name_maps_to_the_registry_name_and_ports_are_read(self) -> None:
        names = {"skel::GetParent", "Abs<Float>", "IfBegin"}
        info = self.module.apex_info("apex/skel--GetParent", self.Registry(), names)
        self.assertEqual(info["type"], "skel::GetParent")
        self.assertIn("geo", info["names"])
        self.assertEqual([(p["direction"], p["name"], p["type"]) for p in info["ports"]],
                         [("input", "geo", "Geometry"), ("input", "joint", "Int"), ("output", "parent", "Int")])

    def test_internal_spare_ports_are_not_listed(self) -> None:
        info = self.module.apex_info("apex/IfBegin", self.Registry(), {"IfBegin"})
        self.assertEqual([p["name"] for p in info["ports"]], ["condition", "scope"])
        self.assertNotIn("__spare__", info["names"])

    def test_generic_only_nodes_are_found_by_their_base_name(self) -> None:
        info = self.module.apex_info("apex/Abs", self.Registry(), {"Abs<Float>"})
        self.assertEqual(info["type"], "Abs<Float>")

    def test_a_missing_node_is_none(self) -> None:
        self.assertIsNone(self.module.apex_info("apex/Nope", self.Registry(), {"IfBegin"}))


if __name__ == "__main__":
    unittest.main()
