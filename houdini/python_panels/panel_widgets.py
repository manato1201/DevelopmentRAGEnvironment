"""
panel_widgets.py — パネルで共通に使う部品（PySide6）

  CollapsibleBox … 見出しをクリックして、中身を折りたたむ・開く箱。
                   開閉の状態は、キー（state_key）ごとに ~/.houdini/rag_chatbot_ui.json に覚える。
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QSizePolicy, QToolButton, QVBoxLayout, QWidget

_STATE_PATH = Path.home() / ".houdini" / "rag_chatbot_ui.json"


def _load_state() -> dict:
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # 保存できなくても、開閉はできる


def ui_state_get(key: str, default=None):
    """画面の状態（最後に確認した役割など）を、~/.houdini/rag_chatbot_ui.json から読む。"""
    return _load_state().get(key, default)


def ui_state_set(key: str, value) -> None:
    state = _load_state()
    state[key] = value
    _save_state(state)


class CollapsibleBox(QWidget):
    """見出し（▸/▾ ＋ タイトル）と、折りたためる中身。

    state_key を渡すと、開閉の状態を覚える（次に開いたときも同じ状態）。渡さなければ、覚えない
    （回答ごとの出典など、数が増えるものは覚えない）。
    """

    toggled = Signal(bool)  # True = 開いた

    def __init__(
        self,
        title: str,
        content: QWidget,
        collapsed: bool = True,
        state_key: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._state_key = state_key
        if state_key:
            saved = _load_state().get("collapsed", {}).get(state_key)
            if isinstance(saved, bool):
                collapsed = saved
        self._header = QToolButton()
        self._header.setCheckable(True)
        self._header.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._header.setStyleSheet(
            "QToolButton{border:none;text-align:left;color:#cbd5e1;padding:2px 0;}QToolButton:hover{color:#fff;}"
        )
        self._header.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed
        )  # タイトルが長くても、ペインを広げない
        self._header.clicked.connect(self._on_clicked)
        self._content = content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._header)
        layout.addWidget(self._content)
        self.set_collapsed(collapsed)

    def title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        self._title = title
        self._refresh_header()

    def is_collapsed(self) -> bool:
        return not self._header.isChecked()

    def set_collapsed(self, collapsed: bool) -> None:
        self._header.setChecked(not collapsed)
        self._content.setVisible(not collapsed)
        self._refresh_header()

    def _refresh_header(self) -> None:
        arrow = "▾" if self._header.isChecked() else "▸"
        self._header.setText(f"{arrow} {self._title}")
        self._header.setToolTip(self._title)

    def _on_clicked(self) -> None:
        collapsed = not self._header.isChecked()
        self._content.setVisible(not collapsed)
        self._refresh_header()
        if self._state_key:
            state = _load_state()
            state.setdefault("collapsed", {})[self._state_key] = collapsed
            _save_state(state)
        self.toggled.emit(not collapsed)


def make_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color:#334155;")
    return line
