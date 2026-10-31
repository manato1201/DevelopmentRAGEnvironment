"""view_viewport / inspect_geometry の frame / promote_parameter / layout_network / press_button（houdini_tools.py）のテスト。
標準の unittest。Houdini は使わず、test_parm_tools.py の偽の hou（ノード・パラメータ・テンプレート）で動かす。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import base64
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python_panels"))

import houdini_tools as ht  # noqa: E402
from test_parm_tools import SANDBOX, StringParm, Template, make_executor, make_world  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


class ToolListTest(unittest.TestCase):
    def test_new_tools_are_defined_before_the_finishing_pair(self) -> None:
        names = [t["name"] for t in ht.HOUDINI_TOOLS]
        for tool in ("view_viewport", "promote_parameter", "layout_network", "press_button"):
            self.assertIn(tool, names)
            self.assertLess(names.index(tool), names.index("finish_tutorial"))
        self.assertEqual(names[-2:], ["finish_tutorial", "confirm_tutorial"])
        self.assertEqual(len(set(names)), len(names))
        by_name = {t["name"]: t for t in ht.HOUDINI_TOOLS}
        self.assertEqual(by_name["promote_parameter"]["input_schema"]["required"], ["node", "parm"])
        self.assertEqual(by_name["press_button"]["input_schema"]["required"], ["node", "parm"])
        self.assertIn("frame", by_name["inspect_geometry"]["input_schema"]["properties"])
        self.assertIn("frame", by_name["view_viewport"]["input_schema"]["properties"])


class ViewViewportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ex = make_executor(self.hou, self.sandbox)
        self.ex._screenshot_dir = Path(self.tmp.name)
        self.ex.last_screenshot_b64 = None
        self.captures: list[dict] = []
        outer = self

        def capture_viewport(path, width=0, height=0, log_path=None, frame_path=None):
            outer.captures.append({"path": path, "size": (width, height), "frame": outer.hou.frame(), "frame_path": frame_path})
            if outer.capture_ok:
                Path(path).write_bytes(PNG)
            return outer.capture_ok

        self.capture_ok = True
        module = types.ModuleType("screen_capture")
        module.capture_viewport = capture_viewport
        patcher = mock.patch.dict(sys.modules, {"screen_capture": module})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.geo = self.add("geo1", "geo", "Object")
        self.box = self.add("geo1/box1", "box", "Sop", parent=self.geo)

    def test_takes_a_small_picture_and_keeps_it_for_the_agent_loop(self) -> None:
        out = self.ex._tool_view_viewport({})
        self.assertIn("撮影しました", out)
        self.assertEqual(base64.b64decode(self.ex.last_screenshot_b64), PNG)
        self.assertEqual(self.captures[0]["size"], (ht.HoudiniToolExecutor._VIEW_WIDTH, ht.HoudiniToolExecutor._VIEW_HEIGHT))
        self.assertLess(self.captures[0]["size"][0], 1920, "smaller than the final check image: it costs tokens")
        self.assertEqual(self.captures[0]["frame_path"], SANDBOX)

    def test_node_is_shown_and_frame_is_set_then_restored(self) -> None:
        out = self.ex._tool_view_viewport({"node": "geo1/box1", "frame": 24})
        self.assertTrue(self.box.display_set, "the requested node is shown in the viewport")
        self.assertEqual(self.captures[0]["frame"], 24.0, "the picture is taken at the requested frame")
        self.assertEqual(self.hou.frame(), 1.0, "and the playbar goes back")
        self.assertIn("geo1/box1", out)
        self.assertIn("フレーム 24", out)

    def test_frame_is_restored_even_when_the_capture_raises(self) -> None:
        sys.modules["screen_capture"].capture_viewport = mock.Mock(side_effect=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            self.ex._tool_view_viewport({"frame": 100})
        self.assertEqual(self.hou.frame(), 1.0)

    def test_failure_returns_text_and_no_image(self) -> None:
        self.capture_ok = False
        out = self.ex._tool_view_viewport({})
        self.assertIn("失敗", out)
        self.assertIsNone(self.ex.last_screenshot_b64)

    def test_limited_to_eight_pictures_per_generation(self) -> None:
        self.ex.step_log = [{"tool": "view_viewport", "is_error": False, "result": ""}] * 8
        out = self.ex._tool_view_viewport({})
        self.assertIn("8回まで", out)
        self.assertEqual(self.captures, [])
        self.assertIsNone(self.ex.last_screenshot_b64)

    def test_without_a_screenshot_folder(self) -> None:
        self.ex._screenshot_dir = None
        self.assertIn("保存先がありません", self.ex._tool_view_viewport({}))

    def test_an_old_picture_never_leaks_into_a_failed_call(self) -> None:
        self.ex._tool_view_viewport({})
        self.capture_ok = False
        self.ex._tool_view_viewport({})
        self.assertIsNone(self.ex.last_screenshot_b64)

    def test_the_agent_loop_attaches_the_picture_to_the_tool_result(self) -> None:
        try:
            import tutorial_agent
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(str(exc)) from exc

        class StubExecutor:
            step_log: list = []
            pending_finish = None
            finish_data = None
            last_screenshot_b64 = None

            def execute(self, name, args):
                if name == "view_viewport":
                    self.last_screenshot_b64 = base64.b64encode(PNG).decode("ascii")
                    self.finish_data = {}  # このテストは、1周で終える
                    return "撮影しました", False
                return "ok", False

        agent = tutorial_agent.TutorialAgent.__new__(tutorial_agent.TutorialAgent)
        agent._model = tutorial_agent.DEFAULT_MODEL
        agent._progress = lambda _msg: None
        agent.executor = StubExecutor()
        agent._call_api = lambda system, tools, messages: {  # type: ignore[method-assign]
            "content": [{"type": "tool_use", "id": "t1", "name": "view_viewport", "input": {}}],
            "usage": {}, "stop_reason": "tool_use",
        }
        messages: list = [{"role": "user", "content": "x"}]
        agent._run_loop([], [], messages, tutorial_agent.TutorialResult())
        content = messages[-1]["content"][0]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual([b["type"] for b in content], ["text", "image"])
        self.assertIsNone(agent.executor.last_screenshot_b64, "the picture is used once")


class InspectFrameTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.ex = make_executor(self.hou, self.sandbox)
        self.add("geo1", "geo", "Object")
        self.add("geo1/box1", "box", "Sop", parent=self.nodes[f"{SANDBOX}/geo1"])
        self.seen: list[float] = []
        self.ex._inspect_geometry_now = lambda args: (self.seen.append(self.hou.frame()) or "INSPECTED")  # type: ignore[method-assign]

    def test_without_a_frame_nothing_changes(self) -> None:
        self.assertEqual(self.ex._tool_inspect_geometry({"node": "geo1/box1"}), "INSPECTED")
        self.assertEqual(self.seen, [1.0])

    def test_inspects_at_that_frame_and_goes_back(self) -> None:
        out = self.ex._tool_inspect_geometry({"node": "geo1/box1", "frame": 48})
        self.assertEqual(self.seen, [48.0])
        self.assertEqual(self.hou.frame(), 1.0)
        self.assertIn("フレーム 48 の状態", out)
        self.assertTrue(out.endswith("INSPECTED"))

    def test_goes_back_even_when_inspecting_raises(self) -> None:
        self.ex._inspect_geometry_now = mock.Mock(side_effect=RuntimeError("x"))  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            self.ex._tool_inspect_geometry({"node": "geo1/box1", "frame": 5})
        self.assertEqual(self.hou.frame(), 1.0)

    def test_bad_frames_are_refused_without_touching_the_playbar(self) -> None:
        for bad in ("abc", 10**9, -5000):
            out = self.ex._tool_inspect_geometry({"node": "geo1/box1", "frame": bad})
            self.assertTrue("数値" in out or "範囲外" in out, out)
        self.assertEqual(self.seen, [])
        self.assertEqual(self.hou.frame(), 1.0)


class PromoteParameterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.ex = make_executor(self.hou, self.sandbox)
        self.geo = self.add("geo1", "geo", "Object")
        self.scatter = self.add("geo1/scatter1", "scatter::2.0", "Sop", parent=self.geo)
        self.npts = self.scatter.add_parm(Template("npts", "Force Total Count", "Int", default=1000), 250)
        self.scatter.add_tuple(Template("size", "Size", "Float", default=(1.0, 1.0, 1.0), n=3), (2.0, 3.0, 4.0))
        self.scatter.add_parm(Template("file", "File", "String", default=""), "a.bgeo")

    def promote(self, **args) -> str:
        return self.ex._tool_promote_parameter({"node": "geo1/scatter1", "parm": "npts", **args})

    def test_creates_the_parameter_on_the_parent_with_the_current_value_and_references_it(self) -> None:
        out = self.promote()
        self.assertIn("昇格しました: geo1/scatter1.npts → geo1.npts", out)
        promoted = self.geo.parm("npts")
        self.assertIsNotNone(promoted)
        self.assertEqual(promoted.eval(), 250, "the current value moves up (not the default)")
        self.assertEqual(self.npts.expression, 'ch("../npts")')
        self.assertIn("Force Total Count", out)

    def test_name_and_label_and_a_higher_container(self) -> None:
        out = self.promote(name="density", label="Point Density", to="")
        self.assertIsNotNone(self.geo.parm("density"))
        self.assertEqual(self.geo.parm("density").parmTemplate().label(), "Point Density")
        self.assertEqual(self.npts.expression, 'ch("../density")')
        self.assertIn("Point Density", out)
        # サンドボックス直下へ（2つ上）
        self.scatter.add_parm(Template("seed", "Seed", "Int", default=0), 7)
        self.ex._tool_promote_parameter({"node": "geo1/scatter1", "parm": "seed", "to": self.sandbox.path()})
        self.assertEqual(self.scatter.parm("seed").expression, 'ch("../../seed")')
        self.assertEqual(self.sandbox.parm("seed").eval(), 7)

    def test_tuples_move_as_a_whole_and_each_component_references_its_own(self) -> None:
        out = self.promote(parm="size")
        self.assertIn("geo1.size", out)
        comps = list(self.geo.parmTuple("size"))
        self.assertEqual([c.eval() for c in comps], [2.0, 3.0, 4.0])
        self.assertEqual([c.expression for c in self.scatter._tuples["size"]],
                         ['ch("../sizex")', 'ch("../sizey")', 'ch("../sizez")'])

    def test_strings_use_chs_and_keep_the_raw_text(self) -> None:
        self.scatter._parms["file"] = StringParm(Template("file", "File", "String"), "$HIP/a.bgeo")
        self.promote(parm="file")
        self.assertEqual(self.scatter.parm("file").expression, 'chs("../file")')
        self.assertEqual(self.geo.parm("file").eval(), "$HIP/a.bgeo", "not the expanded path")

    def test_refusals(self) -> None:
        self.assertIn("既にあります", (self.promote(), self.promote())[1])
        self.assertIn("祖先", self.ex._tool_promote_parameter({"node": "geo1/scatter1", "parm": "file", "to": "geo1/scatter1"}))
        other = self.add("other", "geo", "Object")
        self.assertIn("祖先", self.ex._tool_promote_parameter({"node": "geo1/scatter1", "parm": "file", "to": "other"}))
        self.assertIsNotNone(other)
        self.assertIn("見つかりません", self.ex._tool_promote_parameter({"node": "geo1/scatter1", "parm": "nope"}))
        self.scatter.add_parm(Template("animated", "Animated", "Float"), 1.0, keyframed=True)
        self.assertIn("式かキーフレーム", self.ex._tool_promote_parameter({"node": "geo1/scatter1", "parm": "animated"}))
        self.scatter.add_parm(Template("ramp1", "Ramp", "Ramp"), 0)
        self.assertIn("昇格できません", self.ex._tool_promote_parameter({"node": "geo1/scatter1", "parm": "ramp1"}))
        self.assertIsNone(self.scatter.parm("animated").__dict__.get("expression"), "a refused promotion changes nothing")

    def test_a_node_directly_under_the_sandbox_promotes_to_the_sandbox(self) -> None:
        top = self.add("grid1", "grid", "Sop")
        top.add_parm(Template("rows", "Rows", "Int", default=10), 20)
        out = self.ex._tool_promote_parameter({"node": "grid1", "parm": "rows"})
        self.assertIn("昇格しました", out)
        self.assertEqual(top.parm("rows").expression, 'ch("../rows")')


class LayoutNetworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.ex = make_executor(self.hou, self.sandbox)
        self.geo = self.add("geo1", "geo", "Object")
        self.box = self.add("geo1/box1", "box", "Sop", parent=self.geo)
        self.matnet = self.add("matnet1", "matnet", "Object")
        self.mat = self.add("matnet1/mat1", "principledshader::2.0", "Vop", parent=self.matnet)

    def test_lays_out_the_sandbox_and_every_container_inside(self) -> None:
        out = self.ex._tool_layout_network({})
        self.assertEqual((self.sandbox.laid_out, self.geo.laid_out, self.matnet.laid_out), (1, 1, 1))
        self.assertEqual((self.box.laid_out, self.mat.laid_out), (0, 0), "leaf nodes are not containers")
        self.assertIn("3 か所", out)
        self.assertIn("（サンドボックス）", out)

    def test_one_container_only(self) -> None:
        self.ex._tool_layout_network({"node": "geo1", "recursive": False})
        self.assertEqual((self.sandbox.laid_out, self.geo.laid_out, self.matnet.laid_out), (0, 1, 0))

    def test_outside_the_sandbox_is_refused_and_empty_is_explained(self) -> None:
        with self.assertRaises(ht.SandboxViolation):
            self.ex._tool_layout_network({"node": "/obj/other"})
        self.sandbox.kids.clear()
        self.assertIn("整列するノードがありません", self.ex._tool_layout_network({}))


class PressButtonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache" / "ai_tutorial_1"
        self.ex = make_executor(self.hou, self.sandbox)
        self.ex._cache_dir = self.cache
        self.geo = self.add("geo1", "geo", "Object")
        self.fc = self.add("geo1/filecache1", "filecache::2.0", "Sop", parent=self.geo)
        file_tpl = Template("file", "Geometry File", "String")
        file_tpl._a["string_type"] = "FileReference"
        self.file = self.fc.add_parm(file_tpl, "")
        self.name_parm = self.fc.add_parm(Template("label", "Label", "String"), "a/b")  # 普通の文字列は、パスでも対象外
        self.execute = self.fc.add_parm(Template("execute", "Save to Disk", "Button"), 0)
        self.reload = self.fc.add_parm(Template("reload", "Reload", "Button"), 0)
        self.execute.on_press = self._write_cache

    def _write_cache(self) -> None:
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / "frame.bgeo.sc").write_bytes(b"x" * 2048)

    def press(self, **args) -> str:
        return self.ex._tool_press_button({"node": "geo1/filecache1", "parm": "execute", **args})

    def test_refuses_while_the_file_points_outside_the_cache_folder(self) -> None:
        self.file.value = "C:/Users/me/Desktop/precious.bgeo.sc"
        out = self.press()
        self.assertIn("許可されたフォルダの外", out)
        self.assertIn(self.cache.as_posix(), out)
        self.assertIn("file = C:/Users/me/Desktop/precious.bgeo.sc", out)
        self.assertEqual(getattr(self.execute, "pressed", 0), 0, "nothing was written")
        self.assertFalse(self.cache.exists())

    def test_an_empty_file_setting_is_treated_as_not_set(self) -> None:
        out = self.press()
        self.assertIn("ボタンを押しました", out)

    def test_presses_when_the_file_is_inside_and_reports_what_was_written(self) -> None:
        self.file.value = (self.cache / "frame.$F4.bgeo.sc").as_posix()
        out = self.press()
        self.assertEqual(self.execute.pressed, 1)
        self.assertIn("ファイルが 1 個増え", out)
        self.assertIn("2 KB", out)

    def test_parent_directory_tricks_do_not_pass(self) -> None:
        self.file.value = (self.cache / ".." / ".." / "evil.bgeo.sc").as_posix()
        self.assertIn("許可されたフォルダの外", self.press())
        sibling = Path(self.tmp.name) / "cache" / "ai_tutorial_1_evil" / "x.bgeo"
        self.file.value = sibling.as_posix()
        self.assertIn("許可されたフォルダの外", self.press(), "a folder whose name merely starts with ours is outside")
        self.assertEqual(getattr(self.execute, "pressed", 0), 0)

    def test_only_allowed_buttons_and_only_buttons(self) -> None:
        out = self.press(parm="reload")
        self.assertIn("押せません", out)
        self.assertIn("execute", out)
        self.assertEqual(getattr(self.reload, "pressed", 0), 0)
        out = self.press(parm="label")
        self.assertIn("ボタンではありません", out)
        self.assertIn("execute, reload", out)

    def test_unavailable_without_a_cache_folder_and_capped(self) -> None:
        self.ex._cache_dir = None
        self.assertIn("使えません", self.press())
        self.ex._cache_dir = self.cache
        self.ex.step_log = [{"tool": "press_button", "is_error": False, "result": ""}] * 10
        self.assertIn("10回まで", self.press())
        self.assertEqual(getattr(self.execute, "pressed", 0), 0)

    def test_errors_and_warnings_from_the_node_are_reported(self) -> None:
        self.fc.errs = ["Unable to write file"]
        self.fc.warns = ["Disk is almost full"]
        out = self.press()
        self.assertIn("[エラー] Unable to write file", out)
        self.assertIn("[警告] Disk is almost full", out)

    def test_a_huge_cache_gets_a_warning(self) -> None:
        with mock.patch.object(ht.HoudiniToolExecutor, "_CACHE_MAX_BYTES", 1024):
            out = self.press()
        self.assertIn("MB を超えました", out)

    def test_executor_decides_the_cache_folder_next_to_the_screenshots(self) -> None:
        source = Path(ht.__file__).read_text(encoding="utf-8")
        self.assertIn('Path(screenshot_dir).parent / "cache" / self._sandbox_name', source)


class CacheSectionTest(unittest.TestCase):
    def test_prompt_only_mentions_press_button_when_there_is_a_real_folder(self) -> None:
        try:
            import tutorial_agent
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(str(exc)) from exc
        agent = tutorial_agent.TutorialAgent.__new__(tutorial_agent.TutorialAgent)
        agent.executor = types.SimpleNamespace(cache_dir=Path("C:/proj/logs/tutorial_agent/cache/ai_tutorial_1"))
        text = agent._cache_section()
        self.assertIn("C:/proj/logs/tutorial_agent/cache/ai_tutorial_1/", text)
        self.assertIn("press_button", text)
        agent.executor = types.SimpleNamespace(cache_dir=None)
        self.assertEqual(agent._cache_section(), "")
        agent.executor = mock.Mock()  # テストの代用品など、本物のパスでないもの
        self.assertEqual(agent._cache_section(), "")
        agent.executor = None
        self.assertEqual(agent._cache_section(), "")


if __name__ == "__main__":
    unittest.main()
