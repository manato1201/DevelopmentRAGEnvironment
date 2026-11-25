"""
question_hints.py — Chat の「質問の例」（押すと、そのまま送る）を作る（2026-11-25。Qt にも Houdini にも依存しない。単体テストできる）

背景（実証実験の A3）: 「何がわからないのかがわからない」ときに、質問しにくい。
方針: いまの作業の状況（Guide で見ている手順・選んでいるノード・エラーの出ているノード）から、聞けそうな質問を、
  最大 MAX_HINTS 件、選べる形で出す。文は決まった型で作る（AI は使わない。費用がかからず、すぐ出る）。

  suggest(guide_step, selected, errors) … 質問の例（[{"label": ボタンの文, "query": 送る文}]）。
    guide_step: Guide で見ている手順（{"index", "total", "title", "instruction", "node_label", "node", "purpose"}）。無ければ None
    selected:   選んでいるノード（[{"label": 表示名, "type": 型の名前, "name": ノードの名前}]。先頭から使う）
    errors:     エラーの出ているノード（selected と同じ形）
"""

from __future__ import annotations

MAX_HINTS = 3
_NAME_MAX = 16   # ボタンの文に入れるノード名の長さ（長い名前は「…」で切る。質問の文には、全部入れる）

# 状況が何も無いとき（Houdini を開いたばかり など）の例。初めての人がつまずきやすいところ
GENERAL = (
    {"label": "SOP と DOP の違いは？", "query": "SOP と DOP の違いを、初心者向けに教えてください。どんなときに、どちらを使いますか？"},
    {"label": "ノードのつなぎ方の基本", "query": "Houdini で、ノードをつなぐ基本の流れ（上から下へ、入力と出力、表示フラグ）を教えてください。"},
    {"label": "まず何から覚えればいい？", "query": "Houdini を始めたばかりです。最初に覚えるとよい操作とノードを、順番に教えてください。"},
)


def _short(text: str, limit: int = _NAME_MAX) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _node_name(node: dict) -> str:
    return str(node.get("label") or node.get("type") or node.get("name") or "").strip()


def _step_number(step: dict) -> str:
    return f"手順 {int(step['index']) + 1}" if isinstance(step.get("index"), int) else "いまの手順"


def guide_step_question(step: dict, stuck: bool = False) -> str:
    """Guide の手順について聞く文。stuck=True は、Guide の「この手順を Chat に聞く」（詰まったとき。A18）。"""
    title = f"「{step['title']}」の" if step.get("title") else ""
    instruction = str(step.get("instruction") or "").strip()
    purpose = str(step.get("purpose") or "").strip()
    node = str(step.get("node_label") or step.get("node") or "").strip()
    lines = [f"Guide の{title}{_step_number(step)}で、次の作業をしています。"]
    if instruction:
        lines.append(f"作業: {instruction}")
    elif node:
        lines.append(f"ノード: {node}")
    if purpose:
        lines.append(f"目的: {purpose}")
    if stuck:
        lines.append("この手順で詰まっています。この手順で何をしているのか、Houdini の画面でのやり方と、"
                     "うまくいかないときに確かめること（よくある間違い）を、初心者向けに教えてください。")
    else:
        lines.append("この手順で何をしているのか、なぜ必要なのかを、初心者向けに説明してください。")
    return "\n".join(lines)


def suggest(guide_step: dict | None = None, selected: list[dict] | None = None, errors: list[dict] | None = None,
            limit: int = MAX_HINTS) -> list[dict]:
    """質問の例。優先の順: エラーの直し方 → Guide の手順 → 選んでいるノード → 一般の例（空きを埋める）。同じ文は 1 回だけ。"""
    out: list[dict] = []

    def add(label: str, query: str) -> None:
        if len(out) < limit and query and all(h["query"] != query for h in out):
            out.append({"label": label, "query": query})

    for node in errors or []:
        name = _node_name(node)
        if name:
            path = str(node.get("name") or "")
            where = f"（{path}）" if path and path != name else ""
            add(f"{_short(name)} のエラーを直すには？", f"{name} ノード{where}にエラーが出ています。よくある原因と、直し方を教えてください。")
            break

    step = guide_step if isinstance(guide_step, dict) else None
    if step and (step.get("instruction") or step.get("node_label") or step.get("node")):
        add(f"{_step_number(step)}は何をしている？", guide_step_question(step))
        node = str(step.get("node_label") or step.get("node") or "").strip()
        if node:
            add(f"{_short(node)} の主なパラメータは？", f"{node} ノードの、よく変える主なパラメータと、変えると結果がどう変わるかを教えてください。")

    for node in selected or []:
        name = _node_name(node)
        if name:
            add(f"{_short(name)} は何をするノード？", f"{name} ノードは何をするノードですか？ よく使う場面と、前後につなぐノードの例も教えてください。")
            break

    for hint in GENERAL:
        add(hint["label"], hint["query"])
    return out
