"""
video_factory_bridge.py — LearningQt の動画生成エンジンをHoudini側から起動する

tutorial_view.py::_on_save がチュートリアルの .md/.json を保存した直後に呼ぶ:
  1. 3Dビューポート／ネットワークエディタのスクリーンショットを撮影（screen_capture.py）
  2. video_factory_cloudrag_poc.exe を --houdini-md/--houdini-json/
     --houdini-viewport/--houdini-network 付きで非同期起動する

起動は rag_chatbot.py の RAG local bridge 起動パターン（subprocess.Popen +
stdout/stderrをDEVNULLへ、プロセスの完了は待たない）を踏襲している。Houdini
のUIをブロックしないことを優先し、動画生成の成否そのものはこのプロセスからは
追跡しない（Webダッシュボードに公開されるまで数分かかるため、ここで待つのは
そもそも不適切）。

ベストエフォート: どの段階が失敗してもチュートリアル保存自体は既に成功して
いるので、例外を外に投げず、状態表示用の短い文字列を返すだけに留める。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from screen_capture import capture_network_editor, capture_viewport, focus_network_on


def launch_video_generation(
    md_path: Path,
    json_path: Path,
    sandbox_path: str,
    exe_path: str,
) -> str:
    """
    動画生成を非同期で起動する。呼び出し元（tutorial_view.py の状態ラベル）に
    そのまま表示できる短い日本語メッセージを返す。例外は投げない。
    """
    if not exe_path:
        return "動画生成: video_factory_exe_path が未設定のためスキップしました（Settingsタブで設定してください）"
    if not Path(exe_path).exists():
        return f"動画生成: exeが見つかりません: {exe_path}"

    viewport_png = md_path.with_name(md_path.stem + "_viewport.png")
    network_png = md_path.with_name(md_path.stem + "_network.png")

    if sandbox_path:
        focus_network_on(sandbox_path)
    got_viewport = capture_viewport(viewport_png)
    got_network = capture_network_editor(network_png)

    args = [
        exe_path,
        "--houdini-md",
        str(md_path),
        "--houdini-json",
        str(json_path),
    ]
    if got_viewport:
        args += ["--houdini-viewport", str(viewport_png)]
    if got_network:
        args += ["--houdini-network", str(network_png)]

    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return f"動画生成の起動に失敗しました: {exc}"

    shots = []
    if got_viewport:
        shots.append("ビューポート")
    if got_network:
        shots.append("ネットワーク")
    shots_desc = "・".join(shots) if shots else "スクリーンショットなし"
    return f"動画生成をバックグラウンドで開始しました（{shots_desc}）"
