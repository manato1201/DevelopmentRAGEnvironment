"""Pyro のシェルフツールの撮影レシピ（2026-11-25）。recipes.py から読み込まれる。

Houdini 付属のツールのレシピ（hou.data.dataFromRecipe。シェルフの Simple Fireball などが置くノードの組み立て）を、そのまま作って動かす
（hython_shot.py の build_tool_recipe）。古い DOP 版のシェルフツール（Pyro FX タブの Fireball など）は、画面の操作（hou.ui）が要るので、
hython では作れない。なので、同じ種類の効果の SOP 版のレシピの絵を付ける（説明の「例」は、この絵の条件に合わせて作り直す）。
"nodes" は、ノード図と説明の材料に使う、主なノードのつながり（レシピの全部ではない）。撮影では使わない。
"""

from __future__ import annotations

import copy


def _chain(*names_types: tuple[str, str]) -> list[dict]:
    """(名前, 型) の並びを、1 本の鎖にする（それぞれ、1 つ前の出力を、入力 0 につなぐ）。"""
    nodes = []
    for i, (name, type_name) in enumerate(names_types):
        nodes.append({"name": name, "type": [type_name], "inputs": [names_types[i - 1][0]] if i else []})
    return nodes


def _tool(key: str, recipe: str, label: str, chain: list[dict], node: str, before: str | None, sim: int, note: str,
          rewire: dict | None = None) -> dict:
    graph = {"tool_recipe": recipe, "node": node, "nodes": chain}
    if before:
        graph["before"] = before
    if rewire:
        graph["rewire"] = rewire
    solver = next((n["type"][0] for n in chain if n["type"][0].endswith("solver")), chain[-1]["type"][0])  # 主なノード = ソルバー
    out = {"kind": "shelf", "key": key, "type": [solver], "parms": {}, "sim": sim, "graph": graph, "tool_label": label,
           "note": note}
    if not before:
        out["create"] = True  # 何も無いところから、全部を置くツール。「適用前」は無い（置く前は、空の画面）
    return out


FIREBALL = _tool(
    "shelf/geometry_pyrosimplefireball", "sidefx::recipe::pyro::fireball", "Simple Fireball",
    _chain(("add1", "add"), ("pyroburstsource1", "pyroburstsource"), ("volumerasterizeattributes1", "volumerasterizeattributes"),
           ("pyrosolver1", "pyrosolver"), ("pyrobakevolume1", "pyrobakevolume")),
    "pyrobakevolume1", None, 30,
    "Simple Fireball のレシピ（sidefx::recipe::pyro::fireball）が置くノードを、そのまま動かした。点 1 つ（Add）から、Pyro Burst Source が"
    "爆発の元の点を作り、Volume Rasterize Attributes でボリュームにして、Pyro Solver で 30 フレーム動かす。色は、Pyro Bake Volume（炎の明るさ・煙の色）",
    rewire={"pyrobakevolume1": "pyrosolver1"},  # レシピでは、間に「キャッシュが無いときの切り替え」（switchif）が入る。撮影では、ソルバーの出力を、そのまま見る
)

CANDLE = _tool(
    "shelf/pyro_candleflame", "sidefx::recipe::pyro::candleflame", "Candle",
    _chain(("sphere1", "sphere"), ("softtransform1", "softxform"), ("pyrosource1", "pyrosource"),
           ("volumerasterizeattributes1", "volumerasterizeattributes"), ("pyrosolver1", "pyrosolver"), ("pyrobakevolume1", "pyrobakevolume"),
           ("merge3", "merge")),
    "merge3", "merge2", 48,
    "Candle（ろうそくの炎）の、SOP 版のレシピ（sidefx::recipe::pyro::candleflame）が置くノードを、そのまま動かした。適用前は、ろうそくと芯だけ。"
    "適用後は、芯の上の小さな球（Sphere）から、Pyro Source で炎の元の点を作り、Pyro Solver で 48 フレーム動かした炎を、重ねる",
)

FLAMES = _tool(
    "shelf/pyro_burn", "sidefx::recipe::pyro::smokelessflame", "Flames",
    _chain(("circle1", "circle"), ("pyrosource1", "pyrosource"), ("volumerasterizeattributes1", "volumerasterizeattributes"),
           ("pyrosolver1", "pyrosolver"), ("pyropostprocess1", "pyropostprocess"), ("pyrobakevolume1", "pyrobakevolume")),
    "pyrobakevolume1", "circle1", 36,
    "Flames（炎）に近い、SOP 版のレシピ Smokeless Flame（sidefx::recipe::pyro::smokelessflame）が置くノードを、そのまま動かした。"
    "円（Circle）から、Pyro Source で炎の元の点を作り、Pyro Solver で 36 フレーム動かす。適用前は、元の円",
)

WISPY = _tool(
    "shelf/pyro_wispy", "sidefx::recipe::pyro::wispysmokea", "Wispy Smoke",
    _chain(("tube1", "tube"), ("transform1", "xform"), ("location_offset1", "xform"), ("pyrosource1", "pyrosource"),
           ("volumerasterizeattributes1", "volumerasterizeattributes"), ("pyrosolver1", "pyrosolver"), ("pyrobakevolume1", "pyrobakevolume")),
    "pyrobakevolume1", "location_offset1", 48,
    "Wispy Smoke（細くたなびく煙）の、SOP 版のレシピ（sidefx::recipe::pyro::wispysmokea）が置くノードを、そのまま動かした。"
    "筒（Tube）から、Pyro Source で煙の元の点を作り、Pyro Solver で 48 フレーム動かす。適用前は、元の筒",
)

DRY_ICE = _tool(
    "shelf/pyro_dryice", "sidefx::recipe::pyro::dryice", "Dry Ice",
    [{"name": "glass_model1", "type": ["subnet"], "inputs": []},  # グラスと液面の形（レシピの中の subnet）
     {"name": "merge1", "type": ["merge"], "inputs": ["glass_model1"]},
     {"name": "GEO_PYRO_Source1", "type": ["null"], "inputs": ["glass_model1"]},
     {"name": "pyrosource1", "type": ["pyrosource"], "inputs": ["GEO_PYRO_Source1"]},
     {"name": "volumerasterizeattributes1", "type": ["volumerasterizeattributes"], "inputs": ["pyrosource1"]},
     {"name": "pyrosolver1", "type": ["pyrosolver"], "inputs": ["volumerasterizeattributes1", "merge1"]},  # 2 番目の入力: ぶつかる相手（グラス）
     {"name": "merge3", "type": ["merge"], "inputs": ["pyrosolver1", "merge1"]}],
    "merge3", "merge1", 48,
    "Dry Ice（ドライアイスの、低く広がる煙）の、SOP 版のレシピ（sidefx::recipe::pyro::dryice）が置くノードを、そのまま動かした。"
    "グラスの中の液面から、Pyro Source で煙の元の点を作り、Pyro Solver で 48 フレーム動かす。煙は、グラスからあふれて、下へ流れる。適用前は、グラスだけ",
)

EXPLOSION = _tool(
    "shelf/pyro_explosion", "sidefx::recipe::pyro::groundexplosiona", "Explosion",
    _chain(("add1", "add"), ("transform1", "xform"), ("pyroburstsource1", "pyroburstsource"), ("volumerasterizeattributes2", "volumerasterizeattributes"),
           ("pyrosolver_explosion1", "pyrosolver"), ("pyrobakevolume1", "pyrobakevolume")),
    "pyrobakevolume1", None, 30,
    "Explosion（爆発）に近い、SOP 版のレシピ Ground Explosion（sidefx::recipe::pyro::groundexplosiona）が置くノードを、そのまま動かした。"
    "点 1 つ（Add）から、Pyro Burst Source が爆発の元の点を作り、Pyro Solver で 30 フレーム動かす",
    rewire={"pyrobakevolume1": "pyrosolver_explosion1"},
)

# CANDLE・FLAMES は、撮らない（2026-11-25 に試した。Candle は、炎が、芯から離れた高さに映る。Flames（煙の無い炎）は、
# ビューポートの表示では、炎が映らない。どちらも、読んだ人を誤らせる絵になる）
PYRO_TOOLS = [FIREBALL, WISPY, DRY_ICE, EXPLOSION]
SHELF_FROM = {"shelf/pyro_fireball": FIREBALL}  # 古い DOP 版の Fireball にも、SOP 版の Simple Fireball の絵を付ける


def build() -> list[dict]:
    out = copy.deepcopy(PYRO_TOOLS)
    for key, base in SHELF_FROM.items():
        recipe = copy.deepcopy(base)
        recipe["key"] = key
        out.append(recipe)
    return out
