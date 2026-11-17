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

import json
import re
from typing import Callable

# finish_tutorial の「レッスン用の項目」。キー → (日本語の名前, 書き方の指示)
LESSON_FIELDS: dict[str, tuple[str, str]] = {
    "prerequisites": (
        "前提条件",
        "対象の読者・前提知識・Houdiniのバージョン・用意するもの（素材・モデル）。"
        "「知っている人は〇から読む」「分からなければ先に△△を見る」も書く（Markdown箇条書き）",
    ),
    "use_cases": (
        "どんな場面で使うか",
        "この技法が役立つ具体的な場面を2〜3個（ゲーム・映像など）。「〇〇のとき、これを使う」の形で",
    ),
    "roadmap": (
        "作る前に: 使うノードと、できること",
        "使うノードを使う順に並べ、各ノードで何ができるかを1行ずつ（Markdown番号付き）。全体の段取りが分かる形に",
    ),
    "learn": ("このレッスンで学ぶこと", "身につくことを2〜4個の箇条書きで"),
    "concepts": (
        "先に知っておく考え方",
        "このレッスンで初めて出る用語の一言説明と、仕組みの見取り図（Markdown。箇条書き）。"
        "レッスン1は日常のたとえ、レッスン2・3は設計判断（選んだ構成・代わりの方法・選ぶ基準）を書く",
    ),
    "experiments": (
        "パラメータを動かして確かめよう",
        "実際に set_parameter で値を変えて cook_node し、どう変わったかを2〜3個。"
        "「ノード.パラメータ: 値A → 値B で、〇〇がこう変わる」の形で。終わったら値を元に戻すこと",
    ),
    "polish": ("仕上げ", "見た目を整える1〜2個の操作（色・密度・大きさ・向きなど）と、その効果"),
    "tips": (
        "TIPS",
        "作業が楽になるコツ・確かめ方・うまくいかないときの切り分け方を3〜5個（Markdown箇条書き）。確かめたことだけ書く",
    ),
    "challenge": (
        "自分でやってみよう",
        "手本を見ずに自分で作る課題。やり方ではなく「結果の条件」だけを書く（例: 「点が500個以上あり、〇〇属性がある」）。余裕がある人向けの応用も1つ",
    ),
    "next_lesson": ("次のレッスン", "このレッスンの次に学ぶとよいこと（1〜2個）と、そのために今回の内容がどう役立つか"),
}

CHECKPOINT_MARK = "✅"
MIN_CHECKPOINTS = 2
MIN_EXPERIMENTS = 2

# 各項目の配点（合計100）
_WEIGHTS: dict[str, int] = {
    "learn": 6,
    "concepts": 10,
    "checkpoints": 12,
    "experiments_written": 10,
    "experiments_done": 10,
    "verified_numerically": 8,
    "polish": 6,
    "pitfalls": 6,
    "next_lesson": 6,
    "steps_explain_why": 6,
    # 2026-11-03: 初心者レビューで足りないと言われた「読む前の準備」と「読んだあとの手がかり」
    "prerequisites": 4,
    "use_cases": 4,
    "roadmap": 4,
    "tips": 4,
    "challenge": 4,
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
        elif tool == "try_parameter" and not failed and "→ エラー" not in str(entry.get("result", "")):
            done += 1  # 値を変えて cook し、結果を数値で比べ、元へ戻すところまでを1回で行う
    return done


def review_finish(finish: dict, step_log: list[dict] | None = None, topic: str = "", requirements: str = "") -> dict:
    """採点。戻り値: {"score": 0-100, "checks": {名前: bool}, "missing": [人が読める不足項目],
    "reproducibility": 手順書に書かれていない操作の件数（種類別）, "topic_unmet": 題材の達成基準で未確認のもの}。
    後ろの2つは点数に含めない（点数の意味を変えないため。足りない項目は別に報告する）。"""
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
    put("prerequisites", len(_text(finish.get("prerequisites"))) >= 12, "前提条件")
    put("use_cases", len(_text(finish.get("use_cases"))) >= 12, "どんな場面で使うか")
    put("roadmap", len(_text(finish.get("roadmap"))) >= 12, "作る前に（使うノードとできること）")
    put("tips", len(_text(finish.get("tips"))) >= 12, "TIPS")
    put("challenge", len(_text(finish.get("challenge"))) >= 12, "自分でやってみよう")

    step_lines = [ln for ln in steps.splitlines() if _STEP_LINE_RE.match(ln)]
    if step_lines:
        why = sum(1 for ln in step_lines if _WHY_RE.search(ln))
        put("steps_explain_why", why / len(step_lines) >= 0.5, "手順に「なぜそうするか」")
    else:
        put("steps_explain_why", False, "手順に「なぜそうするか」")

    score = sum(_WEIGHTS[k] for k, ok in checks.items() if ok)
    gaps = fidelity_gaps(steps, step_log)
    reproducibility = {k: len(gaps[k]) for k in ("nodes", "values", "code", "connections", "phantoms")}
    return {
        "score": score, "checks": checks, "missing": missing,
        "reproducibility": reproducibility,
        "topic_unmet": topic_unmet(topic, requirements, step_log),
    }


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
        "【書き足しが必要です】この生成物は「手順の記録」で止まっています。読者が理解できるレッスンにするため、"
        "次を加えてから finish_tutorial を呼び直してください（confirm_tutorial はそのあとに）。"
        "すでに実際に確かめた内容だけを書き、確かめていないことは書かないこと。\n" + "\n".join(lines)
    )


def summarize(report: dict) -> str:
    """進行表示用の1行。"""
    text = f"レッスン品質チェック: {report['score']}/100"
    if report["missing"]:
        text += "（不足: " + "、".join(report["missing"][:4]) + ("…" if len(report["missing"]) > 4 else "") + "）"
    labels = {"nodes": "手順書に無いノード", "values": "値が書かれていないパラメータ", "code": "全文が載っていないコード",
              "connections": "書かれていない接続", "phantoms": "作られていないノードの記述"}
    repro = [f"{labels[k]} {n}件" for k, n in (report.get("reproducibility") or {}).items() if n]
    if repro:
        text += " / 再現性: " + "、".join(repro)
    if report.get("topic_unmet"):
        text += " / 題材の基準で未確認: " + "、".join(report["topic_unmet"][:2]) + ("…" if len(report["topic_unmet"]) > 2 else "")
    return text


# ─── 手順の抜け漏れの検出（2026-11-17） ────────────────────────────────────────────
# 実証実験で「省いている箇所に抜け漏れがあり、同じ手順でやってもできない場合がある」という指摘が出た。
# 上の採点は「項目が書かれているか」「✅ が2個以上あるか」を見るだけで、手順書の内容が、実際に行った操作
# （ツールの呼び出しの記録）と合っているかは見ていなかった。ここでは、記録から「最終的に残る構成」を組み立て、
# 手順書（steps）に次の4つが書かれているかを調べる（Claudeは呼ばない。Houdiniも不要）。
#   ・ノード       : 作ったのに、手順書に出てこないノード（前提のノードが無い）
#   ・パラメータ値 : 値を設定したのに、手順書に値が書かれていないもの
#   ・コード       : 長いコード（VEXなど）の全文が載っていないもの（「…」で省いた場合を含む）
#   ・接続         : つないだのに、手順書に「どれとどれを」が書かれていないもの（接続の順序が飛ぶ）
# 手順書に「作られていないノード」が出てくる場合（書き間違い・幻のノード）も拾う。

_CREATE_RE = re.compile(r"作成しました: (\S+?)（タイプ: ([^）]+)）")
_CONNECT_RE = re.compile(r"接続しました: (\S+?)\[out:(\d+)([^\]]*)\] → (\S+?)\[in:(\d+)([^\]]*)\]")
_DELETE_RE = re.compile(r"削除しました: (\S+)")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_CODE_MIN_CHARS = 40          # これ以上、または複数行の値は「コード」として全文を確かめる
_CODE_COVERAGE_MIN = 0.7      # コードの行のうち、手順書に載っているべき割合
_REPORT_LIMIT = 6             # 1種類につき、案内に書く件数の上限
# 「どれとどれをつなぐか」が書かれているとみなす言葉（2つのノード名が同じ塊にあっても、つなぐと書かれていなければ、接続の説明にならない）
_CONNECT_WORDS = re.compile(r"接続|つな|繋|→|->|入力|出力|input|output|connect|差し|挿|渡|流|直列|チェーン", re.IGNORECASE)


def _rel(path: str) -> str:
    return (path or "").strip().lstrip("/")


def _leaf(rel: str) -> str:
    return rel.rsplit("/", 1)[-1]


def _failed(entry: dict) -> bool:
    return bool(entry.get("is_error")) or str(entry.get("result", "")).startswith(("エラー", "[サンドボックス違反]"))


def operations_from_log(step_log: list[dict]) -> dict:
    """ツールの呼び出しの記録から、最終的に残る構成を組み立てる（作って消したノードは除く）。
    戻り値: {"nodes": {パス: タイプ}, "connections": [{"from","to","in","out"}], "params": {(パス, パラメータ): {"value","kind"}}}。
    パスはサンドボックス相対。設定は、同じ項目なら最後の値。"""
    nodes: dict[str, str] = {}
    connections: list[dict] = []
    params: dict[tuple[str, str], dict] = {}

    def drop(rel: str) -> None:
        for key in [k for k in nodes if k == rel or k.startswith(rel + "/")]:
            del nodes[key]
        gone = lambda p: p == rel or p.startswith(rel + "/")  # noqa: E731
        connections[:] = [c for c in connections if not gone(c["from"]) and not gone(c["to"])]
        for key in [k for k in params if gone(k[0])]:
            del params[key]

    for entry in step_log:
        if _failed(entry):
            continue
        tool = entry.get("tool")
        result = str(entry.get("result", ""))
        args = entry.get("input") or {}
        if tool == "create_node":
            match = _CREATE_RE.match(result)
            if match:
                nodes[_rel(match.group(1))] = match.group(2)
        elif tool == "delete_node":
            match = _DELETE_RE.match(result)
            if match:
                drop(_rel(match.group(1)))
        elif tool == "connect_nodes":
            match = _CONNECT_RE.match(result)
            if match:
                item = {
                    "from": _rel(match.group(1)), "to": _rel(match.group(4)),
                    "in": int(match.group(5)), "out": int(match.group(2)),
                    "in_name": match.group(6).strip(),
                }
                connections[:] = [c for c in connections if not (c["to"] == item["to"] and c["in"] == item["in"])]
                connections.append(item)
        elif tool == "set_parameter":
            node, parm = _rel(str(args.get("node", ""))), str(args.get("parm", ""))
            if not node or not parm or not result.startswith(f"{node}.{parm}"):
                continue
            if args.get("ramp"):
                kind, value = "ramp", json.dumps(args["ramp"], ensure_ascii=False)
            elif args.get("keyframes"):
                kind, value = "keyframes", json.dumps(args["keyframes"], ensure_ascii=False)
            elif args.get("expression") is not None:
                kind, value = "expression", str(args["expression"])
            elif "value" in args:
                kind, value = "value", str(args["value"])
            else:
                continue
            params[(node, parm)] = {"value": value, "kind": kind}
    return {"nodes": nodes, "connections": connections, "params": params}


def _compact(text: str) -> str:
    """大小・空白・区切りを無視して比べるための形。"""
    return re.sub(r"[\s_\-,（）()、。]+", "", (text or "").lower())


def _blocks(steps: str) -> list[str]:
    """手順書を、章・手順ごとの塊に分ける（見出し・番号つきの行で区切る。無ければ空行で）。"""
    lines = steps.splitlines()
    marks = [i for i, ln in enumerate(lines) if re.match(r"\s{0,3}(?:#{1,6}\s|\d+[.)．]\s)", ln)]
    if len(marks) >= 2:
        edges = marks + [len(lines)]
        head = ["\n".join(lines[: marks[0]])] if marks[0] > 0 else []
        return head + ["\n".join(lines[a:b]) for a, b in zip(edges, edges[1:])]
    return [b for b in re.split(r"\n\s*\n", steps) if b.strip()]


def _mentions(text: str, rel: str, node_type: str = "") -> bool:
    """text が、このノードに触れているか（ノード名、または十分に長いタイプ名）。"""
    low = (text or "").lower()
    leaf = _leaf(rel).lower()
    if leaf and (leaf in low or _compact(leaf) in _compact(low)):
        return True
    base = node_type.split("::")[0].lower()
    return len(base) >= 5 and _compact(base) in _compact(low)


def _numbers(text: str) -> set[float]:
    return {round(float(x), 6) for x in _NUM_RE.findall(text or "")}


def _value_tokens(value: str) -> tuple[set[float] | None, str]:
    """(数値だけの値ならその数値の集合, そうでなければ文字列の正規形)。"""
    stripped = value.strip()
    if stripped and not re.search(r"[A-Za-z_$@]", stripped) and _NUM_RE.search(stripped):
        return _numbers(stripped), ""
    return None, _compact(stripped)


def _is_code(value: str) -> bool:
    if "\n" not in value and not re.search(r"\s", value.strip()) and re.search(r"[/\\]", value):
        return False  # 長くても、ファイルやノードのパス（空白なし）はコードではない
    return "\n" in value or len(value) >= _CODE_MIN_CHARS or (";" in value and len(value) >= 20)


def _code_lines(value: str) -> list[str]:
    out = []
    for line in value.splitlines():
        line = line.strip()
        if not line or line.startswith(("//", "#")):
            continue
        out.append(_compact(line))
    return [x for x in out if len(x) >= 4]


def fidelity_gaps(steps: str, step_log: list[dict]) -> dict:
    """手順書（steps）に、実際に行った操作が書かれているかを調べる。
    戻り値: {"nodes": [...], "values": [...], "code": [...], "connections": [...], "phantoms": [...], "ops": 最終構成}。
    各リストが空なら、その種類の抜けは無い。"""
    ops = operations_from_log(step_log)
    text = steps or ""
    blocks = _blocks(text)
    gaps: dict = {"nodes": [], "values": [], "code": [], "connections": [], "phantoms": [], "ops": ops}
    if not text.strip() or not ops["nodes"]:
        return gaps
    compact_text = _compact(text)

    for rel, node_type in ops["nodes"].items():
        if not _mentions(text, rel, node_type):
            gaps["nodes"].append({"node": rel, "type": node_type})

    for (rel, parm), item in ops["params"].items():
        value, kind = item["value"], item["kind"]
        node_type = ops["nodes"].get(rel, "")
        if re.match(r"^(?:[A-Za-z]:[\\/]|/)", value.strip()) and not re.search(r"\s", value.strip()):
            continue  # 絶対パス（書き出し先など）は、環境ごとに違うので、手順書の対象にしない
        if kind in ("value", "expression") and _is_code(value):
            lines = _code_lines(value)
            if not lines:
                continue
            found = sum(1 for ln in lines if ln in compact_text)
            if found / len(lines) < _CODE_COVERAGE_MIN:
                gaps["code"].append({"node": rel, "parm": parm, "value": value, "found": found, "total": len(lines)})
            continue
        numbers, normal = _value_tokens(value)
        scoped = [b for b in blocks if _mentions(b, rel, node_type)] or blocks
        if numbers is not None:
            ok = any(numbers <= _numbers(b) for b in scoped)
        else:
            ok = bool(normal) and any(normal in _compact(b) for b in scoped)
        if not ok:
            gaps["values"].append({"node": rel, "parm": parm, "value": value, "kind": kind})

    for edge in ops["connections"]:
        src_type, dst_type = ops["nodes"].get(edge["from"], ""), ops["nodes"].get(edge["to"], "")
        covered = any(
            _mentions(b, edge["from"], src_type) and _mentions(b, edge["to"], dst_type) and _CONNECT_WORDS.search(b)
            for b in blocks
        )
        if not covered:
            gaps["connections"].append(edge)

    # 手順書に「`名前` ノード」と書かれているのに、作られていないもの（書き間違い・幻のノード）
    known = {_leaf(r).lower() for r in ops["nodes"]} | {t.split("::")[0].lower() for t in ops["nodes"].values()}
    created_ever = {
        _leaf(_rel(m.group(1))).lower() for e in step_log if e.get("tool") == "create_node" for m in [_CREATE_RE.match(str(e.get("result", "")))] if m
    }
    for match in re.finditer(r"`([A-Za-z][A-Za-z0-9_:.]*)`\s*ノード|ノード\s*`([A-Za-z][A-Za-z0-9_:.]*)`", text):
        name = (match.group(1) or match.group(2)).lower()
        base = name.split("::")[0]
        if base in known or name in known or base in created_ever or name in created_ever:
            continue
        if name not in [p.lower() for p in gaps["phantoms"]]:
            gaps["phantoms"].append(match.group(1) or match.group(2))
    return gaps


def fidelity_significant(gaps: dict) -> bool:
    """モデルに書き直しを求めるほどの抜けか（小さな値の省略だけなら求めない）。"""
    return bool(gaps["nodes"] or gaps["code"] or gaps["connections"] or gaps["phantoms"] or len(gaps["values"]) >= 3)


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fidelity_message(gaps: dict) -> str:
    """finish_tutorial の返答に付ける「手順書の抜け」の案内。抜けが小さければ空文字。"""
    if not fidelity_significant(gaps):
        return ""
    lines: list[str] = []
    for item in gaps["nodes"][:_REPORT_LIMIT]:
        lines.append(f"- ノード `{item['node']}`（{item['type']}）を作ったのに、手順書に出てきません。作る手順と、何のためのノードかを書く")
    for item in gaps["connections"][:_REPORT_LIMIT]:
        port = f"（入力 {item['in_name']}）" if item.get("in_name") else (f"（入力 {item['in'] + 1} 番目）" if item["in"] else "")
        lines.append(f"- 接続 `{_leaf(item['from'])}` → `{_leaf(item['to'])}`{port} が、手順書のどこにも書かれていません。どれとどれをつなぐかを書く")
    for item in gaps["code"][:_REPORT_LIMIT]:
        lines.append(
            f"- `{item['node']}` の `{item['parm']}` のコードが、全文は載っていません（{item['found']}/{item['total']} 行）。"
            "「…」で省かず、コードの全文をコードブロックで載せる"
        )
    for item in gaps["values"][:_REPORT_LIMIT]:
        lines.append(f"- `{item['node']}` の `{item['parm']}` を {_short(item['value'], 30)} にしたことが、手順書に書かれていません。値を書く")
    if len(gaps["values"]) > _REPORT_LIMIT:
        lines.append(f"- ほか、値の書かれていないパラメータが {len(gaps['values']) - _REPORT_LIMIT} 件あります")
    for name in gaps["phantoms"][:_REPORT_LIMIT]:
        lines.append(f"- 手順書の `{name}` ノードは、実際には作られていません。名前の書き間違いか、作る手順の書き忘れです")
    return (
        "【手順書に抜けがあります】手順書だけを見て同じ操作をしても、再現できません。"
        "次を書き足してから finish_tutorial を呼び直してください（confirm_tutorial はそのあとに）。\n" + "\n".join(lines)
    )


def phantom_message(gaps: dict) -> str:
    """手順書に書かれているのに、作られていないノードだけの案内（記録から自動で補えない「間違い」なので、書き直してもらう）。無ければ空文字。
    ノード・値・コード・接続の抜けは、operation_appendix が記録から補うので、書き直しを求めない（finish_tutorial の再提出は、約40秒かかるため）。"""
    return fidelity_message({**gaps, "nodes": [], "values": [], "code": [], "connections": []}) if gaps.get("phantoms") else ""


APPENDIX_TITLE = "#### 手順の補足（実際の記録から自動で書き出しました。上の手順で省かれていた内容です）"
_APPENDIX_CODE_CHARS = 3000    # 1つのコードの全文の上限。超えたら、省いたことを書く（黙って切らない）
_APPENDIX_TOTAL_CHARS = 12000  # 補足の全体の上限。手順書が、補足で膨れ上がらないように
_APPENDIX_INLINE_CHARS = 80    # 1行の値の上限
_APPENDIX_STRUCT_CHARS = 300   # ランプ・キーフレームの JSON は、省くと意味が変わるので長く取る


def _inline(text: str, limit: int) -> str:
    """Markdown の `…`（インラインのコード）に入れても壊れない形。バッククォートは、似た文字に替える。"""
    return _short(text, limit).replace("`", "\u2019")


def _fence_for(code: str) -> str:
    """コードの中のバッククォートの並びより長い囲い（```以上）。コードの中に ``` があっても、Markdown が壊れない。"""
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", code)), default=0)
    return "`" * max(3, longest + 1)


def operation_appendix(gaps: dict) -> str:
    """手順書で省かれていた操作を、実際の記録から機械的に書き出した補足（Markdown）。抜けが無ければ空文字。
    モデルが書き直さなかった場合でも、再現に必要な情報（ノード・値・コードの全文・接続）が、手順書に残る。
    記録の値は、データとして、コードブロックか `…` の中にだけ入れる（地の文にしない）。全体の長さにも上限がある。"""
    parts: list[str] = []
    ops = gaps.get("ops") or {}
    if gaps.get("nodes"):
        parts.append("**作るノード**\n" + "\n".join(
            f"- `{_inline(g['node'], 120)}`（タイプ `{_inline(g['type'], 120)}`）" for g in gaps["nodes"]))
    if gaps.get("values"):
        rows = []
        for g in gaps["values"]:
            limit = _APPENDIX_INLINE_CHARS if g.get("kind", "value") == "value" else _APPENDIX_STRUCT_CHARS
            rows.append(f"- `{_inline(g['node'], 120)}` の `{_inline(g['parm'], 60)}` = `{_inline(g['value'], limit)}`")
        parts.append("**設定するパラメータ**\n" + "\n".join(rows))
    for g in gaps.get("code", []):
        code = str(g["value"])
        shown = code[:_APPENDIX_CODE_CHARS]
        fence = _fence_for(shown)
        tag = "vex" if "@" in code or ";" in code else ""
        cut = f"\n（以下は省略: 全 {len(code)} 文字のうち、先頭の {len(shown)} 文字）" if len(code) > len(shown) else ""
        parts.append(f"**`{_inline(g['node'], 120)}` の `{_inline(g['parm'], 60)}`（全文）**\n{fence}{tag}\n{shown}\n{fence}{cut}")
    if gaps.get("connections"):
        rows = []
        for e in gaps["connections"]:
            port = f"、入力 `{_inline(e['in_name'], 40)}`" if e.get("in_name") else (f"、{e['in'] + 1} 番目の入力" if e["in"] else "")
            rows.append(f"- `{_inline(_leaf(e['from']), 80)}` の出力 → `{_inline(_leaf(e['to']), 80)}`{port}")
        parts.append("**つなぐ順**\n" + "\n".join(rows))
    if not parts or not ops:
        return ""
    kept, size = [], len(APPENDIX_TITLE)
    for part in parts:
        if size + len(part) > _APPENDIX_TOTAL_CHARS and kept:
            kept.append("（補足が長いため、ここから先は省略しました。記録は監査ログに残っています）")
            break
        kept.append(part)
        size += len(part) + 2
    return APPENDIX_TITLE + "\n\n" + "\n\n".join(kept)


# ─── 題材ごとの達成基準（2026-11-17） ────────────────────────────────────────────
# 実証実験で、炎・煙はできたが「炎の竜巻」ができなかった（最終確認のメモにも「細い柱状で、竜巻らしい広がりは弱い」とあった）。
# 原因は、①「竜巻らしさ」の基準がプロンプトに無く、ノードが動いて cook が通れば完成にしていた、②渦（回転）と
# 漏斗（高さで半径が変わる）の作り方の手がかりが無かった、の2つ。題材ごとに、作り方の手がかりと、確かめる基準を持たせる。
# 基準の確認は「記録（ツールの呼び出し）に、その証拠があるか」の機械的な判定で、見た目そのものの判定ではない。

_CODE_PARM_TOOLS = ("set_parameter",)
_SIZE_RE = re.compile(r"バウンディングボックス: サイズ \(([-\d.e+]+), ([-\d.e+]+), ([-\d.e+]+)\)")


def _code_blob(step_log: list[dict]) -> str:
    """設定した値・式・コードを、すべて連結した文字列（証拠の探索用）。"""
    parts = []
    for e in step_log:
        if _failed(e) or e.get("tool") not in _CODE_PARM_TOOLS:
            continue
        a = e.get("input") or {}
        parts.append(str(a.get("value", "")) + " " + str(a.get("expression", "")))
    return "\n".join(parts)


def _frames_seen(step_log: list[dict]) -> set[float]:
    """inspect_geometry / view_viewport で見たフレーム（2つ以上なら、時間で変わる様子を比べられる）。"""
    frames: set[float] = set()
    for e in step_log:
        if _failed(e) or e.get("tool") not in ("inspect_geometry", "view_viewport"):
            continue
        frame = (e.get("input") or {}).get("frame")
        try:
            frames.add(float(frame))
        except (TypeError, ValueError):
            pass
    return frames


def _inspect_results(step_log: list[dict]) -> list[str]:
    return [str(e.get("result", "")) for e in step_log if e.get("tool") == "inspect_geometry" and not _failed(e)]


def _any_type(ops: dict, pattern: str) -> bool:
    return any(re.search(pattern, t, re.IGNORECASE) for t in ops["nodes"].values())


def _tall_column_seen(step_log: list[dict], ratio: float = 1.5) -> bool:
    for text in _inspect_results(step_log):
        match = _SIZE_RE.search(text)
        if match:
            try:
                x, y, z = (abs(float(v)) for v in match.groups())
            except ValueError:
                continue
            if y >= ratio * max(x, z, 1e-9):
                return True
    return False


def _field_seen(step_log: list[dict], names: tuple[str, ...]) -> bool:
    blob = "\n".join(_inspect_results(step_log)).lower()
    return any(n in blob for n in names)


# 半径らしい変数（r・rad・radius など）に、高さらしい量（t・h・height・P.y・fit・lerp・pow など）を使った式を代入しているか
_FUNNEL_RE = re.compile(
    r"\b(?:r|rad|radius|r_\w+|taper\w*|funnel\w*|spread|width)\s*=[^;\n]*?"
    r"(?:\bt\b|\bh\b|height|P\.y|@P\.y|\by\b|\bfit\s*\(|\blerp\s*\(|\bpow\s*\(|\bsmoothstep\s*\()",
    re.IGNORECASE,
)


def _funnel_in_code(code: str) -> bool:
    return bool(_FUNNEL_RE.search(code))


def _moving_checked(ops: dict, step_log: list[dict]) -> bool:
    return len(_frames_seen(step_log)) >= 2


# 題材: (識別子, 題材を見分ける正規表現, 作り方の手がかり, [(基準の名前, 判定関数(ops, step_log))])
_TOPIC_RULES: tuple[tuple[str, re.Pattern[str], str, tuple[tuple[str, Callable[[dict, list[dict]], bool]], ...]], ...] = (
    (
        "tornado",
        re.compile(r"竜巻|トルネード|旋風|つむじ|tornado|twister|cyclone|dust\s*devil|vortex|渦", re.IGNORECASE),
        (
            "竜巻（渦）は、「回転」「漏斗の形」「縦に長い柱」の3つが揃って、初めて竜巻に見えます。ノードが動くだけでは完成にしないでください。\n"
            "- 回転: 点ごとの速度（v）を、軸まわりの接線方向にする。例: `vector axis = {0,1,0}; vector r = @P - set(0,@P.y,0); @v = cross(axis, r) * speed;`"
            "（cross で、軸と半径方向に直交する向きになる）。パーティクルなら popwind / popvortex 系、ボリュームなら速度（vel）にこの値を入れる\n"
            "- 漏斗: 半径を高さで変える。例: `float h = fit(@P.y, 0, height, 0, 1); float rad = lerp(r_bottom, r_top, pow(h, 1.5));`。"
            "下が細く、上が広い（または逆）形にして、円柱にしない。目安: 上端の半径は下端の2〜4倍、高さは最大の幅の2〜4倍\n"
            "- 柱: 高さが幅の2倍前後以上。pyro など体積のシミュレーションで、解像度（voxel/division size）を粗くしすぎると、細い線にしかならない。"
            "広がりが弱いときは、半径（r_top）・回転の強さ・ソースの太さ・ソースの点の数を上げる。らせん状の1本の点列だけをソースにすると、細い線になりやすい"
            "（複数の高さで、輪（円周上の点）を重ねる、または各点に半径（pscale）を持たせて太くする）\n"
            "- 炎の竜巻: 回転する点を pyro のソース（temperature・burn・density）にし、速度（vel）をソースへ入れて、上昇と回転を同時に与える。"
            "ソースの点は、毎フレーム新しく出す（時間で位置を回転させる: `@P = rotate(@P, radians(@Frame*speed), {0,1,0})` のように、$F・@Frame を使う）\n"
            "- 確かめ方: inspect_geometry で、バウンディングボックスの高さ(Y)が幅(X,Z)の1.5倍以上か、frame を変えて2回以上（回転・上昇が時間で変わるか）を数値で見る。"
            "view_viewport で、渦が見えるか（細い1本の線になっていないか）を画像で見る"
        ),
        (
            ("回転（cross・sin/cos・rotate・curlnoise、または vortex 系のノード）",
             lambda ops, log: bool(re.search(r"\b(cross|rotate|qrotate|curlnoise|atan2)\s*\(|\bsin\s*\(.*\bcos\s*\(|\bcos\s*\(.*\bsin\s*\(", _code_blob(log), re.S))
             or _any_type(ops, r"vortex|twist|swirl|popwind|rotate")),
            ("漏斗の形（高さに応じて半径が変わる式）", lambda ops, log: _funnel_in_code(_code_blob(log))),
            ("縦長の柱（バウンディングボックスの高さが幅の1.5倍以上）を inspect_geometry で確認", lambda ops, log: _tall_column_seen(log)),
            ("時間で動く様子を、2つ以上のフレームで確認", _moving_checked),
        ),
    ),
    (
        "fire",
        re.compile(r"炎|火|燃|fire|flame|burn|爆発|explosion", re.IGNORECASE),
        (
            "炎は、温度（temperature）・燃焼（burn）・燃料（fuel/density）の3つの場で作る。ソース（pyrosource）に temperature と density を出させ、"
            "pyrosolver に渡す。煙だけ・光るだけの見た目で済ませない。確かめ方: inspect_geometry で、シミュレーションのあとのフレーム（例: 12）に "
            "temperature / density / flame の場があり、値が0でないこと。時間で動くので、frame を変えて2回以上見る"
        ),
        (
            ("pyro 系のノード（pyrosolver / pyrosource など）を使っている", lambda ops, log: _any_type(ops, r"pyro")),
            ("温度・密度・炎の場（temperature / density / flame / burn）が、結果に出ていることを確認",
             lambda ops, log: _field_seen(log, ("temperature", "density", "flame", "burn"))),
            ("時間で動く様子を、2つ以上のフレームで確認", _moving_checked),
        ),
    ),
    (
        "smoke",
        re.compile(r"煙|スモーク|smoke|steam|湯気|霧|fog", re.IGNORECASE),
        (
            "煙は、密度（density）と速度（vel）の場で作る。ソースから density を出し、温度で上昇させる。ビューポートでボリュームが枠だけに見える場合は、"
            "可視化（ボリュームの表示設定、またはポイント・メッシュ化）で中身を見せる。確かめ方: inspect_geometry で、あとのフレームに density があり、値が0でないこと"
        ),
        (
            ("密度（density）の場が、結果に出ていることを確認", lambda ops, log: _field_seen(log, ("density",))),
            ("時間で動く様子を、2つ以上のフレームで確認", _moving_checked),
        ),
    ),
    (
        "cloud",
        re.compile(r"雲|クラウド|cloud", re.IGNORECASE),
        (
            "雲は、粗い形（ポイント・メッシュ）を VDB（vdbfrompolygons / volume）にして、cloudnoise や volumewrangle で、ふちを崩して作る。"
            "確かめ方: inspect_geometry で、density の値が0〜1の範囲にあり、広がり（サイズ）が想定どおりか。ふちがなめらかか、view_viewport で見る"
        ),
        (
            ("ボリューム（VDB・density）として作っている", lambda ops, log: _any_type(ops, r"volume|vdb|cloud|fog") or _field_seen(log, ("density",))),
            ("密度（density）の範囲を inspect_geometry で確認", lambda ops, log: _field_seen(log, ("density",))),
        ),
    ),
    (
        "rbd",
        re.compile(r"\brbd\b|剛体|破壊|崩壊|崩れ|瓦礫|fracture|debris|粉砕|割れ", re.IGNORECASE),
        (
            "剛体（RBD）は、割る（voronoifracture / rbdmaterialfracture）→ 剛体に変える（rbdconfigure / rbdbulletsolver）→ 地面・衝突を設ける、の順。"
            "確かめ方: 最初と後のフレームで、ピース数が同じか、位置（バウンディングボックス）が動いたか（落ちた・崩れたか）を inspect_geometry で、frame を変えて見る"
        ),
        (
            ("割る・剛体にするノード（fracture / rbd）を使っている", lambda ops, log: _any_type(ops, r"fracture|rbd|bullet")),
            ("時間で動く様子（落ちる・崩れる）を、2つ以上のフレームで確認", _moving_checked),
        ),
    ),
    (
        "rig",
        re.compile(r"\bapex\b|リグ|リギング|\brig(ging)?\b|kinefx|スケルトン|skelet|ボーン|\bik\b|キャラクター", re.IGNORECASE),
        (
            "リギング（KineFX / APEX）は、骨格（skeleton）→ リグの部品（autorig / rigpose）→ キャラクターへの割り当て（mapcharacter / packcharacter）→ 動き（sceneanimate / rigpose の変換）の順。"
            "APEX のグラフの中身は、このツールでは編集できないので、APEX のSOPノードを接続して構成する。確かめ方: 最終ノードが cook でエラーなし、"
            "inspect_geometry で関節（点）の数・階層（name 属性）が想定どおり、frame を変えて、関節の位置・回転が変わること（動かしたときに、メッシュが追従すること）。"
            "実機でしか分からない見た目の品質（変形の破綻）は、view_viewport で frame を変えて見る"
        ),
        (
            ("KineFX / APEX のノードを使っている", lambda ops, log: _any_type(ops, r"kinefx|apex|skeleton|rigpose")),
            ("関節（点）の構成を inspect_geometry で確認", lambda ops, log: bool(_inspect_results(log))),
            ("動かして、2つ以上のフレームで確認", _moving_checked),
        ),
    ),
)

def matched_topics(topic: str, requirements: str = "") -> list[str]:
    """題材（炎・煙・竜巻・雲・RBD・リグ）の識別子。複数当てはまれば、すべて。"""
    text = f"{topic}\n{requirements}"
    return [key for key, pattern, _hint, _checks in _TOPIC_RULES if pattern.search(text)]


def topic_hint_section(topic: str, requirements: str = "") -> str:
    """システムプロンプトに入れる、題材別の作り方の手がかりと達成基準（当てはまる題材が無ければ空文字）。"""
    matched = set(matched_topics(topic, requirements))
    if not matched:
        return ""
    blocks = []
    for key, _pattern, hint, checks in _TOPIC_RULES:
        if key not in matched:
            continue
        criteria = "\n".join(f"  ・{name}" for name, _fn in checks)
        blocks.append(f"### 題材: {key}\n{hint}\n達成基準（finish_tutorial の前に、どれも数値か画像で確かめる）:\n{criteria}")
    return (
        "\n## 題材別の作り方と達成基準（cook が通るだけでは完成ではありません。基準を満たしているか確かめ、満たさないときは直してから終える）\n"
        + "\n\n".join(blocks) + "\n"
    )


def topic_unmet(topic: str, requirements: str, step_log: list[dict]) -> list[str]:
    """題材別の達成基準のうち、記録に証拠が無いもの（人が読める名前）。当てはまる題材が無ければ空。"""
    matched = set(matched_topics(topic, requirements))
    if not matched:
        return []
    ops = operations_from_log(step_log)
    unmet: list[str] = []
    for key, _pattern, _hint, checks in _TOPIC_RULES:
        if key not in matched:
            continue
        for name, check in checks:
            try:
                ok = bool(check(ops, step_log))
            except Exception:  # noqa: BLE001 -- 判定に失敗したら、指摘しない（誤った差し戻しを避ける）
                ok = True
            if not ok and name not in unmet:
                unmet.append(name)
    return unmet


def topic_gap_message(unmet: list[str]) -> str:
    if not unmet:
        return ""
    return (
        "【題材の達成基準で、まだ確かめていないものがあります】cook が通っても、題材らしい結果になっているとは限りません。"
        "次を確かめ（足りなければ直し）てから、finish_tutorial を呼び直してください。確かめられない・不要と判断したものは、pitfalls にその理由を書く。\n"
        + "\n".join(f"- {name}" for name in unmet[:6])
    )
