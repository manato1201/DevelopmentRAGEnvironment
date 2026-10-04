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

import datetime
import re
from pathlib import Path

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


def _frame_network_children(network_editor, network, log_path: Path | None) -> None:
    """ネットワーク直下の全ノードが視野に収まるよう、ネットワークエディタの表示範囲を合わせる。"""
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


def focus_network_on(node_path: str, log_path: Path | None = None) -> None:
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
        _frame_network_children(network_editor, network, log_path)
        if hasattr(network_editor, "setIsCurrentTab"):
            network_editor.setIsCurrentTab()
            _flush_qt_events()
        else:
            _log("focus_network_on: no setIsCurrentTab() on this Houdini build", log_path)
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"focus_network_on failed: {exc!r}", log_path)


def capture_viewport(
    output_path: Path, width: int = 1280, height: int = 720, log_path: Path | None = None
) -> bool:
    """
    現在の3Dビューポートを1枚の静止画として output_path に保存する。
    hou.SceneViewer.flipbook()（Houdiniの標準ビューポート書き出しAPI）を
    現在フレームだけの1フレームレンジで呼び出す実装。
    """
    try:
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
        try:
            scene_viewer.curViewport().frameAll()
        except Exception as exc:  # noqa: BLE001
            _log(f"frameAll() failed, capturing with current framing: {exc!r}", log_path)
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
        return exists
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"viewport capture failed: {exc!r}", log_path)
        return False


def capture_viewport_clip(
    output_dir: Path,
    base_name: str,
    frame_count: int = 16,
    fps: int = 12,
    width: int = 640,
    height: int = 360,
    log_path: Path | None = None,
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
        try:
            scene_viewer.curViewport().frameAll()
        except Exception as exc:  # noqa: BLE001
            _log(f"frameAll() failed before clip capture: {exc!r}", log_path)

        original_frame = hou.frame()
        start_frame = original_frame
        end_frame = start_frame + frame_count - 1
        output_template = str(output_dir / f"{base_name}.$F4.png")
        try:
            settings = scene_viewer.flipbookSettings().stash()
            settings.frameRange((start_frame, end_frame))
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


def _grab_network_pane(network_editor, log_path: Path | None):
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
    _log(f"NetworkEditor qtScreenGeometry: ({x},{y},{w},{h})", log_path)
    if w < 200 or h < 120:
        _log("NetworkEditor pane is too small to capture (hidden or collapsed?)", log_path)
        return None

    # 画面切り出しは「今画面に見えているもの」をそのままコピーするため、Houdini以外の
    # アプリ（ブラウザ等）が手前に来ているとそれが映ってしまい、しかもウィジェット側からは
    # 検知できない。アプリがアクティブでない間は撮らず、自前描画の図に任せる。
    from PySide6.QtCore import Qt as QtNamespace

    if QGuiApplication.applicationState() != QtNamespace.ApplicationActive:
        _log("Houdini is not the active application (another window may cover the pane); not grabbing the screen", log_path)
        return None

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
                _log("the RAGChatBot panel overlaps the NetworkEditor pane on screen; not grabbing it", log_path)
                return None
            top_windows.add(id(covering.window()))
    if len(top_windows) != 1:
        _log("another window (e.g. the Houdini Console) overlaps the pane; not grabbing the screen", log_path)
        return None

    origin = screen.geometry().topLeft()
    image = screen.grabWindow(0, x - origin.x(), y - origin.y(), w, h).toImage()
    if _looks_blank(image):
        _log("the grabbed NetworkEditor region is blank", log_path)
        return None
    return image


# ─── 自前描画のネットワーク図（実画面が撮れない場合のフォールバック） ──────────────────

_MAX_DIAGRAM_NODES = 60


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 -- 図の描画は情報が欠けても続行する
        return default


def _collect_network_model(network) -> list[dict]:
    """ネットワーク直下のノード（名前・タイプ・色・フラグ・入力接続・元の座標）を集める。"""
    children = list(network.children())[:_MAX_DIAGRAM_NODES]
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


def _paint_network_diagram(layers, container_path, focus_path, callout, width, height):
    """Houdiniのネットワークエディタ風のダーク配色で、上→下の流れの図を QImage に描く。"""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import (
        QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen,
    )

    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor("#2f2f31"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

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

    name_font = QFont("Segoe UI", 11)
    name_font.setBold(True)
    type_font = QFont("Segoe UI", 8)
    tag_font = QFont("Segoe UI", 10)
    tag_font.setBold(True)
    name_metrics = QFontMetricsF(name_font)

    box_h, gap_x, gap_y = 48.0, 36.0, 56.0
    rows = []
    for members in layers:
        widths = [max(140.0, name_metrics.horizontalAdvance(n["name"]) + 40.0) for n in members]
        rows.append(widths)

    if not layers or not any(layers):
        painter.setPen(QColor("#8d8d92"))
        painter.setFont(bar_font)
        painter.drawText(QRectF(0, 40, width, height - 40), Qt.AlignCenter, "(このネットワークにはまだノードがありません)")
        painter.end()
        return image

    row_widths = [sum(ws) + gap_x * (len(ws) - 1) for ws in rows]
    layout_w = max(row_widths)
    layout_h = len(rows) * box_h + (len(rows) - 1) * gap_y
    avail_w, avail_h = width - 80.0, height - 40.0 - 48.0
    scale = max(0.35, min(avail_w / layout_w, avail_h / layout_h, 1.6))
    offset_x = (width - layout_w * scale) / 2.0
    offset_y = 40.0 + (height - 40.0 - layout_h * scale) / 2.0
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
            painter.drawText(QRectF(rect.left(), rect.top() + 4, rect.width(), 24), Qt.AlignCenter, n["name"])

            painter.setFont(type_font)
            painter.setPen(QColor("#55555b") if dark_text else QColor("#b9b9bf"))
            painter.drawText(QRectF(rect.left(), rect.top() + 27, rect.width(), 16), Qt.AlignCenter, n["type"])

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
        tag_rect = QRectF(focus_rect.right() + 40, focus_rect.center().y() - 15, tag_w, 30)
        top_left = painter.transform().map(tag_rect.topLeft())
        overflow = top_left.x() + tag_w * scale - (width - 8)
        if overflow > 0:
            tag_rect = QRectF(focus_rect.left() - 40 - tag_w, tag_rect.top(), tag_w, 30)
        painter.setPen(QPen(QColor("#ffb000"), 1.6))
        painter.setBrush(QColor("#1e1e20"))
        painter.drawRoundedRect(tag_rect, 6, 6)
        painter.setPen(QColor("#ffd27a"))
        painter.drawText(tag_rect, Qt.AlignCenter, label)

    painter.end()
    return image


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
        layers = _assign_layers(_collect_network_model(network))
        image = _paint_network_diagram(layers, container_path, focus_path, callout, width, height)
        if not image.save(str(output_path), "PNG"):
            _log(f"render_network_diagram: image.save() returned False for {output_path}", log_path)
            return False
        _log(f"network capture method: synthetic diagram ({container_path})", log_path)
        return True
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"render_network_diagram failed: {exc!r}", log_path)
        return False


def _fit_text(metrics, text: str, max_width: float) -> str:
    """max_width に収まるよう、末尾を…で省略した文字列を返す。"""
    if metrics.horizontalAdvance(text) <= max_width:
        return text
    while len(text) > 1 and metrics.horizontalAdvance(text + "…") > max_width:
        text = text[:-1]
    return text + "…"


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

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(QColor("#2f2f31"))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

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
            p.drawText(QRectF(56, y + 27, label_w - 20, 16), Qt.AlignVCenter | Qt.AlignLeft, f"({c.get('name', '')})")

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
        _flush_qt_events()
        try:
            image = _grab_network_pane(network_editor, log_path)
            if image is not None:
                if width and height:
                    from PySide6.QtCore import Qt as QtNamespace

                    image = image.scaled(
                        width, height, QtNamespace.KeepAspectRatio, QtNamespace.SmoothTransformation
                    )
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
