"""
guide_shortcuts.py — 案内モード（Guide タブ）のショートカット表（2026-11-06）

手順ごとに「いま使うキー」を出すための、キーの表。以前は6個だけだったので、SideFX の公式ドキュメントで確かめた
キーに広げた（ネットワークエディタ・ビューポート・パラメータ・タイムライン・ペインの切り替え）。

守ること:
  ・載せるのは、下の SOURCES に挙げた公式ドキュメントに書かれているキーだけ。確かめられなかったものは載せない
    （例: レイアウトの L、削除の Delete、コピー・貼り付け）。足すときは、出典を確かめてから、source に書く。
  ・Houdini の標準のホットキー設定が前提（ホットキーを変えている人には、合わないことがある）。
  ・左右・中のボタンは「左／右／中」で書く。Space や Alt は、押しながらの操作。

Qt にも Houdini にも依存しない（テストできる）。
"""

from __future__ import annotations

SOURCES: dict[str, tuple[str, str]] = {
    "network": ("Network editor shortcuts", "https://www.sidefx.com/docs/houdini/network/shortcuts.html"),
    "hotkeys": ("Hotkey quick reference", "https://www.sidefx.com/docs/houdini/start/hotkeys.html"),
    "view": ("Viewing the scene", "https://www.sidefx.com/docs/houdini/basics/view.html"),
    "parms": ("Parameter editor", "https://www.sidefx.com/docs/houdini/network/parms.html"),
    "menus": ("Menus（Edit ▸ Undo）", "https://www.sidefx.com/docs/houdini/ref/menus.html"),
    "organize": ("Organizing, customizing, and annotating nodes and networks", "https://www.sidefx.com/docs/houdini/network/organize.html"),
}

GROUP_NETWORK = "ネットワークエディタ"
GROUP_ORGANIZE = "ネットワークの整理（ボックス・メモ・整列）"
GROUP_VIEWPORT = "ビューポート"
GROUP_PARM = "パラメータ"
GROUP_TIMELINE = "タイムライン"
GROUP_PANE = "ペイン（タブ）の切り替え"
GROUP_COMMON = "共通"
GROUPS = (GROUP_NETWORK, GROUP_ORGANIZE, GROUP_VIEWPORT, GROUP_PARM, GROUP_TIMELINE, GROUP_PANE, GROUP_COMMON)

# (id, グループ, キー, 何をするか, 出典)
_ROWS: list[tuple[str, str, str, str, str]] = [
    # ── ネットワークエディタ ──
    ("net_tab", GROUP_NETWORK, "Tab", "ノードの検索メニューを開く。名前を打って Enter", "hotkeys"),
    ("net_file", GROUP_NETWORK, "=", "File ノードを足す（使えるとき）", "network"),
    ("net_g", GROUP_NETWORK, "G", "選んでいるノードを、画面いっぱいに映す", "network"),
    ("net_h", GROUP_NETWORK, "H", "ネットワーク全体を映す", "network"),
    ("net_pan", GROUP_NETWORK, "Space + 左／中ドラッグ", "画面を平行移動する", "network"),
    ("net_zoom", GROUP_NETWORK, "Space + 右ドラッグ、またはホイール", "拡大・縮小する", "network"),
    ("net_wire", GROUP_NETWORK, "ドラッグ", "上のノードの出力（下の丸）から、下のノードの入力（上の丸）へ線を引く", "network"),
    ("net_insert", GROUP_NETWORK, "線を右クリック", "つながっているノードの間に、新しいノードを差し込む", "network"),
    ("net_branch", GROUP_NETWORK, "線を中クリック", "その線から枝分かれする、新しいノードを作る", "network"),
    ("net_cut", GROUP_NETWORK, "Y を押しながら線をまたいでドラッグ", "またいだ線を切る（つなぎ間違えたとき）", "network"),
    ("net_shake", GROUP_NETWORK, "ノードを振る（左右に素早くドラッグ）", "そのノードの線を、全部外す", "network"),
    ("net_dot", GROUP_NETWORK, "Alt + 線を左クリック", "線に中継点（ドット）を足して、線の通り道を整える", "network"),
    ("net_enter", GROUP_NETWORK, "Enter、またはダブルクリック", "選んだノード（geo など）の中に入る", "network"),
    ("net_up", GROUP_NETWORK, "U", "1つ上の階層へ出る", "network"),
    ("net_back", GROUP_NETWORK, "` （バッククォート）", "前に見ていた表示へ戻る", "network"),
    ("net_pgup", GROUP_NETWORK, "PgUp", "上流（入力側）のノードを選ぶ", "network"),
    ("net_pgdn", GROUP_NETWORK, "PgDn", "下流（出力側）のノードを選ぶ", "network"),
    ("net_info", GROUP_NETWORK, "ノードを中ボタンで押し続ける", "ノードの情報の窓を出す", "network"),
    ("net_copy", GROUP_NETWORK, "Alt + ノードをドラッグ", "ノードをコピーする", "network"),
    ("net_layout", GROUP_ORGANIZE, "A を押しながらノードをドラッグ（上・左へ／下・右へ）", "上流／下流のノードを、きれいに並べ直す", "network"),
    ("net_align", GROUP_ORGANIZE, "Shift + A を押しながらドラッグ", "選んだノードをそろえる", "network"),
    ("net_box", GROUP_ORGANIZE, "Shift + O", "選んだノードを入れた、ネットワークボックスを足す（ノードを囲んで、まとめられる）", "network"),
    ("net_note", GROUP_ORGANIZE, "Shift + P", "付箋（メモ）を足す", "network"),
    ("net_parm", GROUP_NETWORK, "P", "浮動のパラメータエディタを出す・しまう", "network"),
    ("net_find", GROUP_NETWORK, "Ctrl + F、または /", "ノードを検索する（Ctrl + G で次の一致）", "network"),
    ("net_bypass", GROUP_NETWORK, "Q（または B）を押しながらノードをクリック", "バイパス（そのノードを飛ばして、入力をそのまま通す）を切り替える", "network"),
    ("net_upstream", GROUP_NETWORK, "Alt + Shift + クリック", "ノードと、その上流（入力側）をすべて選ぶ", "network"),
    ("net_downstream", GROUP_NETWORK, "Alt + Ctrl + クリック", "ノードと、その下流（出力側）をすべて選ぶ", "network"),
    # ── ネットワークの整理 ──
    ("org_distribute", GROUP_ORGANIZE, "Alt + A を押しながらドラッグ", "選んだノードを、等間隔に並べる", "network"),
    ("org_shrink", GROUP_ORGANIZE, "Shift + M", "選んだネットワークボックスを、中身にぴったり合わせて縮める", "network"),
    ("org_minimize", GROUP_ORGANIZE, "Shift + J", "選んだ付箋・ボックスを、最小化（たたむ）", "network"),
    ("org_restore", GROUP_ORGANIZE, "Shift + K", "最小化した付箋・ボックスを、元に戻す", "network"),
    ("org_delete_box", GROUP_ORGANIZE, "Delete", "付箋、または中身を残したネットワークボックスを削除する（ノードは消えない）", "organize"),
    ("org_delete_all", GROUP_ORGANIZE, "Shift + Delete", "ネットワークボックスを、中のノードごと削除する", "organize"),
    ("org_color", GROUP_ORGANIZE, "C", "カラーパレットを出す・しまう（ノード・ボックス・付箋の色を付ける）", "network"),
    ("org_shape", GROUP_ORGANIZE, "Z", "シェイプパレットを出す・しまう（ノードの形を変える）", "network"),
    ("org_overview", GROUP_ORGANIZE, "O", "ネットワークの全体図（オーバービュー）を出す・しまう", "network"),
    ("org_tree", GROUP_ORGANIZE, "Shift + W", "ネットワークの階層（ツリー）表示を出す・しまう", "network"),
    ("org_marks", GROUP_ORGANIZE, "Ctrl + 1〜5 ／ Shift + 1〜5", "いまの表示を、しおり（1〜5）に登録する／しおりの表示へ戻る", "network"),
    ("org_move_in", GROUP_ORGANIZE, "Shift + ドラッグ", "ノードと、その上流（入力側）を、いっしょに動かす", "network"),
    ("org_move_out", GROUP_ORGANIZE, "Ctrl + ドラッグ", "ノードと、その下流（出力側）を、いっしょに動かす", "network"),
    # ── ビューポート ──
    ("vp_tumble", GROUP_VIEWPORT, "Space + 左ドラッグ", "回転する", "hotkeys"),
    ("vp_dolly", GROUP_VIEWPORT, "Space + 右ドラッグ、またはホイール", "近づく・離れる（ズーム）", "hotkeys"),
    ("vp_track", GROUP_VIEWPORT, "Space + 中ドラッグ", "平行移動する", "hotkeys"),
    ("vp_home", GROUP_VIEWPORT, "Space + H", "初期のビューに戻す", "hotkeys"),
    ("vp_frame_sel", GROUP_VIEWPORT, "Space + G", "選んだものを、画面いっぱいに映す", "hotkeys"),
    ("vp_frame_all", GROUP_VIEWPORT, "Space + A", "すべてのオブジェクトが入るように映す", "hotkeys"),
    ("vp_pivot", GROUP_VIEWPORT, "Space + Z", "ポインタの下の点を、回転の中心にする", "hotkeys"),
    ("vp_fine", GROUP_VIEWPORT, "Shift を押しながら回転・ズーム・移動", "細かく、ゆっくり動かす", "view"),
    ("vp_shade", GROUP_VIEWPORT, "W", "シェード表示とワイヤーフレーム表示を切り替える", "hotkeys"),
    ("vp_display", GROUP_VIEWPORT, "D", "ディスプレイオプションの窓を出す", "hotkeys"),
    ("vp_quad", GROUP_VIEWPORT, "Space + B", "1画面と4画面を切り替える", "hotkeys"),
    ("vp_ortho", GROUP_VIEWPORT, "Space + O", "パース（遠近）と正投影を切り替える", "hotkeys"),
    ("vp_views", GROUP_VIEWPORT, "Space + 1／2／3／4", "視点を パース／上／正面／側面 にする", "hotkeys"),
    ("vp_history", GROUP_VIEWPORT, "[ と ]", "視点の履歴を、戻る・進む", "view"),
    ("vp_boxzoom", GROUP_VIEWPORT, "Ctrl + Alt + 左ドラッグ", "囲んだ範囲を拡大する", "hotkeys"),
    ("vp_tools", GROUP_VIEWPORT, "S／T／R／E", "選択／移動／回転／スケールのツールにする（Esc で表示ツールへ）", "hotkeys"),
    # ── パラメータ ──
    ("pm_ladder", GROUP_PARM, "名前か欄を中ボタンでドラッグ", "値の「ラダー」を出す。上下で変化の大きさ、左右で値を変える", "parms"),
    ("pm_default", GROUP_PARM, "Ctrl + 中クリック", "そのパラメータを、既定値に戻す", "parms"),
    ("pm_arrow", GROUP_PARM, "数字の左をクリックして ↑／↓", "カーソルの右の桁を、増やす・減らす", "parms"),
    ("pm_prev", GROUP_PARM, "欄を右クリック → Revert to Previous Value", "直前の値に戻す", "parms"),
    ("pm_editor", GROUP_PARM, "欄をクリックして Alt + E", "外部のエディタで、中身（コードなど）を編集する", "parms"),
    ("pm_jump", GROUP_PARM, "Ctrl + 参照アイコンをクリック", "参照先のノードのパラメータを、別の窓で開く", "parms"),
    # ── タイムライン ──
    ("tl_play", GROUP_TIMELINE, "↑／↓", "順方向／逆方向に再生する", "hotkeys"),
    ("tl_step", GROUP_TIMELINE, "←／→", "前／次の1フレームへ", "hotkeys"),
    ("tl_first", GROUP_TIMELINE, "Ctrl + ↑", "最初のフレームへ", "hotkeys"),
    # ── ペイン（タブ）の切り替え ──
    ("pn_scene", GROUP_PANE, "Alt + 1", "シーンビュー（ビューポート）を前面に", "hotkeys"),
    ("pn_net", GROUP_PANE, "Alt + 2", "ネットワークエディタを前面に", "hotkeys"),
    ("pn_parm", GROUP_PANE, "Alt + 3", "パラメータを前面に", "hotkeys"),
    ("pn_sheet", GROUP_PANE, "Alt + 8", "Geometry Spreadsheet（Details view）を前面に", "hotkeys"),
    ("pn_new", GROUP_PANE, "Ctrl + T", "新しいタブを作る", "hotkeys"),
    ("pn_close", GROUP_PANE, "Ctrl + W", "タブを閉じる", "hotkeys"),
    ("pn_switch", GROUP_PANE, "Ctrl + PgUp／PgDn", "前／次のタブへ", "hotkeys"),
    ("pn_tear", GROUP_PANE, "Alt + Shift + C", "タブを、別の窓に切り離す", "hotkeys"),
    # ── 共通 ──
    ("undo", GROUP_COMMON, "Ctrl + Z", "直前の操作を取り消す（Edit ▸ Undo）", "menus"),
]

SHORTCUTS: list[dict] = [
    {"id": i, "group": g, "keys": k, "what": w, "source": s} for i, g, k, w, s in _ROWS
]
BY_ID: dict[str, dict] = {row["id"]: row for row in SHORTCUTS}

# 手順（ツール）ごとに出すキー。上から、使う順・大事な順。
TOOL_IDS: dict[str, list[str]] = {
    "create_node": ["net_tab", "net_find", "net_g", "net_h", "net_pan", "net_zoom", "net_enter", "net_up", "net_box", "net_note", "pn_net", "undo"],
    "connect_nodes": ["net_wire", "net_insert", "net_branch", "net_cut", "net_shake", "net_dot", "net_layout", "net_align", "org_distribute", "net_box", "net_note", "org_color", "net_g", "net_h", "pn_net", "undo"],
    "delete_node": ["net_bypass", "net_pgup", "net_pgdn", "org_delete_box", "org_delete_all", "net_g", "net_h", "undo"],
    "set_parameter": ["pm_ladder", "pm_default", "pm_arrow", "pm_prev", "pm_jump", "net_parm", "pn_parm", "undo"],
    "cook_node": ["vp_tumble", "vp_dolly", "vp_track", "vp_home", "vp_frame_sel", "vp_pivot", "vp_fine", "vp_shade", "vp_display",
                  "tl_play", "tl_step", "tl_first", "pn_sheet", "pn_scene"],
}
# コードを入れるパラメータの手順だけに足すキー
CODE_PARM_IDS = ["pm_editor"]


def for_step(tool: str, code: bool = False) -> list[dict]:
    """手順（ツール）に合う、キーの一覧。各項目は {"keys", "what", "group"}。code=True なら、コード欄向けのキーも足す。"""
    ids = list(TOOL_IDS.get(tool, []))
    if code:
        at = ids.index("pm_jump") if "pm_jump" in ids else len(ids)
        ids[at:at] = CODE_PARM_IDS
    return [{"keys": BY_ID[i]["keys"], "what": BY_ID[i]["what"], "group": BY_ID[i]["group"]} for i in ids if i in BY_ID]


def cheatsheet(query: str = "") -> list[tuple[str, list[dict]]]:
    """全部のキーを、グループごとに。query があれば、キー・説明・グループの名前に含まれるものだけ（大文字小文字・全角半角の差は無視）。"""
    needle = _norm(query)
    out: list[tuple[str, list[dict]]] = []
    for group in GROUPS:
        rows = [r for r in SHORTCUTS if r["group"] == group and (not needle or needle in _norm(r["keys"] + r["what"] + r["group"]))]
        if rows:
            out.append((group, rows))
    return out


def _norm(text: str) -> str:
    return "".join(str(text).lower().split())
