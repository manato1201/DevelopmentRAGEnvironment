"""
panel_debug.py — デバッグ情報の記録（Qt に依存しない。単体テストできる）

利用者に見せる文は、短く分かりやすくする（panel_info.friendly_error）。生のエラー・通信の詳細・状態は、ここに記録して、
設定者向けの「デバッグ」タブで見る。記録には、秘密（APIキー・トークン）を残さない（mask_secrets）。
"""
from __future__ import annotations

import re
import time
from collections import deque

_MAX_ENTRIES = 500
_ENTRIES: deque[tuple[float, str, str]] = deque(maxlen=_MAX_ENTRIES)

# 秘密らしい文字列を伏せる: Bearer トークン、sk-… 形式のキー、長い英数字の並び（キーのハッシュなど）、
# key=… / token=… / api_key": "…" の値
_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1****"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"), "sk-****"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password|key)[\"']?\s*[:=]\s*[\"']?)[^\s\"',&}]{6,}"), r"\1****"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "****"),
]


def mask_secrets(text: str) -> str:
    out = str(text)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def mask_key(key: str) -> str:
    """設定済みかどうかと、末尾4文字だけを示す（全体は、画面にも記録にも出さない）。"""
    key = (key or "").strip()
    if not key:
        return "未設定"
    return f"設定済み（末尾 {key[-4:]}）" if len(key) > 8 else "設定済み"


def log(kind: str, message: str) -> None:
    """kind: "接続" "質問" "設定" "評価" など。1行にして、秘密を伏せて、記録する。"""
    line = " ".join(mask_secrets(message).split())
    _ENTRIES.append((time.time(), kind, line[:600]))


def entries() -> list[tuple[float, str, str]]:
    return list(_ENTRIES)


def clear() -> None:
    _ENTRIES.clear()


def as_text(limit: int = 200) -> str:
    rows = list(_ENTRIES)[-limit:]
    return "\n".join(f"{time.strftime('%H:%M:%S', time.localtime(ts))} [{kind}] {msg}" for ts, kind, msg in rows)
