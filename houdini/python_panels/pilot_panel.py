"""
pilot_panel.py — 「課題」タブ（実証実験の参加者向け。PySide6）

  ・最初に1回、事前アンケート（学習背景・経験など。個人を特定する情報は聞かない）。
  ・そのあと、いまの回の「固定課題」と「自由課題」を、開始 → 終了。終了時に、課題後アンケート。
  ・経過時間と、cook エラーのノード数（ErrorSampler）を、課題の間だけ記録する。
  ・アンケートで止めない: 答えなくても閉じられる（「戻る」）。答えなかった項目は空欄のまま送る。
  ・途中で Houdini が閉じても、「続きから開始」で再開できる（途中経過はこのPCに残し、閉じていた時間は所要時間から引く）。
  ・やり直し: 計測中は「計測をやり直す」、終えたあとは「完了した記録」の「やり直す」。次の回を始めるまでは、前の回も直せる。

接続・保存は rag_client（/pilot/*）。このタブは、接続タブの「実証実験に参加する」を入れたときだけ表示する。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pilot_task as pt
from panel_info import friendly_error
from rag_client import RAGClient

try:  # Houdini の外（単体テスト・画面だけの確認）では、cook エラーは測れない
    import hou  # type: ignore
except ImportError:  # pragma: no cover
    hou = None

_SAMPLE_INTERVAL_MS = 20_000  # cook エラーの採取の間隔
_PROGRESS_PATH = Path.home() / ".houdini" / "rag_pilot_progress.json"
_FINISH_TEXT = "終了して振り返りへ"
_CARD_STYLE = "QFrame#card{background:#1e293b;border-radius:6px;}QLabel{background:transparent;}"


class _CallWorker(QThread):
    """サーバー呼び出しを別スレッドで行う（画面を止めない）。"""
    finished_with = Signal(object, str)  # (応答, エラー文。成功なら空)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.finished_with.emit(self._fn(), "")
        except Exception as exc:  # noqa: BLE001
            self.finished_with.emit(None, str(exc))


def _scale_row(question: str, low: str, high: str):
    """1〜5 を選ぶ1行。最初は未選択（答えなくてよい）。(widget, group) を返す。"""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(1)
    layout.addWidget(QLabel(question))
    row = QHBoxLayout()
    row.addWidget(QLabel(f"1 {low}"))
    group = QButtonGroup(box)
    for value in range(1, 6):
        radio = QRadioButton(str(value))
        group.addButton(radio, value)
        row.addWidget(radio)
    row.addWidget(QLabel(f"5 {high}"))
    row.addStretch()
    layout.addLayout(row)
    return box, group


class TaskSurveyDialog(QDialog):
    """課題後アンケート。「送信」か「戻る」（閉じても、課題は続いたまま。終了は取り消される）。"""

    def __init__(self, parent: QWidget | None, kind: str, label: str, condition: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{pt.KIND_TEXT.get(kind, kind)}の振り返り")
        self.resize(560, 640)
        self._groups: dict[str, QButtonGroup] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"お疲れさまでした。「{label}」について、答えられるところだけ答えてください（空欄でも構いません）。"))

        # 到達: 課題の題材として、作品物ができているか
        layout.addWidget(QLabel("課題の題材として、作品物ができましたか"))
        reach_row = QHBoxLayout()
        self._reach_yes = QRadioButton("できた")
        self._reach_no = QRadioButton("できなかった")
        reach_row.addWidget(self._reach_yes)
        reach_row.addWidget(self._reach_no)
        reach_row.addStretch()
        layout.addLayout(reach_row)

        for key, question, low, high in [pt.SELF_MISTAKE_QUESTION, *pt.survey_questions(condition)]:
            widget, group = _scale_row(question, low, high)
            self._groups[key] = group
            layout.addWidget(widget)

        layout.addWidget(QLabel("自由記述（任意）: 困ったこと・良かったこと"))
        self._comment = QTextEdit()
        self._comment.setFixedHeight(70)
        layout.addWidget(self._comment)

        buttons = QHBoxLayout()
        buttons.addStretch()
        later = QPushButton("戻る（課題を続ける）")
        later.clicked.connect(self.reject)
        send = QPushButton("送信して課題を終える")
        send.clicked.connect(self.accept)
        buttons.addWidget(later)
        buttons.addWidget(send)
        layout.addLayout(buttons)

    def reached(self):
        return True if self._reach_yes.isChecked() else (False if self._reach_no.isChecked() else None)

    def self_mistakes(self):
        value = self._groups["selfMistakes"].checkedId()
        return value if value > 0 else None

    def answers(self) -> dict:
        return {k: g.checkedId() for k, g in self._groups.items() if k != "selfMistakes" and g.checkedId() > 0}

    def comment(self) -> str:
        return self._comment.toPlainText()


class PilotTaskPanel(QWidget):
    def __init__(self, cfg_getter, parent: QWidget | None = None, progress_path=None) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._workers: list[_CallWorker] = []
        self._plan: dict | None = None
        self._active: dict | None = None  # {sessionId, startedAt, kind, condition, label, pausedSec}
        self._pending_end: dict | None = None  # 送信に失敗した終了（答えを残して、再送する）
        self._sampler = pt.ErrorSampler(hou)
        self._progress = pt.ProgressStore(progress_path or _PROGRESS_PATH)
        self._build_ui()
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._sample_timer = QTimer(self)
        self._sample_timer.timeout.connect(self._on_sample)

    # ── 画面 ──
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self._header = QLabel("")
        self._header.setStyleSheet("font-weight:bold;")
        layout.addWidget(self._header)
        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setStyleSheet("color:#94a3b8;")
        layout.addWidget(self._message)

        # 事前アンケート
        self._profile_box = QFrame()
        self._profile_box.setObjectName("card")
        self._profile_box.setStyleSheet(_CARD_STYLE)
        form = QFormLayout(self._profile_box)
        intro = QLabel("実験の最初に、1回だけ答えてください。氏名など、個人を特定する情報は聞きません。")
        intro.setWordWrap(True)
        form.addRow(intro)
        self._years = QDoubleSpinBox()
        self._years.setRange(0, 30)
        self._years.setSingleStep(0.5)
        self._years.setSuffix(" 年")
        self._level = QComboBox()
        self._level.addItems(pt.PROFILE_LEVELS)
        self._background = QLineEdit()
        self._background.setPlaceholderText("例: CGコースで2年。モデリングとマテリアルを履修")
        self._practice = QLineEdit()
        self._practice.setPlaceholderText("例: 個人制作のみ／インターン経験あり")
        self._tools = QLineEdit()
        self._tools.setPlaceholderText("例: Blender 2年、Maya 1年、Houdini 半年")
        form.addRow("Houdini の使用経験", self._years)
        form.addRow("自己評価のレベル", self._level)
        form.addRow("学習背景", self._background)
        form.addRow("実務経験", self._practice)
        form.addRow("ツールの使用歴", self._tools)
        self._profile_send = QPushButton("送信して始める")
        self._profile_send.clicked.connect(self._on_profile_send)
        form.addRow(self._profile_send)
        layout.addWidget(self._profile_box)

        # 課題（固定・自由）
        self._cards: dict[str, dict] = {}
        self._plan_box = QWidget()
        plan_layout = QVBoxLayout(self._plan_box)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        for kind in ("fixed", "free"):
            card = QFrame()
            card.setObjectName("card")
            card.setStyleSheet(_CARD_STYLE)
            inner = QVBoxLayout(card)
            title = QLabel("")
            title.setStyleSheet("font-weight:bold;")
            condition = QLabel("")
            condition.setWordWrap(True)
            criterion = QLabel("")
            criterion.setWordWrap(True)
            criterion.setStyleSheet("color:#94a3b8;")
            status = QLabel("")
            status.setStyleSheet("color:#cbd5e1;")
            row = QHBoxLayout()
            start = QPushButton("開始")
            finish = QPushButton(_FINISH_TEXT)
            restart = QPushButton("計測をやり直す")
            start.clicked.connect(lambda _c=False, k=kind: self._on_start(k))
            finish.clicked.connect(self._on_finish)
            restart.clicked.connect(self._on_restart)
            row.addWidget(start)
            row.addWidget(finish)
            row.addWidget(restart)
            row.addStretch()
            for w in (title, condition, criterion, status):
                inner.addWidget(w)
            inner.addLayout(row)
            plan_layout.addWidget(card)
            self._cards[kind] = {"title": title, "condition": condition, "criterion": criterion, "status": status, "start": start, "finish": finish, "restart": restart}
        layout.addWidget(self._plan_box)

        # 完了した記録（間違えて終えたとき・取り直したいときの、やり直し）
        self._history_box = QFrame()
        self._history_box.setObjectName("card")
        self._history_box.setStyleSheet(_CARD_STYLE)
        self._history_layout = QVBoxLayout(self._history_box)
        layout.addWidget(self._history_box)

        refresh = QPushButton("更新")
        refresh.setFixedWidth(80)
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        layout.addStretch()
        self._profile_box.setVisible(False)
        self._plan_box.setVisible(False)
        self._history_box.setVisible(False)

    # ── サーバー呼び出し ──
    def _call(self, fn, on_done, on_error=None) -> None:
        worker = _CallWorker(fn)

        def done(result, error: str) -> None:
            if worker in self._workers:
                self._workers.remove(worker)
            if error:
                self._message.setText(friendly_error(error))
                if on_error:
                    on_error()
                return
            on_done(result)

        worker.finished_with.connect(done)
        self._workers.append(worker)  # 終わるまで参照を保つ
        worker.start()

    def _client(self) -> RAGClient:
        return RAGClient(self._cfg_getter())

    def refresh(self) -> None:
        self._message.setText("読み込み中…")
        self._call(lambda: self._client().pilot_plan(), self._apply_plan)

    def _apply_plan(self, plan: dict) -> None:
        self._plan = plan
        self._message.setText("")
        if not plan.get("profile"):
            self._header.setText("実証実験への参加")
            self._profile_box.setVisible(True)
            self._plan_box.setVisible(False)
            self._history_box.setVisible(False)
            return
        self._profile_box.setVisible(False)
        self._plan_box.setVisible(True)
        self._header.setText(pt.format_plan_header(plan))
        self._rebuild_history(plan.get("history") or [])
        if plan.get("finished"):
            self._plan_box.setVisible(False)
            return
        for kind in ("fixed", "free"):
            item, card = plan[kind], self._cards[kind]
            card["title"].setText(f"{pt.KIND_TEXT[kind]}: {item['label']}")
            card["condition"].setText(pt.CONDITION_TEXT.get(item["condition"], ""))
            card["condition"].setStyleSheet("color:#fbbf24;" if item["condition"] == "docs_only" else "color:#cbd5e1;")
            card["criterion"].setText(f"到達の基準: {plan.get('criterion', '')}" if kind == "fixed" else "自分が作りたいものを題材にしてください。")
            running = bool(self._active and self._active["kind"] == kind)
            card["start"].setText("続きから開始" if item.get("active") and not running else "開始")
            card["start"].setEnabled(not item["done"] and not running and self._active is None)
            card["finish"].setEnabled(running)
            card["finish"].setText("答えを再送する" if running and self._pending_end else _FINISH_TEXT)
            card["restart"].setEnabled(running)
            card["status"].setText("完了しました" if item["done"] else ("" if not running else "記録中…"))

    def _rebuild_history(self, history: list) -> None:
        """完了した記録の一覧。次の回を始める前なら、「やり直す」が出る（計測中の記録は、カードの「計測をやり直す」）。"""
        while self._history_layout.count():
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        done = [h for h in history if not h.get("running")]
        self._history_box.setVisible(bool(done))
        if not done:
            return
        title = QLabel("完了した記録")
        title.setStyleSheet("font-weight:bold;")
        self._history_layout.addWidget(title)
        for item in done:
            row = QHBoxLayout()
            row.addWidget(QLabel(pt.format_history_line(item)))
            row.addStretch()
            if item.get("redoable"):
                redo = QPushButton("やり直す")
                redo.setEnabled(self._active is None)
                redo.clicked.connect(lambda _c=False, i=item: self._on_redo(i))
                row.addWidget(redo)
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            self._history_layout.addWidget(holder)
        note = QLabel("間違えて終えたときは、「やり直す」で取り直せます（次の回を始めるまで）。やり直した回数は、記録に残ります。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#94a3b8;")
        self._history_layout.addWidget(note)

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "確認", text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    # ── 事前アンケート ──
    def _on_profile_send(self) -> None:
        payload = pt.build_profile_payload(self._years.value(), self._level.currentText(), self._background.text(), self._practice.text(), self._tools.text())
        self._profile_send.setEnabled(False)
        self._call(lambda: self._client().pilot_profile(payload), self._on_profile_done)

    def _on_profile_done(self, plan: dict) -> None:
        self._profile_send.setEnabled(True)
        self._apply_plan(plan)

    # ── 課題の開始・終了 ──
    def _on_start(self, kind: str) -> None:
        self._call(lambda: self._client().pilot_session_start(kind), self._on_started)

    def _on_started(self, started: dict) -> None:
        # 続きからのときは、前に集めたエラーのノードと、閉じていた時間（中断）を引き継ぐ
        saved = self._progress.load(started["sessionId"]) if started.get("resumed") else None
        paths, paused = pt.resume_state(saved, time.time())
        self._active = {
            "sessionId": started["sessionId"], "startedAt": float(started["startedAt"]), "kind": started["kind"],
            "condition": started["condition"], "label": started["label"], "pausedSec": paused,
        }
        self._pending_end = None
        self._sampler.reset()
        self._sampler.restore(paths)
        self._on_sample()
        self._tick.start(1000)
        self._sample_timer.start(_SAMPLE_INTERVAL_MS)
        if self._plan:
            self._apply_plan(self._plan)
        self._on_tick()

    def _on_sample(self) -> None:
        """cook エラーを採取し、途中経過をこのPCに残す（Houdini が閉じても、続きから引き継げるように）。"""
        self._sampler.sample()
        if self._active:
            self._progress.save(self._active["sessionId"], self._sampler.paths, self._active["pausedSec"], time.time())

    def _on_tick(self) -> None:
        if not self._active:
            return
        card = self._cards[self._active["kind"]]
        elapsed = pt.format_elapsed(time.time() - self._active["startedAt"] - self._active["pausedSec"])
        errors = self._sampler.count
        card["status"].setText(f"記録中 {elapsed}" + (f"　cookエラーのノード: {errors}" if errors is not None else ""))

    def _on_finish(self) -> None:
        if not self._active:
            return
        if self._pending_end:  # 前回は、送れなかった。答えは残っているので、そのまま再送する
            self._send_end()
            return
        self._sampler.sample()  # 終了時の分も数える
        active = self._active
        pressed = time.monotonic()
        dialog = TaskSurveyDialog(self, active["kind"], active["label"], active["condition"])
        if not dialog.exec():
            return  # 「戻る」: 課題は続いたまま（終了は取り消される）
        payload = pt.build_end_payload(
            active["sessionId"], dialog.reached(), self._sampler.count, dialog.self_mistakes(), dialog.answers(), dialog.comment(), active["pausedSec"],
        )
        self._pending_end = {"payload": payload, "pressed": pressed}
        self._send_end()

    def _send_end(self) -> None:
        pending = self._pending_end
        # 終了を押してから送るまで（振り返りの回答・再送の待ち）は、作業の時間に入れない。サーバーが、送信の時刻から引く。
        payload = {**pending["payload"], "surveySec": int(time.monotonic() - pending["pressed"])}
        self._call(lambda: self._client().pilot_session_end(payload), self._on_ended, self._on_end_failed)

    def _on_end_failed(self) -> None:
        self._message.setText(self._message.text() + "　答えは残してあります。「答えを再送する」を押してください。")
        if self._active:
            self._cards[self._active["kind"]]["finish"].setText("答えを再送する")

    def _stop_recording(self) -> None:
        self._active = None
        self._pending_end = None
        self._tick.stop()
        self._sample_timer.stop()
        self._progress.clear()

    def _on_ended(self, plan: dict) -> None:
        self._stop_recording()
        self._apply_plan(plan)
        self._message.setText("送信しました。ご協力ありがとうございます。")

    # ── やり直し ──
    def _on_restart(self) -> None:
        """計測中の課題を破棄して、最初からやり直す。"""
        if not self._active:
            return
        if not self._confirm("いまの計測を破棄して、最初からやり直しますか？\nこれまでの計測は、集計に入りません。"):
            return
        session_id = self._active["sessionId"]
        self._call(lambda: self._client().pilot_session_reset(session_id), self._on_reset_done)

    def _on_redo(self, item: dict) -> None:
        """完了した記録を破棄して、同じ課題を取り直す。"""
        if not self._confirm(f"「{pt.format_history_line(item)}」の記録を消して、もう一度行いますか？\n消した記録は、集計に入りません。"):
            return
        session_id = item["sessionId"]
        self._call(lambda: self._client().pilot_session_reset(session_id), self._on_reset_done)

    def _on_reset_done(self, plan: dict) -> None:
        self._stop_recording()
        self._apply_plan(plan)
        self._message.setText("記録を破棄しました。もう一度、「開始」から行えます。")
