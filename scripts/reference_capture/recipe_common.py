"""撮影レシピが共通で使う、入力の形（2026-11-24）。recipes.py・recipes_vex.py・recipes_more.py が、ここから読む（同じ値を、3 か所に書かない）。"""

from __future__ import annotations

GRID = {"type": "grid", "parms": {"rows": 60, "cols": 60, "size": [4, 4]}}
GRID_COARSE = {"type": "grid", "parms": {"rows": 10, "cols": 10, "size": [3, 3]}}  # 面が 100 枚（面の番号で、消す範囲を言える）
SPHERE = {"type": "sphere", "parms": {"type": 2, "rows": 40, "cols": 80}}  # 多角形メッシュの球（rows・cols が効く種類。面が約 3000 枚）
