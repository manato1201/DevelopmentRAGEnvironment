"""
tutorial_followup.py — 生成したチュートリアルへの「追加指示」から、次の生成の必須条件を作る（2026-11-18）

要望: 「生成後のものに対して追加指示して、さらなるチュートリアル生成ができるといい」。

方式（いまの生成の仕組みを、そのまま使う）:
  生成エージェントは、サンドボックスを、毎回、新しく作る（前のノードを引き継いで編集するのではない）。そこで、
  前のチュートリアルの要点（題・概要・手順の見出し）と、追加指示を、「必須条件」（最優先の指定）に入れて、もう一度生成する。
  新しいチュートリアルは、土台の部分も含めた、完全な手順になる（前の結果は、保存していなければ、破棄される）。

Qt にも Houdini にも依存しない（単体テストできる）。
"""

from __future__ import annotations

import re

MAX_INSTRUCTION_CHARS = 600
MAX_DIGEST_CHARS = 1800
_MAX_HEADINGS = 40

_OVERVIEW_RE = re.compile(r"^##\s*概要\s*$", re.MULTILINE)
_NEXT_H2_RE = re.compile(r"^##\s", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


def clean_instruction(text: str) -> str:
    """追加指示を、1 つの文章に整える（改行をつなぎ、長すぎれば切る）。空なら、空の文字列。"""
    one_line = " ".join(str(text or "").split())
    return one_line[:MAX_INSTRUCTION_CHARS]


def digest_of(markdown: str) -> str:
    """前のチュートリアルの要点: 概要（冒頭）と、手順の見出し（### …）の一覧。MAX_DIGEST_CHARS までに収める。"""
    text = str(markdown or "")
    parts: list[str] = []
    match = _OVERVIEW_RE.search(text)
    if match:
        rest = text[match.end():]
        nxt = _NEXT_H2_RE.search(rest)
        overview = " ".join((rest[:nxt.start()] if nxt else rest).split())
        if overview:
            parts.append("概要: " + overview[:400])
    headings: list[str] = []
    for found in _H3_RE.finditer(text):
        title = " ".join(found.group(1).split())
        if title and title not in headings:
            headings.append(title[:80])
        if len(headings) >= _MAX_HEADINGS:
            break
    if headings:
        parts.append("手順の見出し: " + " / ".join(f"{i}. {h}" for i, h in enumerate(headings, 1)))
    return "\n".join(parts)[:MAX_DIGEST_CHARS]


def build_requirements(base_requirements: str, topic: str, title: str, markdown: str, instruction: str) -> str:
    """次の生成に渡す「必須条件」。元の必須条件（あれば）の下に、続きの生成の指示を足す。追加指示が空なら、空の文字列。"""
    extra = clean_instruction(instruction)
    if not extra:
        return ""
    lines = [
        f"【続きの生成】直前に作ったチュートリアル「{title or topic}」（題材: {topic}）に、次の追加指示を反映した、完全な新しいチュートリアルを作ること。",
        f"追加指示: {extra}",
        "直前のチュートリアルの要点（これを土台にして、追加指示に関わる部分だけを、足す・変える。土台の部分は、同じ構成で作り直してよい）:",
    ]
    digest = digest_of(markdown)
    lines.append(digest if digest else "（要点を取り出せませんでした。題材と追加指示から、作ってください）")
    base = str(base_requirements or "").strip()
    return (base + "\n\n" if base else "") + "\n".join(lines)
