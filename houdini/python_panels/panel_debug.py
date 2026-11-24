"""
panel_debug.py — デバッグ情報の記録（Qt に依存しない。単体テストできる）

利用者に見せる文は、短く分かりやすくする（panel_info.friendly_error）。生のエラー・通信の詳細・状態は、ここに記録して、
設定者向けの「デバッグ」タブで見る。記録には、秘密（APIキー・トークン）を残さない（mask_secrets）。
"""
from __future__ import annotations

import functools
import re
import sys
import time
import traceback
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


def exception_summary(exc: BaseException) -> str:
    """例外を 1 行にする（型・メッセージ・どこで起きたか）。"""
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    where = f" @ {frames[-1].filename.replace(chr(92), '/').split('/')[-1]}:{frames[-1].lineno} {frames[-1].name}" if frames else ""
    return f"{type(exc).__name__}: {exc}{where}"


def guard(kind: str, restore: str | None = None):
    """Qt のスロット（完了・失敗の処理）を守る（2026-11-24。「生成のあとに、タブ以外が効かなくなる」への備え）。

    Qt のスロットの中の例外は、画面に何も出さずに、処理を途中で止める。そのとき、ボタンが無効のまま残ると、タブの切り替えしか効かなくなる。
    このデコレータは、入口・出口を記録し、例外が出たら、記録に残して（メニュー ≡ →「デバッグ」で見られる）、
    restore に挙げた名前の（引数が例外 1 つだけの）メソッドを呼んで、ボタンなどを元に戻す。例外は、ここで止める（Houdini のコンソールには、続けて出す）。"""

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log(kind, f"{fn.__name__}: 開始")
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 -- ここで記録して、元に戻す
                log(kind, f"{fn.__name__}: 例外 {exception_summary(exc)}")
                traceback.print_exc()
                if restore and args:
                    try:
                        getattr(args[0], restore)(exc)
                    except Exception as inner:  # noqa: BLE001 -- 元に戻す処理が失敗しても、続ける
                        log(kind, f"{fn.__name__}: 元に戻す処理でも例外 {exception_summary(inner)}")
                return None
            log(kind, f"{fn.__name__}: 終了")
            return result

        return wrapper

    return decorate


_HOOK_INSTALLED = False


def install_excepthook() -> None:
    """どこにも捕まらなかった例外（Qt のスロットから出たもの）を、記録に残す。前の処理は、そのまま続ける。何度呼んでもよい。"""
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    _HOOK_INSTALLED = True
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            exc.__traceback__ = tb
            log("例外", exception_summary(exc))
        except Exception:  # noqa: BLE001 -- 記録できなくても、前の処理は呼ぶ
            pass
        previous(exc_type, exc, tb)

    sys.excepthook = hook
