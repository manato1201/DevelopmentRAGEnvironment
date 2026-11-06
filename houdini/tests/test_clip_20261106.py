"""動画に混ぜる、動く様子の約10秒のクリップ（2026-11-06）のテスト。Houdini は偽物（fake hou）で動かす。

  ・plan_clip: 再生範囲を120コマ以内に収め、約10秒になる fps を決める（純粋な関数）
  ・scene_is_animated: 表示中のジオメトリが、フレームで変わるか（動かない＝静止画のまま）
  ・capture_viewport_clip: 間引き（frameIncrement）と開始フレームを flipbook に渡す
  ・HoudiniToolExecutor._capture_cook_clip: 動く→約10秒、動かない→撮らない、判定不能・上限→従来の短いクリップ
実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
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

import houdini_tools as ht  # noqa: E402
import screen_capture as sc  # noqa: E402
import video_script as vs  # noqa: E402


class PlanClipTest(unittest.TestCase):
    def test_default_houdini_range_gives_about_ten_seconds(self):
        plan = sc.plan_clip(1, 240)
        self.assertEqual((plan["step"], plan["frames"], plan["fps"]), (2, 120, 12))
        self.assertEqual(plan["seconds"], 10.0)
        self.assertEqual((plan["start"], plan["end"]), (1, 239))

    def test_short_ranges_are_played_slower_but_never_below_the_floor(self):
        plan = sc.plan_clip(1, 100)
        self.assertEqual((plan["step"], plan["frames"], plan["fps"]), (1, 100, 10))
        self.assertEqual(plan["seconds"], 10.0)
        slow = sc.plan_clip(1, 48)
        self.assertEqual((slow["frames"], slow["fps"]), (48, sc.LONG_CLIP_FPS_MIN))
        self.assertEqual(slow["seconds"], 8.0)

    def test_long_ranges_are_thinned_to_the_frame_cap(self):
        plan = sc.plan_clip(1, 1000)
        self.assertLessEqual(plan["frames"], sc.LONG_CLIP_FRAMES)
        self.assertEqual(plan["step"], 9)
        self.assertEqual(plan["fps"], 11)  # 112コマ ÷ 10秒
        self.assertLessEqual(plan["end"], 1000)

    def test_a_single_frame_range(self):
        plan = sc.plan_clip(5, 5)
        self.assertEqual((plan["frames"], plan["step"], plan["start"], plan["end"]), (1, 1, 5, 5))

    def test_the_cap_and_size_are_modest(self):
        self.assertLessEqual(sc.LONG_CLIP_FRAMES, 150)
        self.assertLess(sc.LONG_CLIP_WIDTH * sc.LONG_CLIP_HEIGHT, sc.CLIP_WIDTH * sc.CLIP_HEIGHT, "the long clip is smaller than the short one")


# ── 偽の Houdini ───────────────────────────────────────────────────────────────

class _Vec:
    def __init__(self, *v): self.v = list(v)
    def __getitem__(self, i): return self.v[i]
    def __mul__(self, other): return _Vec(*self.v)  # worldTransform は単位行列


class _Box:
    def __init__(self, lo=(0, 0, 0), hi=(1, 1, 1)): self.lo, self.hi = list(lo), list(hi)
    def isValid(self): return True
    def minvec(self): return _Vec(*self.lo)
    def maxvec(self): return _Vec(*self.hi)
    def sizevec(self): return _Vec(*[hi - lo for lo, hi in zip(self.lo, self.hi)])
    def center(self): return _Vec(*[(hi + lo) / 2 for lo, hi in zip(self.lo, self.hi)])


class _BoundingBox(_Box):
    def __init__(self, x0, y0, z0, x1, y1, z1): super().__init__((x0, y0, z0), (x1, y1, z1))
    def enlargeToContain(self, p):
        for i in range(3):
            self.lo[i] = min(self.lo[i], p[i])
            self.hi[i] = max(self.hi[i], p[i])


class _Geo:
    def __init__(self, world): self.world = world
    def boundingBox(self): return self.world.box()
    def intrinsicValue(self, name): return self.world.points()


class _Child:
    def __init__(self, world): self.world = world
    def type(self): return types.SimpleNamespace(category=lambda: "obj")
    def isDisplayFlagSet(self): return True
    def displayNode(self): return types.SimpleNamespace(geometry=lambda: _Geo(self.world))
    def worldTransform(self): return None
    def path(self): return "/obj/sb/geo"


class FakeWorld:
    """frame に応じて、境界ボックスと点の数が変わる（または変わらない）世界。"""

    def __init__(self, animated: bool, range_=(1.0, 240.0), empty_from: float | None = None):
        self.animated, self.frame_now, self.range_ = animated, 1.0, range_
        self.empty_from = empty_from  # このフレーム以降は、ジオメトリが空（燃え尽きた・エラー）
        self.set_frames: list[float] = []

    def is_empty(self): return self.empty_from is not None and self.frame_now >= self.empty_from

    def box(self):
        if self.is_empty():
            invalid = _Box()
            invalid.isValid = lambda: False
            return invalid
        grow = (self.frame_now / 24.0) if self.animated else 0.0
        return _Box((0, 0, 0), (1 + grow, 1 + grow, 1))

    def points(self): return int(100 + (self.frame_now * 5 if self.animated else 0))

    def hou(self):
        world = self
        container = types.SimpleNamespace(children=lambda: [_Child(world)])

        def set_frame(f):
            world.frame_now = f
            world.set_frames.append(f)

        return types.SimpleNamespace(
            frame=lambda: world.frame_now, setFrame=set_frame,
            playbar=types.SimpleNamespace(playbackRange=lambda: world.range_),
            node=lambda path: container, objNodeTypeCategory=lambda: "obj",
            BoundingBox=_BoundingBox, Vector3=lambda x, y, z: _Vec(x, y, z),
        )


class PlaybackRangeTest(unittest.TestCase):
    def test_reads_the_playback_range_or_falls_back_to_the_current_frame(self):
        world = FakeWorld(True, range_=(1.0, 120.0))
        with mock.patch.object(sc, "hou", world.hou()):
            self.assertEqual(sc.playback_range(), (1.0, 120.0))
        broken = world.hou()
        broken.playbar = types.SimpleNamespace(playbackRange=mock.Mock(side_effect=RuntimeError("no playbar")))
        broken.frame = lambda: 9.0
        with mock.patch.object(sc, "hou", broken):
            self.assertEqual(sc.playback_range(), (9.0, 9.0))


class SceneIsAnimatedTest(unittest.TestCase):
    def check(self, animated):
        world = FakeWorld(animated)
        with mock.patch.object(sc, "hou", world.hou()):
            result = sc.scene_is_animated("/obj/sb", 1.0, 240.0)
        return world, result

    def test_a_moving_scene_is_animated_and_the_frame_goes_back(self):
        world, result = self.check(True)
        self.assertTrue(result)
        self.assertEqual(world.frame_now, 1.0, "the playhead is restored")
        self.assertEqual(world.set_frames[:3], [1.0, 120.5, 240.0], "start, middle and end are looked at")

    def test_a_static_scene_is_not_animated(self):
        world, result = self.check(False)
        self.assertIs(result, False)
        self.assertEqual(world.frame_now, 1.0)

    def test_a_single_frame_range_is_not_animated_and_touches_nothing(self):
        world = FakeWorld(True)
        with mock.patch.object(sc, "hou", world.hou()):
            self.assertIs(sc.scene_is_animated("/obj/sb", 5.0, 5.0), False)
        self.assertEqual(world.set_frames, [])

    def test_unknown_when_nothing_is_displayed_or_the_api_fails(self):
        world = FakeWorld(True)
        fake = world.hou()
        fake.node = lambda path: types.SimpleNamespace(children=lambda: [])
        with mock.patch.object(sc, "hou", fake):
            self.assertIsNone(sc.scene_is_animated("/obj/sb", 1.0, 240.0), "no displayed geometry: can not tell")
        self.assertEqual(world.frame_now, 1.0)
        fake.setFrame = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.object(sc, "hou", fake):
            self.assertIsNone(sc.scene_is_animated("/obj/sb", 1.0, 240.0))


class EmptyGeometryTest(unittest.TestCase):
    """燃え尽きて空になるフレームがあっても、「動く」と判定する（2026-11-06: None になり、短いクリップに落ちていた）。"""

    def test_a_scene_that_burns_out_is_animated(self):
        world = FakeWorld(False, empty_from=200.0)  # 形は変わらないが、終わりでは空
        with mock.patch.object(sc, "hou", world.hou()):
            self.assertIs(sc.scene_is_animated("/obj/sb", 1.0, 240.0), True)

    def test_a_scene_that_is_empty_all_the_time_is_not_animated(self):
        world = FakeWorld(True, empty_from=0.0)  # エラーのクック: ずっと空
        with mock.patch.object(sc, "hou", world.hou()):
            self.assertIs(sc.scene_is_animated("/obj/sb", 1.0, 240.0), False)
        self.assertEqual(world.frame_now, 1.0)

    def test_the_empty_signature_needs_a_displayed_object(self):
        world = FakeWorld(True)
        fake = world.hou()
        fake.node = lambda path: types.SimpleNamespace(children=lambda: [])
        with mock.patch.object(sc, "hou", fake):
            self.assertFalse(sc._has_displayed_object("/obj/sb"))
            self.assertIsNone(sc._displayed_signature("/obj/sb", None))


# ── flipbook への指示 ─────────────────────────────────────────────────────────

class CaptureClipTest(unittest.TestCase):
    def run_capture(self, *, increment_supported=True, **kwargs):
        calls: dict = {}

        class Settings:
            def stash(self): return self
            def frameRange(self, rng): calls.setdefault("ranges", []).append(tuple(rng))
            def output(self, path): calls["output"] = path
            def outputToMPlay(self, on): pass
            def resolution(self, size): calls["resolution"] = tuple(size)

        if increment_supported:
            Settings.frameIncrement = lambda self, n: calls.__setitem__("increment", n)
        settings = Settings()
        viewport = types.SimpleNamespace(size=lambda: (0, 0, 1600, 900))
        viewer = types.SimpleNamespace(
            curViewport=lambda: viewport, flipbookSettings=lambda: settings,
            flipbook=lambda vp, st: None,
        )
        fake = types.SimpleNamespace(
            ui=types.SimpleNamespace(paneTabOfType=lambda t: viewer), paneTabType=types.SimpleNamespace(SceneViewer="sv"),
            frame=lambda: 7.0, setFrame=lambda f: calls.__setitem__("restored", f),
        )
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sc, "hou", fake), mock.patch.object(sc, "_frame_view", lambda *a, **k: "all"):
            frames, fps = sc.capture_viewport_clip(Path(d), "clip", **kwargs)
            calls["result"] = (frames, fps)
        return calls

    def test_start_frame_and_step_are_passed_to_the_flipbook(self):
        calls = self.run_capture(frame_count=120, fps=12, start_frame=1, frame_step=2, width=640, height=360)
        self.assertEqual(calls["ranges"][0], (1, 239))
        self.assertEqual(calls["increment"], 2)
        self.assertEqual(calls["resolution"][0], 640)
        self.assertEqual(calls["restored"], 7.0, "the playhead goes back to where it was")

    def test_without_arguments_it_is_the_old_short_clip(self):
        calls = self.run_capture()
        self.assertEqual(calls["ranges"][0], (7.0, 22.0), "16 frames from the current frame")
        self.assertNotIn("increment", calls)

    def test_old_builds_without_frame_increment_still_capture_the_same_number_of_frames(self):
        calls = self.run_capture(increment_supported=False, frame_count=120, start_frame=1, frame_step=2)
        self.assertEqual(calls["ranges"][-1], (1, 120))


# ── 手順ごとの判断 ────────────────────────────────────────────────────────────

class CookClipDecisionTest(unittest.TestCase):
    def setUp(self):
        self.ex = ht.HoudiniToolExecutor.__new__(ht.HoudiniToolExecutor)
        self.ex.sandbox_path = "/obj/sb"
        self.ex._screenshot_dir = Path("shots")
        self.ex._long_clips = 0
        self.calls: list[dict] = []
        outer = self

        def clip(output_dir, base, **kwargs):
            outer.calls.append({"base": base, **kwargs})
            return [Path(f"{base}.{i:04d}.png") for i in range(kwargs.get("frame_count", 16))], kwargs.get("fps", 12)

        self.sc = types.SimpleNamespace(
            playback_range=lambda: (1.0, 240.0), plan_clip=sc.plan_clip, scene_is_animated=lambda *a, **k: True,
            capture_viewport_clip=clip, _log=lambda *a, **k: None,
            LONG_CLIP_WIDTH=640, LONG_CLIP_HEIGHT=360,
        )

    def test_an_animated_scene_gets_a_ten_second_clip(self):
        frames, fps = self.ex._capture_cook_clip(self.sc, 5, None)
        self.assertEqual((len(frames), fps), (120, 12))
        self.assertEqual(self.calls[0]["frame_step"], 2)
        self.assertEqual(self.calls[0]["start_frame"], 1)
        self.assertEqual(self.ex._long_clips, 1)

    def test_a_static_scene_gets_no_clip_at_all(self):
        self.sc.scene_is_animated = lambda *a, **k: False
        self.assertEqual(self.ex._capture_cook_clip(self.sc, 5, None), ([], 0))
        self.assertEqual(self.calls, [], "no flipbook is run: the still picture is enough")

    def test_when_it_cannot_tell_the_old_short_clip_is_kept(self):
        self.sc.scene_is_animated = lambda *a, **k: None
        frames, fps = self.ex._capture_cook_clip(self.sc, 5, None)
        self.assertEqual((len(frames), fps), (16, 12))
        self.assertNotIn("frame_step", self.calls[0])

    def test_when_it_cannot_tell_and_nothing_is_displayed_nothing_is_filmed(self):
        self.sc.scene_is_animated = lambda *a, **k: None
        self.sc._displayed_bounds = lambda path, log: None
        self.assertEqual(self.ex._capture_cook_clip(self.sc, 5, None), ([], 0))
        self.assertEqual(self.calls, [], "an empty grid is not worth 16 frames")

    def test_when_it_cannot_tell_but_something_is_displayed_the_short_clip_is_kept(self):
        self.sc.scene_is_animated = lambda *a, **k: None
        self.sc._displayed_bounds = lambda path, log: object()
        self.assertEqual(len(self.ex._capture_cook_clip(self.sc, 5, None)[0]), 16)

    def test_when_planning_raises_the_old_short_clip_is_kept(self):
        self.sc.playback_range = mock.Mock(side_effect=RuntimeError("no playbar"))
        frames, _ = self.ex._capture_cook_clip(self.sc, 5, None)
        self.assertEqual(len(frames), 16)

    def test_only_a_few_long_clips_per_generation(self):
        sizes = [len(self.ex._capture_cook_clip(self.sc, i, None)[0]) for i in range(1, 6)]
        self.assertEqual(sizes, [120, 120, 120, 16, 16])
        self.assertEqual(self.ex._long_clips, ht.HoudiniToolExecutor._LONG_CLIP_MAX)

    def test_a_failed_long_clip_falls_back_to_the_short_one(self):
        original = self.sc.capture_viewport_clip
        self.sc.capture_viewport_clip = lambda out, base, **k: ([], 0) if "frame_step" in k else original(out, base, **k)
        frames, _ = self.ex._capture_cook_clip(self.sc, 5, None)
        self.assertEqual(len(frames), 16)


# ── 自己確認の画像は、動く題材では途中のフレームで撮る ──────────────────────────────

class MidFrameTest(unittest.TestCase):
    def setUp(self):
        self.ex = ht.HoudiniToolExecutor.__new__(ht.HoudiniToolExecutor)
        self.ex.sandbox_path = "/obj/sb"

    def test_an_animated_scene_is_checked_at_the_middle_of_the_range(self):
        fake = types.SimpleNamespace(playback_range=lambda: (1.0, 240.0), scene_is_animated=lambda *a: True, _log=lambda *a: None)
        self.assertEqual(self.ex._mid_frame_if_animated(fake, None), 120.0)

    def test_a_static_or_unknown_scene_stays_on_the_current_frame(self):
        for verdict in (False, None):
            fake = types.SimpleNamespace(playback_range=lambda: (1.0, 240.0), scene_is_animated=lambda *a, v=verdict: v, _log=lambda *a: None)
            self.assertIsNone(self.ex._mid_frame_if_animated(fake, None))

    def test_a_failure_never_raises(self):
        def boom(*a): raise RuntimeError("no playbar")
        fake = types.SimpleNamespace(playback_range=boom, scene_is_animated=boom, _log=lambda *a: None)
        self.assertIsNone(self.ex._mid_frame_if_animated(fake, None))


class KatakanaFixTest(unittest.TestCase):
    def test_a_mangled_wrangle_is_repaired(self):
        self.assertEqual(vs.to_katakana("アトリビュートランglを作り、名前をburn_wrにします。"), "アトリビュートラングルを作り、名前をburn_wrにします。")
        self.assertEqual(vs.to_katakana("ランglow_fxを作る"), "ランglow_fxを作る", "names that only start like it are left alone")

    def test_node_labels_are_read_in_katakana(self):
        self.assertEqual(vs.to_katakana("Blastノードを作る"), "ブラストノードを作る")
        self.assertEqual(vs.to_katakana("Attribute Createを作る"), "アトリビュートクリエイトを作る")

    def test_the_create_template_has_no_english_left(self):
        entry = {"step": 9, "tool": "create_node", "result": "「Blast」ノード（blast）を作り、名前を ash_blast にする"}
        text = vs._template_step(entry, set(), True)["narration"]
        self.assertIn("ブラスト", text)
        self.assertNotIn("Blast", text)


# ── 台本とエージェントへの指示 ─────────────────────────────────────────────────

class PromptsTest(unittest.TestCase):
    def test_the_script_writer_is_told_which_steps_have_a_moving_picture(self):
        steps = [
            {"step": 1, "tool": "cook_node", "result": "x を評価", "viewport_clip_frames": ["f"] * 120, "viewport_clip_fps": 12},
            {"step": 2, "tool": "cook_node", "result": "y を評価", "viewport_clip_frames": ["f"] * 16, "viewport_clip_fps": 12},
            {"step": 3, "tool": "create_node", "result": "z を作る"},
        ]
        text = vs.build_user_prompt("t", "x", steps, None, "basic")
        self.assertIn("約10秒の動く映像が再生される", text)
        self.assertEqual(text.count('"動く映像"'), 1, "the 1.3 second clip is not announced")
        for level in ("basic", "applied", "advanced"):
            self.assertIn("「動く映像」がある手順", vs.system_prompt(level))

    def test_the_agent_is_asked_to_build_moving_results_for_moving_topics(self):
        import tutorial_agent as ta

        self.assertIn("時間で動く題材", ta._SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("約10秒の映像", ta._SYSTEM_PROMPT_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
