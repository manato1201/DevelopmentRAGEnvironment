"""Houdini（hython）で、ノードの種類ごとに、本物のパラメータ名・メニュー項目の名前を書き出す（2026-11-20）。

使い方（hython で）:  hython dump_parms.py <キーの JSON（["sop/scatter", ...]）> <出力の JSON>
出力: {キー: {"type": 実際の種類名, "names": [パラメータの内部名・表示名・メニュー項目・フォルダ名, ...]} または null（その種類が無い）,
       "__node_types__": [全部のノード種類の内部名・表示名]}  （説明が、別のノードの名前を挙げても、嘘と見なさないため）

説明に書かれたパラメータ名が、本物の Houdini に在るかを確かめるための材料（scripts/audit_reference.py が使う）。
"""

import json
import sys

import hou  # type: ignore

# cop は、Copernicus（Houdini 20.5 以降の新しい COP。カテゴリ名 Cop）。cop2 は、従来の COP（Cop2）。前は cop を Cop2 に当てていて、
# Copernicus のノードが「Houdini 22 に無い」ことになっていた（2026-11-24）。
CATEGORY_NAMES = {"sop": "Sop", "obj": "Object", "dop": "Dop", "lop": "Lop", "vop": "Vop", "cop2": "Cop2", "cop": "Cop",
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


def _slug(text):
    import re

    return re.sub(r"[^0-9a-zA-Z_]+", "_", str(text or "").strip()).strip("_").lower() or "item"


def apex_info(key, registry, names):
    """APEX のノード（キーは apex/skel--GetParent。レジストリの名前は skel::GetParent）の、本物の入出力のポート名。
    見つからなければ None（Houdini 22 に、このノードが無い）。"""
    import re

    page = key.partition("/")[2]
    candidates = [page, page.replace("--", "::")]
    registry_name = next((c for c in candidates if c in names), None)
    if registry_name is None:  # ジェネリックの版（Abs<Float> など）しか無いもの
        registry_name = next((n for n in sorted(names) if re.sub(r"<.*>", "", n) in candidates), None)
    if registry_name is None:
        return None
    found = {registry_name, page, page.split("--")[-1]}
    ports = []
    try:
        signature = registry.getSignature(registry_name)
        for direction, parms in (("input", signature.inputs()), ("output", signature.outputs())):
            for parm in parms:
                text = repr(parm)  # <APEX_Parm 'geo' Geometry>
                match = re.match(r"<APEX_Parm '([^']*)'\s*([^>]*)>", text)
                if match and not match.group(1).startswith("__"):
                    found.add(match.group(1))
                    ports.append({"direction": direction, "name": match.group(1), "type": match.group(2).strip()})
    except Exception:  # noqa: BLE001 -- 署名が読めなくても、実在は確かめられた
        pass
    return {"type": registry_name, "names": sorted(n for n in found if n), "ports": ports}


def shelf_info(key, tools_by_slug, shelf_of):
    """シェルフツール（キーは shelf/<ツールの内部名の slug>）の、本物の表示名・内部名・属するシェルフ。無ければ None。"""
    tool = tools_by_slug.get(key.partition("/")[2])
    if tool is None:
        return None
    found = {tool.name(), tool.label()}
    shelf = shelf_of.get(tool.name())
    if shelf:
        found.add(shelf)
    try:
        found.add(tool.helpURL())
    except Exception:  # noqa: BLE001
        pass
    return {"type": tool.name(), "names": sorted(n for n in found if n), "label": tool.label(), "shelf": shelf or ""}


def main():
    keys = json.load(open(sys.argv[1], encoding="utf-8"))
    categories = hou.nodeTypeCategories()
    result = {}
    apex_registry = apex_names = None
    tools_by_slug = shelf_of = None
    for key in keys:
        context, _, name = key.partition("/")
        if context == "apex":
            if apex_registry is None:
                import apex  # type: ignore

                apex_registry = apex.Registry()
                apex_names = set(apex_registry.findMatchingNames("*"))
            result[key] = apex_info(key, apex_registry, apex_names)
            continue
        if context == "shelf":
            if tools_by_slug is None:
                tools_by_slug = {_slug(t.name()): t for t in hou.shelves.tools().values()}
                shelf_of = {}
                for shelf in hou.shelves.shelves().values():
                    for tool in shelf.tools():
                        shelf_of.setdefault(tool.name(), shelf.label())
            result[key] = shelf_info(key, tools_by_slug, shelf_of)
            continue
        category = categories.get(CATEGORY_NAMES.get(context, context.capitalize()))
        node_type = resolve(category, name) if category is not None else None
        if node_type is None and context == "cop" and categories.get("Cop2") is not None:
            node_type = None  # Copernicus にだけ、このノードが無いとき、従来の COP の同名のノードを、代わりに使わない（別のノードの説明になる）
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
    if tools_by_slug is not None:  # 説明が、ほかのシェルフツールの名前を挙げても、嘘と見なさない
        result["__shelf_labels__"] = sorted({t.label() for t in tools_by_slug.values() if t.label()} | {name for shelf in hou.shelves.shelves().values() for name in (shelf.label(),)})
    if apex_names is not None:  # 説明が、ほかの APEX ノードの名前を挙げても、嘘と見なさない
        import re as _re

        result["__apex_names__"] = sorted({n for name in apex_names for n in (name, _re.sub(r"<.*>", "", name), name.split("::")[-1])})
    json.dump(result, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
    print("done", len(result))


if __name__ == "__main__":  # hython が、スクリプトとして実行するとき。テストが import しても、動かない
    main()
