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
"""

from __future__ import annotations

from pathlib import Path

import hou


def focus_network_on(node_path: str) -> None:
    """
    ネットワークエディタのペインを指定ノード配下にフォーカス・フレームする。
    スクリーンショット撮影前に呼ぶことで、サンドボックス以外の無関係な
    ネットワークが映り込むのを防ぐ。失敗しても静かに諦める（ベストエフォート）。
    """
    try:
        node = hou.node(node_path)
        if node is None:
            return
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor is None:
            return
        network_editor.setCurrentNode(node)
        network_editor.setPwd(node)
        network_editor.homeToSelection()
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        print(f"[screen_capture] focus_network_on failed: {exc}")


def capture_viewport(output_path: Path, width: int = 1280, height: int = 720) -> bool:
    """
    現在の3Dビューポートを1枚の静止画として output_path に保存する。
    hou.SceneViewer.flipbook()（Houdiniの標準ビューポート書き出しAPI）を
    現在フレームだけの1フレームレンジで呼び出す実装。
    """
    try:
        scene_viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if scene_viewer is None:
            print("[screen_capture] no SceneViewer pane found")
            return False
        settings = hou.FlipbookSettings()
        current_frame = hou.frame()
        settings.frameRange((current_frame, current_frame))
        settings.output(str(output_path))
        settings.outputToMPlay(False)
        settings.resolution((width, height))
        scene_viewer.flipbook(scene_viewer.curViewport(), settings)
        return output_path.exists()
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        print(f"[screen_capture] viewport capture failed: {exc}")
        return False


def capture_network_editor(
    output_path: Path, width: int = 1280, height: int = 720
) -> bool:
    """
    現在のネットワークエディタペインをスクリーンショットとして保存する。
    未検証のフォールバック実装 -- ファイル先頭の注意書き参照。
    """
    try:
        network_editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if network_editor is None:
            print("[screen_capture] no NetworkEditor pane found")
            return False
        widget = network_editor.qtWidget()
        if widget is None:
            print("[screen_capture] NetworkEditor pane has no qtWidget()")
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
        return bool(pixmap.save(str(output_path), "PNG"))
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
        print(f"[screen_capture] network editor capture failed: {exc}")
        return False
