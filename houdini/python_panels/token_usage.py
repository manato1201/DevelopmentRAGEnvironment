"""
token_usage.py — houdini21チュートリアル生成のトークン消費量トラッキング＆可視化

tutorial_agent.py が計測した usage（input/output/cache tokens・コスト）を
`logs/houdini_token_usage.jsonl` に永続化し、累積消費量を「残量ドーナツゲージ」
として可視化する。1レコード = 1回のチュートリアル生成（Houdini再起動をまたいで
累積される）。

ウィジェット単体で import できるよう、Anthropic SDK 等への依存はない
（PySide6 のみ）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

DEFAULT_TOKEN_BUDGET = 500_000
_LOG_RELATIVE_PATH = Path("logs") / "houdini_token_usage.jsonl"


# ─── 永続化 ──────────────────────────────────────────────────────────────────────

def _log_path(bridge_dir: str) -> Optional[Path]:
    if not bridge_dir:
        return None
    return Path(bridge_dir) / _LOG_RELATIVE_PATH


def record_usage(bridge_dir: str, topic: str, result) -> None:
    """
    TutorialResult（tutorial_agent.py）を1レコードとしてJSONLに追記する。
    bridge_dir が未設定の場合は何もしない（設定前でも生成自体は失敗させない）。
    """
    path = _log_path(bridge_dir)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "topic": topic,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cache_write_tokens": result.cache_write_tokens,
        "cache_read_tokens": result.cache_read_tokens,
        "total_tokens": result.total_tokens,
        "cost_usd": result.cost_usd,
        "completed": result.completed,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_summary(bridge_dir: str) -> dict:
    """
    累積トークン消費量・コスト・生成回数を返す。ログが無ければ全て0。
    """
    summary = {"total_tokens": 0, "total_cost_usd": 0.0, "record_count": 0}
    path = _log_path(bridge_dir)
    if path is None or not path.exists():
        return summary
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            summary["total_tokens"] += rec.get("total_tokens", 0)
            summary["total_cost_usd"] += rec.get("cost_usd", 0.0)
            summary["record_count"] += 1
    return summary


# ─── ドーナツゲージ（QPainter直描画） ──────────────────────────────────────────────

class DonutGauge(QWidget):
    """
    「残量」を円弧の塗り具合で表す小型ゲージ。中央にパーセント、直下にラベル。
    used/budget が大きいほど円弧が減っていく（budgetを使い切ると0%）。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._percent = 100.0
        self.setMinimumSize(120, 120)

    def set_percent(self, percent: float) -> None:
        self._percent = max(0.0, min(100.0, percent))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        side = min(self.width(), self.height()) - 12
        rect = QRectF(
            (self.width() - side) / 2, (self.height() - side) / 2, side, side
        )

        track_pen = QPen(QColor("#3a3f4a"), max(6, side // 10))
        track_pen.setCapStyle(Qt.FlatCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        fill_pen = QPen(QColor("#4a90e2"), max(6, side // 10))
        fill_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(fill_pen)
        span = int(360 * 16 * (self._percent / 100.0))
        painter.drawArc(rect, 90 * 16, -span)

        painter.setPen(QColor("#e6e8ee"))
        font = QFont()
        font.setPointSize(max(10, side // 6))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, f"{self._percent:.0f}%")

        painter.end()


class TokenUsageWidget(QWidget):
    """
    Tutorialタブ上部に置く累積トークン使用量パネル。
    refresh(bridge_dir, budget) を呼ぶたびに最新のログを読み直して表示を更新する。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)

        self._gauge = DonutGauge()
        layout.addWidget(self._gauge, alignment=Qt.AlignHCenter)

        self._label = QLabel("トークン残量")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("color:#aaa;font-size:11px;")
        layout.addWidget(self._label)

        self._detail = QLabel("")
        self._detail.setAlignment(Qt.AlignCenter)
        self._detail.setStyleSheet("font-size:13px;font-weight:bold;")
        layout.addWidget(self._detail)

        self._sub = QLabel("")
        self._sub.setAlignment(Qt.AlignCenter)
        self._sub.setStyleSheet("color:#888;font-size:10px;")
        layout.addWidget(self._sub)

    def refresh(self, bridge_dir: str, budget: int) -> None:
        summary = load_summary(bridge_dir)
        used = summary["total_tokens"]
        budget = max(1, budget)
        remaining = max(0, budget - used)
        percent = remaining / budget * 100.0

        self._gauge.set_percent(percent)
        self._detail.setText(f"{remaining:,} / {budget:,}")
        self._sub.setText(
            f"累積コスト ${summary['total_cost_usd']:.3f}"
            f"（生成{summary['record_count']}回）"
        )
        if used > budget:
            self._sub.setStyleSheet("color:#e07a5f;font-size:10px;")
        else:
            self._sub.setStyleSheet("color:#888;font-size:10px;")
