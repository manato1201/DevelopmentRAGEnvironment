"""
trial_pruning.py — 「試して、失敗して、消したノード」の手順を、動画とガイドから省く（2026-11-06）

上級の題材では、方式を試す → うまくいかない → 消して作り直す、という流れが手順の約2割を占めた
（紙燃焼: 76手順のうち約15手順。動画は1569秒）。視聴者・学習者が真似るのは、最終的に残る構成なので、
作って消したノードにまつわる手順は、手順の記録（step_screenshots）の段階で取り除く。

  ・作って、あとで消したノード（同じ名前を作り直したときは、別のノードとして数える）の、
    作成・パラメータ設定・クック・削除の手順は省く
  ・そのノードにつないだ接続は省く。まとめた接続（「3本のノードをつなぐ」）は、残る分だけにする
  ・すでにつながっている同じ接続を、つなぎ直しただけの手順も省く（検査のために外して、戻した手順）
  ・手順の番号は、1から振り直す

チュートリアルの本文（.md）とノードの構成図は変えない（省くのは手順の記録だけ）。
純粋な関数だけ（Houdini を使わない）。判断できない手順（ノード名の記録が無い）は、必ず残す。
"""

from __future__ import annotations

import copy
import re

_INPUT_NTH_RE = re.compile(r"の(\d+)番目の入力につなぐ")
_INPUT_NAMED_RE = re.compile(r"の「(.+?)」入力につなぐ")


def _pair_input(value: object) -> int | str:
    """接続先の入力。名前（文字列）か、0始まりの番号。"""
    if isinstance(value, str) and value:
        return value
    try:
        return int(value or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0


def _connect_pairs(step: dict) -> list[dict]:
    """接続の手順が表す接続の一覧: [{"from", "to", "input"}]。読めなければ空。"""
    guide = step.get("guide") or {}
    raw = guide.get("connections")
    if isinstance(raw, list) and raw:
        return [
            {"from": str(c.get("from") or ""), "to": str(c.get("to") or ""), "input": _pair_input(c.get("input"))}
            for c in raw if isinstance(c, dict)
        ]
    src, dst = str(guide.get("from") or ""), str(guide.get("to") or "")
    if not src or not dst:
        return []
    if "input" in guide:
        return [{"from": src, "to": dst, "input": _pair_input(guide.get("input"))}]
    text = str(step.get("result") or "")
    nth = _INPUT_NTH_RE.search(text)
    named = _INPUT_NAMED_RE.search(text)
    index: int | str = (int(nth.group(1)) - 1) if nth else (named.group(1) if named else 0)
    return [{"from": src, "to": dst, "input": index}]


def _connect_text(pairs: list[dict]) -> str:
    """houdini_tools._step_instruction と同じ書き方の、接続の操作文。"""
    if len(pairs) > 1:
        shown = "、".join(f"{p['from']} → {p['to']}" for p in pairs[:6])
        more = f" ほか{len(pairs) - 6}本" if len(pairs) > 6 else ""
        return f"{len(pairs)}本のノードをつなぐ: {shown}{more}"
    p = pairs[0]
    if isinstance(p["input"], str):
        return f"{p['from']} の出力を、{p['to']} の「{p['input']}」入力につなぐ"
    if p["input"] > 0:
        return f"{p['from']} の出力を、{p['to']} の{p['input'] + 1}番目の入力につなぐ"
    return f"{p['from']} の出力を、{p['to']} の入力につなぐ"


def _rewrite_connect(step: dict, pairs: list[dict]) -> dict:
    """残った接続だけにした、手順のコピー。"""
    out = copy.deepcopy(step)
    guide = out.setdefault("guide", {})
    guide.pop("connections", None)
    guide["from"], guide["to"], guide["input"] = pairs[-1]["from"], pairs[-1]["to"], pairs[-1]["input"]
    if len(pairs) > 1:
        guide["connections"] = [dict(p) for p in pairs][:12]
    out["result"] = _connect_text(pairs)
    return out


def prune_failed_trials(steps: list[dict]) -> tuple[list[dict], list[dict]]:
    """手順の記録から、作って消したノードの手順を省く。
    戻り値: (残した手順（番号を振り直したコピー）, 省いた手順の一覧 [{"step", "tool", "reason"}])。
    入力は変えない。省くものが無ければ、同じ内容のコピーを返す。"""
    steps = [s for s in (steps or []) if isinstance(s, dict)]
    # ① ノードの「命」に番号を振る（同じ名前の作り直しは別の命）。あとで消された命が「失敗した試し」
    current: dict[str, int] = {}
    dead: set[int] = set()
    next_id = 0
    refs: list[dict] = []
    for step in steps:
        tool = step.get("tool")
        guide = step.get("guide") or {}
        name = str(guide.get("node") or "")
        ref: dict = {}
        if tool == "create_node" and name:
            next_id += 1
            current[name] = next_id
            ref["target"] = next_id
        elif tool == "delete_node" and name:
            life = current.pop(name, None)
            if life is not None:
                dead.add(life)
                ref["target"] = life
        elif tool in ("set_parameter", "cook_node") and name:
            ref["target"] = current.get(name)
        elif tool == "connect_nodes":
            ref["pairs"] = [(p, current.get(p["from"]), current.get(p["to"])) for p in _connect_pairs(step)]
        refs.append(ref)

    # ② 省く。接続は、残った接続の表（接続先の入力 → つなぐ元）と比べて、つなぎ直しだけの手順も省く
    kept: list[dict] = []
    dropped: list[dict] = []
    wired: dict[tuple[str, int | str], str] = {}
    for step, ref in zip(steps, refs):
        tool = step.get("tool")
        if tool == "connect_nodes" and ref.get("pairs"):
            live = [p for p, a, b in ref["pairs"] if not (a in dead or b in dead)]
            fresh = []
            for p in live:
                if wired.get((p["to"], p["input"])) == p["from"]:
                    continue  # すでに同じつなぎ。つなぎ直しだけ
                fresh.append(p)
            for p in fresh:
                wired[(p["to"], p["input"])] = p["from"]
            if not fresh:
                dropped.append({"step": step.get("step"), "tool": tool, "reason": "試して消したノードの接続、またはつなぎ直しだけ"})
                continue
            original = [p for p, _, _ in ref["pairs"]]
            kept.append(step if fresh == original else _rewrite_connect(step, fresh))
            continue
        target = ref.get("target")
        if target is not None and target in dead:
            dropped.append({"step": step.get("step"), "tool": tool, "reason": "作って、あとで消したノード"})
            continue
        kept.append(step)

    out: list[dict] = []
    for number, step in enumerate(kept, start=1):
        copied = dict(step)
        copied["step"] = number
        out.append(copied)
    return out, dropped
