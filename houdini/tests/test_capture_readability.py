"""screen_capture.py の「読める大きさで撮る」部分のテスト（2026-11-17。実証実験の「ノード数が増えると見づらい」「VEX がつぶれる」「値を変える対象が見えない」）。

・範囲の計算・コードの折り返しと分割・タブの選び方は、純粋な関数（Qt も hou も不要）。
・描画（ノード図・コードのカード）は、PySide6 がある環境でだけ確かめる（無ければ飛ばす）。hou は偽物で差し替える。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_capture_readability.py -v
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))
sys.modules.setdefault("hou", types.ModuleType("hou"))

import screen_capture as sc  # noqa: E402

try:
    from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
except ImportError:
    QImage = None


def chain(count: int) -> list[dict]:
    """一本道（上から下へ）の count 個のノードの model。"""
    return [
        {"path": f"/n/{i}", "name": f"node_{i}", "type": "null", "color": (0.5, 0.5, 0.5), "display": False, "render": False,
         "bypass": False, "error": False, "x": 0.0, "inputs": [(f"/n/{i - 1}", 0)] if i else []}
        for i in range(count)
    ]


def old_scale(layer_count: int) -> float:
    """変更前の拡大率の式（下限 0.35。全ノードを 1 枚に収める）。再現用。"""
    layout_h = layer_count * 48 + (layer_count - 1) * 56
    return max(0.35, min((1280 - 80) / 140, (720 - 88) / layout_h, 1.6))


class BeforeAfterTest(unittest.TestCase):
    def test_before_40_nodes_were_unreadable_and_off_canvas(self) -> None:
        """前: 40 ノードの一本道は、拡大率が下限 0.35（名前 3.85pt）に張り付き、図の高さが画面（632）を超えた。"""
        scale = old_scale(40)
        self.assertAlmostEqual(scale, 0.35)
        self.assertLess(11 * scale, 4.0)
        self.assertGreater((40 * 48 + 39 * 56) * scale, 720 - 88)

    def test_after_focus_view_keeps_the_name_size_floor(self) -> None:
        model = chain(40)
        shown, hidden = sc.select_focus_nodes(model, "/n/20")
        self.assertEqual(len(shown) + hidden, 40)
        self.assertIn("/n/20", [n["path"] for n in shown])
        lw, lh, _ = sc.layout_extent(sc._assign_layers(shown))
        scale, fits = sc.diagram_scale(lw, lh, 1280, 720, sc.MIN_FOCUS_SCALE)
        self.assertTrue(fits)
        self.assertGreaterEqual(sc.DIAGRAM_NAME_PT * scale, sc.MIN_NAME_PT)

    def test_all_nodes_do_not_fit_at_the_floor(self) -> None:
        lw, lh, _ = sc.layout_extent(sc._assign_layers(chain(40)))
        self.assertFalse(sc.diagram_scale(lw, lh, 1280, 720, sc.MIN_FOCUS_SCALE)[1])


class SelectFocusNodesTest(unittest.TestCase):
    def test_no_focus_returns_everything(self) -> None:
        model = chain(12)
        shown, hidden = sc.select_focus_nodes(model, None)
        self.assertEqual((len(shown), hidden), (12, 0))
        shown, hidden = sc.select_focus_nodes(model, "/missing")
        self.assertEqual((len(shown), hidden), (12, 0))

    def test_small_graph_is_shown_whole(self) -> None:
        shown, hidden = sc.select_focus_nodes(chain(5), "/n/2")
        self.assertEqual((len(shown), hidden), (5, 0))

    def test_neighbors_come_before_far_nodes(self) -> None:
        shown, _ = sc.select_focus_nodes(chain(40), "/n/20")
        names = {n["name"] for n in shown}
        self.assertTrue({"node_19", "node_20", "node_21"} <= names)
        self.assertNotIn("node_0", names)
        self.assertNotIn("node_39", names)

    def test_edges_to_hidden_nodes_are_dropped(self) -> None:
        shown, _ = sc.select_focus_nodes(chain(40), "/n/20")
        kept = {n["path"] for n in shown}
        for n in shown:
            for source, _idx in n["inputs"]:
                self.assertIn(source, kept)

    def test_wide_fan_in_keeps_focus_and_trims_the_ring(self) -> None:
        """入力が 30 本ある merge でも、注目ノードは必ず残り、名前の下限を守れる数だけにする。"""
        model = [
            {"path": f"/n/s{i}", "name": f"source_{i}", "type": "null", "color": (0.5,) * 3, "display": False, "render": False,
             "bypass": False, "error": False, "x": float(i), "inputs": []}
            for i in range(30)
        ]
        model.append({"path": "/n/merge", "name": "merge1", "type": "merge", "color": (0.5,) * 3, "display": True, "render": False,
                      "bypass": False, "error": False, "x": 0.0, "inputs": [(f"/n/s{i}", i) for i in range(30)]})
        shown, hidden = sc.select_focus_nodes(model, "/n/merge")
        self.assertIn("/n/merge", [n["path"] for n in shown])
        self.assertGreater(hidden, 0)
        lw, lh, _ = sc.layout_extent(sc._assign_layers(shown))
        self.assertTrue(sc.diagram_scale(lw, lh, 1280, 720, sc.MIN_FOCUS_SCALE)[1])


class PlanFocusBoundsTest(unittest.TestCase):
    ITEMS = [
        {"path": "/a", "x": 0.0, "y": 0.0, "inputs": []},
        {"path": "/b", "x": 0.0, "y": -1.5, "inputs": ["/a"]},
        {"path": "/c", "x": 0.0, "y": -3.0, "inputs": ["/b"]},
        {"path": "/far", "x": 60.0, "y": -3.0, "inputs": ["/b"]},
        {"path": "/unrelated", "x": 2.0, "y": 8.0, "inputs": []},
    ]

    def test_focus_and_neighbors_are_in_view(self) -> None:
        (x0, y0, x1, y1), shown, _hidden = sc.plan_focus_bounds(self.ITEMS, "/b")
        self.assertTrue({"/a", "/b", "/c"} <= set(shown))
        for item in self.ITEMS[:3]:
            self.assertTrue(x0 <= item["x"] <= x1 and y0 <= item["y"] <= y1)

    def test_view_is_never_wider_than_the_limit_for_neighbors(self) -> None:
        """遠すぎる前後のノード（x=60）に合わせて広げない（名前が読めなくなる）。"""
        (x0, _y0, x1, _y1), shown, hidden = sc.plan_focus_bounds(self.ITEMS, "/b")
        self.assertNotIn("/far", shown)
        self.assertIn("/far", hidden)
        self.assertLessEqual(x1 - x0, sc.MAX_VIEW_WIDTH + 1e-6)

    def test_view_is_not_zoomed_in_too_far(self) -> None:
        (x0, _y0, x1, _y1), _s, _h = sc.plan_focus_bounds(self.ITEMS[:1], "/a")
        self.assertGreaterEqual(x1 - x0, sc.MIN_VIEW_WIDTH - 1e-6)

    def test_aspect_matches_the_pane(self) -> None:
        for aspect in (16 / 9, 1.0, 2.4):
            (x0, y0, x1, y1), _s, _h = sc.plan_focus_bounds(self.ITEMS, "/b", aspect)
            self.assertAlmostEqual((x1 - x0) / (y1 - y0), aspect, places=3)

    def test_extreme_pane_aspect_does_not_blow_up_the_range(self) -> None:
        """ペインが極端に細い・太いとき（幅 1px など）も、範囲が桁違いに大きくならない。"""
        for aspect in (1e-9, 0.0, -1.0, float("nan"), float("inf"), 1e9):
            (x0, y0, x1, y1), shown, _h = sc.plan_focus_bounds(self.ITEMS, "/b", aspect)
            self.assertLess(x1 - x0, 1000.0, aspect)
            self.assertLess(y1 - y0, 1000.0, aspect)
            self.assertIn("/b", shown)

    def test_unknown_focus_raises(self) -> None:
        with self.assertRaises(ValueError):
            sc.plan_focus_bounds(self.ITEMS, "/nope")

    def test_a_narrow_pane_is_maximized_only_while_capturing_and_always_restored(self) -> None:
        class Pane:
            def __init__(self, maximized=False):
                self.maximized, self.calls = maximized, []

            def isMaximized(self):
                return self.maximized

            def setIsMaximized(self, value):
                self.maximized = value
                self.calls.append(value)

        class Tab:
            def __init__(self, width, pane):
                self._w, self._pane = width, pane

            def qtScreenGeometry(self):
                return types.SimpleNamespace(width=lambda: self._w)

            def pane(self):
                return self._pane

        with mock.patch.object(sc, "_flush_qt_events", lambda: None):
            narrow = Pane()
            with sc.maximized_if_narrow(Tab(612, narrow), None, settle_seconds=0):
                self.assertTrue(narrow.maximized, "wide capture while the block runs")
            self.assertEqual(narrow.calls, [True, False], "restored afterwards")
            wide = Pane()
            with sc.maximized_if_narrow(Tab(1500, wide), None, settle_seconds=0):
                pass
            self.assertEqual(wide.calls, [], "a wide pane is left alone")
            already = Pane(maximized=True)
            with sc.maximized_if_narrow(Tab(612, already), None, settle_seconds=0):
                pass
            self.assertEqual(already.calls, [], "an already-maximized pane is not touched (nor un-maximized)")
            boom = Pane()
            with self.assertRaises(RuntimeError):
                with sc.maximized_if_narrow(Tab(612, boom), None, settle_seconds=0):
                    raise RuntimeError("capture failed")
            self.assertEqual(boom.calls, [True, False], "restored even when the capture raises")

    def test_a_pane_that_cannot_be_maximized_does_not_stop_the_capture(self) -> None:
        class Broken:
            def qtScreenGeometry(self):
                raise RuntimeError("no geometry")

        ran = []
        with sc.maximized_if_narrow(Broken(), None, settle_seconds=0):
            ran.append(1)
        self.assertEqual(ran, [1])

    def test_the_screen_grab_is_retried_before_giving_up_on_the_real_image(self) -> None:
        results = [None, None, "image"]
        with mock.patch.object(sc, "_grab_network_pane", lambda *a, **k: results.pop(0)), mock.patch.object(sc, "_flush_qt_events", lambda: None),                 mock.patch.object(sc.time, "sleep", lambda s: None):
            self.assertEqual(sc._grab_with_retry(object(), None), "image")
        results = [None, None, None]
        with mock.patch.object(sc, "_grab_network_pane", lambda *a, **k: results.pop(0)), mock.patch.object(sc, "_flush_qt_events", lambda: None),                 mock.patch.object(sc.time, "sleep", lambda s: None):
            self.assertIsNone(sc._grab_with_retry(object(), None))
        self.assertEqual(results, [], "tried three times")

    def test_bringing_houdini_to_front_does_nothing_when_it_is_already_active(self) -> None:
        with mock.patch.object(sc, "houdini_is_active", lambda: True):
            self.assertTrue(sc.bring_houdini_to_front(object(), None))

    def test_bringing_houdini_to_front_tries_the_window_and_reports_failure(self) -> None:
        calls = []

        class Window:
            def isMinimized(self):
                return True

            def showNormal(self):
                calls.append("showNormal")

            def raise_(self):
                calls.append("raise")

            def activateWindow(self):
                calls.append("activate")

            def winId(self):
                return 0

        tab = types.SimpleNamespace(qtParentWindow=lambda: Window())
        with mock.patch.object(sc, "houdini_is_active", lambda: False), mock.patch.object(sc, "_flush_qt_events", lambda: None),                 mock.patch.object(sc.time, "sleep", lambda s: None):
            self.assertFalse(sc.bring_houdini_to_front(tab, None, attempts=2))
        self.assertEqual(calls, ["showNormal", "raise", "activate"])


class CodeLayoutTest(unittest.TestCase):
    def test_before_long_lines_were_cut_with_an_ellipsis(self) -> None:
        """前: 右の列（幅 480）に 1365 の長さの 1 行を出すと、読める部分は 3 分の 1 以下で、残りは「…」で消えた。"""
        self.assertLess(480 - 24, 1365 / 2)

    def test_a_huge_input_is_cut_instead_of_hanging(self) -> None:
        """5MB の 1 行でも、数秒で終わる（前は、折り返しのたびに残りを複製し、1 分近くかかった）。"""
        import time
        started = time.time()
        rows = sc.wrap_code_lines("x" * 5_000_000, 60)
        self.assertLess(time.time() - started, 5.0)
        self.assertLessEqual(sum(len(t) for _n, t in rows), sc.MAX_CODE_CHARS * 2)

    def test_long_lines_are_wrapped_not_dropped(self) -> None:
        code = "int n = 600;\n" + "float v = " + "x * " * 40 + "1.0;"
        rows = sc.wrap_code_lines(code, 60)
        self.assertEqual(rows[0], (1, "int n = 600;"))
        self.assertTrue(all(len(text) <= 60 for _n, text in rows))
        self.assertEqual([n for n, _t in rows if n], [1, 2])
        self.assertTrue(any(n is None for n, _t in rows), "wrapped continuation rows have no line number")
        joined = "".join(t.strip() for n, t in rows if n is None)
        self.assertIn("1.0;", joined)

    def test_full_width_comment_counts_two_columns(self) -> None:
        rows = sc.wrap_code_lines("// " + "螺" * 30, 40)
        self.assertGreater(len(rows), 1)

    def test_tabs_become_spaces(self) -> None:
        self.assertEqual(sc.wrap_code_lines("\tx;", 40)[0][1], "    x;")

    def test_paginate_splits_and_reports_hidden_rows(self) -> None:
        rows = [(i, f"line {i}") for i in range(1, 31)]
        pages, hidden = sc.paginate_code(rows, 10, 8, max_pages=4)
        self.assertEqual([len(p) for p in pages], [10, 8, 8, 4])
        self.assertEqual(hidden, 0)
        pages, hidden = sc.paginate_code(rows, 10, 8, max_pages=2)
        self.assertEqual(len(pages), 2)
        self.assertEqual(hidden, 12)

    def test_first_page_holds_fewer_lines_with_more_changes(self) -> None:
        first0, other = sc.code_card_capacity(0)
        first3, other3 = sc.code_card_capacity(3)
        self.assertGreater(first0, first3)
        self.assertEqual(other, other3)
        self.assertGreaterEqual(first3, 8)

    def test_code_font_is_larger_than_before(self) -> None:
        self.assertGreaterEqual(sc.CODE_FONT_PT, 16)  # 前は 11pt

    def test_page_file_names(self) -> None:
        base = Path("step_012_network.png")
        self.assertEqual(sc.extra_page_path(base, 1), base)
        self.assertEqual(sc.extra_page_path(base, 3), Path("step_012_network_p3.png"))
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "step_012_network.png"
            for name in ("step_012_network.png", "step_012_network_p2.png", "step_012_network_p10.png", "step_013_network_p2.png"):
                (Path(d) / name).write_bytes(b"x")
            self.assertEqual([p.name for p in sc.find_extra_pages(base)], ["step_012_network_p2.png", "step_012_network_p10.png"])


class FolderTabTest(unittest.TestCase):
    def test_pick_folder_index(self) -> None:
        self.assertEqual(sc.pick_folder_index(["Transform", "Render", "Misc"], ["Render"]), 1)
        self.assertEqual(sc.pick_folder_index(["Code", "Bindings"], ["Code"]), 0)
        self.assertIsNone(sc.pick_folder_index(["A", "B"], ["Z"]))

    def test_tab_path_and_reveal_use_the_parm_folders(self) -> None:
        class FolderSet:
            def __init__(self) -> None:
                self.value = 0

            def parmTemplate(self):
                return types.SimpleNamespace(folderNames=lambda: ("Transform", "Render", "Misc"))

            def eval(self):
                return (self.value,)

            def set(self, values):
                self.value = values[0]

        folder_set = FolderSet()
        parm = types.SimpleNamespace(
            containingFolders=lambda: ("Render",), containingFolderSetParmTuples=lambda: (folder_set,)
        )
        node = types.SimpleNamespace(parm=lambda name: parm if name == "vm_renderable" else None, parmTuple=lambda name: None)
        self.assertEqual(sc.tab_path_of(node, "vm_renderable"), "Render")
        self.assertEqual(sc.tab_path_of(node, "missing"), "")
        self.assertEqual(sc.reveal_parm_tabs(node, ["vm_renderable"]), 1)
        self.assertEqual(folder_set.value, 1, "the Render tab is brought to the front")
        self.assertEqual(sc.reveal_parm_tabs(node, ["vm_renderable"]), 0, "already shown: nothing to switch")

    def test_with_tab_paths_copies_and_adds_the_tab(self) -> None:
        parm = types.SimpleNamespace(containingFolders=lambda: ("Code",), containingFolderSetParmTuples=lambda: ())
        node = types.SimpleNamespace(parm=lambda name: parm, parmTuple=lambda name: None)
        original = [{"label": "Run Over", "name": "class", "old": "2", "new": "detail"}]
        result = sc.with_tab_paths(node, original)
        self.assertEqual(result[0]["tab"], "Code")
        self.assertNotIn("tab", original[0], "the input is not modified")
        self.assertEqual(sc.with_tab_paths(None, original)[0].get("tab"), None)


class FakeNode:
    def __init__(self, path: str, name: str, inputs: list["FakeNode"] | None = None, y: float = 0.0) -> None:
        self._path, self._name, self._inputs, self._y = path, name, inputs or [], y

    def path(self):
        return self._path

    def name(self):
        return self._name

    def position(self):
        return (0.0, self._y)

    def inputConnections(self):
        return [types.SimpleNamespace(inputNode=lambda n=n: n, inputIndex=lambda: 0) for n in self._inputs]


class FakeNetwork:
    def __init__(self, count: int) -> None:
        self._nodes: list[FakeNode] = []
        for i in range(count):
            self._nodes.append(FakeNode(f"/obj/geo1/node_{i}", f"node_{i}", [self._nodes[-1]] if self._nodes else [], -1.5 * i))

    def children(self):
        return list(self._nodes)


@unittest.skipIf(QImage is None, "PySide6 がないため、描画のテストを飛ばす")
class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def _render(self, count: int, focus: str | None, tmp: Path) -> tuple[bool, Path]:
        network = FakeNetwork(count)
        out = tmp / "net.png"
        with mock.patch.object(sc.hou, "node", create=True, return_value=network):
            ok = sc.render_network_diagram(out, "/obj/geo1", focus, "cook OK", log_path=tmp / "log.txt")
        return ok, out

    def test_focus_diagram_of_a_40_node_network_keeps_names_readable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ok, out = self._render(40, "/obj/geo1/node_20", Path(d))
            self.assertTrue(ok)
            image = QImage(str(out))
            self.assertEqual((image.width(), image.height()), (1280 * sc.RENDER_SCALE, 720 * sc.RENDER_SCALE))
            meta = sc.read_capture_meta(out)
            self.assertEqual(meta["nodes_total"], 40)
            self.assertLess(meta["nodes_shown"], 40)
            self.assertTrue(meta["fits"])
            self.assertGreaterEqual(meta["name_pt"], sc.MIN_NAME_PT)

    def test_focus_node_beyond_the_overview_limit_is_still_drawn_readably(self) -> None:
        """全体図は先頭 60 個までしか読まない。注目ノードが 61 個目以降でも、注目ノードの図は、そのノードを中心に描く。"""
        with tempfile.TemporaryDirectory() as d:
            ok, out = self._render(100, "/obj/geo1/node_80", Path(d))
            self.assertTrue(ok)
            meta = sc.read_capture_meta(out)
            self.assertEqual(meta["nodes_total"], 100)
            self.assertLess(meta["nodes_shown"], 100)
            self.assertTrue(meta["fits"])
            self.assertGreaterEqual(meta["name_pt"], sc.MIN_NAME_PT)

    def test_overview_of_a_40_node_network_stays_on_the_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ok, out = self._render(40, None, Path(d))
            self.assertTrue(ok)
            meta = sc.read_capture_meta(out)
            self.assertEqual(meta["nodes_shown"], 40)
            self.assertTrue(meta["overview"])
            self.assertTrue(meta["fits"], "全体図は、拡大率を下げて、画面の中に収める（前は、はみ出した）")
            self.assertFalse(meta["readable"], "40 ノードの全体図では、名前は読めない大きさになる（だから、各手順は注目ノードの図にする）")

    def test_code_cards_are_split_and_written(self) -> None:
        code = "\n".join(f"float v{i} = chf(\"p{i}\") * (rand(i + seed * 31.7) - 0.5) + noise(@P * 3.0 + {i}) * 12.0;" for i in range(40))
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "step_003_network.png"
            stale = Path(d) / "step_003_network_p9.png"
            stale.write_bytes(b"old")
            pages = sc.render_code_cards(
                out, "/obj/geo1", "vortex_points", "Attribute Wrangle",
                [{"label": "Run Over", "name": "class", "old": "2", "new": "Detail (only once)", "tab": "Code"}],
                {"label": "VEXpression", "name": "snippet", "new": code, "tab": "Code"},
            )
            self.assertGreaterEqual(len(pages), 2)
            self.assertEqual(pages[0], out)
            self.assertFalse(stale.exists(), "stale pages from an earlier run are removed")
            for page in pages:
                image = QImage(str(page))
                self.assertEqual(image.width(), 1280 * sc.RENDER_SCALE)
            meta = sc.read_capture_meta(out)
            self.assertEqual(meta["kind"], "code_card")
            self.assertEqual(meta["pages"], len(pages))
            self.assertEqual(meta["lines_total"], 40)
            self.assertEqual([p.name for p in sc.find_extra_pages(out)], [p.name for p in pages[1:]])


class RealScreenFixes20261120Test(unittest.TestCase):
    """2026-11-20 の実機の画像で見つけた不具合: 最大化が効かない・上端のノードが帯に隠れる・格子だけのビューポート・小さく映る作ったもの。"""

    ITEMS = [
        {"path": "/a", "x": 0.0, "y": 0.0, "inputs": []},
        {"path": "/b", "x": 0.0, "y": -1.5, "inputs": ["/a"]},
        {"path": "/c", "x": 0.0, "y": -3.0, "inputs": ["/b"]},
    ]

    def test_the_top_node_is_placed_below_the_path_bar_overlay(self) -> None:
        (x0, y0, x1, y1), shown, _h = sc.plan_focus_bounds(self.ITEMS, "/b", 16 / 9)
        visible_top = y1 - sc.NETWORK_TOP_OVERLAY * (y1 - y0)
        self.assertLess(max(i["y"] for i in self.ITEMS), visible_top, "the top node is under the overlay band otherwise (cut off in the real image)")
        self.assertEqual(set(shown), {"/a", "/b", "/c"})
        (_a, ay0, _b, ay1), _s, _h = sc.plan_focus_bounds(self.ITEMS, "/b", 16 / 9, top_overlay=0.0)
        self.assertGreater(y1 - y0, ay1 - ay0, "the range is taller than without the overlay")

    def test_an_overlay_never_changes_the_aspect(self) -> None:
        for aspect in (16 / 9, 1.0, 0.6):
            (x0, y0, x1, y1), _s, _h = sc.plan_focus_bounds(self.ITEMS, "/b", aspect)
            self.assertAlmostEqual((x1 - x0) / (y1 - y0), aspect, places=3)

    def test_a_node_under_the_overlay_counts_as_outside(self) -> None:
        items = self.ITEMS + [{"path": "/up", "x": 0.0, "y": 0.9, "inputs": []}]
        (x0, y0, x1, y1), _s, hidden = sc.plan_focus_bounds(items, "/b", 16 / 9)
        visible_top = y1 - sc.NETWORK_TOP_OVERLAY * (y1 - y0)
        if items[-1]["y"] > visible_top:
            self.assertIn("/up", hidden)

    def test_waiting_for_the_ui_returns_when_the_condition_holds_or_time_runs_out(self) -> None:
        state = {"n": 0}

        def grows() -> bool:
            state["n"] += 1
            return state["n"] >= 3

        with mock.patch.object(sc, "_flush_qt_events", lambda: None):
            self.assertTrue(sc._wait_for_ui(grows, 2.0))
            self.assertFalse(sc._wait_for_ui(lambda: False, 0.05))
            self.assertTrue(sc._wait_for_ui(lambda: True, 0))
            self.assertFalse(sc._wait_for_ui(lambda: 1 / 0, 0.05), "an exception in the condition is a no")

    def test_the_ui_is_driven_through_houdinis_wait_until_when_it_exists(self) -> None:
        calls = []
        fake_ui = types.SimpleNamespace(waitUntil=lambda cb: calls.append(cb()))
        with mock.patch.object(sc.hou, "ui", fake_ui, create=True), mock.patch.object(sc, "_flush_qt_events", lambda: None):
            sc._wait_for_ui(lambda: False, 0.05)
        self.assertTrue(calls, "hou.ui.waitUntil was used")

    def test_maximizing_waits_until_the_pane_is_really_wider_and_says_so_when_it_is_not(self) -> None:
        class Pane:
            def __init__(self):
                self.maximized, self.tab = False, None

            def isMaximized(self):
                return self.maximized

            def setIsMaximized(self, value):
                self.maximized = value

        class Tab:
            def __init__(self, pane, grows):
                self.pane_obj, self.grows = pane, grows
                pane.tab = self
                self.reads_after = 0

            def qtScreenGeometry(self):
                if self.pane_obj.maximized:
                    self.reads_after += 1
                wide = self.grows and self.pane_obj.maximized and self.reads_after >= 3
                return types.SimpleNamespace(width=lambda: 1800 if wide else 612)

            def pane(self):
                return self.pane_obj

        messages = []
        with mock.patch.object(sc, "_flush_qt_events", lambda: None), mock.patch.object(sc, "_log", lambda line, path=None: messages.append(line)):
            grown = Tab(Pane(), True)
            with sc.maximized_if_narrow(grown, None, settle_seconds=1.0):
                self.assertEqual(grown.qtScreenGeometry().width(), 1800)
            self.assertTrue(any("612px -> 1800px" in m for m in messages))
            stuck = Tab(Pane(), False)
            with sc.maximized_if_narrow(stuck, None, settle_seconds=0.1):
                pass
            self.assertTrue(any("did not get wider" in m for m in messages))

    def test_a_narrow_grab_is_not_stretched_to_1280(self) -> None:
        self.assertEqual(sc.fit_pane_size(612, 386, min_width=min(612, sc.PANE_MIN_WIDTH)), (612, 386))
        self.assertEqual(sc.fit_pane_size(2000, 1000, min_width=min(2000, sc.PANE_MIN_WIDTH)), (2000, 1000))

    def test_fit_zoom_zooms_in_on_small_objects_and_out_on_big_ones(self) -> None:
        self.assertLess(sc.fit_zoom(0.2, 0.15), 1.0)
        self.assertEqual(sc.fit_zoom(0.2, 0.15), 0.5, "clamped")
        self.assertAlmostEqual(sc.fit_zoom(0.88, 0.5), 1.0, places=3)
        self.assertGreater(sc.fit_zoom(0.95, 1.4), 1.0, "an object taller than the band is moved back")
        self.assertEqual(sc.fit_zoom(0, 0), 1.0)

    def test_refine_framing_reframes_by_the_measured_size(self) -> None:
        class Box:
            def minvec(self):
                return (0.0, 0.0, 0.0)

            def maxvec(self):
                return (2.0, 2.0, 2.0)

            def sizevec(self):
                return (2.0, 2.0, 2.0)

        class View:
            def __init__(self, extent):
                self.framed, self.extent = [], extent

            def size(self):
                return (0, 0, 800, 1000)

            def mapToScreen(self, v):
                return (400.0 + (v[0] - 1) * self.extent, 500.0 + (v[1] - 1) * self.extent)  # 画素

            def frameBoundingBox(self, box):
                self.framed.append(box)

        class FakeBB:
            def __init__(self, *a):
                self.a = a

        fake_hou = types.SimpleNamespace(Vector3=lambda x, y, z: (x, y, z), BoundingBox=FakeBB)
        view = View(extent=60.0)  # 画面で、1 辺が 120 画素（幅 800 の 15%）
        with mock.patch.object(sc, "hou", fake_hou):
            self.assertTrue(sc._refine_framing(view, Box(), 0.3, (1.0, 1.0, 1.0), 2.0, None))
        self.assertEqual(len(view.framed), 1, "reframed")
        low, high = view.framed[0].a[:3], view.framed[0].a[3:]
        self.assertLess(high[0] - low[0], 2 * (1.0 + 0.3) * 2.0, "tighter than the uniform widening")
        class NoMap:  # mapToScreen が無い Houdini
            framed: list = []

            def size(self):
                return (0, 0, 800, 1000)

            def frameBoundingBox(self, box):
                self.framed.append(box)

        view2 = NoMap()
        with mock.patch.object(sc, "hou", fake_hou):
            self.assertFalse(sc._refine_framing(view2, Box(), 0.3, (1.0, 1.0, 1.0), 2.0, None))
        self.assertEqual(view2.framed, [])

    def test_an_empty_viewport_is_detected_only_when_it_is_certain(self) -> None:
        class Geo:
            def __init__(self, n):
                self.n = n

            def points(self):
                return range(self.n)

        class Disp:
            def __init__(self, n):
                self.n = n

            def geometry(self):
                return Geo(self.n)

        class Child:
            def __init__(self, shown, n, category="obj"):
                self.shown, self.n, self.category = shown, n, category

            def type(self):
                return types.SimpleNamespace(category=lambda: self.category)

            def isDisplayFlagSet(self):
                return self.shown

            def displayNode(self):
                return Disp(self.n)

        def hou_with(children):
            container = types.SimpleNamespace(children=lambda: children)
            return types.SimpleNamespace(node=lambda p: container if p == "/obj/sb" else None, objNodeTypeCategory=lambda: "obj")

        with mock.patch.object(sc, "hou", hou_with([Child(True, 0)])):
            self.assertTrue(sc.viewport_is_empty("/obj/sb"))
        with mock.patch.object(sc, "hou", hou_with([Child(True, 400)])):
            self.assertFalse(sc.viewport_is_empty("/obj/sb"))
        with mock.patch.object(sc, "hou", hou_with([Child(True, 0), Child(True, 5)])):
            self.assertFalse(sc.viewport_is_empty("/obj/sb"))
        with mock.patch.object(sc, "hou", hou_with([Child(False, 100)])):
            self.assertFalse(sc.viewport_is_empty("/obj/sb"), "nothing is displayed at all: cannot say (camera may show other things)")
        with mock.patch.object(sc, "hou", hou_with([Child(True, 0, category="lop")])):
            self.assertFalse(sc.viewport_is_empty("/obj/sb"))
        with mock.patch.object(sc, "hou", hou_with([])):
            self.assertFalse(sc.viewport_is_empty("/obj/sb"))
            self.assertFalse(sc.viewport_is_empty("/missing"))
            self.assertFalse(sc.viewport_is_empty(None))

    def test_the_step_still_is_skipped_for_an_empty_viewport_only_when_asked(self) -> None:
        with mock.patch.object(sc, "viewport_is_empty", lambda *a, **k: True), mock.patch.object(sc, "_log", lambda *a, **k: None):
            with tempfile.TemporaryDirectory() as d:
                self.assertFalse(sc.capture_viewport(Path(d) / "v.png", frame_path="/obj/sb", skip_if_empty=True))


if __name__ == "__main__":
    unittest.main()
