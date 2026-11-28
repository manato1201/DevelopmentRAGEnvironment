"""reference_conditions.py — Reference の画像を撮ったネットワークの、同じ結果にする条件（2026-11-28）。

実証実験の参加者が、Reference のノード例を見て作り直しても、同じ結果にならなかった。説明の「実例」は AI が短くまとめた文で、
板の大きさ・位置、どの出力をどの入力につなぐか、何フレーム目を見るか、が抜けることがあった。
撮影のレシピと同じ作り方で組んだネットワークから、画面に出る名前（ノード・パラメータ・入出力の表示名）を、実機（hython）で書き出し
（scripts/reference_capture/dump_conditions.py）、説明に "conditions" として付けて公開する。ここは、その表示と点検。

conditions = {"frame": 40, "sim": true, "display": "final", "note": "...",
              "nodes": [{"name", "type", "label", "category", "context", "hidden", "replacement",
                         "parms": [{"name", "label", "where", "value"}], "inputs": [{"index", "label", "from", "output", "output_label"}],
                         "vop": [... 同じ形 ...]}],
              "lights": [... 同じ形 ...], "tab_hidden": ["Mountain（mountain::2.0）", ...]}
"""

from __future__ import annotations

import html

_MAX_NODES = 40
_MAX_ROWS = 40
_TEXT = 300

_WARN = "background-color:#422006;color:#fde68a;padding:6px"


def _s(value, limit: int = _TEXT) -> str:
    return str(value if value is not None else "")[:limit]


def _i(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_node(raw) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("type"):
        return None
    node = {k: _s(raw.get(k)) for k in ("name", "type", "label", "category", "context", "replacement")}
    node["hidden"] = bool(raw.get("hidden"))
    node["parms"] = [{k: _s(p.get(k)) for k in ("name", "label", "where", "value")}
                     for p in (raw.get("parms") or [])[:_MAX_ROWS] if isinstance(p, dict)]
    node["inputs"] = [{"index": _i(c.get("index")), "label": _s(c.get("label")), "from": _s(c.get("from")),
                       "output": _i(c.get("output")), "output_label": _s(c.get("output_label"))}
                      for c in (raw.get("inputs") or [])[:_MAX_ROWS] if isinstance(c, dict)]
    vop = [n for n in (_clean_node(v) for v in (raw.get("vop") or [])[:_MAX_NODES]) if n]
    if vop:
        node["vop"] = vop
    return node


def clean(raw) -> dict | None:
    """受け取った条件を、決まった形・長さにそろえる。使えなければ None。"""
    if not isinstance(raw, dict):
        return None
    nodes = [n for n in (_clean_node(r) for r in (raw.get("nodes") or [])[:_MAX_NODES]) if n]
    if not nodes:
        return None
    return {"frame": max(1, _i(raw.get("frame"), 1)), "sim": bool(raw.get("sim")), "display": _s(raw.get("display"), 64),
            "note": _s(raw.get("note"), 600), "nodes": nodes,
            "lights": [n for n in (_clean_node(r) for r in (raw.get("lights") or [])[:8]) if n],
            "tab_hidden": [_s(h, 120) for h in (raw.get("tab_hidden") or [])[:10]]}


def _ancestors(nodes: list[dict], start: str) -> set[str]:
    """start から、入力をさかのぼって届くノードの名前（start を含む）。"""
    by_name = {n["name"]: n for n in nodes}
    seen: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        stack.extend(c["from"] for c in by_name[name]["inputs"] if c.get("from"))
    return seen


def _place(node: dict) -> str:
    context = node.get("context") or ""
    if context == "stage":
        return "/stage（LOP）に"
    if context.startswith("dop:"):
        return f"DOP ネットワーク {context[4:]} の中に"
    if context == "obj":
        return "/obj に"
    return ""


def _node_lines(node: dict, esc) -> list[str]:
    title = f"<b>{esc(node['label'] or node['type'])}</b>（{esc(node['type'])}）"
    place = _place(node)
    lines = [f"{esc(place)}{title} を置き、名前を <code>{esc(node['name'])}</code> にする"]
    if node.get("hidden"):
        alt = f"。代わり: {esc(node['replacement'])}" if node.get("replacement") else ""
        lines.append(f"<span style='color:#fbbf24'>⚠ Tab メニューに出ない古いノードです{alt}</span>")
    for c in node["inputs"]:
        out = f"{c['output'] + 1} 番目の出力" + (f"（{esc(c['output_label'])}）" if c["output_label"] else "")
        inp = f"{c['index'] + 1} 番目の入力" + (f"（{esc(c['label'])}）" if c["label"] else "")
        lines.append(f"つなぐ: <code>{esc(c['from'])}</code> の {out} → {inp}")
    for p in node["parms"]:
        where = f"{esc(p['where'])} の " if p["where"] else ""
        lines.append(f"{where}<b>{esc(p['label'])}</b>（<code>{esc(p['name'])}</code>）= {esc(p['value'])}")
    if not node["parms"]:
        lines.append("パラメータは初期値のまま")
    return lines


def html_block(raw) -> str:
    """「同じ結果にする条件」の HTML。条件が無ければ ""。文字は、すべてエスケープする。"""
    cond = clean(raw)
    if cond is None:
        return ""
    esc = html.escape
    parts = ["<p style='margin-bottom:0'><b>同じ結果にする条件（上の画像を撮ったネットワーク。Houdini 22）</b></p>"]
    if cond["tab_hidden"]:
        parts.append(f"<p style='{_WARN}'>⚠ この例には、Tab メニューに出ない古いノードがあります: {esc('、'.join(cond['tab_hidden']))}。"
                     "古いファイルで見かけたときのための説明です。新しく作るときは、代わりのノードを使ってください</p>")
    used = _ancestors(cond["nodes"], cond["display"]) if cond["display"] else {n["name"] for n in cond["nodes"]}
    main = [n for n in cond["nodes"] if n["name"] in used]
    helper = [n for n in cond["nodes"] if n["name"] not in used]
    parts.append("<ol style='margin-top:2px'>")
    for node in main:
        lines = _node_lines(node, esc)
        sub = "".join(f"<li>{line}</li>" for line in lines[1:])
        vop = ""
        if node.get("vop"):
            vop = "<li>中に入り、次の VOP を置く:<ul>" + "".join(
                "<li>" + "<br>".join(_node_lines(v, esc)) + "</li>" for v in node["vop"]) + "</ul></li>"
        parts.append(f"<li>{lines[0]}<ul>{sub}{vop}</ul></li>")
    for light in cond["lights"]:
        lines = _node_lines(light, esc)
        parts.append(f"<li>{lines[0]}<ul>" + "".join(f"<li>{line}</li>" for line in lines[1:]) + "</ul></li>")
    last = f"表示フラグを <code>{esc(cond['display'])}</code> に付ける" if cond["display"] else "最後のノードに表示フラグを付ける"
    if cond["sim"]:
        last += f"。1 フレーム目から {cond['frame']} フレーム目まで再生して、{cond['frame']} フレーム目を見る（シミュレーションは、順に進めないと結果が出ない）"
    elif cond["frame"] > 1:
        last += f"。{cond['frame']} フレーム目を見る"
    parts.append(f"<li>{last}</li></ol>")
    if helper:
        parts.append("<p style='margin-top:0;color:#94a3b8'>適用前の画像を並べるためだけのノード（作らなくてよい）: "
                     + esc("、".join(f"{n['name']}（{n['label'] or n['type']}）" for n in helper)) + "</p>")
    if cond["note"]:
        parts.append(f"<p style='margin-top:0;color:#94a3b8'>補足: {esc(cond['note'])}</p>")
    return "".join(parts)
