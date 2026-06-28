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

import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

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

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
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

    def query(self, query: str, history: list[dict]) -> dict:
        """
        RAG にクエリを送る。モードに応じてエンドポイントとリクエスト形式を切り替える。
        history は会話コンテキストとして送る（Gemini / Claude のマルチターン対話用）。
        """
        if self.cfg["mode"] == "cloud":
            return _post_json(
                self.cfg["gas_url"],
                {
                    "query":  query,
                    "dbKey":  self.cfg.get("gas_db_key") or "all",
                    "history": history,
                    "apiKey": self.cfg.get("gas_api_key", ""),
                },
            )
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

    def __init__(self, client: RAGClient, query: str, history: list[dict]) -> None:
        super().__init__()
        self._client  = client
        self._query   = query
        self._history = history

    def run(self) -> None:
        try:
            result = self._client.query(self._query, self._history)
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

        self._build_ui()
        self._ensure_bridge()  # Local モードなら起動確認

    # ── UI 構築 ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """ルートレイアウトを構築してタブを追加する。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        tabs = QTabWidget()
        tabs.addTab(self._build_chat_tab(),     "Chat")
        tabs.addTab(self._build_graph_tab(),    "Graph")
        tabs.addTab(self._build_settings_tab(), "Settings")
        root.addWidget(tabs)

        # 下部ステータスバー（接続状態や参照ドキュメントを表示）
        self._status = QLabel("")
        self._status.setStyleSheet("color:#aaa;font-size:11px;")
        root.addWidget(self._status)

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
            self._graph_widget = _RAGGraphWidget(port=self._cfg.get("local_port", 8766))
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
        self._db_key_edit.setPlaceholderText("all / tool_docs / afuri / ...")
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

        self._input.clear()
        self._add_bubble(query, is_user=True)
        self._history.append({"role": "user", "text": query})
        self._set_status("応答中...")
        self._send_btn.setEnabled(False)

        # 直近 12 件の履歴を Worker に渡す（古すぎる会話は LLM に送らない）
        self._worker = QueryWorker(self._client, query, self._history[-12:])
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

    def _on_query_error(self, msg: str) -> None:
        """クエリ失敗時のコールバック。エラーをバブルとステータスに表示する。"""
        self._add_bubble(f"エラー: {msg}", is_user=False)
        self._set_status(msg)
        self._send_btn.setEnabled(True)

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
        try:
            self._cfg["local_port"] = int(self._port_edit.text())
        except ValueError:
            pass  # 不正なポート値は無視して既存値を維持
        _save_config(self._cfg)
        self._client = RAGClient(self._cfg)
        self._set_status("設定を保存しました")

    def _on_check_health(self) -> None:
        """接続確認ボタン。health() の結果をステータスに表示する。"""
        ok = self._client.health()
        self._set_status("接続OK" if ok else "接続失敗 — ブリッジが起動しているか確認してください")

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
