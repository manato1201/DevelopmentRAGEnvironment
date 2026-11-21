"""hython で、1 つのノードの「適用前」「適用後」「適用の動き（連番）」を、OpenGL ROP で 1 回だけ撮る（2026-11-19）。

使い方:  hython hython_shot.py <recipe.json> <before|after|clip|check> <出力>
    before / after … 出力は、PNG のパス
    clip           … 出力は、連番の PNG の置き場所のフォルダ（frame.0001.png …）
    check          … 撮らずに、レシピだけを調べる（出力は使わない。数秒で終わる）。レシピを足すときの確かめ用

制約（実測）: hython では、1 つのプロセスで OpenGL ROP の render() を 2 回呼ぶと、2 回目でクラッシュする（Houdini 22.0.506）。
  なので、1 回の起動で 1 回だけ撮る。前後で同じ構図にするため、毎回、前後の両方を cook して、カメラは両方のバウンディングボックスから決める。
レシピ（recipes.py の 1 件）: {"type": ["mountain::2.0", "mountain"], "input": {"type": "grid", "parms": {...}},
    "parms": {...適用後の値}, "sweep": {"parm": "height", "from": 0.0, "to": 1.2}}
  "input" / "inputs" の各項目は、{"type", "parms"} に加えて、"after": [{"type", "parms"}, …] を持てる（元のノードの後ろに、順に直列につなぐ。
    例: 凸凹の板 = grid の後ろに mountain）。その最後のノードが、その入力になる。
終了コード: 0 = 撮れた / 2 = レシピの不備（ノードが作れない・cook エラー・形が空・適用の前後で何も変わらない）。理由は、標準出力の最後の行（REASON: …）。
  「適用の前後で何も変わらない」は、点の数・面の数・形の大きさ・位置の合計・色（Cd）・法線（N）のどれも、前後で同じとき。
  何も変わらない絵を、「適用した結果」として載せない（読んだ人が、同じ手順で何も起きないと困るため）。
"""

import json
import math
import os
import sys

import hou  # noqa: E402  (hython の中でだけ動く)

FRAMES = 48
WIDTH = int(os.environ.get("REF_W", "960"))
HEIGHT = int(os.environ.get("REF_H", "540"))


def fail(reason: str) -> None:
    print("REASON: " + reason)
    sys.exit(2)


def set_parms(node, parms: dict) -> None:
    for name, value in (parms or {}).items():
        tup = node.parmTuple(name)
        if tup is None:
            single = node.parm(name)  # r の中の ry のように、組の中の 1 つの名前
            if single is None:
                fail(f"{node.type().name()} に、パラメータ {name} がありません")
            single.set(value[0] if isinstance(value, (list, tuple)) else value)
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        if len(values) != len(tup):
            if len(tup) == 1:
                fail(f"{name} は 1 つの値です")
            values = list(values) + [values[-1]] * (len(tup) - len(values))
        tup.set(values[: len(tup)])


def _current(node, name: str):
    """パラメータ（組）の、いまの値と、初期値のままか。"""
    parm = node.parmTuple(name) or node.parm(name)
    if parm is None:
        return None, True, None
    members = list(parm) if hasattr(parm, "__len__") else [parm]
    return members, all(m.isAtDefault() for m in members), [m.eval() if m.parmTemplate().type() != hou.parmTemplateType.String else m.unexpandedString() for m in members]


def quiet_signature(node):
    """cook して、形の特徴を返す（失敗・空のときは、その旨の文字。fail しない。値を変えて試すときに使う）。"""
    node.cook(force=True)
    if node.errors():
        return "error"
    geometry = node.geometry()
    if geometry is None or not geometry.points():
        return "empty"
    return signature(geometry)


def ineffective_parms(node, parms: dict, after_sig: dict, keep: list | tuple = ()) -> list[str]:
    """レシピの値を 1 つずつ初期値に戻して、形が変わらないものの名前（値が効いていない）。初期値のままの値は、調べない。
    例: Attribute Noise は、P（ベクトル）のとき amplitudev だけが効き、amplitude（スカラー用）を変えても、形は変わらない（2026-11-21 に見つけた）。"""
    idle = []
    for name in parms:
        if name in keep:  # 結果は同じでも、書いておくほうが分かりやすい値（例: blast の grouptype = Primitives）。レシピの "keep" に挙げたものだけ
            continue
        members, at_default, values = _current(node, name)
        if members is None or at_default:
            continue
        for m in members:
            m.revertToDefaults()
        sig = quiet_signature(node)
        for m, v in zip(members, values):
            m.set(v)
        if sig == after_sig:
            idle.append(name)
    node.cook(force=True)  # 元の値に戻した状態で、もう一度 cook しておく
    return idle


def ineffective_sweep(node, target, sweep: dict) -> list[str]:
    """動かす値の最初と最後で、形が変わらないとき、その名前。"""
    parm = target.parm(sweep["parm"])
    if parm is None:
        return []
    keep = parm.eval()
    parm.set(sweep["from"])
    first = quiet_signature(node)
    parm.set(sweep["to"])
    last = quiet_signature(node)
    parm.set(keep)
    node.cook(force=True)
    return [] if first != last else [f"{sweep['parm']}（動きの最初と最後で、形が同じ）"]


def make_node(parent, type_names, name: str):
    names = type_names if isinstance(type_names, (list, tuple)) else [type_names]
    category = parent.childTypeCategory()
    for type_name in names:
        if hou.nodeType(category, type_name) is not None:
            return parent.createNode(type_name, name)
    fail(f"ノードのタイプが見つかりません: {names}")


def geometry_of(node):
    node.cook(force=True)
    errors = node.errors()
    if errors:
        fail(f"{node.name()} の cook エラー: {errors[0][:120]}")
    geometry = node.geometry()
    if geometry is None or not geometry.points():
        fail(f"{node.name()} の形が空です")
    return geometry


def signature(geometry) -> dict:
    """形の特徴（前後で比べる）。点・面の数、形の大きさ、位置・色・法線の合計。"""
    box = geometry.boundingBox()
    sig = {
        "points": len(geometry.points()),
        "prims": len(geometry.prims()),
        "bbox": [round(v, 4) for v in (*box.minvec(), *box.maxvec())],
    }
    positions = geometry.pointFloatAttribValues("P")
    sig["sum_p"] = round(sum(positions), 3)
    sig["sum_abs_p"] = round(sum(abs(v) for v in positions), 3)
    for name in ("Cd", "N"):
        for owner, getter in (("point", geometry.findPointAttrib), ("prim", geometry.findPrimAttrib), ("vertex", geometry.findVertexAttrib)):
            attrib = getter(name)
            if attrib is None:
                continue
            if owner == "point":
                values = geometry.pointFloatAttribValues(name)
            elif owner == "prim":
                values = geometry.primFloatAttribValues(name)
            else:
                values = [v for point in geometry.points() for v in point.attribValue(name)] if len(geometry.points()) < 20000 else []
            sig[f"{name}_{owner}"] = round(sum(values), 3)
    return sig


def build_chain(geo, spec: dict, name: str):
    """spec の元のノードを作り、"after" のノードを、順に後ろへつなぐ。最後のノードを返す。"""
    last = make_node(geo, spec["type"], name)
    set_parms(last, spec.get("parms"))
    for i, step in enumerate(spec.get("after") or []):
        nxt = make_node(geo, step["type"], f"{name}_{i}")
        nxt.setInput(0, last)
        set_parms(nxt, step.get("parms"))
        last = nxt
    return last


def main() -> None:
    recipe = json.loads(open(sys.argv[1], encoding="utf-8").read())
    mode, out = sys.argv[2], sys.argv[3]
    obj = hou.node("/obj")
    geo = obj.createNode("geo", "ref")
    for child in geo.children():
        child.destroy()
    inputs = recipe.get("inputs") or [recipe["input"]]
    sources = []
    for i, spec in enumerate(inputs):
        sources.append(build_chain(geo, spec, f"in{i}"))
    node = make_node(geo, recipe["type"], "node")
    for i, src in enumerate(sources):
        node.setInput(i, src)
    parms = dict(recipe.get("parms") or {})
    sweep = recipe.get("sweep")
    # 動かすパラメータは、ノード自身のほか、入力のノード（"node": "in1" = 2 番目の入力の元のノード、"in1_0" = そのあとの 1 つ目）でもよい
    # （boolean の B を動かす・copytopoints の元の点の数を増やす、など。ノード自身には、動かせる数値が無いもの）
    target = node
    if sweep and sweep.get("node"):
        target = geo.node(sweep["node"])
        if target is None:
            fail(f"動かすノード {sweep['node']} がありません")
    if sweep and mode != "clip":
        if target is node:
            parms[sweep["parm"]] = sweep["to"]  # 静止画の「適用後」は、動きの最後の値
    set_parms(node, parms)
    if sweep and mode != "clip" and target is not node:
        set_parms(target, {sweep["parm"]: sweep["to"]})
    if sweep and mode == "clip":
        parm = target.parm(sweep["parm"])
        if parm is None:
            fail(f"動かすパラメータ {sweep['parm']} がありません")
        parm.setExpression(f"fit($F,1,{FRAMES},{sweep['from']},{sweep['to']})")

    # 前後の両方を、最後の状態で cook して、同じ構図のカメラを決める
    hou.setFrame(FRAMES if (sweep and mode == "clip") else 1)
    # 入力が複数のノード（boolean・copytopoints など）の「適用前」は、入力を全部並べた絵にする（1 つだけ映すと、材料が見えない）
    before_node = sources[0]
    if len(sources) > 1:
        before_node = geo.createNode("merge", "before_merge")
        for i, src in enumerate(sources):
            before_node.setInput(i, src)
    before_geo = geometry_of(before_node)
    after_geo = geometry_of(node)
    before_sig, after_sig = signature(before_geo), signature(after_geo)
    if before_sig == after_sig:
        fail("適用の前後で、形が何も変わりません（効果が見えない絵になるので、撮りません）")
    if mode != "clip":
        idle = ineffective_parms(node, parms, after_sig, recipe.get("keep") or ())
        if sweep:
            idle += ineffective_sweep(node, target, sweep)
        if idle:
            fail("値を変えても、形が変わらないパラメータがあります（説明に「効く」と書けないので、撮りません）: " + ", ".join(idle))
    if mode == "check":
        changed = [k for k in after_sig if before_sig.get(k) != after_sig[k]]
        print("CHANGED: " + ", ".join(changed))
        print("OK")
        return
    lo = [min(before_geo.boundingBox().minvec()[i], after_geo.boundingBox().minvec()[i]) for i in range(3)]
    hi = [max(before_geo.boundingBox().maxvec()[i], after_geo.boundingBox().maxvec()[i]) for i in range(3)]
    center = hou.Vector3([(lo[i] + hi[i]) / 2 for i in range(3)])
    size = max(hi[i] - lo[i] for i in range(3)) or 1.0
    radius = 0.5 * math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3))) or 0.5
    distance = max(size * 2.4, radius * 4.0)  # 16:9（縦の画角が 26 度ほどで狭い）でも、背の高い形・立方体の角が、はみ出さない距離
    direction = hou.Vector3((0.45, 0.4, 1.0)).normalized()
    target = obj.createNode("null", "look")
    target.parmTuple("t").set(center)
    target.setDisplayFlag(False)  # 向きを決めるだけの null。表示したままだと、軸の緑の線が絵の中央に映る（2026-11-20 に確認）
    cam = obj.createNode("cam", "cam1")
    cam.parmTuple("t").set(center + direction * distance)
    cam.parm("lookatpath").set(target.path())
    cam.parm("resx").set(WIDTH)
    cam.parm("resy").set(HEIGHT)

    shown = before_node if mode == "before" else node
    shown.setDisplayFlag(True)
    shown.setRenderFlag(True)

    rop = hou.node("/out").createNode("opengl", "gl")
    rop.parm("camera").set(cam.path())
    rop.parm("tres").set(1)
    rop.parm("res1").set(WIDTH)
    rop.parm("res2").set(HEIGHT)
    if mode == "clip":
        os.makedirs(out, exist_ok=True)
        rop.parm("trange").set(1)
        rop.parm("f1").set(1)
        rop.parm("f2").set(FRAMES)
        rop.parm("f3").set(1)
        rop.parm("picture").set(os.path.join(out, "frame.$F4.png").replace("\\", "/"))
    else:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        rop.parm("trange").set(0)
        rop.parm("picture").set(out.replace("\\", "/"))
    rop.render()
    print("OK")


main()
