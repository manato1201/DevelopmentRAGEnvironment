"""
rag_chatbot.py — Houdini 21+ Python Panel
RAG チャットボット（Cloud / Local 切り替え対応）

アーキテクチャ:
  このファイルは1つで完結する Houdini Python Panel。
  ・設定は ~/.houdini/rag_chatbot_config.json に JSON で永続化
  ・Cloud モード: GAS WebApp (doPost) に HTTPS で問い合わせ Gemini が回答
  ・Local モード : localhost:8766 の Python ブリッジ経由で Claude / ChromaDB が回答
  ・通信は QThread（QueryWorker）で行い、UI をブロックしない
  ・ローカルブリッジの自動起動も BridgeStartWorker で非同期に行う

Houdini セットアップ:
  1. Windows > Python Panel Editor で新規パネル作成
  2. "Interface" タブにこのファイルの内容を貼り付け
  3. Entry Point を onCreateInterface に設定
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import sys as _sys
import os as _os

# ── パス設定 ─────────────────────────────────────────────────────────────────
# Houdini Python Panel はコードを文字列として実行するため __file__ が未定義になる。
# その場合は hou.homeHoudiniDirectory() でパネルディレクトリを特定してパスに追加する。
try:
    # 通常の Python 実行時（テストやデバッグ）
    _sys.path.insert(0, _os.path.dirname(__file__))
except NameError:
    # Houdini Python Panel 実行時（__file__ が NameError になる）
    try:
        import hou as _hou
        _sys.path.insert(0, _os.path.join(_hou.homeHoudiniDirectory(), "python_panels"))
    except Exception:
        pass

# graph_view.py がインポートできない場合はフォールバック UI を表示する
try:
    from graph_view import RAGGraphWidget as _RAGGraphWidget
    _GRAPH_AVAILABLE = True
except ImportError:
    _GRAPH_AVAILABLE = False

# tutorial_view.py（チュートリアル生成タブ）も同様にフォールバック対応
try:
    from tutorial_view import TutorialGeneratePanel as _TutorialGeneratePanel
    from tutorial_view import TutorialHistoryPanel as _TutorialHistoryPanel
    _TUTORIAL_AVAILABLE = True
except ImportError:
    _TUTORIAL_AVAILABLE = False

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ─── 設定ファイル ─────────────────────────────────────────────────────────────
# ~/.houdini/ に保存することで Houdini のバージョンに依存しない場所に永続化できる
_CONFIG_PATH = Path.home() / ".houdini" / "rag_chatbot_config.json"
_DEFAULT_CONFIG = {
    "mode":             "local",   # "cloud" | "local"
    "gas_url":          "",        # GAS WebApp のデプロイ URL
    "gas_api_key":      "",        # Cloud RAG の API 認証キー（32 文字）
    "gas_db_key":       "all",     # 検索対象 DB（"all" で全 DB）
    "local_port":       8766,      # ローカルブリッジのポート番号
    "local_bridge_dir": "",        # rag_local_bridge.py が含まれるプロジェクトのパス
    "llm_backend":      "claude",  # "claude" | "gemini"（Local モード LLM 切り替え）
    "score_user_id":    "",        # 理解度スコア記録用ユーザーID
    "video_factory_exe_path": "",  # LearningQt video_factory_cloudrag_poc.exe のフルパス
                                    # （チュートリアル保存時に自動で動画生成を起動する）
}


def _load_config() -> dict:
    """
    設定ファイルを読み込む。
    ファイルが存在しない or 壊れている場合はデフォルト設定を返す。
    既存設定とデフォルトをマージするので、新しいキーが追加されても後方互換を保てる。
    """
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            return {**_DEFAULT_CONFIG, **cfg}  # デフォルトに既存設定を上書きマージ
        except Exception:
            pass
    return dict(_DEFAULT_CONFIG)


def _save_config(cfg: dict) -> None:
    """設定を JSON ファイルに書き込む。ディレクトリが存在しない場合は作成する。"""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ─── RAG クライアント ─────────────────────────────────────────────────────────

def _post_json(url: str, body: dict, timeout: int = 60) -> dict:
    """
    JSON を POST して dict を返す低レベルヘルパー。
    urllib のみを使うことで外部ライブラリへの依存をゼロにしている。
    timeout はデフォルト 60 秒（LLM の回答生成に時間がかかるため長めに設定）。
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get_json(url: str, timeout: int = 5) -> dict:
    """
    JSON を GET して dict を返す低レベルヘルパー。
    ヘルスチェック用。timeout は 5 秒（ブリッジ未起動時に UI が固まらないよう短く設定）。
    """
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def _capture_viewport_b64() -> str | None:
    """
    現在の Houdini ビューポートを一時 PNG としてキャプチャし、base64 文字列にして返す
    （IMPROVEMENT_PLAN.md Phase2: VLM入力）。失敗時・screen_capture.py が無い環境
    （Houdini外でのテスト等）では None を返す。

    screen_capture.py の capture 系関数は houdini_tools.py 側では QThread から
    hdefereval 経由でメインスレッドへディスパッチして呼ばれているが、この関数は
    「送信」ボタンのクリックハンドラ（＝既にメインスレッド）から直接呼ばれる想定
    なので、ディスパッチは不要（QueryWorker=バックグラウンドスレッドを起動する前に
    呼ぶこと。バックグラウンドスレッドから呼ぶと hou 呼び出しが安全でなくなる）。
    """
    try:
        import screen_capture
    except ImportError:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "chat_attach.png"
            if not screen_capture.capture_viewport(path):
                return None
            return base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:  # noqa: BLE001 -- best-effort, never raise
        return None


class RAGClient:
    """
    Cloud / Local を透過的に扱う RAG クライアント。

    Cloud モードのリクエスト body:
      {"query": "...", "dbKey": "all", "history": [...], "apiKey": "..."}

    Local モードのリクエスト body:
      {"query": "...", "history": [...], "limit": 5}
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def query(self, query: str, history: list[dict], image_b64: str | None = None) -> dict:
        """
        RAG にクエリを送る。モードに応じてエンドポイントとリクエスト形式を切り替える。
        history は会話コンテキストとして送る（Gemini / Claude のマルチターン対話用）。

        image_b64（IMPROVEMENT_PLAN.md Phase2: VLM入力）は Cloud モードでのみ有効。
        gas_cloud_rag.js の doPost（query アクション）が {"image":{"mimeType","data"}} を
        受け取ると、検索コンテキストに加えて画像自体もGeminiに見せて回答する
        （§8.20参照）。Local モードは未対応のため、渡されても無視する
        （rag_local_bridge.py の /query は image フィールドを見ない）。
        """
        if self.cfg["mode"] == "cloud":
            body = {
                "query":  query,
                "dbKey":  self.cfg.get("gas_db_key") or "all",
                "history": history,
                "apiKey": self.cfg.get("gas_api_key", ""),
            }
            if image_b64:
                body["image"] = {"mimeType": "image/png", "data": image_b64}
            return _post_json(self.cfg["gas_url"], body)
        else:
            port = self.cfg["local_port"]
            return _post_json(
                f"http://localhost:{port}/query",
                {"query": query, "history": history, "limit": 5},
            )

    def health(self) -> bool:
        """
        サーバーの疎通確認。例外が発生した場合は False を返す。
        Cloud: URL に GET して 200 OK か確認。
        Local: /health エンドポイントで {"status":"ok"} を確認。
        """
        try:
            if self.cfg["mode"] == "cloud":
                with urllib.request.urlopen(self.cfg["gas_url"], timeout=5):
                    return True
            else:
                data = _get_json(f"http://localhost:{self.cfg['local_port']}/health")
                return data.get("status") == "ok"
        except Exception:
            return False

    def rate(self, memory_id: str, rating: str) -> bool:
        """
        Cloud モードのみ有効。GAS の RAG_Memory 行に 👍/👎 評価を送る。
        Local モードは評価先がないため常に True を返す（no-op）。
        rating: "up"（👍）| "down"（👎）
        """
        if self.cfg["mode"] != "cloud":
            return True
        url = self.cfg.get("gas_url", "")
        if not url or not memory_id:
            return False
        try:
            result = _post_json(
                url,
                {
                    "action":   "rate",
                    "memoryId": memory_id,
                    "rating":   rating,
                    "apiKey":   self.cfg.get("gas_api_key", ""),
                },
                timeout=15,
            )
            return bool(result.get("ok", False))
        except Exception:
            return False


# ─── バックグラウンドワーカー ─────────────────────────────────────────────────

class QueryWorker(QThread):
    """
    RAG クエリを別スレッドで実行するワーカー。
    PySide6 の UI スレッドで HTTP ブロッキング処理を行うとフリーズするため、
    QThread に切り出して Signal で結果を UI スレッドに返す。
    """
    finished = Signal(dict)  # 成功時: {"answer": str, "sources": list}
    error    = Signal(str)   # 失敗時: エラーメッセージ

    def __init__(
        self, client: RAGClient, query: str, history: list[dict], image_b64: str | None = None
    ) -> None:
        super().__init__()
        self._client    = client
        self._query     = query
        self._history   = history
        self._image_b64 = image_b64

    def run(self) -> None:
        try:
            result = self._client.query(self._query, self._history, image_b64=self._image_b64)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class RateWorker(QThread):
    """
    評価（👍/👎）を別スレッドで送信するワーカー。
    UI スレッドをブロックしないよう QThread に切り出している。
    """
    done = Signal(bool)  # 送信結果（True=成功, False=失敗）

    def __init__(self, client: RAGClient, memory_id: str, rating: str) -> None:
        super().__init__()
        self._client    = client
        self._memory_id = memory_id
        self._rating    = rating

    def run(self) -> None:
        ok = self._client.rate(self._memory_id, self._rating)
        self.done.emit(ok)


class _ConnectionCheckWorker(QThread):
    """接続確認を別スレッドで行うワーカー（HTTP待機でUIをブロックしないため）。"""

    result = Signal(bool)

    def __init__(self, client: RAGClient) -> None:
        super().__init__()
        self._client = client

    def run(self) -> None:
        self.result.emit(self._client.health())


class BridgeStartWorker(QThread):
    """
    Python ブリッジの起動と起動確認を別スレッドで行うワーカー。
    起動確認は 500ms × 16 回（最大 8 秒）のポーリングで行う。
    """
    started_ok = Signal()     # 起動成功
    failed     = Signal(str)  # 失敗理由

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._cfg = cfg

    def run(self) -> None:
        bridge_dir = self._cfg.get("local_bridge_dir", "")
        if not bridge_dir:
            self.failed.emit("local_bridge_dir が設定されていません（設定タブで指定してください）")
            return

        port = self._cfg["local_port"]
        try:
            # バックグラウンドで Python プロセスを起動（stdout/stderr は捨てる）
            subprocess.Popen(
                ["python", "scripts/rag_local_bridge.py", f"--port={port}"],
                cwd=bridge_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.failed.emit("python が PATH に見つかりません")
            return

        # 起動待ち（最大 8 秒 = 500ms × 16 回）
        client = RAGClient(self._cfg)
        import time
        for _ in range(16):
            time.sleep(0.5)
            if client.health():
                self.started_ok.emit()
                return
        self.failed.emit("ブリッジ起動タイムアウト")


# ─── チャットバブル ───────────────────────────────────────────────────────────

class ChatBubble(QLabel):
    """
    1件のメッセージをバブル形式で表示するラベル。
    ユーザー発言は青系背景・右寄せ、RAG 回答はグレー背景・左寄せ で視覚的に区別する。
    テキスト選択を有効にしてコピーできるようにしている。
    """

    def __init__(self, text: str, is_user: bool) -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        bg    = "#2a4a7f" if is_user else "#3a3a3a"
        align = "right"   if is_user else "left"
        self.setStyleSheet(
            f"background:{bg};border-radius:8px;padding:6px 10px;"
            f"color:#eee;text-align:{align};"
        )
        if is_user:
            self.setAlignment(Qt.AlignRight)


# ─── 接続状態ランプ ───────────────────────────────────────────────────────────
# 以前はTutorialタブの中だけに表示していたが、Tutorialタブを開いていないと
# 接続状態を確認できないのは不親切なため、タブバー右端（setCornerWidget）に
# 移動し、どのタブを操作していても常時表示されるようにした。

_CONNECTION_CHECK_INTERVAL_MS = 20_000  # 自動再チェックの間隔（ミリ秒）


class _ConnectionLamp(QWidget):
    """接続状態を丸いランプ（色）+ テキストで示すインジケータ。"""

    _COLORS = {"ok": "#22c55e", "fail": "#ef4444", "checking": "#f59e0b"}
    _LABELS = {"ok": "接続OK", "fail": "接続なし", "checking": "確認中…"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(5)
        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._text = QLabel()
        self._text.setStyleSheet("color:#94a3b8;font-size:11px;")
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        self.set_state("checking")

    def set_state(self, state: str, mode_label: str = "") -> None:
        color = self._COLORS.get(state, "#6b7280")
        label = self._LABELS.get(state, state)
        self._dot.setStyleSheet(f"background:{color};border-radius:5px;")
        self._text.setText(f"{mode_label} {label}".strip())
        self.setToolTip(
            "Cloud: GAS WebApp URL への疎通 / Local: ブリッジの /health を定期確認しています"
        )


# ─── メインパネル ─────────────────────────────────────────────────────────────

class RAGChatbotPanel(QWidget):
    """
    Houdini Python Panel のルートウィジェット。
    Chat / Graph / Settings の3タブ構成。

    状態:
      _cfg           : 設定辞書（常に最新値を保持）
      _client        : RAGClient（設定変更時に再生成）
      _history       : 会話履歴リスト（ユーザー / アシスタント交互に追加）
      _worker        : 実行中の QueryWorker（二重送信防止に使う）
      _bridge_worker : ブリッジ起動中の BridgeStartWorker
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg           = _load_config()
        self._client        = RAGClient(self._cfg)
        self._history: list[dict]               = []
        self._worker: QueryWorker | None        = None
        self._bridge_worker: BridgeStartWorker | None = None
        self._rate_workers: list[RateWorker]    = []  # GC 防止のため参照を保持
        self._conn_worker: _ConnectionCheckWorker | None = None

        self._build_ui()
        self._ensure_bridge()  # Local モードなら起動確認

        # 接続状態ランプ: 初回チェック + 定期的な自動再チェック（タブを切り替えなくても
        # 現在の接続状態が分かるようにするため）。
        self._conn_timer = QTimer(self)
        self._conn_timer.timeout.connect(self._check_connection_async)
        self._conn_timer.start(_CONNECTION_CHECK_INTERVAL_MS)
        self._check_connection_async()

    # ── UI 構築 ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """ルートレイアウトを構築してタブを追加する。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        tabs = QTabWidget()
        # 「はじめに」を先頭タブにする: 初めて開いたユーザーが最初に目にするのが
        # 空のチャット欄だと何をすればいいか分からない、という実機フィードバックへの
        # 対策。各タブの役割・最初にやること・つまずきやすい点をまとめた説明を置く。
        tabs.addTab(self._build_help_tab(),     "はじめに")
        tabs.addTab(self._build_chat_tab(),     "Chat")
        tabs.addTab(self._build_graph_tab(),    "Graph")
        tabs.addTab(self._build_tutorial_tab(), "Tutorial")
        tabs.addTab(self._build_history_tab(),  "History")
        tabs.addTab(self._build_settings_tab(), "Settings")
        self._tabs = tabs  # /tutorial コマンドでのタブ切り替えに使う

        # 接続状態ランプをタブバーの右端に配置する。以前はTutorialタブの中だけに
        # 表示していたが、他のタブを開いているときに確認できないのは不親切なため、
        # setCornerWidgetでタブ切り替えに関わらず常時表示されるようにした。
        self._conn_lamp = _ConnectionLamp()
        tabs.setCornerWidget(self._conn_lamp, Qt.TopRightCorner)

        root.addWidget(tabs)

        # 下部ステータスバー（接続状態や参照ドキュメントを表示）
        self._status = QLabel("")
        self._status.setStyleSheet("color:#aaa;font-size:11px;")
        root.addWidget(self._status)

    def _build_help_tab(self) -> QWidget:
        """
        「はじめに」タブ: 初めてこのパネルを開いた人向けのクイックスタート・
        各タブの役割・よくある詰まりポイントをまとめた静的な説明タブ。
        設定や外部通信を一切行わない読み取り専用タブなので、フォールバック
        UI や例外処理は不要（QTextEdit にHTMLを流すだけ）。
        """
        w = QWidget()
        layout = QVBoxLayout(w)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet(
            "QTextEdit{background:#0f172a;color:#e2e8f0;border:none;padding:8px;"
            "font-family:'Segoe UI','Yu Gothic UI',sans-serif;font-size:13px;}"
        )
        view.document().setDefaultStyleSheet(
            "body{line-height:150%;}"
            "h2{color:#93c5fd;border-bottom:1px solid #334155;padding-bottom:2px;margin-top:14px;}"
            "h3{color:#7dd3fc;margin-top:10px;}"
            "code{font-family:Consolas,'Yu Gothic UI',monospace;"
            "background:#1e293b;color:#fbbf24;padding:1px 4px;border-radius:3px;}"
            "li{margin-bottom:3px;}"
        )
        view.setHtml("""
<h2>このパネルについて</h2>
<p>Houdini から RAG（ナレッジベース検索付きチャット）に質問したり、
トピックを指定して Houdini チュートリアルを自動生成したりするためのパネルです。
初めて使う場合は、下の「はじめの3ステップ」から進めてください。</p>

<h2>はじめの3ステップ</h2>
<ol>
<li><b>接続を確認する</b> — タブバー右端に「Local 接続OK」または「Cloud 接続OK」の
緑ランプが出ているか確認してください。赤色（接続なし）の場合は
<code>Settings</code> タブで設定を確認し、「接続確認」ボタンを押してください。</li>
<li><b>まず Chat タブで質問してみる</b> — 例:「mountainノードの使い方は？」と入力して
<code>Ctrl+Enter</code>（または「送信」ボタン）で聞いてみてください。</li>
<li><b>慣れたら Tutorial タブでチュートリアル生成を試す</b> — トピックを1行で入力
（例:「岩を地形に散布するプロシージャルセットアップ」）して「生成」を押すと、
エージェントが実際に Houdini 上でノードを組み立てながらチュートリアルを作成します。
生成には数十秒〜数分、Claude APIのコストが数セント〜十数セント程度かかります。</li>
</ol>

<h2>各タブの役割</h2>
<ul>
<li><b>Chat</b> — ナレッジベースに質問して回答を得る通常のチャット。<code>/tutorial ＜トピック＞</code>
と入力すると Tutorial タブに切り替わりその場で生成を開始できます。</li>
<li><b>Graph</b> — ナレッジベース内のドキュメント同士の関係を可視化するグラフビュー。
「更新」を押すとノード（ドキュメント）とエッジ（類似度）を取得して描画します。</li>
<li><b>Tutorial</b> — トピックを入力してチュートリアルを自動生成するタブ。生成結果は
プレビュー表示されるだけで、「保存」を押すまでファイルには書き込まれません。</li>
<li><b>History</b> — 保存済みチュートリアルの一覧と、実際に組み立てられたノード
グラフのビューア。「簡易」は直列に繋がったノードを1つにまとめた要約表示、
「詳細」は全ノードをそのまま表示するモードです（マウスホバーで各ボタンの
説明が出ます）。</li>
<li><b>Settings</b> — Cloud RAG（GAS WebApp URL / APIキー）と Local RAG
（ブリッジのポート・プロジェクトパス）の接続設定。</li>
</ul>

<h2>よくある詰まりポイント</h2>
<ul>
<li><b>ランプが赤い（接続なし）</b> — Local モードならブリッジ（<code>rag_local_bridge.py</code>）
が起動しているか確認してください。<code>Settings</code> タブの「ブリッジ再起動」で
自動起動を試みます。Cloud モードなら GAS WebApp URL / API Key の設定を見直してください。</li>
<li><b>チュートリアル生成が途中で打ち切られる</b> — 抽象的すぎるトピック
（例: 具体的なノードで表現しにくい題材）だと、Houdiniのノードタイプを
探し続けて反復回数を使い切ることがあります。より具体的な操作
（例:「〇〇を散布する」「〇〇を変形する」）に言い換えると成功しやすくなります。</li>
<li><b>参考ドキュメントが少ない/関係ない</b> — ナレッジベース側にそのトピックの
ドキュメントがまだ登録されていない可能性があります。生成自体はRAGの
参考ドキュメントが0件でも進行します。</li>
</ul>
""")
        layout.addWidget(view)
        return w

    def _build_chat_tab(self) -> QWidget:
        """
        Chat タブ:
          - モード切り替えコンボ（local / cloud）
          - スクロール可能なメッセージエリア
          - 入力テキストエリア（Ctrl+Enter で送信）
          - 送信 / クリアボタン
        """
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(4)

        # モード切り替え行
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("モード:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["local", "cloud"])
        self._mode_combo.setCurrentText(self._cfg["mode"])
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo)

        # 画面添付チェックボックス（IMPROVEMENT_PLAN.md Phase2: VLM入力）。
        # Cloud RAGのみ対応（gas_cloud_rag.js §8.20）。次の送信1回だけ有効な
        # ワンショット仕様にしている（毎回同じ画面を送り続けてしまう事故を防ぐため）。
        self._attach_viewport_checkbox = QCheckBox("画面を添付")
        self._attach_viewport_checkbox.setToolTip(
            "現在のHoudiniビューポートをキャプチャして次のメッセージに添付します"
            "（Cloud RAGのみ対応。送信すると自動でオフに戻ります）"
        )
        self._attach_viewport_checkbox.setEnabled(self._cfg["mode"] == "cloud")
        mode_row.addWidget(self._attach_viewport_checkbox)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # メッセージエリア（スクロール）
        self._chat_scroll  = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_inner   = QWidget()
        self._chat_layout  = QVBoxLayout(self._chat_inner)
        self._chat_layout.addStretch()  # バブルを下から積み上げるためのスペーサー
        self._chat_scroll.setWidget(self._chat_inner)
        layout.addWidget(self._chat_scroll, stretch=1)

        # テキスト入力
        self._input = QTextEdit()
        self._input.setFixedHeight(70)
        self._input.setPlaceholderText("質問を入力（Ctrl+Enter で送信）")
        layout.addWidget(self._input)

        btn_row = QHBoxLayout()
        self._send_btn = QPushButton("送信")
        self._send_btn.clicked.connect(self._on_send)
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self._on_clear)
        btn_row.addStretch()
        btn_row.addWidget(self._send_btn)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        # Ctrl+Enter の検知は eventFilter で行う
        self._input.installEventFilter(self)
        return w

    def _build_graph_tab(self) -> QWidget:
        """
        Graph タブ:
          graph_view.py が利用可能なら RAGGraphWidget を表示。
          インポートできない場合はエラーメッセージを表示するフォールバック UI を返す。
        """
        if _GRAPH_AVAILABLE:
            self._graph_widget = _RAGGraphWidget(
                port=self._cfg.get("local_port", 8766),
                rag_mode=self._cfg.get("mode", "local"),
                gas_url=self._cfg.get("gas_url", ""),
                gas_api_key=self._cfg.get("gas_api_key", ""),
            )
            return self._graph_widget
        # フォールバック: graph_view.py が見つからない場合
        w = QWidget()
        layout = QVBoxLayout(w)
        label = QLabel(
            "graph_view.py が見つかりません。\n"
            "houdini/python_panels/ に graph_view.py を配置してください。"
        )
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        return w

    def _build_tutorial_tab(self) -> QWidget:
        """
        Tutorial タブ:
          自然言語トピック → エージェントループでノードグラフ組み立て →
          Markdown プレビュー → ユーザー確認後に localRAG/tutorials/ へ保存。
        tutorial_view.py がない場合はフォールバック UI を返す。
        """
        if _TUTORIAL_AVAILABLE:
            # cfg_getter で常に最新の設定（ポート・プロジェクトパス）を参照させる。
            # on_connection_event: 生成失敗直後に接続ランプへ即時再確認を促すコールバック
            # （ランプ自体はこのタブの外＝タブバー右端にあるため、通知だけ受け取る）。
            self._tutorial_panel = _TutorialGeneratePanel(
                lambda: self._cfg, on_connection_event=self._check_connection_async
            )
            return self._tutorial_panel
        self._tutorial_panel = None
        return self._missing_module_widget("tutorial_view.py")

    def _build_history_tab(self) -> QWidget:
        """History タブ: 保存済みチュートリアルの一覧とノードグラフ表示。"""
        if _TUTORIAL_AVAILABLE:
            self._history_panel = _TutorialHistoryPanel(lambda: self._cfg)
            return self._history_panel
        return self._missing_module_widget("tutorial_view.py")

    @staticmethod
    def _missing_module_widget(module_name: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        label = QLabel(
            f"{module_name} が見つかりません。\n"
            f"houdini/python_panels/ に {module_name} を配置してください。"
        )
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        return w

    def _build_settings_tab(self) -> QWidget:
        """
        Settings タブ:
          Cloud RAG: GAS URL / API Key（パスワード非表示）/ DB Key
          Local RAG : Bridge Port / Bridge Directory
          操作ボタン: 設定保存 / 接続確認 / ブリッジ再起動
        """
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # Cloud RAG 設定
        layout.addWidget(QLabel("Cloud RAG"))

        layout.addWidget(QLabel("GAS WebApp URL:"))
        self._gas_url_edit = QLineEdit(self._cfg.get("gas_url", ""))
        self._gas_url_edit.setPlaceholderText("https://script.google.com/macros/s/...")
        layout.addWidget(self._gas_url_edit)

        layout.addWidget(QLabel("API Key:"))
        self._api_key_edit = QLineEdit(self._cfg.get("gas_api_key", ""))
        self._api_key_edit.setPlaceholderText("管理画面で発行した32文字のキー")
        self._api_key_edit.setEchoMode(QLineEdit.Password)  # 入力文字を ● で隠す
        layout.addWidget(self._api_key_edit)

        layout.addWidget(QLabel("DB Key:"))
        self._db_key_edit = QLineEdit(self._cfg.get("gas_db_key", "all"))
        self._db_key_edit.setPlaceholderText("all / tool_docs / houdini21 / afuri / ...")
        layout.addWidget(self._db_key_edit)

        # Local RAG 設定
        layout.addWidget(QLabel("Local RAG"))

        layout.addWidget(QLabel("Bridge Port:"))
        self._port_edit = QLineEdit(str(self._cfg.get("local_port", 8766)))
        layout.addWidget(self._port_edit)

        layout.addWidget(QLabel("Bridge Directory:"))
        self._bridge_dir_edit = QLineEdit(self._cfg.get("local_bridge_dir", ""))
        self._bridge_dir_edit.setPlaceholderText("DevelopmentRAGEnvironment のパス")
        layout.addWidget(self._bridge_dir_edit)

        # LLM バックエンド
        layout.addWidget(QLabel("LLM バックエンド:"))
        self._backend_combo = QComboBox()
        self._backend_combo.addItems(["claude", "gemini"])
        self._backend_combo.setCurrentText(self._cfg.get("llm_backend", "claude"))
        layout.addWidget(self._backend_combo)

        # スコアユーザーID
        layout.addWidget(QLabel("スコアユーザーID:"))
        self._score_uid_edit = QLineEdit(self._cfg.get("score_user_id", ""))
        self._score_uid_edit.setPlaceholderText("例: my_user")
        layout.addWidget(self._score_uid_edit)

        # 動画生成（LearningQt video factory）
        layout.addWidget(QLabel("Video Factory exe パス:"))
        self._video_factory_exe_edit = QLineEdit(self._cfg.get("video_factory_exe_path", ""))
        self._video_factory_exe_edit.setPlaceholderText(
            "LearningQt\\build\\engine\\video_factory_cloudrag_poc.exe（未設定なら自動起動しない）"
        )
        layout.addWidget(self._video_factory_exe_edit)

        # 注意: チュートリアル生成のClaudeトークン上限は、ここではなくGAS管理画面
        # （🔑APIキー管理タブ）側でAPIキーごとに設定する。クライアント側で
        # 上限を自己申告・改ざんできない構成にするため、意図的にここには置いていない。

        # 操作ボタン
        save_btn = QPushButton("設定を保存")
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)

        check_btn = QPushButton("接続確認")
        check_btn.clicked.connect(self._on_check_health)
        layout.addWidget(check_btn)

        restart_btn = QPushButton("ブリッジ再起動")
        restart_btn.clicked.connect(self._on_restart_bridge)
        layout.addWidget(restart_btn)

        # 注意書き: ANTHROPIC_API_KEY は .env ではなく OS 環境変数で渡す
        note = QLabel(
            "ANTHROPIC_API_KEY は Houdini 起動前に\n"
            "OS 環境変数に設定してください。"
        )
        note.setStyleSheet("color:#f90;")
        layout.addWidget(note)
        layout.addStretch()
        return w

    # ── イベント ───────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """Ctrl+Enter で _on_send() を呼ぶ。それ以外は通常のイベント処理に委譲する。"""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            ke = QKeyEvent(event)
            if ke.key() == Qt.Key_Return and ke.modifiers() == Qt.ControlModifier:
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def _on_mode_changed(self, mode: str) -> None:
        """モード切り替え時に設定を保存してクライアントを再生成する。"""
        self._cfg["mode"] = mode
        _save_config(self._cfg)
        self._client = RAGClient(self._cfg)
        if mode == "local":
            self._ensure_bridge()
        # 画面添付（VLM入力）はCloud RAG専用（§8.20）。Localに切り替えたら
        # チェックが入っていても解除し、無効な状態のまま残らないようにする。
        self._attach_viewport_checkbox.setEnabled(mode == "cloud")
        if mode != "cloud":
            self._attach_viewport_checkbox.setChecked(False)
        self._check_connection_async()

    # ── 接続状態ランプ ───────────────────────────────────────────────────────────

    def _check_connection_async(self) -> None:
        """
        接続確認を別スレッドで開始する（前回のチェックが終わっていなければスキップして
        二重起動を防ぐ）。QTimerの定期実行・モード切替/設定保存直後・チュートリアル生成
        失敗直後に呼ばれる。タブバー右端のランプはどのタブを開いていても表示される。
        """
        if self._conn_worker is not None and self._conn_worker.isRunning():
            return
        mode_label = "Cloud" if self._cfg.get("mode") == "cloud" else "Local"
        self._conn_lamp.set_state("checking", mode_label)
        self._conn_worker = _ConnectionCheckWorker(self._client)
        self._conn_worker.result.connect(
            lambda ok, ml=mode_label: self._conn_lamp.set_state("ok" if ok else "fail", ml)
        )
        self._conn_worker.start()

    def _on_send(self) -> None:
        """
        送信ボタンまたは Ctrl+Enter で呼ばれる。
        すでに Worker が動いている場合は二重送信を防ぐためスキップする。
        会話履歴は直近 12 件に絞って送る（トークン節約）。
        """
        if self._worker and self._worker.isRunning():
            return
        query = self._input.toPlainText().strip()
        if not query:
            return

        # /tutorial コマンド: Tutorial タブに切り替えて生成を開始する
        if query.startswith("/tutorial"):
            topic = query[len("/tutorial"):].strip()
            self._input.clear()
            if not _TUTORIAL_AVAILABLE or self._tutorial_panel is None:
                self._add_bubble("tutorial_view.py が見つからないため /tutorial は使えません", is_user=False)
                return
            if not topic:
                self._add_bubble("使い方: /tutorial <トピック>（例: /tutorial 岩の散布）", is_user=False)
                return
            self._tabs.setCurrentWidget(self._tutorial_panel)
            self._tutorial_panel.start_with_topic(topic)
            return

        # 画面添付（VLM入力、§8.20）: チェックされていれば送信前にビューポートを
        # キャプチャしてbase64化する。hou呼び出しを含むため、バックグラウンドの
        # QueryWorkerを起動する前に、まだメインスレッドであるここで同期的に行う。
        # ワンショット仕様（送信のたびに毎回オフへ戻す）。
        image_b64 = None
        if self._attach_viewport_checkbox.isChecked():
            self._attach_viewport_checkbox.setChecked(False)
            image_b64 = _capture_viewport_b64()
            if image_b64 is None:
                self._add_bubble("画面のキャプチャに失敗しました（添付なしで続行します）", is_user=False)

        self._input.clear()
        self._add_bubble(query, is_user=True)
        self._history.append({"role": "user", "text": query})
        self._set_status("応答中...")
        self._send_btn.setEnabled(False)

        # 直近 12 件の履歴を Worker に渡す（古すぎる会話は LLM に送らない）
        self._worker = QueryWorker(self._client, query, self._history[-12:], image_b64=image_b64)
        self._worker.finished.connect(self._on_query_done)
        self._worker.error.connect(self._on_query_error)
        self._worker.start()

    def _on_query_done(self, result: dict) -> None:
        """クエリ成功時のコールバック。回答バブルを追加し参照ドキュメントをステータスに表示する。"""
        answer    = result.get("answer", "(空の回答)")
        sources   = result.get("sources", [])
        memory_id = result.get("memoryId", "")
        self._add_rag_bubble(answer, memory_id)
        self._history.append({"role": "assistant", "text": answer})
        if sources:
            titles = ", ".join(s.get("title", "") for s in sources)
            self._set_status(f"参照: {titles}")
        else:
            self._set_status("")
        self._send_btn.setEnabled(True)
        self._scroll_to_bottom()
        # 理解度スコアを自動更新
        uid = self._cfg.get("score_user_id", "")
        if self._cfg["mode"] == "local" and uid:
            threading.Thread(target=self._post_score, args=(uid, True), daemon=True).start()

    def _on_query_error(self, msg: str) -> None:
        """クエリ失敗時のコールバック。エラーをバブルとステータスに表示する。"""
        self._add_bubble(f"エラー: {msg}", is_user=False)
        self._set_status(msg)
        self._send_btn.setEnabled(True)
        # 理解度スコアをエラーとして更新
        uid = self._cfg.get("score_user_id", "")
        if self._cfg["mode"] == "local" and uid:
            threading.Thread(target=self._post_score, args=(uid, False), daemon=True).start()

    def _on_clear(self) -> None:
        """会話履歴とバブルをすべて削除してチャットをリセットする。"""
        self._history.clear()
        # stretch（最後の要素）以外のすべてのバブルを削除する
        for i in reversed(range(self._chat_layout.count() - 1)):
            item = self._chat_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._set_status("")

    def _on_save_settings(self) -> None:
        """設定タブの入力値を _cfg に反映してファイルに保存し、クライアントを再生成する。"""
        self._cfg["gas_url"]          = self._gas_url_edit.text().strip()
        self._cfg["gas_api_key"]      = self._api_key_edit.text().strip()
        self._cfg["gas_db_key"]       = self._db_key_edit.text().strip() or "all"
        self._cfg["local_bridge_dir"] = self._bridge_dir_edit.text().strip()
        self._cfg["llm_backend"]      = self._backend_combo.currentText()
        self._cfg["score_user_id"]    = self._score_uid_edit.text().strip()
        self._cfg["video_factory_exe_path"] = self._video_factory_exe_edit.text().strip()
        try:
            self._cfg["local_port"] = int(self._port_edit.text())
        except ValueError:
            pass  # 不正なポート値は無視して既存値を維持
        _save_config(self._cfg)
        self._client = RAGClient(self._cfg)
        # バックエンド変更をブリッジに通知
        if self._cfg["mode"] == "local":
            threading.Thread(target=self._push_backend, daemon=True).start()
        self._set_status("設定を保存しました")
        self._check_connection_async()

    def _on_check_health(self) -> None:
        """接続確認ボタン。health() の結果をステータスとタブバーのランプ両方に反映する。"""
        ok = self._client.health()
        self._set_status("接続OK" if ok else "接続失敗 — ブリッジが起動しているか確認してください")
        mode_label = "Cloud" if self._cfg.get("mode") == "cloud" else "Local"
        self._conn_lamp.set_state("ok" if ok else "fail", mode_label)

    def _on_restart_bridge(self) -> None:
        """ブリッジ再起動ボタン。force=True で既存プロセスを無視して再起動する。"""
        self._ensure_bridge(force=True)

    def _on_bridge_started(self) -> None:
        """BridgeStartWorker からの起動成功シグナルを受けるスロット。"""
        self._set_status("ブリッジ接続済み")

    def _on_bridge_failed(self, msg: str) -> None:
        """BridgeStartWorker からの失敗シグナルを受けるスロット。"""
        self._set_status(f"ブリッジ起動失敗: {msg}")

    # ── ブリッジ自動起動 ───────────────────────────────────────────────────────

    def _post_score(self, user_id: str, success: bool) -> None:
        """理解度スコアを /api/score に POST して結果をステータスバーに反映する。"""
        try:
            result = _post_json(
                f"http://localhost:{self._cfg['local_port']}/api/score",
                {"user_id": user_id, "topic": "general", "success": success},
                timeout=5,
            )
            score = result.get("new_score", 0.5)
            self._set_status(f"理解度スコア: {score:.2f}")
        except Exception:
            pass  # スコア更新失敗は無視（主処理に影響させない）

    def _push_backend(self) -> None:
        """選択した LLM バックエンドをブリッジに通知する。"""
        try:
            _post_json(
                f"http://localhost:{self._cfg['local_port']}/api/llm-backend",
                {"backend": self._cfg["llm_backend"]},
                timeout=5,
            )
        except Exception:
            pass

    def _ensure_bridge(self, force: bool = False) -> None:
        """
        Local モード時にブリッジが未起動なら BridgeStartWorker で自動起動する。
        force=True の場合はヘルスチェックをスキップして強制起動する（再起動ボタン用）。
        """
        if self._cfg["mode"] != "local":
            return
        if not force and self._client.health():
            self._set_status("ブリッジ接続済み")
            return
        self._set_status("ブリッジを起動中...")
        self._bridge_worker = BridgeStartWorker(self._cfg)
        self._bridge_worker.started_ok.connect(self._on_bridge_started)
        self._bridge_worker.failed.connect(self._on_bridge_failed)
        self._bridge_worker.start()

    # ── UI ヘルパー ────────────────────────────────────────────────────────────

    def _add_bubble(self, text: str, is_user: bool) -> None:
        """
        チャットエリアにメッセージバブルを追加する。
        ユーザー発言は右寄せ（stretch → bubble）、RAG 回答は左寄せ（bubble → stretch）。
        stretch の手前に挿入することで常にバブルが下から積み上がるようにする。
        """
        bubble = ChatBubble(text, is_user)
        row = QHBoxLayout()
        if is_user:
            row.addStretch()
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch()
        insert_at = max(0, self._chat_layout.count() - 1)
        self._chat_layout.insertLayout(insert_at, row)

    def _add_rag_bubble(self, text: str, memory_id: str) -> None:
        """
        RAG 回答専用バブル。テキストの下に 👍/👎 ボタンを追加する。
        memory_id が空の場合（Local モードなど）はボタンを表示しない。
        """
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 4)
        v.setSpacing(2)

        # テキストバブル行
        bubble_row = QHBoxLayout()
        bubble_row.addWidget(ChatBubble(text, is_user=False))
        bubble_row.addStretch()
        v.addLayout(bubble_row)

        # 評価ボタン行（Cloud モードで memoryId がある場合のみ）
        if memory_id:
            btn_row = QHBoxLayout()
            thumb_up   = QPushButton("👍")
            thumb_down = QPushButton("👎")
            for btn in (thumb_up, thumb_down):
                btn.setFixedSize(32, 24)
                btn.setFlat(True)
                btn.setStyleSheet("QPushButton{border-radius:4px;font-size:14px;}")

            def _on_up(checked=False, mid=memory_id, u=thumb_up, d=thumb_down):
                u.setStyleSheet("QPushButton{border-radius:4px;font-size:14px;background:#2a7a2a;}")
                d.setStyleSheet("QPushButton{border-radius:4px;font-size:14px;}")
                u.setEnabled(False)
                d.setEnabled(False)
                self._on_rate(mid, "up")

            def _on_down(checked=False, mid=memory_id, u=thumb_up, d=thumb_down):
                d.setStyleSheet("QPushButton{border-radius:4px;font-size:14px;background:#7a2a2a;}")
                u.setStyleSheet("QPushButton{border-radius:4px;font-size:14px;}")
                u.setEnabled(False)
                d.setEnabled(False)
                self._on_rate(mid, "down")

            thumb_up.clicked.connect(_on_up)
            thumb_down.clicked.connect(_on_down)
            btn_row.addWidget(thumb_up)
            btn_row.addWidget(thumb_down)
            btn_row.addStretch()
            v.addLayout(btn_row)

        insert_at = max(0, self._chat_layout.count() - 1)
        self._chat_layout.insertWidget(insert_at, container)

    def _on_rate(self, memory_id: str, rating: str) -> None:
        """評価を RateWorker でバックグラウンド送信する。"""
        worker = RateWorker(self._client, memory_id, rating)
        worker.done.connect(
            lambda ok: self._set_status("評価を送信しました ✓" if ok else "評価の送信に失敗しました")
        )
        self._rate_workers.append(worker)  # GC 防止
        worker.start()

    def _scroll_to_bottom(self) -> None:
        """スクロールエリアを最下部にスクロールして最新メッセージを表示する。"""
        sb = self._chat_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_status(self, text: str) -> None:
        """下部ステータスラベルのテキストを更新する。"""
        self._status.setText(text)


# ─── Houdini エントリポイント ─────────────────────────────────────────────────

def onCreateInterface():
    """
    Houdini Python Panel のエントリポイント。
    Python Panel Editor の "Entry Point" フィールドにこの関数名を設定する。
    パネルが開かれるたびに呼ばれ、返したウィジェットがパネルに表示される。
    """
    panel = RAGChatbotPanel()
    return panel
