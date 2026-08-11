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
from pathlib import Path

import hou


def _log(message: str, log_path: Path | None) -> None:
    """print() に加えてファイルへも書く（ファイル書き込み失敗は無視する）。"""
    line = f"[screen_capture] {message}"
    print(line)
    if log_path is None:
        return
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


def focus_network_on(node_path: str, log_path: Path | None = None) -> None:
    """
    ネットワークエディタのペインを指定ノード配下にフォーカス・フレームし、
    そのペインを「現在表示中のタブ」に切り替える。

    Houdiniのペインはタブ切り替え式で、同じペイングループ内の他のタブ
    （Scene View等）がアクティブだと、Qt側はネットワークエディタの中身を
    そもそも描画していない。2026-07-25の実機検証で capture_network_editor()
    が一貫して間違った内容（アクティブな別タブ）を撮っていたのは、これが
    根本原因である可能性が高い。setIsCurrentTab() でネットワークエディタを
    強制的に前面に出してから撮影する。失敗しても静かに諦める
    （ベストエフォート）。
    """
    try:
        node = hou.node(node_path)
        if node is None:
            _log(f"focus_network_on: node not found: {node_path}", log_path)
            return
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor is None:
            _log("focus_network_on: no NetworkEditor pane found", log_path)
            return
        network_editor.setCurrentNode(node)
        network_editor.setPwd(node)
        network_editor.homeToSelection()
        if hasattr(network_editor, "setIsCurrentTab"):
            network_editor.setIsCurrentTab()
            # setIsCurrentTab() 直後はまだ古いタブの内容が画面に残っている
            # ことがあるため、grab() 前に repaint を強制的に完了させる。
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


def _bounds_size(bounds) -> tuple[int, int] | None:
    """
    hou.PaneTab.screenBounds() が返す hou.BoundingRect からサイズ（幅・高さ）
    だけを取り出す。座標としての信頼性は無い（下記docstring参照）が、
    「このペインの見た目上の大きさ」としては再利用できる。
    hou.BoundingRect は 4要素シーケンス (xmin, ymin, xmax, ymax) として
    インデックスアクセスできるはずだが、Houdiniのビルドによって挙動が
    変わりうるため sizevec2() も保険として試す。
    """
    try:
        return int(round(bounds[2] - bounds[0])), int(round(bounds[3] - bounds[1]))
    except Exception:
        pass
    try:
        size = bounds.sizevec2()
        return int(round(size[0])), int(round(size[1]))
    except Exception:
        return None


def _find_network_editor_widget(network_editor, main_window, log_path: Path | None):
    """
    main_window（hou.qt.mainWindow()）全体ではなく、NetworkEditorペイン
    単体に絞ってキャプチャするため、その中の該当ウィジェットを探す。

    Houdiniのペインタブオブジェクトは Qt ウィジェットへの直接参照を
    公開していない（qtWidget() はこのビルドに存在しないことを実機の
    dir() で確認済み）。そこで network_editor.screenBounds() が返す
    サイズ（実機で確認: 常に固定値が返る＝絶対座標としては使えないが、
    ペイン自身の見た目上の幅・高さとしては再利用できる）をシグネチャに
    使い、main_window 配下の全ウィジェットからサイズが一致する可視
    ウィジェットを探す。見つからなければ None を返し、呼び出し側は
    ウィンドウ全体グラブにフォールバックする。
    """
    try:
        bounds = network_editor.screenBounds()
    except Exception as exc:
        _log(f"screenBounds() unavailable, cannot narrow capture target: {exc!r}", log_path)
        return None
    size = _bounds_size(bounds)
    if size is None:
        _log(f"could not extract width/height from screenBounds()={bounds!r}", log_path)
        return None
    w, h = size
    if w <= 0 or h <= 0:
        return None

    from PySide6.QtWidgets import QWidget

    candidates = [
        c for c in main_window.findChildren(QWidget)
        if c.isVisible() and c.width() == w and c.height() == h
    ]
    if not candidates:
        _log(f"no visible child widget matches NetworkEditor size {w}x{h}; "
             "falling back to whole-window grab", log_path)
        return None
    if len(candidates) > 1:
        _log(f"{len(candidates)} widgets match NetworkEditor size {w}x{h}; using the first", log_path)
    return candidates[0]


def capture_network_editor(
    output_path: Path, width: int = 1280, height: int = 720, log_path: Path | None = None
) -> bool:
    """
    現在のネットワークエディタペインをスクリーンショットとして保存する。

    2026-07-25 実機検証で判明: network_editor.screenBounds() は物理画面の
    絶対座標ではなく、Houdiniのペイン内部だけで使われるローカル座標系の
    模様（17ステップ全てで [0, 0, 613, 332] という同一値が返り、その座標で
    画面全体スクリーンショットを切り出すと、実際のネットワークエディタの
    位置に関わらず常に画面左上のメニューバー付近という同一の誤った領域が
    映ってしまうことを確認した）。よってその方式は撤回し、Qtウィンドウを
    そのままキャプチャする方式に切り替えた。

    2026-08-08 実機検証で判明: network_editor.qtParentWindow() は
    「ネットワークエディタが実際に属するウィンドウ」ではなく、その時点で
    フォーカスを持つ別の最上位ウィンドウ（本チュートリアル生成エージェント
    自身のPython Panel＝tutorial_view.pyのChat/Graph/...タブUI）を返す
    ことがあり、生成された動画にNetworkEditorではなくPython Panel Editor
    の画面が映り込む不具合の原因だった（_flush_qt_events()によるrepaint
    待ちを追加しても、そもそも掴んでいるウィンドウ自体が別物なので直らな
    かった）。hou.qt.mainWindow() に切り替えて一意なメインウィンドウを
    掴むようにしたが、これでもなお不具合が再現した。

    2026-08-08 追加修正: hou.qt.mainWindow() は「Houdiniのメインウィンドウ
    そのもの」を確実に返すが、それは単なる開始点に過ぎない ── RAGChatBot
    パネル（Python Panel Editor）がユーザーのレイアウトでメインウィンドウに
    ドッキングされている場合、NetworkEditor と同じ1つのトップレベル
    ウィンドウの中に両方が同居することになる。ウィンドウ全体を grab()
    すると、その中の**すべての**ドッキング済みパネル（RAGChatBotパネルを
    含む）が一緒に写り込む。動画側のスライドはこの画像をそのまま縮小して
    使うため、画面占有率の大きい方（往々にしてRAGChatBotパネル）が
    目立って「NetworkEditorではなくPython Panel Editorが映っている」ように
    見えていた、というのが一連の不具合の本当の原因だった可能性が高い。
    _find_network_editor_widget() でメインウィンドウ配下からNetworkEditor
    ペイン単体に相当する子ウィジェットを探し、見つかればそれだけを
    grab() することで、他のドッキング済みパネルを写り込ませないようにする。
    見つからない場合（Houdiniのバージョン差異等）は、従来どおりウィンドウ
    全体をフォールバックとして使う。
    """
    try:
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor is None:
            _log("no NetworkEditor pane found in the current desktop", log_path)
            return False
        main_window = hou.qt.mainWindow()
        if main_window is None:
            _log("hou.qt.mainWindow() returned None", log_path)
            return False
        _flush_qt_events()  # 念のため grab() 直前にも repaint を確定させる

        target_widget = _find_network_editor_widget(network_editor, main_window, log_path)
        widget = target_widget if target_widget is not None else main_window
        pixmap = widget.grab()
        if width and height:
            from PySide6.QtCore import Qt as QtNamespace

            pixmap = pixmap.scaled(
                width,
                height,
                QtNamespace.KeepAspectRatio,
                QtNamespace.SmoothTransformation,
            )
        saved = bool(pixmap.save(str(output_path), "PNG"))
        if not saved:
            _log(f"pixmap.save() returned False for {output_path}", log_path)
        return saved
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        _log(f"network editor capture failed: {exc!r}", log_path)
        return False
