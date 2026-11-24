"""Vellum・RBD・ライトの撮影レシピ（2026-11-24）。recipes.py から読み込まれる。つなぎ方を書く "graph"、ライトを置く "lights" を使う（hython_shot.py の説明を参照）。

シミュレーションは、SOP のソルバー（vellumsolver・rbdbulletsolver）で動かす。シェルフのツールが作る DOP の組み立ては、画面の操作（hou.ui）が要るので、hython では作れない。
なので、シェルフのキーには、同じ種類のシミュレーションを SOP で再現した絵を付ける（説明の「例」は、この絵の条件に合わせて作り直す）。
"""

from __future__ import annotations

import copy

BALL = {"name": "ball", "type": ["sphere"], "parms": {"type": 2, "rad": [0.5, 0.5, 0.5], "t": [0, 0.3, 0], "rows": 24, "cols": 48}}

# 布: 板を、球の上に落とす（球は、ぶつかる相手）
VELLUM_CLOTH = {
    "kind": "node", "key": "sop/vellumsolver", "type": ["vellumsolver"], "parms": {}, "sim": 40,
    "view": {"lo": [-1.5, -0.3, -1.5], "hi": [1.5, 1.7, 1.5]},
    "graph": {"node": "final", "before": "scene", "nodes": [
        {"name": "cloth", "type": ["grid"], "parms": {"size": [2, 2], "rows": 30, "cols": 30, "t": [0, 1.0, 0]}},
        BALL,
        {"name": "constraints", "type": ["vellumconstraints"], "inputs": ["cloth"]},  # 初期値の Cloth（布）の拘束
        {"name": "solver", "type": ["vellumsolver"], "inputs": [["constraints", 0], ["constraints", 1], "ball"]},
        {"name": "scene", "type": ["merge"], "inputs": ["cloth", "ball"]},
        {"name": "final", "type": ["merge"], "inputs": ["solver", "ball"]},
    ]},
    "note": "板（布）を球の上 1.0 の高さに置き、Vellum Constraints（Cloth）をつけて、Vellum Solver で 40 フレーム動かす。球は、ぶつかる相手（3 番目の入力）",
}

# RBD: 箱を砕いて（ピース 25 個）、地面へ落とす
RBD_DROP = {
    "kind": "node", "key": "sop/rbdbulletsolver", "type": ["rbdbulletsolver"], "parms": {}, "sim": 30,
    "view": {"lo": [-2.5, -0.2, -2.5], "hi": [2.5, 3.6, 2.5]},
    "graph": {"node": "final", "before": "scene", "nodes": [
        {"name": "box", "type": ["box"], "parms": {"size": [1, 1, 1], "t": [0, 2.5, 0], "r": [0, 0, 35]}},
        {"name": "ground", "type": ["grid"], "parms": {"size": [6, 6], "rows": 2, "cols": 2}},
        {"name": "fracture", "type": ["rbdmaterialfracture::4.0", "rbdmaterialfracture"], "inputs": ["box"]},
        {"name": "config", "type": ["rbdconfigure"], "inputs": [["fracture", 0], ["fracture", 1]]},
        {"name": "solver", "type": ["rbdbulletsolver"], "inputs": [["config", 0], None, None, "ground"]},  # 2 番目（拘束）は、つながない = ピースが、つながらず、ばらばらに落ちる。4 番目の入力が、ぶつかる地面
        {"name": "scene", "type": ["merge"], "inputs": ["box", "ground"]},
        {"name": "final", "type": ["merge"], "inputs": ["solver", "ground"]},
    ]},
    "note": "傾けた箱（高さ 2.5）を RBD Material Fracture で砕き（ピース 25 個）、RBD Configure をつけて、RBD Bullet Solver で 30 フレーム動かす。拘束（ピースをつなぐもの）はつながないので、ピースは、ばらばらに積もる。地面は、4 番目の入力",
}

SCENE = {"node": "scene", "before": "scene", "nodes": [
    {"name": "ball", "type": ["sphere"], "parms": {"type": 2, "rad": [0.8, 0.8, 0.8], "rows": 24, "cols": 48}},
    {"name": "ground", "type": ["grid"], "parms": {"size": [4, 4], "t": [0, -0.8, 0]}},
    {"name": "scene", "type": ["merge"], "inputs": ["ball", "ground"]},
]}
POINT_LIGHT = {"kind": "node", "key": "obj/hlight", "type": ["hlight"], "parms": {}, "lighting": True, "graph": SCENE,
               "lights": [{"name": "key", "type": ["hlight"], "parms": {"t": [2.5, 2.5, 2.0], "light_type": 0, "light_intensity": 40}}],
               "note": "球と地面の、斜め上（2.5, 2.5, 2.0）に、点光源（Point）を置く。light_intensity = 40。置く前は、ビューポートの標準の明かり（ヘッドライト）で見える"}
AREA_LIGHT = {"kind": "shelf", "key": "shelf/object_arealight", "type": ["hlight"], "parms": {}, "lighting": True, "graph": SCENE,
              "lights": [{"name": "key", "type": ["hlight"], "parms": {"t": [0, 3, 0], "r": [-90, 0, 0], "light_type": 2, "areasize": [3, 3], "light_intensity": 12}}],
              "note": "真上（0, 3, 0）に、下向きの面光源（Grid、3 x 3）を置く。light_type = 2 は、メニューの「Grid」。置く前は、ビューポートの標準の明かり"}

SHELF_FROM = {
    "shelf/dynamics_vellumcloth": VELLUM_CLOTH, "shelf/geometry_vellumsimplecloth": VELLUM_CLOTH,
    "shelf/dynamics_rbdfracturedobject": RBD_DROP,
    "shelf/object_pointlight": POINT_LIGHT,
}


def build() -> list[dict]:
    out = [VELLUM_CLOTH, RBD_DROP, POINT_LIGHT, AREA_LIGHT]
    for key, base in SHELF_FROM.items():
        recipe = copy.deepcopy(base)
        recipe["kind"], recipe["key"] = "shelf", key
        out.append(recipe)
    return copy.deepcopy(out)
