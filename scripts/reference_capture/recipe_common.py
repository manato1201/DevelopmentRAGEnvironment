"""撮影レシピが共通で使う、入力の形（2026-11-24）。recipes.py・recipes_vex.py・recipes_more.py が、ここから読む（同じ値を、3 か所に書かない）。"""

from __future__ import annotations

GRID = {"type": "grid", "parms": {"rows": 60, "cols": 60, "size": [4, 4]}}
GRID_COARSE = {"type": "grid", "parms": {"rows": 10, "cols": 10, "size": [3, 3]}}  # 面が 100 枚（面の番号で、消す範囲を言える）
SPHERE = {"type": "sphere", "parms": {"type": 2, "rows": 40, "cols": 80}}  # 多角形メッシュの球（rows・cols が効く種類。面が約 3000 枚）


def input_specs(recipe: dict) -> list[dict]:
    """レシピの「入力の鎖」（元のノード + 後ろにつなぐノード）の一覧。入力を持たないもの（create）と、つなぎ方を書くもの（graph）は、空。"""
    if recipe.get("create") or recipe.get("graph"):
        return []
    return recipe.get("inputs") or [recipe["input"]]


def graph_nodes(recipe: dict) -> list[dict]:
    """graph（つなぎ方を書くレシピ）のノードの一覧。無ければ、空。"""
    return list((recipe.get("graph") or {}).get("nodes") or [])


# 入力が無く、置くだけで形ができるノード（Box・Sphere など）の動き: 大きさ・長さ・回数のパラメータを、小さい値から最後の値まで動かす（2026-11-24）。
# （まわりを 1 周するだけだと、球・ドーナツのように、回しても見た目が変わらない形は、止まった絵になる）
CREATE_SWEEPS = {
    "box": ("scale", 0.2, 1.0), "sphere": ("scale", 0.2, 1.0), "tube": ("height", 0.2, 1.0), "torus": ("scale", 0.2, 1.0),
    "grid": ("sizex", 0.5, 3.0), "line": ("dist", 0.2, 2.0), "circle": ("scale", 0.2, 1.0), "platonic": ("radius", 0.2, 1.0),
    "lsystem": ("generations", 1, 7), "metaball": ("radx", 0.3, 1.0), "font": ("fontsize", 0.3, 1.0), "spiral": ("turns", 1, 6),
}


def create_sweep(type_name: str) -> dict | None:
    """create のノード（type_name = ノードの型の名前）の、動かすパラメータ。無ければ None。"""
    spec = CREATE_SWEEPS.get(type_name.split("::")[0])
    return {"parm": spec[0], "from": spec[1], "to": spec[2]} if spec else None
