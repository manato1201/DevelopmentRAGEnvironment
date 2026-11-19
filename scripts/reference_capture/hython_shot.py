"""hython で、1 つのノードの「適用前」「適用後」「適用の動き（連番）」を、OpenGL ROP で 1 回だけ撮る（2026-11-19）。

使い方:  hython hython_shot.py <recipe.json> <before|after|clip> <出力>
    before / after … 出力は、PNG のパス
    clip           … 出力は、連番の PNG の置き場所のフォルダ（frame.0001.png …）

制約（実測）: hython では、1 つのプロセスで OpenGL ROP の render() を 2 回呼ぶと、2 回目でクラッシュする（Houdini 22.0.506）。
  なので、1 回の起動で 1 回だけ撮る。前後で同じ構図にするため、毎回、前後の両方を cook して、カメラは両方のバウンディングボックスから決める。
レシピ（recipes.py の 1 件）: {"type": ["mountain::2.0", "mountain"], "input": {"type": "grid", "parms": {...}},
    "parms": {...適用後の値}, "sweep": {"parm": "height", "from": 0.0, "to": 1.2}}
終了コード: 0 = 撮れた / 2 = レシピの不備（ノードが作れない・cook エラー・形が空）。理由は、標準出力の最後の行（REASON: …）。
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
            fail(f"{node.type().name()} に、パラメータ {name} がありません")
        values = value if isinstance(value, (list, tuple)) else [value]
        if len(values) != len(tup):
            if len(tup) == 1:
                fail(f"{name} は 1 つの値です")
            values = list(values) + [values[-1]] * (len(tup) - len(values))
        tup.set(values[: len(tup)])


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
        src = make_node(geo, spec["type"], f"in{i}")
        set_parms(src, spec.get("parms"))
        sources.append(src)
    node = make_node(geo, recipe["type"], "node")
    for i, src in enumerate(sources):
        node.setInput(i, src)
    parms = dict(recipe.get("parms") or {})
    sweep = recipe.get("sweep")
    if sweep and mode != "clip":
        parms[sweep["parm"]] = sweep["to"]  # 静止画の「適用後」は、動きの最後の値
    set_parms(node, parms)
    if sweep and mode == "clip":
        parm = node.parm(sweep["parm"])
        if parm is None:
            fail(f"動かすパラメータ {sweep['parm']} がありません")
        parm.setExpression(f"fit($F,1,{FRAMES},{sweep['from']},{sweep['to']})")

    # 前後の両方を、最後の状態で cook して、同じ構図のカメラを決める
    hou.setFrame(FRAMES if (sweep and mode == "clip") else 1)
    before_geo = geometry_of(sources[0])
    after_geo = geometry_of(node)
    lo = [min(before_geo.boundingBox().minvec()[i], after_geo.boundingBox().minvec()[i]) for i in range(3)]
    hi = [max(before_geo.boundingBox().maxvec()[i], after_geo.boundingBox().maxvec()[i]) for i in range(3)]
    center = hou.Vector3([(lo[i] + hi[i]) / 2 for i in range(3)])
    size = max(hi[i] - lo[i] for i in range(3)) or 1.0
    radius = 0.5 * math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3))) or 0.5
    distance = max(size * 2.4, radius * 4.0)  # 16:9（縦の画角が 26 度ほどで狭い）でも、背の高い形・立方体の角が、はみ出さない距離
    direction = hou.Vector3((0.45, 0.4, 1.0)).normalized()
    target = obj.createNode("null", "look")
    target.parmTuple("t").set(center)
    cam = obj.createNode("cam", "cam1")
    cam.parmTuple("t").set(center + direction * distance)
    cam.parm("lookatpath").set(target.path())
    cam.parm("resx").set(WIDTH)
    cam.parm("resy").set(HEIGHT)

    shown = sources[0] if mode == "before" else node
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
