"""Houdini（hython）で、ノードの種類ごとに、本物のパラメータ名・メニュー項目の名前を書き出す（2026-11-20）。

使い方（hython で）:  hython dump_parms.py <キーの JSON（["sop/scatter", ...]）> <出力の JSON>
出力: {キー: {"type": 実際の種類名, "names": [パラメータの内部名・表示名・メニュー項目・フォルダ名, ...]} または null（その種類が無い）,
       "__node_types__": [全部のノード種類の内部名・表示名]}  （説明が、別のノードの名前を挙げても、嘘と見なさないため）

説明に書かれたパラメータ名が、本物の Houdini に在るかを確かめるための材料（scripts/audit_reference.py が使う）。
"""

import json
import sys

import hou  # type: ignore

CATEGORY_NAMES = {"sop": "Sop", "obj": "Object", "dop": "Dop", "lop": "Lop", "vop": "Vop", "cop2": "Cop2", "cop": "Cop2",
                  "top": "Top", "chop": "Chop", "rop": "Driver", "out": "Driver", "shop": "Shop"}


def walk(templates, names):
    for template in templates:
        names.add(template.name())
        names.add(template.label())
        try:
            for label in template.menuLabels():
                names.add(label)
            for item in template.menuItems():
                names.add(item)
        except Exception:  # noqa: BLE001
            pass
        if hasattr(template, "parmTemplates"):
            walk(template.parmTemplates(), names)


_PARENTS = {}


def _scratch_parent(category):
    """そのカテゴリのノードを、試しに作れる親（作れない種類は None）。Sop は geo の中、Object は /obj。"""
    name = category.name()
    if name in _PARENTS:
        return _PARENTS[name]
    parent = None
    try:
        if name == "Sop":
            parent = hou.node("/obj").createNode("geo", "scratch_for_dump")
        elif name == "Object":
            parent = hou.node("/obj")
    except Exception:  # noqa: BLE001
        parent = None
    _PARENTS[name] = parent
    return parent


def created_type(category, name):
    """学習者が Tab メニューから作ると、実際にできる種類。同じ名前で版が複数あるとき（attribnoise と attribnoise::2.0 など）、
    hou.nodeType(category, name) は古い版を返すことがある。createNode が選ぶ版が、画面に出る版（パラメータが違う）。
    2026-11-20: attribnoise が、古い版の amp1・amp3 で点検されていて、実機の attribnoise::2.0（amplitude）とずれていた。"""
    parent = _scratch_parent(category)
    if parent is None:
        return None
    try:
        node = parent.createNode(name)
    except Exception:  # noqa: BLE001
        return None
    node_type = node.type()
    node.destroy()
    return node_type


def resolve(category, name):
    """名前から種類を探す。まず、createNode で実際にできる種類。版つき（mountain::2.0）や、別名（transform → xform）も、表示名が同じなら拾う。"""
    node_type = created_type(category, name)
    if node_type is not None:
        return node_type
    node_type = hou.nodeType(category, name)
    if node_type is not None:
        return node_type
    versions = sorted((n for n in category.nodeTypes() if n.startswith(name + "::")), reverse=True)
    if versions:
        return category.nodeTypes()[versions[0]]
    for node_type in category.nodeTypes().values():
        if node_type.description().replace(" ", "").lower() == name.replace(" ", "").lower() and not node_type.hidden():
            return node_type
    return None


def main():
    keys = json.load(open(sys.argv[1], encoding="utf-8"))
    categories = hou.nodeTypeCategories()
    result = {}
    for key in keys:
        context, _, name = key.partition("/")
        category = categories.get(CATEGORY_NAMES.get(context, context.capitalize()))
        node_type = resolve(category, name) if category is not None else None
        if node_type is None:
            result[key] = None
            continue
        names = {node_type.name(), node_type.description()}
        walk(node_type.parmTemplateGroup().entries(), names)
        result[key] = {"type": node_type.name(), "names": sorted(n for n in names if n)}
    everything = set()
    for category in categories.values():
        for node_type in category.nodeTypes().values():
            everything.add(node_type.name())
            everything.add(node_type.description())
    result["__node_types__"] = sorted(n for n in everything if n)
    json.dump(result, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
    print("done", len(result))


main()
