"""
token_usage.py — houdini21チュートリアル生成のトークン消費量トラッキング＆可視化

表示するゲージは2種類ある:
  ① Claudeトークン残量（サーバー管理・実際に強制される上限）
     GAS（gas_cloud_rag.js）が action:'claude_messages' の応答に含めて返す
     claudeQuota（そのAPIキーの実際の残高/上限）をそのまま表示する。この値は
     GAS の API_KEYS_CONFIG（claudeCapacity/claudeBalance）が唯一の正であり、
     Houdini側ではローカルに上限を計算・改ざんできない（docs/cloud-rag.md §8.14）。
     直近の値は logs/houdini_claude_quota_cache.json にキャッシュし、Houdini
     再起動直後もパネルが空にならないようにするだけで、判定には使わない
     （実際の許可/拒否は毎回GAS側が判定する）。
  ② ローカル生成ログ（このHoudiniでの累積、参考値）
     tutorial_agent.py が計測した usage を logs/houdini_token_usage.jsonl に
     追記し、このHoudiniからの累積トークン数・コストを表示する。これは
     ユーザー自身の目安であり、上限の強制には一切使わない。

ウィジェット単体で import できるよう、Anthropic SDK 等への依存はない
（PySide6 のみ）。
"""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

_LOG_RELATIVE_PATH = Path("logs") / "houdini_token_usage.jsonl"
_QUOTA_CACHE_RELATIVE_PATH = Path("logs") / "houdini_claude_quota_cache.json"


# ─── 永続化: ローカル生成ログ（参考値） ─────────────────────────────────────────────

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


# ─── 永続化: サーバー側Claude残高のキャッシュ（表示専用、判定には使わない） ──────────────

def _quota_cache_path(bridge_dir: str) -> Optional[Path]:
    if not bridge_dir:
        return None
    return Path(bridge_dir) / _QUOTA_CACHE_RELATIVE_PATH


def save_server_quota(
    bridge_dir: str,
    balance: Optional[int],
    capacity: Optional[int],
    reset_interval_hours: Optional[int] = None,
    reset_at: Optional[str] = None,
) -> None:
    path = _quota_cache_path(bridge_dir)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "balance": balance,
            "capacity": capacity,
            "reset_interval_hours": reset_interval_hours,
            "reset_at": reset_at,
            "ts": time.time(),
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def load_cached_server_quota(bridge_dir: str) -> Optional[dict]:
    path = _quota_cache_path(bridge_dir)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _format_recovery_note(reset_interval_hours: Optional[int], reset_at: Optional[str]) -> str:
    """自動回復タイミングの説明文を作る（自動回復オフなら手動チャージが必要な旨を表示）。"""
    if not reset_interval_hours:
        return "自動回復は設定されていません（管理者にチャージを依頼してください）"
    when = "不明"
    if reset_at:
        try:
            dt = datetime.datetime.fromisoformat(reset_at.replace("Z", "+00:00")).astimezone()
            when = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            when = reset_at
    return f"次回自動回復: {when}（{reset_interval_hours}時間毎）"


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
    Tutorialタブ上部に置くトークン使用量パネル。

    ゲージ本体はGASが報告する「Claudeトークン残高（サーバー管理・実際の上限）」を
    表示する。生成のたびに tutorial_view.py が set_server_quota() を呼んで更新する。
    その下の小さいテキストは、このHoudiniからの累積送信量（ローカル記録・参考値）。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)

        self._gauge = DonutGauge()
        layout.addWidget(self._gauge, alignment=Qt.AlignHCenter)

        self._label = QLabel("Claudeトークン残量（サーバー管理）")
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

        self._local_sub = QLabel("")
        self._local_sub.setAlignment(Qt.AlignCenter)
        self._local_sub.setStyleSheet("color:#666;font-size:9px;")
        layout.addWidget(self._local_sub)

    def set_server_quota(
        self,
        balance: Optional[int],
        capacity: Optional[int],
        reset_interval_hours: Optional[int] = None,
        reset_at: Optional[str] = None,
    ) -> None:
        """GASから返された最新のClaudeトークン残高/上限/回復タイミングを表示する（唯一の正）。"""
        if capacity is None:
            self._gauge.set_percent(100.0)
            self._detail.setText("無制限")
            self._sub.setText("このAPIキーにはClaudeトークン上限が設定されていません")
            self._sub.setStyleSheet("color:#888;font-size:10px;")
            return
        percent = (balance / capacity * 100.0) if capacity > 0 else 0.0
        self._gauge.set_percent(percent)
        self._detail.setText(f"{balance:,} / {capacity:,}")
        recovery_note = _format_recovery_note(reset_interval_hours, reset_at)
        if percent <= 15:
            self._sub.setText(f"残量が少なくなっています。{recovery_note}")
            self._sub.setStyleSheet("color:#e07a5f;font-size:10px;")
        else:
            self._sub.setText(recovery_note)
            self._sub.setStyleSheet("color:#888;font-size:10px;")

    def _set_unknown(self) -> None:
        self._gauge.set_percent(100.0)
        self._detail.setText("未取得")
        self._sub.setText("チュートリアルを1回生成すると表示されます")
        self._sub.setStyleSheet("color:#888;font-size:10px;")

    def refresh(self, bridge_dir: str) -> None:
        """
        パネル初期表示・生成後の更新用。サーバー残高はキャッシュ（表示専用、
        判定には使わない）があればそれを表示し、無ければ「未取得」にする。
        ローカル生成ログの累積は下部に小さく参考表示する。
        """
        cached = load_cached_server_quota(bridge_dir)
        if cached is not None:
            self.set_server_quota(
                cached.get("balance"),
                cached.get("capacity"),
                cached.get("reset_interval_hours"),
                cached.get("reset_at"),
            )
        else:
            self._set_unknown()

        summary = load_summary(bridge_dir)
        if summary["record_count"] > 0:
            self._local_sub.setText(
                f"（このHoudiniでの累積: {summary['total_tokens']:,} トークン / "
                f"${summary['total_cost_usd']:.3f} / 生成{summary['record_count']}回・参考値）"
            )
        else:
            self._local_sub.setText("")
