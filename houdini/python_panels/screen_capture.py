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
    映ってしまうことを確認した）。よってその方式は撤回し、
    qtParentWindow() が返すQtウィンドウ全体をそのままキャプチャする
    （ネットワークエディタ単体には絞れないが、実際に変化する内容が映る）。
    """
    try:
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor is None:
            _log("no NetworkEditor pane found in the current desktop", log_path)
            return False
        if not hasattr(network_editor, "qtParentWindow"):
            _log(
                "NetworkEditor pane tab has no qtParentWindow() on this "
                "Houdini build -- re-run dir() and report back",
                log_path,
            )
            return False
        widget = network_editor.qtParentWindow()
        if widget is None:
            _log("NetworkEditor pane's qtParentWindow() returned None", log_path)
            return False
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
