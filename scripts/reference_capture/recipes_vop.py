"""VOP ノードの撮影レシピ（2026-11-25）。Attribute VOP の中に、そのノードを置いて、P（位置）や N を入れ、出力を Cd（色）か P（位置）につなぐ。
recipes.py から読み込まれる。キーは vop/<名前>（例: vop/aanoise）。図（node.png）は、VOP の中のつなぎを描く（capture.vop_diagram）。
"""

from __future__ import annotations

import copy

from recipe_common import GRID, SPHERE

SPHERE_N = {"type": "sphere", "parms": {"type": 2, "rows": 40, "cols": 80, "t": [1.5, 0.5, 0]}, "after": [{"type": "normal", "parms": {"type": 0}}]}  # 原点からずらした球（中心の球だと N と P が平行で、外積が 0 になる）  # type = 0 は、点に付ける  # 点の法線 N を付けた球（Cross Product に N を入れるため）


def _vop(name: str, nodes: list[dict], wires: list[list], note: str, input_: dict | None = None) -> dict:
    return {"kind": "node", "key": f"vop/{name}", "type": ["attribvop"], "input": input_ or GRID, "parms": {},
            "vop": {"nodes": nodes, "wires": wires}, "note": note}


def _n(name: str, type_name: str, parms: dict | None = None) -> dict:
    return {"name": name, "type": [type_name], "parms": parms or {}}


VOP_RECIPES = [
    _vop("aanoise", [_n("noise", "aanoise", {"freq": [1.5, 1.5, 1.5], "amp": 3})], [["global", "P", "noise", "pos"], ["noise", "noise", "out", "Cd"]],
         "Anti-Aliased Noise の pos に位置 P を入れ（freq 1.5・amp 3）、noise（0〜1 の値）を色 Cd につなぐ。板が、まだらの濃淡になる"),
    _vop("turbnoise", [_n("noise", "turbnoise", {"freq": [1.5, 1.5, 1.5], "amp": 3})], [["global", "P", "noise", "pos"], ["noise", "noise", "out", "Cd"]],
         "Turbulent Noise の pos に P を入れ（freq 1.5・amp 3）、noise を Cd につなぐ。細かい渦の濃淡になる"),
    _vop("curlnoise", [_n("noise", "curlnoise")], [["global", "P", "noise", "pos"], ["noise", "noise", "out", "Cd"]],
         "Curl Noise の pos に P を入れ、noise（向きの値）を Cd につなぐ。向きが、色の違いとして見える"),
    _vop("abs", [_n("abs", "abs")], [["global", "P", "abs", "val"], ["abs", "abs", "out", "Cd"]],
         "Absolute の val に P を入れ、abs を Cd につなぐ。中心から外へ、どの向きも明るくなる（負の値が正になる）"),
    _vop("length", [_n("len", "length")], [["global", "P", "len", "vec"], ["len", "len", "out", "Cd"]],
         "Length の vec に P を入れ、len（原点からの距離）を Cd につなぐ。中心が暗く、外ほど明るい"),
    _vop("normalize", [_n("nrm", "normalize")], [["global", "P", "nrm", "vec"], ["nrm", "nvec", "out", "Cd"]],
         "Normalize の vec に P を入れ、nvec（長さ 1 の向き）を Cd につなぐ。球の向きごとに、色が変わる", SPHERE),
    _vop("floor", [_n("floor", "floor")], [["global", "P", "floor", "val"], ["floor", "floor", "out", "Cd"]],
         "Floor の val に P を入れ、floor（切り捨てた値）を Cd につなぐ。色が、1 刻みの段になる"),
    _vop("clamp", [_n("clamp", "clamp")], [["global", "P", "clamp", "val"], ["clamp", "clamp", "out", "Cd"]],
         "Clamp の val に P を入れ（min 0・max 1 は初期値）、clamp を Cd につなぐ。0〜1 の外は、端の色で止まる"),
    _vop("cross", [_n("cross", "cross")], [["global", "N", "cross", "vec1"], ["global", "P", "cross", "vec2"], ["cross", "crossprod", "out", "Cd"]],
         "Cross Product に、法線 N と位置 P を入れ、crossprod（両方に垂直な向き）を Cd につなぐ。入力は、原点からずらし、法線（Normal）を付けた球（原点の球だと、N と P が同じ向きで、外積は 0 になる）",
         SPHERE_N),
    _vop("vectofloat", [_n("split", "vectofloat")], [["global", "P", "split", "vec"], ["split", "fval1", "out", "Cd"]],
         "Vector to Float の vec に P を入れ、fval1（X の値）だけを Cd につなぐ。左右で、明るさが変わる"),
    _vop("sqrt", [_n("len", "length"), _n("root", "sqrt")], [["global", "P", "len", "vec"], ["len", "len", "root", "val"], ["root", "sqrt", "out", "Cd"]],
         "Length で原点からの距離を出し、Square Root の val に入れ、sqrt を Cd につなぐ。中心の近くで、明るさが急に変わる"),
    _vop("add", [_n("noise", "curlnoise", {"amp": 0.15}), _n("add", "add")], [["global", "P", "noise", "pos"], ["global", "P", "add", 0], ["noise", "noise", "add", 1], ["add", "sum", "out", "P"]],
         "Add の 1 番目に P、2 番目に Curl Noise（amp 0.15）の noise を入れ、sum を P につなぐ。板が、ノイズの分だけ、波打つ"),
    _vop("subtract", [_n("noise", "curlnoise", {"amp": 0.15}), _n("sub", "subtract")], [["global", "P", "noise", "pos"], ["global", "P", "sub", 0], ["noise", "noise", "sub", 1], ["sub", "diff", "out", "P"]],
         "Subtract の 1 番目に P、2 番目に Curl Noise（amp 0.15）の noise を入れ、diff を P につなぐ。Add と逆向きに、波打つ"),
    _vop("multiply", [_n("len", "length"), _n("mul", "multiply")], [["global", "P", "len", "vec"], ["global", "P", "mul", 0], ["len", "len", "mul", 1], ["mul", "product", "out", "P"]],
         "Multiply の 1 番目に P、2 番目に原点からの距離（Length）を入れ、product を P につなぐ。外ほど、大きく引き伸ばされる"),
    _vop("divide", [_n("len", "length"), _n("div", "divide")], [["global", "P", "len", "vec"], ["global", "P", "div", 0], ["len", "len", "div", 1], ["div", "div", "out", "P"]],
         "Divide の 1 番目に P、2 番目に原点からの距離（Length）を入れ、div を P につなぐ。どの点も、距離 1 の円の上に集まる"),
]


def build() -> list[dict]:
    return copy.deepcopy(VOP_RECIPES)
