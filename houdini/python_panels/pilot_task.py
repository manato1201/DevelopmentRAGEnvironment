"""
pilot_task.py — 実証実験の課題まわりの、Qt に依存しない部品（単体テストできる）

  ErrorSampler   … 課題の間に、cook エラーが出たノードを数える（hou を渡して、定期的に採取する）。
  format_*       … 画面に出す文言。
  build_end_payload … 課題を終えるときにサーバーへ送る内容。

cook エラー数について（定義）:
  課題の間、一定の間隔（と、終了時）にシーンを見て、エラー状態のノードの「パス」を集める。
  数えるのは、のべの回数ではなく、**一度でもエラーになったノードの数**。
  採取の合間に起きて、すぐ直されたエラーは数えられない（実際より少なくなりうる）。評価の集計は、この前提で読む。
  hou が無いとき（Houdini の外）は、測れないので None（空欄）を送る。0 とは区別する。
  1回の採取は、時間の上限（SCAN_BUDGET_SEC）を超えたら打ち切る（巨大なシーンで、画面を止めないため）。打ち切ったときは、
  実際より少なく数えうる。

途中で Houdini が閉じた・落ちたとき:
  課題の記録は、サーバーに残る（「続きから開始」で再開できる）。このPCにも、途中経過（エラーのノード・最後に生きていた時刻・
  中断の秒数）を残し（ProgressStore）、再開したときに引き継ぐ。閉じていた時間は「中断」として所要時間から引く。
  Houdini が固まっていた（落ちずに処理が重かった）だけの時間は、作業の時間なので、引かない。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# エラーを探すネットワークの入口。ここから下を、すべて見る。
SCAN_ROOTS = ("/obj", "/stage", "/mat", "/out")
SCAN_LIMIT = 20000  # 1回の採取で見るノードの上限（巨大なシーンで、画面を止めないため）
SCAN_BUDGET_SEC = 1.0  # 1回の採取に使う時間の上限
PAUSE_MIN_SEC = 40  # 再開までの空きがこれ以上なら、Houdini が閉じていた（中断）とみなす（採取の間隔 20 秒の倍）
MAX_SAVED_PATHS = 2000

CONDITION_TEXT = {
    "system": "本システム（チャット・チュートリアル生成）を使って構いません。",
    "docs_only": "この回は「公式ドキュメント・Web検索のみ」で行ってください。このパネルのチャットとチュートリアル生成は使わないでください（使った記録は、集計で確認されます）。",
}
KIND_TEXT = {"fixed": "固定課題", "free": "自由課題"}

# 課題後アンケート: (キー, 質問, 1 の意味, 5 の意味)。source_useful は、本システムを使わない回には出さない。
SURVEY_QUESTIONS = (
    ("difficulty", "この課題は、どれくらい難しかったですか", "とても易しい", "とても難しい"),
    ("clarity", "手順は、わかりやすかったですか", "わかりにくい", "わかりやすい"),
    ("focus", "作業への集中を妨げられましたか", "妨げられなかった", "とても妨げられた"),
    ("accuracyWorry", "回答や手順の正確性に不安を感じましたか", "不安はなかった", "とても不安だった"),
    ("sourceUseful", "提示された出典（参照先）は役立ちましたか", "役立たなかった", "とても役立った"),
    ("reuse", "また使いたいと思いますか", "使いたくない", "ぜひ使いたい"),
)
SELF_MISTAKE_QUESTION = ("selfMistakes", "ビジュアル操作（ビューポートでの操作・見た目の調整）での操作ミスは、多かったですか", "ほとんどなかった", "とても多かった")


def scan_error_nodes(hou, roots=SCAN_ROOTS, limit: int = SCAN_LIMIT, budget_sec: float = SCAN_BUDGET_SEC, clock=time.monotonic) -> set[str]:
    """いまエラー状態のノードのパス。hou は、Houdini の hou モジュール（テストでは、同じ形の偽物）。"""
    found: set[str] = set()
    scanned = 0
    deadline = clock() + budget_sec
    for root in roots:
        try:
            top = hou.node(root)
            if top is None:
                continue
            nodes = top.allSubChildren()
        except Exception:  # noqa: BLE001 -- 採取の失敗で、課題を止めない
            continue
        for node in nodes:
            scanned += 1
            if scanned > limit or (scanned % 64 == 0 and clock() > deadline):
                return found
            try:
                if node.errors():
                    found.add(node.path())
            except Exception:  # noqa: BLE001
                continue
    return found


class ErrorSampler:
    """課題の間に、エラーになったノードを集める。hou が無い（None）ときは、測れないので count が None。"""

    def __init__(self, hou=None) -> None:
        self._hou = hou
        self._paths: set[str] = set()
        self.samples = 0

    @property
    def measurable(self) -> bool:
        return self._hou is not None

    def sample(self) -> int | None:
        if self._hou is None:
            return None
        self._paths |= scan_error_nodes(self._hou)
        self.samples += 1
        return len(self._paths)

    @property
    def paths(self) -> list[str]:
        return sorted(self._paths)

    def restore(self, paths) -> None:
        """再開のとき、前に集めたエラーのノードを引き継ぐ。"""
        self._paths |= {str(p) for p in paths or []}

    @property
    def count(self) -> int | None:
        """一度でもエラーになったノードの数。測れなかった（hou が無い・1度も採取していない）ときは None。"""
        return len(self._paths) if self._hou is not None and self.samples > 0 else None

    def reset(self) -> None:
        self._paths = set()
        self.samples = 0


class ProgressStore:
    """課題の途中経過を、このPCに残す（Houdini が閉じた・落ちたあとの「続きから」のため）。1つの課題ぶんだけ。"""

    def __init__(self, path) -> None:
        self._path = Path(path)

    def save(self, session_id: str, error_paths, paused_sec: int, now: float) -> None:
        data = {"sessionId": session_id, "errorPaths": sorted(error_paths)[:MAX_SAVED_PATHS], "pausedSec": int(paused_sec), "lastSeen": float(now)}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # 残せなくても、課題は続けられる

    def load(self, session_id: str) -> dict | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("sessionId") == session_id else None

    def clear(self) -> None:
        try:
            self._path.unlink()
        except OSError:
            pass


def resume_state(saved: dict | None, now: float) -> tuple[set[str], int]:
    """再開のとき、引き継ぐエラーのノードと、中断の秒数（これまでの中断 + 今回の空き。短い空きは数えない）。"""
    if not saved:
        return set(), 0
    gap = max(0.0, now - float(saved.get("lastSeen") or now))
    paused = int(saved.get("pausedSec") or 0) + (int(gap) if gap >= PAUSE_MIN_SEC else 0)
    return {str(p) for p in saved.get("errorPaths") or []}, paused


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def format_plan_header(plan: dict) -> str:
    if plan.get("finished"):
        return "3回すべて完了しました。ご協力ありがとうございました。"
    pid = plan.get("pid")
    who = f"（参加者 P{int(pid):02d}）" if pid else ""
    return f"第{plan['round']}回 / 3回{who}"


def format_history_line(item: dict) -> str:
    """「完了した記録」の1行。"""
    seconds = item.get("durationSec")
    took = f"　{max(1, round(seconds / 60))}分" if isinstance(seconds, (int, float)) else ""
    return f"第{item.get('round')}回 {KIND_TEXT.get(item.get('kind'), '')}: {item.get('label', '')}{took}"


def survey_questions(condition: str) -> list[tuple]:
    """この条件で聞く質問。公式ドキュメントのみの回は、出典の質問を出さない。"""
    return [q for q in SURVEY_QUESTIONS if not (q[0] == "sourceUseful" and condition == "docs_only")]


def build_end_payload(session_id: str, reached, cook_nodes, self_mistakes, answers: dict, comment: str, paused_sec: int = 0) -> dict:
    """課題を終えるときの送信内容。答えなかった項目は、送らない（空欄のまま）。

    paused_sec は、Houdini が閉じていた秒数（所要時間から引く）。振り返りの回答に使った秒数（surveySec）は、送る直前に足す。"""
    survey = {k: int(v) for k, v in (answers or {}).items() if v in (1, 2, 3, 4, 5)}
    payload: dict = {
        "sessionId": session_id,
        "reached": None if reached is None else bool(reached),
        "cookErrorNodes": cook_nodes,
        "selfMistakes": self_mistakes if self_mistakes in (1, 2, 3, 4, 5) else None,
        "survey": survey,
        "comment": (comment or "").strip()[:1000],
        "pausedSec": max(0, int(paused_sec or 0)),
    }
    return payload


PROFILE_LEVELS = ("初心者", "初級", "中級", "上級")


def build_profile_payload(years: float, level: str, background: str, practice: str, tools: str) -> dict:
    return {
        "experienceYears": float(years),
        "selfLevel": level if level in PROFILE_LEVELS else "",
        "background": (background or "").strip()[:400],
        "practice": (practice or "").strip()[:400],
        "toolHistory": (tools or "").strip()[:400],
    }
