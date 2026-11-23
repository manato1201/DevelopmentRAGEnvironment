"""
screen_capture.py — Houdini ビューポート／ネットワークエディタのスクリーンショット取得

LearningQt の動画生成エンジン（video_factory_cloudrag_poc.exe）が右パネルに
「実際のHoudini画面」を表示できるよう、チュートリアル保存直後
（tutorial_view.py::_on_save、video_factory_bridge.py 経由）に呼ばれる。

いずれの関数もベストエフォート: 失敗時は例外を投げず False を返すだけ
（呼び出し元の tutorial_view.py::_on_save がチュートリアル保存そのものを
失敗させないため）。

実機検証の経緯（2026-07-24/25、Houdini 21.0.700）:
  - 初回: 両キャプチャとも失敗し、PNGも作られずコンソールにも何も出ない事例を
    確認。Houdiniがコンソール非接続のGUIプロセスとして起動されていると
    print() の行き先が無く消えるため、_log() でファイルにも書くようにした
    （video_factory_bridge.py 側が <slug>_capture.log のパスを渡す）
  - hou.FlipbookSettings() の直接コンストラクタ呼び出しが「抽象クラス」
    エラーになることが判明 → flipbookSettings().stash() 経由に修正
  - capture_network_editor() の qtWidget() がこのビルドに存在しないことが
    dir() で判明 → qtParentWindow() 全体グラブに変更したが、生成中に
    RAGChatBotパネル自体が映り込む問題が発生
  - screenBounds() でペイン単体に絞り込むクロップを試したが、17ステップ
    全てで同一の [0, 0, 613, 332] が返り、実際には画面の絶対座標ではなく
    Houdiniのペイン内部だけのローカル座標系だったため、常に画面左上の同じ
    誤った領域（メニューバー付近）を切り出してしまうことが確認された →
    このクロップは撤回し、qtParentWindow() 全体グラブに戻した
    （ネットワークエディタ単体には絞れないが、実際に変化する内容が映る）
  - capture_viewport() の flipbook() 自体は正しく動作し内容も毎回変化する
    ことを確認したが、ビューポートのフレーミングが素のままだと対象物が
    画面の隅の小さな点になってしまう問題があったため、撮影前に
    curViewport().frameAll() を追加した

2026-08-06 追加: capture_viewport_clip() — cook_node（シミュレーション系
ノードの評価）専用に、静止画1枚ではなく短い連番PNGクリップを撮る。
flipbook() のフレームレンジを複数枚に広げるだけで、既存の capture_viewport()
と同じ機構を再利用できる。重さ・コスト面を考慮して解像度と枚数を意図的に
低く抑えてある。

2026-08-08 追加: focus_network_on() の setIsCurrentTab() 呼び出し直後に
QApplication.processEvents() を挟むよう修正。commit a8c5ccb で
setIsCurrentTab() を導入したがそれでも capture_network_editor() が
Python Panel Editor（RAGChatBotパネル自身）の中身を撮ってしまう不具合が
実機で再現した。原因は setIsCurrentTab() がタブの「アクティブ」状態を
即座に切り替えるものの、実際の再描画は Qt のイベントループが次に回る
まで行われないため。このモジュールの capture 系関数は Python の同期呼び
出しだけで完結しており、setIsCurrentTab() の直後に間を置かず
qtParentWindow().grab() してしまうと、Qt がまだ古い（切り替え前の）
内容を描画したままのウィジェットを掴んでしまう。processEvents() を
数回呼んでイベントループを手動で回し、タブ切り替えの再描画を
grab() の前に強制的に完了させる。

2026-09-26 ネットワーク画面の撮影を作り直し: capture_network_editor() は
hou.NetworkEditor.qtScreenGeometry()（公式ドキュメントにある「ペインの画面座標」）で
実画面を切り出し、成立しなければ自前描画のネットワーク図（render_network_diagram）へ
フォールバックする。ウィジェット階層の探索（hou.qt.mainWindow()/トップレベルウィンドウ列挙）
は実機でHoudini本体を返さないと判明済みのため廃止した。撮影対象も「サンドボックス直下」
から「作業中のネットワーク（geoの中身）」に変更した。

2026-11-17 実証実験を受けた変更（video-capture）:
  - ノード図: 注目ノードと前後だけを、名前が読める大きさ（MIN_NAME_PT）で描く。全体図は 1 枚だけ（select_focus_nodes）
  - 実画面のネットワークエディタ: 注目ノードと前後が映る範囲に合わせる（plan_focus_bounds / frame_network_on_focus）。
    ペインが狭いときは、ペインを一時的に最大化して撮る（maximized_if_narrow。描き直した図は、実画面が撮れないときの最後の手段）
  - 長いコード: 専用のカード（大きい等幅・折り返し・複数枚。render_code_cards）
  - パラメータ画面: 変更した項目のタブを前面にし（reveal_parm_tabs）、タブ名をスライドに出す（with_tab_paths）
  - 撮った画像のとなりに <画像>.meta.json を書く（品質チェッカーが、文字の大きさ・省略の有無を読む）

2026-08-12 追加: IMPROVEMENT_PLAN.md Phase2（VLM対応）で、capture_viewport() の
出力（PNG）を rag_chatbot.py のChatタブ添付画像・localRAG画像インデックス
（scripts/image_embedding_generator.py）の両方の入力ソースとして流用している。
新規のキャプチャ機構は作らず、この2関数（capture_viewport / capture_viewport_clip）
のシグネチャ（output_path/output_dir・width・height・log_path、戻り値bool/
(list[Path], int)）を「画面キャプチャ→VLM入力」経路の共通インターフェース候補
として扱う。別文書「VLMAutoReplayTool設計書」が同型の経路（画面キャプチャ→VLM
入力）を扱う場合は、独自のキャプチャ実装を持たずこのモジュールを参照すること。
"""

from __future__ import annotations

import contextlib
import datetime
import glob
import re
import time
import unicodedata
from pathlib import Path

import display_isolation
import hou


def _log(message: str, log_path: Path | None) -> None:
    """print() に加えてファイルへも書く（ファイル書き込み失敗は無視する）。"""
    line = f"[screen_capture] {message}"
    if log_path is None:
        print(line)
        return
    # log_path がある（生成中の通常経路）ときは print しない。Houdini は標準出力に初めて
    # 文字が出た時に「Houdini Console」ウィンドウを開き、それがちょうどネットワーク
    # エディタの上に重なって動画に写り込んでいた（2026-10-04、実機で確認）。ログは
    # capture.log に残る。
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()} {line}\n")
    except OSError:
        pass


def _flush_qt_events() -> None:
    """
    保留中の Qt イベント（ペイン切り替えの再描画など）を強制的に処理させる。
    setIsCurrentTab() のようなウィジェット状態の変更は、Python の同期呼び出し
    だけでは即座に画面へ反映されない（次のイベントループ周回で初めて repaint
    される）ため、その直後に grab() すると切り替え前の内容を掴んでしまう。
    数回 processEvents() を回すことで、grab() 前に repaint を確実に終わらせる。
    """
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        for _ in range(4):
            app.processEvents()
    except Exception:  # noqa: BLE001 -- best-effort, never raise
        pass


def _frame_network_children(network_editor, network, log_path: Path | None, focus_path: str | None = None) -> None:
    """ネットワークの表示範囲を合わせる。focus_path があれば、そのノードと前後を、読める大きさで映す（frame_network_on_focus）。
    無ければ、直下の全ノードが視野に収まるようにする（ノードが多いと、名前は小さくなる）。"""
    if focus_path and frame_network_on_focus(network_editor, network, focus_path, log_path):
        return
    children = list(network.children())
    if children:
        try:
            xs = [c.position()[0] for c in children]
            ys = [c.position()[1] for c in children]
            pad = 2.5  # ノード1個分（約1.0x0.3）に余白を足した程度
            bounds = hou.BoundingRect(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
            network_editor.setVisibleBounds(bounds)
            return
        except Exception as exc:  # noqa: BLE001
            _log(f"setVisibleBounds failed, falling back to homeToSelection(): {exc!r}", log_path)
    try:
        network_editor.homeToSelection()
    except Exception as exc:  # noqa: BLE001
        _log(f"homeToSelection() failed: {exc!r}", log_path)


def frame_network_on_focus(network_editor, network, focus_path: str, log_path: Path | None = None) -> bool:
    """注目ノード（focus_path）と、その前後のノードが、読める大きさで映るよう、ネットワークエディタの表示範囲を合わせる。
    範囲の決め方は plan_focus_bounds（幅の上限 MAX_VIEW_WIDTH）。合わせられたら True。"""
    try:
        children = list(network.children())
        items = []
        for c in children:
            pos = c.position()
            inputs = []
            for conn in c.inputConnections():
                source = conn.inputNode()
                if source is not None:
                    inputs.append(source.path())
            item = {"path": c.path(), "x": float(pos[0]), "y": float(pos[1]), "inputs": inputs}
            try:  # ノードの箱の大きさ（COP のノードは大きい）。取れなければ、位置だけで範囲を決める
                size = c.size()
                item["w"], item["h"] = float(size[0]), float(size[1])
            except Exception:  # noqa: BLE001
                pass
            items.append(item)
        if not any(i["path"] == focus_path for i in items):
            return False
        aspect = 16 / 9
        try:
            rect = network_editor.qtScreenGeometry()
            if rect.height() > 0:
                aspect = float(rect.width()) / float(rect.height())
        except Exception:  # noqa: BLE001 -- 縦横比が読めなければ、16:9
            pass
        (x0, y0, x1, y1), shown, hidden = plan_focus_bounds(items, focus_path, aspect)
        network_editor.setVisibleBounds(hou.BoundingRect(x0, y0, x1, y1))
        _log(f"network framing: focus {focus_path}, {len(shown)} node(s) in view, {len(hidden)} outside", log_path)
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"frame_network_on_focus failed: {exc!r}", log_path)
        return False


def focus_network_on(node_path: str, log_path: Path | None = None, focus_path: str | None = None) -> None:
    """
    ネットワークエディタのペインを、node_path（ネットワーク＝ノードを内包するコンテナ）の
    中身が全部見える状態にし、そのペインを「現在表示中のタブ」に切り替える。

    2026-09-26: 引数は「サンドボックス」ではなく「作業中のネットワーク（例: geoノード）」
    を渡す。以前は常にサンドボックス直下を映しており、実際のノードが入っているgeoの
    中身が映らなかった。表示範囲も homeToSelection()（選択ノードだけを拡大）ではなく
    子ノード全体が入る矩形にする。

    Houdiniのペインはタブ切り替え式で、同じペイングループ内の他のタブ（Scene View等）が
    アクティブだと、Qt側はネットワークエディタの中身をそもそも描画していない。
    setIsCurrentTab() で前面に出し、_flush_qt_events() で再描画を完了させてから撮影する。
    失敗しても静かに諦める（ベストエフォート）。

    2026-11-17: focus_path（注目ノード）を渡すと、そのノードと前後が読める大きさで映る範囲に合わせる（frame_network_on_focus）。
    渡さなくても、capture_network_editor が、撮影の直前に、注目ノードに合わせ直す。
    """
    try:
        network = hou.node(node_path)
        if network is None:
            _log(f"focus_network_on: network not found: {node_path}", log_path)
            return
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor is None:
            _log("focus_network_on: no NetworkEditor pane found", log_path)
            return
        network_editor.setPwd(network)
        _frame_network_children(network_editor, network, log_path, focus_path)
        if hasattr(network_editor, "setIsCurrentTab"):
            network_editor.setIsCurrentTab()
            _flush_qt_events()
        else:
            _log("focus_network_on: no setIsCurrentTab() on this Houdini build", log_path)
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"focus_network_on failed: {exc!r}", log_path)



# 2026-10-21: ビューポートの「見切れ」対策。以前は frameAll()（シーン全体）に合わせていたため、
# ①サンドボックスの外にある、ユーザー自身のオブジェクトまで含めた範囲になり、作ったものが小さくなる／端に寄る、
# ②出力（1280x720）の縦横比が、ビューポートの縦横比と違うと、上下（または左右）が切り落とされる、が起きていた。
# 作ったジオメトリ（表示中のオブジェクト）の境界ボックスに、余白をつけて合わせ、出力の縦横比を、ビューポートに合わせる。
_FRAME_PADDING = 0.18  # 境界ボックスの各辺に足す余白（大きさに対する割合）
_MIN_ASPECT, _MAX_ASPECT = 0.6, 2.4

# 2026-10-31: 画像の解像度を上げた（動画やビューアで見るとき、ノード名・パラメータの文字がつぶれていたため）。
#   ・ビューポート: 1280x720 → 1920x1080（flipbook の書き出しサイズ）
#   ・短いクリップ: 640x360 → 960x540（枚数が多いので、控えめに）
#   ・描き直す図・カード（ネットワーク図・パラメータカード・パラメータ画面の合成）:
#       レイアウトは従来どおり 1280x720 の座標のまま、画素だけ RENDER_SCALE 倍で描く（出力は 2560x1440）。
#       座標を書き換えないので、文字の大きさ・配置の比率は変わらず、細かさだけが上がる。
#   ・実画面（ネットワークエディタ・パラメータ画面）の切り出し: 以前は 1280x720 に合わせて縮小していた
#       （高解像度の画面では、半分以下に縮んで文字がつぶれた）。今は、切り出した画素数のまま保存する。
#       小さすぎるときだけ拡大し、極端に大きいときだけ縮小する（fit_pane_size）。
VIEWPORT_WIDTH, VIEWPORT_HEIGHT = 1920, 1080
CLIP_WIDTH, CLIP_HEIGHT = 960, 540
# 2026-11-06: 動く様子の長いクリップ（約10秒）。動画エンジンは、クリップを自分の fps で頭から再生し、終わったら最後のコマで止める
# （RAGReel の main_cloudrag.cpp）。16コマ・12fps（約1.3秒）だと、解説の12秒のうち、10秒ほどが止まった絵になっていた。
# 枚数は、シミュレーションを頭から回す時間とディスクの量に直結するので、控えめに（120コマ。640x360）。
LONG_CLIP_FRAMES = 120
LONG_CLIP_FPS_MIN, LONG_CLIP_FPS_MAX = 6, 12
LONG_CLIP_TARGET_SECONDS = 10.0
LONG_CLIP_WIDTH, LONG_CLIP_HEIGHT = 640, 360
LOGICAL_WIDTH, LOGICAL_HEIGHT = 1280, 720
RENDER_SCALE = 2
PANE_MIN_WIDTH, PANE_MAX_WIDTH = 1280, 3840


def fit_pane_size(width: int, height: int, min_width: int = PANE_MIN_WIDTH, max_width: int = PANE_MAX_WIDTH) -> tuple[int, int]:
    """切り出した画面の保存サイズ。min_width〜max_width の範囲ならそのまま（縮小しない）。
    狭いときは幅を min_width まで、広すぎるときは max_width まで、縦横比を保って変える。"""
    if width <= 0 or height <= 0:
        return width, height
    target = min(max(width, min_width), max_width)
    if target == width:
        return width, height
    return target, max(1, int(round(height * target / width)))


# ─── 注目するノードを中心にした、読める大きさの撮り方（2026-11-17。副作用なし。Qt も hou も使わない） ───────────
# 実験の結果、「ノード数が増えると、全体を 1 枚に収めるので、ノード名が小さくて読めない」が出た。
# 前の動き: 描き直すネットワーク図は、全ノードを 1 枚に収め、拡大率の下限は 0.35 だった。40 ノードの一本道では、
#   名前の文字は 3.85pt（読めない）になり、しかも図の高さ（1436）が画面の高さ（632）を超えて、画面の外にはみ出した。
# 後の動き: 各手順の図は、注目するノードと、その前後（つながっているノード）だけを大きく描く。名前の大きさに下限（MIN_NAME_PT）
#   を決め、下限を守れる数のノードだけを残す（ほかは、「ほか N 個は省略」と書く）。全体図は、章の冒頭などで 1 枚だけ使う。
DIAGRAM_NAME_PT = 14.0
DIAGRAM_TYPE_PT = 10.0
MIN_NAME_PT = 12.0  # 注目ノードの図で、ノード名の最小の大きさ（pt。出力の論理座標 1280x720 での値。動画では約 1.3 倍の画素になる）
MIN_FOCUS_SCALE = MIN_NAME_PT / DIAGRAM_NAME_PT
OVERVIEW_MIN_SCALE = 0.05  # 全体図は、構成が分かればよい。名前が読めなくても、画面の外にははみ出させない（ほぼ無制限に縮める）
DIAGRAM_MAX_SCALE = 1.6
DIAGRAM_BOX_H, DIAGRAM_GAP_X, DIAGRAM_GAP_Y = 56.0, 36.0, 52.0
DIAGRAM_BOX_MIN_W = 150.0
DIAGRAM_BAR_H = 40.0
DIAGRAM_MARGIN_W, DIAGRAM_MARGIN_H = 80.0, 48.0


def diagram_node_width(name: str, advance: float | None = None) -> float:
    """図の中のノードの箱の幅。advance は、名前の文字列の実際の幅（Qt の測定値）。無ければ、文字数からの見積もり。"""
    text_w = advance if advance is not None else len(name) * DIAGRAM_NAME_PT * 0.62
    return max(DIAGRAM_BOX_MIN_W, text_w + 40.0)


def layout_extent(layers: list[list[dict]], width_of=None) -> tuple[float, float, list[float]]:
    """段（レイヤー）に分けたノードを並べたときの、全体の幅・高さと、各段の幅。"""
    width_of = width_of or (lambda n: diagram_node_width(n["name"]))
    row_widths = []
    for members in layers:
        widths = [width_of(n) for n in members]
        row_widths.append(sum(widths) + DIAGRAM_GAP_X * max(0, len(widths) - 1))
    layout_w = max(row_widths, default=0.0)
    layout_h = len(layers) * DIAGRAM_BOX_H + max(0, len(layers) - 1) * DIAGRAM_GAP_Y
    return layout_w, layout_h, row_widths


def diagram_scale(
    layout_w: float, layout_h: float, width: int, height: int, min_scale: float
) -> tuple[float, bool]:
    """図を画面に収める拡大率。戻り値: (拡大率, min_scale を守って収まるか)。収まらないときの拡大率は min_scale。"""
    if layout_w <= 0 or layout_h <= 0:
        return 1.0, True
    avail_w = width - DIAGRAM_MARGIN_W
    avail_h = height - DIAGRAM_BAR_H - DIAGRAM_MARGIN_H
    fit = min(avail_w / layout_w, avail_h / layout_h, DIAGRAM_MAX_SCALE)
    return max(min_scale, fit), fit >= min_scale


def _subset_model(model: list[dict], keep: set[str]) -> list[dict]:
    """keep に含まれるノードだけの model。入力の接続は、残ったノード同士のものだけにする。"""
    out = []
    for n in model:
        if n["path"] in keep:
            copy = dict(n)
            copy["inputs"] = [(p, i) for p, i in n["inputs"] if p in keep]
            out.append(copy)
    return out


# 近場の図に、最低でも、注目ノードを含めて、この数のノードを入れる（2026-11-23）。実際の動画で、ノードを作った手順の図が、
# 作ったノード 1 個だけ（まだつながっていないため）で、周りのノードが分からなかった。つながりが足りないときは、位置の近いノードを足す。
MIN_CONTEXT_NODES = 3


def _distance_sq(a: dict, b: dict) -> float:
    return (float(a.get("x", 0.0)) - float(b.get("x", 0.0))) ** 2 + (float(a.get("y", 0.0)) - float(b.get("y", 0.0))) ** 2


def select_focus_nodes(
    model: list[dict], focus_path: str | None, width: int = LOGICAL_WIDTH, height: int = LOGICAL_HEIGHT,
    width_of=None, min_scale: float = MIN_FOCUS_SCALE, min_context: int = MIN_CONTEXT_NODES,
) -> tuple[list[dict], int]:
    """注目ノードと、その前後だけを残す。戻り値: (残した model, 省いたノード数)。
    つながりの近さ（何本たどるか）が小さいノードから足し、名前の大きさの下限（min_scale）を守れる範囲で止める。
    つながっているノードが少なくて、注目ノードを含めて min_context 個に満たないときは、ネットワークでの位置が近いノードを足す
    （作ったばかりで、まだつながっていないノードでも、周りが分かるように）。
    focus_path が無い・model に無いときは、全部を返す（全体図）。"""
    by_path = {n["path"]: n for n in model}
    if focus_path is None or focus_path not in by_path:
        return list(model), 0

    adjacent: dict[str, set[str]] = {p: set() for p in by_path}
    for n in model:
        for source, _idx in n["inputs"]:
            if source in by_path:
                adjacent[n["path"]].add(source)
                adjacent[source].add(n["path"])
    distance = {focus_path: 0}
    queue = [focus_path]
    for current in queue:
        for neighbor in sorted(adjacent[current]):
            if neighbor not in distance:
                distance[neighbor] = distance[current] + 1
                queue.append(neighbor)

    def fits(keep: set[str]) -> bool:
        sub = _subset_model(model, keep)
        lw, lh, _ = layout_extent(_assign_layers(sub), width_of)
        return diagram_scale(lw, lh, width, height, min_scale)[1]

    keep = {focus_path}
    rings: dict[int, list[str]] = {}
    for path, d in distance.items():
        if d > 0:
            rings.setdefault(d, []).append(path)
    for d in sorted(rings):
        ring = sorted(rings[d], key=lambda p: by_path[p]["name"])
        if fits(keep | set(ring)):
            keep |= set(ring)
            continue
        for path in ring:  # 1 周は入りきらない。入るだけ足して、そこで止める
            if fits(keep | {path}):
                keep.add(path)
        break
    if len(keep) < min_context:
        focus = by_path[focus_path]
        for node in sorted((n for n in model if n["path"] not in keep), key=lambda n: (_distance_sq(n, focus), n["name"])):
            if len(keep) >= min_context:
                break
            if fits(keep | {node["path"]}):
                keep.add(node["path"])
    kept = _subset_model(model, keep)
    return kept, len(model) - len(kept)


# 実画面（ネットワークエディタ）の撮影範囲。ネットワークの座標は、ノード 1 個が約 1.0〜1.6 の幅（推測。実機で要確認）。
MIN_VIEW_WIDTH, MAX_VIEW_WIDTH = 7.0, 14.0
VIEW_PAD_X, VIEW_PAD_Y = 1.6, 1.2
MIN_VIEW_ASPECT, MAX_VIEW_ASPECT = 0.25, 4.0
# ネットワークエディタの上端には、パス欄とメニューの帯が重なっている（実機の画像で、高さの約 16%）。範囲を合わせても、
# 上端のノードがこの帯に隠れて、切れて見えた（2026-11-20）。範囲を上に広げて、ノードを帯の下に収める。
NETWORK_TOP_OVERLAY = 0.16


def plan_focus_bounds(
    items: list[dict], focus_path: str, aspect: float = 16 / 9,
    min_width: float = MIN_VIEW_WIDTH, max_width: float = MAX_VIEW_WIDTH, top_overlay: float = NETWORK_TOP_OVERLAY,
) -> tuple[tuple[float, float, float, float], list[str], list[str]]:
    """実画面のネットワークエディタで、注目ノードと、その前後を、読める大きさで映す範囲を決める。
    items: [{"path", "x", "y", "inputs": [path...], "w"?, "h"?}]。aspect: ペインの 幅/高さ。w・h は、ノードの箱の大きさ（無ければ 0）。
    COP のノードは、SOP より大きい（サムネイルつき）ので、位置だけで範囲を決めると、端のノードが切れて見えた（2026-11-23 の実画面）。
    戻り値: ((x0, y0, x1, y1), 映るノードの path, 範囲の外に出るノードの path)。
    幅が max_width（これ以上広いと、名前が読めない）を超えるときは、注目ノードから遠いものを外す。min_width より狭いときは広げる。
    つながっているノードが少なくて、注目ノードを含めて MIN_CONTEXT_NODES 個に満たないときは、位置の近いノードも入れる。"""
    by_path = {i["path"]: i for i in items}
    focus = by_path.get(focus_path)
    if focus is None:
        raise ValueError(f"focus node not found: {focus_path}")
    related = {focus_path}
    for item in items:
        if item["path"] == focus_path:
            related.update(p for p in item["inputs"] if p in by_path)
        elif focus_path in item["inputs"]:
            related.add(item["path"])
    if len(related) < MIN_CONTEXT_NODES:
        nearest = sorted((i for i in items if i["path"] not in related), key=lambda i: (_distance_sq(i, focus), i["path"]))
        for item in nearest[: MIN_CONTEXT_NODES - len(related)]:
            related.add(item["path"])

    def right(item: dict) -> float:
        return item["x"] + float(item.get("w") or 0.0)

    def top(item: dict) -> float:
        return item["y"] + float(item.get("h") or 0.0)

    # 注目ノードに近い順（横の距離＋縦の距離）に、幅の上限に収まるぶんだけ入れる
    others = sorted(related - {focus_path}, key=lambda p: abs(by_path[p]["x"] - focus["x"]) + abs(by_path[p]["y"] - focus["y"]))
    shown = [focus_path]
    x0, x1 = focus["x"], right(focus)
    y0, y1 = focus["y"], top(focus)
    for path in others:
        item = by_path[path]
        nx0, nx1 = min(x0, item["x"]), max(x1, right(item))
        if (nx1 - nx0) + 2 * VIEW_PAD_X > max_width:
            continue
        x0, x1 = nx0, nx1
        y0, y1 = min(y0, item["y"]), max(y1, top(item))
        shown.append(path)
    x0, x1, y0, y1 = x0 - VIEW_PAD_X, x1 + VIEW_PAD_X, y0 - VIEW_PAD_Y, y1 + VIEW_PAD_Y
    width, height = x1 - x0, y1 - y0
    width = max(width, min_width)
    # ペインが極端に細い・太い（幅 1px など）ときに、範囲が桁違いに大きくならないよう、縦横比を現実的な幅に収める
    aspect = min(max(aspect, MIN_VIEW_ASPECT), MAX_VIEW_ASPECT) if aspect > 0 else 16 / 9  # 0 以下・NaN は 16:9
    if width / height < aspect:  # ペインの縦横比に合わせる（縦が長いときは横を広げ、横が長いときは縦を広げる）
        width = height * aspect
    else:
        height = width / aspect
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    overlay = min(max(top_overlay, 0.0), 0.4)
    if overlay > 0:
        # 上端の帯（パス欄・メニュー）の下に、ノードが収まるよう、範囲を広げ、上に足す（下端はそのまま）
        bottom = cy - height / 2.0
        scale = 1.0 / (1.0 - overlay)
        cx_width, height = width * scale, height * scale
        bounds = (cx - cx_width / 2.0, bottom, cx + cx_width / 2.0, bottom + height)
        visible_top = bounds[3] - overlay * height
    else:
        bounds = (cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)
        visible_top = bounds[3]
    inside = [
        i["path"] for i in items
        if bounds[0] <= i["x"] <= bounds[2] and bounds[1] <= i["y"] <= visible_top
    ]
    hidden = [i["path"] for i in items if i["path"] not in inside]
    return bounds, inside, hidden


# 実画面が小さいとき（ペインの幅が足りないとき）は、拡大すると画素が粗くなる。この幅より狭いなら、撮るあいだ、ペインを最大化する（maximized_if_narrow）。
PANE_WIDE_ENOUGH_WIDTH = 1000


# ─── 長いコード（VEX など）の読める出し方（2026-11-17。副作用なし） ─────────────────────────────────────────
# 前の動き: パラメータ画面の右の列（幅 480 の論理座標）に、等幅 11pt で、1 行ずつ、はみ出す部分を「…」で切って出していた
#   （長い 1 行は 1365 の幅 → 読める部分は 3 分の 1 だけ）。行数も、画面に収まる分だけで、残りは出ない。
# 後の動き: コードは専用のカード（幅いっぱい・等幅 16pt）に出す。長い行は折り返し（続きの行は、行番号なしの印つき）、
#   画面に収まらない行数は、複数枚に分ける（1 枚目は変更点の一覧と一緒、2 枚目からはコードだけ）。
CODE_FONT_PT = 16.0
CODE_LINE_H = 28.0
CODE_MAX_PAGES = 4
CODE_SCALE_MAX = 1.9  # 行が少ないとき、コードの文字を、最大この倍率まで大きくする
MAX_CODE_CHARS = 200_000  # これより長いコードは、ここで切る（表示できるのは CODE_MAX_PAGES 枚まで。巨大な入力で固まらないため）


def _cols(ch: str) -> int:
    """等幅フォントでの、1 文字の桁数。全角（日本語のコメントなど）は 2 桁。"""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _split_cols(text: str, max_cols: int) -> tuple[str, str]:
    """text の先頭から、max_cols 桁に収まる部分と、残りに分ける。"""
    used = 0
    for index, ch in enumerate(text):
        used += _cols(ch)
        if used > max_cols:
            return text[:index], text[index:]
    return text, ""


def wrap_code_lines(code: str, max_cols: int) -> list[tuple[int | None, str]]:
    """コードを、max_cols 桁で折り返した行の一覧にする。戻り値: [(元の行番号（1 始まり）。折り返しの続きは None, 文字列)]。
    タブは 4 桁の空白にする。全角の文字は 2 桁で数える。続きの行は、元の行の字下げ＋2 桁にする。"""
    rows: list[tuple[int | None, str]] = []
    max_cols = max(10, int(max_cols))
    for number, raw in enumerate(str(code)[:MAX_CODE_CHARS].replace("\r\n", "\n").split("\n"), start=1):
        line = raw.replace("\t", "    ").rstrip()
        head, rest = _split_cols(line, max_cols)
        rows.append((number, head))
        indent = " " * min(len(line) - len(line.lstrip()), max_cols // 3) + "  "
        while rest:
            part, rest = _split_cols(rest, max(8, max_cols - len(indent)))
            rows.append((None, indent + part))
    return rows


def paginate_code(
    rows: list[tuple[int | None, str]], first_capacity: int, other_capacity: int, max_pages: int = CODE_MAX_PAGES
) -> tuple[list[list[tuple[int | None, str]]], int]:
    """行を、ページに分ける。1 枚目は first_capacity 行、2 枚目からは other_capacity 行。
    戻り値: (ページの一覧, 最後のページに入りきらなかった行数)。"""
    first_capacity, other_capacity = max(1, first_capacity), max(1, other_capacity)
    pages: list[list[tuple[int | None, str]]] = []
    index = 0
    while index < len(rows) and len(pages) < max_pages:
        size = first_capacity if not pages else other_capacity
        pages.append(rows[index:index + size])
        index += size
    return pages or [[]], max(0, len(rows) - index)


def extra_page_path(base: Path, page: int) -> Path:
    """複数枚に分けた画像の、2 枚目以降のパス（step_012_network.png → step_012_network_p2.png）。page は 1 始まり。"""
    return base if page <= 1 else base.with_name(f"{base.stem}_p{page}{base.suffix}")


def find_extra_pages(base: Path) -> list[Path]:
    """base（1 枚目）と同じ手順の、2 枚目以降の画像（ページ順）。無ければ空。"""
    found = []
    for path in base.parent.glob(f"{glob.escape(base.stem)}_p*{glob.escape(base.suffix)}"):  # 名前に [ ] などがあっても探せる
        match = re.fullmatch(rf"{re.escape(base.stem)}_p(\d+)", path.stem)
        if match:
            found.append((int(match.group(1)), path))
    return [p for _n, p in sorted(found)]


# ─── 撮影した画像の補足情報（品質チェッカー用。video_script.check_video_quality が読む） ─────────────────────────

def meta_path(image_path: Path) -> Path:
    return image_path.with_name(image_path.name + ".meta.json")


def write_capture_meta(image_path: Path, meta: dict, log_path: Path | None = None) -> None:
    """画像のとなりに、何を描いたかの情報（ノード数・名前の大きさ・コードが切れたか）を書く。失敗しても、撮影は止めない。"""
    try:
        import json

        meta_path(image_path).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        _log(f"write_capture_meta failed: {exc!r}", log_path)


def read_capture_meta(image_path: Path | str) -> dict:
    try:
        import json

        data = json.loads(meta_path(Path(image_path)).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ─── パラメータの置き場所（タブ）を合わせる ──────────────────────────────────────────────────────────

def pick_folder_index(folder_names: list[str], containing_labels: list[str]) -> int | None:
    """フォルダ（タブ）の集まりの中で、対象のパラメータが入っているタブの番号。入っていなければ None。"""
    for label in containing_labels:
        for index, name in enumerate(folder_names):
            if name == label:
                return index
    return None


def tab_path_of(node, parm_name: str) -> str:
    """パラメータが入っているタブ・フォルダの名前を、「A › B」の形で。タブが無い・読めないときは空文字。"""
    try:
        parm = node.parm(parm_name)
        if parm is None:
            tup = node.parmTuple(parm_name)
            parm = tup[0] if tup else None
        if parm is None:
            return ""
        return " › ".join(str(x) for x in parm.containingFolders())
    except Exception:  # noqa: BLE001
        return ""


def reveal_parm_tabs(node, parm_names: list[str], log_path: Path | None = None) -> int:
    """対象のパラメータが入っているタブを、前面にする（パラメータ画面が、別のタブを映していると、変更した項目が写らない）。
    戻り値: 切り替えたタブの数。公式の API（Parm.containingFolderSetParmTuples / containingFolders）を使うが、
    実機では未確認なので、失敗しても、何もせず、ログに残す。"""
    switched = 0
    for name in parm_names:
        try:
            parm = node.parm(name)
            if parm is None:
                tup = node.parmTuple(name)
                parm = tup[0] if tup else None
            if parm is None:
                continue
            labels = [str(x) for x in parm.containingFolders()]
            for folder_set in parm.containingFolderSetParmTuples():
                names = [str(x) for x in folder_set.parmTemplate().folderNames()]
                index = pick_folder_index(names, labels)
                if index is not None and int(folder_set.eval()[0]) != index:
                    folder_set.set((index,))
                    switched += 1
        except Exception as exc:  # noqa: BLE001 -- タブを合わせられなくても、撮影は続ける
            _log(f"reveal_parm_tabs({name}) failed: {exc!r}", log_path)
    return switched


def _displayed_bounds(container_path: str | None, log_path: Path | None):
    """container_path（サンドボックス）の中の、表示中のオブジェクトのジオメトリの境界ボックス（ワールド座標）。
    無い・求められないときは None。"""
    if not container_path:
        return None
    container = hou.node(container_path)
    if container is None:
        return None
    union = None
    for child in container.children():
        try:
            # LOP ネットワーク（solaris）などは isDisplayFlagSet を持たない。ジオメトリの箱ではないので、飛ばす（エラーにしない）
            if child.type().category() != hou.objNodeTypeCategory() or not hasattr(child, "isDisplayFlagSet"):
                continue
            if not child.isDisplayFlagSet():
                continue
            display = child.displayNode()
            geometry = display.geometry() if display is not None else None
            if geometry is None:
                continue
            box = geometry.boundingBox()
            if not box.isValid():
                continue
            world = child.worldTransform()
            lo, hi = box.minvec(), box.maxvec()
            for x in (lo[0], hi[0]):
                for y in (lo[1], hi[1]):
                    for z in (lo[2], hi[2]):
                        corner = hou.Vector3(x, y, z) * world
                        if union is None:
                            union = hou.BoundingBox(corner[0], corner[1], corner[2], corner[0], corner[1], corner[2])
                        else:
                            union.enlargeToContain(corner)
        except Exception as exc:  # noqa: BLE001 -- 1つのノードが読めなくても、他で求める
            _log(f"bounds of {child.path()} failed: {exc!r}", log_path)
    if union is None or not union.isValid():
        return None
    size = union.sizevec()
    if max(size[0], size[1], size[2]) <= 1e-6:
        return None
    return union


def viewport_is_empty(container_path: str | None, log_path: Path | None = None) -> bool:
    """container_path の中で、表示中のオブジェクトのジオメトリが、点を 1 つも持たない（ビューポートに、床の格子しか映らない）か。
    確かに空だと言えるときだけ True（LOP などジオメトリの箱でないものがある・読めないときは、False = 撮る）。
    実機（2026-11-20）: 何も表示されていない手順のビューポート画像が、格子だけの絵になり、動画の画面の約 4 割を占めた。"""
    if not container_path:
        return False
    try:
        container = hou.node(container_path)
        if container is None:
            return False
        seen_object = False
        for child in container.children():
            if child.type().category() != hou.objNodeTypeCategory() or not hasattr(child, "isDisplayFlagSet"):
                return False  # ジオメトリの箱でないもの（LOP など）がある。空とは言えない
            if not child.isDisplayFlagSet():
                continue
            seen_object = True
            display = child.displayNode()
            geometry = display.geometry() if display is not None else None
            if geometry is not None and len(geometry.points()) > 0:
                return False
        return seen_object
    except Exception as exc:  # noqa: BLE001
        _log(f"viewport_is_empty failed: {exc!r}", log_path)
        return False


def fit_zoom(extent_x: float, extent_y: float, margin: float = 0.88) -> float:
    """作ったものを、動画の枠（16:9 の中央の帯）に大きく収めるための、境界ボックスの倍率。
    extent_x: 作ったものの、画面上の幅（ビューポートの幅に対する割合。0〜1）。
    extent_y: 同じく高さ（動画に使う中央の帯の高さに対する割合。_refine_framing が直して渡す）。
    戻り値: いまの構図に対する、境界ボックスの倍率。1 より小さければ寄る（拡大）、大きければ引く（0.5〜_MAX_FRAME_SCALE）。"""
    need = max(extent_x / margin, extent_y / margin) if (extent_x > 0 or extent_y > 0) else 1.0
    return min(max(need, 0.5), _MAX_FRAME_SCALE)


def _refine_framing(viewport, box, pad: float, center, scale: float, log_path: Path | None) -> bool:
    """いったん合わせた構図で、作ったものが、画面の中央の 16:9 の帯に、どれくらいの大きさで映るかを測り、倍率を合わせ直す。
    境界ボックスを一律に広げる方法（frame_scale）では、縦長のペインで、作ったものが小さくなった（動画では、画面の 1 割ほど）。
    hou.GeometryViewport.mapToScreen() が使えないときは、何もしない（False）。"""
    try:
        map_to_screen = getattr(viewport, "mapToScreen", None)
        if map_to_screen is None:
            return False
        size = tuple(viewport.size())
        view_w, view_h = (float(size[-2]), float(size[-1])) if len(size) >= 4 else (float(size[0]), float(size[1]))
        if view_w <= 0 or view_h <= 0:
            return False
        lo, hi = box.minvec(), box.maxvec()
        points = []
        for x in (lo[0], hi[0]):
            for y in (lo[1], hi[1]):
                for z in (lo[2], hi[2]):
                    p = map_to_screen(hou.Vector3(x, y, z))
                    points.append((float(p[0]), float(p[1])))
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        ex, ey = max(xs) - min(xs), max(ys) - min(ys)
        if max(abs(v) for v in xs + ys) > 2.0:  # 画素で返ってきた。割合にする
            ex, ey = ex / view_w, ey / view_h
        band_h = min(1.0, (view_w / OUTPUT_ASPECT) / view_h)  # 動画に使う中央の帯の高さ（ビューポートの高さに対する割合）
        zoom = fit_zoom(ex, ey / band_h)
        _log(f"viewport fit: object spans {ex:.2f} x {ey:.2f} of the view (band height {band_h:.2f}) -> zoom {zoom:.2f}", log_path)
        if abs(zoom - 1.0) < 0.08:
            return True
        half = [(box.sizevec()[i] / 2 + pad) * scale * zoom for i in range(3)]  # いまの構図の倍率（scale）に、測った倍率をかける
        viewport.frameBoundingBox(hou.BoundingBox(
            center[0] - half[0], center[1] - half[1], center[2] - half[2],
            center[0] + half[0], center[1] + half[1], center[2] + half[2]))
        return True
    except Exception as exc:  # noqa: BLE001 -- 測れなければ、一律の倍率のまま
        _log(f"viewport fit failed: {exc!r}", log_path)
        return False


def _frame_view(viewport, container_path: str | None, log_path: Path | None, scale: float = 1.0) -> str:
    """ビューポートを、作ったものに合わせる。使った方法を返す（"bounds" / "all" / ""）。
    scale: 境界ボックスを広げる倍率（縦長のペインを 16:9 に切り出しても、作ったものが欠けないように。1 = そのまま）。"""
    try:
        box = _displayed_bounds(container_path, log_path)
        if box is not None:
            size, center = box.sizevec(), box.center()
            pad = max(size[0], size[1], size[2]) * _FRAME_PADDING
            half = [(size[i] / 2 + pad) * max(1.0, scale) for i in range(3)]
            padded = hou.BoundingBox(
                center[0] - half[0], center[1] - half[1], center[2] - half[2],
                center[0] + half[0], center[1] + half[1], center[2] + half[2],
            )
            viewport.frameBoundingBox(padded)
            if scale > 1.0:  # 縦長のペイン（16:9 に切り出す）。一律に広げた構図を、作ったものの実際の大きさで合わせ直す
                _refine_framing(viewport, box, pad, center, max(1.0, scale), log_path)
            return "bounds"
    except Exception as exc:  # noqa: BLE001
        _log(f"frameBoundingBox failed, falling back to frameAll(): {exc!r}", log_path)
    try:
        viewport.frameAll()
        return "all"
    except Exception as exc:  # noqa: BLE001
        _log(f"frameAll() failed, capturing with current framing: {exc!r}", log_path)
        return ""


def _output_size(viewport, width: int, height: int, log_path: Path | None) -> tuple[int, int]:
    """幅は指定のまま、高さを、ビューポートの縦横比に合わせる（縦横比が違うと、出力で上下・左右が切り落とされる）。
    縦横比が読めない・極端なときは、指定のまま。"""
    try:
        size = tuple(viewport.size())
        view_w, view_h = (size[-2], size[-1]) if len(size) >= 4 else (size[0], size[1])
        aspect = float(view_w) / float(view_h)
        if _MIN_ASPECT <= aspect <= _MAX_ASPECT:
            return width, max(2, int(round(width / aspect / 2.0)) * 2)
    except Exception as exc:  # noqa: BLE001
        _log(f"viewport aspect unavailable, using {width}x{height}: {exc!r}", log_path)
    return width, height


def _view_aspect(viewport) -> float:
    """ビューポートの縦横比（幅 / 高さ）。読めないときは 16:9（= 何も変えない）。"""
    try:
        size = tuple(viewport.size())
        view_w, view_h = (size[-2], size[-1]) if len(size) >= 4 else (size[0], size[1])
        return float(view_w) / float(view_h)
    except Exception:  # noqa: BLE001
        return OUTPUT_ASPECT


# 動画のビューポート画像は 16:9 で使われる。縦長のペインで撮ると、そのまま（例 1920x2132）では、動画の枠に小さく収まり、
# 左右に黒い帯が出ていた（2026-11-18 の動画で確認）。撮った画像は、中央を 16:9 に切り出す。切り出しで作ったものが
# 欠けないよう、撮る前に、作ったものを、その分だけ小さく収める（frame_scale）。
OUTPUT_ASPECT = 16.0 / 9.0
_MAX_FRAME_SCALE = 2.4


def crop_rect_for_aspect(width: int, height: int, aspect: float = OUTPUT_ASPECT) -> tuple[int, int, int, int]:
    """画像の中央を、縦横比 aspect に切り出す矩形 (x, y, w, h)。すでに近い（差が 2% 未満）・大きさが不正なときは、全体。"""
    if width <= 0 or height <= 0 or aspect <= 0:
        return 0, 0, max(0, width), max(0, height)
    current = width / height
    if abs(current - aspect) / aspect < 0.02:
        return 0, 0, width, height
    if current < aspect:  # 縦長: 上下を切る
        new_h = max(2, int(round(width / aspect / 2.0)) * 2)
        new_h = min(new_h, height)
        return 0, (height - new_h) // 2, width, new_h
    new_w = max(2, int(round(height * aspect / 2.0)) * 2)  # 横長: 左右を切る
    new_w = min(new_w, width)
    return (width - new_w) // 2, 0, new_w, height


def frame_scale(view_aspect: float, aspect: float = OUTPUT_ASPECT) -> float:
    """縦長のペインで、16:9 に切り出しても、作ったものが欠けないよう、境界ボックスを広げる倍率（1 以上）。"""
    if view_aspect <= 0 or view_aspect >= aspect:
        return 1.0
    return min(_MAX_FRAME_SCALE, aspect / view_aspect)


def crop_to_aspect(path: Path, aspect: float = OUTPUT_ASPECT, log_path: Path | None = None) -> bool:
    """画像の中央を、縦横比 aspect に切り出して上書きする。切り出した（または、すでに近い）ときは True。"""
    try:
        from PySide6.QtGui import QImage

        image = QImage(str(path))
        if image.isNull():
            return False
        x, y, w, h = crop_rect_for_aspect(image.width(), image.height(), aspect)
        if (w, h) == (image.width(), image.height()):
            return True
        return bool(image.copy(x, y, w, h).save(str(path), "PNG"))
    except Exception as exc:  # noqa: BLE001 -- 撮影は止めない（切り出せなければ、元の画像のまま）
        _log(f"crop_to_aspect failed: {exc!r}", log_path)
        return False


def _isolate_for_capture(frame_path: str | None, log_path: Path | None) -> None:
    """撮る前に、サンドボックス以外のオブジェクトの表示を切る（関係ないものが、ビューポートに重ならないように）。"""
    if not frame_path:
        return
    try:
        turned_off = display_isolation.isolate(hou, [frame_path])
        if turned_off:
            _log("hid other objects before capture: " + ", ".join(turned_off), log_path)
    except Exception as exc:  # noqa: BLE001
        _log(f"display isolation failed: {exc!r}", log_path)


def capture_viewport(
    output_path: Path, width: int = VIEWPORT_WIDTH, height: int = VIEWPORT_HEIGHT, log_path: Path | None = None,
    frame_path: str | None = None, skip_if_empty: bool = False,
) -> bool:
    """
    現在の3Dビューポートを1枚の静止画として output_path に保存する。
    hou.SceneViewer.flipbook()（Houdiniの標準ビューポート書き出しAPI）を
    現在フレームだけの1フレームレンジで呼び出す実装。
    """
    try:
        if skip_if_empty and viewport_is_empty(frame_path, log_path):
            _log("nothing is displayed in the viewport; no still is taken (the node screen is used instead)", log_path)
            return False
        scene_viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if scene_viewer is None:
            _log("no SceneViewer pane found in the current desktop", log_path)
            return False
        # Real-Houdini capture confirmed flipbook() itself works, but
        # without an explicit frame-all the camera keeps whatever framing
        # it happened to have (often near-empty, geometry a tiny speck in
        # a sea of background) -- fit the view to the sandbox's geometry
        # right before capturing. Best-effort: a failed frameAll() still
        # lets the capture proceed with whatever framing was already there.
        viewport = scene_viewer.curViewport()
        _isolate_for_capture(frame_path, log_path)
        method = _frame_view(viewport, frame_path, log_path, frame_scale(_view_aspect(viewport)))
        width, height = _output_size(viewport, width, height, log_path)
        _log(f"viewport framing: {method or 'unchanged'} ({width}x{height})", log_path)
        # hou.FlipbookSettings() is abstract and can't be constructed
        # directly (confirmed via real-Houdini AttributeError: "No
        # constructor defined - class is abstract") -- the documented
        # pattern is to clone the viewer's own current settings via
        # .stash() and mutate the copy.
        settings = scene_viewer.flipbookSettings().stash()
        current_frame = hou.frame()
        settings.frameRange((current_frame, current_frame))
        settings.output(str(output_path))
        settings.outputToMPlay(False)
        settings.resolution((width, height))
        scene_viewer.flipbook(scene_viewer.curViewport(), settings)
        exists = output_path.exists()
        if not exists:
            _log(f"flipbook() returned without raising but no file at {output_path}", log_path)
        else:
            flatten_alpha(output_path, log_path)
            crop_to_aspect(output_path, OUTPUT_ASPECT, log_path)  # 動画で 16:9 の枠に収まるように、中央を切り出す
        return exists
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"viewport capture failed: {exc!r}", log_path)
        return False


# flipbook() の PNG は、背景が透明（アルファつき）。RGB は透明部分で 0 や 255 の無意味な値になっており、アルファを無視して
# 読むと、空が真っ黒・床が真っ白の画像になる（2026-11-06の動画で確認）。撮った直後に、不透明な暗いグレーの上に重ねて保存し直す。
VIEWPORT_BACKGROUND_RGB = (58, 58, 62)


def flatten_alpha(path: Path, log_path: Path | None = None, background: tuple[int, int, int] = VIEWPORT_BACKGROUND_RGB) -> bool:
    """アルファつきの画像を、背景色の上に重ねた不透明な画像として上書きする。アルファが無い・失敗したときは何もしない。戻り値: 書き換えたか。"""
    try:
        from PySide6.QtGui import QColor, QImage, QPainter

        image = QImage(str(path))
        if image.isNull() or not image.hasAlphaChannel():
            return False
        flat = QImage(image.width(), image.height(), QImage.Format_RGB32)
        flat.fill(QColor(*background))
        painter = QPainter(flat)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawImage(0, 0, image)
        painter.end()
        return bool(flat.save(str(path), "PNG"))
    except Exception as exc:  # noqa: BLE001 -- 撮影は止めない
        _log(f"flatten_alpha failed: {exc!r}", log_path)
        return False


def plan_clip(start: float, end: float, max_frames: int = LONG_CLIP_FRAMES) -> dict:
    """再生範囲 [start, end] を、max_frames 枚以内に収める撮影計画（純粋な関数）。
    範囲が長いときは、フレームを間引く（frame_step）。再生 fps は、約10秒になるよう、6〜12の範囲で決める。
    戻り値: {"start", "end", "step", "frames", "fps", "seconds"}。"""
    first = int(round(start))
    total = max(1, int(round(end)) - first + 1)
    step = max(1, -(-total // max(1, max_frames)))  # 切り上げ
    frames = -(-total // step)
    fps = int(min(LONG_CLIP_FPS_MAX, max(LONG_CLIP_FPS_MIN, round(frames / LONG_CLIP_TARGET_SECONDS))))
    return {"start": first, "end": first + (frames - 1) * step, "step": step, "frames": frames, "fps": fps, "seconds": round(frames / fps, 1)}


def playback_range() -> tuple[float, float]:
    """タイムラインの再生範囲（開始, 終了）。読めなければ、現在のフレームだけ。"""
    try:
        rng = hou.playbar.playbackRange()
        return float(rng[0]), float(rng[1])
    except Exception:  # noqa: BLE001
        frame = float(hou.frame())
        return frame, frame


_EMPTY_SIGNATURE = ("empty", 0)


def _has_displayed_object(container_path: str | None) -> bool:
    """container_path の中に、表示フラグが立っているオブジェクトノードがあるか（中身が空でもよい）。"""
    try:
        container = hou.node(container_path) if container_path else None
        if container is None:
            return False
        for child in container.children():
            if child.type().category() == hou.objNodeTypeCategory() and hasattr(child, "isDisplayFlagSet") and child.isDisplayFlagSet():
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _displayed_signature(container_path: str | None, log_path: Path | None) -> tuple | None:
    """表示中のジオメトリの「署名」（境界ボックスと、点の数）。フレームが違うと変わるかを比べるための値。
    表示中のオブジェクトがあるのに中身が空（燃え尽きた・エラー）なら、「空」という署名にする（2026-11-06: 以前は None で、
    燃え尽きたあとのフレームがあるだけで「判定できない」になり、燃える様子の約10秒のクリップが、短い16コマの
    クリップに落ちた）。表示中のオブジェクトが無い・求められないときだけ None。"""
    box = _displayed_bounds(container_path, log_path)
    if box is None:
        return _EMPTY_SIGNATURE if _has_displayed_object(container_path) else None
    count = 0
    try:
        container = hou.node(container_path)
        for child in container.children():
            if child.type().category() == hou.objNodeTypeCategory() and hasattr(child, "isDisplayFlagSet") and child.isDisplayFlagSet():
                display = child.displayNode()
                geometry = display.geometry() if display is not None else None
                if geometry is not None:
                    count += int(geometry.intrinsicValue("pointcount"))
    except Exception:  # noqa: BLE001 -- 点の数が読めなくても、境界ボックスで比べる
        count = -1
    lo, hi = box.minvec(), box.maxvec()
    return (tuple(round(float(v), 3) for v in (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])), count)


def scene_is_animated(container_path: str | None, start: float, end: float, log_path: Path | None = None) -> bool | None:
    """再生範囲の頭・中・終わりで、表示中のジオメトリが変わるか。True=動く / False=動かない / None=判定できない。
    動かない（静的な形状）なら、クリップにしても止まった絵なので、静止画のままにする（撮影の時間も節約できる）。
    調べたあと、フレームは元に戻す。"""
    if end <= start:
        return False
    original = hou.frame()
    try:
        signatures = []
        for frame in (start, (start + end) / 2.0, end):
            hou.setFrame(frame)
            signature = _displayed_signature(container_path, log_path)
            if signature is None:
                return None
            signatures.append(signature)
        return len(set(signatures)) > 1
    except Exception as exc:  # noqa: BLE001
        _log(f"scene_is_animated failed: {exc!r}", log_path)
        return None
    finally:
        try:
            hou.setFrame(original)
        except Exception:  # noqa: BLE001 -- 戻せなくても、判定の結果は返す
            pass


def capture_viewport_clip(
    output_dir: Path,
    base_name: str,
    frame_count: int = 16,
    fps: int = 12,
    width: int = CLIP_WIDTH,
    height: int = CLIP_HEIGHT,
    log_path: Path | None = None,
    frame_path: str | None = None,
    start_frame: float | None = None,
    frame_step: int = 1,
) -> tuple[list[Path], int]:
    """
    現在フレームから frame_count 枚分、ビューポートを連番PNGとして撮影する
    （cook_node 直後専用 -- シミュレーション系ノードが実際に時間経過で
    変化していく様子を、静止画1枚ではなく短いクリップとして見せるため）。

    capture_viewport() と同じ flipbook() 機構を、1フレームではなく複数
    フレームのレンジで呼び出すだけの拡張。解像度・枚数を意図的に低く
    絞ってあるのは、動画側の重量・コスト増を per-step の静止画1枚追加分
    程度に抑えるため（呼び出し元は cook_node のみに限定している）。

    戻り値は (フレームパスのリスト, fps)。失敗時は ([], 0)。
    撮影中に再生ヘッドが動くため、終了後は元のフレームへ必ず戻す。
    """
    try:
        scene_viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if scene_viewer is None:
            _log("no SceneViewer pane found for clip capture", log_path)
            return [], 0
        clip_viewport = scene_viewer.curViewport()
        _isolate_for_capture(frame_path, log_path)
        _frame_view(clip_viewport, frame_path, log_path, frame_scale(_view_aspect(clip_viewport)))
        width, height = _output_size(clip_viewport, width, height, log_path)

        original_frame = hou.frame()
        first_frame = original_frame if start_frame is None else start_frame
        step = max(1, int(frame_step))
        end_frame = first_frame + (frame_count - 1) * step
        output_template = str(output_dir / f"{base_name}.$F4.png")
        try:
            settings = scene_viewer.flipbookSettings().stash()
            settings.frameRange((first_frame, end_frame))
            if step > 1:
                if hasattr(settings, "frameIncrement"):
                    settings.frameIncrement(step)
                else:  # 古いビルド: 間引けないので、同じ枚数を連続フレームで撮る
                    settings.frameRange((first_frame, first_frame + frame_count - 1))
            settings.output(output_template)
            settings.outputToMPlay(False)
            settings.resolution((width, height))
            scene_viewer.flipbook(scene_viewer.curViewport(), settings)
        finally:
            hou.setFrame(original_frame)

        frames = sorted(output_dir.glob(f"{base_name}.*.png"))
        if not frames:
            _log(f"clip flipbook() produced no frames in {output_dir}", log_path)
            return [], 0
        for frame_file in frames:
            flatten_alpha(frame_file, log_path)
            crop_to_aspect(frame_file, OUTPUT_ASPECT, log_path)
        return frames, fps
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"viewport clip capture failed: {exc!r}", log_path)
        return [], 0


_OWN_PANEL_CLASS_HINTS = {"ragchatbotpanel", "tutorialgeneratepanel"}
# このコードベース自身のUIクラス（rag_chatbot.py/tutorial_view.py）の目印。
# 撮影範囲の上に自分のパネルが重なっていないかの判定に使う。


def _is_own_panel_widget(widget) -> bool:
    """widget（またはその親のいずれか）がこのコードベース自身のパネルUIなら True。"""
    current = widget
    for _ in range(50):
        if current is None:
            return False
        if type(current).__name__.lower() in _OWN_PANEL_CLASS_HINTS:
            return True
        current = current.parentWidget()
    return False


def _looks_blank(image) -> bool:
    """QImage がほぼ単色（何も描かれていない・真っ黒・真っ白）なら True。"""
    width, height = image.width(), image.height()
    if width <= 0 or height <= 0:
        return True
    colors = set()
    for gy in range(1, 13):
        for gx in range(1, 21):
            colors.add(image.pixel(gx * width // 21, gy * height // 13))
            if len(colors) > 3:
                return False
    return True


# ─── 画像の余白を切り詰める（2026-11-22）──────────────────────────────────────────────────────────────
# 動画で、実画面のパラメータ・ネットワークが、枠の半分ほどの大きさでしか映らず、文字が読めなかった（実際の動画で確認）。
# 原因: ペインを最大化して撮った（2560x1440 など）画像の、実際の中身（パラメータの行）は、左上の 3 割ほどで、残りは背景の色。
# それを、そのまま枠に縮めて入れていた。背景の色と違う画素の範囲だけを切り出して、枠いっぱいに使う。

CROP_PAD = 24          # 中身の外側に残す余白（画素）
CROP_TOLERANCE = 10    # 背景の色との差（各色 0〜255）がこれ以下なら、背景とみなす
CROP_MIN_FRACTION = 0.92  # 切り出した結果が、元の面積のこれ以上なら、切らない（ほとんど変わらない）


def content_rect(image, pad: int = CROP_PAD, tolerance: int = CROP_TOLERANCE, step: int = 3):
    """背景の色と違う画素が入っている範囲 (x, y, w, h)。背景の色は、画像の四辺で最も多い色。中身が見つからない（単色）ときは None。
    step 画素おきに調べ、見つかった範囲の端を、1 画素ずつ詰める（巨大な画像でも、数十万回の判定で済む）。"""
    from PySide6.QtGui import QImage

    width, height = image.width(), image.height()
    if width <= 0 or height <= 0:
        return None
    img = image.convertToFormat(QImage.Format_RGB32)
    data = memoryview(bytes(img.constBits()))
    stride = img.bytesPerLine()

    def px(x: int, y: int) -> tuple[int, int, int]:
        i = y * stride + x * 4  # Format_RGB32 は、リトルエンディアンで B, G, R, (A)
        return data[i + 2], data[i + 1], data[i]

    border: dict[tuple[int, int, int], int] = {}
    for x in range(0, width, max(1, step * 4)):
        for y in (0, height - 1):
            border[px(x, y)] = border.get(px(x, y), 0) + 1
    for y in range(0, height, max(1, step * 4)):
        for x in (0, width - 1):
            border[px(x, y)] = border.get(px(x, y), 0) + 1
    bg = max(border, key=border.get)

    def differs(x: int, y: int) -> bool:
        r, g, b = px(x, y)
        return abs(r - bg[0]) > tolerance or abs(g - bg[1]) > tolerance or abs(b - bg[2]) > tolerance

    x0, y0, x1, y1 = width, height, -1, -1
    for y in range(0, height, step):
        for x in range(0, width, step):
            if differs(x, y):
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    if x1 < 0:
        return None
    # 標本の間にあった中身の端を、1 画素ずつ詰めて確かめる
    x0 = max(0, x0 - step)
    y0 = max(0, y0 - step)
    x1 = min(width - 1, x1 + step)
    y1 = min(height - 1, y1 + step)
    left = next((x for x in range(x0, x1 + 1) if any(differs(x, y) for y in range(y0, y1 + 1, step))), x0)
    right = next((x for x in range(x1, x0 - 1, -1) if any(differs(x, y) for y in range(y0, y1 + 1, step))), x1)
    top = next((y for y in range(y0, y1 + 1) if any(differs(x, y) for x in range(left, right + 1, step))), y0)
    bottom = next((y for y in range(y1, y0 - 1, -1) if any(differs(x, y) for x in range(left, right + 1, step))), y1)
    rx, ry = max(0, left - pad), max(0, top - pad)
    rw, rh = min(width, right + 1 + pad) - rx, min(height, bottom + 1 + pad) - ry
    return rx, ry, rw, rh


def crop_to_content(image, pad: int = CROP_PAD, min_width: int = 480, min_height: int = 270):
    """image（QImage）の、中身だけを切り出した QImage を返す。ほとんど切れない・中身が無いときは、元の image のまま。
    切り出した結果が、min_width x min_height より小さくなるときは、中心はそのままに、その大きさまで広げる（小さな部品が、拡大されすぎない）。"""
    rect = content_rect(image, pad)
    if rect is None:
        return image
    x, y, w, h = rect
    width, height = image.width(), image.height()
    if w * h >= width * height * CROP_MIN_FRACTION:
        return image
    w2, h2 = max(w, min(min_width, width)), max(h, min(min_height, height))
    cx, cy = x + w / 2, y + h / 2
    x2 = int(min(max(0, cx - w2 / 2), width - w2))
    y2 = int(min(max(0, cy - h2 / 2), height - h2))
    return image.copy(x2, y2, w2, h2)


# パラメータ画面（Parm ペイン）の切り出し。ペインを最大化して撮ると、ラベルと値の欄は、左の 4〜5 割に収まり、残りは、スライダーの
# 線が伸びるだけになる。全体を、変更点の一覧の隣の枠に入れると、文字が半分以下に縮み、読めなかった（2026-11-23 の動画で確認:
# 1918 画素の画像を、約 770 画素の枠に入れていた）。左の、ラベルと値の欄がある範囲だけを残す。
PARM_CROP_MIN_WIDTH = 900
PARM_CROP_FRACTION = 0.5


def crop_parm_pane(image):
    """パラメータ画面の切り出し（QImage）から、ラベルと値の欄がある、左側だけを残した QImage を返す。
    まず、背景だけの余白を切る（crop_to_content）。そのあと、幅が PARM_CROP_MIN_WIDTH より広ければ、
    max(PARM_CROP_MIN_WIDTH, 幅の PARM_CROP_FRACTION) 画素だけ、左から残す。狭い画像は、そのまま。"""
    image = crop_to_content(image)
    keep = min(image.width(), max(PARM_CROP_MIN_WIDTH, int(image.width() * PARM_CROP_FRACTION)))
    if keep >= image.width():
        return image
    return image.copy(0, 0, keep, image.height())


def shrink_saved_image(path: Path, log_path: Path | None = None) -> bool:
    """保存した画像（PNG）の余白を切り詰めて、同じ場所に保存し直す。切ったら True。失敗・切る必要が無いときは False（元のまま）。"""
    try:
        from PySide6.QtGui import QImage

        image = QImage(str(path))
        if image.isNull():
            return False
        cropped = crop_to_content(image)
        if cropped is image or (cropped.width(), cropped.height()) == (image.width(), image.height()):
            return False
        ok = bool(cropped.save(str(path), "PNG"))
        if ok:
            _log(f"cropped {path.name}: {image.width()}x{image.height()} -> {cropped.width()}x{cropped.height()}", log_path)
        return ok
    except Exception as exc:  # noqa: BLE001 -- 切れなくても、元の画像のまま使える
        _log(f"shrink_saved_image failed: {exc!r}", log_path)
        return False


# ─── 実画面を、必ず撮るための準備（2026-11-20）─────────────────────────────────────────────────────────
# 動画に、ネットワーク画面・パラメータ画面の実物が出ていなかった。撮影ログの原因は 2 つ:
#   ① ペインが狭い（612px）と、実画面を拡大するとぼやけるので、描き直した図を使っていた（旧 prefer_diagram。廃止）
#   ② Houdini が、前面のアプリでない（生成を待つあいだ、別のアプリを見ている）と、別のウィンドウが写り込むのを恐れて、撮らなかった
# 直し方: ① ペインを一時的に最大化して、広く撮る（撮ったら、元に戻す）。② Houdini を前面に出す。前面に出せなくても、撮る範囲の最前面が
# 全部 Houdini のウィンドウなら（格子状に調べる）、撮ってよい（別のアプリが重なっていれば、そこは Houdini のウィンドウではないので、撮らない）。

def houdini_is_active() -> bool:
    try:
        from PySide6.QtCore import Qt as QtNamespace
        from PySide6.QtGui import QGuiApplication

        return QGuiApplication.applicationState() == QtNamespace.ApplicationActive
    except Exception:  # noqa: BLE001
        return False


def _force_foreground(hwnd: int) -> None:
    """Windows は、別のアプリが前面にあると、SetForegroundWindow を断る。Alt キーの押下を挟むと、通る（よく知られた方法）。"""
    import sys

    if sys.platform != "win32" or not hwnd:
        return
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(0x12, 0, 0, 0)  # Alt 押す
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.keybd_event(0x12, 0, 2, 0)  # Alt 離す


def bring_houdini_to_front(pane_tab, log_path: Path | None, attempts: int = 8) -> bool:
    """Houdini のウィンドウを前面に出す。出せたか（アプリが Active か）を返す。すでに前面なら、何もしない。"""
    if houdini_is_active():
        return True
    window = None
    try:
        window = pane_tab.qtParentWindow()
    except Exception as exc:  # noqa: BLE001
        _log(f"qtParentWindow() failed: {exc!r}", log_path)
    if window is not None:
        try:
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.activateWindow()
            _force_foreground(int(window.winId()))
        except Exception as exc:  # noqa: BLE001
            _log(f"bringing Houdini to the front failed: {exc!r}", log_path)
    for _ in range(attempts):
        _flush_qt_events()
        if houdini_is_active():
            _log("Houdini was brought to the front", log_path)
            return True
        time.sleep(0.1)
    _log("Houdini could not be brought to the front; relying on the overlap check of the pane", log_path)
    return False


def _wait_for_ui(predicate, timeout: float) -> bool:
    """Houdini / Qt の画面の更新を進めながら、predicate が真になるまで待つ（最大 timeout 秒）。真になったかを返す。
    実機（2026-11-20）: ペインを最大化しても、time.sleep() と processEvents() を回すだけでは、ペインの大きさが変わらなかった
    （最大化したと記録したのに、直後の qtScreenGeometry は 612px のまま）。Houdini の画面の更新は、hou.ui.waitUntil() の中で進む。"""

    def ready() -> bool:
        try:
            return bool(predicate())
        except Exception:  # noqa: BLE001
            return False

    if ready() or timeout <= 0:
        return ready()
    deadline = time.monotonic() + timeout

    def check() -> bool:
        _flush_qt_events()
        return ready() or time.monotonic() >= deadline

    wait_until = getattr(getattr(hou, "ui", None), "waitUntil", None)
    if callable(wait_until):
        try:
            wait_until(check)
        except Exception:  # noqa: BLE001 -- 使えなければ、下の待ち方
            pass
    while not ready() and time.monotonic() < deadline:
        _flush_qt_events()
        time.sleep(0.05)
    return ready()


@contextlib.contextmanager
def maximized_if_narrow(pane_tab, log_path: Path | None, min_width: int = PANE_WIDE_ENOUGH_WIDTH, settle_seconds: float = 2.0):
    """ペインの幅が min_width より狭いとき、撮っているあいだだけ、ペインを最大化する（広い実画面を撮るため）。出るときに、必ず元に戻す。
    最大化できなくても（ペインが無い・浮いている窓など）、そのまま続ける（例外は出さない）。
    幅が実際に広がるまで待ち（settle_seconds まで）、広がらなかったときは、ログに残す（狭いまま撮ることになる）。"""
    pane = None
    changed = False
    width = 0
    try:
        width = int(pane_tab.qtScreenGeometry().width())
        pane = pane_tab.pane()
        if 0 < width < min_width and pane is not None and not pane.isMaximized():
            pane.setIsMaximized(True)
            changed = True
            _flush_qt_events()
            grown = _wait_for_ui(lambda: int(pane_tab.qtScreenGeometry().width()) > width * 1.15, settle_seconds)
            if grown:
                _flush_qt_events()
                _log(f"pane maximized for the capture ({width}px -> {int(pane_tab.qtScreenGeometry().width())}px wide)", log_path)
            else:
                _log(f"WARNING: the pane was maximized but did not get wider (still {width}px); the capture stays narrow", log_path)
    except Exception as exc:  # noqa: BLE001
        _log(f"could not maximize the pane: {exc!r}", log_path)
    try:
        yield
    finally:
        if changed:
            try:
                pane.setIsMaximized(False)
                _flush_qt_events()
                _wait_for_ui(lambda: int(pane_tab.qtScreenGeometry().width()) <= width * 1.15, min(settle_seconds, 1.0))
            except Exception as exc:  # noqa: BLE001
                _log(f"could not restore the pane size: {exc!r}", log_path)


def _grab_with_retry(pane_tab, log_path: Path | None, label: str = "NetworkEditor", attempts: int = 3):
    """実画面の切り出しを、数回やり直す（一時的な重なり・描き直しの途中で、1 回だけ失敗することがあるため。描き直した図は、最後の手段）。"""
    for attempt in range(1, attempts + 1):
        image = _grab_network_pane(pane_tab, log_path, label=label)
        if image is not None:
            return image
        if attempt < attempts:
            _log(f"{label} screen grab failed ({attempt}/{attempts}); trying again", log_path)
            time.sleep(0.4)
            _flush_qt_events()
    _log(f"WARNING: the real {label} screen could not be captured; a drawn image is used instead", log_path)
    return None


def _grab_network_pane(network_editor, log_path: Path | None, label: str = "NetworkEditor"):
    """
    NetworkEditor ペインが「画面上で占めている矩形」を直接切り出して QImage で返す
    （撮れなければ None）。

    2026-09-26: 以前は hou.PaneTab.screenBounds() の値で画面を切り出そうとして、
    それがペイン内部のローカル座標（常に同じ [0,0,613,332]）で使い物にならないため
    断念していた。公式ドキュメントには hou.PaneTab.qtScreenGeometry() が
    「ペインの左上を画面座標で指す QRect」を返すと明記されており、これが本来使うべき
    APIだった（qtWidget() が無いのでウィジェット探索に走ったのが遠回りだった）。
    QScreen.grabWindow() は画面上の矩形をそのままコピーするだけなので、Houdiniの
    ウィジェット階層（実機ログで、hou.qt.mainWindow() やトップレベルウィンドウ列挙が
    Houdini本体を返さないと判明済み）には一切依存しない。

    誤った画像を静かに保存しないための検査:
      ・ペインが小さすぎる（折りたたみ・非表示）→ 撮らない
      ・矩形の中心に自分のRAGChatBotパネルが重なっている → 撮らない
      ・切り出し結果がほぼ単色 → 撮らない
    いずれも None を返し、呼び出し側が自前描画のダイアグラムにフォールバックする。
    """
    geometry_fn = getattr(network_editor, "qtScreenGeometry", None)
    if geometry_fn is None:
        _log("qtScreenGeometry() is not available on this Houdini build", log_path)
        return None

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    rect = geometry_fn()
    x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
    _log(f"{label} qtScreenGeometry: ({x},{y},{w},{h})", log_path)
    if w < 200 or h < 120:
        _log(f"{label} pane is too small to capture (hidden or collapsed?)", log_path)
        return None

    # 画面切り出しは「今画面に見えているもの」をそのままコピーするため、Houdini以外の
    # アプリ（ブラウザ等）が手前に来ているとそれが映ってしまい、しかもウィジェット側からは
    # 検知できない。アプリがアクティブでない間は撮らず、自前描画の図に任せる。
    # Houdini が前面でなくても、撮る範囲の最前面が全部 Houdini のウィンドウなら撮れる（下の格子の検査）。まず、前面に出す。
    bring_houdini_to_front(network_editor, log_path)

    center = QPoint(x + w // 2, y + h // 2)
    screen = QGuiApplication.screenAt(center)
    if screen is None:
        _log(f"no screen contains the pane center ({center.x()},{center.y()})", log_path)
        return None
    # ペインの矩形の中を格子状に調べ、最前面が全部「同じトップレベルウィンドウ」であることを
    # 確かめる。中心1点だけだと、ペインの一部だけに被さるウィンドウ（Houdini Consoleなど）を
    # 見逃す（実機で、コンソールが下半分に写り込んだ）。他アプリ・別ウィンドウ・自分のパネルの
    # いずれかが被っていれば撮らず、自前描画の図に任せる。
    top_windows = set()
    for fx in (0.08, 0.3, 0.5, 0.7, 0.92):
        for fy in (0.1, 0.35, 0.6, 0.9):
            point = QPoint(x + int(w * fx), y + int(h * fy))
            covering = QApplication.widgetAt(point)
            if covering is None:
                _log("something outside Houdini covers part of the pane; not grabbing the screen", log_path)
                return None
            if _is_own_panel_widget(covering):
                _log(f"the RAGChatBot panel overlaps the {label} pane on screen; not grabbing it", log_path)
                return None
            top_windows.add(id(covering.window()))
    if len(top_windows) != 1:
        _log("another window (e.g. the Houdini Console) overlaps the pane; not grabbing the screen", log_path)
        return None

    origin = screen.geometry().topLeft()
    image = screen.grabWindow(0, x - origin.x(), y - origin.y(), w, h).toImage()
    if _looks_blank(image):
        _log(f"the grabbed {label} region is blank", log_path)
        return None
    return image


# ─── 自前描画のネットワーク図（実画面が撮れない場合のフォールバック） ──────────────────

_MAX_DIAGRAM_NODES = 60
# 注目ノードの図は、ネットワークの全ノードから、注目ノードの前後だけを選ぶ（select_focus_nodes）。先頭の 60 個だけを読むと、
# 61 個目以降のノードに注目する手順で、注目ノードが図に出ない。選ぶ前のノード数の上限（座標・接続を読む時間の上限）。
_MAX_FOCUS_MODEL_NODES = 500


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 -- 図の描画は情報が欠けても続行する
        return default


def _collect_network_model(network, limit: int = _MAX_DIAGRAM_NODES) -> list[dict]:
    """ネットワーク直下のノード（名前・タイプ・色・フラグ・入力接続・元の座標）を集める。limit 個まで。"""
    children = list(network.children())[:limit]
    known = {c.path() for c in children}
    model = []
    for c in children:
        position = _safe(lambda: c.position(), None)
        entry = {
            "path": c.path(),
            "name": c.name(),
            "type": _safe(lambda: c.type().name(), ""),
            "color": _safe(lambda: tuple(c.color().rgb()), (0.8, 0.8, 0.8)),
            "display": bool(_safe(lambda: c.isDisplayFlagSet(), False)),
            "render": bool(_safe(lambda: c.isRenderFlagSet(), False)),
            "bypass": bool(_safe(lambda: c.isBypassed(), False)),
            "error": bool(_safe(lambda: c.errors(), ())),
            "x": float(position[0]) if position is not None else 0.0,
            "y": float(position[1]) if position is not None else 0.0,  # 位置の近いノードを、注目ノードの周りに足すため（2026-11-23）
            "inputs": [],
        }
        for connection in _safe(lambda: c.inputConnections(), ()):
            source = _safe(lambda: connection.inputNode(), None)
            if source is not None and source.path() in known:
                entry["inputs"].append((source.path(), int(connection.inputIndex())))
        model.append(entry)
    return model


def _assign_layers(model: list[dict]) -> list[list[dict]]:
    """接続の向き（上流→下流）に沿って上から下へ段（レイヤー）に分け、各段の左右順を決める。"""
    layer = {n["path"]: 0 for n in model}
    for _ in range(len(model) + 1):
        changed = False
        for n in model:
            for source_path, _idx in n["inputs"]:
                if layer[n["path"]] < layer[source_path] + 1:
                    layer[n["path"]] = layer[source_path] + 1
                    changed = True
        if not changed:
            break

    layers: list[list[dict]] = []
    for depth in range(max(layer.values(), default=0) + 1):
        layers.append([n for n in model if layer[n["path"]] == depth])

    order: dict[str, float] = {}
    for depth, members in enumerate(layers):
        def sort_key(n, _order=order):
            parent_positions = [_order[p] for p, _ in n["inputs"] if p in _order]
            barycenter = sum(parent_positions) / len(parent_positions) if parent_positions else 0.0
            return (barycenter, n["x"], n["name"])

        members.sort(key=sort_key)
        for index, n in enumerate(members):
            order[n["path"]] = float(index)
    return layers


def _short_callout(text: str | None) -> str:
    """ツール結果テキストを、図の中に添える短いラベルに要約する。"""
    if not text:
        return ""
    first = text.strip().splitlines()[0] if text.strip() else ""
    if first.startswith("作成しました"):
        return "NEW"
    if first.startswith("cook 成功"):
        return "cook OK"
    if first.startswith("cook 結果"):
        return "cook: エラー/警告あり"
    if first.startswith("接続しました"):
        return ""
    match = re.match(r"^\S+\.(\w+) = (.+)$", first)
    if match:
        return f"{match.group(1)} = {match.group(2)}"[:60]
    return first[:40]


def _paint_network_diagram(
    layers, container_path, focus_path, callout, width, height, hidden: int = 0, total: int = 0,
    min_scale: float = MIN_FOCUS_SCALE, meta_out: dict | None = None, reserve_right: float = 0.0,
):
    """Houdiniのネットワークエディタ風のダーク配色で、上→下の流れの図を QImage に描く。
    hidden / total: 読める大きさを守るために省いたノードの数 / 元のノード数（上の帯に書く）。
    min_scale: 拡大率の下限（注目ノードの図は MIN_FOCUS_SCALE。全体図は OVERVIEW_MIN_SCALE）。
    meta_out: 渡すと、描いた内容（ノード数・名前の大きさ）を書き込む（品質チェッカー用）。
    reserve_right: 右端に空ける幅（論理座標）。全体の小さな図（paint_overview_inset）を置くとき、近場の図がそこに重ならないようにする。"""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import (
        QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen,
    )

    image = QImage(width * RENDER_SCALE, height * RENDER_SCALE, QImage.Format_ARGB32)
    image.fill(QColor("#2f2f31"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.scale(RENDER_SCALE, RENDER_SCALE)  # 座標は width x height のまま、画素だけ細かくする

    # 背景の格子点（Houdiniのネットワークエディタの雰囲気）
    painter.setPen(QPen(QColor("#3b3b3e"), 2))
    for gx in range(20, width, 40):
        for gy in range(64, height, 40):
            painter.drawPoint(gx, gy)

    # 上部のパスバー
    painter.fillRect(QRectF(0, 0, width, 40), QColor("#232325"))
    painter.setPen(QColor("#c9c9cc"))
    bar_font = QFont("Segoe UI", 12)
    bar_font.setBold(True)
    painter.setFont(bar_font)
    painter.drawText(QRectF(16, 0, width - 32, 40), Qt.AlignVCenter | Qt.AlignLeft, container_path)

    name_font = QFont("Segoe UI")
    name_font.setPointSizeF(DIAGRAM_NAME_PT)
    name_font.setBold(True)
    type_font = QFont("Segoe UI")
    type_font.setPointSizeF(DIAGRAM_TYPE_PT)
    tag_font = QFont("Segoe UI", 12)
    tag_font.setBold(True)
    name_metrics = QFontMetricsF(name_font)

    box_h, gap_x, gap_y = DIAGRAM_BOX_H, DIAGRAM_GAP_X, DIAGRAM_GAP_Y

    def width_of(n):
        return diagram_node_width(n["name"], name_metrics.horizontalAdvance(n["name"]))

    rows = [[width_of(n) for n in members] for members in layers]

    if not layers or not any(layers):
        painter.setPen(QColor("#8d8d92"))
        painter.setFont(bar_font)
        painter.drawText(QRectF(0, 40, width, height - 40), Qt.AlignCenter, "(このネットワークにはまだノードがありません)")
        painter.end()
        return image

    layout_w, layout_h, row_widths = layout_extent(layers, width_of)
    # 以前は、拡大率の下限が 0.35 で、40 ノードの一本道だと、名前は 3.85pt になり、図が画面の高さを超えて、はみ出した。
    usable_w = max(1.0, width - reserve_right)  # 図を置ける幅（右端に、全体の小さな図を置くときは、その分を除く）
    scale, fits = diagram_scale(layout_w, layout_h, int(usable_w), height, min_scale)
    node_count = sum(len(members) for members in layers)
    if meta_out is not None:
        meta_out.update({
            "kind": "node_diagram", "nodes_shown": node_count, "nodes_total": total or node_count,
            "scale": round(scale, 3), "name_pt": round(DIAGRAM_NAME_PT * scale, 1), "fits": bool(fits),
            "overview": focus_path is None, "readable": DIAGRAM_NAME_PT * scale >= MIN_NAME_PT,
        })
    offset_x = (usable_w - layout_w * scale) / 2.0
    offset_y = DIAGRAM_BAR_H + (height - DIAGRAM_BAR_H - layout_h * scale) / 2.0
    if hidden > 0:
        painter.setPen(QColor("#ffb000"))
        note_font = QFont("Segoe UI", 11)
        painter.setFont(note_font)
        painter.drawText(QRectF(width * 0.45, 0, width * 0.55 - 16, 40), Qt.AlignVCenter | Qt.AlignRight,
                         f"表示 {node_count}/{total or node_count} ノード（ほか {hidden} 個は省略）")
    painter.translate(offset_x, offset_y)
    painter.scale(scale, scale)

    rects: dict[str, QRectF] = {}
    for depth, members in enumerate(layers):
        start_x = (layout_w - row_widths[depth]) / 2.0
        y = depth * (box_h + gap_y)
        cursor = start_x
        for n, w in zip(members, rows[depth]):
            rects[n["path"]] = QRectF(cursor, y, w, box_h)
            cursor += w + gap_x

    # 接続線（下流ノードの上辺の入力スロットへ、上流ノードの下辺中央から）
    painter.setBrush(Qt.NoBrush)
    wire_pen = QPen(QColor("#a7a7ab"), 2.2)
    painter.setPen(wire_pen)
    for members in layers:
        for n in members:
            dest = rects[n["path"]]
            slots = max([idx for _, idx in n["inputs"]] + [0]) + 1
            for source_path, input_index in n["inputs"]:
                src = rects[source_path]
                x1, y1 = src.center().x(), src.bottom()
                x2 = dest.left() + dest.width() * (input_index + 0.5) / max(slots, 1)
                y2 = dest.top()
                dy = max(24.0, abs(y2 - y1) * 0.45)
                path = QPainterPath(QPointF(x1, y1))
                path.cubicTo(QPointF(x1, y1 + dy), QPointF(x2, y2 - dy), QPointF(x2, y2))
                painter.drawPath(path)

    # ノード本体
    for members in layers:
        for n in members:
            rect = rects[n["path"]]
            r, g, b = (max(0.0, min(1.0, float(c))) for c in n["color"])
            fill = QColor.fromRgbF(r, g, b)
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            is_focus = focus_path is not None and n["path"] == focus_path
            if is_focus:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 176, 0, 70))
                painter.drawRoundedRect(rect.adjusted(-7, -7, 7, 7), 9, 9)
            painter.setPen(QPen(QColor("#ffb000") if is_focus else QColor("#141416"), 3.0 if is_focus else 1.4))
            painter.setBrush(fill.darker(150) if n["bypass"] else fill)
            painter.drawRoundedRect(rect, 6, 6)
            if n["error"]:
                painter.setPen(QPen(QColor("#e5484d"), 3.0))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 8, 8)

            # ノード名（上段）とタイプ名（下段）を箱の中に収める。箱の外に書くと、下流へ
            # 伸びる接続線と文字が重なって読めなくなる。
            dark_text = luminance > 0.55
            painter.setFont(name_font)
            painter.setPen(QColor("#1b1b1d") if dark_text else QColor("#f2f2f4"))
            painter.drawText(QRectF(rect.left(), rect.top() + 5, rect.width(), 28), Qt.AlignCenter, n["name"])

            if scale >= 0.5:  # 全体図で小さくなるときは、名前だけにする（タイプ名は、読めない大きさになる）
                painter.setFont(type_font)
                painter.setPen(QColor("#55555b") if dark_text else QColor("#b9b9bf"))
                painter.drawText(QRectF(rect.left(), rect.top() + 33, rect.width(), 18), Qt.AlignCenter, n["type"])

            # フラグ（Houdiniは右側に表示: 青=display / 紫=render）
            flag_x = rect.right() + 8
            for is_set, color in ((n["display"], "#4aa3ff"), (n["render"], "#b57bff")):
                if is_set:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(color))
                    painter.drawEllipse(QPointF(flag_x, rect.center().y()), 6, 6)
                    flag_x += 16

    # 直近の操作の要点（パラメータ変更・cook結果・新規作成）を対象ノードの脇に添える
    label = _short_callout(callout)
    focus_rect = rects.get(focus_path) if focus_path else None
    if label and focus_rect is not None:
        painter.setFont(tag_font)
        tag_w = QFontMetricsF(tag_font).horizontalAdvance(label) + 24.0
        mid_y = focus_rect.center().y() - 15
        # 札の置き場所: 右 → 左 → 上 → 下の順に、画面に収まり、ほかのノードと重ならない所を選ぶ（周りのノードを入れたので、
        # 左に置くと、隣のノードの名前に重なった。2026-11-23）。どこも合わなければ、従来どおり（右。収まらなければ左）。
        candidates = [
            QRectF(focus_rect.right() + 40, mid_y, tag_w, 30),
            QRectF(focus_rect.left() - 40 - tag_w, mid_y, tag_w, 30),
            QRectF(focus_rect.center().x() - tag_w / 2, focus_rect.top() - 50, tag_w, 30),
            QRectF(focus_rect.center().x() - tag_w / 2, focus_rect.bottom() + 20, tag_w, 30),
        ]
        others = [r.adjusted(-10, -10, 10, 10) for path, r in rects.items() if path != focus_path]
        to_screen = painter.transform()

        def on_screen(rect) -> bool:
            # to_screen は、画素（論理座標の RENDER_SCALE 倍）への変換。上の帯・端との比較は、論理座標でする
            top_left_px, bottom_right_px = to_screen.map(rect.topLeft()), to_screen.map(rect.bottomRight())
            left, top = top_left_px.x() / RENDER_SCALE, top_left_px.y() / RENDER_SCALE
            right, bottom = bottom_right_px.x() / RENDER_SCALE, bottom_right_px.y() / RENDER_SCALE
            return left >= 8 and right <= usable_w - 8 and top >= DIAGRAM_BAR_H and bottom <= height - 8

        tag_rect = next((c for c in candidates if on_screen(c) and not any(c.intersects(o) for o in others)), None)
        if tag_rect is None:
            tag_rect = next((c for c in candidates[:2] if on_screen(c)), candidates[0])
        painter.setPen(QPen(QColor("#ffb000"), 1.6))
        painter.setBrush(QColor("#1e1e20"))
        painter.drawRoundedRect(tag_rect, 6, 6)
        painter.setPen(QColor("#ffd27a"))
        painter.drawText(tag_rect, Qt.AlignCenter, label)

    painter.end()
    return image


# ─── 近場の図に添える、全体の小さな図（2026-11-23）────────────────────────────────────────────────────────
# 実際の動画で、近場の図（注目ノードと周り）だけでは、ネットワーク全体の中のどこかが分からなかった。「全体用」と「近場用」を分け、
# 近場の図を大きく（名前を読める大きさで）、全体は、右上の小さな図で添える（注目ノードを強調）。全体の名前は読めなくてよい（構成と位置が分かればよい）。
INSET_WIDTH_FRACTION = 0.27
INSET_HEIGHT_FRACTION = 0.36
INSET_MARGIN = 16.0
INSET_TITLE_H = 24.0
INSET_MIN_NODES = 4        # 全体のノード数がこれ未満なら、近場の図に全部が入るので、添えない
INSET_NAME_MIN_PT = 7.0    # 小さな図でも、名前がこの大きさ以上なら書く（それ未満は、読めないので書かない）


def overview_inset_width(width: int) -> float:
    """全体の小さな図に使う、右端の幅（論理座標。余白を含む）。近場の図は、この分を空けて描く（reserve_right）。"""
    return width * INSET_WIDTH_FRACTION + INSET_MARGIN


def paint_overview_inset(image, model: list[dict], focus_path: str | None, width: int = LOGICAL_WIDTH, height: int = LOGICAL_HEIGHT) -> dict:
    """image（QImage。論理座標 width x height を RENDER_SCALE 倍の画素で描いたもの）の右上に、ネットワーク全体の小さな図を描き足す。
    戻り値: 描いた内容の要約（meta 用）。ノードが INSET_MIN_NODES 個未満・描けないときは {}。"""
    if len(model) < INSET_MIN_NODES:
        return {}
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

    box_w, box_h = width * INSET_WIDTH_FRACTION, height * INSET_HEIGHT_FRACTION
    x0, y0 = width - box_w - INSET_MARGIN, DIAGRAM_BAR_H + 12.0
    layers = _assign_layers(model)
    node_w = DIAGRAM_BOX_MIN_W
    layout_w, layout_h, row_widths = layout_extent(layers, lambda _n: node_w)
    area = QRectF(x0 + 12, y0 + INSET_TITLE_H + 6, box_w - 24, box_h - INSET_TITLE_H - 18)
    if layout_w <= 0 or layout_h <= 0 or area.width() <= 0 or area.height() <= 0:
        return {}
    scale = min(area.width() / layout_w, area.height() / layout_h, 0.8)
    offset_x = area.x() + (area.width() - layout_w * scale) / 2.0
    offset_y = area.y() + (area.height() - layout_h * scale) / 2.0

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.scale(RENDER_SCALE, RENDER_SCALE)
        painter.setPen(QPen(QColor("#4a4a4f"), 1.2))
        painter.setBrush(QColor(28, 28, 30, 235))
        painter.drawRoundedRect(QRectF(x0, y0, box_w, box_h), 8, 8)
        title_font = QFont("Segoe UI", 10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#ffb000"))
        painter.drawText(QRectF(x0 + 12, y0 + 2, box_w - 24, INSET_TITLE_H), Qt.AlignVCenter | Qt.AlignLeft, f"全体（{len(model)} ノード）")

        rects: dict[str, QRectF] = {}
        for depth, members in enumerate(layers):
            cursor = offset_x + (layout_w - row_widths[depth]) * scale / 2.0
            y = offset_y + depth * (DIAGRAM_BOX_H + DIAGRAM_GAP_Y) * scale
            for n in members:
                rects[n["path"]] = QRectF(cursor, y, node_w * scale, DIAGRAM_BOX_H * scale)
                cursor += (node_w + DIAGRAM_GAP_X) * scale
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#8d8d92"), 1.0))
        for n in model:
            dest = rects.get(n["path"])
            for source_path, _idx in n["inputs"]:
                src = rects.get(source_path)
                if src is not None and dest is not None:
                    painter.drawLine(QPointF(src.center().x(), src.bottom()), QPointF(dest.center().x(), dest.top()))

        name_pt = DIAGRAM_NAME_PT * scale
        name_font = QFont("Segoe UI")
        name_font.setPointSizeF(max(1.0, name_pt))
        name_font.setBold(True)
        metrics = QFontMetricsF(name_font)
        show_names = name_pt >= INSET_NAME_MIN_PT
        for n in model:
            rect = rects.get(n["path"])
            if rect is None:
                continue
            r, g, b = (max(0.0, min(1.0, float(c))) for c in n.get("color", (0.8, 0.8, 0.8)))
            is_focus = focus_path is not None and n["path"] == focus_path
            if is_focus:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 176, 0, 90))
                painter.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 5, 5)
            painter.setPen(QPen(QColor("#ffb000") if is_focus else QColor("#141416"), 2.2 if is_focus else 1.0))
            painter.setBrush(QColor.fromRgbF(r, g, b))
            painter.drawRoundedRect(rect, 3, 3)
            if show_names:
                painter.setFont(name_font)
                luminance = 0.299 * r + 0.587 * g + 0.114 * b
                painter.setPen(QColor("#1b1b1d") if luminance > 0.55 else QColor("#f2f2f4"))
                painter.drawText(rect, Qt.AlignCenter, _fit_text(metrics, n["name"], rect.width() - 4))
    finally:
        painter.end()
    return {"overview_inset": True, "inset_nodes": len(model), "inset_names": bool(show_names)}


def render_network_diagram(
    output_path: Path,
    container_path: str | None,
    focus_path: str | None = None,
    callout: str | None = None,
    width: int = 1280,
    height: int = 720,
    log_path: Path | None = None,
) -> bool:
    """
    container_path のネットワーク直下のノード構成を、Houdiniのネットワークエディタ風の図として
    output_path に描く（ベストエフォート、失敗時は False）。

    2026-11-23: 注目ノード（focus_path）の図は、近場（注目ノードと周り。名前を読める大きさ）を大きく描き、近場に入りきらないノードがあるときは、
    右上に、全体の小さな図（paint_overview_inset）を添える。「全体用」と「近場用」を、1 枚の中で分ける。

    実画面のキャプチャ（_grab_network_pane）が成立しない環境でも、ノード画面を確実に
    動画素材として出すためのフォールバック。実画面と違い、hou のデータから描き直した
    「図」であること、そのぶんレイアウトが安定して読みやすく、対象ノードを強調できることが
    特徴（ノード位置が重なる・画面外に出るといった実画面固有の問題が起きない）。
    """
    try:
        network = hou.node(container_path) if container_path else None
        if network is None:
            _log(f"render_network_diagram: network not found: {container_path}", log_path)
            return False
        model = _collect_network_model(network, _MAX_FOCUS_MODEL_NODES if focus_path else _MAX_DIAGRAM_NODES)
        # 注目ノードと、その前後だけを、読める大きさで描く（ノードが多くても、名前の大きさの下限 MIN_NAME_PT を守る）。
        # 注目ノードが分からないとき（None）は、全部を描く（全体図）。
        shown, hidden = select_focus_nodes(model, focus_path, width, height)
        reserve = 0.0
        if focus_path and hidden > 0 and len(model) >= INSET_MIN_NODES:
            # 近場に入りきらないノードがある。右上に全体の小さな図を置くので、その分を空けて、近場を選び直す（名前の大きさの下限は守る）
            reserve = overview_inset_width(width)
            shown, hidden = select_focus_nodes(model, focus_path, int(width - reserve), height)
        layers = _assign_layers(shown)
        meta: dict = {}
        image = _paint_network_diagram(
            layers, container_path, focus_path, callout, width, height, hidden=hidden, total=len(model),
            min_scale=MIN_FOCUS_SCALE if focus_path else OVERVIEW_MIN_SCALE, meta_out=meta, reserve_right=reserve,
        )
        if reserve > 0:
            meta.update(paint_overview_inset(image, model, focus_path, width, height))
        if not image.save(str(output_path), "PNG"):
            _log(f"render_network_diagram: image.save() returned False for {output_path}", log_path)
            return False
        meta.update({"width": image.width(), "height": image.height()})
        write_capture_meta(output_path, meta, log_path)
        _log(
            f"network capture method: synthetic diagram ({container_path}; {len(shown)}/{len(model)} nodes, "
            f"name {meta.get('name_pt', '?')}pt)", log_path,
        )
        return True
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"render_network_diagram failed: {exc!r}", log_path)
        return False


def render_graph_diagram(
    graph: dict,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    log_path: Path | None = None,
) -> bool:
    """保存済みのノードグラフ（NodeGraphAsset形式の dict）から、ノードの関係図を output_path に描く。

    hou のノードを読まないので、サンドボックスを消したあとでも描ける。動画の説明スライド
    （考え方・全体の流れなど）に、ぼやけた空の板の代わりに出す。失敗時は False（例外は投げない）。"""
    try:
        from graph_diagram import graph_to_model

        label, model = graph_to_model(graph or {})
        if not model:
            _log("render_graph_diagram: the graph has no nodes", log_path)
            return False
        layers = _assign_layers(model)
        meta: dict = {}
        # 全体図（章の冒頭・構成の説明に 1 枚だけ使う）。全ノードを入れる。多いと名前は小さくなるが、画面の外にははみ出さない。
        image = _paint_network_diagram(
            layers, label or "ノードの関係図", None, None, width, height, total=len(model),
            min_scale=OVERVIEW_MIN_SCALE, meta_out=meta,
        )
        if not image.save(str(output_path), "PNG"):
            _log(f"render_graph_diagram: image.save() returned False for {output_path}", log_path)
            return False
        meta.update({"width": image.width(), "height": image.height()})
        write_capture_meta(output_path, meta, log_path)
        _log(f"node diagram rendered from the saved graph ({len(model)} nodes)", log_path)
        return True
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"render_graph_diagram failed: {exc!r}", log_path)
        return False


def _fit_text(metrics, text: str, max_width: float) -> str:
    """max_width に収まるよう、末尾を…で省略した文字列を返す。"""
    if metrics.horizontalAdvance(text) <= max_width:
        return text
    while len(text) > 1 and metrics.horizontalAdvance(text + "…") > max_width:
        text = text[:-1]
    return text + "…"


PARAM_SCALE_MAX = 1.8  # 変更が少ないとき、パラメータのカードの文字・行を、最大この倍率まで大きくする


def param_card_scale(plain_count: int, has_code: bool = False, has_others: bool = False, height: float = LOGICAL_HEIGHT) -> float:
    """パラメータのカードの、全体の拡大率（1.0 以上、PARAM_SCALE_MAX 以下）。変更が 1〜3 行だと、カードの上のほうに小さく出て、
    下が空いていた（2026-11-18 の動画で確認）。コードの欄・「その他の設定」があるカードは、そのまま（1.0）。"""
    if has_code or has_others or plain_count <= 0:
        return 1.0
    content = 134.0 + 32.0 + min(plain_count, 8) * 56.0 + 20.0
    return max(1.0, min(PARAM_SCALE_MAX, (height - 30.0) / content))


def render_parameter_card(
    output_path: Path,
    container_path: str,
    node_name: str,
    node_type_label: str,
    changes: list[dict],
    others: list[tuple[str, str]] | None = None,
    width: int = 1280,
    height: int = 720,
    log_path: Path | None = None,
) -> bool:
    """
    「このノードのどのパラメータを、いくつからいくつに変えたか」を、Houdiniのパラメータ
    エディタ風のカードとして描く（動画のスライド用、2026-10-04追加）。

    changes: [{"label": "Size X", "name": "sizex", "old": "1", "new": "0.15", "code": False}, ...]
    コード欄（VEXのsnippet等、"code": True）は等幅フォントのコードブロックで見せる。
    others: 変更済みだがこのステップの対象ではないパラメータ（label, value）。淡く下に添える。

    実画面のパラメータペインは、どのパラメータを変えたかを示せず、他のウィンドウの
    重なりや折りたたみでも崩れる。描き直した図なら、変更点を強調でき、毎回同じ品質になる。
    """
    try:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen

        has_code = any(c.get("code") for c in changes)
        zoom = param_card_scale(sum(1 for c in changes if not c.get("code")), has_code, bool(others), height)
        image = QImage(width * RENDER_SCALE, height * RENDER_SCALE, QImage.Format_ARGB32)
        image.fill(QColor("#2f2f31"))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.scale(RENDER_SCALE * zoom, RENDER_SCALE * zoom)  # 座標は、（width / zoom）x（height / zoom）。画素は細かく、全体を大きくする
        width, height = width / zoom, height / zoom

        bar_font = QFont("Segoe UI", 12)
        bar_font.setBold(True)
        p.fillRect(QRectF(0, 0, width, 40), QColor("#232325"))
        p.setPen(QColor("#c9c9cc"))
        p.setFont(bar_font)
        p.drawText(QRectF(16, 0, width - 32, 40), Qt.AlignVCenter | Qt.AlignLeft, f"{container_path}  ›  {node_name}")

        title_font = QFont("Segoe UI", 22)
        title_font.setBold(True)
        sub_font = QFont("Segoe UI", 12)
        p.setFont(sub_font)
        p.setPen(QColor("#9a9aa0"))
        p.drawText(QRectF(40, 56, width - 80, 24), Qt.AlignVCenter | Qt.AlignLeft, node_type_label)
        p.setFont(title_font)
        p.setPen(QColor("#f2f2f4"))
        p.drawText(QRectF(40, 78, width - 80, 40), Qt.AlignVCenter | Qt.AlignLeft, node_name)

        label_font = QFont("Segoe UI", 17)
        label_font.setBold(True)
        name_font = QFont("Consolas", 11)
        value_font = QFont("Segoe UI", 18)
        value_font.setBold(True)
        old_font = QFont("Segoe UI", 15)
        code_font = QFont("Consolas", 12)
        section_font = QFont("Segoe UI", 11)
        section_font.setBold(True)

        y = 134.0
        p.setFont(section_font)
        p.setPen(QColor("#ffb000"))
        p.drawText(QRectF(40, y, width - 80, 22), Qt.AlignVCenter | Qt.AlignLeft, "変更したパラメータ")
        y += 32

        code_changes = [c for c in changes if c.get("code")]
        all_plain = [c for c in changes if not c.get("code")]
        plain_changes = all_plain[:8]
        row_h = 56.0
        label_w = 330.0
        value_x = 40 + label_w + 24
        for c in plain_changes:
            row = QRectF(40, y, width - 80, row_h - 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 176, 0, 34))
            p.drawRoundedRect(row, 8, 8)
            p.setPen(QPen(QColor("#ffb000"), 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(row, 8, 8)

            # ラベル（Houdiniの画面と同じ表示名）と内部名を、行の中で上下に分けて重ならないように置く
            p.setFont(label_font)
            p.setPen(QColor("#f2f2f4"))
            p.drawText(QRectF(56, y + 2, label_w - 20, 26), Qt.AlignVCenter | Qt.AlignLeft,
                       _fit_text(QFontMetricsF(label_font), c.get("label", c.get("name", "")), label_w - 20))
            p.setFont(name_font)
            p.setPen(QColor("#8d8d92"))
            p.drawText(QRectF(56, y + 27, label_w - 20, 16), Qt.AlignVCenter | Qt.AlignLeft,
                       _fit_text(QFontMetricsF(name_font), (f"{c['tab']}  " if c.get("tab") else "") + f"({c.get('name', '')})", label_w - 20))

            old, new = str(c.get("old", "")), str(c.get("new", ""))
            cursor = value_x
            if old and old != new:
                p.setFont(old_font)
                p.setPen(QColor("#8d8d92"))
                old_text = _fit_text(QFontMetricsF(old_font), old, 260)
                ow = QFontMetricsF(old_font).horizontalAdvance(old_text)
                p.drawText(QRectF(cursor, y, ow + 4, row_h - 10), Qt.AlignVCenter | Qt.AlignLeft, old_text)
                cursor += ow + 18
                p.setPen(QColor("#ffb000"))
                p.setFont(value_font)
                p.drawText(QRectF(cursor, y, 40, row_h - 10), Qt.AlignVCenter | Qt.AlignLeft, "→")
                cursor += 44
            p.setFont(value_font)
            p.setPen(QColor("#ffd27a"))
            p.drawText(QRectF(cursor, y, width - 60 - cursor, row_h - 10), Qt.AlignVCenter | Qt.AlignLeft,
                       _fit_text(QFontMetricsF(value_font), new, width - 80 - cursor))
            y += row_h
        if len(all_plain) > len(plain_changes):
            p.setFont(name_font)
            p.setPen(QColor("#8d8d92"))
            p.drawText(QRectF(40, y, width - 80, 20), Qt.AlignVCenter | Qt.AlignLeft,
                       f"… ほか {len(all_plain) - len(plain_changes)} 件")
            y += 24

        for c in code_changes[:1]:
            p.setFont(label_font)
            p.setPen(QColor("#f2f2f4"))
            p.drawText(QRectF(40, y, width - 80, 28), Qt.AlignVCenter | Qt.AlignLeft,
                       f"{c.get('label', '')}  ({c.get('name', '')})")
            y += 34
            lines = str(c.get("new", "")).splitlines() or [""]
            avail = height - y - 70
            max_lines = max(3, int(avail // 22))
            shown = lines[:max_lines]
            box = QRectF(40, y, width - 80, min(avail, len(shown) * 22 + 24) + (22 if len(lines) > max_lines else 0))
            p.setPen(QPen(QColor("#ffb000"), 1.6))
            p.setBrush(QColor("#1d1d1f"))
            p.drawRoundedRect(box, 8, 8)
            p.setFont(code_font)
            metrics = QFontMetricsF(code_font)
            ty = y + 12
            for line in shown:
                p.setPen(QColor("#7ec699") if line.lstrip().startswith("//") else QColor("#e6e6e8"))
                p.drawText(QRectF(56, ty, width - 112, 22), Qt.AlignVCenter | Qt.AlignLeft,
                           _fit_text(metrics, line.replace("\t", "    "), width - 112))
                ty += 22
            if len(lines) > max_lines:
                p.setPen(QColor("#8d8d92"))
                p.drawText(QRectF(56, ty, width - 112, 22), Qt.AlignVCenter | Qt.AlignLeft,
                           f"… ほか {len(lines) - max_lines} 行")
            y = box.bottom() + 16

        if others and y < height - 90:
            p.setFont(section_font)
            p.setPen(QColor("#8d8d92"))
            p.drawText(QRectF(40, height - 100, width - 80, 20), Qt.AlignVCenter | Qt.AlignLeft, "このノードのその他の設定")
            p.setFont(name_font)
            line = "    ".join(f"{k} = {v}" for k, v in others[:5])
            p.drawText(QRectF(40, height - 76, width - 80, 44), Qt.AlignTop | Qt.AlignLeft | Qt.TextWordWrap,
                       _fit_text(QFontMetricsF(name_font), line, (width - 80) * 2))

        p.end()
        if not image.save(str(output_path), "PNG"):
            _log(f"render_parameter_card: image.save() returned False for {output_path}", log_path)
            return False
        _log(f"parameter card rendered ({node_name}: {len(changes)} change(s))", log_path)
        return True
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"render_parameter_card failed: {exc!r}", log_path)
        return False


def code_scale(row_count: int, longest_cols: int, max_cols: int, available_height: float, line_height: float = CODE_LINE_H) -> float:
    """コードのカードの、文字を大きくする倍率（1.0 以上、CODE_SCALE_MAX 以下）。
    行が少ないと、カードの上のほうに小さく出て、残りが空いていた（2026-11-18 の動画で確認）。行が収まる・いちばん長い行が収まる範囲で、大きくする。
    row_count: 行数（折り返し後）、longest_cols: いちばん長い行の桁数、max_cols: 倍率 1.0 での 1 行に入る桁数、available_height: コードの箱に使える高さ。"""
    if row_count <= 0 or longest_cols <= 0 or max_cols <= 0 or available_height <= 0:
        return 1.0
    by_width = max_cols / longest_cols
    by_height = available_height / (row_count * line_height + 24.0)
    return max(1.0, min(CODE_SCALE_MAX, by_width, by_height))


def code_card_capacity(plain_count: int, height: int = LOGICAL_HEIGHT) -> tuple[int, int]:
    """コードのカードの 1 枚に入る行数。戻り値: (1 枚目, 2 枚目から)。1 枚目は、変更点の行（plain_count。最大 3）と一緒。"""
    box_top_first = 100.0 + 30.0 + min(plain_count, 3) * 52.0 + 42.0
    box_top_other = 100.0
    usable = lambda top: max(1, int((height - top - 24.0 - 16.0) // CODE_LINE_H))  # noqa: E731 -- 箱の余白 24、下の余白 16
    return usable(box_top_first), usable(box_top_other)


def render_code_cards(
    output_path: Path,
    container_path: str,
    node_name: str,
    node_type_label: str,
    plain_changes: list[dict],
    code_change: dict,
    width: int = 1280,
    height: int = 720,
    log_path: Path | None = None,
) -> list[Path]:
    """長いコード（VEX など）を、読める大きさで、複数枚のカードに出す。戻り値: 書いた画像のパス（1 枚目は output_path。
    2 枚目以降は extra_page_path）。失敗は空のリスト。

    等幅 CODE_FONT_PT（16pt）、行番号つき、長い行は折り返し。1 枚目は変更点の一覧と一緒、2 枚目からはコードだけ。
    CODE_MAX_PAGES 枚に入りきらない行は、最後のカードに「ほか N 行」と書く。"""
    try:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen

        code_font = QFont("Consolas")
        code_font.setPointSizeF(CODE_FONT_PT)
        metrics = QFontMetricsF(code_font)
        gutter = 48.0
        box_w = width - 80.0
        char_w = max(1.0, metrics.horizontalAdvance("M"))
        max_cols = int((box_w - 24.0 - gutter) // char_w)
        rows = wrap_code_lines(str(code_change.get("new", "")), max_cols)
        shown_plain = plain_changes[:3]
        first_cap, other_cap = code_card_capacity(len(shown_plain), height)
        pages, hidden_rows = paginate_code(rows, first_cap, other_cap)
        total_lines = max((n for n, _t in rows if n), default=0)
        # 1 枚に収まり、折り返しも無いときは、文字を大きくして、カードの空きを使う
        scale = 1.0
        if len(pages) == 1 and not hidden_rows and not any(n is None for n, _t in rows):
            box_top = 100.0 + 30.0 + len(shown_plain) * 52.0 + 4.0 + 38.0
            longest = max((len(t) for _n, t in rows), default=0)
            scale = code_scale(len(rows), longest, max_cols, height - box_top - 20.0)
        line_h = CODE_LINE_H * scale
        if scale > 1.0:
            code_font.setPointSizeF(CODE_FONT_PT * scale)
            gutter = 48.0 * scale

        for stale in find_extra_pages(output_path):  # 前の実行の、使われない続きの画像を消す
            try:
                stale.unlink()
            except OSError:
                pass

        paths: list[Path] = []
        for page_no, page_rows in enumerate(pages, start=1):
            image = QImage(width * RENDER_SCALE, height * RENDER_SCALE, QImage.Format_ARGB32)
            image.fill(QColor("#2f2f31"))
            p = QPainter(image)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setRenderHint(QPainter.TextAntialiasing, True)
            p.scale(RENDER_SCALE, RENDER_SCALE)

            bar_font = QFont("Segoe UI", 12)
            bar_font.setBold(True)
            p.fillRect(QRectF(0, 0, width, 40), QColor("#232325"))
            p.setPen(QColor("#c9c9cc"))
            p.setFont(bar_font)
            p.drawText(QRectF(16, 0, width - 32, 40), Qt.AlignVCenter | Qt.AlignLeft, f"{container_path}  ›  {node_name}")
            if len(pages) > 1 or hidden_rows:
                p.setPen(QColor("#ffb000"))
                p.drawText(QRectF(16, 0, width - 32, 40), Qt.AlignVCenter | Qt.AlignRight, f"{page_no} / {len(pages)}")

            label_font = QFont("Segoe UI", 17)
            label_font.setBold(True)
            sub_font = QFont("Segoe UI", 12)
            value_font = QFont("Segoe UI", 18)
            value_font.setBold(True)
            old_font = QFont("Segoe UI", 15)
            y = 52.0
            if page_no == 1:
                p.setFont(sub_font)
                p.setPen(QColor("#9a9aa0"))
                p.drawText(QRectF(40, y, width - 80, 22), Qt.AlignVCenter | Qt.AlignLeft, node_type_label)
                y = 100.0
                p.setFont(QFont("Segoe UI", 11))
                p.setPen(QColor("#ffb000"))
                p.drawText(QRectF(40, y - 4, width - 80, 22), Qt.AlignVCenter | Qt.AlignLeft, "変更したパラメータ")
                y += 30.0
                for c in shown_plain:
                    row = QRectF(40, y, width - 80, 44)
                    p.setPen(QPen(QColor("#ffb000"), 1.6))
                    p.setBrush(QColor(255, 176, 0, 34))
                    p.drawRoundedRect(row, 8, 8)
                    label = c.get("label", c.get("name", ""))
                    tab = c.get("tab", "")
                    p.setFont(label_font)
                    p.setPen(QColor("#f2f2f4"))
                    p.drawText(QRectF(56, y, 420, 44), Qt.AlignVCenter | Qt.AlignLeft,
                               _fit_text(QFontMetricsF(label_font), (f"{tab} › " if tab else "") + label, 410))
                    old, new = str(c.get("old", "")), str(c.get("new", ""))
                    cursor = 500.0
                    if old and old != new:
                        p.setFont(old_font)
                        p.setPen(QColor("#8d8d92"))
                        text = _fit_text(QFontMetricsF(old_font), old, 220)
                        ow = QFontMetricsF(old_font).horizontalAdvance(text)
                        p.drawText(QRectF(cursor, y, ow + 4, 44), Qt.AlignVCenter | Qt.AlignLeft, text)
                        cursor += ow + 16
                        p.setFont(value_font)
                        p.setPen(QColor("#ffb000"))
                        p.drawText(QRectF(cursor, y, 40, 44), Qt.AlignVCenter | Qt.AlignLeft, "→")
                        cursor += 40
                    p.setFont(value_font)
                    p.setPen(QColor("#ffd27a"))
                    p.drawText(QRectF(cursor, y, width - 56 - cursor, 44), Qt.AlignVCenter | Qt.AlignLeft,
                               _fit_text(QFontMetricsF(value_font), new, width - 60 - cursor))
                    y += 52.0
                y += 4.0
            title = f"{code_change.get('tab', '') + ' › ' if code_change.get('tab') else ''}{code_change.get('label', '')}  （全 {total_lines} 行）"
            if page_no > 1:
                title += "  続き"
            p.setFont(label_font)
            p.setPen(QColor("#f2f2f4"))
            p.drawText(QRectF(40, y, width - 80, 30), Qt.AlignVCenter | Qt.AlignLeft,
                       _fit_text(QFontMetricsF(label_font), title, width - 80))
            y += 38.0 if page_no == 1 else 34.0
            box = QRectF(40, y, box_w, len(page_rows) * line_h + 24.0)
            p.setPen(QPen(QColor("#ffb000"), 1.6))
            p.setBrush(QColor("#1d1d1f"))
            p.drawRoundedRect(box, 8, 8)
            p.setFont(code_font)
            ty = y + 12.0
            for number, text in page_rows:
                if number is not None:
                    p.setPen(QColor("#6f6f76"))
                    p.drawText(QRectF(52, ty, gutter - 8, line_h), Qt.AlignVCenter | Qt.AlignRight, str(number))
                p.setPen(QColor("#7ec699") if text.lstrip().startswith("//") else QColor("#e6e6e8"))
                p.drawText(QRectF(52 + gutter, ty, box_w - gutter - 24, line_h), Qt.AlignVCenter | Qt.AlignLeft, text)
                ty += line_h
            if hidden_rows and page_no == len(pages):
                p.setFont(QFont("Segoe UI", 12))
                p.setPen(QColor("#8d8d92"))
                p.drawText(QRectF(40, box.bottom() + 4, width - 80, 20), Qt.AlignVCenter | Qt.AlignLeft,
                           f"… ほか {hidden_rows} 行（全文はチュートリアルの本文にあります）")
            p.end()
            target = extra_page_path(output_path, page_no)
            if not image.save(str(target), "PNG"):
                _log(f"render_code_cards: image.save() returned False for {target}", log_path)
                return []
            paths.append(target)
        write_capture_meta(output_path, {
            "kind": "code_card", "pages": len(paths), "lines_total": total_lines, "lines_hidden": hidden_rows,
            "font_pt": round(CODE_FONT_PT * scale, 1), "max_cols": max_cols, "wrapped": any(n is None for n, _t in rows),
            "width": width * RENDER_SCALE, "height": height * RENDER_SCALE,
        }, log_path)
        _log(f"code card rendered ({node_name}: {total_lines} lines, {len(paths)} page(s), {hidden_rows} row(s) not shown)", log_path)
        return paths
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"render_code_cards failed: {exc!r}", log_path)
        return []


def _compose_parameter_screen(
    output_path: Path,
    pane_image,
    container_path: str,
    node_name: str,
    changes: list[dict],
    width: int,
    height: int,
    log_path: Path | None,
) -> bool:
    """実際のパラメータ画面（Houdiniのペインの切り出し）を左に大きく、「何を、いくつからいくつに変えたか」を右に並べる。
    実画面は、パラメータがどこにあるかが分かる。右の一覧は、実画面ではスクロールや折りたたみで見えないことがある
    変更点を、確実に伝える。"""
    try:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen

        image = QImage(width * RENDER_SCALE, height * RENDER_SCALE, QImage.Format_ARGB32)
        image.fill(QColor("#2f2f31"))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.scale(RENDER_SCALE, RENDER_SCALE)  # 座標は width x height のまま、画素だけ細かくする

        bar_h = 40
        p.fillRect(QRectF(0, 0, width, bar_h), QColor("#232325"))
        bar_font = QFont("Segoe UI", 12)
        bar_font.setBold(True)
        p.setFont(bar_font)
        p.setPen(QColor("#c9c9cc"))
        p.drawText(QRectF(16, 0, width - 32, bar_h), Qt.AlignVCenter | Qt.AlignLeft, f"{container_path}  ›  {node_name}")

        pane_image = crop_parm_pane(pane_image)  # ペイン全体ではなく、パラメータの行がある範囲だけを大きく使う（読めなかった。2026-11-22・23）
        pane_w = int(width * 0.60)
        area = QRectF(12, bar_h + 12, pane_w - 12, height - bar_h - 24)
        # 切り出した画像は、先に縮小せず、元の画素のまま、描画先の矩形へ直接描く（2倍の画素で描くので、細かさを保つ）。
        fit = min(area.width() / pane_image.width(), area.height() / pane_image.height())
        target_w, target_h = pane_image.width() * fit, pane_image.height() * fit
        px = area.x()
        py = area.y() + max(0.0, (area.height() - target_h) / 2.0)  # 縦の中央に置く（上寄せだと、下の 3 割ほどが空いた画面になった。2026-11-20）
        p.drawImage(QRectF(px, py, target_w, target_h), pane_image)
        p.setPen(QPen(QColor("#4a4a4f"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(px, py, target_w, target_h))

        x0 = pane_w + 12.0
        col_w = width - x0 - 20
        section_font = QFont("Segoe UI", 11)
        section_font.setBold(True)
        label_font = QFont("Segoe UI", 15)
        label_font.setBold(True)
        value_font = QFont("Segoe UI", 16)
        value_font.setBold(True)
        old_font = QFont("Segoe UI", 13)
        code_font = QFont("Consolas", 11)
        y = bar_h + 16.0
        p.setFont(section_font)
        p.setPen(QColor("#ffb000"))
        p.drawText(QRectF(x0, y, col_w, 22), Qt.AlignVCenter | Qt.AlignLeft, "変更したパラメータ")
        y += 30
        plain = [c for c in changes if not c.get("code")][:6]
        code = [c for c in changes if c.get("code")][:1]
        for c in plain:
            row = QRectF(x0, y, col_w, 62)
            p.setPen(QPen(QColor("#ffb000"), 1.4))
            p.setBrush(QColor(255, 176, 0, 30))
            p.drawRoundedRect(row, 8, 8)
            p.setFont(label_font)
            p.setPen(QColor("#f2f2f4"))
            p.drawText(QRectF(x0 + 12, y + 3, col_w - 24, 26), Qt.AlignVCenter | Qt.AlignLeft,
                       _fit_text(QFontMetricsF(label_font), (f"{c['tab']} › " if c.get("tab") else "") + c.get("label", c.get("name", "")), col_w - 24))
            old, new = str(c.get("old", "")), str(c.get("new", ""))
            cursor = x0 + 12
            if old and old != new:
                p.setFont(old_font)
                p.setPen(QColor("#8d8d92"))
                old_text = _fit_text(QFontMetricsF(old_font), old, col_w * 0.34)
                ow = QFontMetricsF(old_font).horizontalAdvance(old_text)
                p.drawText(QRectF(cursor, y + 31, ow + 4, 26), Qt.AlignVCenter | Qt.AlignLeft, old_text)
                cursor += ow + 12
                p.setFont(value_font)
                p.setPen(QColor("#ffb000"))
                p.drawText(QRectF(cursor, y + 31, 30, 26), Qt.AlignVCenter | Qt.AlignLeft, "→")
                cursor += 34
            p.setFont(value_font)
            p.setPen(QColor("#ffd27a"))
            p.drawText(QRectF(cursor, y + 31, x0 + col_w - cursor - 8, 26), Qt.AlignVCenter | Qt.AlignLeft,
                       _fit_text(QFontMetricsF(value_font), new, x0 + col_w - cursor - 8))
            y += 72
        for c in code:
            p.setFont(label_font)
            p.setPen(QColor("#f2f2f4"))
            p.drawText(QRectF(x0, y, col_w, 26), Qt.AlignVCenter | Qt.AlignLeft,
                       _fit_text(QFontMetricsF(label_font), c.get("label", c.get("name", "")), col_w))
            y += 32
            lines = str(c.get("new", "")).splitlines() or [""]
            shown = lines[: max(2, int((height - y - 30) // 20))]
            box = QRectF(x0, y, col_w, len(shown) * 20 + 20)
            p.setPen(QPen(QColor("#ffb000"), 1.4))
            p.setBrush(QColor("#1d1d1f"))
            p.drawRoundedRect(box, 8, 8)
            p.setFont(code_font)
            metrics = QFontMetricsF(code_font)
            ty = y + 10
            for line in shown:
                p.setPen(QColor("#7ec699") if line.lstrip().startswith("//") else QColor("#e6e6e8"))
                p.drawText(QRectF(x0 + 12, ty, col_w - 24, 20), Qt.AlignVCenter | Qt.AlignLeft,
                           _fit_text(metrics, line.replace("\t", "    "), col_w - 24))
                ty += 20
        p.end()
        return bool(image.save(str(output_path), "PNG"))
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"_compose_parameter_screen failed: {exc!r}", log_path)
        return False


def with_tab_paths(node, changes: list[dict]) -> list[dict]:
    """changes の各項目に、パラメータが入っているタブ（"tab": "A › B"）を足した複製を返す。元は変えない。読めなければ、足さない。"""
    out = []
    for c in changes:
        item = dict(c)
        if node is not None and not item.get("tab") and item.get("name"):
            tab = tab_path_of(node, str(item["name"]))
            if tab:
                item["tab"] = tab
        out.append(item)
    return out


def capture_parameter_screen(
    output_path: Path,
    node_path: str,
    container_path: str,
    node_name: str,
    node_type_label: str,
    changes: list[dict],
    others: list[tuple[str, str]] | None = None,
    width: int = 1280,
    height: int = 720,
    log_path: Path | None = None,
) -> str:
    """set_parameter のステップ用の画像を作る。戻り値: 使った方法（"code_card" / "pane" / "card" / ""=失敗）。

    0. "code_card"（2026-11-17）: 長いコード（VEX など）の変更があるとき。専用のカードに、大きく・折り返して・複数枚で出す
       （render_code_cards。2 枚目以降は extra_page_path のファイル名で、同じ場所に書く）。実画面の小さな枠では読めないため。
       変更した項目が入っているタブの名前を添える（with_tab_paths）。それ以外は、次の 1、2。
    1. "pane": 実際のパラメータ画面（Parmペイン）を切り出し、変更点の一覧を添える（2026-10-21）。
       どこに何があるかが、実画面のほうが分かりやすい。ノードを選択して、ペインに表示させる。
       ペインが無い・固定表示（ピン）・隠れている・他のウィンドウが重なっている等で撮れなければ、次へ。
    2. "card": 従来どおり、Houdiniのパラメータ画面風に描き直したカード（render_parameter_card）。
    どちらで撮れたかは、capture.log に「parameter capture method: ...」と残る。"""
    # 変更した項目が入っているタブの名前を足し（スライドに「どのタブの、どの項目か」を出すため）、パラメータ画面のタブをそこに合わせる。
    try:
        target_node = hou.node(node_path)
    except Exception:  # noqa: BLE001
        target_node = None
    changes = with_tab_paths(target_node, changes)
    code_change = next((c for c in changes if c.get("code")), None)
    if code_change is not None:
        # 長いコード（VEX など）は、パラメータ画面の小さな枠では読めない。専用のカードに、大きく・折り返して・複数枚で出す。
        pages = render_code_cards(
            output_path, container_path, node_name, node_type_label, [c for c in changes if not c.get("code")],
            code_change, width, height, log_path,
        )
        if pages:
            _log("parameter capture method: code card", log_path)
            for page_path in [output_path, *find_extra_pages(output_path)]:
                shrink_saved_image(page_path, log_path)  # カードの下の空きを切り詰める（動画で、コードが小さく映っていた。2026-11-22）
            return "code_card"
    if target_node is not None:
        reveal_parm_tabs(target_node, [c["name"] for c in changes if c.get("name")], log_path)
    pane_image = None
    try:
        pane = hou.ui.paneTabOfType(hou.paneTabType.Parm)
    except Exception as exc:  # noqa: BLE001
        _log(f"paneTabOfType(Parm) failed: {exc!r}", log_path)
        pane = None
    if pane is None:
        _log("no Parm pane found in the current desktop; using the drawn card", log_path)
    else:
        try:
            if pane.isPin():
                _log("the Parm pane is pinned (it may show another node); using the drawn card", log_path)
            else:
                node = hou.node(node_path)
                if node is not None:
                    node.setCurrent(True, clear_all_selected=True)
                    pane.setIsCurrentTab()
                    time.sleep(0.2)  # パラメータ画面が、選んだノードの内容に組み替わるのを待つ
                    _flush_qt_events()
                    with maximized_if_narrow(pane, log_path):  # 狭いペインは、撮るあいだだけ最大化（広い実画面を撮る）
                        pane_image = _grab_with_retry(pane, log_path, label="Parm")
        except Exception as exc:  # noqa: BLE001
            _log(f"screen grab of the Parm pane failed: {exc!r}", log_path)
            pane_image = None
    if pane_image is not None and _compose_parameter_screen(
        output_path, pane_image, container_path, node_name, changes, width, height, log_path
    ):
        _log("parameter capture method: pane (qtScreenGeometry) + change list", log_path)
        return "pane"
    if render_parameter_card(
        output_path, container_path, node_name, node_type_label, changes, others, width, height, log_path
    ):
        _log("parameter capture method: drawn card", log_path)
        return "card"
    return ""


def capture_network_editor(
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    log_path: Path | None = None,
    *,
    container_path: str | None = None,
    focus_path: str | None = None,
    callout: str | None = None,
) -> bool:
    """
    ノード画面（ネットワークエディタ）の画像を output_path に保存する。

    1. 実画面: hou.NetworkEditor.qtScreenGeometry() が示すペインの矩形を画面から切り出す
       （_grab_network_pane。誤画像を保存しないための検査つき）
    2. 上が成立しなければ、container_path のノード構成を自前で描いた図
       （render_network_diagram）にフォールバックする
    どちらの方法で撮れたかは log_path に「network capture method: ...」として残る。

    経緯（2026-07〜09の実機検証で繰り返し失敗）: qtParentWindow() 全体の grab は
    自分のRAGChatBotパネルが映り込み、hou.qt.mainWindow()/トップレベルウィンドウ列挙は
    Houdini本体を返さず（0x0のウィンドウしか見つからない）、screenBounds() は
    ペイン内ローカル座標で使えなかった。原因は、ドキュメントに載っている
    qtScreenGeometry() を使わずにウィジェット探索に頼っていたこと。加えて、撮影対象が
    常にサンドボックス直下で、作業の実体が入っている geo の中身を映していなかった。
    """
    try:
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    except Exception as exc:  # noqa: BLE001
        _log(f"paneTabOfType(NetworkEditor) failed: {exc!r}", log_path)
        network_editor = None

    if network_editor is not None:
        try:
            # 狭いペインは、撮るあいだだけ最大化する（広い実画面を撮る。描き直した図は、実画面が撮れないときだけ）。注目ノードに合わせるのは、広げたあと。
            with maximized_if_narrow(network_editor, log_path):
                # 注目ノードと前後を、読める大きさで映す（focus_network_on は、注目ノードを知らずに全体を映していた）。
                if focus_path and container_path:
                    try:
                        network = hou.node(container_path)
                        if network is not None and frame_network_on_focus(network_editor, network, focus_path, log_path):
                            _flush_qt_events()
                    except Exception as exc:  # noqa: BLE001
                        _log(f"re-framing on the focus node failed: {exc!r}", log_path)
                _flush_qt_events()
                image = _grab_with_retry(network_editor, log_path)
            if image is not None:
                # 以前は width x height（1280x720）に縮めていたため、高解像度の画面では文字がつぶれた。
                # 切り出した画素数のまま保存し、狭すぎる／広すぎるときだけ調整する（fit_pane_size）。
                # 狭いペインを、1280 まで引き伸ばさない（画素が増えるわけではなく、ぼやけるだけ。2026-11-20 の実機の画像で確認）。
                new_w, new_h = fit_pane_size(image.width(), image.height(), min_width=min(image.width(), PANE_MIN_WIDTH))
                if (new_w, new_h) != (image.width(), image.height()):
                    from PySide6.QtCore import Qt as QtNamespace

                    image = image.scaled(new_w, new_h, QtNamespace.IgnoreAspectRatio, QtNamespace.SmoothTransformation)
                _log(f"network capture size: {image.width()}x{image.height()}", log_path)
                if image.save(str(output_path), "PNG"):
                    _log("network capture method: screen (qtScreenGeometry)", log_path)
                    return True
                _log(f"image.save() returned False for {output_path}", log_path)
        except Exception as exc:  # noqa: BLE001
            _log(f"screen grab of the NetworkEditor pane failed: {exc!r}", log_path)
    else:
        _log("no NetworkEditor pane found in the current desktop", log_path)

    return render_network_diagram(
        output_path, container_path, focus_path, callout, width, height, log_path
    )
