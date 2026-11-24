"""シミュレーション（Pyro など）の撮影レシピ（2026-11-24）。recipes.py から読み込まれる。

hython_shot.py の "sim": N = 1〜N 枚目を順に cook して進める。「適用前」は、元の形（1 枚目）、「適用後」は N 枚目。
Pyro は、SOP の Pyro Solver（pyrosolver）で動かす（シェルフのツールが作る DOP の組み立ては、画面の操作（hou.ui）が要るので、hython では作れない）。
"""

from __future__ import annotations

import copy

# 球 → Pyro Source（煙の元の点）→ Volume Rasterize Attributes（点を、密度・温度のボリュームにする）
SMOKE_SOURCE = {
    "type": "sphere", "parms": {"type": 2, "rad": [0.4, 0.4, 0.4], "t": [0, 0.4, 0]},
    "after": [
        {"type": "pyrosource", "parms": {"mode": 0, "attributes": 2, "name1": "density", "name2": "temperature"}},
        {"type": "volumerasterizeattributes", "parms": {"attributes": "density temperature", "voxelsize": 0.05}},
    ],
}
SMOKE_VIEW = {"lo": [-1.5, -0.5, -1.5], "hi": [1.5, 8.5, 1.5]}

PYRO_SOLVER = {"kind": "node", "key": "sop/pyrosolver", "type": ["pyrosolver"], "input": SMOKE_SOURCE, "sim": 24, "view": SMOKE_VIEW,
               "parms": {"divsize": 0.05}, "keep": ["divsize"],
               "note": "球から出る煙を、24 フレーム分、動かした結果（SOP の Pyro Solver。元の形は、密度と温度のボリューム）"}

RASTERIZE = {"kind": "node", "key": "sop/volumerasterizeattributes", "type": ["volumerasterizeattributes"],
             "input": {"type": "sphere", "parms": {"type": 2, "rad": [0.6, 0.6, 0.6]}, "after": [
                 {"type": "pyrosource", "parms": {"mode": 0, "attributes": 1, "name1": "density"}}]},
             "parms": {"attributes": "density", "voxelsize": 0.05}, "keep": ["attributes"],
             "note": "点（Pyro Source が作った密度つきの点）を、密度のボリュームにする"}

SHELF_FROM = {"shelf/pyro_billowysmoke": PYRO_SOLVER, "shelf/geometry_pyrosimplebillowysmoke": PYRO_SOLVER}


def build() -> list[dict]:
    out = [PYRO_SOLVER, RASTERIZE]
    for key, base in SHELF_FROM.items():
        recipe = copy.deepcopy(base)
        recipe["kind"], recipe["key"] = "shelf", key
        out.append(recipe)
    return copy.deepcopy(out)
