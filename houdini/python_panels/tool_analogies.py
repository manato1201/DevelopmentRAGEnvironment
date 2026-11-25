"""
tool_analogies.py — Houdini のノードが、ほかのツール（Maya・Blender）でいうと何に近いか（2026-11-25。Qt にも Houdini にも依存しない）

背景（実証実験の第 2 回・修正リストの A27）: 「ほかのツールを触ったことがある人用の解説がほしい（〜の機能は Maya でいうこんな機能です）」。
参加者は CG コースの学生で、Maya・Blender の経験がある人が多い。

方針:
  ・AI に作らせない（対応を取り違えると、そのまま誤りを覚える）。広く知られた対応だけを、手で書く。無いものは出さない。
  ・「同じもの」ではなく「近いもの」と書く。Houdini は、ノードのつながり（手順）として残る点が違う、と添える。
  ・Maya は標準の機能（メニューの場所）、Blender は標準の機能（モディファイア・物理・ジオメトリノード）で書く。プラグイン・アドオンは、そう書く。

  for_node(type_name, context="") … {"maya": 文, "blender": 文} / None（type_name は "scatter::2.0" のような版つきでもよい）
  for_item(item)                   … Reference の項目（{"kind": "node", "key": "sop/scatter"}）用
  html_block(analogy)              … 表示用の HTML（文字はエスケープ済み）
"""

from __future__ import annotations

import html

NOTE = "近い機能の例です（同じではありません）。Houdini では、操作がノードのつながりとして残り、あとから値を変えると、下流の結果も作り直されます。"

# (文脈, 版を除いた型の名前) → (Maya, Blender)。文脈は sop / obj / dop / cop など（Reference のキーの前半）
_TABLE: dict[tuple[str, str], tuple[str, str]] = {
    # 形を作る
    ("obj", "geo"): ("オブジェクト（トランスフォーム ＋ シェイプ）", "オブジェクト"),
    ("sop", "box"): ("Create ▸ Polygon Primitives ▸ Cube", "Add ▸ Mesh ▸ Cube"),
    ("sop", "sphere"): ("Create ▸ Polygon Primitives ▸ Sphere", "Add ▸ Mesh ▸ UV Sphere / Ico Sphere"),
    ("sop", "grid"): ("Create ▸ Polygon Primitives ▸ Plane", "Add ▸ Mesh ▸ Plane / Grid"),
    ("sop", "tube"): ("Create ▸ Polygon Primitives ▸ Cylinder", "Add ▸ Mesh ▸ Cylinder"),
    ("sop", "torus"): ("Create ▸ Polygon Primitives ▸ Torus", "Add ▸ Mesh ▸ Torus"),
    ("sop", "circle"): ("Create ▸ NURBS Primitives ▸ Circle", "Add ▸ Mesh ▸ Circle"),
    # 形を変える
    ("sop", "xform"): ("移動・回転・スケール（チャンネルボックスの Translate / Rotate / Scale）", "移動・回転・拡大縮小（G / R / S）"),
    ("sop", "polyextrude"): ("Edit Mesh ▸ Extrude", "押し出し（E）"),
    ("sop", "polybevel"): ("Edit Mesh ▸ Bevel", "ベベル（Ctrl+B）・Bevel モディファイア"),
    ("sop", "subdivide"): ("Mesh ▸ Smooth", "Subdivision Surface モディファイア"),
    ("sop", "mirror"): ("Mesh ▸ Mirror", "Mirror モディファイア"),
    ("sop", "boolean"): ("Mesh ▸ Booleans", "Boolean モディファイア"),
    ("sop", "attribnoise"): ("Texture Deformer（テクスチャで頂点を動かす）", "Displace モディファイア（テクスチャで頂点を動かす）"),
    ("sop", "merge"): ("Mesh ▸ Combine", "結合（Ctrl+J）"),
    ("sop", "blast"): ("フェースを選んで Delete", "面を選んで削除（X）"),
    ("sop", "fuse"): ("Edit Mesh ▸ Merge", "Merge by Distance"),
    ("sop", "resample"): ("Curves ▸ Rebuild", "—（Geometry Nodes の Resample Curve）"),
    ("sop", "sweep"): ("Surfaces ▸ Extrude（カーブに沿って）・Sweep Mesh", "カーブの Bevel（断面）・Geometry Nodes の Curve to Mesh"),
    # 散らす・並べる
    ("sop", "scatter"): ("MASH の Distribute（Mesh で面に散らす）", "Geometry Nodes の Distribute Points on Faces"),
    ("sop", "copytopoints"): ("MASH（点に複製を置く）・Instancer", "Geometry Nodes の Instance on Points"),
    # 属性・コード
    ("sop", "attribwrangle"): ("Expression・Python で、頂点ごとの値を書き換える処理", "Geometry Nodes の Set Position・Store Named Attribute（ノードで書く代わりに、コードで書く）"),
    ("sop", "attribcreate"): ("頂点に独自のデータを持たせる（Add Attribute）", "Geometry Nodes の Store Named Attribute"),
    ("sop", "color"): ("頂点カラー（Mesh Display ▸ Apply Color）", "頂点カラー（Color Attribute）"),
    # UV・マテリアル
    ("sop", "uvunwrap"): ("UV Editor の Unfold・Automatic", "UV ▸ Unwrap"),
    ("sop", "uvflatten"): ("UV Editor の Unfold", "UV ▸ Unwrap"),
    ("sop", "uvlayout"): ("UV Editor の Layout", "UV ▸ Pack Islands"),
    ("vop", "principledshader"): ("Arnold の aiStandardSurface・Standard Surface", "Principled BSDF"),
    ("sop", "material"): ("Assign Material（Hypershade で割り当てる）", "マテリアルの割り当て（Material スロット）"),
    # シミュレーション
    ("sop", "rbdbulletsolver"): ("Bullet の Rigid Body（プラグイン）", "Rigid Body（Physics）"),
    ("sop", "voronoifracture"): ("—（標準の機能には無い。Bullet の Shatter など）", "Cell Fracture（アドオン）"),
    ("sop", "rbdmaterialfracture"): ("—（標準の機能には無い。Bullet の Shatter など）", "Cell Fracture（アドオン）"),
    ("sop", "pyrosolver"): ("Bifrost Aero・Fluid Effects（煙・炎）", "Mantaflow の Smoke / Fire（Quick Smoke）"),
    ("sop", "pyrosource"): ("Fluid Effects の Emitter", "Mantaflow の Flow（Smoke の発生源）"),
    ("sop", "vellumsolver"): ("nCloth", "Cloth（Physics）"),
    ("sop", "flipsolver"): ("Bifrost Liquid", "Mantaflow の Liquid"),
    ("dop", "popsolver"): ("nParticles", "Particle System"),
    ("dop", "rbdpackedobject"): ("Rigid Body（Active）", "Rigid Body（Active）"),
    ("dop", "staticobject"): ("Rigid Body（Passive）", "Rigid Body（Passive）"),
    ("dop", "gravity"): ("Gravity Field", "Scene の Gravity"),
    # リグ（KineFX）
    ("sop", "skeleton"): ("Skeleton ▸ Create Joints", "Armature（骨）"),
    ("sop", "jointdeform"): ("Bind Skin（skinCluster）で、骨に合わせてメッシュを動かす", "Armature モディファイア"),
    ("sop", "jointcaptureproximity"): ("Bind Skin の重み付け（近さで決める）", "Automatic Weights（自動のウェイト）"),
    ("sop", "rigpose"): ("ジョイントを回して、ポーズを付ける", "Pose Mode でポーズを付ける"),
}


def _base(type_name: str) -> str:
    """型の名前から、名前空間と版を外した名前。"scatter::2.0" → scatter、"kinefx::jointdeform" → jointdeform、
    Reference のキー "sop/kinefx--jointdeform" → jointdeform。"""
    name = str(type_name or "").strip().rsplit("/", 1)[-1].split("--")[-1].lower()
    parts = [p for p in name.split("::") if p and not p.replace(".", "").isdigit()]
    return parts[-1] if parts else ""


def for_node(type_name: str, context: str = "") -> dict | None:
    """ノードの型（"scatter::2.0" など）の、近い機能。文脈（sop / dop など）が分からなければ、sop → obj → dop → vop の順に探す。"""
    base = _base(type_name)
    if not base:
        return None
    contexts = [context.lower()] if context else ["sop", "obj", "dop", "vop"]
    for ctx in contexts:
        hit = _TABLE.get((ctx, base))
        if hit:
            return {"maya": hit[0], "blender": hit[1]}
    return None


def for_item(item: dict) -> dict | None:
    """Reference の項目（ノードだけ。キーは "sop/scatter"）の、近い機能。"""
    if not isinstance(item, dict) or item.get("kind") != "node":
        return None
    key = str(item.get("key") or "")
    context, _, name = key.partition("/")
    return for_node(name, context) if name else None


def html_block(analogy: dict | None, heading_style: str = "") -> str:
    """表示用の HTML（見出し・Maya・Blender・注記）。無ければ空文字。"""
    if not analogy:
        return ""
    esc = html.escape
    style = heading_style or "margin-bottom:2px;color:#c4b5fd"
    return (f"<p style='{style}'><b>ほかのツールでいうと（近いもの）</b></p>"
            f"<p style='margin-top:2px'>Maya: {esc(analogy['maya'])}<br>Blender: {esc(analogy['blender'])}<br>"
            f"<span style='color:#94a3b8'>{esc(NOTE)}</span></p>")
