"""
graph_view.py — Houdini RAG グラフビュー（PySide6 QGraphicsView、3D表示）

rag_chatbot.py の Graph タブに埋め込む自己完結ウィジェット。
Local モードでは rag_local_bridge.py の /graph エンドポイントから、
Cloud モードでは gas_cloud_rag.js（doPost の action:'graph'）からデータを取得して描画する。

2026-08-28: 2D表示を3D表示化した。Cloudflare Web UI側のグラフ（chatUi.ts、Three.js）が
既に3D実装済みで、Houdini側だけ2Dのままだと「webとアプリで表示が違う」状態になって
いたため。新しいQtモジュール（Qt3D等、Houdiniのバンドル内に存在するか未確認）や
埋め込みブラウザには依存せず、既存のQGraphicsView/QGraphicsSceneの上で手製の
透視投影（perspective projection）を行うことで3D風の回転操作を実現している
（動画再生問題の原因が埋め込みブラウザのコーデック非対応だったばかりなので、
ブラウザ依存を増やす方向は避けた）。左ドラッグでカメラを回転、中ドラッグでパン、
ホイールでズームする。

アーキテクチャ:
  GraphFetchWorker  : /graph を非同期で取得する QThread
  Camera3D          : 方位角・仰角を持ち、3D座標を2Dスクリーン座標へ透視投影する
  NodeItem          : クリッカブルなノード円（QGraphicsEllipseItem）。奥行きに応じて
                       拡縮・不透明度が変わる
  EdgeItem          : 類似度スコア×奥行きフォグに応じた透明度のエッジ（QGraphicsLineItem）
  RAGGraphScene     : 3Dレイアウトを計算し、カメラ回転のたびに再投影する QGraphicsScene
  RAGGraphView      : ホイールズーム・左ドラッグ回転・中ドラッグパン対応の QGraphicsView
  RAGGraphWidget    : 上記をまとめた完成ウィジェット（rag_chatbot.py が import する）

Houdini での利用方法:
    # rag_chatbot.py から自動で import される。直接使う場合は:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from graph_view import RAGGraphWidget

注意: このセッションの開発環境にはPySide6がインストールされておらず（Houdini本体でしか
動かせないモジュールのため）、python_compileによる構文チェックのみで実機テストは
できていない。Houdini上での動作確認が必要。
"""

from __future__ import annotations

import json
import math
import random
import urllib.error
import urllib.request
from typing import Optional

from PySide6.QtCore import QThread, Qt, Signal
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

# ノードの x, y, z（[0, 1] 正規化座標）を掛けてワールド座標に変換するスケール値。
# 大きいほどノード間の距離が広がる。
# 2026-08-27修正: 従来は固定値だったため、ノード数が増えるほど単位面積あたりの
# ノード密度が上がり続け、実機で218ノード/358エッジのグラフがラベルもろとも
# 団子状に潰れて読めなくなる不具合があった（「相変わらずひどい」として報告）。
# ノード数のルートに比例させ、密度がおおよそ一定になるようにする
# （50ノード時に900、218ノード時は約1880になる）。3D化後もこの式を流用しているが、
# 本来は体積(³√n)に対して比例させる方が理論的には正しく、実機の見え方次第では
# 調整が必要かもしれない。
_BASE_SCENE_SIZE = 900.0
_BASE_NODE_COUNT = 50.0


def _scene_size_for(node_count: int) -> float:
    return max(_BASE_SCENE_SIZE, _BASE_SCENE_SIZE * math.sqrt(max(node_count, 1) / _BASE_NODE_COUNT))


# ラベルが長いと、ノード間隔がどれだけ広くても隣接ラベル同士が重なって読めなくなる
# （実機の「CEDEC2025_[クリエイターズ]AIが牽引する...」のような長いタイトルで確認）。
# 常時表示ではなくホバー時のみ表示に切り替え、それでも長すぎる場合はこの文字数で
# 省略する（フルタイトルは選択時の詳細パネルに出るため、常時表示分は短くて構わない）。
_LABEL_MAX_CHARS = 14


def _spring_layout_3d(
    node_ids: list[str],
    edges: list[dict],
    iterations: int = 80,
) -> dict[str, tuple[float, float, float]]:
    """
    フォースディレクテッド簡易レイアウトの3D版。x/y版（_spring_layout、2026-08-27まで
    存在。8-08修正の孤立ノード四隅集中バグ対策・ノード数正規化を含む）をz軸へ
    そのまま拡張したもの。

    Local RAGの/graphが返すx/y、Cloud RAGが返さないx/yのどちらも「2Dレイアウト」で
    z成分を持たないため、3D表示ではバックエンドの座標を使わず常にここで計算する
    （2D座標だけ流用してzだけこちらで足すと、レイアウトの意図が噛み合わず歪んだ
    見た目になるため）。
    """
    if not node_ids:
        return {}
    if len(node_ids) == 1:
        return {node_ids[0]: (0.5, 0.5, 0.5)}

    n = len(node_ids)
    rnd = random.Random(42)
    pos: dict[str, list[float]] = {
        nid: [rnd.uniform(0.1, 0.9), rnd.uniform(0.1, 0.9), rnd.uniform(0.1, 0.9)]
        for nid in node_ids
    }
    edge_scores: dict[tuple[str, str], float] = {}
    for e in edges:
        a, b = e.get("source"), e.get("target")
        if a in pos and b in pos:
            edge_scores[(a, b)] = e.get("score", 0.7)

    center_pull = 0.01  # 求心力の強さ（弱め: 引力が働くノード同士の凝集は妨げない）
    for _ in range(iterations):
        forces: dict[str, list[float]] = {nid: [0.0, 0.0, 0.0] for nid in node_ids}
        for ai in range(len(node_ids)):
            a = node_ids[ai]
            for bi in range(ai + 1, len(node_ids)):
                b = node_ids[bi]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                dz = pos[a][2] - pos[b][2]
                d = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.001
                f_rep = 0.004 / (d * d) / n  # ノード数で正規化
                forces[a][0] += dx / d * f_rep
                forces[a][1] += dy / d * f_rep
                forces[a][2] += dz / d * f_rep
                forces[b][0] -= dx / d * f_rep
                forces[b][1] -= dy / d * f_rep
                forces[b][2] -= dz / d * f_rep
                score = edge_scores.get((a, b), edge_scores.get((b, a), 0.0))
                if score > 0:
                    f_att = score * 0.025
                    forces[a][0] -= dx * f_att
                    forces[a][1] -= dy * f_att
                    forces[a][2] -= dz * f_att
                    forces[b][0] += dx * f_att
                    forces[b][1] += dy * f_att
                    forces[b][2] += dz * f_att
        for nid in node_ids:
            forces[nid][0] -= (pos[nid][0] - 0.5) * center_pull  # 求心力
            forces[nid][1] -= (pos[nid][1] - 0.5) * center_pull
            forces[nid][2] -= (pos[nid][2] - 0.5) * center_pull
            pos[nid][0] = max(0.04, min(0.96, pos[nid][0] + forces[nid][0]))
            pos[nid][1] = max(0.04, min(0.96, pos[nid][1] + forces[nid][1]))
            pos[nid][2] = max(0.04, min(0.96, pos[nid][2] + forces[nid][2]))

    return {nid: (pos[nid][0], pos[nid][1], pos[nid][2]) for nid in node_ids}


# ─── カメラ / 透視投影 ──────────────────────────────────────────────────────────

class Camera3D:
    """
    方位角(azimuth)・仰角(elevation)を持つ簡易カメラ。ワールド座標系の3D点を
    Y軸→X軸の順に回転させ、透視除算（perspective divide）で2Dスクリーン座標へ
    投影する。焦点距離はscene_sizeに比例させ、グラフの規模に関わらず同じような
    見え方になるようにしている。
    """

    ELEVATION_LIMIT = math.radians(75)  # これを超えるとほぼ真上/真下からの見下ろしで
                                          # 奥行きが分かりづらくなり、90度超で反転もするため

    def __init__(self) -> None:
        # 初期値はあえて真正面(0,0)にせず、最初から奥行きが見える角度にしておく
        # （回転してもらわないと3D化した意味が伝わらないため）。
        self.azimuth = math.radians(28.0)
        self.elevation = math.radians(16.0)

    def rotate(self, d_azimuth: float, d_elevation: float) -> None:
        self.azimuth += d_azimuth
        self.elevation = max(
            -self.ELEVATION_LIMIT, min(self.ELEVATION_LIMIT, self.elevation + d_elevation)
        )

    def project(self, x: float, y: float, z: float, scene_size: float) -> tuple[float, float, float]:
        """
        中心済みワールド座標(x, y, z)を2Dスクリーン座標(sx, sy)へ投影し、あわせて
        奥行き係数k（1.0=基準距離、1より大きい=手前で拡大、小さい=奥で縮小）を返す。
        """
        ca, sa = math.cos(self.azimuth), math.sin(self.azimuth)
        x1 = x * ca + z * sa
        z1 = -x * sa + z * ca
        ce, se = math.cos(self.elevation), math.sin(self.elevation)
        y2 = y * ce - z1 * se
        z2 = y * se + z1 * ce

        focal = scene_size * 1.6  # カメラの引き位置。scene_sizeに比例させグラフ規模に依存しないようにする
        denom = max(z2 + focal, focal * 0.15)  # カメラに極端に近い点で分母が0/負にならないようクランプ
        k = focal / denom
        return x1 * k, y2 * k, k


# ─── 非同期取得ワーカー ─────────────────────────────────────────────────────────

class GraphFetchWorker(QThread):
    """
    グラフデータを非同期で取得する QThread ワーカー。
    取得完了時は data_ready シグナルで dict を、失敗時は error シグナルで
    メッセージを UI スレッドに渡す。
    タイムアウト 90 秒（大量ドキュメントのグラフ生成に時間がかかるため長めに設定）。

    rag_mode に応じて取得先を切り替える:
      "local" : http://localhost:{port}/graph へ GET（rag_local_bridge.py の /graph）
      "cloud" : gas_url へ {"action":"graph","apiKey":gas_api_key} を POST
                （gas_cloud_rag.js の doPost 内 action:'graph' ブランチ。戻り値の形は
                /graph エンドポイントと完全に同一なので呼び出し側の扱いは変わらない）
    """
    data_ready = Signal(dict)  # 成功時: レスポンス全体（nodes/edges/status）
    error      = Signal(str)   # 失敗時: エラーメッセージ

    def __init__(
        self,
        port: int,
        rag_mode: str = "local",
        gas_url: str = "",
        gas_api_key: str = "",
    ) -> None:
        super().__init__()
        self._port        = port
        self._rag_mode    = rag_mode
        self._gas_url     = gas_url
        self._gas_api_key = gas_api_key

    def run(self) -> None:
        try:
            if self._rag_mode == "cloud":
                data = self._fetch_cloud()
            else:
                data = self._fetch_local()
            self.data_ready.emit(data)
        except urllib.error.URLError as exc:
            self.error.emit(f"ブリッジ未起動: {exc.reason}")
        except Exception as exc:
            self.error.emit(str(exc))

    def _fetch_local(self) -> dict:
        """ローカルブリッジの /graph エンドポイントに GET する。"""
        url = f"http://localhost:{self._port}/graph"
        with urllib.request.urlopen(url, timeout=90) as resp:
            return json.loads(resp.read())

    def _fetch_cloud(self) -> dict:
        """
        GAS WebApp に {"action":"graph","apiKey":...} を POST する。
        tutorial_agent.py の _call_api / _rag_search_cloud と同じ
        urllib.request.Request(..., method='POST') パターン。
        """
        if not self._gas_url:
            raise RuntimeError("Cloud RAGモードですが gas_url が未設定です")
        body = json.dumps(
            {"action": "graph", "apiKey": self._gas_api_key},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            self._gas_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read())


# ─── グラフアイテム ─────────────────────────────────────────────────────────────

class NodeItem(QGraphicsEllipseItem):
    """
    クリッカブルなノード円。3D座標(pos3d)を保持し、RAGGraphScene.reproject()から
    毎回 apply_projection() で画面上の位置・拡縮・不透明度を更新される
    （手前のノードほど大きく・不透明に、奥のノードほど小さく・薄く見える）。

    状態と色:
      通常    : DB カラーパレットで決まる色
      ホバー  : 通常色を 160% 明るくした色
      選択    : 黄色（#fbbf24）

    ラベルはノードの下に小さく表示する。
    setFlag(ItemIsSelectable) で QGraphicsScene の選択機能と連携する。
    """

    RADIUS = 18.0  # ノードの半径（ピクセル。奥行きスケールと合わせてさらに拡縮される）

    # 奥行きに応じた拡大率・不透明度のクランプ範囲。0や極端な値にはしない
    # （遠いノードが消えて選択できなくなったり、近いノードが暴走的に巨大化しないため）。
    _SCALE_RANGE = (0.5, 1.7)
    _OPACITY_RANGE = (0.4, 1.0)

    # ホバー/選択中のノードは常に最前面に来てほしいので、奥行きベースのzValue
    # （後述のapply_projectionで most 2000程度まで）よりも十分大きいオフセットを足す。
    _HOVER_Z_BOOST = 100000.0
    _SELECT_Z_BOOST = 50000.0

    def __init__(self, node_data: dict) -> None:
        r = self.RADIUS
        super().__init__(-r, -r, r * 2, r * 2)  # 中心を原点に配置
        self.node_data = node_data
        self.pos3d: tuple[float, float, float] = (0.0, 0.0, 0.0)  # ワールド座標。scene.build()が設定
        self._base_z = 0.0  # 奥行き由来のzValue基準値。apply_projection()が更新する
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

        # DB キーから色を決定し、ブラシをキャッシュしておく（毎フレームの生成を避けるため）
        color_hex            = _DB_COLORS.get(node_data.get("db", ""), _DEFAULT_NODE_COLOR)
        self._default_brush  = QBrush(QColor(color_hex))
        self._hover_brush    = QBrush(QColor(color_hex).lighter(160))  # ホバー時は明るく
        self._select_brush   = QBrush(QColor("#fbbf24"))               # 選択時は黄色
        self.setBrush(self._default_brush)
        self.setPen(QPen(QColor("#1e293b"), 1.5))  # 暗いボーダーで形を際立たせる

        # ノード名ラベルを子アイテムとして配置（円の下に表示）。長いタイトルは省略し、
        # ノード数が多いグラフで隣接ラベル同士が重なって読めなくなるのを避けるため、
        # 通常時は非表示にしてホバー/選択時のみ表示する（2026-08-27）。
        full_label = node_data.get("label", "")
        short_label = full_label if len(full_label) <= _LABEL_MAX_CHARS else full_label[:_LABEL_MAX_CHARS] + "…"
        self._label = QGraphicsSimpleTextItem(short_label, self)
        font = QFont()
        font.setPointSize(8)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor("#f8fafc")))
        br = self._label.boundingRect()
        self._label.setPos(-br.width() / 2, r + 2)  # 円の下中央に配置
        self._label.setVisible(False)
        self._label.setZValue(4)  # 子アイテムは常に親より手前に描画されるため、相対値のままでよい

    def apply_projection(self, screen_x: float, screen_y: float, depth_k: float) -> None:
        """
        RAGGraphScene.reproject()から呼ばれる。透視投影後のスクリーン座標と
        奥行き係数(depth_k、1.0=基準距離)を反映する。
        """
        clamped_scale = max(self._SCALE_RANGE[0], min(self._SCALE_RANGE[1], depth_k))
        clamped_opacity = max(self._OPACITY_RANGE[0], min(self._OPACITY_RANGE[1], depth_k))
        self.setPos(screen_x, screen_y)
        self.setScale(clamped_scale)
        self.setOpacity(clamped_opacity)
        self._base_z = depth_k * 1000.0
        # ホバー中/選択中はブースト込みのzValueを維持したいので、通常状態のときだけ
        # 素の奥行きzValueを反映する（ホバー/選択解除時にhoverLeaveEvent/itemChangeが
        # 呼ばれて正しい値へ戻る）。
        if not self.isUnderMouse() and not self.isSelected():
            self.setZValue(self._base_z)

    def hoverEnterEvent(self, event) -> None:
        """ホバー開始時: ブラシを明るい色に変え、最前面に移動してラベルを表示する。"""
        self.setBrush(self._hover_brush)
        self.setZValue(self._base_z + self._HOVER_Z_BOOST)
        self._label.setVisible(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        """ホバー終了時: 選択中なら選択色、そうでなければデフォルト色に戻す。
        ラベルは選択中のみ表示を維持する。zValueも奥行き基準値(+選択ブースト)へ戻す。"""
        selected = self.isSelected()
        self.setBrush(self._select_brush if selected else self._default_brush)
        self.setZValue(self._base_z + (self._SELECT_Z_BOOST if selected else 0.0))
        self._label.setVisible(selected)
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        """
        QGraphicsScene の選択状態が変化したときに呼ばれる。
        選択: 黄色ブラシ＋ラベル表示＋zValueブースト / 非選択: デフォルト色ブラシ＋
        ラベル非表示＋奥行き基準zValueに切り替える。
        """
        if change == QGraphicsItem.ItemSelectedChange:
            self.setBrush(self._select_brush if value else self._default_brush)
            self._label.setVisible(bool(value))
            self.setZValue(self._base_z + (self._SELECT_Z_BOOST if value else 0.0))
        return super().itemChange(change, value)


class EdgeItem(QGraphicsLineItem):
    """
    ドキュメント間の類似度エッジ。

    元のスコアと、両端ノードの平均奥行き係数（フォグ効果。奥にあるほど薄く見せる）
    の両方から透明度を計算する。update_geometry()はRAGGraphScene.reproject()から
    カメラ回転のたびに呼ばれ、ノードの新しい画面座標に合わせて線を引き直す。
    pen.setCosmetic(True) でビューのズームに関わらず線幅を一定に保つ。
    """

    def __init__(self, score: float) -> None:
        super().__init__()
        self._score = score
        pen = QPen(QColor(150, 150, 150, 128), 1.2)
        pen.setCosmetic(True)  # ズームしても線幅が変わらない
        self.setPen(pen)

    def update_geometry(self, x1: float, y1: float, x2: float, y2: float, depth_fog: float) -> None:
        """depth_fog は両端ノードの平均奥行き係数(1.0=基準距離)。奥にあるほど薄くする。"""
        self.setLine(x1, y1, x2, y2)
        fog = max(0.35, min(1.0, depth_fog))
        alpha = int((50 + self._score * 160) * fog)
        pen = self.pen()
        color = pen.color()
        color.setAlpha(max(10, min(255, alpha)))
        pen.setColor(color)
        self.setPen(pen)
        # 常にノード（zValue >= 0）より奥に描画されるよう、奥行きで軽くソートしつつ
        # 確実に負の範囲へ収める。
        self.setZValue(depth_fog * 10.0 - 1000.0)


# ─── シーン ─────────────────────────────────────────────────────────────────────

class RAGGraphScene(QGraphicsScene):
    """
    3Dレイアウトを計算し、カメラの回転に応じてノード/エッジを再投影する QGraphicsScene。

    build() で3Dレイアウトを計算してノードとエッジを配置し、reproject() で
    現在のカメラ角度に基づく2D画面座標へ変換する。rotate_camera() はビューの
    ドラッグ操作から呼ばれ、カメラ角度を更新してreproject()する。
    ノードが選択されると node_selected シグナルで node_data を発行する。
    """
    node_selected = Signal(dict)  # 選択されたノードの node_data

    def __init__(self) -> None:
        super().__init__()
        self._node_items: dict[str, NodeItem] = {}  # id → NodeItem の参照マップ
        self._edges: list[tuple[EdgeItem, str, str]] = []  # (edge, source_id, target_id)
        self._camera = Camera3D()
        self._scene_size = _BASE_SCENE_SIZE

    def build(self, data: dict) -> None:
        """
        グラフデータから3Dレイアウトを計算し、ノードとエッジを構築する。
        バックエンドが返すx/y（2D専用）は使わず、常にこちらで3Dレイアウトを
        再計算する（_spring_layout_3dのdocstring参照）。
        """
        self.clear()
        self._node_items.clear()
        self._edges.clear()

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        self._scene_size = _scene_size_for(len(nodes))

        node_ids = [nd["id"] for nd in nodes]
        layout_3d = _spring_layout_3d(node_ids, edges)

        # ノードを配置（ワールド座標は中心を原点とする [-scene_size/2, scene_size/2]^3 へ変換）
        for nd in nodes:
            wx, wy, wz = layout_3d.get(nd["id"], (0.5, 0.5, 0.5))
            item = NodeItem(nd)
            item.pos3d = (
                (wx - 0.5) * self._scene_size,
                (wy - 0.5) * self._scene_size,
                (wz - 0.5) * self._scene_size,
            )
            self.addItem(item)
            self._node_items[nd["id"]] = item

        # エッジを配置（初期ジオメトリはreproject()で確定するので、ここではitem追加のみ）
        for ed in edges:
            src_id, tgt_id = ed.get("source"), ed.get("target")
            if src_id in self._node_items and tgt_id in self._node_items:
                edge = EdgeItem(ed.get("score", 0.7))
                self.addItem(edge)
                self._edges.append((edge, src_id, tgt_id))

        self.selectionChanged.connect(self._on_selection_changed)
        self.reproject()

    def reproject(self) -> None:
        """現在のカメラ角度で全ノード/エッジの画面座標・拡縮・不透明度を計算し直す。"""
        depth_by_id: dict[str, float] = {}
        for node_id, item in self._node_items.items():
            wx, wy, wz = item.pos3d
            sx, sy, k = self._camera.project(wx, wy, wz, self._scene_size)
            item.apply_projection(sx, sy, k)
            depth_by_id[node_id] = k

        for edge, src_id, tgt_id in self._edges:
            src_item = self._node_items.get(src_id)
            tgt_item = self._node_items.get(tgt_id)
            if src_item is None or tgt_item is None:
                continue
            sp, tp = src_item.pos(), tgt_item.pos()
            fog = (depth_by_id.get(src_id, 1.0) + depth_by_id.get(tgt_id, 1.0)) / 2.0
            edge.update_geometry(sp.x(), sp.y(), tp.x(), tp.y(), fog)

    def rotate_camera(self, d_azimuth: float, d_elevation: float) -> None:
        """ビューのドラッグ操作から呼ばれる。カメラ角度を更新して再投影する。"""
        self._camera.rotate(d_azimuth, d_elevation)
        self.reproject()

    def _on_selection_changed(self) -> None:
        """選択アイテムが NodeItem の場合に node_selected シグナルを発行する。"""
        items = self.selectedItems()
        if items and isinstance(items[0], NodeItem):
            self.node_selected.emit(items[0].node_data)


# ─── ビュー ─────────────────────────────────────────────────────────────────────

class RAGGraphView(QGraphicsView):
    """
    ホイールズーム・左ドラッグ回転・中ドラッグパン対応のグラフビュー。

    2D時代はScrollHandDrag（左ドラッグ＝パン）だったが、3D化にあたり左ドラッグは
    カメラ回転に割り当てた。パンは中ドラッグに変更している。
    setTransformationAnchor(AnchorUnderMouse) でズーム中心をマウス位置にする。
    wheelEvent をオーバーライドして拡大率 1.15 倍 / 縮小率 1/1.15 倍のズームを実装する。
    """

    # ドラッグ量→回転角(ラジアン)の変換係数。大きいほど少ないドラッグで大きく回る。
    _ROTATE_SENSITIVITY = 0.008

    def __init__(self, scene: RAGGraphScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)                          # アンチエイリアス
        self.setDragMode(QGraphicsView.NoDrag)                             # 左ドラッグは回転に使うため無効化
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)      # ズームのアンカー
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#1a1a2e")))                 # 暗い背景色
        self.setMinimumSize(300, 300)

        self._rotating = False
        self._panning = False
        self._last_pos = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        """スクロールホイールでズームする。上スクロール: 1.15 倍拡大、下: 縮小。"""
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._rotating = True
            self._last_pos = event.position()
            self.setCursor(Qt.SizeAllCursor)
            event.accept()
            return
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._last_pos = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._rotating and self._last_pos is not None:
            pos = event.position()
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            self._last_pos = pos
            scene = self.scene()
            if isinstance(scene, RAGGraphScene):
                scene.rotate_camera(dx * self._ROTATE_SENSITIVITY, dy * self._ROTATE_SENSITIVITY)
            event.accept()
            return
        if self._panning and self._last_pos is not None:
            pos = event.position()
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            self._last_pos = pos
            hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
            hbar.setValue(hbar.value() - int(dx))
            vbar.setValue(vbar.value() - int(dy))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._rotating:
            self._rotating = False
            self._last_pos = None
            self.unsetCursor()
            event.accept()
            return
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self._last_pos = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ─── 完成ウィジェット ───────────────────────────────────────────────────────────

class RAGGraphWidget(QWidget):
    """
    Graph タブに埋め込む完成ウィジェット。
    rag_chatbot.py の _build_graph_tab() から import・インスタンス化される。

    構成:
      ツールバー  : 更新ボタン / 全体フィットボタン / ステータスラベル
      グラフビュー: RAGGraphView（QGraphicsView、3D投影）
      詳細パネル  : 選択ノードの情報（ラベル / DB / チャンク数）
    """

    def __init__(
        self,
        port: int = 8766,
        parent: Optional[QWidget] = None,
        rag_mode: str = "local",
        gas_url: str = "",
        gas_api_key: str = "",
    ) -> None:
        super().__init__(parent)
        self._port         = port
        self._rag_mode     = rag_mode
        self._gas_url      = gas_url
        self._gas_api_key  = gas_api_key
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
        self._worker = GraphFetchWorker(
            self._port,
            rag_mode=self._rag_mode,
            gas_url=self._gas_url,
            gas_api_key=self._gas_api_key,
        )
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_data_ready(self, data: dict) -> None:
        """取得成功時: シーンを再構築してビューを全体フィットさせる。"""
        self._scene.build(data)
        n = len(data.get("nodes", []))
        e = len(data.get("edges", []))
        self._status.setText(f"{n} ノード / {e} エッジ  左ドラッグ: 回転  中ドラッグ: パン  ホイール: ズーム")
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
