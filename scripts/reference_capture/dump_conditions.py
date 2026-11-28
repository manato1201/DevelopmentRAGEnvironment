"""Reference の「適用前・適用後」の画像を撮ったネットワークの条件を、実機（hython）で書き出す（2026-11-28）。

  hython dump_conditions.py <出力.json> [キー,キー,...]

実証実験の参加者が、Reference のノード例を見て作り直しても、同じ結果にならなかった（板の大きさ・位置、どの出力をどの入力に
つなぐか、何フレーム目を見るか、が説明の文に無かった）。撮影のレシピ（recipes.py）と同じ作り方でネットワークを組み、
画面に出る名前（ノードの表示名・パラメータの表示名とタブ・入出力の名前）を、Houdini から取って書き出す。
撮影はしない（cook もしない）ので、全部のレシピでも数十秒で終わる。

あわせて、Tab メニューに出ない種類（hidden() / deprecated()）を使っていないかを調べる（"tab_hidden"）。
出力: {キー: {"frame", "display", "nodes": [...], "lights": [...], "note", "tab_hidden": [...]}, ...}、失敗したキーは {"error": 理由}
"""

import json
import os
import sys

import hou  # noqa: E402  (hython の中でだけ動く)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# hython_shot.py は、読み込むと main() が動く。組み立ての関数だけを使うため、最後の main() の呼び出しを除いて読み込む
_src = open(os.path.join(HERE, "hython_shot.py"), encoding="utf-8").read()
_src = _src[: _src.rstrip().rfind("\nmain()")]
_shot: dict = {"__name__": "hython_shot_lib", "__file__": os.path.join(HERE, "hython_shot.py")}
exec(compile(_src, "hython_shot.py", "exec"), _shot)


class RecipeError(Exception):
    pass


def _fail(reason: str) -> None:
    raise RecipeError(reason)


_shot["fail"] = _fail  # 撮影用の fail（終了する）を、例外に差し替える

from recipes import RECIPES  # noqa: E402

FRAMES = _shot["FRAMES"]


def _folders(node) -> dict:
    """パラメータ名 → 置かれているタブ・折りたたみの道筋（"Sourcing > Emission"）。"""
    out: dict = {}

    def walk(entries, path):
        for entry in entries:
            if entry.type() == hou.parmTemplateType.Folder:
                walk(entry.parmTemplates(), path + (entry.label(),))
            else:
                out[entry.name()] = " > ".join(path)
    try:
        walk(node.parmTemplateGroup().entries(), ())
    except Exception:  # noqa: BLE001
        pass
    return out


def _value_text(template, value) -> str:
    """値を、画面で見える形に（メニューは表示名、チェックボックスは入れる・外す、式は式のまま）。"""
    if isinstance(value, dict) and "expr" in value:
        return f"式 {value['expr']}"
    try:
        kind = template.type()
        if kind == hou.parmTemplateType.Toggle:
            on = bool(value[0] if isinstance(value, (list, tuple)) else value)
            return "入れる" if on else "外す"
        if kind == hou.parmTemplateType.Menu:
            items, labels = list(template.menuItems()), list(template.menuLabels())
            raw = value[0] if isinstance(value, (list, tuple)) else value
            index = raw if isinstance(raw, int) else (items.index(str(raw)) if str(raw) in items else -1)
            if 0 <= index < len(labels):
                return f"{labels[index]}"
    except Exception:  # noqa: BLE001
        pass
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _parm_rows(node, parms: dict) -> list:
    folders = _folders(node)
    rows = []
    for name, value in (parms or {}).items():
        tup = node.parmTuple(name)
        template = tup.parmTemplate() if tup is not None else (node.parm(name).parmTemplate() if node.parm(name) is not None else None)
        label = template.label() if template is not None else name
        if isinstance(value, str) and value.startswith("@"):
            value = f"{value[1:]} のパス"
        rows.append({"name": name, "label": label, "where": folders.get(template.name() if template is not None else name, ""),
                     "value": _value_text(template, value) if template is not None else str(value)})
    return rows


def _labels(fn) -> list:
    try:
        return [str(x) for x in fn()]
    except Exception:  # noqa: BLE001
        return []


def _node_info(node, alias: str, parms: dict, context: str = "") -> dict:
    t = node.type()
    inputs = []
    in_labels = _labels(node.inputLabels)
    for conn in node.inputConnections():
        src = conn.inputNode()
        out_labels = _labels(src.outputLabels) if src is not None else []
        i, o = conn.inputIndex(), conn.outputIndex()
        inputs.append({"index": i, "label": in_labels[i] if i < len(in_labels) else "",
                       "from": src.name() if src is not None else "", "output": o,
                       "output_label": out_labels[o] if o < len(out_labels) else ""})
    inputs.sort(key=lambda x: x["index"])
    hidden = bool(t.hidden()) or bool(t.deprecated())
    info = {"name": alias, "type": t.name(), "label": t.description(), "category": t.category().name(), "context": context,
            "hidden": hidden, "parms": _parm_rows(node, parms), "inputs": inputs}
    # ポートの並び（Reference のノード図で、どの位置の点から線を出すかを、実物どおりに描くため。2026-11-28）
    try:
        max_inputs = int(t.maxNumInputs())
    except Exception:  # noqa: BLE001
        max_inputs = len(in_labels)
    info["multi_input"] = max_inputs > 8  # Merge のように、いくつでもつなげる入力（画面では、横長の 1 つの口）
    info["input_labels"] = [] if info["multi_input"] else in_labels[:max(0, max_inputs)]
    info["output_labels"] = _labels(node.outputLabels)[:8]
    if hidden:
        info["replacement"] = _replacement(t)
    return info


# SideFX の deprecationInfo に代わりが書かれていない、Tab に出ない種類の、近いもの（Houdini 22 で確かめた）
_NEAREST = {"polycap": "PolyFill（polyfill）", "knife": "Clip（clip::2.0。シェルフの Knife もこれを置く）"}


def _replacement(t) -> str:
    try:
        new = (t.deprecationInfo() or {}).get("new_type") if t.deprecated() else None
        if new is not None:
            return f"{new.description()}（{new.name()}）"
    except Exception:  # noqa: BLE001
        pass
    return _NEAREST.get(t.name().split("::")[0], "")


def conditions_for(recipe: dict) -> dict:
    obj = hou.node("/obj")
    for child in list(obj.children()):
        child.destroy()
    stage = hou.node("/stage")
    for child in list(stage.children()) if stage is not None else []:
        child.destroy()
    geo = obj.createNode("geo", "ref")
    for child in geo.children():
        child.destroy()
    nodes: list = []
    graph = recipe.get("graph")
    display = ""
    if recipe.get("cop"):
        raise RecipeError("COP のレシピは、別の書き方（copnet の中）なので、まだ書き出さない")
    if graph and graph.get("tool_recipe"):
        raise RecipeError("ツールのレシピ（Houdini 付属）で置くので、手で組む条件ではない")
    if graph:
        made_order = []
        node, _before = _shot["build_graph"](geo, graph)
        display = graph["node"]
        for spec in graph["nodes"]:
            context = str(spec.get("context") or "")
            parent = stage if context == "stage" else (obj.node(context[4:]) if context.startswith("dop:") else geo)
            made = parent.node(spec["name"]) if parent is not None else None
            if made is None:
                raise RecipeError(f"{spec['name']} が見つかりません")
            made_order.append(_node_info(made, spec["name"], spec.get("parms") or {}, context))
        nodes = made_order
    else:
        create = bool(recipe.get("create"))
        for i, spec in enumerate([] if create else (recipe.get("inputs") or [recipe["input"]])):
            last = _shot["build_chain"](geo, spec, f"in{i}")
            del last
        node = _shot["make_node"](geo, recipe["type"], "node")
        for i, spec in enumerate([] if create else (recipe.get("inputs") or [recipe["input"]])):
            chain = [geo.node(f"in{i}")] + [geo.node(f"in{i}_{j}") for j in range(len(spec.get("after") or []))]
            node.setInput(i, chain[-1])
            nodes.append(_node_info(chain[0], f"in{i}", spec.get("parms") or {}))
            for j, step in enumerate(spec.get("after") or []):
                nodes.append(_node_info(chain[j + 1], f"in{i}_{j}", step.get("parms") or {}))
        if recipe.get("vop"):
            _shot["build_vop"](node, recipe["vop"])
        parms = dict(recipe.get("parms") or {})
        sweep = recipe.get("sweep")
        if sweep and not sweep.get("node"):
            parms[sweep["parm"]] = sweep["to"]
        _shot["set_parms"](node, parms)
        info = _node_info(node, "node", parms)
        if recipe.get("vop"):
            info["vop"] = []
            for spec in recipe["vop"].get("nodes") or []:
                child = node.node(spec["name"])
                if child is not None:
                    info["vop"].append(_node_info(child, spec["name"], spec.get("parms") or {}))
        nodes.append(info)
        if sweep and sweep.get("node"):
            target = geo.node(sweep["node"])
            for n in nodes:
                if target is not None and n["name"] == sweep["node"]:
                    n["parms"] += _parm_rows(target, {sweep["parm"]: sweep["to"]})
        display = "node"
    lights = []
    for spec in recipe.get("lights") or []:
        light = _shot["make_node"](obj, spec["type"], spec["name"])
        _shot["set_parms"](light, spec.get("parms"))
        lights.append(_node_info(light, spec["name"], spec.get("parms") or {}, "obj"))
    sim = int(recipe.get("sim") or 0)
    animate = bool(recipe.get("animate"))
    frame = sim or (FRAMES if animate else 1)
    hidden = sorted({f"{n['label']}（{n['type']}）" for n in nodes + lights + [v for n in nodes for v in n.get("vop", [])] if n["hidden"]})
    return {"frame": frame, "sim": bool(sim), "display": display, "nodes": nodes, "lights": lights,
            "note": str(recipe.get("note") or ""), "tab_hidden": hidden}


def main() -> None:
    out_path = sys.argv[1]
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 and sys.argv[2] else set()
    result: dict = {}
    for recipe in RECIPES:
        key = recipe["key"]
        if only and key not in only:
            continue
        try:
            result[key] = conditions_for(recipe)
        except RecipeError as exc:
            result[key] = {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 -- 1 件が壊れても、ほかは続ける
            result[key] = {"error": f"{type(exc).__name__}: {exc}"}
        print(("NG " if "error" in result[key] else "OK ") + key, flush=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
