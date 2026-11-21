"""
panel_bus.py — 同じ Houdini の中で開いている、複数のパネルの間の連絡（2026-11-21）

背景: パネルを 2 つ以上開いて、並べて使う人がいる（片方で Guide、もう片方で Reference を見る、など）。
  今までは、Guide の「ノードの説明」を押すと、同じパネルの中の Reference タブに切り替わり、Guide が見えなくなった。
  → 別のパネルが開いているときは、そちらの Reference タブを開く（逆に、Reference の「使っている手順」を押すと、そちらの Guide の手順を開く）。

  ・register()   … パネルを登録する（パネルの作成時に 1 回）。弱い参照なので、閉じたパネルは自然に消える
  ・route()      … 「ほかのパネルの、その画面部品」を返す。無ければ None（呼び出し側は、今まで通り、同じパネルの中で開く）
  ・panel_of()   … ある画面部品が入っているパネル

選び方: 自分のパネル以外で、いま見えているもの（隠れたペインタブのパネルは、見えないので選ばない）。
  すでに、その画面（Reference など）を表示しているパネルがあれば、それを優先する。
Houdini にも、画面の細部にも依存しない（Qt のウィジェットの isVisible / isAncestorOf / findChild だけを使う。単体テストできる）。
"""

from __future__ import annotations

import weakref
from typing import Any, Callable

CROSS_JUMP_KEY = "cross_panel_jump"  # ui_state のキー。既定は、入（別のパネルがあれば、そちらで開く）

_panels: list[weakref.ReferenceType] = []


def register(panel: Any) -> None:
    """パネルを登録する（2 回目以降は、何もしない）。"""
    _prune()
    if not any(ref() is panel for ref in _panels):
        _panels.append(weakref.ref(panel))


def unregister(panel: Any) -> None:
    _panels[:] = [ref for ref in _panels if ref() is not None and ref() is not panel]


def live_panels() -> list[Any]:
    """いま生きている、登録済みのパネル（登録順）。"""
    _prune()
    return [p for p in (ref() for ref in _panels) if p is not None]


def _prune() -> None:
    _panels[:] = [ref for ref in _panels if ref() is not None]


def _safe(call: Callable[[], Any], default: Any = None) -> Any:
    """Qt の、削除済みのウィジェットを触ると、RuntimeError になる。そのときは、既定値を返す。"""
    try:
        return call()
    except RuntimeError:
        return default


def panel_of(widget: Any) -> Any | None:
    """widget が入っている、登録済みのパネル。無ければ None。"""
    for panel in live_panels():
        if panel is widget or _safe(lambda p=panel: p.isAncestorOf(widget), False):
            return panel
    return None


def _showing(panel: Any, widget: Any) -> bool:
    """panel の中のタブで、いま widget を含むページが表示されているか。"""
    tabs = getattr(panel, "_tabs", None)
    if tabs is None:
        return False
    current = _safe(tabs.currentWidget)
    return current is not None and (current is widget or bool(_safe(lambda: current.isAncestorOf(widget), False)))


def route(source: Any, widget_type: type, enabled: bool = True) -> Any | None:
    """source のパネル以外で、いま見えているパネルの中の、widget_type の部品を返す。無ければ None。
    その画面（タブ）をすでに表示しているパネルがあれば、それを優先する。enabled=False なら、いつも None。"""
    if not enabled:
        return None
    own = panel_of(source)
    found: list[tuple[bool, Any]] = []
    for panel in live_panels():
        if panel is own:
            continue
        if not _safe(panel.isVisible, False):
            continue  # 隠れたペインタブのパネルは、見えない（そこで開いても、気づけない）
        widget = _safe(lambda p=panel: p.findChild(widget_type))
        if widget is None:
            continue
        found.append((_showing(panel, widget), widget))
    if not found:
        return None
    found.sort(key=lambda t: not t[0])  # 表示中のものが先（同じ条件なら、登録順）
    return found[0][1]


def enabled() -> bool:
    """設定: ほかのパネルがあるとき、そちらで開くか（既定は、開く）。"""
    try:
        from panel_widgets import ui_state_get

        return bool(ui_state_get(CROSS_JUMP_KEY, True))
    except Exception:  # noqa: BLE001 -- 設定が読めなくても、既定（入）で動く
        return True


def set_enabled(value: bool) -> None:
    try:
        from panel_widgets import ui_state_set

        ui_state_set(CROSS_JUMP_KEY, bool(value))
    except Exception:  # noqa: BLE001
        pass
