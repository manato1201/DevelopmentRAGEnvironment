"""
video_progress.py — 動画生成の進捗（％と段階）を、ログから求める（2026-10-21）

動画の生成は、数分かかる。これまでは「フレーム N/M」の文字だけで、台本づくりと音声の間は
「準備中…」のまま、どこまで進んだか分からなかった。パネルのプログレスバー用に、段階ごとの
重みをつけた全体の％を求める。Qt にも Houdini にも依存しない（単体テストできる）。

段階（％は全体に対する範囲。実測の所要時間の比に近い）:
  0〜25  台本づくり（Claude。終わりが読めないので、時間の経過でゆっくり進める）
  25〜30 動画エンジンの起動・資料の読み込み・スライドの構成
  30〜70 音声の作成（エンジンが「Narration progress: k / n」を1スライドごとに出す）
  70〜98 描画（「Rendered frame N / M」）
  100    完了（「Wrote <ファイル>.webm」）
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

SCRIPT_END = 25
ENGINE_START = 25
NARRATION_START, NARRATION_END = 30, 70
RENDER_START, RENDER_END = 70, 98

_NARRATION_PROGRESS = re.compile(r"Narration progress: (\d+) / (\d+)")
_RENDER_PROGRESS = re.compile(r"Rendered frame (\d+) / (\d+)")
_WROTE = re.compile(r"Wrote (\S+\.webm)")


@dataclass
class VideoProgress:
    percent: int = 0
    stage: str = ""          # script / start / narration / render / done / failed
    label: str = ""          # 画面に出す短い日本語
    done: bool = False
    failed: bool = False
    webm: str = ""           # 完了時のファイル名


def script_stage_percent(elapsed_seconds: float, tau: float = 25.0) -> int:
    """台本づくり（Claudeの呼び出し）の間の％。終わりが読めないので、SCRIPT_END に近づくだけで、超えない。"""
    if elapsed_seconds <= 0:
        return 0
    return min(SCRIPT_END - 1, int((SCRIPT_END - 1) * (1 - math.exp(-elapsed_seconds / tau))))


def _scale(done: int, total: int, start: int, end: int) -> int:
    if total <= 0:
        return start
    return start + int((end - start) * min(max(done / total, 0.0), 1.0))


def progress_from_log(text: str) -> VideoProgress:
    """動画エンジンのログ全文から、現在の進捗を求める。"""
    wrote = _WROTE.search(text)
    if wrote:
        return VideoProgress(100, "done", "完了", done=True, webm=wrote.group(1))

    # 失敗は、エンジンが「ERROR:」で始まる行を出したときだけ。ログのどこかに「エラー」「ERROR」の文字があるだけでは、
    # 失敗にしない（スライドの見出しに「エラーが出ないか確かめる」などが入るため。2026-10-21、実機で誤判定を確認）。
    error_lines = [ln for ln in text.splitlines() if ln.startswith("ERROR:")]
    failed = bool(error_lines)
    last_line = error_lines[-1][:80] if error_lines else ""

    render = None
    for line in reversed(text.splitlines()):
        render = _RENDER_PROGRESS.search(line)
        if render:
            break
    if render:
        done, total = int(render.group(1)), int(render.group(2))
        p = VideoProgress(_scale(done, total, RENDER_START, RENDER_END), "render", f"描画中 {done}/{total} フレーム")
    elif "Narration synthesized" in text or "Narration synthesis failed" in text or "Video duration" in text:
        p = VideoProgress(NARRATION_END, "render", "描画の準備中")
    else:
        narration = None
        for line in reversed(text.splitlines()):
            narration = _NARRATION_PROGRESS.search(line)
            if narration:
                break
        if narration:
            k, n = int(narration.group(1)), int(narration.group(2))
            p = VideoProgress(_scale(k, n, NARRATION_START, NARRATION_END), "narration", f"音声を作成中 {k}/{n}")
        elif "Synthesizing" in text:
            p = VideoProgress(NARRATION_START, "narration", "音声を作成中")
        elif "Split into" in text or "Beginner script applied" in text:
            p = VideoProgress(NARRATION_START - 2, "start", "スライドを構成しました")
        elif "Loading Houdini tutorial" in text:
            p = VideoProgress(ENGINE_START + 2, "start", "資料を読み込み中")
        else:
            p = VideoProgress(ENGINE_START, "start", "動画エンジンを準備中")

    if failed:
        p.failed = True
        p.stage = "failed"
        p.label = f"失敗の可能性: {last_line}"
    return p
