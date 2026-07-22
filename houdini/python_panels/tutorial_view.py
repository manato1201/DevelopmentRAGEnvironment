"""
tutorial_view.py — チュートリアル生成タブ / 過去のチュートリアルタブ（PySide6）

rag_chatbot.py に埋め込まれる2つのウィジェットを提供する:

  TutorialGeneratePanel : トピック入力 → エージェント進行状況のリアルタイム表示
                          → Markdown プレビュー → ユーザーが「保存」を押して初めて
                          localRAG/tutorials/ に書き込む（設計 §2.7 プレビュー要件）
  TutorialHistoryPanel  : 保存済みチュートリアルの一覧 → 選択すると Markdown と
                          ノードグラフ（NodeGraphAsset JSON）を QGraphicsView で表示

ノードグラフ描画は graph_view.py の実装パターン（QGraphicsScene/View、
ホイールズーム・ドラッグパン）を流用している。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ─── 生成ワーカー ────────────────────────────────────────────────────────────────

class TutorialWorker(QThread):
    """
    TutorialAgent.generate() を別スレッドで実行するワーカー。
    hou 操作自体は houdini_tools 側で hdefereval によりメインスレッドへ
    ディスパッチされるため、このスレッドは API 通信の待機が主となる。
    """
    progress = Signal(str)     # 進行状況テキスト（ツール呼び出しごと）
    done     = Signal(object)  # TutorialResult
    failed   = Signal(str)     # エラーメッセージ

    def __init__(self, agent, topic: str) -> None:
        super().__init__()
        self._agent = agent
        self._topic = topic

    def run(self) -> None:
        try:
            result = self._agent.generate(self._topic)
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


# ─── 生成タブ ────────────────────────────────────────────────────────────────────

class TutorialGeneratePanel(QWidget):
    """
    チュートリアル生成タブ。

    cfg_getter は現在の設定 dict を返す callable（rag_chatbot.py から渡される）。
    設定は生成開始時に評価するので、Settings タブでの変更が即反映される。
    """

    def __init__(self, cfg_getter: Callable[[], dict], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._worker: TutorialWorker | None = None
        self._agent = None            # 生成後もサンドボックス削除用に保持
        self._result = None           # TutorialResult（保存待ち）
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # トピック入力行
        input_row = QHBoxLayout()
        self._topic_edit = QLineEdit()
        self._topic_edit.setPlaceholderText("例: 岩を地形に散布するプロシージャルセットアップ")
        self._topic_edit.returnPressed.connect(self._on_generate)
        self._generate_btn = QPushButton("生成")
        self._generate_btn.clicked.connect(self._on_generate)
        input_row.addWidget(QLabel("トピック:"))
        input_row.addWidget(self._topic_edit, stretch=1)
        input_row.addWidget(self._generate_btn)
        layout.addLayout(input_row)

        # 進行ログとプレビューを縦分割
        splitter = QSplitter(Qt.Vertical)

        self._progress_log = QTextEdit()
        self._progress_log.setReadOnly(True)
        self._progress_log.setPlaceholderText("進行状況（どのツールを呼んでいるか）がここに表示されます")
        self._progress_log.setStyleSheet("font-family:Consolas,monospace;font-size:11px;")
        splitter.addWidget(self._progress_log)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("生成が完了すると Markdown プレビューがここに表示されます")
        splitter.addWidget(self._preview)
        splitter.setSizes([160, 400])
        layout.addWidget(splitter, stretch=1)

        # 保存確認行（プレビュー後にのみ有効化）
        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("保存（localRAG/tutorials/）")
        self._save_btn.clicked.connect(self._on_save)
        self._discard_btn = QPushButton("破棄")
        self._discard_btn.clicked.connect(self._on_discard)
        self._delete_sandbox_btn = QPushButton("サンドボックス削除")
        self._delete_sandbox_btn.clicked.connect(self._on_delete_sandbox)
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn):
            btn.setEnabled(False)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#aaa;font-size:11px;")
        layout.addWidget(self._status)

    # ── 外部 API（/tutorial コマンド用） ────────────────────────────────────────

    def start_with_topic(self, topic: str) -> None:
        """Chat タブの /tutorial コマンドから呼ばれる。"""
        self._topic_edit.setText(topic)
        self._on_generate()

    # ── 生成 ────────────────────────────────────────────────────────────────────

    def _on_generate(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        topic = self._topic_edit.text().strip()
        if not topic:
            self._status.setText("トピックを入力してください")
            return

        cfg = self._cfg_getter()
        try:
            from tutorial_agent import TutorialAgent
        except ImportError as exc:
            self._status.setText(f"tutorial_agent の読み込みに失敗: {exc}")
            return

        self._progress_log.clear()
        self._preview.clear()
        self._result = None
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn):
            btn.setEnabled(False)
        self._generate_btn.setEnabled(False)
        self._status.setText("生成中...")

        self._agent = TutorialAgent(
            bridge_port=cfg.get("local_port", 8766),
            project_dir=cfg.get("local_bridge_dir", ""),
            rag_mode=cfg.get("mode", "local"),
            gas_url=cfg.get("gas_url", ""),
            gas_api_key=cfg.get("gas_api_key", ""),
        )
        self._worker = TutorialWorker(self._agent, topic)
        # progress_cb は QThread 内から呼ばれるため Signal 経由で UI スレッドに渡す
        self._agent._progress = self._worker.progress.emit
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, text: str) -> None:
        self._progress_log.append(text)
        sb = self._progress_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_done(self, result) -> None:
        self._result = result
        self._preview.setMarkdown(result.markdown)
        self._generate_btn.setEnabled(True)
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn):
            btn.setEnabled(True)
        state = "完了" if result.completed else f"途中経過（{result.abort_reason}）"
        self._status.setText(
            f"{state} — ${result.cost_usd:.3f} / {result.iterations} ステップ。"
            "内容を確認して「保存」を押してください（保存するまでファイルは書き込まれません）"
        )

    def _on_failed(self, msg: str) -> None:
        self._progress_log.append(f"エラー: {msg}")
        self._status.setText(f"生成失敗: {msg}")
        self._generate_btn.setEnabled(True)
        # サンドボックスが作られていた場合は削除だけ許可する
        if self._agent and self._agent.executor is not None:
            self._delete_sandbox_btn.setEnabled(True)

    # ── 保存 / 破棄 ─────────────────────────────────────────────────────────────

    def _tutorials_dir(self) -> Path | None:
        bridge_dir = self._cfg_getter().get("local_bridge_dir", "")
        if not bridge_dir:
            QMessageBox.warning(
                self, "保存先未設定",
                "Settings タブで Bridge Directory（DevelopmentRAGEnvironment のパス）を設定してください。",
            )
            return None
        return Path(bridge_dir) / "localRAG" / "tutorials"

    def _on_save(self) -> None:
        if self._result is None:
            return
        tutorials_dir = self._tutorials_dir()
        if tutorials_dir is None:
            return
        tutorials_dir.mkdir(parents=True, exist_ok=True)

        # 同名ファイルがある場合は連番サフィックスで衝突回避（既存生成物を上書きしない）
        basename = self._result.file_basename()
        candidate = basename
        counter = 2
        while (tutorials_dir / f"{candidate}.md").exists():
            candidate = f"{basename}-{counter}"
            counter += 1

        md_path = tutorials_dir / f"{candidate}.md"
        json_path = tutorials_dir / f"{candidate}.json"
        try:
            md_path.write_text(self._result.markdown, encoding="utf-8")
            json_path.write_text(
                json.dumps(self._result.graph, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self._status.setText(f"保存失敗: {exc}")
            return

        self._save_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._status.setText(
            f"保存しました: {md_path.name} / {json_path.name}"
            "（watchdog が自動インデックス化します）"
        )

        # 動画生成をバックグラウンドで自動起動（ベストエフォート）。
        # video_factory_bridge / screen_capture は LearningQt 側の video
        # factory との連携用に追加したモジュールで、失敗してもチュートリアル
        # 保存そのものは既に成功済みなので、状態表示に追記するだけに留める。
        try:
            from video_factory_bridge import launch_video_generation

            video_status = launch_video_generation(
                md_path=md_path,
                json_path=json_path,
                sandbox_path=self._result.sandbox_path,
                exe_path=self._cfg_getter().get("video_factory_exe_path", ""),
            )
            self._status.setText(f"{self._status.text()} / {video_status}")
        except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
            self._status.setText(f"{self._status.text()} / 動画生成の起動に失敗: {exc}")

    def _on_discard(self) -> None:
        self._result = None
        self._preview.clear()
        self._save_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._status.setText("破棄しました（サンドボックスは残っています。不要なら「サンドボックス削除」）")

    def _on_delete_sandbox(self) -> None:
        if self._agent is None:
            return
        answer = QMessageBox.question(
            self, "サンドボックス削除",
            f"{getattr(self._agent.executor, 'sandbox_path', '')} を削除しますか？",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._agent.destroy_sandbox()
            self._delete_sandbox_btn.setEnabled(False)
            self._status.setText("サンドボックスを削除しました")
        except Exception as exc:
            self._status.setText(f"サンドボックス削除失敗: {exc}")


# ─── ノードグラフビューア（NodeGraphAsset JSON） ─────────────────────────────────

_NODE_W, _NODE_H = 130.0, 34.0
_POS_SCALE = 150.0  # Houdini ネットワーク座標 → シーン座標のスケール

# ノードカテゴリの目安色（kind のプレフィックスで判定できないため単色ベース＋subnet 区別）
_NODE_COLOR = "#3b6ea5"
_SUBNET_COLOR = "#7c5cbf"


class _GraphNodeItem(QGraphicsRectItem):
    """NodeGraphAsset の1ノードを矩形＋ラベルで表示する。"""

    def __init__(self, node: dict) -> None:
        super().__init__(-_NODE_W / 2, -_NODE_H / 2, _NODE_W, _NODE_H)
        self.node_data = node
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        color = _SUBNET_COLOR if node.get("kind") in ("subnet", "geo") else _NODE_COLOR
        self.setBrush(QBrush(QColor(color)))
        self.setPen(QPen(QColor("#1e293b"), 1.5))
        self.setZValue(1)

        label = QGraphicsSimpleTextItem(node.get("label", ""), self)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        label.setFont(font)
        label.setBrush(QBrush(QColor("#f8fafc")))
        br = label.boundingRect()
        label.setPos(-br.width() / 2, -br.height() - 2 + _NODE_H / 2 - 24)

        kind_label = QGraphicsSimpleTextItem(node.get("kind", ""), self)
        kind_font = QFont()
        kind_font.setPointSize(7)
        kind_label.setFont(kind_font)
        kind_label.setBrush(QBrush(QColor("#cbd5e1")))
        kbr = kind_label.boundingRect()
        kind_label.setPos(-kbr.width() / 2, 0)


class _NodeGraphScene(QGraphicsScene):
    """NodeGraphAsset JSON からノードとエッジを構築するシーン。"""

    node_selected = Signal(dict)

    def build(self, graph: dict) -> None:
        self.clear()
        items: dict[str, _GraphNodeItem] = {}

        for node in graph.get("nodes", []):
            item = _GraphNodeItem(node)
            x, y = node.get("position", [0, 0])
            item.setPos(x * _POS_SCALE, y * _POS_SCALE)
            self.addItem(item)
            items[node["id"]] = item

        pen = QPen(QColor(160, 160, 160, 180), 1.4)
        pen.setCosmetic(True)
        for edge in graph.get("edges", []):
            src = items.get(edge.get("source"))
            dst = items.get(edge.get("target"))
            if src and dst:
                line = self.addLine(
                    src.pos().x(), src.pos().y() + _NODE_H / 2,
                    dst.pos().x(), dst.pos().y() - _NODE_H / 2,
                    pen,
                )
                line.setZValue(0)

        self.selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self) -> None:
        items = self.selectedItems()
        if items and isinstance(items[0], _GraphNodeItem):
            self.node_selected.emit(items[0].node_data)


class _NodeGraphView(QGraphicsView):
    """ホイールズーム・ドラッグパン対応（graph_view.py と同じ操作感）。"""

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#1a1a2e")))
        self.setMinimumSize(200, 200)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)


# ─── 過去のチュートリアルタブ ────────────────────────────────────────────────────

class TutorialHistoryPanel(QWidget):
    """
    localRAG/tutorials/ の保存済みチュートリアル一覧。
    選択すると Markdown プレビューとノードグラフ（同名 .json）を表示する。
    """

    def __init__(self, cfg_getter: Callable[[], dict], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("更新")
        refresh_btn.setFixedWidth(60)
        refresh_btn.clicked.connect(self.refresh)
        self._status = QLabel("")
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;")
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(self._status)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)
        splitter.addWidget(self._list)

        right = QSplitter(Qt.Vertical)
        self._graph_scene = _NodeGraphScene()
        self._graph_view = _NodeGraphView(self._graph_scene)
        self._graph_scene.node_selected.connect(self._on_node_selected)
        right.addWidget(self._graph_view)

        self._md_view = QTextEdit()
        self._md_view.setReadOnly(True)
        right.addWidget(self._md_view)
        right.setSizes([250, 350])

        splitter.addWidget(right)
        splitter.setSizes([200, 500])
        layout.addWidget(splitter, stretch=1)

        self._detail = QLabel("")
        self._detail.setStyleSheet(
            "background:#1e293b;color:#e2e8f0;padding:4px 8px;font-size:11px;"
        )
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

    def _tutorials_dir(self) -> Path | None:
        bridge_dir = self._cfg_getter().get("local_bridge_dir", "")
        if not bridge_dir:
            return None
        return Path(bridge_dir) / "localRAG" / "tutorials"

    def refresh(self) -> None:
        self._list.clear()
        tutorials_dir = self._tutorials_dir()
        if tutorials_dir is None:
            self._status.setText("Settings タブで Bridge Directory を設定してください")
            return
        if not tutorials_dir.exists():
            self._status.setText("まだ保存されたチュートリアルがありません")
            return
        files = sorted(tutorials_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files:
            item = QListWidgetItem(path.stem)
            item.setData(Qt.UserRole, str(path))
            self._list.addItem(item)
        self._status.setText(f"{len(files)} 件")

    def _on_select(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        md_path = Path(current.data(Qt.UserRole))
        try:
            self._md_view.setMarkdown(md_path.read_text(encoding="utf-8"))
        except OSError as exc:
            self._md_view.setPlainText(f"読み込みエラー: {exc}")

        json_path = md_path.with_suffix(".json")
        if json_path.exists():
            try:
                graph = json.loads(json_path.read_text(encoding="utf-8"))
                self._graph_scene.build(graph)
                self._graph_view.fitInView(
                    self._graph_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30),
                    Qt.KeepAspectRatio,
                )
                self._detail.setText(
                    f"{len(graph.get('nodes', []))} ノード / {len(graph.get('edges', []))} エッジ"
                    f"  |  sandbox: {graph.get('sandbox', '')}"
                )
            except (OSError, json.JSONDecodeError) as exc:
                self._detail.setText(f"ノードグラフ読み込みエラー: {exc}")
        else:
            self._graph_scene.clear()
            self._detail.setText("ノードグラフ JSON がありません")

    def _on_node_selected(self, node: dict) -> None:
        params = ", ".join(f"{k}={v}" for k, v in node.get("params", {}).items()) or "（デフォルト）"
        self._detail.setText(f"{node.get('id')}  |  {node.get('kind')}  |  {params}")
