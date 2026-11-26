"""
panel_motion.py — Chat の状態変化の小さな動き(ばね)。2026-11-26

Web のチャット画面(cloudflare-rag-poc/src/chatUi.ts の DRMotion)と、同じ値・同じ解き方にしている。
ばねの値は designbookmark の部品(Copy button / Letter limit / Storage meter)に合わせた。
元のコードは写していない(ライセンスの記載が無いため。値と、ふるまいの決まりだけを合わせて自作した)。

  step()          … ばねを 1 フレーム進める(Qt に依存しない純粋な関数。単体テストできる)。
  Spring          … QTimer で値を目標へ寄せ、値が変わるたびに on_change を呼ぶ。
  CopyFeedback    … 回答のコピーボタン。押すとアイコンが回りながら ✓ に変わり、1.8 秒で戻る。
  LetterLimitRing … 質問の文字数の輪。400 字から出て、残り 80 字で橙、800 字を超えると赤になり、一度だけ揺れる。
                    入力は止めない(800 字は、続けて質問したとき前の質問が文脈に残る長さ。src/query.ts)。

動きを減らす設定(panel_thinking.reduced_motion)のときは、ばねを使わず、すぐに目標の値にする。
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget

from panel_actions import COLOR_MUTED, COLOR_NORMAL, make_icon, px
from panel_thinking import reduced_motion

# (stiffness, damping)。質量は 1。Web の DRMotion.SPRINGS と同じ。
SPRINGS: dict[str, tuple[float, float]] = {
    "copyIcon": (420, 18),
    "limitFill": (280, 22),
    "limitPop": (520, 16),
    "limitShake": (700, 12),
    "meterWidth": (260, 24),
    "meterSquash": (520, 16),
}
COPY_REVERT_MS = 1800
Q_SOFT_LIMIT = 800             # 続けて質問したとき、前の質問が文脈に残る長さ(src/query.ts の slice(0, 800))
Q_SHOW_FROM = Q_SOFT_LIMIT // 2  # この字数から輪を出す
Q_NEAR = Q_SOFT_LIMIT // 10      # 残りがこの字数以下で、橙にする

COLOR_DONE = "#4ade80"   # コピーできた(いいねの色と同じ)
COLOR_NEAR = "#fbbf24"   # 残りわずか(ブックマークの色と同じ)
COLOR_OVER = "#f87171"   # 超えた(悪いねの色と同じ)
COLOR_TRACK = "#334155"

_FRAME_MS = 16
_SUBSTEPS = 4
_MAX_DT = 1.0 / 30.0


def step(x: float, v: float, target: float, stiffness: float, damping: float, dt: float) -> tuple[float, float]:
    """ばねを dt 秒進める。半陰的オイラー(速度を先に更新)を 4 回に分けて解く。dt は 1/30 秒で頭打ち。"""
    dt = min(max(dt, 0.0), _MAX_DT)
    h = dt / _SUBSTEPS
    for _ in range(_SUBSTEPS):
        a = -stiffness * (x - target) - damping * v
        v += a * h
        x += v * h
    return x, v


def at_rest(x: float, v: float, target: float) -> bool:
    """止まったとみなすか(位置の差 0.001 未満・速さ 0.01 未満)。"""
    return abs(x - target) < 0.001 and abs(v) < 0.01


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


class Spring(QObject):
    """値を目標へ、ばねで寄せる。動いているあいだだけ QTimer が回る(止まったら止める)。"""

    def __init__(self, name: str, value: float = 0.0, on_change: Optional[Callable[[float], None]] = None,
                 parent: Optional[QObject] = None, reduced: Optional[Callable[[], bool]] = None) -> None:
        super().__init__(parent)
        self._k, self._c = SPRINGS[name]
        self.value = float(value)
        self.target = float(value)
        self.velocity = 0.0
        self._on_change = on_change
        self._reduced = reduced or reduced_motion
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._last = 0.0

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def jump(self, value: float) -> None:
        """動かさずに、その値にする(目標も同じにする)。"""
        self.value = self.target = float(value)
        self.velocity = 0.0
        self._timer.stop()
        self._emit()

    def to(self, target: float) -> None:
        """目標を変える。動きを減らす設定のときは、すぐにその値にする。"""
        if self._reduced():
            self.jump(target)
            return
        self.target = float(target)
        self._start()

    def kick(self, velocity: float) -> None:
        """速さを足す(揺れ)。動きを減らす設定のときは、何もしない。"""
        if self._reduced():
            return
        self.velocity += velocity
        self._start()

    def advance(self, dt: float) -> None:
        """dt 秒進める(QTimer から呼ぶ。テストでは直接呼ぶ)。"""
        self.value, self.velocity = step(self.value, self.velocity, self.target, self._k, self._c, dt)
        if at_rest(self.value, self.velocity, self.target):
            self.value = self.target
            self.velocity = 0.0
            self._timer.stop()
        self._emit()

    def _start(self) -> None:
        if not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        self.advance(dt)

    def _emit(self) -> None:
        if self._on_change is not None:
            self._on_change(self.value)


class CopyFeedback(QObject):
    """
    回答のコピーボタン(panel_actions.action_button("copy", ...))に付ける。copied() を呼ぶと、
    コピーのアイコンが回りながら小さく消え、✓ が弾んで出る。1.8 秒で元に戻る。ツールチップも「コピーしました」に変わる。
    """

    def __init__(self, button: QToolButton, idle_tip: str) -> None:
        super().__init__(button)
        self._btn = button
        self._idle_tip = idle_tip
        self._idle_text = button.text()
        side = button.iconSize().width() or px(16)
        self._side = side
        self._copy_pm = make_icon("copy", COLOR_NORMAL).pixmap(side, side)
        self._ok_pm = make_icon("check", COLOR_DONE).pixmap(side, side)
        self._has_icons = not self._copy_pm.isNull() and not self._ok_pm.isNull()
        self.done = False
        self._spring = Spring("copyIcon", 0.0, self._render, self)
        self._revert = QTimer(self)
        self._revert.setSingleShot(True)
        self._revert.setInterval(COPY_REVERT_MS)
        self._revert.timeout.connect(self._reset)

    def copied(self) -> None:
        self.done = True
        self._set_tip("コピーしました")
        if not self._has_icons:  # SVG が使えない環境: 文字を入れ替えるだけ
            self._btn.setText("✓")
        self._spring.to(1.0)
        self._revert.start()

    def _reset(self) -> None:
        self.done = False
        self._set_tip(self._idle_tip)
        if not self._has_icons:
            self._btn.setText(self._idle_text)
        self._spring.to(0.0)

    def _set_tip(self, text: str) -> None:
        self._btn.setToolTip(text)
        self._btn.setAccessibleName(text)

    def _render(self, x: float) -> None:
        """x = 0(コピー)〜 1(✓)。Web と同じ: コピーは縮みながら -40° 回って消え、✓ は 0.4 倍から弾んで出る。"""
        if not self._has_icons:
            return
        i = max(-0.2, min(1.2, x))
        p = _clamp01(i)
        dpr = self._copy_pm.devicePixelRatio() or 1.0
        canvas = QPixmap(self._copy_pm.size())
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(Qt.transparent)
        logical = self._copy_pm.width() / dpr
        center = QPointF(logical / 2, logical / 2)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        for pm, opacity, scale, angle in (
            (self._copy_pm, _clamp01(1 - 1.6 * i), 1 - 0.5 * p, -40 * p),
            (self._ok_pm, _clamp01(1.6 * i - 0.4), 0.4 + 0.6 * i, 0.0),
        ):
            if opacity <= 0.0:
                continue
            painter.save()
            painter.setOpacity(opacity)
            painter.translate(center)
            painter.rotate(angle)
            painter.scale(scale, scale)
            painter.translate(-center)
            painter.drawPixmap(0, 0, pm)
            painter.restore()
        painter.end()
        self._btn.setIcon(QIcon(canvas))


class LetterLimitRing(QWidget):
    """
    質問の文字数の輪と、残りの字数。set_count(n) で更新する。
    400 字未満では隠れる。残り 80 字以下で橙、800 字を超えると赤になり、超えた瞬間だけ大きく弾んで首を振る。
    字数が変わるたびに、数字が小さく弾む。入力は止めない(説明はツールチップに出す)。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._count = 0
        self._was_over = False
        self._fill = Spring("limitFill", 0.0, lambda _v: self.update(), self)
        self._pop = Spring("limitPop", 1.0, lambda _v: self.update(), self)
        self._shake = Spring("limitShake", 0.0, lambda _v: self.update(), self)
        self.setFixedSize(px(64), px(22))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setVisible(False)

    @property
    def state(self) -> str:
        """"hidden" / "ok" / "near" / "over"。"""
        if self._count < Q_SHOW_FROM:
            return "hidden"
        left = Q_SOFT_LIMIT - self._count
        return "over" if left < 0 else "near" if left <= Q_NEAR else "ok"

    @property
    def remaining(self) -> int:
        return Q_SOFT_LIMIT - self._count

    def set_count(self, n: int) -> None:
        prev = self._count
        self._count = max(0, int(n))
        show = self._count >= Q_SHOW_FROM
        if show and self.isHidden():
            self._fill.jump(self._count / Q_SOFT_LIMIT)  # 出た瞬間は、動かさずに合わせる
        self.setVisible(show)
        if not show:
            self._was_over = False
            return
        over = self.remaining < 0
        tip = ("800 字を超えた分は、続けて質問したときの文脈には入りません(この質問の検索・回答には使います)"
               if over else "続けて質問したとき、前の質問は 800 字まで文脈に入ります")
        self.setToolTip(tip)
        self.setAccessibleName(f"残り {self.remaining} 字。{tip}")
        if self._count != prev:
            self._pop.jump(1.25 if over and not self._was_over else 1.12)
            self._pop.to(1.0)
        if over and not self._was_over:
            self._shake.kick(34)  # 超えた瞬間だけ、首を振る
        self._was_over = over
        self._fill.to(self._count / Q_SOFT_LIMIT)
        self.update()

    def _color(self) -> QColor:
        return QColor({"over": COLOR_OVER, "near": COLOR_NEAR}.get(self.state, COLOR_MUTED))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = self._color()
        d = px(16)
        cy = self.height() / 2
        shake = self._shake.value * px(1)  # 揺れ(px)。Web と同じく、数字は x、輪は x/2 だけ横にずらす

        # 輪(下地 + 埋まった分)
        rect = QRectF(px(2) + shake / 2, cy - d / 2, d, d)
        width = max(2.0, px(2.5))
        painter.setPen(QPen(QColor(COLOR_TRACK), width))
        painter.drawEllipse(rect)
        pen = QPen(color, width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        span = int(-360 * 16 * _clamp01(self._fill.value))
        painter.drawArc(rect, 90 * 16, span)

        # 残りの字数(弾む)
        painter.save()
        text_rect = QRectF(rect.right() + px(5), 0, self.width() - rect.right() - px(5), self.height())
        text_rect.translate(shake / 2, 0)  # 輪で x/2 ずれているので、残りの x/2 を足す
        origin = QPointF(text_rect.left(), cy)
        painter.translate(origin)
        painter.scale(self._pop.value, self._pop.value)
        painter.translate(-origin)
        font = QFont(self.font())
        font.setBold(self.state == "over")
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, str(self.remaining))
        painter.restore()
        painter.end()
