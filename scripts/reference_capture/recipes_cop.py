"""COP（Copernicus）ノードの撮影レシピ（2026-11-25）。recipes.py から読み込まれる。キーは cop/<名前>。

COP は、画像を作るノード。copnet の中に作って、そのノードの画像（層）を、そのまま書き出す（hython_shot.shoot_cop。OpenGL ROP は使わない）。
"cop": {"nodes": [{"name", "type", "parms", "inputs"}], "node": 適用後のノード, "before": 適用前のノード（無ければ、置くだけで画像ができるもの）}
"""

from __future__ import annotations

import copy

NOISE = {"name": "noise", "type": ["fractalnoise"], "parms": {"elementsize": 0.15, "amp": 1.0, "contrast": 0.6}}  # 濃淡を強めた雲の模様（前後の違いが見えるように）


def _create(name: str, parms: dict, note: str, sweep: tuple, type_name: str | None = None) -> dict:
    """置くだけで画像ができる COP。sweep = (動かすパラメータ, 最初, 最後)。動き（GIF）は、その値を動かした画像の連番。"""
    return {"kind": "node", "key": f"cop/{name}", "type": [type_name or name], "parms": {}, "create": True,
            "cop": {"node": "n", "nodes": [{"name": "n", "type": [type_name or name], "parms": parms}]}, "note": note,
            "sweep": {"parm": sweep[0], "from": sweep[1], "to": sweep[2]}}


def _apply(name: str, parms: dict, note: str, source: dict | None = None) -> dict:
    source = source or NOISE
    return {"kind": "node", "key": f"cop/{name}", "type": [name], "parms": {},
            "cop": {"node": "n", "before": source["name"], "nodes": [source, {"name": "n", "type": [name], "parms": parms, "inputs": [source["name"]]}]},
            "note": note}


COP_RECIPES = [
    _create("fractalnoise", {"elementsize": 0.15, "amp": 1.0, "contrast": 0.6}, "Fractal Noise を置く（elementsize = 0.15、amp = 1、contrast = 0.6）。入力は要らず、置くだけで、雲のような濃淡の画像ができる", ("elementsize", 0.4, 0.15)),
    _create("cellularnoise", {}, "Cellular Noise を置く（パラメータは、初期値のまま）。細胞のような模様の画像ができる", ("elementsize", 0.5, 0.2)),
    _create("worleynoise", {}, "Worley Noise を置く（パラメータは、初期値のまま）。点からの距離でできる、粒の模様の画像", ("elementsize", 0.3, 0.1)),
    _create("ramp", {}, "Ramp を置く（パラメータは、初期値のまま）。左から右へ、明るさが変わる画像", ("cycles", 4.0, 1.0)),
    _apply("blur", {"size": 0.05}, "Fractal Noise（elementsize 0.15、amp 1、contrast 0.6）の画像に、Blur をつなぐ（size = 0.05）。細かい模様が、ぼける"),
    _apply("sharpen", {}, "Fractal Noise（elementsize 0.15、amp 1、contrast 0.6）の画像に、Sharpen をつなぐ（初期値）。境目が、くっきりする"),
    _apply("edgedetect", {}, "Fractal Noise（elementsize 0.15、amp 1、contrast 0.6）の画像に、Edge Detect をつなぐ（初期値）。明るさが変わる境目だけが、線として残る"),
]


def build() -> list[dict]:
    return copy.deepcopy(COP_RECIPES)
