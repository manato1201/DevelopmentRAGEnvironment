"""FLIP（液体）と POP（パーティクル）の撮影レシピ（2026-11-25）。recipes.py から読み込まれる。

FLIP: SOP の FLIP Container の 3 つの出力（Sources・Container・Collisions）を、FLIP Boundary（出す元）→ FLIP Collide（ぶつかる相手）→ FLIP Solver の
  同じ番号の入力へ、順につなぐ（FLIP DOP Source = flipsource は、DOP 用。SOP の FLIP Solver につないでも、粒子は出ない。以前、粒子が 5 個しか出なかった原因）。
POP: /obj の DOP ネットワークの中で組む（recipes_dop.py と同じ。POP Object → POP Solver、出す元は POP Solver の 3 番目の入力）。SOP の DOP Import で読み込む。
粒子は、そのままだと、画面で小さな点になって見えにくいので、小さな球を、粒子の位置に置いて見せる（Copy to Points。見せるためだけのノード）。
"""

from __future__ import annotations

import copy

# --- FLIP -------------------------------------------------------------------------------------------
FLIP_VIEW = {"lo": [-2.6, -0.6, -2.6], "hi": [2.6, 2.4, 2.6]}
FLIP_NODES = [
    {"name": "water", "type": ["sphere"], "parms": {"type": 2, "rad": [0.5, 0.5, 0.5], "t": [0, 1.6, 0]}},
    {"name": "ground", "type": ["box"], "parms": {"size": [5, 1, 5], "t": [0, -0.3, 0]}},  # 上の面が、高さ 0.2
    {"name": "container", "type": ["flipcontainer"], "parms": {"sizex": 6, "sizey": 4, "sizez": 6, "ty": 1.5, "particlesep": 0.04}},
    # 出す元: 1 フレーム目だけ、球の中を水で満たす（activate = 1 のままだと、毎フレーム出し続ける）
    {"name": "source", "type": ["flipboundary"], "parms": {"activate": {"expr": "$F == 1"}},
     "inputs": [["container", 0], ["container", 1], ["container", 2], "water"]},
    {"name": "collide", "type": ["flipcollide"], "inputs": [["source", 0], ["source", 1], ["source", 2], "ground"]},
    {"name": "solver", "type": ["flipsolver"], "inputs": [["collide", 0], ["collide", 1], ["collide", 2]]},
    # FLIP の粒子は、半径の属性 pscale（= 0.048）を持つ。Copy to Points は、置く形を、その倍率で縮めるので、半径 0.5 の球 = 半径 0.024 の粒
    {"name": "drop", "type": ["sphere"], "parms": {"type": 2, "rad": [0.5, 0.5, 0.5], "rows": 4, "cols": 6}},
    {"name": "show", "type": ["copytopoints::2.0", "copytopoints"], "inputs": ["drop", ["solver", 0]]},
    {"name": "blue", "type": ["color"], "parms": {"color": [0.25, 0.55, 1.0]}, "inputs": ["show"]},
    {"name": "scene", "type": ["merge"], "inputs": ["water", "ground"]},
    {"name": "final", "type": ["merge"], "inputs": ["blue", "ground"]},
]
FLIP_SOLVER = {
    "kind": "node", "key": "sop/flipsolver", "type": ["flipsolver"], "parms": {}, "sim": 18, "view": FLIP_VIEW,
    "graph": {"node": "final", "before": "scene", "nodes": FLIP_NODES},
    "note": "球（高さ 1.6）の中を、1 フレーム目だけ水で満たし（FLIP Boundary の activate = $F == 1）、FLIP Solver で 18 フレーム動かす。"
            "水は落ちて、台（FLIP Collide でつないだ、ぶつかる相手。上の面が高さ 0.2）の上に、薄く広がる。FLIP Container の 3 つの出力を、Boundary → Collide → Solver の"
            "同じ番号の入力へ、順につなぐ。粒子の間隔は particlesep = 0.04。粒子は、見やすいように、小さな青い球にして見せる",
}


# --- POP --------------------------------------------------------------------------------------------
POP_FRAMES = 20
POP_VIEW = {"lo": [-1.5, -2.2, -1.5], "hi": [2.5, 1.8, 1.5]}  # 20 フレーム（0.83 秒）で、粒子は、板から 3.4 ほど落ちる
EMITTER = {"name": "emitter", "type": ["grid"], "parms": {"size": [1.5, 1.5], "t": [0, 1.5, 0], "rows": 8, "cols": 8}}


def _pop_world(net: str, wind: bool = False, force: bool = False, location: bool = False) -> list[dict]:
    """DOP ネットワーク <net> の中身。板（emitter）から粒子を出し（location = True のときは、POP Location で、1 点から出す）、POP Solver と Gravity で動かす。"""
    ctx = f"dop:{net}"
    nodes = [{"name": f"{net}_object", "type": ["popobject"], "context": ctx}]
    if location:
        nodes.append({"name": f"{net}_source", "type": ["poplocation"], "parms": {"t": [0, 1.5, 0], "constantrate": 2000, "life": 10}, "context": ctx})
    else:
        nodes.append({"name": f"{net}_source", "type": ["popsource"], "parms": {"usecontextgeo": 0, "soppath": "@emitter", "constantrate": 2000,
                                                                               "life": 10}, "context": ctx})
    post = f"{net}_source"
    if wind:
        nodes.append({"name": f"{net}_wind", "type": ["popwind"], "parms": {"wind": [4, 0, 0]}, "inputs": [post], "context": ctx})
        post = f"{net}_wind"
    if force:
        nodes.append({"name": f"{net}_force", "type": ["popforce"], "parms": {"amp": 12, "swirlsize": 0.6}, "inputs": [post], "context": ctx})
        post = f"{net}_force"
    nodes.append({"name": f"{net}_solver", "type": ["popsolver"], "inputs": [f"{net}_object", None, post], "context": ctx})
    nodes.append({"name": f"{net}_gravity", "type": ["gravity"], "inputs": [f"{net}_solver"], "context": ctx})
    nodes.append({"name": f"{net}_out", "type": ["output"], "inputs": [f"{net}_gravity"], "context": ctx, "display": True})
    return nodes


def _shown(name: str, net: str) -> list[dict]:
    """DOP ネットワーク <net> の粒子を読み込み、小さな球にして見せる（<name> が、映すノード）。"""
    return [{"name": f"{net}_import", "type": ["dopimport"], "parms": {"doppath": f"@{net}"}},
            {"name": f"{name}_dot", "type": ["sphere"], "parms": {"type": 2, "rad": [0.025, 0.025, 0.025], "rows": 4, "cols": 6}},
            {"name": f"{name}_copy", "type": ["copytopoints::2.0", "copytopoints"], "inputs": [f"{name}_dot", f"{net}_import"]},
            {"name": f"{name}_color", "type": ["color"], "parms": {"color": [1.0, 0.75, 0.3]}, "inputs": [f"{name}_copy"]},
            {"name": name, "type": ["merge"], "inputs": [f"{name}_color", "emitter"]}]


def _pop_recipe(key: str, before: dict | None, after: dict, note: str) -> dict:
    """before = None: 適用前は、粒子を出す元の板（1 フレーム目）。それ以外: 適用前も、同じ設定から 1 つ抜いた DOP ネットワークを、同じフレームまで動かす。"""
    nodes = [copy.deepcopy(EMITTER), *_pop_world("after", **after), *_shown("after_view", "after")]
    graph = {"node": "after_view", "nodes": nodes}
    out = {"kind": "node", "key": key, "type": [key.split("/")[1]], "parms": {}, "sim": POP_FRAMES, "view": POP_VIEW, "graph": graph, "note": note}
    if before is None:
        graph["before"] = "emitter"
    else:
        nodes[1:1] = [*_pop_world("before", **before), *_shown("before_view", "before")]
        graph["before"] = "before_view"
        out["compare_at_end"] = True
    return out


POP_RECIPES = [
    _pop_recipe("dop/popsolver", None, {}, "板（1.5 x 1.5、高さ 1.5）から、POP Source で 1 秒に 2000 個の粒子を出し、POP Solver と Gravity で 20 フレーム動かす。"
                "POP Source は、POP Solver の 3 番目の入力（Sources）につなぐ。適用前は、出す元の板だけ。粒子は、見やすいように、小さな球にして見せる"),
    _pop_recipe("dop/popsource", None, {}, "板（1.5 x 1.5、高さ 1.5）を、POP Source の soppath に指定し（usecontextgeo = 0 は、メニューの「Use Parameter Values」。soppath に書いた SOP を使う）、"
                "1 秒に 2000 個（constantrate）、寿命 10 秒（life）の粒子を出す。POP Solver と Gravity で 20 フレーム動かす。適用前は、出す元の板だけ"),
    _pop_recipe("dop/popwind", {}, {"wind": True}, "板から粒子を出し、Gravity で 20 フレーム落とす。適用後は、POP Source の後ろに POP Wind（wind = (4, 0, 0)）をつなぐ。"
                "粒子は、右（+X）へ流されながら落ちる（適用前は、まっすぐ下へ落ちる）"),
    _pop_recipe("dop/popforce", {}, {"force": True}, "板から粒子を出し、Gravity で 20 フレーム落とす。適用後は、POP Source の後ろに POP Force をつなぎ、"
                "ノイズの力（amp = 12、swirlsize = 0.6）を足す。粒子は、渦を巻くように散らばりながら落ちる（適用前は、まっすぐ下へ落ちる）"),
]

POP_LOCATION = _pop_recipe("shelf/dynamics_poplocation", None, {"location": True},
                           "POP Location で、1 点（0, 1.5, 0）から、1 秒に 2000 個、寿命 10 秒の粒子を出し、POP Solver と Gravity で 20 フレーム動かす。"
                           "適用前は、何も無い（板は、位置の目安）。粒子は、見やすいように、小さな球にして見せる")
POP_LOCATION["kind"] = "shelf"
POP_RECIPES.append(POP_LOCATION)

SHELF_FROM = {"shelf/dynamics_popwind": "dop/popwind"}


def build() -> list[dict]:
    out = [copy.deepcopy(FLIP_SOLVER), *copy.deepcopy(POP_RECIPES)]
    by_key = {r["key"]: r for r in out}
    for shelf_key, node_key in SHELF_FROM.items():
        recipe = copy.deepcopy(by_key[node_key])
        recipe["kind"], recipe["key"] = "shelf", shelf_key
        out.append(recipe)
    return out
