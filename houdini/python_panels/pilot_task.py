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

# 条件は、サーバーが決めて返す（運営が管理画面で、自動・全員ツール使用・全員ドキュメントのみ、を切り替える。2026-11-17）。
# 画面は、返ってきた値に従って、どちらの条件かをはっきり出す（パネル側で、番号から決め直さない）。
CONDITION_LABEL = {"system": "ツール使用", "docs_only": "ドキュメントのみ"}
CONDITION_TEXT = {
    "system": "【条件: ツール使用】本システム（チャット・チュートリアル生成）を使って行ってください。",
    "docs_only": "【条件: ドキュメントのみ】この課題は「公式ドキュメント・Web検索のみ」で行ってください。このパネルのチャットとチュートリアル生成は使わないでください（使った記録は、集計で確認されます）。",
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

# ── 学びの確認（2026-11-22）─────────────────────────────────────────────────
# 本システムの目的は、チュートリアルの生成物を作れるようになることではなく、作られたものを追って、Houdini（DCC ツール）の中身
# （ノードの組み合わせ・使い方）を理解し、自分の制作に使えるようになること。それが達成されているかを、事前と事後の同じ質問で比べる。
# すべて任意（答えなくても送れる）。所要時間は、1 コマ（約 90 分）に収めるため、事前 約 2 分・事後 約 4 分に抑える。
GOAL_ENDS = ("完成物（作品）を、手早く作れるようになること", "Houdini の仕組み（ノードのつながり・原理）を理解すること")
GOAL_PRE_QUESTION = ("goalPre", "この実験で、あなたが得たいものは、どちらに近いですか", *GOAL_ENDS)
GOAL_POST_QUESTION = ("goalPost", "いま、あなたが学びたいものは、どちらに近いですか", *GOAL_ENDS)
GOAL_USED_QUESTION = ("goalUsed", "本システムを、主にどう使いましたか", "答え・完成物を出してもらうため", "作られた中身を追って、仕組みを理解するため")
# 事前と事後で、同じ文面を聞く（差を見る）。キーは、事前は末尾に Pre を付ける（selfHowPre）。
SELF_ITEMS = (
    ("selfHow", "できあがった（作られた）ネットワークを見て、それぞれのノードが何をしているか、説明できる", "まったくできない", "よくできる"),
    ("selfExplore", "初めて見るノードでも、Reference やドキュメントで調べて、使い方を判断できる", "まったくできない", "よくできる"),
    ("selfWhat", "Houdini が何をするツールか（ほかの DCC ツールと何が違うか）、人に説明できる", "まったくできない", "よくできる"),
)
LEARNED_QUESTION = ("learned", "この時間で、Houdini について、新しく理解できたことがありましたか", "ほとんどなかった", "たくさんあった")
HOUDINI_DEF_QUESTION = "Houdini とは、どんなツールだと思いますか。知っている範囲で、自分の言葉で、一言で"
EXPLAIN_OWN_QUESTION = "できあがったネットワークから、ノードを 1 つ選んで、そのノードが何をしているか、なぜそのつながりなのかを、自分の言葉で書いてください"
FUN_QUESTION = "やってみて、何が楽しかったですか（どの場面でも）"
ESSAY_MAX = {"explainOwn": 600, "houdiniDef": 300, "fun": 400}  # Worker（pilotTasks.ts の ESSAY_MAX）と同じ
LEARNING_NOTE = {"profile": "約 2 分", "fixed": "約 4 分", "free": "約 1 分"}  # 1 コマ（約 90 分）に収めるための目安（画面に出す）

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
        return "課題はすべて完了しました。ご協力ありがとうございました。"
    pid = plan.get("pid")
    who = f"（参加者 P{int(pid):02d}）" if pid else ""
    if plan.get("completed"):  # 固定課題を終えた。自由課題は任意（1コマに収めるため。時間が余ったときだけ）
        return f"固定課題は完了しました。自由課題は、時間があるときだけ{who}"
    if plan.get("canStart") is False or plan.get("round") is None:
        return f"いま、課題は受け付けていません{who}"
    label = (plan.get("roundLabel") or "").strip()  # 回の期間（運営が管理画面で決める。「11/16〜11/21」など）
    return f"第{plan['round']}回{f'（{label}）' if label else ''}{who}"


def format_history_line(item: dict) -> str:
    """「完了した記録」の1行。"""
    seconds = item.get("durationSec")
    took = f"　{max(1, round(seconds / 60))}分" if isinstance(seconds, (int, float)) else ""
    return f"第{item.get('round')}回 {KIND_TEXT.get(item.get('kind'), '')}: {item.get('label', '')}{took}"


def format_task_title(kind: str, item: dict) -> str:
    """課題カードの見出し。条件（ツール使用／ドキュメントのみ）を、題材と並べてはっきり出す。自由課題は任意。"""
    optional = "（任意）" if item.get("optional") else ""
    label = CONDITION_LABEL.get(item.get("condition"))
    return f"{KIND_TEXT.get(kind, kind)}{optional}: {item.get('label', '')}" + (f"［{label}］" if label else "")


def apply_started(plan: dict | None, started: dict) -> dict | None:
    """課題を始めたときにサーバーが返した題材・条件を、手元の plan に反映する。

    運営が、受け付けの途中で条件の割り当てを切り替えたとき、画面に出ていた古い plan の条件ではなく、
    実際に記録された条件（サーバーの値）を出すため。plan が無ければ、何もしない。"""
    if not plan:
        return plan
    item = plan.get(started.get("kind"))
    if isinstance(item, dict):
        for key in ("taskId", "label", "condition"):
            if started.get(key):
                item[key] = started[key]
        item["active"] = True
    return plan


def survey_questions(condition: str) -> list[tuple]:
    """この条件で聞く質問。公式ドキュメントのみの回は、出典の質問を出さない。"""
    return [q for q in SURVEY_QUESTIONS if not (q[0] == "sourceUseful" and condition == "docs_only")]


def pre_questions() -> list[tuple]:
    """事前アンケートの、学びの確認の 1〜5 の質問（キー, 質問, 1 の意味, 5 の意味）。キーは、事後と区別するため Pre を付ける。"""
    return [GOAL_PRE_QUESTION, *[(f"{key}Pre", question, low, high) for key, question, low, high in SELF_ITEMS]]


def learning_questions(condition: str, kind: str) -> list[tuple]:
    """課題後アンケートの、学びの確認の 1〜5 の質問。固定課題だけ（自由課題は、任意で時間が余った人だけなので、楽しかったことだけ聞く）。
    本システムの使い方は、本システムを使わない回（ドキュメントのみ）には聞かない。"""
    if kind != "fixed":
        return []
    questions = [GOAL_POST_QUESTION, GOAL_USED_QUESTION, *SELF_ITEMS, LEARNED_QUESTION]
    return [q for q in questions if not (q[0] == "goalUsed" and condition == "docs_only")]


def essay_questions(kind: str) -> list[tuple]:
    """課題後アンケートの自由記述（キー, 質問）。固定課題は、Houdini とは何か・自分の言葉での説明・楽しかったこと。自由課題は、楽しかったことだけ。"""
    fun = ("fun", FUN_QUESTION)
    return [("houdiniDef", HOUDINI_DEF_QUESTION), ("explainOwn", EXPLAIN_OWN_QUESTION), fun] if kind == "fixed" else [fun]


LEARNING_KEYS = frozenset({"goalPost", "goalUsed", "selfHow", "selfExplore", "selfWhat", "learned"})  # 課題後（Worker の LEARNING_FIELDS と同じ）
PRE_KEYS = frozenset({"goalPre", "selfHowPre", "selfExplorePre", "selfWhatPre"})  # 事前


def _likert_only(values: dict | None, allowed=None) -> dict:
    """1〜5 の答えだけ。allowed があれば、そのキーだけ（知らないキーは送らない）。"""
    return {k: int(v) for k, v in (values or {}).items() if v in (1, 2, 3, 4, 5) and (allowed is None or k in allowed)}


def _essays_only(essays: dict | None) -> dict:
    return {k: str(v).strip()[:ESSAY_MAX[k]] for k, v in (essays or {}).items() if k in ESSAY_MAX and str(v or "").strip()}


def build_end_payload(session_id: str, reached, cook_nodes, self_mistakes, answers: dict, comment: str, paused_sec: int = 0,
                      learning: dict | None = None, essays: dict | None = None) -> dict:
    """課題を終えるときの送信内容。答えなかった項目は、送らない（空欄のまま）。

    paused_sec は、Houdini が閉じていた秒数（所要時間から引く）。振り返りの回答に使った秒数（surveySec）は、送る直前に足す。
    learning は学びの確認の 1〜5（goalPost・goalUsed・selfHow・selfExplore・selfWhat・learned）、essays は自由記述（houdiniDef・explainOwn・fun）。"""
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
    if _likert_only(learning, LEARNING_KEYS):
        payload["learning"] = _likert_only(learning, LEARNING_KEYS)
    if _essays_only(essays):
        payload["essays"] = _essays_only(essays)
    return payload


PROFILE_LEVELS = ("初心者", "初級", "中級", "上級")


def build_profile_payload(years: float, level: str, background: str, practice: str, tools: str, months: int = 0,
                          learning: dict | None = None, houdini_def: str = "") -> dict:
    """事前アンケートの送信内容。経験は、年と月で聞き、合計の月数（experienceMonths）と、年（月数 ÷ 12。分析の既存の列）で送る。
    learning は学びの確認の事前の 1〜5（goalPre・selfHowPre・selfExplorePre・selfWhatPre）、houdini_def は「Houdini とは」の自由記述。
    答えなかった項目は、送らない（サーバーは、すでにある値を消さない）。"""
    total = max(0, min(720, round(float(years) * 12) + int(months)))
    payload = {
        "experienceMonths": total,
        "experienceYears": round(total / 12, 4),
        "selfLevel": level if level in PROFILE_LEVELS else "",
        "background": (background or "").strip()[:400],
        "practice": (practice or "").strip()[:400],
        "toolHistory": (tools or "").strip()[:400],
    }
    payload.update(_likert_only(learning, PRE_KEYS))
    if str(houdini_def or "").strip():
        payload["houdiniDefPre"] = str(houdini_def).strip()[:ESSAY_MAX["houdiniDef"]]
    return payload
