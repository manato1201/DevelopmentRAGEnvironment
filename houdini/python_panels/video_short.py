"""
video_short.py — 動画の「短縮版」: 要点の手順だけを選ぶ（2026-11-19）

背景: 実証実験は、1 人 90 分。チュートリアルの生成と動画の生成に、合わせて 15 分以上かかっていた。実機の記録（2026-11-18）:
  炎のエネルギー: 生成 368 秒 + 台本 約 1 分 + 動画（音声 579 秒 + 描画 295 秒）= 約 22 分。動画は 1390 秒（23 分）、ナレーション 8124 文字、74 スライド。
  らせんの光: 生成 244 秒 + 動画（音声 301 秒 + 描画 203 秒）。動画は 858 秒（14 分）。
  動画の長さは、ナレーションの文字数にほぼ比例する（6 文字 / 秒）。参加者は、23 分の動画を、90 分の中で見られない。
  → 動画は、要点の手順だけの「短縮版」（約 3〜4 分）にする。手順書（Markdown）と Guide には、全部の手順が残る。

  ・select_steps(steps)    … 動画に出す手順を選ぶ（順番は保つ）。最初・最後・コード・つなぎ・結果の確認を優先する
  ・length_mode(cfg)       … 設定 "video_length" から "short" / "full"（既定は short）
  ・engine_args(mode)      … 動画エンジンに足す引数（短縮版なら ["--short"]。エンジンは、節のスライドを作らない）

手順書・Guide・保存する内容は変えない。動画に渡す、スクリーンショットの一覧と台本の手順だけを、選んだものにする。
Qt にも Houdini にも依存しない（単体テストできる）。
"""

from __future__ import annotations

SHORT = "short"
FULL = "full"
SHORT_MAX_STEPS = 10        # 約 10 手順 × 100 文字 + 冒頭・まとめ = 約 1500 文字 = 約 4 分
SHORT_MAX_CODE_STEPS = 4    # コードの手順は、この件数まで（コードだけが続くと、画面が単調で、動画が分かりにくい）
SHORT_MAX_COOK_STEPS = 3    # 結果の確認（cook）は、この件数まで（結果の画面が、いくつも続かないように）
CONFIG_KEY = "video_length"

# 手順の重み（大きいほど、動画に残す）
_SCORE_FIRST = 100
_SCORE_LAST = 100
_SCORE_COOK = 40
_SCORE_CODE = 50
_SCORE_CONNECT = 45
_SCORE_PARAM_BASE = 20
_SCORE_PARAM_PER_CHANGE = 4
_SCORE_CREATE = 12


def length_mode(cfg: dict | None) -> str:
    """設定の動画の長さ。"full" のときだけ完全版。それ以外（無い・不正）は、短縮版。"""
    value = str((cfg or {}).get(CONFIG_KEY, SHORT) or SHORT).strip().lower()
    return FULL if value == FULL else SHORT


def engine_args(mode: str) -> list[str]:
    """動画エンジンに足す引数。"""
    return ["--short"] if mode == SHORT else []


def _is_code_step(step: dict) -> bool:
    capture = step.get("capture")
    return isinstance(capture, dict) and capture.get("kind") == "code_card"


def _change_count(step: dict) -> int:
    changes = step.get("changes")
    return len(changes) if isinstance(changes, list) else 0


def score(step: dict, is_first: bool, is_last: bool) -> int:
    """1 手順の重み。"""
    tool = str(step.get("tool") or "")
    total = 0
    if is_first:
        total += _SCORE_FIRST
    if is_last:
        total += _SCORE_LAST
    if tool == "cook_node":
        total += _SCORE_COOK
    elif tool == "connect_nodes":
        total += _SCORE_CONNECT
    elif tool == "set_parameter":
        total += _SCORE_PARAM_BASE + _SCORE_PARAM_PER_CHANGE * min(_change_count(step), 5)
        if _is_code_step(step):
            total += _SCORE_CODE
    elif tool == "create_node":
        total += _SCORE_CREATE
    return total


def select_steps(
    steps: list[dict], max_steps: int = SHORT_MAX_STEPS, max_code: int = SHORT_MAX_CODE_STEPS, max_cook: int = SHORT_MAX_COOK_STEPS,
) -> list[dict]:
    """動画に出す手順を選ぶ（元の順番を保つ）。max_steps 以下なら、全部。
    点数の高い順に max_steps 件を選ぶ。同点は、後の手順より前の手順を優先（流れの最初を残す）。
    コードの手順は max_code 件、cook（結果の確認）は max_cook 件まで（最初と最後の手順は、数えず、必ず残す）。
    cook_node（結果の確認）は、最後の 1 件を必ず入れる（結果が、動画のどこかに出るように）。"""
    items = [s for s in (steps or []) if isinstance(s, dict)]
    if max_steps <= 0:
        return []
    if len(items) <= max_steps:
        return list(items)
    last = len(items) - 1
    ranked = sorted(range(len(items)), key=lambda i: (-score(items[i], i == 0, i == last), i))
    chosen: set[int] = set()
    code_count = cook_count = 0
    for i in ranked:
        if len(chosen) >= max_steps:
            break
        if i not in (0, last):
            if _is_code_step(items[i]):
                if code_count >= max_code:
                    continue
                code_count += 1
            elif items[i].get("tool") == "cook_node":
                if cook_count >= max_cook:
                    continue
                cook_count += 1
        chosen.add(i)
    for i in ranked:  # コードの上限で足りなくなったら、残りで埋める（max_steps 件にそろえる）
        if len(chosen) >= max_steps:
            break
        chosen.add(i)
    cooks = [i for i, s in enumerate(items) if s.get("tool") == "cook_node"]
    if cooks and not any(i in chosen for i in cooks[-1:]):
        weakest = max(chosen, key=lambda i: (-score(items[i], i == 0, i == last), -i))  # いちばん点の低い（同点なら後ろの）手順を、外す
        if weakest not in (0, last):
            chosen.discard(weakest)
            chosen.add(cooks[-1])
    return [items[i] for i in sorted(chosen)]


def step_numbers(steps: list[dict]) -> list[int]:
    """手順の番号（step_screenshots の "step"）の一覧。"""
    out: list[int] = []
    for s in steps or []:
        try:
            out.append(int(s.get("step")))
        except (TypeError, ValueError):
            continue
    return out


def describe(total: int, kept: int, mode: str) -> str:
    """画面に出す 1 文。"""
    if mode != SHORT or kept >= total:
        return ""
    return f"動画は短縮版（{total} 手順のうち {kept} 手順。手順書と Guide には、全部の手順があります）"
