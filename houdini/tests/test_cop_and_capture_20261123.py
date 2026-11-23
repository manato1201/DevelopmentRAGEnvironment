"""2026-11-23 の実機の記録を受けた、COP の生成の失敗と、動画の画像のテスト。

実機の記録（チュートリアル生成を COP（Copernicus）でやったとき）:
  ・「The OpenCL device has run out of memory」が出て、そのあとの撮影（実画面）が、すべて失敗して、描き直した簡易の図になった。
    原因: validate_network が、ロックされたアセット（HeightField Erode など）の内部のノードまで cook した。hython 22.0.506 で再現:
    サンドボックスの 207 ノードのうち、ユーザーが作ったのは 5 個、残りの 202 個が内部で、ユーザーのノードの cook は合計 1.6 秒、
    内部を cook すると、ノードが OperationFailed になり、OpenCL のメモリ不足（1 ノードで 41 秒）になった。
  ・動画の画像: ノードを作った手順の図が、作ったノード 1 個だけ（まだつながっていないため）で、周りが分からなかった。
    パラメータ画面は、1918 画素の画像が、約 770 画素の枠に入って、文字が半分以下に縮んでいた。

直し方: ① アセットの内部は、cook も報告もしない。② 近場の図は、つながりが無くても、位置の近いノードを入れる。全体は、右上の小さな図で添える。
        ③ パラメータ画面は、ラベルと値の欄がある、左側だけを残す。

実行（リポジトリのルートで）:  uv run --with PySide6 python -m unittest houdini/tests/test_cop_and_capture_20261123.py -v
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

import pilot_task  # noqa: E402
import screen_capture as sc  # noqa: E402
from test_capture_readability import FakeNode  # noqa: E402
from test_parm_tools import make_executor, make_world  # noqa: E402

try:
    from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
except ImportError:
    QImage = None


class ValidateSkipsLockedAssetInternalsTest(unittest.TestCase):
    """COP の HeightField Erode のようなロック済みアセットの内部は、cook も、エラー・警告の報告もしない。"""

    def setUp(self) -> None:
        self.hou, self.sandbox, self.add, self.nodes = make_world()
        self.ex = make_executor(self.hou, self.sandbox)
        self.net = self.add("mtn", "copnet", "Cop")
        self.noise = self.add("mtn/base_noise", "fractalnoise", "Cop", parent=self.net)
        self.erode = self.add("mtn/erode", "heightfield_erode", "Cop", parent=self.net)
        self.noise.out = [self.erode]
        self.erode.isLockedHDA = lambda: True
        # アセットの内部: 前提の入力が無いので、単独で cook するとエラーになり、GPU のメモリも使う
        self.inner = [self.add(f"mtn/erode/block_{i}", "block_end", "Cop", parent=self.erode) for i in range(5)]
        for node in self.inner:
            node.errs = ["Required input 1 (input1) not wired in"]

    def test_inner_nodes_are_not_cooked_and_their_errors_are_not_reported(self) -> None:
        out = self.ex._tool_validate_network({})
        self.assertTrue(all(node.cooks == 0 for node in self.inner), "内部のノードを cook しない（OpenCL のメモリを使い切るため）")
        self.assertEqual((self.noise.cooks, self.erode.cooks), (1, 1), "ユーザーが作ったノードは cook する")
        self.assertNotIn("block_", out.split("[対象外]")[0], "内部のエラーは、報告しない（ユーザーが直せない。69 件の誤った NG の原因）")
        self.assertTrue(out.startswith("検証OK"), out)
        self.assertIn("[対象外]", out)
        self.assertIn("5 個", out)

    def test_the_users_own_asset_node_errors_are_still_reported(self) -> None:
        self.erode.errs = ["Input geometry is empty"]
        out = self.ex._tool_validate_network({})
        self.assertTrue(out.startswith("検証NG"), out)
        self.assertIn("[エラー] mtn/erode: Input geometry is empty", out)

    def test_the_real_api_is_used_when_the_node_has_it(self) -> None:
        """実機には isInsideLockedHDA() がある。親をたどる代わりに、その答えを使う。"""
        for node in self.inner:
            node.isInsideLockedHDA = lambda: True
        for node in (self.net, self.noise, self.erode):
            node.isInsideLockedHDA = lambda: False
        out = self.ex._tool_validate_network({})
        self.assertTrue(all(node.cooks == 0 for node in self.inner))
        self.assertIn("5 個", out)

    def test_without_locked_assets_nothing_is_added(self) -> None:
        self.erode.isLockedHDA = lambda: False  # ロックされていないなら、中身はユーザーのノード（従来どおり cook する）
        out = self.ex._tool_validate_network({})
        self.assertTrue(all(node.cooks == 1 for node in self.inner))
        self.assertNotIn("[対象外]", out)


class PilotErrorScanTest(unittest.TestCase):
    """実験の「操作ミス」（エラーのノードの数。上限 10 で 1）に、アセットの内部を数えない。"""

    @staticmethod
    def node(path: str, errors: list[str], inside_locked=None):
        n = types.SimpleNamespace(path=lambda: path, errors=lambda: errors)
        if inside_locked is not None:
            n.isInsideLockedHDA = lambda: inside_locked
        return n

    def test_inner_nodes_of_a_locked_asset_are_not_counted(self) -> None:
        user = self.node("/obj/mtn/erode", ["x"], inside_locked=False)
        inner = [self.node(f"/obj/mtn/erode/in{i}", ["x"], inside_locked=True) for i in range(40)]
        top = types.SimpleNamespace(allSubChildren=lambda: [user, *inner])
        hou = types.SimpleNamespace(node=lambda path: top if path == "/obj" else None)
        found = pilot_task.scan_error_nodes(hou, roots=("/obj",))
        self.assertEqual(found, {"/obj/mtn/erode"}, "1 つのミスが、内部の 40 個のエラーになって、上限の 10 に張り付かない")

    def test_nodes_without_the_api_are_counted_as_before(self) -> None:
        legacy = self.node("/obj/a", ["x"])
        top = types.SimpleNamespace(allSubChildren=lambda: [legacy])
        hou = types.SimpleNamespace(node=lambda path: top if path == "/obj" else None)
        self.assertEqual(pilot_task.scan_error_nodes(hou, roots=("/obj",)), {"/obj/a"})


def model_node(name: str, x: float, y: float, inputs: list[str] | None = None) -> dict:
    return {
        "path": f"/n/{name}", "name": name, "type": "null", "color": (0.5, 0.5, 0.5), "display": False, "render": False,
        "bypass": False, "error": False, "x": x, "y": y, "inputs": [(f"/n/{i}", 0) for i in (inputs or [])],
    }


class NearbyNodesTest(unittest.TestCase):
    """ノードを作った手順の図が、まだつながっていない新しいノード 1 個だけで、周りが分からなかった（動画の「手順 22」）。"""

    def setUp(self) -> None:
        # 一本道 a→b→c→d と、まだつながっていない新しいノード new（c の近く）、離れた z
        self.model = [
            model_node("a", 0, 0), model_node("b", 0, -3, ["a"]), model_node("c", 0, -6, ["b"]), model_node("d", 0, -9, ["c"]),
            model_node("new", 3, -6), model_node("z", 40, 40),
        ]

    def test_before_an_unconnected_new_node_was_drawn_alone(self) -> None:
        shown, hidden = sc.select_focus_nodes(self.model, "/n/new", min_context=1)  # 変更前の動き
        self.assertEqual([n["name"] for n in shown], ["new"])
        self.assertEqual(hidden, 5)

    def test_after_the_nearest_nodes_by_position_are_added(self) -> None:
        shown, hidden = sc.select_focus_nodes(self.model, "/n/new")
        names = {n["name"] for n in shown}
        self.assertEqual(len(names), sc.MIN_CONTEXT_NODES)
        self.assertIn("new", names)
        self.assertIn("c", names, "位置がいちばん近いノードが入る")
        self.assertNotIn("z", names, "離れたノードは入れない")
        self.assertEqual(hidden, len(self.model) - len(names))

    def test_connected_nodes_still_come_first(self) -> None:
        shown, _ = sc.select_focus_nodes(self.model, "/n/c")
        self.assertTrue({"b", "d", "c"} <= {n["name"] for n in shown})

    def test_a_single_node_network_is_shown_as_it_is(self) -> None:
        shown, hidden = sc.select_focus_nodes([model_node("only", 0, 0)], "/n/only")
        self.assertEqual((len(shown), hidden), (1, 0))

    def test_old_models_without_y_do_not_break(self) -> None:
        model = [{k: v for k, v in n.items() if k != "y"} for n in self.model]
        shown, _ = sc.select_focus_nodes(model, "/n/new")
        self.assertGreaterEqual(len(shown), 1)

    def test_real_screen_framing_includes_the_nearest_nodes_too(self) -> None:
        items = [{"path": n["path"], "x": n["x"], "y": n["y"], "inputs": [p for p, _ in n["inputs"]]} for n in self.model]
        _bounds, shown, _hidden = sc.plan_focus_bounds(items, "/n/new")
        self.assertIn("/n/c", shown)
        self.assertNotIn("/n/z", shown)

    def test_node_size_widens_the_view_so_big_cop_nodes_are_not_cut(self) -> None:
        """COP のノードは、SOP より大きい。位置だけで範囲を決めると、端のノードが切れた（2026-11-23 の実画面）。"""
        small = [{"path": "/n/a", "x": 0.0, "y": 0.0, "inputs": []}, {"path": "/n/b", "x": 4.0, "y": 0.0, "inputs": ["/n/a"]}]
        big = [dict(i, w=2.4, h=2.6) for i in small]
        (sx0, sy0, sx1, sy1), _, _ = sc.plan_focus_bounds(small, "/n/a", aspect=1.0, top_overlay=0.0)
        (bx0, by0, bx1, by1), _, _ = sc.plan_focus_bounds(big, "/n/a", aspect=1.0, top_overlay=0.0)
        self.assertGreaterEqual(bx1, 4.0 + 2.4, "右端のノードの右の辺まで入る")
        self.assertGreaterEqual(by1 - by0, sy1 - sy0)
        self.assertGreater(bx1, sx1 - 1e-9)


@unittest.skipIf(QImage is None, "PySide6 がないため、描画のテストを飛ばす")
class DrawingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    @staticmethod
    def solid(width: int, height: int, color: str = "#2f2f31") -> "QImage":
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor(color))
        return image

    def test_parm_pane_keeps_only_the_left_where_labels_and_values_are(self) -> None:
        image = self.solid(1918, 803)
        for x in range(30, 1900, 7):  # 全幅に、スライダーの線のような中身（背景と違う色）
            image.setPixelColor(x, 400, QColor("#a0a0a8"))
        out = sc.crop_parm_pane(image)
        self.assertEqual(out.height(), 803)
        self.assertEqual(out.width(), max(sc.PARM_CROP_MIN_WIDTH, int(1918 * sc.PARM_CROP_FRACTION)))
        self.assertLess(out.width(), 1918 * 0.6)

    def test_a_narrow_parm_pane_is_left_alone(self) -> None:
        image = self.solid(612, 803)
        for x in range(10, 600, 5):
            image.setPixelColor(x, 300, QColor("#a0a0a8"))
        # 狭い画像は、左側だけ残す切り出しはしない（背景の余白を切るだけ）。中身の幅（10〜595）は、全部残る
        self.assertGreaterEqual(sc.crop_parm_pane(image).width(), 590)

    def test_the_parm_pane_text_gets_bigger_in_the_composed_image(self) -> None:
        """前: 1918 画素を約 770 画素の枠へ（0.40 倍）。後: 約 960 画素を同じ枠へ（約 0.8 倍）。"""
        area_w = 1280 * 0.60 - 12
        before = area_w / 1918
        after = area_w / sc.crop_parm_pane(self._wide_pane()).width()
        self.assertGreater(after, before * 1.8)

    def _wide_pane(self) -> "QImage":
        image = self.solid(1918, 803)
        for x in range(30, 1900, 7):
            image.setPixelColor(x, 400, QColor("#a0a0a8"))
        return image

    @staticmethod
    def fake_network(count: int, new_unconnected: bool = True):
        nodes: list[FakeNode] = []
        for i in range(count):
            inputs = [nodes[-1]] if nodes and not (new_unconnected and i == count - 1) else []
            node = FakeNode(f"/obj/mtn/node_{i}", f"node_{i}", inputs, -3.0 * i)
            if new_unconnected and i == count - 1:  # 作ったばかりの、つながっていないノードは、前のノードの脇に置かれる
                node.position = lambda y=-3.0 * (count - 2): (3.0, y)
            nodes.append(node)
        return types.SimpleNamespace(children=lambda: list(nodes))

    def render(self, count: int, focus: str, tmp: Path):
        out = tmp / "net.png"
        network = self.fake_network(count)
        with mock.patch.object(sc.hou, "node", create=True, return_value=network):
            ok = sc.render_network_diagram(out, "/obj/mtn", focus, "作成しました: x", log_path=tmp / "log.txt")
        return ok, out

    def test_a_new_node_diagram_shows_the_neighbors_and_adds_a_small_overview(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ok, out = self.render(9, "/obj/mtn/node_8", Path(d))
            self.assertTrue(ok)
            meta = sc.read_capture_meta(out)
            self.assertGreaterEqual(meta["nodes_shown"], sc.MIN_CONTEXT_NODES, "周りのノードが分かる（前は 1 個だけ）")
            self.assertEqual(meta["nodes_total"], 9)
            self.assertTrue(meta.get("overview_inset"), "近場に入りきらないので、全体を右上の小さな図で添える")
            self.assertEqual(meta["inset_nodes"], 9)
            self.assertGreaterEqual(meta["name_pt"], sc.MIN_NAME_PT, "近場の名前は、読める大きさのまま")
            self.assertTrue(meta["fits"])
            image = QImage(str(out))
            self.assertEqual((image.width(), image.height()), (1280 * sc.RENDER_SCALE, 720 * sc.RENDER_SCALE))
            # 右上（全体の図）に、注目ノードの強調（琥珀色 #ffb000）の画素がある
            x0 = int((1280 - 1280 * sc.INSET_WIDTH_FRACTION - sc.INSET_MARGIN) * sc.RENDER_SCALE)
            y0, y1 = int(sc.DIAGRAM_BAR_H * sc.RENDER_SCALE), int(((sc.DIAGRAM_BAR_H + 12 + 720 * sc.INSET_HEIGHT_FRACTION)) * sc.RENDER_SCALE)
            amber = 0
            for y in range(y0 + 60, y1, 4):
                for x in range(x0, image.width() - 8, 4):
                    c = QColor(image.pixel(x, y))
                    if c.red() > 230 and 150 < c.green() < 200 and c.blue() < 60:
                        amber += 1
            self.assertGreater(amber, 0, "全体の図の中で、注目ノードが強調されている")

    def test_the_main_diagram_does_not_run_under_the_overview(self) -> None:
        """近場の図は、右端に、全体の図の分を空けて、左にまとまる。"""
        with tempfile.TemporaryDirectory() as d:
            ok, out = self.render(9, "/obj/mtn/node_8", Path(d))
            self.assertTrue(ok)
            image = QImage(str(out))
            inset_left = int((1280 - 1280 * sc.INSET_WIDTH_FRACTION - sc.INSET_MARGIN) * sc.RENDER_SCALE)
            # 近場のノード（明るい灰色の箱）が、全体の図の左端より右には、はみ出していない（全体の図の外の、下の部分で確かめる）
            bottom = int((720 - 60) * sc.RENDER_SCALE)
            light = [x for x in range(inset_left, image.width(), 6) if QColor(image.pixel(x, bottom)).lightness() > 150]
            self.assertEqual(light, [])

    def test_a_small_network_is_drawn_whole_without_an_overview(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ok, out = self.render(3, "/obj/mtn/node_2", Path(d))
            self.assertTrue(ok)
            meta = sc.read_capture_meta(out)
            self.assertFalse(meta.get("overview_inset", False))
            self.assertEqual(meta["nodes_shown"], 3)

    def test_the_overview_alone_returns_nothing_for_a_tiny_network(self) -> None:
        image = self.solid(1280 * sc.RENDER_SCALE, 720 * sc.RENDER_SCALE)
        self.assertEqual(sc.paint_overview_inset(image, [model_node("a", 0, 0)], "/n/a"), {})


if __name__ == "__main__":
    unittest.main()
