"""
tutorial_review.py — 生成したチュートリアルが「教えるレッスン」になっているかの採点（2026-10-20）

これまでの生成物は、ノードを組んだ記録（手順の羅列）になりがちで、プロの解説動画にある
  ・「〜とは？」から始まる考え方の説明
  ・各段階で「ここでこう見えれば正しい」という確認ポイント
  ・パラメータを動かして、効果を見せる実験
  ・仕上げと、次のレッスンへの橋渡し
が欠けていた。ここでは、それらが揃っているかを機械的に採点する（Claudeは呼ばない。Houdiniも不要）。

使い道は2つ:
  1. finish_tutorial を受け取った時点で、足りない項目をモデルに返して書き足させる（houdini_tools.py）
  2. 生成の自動指標（metrics）に点数を残し、改善の効果を測る（tutorial_agent.py）
"""

from __future__ import annotations

import re

# finish_tutorial の「レッスン用の項目」。キー → (日本語の名前, 書き方の指示)
LESSON_FIELDS: dict[str, tuple[str, str]] = {
    "learn": ("このレッスンで学ぶこと", "身につくことを2〜4個の箇条書きで"),
    "concepts": (
        "先に知っておく考え方",
        "初めて出る用語を一言で説明し、仕組み全体を日常のたとえで1つ説明する（Markdown。用語ごとに箇条書き）",
    ),
    "experiments": (
        "パラメータを動かして確かめよう",
        "実際に set_parameter で値を変えて cook_node し、どう変わったかを2〜3個。"
        "「ノード.パラメータ: 値A → 値B で、〇〇がこう変わる」の形で。終わったら値を元に戻すこと",
    ),
    "polish": ("仕上げ", "見た目を整える1〜2個の操作（色・密度・大きさ・向きなど）と、その効果"),
    "next_lesson": ("次のレッスン", "このレッスンの次に学ぶとよいこと（1〜2個）と、そのために今回の内容がどう役立つか"),
}

CHECKPOINT_MARK = "✅"
MIN_CHECKPOINTS = 2
MIN_EXPERIMENTS = 2

# 各項目の配点（合計100）
_WEIGHTS: dict[str, int] = {
    "learn": 8,
    "concepts": 14,
    "checkpoints": 16,
    "experiments_written": 12,
    "experiments_done": 14,
    "verified_numerically": 8,
    "polish": 8,
    "pitfalls": 6,
    "next_lesson": 6,
    "steps_explain_why": 8,
}

_WHY_RE = re.compile(r"ため|ので|理由|なぜ|から(?:です|だ|。)|役割|目的")
_STEP_LINE_RE = re.compile(r"^\s*(?:\d+[.)．]|[-*]\s)", re.M)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _items(text: str) -> int:
    """箇条書き（- / * / 番号）の行数。無ければ、空でない文があれば1。"""
    n = len(_STEP_LINE_RE.findall(text))
    return n if n else (1 if text.strip() else 0)


def missing_lesson_fields(finish: dict) -> list[str]:
    """finish_tutorial の入力で、書かれていないレッスン用の項目のキー。"""
    return [key for key in LESSON_FIELDS if len(_text(finish.get(key))) < 12]


def count_checkpoints(steps_text: str) -> int:
    return steps_text.count(CHECKPOINT_MARK)


def count_verified_experiments(step_log: list[dict]) -> int:
    """実際に「値を変えて、もう一度 cook した」回数。最初の cook 成功より後の set_parameter のあとに cook_node が続いた数。"""
    cooked_ok = False
    changed_since_cook = False
    done = 0
    for entry in step_log:
        tool = entry.get("tool")
        failed = bool(entry.get("is_error")) or "[エラー]" in str(entry.get("result", ""))
        if tool == "cook_node" and not failed:
            if cooked_ok and changed_since_cook:
                done += 1
            cooked_ok = True
            changed_since_cook = False
        elif tool == "set_parameter" and cooked_ok and not failed:
            changed_since_cook = True
    return done


def review_finish(finish: dict, step_log: list[dict] | None = None) -> dict:
    """採点。戻り値: {"score": 0-100, "checks": {名前: bool}, "missing": [人が読める不足項目]}。"""
    step_log = step_log or []
    steps = _text(finish.get("steps"))
    checks: dict[str, bool] = {}
    missing: list[str] = []

    def put(key: str, ok: bool, label: str) -> None:
        checks[key] = ok
        if not ok:
            missing.append(label)

    put("learn", len(_text(finish.get("learn"))) >= 12, "学ぶこと")
    put("concepts", len(_text(finish.get("concepts"))) >= 40, "考え方（用語とたとえ）")
    put("checkpoints", count_checkpoints(steps) >= MIN_CHECKPOINTS, f"各段階の確認ポイント（{CHECKPOINT_MARK} を{MIN_CHECKPOINTS}個以上）")
    put("experiments_written", _items(_text(finish.get("experiments"))) >= MIN_EXPERIMENTS, f"パラメータ実験（{MIN_EXPERIMENTS}個以上）")
    put("experiments_done", count_verified_experiments(step_log) >= MIN_EXPERIMENTS, "実験の実行（値を変えて cook_node）")
    inspected = sum(1 for e in step_log if e.get("tool") == "inspect_geometry" and not e.get("is_error"))
    put("verified_numerically", inspected >= 1, "数値での確認（inspect_geometry）")
    put("polish", len(_text(finish.get("polish"))) >= 12, "仕上げ")
    put("pitfalls", len(_text(finish.get("pitfalls"))) >= 12, "つまずきやすい点")
    put("next_lesson", len(_text(finish.get("next_lesson"))) >= 12, "次のレッスン")

    step_lines = [ln for ln in steps.splitlines() if _STEP_LINE_RE.match(ln)]
    if step_lines:
        why = sum(1 for ln in step_lines if _WHY_RE.search(ln))
        put("steps_explain_why", why / len(step_lines) >= 0.5, "手順に「なぜそうするか」")
    else:
        put("steps_explain_why", False, "手順に「なぜそうするか」")

    score = sum(_WEIGHTS[k] for k, ok in checks.items() if ok)
    return {"score": score, "checks": checks, "missing": missing}


def finish_gap_message(finish: dict) -> str:
    """finish_tutorial の返答に付ける「書き足してください」。足りなければ空文字ではなく案内文、揃っていれば空文字。"""
    absent = missing_lesson_fields(finish)
    lines: list[str] = [
        f"- `{key}`（{LESSON_FIELDS[key][0]}）: {LESSON_FIELDS[key][1]}" for key in absent
    ]
    if count_checkpoints(_text(finish.get("steps"))) < MIN_CHECKPOINTS:
        lines.append(
            f"- `steps` の各章の終わりに、{CHECKPOINT_MARK} 確認ポイント（「ここで〇〇が見えれば正しい」。"
            f"数値や見た目で）を書く（{MIN_CHECKPOINTS}個以上）"
        )
    if not lines:
        return ""
    return (
        "【書き足しが必要です】この生成物は「手順の記録」で止まっています。初心者が理解できるレッスンにするため、"
        "次を加えてから finish_tutorial を呼び直してください（confirm_tutorial はそのあとに）。"
        "すでに実際に確かめた内容だけを書き、確かめていないことは書かないこと。\n" + "\n".join(lines)
    )


def summarize(report: dict) -> str:
    """進行表示用の1行。"""
    text = f"レッスン品質チェック: {report['score']}/100"
    if report["missing"]:
        text += "（不足: " + "、".join(report["missing"][:4]) + ("…" if len(report["missing"]) > 4 else "") + "）"
    return text
