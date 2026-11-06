"""2026-11-06 の水上爆発の生成ログ・動画から見つけた不具合の修正のテスト。

  ・グラフの書き出しに、ロックされたデジタルアセット（Karma など）の中身が入っていた（321ノード・手順書195,000文字）
  ・「ノードをつなぐ」が12回続き、同じ見出しの3秒のスライドが12枚になった
  ・ビューポートの画像が、アルファつきで、アルファを無視すると空が黒・床が白になった
  ・動画の台本の節が、見出しのずれで全部定型の文になった／英語→カタカナが名前の途中を壊した／同じ節が2回出た
実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
Qt の描画も確かめるとき:     uv run --with PySide6 python -m unittest houdini/tests/test_run_20261106.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))
sys.modules.setdefault("hou", types.ModuleType("hou"))

import guide_mode as gm  # noqa: E402
import houdini_tools as ht  # noqa: E402
import video_script as vs  # noqa: E402
from test_parm_tools import make_executor, make_world  # noqa: E402
from test_video_script import make_steps  # noqa: E402


# ── グラフの書き出し ───────────────────────────────────────────────────────────

class _P:
    def __init__(self, name, value, default=False):
        self._n, self._v, self._d = name, value, default

    def name(self): return self._n
    def eval(self): return self._v
    def isAtDefault(self): return self._d


class _N:
    def __init__(self, path, kind="null", locked=False, parms=None):
        self._path, self._kind, self._locked = path, kind, locked
        self._parms = parms or []
        self.kids: list[_N] = []

    def path(self): return self._path
    def name(self): return self._path.rsplit("/", 1)[-1]
    def type(self): return types.SimpleNamespace(name=lambda: self._kind)
    def position(self): return (1.0, 2.0)
    def parms(self): return self._parms
    def children(self): return tuple(self.kids)
    def inputConnections(self): return ()
    def isLockedHDA(self): return self._locked


class ExportGraphTest(unittest.TestCase):
    def executor(self, sandbox):
        ex = ht.HoudiniToolExecutor.__new__(ht.HoudiniToolExecutor)
        ex._sandbox = sandbox
        ex.sandbox_path = sandbox.path()
        ex._append_audit = lambda event: None
        return ex

    def world(self):
        sandbox = _N("/obj/sb", "subnet")
        lopnet = _N("/obj/sb/solaris", "lopnet")
        karma = _N("/obj/sb/solaris/settings", "karmarendersettings", locked=True)
        karma.kids = [_N(f"/obj/sb/solaris/settings/rendervar{i}", "rendervar") for i in range(80)]
        sky = _N("/obj/sb/solaris/sky", "karmaskydome", locked=True)
        sky.kids = [_N(f"/obj/sb/solaris/sky/switch{i}", "switch") for i in range(20)]
        mine = _N("/obj/sb/solaris/mine", "null")
        lopnet.kids = [karma, sky, mine]
        geo = _N("/obj/sb/fx", "geo")
        geo.kids = [_N("/obj/sb/fx/a", "box"), _N("/obj/sb/fx/b", "sphere")]
        sandbox.kids = [geo, lopnet]
        return sandbox

    def test_locked_asset_internals_are_not_exported(self):
        graph = self.executor(self.world()).export_node_graph()
        ids = [n["id"] for n in graph["nodes"]]
        self.assertEqual(len(ids), 7, ids[:10])
        self.assertIn("solaris/settings", ids, "the asset node itself is kept")
        self.assertFalse([i for i in ids if "rendervar" in i or "/switch" in i], "its internals are not")
        self.assertIn("fx/a", ids, "ordinary containers are still walked")

    def test_a_node_the_api_cannot_ask_is_still_walked(self):
        sandbox = self.world()
        for node in sandbox.kids[1].kids:
            node.isLockedHDA = mock.Mock(side_effect=AttributeError("no such method"))
        graph = self.executor(sandbox).export_node_graph()
        self.assertGreater(len(graph["nodes"]), 100, "unknown = the old behaviour (everything is walked)")

    def test_parameters_are_capped_in_number_and_length(self):
        node = _N("/obj/sb/big", "attribwrangle", parms=[_P(f"p{i}", i) for i in range(55)] + [_P("code", "x" * 2000), _P("same", 1, default=True)])
        sandbox = _N("/obj/sb", "subnet")
        sandbox.kids = [node]
        entry = self.executor(sandbox).export_node_graph()["nodes"][0]
        self.assertEqual(len(entry["params"]), ht.HoudiniToolExecutor._GRAPH_MAX_PARMS)
        self.assertEqual(entry["params_omitted"], 56 - ht.HoudiniToolExecutor._GRAPH_MAX_PARMS)
        self.assertNotIn("same", entry["params"], "defaults are not listed")
        self.assertNotIn("code", entry["params"], "the long code is among the omitted, not half-written")
        small = _N("/obj/sb/w", "attribwrangle", parms=[_P("code", "x" * 2000)])
        sandbox.kids = [small]
        value = self.executor(sandbox).export_node_graph()["nodes"][0]["params"]["code"]
        self.assertLessEqual(len(value), ht.HoudiniToolExecutor._GRAPH_MAX_VALUE_CHARS + 1)
        self.assertTrue(value.endswith("…"))

    def test_markdown_lists_are_capped(self):
        try:
            import tutorial_agent as ta
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"tutorial_agent をimportできません: {exc}")
        agent = ta.TutorialAgent.__new__(ta.TutorialAgent)
        agent._model = "test"
        agent.executor = None
        result = ta.TutorialResult()
        result.completed = True
        result.graph = {
            "nodes": [{"id": f"n{i}", "kind": "null", "params": {}} for i in range(500)],
            "edges": [{"source": f"n{i}", "target": f"n{i + 1}", "targetInput": 0} for i in range(400)],
        }
        md = agent._assemble_markdown("t", {"title": "T", "steps": "1. a"}, result)
        self.assertLess(len(md), 30000)
        self.assertIn("ほか 380 ノード", md)
        self.assertIn("ほか 280 本", md)


# ── 連続した接続を1手順にまとめる ───────────────────────────────────────────────

class ConnectGroupingTest(unittest.TestCase):
    def setUp(self):
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.ex = make_executor(self.hou, self.sandbox)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ex._screenshot_dir = Path(self.tmp.name)
        self.ex._last_parm_change = None
        self.ex._param_group = None
        self.ex._connect_group = None
        self.geo = self.add("geo1", "geo", "Object")
        for name in ("a", "b", "c", "d"):
            self.add(f"geo1/{name}", "null", "Sop", parent=self.geo)
        module = types.ModuleType("screen_capture")
        module.capture_viewport = lambda path, *a, **k: Path(path).write_bytes(b"png") and True
        module.capture_viewport_clip = lambda *a, **k: ([], 0)
        module.focus_network_on = lambda *a, **k: None
        module.capture_network_editor = lambda path, *a, **k: Path(path).write_bytes(b"png") and True
        module.capture_parameter_screen = lambda *a, **k: ""
        module._log = lambda *a, **k: None
        patcher = mock.patch.dict(sys.modules, {"screen_capture": module})
        patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self, src, dst, idx=0):
        args = {"from_node": f"geo1/{src}", "to_node": f"geo1/{dst}", "input_index": idx}
        self.ex._capture_step_screenshot("connect_nodes", args, f"接続しました: {src}[out:0] → {dst}[in:{idx}]")

    def test_consecutive_connections_become_one_step(self):
        self.connect("a", "b")
        self.assertEqual(len(self.ex.step_screenshots), 1)
        self.assertEqual(self.ex.step_screenshots[0]["result"], "a の出力を、b の入力につなぐ", "a single connection keeps its old sentence")
        self.connect("b", "c")
        self.connect("c", "d")
        steps = self.ex.step_screenshots
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["step"], 1)
        self.assertEqual(steps[0]["result"], "3本のノードをつなぐ: a → b、b → c、c → d")
        self.assertEqual([(c["from"], c["to"]) for c in steps[0]["guide"]["connections"]], [("a", "b"), ("b", "c"), ("c", "d")])

    def test_another_tool_in_between_starts_a_new_step(self):
        self.connect("a", "b")
        self.ex._capture_step_screenshot("cook_node", {"node": "geo1/b"}, "cook 成功: geo1/b（エラー・警告なし）")
        self.connect("b", "c")
        self.assertEqual([s["tool"] for s in self.ex.step_screenshots], ["connect_nodes", "cook_node", "connect_nodes"])
        self.assertEqual([s["step"] for s in self.ex.step_screenshots], [1, 2, 3])

    def test_the_same_connection_twice_is_listed_once(self):
        self.connect("a", "b")
        self.connect("a", "b")
        self.connect("b", "c")
        self.assertEqual(self.ex.step_screenshots[0]["result"], "2本のノードをつなぐ: a → b、b → c")

    def test_long_groups_are_summarised(self):
        for src, dst in (("a", "b"), ("b", "c"), ("c", "d"), ("a", "c"), ("a", "d"), ("b", "d"), ("d", "a")):
            self.connect(src, dst)
        text = self.ex.step_screenshots[0]["result"]
        self.assertTrue(text.startswith("7本のノードをつなぐ: "))
        self.assertTrue(text.endswith("ほか1本"))
        self.assertEqual(len(self.ex.step_screenshots[0]["guide"]["connections"]), 7)

    def test_the_video_gets_one_slide_with_its_own_wording(self):
        self.connect("a", "b")
        self.connect("b", "c")
        entry = self.ex.step_screenshots[0]
        template = vs._template_step(entry)
        self.assertIn("2本", template["heading"])
        self.assertIn("aからb", template["narration"])
        self.assertNotEqual(template["heading"], "ノードをつなぐ")

    def test_guide_reads_both_the_record_and_the_old_sentence(self):
        self.connect("a", "b")
        self.connect("b", "c")
        entry = dict(self.ex.step_screenshots[0])
        steps = gm.build_guide([entry])["steps"]
        self.assertEqual(len(steps[0]["connections"]), 2)
        self.assertIn("2本つなぎます", steps[0]["hint"])
        without = dict(entry)
        without.pop("guide")
        again = gm.build_guide([without])["steps"][0]
        self.assertEqual([(c["from"], c["to"]) for c in again["connections"]], [("a", "b"), ("b", "c")])


# ── 動画の台本 ────────────────────────────────────────────────────────────────

class VideoScriptFixesTest(unittest.TestCase):
    def test_katakana_does_not_break_snake_case_names(self):
        for name in ("fire_sphere", "spray_scatter", "merge_layers", "A_keep_density", "column_vdb"):
            self.assertEqual(vs.to_katakana(f"名前を{name}にします"), f"名前を{name}にします", name)
        self.assertEqual(vs.to_katakana("Scatter を使う"), "スキャッター を使う", "plain words are still read in katakana")
        self.assertEqual(vs.to_katakana("(Merge)"), "(マージ)")

    def test_sections_match_by_id_then_exact_then_normalised_then_order(self):
        headings = ["前提条件", "作る前に: 使うノードと、できること", "TIPS", "次のレッスン"]
        raw = [
            {"id": 2, "match": "全然違う", "narration": "b"},
            {"match": "TIPS", "narration": "c"},
            {"match": "前提条件 ", "narration": "a"},
            {"match": "次の レッスン", "narration": "d"},
        ]
        found = vs.match_sections(raw, headings)
        self.assertEqual({h: i["narration"] for h, i in found.items()}, {"前提条件": "a", "作る前に: 使うノードと、できること": "b", "TIPS": "c", "次のレッスン": "d"})
        by_order = vs.match_sections([{"narration": "x"}, {"narration": "y"}], ["H1", "H2"])
        self.assertEqual([by_order["H1"]["narration"], by_order["H2"]["narration"]], ["x", "y"], "same count, no ids: by order")
        self.assertEqual(vs.match_sections([{"narration": "x"}], ["H1", "H2"]), {}, "different count and no match: nothing is guessed")
        self.assertEqual(vs.match_sections(None, ["H1"]), {})

    def test_an_item_is_used_once(self):
        found = vs.match_sections([{"id": 1, "match": "A", "narration": "x"}], ["A", "A2"])
        self.assertEqual(list(found), ["A"])

    SECTION_TEXT = "この動画は、ノードを置いてつなげる人向けです。ボリュームの基本は、先に見ておくと進めやすくなります。知っている人は、手順の1から見てください。"

    def test_model_sections_survive_a_heading_that_drifted(self):
        with tempfile.TemporaryDirectory() as d:
            steps = vs.usable_steps(make_steps(Path(d)))
            sections = [("前提条件", "本文"), ("作る前に: 使うノードと、できること", "本文2")]
            model = {"sections": [
                {"id": 1, "match": "前提", "narration": self.SECTION_TEXT},
                {"id": 2, "match": "段取り", "narration": self.SECTION_TEXT.replace("前提", "段取り")},
            ]}
            script, _, notes = vs.assemble_script(model, steps, "t", "", sections, "basic")
            self.assertEqual([s["narration"] for s in script["sections"]][0], self.SECTION_TEXT)
            self.assertFalse([n for n in notes if "節" in n], notes)

    def test_rejected_parts_are_recorded_in_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            steps = vs.usable_steps(make_steps(Path(d)))
            model = {"sections": [{"id": 1, "narration": "短い"}]}
            script, _, notes = vs.assemble_script(model, steps, "t", "", [("TIPS", "本文")], "basic")
            self.assertEqual(script["sections"][0]["narration"], vs._template_section("TIPS")["narration"])
            self.assertTrue(any("TIPS" in n for n in script["notes"]), script["notes"])

    def test_next_lesson_has_its_own_slide_text(self):
        self.assertNotEqual(vs._template_section("次のレッスン")["narration"], vs._template_section("応用・発展のヒント")["narration"])
        self.assertEqual(vs._template_section("次のレッスン")["heading"], "次のレッスン")
        self.assertEqual(vs._template_section("応用・発展のヒント")["heading"], "もっと試してみよう")

    def test_short_steps_may_be_short(self):
        with tempfile.TemporaryDirectory() as d:
            steps = vs.usable_steps(make_steps(Path(d)))
            connect = next(s for s in steps if s["tool"] == "connect_nodes")
            cook = next(s for s in steps if s["tool"] == "cook_node")
            short = "emitの出力を、blastの入力につなぎます。"  # 20文字台。英字が多い（ノード名）が、識別子の文なので通る
            self.assertGreaterEqual(len(short), vs.SHORT_STEP_MIN)
            self.assertLess(len(short), vs.STEP_NARRATION_MIN)
            model = {"steps": [{"step": connect["step"], "narration": short}, {"step": cook["step"], "narration": short}]}
            script, _, _ = vs.assemble_script(model, steps, "t", "")
            by = {s["step"]: s["narration"] for s in script["steps"]}
            self.assertEqual(by[connect["step"]], short, "a connect step may be short")
            self.assertNotEqual(by[cook["step"]], short, "other steps keep the 40-character floor")

    def test_prompt_numbers_the_sections_and_asks_for_ids(self):
        with tempfile.TemporaryDirectory() as d:
            steps = make_steps(Path(d))
            prompt = vs.build_user_prompt("t", "x", steps, [("前提条件", "a"), ("TIPS", "b")], "basic")
            self.assertIn("【節1】## 前提条件", prompt)
            self.assertIn("【節2】## TIPS", prompt)
        for level in ("basic", "applied", "advanced"):
            text = vs.system_prompt(level)
            self.assertIn('"id": 節の番号', text)
            self.assertIn("20を超える", text)
            self.assertIn("column_tube", text)


# ── 撮影 ──────────────────────────────────────────────────────────────────────

try:
    from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
except ImportError:
    QImage = None


@unittest.skipIf(QImage is None, "PySide6 が無いので、画像の確認は飛ばす")
class FlattenAlphaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        import screen_capture

        cls.sc = screen_capture

    def make(self, path):
        image = QImage(4, 2, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))                       # 透明（RGB は意味のない 0）
        image.setPixelColor(1, 0, QColor(255, 255, 255, 3))  # ほぼ透明な白（床）
        image.setPixelColor(2, 0, QColor(255, 255, 255, 255))  # 不透明な白（線）
        image.setPixelColor(3, 0, QColor(200, 0, 0, 128))    # 半透明の赤
        self.assertTrue(image.save(str(path), "PNG"))

    def test_transparent_areas_take_the_background_and_the_file_has_no_alpha(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "v.png"
            self.make(path)
            self.assertTrue(self.sc.flatten_alpha(path))
            image = QImage(str(path))
            self.assertFalse(image.hasAlphaChannel(), "opaque after flattening")
            bg = self.sc.VIEWPORT_BACKGROUND_RGB
            self.assertEqual(image.pixelColor(0, 0).getRgb()[:3], bg, "transparent = the background, not black")
            floor = image.pixelColor(1, 0).getRgb()[:3]
            self.assertTrue(all(abs(floor[i] - bg[i]) <= 4 for i in range(3)), "an almost transparent white floor stays dark: " + str(floor))
            self.assertEqual(image.pixelColor(2, 0).getRgb()[:3], (255, 255, 255), "opaque lines stay white")
            red = image.pixelColor(3, 0).getRgb()[:3]
            self.assertTrue(red[0] > bg[0] and red[1] < 40, "a half transparent red blends with the background: " + str(red))

    def test_images_without_alpha_and_missing_files_are_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rgb.png"
            QImage(3, 3, QImage.Format_RGB32).save(str(path), "PNG")
            before = path.read_bytes()
            self.assertFalse(self.sc.flatten_alpha(path))
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(self.sc.flatten_alpha(Path(d) / "nothing.png"))

    def test_displayed_bounds_skips_nodes_without_a_display_flag_quietly(self):
        logs: list[str] = []

        class Lop:  # LopNetwork: isDisplayFlagSet を持たない
            def type(self): return types.SimpleNamespace(category=lambda: "obj")
            def path(self): return "/obj/sb/solaris"

        class Container:
            def children(self): return [Lop()]

        fake_hou = types.SimpleNamespace(node=lambda path: Container(), objNodeTypeCategory=lambda: "obj")
        with mock.patch.object(self.sc, "hou", fake_hou), mock.patch.object(self.sc, "_log", lambda message, path=None: logs.append(message)):
            self.assertIsNone(self.sc._displayed_bounds("/obj/sb", None))
        self.assertEqual(logs, [], "no 'failed' line for every capture")


if __name__ == "__main__":
    unittest.main()
