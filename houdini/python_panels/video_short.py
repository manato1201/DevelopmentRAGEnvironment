"""
video_short.py — 動画の「短縮版」: 全部の手順を、飛ばさずに、少ない場面にまとめる（2026-11-19 作成、2026-11-20 作り直し）

背景: 実証実験は、1 人 90 分。チュートリアルの生成と動画の生成に、合わせて 15 分以上かかっていた。実機の記録（2026-11-18）:
  炎のエネルギー: 生成 368 秒 + 台本 約 1 分 + 動画（音声 579 秒 + 描画 295 秒）= 約 22 分。動画は 1390 秒（23 分）、ナレーション 8124 文字、74 スライド。
  動画の長さは、ナレーションの文字数にほぼ比例する（6 文字 / 秒）。参加者は、23 分の動画を、90 分の中で見られない。

前の方式（2026-11-19）と、その問題（2026-11-20 に、実機の動画で確認）:
  点数の高い順に 10 手順だけを選んで動画にしていた。41 手順の動画で、1・7・12・13・17・19・27・31・34・41 が選ばれ、
  間の手順は動画に出なかった。ところが、動画エンジンは、見出しを「手順 1〜10」と振り直す。冒頭・まとめは、全体を語る。
  その結果、(1) 途中で話が飛ぶ（エラーを直した手順の次に、別の枝の話が始まる）、(2) 冒頭で約束した内容が、動画の終わりまでに出てこない、
  (3) 「手順 5」が、手順書の手順 5 ではない、という、中途半端な動画になった。

今の方式:
  ・全部の手順を、順番を保ったまま、連続した「場面」に分ける（group_steps）。場面の数は SHORT_MAX_GROUPS まで（約 4〜6 分）。
  ・場面の終わりは、結果の確認（cook）の手順に寄せる（確認できた状態が、その場面の最後の画面になる）。
  ・動画エンジンには、場面の最後の手順だけを渡す（画面は、その時点の、できあがった状態）。その手順に、場面に含まれる手順の番号と操作
    （"covers" / "covered"）を添える。台本を書くモデルは、それを見て、場面の中の操作を全部、順番に説明する（video_script.py）。
  ・手順が SHORT_MAX_GROUPS 以下なら、まとめない（1 手順 = 1 場面）。

手順書・Guide・保存する内容は変えない。動画に渡す、スクリーンショットの一覧と台本の手順だけが、場面になる。
Qt にも Houdini にも依存しない（単体テストできる）。
"""

from __future__ import annotations

SHORT = "short"
FULL = "full"
SHORT_MAX_GROUPS = 12       # 場面の数の上限。1 場面 約 30 秒（ナレーション 約 200 文字）で、約 6 分
CONFIG_KEY = "video_length"
COVERED_TEXT_MAX = 120      # 台本のモデルに渡す、含まれる手順の操作文の長さ（先頭の 1 行）
COVERED_MAX = 14            # 1 場面で、モデルに渡す、含まれる手順の数の上限


def length_mode(cfg: dict | None) -> str:
    """設定の動画の長さ。"full" のときだけ完全版。それ以外（無い・不正）は、短縮版。"""
    value = str((cfg or {}).get(CONFIG_KEY, SHORT) or SHORT).strip().lower()
    return FULL if value == FULL else SHORT


def engine_args(mode: str) -> list[str]:
    """動画エンジンに足す引数。"""
    return ["--short"] if mode == SHORT else []


def _is_cook(step: dict) -> bool:
    return str(step.get("tool") or "") == "cook_node"


def plan_groups(items: list[dict], max_groups: int = SHORT_MAX_GROUPS) -> list[list[int]]:
    """手順の番号（items の位置）を、連続した場面に分ける。戻り値: [[位置, …], …]（全部の位置が、順番に、ちょうど 1 回ずつ出る）。
    場面の数は max_groups 以下。大きさは、ほぼ等しくし、場面の終わりは、近くに cook の手順があれば、そこに寄せる。"""
    n = len(items)
    if n == 0 or max_groups <= 0:
        return []
    count = min(n, max_groups)
    if count == n:
        return [[i] for i in range(n)]
    window = max(1, n // count // 2)
    ends: list[int] = []
    for k in range(count - 1):
        ideal = round((k + 1) * n / count) - 1
        low = (ends[-1] + 1) if ends else 0
        high = n - 1 - (count - 1 - k)  # 後ろの場面に、1 手順ずつは残す
        lo, hi = max(low, ideal - window), min(high, ideal + window)
        if lo > hi:
            lo = hi = min(max(ideal, low), high)
        candidates = range(lo, hi + 1)
        best = min(candidates, key=lambda i: (0 if _is_cook(items[i]) else 1, abs(i - ideal), i))
        ends.append(best)
    ends.append(n - 1)
    groups: list[list[int]] = []
    start = 0
    for end in ends:
        groups.append(list(range(start, end + 1)))
        start = end + 1
    return groups


def _first_line(text: object) -> str:
    return str(text or "").strip().split("\n", 1)[0][:COVERED_TEXT_MAX]


def group_steps(steps: list[dict], max_groups: int = SHORT_MAX_GROUPS) -> list[dict]:
    """動画に出す手順（場面の最後の手順）の一覧。全部の手順が、どれかの場面に入る。
    場面が 2 手順以上のとき、最後の手順の写しに、次を足す:
      "covers": 場面に含まれる手順の番号（順番どおり、最後の手順を含む）
      "covered": [{"step", "tool", "result"}]（含まれる手順の操作。最後の手順を含む。COVERED_MAX 件まで。台本のモデルに渡す）
    元の手順の辞書は、書き換えない。"""
    items = [s for s in (steps or []) if isinstance(s, dict)]
    out: list[dict] = []
    for group in plan_groups(items, max_groups):
        last = dict(items[group[-1]])
        if len(group) > 1:
            last["covers"] = [items[i].get("step") for i in group]
            last["covered"] = [
                {"step": items[i].get("step"), "tool": items[i].get("tool"), "result": _first_line(items[i].get("result")),
                 "tool_result": _first_line(items[i].get("tool_result"))}
                for i in group[:COVERED_MAX]
            ]
        out.append(last)
    return out


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
    """画面に出す 1 文。total: 全部の手順の数、kept: 動画の場面の数。"""
    if mode != SHORT or kept >= total:
        return ""
    return f"動画は短縮版（{total} 手順を {kept} 場面にまとめています。飛ばした手順はありません）"
