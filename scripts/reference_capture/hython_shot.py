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
  "graph": {"nodes": [{"name", "type", "parms", "inputs": [名前 または [名前, 出力の番号] または null, ...]}, ...], "node": 最後のノード, "before": 適用前に映すノード}
    = つなぎ方を書くレシピ（入力が複数・出力が複数のもの。Vellum・RBD など）。nodes は、書いた順に作る。"input" の代わりに使う。
  "vop": {"nodes": [...], "wires": [[元, 出力, 先, 入力], ...]} = type の Attribute VOP の中に作る VOP（build_vop）。
  "lights": [{"name", "type", "parms"}, ...] = /obj に置くライト。「適用後」にだけ置く。"lighting": true と一緒に使う（形は前後で同じなので、形の変化の点検をしない）。
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
        if isinstance(value, dict) and "expr" in value:  # {"expr": "$F == 1"} = 式（HScript）を入れる（FLIP の出す量を、1 フレーム目だけにする、など。2026-11-25）
            parm = node.parm(name)
            if parm is None:
                fail(f"{node.type().name()} に、パラメータ {name} がありません")
            parm.setExpression(value["expr"], hou.exprLanguage.Hscript)
            continue
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
    try:
        node.cook(force=True)
    except hou.OperationFailed:  # 値を初期値に戻すと cook が失敗するノード（例: sweep の Surface Shape の初期値は、2 番目の入力が要る）。その値は「効いている」
        return "error"
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
    for type_name in names:  # 版の付いた名前（popsolver → popsolver::2.0 など）は、createNode が、いまの版に読み替える
        try:
            return parent.createNode(type_name, name)
        except hou.OperationFailed:
            continue
    fail(f"ノードのタイプが見つかりません: {names}")


def geometry_of(node):
    try:
        node.cook(force=True)
    except hou.OperationFailed:  # VEX のコンパイルエラーなど。理由を出して終わる（例外のまま終わると、理由が残らない）
        fail(f"{node.name()} の cook に失敗: {(list(node.errors()) or list(node.warnings()) or ['原因不明'])[0][:160]}")
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
    # ボリューム（Heightfield の高さなど）は、値の合計も比べる（形の大きさが同じまま、高さだけが変わる処理を、「変化なし」と見誤らないため。2026-11-25）
    voxels = [v for prim in geometry.prims() if prim.type() == hou.primType.Volume and math.prod(prim.resolution()) <= 300000 for v in prim.allVoxels()]
    if voxels:
        sig["vox_sum"] = round(sum(voxels), 2)
        sig["vox_sq"] = round(sum(v * v for v in voxels), 2)
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
                # 頂点の属性は、点ではなく、面の頂点から読む（以前は点から読んでいて、Normal SOP の頂点法線で落ちた。2026-11-25）
                values = [v for prim in geometry.prims() for vertex in prim.vertices() for v in vertex.attribValue(name)] if len(geometry.points()) < 20000 else []
            sig[f"{name}_{owner}"] = round(sum(values), 3)
            sig[f"{name}_{owner}_sq"] = round(sum(v * v for v in values), 3)  # 平均が保たれる処理（ぼかし）でも、ばらつきの変化が分かる
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


def build_graph(geo, graph: dict):
    """graph のノードを、書いた順に作ってつなぐ。(最後のノード, 適用前に映すノード) を返す。"""
    made: dict = {}
    for spec in graph["nodes"]:
        # "context": "stage" = /stage（LOP）に置く（2026-11-25）。"dop:<名前>" = /obj の DOP ネットワーク <名前> の中（無ければ作る。
        # 表示は切る: 読み込みは、SOP の dopimport で行う）。それ以外は、撮影用の geo の中（SOP）
        context = str(spec.get("context") or "")
        if context == "stage":
            parent = hou.node("/stage")
        elif context.startswith("dop:"):
            net_name = context[4:]
            if net_name not in made:
                made[net_name] = hou.node("/obj").createNode("dopnet", net_name)
                made[net_name].setDisplayFlag(False)
            parent = made[net_name]
        else:
            parent = geo
        node = make_node(parent, spec["type"], spec["name"])
        made[spec["name"]] = node
        for i, ref in enumerate(spec.get("inputs") or []):
            if ref is None:
                continue
            name, output = (ref, 0) if isinstance(ref, str) else ref
            if name not in made:
                fail(f"{spec['name']} の入力 {name} が、まだ作られていません（nodes は、元のものから順に書く）")
            node.setInput(i, made[name], output)
        # 値が "@名前" の文字列は、そのノードのパスに置き換える（lopimport の loppath に、/stage のノードを指すときなど）
        parms = {k: (made[v[1:]].path() if isinstance(v, str) and v.startswith("@") and v[1:] in made else v) for k, v in (spec.get("parms") or {}).items()}
        set_parms(node, parms)
        if spec.get("display"):  # DOP ネットワークは、表示フラグの付いたノード（output）までを、シミュレーションする
            node.setDisplayFlag(True)
    return made[graph["node"]], made[graph.get("before") or graph["nodes"][0]["name"]]


RECIPE_SKIP_TYPES = {"lopnet", "copnet", "NetworkBox", "StickyNote"}  # SOP の中に作れない・撮影に要らないもの


def build_tool_recipe(geo, graph: dict):
    """Houdini 付属のツールのレシピ（シェルフの Simple Fireball などが置くノードの組み立て）を、そのまま geo の中に作る（2026-11-25）。
    graph = {"tool_recipe": レシピ名, "node": 映すノード, "before": 適用前に映すノード, "rewire": {ノード: 入力 0 につなぎ直すノード},
             "parms": {ノード: {パラメータ: 値}}}。(映すノード, 適用前に映すノード) を返す。"""
    data = hou.data.dataFromRecipe(graph["tool_recipe"])
    kids = {k: v for k, v in data["children"].items() if v.get("type") not in RECIPE_SKIP_TYPES}
    for item in kids.values():
        item["inputs"] = [i for i in item.get("inputs", []) if i.get("from") in kids]
    hou.data.createItemsFromData(geo, kids)
    # 追加のパラメータ（ノードのパスなど）の値は、作ったあとで入れ直す（追加のパラメータを作る前に入れた値が、残らないことがある。
    # 例: Simple Fireball の Volume Rasterize Attributes の pyroburstsourcepath が空になり、式が失敗する）
    for name, item in kids.items():
        node = geo.node(name)
        for parm_name, value in (item.get("parms") or {}).items():
            parm = node.parm(parm_name) if node is not None else None
            if isinstance(value, str) and parm is not None and parm.parmTemplate().type() == hou.parmTemplateType.String and parm.unexpandedString() != value:
                parm.set(value)
    for name, source in (graph.get("rewire") or {}).items():
        geo.node(name).setInput(0, geo.node(source))
    for name, parms in (graph.get("parms") or {}).items():
        set_parms(geo.node(name), parms)
    node = geo.node(graph["node"])
    before = geo.node(graph.get("before") or graph["node"])
    if node is None or before is None:
        fail(f"レシピ {graph['tool_recipe']} に、ノード {graph['node']} / {graph.get('before')} がありません")
    return node, before


VOP_ALIASES = {"global": "geometryvopglobal1", "out": "geometryvopoutput1"}


def build_vop(node, vop: dict) -> None:
    """Attribute VOP（node）の中に、VOP のノードを作って、つなぐ（2026-11-25）。
    vop = {"nodes": [{"name", "type", "parms"}], "wires": [[元, 出力（名前 か 番号）, 先, 入力（名前 か 番号）], ...]}
    global・out は、最初からある Geometry VOP Global / Output のこと。"""
    made = {alias: node.node(child) for alias, child in VOP_ALIASES.items()}
    for spec in vop.get("nodes") or []:
        made[spec["name"]] = make_node(node, spec["type"], spec["name"])
        set_parms(made[spec["name"]], spec.get("parms"))
    for src_name, output, dst_name, input_ in vop.get("wires") or []:
        src, dst = made.get(src_name), made.get(dst_name)
        if src is None or dst is None:
            fail(f"VOP のつなぎの相手がありません: {src_name} → {dst_name}")
        out_index = output if isinstance(output, int) else src.outputIndex(output)
        in_index = input_ if isinstance(input_, int) else dst.inputIndex(input_)
        if out_index < 0 or in_index < 0:
            fail(f"VOP の入出力の名前がありません: {src_name}.{output} → {dst_name}.{input_}")
        dst.setInput(in_index, src, out_index)


COP_MAX_EDGE = 540  # COP の画像を書き出す、長辺の上限（px）
COP_CLIP_FRAMES = 24  # COP の動き（値を動かす）の枚数


def write_cop_layer(node, out: str) -> None:
    """COP ノードの画像（層）を、PGM（1 チャンネル）か PPM（3 チャンネル以上）で書く（2026-11-25）。
    Houdini の Python には Pillow が無いので、外の capture.py が、開いて PNG に直す。値は 0〜1 に収め、表示用のガンマ（1/2.2）を掛ける。"""
    from array import array

    layer = node.layer()
    width, height = layer.bufferResolution()
    channels = layer.channelCount()
    data = array("f")
    data.frombytes(layer.allBufferElements())
    step = max(1, -(-max(width, height) // COP_MAX_EDGE))
    shown = min(channels, 3) if channels >= 3 else 1
    pixels = bytearray()
    for y in range(height - 1, -1, -step):  # 画像の原点は左下。ファイルは上の行から
        row = y * width * channels
        for x in range(0, width, step):
            base = row + x * channels
            for c in range(shown):
                value = data[base + c]
                value = 0.0 if value != value or value < 0 else (1.0 if value > 1 else value)  # NaN・範囲外
                pixels.append(int(round((value ** (1 / 2.2)) * 255)))
    out_w, out_h = len(range(0, width, step)), len(range(height - 1, -1, -step))
    header = ("P5" if shown == 1 else "P6") + f" {out_w} {out_h} 255" + chr(10)
    header = header.encode("ascii")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as handle:
        handle.write(header + bytes(pixels))


def shoot_cop(geo, recipe: dict, mode: str, out: str) -> None:
    """COP のレシピ: copnet の中に作って、適用前・適用後の画像を書く（OpenGL ROP は使わない）。"""
    cop = recipe["cop"]
    net = geo.createNode("copnet", "cops")
    made: dict = {}
    for spec in cop["nodes"]:
        node = make_node(net, spec["type"], spec["name"])
        made[spec["name"]] = node
        for i, ref in enumerate(spec.get("inputs") or []):
            if ref is not None:
                name, output = (ref, 0) if isinstance(ref, str) else ref
                node.setInput(i, made[name], output)
        set_parms(node, spec.get("parms"))
    after = made[cop["node"]]
    before = made.get(cop.get("before") or "")
    for node in [n for n in (before, after) if n is not None]:
        try:
            node.cook(force=True)
        except hou.OperationFailed:
            pass
        if node.errors():
            fail(f"{node.name()} の cook エラー: {node.errors()[0][:120]}")
    if before is not None and before.layer().allBufferElements() == after.layer().allBufferElements():
        fail("適用の前後で、画像が何も変わりません（効果が見えない絵になるので、撮りません）")
    if mode == "check":
        print("OK")
        return
    if mode == "before":
        if before is None:
            fail("形を作るノードには、適用前がありません")
        write_cop_layer(before, out)
    elif mode == "after":
        write_cop_layer(after, out)
    elif recipe.get("sweep"):  # 動き: 値を from から to へ動かした画像を、連番で書く（COP_CLIP_FRAMES 枚）
        sweep = recipe["sweep"]
        parm = after.parm(sweep["parm"])
        if parm is None:
            fail(f"動かすパラメータ {sweep['parm']} がありません")
        os.makedirs(out, exist_ok=True)
        for i in range(COP_CLIP_FRAMES):
            parm.set(sweep["from"] + (sweep["to"] - sweep["from"]) * i / (COP_CLIP_FRAMES - 1))
            after.cook(force=True)
            write_cop_layer(after, os.path.join(out, f"frame.{i + 1:04d}.png"))
    else:
        fail("動かす値の無い COP の動き（clip）は、撮りません（適用前・適用後を交互に見せる GIF を作ります）")
    print("OK")


def advance_simulation(node, frames: int, also=None) -> None:
    """2 枚目から frames 枚目まで、1 枚ずつ cook して、シミュレーションを進める（飛ばして cook すると、途中の状態が作られない）。
    also: 一緒に進める、もう 1 つのノード（適用前も、同じフレームまで動かすとき）。"""
    for f in range(2, frames + 1):
        hou.setFrame(f)
        for target in [n for n in (node, also) if n is not None]:
            target.cook(force=True)
            if target.errors():
                fail(f"{target.name()} の cook エラー（{f} 枚目）: {target.errors()[0][:120]}")


def make_camera(obj, lo, hi, orbit_frames: int = 0):
    """lo〜hi の範囲が収まるカメラを作る（斜め上から見る。向きを決める null も作る）。
    orbit_frames > 0 のときは、1〜orbit_frames 枚目で、対象のまわりを 1 周する（入力が無く、置くだけで形ができるノードの、動き）。"""
    center = hou.Vector3([(lo[i] + hi[i]) / 2 for i in range(3)])
    size = max(hi[i] - lo[i] for i in range(3)) or 1.0
    radius = 0.5 * math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3))) or 0.5
    distance = max(size * 2.4, radius * 4.0)  # 16:9（縦の画角が 26 度ほどで狭い）でも、背の高い形・立方体の角が、はみ出さない距離
    direction = hou.Vector3((0.45, 0.4, 1.0)).normalized()
    look = obj.createNode("null", "look")
    look.parmTuple("t").set(center)
    look.setDisplayFlag(False)  # 向きを決めるだけの null。表示したままだと、軸の緑の線が絵の中央に映る（2026-11-20 に確認）
    cam = obj.createNode("cam", "cam1")
    cam.parmTuple("t").set(center + direction * distance)
    if orbit_frames:
        radius_xz = distance * math.hypot(direction[0], direction[2])
        start = math.degrees(math.atan2(direction[0], direction[2]))
        angle = f"rad({start:.4f} + 360 * ($F - 1) / {orbit_frames})"
        cam.parm("tx").setExpression(f"{center[0]:.5f} + {radius_xz:.5f} * sin({angle})", hou.exprLanguage.Hscript)
        cam.parm("tz").setExpression(f"{center[2]:.5f} + {radius_xz:.5f} * cos({angle})", hou.exprLanguage.Hscript)
    cam.parm("lookatpath").set(look.path())
    cam.parm("resx").set(WIDTH)
    cam.parm("resy").set(HEIGHT)
    return cam


def main() -> None:
    recipe = json.loads(open(sys.argv[1], encoding="utf-8").read())
    mode, out = sys.argv[2], sys.argv[3]
    obj = hou.node("/obj")
    geo = obj.createNode("geo", "ref")
    for child in geo.children():
        child.destroy()
    if recipe.get("cop"):
        shoot_cop(geo, recipe, mode, out)
        return
    # "create": true = 入力を持たず、ノードを置くだけで形ができるもの（Box・Sphere・Torus などのシェルフツール）。「適用前」は無く、「適用後」だけを撮る
    create = bool(recipe.get("create"))
    if create and mode == "before":
        fail("形を作るノードには、適用前がありません")
    graph = recipe.get("graph")
    sources = []
    if graph:
        node, before_source = (build_tool_recipe if graph.get("tool_recipe") else build_graph)(geo, graph)
        sources = [before_source]
    else:
        for i, spec in enumerate([] if create else (recipe.get("inputs") or [recipe["input"]])):
            sources.append(build_chain(geo, spec, f"in{i}"))
        node = make_node(geo, recipe["type"], "node")
        for i, src in enumerate(sources):
            node.setInput(i, src)
        if recipe.get("vop"):
            build_vop(node, recipe["vop"])
    lighting = bool(recipe.get("lighting"))
    if mode != "before":  # ライト（/obj に置く）は、「適用後」にだけ置く
        for spec in recipe.get("lights") or []:
            set_parms(make_node(obj, spec["type"], spec["name"]), spec.get("parms"))
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
        parm.setExpression(f"fit($F,1,{int(recipe.get('sim') or 0) or FRAMES},{sweep['from']},{sweep['to']})")

    # 前後の両方を、最後の状態で cook して、同じ構図のカメラを決める
    # "animate": true = 式が時間（@Frame・@Time）で動くレシピ。静止画の「適用後」は、動きの最後（FRAMES 枚目）で撮り、動きは、1〜FRAMES 枚目を連番で撮る
    animate = bool(recipe.get("animate"))
    # "sim": N = シミュレーション（Pyro など）。1〜N 枚目を順に cook して進め、静止画の「適用後」は N 枚目、動きは 1〜N 枚目を連番で撮る（2026-11-24）。
    #   「適用前」は、シミュレーションの入力（1 枚目の元の形）。値を 1 つずつ戻す点検は、シミュレーションを毎回やり直すので、しない（効き目は、絵で確かめる）
    sim = int(recipe.get("sim") or 0)
    frames = sim or FRAMES
    hou.setFrame(1 if sim else (FRAMES if ((sweep and mode == "clip") or animate) else 1))
    # 入力が複数のノード（boolean・copytopoints など）の「適用前」は、入力を全部並べた絵にする（1 つだけ映すと、材料が見えない）
    before_node = node if create else sources[0]
    if len(sources) > 1:
        before_node = geo.createNode("merge", "before_merge")
        for i, src in enumerate(sources):
            before_node.setInput(i, src)
    before_geo = geometry_of(before_node)
    before_sig, before_box = signature(before_geo), before_geo.boundingBox()  # 値で持つ（このあとフレームを進めると、形の参照が古くなる）
    # "compare_at_end": true = 適用前も、同じフレームまで動かして比べる（DOP の、重力なし・地面なし など。2026-11-25）
    compare_end = bool(recipe.get("compare_at_end")) and sim
    if sim:
        advance_simulation(node, sim, also=before_node if compare_end else None)
    if compare_end:
        before_geo = geometry_of(before_node)
        before_sig, before_box = signature(before_geo), before_geo.boundingBox()
    after_geo = geometry_of(node)
    after_sig = signature(after_geo)
    after_box = after_geo.boundingBox()
    if sim and mode == "before" and not compare_end:
        hou.setFrame(1)
    if before_sig == after_sig and not create and not lighting:
        fail("適用の前後で、形が何も変わりません（効果が見えない絵になるので、撮りません）")
    if mode != "clip" and not sim:
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
    lo = [min(before_box.minvec()[i], after_box.minvec()[i]) for i in range(3)]
    hi = [max(before_box.maxvec()[i], after_box.maxvec()[i]) for i in range(3)]
    view = recipe.get("view")  # {"lo": [...], "hi": [...]} = 構図を、この範囲で決める（シミュレーションの箱は、煙より大きいため）
    if view:
        lo, hi = list(view["lo"]), list(view["hi"])
    cam = make_camera(obj, lo, hi, orbit_frames=frames if (create and mode == "clip" and not sweep) else 0)  # 動かす値が無い、置くだけで形ができるものは、まわりを 1 周する

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
        rop.parm("f2").set(frames)
        rop.parm("f3").set(1)
        rop.parm("picture").set(os.path.join(out, "frame.$F4.png").replace("\\", "/"))
    else:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        rop.parm("trange").set(0)
        rop.parm("picture").set(out.replace("\\", "/"))
    rop.render()
    print("OK")


main()
