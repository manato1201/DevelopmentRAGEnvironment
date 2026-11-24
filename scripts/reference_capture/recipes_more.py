"""ノード・VEX の撮影レシピの追加分（2026-11-24 の 2 回目）。recipes.py から読み込まれる。
撮る前に、`capture.py --check --only <キー>` で、cook が通り、前後で形が変わり、値が全部効くことを確かめる。通らないものは、ここに入れない。
"""

from __future__ import annotations

import copy

from recipe_common import GRID, GRID_COARSE, SPHERE, create_sweep  # noqa: E402,F401

VEX_GRID = {"type": "grid", "parms": {"rows": 40, "cols": 40, "size": [3, 3]}}


def _n(key: str, types: list[str], input_: dict, parms: dict, note: str = "", **extra) -> dict:
    r = {"kind": "node", "key": key, "type": types, "input": input_, "parms": parms, **extra}
    if note:
        r["note"] = note
    return r


def _c(key: str, types: list[str], parms: dict, note: str = "", **extra) -> dict:
    r = {"kind": "node", "key": key, "type": types, "create": True, "parms": parms, **extra}
    if note:
        r["note"] = note
    return r


NODE_MORE = [
    _c("sop/box", ["box"], {}, "Box。置くだけで、箱ができる（パラメータは、初期値のまま）"),
    _c("sop/sphere", ["sphere"], {"type": 2, "rows": 24, "cols": 48}, "type = 2 は、メニューの「Polygon Mesh」（面が見える球）", keep=["type", "rows", "cols"]),
    _c("sop/tube", ["tube"], {"type": 1}, "type = 1 は、メニューの「Polygon」。筒（両端にふた付き）", keep=["type"]),
    _c("sop/torus", ["torus"], {"rows": 24, "cols": 48}, "ドーナツの形"),
    _c("sop/grid", ["grid"], {"rows": 10, "cols": 10, "size": [3, 3]}, "10 x 10 の点の板"),
    _c("sop/line", ["line"], {"dist": 2, "points": 12}, "長さ 2、点が 12 個の線"),
    _c("sop/circle", ["circle"], {"type": 1, "divs": 32}, "type = 1 は、メニューの「Polygon」。32 分割の円", keep=["type"]),
    _c("sop/platonic", ["platonic"], {"type": 3}, "type = 3 は、メニューの「Icosahedron」（正二十面体）", keep=["type"]),
    _c("sop/lsystem", ["lsystem"], {}, "パラメータは、初期値のまま"),
    _c("sop/metaball", ["metaball"], {}, "パラメータは、初期値のまま"),
    _c("sop/font", ["font"], {"text": "Houdini"}, "文字の形（面）を作る。text に書いた文字が、そのまま形になる"),
    _c("sop/spiral", ["spiral"], {"turns": 6, "height": 2.0}, "6 回転・高さ 2 のらせん"),
    _n("sop/pointsfromvolume", ["pointsfromvolume"],
       {"type": "sphere", "parms": {"type": 2, "rad": [0.8, 0.8, 0.8]}, "after": [{"type": "isooffset", "parms": {"divsize": 0.1}}]}, {"particlesep": 0.12},
       "球の SDF（距離のボリューム）の中に、点を詰める"),
]

# 2026-11-25 の追加: Heightfield（地形）と、形が変わる SOP
HF_FLAT = {"type": "heightfield", "parms": {"sizex": 100, "sizey": 100, "gridspacing": 1}}
HF_NOISE = {**HF_FLAT, "after": [{"type": "heightfield_noise", "parms": {"amp": 30, "elementsize": 30}}]}  # 凸凹の地形（高さ 30 ほど）
OPEN_ARC = {"type": "circle", "parms": {"type": 1, "arc": 1, "angle": [0, 270], "divs": 64, "r": 1}}

NODE_MORE += [
    _c("sop/heightfield", ["heightfield"], {"sizex": 100, "sizey": 100, "gridspacing": 1}, "Heightfield を置く（100 x 100、1 マス 1）。平らな地形（高さのボリューム）ができる"),
    _n("sop/heightfield_noise", ["heightfield_noise"], HF_FLAT, {"amp": 30, "elementsize": 30}, "平らな地形に、高さ 30 ほどのノイズを足す（elementsize = 30 は、凸凹の大きさ）",
       sweep={"parm": "amp", "from": 0, "to": 30}),
    _n("sop/heightfield_blur", ["heightfield_blur"], HF_NOISE, {}, "凸凹の地形を、ぼかして、なだらかにする（パラメータは、初期値のまま）"),
    _n("sop/resample", ["resample"], OPEN_ARC, {"length": 0.6}, "細かく分割した円弧を、0.6 の長さごとに、点を置き直す。角ばった、粗い円弧になる",
       sweep={"parm": "length", "from": 0.05, "to": 0.6}),
    _n("sop/primitive", ["primitive"], GRID_COARSE, {"doxform": 1, "rx": 50}, "板の面を、それぞれの中心で、X に 50 度、回す（doxform = 1 で、回転などが効く）",
       keep=["doxform"], sweep={"parm": "rx", "from": 0, "to": 50}),
    _n("sop/matchsize", ["matchsize"], {"type": "box", "parms": {"size": [2, 0.6, 1], "t": [2.5, 1.5, 0]}}, {},
       "原点から離れた、平たい箱を、Match Size で、原点の中心へ動かす（パラメータは、初期値のまま）"),
    _n("sop/shrinkwrap", ["shrinkwrap::2.0", "shrinkwrap"], {"type": "torus", "parms": {"rows": 24, "cols": 48}}, {},
       "ドーナツを、外から包む形（凸包）にする。真ん中の穴が、ふさがる"),
]

# VEX: 色・点・面を、関数で読み書きして、形や色に出るもの
def _v(name: str, snippet: str, see: str, input_: dict | None = None, primitives: bool = False) -> dict:
    """primitives=True は、Run Over を Primitives（class = 1）にする。"""
    parms: dict = {"snippet": snippet}
    extra: dict = {}
    if primitives:
        parms["class"] = 1
        extra["keep"] = ["class"]
    return {"kind": "vex", "key": f"vex/{name}", "type": ["attribwrangle"], "parms": parms, "see": see, "input": input_ or VEX_GRID, **extra}


VEX_MORE = [
    _v("setpointattrib", "setpointattrib(0, 'Cd', @ptnum, set(@P.x*0.5+0.5, 0.2, @P.z*0.5+0.5));", "点ごとに、色（Cd）を書き込むので、板が、位置に応じて赤〜青に塗り分けられる"),
    _v("setattrib", "setattrib(0, 'point', 'Cd', @ptnum, 0, set(@P.z*0.5+0.5, @P.x*0.5+0.5, 0.2));", "setattrib で、点の色（Cd）を、位置から決めて書き込むので、板が色づく"),
    _v("setprimattrib", "vector c = set(rand(@primnum), rand(@primnum+7), rand(@primnum+13)); setprimattrib(0, 'Cd', @primnum, c);", "面ごとに、ばらばらの色（Cd）が書き込まれ、板が、モザイクのように塗り分けられる", primitives=True),
    _v("fresnel", "float kr, kt; fresnel(normalize(@P - {0,0,5}), normalize(@N), 0.75, kr, kt); @Cd = set(kr, kr, kr);", "フレネル反射の強さが、灰色の濃さになり、球の縁が明るく、中央が暗くなる", input_=SPHERE),
    _v("refract", "@Cd = refract(normalize(@P - {0,0,5}), normalize(@N), 0.75) * 0.5 + 0.5;", "球の面で屈折した向きが色になり、場所によって色が変わる", input_=SPHERE),
    _v("cross", "@Cd = cross(normalize(@N), {0,1,0}) * 0.5 + 0.5;", "法線と上向きの外積（どちらにも垂直な向き）が、色になる", input_=SPHERE),
    _v("relpointbbox", "@Cd = relpointbbox(0, @P);", "形の大きさの中での位置（0〜1）が、そのまま色（赤＝X、緑＝Y、青＝Z）になる", input_=SPHERE),
    _v("slerp", "vector4 a = quaternion(0, {0,1,0}); vector4 b = quaternion(radians(160), {0,1,0}); vector4 q = slerp(a, b, fit(@P.x, -1.5, 1.5, 0, 1)); @P = qrotate(q, @P);", "X の位置が右ほど回転の量が大きくなり、板が渦のように変形する"),
    _v("qmultiply", "vector4 q = quaternion(radians(@P.x*50), {0,1,0}); vector4 r = quaternion(radians(@P.z*30), {1,0,0}); @P = qrotate(qmultiply(q, r), @P);", "2 つの回転（Y 軸まわり・X 軸まわり）を掛け合わせた回転で、板がねじれる"),
    _v("lookat", "matrix3 m = lookat({0,0,0}, {1,0.5,0}); @P *= m;", "板が、原点から (1, 0.5, 0) の方向を向くように、回される"),
    _v("dihedral", "matrix3 m = dihedral({0,1,0}, normalize({1,1,0})); @P *= m;", "上向き（Y）の向きを、斜め (1,1,0) の向きに合わせる回転が、板に掛かる"),
    _v("eulertoquaternion", "vector4 q = eulertoquaternion(radians({0, 90, 0}), 0); @P = qrotate(q, @P);", "オイラー角（Y に 90 度）から作った回転で、板が起き上がる"),
    _v("nrandom", "float n = nrandom('twister'); @Cd = set(n, n, n);", "0〜1 の乱数を点ごとに出し、色にする（点ごとに違う灰色）", ),
    _v("determinant", "matrix3 m = set(1.5,0,0, 0,0.7,0, 0,0,1); float d = determinant(m); @P *= m; @Cd = set(d, 0.4, 0.4);", "行列の行列式（体積の変わる倍率）は 1.05。板が、行列で X に伸び、Y に縮む"),
]


for _r in NODE_MORE:
    if _r.get("create") and create_sweep(_r["type"][0]):
        _r["sweep"] = create_sweep(_r["type"][0])


# 2026-11-25 の追加（VEX）
_VOLUME_SPHERE = {"type": "sphere", "parms": {"type": 2, "rad": [1.2, 1.2, 1.2]}, "after": [{"type": "isooffset", "parms": {}}]}  # 球から作った密度のボリューム（Iso Offset の初期値）
_BUMPY = {"type": "grid", "parms": {"rows": 60, "cols": 60, "size": [3, 3]}, "after": [{"type": "mountain::2.0", "parms": {"height": 0.6}}]}
_HALF_GROUP = {"type": "grid", "parms": {"rows": 40, "cols": 40, "size": [3, 3]},
               "after": [{"type": "attribwrangle", "parms": {"snippet": "i@group_half = @P.x > 0;"}}]}  # 右半分の点を、グループ half にした板
VEX_MORE += [
    _v("colormap", "@Cd = colormap('Mandril.pic', set(@P.x / 3 + 0.5, @P.z / 3 + 0.5, 0));",
       "Houdini 付属の画像（Mandril.pic）の色を、板の位置から読み取って、色（Cd）にする。板に、画像が貼られたように見える"),
    {**_v("volumesample", "float d = volumesample(1, 0, @P); @Cd = d > 0.1 ? set(1, 0.4, 0.1) : set(0.15, 0.15, 0.2);",
          "2 番目の入力（球から作った密度のボリューム）の値を、板の位置で読む。球の中（密度がある所）だけが、橙色になる"),
     "inputs": [GRID, _VOLUME_SPHERE]},
    _v("pcfilter", "int h = pcopen(0, 'P', @P, 0.3, 40); @P = pcfilter(h, 'P');",
       "近くの点（半径 0.3・最大 40 個）の位置の平均へ、各点を動かす。凸凹の板が、なめらかになる", _BUMPY),
    _v("invert", "matrix3 m = ident(); rotate(m, radians(40), {0,1,0}); @P *= invert(m);",
       "Y 軸まわりに 40 度回す行列を作り、その逆行列（invert）を掛ける。平たい箱は、反対向きに 40 度回る", {"type": "box", "parms": {"size": [2, 0.6, 1]}}),
    _v("inpointgroup", "@Cd = inpointgroup(0, 'half', @ptnum) ? set(1, 0.3, 0.2) : set(0.2, 0.2, 0.25);",
       "点がグループ half（右半分）に入っているかを調べ、入っている点だけを、赤くする", _HALF_GROUP),
]
for _r in VEX_MORE:
    if "inputs" in _r:
        _r.pop("input", None)


def build() -> list[dict]:
    return copy.deepcopy(NODE_MORE + VEX_MORE)
