"""Reference の「適用前後」の撮影レシピ（2026-11-19）。1 件 = 1 ノード。hython_shot.py の説明を参照。

形:  Recipe(kind, key, type（候補の並び）, input（前の形）, parms（適用後の値）, sweep（動かすパラメータ）, graph（ノード図に描く名前））
  ・key は、reference_data.catalog() のキー（例: sop/mountain）
  ・まず少数（検証用）。増やすときは、ここに足すだけ（撮影は capture.py が、全部のレシピに同じ手順で行う）
"""

from __future__ import annotations

GRID = {"type": "grid", "parms": {"rows": 60, "cols": 60, "size": [4, 4]}}
TALL_TUBE = {"type": "tube", "parms": {"height": 3, "rows": 30, "cols": 16, "rad": [0.5, 0.5]}}  # 縦に細かく分割した筒（ねじりが、見て分かる）

RECIPES: list[dict] = [
    {"kind": "node", "key": "sop/mountain", "type": ["mountain::2.0", "mountain"], "input": GRID,
     "parms": {"height": 1.2}, "sweep": {"parm": "height", "from": 0.0, "to": 1.2}},
    {"kind": "node", "key": "sop/scatter", "type": ["scatter::2.0", "scatter"], "input": GRID,
     "parms": {"npts": 800}, "sweep": {"parm": "npts", "from": 20, "to": 800}},
    {"kind": "node", "key": "sop/twist", "type": ["twist::2.0", "twist"], "input": TALL_TUBE,
     "parms": {"strength": 160}, "sweep": {"parm": "strength", "from": 0, "to": 160}},
    {"kind": "node", "key": "sop/subdivide", "type": ["subdivide"], "input": {"type": "box", "parms": {}},
     "parms": {"iterations": 3}, "sweep": {"parm": "iterations", "from": 0, "to": 3}},
    {"kind": "node", "key": "sop/polyextrude", "type": ["polyextrude::2.0", "polyextrude"], "input": GRID,
     "parms": {"dist": 0.5}, "sweep": {"parm": "dist", "from": 0.0, "to": 0.5}},
]
