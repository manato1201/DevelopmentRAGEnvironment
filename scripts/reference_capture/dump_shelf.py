"""シェルフツールの「どこにあるか」を、hython で取り出す（2026-11-24）。

使い方:  hython dump_shelf.py <keys.json> <out.json>
  keys.json … ["sop_box", "pyro_billowysmoke", ...]（シェルフのキーの、shelf/ の後ろ）
  out.json  … {キー: {"label", "icon", "shelf": {"name", "label"}, "set": {"name", "label"} | null,
                      "tabs": [{"name", "label"}, ...]（そのシェルフを含む、シェルフセットのタブ）,
                      "tools": [{"name", "label", "icon"}, ...]（そのシェルフのボタン）}}
シェルフの名前は、hython の名前（sop_polyextrude_2_0 → sop_polyextrude::2.0）に直して探す。見つからないキーは、出力に入れない。
"""

import json
import re
import sys

import hou  # noqa: E402  (hython の中でだけ動く)

# 画面の既定のレイアウトで、よく見るシェルフセット（タブの並び）を、先に探す
PREFERRED_SETS = ("shelf_set_1", "shelf_set_2", "shelf_set_td", "shelf_set_character")


def resolve(tools: dict, key: str):
    """キーから、hython のツールを探す。sop_polyextrude_2_0 は、sop_polyextrude::2.0 のこと。"""
    if key in tools:
        return tools[key]
    match = re.fullmatch(r"(.+)_(\d+)_(\d+)", key)
    if match:
        candidate = f"{match.group(1)}::{match.group(2)}.{match.group(3)}"
        if candidate in tools:
            return tools[candidate]
    return None


def main() -> None:
    keys = json.loads(open(sys.argv[1], encoding="utf-8").read())
    tools = hou.shelves.tools()
    shelves = list(hou.shelves.shelves().values())
    sets = hou.shelves.shelfSets()
    order = [n for n in PREFERRED_SETS if n in sets] + [n for n in sets if n not in PREFERRED_SETS]
    out = {}
    for key in keys:
        tool = resolve(tools, key)
        if tool is None:
            continue
        shelf = next((s for s in shelves if tool in s.tools()), None)
        if shelf is None:
            continue
        shelf_set = next((sets[n] for n in order if any(s.name() == shelf.name() for s in sets[n].shelves())), None)
        out[key] = {
            "label": tool.label(), "icon": tool.icon(),
            "shelf": {"name": shelf.name(), "label": shelf.label()},
            "set": {"name": shelf_set.name(), "label": shelf_set.label()} if shelf_set else None,
            "tabs": [{"name": s.name(), "label": s.label()} for s in (shelf_set.shelves() if shelf_set else [shelf])],
            "tools": [{"name": t.name(), "label": t.label(), "icon": t.icon()} for t in shelf.tools() if t is not None],
        }
    open(sys.argv[2], "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"OK {len(out)}/{len(keys)}")


main()
