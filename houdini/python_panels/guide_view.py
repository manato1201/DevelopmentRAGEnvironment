"""
guide_view.py — Guide タブ: 保存したチュートリアルを、手順ごとに案内する（2026-11-03）

手順を1つずつ表示し、「見るタブ」「操作するノード」「変えるパラメータ（場所つき）」「使うショートカット」を示す。
「この手順を案内」を押すと、Houdini の画面を動かす: 見るタブを前面に出し、操作するノードを選んで画面に収め、短い表示を出す。
Houdini の画面の部品を消したり、色や設定を書き換えたりはしない（示すだけ）。

案内データは、チュートリアルの保存時に `<名前>_guide.json` として書かれる（tutorial_view.py / guide_mode.py）。
Houdini の外（hou が無い環境）では、手順の表示だけできる。
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Callable

import guide_mode
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

try:
    import hou  # type: ignore[import-not-found]
except ImportError:  # Houdini の外（テスト・単体確認）
    hou = None  # type: ignore[assignment]

_SECTION_TITLES = (("prerequisites", "前提条件"), ("tips", "TIPS"), ("challenge", "自分でやってみよう"))


def render_step_html(guide: dict, index: int) -> str:
    """手順 index（0始まり）の案内を、表示用の HTML にする。"""
    steps = guide.get("steps") or []
    if not steps:
        return ""
    step = steps[max(0, min(index, len(steps) - 1))]
    esc = html.escape
    rows = [f"<p style='font-size:13px'><b>{esc(step.get('instruction') or step.get('hint') or '')}</b></p>"]
    if step.get("hint"):
        rows.append(f"<p>{esc(step['hint'])}</p>")
    node_bits = []
    if step.get("node"):
        label = step.get("node_label") or step.get("node_type") or ""
        node_bits.append(f"操作するノード: <b>{esc(step['node'])}</b>" + (f"（{esc(label)}）" if label else ""))
    node_bits.append(f"見るタブ: <b>{esc(step.get('tab_label') or '')}</b>")
    rows.append("<p>" + "<br>".join(node_bits) + "</p>")
    parms = step.get("parms") or []
    if parms:
        items = []
        for p in parms:
            old = f"{esc(str(p['old']))} → " if p.get("old") not in (None, "") else ""
            where = f"<br><span style='color:#94a3b8'>場所: {esc(p['where'])}</span>" if p.get("where") else ""
            items.append(f"<li><b>{esc(str(p.get('label') or p.get('name') or ''))}</b>: {old}<b>{esc(str(p.get('new') or ''))}</b>{where}</li>")
        rows.append("<p>変えるパラメータ:</p><ul>" + "".join(items) + "</ul>")
    shortcuts = step.get("shortcuts") or []
    if shortcuts:
        items = [f"<li><code>{esc(s['keys'])}</code> … {esc(s['what'])}</li>" for s in shortcuts]
        rows.append("<p>使うショートカット:</p><ul>" + "".join(items) + "</ul>")
    return "".join(rows)


def render_sections_html(guide: dict) -> str:
    """手順書の、前提条件・TIPS・自分でやってみよう（あれば）。"""
    esc = html.escape
    parts = []
    for key, title in _SECTION_TITLES:
        body = str(guide.get(key) or "").strip()
        if body:
            parts.append(f"<p><b>{esc(title)}</b></p><p>{esc(body).replace(chr(10), '<br>')}</p>")
    return "".join(parts)


class GuideWidget(QWidget):
    """Guide タブに埋め込む完成ウィジェット。rag_chatbot.py の _build_guide_tab() から作られる。"""

    def __init__(self, cfg_getter: Callable[[], dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._guide: dict | None = None
        self._index = 0
        self._paths: list[Path] = []
        self._build_ui()

    # ── 画面 ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        bar = QHBoxLayout()
        self._combo = QComboBox()
        self._combo.setToolTip("保存したチュートリアル。保存したときに、案内データも一緒に作られます")
        self._combo.currentIndexChanged.connect(self._on_pick)
        self._refresh_btn = QPushButton("更新")
        self._refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self._combo, stretch=1)
        bar.addWidget(self._refresh_btn)
        root.addLayout(bar)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        nav = QHBoxLayout()
        self._prev_btn = QPushButton("◀ 前へ")
        self._next_btn = QPushButton("次へ ▶")
        self._pos = QLabel("")
        self._pos.setAlignment(Qt.AlignCenter)
        self._prev_btn.clicked.connect(lambda: self._go(-1))
        self._next_btn.clicked.connect(lambda: self._go(1))
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._pos, stretch=1)
        nav.addWidget(self._next_btn)
        root.addLayout(nav)

        split = QSplitter(Qt.Vertical)
        self._step_view = QTextBrowser()
        self._step_view.setOpenLinks(False)
        self._extra_view = QTextBrowser()
        self._extra_view.setOpenLinks(False)
        split.addWidget(self._step_view)
        split.addWidget(self._extra_view)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        root.addWidget(split, stretch=1)

        actions = QHBoxLayout()
        self._apply_btn = QPushButton("この手順を案内")
        self._apply_btn.setToolTip("見るタブを前面に出し、操作するノードを選んで画面に収めます（画面の部品は消しません）")
        self._apply_btn.clicked.connect(self._apply)
        self._auto = QCheckBox("手順を移るたびに自動で案内")
        actions.addWidget(self._apply_btn)
        actions.addWidget(self._auto)
        actions.addStretch()
        root.addLayout(actions)

        self._set_enabled(False)

    def _set_enabled(self, has_guide: bool) -> None:
        self._prev_btn.setEnabled(has_guide)
        self._next_btn.setEnabled(has_guide)
        self._apply_btn.setEnabled(has_guide and hou is not None)
        self._auto.setEnabled(has_guide and hou is not None)

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt
        super().showEvent(event)
        if not self._paths:
            self.refresh()

    # ── 読み込み ─────────────────────────────────────────────────────────────

    def _tutorials_dir(self) -> Path | None:
        bridge_dir = (self._cfg_getter() or {}).get("local_bridge_dir", "")
        return Path(bridge_dir) / "localRAG" / "tutorials" if bridge_dir else None

    def refresh(self) -> None:
        directory = self._tutorials_dir()
        found = guide_mode.list_guides(directory)
        self._combo.blockSignals(True)
        self._combo.clear()
        self._paths = [path for _name, path in found]
        for name, _path in found:
            self._combo.addItem(name)
        self._combo.blockSignals(False)
        if not found:
            self._guide = None
            self._step_view.setHtml("")
            self._extra_view.setHtml("")
            self._pos.setText("")
            self._set_enabled(False)
            self._status.setText(
                "案内できるチュートリアルがありません。Tutorial タブで生成して保存すると、ここに出ます"
                if directory is not None else "設定タブ（Local RAG）で Bridge Directory を設定してください"
            )
            return
        self._load(0)

    def _on_pick(self, index: int) -> None:
        if 0 <= index < len(self._paths):
            self._load(index)

    def _load(self, index: int) -> None:
        guide = guide_mode.load_guide(self._paths[index])
        if guide is None:
            self._guide = None
            self._set_enabled(False)
            self._status.setText("案内データを読み込めませんでした")
            return
        self._guide, self._index = guide, 0
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(index)
        self._combo.blockSignals(False)
        self._extra_view.setHtml(render_sections_html(guide))
        self._set_enabled(True)
        self._status.setText(
            "手順を1つずつ示します。「この手順を案内」で、Houdini の画面を動かします"
            if hou is not None else "Houdini の外なので、手順の表示だけできます"
        )
        self._render()

    # ── 手順の移動と案内 ─────────────────────────────────────────────────────

    def _render(self) -> None:
        if self._guide is None:
            return
        steps = self._guide["steps"]
        self._pos.setText(f"手順 {self._index + 1} / {len(steps)}")
        self._step_view.setHtml(render_step_html(self._guide, self._index))
        self._prev_btn.setEnabled(self._index > 0)
        self._next_btn.setEnabled(self._index < len(steps) - 1)

    def _go(self, delta: int) -> None:
        if self._guide is None:
            return
        self._index = max(0, min(self._index + delta, len(self._guide["steps"]) - 1))
        self._render()
        if self._auto.isChecked():
            self._apply()

    def _apply(self) -> None:
        if self._guide is None or hou is None:
            return
        step = self._guide["steps"][self._index]
        try:
            messages = guide_mode.apply_step(hou, step)
        except Exception as exc:  # noqa: BLE001 -- 案内に失敗しても、パネルは止めない
            messages = [f"案内に失敗しました（{exc}）"]
        self._status.setText(" / ".join(messages))
