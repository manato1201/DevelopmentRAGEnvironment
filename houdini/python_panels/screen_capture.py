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
    かった）。hou.qt.mainWindow()（Houdini公式APIで、Houdini本体のメイン
    ウィンドウを常に一意に返す）を明示的に使うことで、ペインタブ経由の
    不安定な参照に頼らず、NetworkEditor/SceneViewerが実際に存在する
    デスクトップを確実にキャプチャする（ネットワークエディタ単体には
    絞れないが、少なくとも誤った別パネルが映り込むことはなくなる）。
    """
    try:
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor is None:
            _log("no NetworkEditor pane found in the current desktop", log_path)
            return False
        widget = hou.qt.mainWindow()
        if widget is None:
            _log("hou.qt.mainWindow() returned None", log_path)
            return False
        _flush_qt_events()  # 念のため grab() 直前にも repaint を確定させる
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
