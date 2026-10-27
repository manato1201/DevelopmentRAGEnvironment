"""
report_dialog.py — 「評価の集計」の画面（PySide6）

データの組み立ては tutorial_feedback.build_report（Qt に依存しない）。ここは見せるだけ。
  ・上に要点（保存数・評価数・👍/👎・好評率・費用）を大きく出す。
  ・評価が少ないときの注意は、表の上に1か所だけ。
  ・項目別の表はタブで切り替える。列の見出しをクリックすると並べ替え、見出しに触れると列の説明が出る。
  ・好評率は色で読める（高い=緑、中=黄、低=赤）。評価が少ない行は、数字を出さずに「—」にする。
  ・CSVで保存できる（Excel で開ける）。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import tutorial_feedback as fb

_STYLE = """
QDialog{background:#0f172a;color:#e2e8f0;}
QLabel{color:#e2e8f0;}
QTabWidget::pane{border:1px solid #334155;}
QTabBar::tab{background:#1e293b;color:#cbd5e1;padding:5px 14px;border:1px solid #334155;border-bottom:none;}
QTabBar::tab:selected{background:#334155;color:#fff;}
QTableWidget{background:#0f172a;alternate-background-color:#131d33;color:#e2e8f0;gridline-color:#1e293b;border:none;}
QHeaderView::section{background:#1e293b;color:#cbd5e1;border:none;border-right:1px solid #334155;padding:4px 6px;}
QTextEdit{background:#0f172a;color:#e2e8f0;border:none;}
"""

_GOOD, _MID, _BAD = QColor("#14532d"), QColor("#713f12"), QColor("#7f1d1d")
_MUTED = QColor("#64748b")


class _SortItem(QTableWidgetItem):
    """表示は文字、並べ替えは数値。値の無いもの（None）は、昇順でも降順でも最後に回す。"""

    def __init__(self, text: str, value) -> None:
        super().__init__(text)
        self._value = value

    def __lt__(self, other: QTableWidgetItem) -> bool:
        a, b = self._value, getattr(other, "_value", None)
        if a is None or b is None:
            return a is not None and b is None
        return a < b


def _rate_color(rate: float) -> QColor:
    return _GOOD if rate >= 0.7 else _MID if rate >= 0.4 else _BAD


def _card(value: str, caption: str, color: str = "#e2e8f0") -> QFrame:
    box = QFrame()
    box.setStyleSheet("QFrame{background:#1e293b;border-radius:6px;}")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(0)
    big = QLabel(value)
    big.setStyleSheet(f"font-size:22px;font-weight:bold;color:{color};background:transparent;")
    small = QLabel(caption)
    small.setStyleSheet("font-size:11px;color:#94a3b8;background:transparent;")
    layout.addWidget(big)
    layout.addWidget(small)
    return box


def _fmt_rate(value) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def _fmt_num(value, digits: int = 1, prefix: str = "") -> str:
    return "—" if value is None else f"{prefix}{value:.{digits}f}"


class ReportDialog(QDialog):
    def __init__(self, parent: QWidget | None, load_entries: Callable[[], list[dict]]) -> None:
        super().__init__(parent)
        self.setWindowTitle("評価の集計")
        self.resize(900, 620)
        self.setStyleSheet(_STYLE)
        self._load_entries = load_entries
        self._report: dict = {}

        self._root = QVBoxLayout(self)
        self._cards = QHBoxLayout()
        self._root.addLayout(self._cards)
        self._warn = QLabel()
        self._warn.setWordWrap(True)
        self._warn.setStyleSheet("color:#fbbf24;background:#2a2112;border-radius:4px;padding:6px 8px;")
        self._root.addWidget(self._warn)
        self._tabs = QTabWidget()
        self._root.addWidget(self._tabs, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        refresh = QPushButton("更新")
        refresh.clicked.connect(self.reload)
        save = QPushButton("CSVで保存…")
        save.clicked.connect(self._save_csv)
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        for b in (refresh, save, close):
            buttons.addWidget(b)
        self._root.addLayout(buttons)
        self.reload()

    # ── 読み込み・描画 ──
    def reload(self) -> None:
        self._report = fb.build_report(self._load_entries())
        self._render()

    def _render(self) -> None:
        report = self._report
        k = report["kpis"]
        while self._cards.count():
            item = self._cards.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        rate = k["good_rate"]
        rate_color = "#e2e8f0" if rate is None else ("#4ade80" if rate >= 0.7 else "#fbbf24" if rate >= 0.4 else "#f87171")
        self._cards.addWidget(_card(str(k["total"]), "保存したチュートリアル"))
        coverage = "" if k["coverage"] is None else f"（{k['coverage'] * 100:.0f}%）"
        self._cards.addWidget(_card(f"{k['rated']}件", f"評価済み{coverage}", "#e2e8f0" if (k["coverage"] or 0) >= fb.LOW_COVERAGE else "#fbbf24"))
        self._cards.addWidget(_card(f"👍 {k['good']}　👎 {k['bad']}", "評価の内訳"))
        self._cards.addWidget(_card(_fmt_rate(rate), "好評率", rate_color))
        self._cards.addWidget(_card(_fmt_num(k["total_cost"], 2, "$"), "生成の累計費用"))

        self._warn.setText("\n".join("▲ " + w for w in report["warnings"]))
        self._warn.setVisible(bool(report["warnings"]))

        current = self._tabs.currentIndex()
        self._tabs.clear()
        if not report["sections"] and not report["recent_bad"]:
            empty = QLabel("保存されたチュートリアルがありません。")
            empty.setAlignment(Qt.AlignCenter)
            self._tabs.addTab(empty, "集計")
            return
        for section in report["sections"]:
            self._tabs.addTab(self._table(section["rows"]), f"{section['title']}（{len(section['rows'])}）")
        if report["recent_bad"]:
            self._tabs.addTab(self._recent_bad(report["recent_bad"]), "最近の👎のメモ")
        if 0 <= current < self._tabs.count():
            self._tabs.setCurrentIndex(current)

    def _table(self, rows: list[dict]) -> QTableWidget:
        columns = fb.REPORT_COLUMNS
        table = QTableWidget(len(rows), len(columns))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, (_, label, tip) in enumerate(columns):
            head = QTableWidgetItem(label)
            if tip:
                head.setToolTip(tip)
            table.setHorizontalHeaderItem(c, head)
        table.setSortingEnabled(False)
        for r, row in enumerate(rows):
            cells = (
                (row["key"], row["key"]),
                (str(row["total"]), row["total"]),
                (str(row["rated"]) if row["rated"] else "—", row["rated"]),
                (_fmt_rate(row["good_rate"]), row["good_rate"]),
                (_fmt_num(row["avg_iterations"]), row["avg_iterations"]),
                (_fmt_num(row["avg_cost"], 3, "$"), row["avg_cost"]),
                (_fmt_num(row["avg_cook_errors"]), row["avg_cook_errors"]),
                (_fmt_rate(row["abort_rate"]), row["abort_rate"]),
            )
            for c, (text, value) in enumerate(cells):
                item = _SortItem(text, value)
                if c > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 3 and row["good_rate"] is not None:
                    item.setBackground(QBrush(_rate_color(row["good_rate"])))
                if value is None or (row["unknown"] and c == 0):
                    item.setForeground(QBrush(_MUTED))
                if row["unknown"] and c == 0:
                    font = QFont(item.font())
                    font.setItalic(True)
                    item.setFont(font)
                table.setItem(r, c, item)
        table.setSortingEnabled(True)
        table.sortItems(1, Qt.DescendingOrder)  # 件数の多い順
        return table

    def _recent_bad(self, items: list[dict]) -> QTextEdit:
        view = QTextEdit()
        view.setReadOnly(True)
        parts = []
        for it in reversed(items):  # 新しい順
            tags = " ".join(f"<span style='color:#f87171'>[{_esc(t)}]</span>" for t in it["tags"])
            note = f"<br><span style='color:#cbd5e1'>{_esc(it['note'])}</span>" if it["note"] else ""
            parts.append(f"<p><b>{_esc(it['title'])}</b><br>{tags}{note}</p>")
        view.setHtml("".join(parts))
        return view

    def _save_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "集計をCSVで保存", "評価の集計.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM つき: Excel で文字化けしない
                f.write(fb.report_csv(self._report))
        except OSError as exc:
            self._warn.setText(f"▲ 保存できませんでした: {exc}")
            self._warn.setVisible(True)


def _esc(text: str) -> str:
    import html

    return html.escape(str(text))
