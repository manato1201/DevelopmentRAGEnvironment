"""DOP ノードの撮影レシピ（2026-11-25）。recipes.py から読み込まれる。キーは dop/<名前>。

DOP は、/obj の DOP ネットワーク（dopnet）の中で、シミュレーションを組む。SOP の DOP Import（dopimport）で読み込んで、形にして撮る。
比べ方: 「適用前」は、そのノードだけを抜いた、もう 1 つの DOP ネットワーク。両方を同じフレームまで動かして比べる（compare_at_end）。
例: Gravity の適用前 = 重力なし（箱は浮いたまま）、適用後 = 重力あり（落ちて、地面に止まる）。
"""

from __future__ import annotations

import copy

FRAMES = 30
VIEW = {"lo": [-2.5, -2.5, -2.5], "hi": [2.5, 3.2, 2.5]}
SOP_SIDE = [
    {"name": "box", "type": ["box"], "parms": {"t": [0, 2.5, 0], "r": [20, 0, 35]}},
    {"name": "pack", "type": ["pack"], "inputs": ["box"]},
    {"name": "ball", "type": ["sphere"], "parms": {"type": 2, "rad": [0.8, 0.8, 0.8], "t": [0, 0.8, 0]}},
]


def _world(net: str, gravity: bool = True, ground: bool = True, solver: bool = True, static: bool = False) -> list[dict]:
    """DOP ネットワーク <net> の中身。箱（RBD Packed Object）を、ソルバーで動かす。"""
    ctx = f"dop:{net}"
    nodes = [{"name": f"{net}_rbd", "type": ["rbdpackedobject"], "parms": {"soppath": "@pack"}, "context": ctx}]
    merged = [f"{net}_rbd"]
    if static:
        nodes.append({"name": f"{net}_static", "type": ["staticobject"], "parms": {"soppath": "@ball"}, "context": ctx})
        merged.append(f"{net}_static")
    if ground:
        nodes.append({"name": f"{net}_ground", "type": ["groundplane"], "parms": {}, "context": ctx})
        merged.append(f"{net}_ground")
    nodes.append({"name": f"{net}_merge", "type": ["merge"], "inputs": merged, "context": ctx})
    last = f"{net}_merge"
    if solver:
        nodes.append({"name": f"{net}_solver", "type": ["rigidbodysolver"], "inputs": [last], "context": ctx})
        last = f"{net}_solver"
    if gravity:
        nodes.append({"name": f"{net}_gravity", "type": ["gravity"], "inputs": [last], "context": ctx})
        last = f"{net}_gravity"
    nodes.append({"name": f"{net}_out", "type": ["output"], "inputs": [last], "context": ctx, "display": True})
    return nodes


def _recipe(key: str, before: dict, after: dict, note: str) -> dict:
    nodes = [*copy.deepcopy(SOP_SIDE), *_world("before", **before), *_world("after", **after),
             {"name": "before_view", "type": ["dopimport"], "parms": {"doppath": "@before"}},
             {"name": "after_view", "type": ["dopimport"], "parms": {"doppath": "@after"}}]
    return {"kind": "node", "key": key, "type": [key.split("/")[1]], "parms": {}, "sim": FRAMES, "compare_at_end": True, "view": VIEW,
            "graph": {"node": "after_view", "before": "before_view", "nodes": nodes}, "note": note}


DOP_RECIPES = [
    _recipe("dop/gravity", {"gravity": False}, {}, "傾けた箱（高さ 2.5）を RBD Packed Object にし、Rigid Body Solver で 30 フレーム動かす。"
            "適用前は Gravity なし（箱は、浮いたまま）、適用後は Gravity あり（落ちて、Ground Plane に止まる）"),
    _recipe("dop/groundplane", {"ground": False}, {}, "傾けた箱を、Gravity つきで 30 フレーム落とす。適用前は Ground Plane なし（地面を突き抜けて、落ち続ける）、"
            "適用後は Ground Plane あり（地面で止まる）"),
    _recipe("dop/rigidbodysolver", {"solver": False}, {}, "傾けた箱に Gravity をつけ、30 フレーム動かす。適用前は Rigid Body Solver なし（何も動かない）、"
            "適用後は Rigid Body Solver あり（落ちて、地面に止まる）"),
    _recipe("dop/staticobject", {}, {"static": True}, "傾けた箱を、Gravity つきで 30 フレーム落とす。適用後は、下に Static Object（動かない球）を置く。"
            "箱は、球に当たって転がる（適用前は、地面まで、そのまま落ちる）"),
]

SHELF_FROM = {"shelf/dynamics_rbdobjects": "dop/rigidbodysolver"}


def build() -> list[dict]:
    out = copy.deepcopy(DOP_RECIPES)
    by_key = {r["key"]: r for r in out}
    for shelf_key, node_key in SHELF_FROM.items():
        recipe = copy.deepcopy(by_key[node_key])
        recipe["kind"], recipe["key"] = "shelf", shelf_key
        out.append(recipe)
    return out
