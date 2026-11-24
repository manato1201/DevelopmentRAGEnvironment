"""
pilot_panel.py — 「課題」タブ（実証実験の参加者向け。PySide6）

  ・最初に1回、事前アンケート（学習背景・経験など。個人を特定する情報は聞かない）。
  ・そのあと、いまの回の「固定課題」と「自由課題」を、開始 → 終了。終了時に、課題後アンケート。
  ・経過時間と、cook エラーのノード数（ErrorSampler）を、課題の間だけ記録する。
  ・アンケートで止めない: 答えなくても閉じられる（「戻る」）。答えなかった項目は空欄のまま送る。
  ・途中で Houdini が閉じても、「続きから開始」で再開できる（途中経過はこのPCに残し、閉じていた時間は所要時間から引く）。
  ・やり直し: 計測中は「計測をやり直す」、終えたあとは「完了した記録」の「やり直す」。参加は1回だけなので、いつでも取り直せる。

接続・保存は rag_client（/pilot/*）。このタブは、接続タブの「実証実験に参加する」を入れたときだけ表示する。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pilot_task as pt
from panel_actions import COLOR_MUTED, COLOR_TEXT, button_qss, px, type_qss
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
# 文字の大きさは、Tutorial タブと同じ 4 段階（panel_actions.type_qss）にそろえた（2026-11-18）


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
    heading = QLabel(question)
    heading.setWordWrap(True)
    layout.addWidget(heading)
    row = QHBoxLayout()
    group = QButtonGroup(box)
    for value in range(1, 6):
        radio = QRadioButton(str(value))
        group.addButton(radio, value)
        row.addWidget(radio)
    row.addStretch()
    layout.addLayout(row)
    # 両端の意味は、選択肢の下に、折り返して出す（長い文でも、横にあふれない）
    ends = QHBoxLayout()
    low_label = QLabel(f"1 = {low}")
    high_label = QLabel(f"5 = {high}")
    for label, align in ((low_label, Qt.AlignLeft), (high_label, Qt.AlignRight)):
        label.setWordWrap(True)
        label.setAlignment(align | Qt.AlignTop)
        label.setStyleSheet(type_qss("caption", COLOR_MUTED))
        ends.addWidget(label, 1)
    layout.addLayout(ends)
    return box, group


def _essay_box(question: str, height: int = 56):
    """自由記述の1問。(widget, QTextEdit) を返す。"""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(1)
    label = QLabel(question)
    label.setWordWrap(True)
    layout.addWidget(label)
    edit = QTextEdit()
    edit.setFixedHeight(height)
    edit.setAcceptRichText(False)
    layout.addWidget(edit)
    return box, edit


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("font-weight:bold;padding-top:8px;")  # 色は指定しない（画面の背景に合わせる）
    return label


class TaskSurveyDialog(QDialog):
    """課題後アンケート。「送信」か「戻る」（閉じても、課題は続いたまま。終了は取り消される）。
    固定課題には、「学びの確認」（Houdini の中身を理解できたか）も出る。1 コマ（約 90 分）に収めるため、すべて任意（答えなくても送れる）。"""

    def __init__(self, parent: QWidget | None, kind: str, label: str, condition: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{pt.KIND_TEXT.get(kind, kind)}の振り返り")
        self.resize(600, 720)
        self._groups: dict[str, QButtonGroup] = {}
        self._essays: dict[str, QTextEdit] = {}
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(f"お疲れさまでした。「{label}」について、答えられるところだけ答えてください（空欄でも構いません。目安: {pt.LEARNING_NOTE.get(kind, '約 2 分')}）。"))
        scroll = QScrollArea()  # 質問が増えても、画面からはみ出さない
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

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

        # 学びの確認: 本システムは、生成物を作れるようになるためではなく、作られたものを追って、Houdini の中身を理解するためのもの
        learning = pt.learning_questions(condition, kind)
        if learning:
            layout.addWidget(_section_label("Houdini について（いまの考えで）"))
            for key, question, low, high in learning:
                widget, group = _scale_row(question, low, high)
                self._groups[key] = group
                layout.addWidget(widget)
        for key, question in pt.essay_questions(kind):
            box, edit = _essay_box(question, 70 if key == "explainOwn" else 50)
            self._essays[key] = edit
            layout.addWidget(box)

        layout.addWidget(QLabel("自由記述（任意）: 困ったこと・良かったこと"))
        self._comment = QTextEdit()
        self._comment.setFixedHeight(70)
        layout.addWidget(self._comment)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        later = QPushButton("戻る（課題を続ける）")
        later.clicked.connect(self.reject)
        send = QPushButton("送信して課題を終える")
        send.setStyleSheet(button_qss("primary"))
        send.clicked.connect(self.accept)
        buttons.addWidget(later)
        buttons.addWidget(send)
        outer.addLayout(buttons)

    def reached(self):
        return True if self._reach_yes.isChecked() else (False if self._reach_no.isChecked() else None)

    def self_mistakes(self):
        value = self._groups["selfMistakes"].checkedId()
        return value if value > 0 else None

    def _checked(self, keys) -> dict:
        return {k: self._groups[k].checkedId() for k in keys if k in self._groups and self._groups[k].checkedId() > 0}

    def answers(self) -> dict:
        """課題後の 6 項目（難しさ・わかりやすさなど）。学びの確認は、learning()。"""
        return {k: g.checkedId() for k, g in self._groups.items() if k != "selfMistakes" and k not in pt.LEARNING_KEYS and g.checkedId() > 0}

    def learning(self) -> dict:
        """学びの確認の 1〜5（固定課題だけ）。"""
        return self._checked(pt.LEARNING_KEYS)

    def essays(self) -> dict:
        return {k: edit.toPlainText() for k, edit in self._essays.items()}

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
        self._survey_dialog = None  # (sessionId, 振り返りの画面)。「戻る」で閉じても、書いた答えを残す
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
        layout.setSpacing(px(8))
        self._header = QLabel("")
        self._header.setStyleSheet(type_qss("heading", COLOR_TEXT))
        layout.addWidget(self._header)
        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setStyleSheet(type_qss("caption", COLOR_MUTED))
        layout.addWidget(self._message)

        # 事前アンケート
        self._profile_box = QFrame()
        self._profile_box.setObjectName("card")
        self._profile_box.setStyleSheet(_CARD_STYLE)
        form = QFormLayout(self._profile_box)
        intro = QLabel("実験の最初に、1回だけ答えてください。氏名など、個人を特定する情報は聞きません。")
        intro.setWordWrap(True)
        form.addRow(intro)
        self._years = QSpinBox()  # 経験は、年と月で聞く（半年刻みでは、粗かった。2026-11-21）
        self._years.setRange(0, 30)
        self._years.setSuffix(" 年")
        self._months = QSpinBox()
        self._months.setRange(0, 11)
        self._months.setSuffix(" ヶ月")
        experience = QWidget()
        experience_row = QHBoxLayout(experience)
        experience_row.setContentsMargins(0, 0, 0, 0)
        experience_row.addWidget(self._years)
        experience_row.addWidget(self._months)
        experience_row.addStretch()
        self._level = QComboBox()
        self._level.addItems(pt.PROFILE_LEVELS)
        self._background = QLineEdit()
        self._background.setPlaceholderText("例: CGコースで2年。モデリングとマテリアルを履修")
        self._practice = QLineEdit()
        self._practice.setPlaceholderText("例: 個人制作のみ／インターン経験あり")
        self._tools = QLineEdit()
        self._tools.setPlaceholderText("例: Blender 2年、Maya 1年、Houdini 半年")
        form.addRow("Houdini の使用経験（触り始めてから、いま）", experience)
        form.addRow("自己評価のレベル", self._level)
        form.addRow("学習背景", self._background)
        form.addRow("実務経験", self._practice)
        form.addRow("ツールの使用歴", self._tools)
        # 学びの確認（事前）。終わったあとに、同じ質問をもう一度聞き、差を見る。答えなくてもよい（約 2 分）。
        form.addRow(_section_label(f"いまの考えを聞かせてください（{pt.LEARNING_NOTE['profile']}。答えなくても始められます）"))
        self._pre_groups: dict[str, QButtonGroup] = {}
        for key, question, low, high in pt.pre_questions():
            widget, group = _scale_row(question, low, high)
            self._pre_groups[key] = group
            form.addRow(widget)
        self._houdini_def = QLineEdit()
        self._houdini_def.setPlaceholderText("例: ノードをつなげて、手順で 3D を作るツール（わからなければ空欄で）")
        form.addRow(pt.HOUDINI_DEF_QUESTION, self._houdini_def)
        self._profile_send = QPushButton("送信して始める")
        self._profile_send.setStyleSheet(button_qss("primary"))
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
            title.setStyleSheet(type_qss("heading", COLOR_TEXT))
            condition = QLabel("")
            condition.setWordWrap(True)
            criterion = QLabel("")
            criterion.setWordWrap(True)
            criterion.setStyleSheet(type_qss("caption", COLOR_MUTED))
            status = QLabel("")
            status.setStyleSheet(type_qss("body", "#cbd5e1"))
            row = QHBoxLayout()
            start = QPushButton("開始")
            finish = QPushButton(_FINISH_TEXT)
            restart = QPushButton("計測をやり直す")
            start.setStyleSheet(button_qss("primary"))
            finish.setStyleSheet(button_qss("primary"))
            restart.setStyleSheet(button_qss("danger"))  # 計測を捨てて、最初からやり直す操作
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
        if plan.get("canStart") is False:  # 受付を止めている（運営が管理画面で切り替える）。参加済みの人は、止まっても続けられる
            self._plan_box.setVisible(False)
            self._message.setText("いま、課題は受け付けていません。運営からの案内をお待ちください。")
            return
        for kind in ("fixed", "free"):
            item, card = plan[kind], self._cards[kind]
            card["title"].setText(pt.format_task_title(kind, item))  # 条件（ツール使用／ドキュメントのみ）は、サーバーの値のまま出す
            card["condition"].setText(pt.CONDITION_TEXT.get(item["condition"], ""))
            card["condition"].setStyleSheet("color:#fbbf24;font-weight:bold;" if item["condition"] == "docs_only" else "color:#34d399;font-weight:bold;")
            card["criterion"].setText(f"到達の基準: {plan.get('criterion', '')}" if kind == "fixed" else "時間が余ったときだけ、自分が作りたいものを題材にしてください。")
            running = bool(self._active and self._active["kind"] == kind)
            locked = bool(item.get("locked"))  # 自由課題は、必須の固定課題を終えたあとに、時間が余ったときだけ（サーバーも、先には始めさせない）
            card["start"].setText("続きから開始" if item.get("active") and not running else "開始")
            card["start"].setEnabled(not item["done"] and not running and self._active is None and not locked)
            card["finish"].setEnabled(running)
            card["finish"].setText("答えを再送する" if running and self._pending_end else _FINISH_TEXT)
            card["restart"].setEnabled(running)
            card["status"].setText("完了しました" if item["done"] else ("記録中…" if running else "固定課題（必須）を終えると、時間が余ったときに行えます" if locked else ""))

    def _rebuild_history(self, history: list) -> None:
        """完了した記録の一覧。「やり直す」が出る（計測中の記録は、カードの「計測をやり直す」）。"""
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
        title.setStyleSheet(type_qss("heading", COLOR_TEXT))
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
        note = QLabel("間違えて終えたときは、「やり直す」で取り直せます。やり直した回数は、記録に残ります。")
        note.setWordWrap(True)
        note.setStyleSheet(type_qss("caption", COLOR_MUTED))
        self._history_layout.addWidget(note)

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "確認", text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    # ── 事前アンケート ──
    def _on_profile_send(self) -> None:
        pre = {k: g.checkedId() for k, g in self._pre_groups.items() if g.checkedId() > 0}
        payload = pt.build_profile_payload(
            self._years.value(), self._level.currentText(), self._background.text(), self._practice.text(), self._tools.text(), months=self._months.value(),
            learning=pre, houdini_def=self._houdini_def.text(),
        )
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
        pt.apply_started(self._plan, started)  # 運営が条件を切り替えていても、実際に記録された条件を出す
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
        # 「戻る」で閉じても、書いた答えは残す（同じ課題の振り返りを開き直したときに、続きから書ける）
        saved = self._survey_dialog
        if saved is not None and saved[0] == active["sessionId"]:
            dialog = saved[1]
        else:
            dialog = TaskSurveyDialog(self, active["kind"], active["label"], active["condition"])
            self._survey_dialog = (active["sessionId"], dialog)
        if not dialog.exec():
            return  # 「戻る」: 課題は続いたまま（終了は取り消される）
        payload = pt.build_end_payload(
            active["sessionId"], dialog.reached(), self._sampler.count, dialog.self_mistakes(), dialog.answers(), dialog.comment(), active["pausedSec"],
            learning=dialog.learning(), essays=dialog.essays(),
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
        if self._survey_dialog is not None:  # 振り返りの画面を、片づける（残した答えは、もう要らない）
            self._survey_dialog[1].deleteLater()
        self._survey_dialog = None
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
