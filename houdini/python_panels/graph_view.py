"""
graph_view.py — Houdini RAG グラフビュー（PySide6 QGraphicsView）

rag_chatbot.py の Graph タブに埋め込む自己完結ウィジェット。
rag_local_bridge.py の /graph エンドポイントからデータを取得して描画する。

Houdini での利用方法:
    # rag_chatbot.py から
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from graph_view import RAGGraphWidget
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# ─── DB カラーパレット ──────────────────────────────────────────────────────────
_DB_COLORS = {
    "tool_docs":  "#6366f1",
    "game_info":  "#10b981",
    "research":   "#f59e0b",
    "team_notes": "#ef4444",
    "afuri":      "#f97316",
    "braintq":    "#8b5cf6",
    "fourteen":   "#06b6d4",
    "local":      "#3b82f6",
    "cloud":      "#22c55e",
}
_DEFAULT_NODE_COLOR = "#64748b"
_SCENE_SIZE = 900.0   # nodes の x,y [0,1] をこのサイズにスケーリング


# ─── 非同期取得ワーカー ─────────────────────────────────────────────────────────
class GraphFetchWorker(QThread):
    data_ready = Signal(dict)
    error      = Signal(str)

    def __init__(self, port: int) -> None:
        super().__init__()
        self._port = port

    def run(self) -> None:
        try:
            url = f"http://localhost:{self._port}/graph"
            with urllib.request.urlopen(url, timeout=90) as resp:
                data = json.loads(resp.read())
            self.data_ready.emit(data)
        except urllib.error.URLError as exc:
            self.error.emit(f"ブリッジ未起動: {exc.reason}")
        except Exception as exc:
            self.error.emit(str(exc))


# ─── グラフアイテム ─────────────────────────────────────────────────────────────
class NodeItem(QGraphicsEllipseItem):
    """クリッカブルなノード円"""

    RADIUS = 18.0

    def __init__(self, node_data: dict) -> None:
        r = self.RADIUS
        super().__init__(-r, -r, r * 2, r * 2)
        self.node_data = node_data
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

        color_hex = _DB_COLORS.get(node_data.get("db", ""), _DEFAULT_NODE_COLOR)
        self._default_brush = QBrush(QColor(color_hex))
        self._hover_brush   = QBrush(QColor(color_hex).lighter(160))
        self._select_brush  = QBrush(QColor("#fbbf24"))
        self.setBrush(self._default_brush)
        self.setPen(QPen(QColor("#1e293b"), 1.5))
        self.setZValue(1)

        # ラベル
        self._label = QGraphicsSimpleTextItem(node_data.get("label", ""), self)
        font = QFont()
        font.setPointSize(8)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor("#f8fafc")))
        br = self._label.boundingRect()
        self._label.setPos(-br.width() / 2, r + 2)

    def hoverEnterEvent(self, event) -> None:
        self.setBrush(self._hover_brush)
        self.setZValue(3)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setBrush(
            self._select_brush if self.isSelected() else self._default_brush
        )
        self.setZValue(1)
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedChange:
            self.setBrush(self._select_brush if value else self._default_brush)
        return super().itemChange(change, value)


class EdgeItem(QGraphicsLineItem):
    """類似度スコアに応じた透明度のエッジ"""

    def __init__(self, x1: float, y1: float, x2: float, y2: float, score: float) -> None:
        super().__init__(x1, y1, x2, y2)
        alpha = int(50 + score * 160)
        pen = QPen(QColor(150, 150, 150, alpha), 1.2)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(0)


# ─── シーン ─────────────────────────────────────────────────────────────────────
class RAGGraphScene(QGraphicsScene):
    node_selected = Signal(dict)   # node_data

    def __init__(self) -> None:
        super().__init__()
        self._node_items: dict[str, NodeItem] = {}

    def build(self, data: dict) -> None:
        self.clear()
        self._node_items.clear()

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        # ノード配置
        for nd in nodes:
            x = nd.get("x", 0.5) * _SCENE_SIZE
            y = nd.get("y", 0.5) * _SCENE_SIZE
            item = NodeItem(nd)
            item.setPos(x, y)
            self.addItem(item)
            self._node_items[nd["id"]] = item

        # エッジ配置
        for ed in edges:
            src = self._node_items.get(ed["source"])
            tgt = self._node_items.get(ed["target"])
            if src and tgt:
                sp, tp = src.pos(), tgt.pos()
                edge = EdgeItem(sp.x(), sp.y(), tp.x(), tp.y(), ed.get("score", 0.7))
                self.addItem(edge)

        self.selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self) -> None:
        items = self.selectedItems()
        if items and isinstance(items[0], NodeItem):
            self.node_selected.emit(items[0].node_data)


# ─── ビュー ─────────────────────────────────────────────────────────────────────
class RAGGraphView(QGraphicsView):
    """ホイールズーム + ドラッグパン対応ビュー"""

    def __init__(self, scene: RAGGraphScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#1a1a2e")))
        self.setMinimumSize(300, 300)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)


# ─── 完成ウィジェット ───────────────────────────────────────────────────────────
class RAGGraphWidget(QWidget):
    """Graph タブに埋め込む完成ウィジェット"""

    def __init__(self, port: int = 8766, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._port   = port
        self._worker: Optional[GraphFetchWorker] = None

        self._scene = RAGGraphScene()
        self._view  = RAGGraphView(self._scene)
        self._scene.node_selected.connect(self._on_node_selected)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ツールバー
        toolbar = QHBoxLayout()
        self._refresh_btn = QPushButton("更新")
        self._refresh_btn.setFixedWidth(60)
        self._refresh_btn.clicked.connect(self.refresh)
        self._fit_btn = QPushButton("全体")
        self._fit_btn.setFixedWidth(50)
        self._fit_btn.clicked.connect(self._fit_view)
        self._status = QLabel("「更新」を押してグラフを取得")
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;")
        toolbar.addWidget(self._refresh_btn)
        toolbar.addWidget(self._fit_btn)
        toolbar.addWidget(self._status)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        layout.addWidget(self._view, stretch=1)

        # 選択ノード詳細
        self._detail = QLabel("")
        self._detail.setStyleSheet(
            "background:#1e293b;color:#e2e8f0;padding:6px 10px;"
            "border-top:1px solid #334155;font-size:11px;"
        )
        self._detail.setWordWrap(True)
        self._detail.setFixedHeight(50)
        layout.addWidget(self._detail)

    def refresh(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._status.setText("グラフデータ取得中...")
        self._worker = GraphFetchWorker(self._port)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_data_ready(self, data: dict) -> None:
        self._scene.build(data)
        n = len(data.get("nodes", []))
        e = len(data.get("edges", []))
        self._status.setText(f"{n} ノード / {e} エッジ  ドラッグ: パン  ホイール: ズーム")
        self._refresh_btn.setEnabled(True)
        self._fit_view()

    def _on_error(self, msg: str) -> None:
        self._status.setText(f"エラー: {msg}")
        self._refresh_btn.setEnabled(True)

    def _on_node_selected(self, node_data: dict) -> None:
        label = node_data.get("label", "")
        db    = node_data.get("db", "")
        count = node_data.get("chunk_count", "")
        self._detail.setText(f"{label}  |  DB: {db}  |  チャンク数: {count}")

    def _fit_view(self) -> None:
        self._view.fitInView(
            self._scene.itemsBoundingRect().adjusted(-20, -20, 20, 20),
            Qt.KeepAspectRatio,
        )
