"""
graph_view.py — Houdini RAG グラフビュー（PySide6 QGraphicsView）

rag_chatbot.py の Graph タブに埋め込む自己完結ウィジェット。
rag_local_bridge.py の /graph エンドポイントからデータを取得して描画する。

アーキテクチャ:
  GraphFetchWorker  : /graph を非同期で取得する QThread
  NodeItem          : クリッカブルなノード円（QGraphicsEllipseItem）
  EdgeItem          : 類似度スコアに応じた透明度のエッジ（QGraphicsLineItem）
  RAGGraphScene     : ノードとエッジを配置する QGraphicsScene
  RAGGraphView      : ホイールズーム・ドラッグパン対応の QGraphicsView
  RAGGraphWidget    : 上記をまとめた完成ウィジェット（rag_chatbot.py が import する）

Houdini での利用方法:
    # rag_chatbot.py から自動で import される。直接使う場合は:
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
# DB キーごとに色を定義することで、グラフ上でどの DB に属するノードか一目で分かる。
# ここにないキーは _DEFAULT_NODE_COLOR（グレー）にフォールバックする。
_DB_COLORS = {
    "tool_docs":  "#6366f1",  # 紫: ツールドキュメント
    "game_info":  "#10b981",  # 緑: ゲーム情報
    "research":   "#f59e0b",  # 琥珀: 研究・論文
    "team_notes": "#ef4444",  # 赤: チームノート
    "afuri":      "#f97316",  # オレンジ: Afuri 関連
    "braintq":    "#8b5cf6",  # 薄紫: Braintq 関連
    "fourteen":   "#06b6d4",  # シアン: 14 関連
    "local":      "#3b82f6",  # 青: Local DB
    "cloud":      "#22c55e",  # 黄緑: Cloud DB
}
_DEFAULT_NODE_COLOR = "#64748b"  # 未知の DB はグレー

# ノードの x, y（[0, 1] 正規化座標）を掛けてシーン座標に変換するスケール値。
# 大きいほどノード間の距離が広がる。
_SCENE_SIZE = 900.0


# ─── 非同期取得ワーカー ─────────────────────────────────────────────────────────

class GraphFetchWorker(QThread):
    """
    /graph エンドポイントからデータを非同期で取得する QThread ワーカー。
    取得完了時は data_ready シグナルで dict を、失敗時は error シグナルで
    メッセージを UI スレッドに渡す。
    タイムアウト 90 秒（大量ドキュメントのグラフ生成に時間がかかるため長めに設定）。
    """
    data_ready = Signal(dict)  # 成功時: /graph のレスポンス全体
    error      = Signal(str)   # 失敗時: エラーメッセージ

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
    """
    クリッカブルなノード円。

    状態と色:
      通常    : DB カラーパレットで決まる色
      ホバー  : 通常色を 160% 明るくした色
      選択    : 黄色（#fbbf24）

    ラベルはノードの下に小さく表示する。
    setFlag(ItemIsSelectable) で QGraphicsScene の選択機能と連携する。
    """

    RADIUS = 18.0  # ノードの半径（ピクセル。ビュースケールに合わせて拡縮される）

    def __init__(self, node_data: dict) -> None:
        r = self.RADIUS
        super().__init__(-r, -r, r * 2, r * 2)  # 中心を原点に配置
        self.node_data = node_data
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

        # DB キーから色を決定し、ブラシをキャッシュしておく（毎フレームの生成を避けるため）
        color_hex            = _DB_COLORS.get(node_data.get("db", ""), _DEFAULT_NODE_COLOR)
        self._default_brush  = QBrush(QColor(color_hex))
        self._hover_brush    = QBrush(QColor(color_hex).lighter(160))  # ホバー時は明るく
        self._select_brush   = QBrush(QColor("#fbbf24"))               # 選択時は黄色
        self.setBrush(self._default_brush)
        self.setPen(QPen(QColor("#1e293b"), 1.5))  # 暗いボーダーで形を際立たせる
        self.setZValue(1)  # エッジ（ZValue=0）より手前に描画

        # ノード名ラベルを子アイテムとして配置（円の下に表示）
        self._label = QGraphicsSimpleTextItem(node_data.get("label", ""), self)
        font = QFont()
        font.setPointSize(8)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor("#f8fafc")))
        br = self._label.boundingRect()
        self._label.setPos(-br.width() / 2, r + 2)  # 円の下中央に配置

    def hoverEnterEvent(self, event) -> None:
        """ホバー開始時: ブラシを明るい色に変え、最前面に移動する。"""
        self.setBrush(self._hover_brush)
        self.setZValue(3)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        """ホバー終了時: 選択中なら選択色、そうでなければデフォルト色に戻す。"""
        self.setBrush(
            self._select_brush if self.isSelected() else self._default_brush
        )
        self.setZValue(1)
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        """
        QGraphicsScene の選択状態が変化したときに呼ばれる。
        選択: 黄色ブラシ / 非選択: デフォルト色ブラシ に切り替える。
        """
        if change == QGraphicsItem.ItemSelectedChange:
            self.setBrush(self._select_brush if value else self._default_brush)
        return super().itemChange(change, value)


class EdgeItem(QGraphicsLineItem):
    """
    ドキュメント間の類似度エッジ。

    alpha 値を score から計算することで、類似度が高いほど濃く表示する。
      alpha = 50 + score * 160  (score=0 → 50, score=1 → 210)
    pen.setCosmetic(True) でビューのズームに関わらず線幅を一定に保つ。
    """

    def __init__(self, x1: float, y1: float, x2: float, y2: float, score: float) -> None:
        super().__init__(x1, y1, x2, y2)
        alpha = int(50 + score * 160)
        pen = QPen(QColor(150, 150, 150, alpha), 1.2)
        pen.setCosmetic(True)  # ズームしても線幅が変わらない
        self.setPen(pen)
        self.setZValue(0)  # ノードより奥に描画


# ─── シーン ─────────────────────────────────────────────────────────────────────

class RAGGraphScene(QGraphicsScene):
    """
    ノードとエッジを管理する QGraphicsScene。

    build() でノードとエッジを一括配置する。
    ノードが選択されると node_selected シグナルで node_data を発行する。
    """
    node_selected = Signal(dict)  # 選択されたノードの node_data

    def __init__(self) -> None:
        super().__init__()
        self._node_items: dict[str, NodeItem] = {}  # id → NodeItem の参照マップ

    def build(self, data: dict) -> None:
        """
        グラフデータからノードとエッジを構築する。
        ノードの x, y（[0, 1]）を _SCENE_SIZE でスケーリングしてシーン座標に変換する。
        """
        self.clear()
        self._node_items.clear()

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        # ノードを配置
        for nd in nodes:
            x    = nd.get("x", 0.5) * _SCENE_SIZE
            y    = nd.get("y", 0.5) * _SCENE_SIZE
            item = NodeItem(nd)
            item.setPos(x, y)
            self.addItem(item)
            self._node_items[nd["id"]] = item

        # エッジを配置（ノードの中心座標で接続）
        for ed in edges:
            src = self._node_items.get(ed["source"])
            tgt = self._node_items.get(ed["target"])
            if src and tgt:
                sp, tp = src.pos(), tgt.pos()
                edge = EdgeItem(sp.x(), sp.y(), tp.x(), tp.y(), ed.get("score", 0.7))
                self.addItem(edge)

        # 選択変更シグナルを接続（build ごとに再接続）
        self.selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self) -> None:
        """選択アイテムが NodeItem の場合に node_selected シグナルを発行する。"""
        items = self.selectedItems()
        if items and isinstance(items[0], NodeItem):
            self.node_selected.emit(items[0].node_data)


# ─── ビュー ─────────────────────────────────────────────────────────────────────

class RAGGraphView(QGraphicsView):
    """
    ホイールズーム・ドラッグパン対応のグラフビュー。

    setDragMode(ScrollHandDrag) で左ドラッグによるパン操作を有効化する。
    setTransformationAnchor(AnchorUnderMouse) でズーム中心をマウス位置にする。
    wheelEvent をオーバーライドして拡大率 1.15 倍 / 縮小率 1/1.15 倍のズームを実装する。
    """

    def __init__(self, scene: RAGGraphScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)                          # アンチエイリアス
        self.setDragMode(QGraphicsView.ScrollHandDrag)                     # 左ドラッグでパン
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)      # ズームのアンカー
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#1a1a2e")))                 # 暗い背景色
        self.setMinimumSize(300, 300)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """スクロールホイールでズームする。上スクロール: 1.15 倍拡大、下: 縮小。"""
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)


# ─── 完成ウィジェット ───────────────────────────────────────────────────────────

class RAGGraphWidget(QWidget):
    """
    Graph タブに埋め込む完成ウィジェット。
    rag_chatbot.py の _build_graph_tab() から import・インスタンス化される。

    構成:
      ツールバー  : 更新ボタン / 全体フィットボタン / ステータスラベル
      グラフビュー: RAGGraphView（QGraphicsView）
      詳細パネル  : 選択ノードの情報（ラベル / DB / チャンク数）
    """

    def __init__(self, port: int = 8766, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._port   = port
        self._worker: Optional[GraphFetchWorker] = None

        self._scene = RAGGraphScene()
        self._view  = RAGGraphView(self._scene)
        self._scene.node_selected.connect(self._on_node_selected)

        self._build_ui()

    def _build_ui(self) -> None:
        """ツールバー + グラフビュー + 詳細パネルを縦に配置する。"""
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

        # グラフビュー（残りの高さをすべて使う）
        layout.addWidget(self._view, stretch=1)

        # 選択ノード詳細パネル（下部固定）
        self._detail = QLabel("")
        self._detail.setStyleSheet(
            "background:#1e293b;color:#e2e8f0;padding:6px 10px;"
            "border-top:1px solid #334155;font-size:11px;"
        )
        self._detail.setWordWrap(True)
        self._detail.setFixedHeight(50)
        layout.addWidget(self._detail)

    def refresh(self) -> None:
        """
        「更新」ボタンのコールバック。
        Worker が実行中は二重取得を防ぐためスキップする。
        """
        if self._worker and self._worker.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._status.setText("グラフデータ取得中...")
        self._worker = GraphFetchWorker(self._port)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_data_ready(self, data: dict) -> None:
        """取得成功時: シーンを再構築してビューを全体フィットさせる。"""
        self._scene.build(data)
        n = len(data.get("nodes", []))
        e = len(data.get("edges", []))
        self._status.setText(f"{n} ノード / {e} エッジ  ドラッグ: パン  ホイール: ズーム")
        self._refresh_btn.setEnabled(True)
        self._fit_view()

    def _on_error(self, msg: str) -> None:
        """取得失敗時: エラーメッセージをステータスに表示する。"""
        self._status.setText(f"エラー: {msg}")
        self._refresh_btn.setEnabled(True)

    def _on_node_selected(self, node_data: dict) -> None:
        """ノードが選択されたとき、下部詳細パネルに情報を表示する。"""
        label = node_data.get("label", "")
        db    = node_data.get("db", "")
        count = node_data.get("chunk_count", "")
        self._detail.setText(f"{label}  |  DB: {db}  |  チャンク数: {count}")

    def _fit_view(self) -> None:
        """
        全ノードが収まるようにビューをフィットさせる。
        adjusted(-20, -20, 20, 20) でノードの端が切れないよう余白を追加している。
        """
        self._view.fitInView(
            self._scene.itemsBoundingRect().adjusted(-20, -20, 20, 20),
            Qt.KeepAspectRatio,
        )
