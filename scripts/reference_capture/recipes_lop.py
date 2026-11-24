"""LOP（Solaris）ノードの撮影レシピ（2026-11-25）。recipes.py から読み込まれる。キーは lop/<名前>。

LOP は、USD のステージを作るので、そのままでは、OpenGL ROP に映らない。/stage に LOP を置き、SOP の LOP Import（lopimport）で
ステージを読み込み、Unpack USD（unpackusd。出力は Polygons）で、形にして撮る。「適用前」は、ひとつ前の LOP の、同じ読み込み。
"""

from __future__ import annotations

import copy


def _import(prefix: str, lop: str) -> list[dict]:
    """/stage の lop を、SOP で読み込んで、形にする 2 つのノード（<prefix>_imp → <prefix>）。"""
    return [
        {"name": f"{prefix}_imp", "type": ["lopimport"], "parms": {"loppath": f"@{lop}", "primpattern": "*"}},
        {"name": prefix, "type": ["unpackusd"], "parms": {"output": 1}, "inputs": [f"{prefix}_imp"]},
    ]


def _stage(name: str, type_name: str, parms: dict | None = None, inputs: list | None = None) -> dict:
    spec = {"name": name, "type": [type_name], "parms": parms or {}, "context": "stage"}
    if inputs:
        spec["inputs"] = inputs
    return spec


def _create(key: str, type_name: str, parms: dict, note: str) -> dict:
    nodes = [_stage("lop", type_name, parms), *_import("after", "lop")]
    return {"kind": "node", "key": key, "type": [type_name], "parms": {}, "create": True,
            "graph": {"node": "after", "before": "after", "nodes": nodes}, "note": note}


def _modify(key: str, type_name: str, base: list[dict], parms: dict, note: str, extra_inputs: list | None = None) -> dict:
    """base（/stage の、元の LOP の並び）の最後に、type_name をつないだもの。適用前は、元の LOP の最後。"""
    last = base[-1]["name"]
    nodes = [*base, _stage("lop", type_name, parms, [last, *(extra_inputs or [])]), *_import("before", last), *_import("after", "lop")]
    return {"kind": "node", "key": key, "type": [type_name], "parms": {}, "graph": {"node": "after", "before": "before", "nodes": nodes}, "note": note}


CUBE = _stage("cube", "cube")
SPHERE = _stage("sphere", "sphere", {"t": [2.5, 0, 0]})

LOP_RECIPES = [
    _create("lop/cube", "cube", {}, "/stage に Cube を置く（USD の箱のプリム /cube1 ができる）。SOP の LOP Import と Unpack USD で、形にして撮った"),
    _create("lop/sphere", "sphere", {}, "/stage に Sphere を置く（USD の球のプリム）。SOP の LOP Import と Unpack USD で、形にして撮った"),
    _modify("lop/xform", "xform", [CUBE], {"t": [0, 1, 0], "r": [0, 45, 30]},
            "Cube のあとに Transform（xform）をつなぎ、移動 (0, 1, 0)・回転 (0, 45, 30) を与える。適用前は、Cube だけ"),
    _modify("lop/merge", "merge", [CUBE], {}, "Cube と、右にずらした Sphere を、Merge で 1 つのステージにまとめる。適用前は、Cube だけ",
            extra_inputs=["sphere"]),
    _modify("lop/prune", "prune", [CUBE, _stage("both", "merge", {}, ["cube", "sphere"])], {"primpattern1": "/sphere", "method": "deactivate"},
            "Cube と Sphere をまとめたステージから、Prune で /sphere（球のプリム）を外す（method = deactivate: プリムを無効にする。初期値の makeinvisible は、見えなくするだけ）。適用前は、両方ある"),
]
# merge・prune が使う Sphere を、先頭に足す（nodes は、元のものから順に書く）
for _r in LOP_RECIPES:
    names = [n["name"] for n in _r["graph"]["nodes"]]
    if any("sphere" in (n.get("inputs") or []) for n in _r["graph"]["nodes"]) and "sphere" not in names:
        _r["graph"]["nodes"].insert(0, copy.deepcopy(SPHERE))


def build() -> list[dict]:
    return copy.deepcopy(LOP_RECIPES)
