"""
screen_capture.py — Houdini ビューポート／ネットワークエディタのスクリーンショット取得

LearningQt の動画生成エンジン（video_factory_cloudrag_poc.exe）が右パネルに
「実際のHoudini画面」を表示できるよう、チュートリアル保存直後
（tutorial_view.py::_on_save、video_factory_bridge.py 経由）に呼ばれる。

重要な注意: この関数群はHoudini実機の無い環境で書かれており、未検証。
特に capture_network_editor() は、ビューポートの hou.SceneViewer.flipbook() の
ような「1枚だけ画像として保存する」公式APIがネットワークエディタ側には無いため、
ペインのQtウィジェットを直接 grab() するフォールバック実装になっている
（pane.qtWidget() が実際のHoudini 21 HOMに存在するかは未確認）。
動かない場合は Windows > Python Panel Editor の Python Shell で
`hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)` の返り値に対して
`dir(...)` を実行し、実際に使えるメソッド名でこのファイルを直してほしい。

いずれの関数もベストエフォート: 失敗時は例外を投げず False を返すだけ
（呼び出し元の tutorial_view.py::_on_save がチュートリアル保存そのものを
失敗させないため）。

2026-07-24 実機初回検証: 両キャプチャとも失敗し、PNGも作られずコンソールにも
何も出ない事例が確認された。Houdiniがコンソール非接続のGUIプロセスとして
起動されていると print() の行き先が無く消えるため、_log() でファイルにも
書くようにした（video_factory_bridge.py 側が <slug>_capture.log のパスを渡す）。
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
    ネットワークエディタのペインを指定ノード配下にフォーカス・フレームする。
    スクリーンショット撮影前に呼ぶことで、サンドボックス以外の無関係な
    ネットワークが映り込むのを防ぐ。失敗しても静かに諦める（ベストエフォート）。
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
    未検証のフォールバック実装 -- ファイル先頭の注意書き参照。
    """
    try:
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor is None:
            _log("no NetworkEditor pane found in the current desktop", log_path)
            return False
        # Real-Houdini dir() dump (21.0.700) confirmed there is no
        # qtWidget()/grab()/pixmap() on the pane tab itself -- the closest
        # available accessor is qtParentWindow(), which returns the Qt
        # window this pane lives in. We don't attempt to crop it down to
        # just this pane's rect (screenBounds()'s coordinate space/type
        # isn't verified against this Houdini build, and a wrong crop
        # would silently produce a garbled image rather than a clean
        # failure) -- grabbing the whole parent window is less precise but
        # robust, and still a real Houdini screenshot for the video.
        if not hasattr(network_editor, "qtParentWindow"):
            _log(
                "NetworkEditor pane tab has neither qtWidget() nor qtParentWindow() "
                "on this Houdini build -- re-run dir() and report back",
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
