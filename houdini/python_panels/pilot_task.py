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
"""
from __future__ import annotations

# エラーを探すネットワークの入口。ここから下を、すべて見る。
SCAN_ROOTS = ("/obj", "/stage", "/mat", "/out")
SCAN_LIMIT = 20000  # 1回の採取で見るノードの上限（巨大なシーンで、画面を止めないため）

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


def scan_error_nodes(hou, roots=SCAN_ROOTS, limit: int = SCAN_LIMIT) -> set[str]:
    """いまエラー状態のノードのパス。hou は、Houdini の hou モジュール（テストでは、同じ形の偽物）。"""
    found: set[str] = set()
    scanned = 0
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
            if scanned > limit:
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
    def count(self) -> int | None:
        """一度でもエラーになったノードの数。測れなかった（hou が無い・1度も採取していない）ときは None。"""
        return len(self._paths) if self._hou is not None and self.samples > 0 else None

    def reset(self) -> None:
        self._paths = set()
        self.samples = 0


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def format_plan_header(plan: dict) -> str:
    if plan.get("finished"):
        return "3回すべて完了しました。ご協力ありがとうございました。"
    pid = plan.get("pid")
    who = f"（参加者 P{int(pid):02d}）" if pid else ""
    return f"第{plan['round']}回 / 3回{who}"


def survey_questions(condition: str) -> list[tuple]:
    """この条件で聞く質問。公式ドキュメントのみの回は、出典の質問を出さない。"""
    return [q for q in SURVEY_QUESTIONS if not (q[0] == "sourceUseful" and condition == "docs_only")]


def build_end_payload(session_id: str, reached, cook_nodes, self_mistakes, answers: dict, comment: str) -> dict:
    """課題を終えるときの送信内容。答えなかった項目は、送らない（空欄のまま）。"""
    survey = {k: int(v) for k, v in (answers or {}).items() if v in (1, 2, 3, 4, 5)}
    payload: dict = {
        "sessionId": session_id,
        "reached": None if reached is None else bool(reached),
        "cookErrorNodes": cook_nodes,
        "selfMistakes": self_mistakes if self_mistakes in (1, 2, 3, 4, 5) else None,
        "survey": survey,
        "comment": (comment or "").strip()[:1000],
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
