"""VEX の関数の「適用前後」の撮影レシピ（2026-11-24）。1 件 = 1 つの関数。recipes.py から読み込まれる（RECIPES に足される）。

形は、recipes.py と同じ（hython_shot.py の説明を参照）。違いは次の 3 つ:
  ・kind は "vex"、type は attribwrangle（Attribute Wrangle）。snippet に、その関数を使った式を書く（式は、公開する説明の「例」に、そのまま載せる）
  ・see: 絵のどこを見るか（日本語。説明の「見るところ」に載せる）
  ・animate: true … 式が @Time で動くもの。静止画の「適用後」は動きの最後で撮り、動きも撮る
撮る前に、`uv run python scripts/reference_capture/capture.py --check --kind vex` で、cook が通り、前後で形が変わり、値が全部効くことを確かめる。
"""

from __future__ import annotations

GRID = {"type": "grid", "parms": {"rows": 60, "cols": 60, "size": [4, 4]}}
GRID_COARSE = {"type": "grid", "parms": {"rows": 10, "cols": 10, "size": [3, 3]}}
SPHERE = {"type": "sphere", "parms": {"type": 2, "rows": 40, "cols": 80}}
SPHERE_SMALL = {"type": "sphere", "parms": {"type": 2, "rows": 24, "cols": 48, "rad": [0.8, 0.8, 0.8]}}
SPHERE_SIDE = {"type": "sphere", "parms": {"type": 2, "rows": 24, "cols": 48, "t": [1.2, 0.6, 0]}}  # 右上にずらした球（向きを変える関数で、動いたことが分かる）
BOX_FLAT = {"type": "box", "parms": {"size": [2, 0.6, 1]}}
TALL_Y = {"type": "grid", "parms": {"orient": 1, "size": [1.2, 3], "rows": 40, "cols": 6}}  # 縦（Y 方向）に長い、細かく分割した板（Y を軸に回すと、ねじれる）
JITTER = {"type": "grid", "parms": {"rows": 40, "cols": 40, "size": [4, 4]}, "after": [{"type": "pointjitter", "parms": {"scale": 0.12}}]}
RAINBOW = {"type": "grid", "parms": {"rows": 60, "cols": 60, "size": [4, 4]},
           "after": [{"type": "attribwrangle", "parms": {"snippet": "v@Cd = hsvtorgb(fit(@P.x, -2.0, 2.0, 0.0, 1.0), 1.0, 1.0);"}}]}  # 左右で色相が変わる板
SCATTER6 = {"type": "grid", "parms": {"rows": 10, "cols": 10, "size": [4, 4]}, "after": [{"type": "scatter::2.0", "parms": {"npts": 6}}]}
SCATTER30 = {"type": "grid", "parms": {"rows": 10, "cols": 10, "size": [4, 4]}, "after": [{"type": "scatter::2.0", "parms": {"npts": 30}}]}
GRID_HIGH = {"type": "grid", "parms": {"rows": 50, "cols": 50, "size": [2.4, 2.4], "ty": 1.2}}  # 球の上に置いた板


def V(name: str, snippet: str, see: str, input: dict | None = None, **extra) -> dict:
    recipe = {"kind": "vex", "key": f"vex/{name}", "type": ["attribwrangle"], "parms": {"snippet": snippet}, "see": see}
    if "inputs" not in extra:
        recipe["input"] = input or GRID
    recipe.update(extra)
    return recipe


VEX_RECIPES: list[dict] = [
    # --- ノイズ ---
    V("noise", "@P.y = noise(@P * 1.5 + @Time) * 0.8;", "板が、なめらかな起伏になり、時間とともに、起伏がゆっくり動く", animate=True),
    V("anoise", "@P.y = anoise(@P * 1.5 + @Time, 3, 0.5, 1.0) * 0.8;", "なめらかな起伏が、板にできる（細かい成分が、自動で抑えられている）", animate=True),
    V("snoise", "@P.y = snoise(@P * 1.5 + @Time) * 0.6;", "板が、プラスとマイナスの両方に動く、なめらかな起伏になる（値が −1〜1 の範囲）", animate=True),
    V("onoise", "@P.y = onoise(@P * 1.5 + @Time) * 0.6;", "板が、なめらかな起伏になり、時間とともに動く", animate=True),
    V("pnoise", "@P.y = pnoise(@P * 1.5, {3, 3, 3}) * 0.8;", "起伏が、板の左右・前後の端で、きれいにつながる（周期が 3 で、繰り返せるノイズ）"),
    V("xnoise", "@P.y = xnoise(@P * 1.5) * 0.8;", "なめらかな起伏が、板にできる"),
    V("wnoise", "int seed;\nfloat f1, f2;\nwnoise(@P.x * 1.2, @P.z * 1.2, seed, f1, f2);\n@P.y = f1 * 0.8;", "細胞のような（ワーリー）模様の、くぼみと山が、板にできる（いちばん近い点までの距離 f1 が、高さになる）"),
    V("flownoise", "@P.y = flownoise(@P * 1.5, @Time * 2.0) * 0.8;", "起伏が、流れるように形を変えながら動く", animate=True),
    V("curlnoise", "@P += curlnoise(@P * 1.2 + @Time) * 0.35;", "板の点が、渦を巻くように、ゆっくりずれていく（時間とともに動く）", animate=True),
    V("curlnoise2d", "vector c = curlnoise2d(@P.x * 1.2, @P.z * 1.2);\n@P += set(c.x, 0, c.y) * 0.4;", "板の点が、板の面の上で、渦を巻くようにずれる（高さは変わらない）"),
    # --- 範囲・段差・曲線 ---
    V("fit", "@P.y = fit(@P.x, -2, 2, 0, 1.5);", "板が、左端の高さ 0 から、右端の高さ 1.5 まで、まっすぐ傾く"),
    V("fit01", "@P.y = fit01(abs(@P.z) / 2.0, 1.0, 0.0);", "板の手前と奥が高く、真ん中が低い、V 字の谷になる（0〜1 を 1〜0 に対応させた）"),
    V("efit", "@P.y = efit(@P.x, -1, 1, 0, 1) * 0.6;", "x = −1〜1 の間は、まっすぐ傾き、その外側も、同じ傾きで伸び続ける（範囲で止まらない）"),
    V("clamp", "@P.y = clamp(@P.x, -1.0, 1.0) * 0.5;", "傾きは、x = −1〜1 の間だけで、その外側は、平らに止まる"),
    V("abs", "@P.y = abs(@P.x) * 0.4;", "左右が同じ高さの、V 字の谷になる（マイナスが、プラスになる）"),
    V("pow", "@P.y = pow(abs(@P.x) * 0.5, 2.0);", "真ん中は平らで、端へ行くほど急に立ち上がる、放物線の谷になる"),
    V("sqrt", "@P.y = sqrt(abs(@P.x)) * 0.5;", "真ん中が急に立ち上がり、端は、ゆるやかになる谷になる"),
    V("frac", "@P.y = frac(@P.x * 0.8) * 0.5;", "のこぎりの歯のように、低い所から高い所まで上がって、また低い所へ戻ることを繰り返す"),
    V("floor", "@P.y = floor(@P.x * 1.5) * 0.25;", "板が、階段のように、段になる（小数を切り捨てる）"),
    V("ceil", "@P.y = ceil(@P.x * 1.5) * 0.25;", "板が、階段のように、段になる（小数を切り上げる。floor と、段の境目の位置が違う）"),
    V("trunc", "@P.y = trunc(@P.x * 1.5) * 0.25;", "階段の段が、真ん中（x = 0）の前後で、対称になる（小数を、0 に向けて切り捨てる）"),
    V("sign", "@P.y = sign(@P.x) * 0.3;", "左半分が低く、右半分が高い、1 段の段差になる（符号だけが効く）"),
    V("smooth", "@P.y = smooth(-1.5, 1.5, @P.x) * 0.8;", "なめらかに、低い所から高い所へ、S 字に上がる"),
    V("min", "@P.y = min(@P.x * 0.4, 0.3);", "傾きが、高さ 0.3 で頭打ちになる"),
    V("max", "@P.y = max(@P.x * 0.4, 0.0);", "左半分は平らで、右半分だけが、傾いて上がる"),
    V("lerp", "@P = lerp(@P, normalize(@P) * 1.8, 0.8);", "四角い板が、円形に近づく（元の位置と、円周上の位置を、0.8 の割合で混ぜた）"),
    # --- 三角関数・指数・対数 ---
    V("sin", "@P.y = sin(length(@P) * 4.0 - @Time * 5.0) * 0.25;", "板の中心から、波が輪になって広がる（時間とともに動く）", animate=True),
    V("cos", "@P.y = cos(@P.x * 3.0) * cos(@P.z * 3.0) * 0.3;", "山と谷が、碁盤の目のように並ぶ"),
    V("tan", "@P.y = clamp(tan(@P.x * 0.7), -1.0, 1.0) * 0.4;", "傾きが、端へ行くほど急になり、高さ 1 で頭打ちになる"),
    V("asin", "@P.y = asin(clamp(@P.x * 0.5, -1.0, 1.0)) * 0.4;", "真ん中はゆるやかで、左右の端が急に立ち上がる曲線になる"),
    V("acos", "@P.y = acos(clamp(@P.x * 0.5, -1.0, 1.0)) * 0.4;", "左が高く、右が低い曲線になる（asin の、向きが逆の形）"),
    V("atan", "@P.y = atan(@P.x * 2.0) * 0.5;", "真ん中が急で、端がゆるやかになる、S 字の曲線になる"),
    V("atan2", "@P.y = atan2(@P.z, @P.x) * 0.2;", "中心を回る向きに、高さが上がり、一周すると段差になる（らせん階段のような形）"),
    V("sinh", "@P.y = sinh(@P.x * 1.0) * 0.3;", "真ん中はゆるやかで、端へ行くほど急に、プラスとマイナスへ伸びる"),
    V("cosh", "@P.y = (cosh(@P.x * 1.0) - 1.0) * 0.4;", "真ん中は平らで、左右の端が、急に立ち上がる谷になる"),
    V("tanh", "@P.y = tanh(@P.x * 1.5) * 0.5;", "真ん中が急で、左右が平らに落ち着く、S 字になる"),
    V("exp", "@P.y = exp(@P.x * 0.8) * 0.2;", "左は平らで、右へ行くほど、急に立ち上がる"),
    V("log", "@P.y = log(@P.x + 2.2) * 0.5;", "左が急で、右へ行くほど、ゆるやかになる"),
    V("log10", "@P.y = log10(@P.x + 2.2) * 1.0;", "左が急で、右へ行くほど、ゆるやかになる（log と、高さの大きさが違う）"),
    V("cbrt", "@P.y = cbrt(@P.x) * 0.5;", "真ん中の傾きが急で、左右の端がゆるやかな、S 字になる（マイナスの値でも使える）"),
    V("degrees", "@P.y = degrees(@P.x) * 0.006;", "板が、左から右へ、まっすぐ傾く（ラジアンを度に直した値が、そのまま高さになる）"),
    V("radians", "@P.y = sin(radians(@P.x * 90.0)) * 0.4;", "x を度として、波ができる（90 度ごとに、山と谷が切り替わる）"),
    # --- 距離・ベクトル ---
    V("length", "@P.y = length(@P) * 0.4;", "中心が低く、外へ行くほど高い、円すいの谷になる"),
    V("length2", "@P.y = length2(@P) * 0.1;", "中心が低く、外へ行くほど急に高くなる、おわんの形になる"),
    V("distance", "@P.y = distance(@P, {1, 0, 1}) * 0.4;", "点 (1, 0, 1) が低く、そこから離れるほど高い、円すいの谷になる"),
    V("distance2", "@P.y = distance2(@P, {1, 0, 1}) * 0.1;", "点 (1, 0, 1) が低く、離れるほど急に高くなる、おわんの形になる"),
    V("dot", "@P.y = dot(normalize(@P), {1, 0, 0}) * 0.6;", "中心から見て、右（x の向き）にある点が高く、左にある点が低くなる"),
    V("normalize", "@P = normalize(@P) * 1.5;", "四角い板の点が、すべて、半径 1.5 の円の上に集まる（長さが、そろう）"),
    V("reflect", "@P = reflect(@P, normalize({1, 1, 0}));", "右上にあった球が、斜めの鏡の面で反転して、左下へ移る", input=SPHERE_SIDE),
    V("set", "@P = set(@P.x, sin(@P.x * 3.0) * 0.3, @P.z);", "x と z はそのままで、高さ（y）だけが、波になる（3 つの値から、ベクトルを作る）"),
    # --- 乱数・色 ---
    V("rand", "@P.y = rand(@ptnum) * 0.3;", "点ごとに、高さがばらばらになる（点の番号が同じなら、毎回同じ値）"),
    V("random", "@P.y = random(@P * 3.0) * 0.3;", "位置ごとに、高さがばらばらになる"),
    V("hsvtorgb", "v@Cd = hsvtorgb(fit(@P.x, -2.0, 2.0, 0.0, 1.0), 1.0, 1.0);", "板が、左から右へ、虹の色に変わる（色相 0〜1 を、赤・緑・青の色に直した）"),
    V("rgbtohsv", "vector hsv = rgbtohsv(@Cd);\n@P.y = hsv.x * 0.8;", "虹色の板が、色相の値の分だけ、持ち上がる（色相の値が、高さになる）", input=RAINBOW),
    V("luminance", "@P.y = luminance(@Cd) * 0.8;", "虹色の板が、明るい色（黄・緑）の所ほど、高くなる", input=RAINBOW),
    V("sample_hemisphere", "vector2 u = set(rand(@ptnum), rand(@ptnum + 7));\n@P = sample_hemisphere(u) * 1.5;", "板の点が、半球の表面に、ばらばらに散らばる"),
    V("sample_direction_uniform", "vector2 u = set(rand(@ptnum), rand(@ptnum + 7));\n@P = sample_direction_uniform(u) * 1.5;", "板の点が、球の表面に、ばらばらに散らばる"),
    # --- 回転・変換 ---
    V("rotate", "matrix3 m = ident();\nrotate(m, @P.y * 1.2, {0, 1, 0});\n@P *= m;", "縦長の板が、上へ行くほど、ねじれる（高さに比例した角度で、Y 軸のまわりに回した）", input=TALL_Y),
    V("quaternion", "@P = qrotate(quaternion(@P.y * 1.5, {0, 1, 0}), @P);", "縦長の板が、上へ行くほど、ねじれる（角度と軸から、回転を表す値を作った）", input=TALL_Y),
    V("qrotate", "@P = qrotate(quaternion(radians(50), {0, 0, 1}), @P);", "平たい箱が、Z 軸のまわりに、50 度回る", input=BOX_FLAT),
    V("scale", "matrix3 m = ident();\nscale(m, {1.5, 0.3, 1.5});\n@P *= m;", "球が、横に広がり、縦につぶれる", input=SPHERE),
    V("translate", "matrix m = ident();\ntranslate(m, {0, 0.8, 0});\n@P *= m;", "球が、真上へ 0.8 動く", input=SPHERE),
    V("maketransform", "matrix m = maketransform(0, 0, {0, 0, 0}, {0, 0, 40});\n@P *= m;", "平たい箱が、Z 軸のまわりに、40 度回る（移動・回転から、変換の行列を作った）", input=BOX_FLAT),
    # --- ジオメトリを調べる ---
    V("nearpoint", "int n = nearpoint(1, @P);\n@P.y = 1.0 - min(distance(@P, point(1, \"P\", n)), 1.0);", "2 番目の入力の点（6 つ）のそばだけが、山になる（いちばん近い点までの距離で、高さが決まる）", inputs=[GRID, SCATTER6]),
    V("nearpoints", "int n[] = nearpoints(1, @P, 1.0);\n@P.y = len(n) * 0.25;", "2 番目の入力の点（6 つ）のそばが、段になって高くなる（距離 1 の中の点の数が、高さになる）", inputs=[GRID, SCATTER6]),
    V("xyzdist", "int prim;\nvector uv;\nfloat d = xyzdist(1, @P, prim, uv);\n@P.y = 1.0 - min(d, 1.0);", "2 番目の入力の球の近くが、高くなる（球の表面までの距離で、高さが決まる）", inputs=[GRID, SPHERE_SMALL]),
    V("pcopen", "int h = pcopen(1, \"P\", @P, 1.0, 50);\n@P.y = pcnumfound(h) * 0.15;", "2 番目の入力の点（30 個）が、多く集まっている所が、高くなる", inputs=[GRID, SCATTER30]),
    V("pcfind", "int n[] = pcfind(1, \"P\", @P, 1.0, 50);\n@P.y = len(n) * 0.15;", "2 番目の入力の点（30 個）が、多く集まっている所が、高くなる", inputs=[GRID, SCATTER30]),
    V("intersect", "vector hit, uv;\nint prim = intersect(1, @P + {0, 3, 0}, {0, -6, 0}, hit, uv);\nif (prim >= 0) {\n    @P = hit;\n}", "球の真上にある板の点が、上から落とした光線が当たった、球の表面へ移る", inputs=[GRID, SPHERE_SMALL]),
    V("minpos", "@P = minpos(1, @P);", "球の上に置いた板が、球の表面の、いちばん近い所へ移って、球にかぶさる", inputs=[GRID_HIGH, SPHERE]),
    V("relbbox", "v@Cd = relbbox(0, @P);", "球が、形の大きさの中での位置に応じた色になる（x・y・z が、赤・緑・青に対応）", input=SPHERE),
    V("getbbox", "vector mn, mx;\ngetbbox(0, mn, mx);\n@P.x = fit(@P.x, mn.x, mx.x, 0, 1);\n@P.z = fit(@P.z, mn.z, mx.z, 0, 1);", "板が、大きさ 4 × 4 から、1 × 1 に縮む（形の範囲を調べて、0〜1 に収めた）"),
    V("npoints", "@P.y = @ptnum / float(npoints(0));", "点の番号順に、高さが 0 から 1 へ上がる（板の手前の列から順に、段になる）"),
    V("point", "vector other = point(0, \"P\", (@ptnum + 61) % @numpt);\n@P.y = other.x * 0.3;", "別の点（番号が 61 先の点）の x を読んで、高さにしている。板に、ずれた傾きができる"),
    V("neighbourcount", "@P.y = neighbourcount(0, @ptnum) * 0.1;", "板の縁（隣の点が少ない所）が、中の部分より、低くなる"),
    V("neighbours", "int n[] = neighbours(0, @ptnum);\nvector s = 0;\nforeach (int i; n) {\n    s += point(0, \"P\", i);\n}\n@P = s / len(n);", "ざらざらの板が、隣の点の平均の位置へ動いて、なめらかになる", input=JITTER),
    # --- 点・面の追加と削除 ---
    V("addpoint", "addpoint(0, @P + {0, 0.5, 0});", "板の上の 0.5 の高さに、点が、もう 1 組ならぶ（点ごとに、新しい点を足した）", input=GRID_COARSE),
    V("addprim", "if (@ptnum + 1 < @numpt) {\n    addprim(0, \"polyline\", @ptnum, @ptnum + 1);\n}", "点どうしを、番号順に結ぶ線が、板の上にできる", input=GRID_COARSE),
    V("removepoint", "if (@P.x > 0) {\n    removepoint(0, @ptnum);\n}", "板の右半分が、消える（x がプラスの点を消した）", input=GRID_COARSE),
    V("removeprim", "if (@primnum % 2 == 0) {\n    removeprim(0, @primnum, 1);\n}", "面が 1 枚おきに消えて、市松模様になる（面の番号が偶数のものを消した。Run Over は Primitives）", input=GRID_COARSE, parms={"snippet": "if (@primnum % 2 == 0) {\n    removeprim(0, @primnum, 1);\n}", "class": 1}, keep=["class"]),
]
