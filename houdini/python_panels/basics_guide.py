"""
basics_guide.py — Guide タブに組み込みの「Houdini の基本操作（練習）」（2026-11-25。Qt にも Houdini にも依存しない）

背景: 本システムは、基本操作ができる人に、ノードの組み方を教える作り。実証実験の参加者の多くは Houdini が初めてで
（第 2 回は 8 人中 5 人が経験 0 年）、「Guide の操作のための用語が、そもそも分からない」という声があった。
→ 生成したチュートリアルの前に、手で書いた練習で、画面の見方・ビューポートの動かし方・ノードの作り方・中への入り方・
   線のつなぎ方・表示フラグ・パラメータを、実際に手を動かして覚える。AI は使わない（費用がかからず、誤りが入らない）。

形は、生成した案内（guide_mode.build_guide の結果）と同じ。Guide の「この手順を案内」「この手順を Chat に聞く」が、そのまま使える。
作るノードは、学習者の /obj の下（practice_geo）。ショートカットは、公式ドキュメントで確かめた表（guide_shortcuts）から引く。
"""

from __future__ import annotations

import guide_shortcuts

KEY = "builtin:basics"
LABEL = "【最初に】Houdini の基本操作（練習・AI を使わない）"
GEO = "practice_geo"


def _keys(*ids: str) -> list[dict]:
    rows = [guide_shortcuts.BY_ID[i] for i in ids if i in guide_shortcuts.BY_ID]
    return [{"keys": r["keys"], "what": r["what"], "group": r["group"]} for r in rows]


def _step(number: int, tool: str, tab: str, work: str, instruction: str, hint: str, shortcuts: list[dict], **extra) -> dict:
    import guide_mode

    step = {"step": number, "tool": tool, "tab": tab, "tab_label": guide_mode.TAB_LABELS[tab], "work": work,
            "instruction": instruction, "hint": hint, "shortcuts": shortcuts, "node": "", "node_path": "", "node_type": "",
            "node_label": "", "parms": [], "from": "", "to": "", "connections": [], "purpose": ""}
    step.update(extra)
    return step


def build() -> dict:
    """練習の案内データ。"""
    steps = [
        _step(1, "learn", "network", "【見る】Houdini の画面の 3 つの場所",
              "ネットワークエディタ・パラメータ・ビューポートの 3 つを見つける",
              "ネットワークエディタは、ノードを置いて線でつなぐ場所。パラメータは、選んだノードの値を変える場所。"
              "ビューポート（Scene View）は、結果の形を見る場所。Houdini では、この 3 つを行き来しながら作ります",
              _keys("pn_net", "pn_parm", "pn_scene")),
        _step(2, "learn", "viewport", "【練習】ビューポートを動かす",
              "ビューポートの上で、回す・近づく・平行移動・元に戻す、を試す",
              "Space を押しながらマウスで動かします。見失ったら Space + H（初期のビュー）か Space + A（全部を映す）",
              _keys("vp_tumble", "vp_dolly", "vp_track", "vp_home", "vp_frame_all")),
        _step(3, "create_node", "network", f"【作業する部分】/obj の中に、新しいノード「Geometry」（名前: {GEO}）を作る",
              f"ネットワークエディタで /obj（Object レベル）を表示し、Tab を押して「Geometry」と入力して Enter",
              f"Object レベル（/obj）には、オブジェクト（形の入れ物）を置きます。名前は、パラメータの上の名前の欄で {GEO} に変えます"
              "（変えなくても練習できますが、Guide はこの名前で案内します）",
              _keys("net_tab", "pn_net", "undo"), node=GEO, node_path=GEO, node_type="geo", node_label="Geometry",
              purpose="形を作る入れ物（オブジェクト）を用意する"),
        _step(4, "learn", "network", f"【作業する部分】{GEO} の中に入る",
              f"{GEO} を選んで Enter（またはダブルクリック）で中に入る。U で 1 つ上（/obj）に戻れることも試す",
              "中に入ると、形そのものを作る階層（SOP）になります。ネットワークエディタの上の道筋（/obj/" + GEO + "）で、いまの階層が分かります。"
              "Guide の「いまのネットワーク」の帯も、同じものを示します",
              _keys("net_enter", "net_up", "net_h"), node=GEO, node_path=GEO, node_type="geo", node_label="Geometry"),
        _step(5, "create_node", "network", f"【作業する部分】/obj/{GEO} の中に、新しいノード「Box」（名前: box1）を作る",
              f"{GEO} の中で、Tab を押して「Box」と入力して Enter",
              "Box は、箱の形を作るノードです。ビューポートに箱が出ます",
              _keys("net_tab", "vp_frame_all", "undo"), node="box1", node_path=f"{GEO}/box1", node_type="box", node_label="Box",
              purpose="形の元（箱）を作る"),
        _step(6, "learn", "network", "【見る】表示フラグ（どのノードの結果を見るか）",
              "ノードの右端の青い部分（表示フラグ）を押すと、そのノードの結果がビューポートに出る",
              "ネットワークの中で、表示フラグが付いた 1 つのノードの結果だけが、ビューポートに出ます。"
              "手順で「結果を確かめる」と書かれたら、そのノードに表示フラグを付けます",
              _keys("net_g", "vp_frame_sel"), node="box1", node_path=f"{GEO}/box1", node_type="box", node_label="Box"),
        _step(7, "create_node", "network", f"【作業する部分】/obj/{GEO} の中に、新しいノード「Transform」（名前: transform1）を作る",
              "Tab を押して「Transform」と入力して Enter。box1 の下に置く",
              "Transform は、形を動かす・回す・大きさを変えるノードです",
              _keys("net_tab", "undo"), node="transform1", node_path=f"{GEO}/transform1", node_type="xform", node_label="Transform",
              purpose="箱を動かす"),
        _step(8, "connect_nodes", "network", f"【作業する部分】/obj/{GEO} の中で、ノードの線をつなぐ",
              "box1 → transform1 をつなぐ",
              "box1 の下の丸（出力端子）から、transform1 の上の丸（入力端子）へ、ドラッグして線を引きます。上から下へ、データが流れます",
              _keys("net_wire", "net_cut", "undo"), node="transform1", node_path=f"{GEO}/transform1", node_type="xform",
              node_label="Transform", **{"from": "box1", "to": "transform1"}, connections=[{"from": "box1", "to": "transform1", "input": 0}]),
        _step(9, "set_parameter", "parm", f"【作業する部分】/obj/{GEO}/transform1 のパラメータを変える",
              "transform1 を選び、パラメータの Translate の 2 つ目（Y）を 1 にする",
              "パラメータは、選んだノードの値です。数字の欄は、直接入力するほか、中ボタンでドラッグして変えられます",
              _keys("pm_ladder", "pm_default", "undo"), node="transform1", node_path=f"{GEO}/transform1", node_type="xform",
              node_label="Transform", parms=[{"name": "ty", "label": "Translate（Y）", "old": "0", "new": "1", "where": ""}]),
        _step(10, "cook_node", "viewport", f"【作業する部分】/obj/{GEO}/transform1 の結果を、ビューポートで確かめる",
              "transform1 に表示フラグを付けて、箱が上に 1 動いたことを確かめる",
              "表示フラグが box1 のままだと、動く前の箱が見えます。最後のノードに表示フラグを付けるのが基本です",
              _keys("vp_frame_all", "vp_tumble"), node="transform1", node_path=f"{GEO}/transform1", node_type="xform", node_label="Transform"),
        _step(11, "learn", "spreadsheet", "【見る】中身を数値で見る（Geometry Spreadsheet）",
              "Geometry Spreadsheet で、箱の点の位置（P）の数値を見る",
              "形は、点の集まりと、点に付いた値（属性）でできています。チュートリアルの「属性」「点」は、この表の行と列のことです",
              _keys("pn_sheet"), node="transform1", node_path=f"{GEO}/transform1", node_type="xform", node_label="Transform"),
        _step(12, "learn", "network", "【まとめ】ここまでできたら、生成したチュートリアルに進める",
              "作る（Tab）→ つなぐ（ドラッグ）→ 値を変える（パラメータ）→ 表示フラグで確かめる、の 4 つが、Guide の手順の基本です",
              "分からない言葉は、手順の文でダブルクリックすると、意味が出ます（ノードの名前は Reference で探します）。"
              "言葉をまとめて見るときは「用語の一覧」。詰まったら「この手順を Chat に聞く」。"
              "練習で作った " + GEO + " は、消してかまいません（/obj で選んで Delete）",
              _keys("net_up", "undo")),
    ]
    return {"version": 1, "title": "Houdini の基本操作（練習）", "level": "basics", "steps": steps, "builtin": KEY,
            "prerequisites": "Houdini を起動し、新しいシーン（File ▸ New）で始めます。",
            "tips": "操作を間違えたら Ctrl + Z で戻せます。"}
