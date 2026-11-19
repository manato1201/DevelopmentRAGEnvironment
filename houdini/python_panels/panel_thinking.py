"""
panel_thinking.py — Chat で、回答を待っているあいだの「確認中…」の表示（2026-11-19）

要望: 応答中の文字が見づらいので、「関連情報を確認中… ●○○」のような動きを加えてほしい（本と虫めがねのアイコン、
文字、順に濃くなる 3 つの点）。以前は、下の細いステータス欄に「応答中...」と出るだけで、待っていることが分かりにくかった。

  ThinkingRow  … チャットの中に出す 1 行（アイコン + 文字 + 動く 3 つの点）。start() で動き、stop() で止まる。
  dot_colors() … 3 つの点の色（どの点が濃いか）。Qt に依存しない純粋な関数（単体テストできる）。
  message_for() … 待った時間に応じた文。最初は「関連情報を確認中」、数秒たつと「回答を作成中」。
  reduced_motion() … 動きを減らす設定のとき True。このときは、点を動かさず、「…」の文字だけにする。

動きを減らす設定は、環境変数 RAGREEL_REDUCE_MOTION=1、または、~/.houdini/rag_chatbot_ui.json の "reduce_motion": true。
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from panel_actions import make_icon, px, type_qss

ACTIVE = "#60a5fa"     # 濃い点
INACTIVE = "#334155"   # 薄い点
TICK_MS = 380          # 点が次へ移る間隔
PHASES = ((0.0, "関連情報を確認中"), (6.0, "回答を作成中"))  # (経過秒, 文)
ICON_NAME = "bookSearch"


def dot_colors(tick: int, count: int = 3) -> list[str]:
    """tick 回目の、count 個の点の色。tick % count 番目の点だけが濃い。"""
    active = tick % max(1, count)
    return [ACTIVE if i == active else INACTIVE for i in range(count)]


def message_for(elapsed_seconds: float) -> str:
    """待った時間に応じた文（PHASES の、いちばん新しいもの）。"""
    text = PHASES[0][1]
    for start, phrase in PHASES:
        if elapsed_seconds >= start:
            text = phrase
    return text


def reduced_motion() -> bool:
    """動きを減らす設定か。"""
    if os.environ.get("RAGREEL_REDUCE_MOTION", "").strip().lower() in ("1", "true", "on", "yes"):
        return True
    try:
        from panel_widgets import ui_state_get

        return bool(ui_state_get("reduce_motion", False))
    except Exception:  # noqa: BLE001 -- 設定が読めなくても、画面は出す
        return False


class _Dots(QWidget):
    """順に濃くなる 3 つの点。"""

    def __init__(self, count: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._count = count
        self._tick = 0
        self.setFixedSize(QSize(px(14) * count + px(6) * (count - 1), px(14)))

    def set_tick(self, tick: int) -> None:
        self._tick = tick
        self.update()

    def colors(self) -> list[str]:
        return dot_colors(self._tick, self._count)

    def paintEvent(self, _event) -> None:  # noqa: N802 -- Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        size, gap = px(14), px(6)
        for i, color in enumerate(self.colors()):
            painter.setBrush(QColor(color))
            painter.drawEllipse(i * (size + gap), 0, size, size)
        painter.end()


class ThinkingRow(QFrame):
    """「関連情報を確認中… ●○○」の 1 行。チャットの回答を待っているあいだだけ出す。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("thinking")
        self.setStyleSheet(f"QFrame#thinking{{background:#1e293b;border-radius:{px(8)}px;}}QLabel{{background:transparent;}}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(px(12), px(10), px(12), px(10))
        layout.setSpacing(px(10))
        self._icon = QLabel()
        icon = make_icon(ICON_NAME, "#60a5fa", 22)
        if icon.isNull():
            self._icon.setText("…")
        else:
            self._icon.setPixmap(icon.pixmap(QSize(px(22), px(22))))
        layout.addWidget(self._icon)
        self._text = QLabel(message_for(0.0))
        self._text.setStyleSheet(type_qss("body", "#e2e8f0"))
        layout.addWidget(self._text)
        self._dots = _Dots()
        layout.addWidget(self._dots)
        layout.addStretch()
        self._reduced = reduced_motion()
        self._dots.setVisible(not self._reduced)
        self._elapsed_ms = 0
        self._tick = 0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self.setAccessibleName("回答を待っています")

    def start(self) -> None:
        self._elapsed_ms, self._tick = 0, 0
        self._refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def text(self) -> str:
        return self._text.text()

    def _on_tick(self) -> None:
        self._elapsed_ms += TICK_MS
        if not self._reduced:  # 動きを減らす設定のときは、点を動かさない（文は、時間で変わる）
            self._tick += 1
        self._refresh()

    def _refresh(self) -> None:
        phrase = message_for(self._elapsed_ms / 1000.0)
        self._text.setText(phrase + ("…" if self._reduced else ""))
        self._dots.set_tick(self._tick)
