"""シェルフツールの「適用前後」の撮影レシピ（2026-11-24）。recipes.py から読み込まれる（RECIPES に足される）。

シェルフツールは、ノードを置く（置いて、つなぐ）操作なので、同じ働きのノードのレシピを、そのまま使う（SHELF_FROM_NODE）。
入力を持たず、置くだけで形ができるツール（Box・Sphere など）は、"create": true にして、「適用後」だけを撮る。
撮る前に、`uv run python scripts/reference_capture/capture.py --check --kind shelf` で確かめる。
シミュレーション系（Pyro・RBD・Vellum・パーティクルなど）・ライト・カメラは、ここに入れない（形の前後を、静止画で比べられないため）。
"""

from __future__ import annotations

import copy

from recipe_common import GRID, create_sweep

# シェルフのキー → 同じ働きのノードのキー
SHELF_FROM_NODE = {
    "shelf/sop_polyextrude_2_0": "sop/polyextrude",
    "shelf/sop_polybevel_3_0": "sop/polybevel",
    "shelf/sop_polyreduce_2_0": "sop/polyreduce",
    "shelf/sop_polyfill": "sop/polyfill",
    "shelf/sop_clip_2_0": "sop/clip",
    "shelf/sop_subdivide": "sop/subdivide",
    "shelf/sop_smooth_2_0": "sop/smooth",
    "shelf/geometry_mirror": "sop/mirror",
    "shelf/geometry_copy": "sop/copytopoints",
    "shelf/generic_delete": "sop/delete",
    "shelf/sop_revolve_2_0": "sop/revolve",
    "shelf/sop_sweep_2_0": "sop/sweep",
    "shelf/sop_boolean_2_0": "sop/boolean",
    "shelf/sop_scatter_2_0": "sop/scatter",
    "shelf/sop_ray": "sop/ray",
    "shelf/sop_carve": "sop/carve",
    "shelf/sop_skin": "sop/skin",
    "shelf/sop_bend": "sop/bend",
    "shelf/sop_ripple_2_0": "sop/ripple",
    "shelf/sop_fractal": "sop/fractal",
    "shelf/sop_heightfield": "sop/heightfield",  # 2026-11-25
    "shelf/sop_heightfield_noise": "sop/heightfield_noise",
    "shelf/sop_heightfield_terrace": "sop/heightfield_terrace",  # 2026-11-25 の 2 回目
    "shelf/sop_heightfield_erode_3_0": "sop/heightfield_erode",
}

CREATE_RECIPES: list[dict] = [
    {"kind": "shelf", "key": "shelf/sop_box", "type": ["box"], "create": True, "parms": {}, "note": "Box。置くだけで、箱ができる（パラメータは、初期値のまま）"},
    {"kind": "shelf", "key": "shelf/geometry_sphere", "type": ["sphere"], "create": True, "parms": {"type": 2, "rows": 24, "cols": 48}, "keep": ["type", "rows", "cols"], "note": "Sphere。type = 2 は、メニューの「Polygon Mesh」（面が見える球）"},
    {"kind": "shelf", "key": "shelf/geometry_tube", "type": ["tube"], "create": True, "parms": {"type": 1}, "keep": ["type"], "note": "Tube。type = 1 は、メニューの「Polygon」。筒（両端にふた付き）"},
    {"kind": "shelf", "key": "shelf/sop_torus", "type": ["torus"], "create": True, "parms": {"rows": 24, "cols": 48}, "note": "Torus。ドーナツの形"},
    {"kind": "shelf", "key": "shelf/sop_grid", "type": ["grid"], "create": True, "parms": {"rows": 10, "cols": 10, "size": [3, 3]}, "note": "Grid。10 x 10 の点の板"},
    {"kind": "shelf", "key": "shelf/geometry_line", "type": ["line"], "create": True, "parms": {"dist": 2, "points": 12}, "note": "Line。長さ 2、点が 12 個の線"},
    {"kind": "shelf", "key": "shelf/geometry_circle", "type": ["circle"], "create": True, "parms": {"type": 1, "divs": 32}, "keep": ["type"], "note": "Circle。type = 1 は、メニューの「Polygon」。32 分割の円"},
    {"kind": "shelf", "key": "shelf/geometry_platonic", "type": ["platonic"], "create": True, "parms": {"type": 3}, "keep": ["type"], "note": "Platonic Solids。type = 3 は、メニューの「Icosahedron」（正二十面体）"},
    {"kind": "shelf", "key": "shelf/sop_lsystem", "type": ["lsystem"], "create": True, "parms": {}, "note": "L-System。パラメータは、初期値のまま"},
    {"kind": "shelf", "key": "shelf/sop_metaball", "type": ["metaball"], "create": True, "parms": {}, "note": "Metaball。パラメータは、初期値のまま"},
]


for _r in CREATE_RECIPES:
    if create_sweep(_r["type"][0]):
        _r["sweep"] = create_sweep(_r["type"][0])


# シェルフのツールが、実際に置くノードで撮る（2026-11-28）。以前は、Mountain・Twist・Knife を、Tab に出ない古いノード
# （mountain::2.0・twist・knife）で撮っていた。Houdini 22 のツールの中身（hou.shelves.tool(...).script()）は、次のとおり:
#   Mountain → Attribute Noise（attribnoise::2.0。名前は mountain1）、Twist → Bend（Twist を入れ、Bend を外す。名前は twist1）、
#   Knife → Clip（clip::2.0。Keep = Both。名前は knife1）
TALL_RIBBON = {"type": "grid", "parms": {"orient": 0, "size": [1.2, 3], "rows": 40, "cols": 6}}
SHELF_TOOL_RECIPES: list[dict] = [
    {"kind": "shelf", "key": "shelf/geometry_mountain", "type": ["attribnoise::2.0"], "input": GRID,
     "parms": {"displace": 1, "attribs": "P", "noiserange": 1, "fractal": 3, "oct": 8, "rough": 0.4, "amplitude": 0.6},
     "sweep": {"parm": "amplitude", "from": 0.0, "to": 0.6},
     "note": "シェルフの Mountain は、Attribute Noise（attribnoise::2.0）を mountain1 という名前で置く。Displace Along を入れ、位置（P）を、"
             "Noise Range = Zero Centered で上下に動かす。Fractal・Octaves・Roughness はツールの値のまま。Amplitude は、見やすいよう 0.6（ツールの値は 0.25）"},
    {"kind": "shelf", "key": "shelf/geometry_twist", "type": ["bend"], "input": TALL_RIBBON,
     "parms": {"enabletwist": 1, "twist": 160,
               "origin": [0, -1.5, 0], "dir": [0, 1, 0], "length": 3},
     "sweep": {"parm": "twist", "from": 0, "to": 160},
     "note": "シェルフの Twist は、Bend を twist1 という名前で置き、Twist を入れて Bend を外す。縦長の板（高さ 3）の下端（0, -1.5, 0）から上向き（0, 1, 0）に、"
             "長さ 3 の範囲を、Twist = 160 度ねじる（Bend の角度は 0 のままなので、曲げは効かない）"},
    {"kind": "shelf", "key": "shelf/geometry_knife", "type": ["clip::2.0"], "input": {"type": "sphere", "parms": {"type": 2, "rows": 40, "cols": 80}},
     "parms": {"clipop": 0, "dir": [0.4, 1, 0]}, "sweep": {"parm": "originy", "from": -0.8, "to": 0.2},
     "note": "シェルフの Knife は、Clip（clip::2.0）を knife1 という名前で置く（Keep = Both: 両側を残して、切れ目だけを入れる）。"
             "ここでは切れ目が見えるよう、Keep を Above（平面の上だけ残す）にし、少し傾けた平面（Direction (0.4, 1, 0)）で球を切る。動きは、平面の高さ（Origin の Y）を -0.8 から 0.2 へ"},
]
CREATE_RECIPES.extend(SHELF_TOOL_RECIPES)


def build(node_recipes: list[dict]) -> list[dict]:
    by_key = {r["key"]: r for r in node_recipes if r["kind"] == "node"}
    out = []
    for shelf_key, node_key in SHELF_FROM_NODE.items():
        if node_key not in by_key:
            continue
        recipe = copy.deepcopy(by_key[node_key])
        recipe["kind"], recipe["key"] = "shelf", shelf_key
        out.append(recipe)
    return out + CREATE_RECIPES
