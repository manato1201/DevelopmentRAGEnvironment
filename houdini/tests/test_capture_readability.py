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

    def test_prefer_diagram_for_narrow_panes(self) -> None:
        self.assertTrue(sc.prefer_diagram(580, 12))
        self.assertFalse(sc.prefer_diagram(1400, 12))
        self.assertFalse(sc.prefer_diagram(580, 0))


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


if __name__ == "__main__":
    unittest.main()
