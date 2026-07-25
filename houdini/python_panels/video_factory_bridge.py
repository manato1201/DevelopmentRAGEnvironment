"""
video_factory_bridge.py — LearningQt の動画生成エンジンをHoudini側から起動する

tutorial_view.py::_on_save がチュートリアルの .md/.json を保存した直後に呼ぶ:
  1. HoudiniToolExecutor が生成中に既に撮影済みの per-step スクリーンショット
     一覧（step_screenshots）を <slug>_screenshots.json マニフェストとして書く
  2. video_factory_cloudrag_poc.exe を --houdini-md/--houdini-json/
     --houdini-screenshots 付きで非同期起動する

起動は rag_chatbot.py の RAG local bridge 起動パターン（subprocess.Popen、
プロセスの完了は待たない）を踏襲している。Houdini のUIをブロックしないことを
優先し、動画生成の成否そのものはこのプロセスからは追跡しない（Webダッシュ
ボードに公開されるまで数分かかるため、ここで待つのはそもそも不適切）。

stdout/stderrはDEVNULLではなく <slug>_video_factory.log へ書く -- 初回の実機
テストで「音声が入っていない」不具合が報告されたが、そのときはstderrが
DEVNULLへ捨てられていて main_cloudrag.cpp 側のログ（narration synthesis
failed等）が一切見えなかった。ログをファイルに残すことで次回以降は原因が
追える。

ベストエフォート: どの段階が失敗してもチュートリアル保存自体は既に成功して
いるので、例外を外に投げず、状態表示用の短い文字列を返すだけに留める。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def launch_video_generation(
    md_path: Path,
    json_path: Path,
    sandbox_path: str,
    step_screenshots: list[dict],
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

    screenshots_path = md_path.with_name(md_path.stem + "_screenshots.json")
    log_path = md_path.with_name(md_path.stem + "_video_factory.log")

    try:
        screenshots_path.write_text(
            json.dumps(step_screenshots, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        return f"動画生成: スクリーンショット一覧の書き出しに失敗しました: {exc}"

    args = [
        exe_path,
        "--houdini-md",
        str(md_path),
        "--houdini-json",
        str(json_path),
        "--houdini-screenshots",
        str(screenshots_path),
    ]

    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            subprocess.Popen(args, stdout=log_file, stderr=subprocess.STDOUT)
    except OSError as exc:
        return f"動画生成の起動に失敗しました: {exc}"

    shot_count = sum(1 for s in step_screenshots if s.get("viewport") or s.get("network"))
    if shot_count:
        return (
            f"動画生成をバックグラウンドで開始しました（スクリーンショット{shot_count}件 / "
            f"ログ: {log_path.name}）"
        )
    return (
        "動画生成をバックグラウンドで開始しました（スクリーンショットなし。"
        f"ログ: {log_path.name}）"
    )
