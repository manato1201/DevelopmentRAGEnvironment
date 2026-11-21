"""Reference の「適用前後」の撮影レシピ（2026-11-19）。1 件 = 1 ノード。hython_shot.py の説明を参照。

形:  Recipe(kind, key, type（候補の並び）, input（前の形）, parms（適用後の値）, sweep（動かすパラメータ）, graph（ノード図に描く名前）, keep（形に効かなくても書く値））
  撮る前に、parms の値を 1 つずつ初期値に戻して、形が変わらない値（効いていない値）があれば、撮らない（hython_shot.py。2026-11-21）
  ・key は、reference_data.catalog() のキー（例: sop/mountain）
  ・まず少数（検証用）。増やすときは、ここに足すだけ（撮影は capture.py が、全部のレシピに同じ手順で行う）
"""

from __future__ import annotations

GRID = {"type": "grid", "parms": {"rows": 60, "cols": 60, "size": [4, 4]}}
GRID_COARSE = {"type": "grid", "parms": {"rows": 10, "cols": 10, "size": [3, 3]}}  # 面が 100 枚（面の番号で、消す範囲を言える）
SPHERE = {"type": "sphere", "parms": {"type": 2, "rows": 40, "cols": 80}}  # 多角形メッシュの球（rows・cols が効く種類。面が約 3000 枚）
BOX_FLAT = {"type": "box", "parms": {"size": [2, 0.6, 1]}}  # 平たい箱（回すと、向きが変わったことが分かる）
OPEN_ARC = {"type": "circle", "parms": {"type": 1, "arc": 1, "angle": [0, 270], "divs": 32, "r": 1}}  # 多角形の開いた円弧（面を持たない線）

TALL_RIBBON = {"type": "grid", "parms": {"orient": 0, "size": [1.2, 3], "rows": 40, "cols": 6}}  # 縦に細かく分割した細長い板（円筒だと、ねじっても見た目が変わらない）

RECIPES: list[dict] = [
    {"kind": "node", "key": "sop/mountain", "type": ["mountain::2.0", "mountain"], "input": GRID,
     "parms": {"height": 1.2}, "sweep": {"parm": "height", "from": 0.0, "to": 1.2}},
    {"kind": "node", "key": "sop/scatter", "type": ["scatter::2.0", "scatter"], "input": GRID,
     "parms": {"npts": 800}, "sweep": {"parm": "npts", "from": 20, "to": 800}},
    {"kind": "node", "key": "sop/twist", "type": ["twist::2.0", "twist"], "input": TALL_RIBBON,
     "parms": {"strength": 160, "paxis": 1}, "sweep": {"parm": "strength", "from": 0, "to": 160}},
    {"kind": "node", "key": "sop/subdivide", "type": ["subdivide"], "input": {"type": "box", "parms": {}},
     "parms": {"iterations": 3}, "sweep": {"parm": "iterations", "from": 0, "to": 3}},
    {"kind": "node", "key": "sop/polyextrude", "type": ["polyextrude::2.0", "polyextrude"], "input": GRID,
     "parms": {"dist": 0.5}, "sweep": {"parm": "dist", "from": 0.0, "to": 0.5}},
    # 2026-11-20 に足した分。足す前に、`hython hython_shot.py <recipe.json> check x` で、cook が通り、前後で形が変わることを確かめる
    {"kind": "node", "key": "sop/xform", "type": ["xform"], "input": BOX_FLAT,
     "parms": {"r": [0, 50, 0]}, "sweep": {"parm": "ry", "from": 0, "to": 50}},
    {"kind": "node", "key": "sop/peak", "type": ["peak"], "input": SPHERE,
     "parms": {"dist": 0.4}, "sweep": {"parm": "dist", "from": 0.0, "to": 0.4}},
    {"kind": "node", "key": "sop/polyreduce", "type": ["polyreduce::2.0", "polyreduce"], "input": SPHERE,
     "parms": {"percentage": 3}, "sweep": {"parm": "percentage", "from": 100, "to": 3}},
    {"kind": "node", "key": "sop/color", "type": ["color"], "input": SPHERE,
     "parms": {"colortype": 1}, "note": 'colortype = 1 は、メニューの「Bounding Box」（形の大きさの中での位置で、色が変わる）'},
    {"kind": "node", "key": "sop/blast", "type": ["blast"], "input": GRID_COARSE,
     "parms": {"group": "0-49", "grouptype": 4}, "keep": ["grouptype"], "note": 'grouptype = 4 は、メニューの「Primitives」。group = 0-49 は、面の番号 0〜49（100 枚のうち、半分）を消す'},
    {"kind": "node", "key": "sop/delete", "type": ["delete"], "input": GRID_COARSE,
     "parms": {"group": "0-49", "entity": 0}, "note": 'entity = 0 は、メニューの「Primitives」。group = 0-49 は、面の番号 0〜49（100 枚のうち、半分）を消す（negate は初期値の「Delete Selected」）'},
    {"kind": "node", "key": "sop/polywire", "type": ["polywire"], "input": OPEN_ARC,
     "parms": {"radius": 0.06}, "sweep": {"parm": "radius", "from": 0.005, "to": 0.06}, "note": '入力の円弧は、circle の type = 1（Polygon）、arc = 1（Open Arc）、angle = 0〜270。面を持たない線を、radius の太さの管にする'},
    {"kind": "node", "key": "sop/boolean", "type": ["boolean::2.0", "boolean"],
     "inputs": [{"type": "box", "parms": {"size": [1.4, 1.4, 1.4]}}, {"type": "sphere", "parms": {"type": 2, "rows": 24, "cols": 48, "rad": [0.95, 0.95, 0.95]}}],
     "parms": {"booleanop": 2}, "sweep": {"node": "in1", "parm": "tx", "from": -2.4, "to": 0.0},
     "note": 'booleanop = 2 は、メニューの「Subtract」（A から B を引く）。箱から球をくりぬく。動きは、球（B）を、横から箱に近づける（球の tx = -2.4 → 0）'},
    {"kind": "node", "key": "sop/copytopoints", "type": ["copytopoints::2.0", "copytopoints"],
     "inputs": [{"type": "box", "parms": {"size": [0.25, 0.25, 0.25]}},
                {"type": "grid", "parms": {"rows": 10, "cols": 10, "size": [4, 4]}, "after": [{"type": "scatter::2.0", "parms": {"npts": 40}}]}],
     "parms": {}, "sweep": {"node": "in1_0", "parm": "npts", "from": 4, "to": 40},
     "note": '動きは、2 番目の入力の点の数（scatter の npts = 4 → 40）を増やし、箱がコピーされる数が増えるところを見せる'},
    {"kind": "node", "key": "sop/attribwrangle", "type": ["attribwrangle"], "input": GRID,
     "parms": {"snippet": "@P.y = sin(@P.x * 3.0) * 0.3;"},
     "note": "snippet は、パラメータ画面で「VEXpression」と表示される欄そのものの名前（別の欄ではない）。Run Over は初期値の Points のまま"},
    {"kind": "node", "key": "sop/pointjitter", "type": ["pointjitter"], "input": GRID,
     "parms": {"scale": 0.1}, "sweep": {"parm": "scale", "from": 0.0, "to": 0.1}},
    {"kind": "node", "key": "sop/attribnoise", "type": ["attribnoise::2.0", "attribnoise"],
     "input": {"type": "grid", "parms": {"rows": 60, "cols": 60, "size": [4, 4]}, "after": [{"type": "attribwrangle", "parms": {"snippet": "v@Cd = {1,1,1};"}}]},
     "parms": {"attribs": "P", "amplitudev": 0.4, "elementsize": 1.0}, "sweep": {"parm": "amplitudev", "from": 0.0, "to": 0.4},
     "note": "attribs = P は、ベクトルの属性。ベクトルのときに効くのは amplitudev（スカラー用の amplitude は、P のときは形に効かない）"},
]
