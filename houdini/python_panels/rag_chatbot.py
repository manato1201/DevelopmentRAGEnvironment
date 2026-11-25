"""
rag_chatbot.py — Houdini 21+ Python Panel
RAG チャットボット（Cloudflare / Local 切り替え対応）

アーキテクチャ:
  このファイルは1つで完結する Houdini Python Panel。
  ・設定は ~/.houdini/rag_chatbot_config.json に JSON で永続化
  ・Cloudflare モード: Cloudflare Worker（/query）に HTTPS で問い合わせ Gemini が回答
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
import html
import json
import subprocess
import tempfile
import threading
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

# reference_view.py（Reference タブ: ノード・VEX・APEX・シェルフツールの説明）も同様
try:
    from reference_view import ChatFigureStrip as _ChatFigureStrip  # 回答の下に、Reference の絵を添える（2026-11-25）
    from reference_view import TermLookup as _TermLookup  # 用語をダブルクリックで、Reference で探す（2026-11-25、A20）
    from reference_view import ReferenceWidget as _ReferenceWidget
    _REFERENCE_AVAILABLE = True
except ImportError:
    _REFERENCE_AVAILABLE = False

# guide_view.py（Guide タブ: 手順ごとの案内）も同様
try:
    from guide_view import GuideWidget as _GuideWidget
    _GUIDE_AVAILABLE = True
except ImportError:
    _GUIDE_AVAILABLE = False

# tutorial_view.py（チュートリアル生成タブ）も同様にフォールバック対応
try:
    from tutorial_view import TutorialGeneratePanel as _TutorialGeneratePanel
    from tutorial_view import TutorialHistoryPanel as _TutorialHistoryPanel
    from tutorial_view import VideoLibraryPanel as _VideoLibraryPanel
    _TUTORIAL_AVAILABLE = True
except ImportError:
    _TUTORIAL_AVAILABLE = False

from rag_client import RAGClient, migrate_config as _migrate_config
from panel_info import ANSWER_MODE_CHOICES as _ANSWER_MODE_CHOICES, EXPLAIN_CHOICES as _EXPLAIN_CHOICES, has_guess as _has_guess, normalize_answer_mode as _normalize_answer_mode, format_explain as _format_explain, format_growth as _format_growth, format_user as _format_user, friendly_error as _friendly_error, is_setup_user as _is_setup_user, summarize_sources as _summarize_sources
from panel_widgets import CollapsibleBox as _CollapsibleBox, ui_state_get as _ui_state_get, ui_state_set as _ui_state_set
import panel_debug as _debug
import node_links as _node_links
import question_hints as _question_hints
import panel_bus as _bus
import panel_nav as _nav
import panel_paths as _paths
from pilot_panel import PilotTaskPanel as _PilotTaskPanel
from rag_client import post_json as _post_json
from rag_client import _cf_base as _cf_base_url
from panel_thinking import ThinkingRow as _ThinkingRow
from panel_actions import TEXT_SCALES as _TEXT_SCALES, set_text_scale as _set_text_scale, text_scale as _text_scale
from panel_actions import Speaker as _Speaker, action_button as _action_button, button_qss as _button_qss, make_icon as _make_icon, px as _px, type_font as _type_font, type_qss as _type_qss, normalize_fonts as _normalize_fonts, set_active as _action_set_active
from PySide6.QtCore import Qt, QSize, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QApplication,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ─── 設定ファイル ─────────────────────────────────────────────────────────────
# ~/.houdini/ に保存することで Houdini のバージョンに依存しない場所に永続化できる
_CONFIG_PATH = Path.home() / ".houdini" / "rag_chatbot_config.json"
_DEFAULT_CONFIG = {
    "mode":             "cloudflare",  # "cloudflare" | "local"
    "cf_url":           "",        # Cloudflare Worker の URL（例: https://rag-poc.xxx.workers.dev）
    "cf_api_key":       "",        # Cloudflare RAG の API キー（管理画面で発行）
    "cf_namespaces":    "",        # チャットで検索するナレッジ（カンマ区切り。空=権限のある全ナレッジ）
    "local_port":       8766,      # ローカルブリッジのポート番号
    "local_bridge_dir": "",        # rag_local_bridge.py が含まれるプロジェクトのパス
    "llm_backend":      "claude",  # "claude" | "gemini"（Local モード LLM 切り替え）
    "tutorial_model":   "claude-sonnet-5-5",  # チュートリアル生成（Cloudflare経由Claude）のモデル。2026-11-25 に claude-sonnet-5 から変更
                                    # （同じ単価で、effort: medium を送れる。実証実験の費用の主因。rag_client.DEFAULT_TUTORIAL_MODEL）
    "score_user_id":    "",        # 理解度スコア記録用ユーザーID
    "explain_level":    "auto",    # チャットの説明レベル: auto（おまかせ＝成長）| basic | applied | advanced
    "answer_mode":      "open",    # チャットの答え方: open（資料を最優先に、足りないところは「（推測）」と明示して答える）| grounded（資料だけ）
    "video_factory_exe_path": "",  # LearningQt video_factory_cloudrag_poc.exe のフルパス
                                    # （チュートリアル保存時に自動で動画生成を起動する）
    # チュートリアル生成が検索するナレッジ（2026-10-04追加）。""=起動中のHoudiniのバージョンに
    # 自動で合わせる（Houdini 22なら houdini22）。"houdini22" / "shared:houdini22" のように指定も可。
    # 上の cf_namespaces（チャット用）とは別物で、チュートリアル生成には影響しない。
    "tutorial_rag_namespace":  "",
    # 動画ギャラリー（ダッシュボードの「動画」ページ）へのアップロード先。
    # gallery_url 例: https://ragreel-gallery.xxx.workers.dev / gallery_token は UPLOAD_TOKEN
    "gallery_url":      "",
    "gallery_token":    "",
    "gallery_auto_upload": True,   # 動画生成の完了時に、自動でギャラリーへ上げる
    "video_length": "full",        # 動画の長さ: "full"（既定。全部の手順を、1 手順ずつ解説する）| "short"（約 22 場面にまとめる。短いが、粗い）
}

def _read_config_file(path: Path) -> tuple[dict | None, str]:
    """設定ファイルを読む。戻り値は (設定, 読めなかった理由)。無いときは (None, "")。

    BOM つき（メモ帳で保存したもの）も読む。空のファイル・壊れた JSON・オブジェクトでない JSON は、
    理由つきで None を返す（呼び出し側が、既定の設定で続ける。以前は、これらが黙って「設定が空」になっていた）。
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None, ""
    except OSError as exc:
        return None, f"設定ファイルを読めません（{exc.__class__.__name__}）"
    if not text.strip():
        return None, "設定ファイルが空です"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"設定ファイルが壊れています（{exc}）"
    if not isinstance(data, dict):
        return None, "設定ファイルの形が違います（{ ... } の形ではありません）"
    return data, ""


def _load_config() -> dict:
    """
    設定ファイルを読み込む。
    ファイルが存在しない or 壊れている場合はデフォルト設定を返す（理由は、メニュー（≡）の「デバッグ」の記録に残す）。
    既存設定とデフォルトをマージするので、新しいキーが追加されても後方互換を保てる。
    保存先（local_bridge_dir）が未設定なら、既定の場所（ドキュメント内の RAGReelTutorial フォルダ）を使う（panel_paths）。
    """
    data, note = _read_config_file(_CONFIG_PATH)
    if note:
        _debug.log("設定", f"{note}: {_CONFIG_PATH}。既定の設定で続けます。")
    cfg = _migrate_config({**_DEFAULT_CONFIG, **data}) if data is not None else dict(_DEFAULT_CONFIG)
    result = _paths.apply_default_data_dir(cfg)
    if result["source"] == "default":
        _debug.log("設定", f"保存先が未設定のため、既定の場所を使います: {result['path']}")
    elif result["error"] and cfg.get("mode") != "local":
        _debug.log("設定", f"保存先を用意できません: {result['error']}")
    return cfg


def _save_config(cfg: dict, dir_edited: bool = False) -> None:
    """
    設定を JSON ファイルに書き込む。ディレクトリが存在しない場合は作成する。
    途中で失敗しても、元のファイルを壊さない（一時ファイルに書いてから置き換える。以前は、途中で失敗すると、空のファイルが残り得た）。
    保存先は、ファイルにある別の値（インストーラーが入れたもの）を、手元の空・既定の値で消さない（panel_paths.choose_to_save）。
    ただし、利用者が画面で保存先を変えた・空にしたとき（dir_edited=True）は、その値をそのまま書く。
    いまのファイルが壊れているときは、上書きする前に、元の中身を「.broken」の名前で残す（手で直せるように）。
    """
    on_disk, note = _read_config_file(_CONFIG_PATH)
    if not dir_edited:
        cfg["local_bridge_dir"] = _paths.choose_to_save(cfg.get("local_bridge_dir"), (on_disk or {}).get("local_bridge_dir"))
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if on_disk is None and ("壊れて" in note or "形が違" in note):  # 空のファイル・読めないファイルは、残さない
        try:
            _os.replace(_CONFIG_PATH, _CONFIG_PATH.with_name(_CONFIG_PATH.name + ".broken"))
        except OSError:
            pass
    temp = _CONFIG_PATH.with_name(_CONFIG_PATH.name + ".tmp")
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        _os.replace(temp, _CONFIG_PATH)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


# ─── RAG クライアント ─────────────────────────────────────────────────────────

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


# ─── バックグラウンドワーカー ─────────────────────────────────────────────────

class QueryWorker(QThread):
    """
    RAG クエリを別スレッドで実行するワーカー。
    PySide6 の UI スレッドで HTTP ブロッキング処理を行うとフリーズするため、
    QThread に切り出して Signal で結果を UI スレッドに返す。
    """
    finished = Signal(dict)  # 成功時: {"answer": str, "sources": list}
    error    = Signal(str)   # 失敗時: エラーメッセージ
    sources_ready = Signal(list)  # stream=True: 検索で見つかった出典（回答より先に届く）
    delta    = Signal(str)   # stream=True: 回答の本文の続き

    def __init__(
        self, client: RAGClient, query: str, history: list[dict], image_b64: str | None = None,
        explain: str | None = None, answer_mode: str | None = None, stream: bool = False,
    ) -> None:
        super().__init__()
        self._client    = client
        self._query     = query
        self._history   = history
        self._image_b64 = image_b64
        self._explain   = explain
        self._answer_mode = answer_mode
        self._stream    = stream

    def run(self) -> None:
        try:
            callbacks = {"on_sources": self.sources_ready.emit, "on_delta": self.delta.emit} if self._stream else {}
            result = self._client.query(self._query, self._history, image_b64=self._image_b64, explain=self._explain,
                                        answer_mode=self._answer_mode, **callbacks)
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
    user_info = Signal(dict)  # どのユーザーで入っているか（接続OKのときだけ）。失敗は {"error": 理由}
    growth_info = Signal(dict)  # 自分の習熟度（説明レベルのおまかせ用）。取れなければ {}

    def __init__(self, client: RAGClient) -> None:
        super().__init__()
        self._client = client

    def run(self) -> None:
        ok = self._client.health()
        self.result.emit(ok)
        if ok and self._client.cfg.get("mode") == "cloudflare":
            try:
                self.user_info.emit(self._client.whoami())
            except Exception as exc:  # 401（キーが無効）など。表示だけの機能なので、落とさない
                self.user_info.emit({"error": str(exc)[:80]})
            try:
                self.growth_info.emit(self._client.growth())
            except Exception:  # 古いWorker（/me/growth なし）でも、他の機能は動かす
                self.growth_info.emit({})
        elif ok:
            self.user_info.emit({})


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
            self.failed.emit("保存先フォルダ（ブリッジのあるフォルダ）が設定されていません（メニュー（≡） → 接続・アカウント → 保存先フォルダ）")
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


# ─── 表示幅の保護 ─────────────────────────────────────────────────────────────

_STATUS_MAX_CHARS = 120


def elide_text(text: str, limit: int = _STATUS_MAX_CHARS) -> str:
    """1行の表示用に、長い文を省略する（全文は呼び出し側がツールチップに出す）。"""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def tame_label_widths(root: QWidget) -> None:
    """折り返さない QLabel の「最小幅」を、中身の長さから切り離す。

    Qt の QLabel は、折り返さない場合、文字列全体の幅を最小幅として要求する。Houdini のペインは、
    パネルの最小幅がペインより広いと、パネルをはみ出させ、ペインの区切りも動かせなくなる
    （チャット後の「参照: …」で実機で発生、2026-10-21）。水平方向を Ignored にすると、レイアウトは
    中身の長さを無視して、割り当てられた幅だけを使う。"""
    for label in root.findChildren(QLabel):
        if label.wordWrap():
            continue
        policy = label.sizePolicy()
        label.setSizePolicy(QSizePolicy.Ignored, policy.verticalPolicy())
        label.setMinimumWidth(0)


# ─── チャットバブル ───────────────────────────────────────────────────────────

def _answer_markdown(question: str, answer: str, sources: list) -> str:
    """回答を、出典つきの Markdown にする(Web のチャット画面の「Markdown コピー」と同じ形)。"""
    lines = []
    if question:
        lines += ["## " + question.strip(), ""]
    lines += [answer.strip(), ""]
    if sources:
        lines.append("### 出典")
        for i, src in enumerate(sources, 1):
            name = src.get("file") or src.get("title") or "(名称なし)"
            ns = src.get("namespace") or ""
            lines.append("%d. %s%s" % (i, name, "（" + ns + "）" if ns else ""))
    return chr(10).join(lines).strip() + chr(10)


LINK_COLOR = _node_links.LINK_COLOR  # 暗い背景で読めるリンクの色


def open_external_url(url: str) -> bool:
    """外部ブラウザで URL を開く。http / https 以外（javascript: など）は、開かない。"""
    if not _node_links.is_safe_url(url):
        _debug.log("リンク", f"開けない URL を止めました: {url[:80]}")
        return False
    return bool(QDesktopServices.openUrl(QUrl(url)))


def make_links_clickable(label: QLabel) -> None:
    """リッチテキストのラベルの、リンクを、クリックで外部ブラウザに開く（Qt 任せにせず、URL を検査してから開く）。"""
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(False)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
    palette = label.palette()
    palette.setColor(QPalette.Link, QColor(LINK_COLOR))
    palette.setColor(QPalette.LinkVisited, QColor("#c4b5fd"))
    label.setPalette(palette)
    label.linkActivated.connect(open_external_url)
    label.linkHovered.connect(lambda url, w=label: w.setToolTip(url or ""))  # 開く前に、行き先を確かめられる


class ChatBubble(QLabel):
    """
    1件のメッセージをバブル形式で表示するラベル。
    ユーザー発言は青系背景・右寄せ、RAG 回答はグレー背景・左寄せ で視覚的に区別する。
    テキスト選択を有効にしてコピーできるようにしている。
    rich_links=True（RAG の回答）のときは、回答の中の http(s) の URL を、クリックできるリンクにする
    （外部ブラウザで開く。文字は、すべてエスケープする）。それ以外は、文字のまま表示する（< や > があっても、タグにならない）。
    """

    def __init__(self, text: str, is_user: bool, rich_links: bool = False) -> None:
        super().__init__()
        self.setWordWrap(True)
        if rich_links:
            self.setText(_node_links.linkify_html(text))
            make_links_clickable(self)
        else:
            self.setTextFormat(Qt.PlainText)
            self.setText(text)
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
    """接続状態を丸いランプ（色）+ テキストで示すインジケータ。クリックすると、接続の画面（メニュー（≡）内）を開く。"""

    clicked = Signal()

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
            "Cloudflare: Worker の /health への疎通 / Local: ブリッジの /health を定期確認しています\n"
            "クリックすると、接続・アカウントの画面を開きます"
        )
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: D102 -- Qt override
        self.clicked.emit()
        super().mousePressEvent(event)


# ─── サイズヒント固定コンテナ ─────────────────────────────────────────────────
# 根本原因（2026-09-07、実機での再現テストにより特定。QSizePolicy.Ignoredを
# 個々のタブ内ウィジェットに指定するだけでは解消しなかった）:
# QTabWidgetは内部でQStackedWidgetを使っているが、これは「現在表示中のタブ」
# だけでなく非表示の全タブページを含めたsizeHint/minimumSizeHintの最大値を
# 自身の値として報告する（タブ切り替え時にレイアウトが揺れないようにするため）。
# つまりDocs/Tutorial/Historyタブが内部に持つ閲覧ウィジェットやノードグラフビューアなどが
# （それ自体は正当な理由で）大きめのminimumSizeを持っていた場合、たとえ
# ユーザーが「はじめに」タブしか開いていなくても、QTabWidget全体の最小サイズが
# それに引きずられて大きくなり、Houdiniのペイン分割がそのサイズより小さく
# 縮められなくなる（「開くと縦が固定される」の実体）。
# 各タブページをこのコンテナで一律に包み、sizeHint()/minimumSizeHint()の
# 両方を固定の小さい値で上書きすることで、タブ内部の実際の要求サイズが
# QTabWidget側の集計に伝播しないようにする。実際に割り当てられる表示サイズ
# には影響しないため、ペインが広ければ従来通りその分だけ中身が広がる。


class _FixedHintTab(QWidget):
    """
    タブページ用ラッパー。sizeHint()/minimumSizeHint()を固定し、内容量や
    子ウィジェットの要求サイズがQTabWidget全体の最小サイズを押し上げない
    ようにする（このクラス手前のコメント参照）。
    """

    def sizeHint(self) -> QSize:  # noqa: D102 -- Qt override
        return QSize(320, 200)

    def minimumSizeHint(self) -> QSize:  # noqa: D102 -- Qt override
        return QSize(50, 50)


# ─── メインパネル ─────────────────────────────────────────────────────────────

class RAGChatbotPanel(QWidget):
    """
    Houdini Python Panel のルートウィジェット。
    Chat / Docs / Settings などのタブ構成。

    状態:
      _cfg           : 設定辞書（常に最新値を保持）
      _client        : RAGClient（設定変更時に再生成）
      _history       : 会話履歴リスト（ユーザー / アシスタント交互に追加）
      _worker        : 実行中の QueryWorker（二重送信防止に使う）
      _bridge_worker : ブリッジ起動中の BridgeStartWorker
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        _debug.install_excepthook()  # スロットから出た例外を、デバッグの記録に残す（2026-11-24）
        super().__init__(parent)
        _bus.register(self)  # ほかのパネルから、Guide ⇄ Reference の移動を受けるため（panel_bus.py）
        self._cfg           = _load_config()
        self._client        = RAGClient(self._cfg)
        self._history: list[dict]               = []
        self._worker: QueryWorker | None        = None
        self._bridge_worker: BridgeStartWorker | None = None
        self._rate_workers: list[RateWorker]    = []  # GC 防止のため参照を保持
        self._last_query = ""            # 直近の質問(回答の「再試行」「出典つきコピー」で使う)
        self._speaker = _Speaker()       # 読み上げ(QtTextToSpeech が無い環境では available=False)
        self._conn_worker: _ConnectionCheckWorker | None = None
        self._role: str = str(_ui_state_get("last_role", "") or "")  # 最後に確認できた役割（画面の出し分け用）
        self._last_health: tuple[float, bool] | None = None
        self._last_user_info: dict | None = None
        self._last_growth: dict | None = None
        self._current_sub = ""           # メニュー（≡）の中の画面を開いているとき、そのキー（タブの画面なら ""）

        self._build_ui()
        self._ensure_bridge()  # Local モードなら起動確認
        QTimer.singleShot(2000, self._setup_float_hotkey)  # シェルフツールが読み込まれたあとで、キーを割り当てる（最初の 1 回）

        # 接続状態ランプ: 初回チェック + 定期的な自動再チェック（タブを切り替えなくても
        # 現在の接続状態が分かるようにするため）。
        self._conn_timer = QTimer(self)
        self._conn_timer.timeout.connect(self._check_connection_async)
        self._conn_timer.start(_CONNECTION_CHECK_INTERVAL_MS)
        self._check_connection_async()

    # ── UI 構築 ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """ルートレイアウトを構築してタブを追加する。"""
        # Houdiniのペインが縦に長い場合でも、このウィジェット自身が利用可能な高さを
        # 素直に受け取れるようにする（既定のPreferredのままだと、内部レイアウトの
        # 都合でウィジェット自体がペインの一部しか使わず、下部（入力欄など）が
        # ペインの空白領域の外に取り残されて操作不能になる不具合の対策、2026-08-27）。
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        tabs = QTabWidget()
        # 「はじめに」を先頭タブにする: 初めて開いたユーザーが最初に目にするのが
        # 空のチャット欄だと何をすればいいか分からない、という実機フィードバックへの
        # 対策。各タブの役割・最初にやること・つまずきやすい点をまとめた説明を置く。
        #
        # 各タブは_wrap_tab()で包んでから追加する（_FixedHintTabのコメント参照）:
        # Docs/Tutorial/Historyタブの中身が持つ正当な最小サイズ要求が、たとえ
        # 別のタブを表示中でもQTabWidget全体の最小サイズに伝播し、ペインを
        # 縮められなくする不具合の対策。
        # Settings / Tutorial は自前のスクロール手段を持たない素のフォーム
        # レイアウトなので scrollable=True にする（_wrap_tab()のdocstring参照。
        # これがないと、割り当て高さ不足時にラベルや入力欄が圧縮されて重なって
        # 見える不具合になっていた＝2026-09-07実機報告の再発分）。
        tutorial_tab = self._build_tutorial_tab()
        self._tutorial_tab_wrapper = self._wrap_tab(tutorial_tab, scrollable=True)
        # 「動画」タブ（2026-09-12追加）は_tutorial_tab_wrapperと同じ理由でself._tabsより
        # 先に参照を確保しておく必要がある。TutorialGeneratePanel/TutorialHistoryPanelの
        # コールバック（_on_video_ready/_on_open_video）がこのタブへの切り替えに使う。
        video_tab = self._build_video_tab()
        self._video_tab_wrapper = self._wrap_tab(video_tab)
        # 「はじめに」は、アイコン（本）だけのタブ。Docs タブは、使わないので、なくした（2026-11-18）。動画のタブは「Movie」
        book = _make_icon(_nav.ICON_TABS["help"])
        help_index = tabs.addTab(self._wrap_tab(self._build_help_tab()), book, "" if not book.isNull() else "?")  # SVG が無い環境は、文字で代用
        tabs.setTabToolTip(help_index, "はじめに（使い方）")
        self._chat_tab_idx = tabs.addTab(self._wrap_tab(self._build_chat_tab()),     "Chat")
        tabs.addTab(self._wrap_tab(self._build_guide_tab(), scrollable=True, min_size=(_px(300), _px(560))), "Guide")
        tabs.addTab(self._tutorial_tab_wrapper,                 "Tutorial")
        tabs.addTab(self._wrap_tab(self._build_reference_tab(), scrollable=True, min_size=(_px(300), _px(520))), "Reference")
        tabs.addTab(self._video_tab_wrapper,                    "Movie")
        # 「課題」タブ（実証実験の参加者向け）。メニュー（≡）「接続・アカウント」の「実証実験に参加する」を入れたときだけ表示する（既定は非表示）。
        self._pilot_panel = _PilotTaskPanel(lambda: self._cfg)
        self._pilot_tab_idx = tabs.addTab(self._wrap_tab(self._pilot_panel, scrollable=True), "課題")
        tabs.setTabVisible(self._pilot_tab_idx, bool(_ui_state_get("pilot_enabled", False)))
        # ふだん使わない画面（履歴・接続・設定・デバッグ）は、タブに並べず、右上のメニュー（≡）の中に置く
        # （2026-11-17 実証実験の感想: 設定のタブが、ふだん使うタブと同じ重さで目立っていた）。
        # 「設定」と「デバッグ」は、設定者（admin / editor）にだけ出す（_apply_role_visibility）。
        # サーバー側の権限が正で、これは画面の出し分け。
        self._sub_wrappers = {
            "history": self._wrap_tab(self._build_history_tab()),
            "connection": self._wrap_tab(self._build_connection_tab(), scrollable=True),
            "settings": self._wrap_tab(self._build_settings_tab(), scrollable=True),
            "debug": self._wrap_tab(self._build_debug_tab(), scrollable=True),
        }
        tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs = tabs  # /tutorial コマンドでのタブ切り替えに使う

        # 接続状態ランプ。以前はQTabWidget.setCornerWidget()でタブバー右端に
        # 埋め込んでいたが、Houdiniのペインに組み込んだ状態でパネルを開くと
        # ウィンドウ全体がリサイズ不能になるという報告があり、疑わしい候補として
        # 撤回した（2026-08-27）。setCornerWidgetは比較的マイナーなAPIで、
        # Houdiniのペインホスト側のサイズ計算と干渉した可能性がある。
        # 素直な行として独立させても「どのタブを開いていても見える」という
        # 目的は変わらず達成できる。
        self._conn_lamp = _ConnectionLamp()
        # どのユーザーで入っているか（キーの名前・役割）。接続確認のたびに更新する。
        self._user_label = QLabel("")
        self._user_label.setStyleSheet("color:#cbd5e1;font-size:11px;")
        self._apply_user_label(None)
        lamp_row = QHBoxLayout()
        lamp_row.addWidget(self._user_label)
        lamp_row.addStretch()
        lamp_row.addWidget(self._conn_lamp)
        self._conn_lamp.clicked.connect(lambda: self._show_sub("connection"))
        lamp_row.addWidget(self._build_gear_button())
        root.addLayout(lamp_row)

        # 0: タブの画面 / 1: メニュー（≡）の中の画面（戻るボタンつき）
        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(tabs)
        self._main_stack.addWidget(self._build_sub_view())
        root.addWidget(self._main_stack, stretch=1)

        # 下部ステータスバー（接続状態や参照ドキュメントを表示）
        self._status = QLabel("")
        self._status.setStyleSheet("color:#aaa;font-size:11px;")
        root.addWidget(self._status)

        # 2026-10-21: チャットの回答のあと、下部に「参照: タイトル, タイトル, …」が1行で出て、
        # ラベルの最小幅がペインより広くなり、パネルがペインからはみ出して、ペインの
        # 区切り（比率）が動かせなくなった。折り返さないラベルは、中身の長さを無視させる。
        tame_label_widths(self)
        _normalize_fonts(self)  # px のフォントを pt に揃える(4K・拡大表示で、文字の大きさが部品とずれないように)

    def _build_help_tab(self) -> QWidget:
        """
        「はじめに」タブ: 初めてこのパネルを開いた人向けのクイックスタート・
        各タブの役割・よくある詰まりポイントをまとめた静的な説明タブ。
        設定や外部通信を一切行わない読み取り専用タブなので、フォールバック
        UI や例外処理は不要（QTextEdit にHTMLを流すだけ）。
        """
        # このタブ自体のコンテナサイズ管理は呼び出し元の_wrap_tab()に委ねている
        # （QTabWidget全体の最小サイズへの伝播対策。_FixedHintTabのコメント参照）。
        w = QWidget()
        layout = QVBoxLayout(w)
        view = QTextEdit()
        view.setReadOnly(True)
        # QTextEditはリッチテキストの内容量に応じてsizeHint()が伸びることがあり、
        # 縦方向のポリシーが既定のPreferredのままだと、Houdiniのペインホストが
        # そのsizeHintに合わせてパネル全体を大きくしようとして、ペインの実際の
        # 表示領域からはみ出した分が切れて見える（内部スクロールバーも出ない）
        # 不具合になっていた（2026-09-07実機報告）。setSizePolicy()の縦方向を
        # Ignoredにし、sizeHintを無視して親レイアウトの割り当て分だけを使わせる
        # ことで、はみ出した内容はQTextEdit自身の内部スクロールに委ねる
        # （471行目のパネル全体と同じ理由の対策）。
        view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
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
<li><b>接続を確認する</b> — 右上に「Local 接続OK」または「Cloudflare 接続OK」の
緑ランプが出ているか確認してください。赤色（接続なし）の場合は、ランプをクリックするか、
右上のメニュー（≡）→ <code>接続・アカウント</code> で URL と APIキーを確認し、「保存して接続を確認」を押してください。</li>
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
と入力すると Tutorial タブに切り替わりその場で生成を開始できます。回答の中の URL はリンクになり、
クリックすると外部ブラウザで開きます。ノードの名前（Pyro Solver など）が出てきたときは、回答の下に、
SideFX の公式ドキュメントへのリンクが出ます。</li>
<li><b>Guide</b> — 保存したチュートリアル（生成した直後のものも）を、手順ごとに案内するタブ。
「この手順を案内」で、操作するノードを選び、見るタブを前面に出します。値を変える手順では、パラメータ画面の項目の位置に合わせます。</li>
<li><b>Tutorial</b> — トピックを入力してチュートリアルを自動生成するタブ。生成結果は
プレビュー表示されるだけで、「保存」を押すまでファイルには書き込まれません。</li>
<li><b>Movie</b> — 生成した動画の一覧。「ダッシュボードへアップロード」で、
ダッシュボードの動画ページ（ギャラリー）に載せられます。</li>
</ul>

<h2>右上のメニュー（≡）（ふだん使わない画面）</h2>
<ul>
<li><b>保存したチュートリアル（History）</b> — 保存済みチュートリアルの一覧と、実際に組み立てられたノード
グラフのビューア。「簡易」は直列に繋がったノードを1つにまとめた要約表示、
「詳細」は全ノードをそのまま表示するモードです（マウスホバーで各ボタンの
説明が出ます）。</li>
<li><b>接続・アカウント</b> — あなたの情報（ユーザー名・役割）と、Worker の URL / APIキー、チャットで検索するナレッジ、
<b>保存先フォルダ</b>（チュートリアル・動画・記録の置き場所。空欄ならドキュメント内の RAGReelTutorial フォルダ）、動画ギャラリーの接続。</li>
<li><b>設定・デバッグ</b>（設定者だけに表示） — チュートリアル生成のモデル・検索するナレッジ、Local RAG の設定と、
接続の詳細・記録（ログ）。</li>
<li><b>このパネルを別ウィンドウで開く</b> — タブを切り替えずに、<b>別のタブを並べて見る</b>ためのものです。
たとえば、片方で Guide を見ながら、もう片方で Chat に質問できます。Houdini のペインを分けて、
もう 1 つ「RAGReel Tutorial」を開いても、同じことができます（「並べて見る方法」を選ぶと、手順が出ます）。</li>
</ul>

<h2>よくある詰まりポイント</h2>
<ul>
<li><b>ランプが赤い（接続なし）</b> — Local モードならブリッジ（<code>rag_local_bridge.py</code>）
が起動しているか確認してください。メニュー（≡）の <code>設定</code> の「Local RAG」にある「ブリッジ再起動」で
自動起動を試みます。Cloudflare モードなら Worker の URL / APIキー の設定を見直してください。</li>
<li><b>「保存先未設定」と出る</b> — 通常は、ドキュメント内の RAGReelTutorial フォルダに自動で保存します。
出たときは、メニュー（≡）→ <code>接続・アカウント</code> の「保存先フォルダ」に、書き込める場所を入力して保存してください。</li>
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
          - モード切り替えコンボ（local / cloudflare）
          - スクロール可能なメッセージエリア
          - 入力テキストエリア（Ctrl+Enter で送信）
          - 送信 / クリアボタン
        """
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(_px(6))  # Tutorial タブと同じ、拡大率に追従する余白（2026-11-18）

        def caption(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet(_type_qss("caption", "#94a3b8"))
            return label

        # モード切り替え行
        mode_row = QHBoxLayout()
        # モード（local / cloudflare）の切り替えは設定者だけ（一般ユーザーは Cloudflare に固定）。
        self._mode_box = QWidget()
        mode_box_layout = QHBoxLayout(self._mode_box)
        mode_box_layout.setContentsMargins(0, 0, 0, 0)
        mode_box_layout.addWidget(caption("モード:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["local", "cloudflare"])
        self._mode_combo.setCurrentText(self._cfg["mode"])
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_box_layout.addWidget(self._mode_combo)
        mode_row.addWidget(self._mode_box)

        # 画面添付チェックボックス（VLM入力）。Cloudflare のみ対応。次の送信1回だけ有効な
        # ワンショット仕様にしている（毎回同じ画面を送り続けてしまう事故を防ぐため）。
        self._attach_viewport_checkbox = QCheckBox("画面を添付")
        self._attach_viewport_checkbox.setToolTip(
            "現在のHoudiniビューポートをキャプチャして次のメッセージに添付します"
            "（Cloudflareモードのみ対応。送信すると自動でオフに戻ります）"
        )
        self._attach_viewport_checkbox.setEnabled(self._cfg["mode"] == "cloudflare")
        mode_row.addWidget(self._attach_viewport_checkbox)

        # 説明レベル（Cloudflare のみ）。おまかせ＝これまでの質問（使った専門用語）から、だんだん高度になる。
        mode_row.addWidget(caption("説明:"))
        self._explain_combo = QComboBox()
        for value, label in _EXPLAIN_CHOICES:
            self._explain_combo.addItem(label, value)
        saved_explain = str(self._cfg.get("explain_level", "auto"))
        idx = self._explain_combo.findData(saved_explain)
        self._explain_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._explain_combo.setToolTip(
            "回答の説明の深さ。おまかせ＝質問に使った専門用語の蓄積から、だんだん高度になります。\n"
            "メニュー（≡） →「接続・アカウント」で、いまの習熟度を確認できます（Cloudflareモードのみ）。"
        )
        self._explain_combo.setEnabled(self._cfg["mode"] == "cloudflare")
        self._explain_combo.currentIndexChanged.connect(self._on_explain_changed)
        mode_row.addWidget(self._explain_combo)

        # 答え方。資料に無い質問（「ミズクラゲを作るのに必要そうなノードは？」など）に、推測でも答えるか。
        mode_row.addWidget(caption("答え方:"))
        self._answer_combo = QComboBox()
        for value, label in _ANSWER_MODE_CHOICES:
            self._answer_combo.addItem(label, value)
        self._answer_combo.setCurrentIndex(max(0, self._answer_combo.findData(_normalize_answer_mode(self._cfg.get("answer_mode")))))
        self._answer_combo.setToolTip(
            "資料＋推測（自由）: 資料を最優先にし、資料に無い話題・見立てが要る質問には、一般知識から答えます。\n"
            "　推測の部分には「（推測）」と、確かさ・確かめ方が付きます（資料に書かれたことと混ざりません）。\n"
            "資料だけ（正確）: 資料に書かれていることだけで答えます。無いときは「わかりません」になります。"
        )
        self._answer_combo.currentIndexChanged.connect(self._on_answer_mode_changed)
        mode_row.addWidget(self._answer_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # メッセージエリア（スクロール）。0にはならない最低限の高さを明示しておく
        # （2026-08-27: スプリッター案は「今度は逆に上（メッセージ欄）が消える」
        # という結果になったため撤回。QSplitterのcollapsible/stretchFactorの
        # 組み合わせに頼らず、素直なQVBoxLayout+stretchに戻し、両方に最低保証の
        # 高さだけを与える、より予測しやすい構成にした）。
        self._chat_scroll  = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setMinimumHeight(120)
        self._chat_scroll.setFrameShape(QFrame.NoFrame)
        self._chat_inner   = QWidget()
        self._chat_inner.setFont(_type_font("body"))  # 回答の文字の大きさを、Tutorial タブと同じ 10pt にそろえる
        self._chat_layout  = QVBoxLayout(self._chat_inner)
        self._chat_layout.addStretch()  # バブルを下から積み上げるためのスペーサー
        self._chat_scroll.setWidget(self._chat_inner)
        layout.addWidget(self._chat_scroll, stretch=1)

        # 質問の例（押すと、そのまま送る）。「何がわからないのかがわからない」ときの入り口（2026-11-25、実証実験の A3）。
        # いま見ている Guide の手順・選んでいるノード・エラーから作る（question_hints.py。AI は使わない）
        self._hints_box = QWidget()
        self._hints_layout = QHBoxLayout(self._hints_box)
        self._hints_layout.setContentsMargins(0, 0, 0, 0)
        self._hints_layout.setSpacing(_px(4))
        layout.addWidget(self._hints_box)
        QTimer.singleShot(0, self._refresh_hints)

        # テキスト入力（固定高さ70→50に縮小。ボタン行と合わせた最低限の要求高さを
        # 減らし、狭いペインでも収まりやすくする）
        self._input = QTextEdit()
        self._input.setFixedHeight(_px(56))
        self._input.setFont(_type_font("body"))
        self._input.setPlaceholderText("質問を入力（Ctrl+Enter で送信）")
        layout.addWidget(self._input)

        # 主な操作は「送信」（主ボタン）。「クリア」は副。送るキーの案内は、補足の文字で左に置く
        btn_row = QHBoxLayout()
        btn_row.addWidget(caption("Ctrl+Enter で送信"))
        self._send_btn = QPushButton("送信")
        self._send_btn.setStyleSheet(_button_qss("primary"))
        self._send_btn.clicked.connect(self._on_send)
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self._on_clear)
        btn_row.addStretch()
        btn_row.addWidget(self._send_btn)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        # Ctrl+Enter の検知は eventFilter で行う
        self._input.installEventFilter(self)

        # Houdiniが新規作成直後のPythonパネルに、最終的なペインサイズが確定する前の
        # 小さい/不確定なサイズで最初のレイアウトを行わせてしまい、そのままレイアウトの
        # 計算結果が固まって見える、という挙動を疑っている（未確認の推測）。次のイベント
        # ループでもう一度サイズ再計算を強制することで、確定後の実サイズに追随させる。
        QTimer.singleShot(0, self._nudge_relayout)
        return w

    def _nudge_relayout(self) -> None:
        """Chatタブのレイアウトを、ウィジェットが実際の最終サイズを得た後に再計算させる。"""
        self._chat_scroll.updateGeometry()
        self._input.updateGeometry()
        self.updateGeometry()
        if self.layout() is not None:
            self.layout().activate()

    def _build_reference_tab(self) -> QWidget:
        """
        Reference タブ（2026-11-19）: ノード・VEX・APEX・シェルフツールの「何をする・使いどころ・実例」。チュートリアルで使ったものに「●」。
        説明は、公式のドキュメントと HoudiniReference を元に、AI がまとめて保存する（reference_view.py）。
        """
        if _REFERENCE_AVAILABLE:
            def complete():
                panel = getattr(self, "_tutorial_panel", None)
                return panel._make_agent().complete_text if panel is not None else None

            self._reference_widget = _ReferenceWidget(lambda: self._cfg, complete)
            return self._reference_widget
        return self._missing_module_widget("reference_view.py")

    def _build_guide_tab(self) -> QWidget:
        """
        Guide タブ（2026-11-03）: 保存したチュートリアルを手順ごとに案内する。見るタブ・操作するノード・
        変えるパラメータ・ショートカットを示し、Houdini の画面のタブとノードを前面に出す（画面の部品は消さない）。
        """
        if _GUIDE_AVAILABLE:
            self._guide_widget = _GuideWidget(lambda: self._cfg)
            return self._guide_widget
        w = QWidget()
        layout = QVBoxLayout(w)
        label = QLabel(
            "guide_view.py が見つかりません。\n"
            "houdini/python_panels/ に guide_view.py と guide_mode.py を配置してください。"
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
            # on_video_ready: 動画生成完了を「動画」タブへ即時反映するコールバック
            # （2026-09-12追加、_on_video_ready参照）。
            self._tutorial_panel = _TutorialGeneratePanel(
                lambda: self._cfg,
                on_connection_event=self._check_connection_async,
                on_video_ready=self._on_video_ready,
            )
            self._tutorial_panel.set_developer_view(self._is_setup())  # 進行ログは設定者だけ（A5。役割が確かめられたら、_apply_role_visibility で直す）
            return self._tutorial_panel
        self._tutorial_panel = None
        return self._missing_module_widget("tutorial_view.py")

    def _build_history_tab(self) -> QWidget:
        """History タブ: 保存済みチュートリアルの一覧とノードグラフ表示。"""
        if _TUTORIAL_AVAILABLE:
            # on_open_video: 「▶ 動画を再生」ボタンから「動画」タブへ切り替えるコールバック
            # （2026-09-12追加、_on_open_video参照）。
            self._history_panel = _TutorialHistoryPanel(lambda: self._cfg, on_open_video=self._on_open_video)
            return self._history_panel
        return self._missing_module_widget("tutorial_view.py")

    def _build_video_tab(self) -> QWidget:
        """
        動画タブ（2026-09-12追加）: 保存済みチュートリアルの動画を一覧・再生する。
        従来は生成直後のプレビュー再生ボタン（別ウィンドウのポップアップ）でしか見られず、
        かつ動画パスがどこにも永続化されていなかったため、タブを離れる/Houdiniを再起動
        すると二度と見つけられなかった（実機フィードバック）。
        """
        if _TUTORIAL_AVAILABLE:
            self._video_library_panel = _VideoLibraryPanel(lambda: self._cfg)
            return self._video_library_panel
        self._video_library_panel = None
        return self._missing_module_widget("tutorial_view.py")

    def _on_video_ready(self, name: str, video_path) -> None:
        """TutorialGeneratePanelから、動画生成が完了するたびに呼ばれる。"""
        if self._video_library_panel is not None:
            self._video_library_panel.show_video(name, video_path)

    def _on_open_video(self, name: str, video_path) -> None:
        """
        TutorialHistoryPanelの「▶ 動画を再生」ボタンから呼ばれる。動画タブへ切り替えて
        該当動画を選択状態にする。
        """
        if self._video_library_panel is not None:
            self._video_library_panel.show_video(name, video_path)
        self._show_main()  # 履歴（メニュー（≡）の中）から呼ばれたとき、動画のタブへ戻る
        self._tabs.setCurrentWidget(self._video_tab_wrapper)

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

    @staticmethod
    def _wrap_tab(content: QWidget, scrollable: bool = False, min_size: tuple[int, int] | None = None) -> QWidget:
        """
        タブページを_FixedHintTabで包む。QTabWidget追加直前に呼ぶこと。
        戻り値のラッパーがQTabWidgetに登録される実際のタブページになるため、
        後から特定のタブへプログラム的に切り替えたい場合（例: /tutorial
        コマンド）は、中身のウィジェットではなくこのラッパーの参照を使うこと。

        scrollable=True の場合、contentをQScrollArea経由で追加する。
        _FixedHintTabはminimumSizeHint()を50x50に固定して報告するため
        （QTabWidget全体の最小サイズへの伝播対策）、Houdini側が実際に割り当てる
        高さがcontentの本来の必要サイズより小さいことがある。Settingsのような
        多数のラベル/入力欄を縦に並べただけの素のフォームタブは、自前のスクロール
        手段を持たないため、割り当てが不足すると各ウィジェットが圧縮され文字が
        重なって見える不具合になっていた（2026-09-07実機報告）。scrollable=True
        で包めば、割り当てが足りない場合はスクロールバーで対処され、圧縮による
        重なりは起きない。
        Chat（自前のメッセージスクロール領域＋常に見える位置固定の入力欄を持つ
        ため外側に更にスクロールを足すと入力欄が隠れる）、History（マウス
        ホイールでズーム操作するキャンバス系ウィジェットのため、外側スクロールが
        ホイールイベントを奪ってしまう）、はじめに（QTextEditが既に内部スクロール
        を持つため二重スクロールになる）は、scrollable=Falseのままにすること。
        """
        wrapper = _FixedHintTab()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        if scrollable:
            if min_size:
                # 狭い・低いペインに置かれても、部品が押しつぶされて重ならないように、最小の大きさを決める。
                # それより小さいときは、スクロールバーが出る（2026-11-21。右下の小さなペインで、Reference の一覧と説明が重なった）。
                content.setMinimumSize(min_size[0], min_size[1])
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setWidget(content)
            layout.addWidget(scroll)
        else:
            layout.addWidget(content)
        return wrapper

    def _build_connection_tab(self) -> QWidget:
        """
        「接続・アカウント」の画面（メニュー（≡）。全員）: あなたの情報 / Worker URL / APIキー / 検索するナレッジ / 保存先フォルダ / 動画・ギャラリー。
        一般ユーザーが触る設定は、ここまで（チュートリアルのモデル・ローカルRAGは「設定」の画面＝設定者だけ）。
        """
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        layout.addWidget(QLabel("あなたの情報"))
        self._conn_user_info = QLabel("")
        self._conn_user_info.setWordWrap(True)
        self._conn_user_info.setStyleSheet("color:#cbd5e1;background:#1e293b;border-radius:6px;padding:6px 10px;")
        layout.addWidget(self._conn_user_info)

        layout.addWidget(QLabel("習熟度（チャットの説明レベル「おまかせ」）"))
        self._conn_growth = QLabel("")
        self._conn_growth.setWordWrap(True)
        self._conn_growth.setStyleSheet("color:#cbd5e1;background:#1e293b;border-radius:6px;padding:6px 10px;")
        layout.addWidget(self._conn_growth)
        reset_growth_btn = QPushButton("習熟度の記録を消す")
        reset_growth_btn.setToolTip("質問に使った専門用語の記録（質問の文章は保存していません）を、すべて消します。説明は basic から始まります。")
        reset_growth_btn.clicked.connect(self._on_reset_growth)
        layout.addWidget(reset_growth_btn)

        layout.addWidget(QLabel("Cloudflare RAG への接続"))
        layout.addWidget(QLabel("Worker URL:"))
        self._cf_url_edit = QLineEdit(self._cfg.get("cf_url", ""))
        self._cf_url_edit.setPlaceholderText("https://rag-poc.xxxx.workers.dev")
        layout.addWidget(self._cf_url_edit)

        layout.addWidget(QLabel("APIキー:"))
        self._cf_api_key_edit = QLineEdit(self._cfg.get("cf_api_key", ""))
        self._cf_api_key_edit.setPlaceholderText("管理者から受け取ったAPIキー")
        self._cf_api_key_edit.setEchoMode(QLineEdit.Password)  # 入力文字を ● で隠す
        layout.addWidget(self._cf_api_key_edit)

        layout.addWidget(QLabel("チャットで検索するナレッジ（カンマ区切り。空欄=権限のある全ナレッジ）:"))
        self._cf_ns_edit = QLineEdit(self._cfg.get("cf_namespaces", ""))
        self._cf_ns_edit.setPlaceholderText("例: houdini22, shared:houdini22")
        layout.addWidget(self._cf_ns_edit)

        # 保存先フォルダ（local_bridge_dir）。一般の利用者にも見える場所に置く（以前は設定者だけの「設定」タブにあり、
        # 未設定のとき、参加者には直せなかった）。空欄なら、ドキュメント内の RAGReelTutorial フォルダを自動で使う。
        layout.addWidget(QLabel("保存先フォルダ（チュートリアル・動画・記録の置き場所。空欄=自動）:"))
        self._bridge_dir_edit = QLineEdit(self._cfg.get("local_bridge_dir", ""))
        self._bridge_dir_edit.setPlaceholderText(str(_paths.default_data_dir()))
        self._bridge_dir_edit.setToolTip(
            "空欄のときは、ドキュメント内の RAGReelTutorial フォルダを使います。\n"
            "Local モード（開発者）では、rag_local_bridge.py のあるプロジェクトのフォルダを入力します。"
        )
        layout.addWidget(self._bridge_dir_edit)
        dir_row = QHBoxLayout()
        open_dir_btn = QPushButton("保存先を開く")
        open_dir_btn.clicked.connect(self._on_open_data_dir)
        dir_row.addWidget(open_dir_btn)
        dir_row.addStretch()
        layout.addLayout(dir_row)
        self._data_dir_note = QLabel("")
        self._data_dir_note.setWordWrap(True)
        self._data_dir_note.setStyleSheet("color:#94a3b8;font-size:11px;")
        layout.addWidget(self._data_dir_note)
        self._refresh_data_dir_note()

        # 動画・ギャラリー: テスター（一般ユーザー）が、運営から受け取った URL とトークンを自分で入れるので、「接続・アカウント」に置く。
        def fill_video(box: QVBoxLayout) -> None:
            box.addWidget(QLabel("Video Factory exe パス:"))
            self._video_factory_exe_edit = QLineEdit(self._cfg.get("video_factory_exe_path", ""))
            self._video_factory_exe_edit.setPlaceholderText(
                "LearningQt\\build\\engine\\video_factory_cloudrag_poc.exe（未設定なら自動起動しない）"
            )
            box.addWidget(self._video_factory_exe_edit)
            box.addWidget(QLabel("ギャラリーURL（ダッシュボードの動画ページ）:"))
            self._gallery_url_edit = QLineEdit(self._cfg.get("gallery_url", ""))
            self._gallery_url_edit.setPlaceholderText("https://ragreel-gallery.xxxx.workers.dev")
            box.addWidget(self._gallery_url_edit)
            box.addWidget(QLabel("アップロードトークン:"))
            self._gallery_token_edit = QLineEdit(self._cfg.get("gallery_token", ""))
            self._gallery_token_edit.setPlaceholderText("ギャラリー管理者から受け取ったトークン")
            self._gallery_token_edit.setEchoMode(QLineEdit.Password)
            box.addWidget(self._gallery_token_edit)
            self._gallery_auto_checkbox = QCheckBox("動画の生成が終わったら、自動でギャラリーへアップロードする")
            self._gallery_auto_checkbox.setChecked(bool(self._cfg.get("gallery_auto_upload", True)))
            box.addWidget(self._gallery_auto_checkbox)
            box.addWidget(QLabel("動画の長さ:"))
            self._video_length_combo = QComboBox()
            self._video_length_combo.addItem("完全版（全部の手順を、1 手順ずつ解説します。長いと、作るのに 10〜20 分かかります）", "full")
            self._video_length_combo.addItem("短縮版（手順を約 22 場面にまとめます。短いですが、解説は粗くなります）", "short")
            self._video_length_combo.setCurrentIndex(max(0, self._video_length_combo.findData(str(self._cfg.get("video_length", "full") or "full"))))
            self._video_length_combo.setToolTip("手順書（Markdown）と Guide には、どちらでも、全部の手順が残ります")
            box.addWidget(self._video_length_combo)

        layout.addWidget(self._group_box("動画・ギャラリー", "conn.video", False, fill_video))

        # 実証実験の参加者だけが入れる。入れると「課題」タブが出る（既定はオフ。一般ユーザーの画面は増えない）。
        self._pilot_checkbox = QCheckBox("実証実験に参加する（「課題」タブを表示します）")
        self._pilot_checkbox.setChecked(bool(_ui_state_get("pilot_enabled", False)))
        self._pilot_checkbox.toggled.connect(self._on_pilot_toggled)
        layout.addWidget(self._pilot_checkbox)

        save_btn = QPushButton("保存して接続を確認")
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)
        layout.addStretch()
        return w

    def _group_box(self, title: str, state_key: str, collapsed: bool, fill) -> _CollapsibleBox:
        """設定のグループ（折りたたみ）。fill(layout) で中身を詰める。開閉の状態は覚える。"""
        content = QWidget()
        inner = QVBoxLayout(content)
        inner.setContentsMargins(12, 0, 0, 6)
        inner.setSpacing(6)
        fill(inner)
        return _CollapsibleBox(title, content, collapsed=collapsed, state_key=state_key)

    def _build_settings_tab(self) -> QWidget:
        """
        設定の画面（メニュー（≡）。設定者だけ）: チュートリアル生成（モデル・検索するナレッジ）/ Local RAG。グループごとに折りたためる。
        URL・APIキー・検索するナレッジ・保存先・動画・ギャラリーは「接続・アカウント」にある（一般ユーザーが自分で入れるもの）。
        """
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        def fill_local(box: QVBoxLayout) -> None:
            box.addWidget(QLabel("Bridge Port:"))
            self._port_edit = QLineEdit(str(self._cfg.get("local_port", 8766)))
            box.addWidget(self._port_edit)
            bridge_note = QLabel("ブリッジのあるフォルダ（Bridge Directory）は、「接続・アカウント」の「保存先フォルダ」と共通です。")
            bridge_note.setWordWrap(True)
            bridge_note.setStyleSheet("color:#888;")
            box.addWidget(bridge_note)
            box.addWidget(QLabel("LLM バックエンド:"))
            self._backend_combo = QComboBox()
            self._backend_combo.addItems(["claude", "gemini"])
            self._backend_combo.setCurrentText(self._cfg.get("llm_backend", "claude"))
            box.addWidget(self._backend_combo)
            restart_btn = QPushButton("ブリッジ再起動")
            restart_btn.clicked.connect(self._on_restart_bridge)
            box.addWidget(restart_btn)

        def fill_tutorial(box: QVBoxLayout) -> None:
            # チュートリアル生成モデル（token消費対策）。tutorial_agent.py の AVAILABLE_MODELS が価格テーブルの正なので、
            # それをインポートして選択肢にする（ここで重複定義しない）。見つからない環境（テスト等）は固定リスト。
            box.addWidget(QLabel("チュートリアル生成モデル（コスト影響あり）:"))
            self._tutorial_model_combo = QComboBox()
            try:
                from tutorial_agent import AVAILABLE_MODELS
            except ImportError:
                AVAILABLE_MODELS = ("claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5")
            self._tutorial_model_combo.addItems(list(AVAILABLE_MODELS))
            self._tutorial_model_combo.setCurrentText(self._cfg.get("tutorial_model", "claude-sonnet-5-5"))
            box.addWidget(self._tutorial_model_combo)
            hint = QLabel(
                "claude-sonnet-5: 既定（$2/$10 per 1Mトークン） / "
                "claude-sonnet-5-5: 同価格の後継 / "
                "claude-opus-5-5: 高品質・約2倍のコスト（$4/$20） / "
                "claude-haiku-4-5: 低コスト（$1/$5）だが品質は下がる場合があります"
            )
            hint.setStyleSheet("color:#888;")
            box.addWidget(hint)

            # 検索対象のナレッジ（Houdiniのバージョン別）。「接続・アカウント」の「チャットで検索するナレッジ」とは別設定。
            box.addWidget(QLabel("チュートリアル生成: 検索するナレッジ（空欄=起動中のHoudiniに自動で合わせる）:"))
            self._tutorial_rag_ns_combo = QComboBox()
            self._tutorial_rag_ns_combo.setEditable(True)
            self._tutorial_rag_ns_combo.addItems(["", "houdini22", "houdini21"])
            self._tutorial_rag_ns_combo.setCurrentText(self._cfg.get("tutorial_rag_namespace", ""))
            self._tutorial_rag_ns_combo.setToolTip(
                "空欄: Houdini 22で起動していれば houdini22、21なら houdini21 を検索します。\n"
                "「接続・アカウント」の「チャットで検索するナレッジ」はチャット用で、この設定には影響しません。"
            )
            box.addWidget(self._tutorial_rag_ns_combo)

            box.addWidget(QLabel("スコアユーザーID:"))
            self._score_uid_edit = QLineEdit(self._cfg.get("score_user_id", ""))
            self._score_uid_edit.setPlaceholderText("例: my_user")
            box.addWidget(self._score_uid_edit)

        layout.addWidget(self._group_box("チュートリアル生成", "settings.tutorial", False, fill_tutorial))
        layout.addWidget(self._group_box("Local RAG（開発者向け）", "settings.local", True, fill_local))

        # 注意: チュートリアル生成のClaudeトークン上限は、ここではなく管理画面（APIキー管理）側でAPIキーごとに設定する。
        # クライアント側で上限を自己申告・改ざんできない構成にするため、意図的にここには置いていない。

        save_btn = QPushButton("設定を保存")
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)
        check_btn = QPushButton("接続確認")
        check_btn.clicked.connect(self._on_check_health)
        layout.addWidget(check_btn)

        # 注意書き: ANTHROPIC_API_KEY は .env ではなく OS 環境変数で渡す
        note = QLabel("ANTHROPIC_API_KEY は Houdini 起動前に\nOS 環境変数に設定してください。")
        note.setStyleSheet("color:#f90;")
        layout.addWidget(note)
        layout.addStretch()
        return w

    def _build_debug_tab(self) -> QWidget:
        """
        デバッグタブ（設定者だけ）: 接続の詳細・設定ファイルの場所・記録（ログ）。
        利用者向けの画面には出さない生の情報をここに集める。APIキーなどの秘密は、伏せて表示する。
        """
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)
        layout.addWidget(QLabel("デバッグ情報（設定者向け。APIキーなどの秘密は伏せて表示します）"))

        self._debug_status = QPlainTextEdit()
        self._debug_status.setReadOnly(True)
        self._debug_status.setMinimumHeight(150)
        layout.addWidget(self._debug_status)

        layout.addWidget(QLabel("記録（接続・質問・設定のエラーなど。新しいものが下）"))
        self._debug_log = QPlainTextEdit()
        self._debug_log.setReadOnly(True)
        self._debug_log.setMinimumHeight(150)
        layout.addWidget(self._debug_log, stretch=1)

        row = QHBoxLayout()
        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(self._refresh_debug)
        copy_btn = QPushButton("コピー")
        copy_btn.setToolTip("状態と記録をクリップボードへ（不具合の報告に貼れます。秘密は伏せてあります）")
        copy_btn.clicked.connect(self._copy_debug)
        clear_btn = QPushButton("記録を消す")
        clear_btn.clicked.connect(lambda: (_debug.clear(), self._refresh_debug()))
        for b in (refresh_btn, copy_btn, clear_btn):
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        return w

    def _debug_status_text(self) -> str:
        """デバッグタブの「状態」。秘密（APIキー・トークン）は、設定済みかどうかと末尾だけ。"""
        try:
            import hou as _h
            houdini = _h.applicationVersionString()
        except Exception:
            houdini = "(Houdini の外)"
        health = "未確認" if self._last_health is None else (
            f"{'OK' if self._last_health[1] else 'NG'}（{_debug.time.strftime('%H:%M:%S', _debug.time.localtime(self._last_health[0]))}）"
        )
        info = json.dumps(self._last_user_info, ensure_ascii=False) if self._last_user_info is not None else "未取得"
        import panel_info as _pi
        lines = [
            f"モード: {self._cfg.get('mode')}",
            f"Worker URL: {self._cfg.get('cf_url') or '未設定'}",
            f"APIキー: {_debug.mask_key(self._cfg.get('cf_api_key', ''))}",
            f"ギャラリーのトークン: {_debug.mask_key(self._cfg.get('gallery_token', ''))}",
            f"ユーザー（サーバーの応答）: {info}",
            f"役割（画面の出し分けに使用）: {self._role or '-'}",
            f"最後の接続確認: {health}",
            f"Local ブリッジ: ポート {self._cfg.get('local_port')} / {self._cfg.get('local_bridge_dir') or '未設定'}",
            f"保存先フォルダ: {_paths.resolve_data_dir(self._cfg)['source']}（{self._cfg.get('local_bridge_dir') or '未設定'}）",
            f"設定ファイル: {_CONFIG_PATH}",
            f"画面の状態ファイル: {Path.home() / '.houdini' / 'rag_chatbot_ui.json'}",
            f"パネルのモジュール: {Path(_pi.__file__).parent}",
            f"Houdini: {houdini}",
        ]
        return "\n".join(lines)

    def _refresh_debug(self) -> None:
        self._debug_status.setPlainText(self._debug_status_text())
        self._debug_log.setPlainText(_debug.as_text())
        sb = self._debug_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy_debug(self) -> None:
        self._refresh_debug()
        QApplication.clipboard().setText(_debug.mask_secrets(self._debug_status_text() + "\n\n" + _debug.as_text()))
        self._set_status("デバッグ情報をコピーしました")

    def _on_tab_changed(self, index: int) -> None:
        if index == getattr(self, "_chat_tab_idx", -1):
            self._refresh_hints()  # Guide で進めた手順・選んだノードに合わせて、質問の例を作り直す
        if index == getattr(self, "_pilot_tab_idx", -1):
            self._pilot_panel.refresh()

    def _on_pilot_toggled(self, enabled: bool) -> None:
        """「実証実験に参加する」: 課題タブの表示を切り替えて、覚える。"""
        _ui_state_set("pilot_enabled", bool(enabled))
        self._tabs.setTabVisible(self._pilot_tab_idx, bool(enabled))
        if enabled:
            self._show_main()
            self._tabs.setCurrentIndex(self._pilot_tab_idx)  # 切り替わると _on_tab_changed が、課題を読み込む

    # ── メニュー（≡）（ふだん使わない画面）・別ウィンドウ ────────────────────────────

    def _is_setup(self) -> bool:
        return _is_setup_user(self._role, self._cfg.get("mode", "cloudflare"))

    def _build_gear_button(self) -> QToolButton:
        """右上のメニュー（≡）。履歴・接続・設定・デバッグの画面と、「別ウィンドウで開く」をまとめたメニュー。"""
        menu = QMenu(self)
        self._sub_actions = {}
        for key, label, _title, _setup_only in _nav.SUB_PAGES:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, k=key: self._show_sub(k))
            self._sub_actions[key] = action
        menu.addSeparator()
        # 文字の大きさ（実証実験の A24「文字が小さい」）。だれでも変えられる。パネルを開き直すと反映
        sizes = menu.addMenu("文字の大きさ")
        current = _text_scale()
        self._text_scale_actions = []
        for value, label in _TEXT_SCALES:
            act = sizes.addAction(f"{label}（{int(round(value * 100))}%）")
            act.setCheckable(True)
            act.setChecked(abs(value - current) < 0.01)
            act.triggered.connect(lambda checked=False, v=value, l=label: self._on_text_scale(v, l))
            self._text_scale_actions.append((value, act))
        menu.addAction("このパネルを別ウィンドウで開く（並べて見る）").triggered.connect(self._on_open_new_window)
        menu.addAction("並べて見る方法").triggered.connect(self._show_parallel_help)
        menu.addAction("キー 1 つで、浮かぶパネルを出し入れする（設定）").triggered.connect(self._show_float_hotkey_help)
        jump = menu.addAction("ほかのパネルがあるとき、そちらで開く（Guide ⇄ Reference）")
        jump.setCheckable(True)
        jump.setChecked(_bus.enabled())
        jump.setToolTip("オン: 別のパネルが見えているとき、Guide の「ノードの説明」は、そちらの Reference で開きます（逆も同じ）。オフ: いつも、このパネルの中で切り替えます")
        jump.toggled.connect(_bus.set_enabled)
        self._gear_menu = menu
        button = _action_button("menu", "メニュー（履歴・接続・設定・別ウィンドウで開く）")
        button.setMenu(menu)
        button.setPopupMode(QToolButton.InstantPopup)
        button.setStyleSheet("QToolButton::menu-indicator{image:none;}")
        return button

    def _on_text_scale(self, value: float, label: str) -> None:
        _set_text_scale(value)
        for choice, act in getattr(self, "_text_scale_actions", []):
            act.setChecked(abs(choice - value) < 0.01)
        self._set_status(f"文字の大きさを「{label}」にしました。パネルを開き直す（ペインタブを閉じて、もう一度開く）と反映します")

    def _build_sub_view(self) -> QWidget:
        """メニュー（≡）の中の画面を出す場所。上に「戻る」と見出し。"""
        view = _FixedHintTab()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        back = QPushButton("← タブに戻る")
        back.setToolTip("Chat / Guide / Tutorial などのタブの画面に戻ります")
        back.clicked.connect(self._show_main)
        self._sub_title = QLabel("")
        self._sub_title.setStyleSheet("color:#e2e8f0;font-weight:bold;")
        header.addWidget(back)
        header.addWidget(self._sub_title, stretch=1)
        layout.addLayout(header)
        self._sub_stack = QStackedWidget()
        for wrapper in self._sub_wrappers.values():
            self._sub_stack.addWidget(wrapper)
        layout.addWidget(self._sub_stack, stretch=1)
        return view

    def _show_sub(self, key: str) -> None:
        """メニュー（≡）の中の画面を開く。設定・デバッグは、設定者だけ。"""
        wrapper = self._sub_wrappers.get(key)
        if wrapper is None or key not in _nav.visible_sub_pages(self._is_setup()):
            return
        self._sub_stack.setCurrentWidget(wrapper)
        self._sub_title.setText(_nav.sub_page_title(key))
        self._main_stack.setCurrentIndex(1)
        self._current_sub = key
        if key == "debug":
            self._refresh_debug()

    def _show_main(self) -> None:
        """タブの画面に戻る。"""
        self._main_stack.setCurrentIndex(0)
        self._current_sub = ""

    def _on_open_new_window(self) -> None:
        """パネルをもう 1 つ、別ウィンドウで開く（別のタブを並べて見るため）。開けなければ、手動の方法を案内する。"""
        ok, reason = _nav.open_in_new_window()
        if ok:
            self._set_status("別ウィンドウでパネルを開きました")
            return
        _debug.log("画面", f"別ウィンドウで開けませんでした: {reason}")
        QMessageBox.information(self, "別ウィンドウで開けませんでした", f"（{reason}）\n\n" + _nav.PARALLEL_VIEW_HELP)

    def _setup_float_hotkey(self) -> None:
        """シェルフツール「RAGReel Tutorial」に、キーを割り当てる（最初の 1 回。割り当てられた・すでにあるとき、印を残す）。"""
        try:
            state, detail = _nav.ensure_float_hotkey(done=bool(_ui_state_get("float_hotkey_done", False)))
        except Exception as exc:  # noqa: BLE001
            state, detail = "failed", str(exc)
        if state in ("assigned", "exists"):
            _ui_state_set("float_hotkey_done", True)
        if state != "skipped":
            _debug.log("画面", f"浮かぶパネルのキー: {state} {detail}")

    def _show_float_hotkey_help(self) -> None:
        QMessageBox.information(self, "キー 1 つで、浮かぶパネルを出し入れする", _nav.FLOAT_HOTKEY_HELP)

    def _show_parallel_help(self) -> None:
        QMessageBox.information(self, "並べて見る方法", _nav.PARALLEL_VIEW_HELP)

    def _refresh_data_dir_note(self) -> None:
        """接続・アカウントの「保存先フォルダ」の下に、いま使っている場所と、その決まり方を出す。"""
        result = _paths.resolve_data_dir(self._cfg)
        if result["source"] == "config":
            auto = _paths.default_data_dir()
            same = str(Path(result["path"])).lower() == str(auto).lower()
            text = f"いまの保存先: {result['path']}" + ("（既定の場所）" if same else "")
        elif result["source"] == "default":
            text = f"いまの保存先: {result['path']}（空欄のため、自動で決めました）"
        else:
            text = result["error"] or _paths.STORAGE_HELP
            if self._cfg.get("mode") != "local":
                text = f"{_paths.STORAGE_HELP}（{text}）"
        self._data_dir_note.setText(text)

    def _on_open_data_dir(self) -> None:
        """保存先のフォルダを、エクスプローラーで開く。"""
        path = (self._bridge_dir_edit.text().strip() or self._cfg.get("local_bridge_dir", "")).strip()
        if not path or not Path(path).is_dir():
            self._set_status("保存先のフォルダがまだありません（チュートリアルを保存すると作られます）")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _apply_role_visibility(self) -> None:
        """設定者（admin / editor、または Local モード）にだけ、メニュー（≡）の設定・デバッグと、モード切り替えを出す。"""
        visible = set(_nav.visible_sub_pages(self._is_setup()))
        for key, action in getattr(self, "_sub_actions", {}).items():
            action.setVisible(key in visible)
        if self._current_sub and self._current_sub not in visible:
            self._show_main()
        box = getattr(self, "_mode_box", None)
        if box is not None:
            box.setVisible(self._is_setup())
        panel = getattr(self, "_tutorial_panel", None)
        if panel is not None and hasattr(panel, "set_developer_view"):
            panel.set_developer_view(self._is_setup())  # 進行ログは設定者だけ（A5）

    # ── イベント ───────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """Ctrl+Enter で _on_send() を呼ぶ。それ以外は通常のイベント処理に委譲する。"""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        if obj is self._input and event.type() == QEvent.FocusIn:
            self._refresh_hints()  # 入力欄を押したとき（ノードを選び直したあと など）、質問の例を作り直す
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
        _paths.apply_default_data_dir(self._cfg)  # Cloudflare に戻したとき、保存先が空なら、既定の場所を使う
        self._refresh_data_dir_note()
        self._client = RAGClient(self._cfg)
        if mode == "local":
            self._ensure_bridge()
        # 画面添付（VLM入力）はCloudflare専用。Localに切り替えたら
        # チェックが入っていても解除し、無効な状態のまま残らないようにする。
        self._attach_viewport_checkbox.setEnabled(mode == "cloudflare")
        self._explain_combo.setEnabled(mode == "cloudflare")
        if mode != "cloudflare":
            self._attach_viewport_checkbox.setChecked(False)
        self._apply_role_visibility()
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
        mode_label = "Cloudflare" if self._cfg.get("mode") == "cloudflare" else "Local"
        self._conn_lamp.set_state("checking", mode_label)
        self._conn_worker = _ConnectionCheckWorker(self._client)
        self._conn_worker.result.connect(self._on_conn_result)
        self._conn_worker.user_info.connect(self._apply_user_label)
        self._conn_worker.growth_info.connect(self._apply_growth)
        self._conn_worker.start()

    def _apply_growth(self, info: dict) -> None:
        """接続タブの「習熟度」を更新する。Local モードや、古い Worker では、説明を出す。"""
        text = _format_growth(info)
        if not text:
            text = ("Local モードでは、習熟度は使いません。" if self._cfg.get("mode") == "local"
                    else "習熟度を取得できません（接続を確認してください）。")
        self._conn_growth.setText(text)
        self._last_growth = info

    def _on_explain_changed(self, _index: int) -> None:
        self._cfg["explain_level"] = self._explain_combo.currentData()
        _save_config(self._cfg)

    def _on_answer_mode_changed(self, _index: int) -> None:
        self._cfg["answer_mode"] = _normalize_answer_mode(self._answer_combo.currentData())
        _save_config(self._cfg)

    def _on_reset_growth(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            self, "習熟度の記録を消す",
            "質問に使った専門用語の記録をすべて消します。説明は basic から始まります。よろしいですか？",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            ok = self._client.growth_reset()
        except Exception as exc:
            _debug.log("設定", f"習熟度の記録を消せませんでした: {exc}")
            self._set_status(_friendly_error(str(exc)))
            return
        self._set_status("習熟度の記録を消しました" if ok else "習熟度の記録を消せませんでした")
        self._check_connection_async()

    def _on_conn_result(self, ok: bool) -> None:
        mode_label = "Cloudflare" if self._cfg.get("mode") == "cloudflare" else "Local"
        self._conn_lamp.set_state("ok" if ok else "fail", mode_label)
        previous = self._last_health[1] if self._last_health else None
        self._last_health = (_debug.time.time(), ok)
        if ok != previous:  # 変わったときだけ記録する（20秒ごとの確認で、記録が埋まらないように）
            _debug.log("接続", f"{mode_label} への接続: {'OK' if ok else 'NG'}（URL: {self._cfg.get('cf_url') or '-'}）")

    def _apply_user_label(self, info: dict | None) -> None:
        """「ユーザー: 名前（役割）」の表示を更新する。info=None は未確認、{} は Local モード。"""
        mode = self._cfg.get("mode", "cloudflare")
        shown = _format_user(info if info else None, mode)
        self._user_label.setText(shown["text"])
        self._user_label.setToolTip(shown["tooltip"])
        self._conn_user_info.setText(shown["text"] + chr(10) + shown["tooltip"])
        if info is not None:
            self._last_user_info = info
        if info and info.get("role"):
            self._role = str(info["role"])
            _ui_state_set("last_role", self._role)  # オフラインのときも、設定者の画面を出し続けるため
        elif info and info.get("error"):
            self._role = ""
            _ui_state_set("last_role", "")
            _debug.log("接続", f"ユーザーを確認できません: {info['error']}")
        self._apply_role_visibility()

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
            # QTabWidgetに実際に登録されているのは_wrap_tab()が返したラッパー
            # であって_tutorial_panelそのものではないため、切り替え先は
            # self._tutorial_tab_wrapperを指定する。
            self._show_main()
            self._tabs.setCurrentWidget(self._tutorial_tab_wrapper)
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
        self._last_query = query
        self._add_bubble(query, is_user=True)
        self._history.append({"role": "user", "text": query})
        self._set_status("応答中...")
        self._send_btn.setEnabled(False)
        self._show_thinking()

        # 直近 12 件の履歴を Worker に渡す（古すぎる会話は LLM に送らない）
        explain = self._explain_combo.currentData() if self._cfg.get("mode") == "cloudflare" else None
        answer_mode = _normalize_answer_mode(self._answer_combo.currentData())
        # Cloudflare では、出典を先に出し、回答を届いた分ずつ出す（/query/stream。待ち時間の体感を短くする。A3）
        stream = self._cfg.get("mode") == "cloudflare" and self._cfg.get("chat_stream", True)
        self._worker = QueryWorker(self._client, query, self._history[-12:], image_b64=image_b64, explain=explain,
                                   answer_mode=answer_mode, stream=stream)
        self._worker.finished.connect(self._on_query_done)
        self._worker.error.connect(self._on_query_error)
        self._worker.sources_ready.connect(self._on_early_sources)
        self._worker.delta.connect(self._on_answer_delta)
        self._worker.start()

    # ── 待っている間の表示（先に見つかった資料・届いた分の回答）と、質問の例（A3） ──────────────

    def _insert_chat_widget(self, widget: QWidget, before: QWidget | None = None) -> None:
        """チャットの末尾（before があれば、その手前）に足す。"""
        index = self._chat_layout.indexOf(before) if before is not None else -1
        self._chat_layout.insertWidget(index if index >= 0 else max(0, self._chat_layout.count() - 1), widget)

    def _on_early_sources(self, sources: list) -> None:
        """検索で見つかった資料を、回答より先に出す（回答が届いたら、回答の下の「出典」に置き換わる）。"""
        try:
            names = []
            for s in sources or []:
                name = str((s or {}).get("file") or (s or {}).get("title") or "").strip()
                if name and name not in names:
                    names.append(name)
            if not names:
                return
            self._clear_stream_widgets(early=True, bubble=False)
            shown = names[:5]
            rest = f"<br>ほか {len(names) - len(shown)} 件" if len(names) > len(shown) else ""
            label = QLabel(
                "<b>先に見つかった資料</b>（回答を作っています。先に開いて読めます）<br>"
                + "<br>".join(f"• {html.escape(n)}" for n in shown) + rest
            )
            label.setTextFormat(Qt.RichText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setStyleSheet("color:#cbd5e1;font-size:11px;padding:4px 8px;background:#1e293b;border-radius:6px;")
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
            self._early_sources = label
            self._insert_chat_widget(label, before=getattr(self, "_thinking_row", None))
            QTimer.singleShot(0, self._scroll_to_bottom)
        except Exception as exc:  # noqa: BLE001 -- 先出しが出せなくても、回答は待つ
            _debug.log("質問", f"先に見つかった資料を出せませんでした: {exc}")

    def _on_answer_delta(self, text: str) -> None:
        """回答の本文を、届いた分ずつ出す（完成したら、リンク・図・出典の付いた、ふつうの回答に置き換える）。"""
        try:
            if not text:
                return
            bubble = getattr(self, "_stream_bubble", None)
            if bubble is None:
                self._hide_thinking()
                self._stream_text = ""
                bubble = ChatBubble("", is_user=False)
                self._stream_bubble = bubble
                self._insert_chat_widget(bubble)
            self._stream_text += text
            bubble.setText(self._stream_text)
            QTimer.singleShot(0, self._scroll_to_bottom)
        except Exception as exc:  # noqa: BLE001 -- 途中の表示ができなくても、完成した回答は出す
            _debug.log("質問", f"届いた分の回答を出せませんでした: {exc}")

    def _clear_stream_widgets(self, early: bool = True, bubble: bool = True) -> None:
        names = (["_early_sources"] if early else []) + (["_stream_bubble"] if bubble else [])
        for name in names:
            widget = getattr(self, name, None)
            if widget is not None:
                self._chat_layout.removeWidget(widget)
                widget.deleteLater()
                setattr(self, name, None)

    def _hint_context(self) -> tuple[dict | None, list[dict], list[dict]]:
        """質問の例の材料（Guide の手順・選んでいるノード・エラーの出ているノード）。Houdini の外では、空。"""
        guide = None
        widget = getattr(self, "_guide_widget", None)
        if widget is not None and hasattr(widget, "step_brief"):
            try:
                guide = widget.step_brief()
            except Exception:  # noqa: BLE001 -- 手順が読めなくても、ほかの例は出す
                guide = None
        selected: list[dict] = []
        errors: list[dict] = []
        try:
            import hou

            def brief(node) -> dict:
                return {"label": node.type().description(), "type": node.type().name(), "name": node.path()}

            picked = list(hou.selectedNodes() or [])[:3]
            selected = [brief(node) for node in picked]
            here: list = []
            try:
                editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)  # いま見ているネットワークの中だけ（シーン全体は見ない。重くなるため）
                here = list(editor.pwd().children())[:200] if editor is not None else []
            except Exception:  # noqa: BLE001 -- 画面が無い（hython など）
                here = []
            for node in picked + here:  # 選んでいるノードを先に。エラーの例は 1 つだけ出す
                try:
                    if node.errors():
                        errors.append(brief(node))
                        break
                except Exception:  # noqa: BLE001 -- エラーの読めないノードは飛ばす
                    continue
        except Exception:  # noqa: BLE001 -- Houdini の外（テスト）では、空
            pass
        return guide, selected, errors

    def _refresh_hints(self) -> None:
        """質問の例を作り直す（Chat タブを開いたとき・入力欄を押したとき・回答のあと）。"""
        layout = getattr(self, "_hints_layout", None)
        if layout is None or not self._cfg.get("chat_hints", True):
            if getattr(self, "_hints_box", None) is not None:
                self._hints_box.hide()
            return
        try:
            hints = _question_hints.suggest(*self._hint_context())
        except Exception as exc:  # noqa: BLE001 -- 例が作れなくても、チャットは使える
            _debug.log("質問", f"質問の例を作れませんでした: {exc}")
            hints = []
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if not hints:
            self._hints_box.hide()
            return
        caption = QLabel("質問の例:")
        caption.setStyleSheet(_type_qss("caption", "#94a3b8"))
        layout.addWidget(caption)
        for hint in hints:
            button = QPushButton(hint["label"])
            button.setToolTip("押すと、この質問を送ります:\n" + hint["query"])
            button.setStyleSheet("QPushButton{font-size:11px;padding:2px 8px;border:1px solid #475569;border-radius:10px;}"
                                 "QPushButton:hover{background:#334155;}")
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked=False, q=hint["query"]: self._send_hint(q))
            layout.addWidget(button, 1)
        self._hints_box.show()

    def ask_chat(self, query: str) -> str:
        """ほかのタブ（Guide の「この手順を Chat に聞く」など）から、Chat タブに切り替えて、質問を送る。画面に出す短い結果を返す。"""
        if self._worker and self._worker.isRunning():
            return "Chat が回答を作っています。届いてから、もう一度押してください"
        self._show_main()
        idx = getattr(self, "_chat_tab_idx", -1)
        if idx >= 0:
            self._tabs.setCurrentIndex(idx)
        self._input.setPlainText(query)
        self._on_send()
        return "Chat タブで質問しました（回答は Chat タブに出ます）"

    def _send_hint(self, query: str) -> None:
        if self._worker and self._worker.isRunning():
            self._set_status("回答を待っています。届いてから、もう一度押してください")
            return
        self._input.setPlainText(query)
        self._on_send()

    def _show_thinking(self) -> None:
        """回答を待っているあいだの「関連情報を確認中… ●○○」を、チャットの末尾に出す（panel_thinking.py）。"""
        self._hide_thinking()
        row = _ThinkingRow()
        self._thinking_row = row
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, row)  # 末尾の stretch の手前
        row.start()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _hide_thinking(self) -> None:
        row = getattr(self, "_thinking_row", None)
        if row is not None:
            row.stop()
            self._chat_layout.removeWidget(row)
            row.deleteLater()
            self._thinking_row = None

    def _restore_after_query_error(self, exc: BaseException) -> None:
        """回答の処理の途中で例外が出たとき、送信ボタンを使える状態に戻す（無効のまま残ると、質問できなくなる。2026-11-24）。"""
        try:
            self._hide_thinking()
            self._clear_stream_widgets()
        except Exception:  # noqa: BLE001 -- 表示の片づけに失敗しても、ボタンは戻す
            pass
        self._send_btn.setEnabled(True)
        self._set_status(f"回答の表示でエラーが出ました（内容は、メニュー ≡ →「デバッグ」）: {type(exc).__name__}")

    @_debug.guard("質問", restore="_restore_after_query_error")
    def _on_query_done(self, result: dict) -> None:
        """クエリ成功時のコールバック。回答バブルを追加し参照ドキュメントをステータスに表示する。"""
        self._hide_thinking()
        self._clear_stream_widgets()
        answer    = result.get("answer", "(空の回答)")
        sources   = result.get("sources", [])
        memory_id = result.get("memoryId", "")
        self._add_rag_bubble(answer, memory_id, sources, result.get("explain"))
        self._history.append({"role": "assistant", "text": answer})
        # 出典と採用比率は、回答の下の折りたたみに出す。下部のステータスには、短い要約だけ。
        self._set_status(_summarize_sources(sources, answer)["summary"])
        self._send_btn.setEnabled(True)
        self._scroll_to_bottom()
        self._refresh_hints()
        # 理解度スコアを自動更新
        uid = self._cfg.get("score_user_id", "")
        if self._cfg["mode"] == "local" and uid:
            threading.Thread(target=self._post_score, args=(uid, True), daemon=True).start()

    @_debug.guard("質問", restore="_restore_after_query_error")
    def _on_query_error(self, msg: str) -> None:
        """クエリ失敗時のコールバック。エラーをバブルとステータスに表示する。"""
        self._hide_thinking()
        self._clear_stream_widgets()
        _debug.log("質問", f"エラー: {msg}")
        friendly = _friendly_error(msg)
        hint = "（詳細は、メニュー（≡）の「デバッグ」）" if _is_setup_user(self._role, self._cfg.get("mode", "cloudflare")) else ""
        self._add_bubble(f"エラー: {friendly}{hint}", is_user=False)
        self._set_status(friendly)
        self._send_btn.setEnabled(True)
        # 理解度スコアをエラーとして更新
        uid = self._cfg.get("score_user_id", "")
        if self._cfg["mode"] == "local" and uid:
            threading.Thread(target=self._post_score, args=(uid, False), daemon=True).start()

    def _on_clear(self) -> None:
        """会話履歴とバブルをすべて削除してチャットをリセットする。"""
        self._history.clear()
        self._hide_thinking()
        self._early_sources = None  # 下の一括削除で消える
        self._stream_bubble = None
        # stretch（最後の要素）以外のすべてのバブルを削除する
        for i in reversed(range(self._chat_layout.count() - 1)):
            item = self._chat_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._set_status("")

    def _on_save_settings(self) -> None:
        """「接続・アカウント」「設定」の入力値を _cfg に反映してファイルに保存し、クライアントを再生成する。"""
        self._cfg["cf_url"]           = self._cf_url_edit.text().strip()
        self._cfg["cf_api_key"]       = self._cf_api_key_edit.text().strip()
        self._cfg["cf_namespaces"]    = self._cf_ns_edit.text().strip()
        dir_text = self._bridge_dir_edit.text().strip()
        dir_edited = dir_text != str(self._cfg.get("local_bridge_dir") or "").strip()  # 触っていなければ、インストーラーの値を守る
        self._cfg["local_bridge_dir"] = dir_text
        self._cfg["llm_backend"]      = self._backend_combo.currentText()
        self._cfg["tutorial_model"]   = self._tutorial_model_combo.currentText()
        self._cfg["tutorial_rag_namespace"] = self._tutorial_rag_ns_combo.currentText().strip()
        self._cfg["gallery_url"]      = self._gallery_url_edit.text().strip()
        self._cfg["gallery_token"]    = self._gallery_token_edit.text().strip()
        self._cfg["gallery_auto_upload"] = self._gallery_auto_checkbox.isChecked()
        self._cfg["score_user_id"]    = self._score_uid_edit.text().strip()
        self._cfg["video_factory_exe_path"] = self._video_factory_exe_edit.text().strip()
        self._cfg["video_length"] = str(self._video_length_combo.currentData() or "full")
        try:
            self._cfg["local_port"] = int(self._port_edit.text())
        except ValueError:
            pass  # 不正なポート値は無視して既存値を維持
        if dir_edited:
            _save_config(self._cfg, dir_edited=True)
        else:
            _save_config(self._cfg)
        _paths.apply_default_data_dir(self._cfg)  # 空欄で保存したときは、既定の場所を使う（ファイルには、空のまま残る）
        if not _paths.is_blank(self._cfg.get("local_bridge_dir")):
            self._bridge_dir_edit.setText(self._cfg["local_bridge_dir"])  # 保存先を、いま使っている値にそろえる
        self._refresh_data_dir_note()
        self._client = RAGClient(self._cfg)
        # バックエンド変更をブリッジに通知
        if self._cfg["mode"] == "local":
            threading.Thread(target=self._push_backend, daemon=True).start()
        self._set_status("設定を保存しました")
        _debug.log("設定", "設定を保存しました")
        self._check_connection_async()

    def _on_check_health(self) -> None:
        """接続確認ボタン。health() の結果をステータスとタブバーのランプ両方に反映する。"""
        ok = self._client.health()
        self._set_status("接続OK" if ok else "接続失敗 — ブリッジが起動しているか確認してください")
        mode_label = "Cloudflare" if self._cfg.get("mode") == "cloudflare" else "Local"
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

    def _add_rag_bubble(self, text: str, memory_id, sources: list | None = None, explain: dict | None = None) -> None:
        """
        RAG 回答専用バブル。テキストの下に 👍/👎 ボタンを追加する。
        memory_id が空（None・""）の場合（Local モードなど）はボタンを表示しない。
        Cloudflare の memoryId は数値（0 以外）。
        """
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 4)
        v.setSpacing(2)

        # テキストバブル行
        bubble_row = QHBoxLayout()
        answer_bubble = ChatBubble(text, is_user=False, rich_links=True)  # 回答の中の URL は、リンクにする
        answer_bubble.setToolTip("語をダブルクリックすると、Reference で探します")
        if _REFERENCE_AVAILABLE:
            try:
                _TermLookup.install(answer_bubble, self._set_status)  # 用語をダブルクリックで調べる（A20）
            except Exception as exc:  # noqa: BLE001
                _debug.log("用語", f"ダブルクリックの検索を付けられませんでした: {exc}")
        bubble_row.addWidget(answer_bubble)
        bubble_row.addStretch()
        v.addLayout(bubble_row)

        # 回答にノードの名前（Pyro Solver など）が出てくるときは、SideFX の公式ドキュメントへのリンクを、回答の下に出す
        # （公式の一覧にあるページだけ。無い名前は、公式サイトの検索のリンク。node_links.py）
        try:
            node_row = _node_links.node_links_html(_node_links.find_node_links(text))
        except Exception as exc:  # noqa: BLE001 -- リンクが作れなくても、回答は出す
            _debug.log("リンク", f"ノードのリンクを作れませんでした: {exc}")
            node_row = ""
        if node_row:
            node_label = QLabel(node_row)
            node_label.setWordWrap(True)
            node_label.setStyleSheet("color:#cbd5e1;font-size:11px;padding:2px 6px;")
            node_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
            make_links_clickable(node_label)
            v.addWidget(node_label)

        # 回答に出てくるノード・VEX 関数・シェルフツールのうち、Reference に撮影した画像があるものを、絵で添える（2026-11-25。実証実験の意見）。
        # 図は AI に作らせない（誤りが、そのまま図になる）。画像は、別スレッドで取り、届いたら出す（無ければ、何も出ない）
        if _REFERENCE_AVAILABLE and self._cfg.get("chat_figures", True):
            try:
                strip = _ChatFigureStrip(self._cfg, text)
                strip.message.connect(self._set_status)
                v.addWidget(strip)
            except Exception as exc:  # noqa: BLE001 -- 絵が出せなくても、回答は出す
                _debug.log("図", f"回答の絵を出せませんでした: {exc}")

        # 説明レベルと、今回の回答で紹介した用語（explain を付けた質問だけ）
        explain_text = _format_explain(explain)
        if explain_text:
            tag = QLabel()
            tag.setTextFormat(Qt.PlainText)  # サーバーの返した用語は、書式として解釈しない
            tag.setText(explain_text)
            tag.setStyleSheet("color:#94a3b8;font-size:11px;padding:0 6px;")
            tag.setWordWrap(True)
            tag.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
            v.addWidget(tag)

        # 推測を含む回答（答え方が「資料＋推測」のとき）。資料に書かれたことと、推測を、見分けられるようにする。
        if _has_guess(text):
            guess_tag = QLabel("「（推測）」の部分は、資料に書かれていない見立てです。確かさと確かめ方を参考に、Reference・公式ドキュメントで確認してください。")
            guess_tag.setStyleSheet("color:#a5b4fc;font-size:11px;padding:0 6px;")
            guess_tag.setWordWrap(True)
            guess_tag.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
            v.addWidget(guess_tag)

        # 出典と採用比率（回答で使った資料／検索で見つかった資料）。見出しに要約、中身は折りたたみ。
        # 出典の番号による引用が無いときは、警告として最初から開いておく。
        info = _summarize_sources(sources or [], text)
        body_box = None
        if info["state"] != "empty":
            body = QLabel(info["html"])
            body.setTextFormat(Qt.RichText)
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.setStyleSheet("color:#cbd5e1;font-size:11px;padding:2px 6px;")
            body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)  # 長いファイル名で、ペインを広げない
            body_box = _CollapsibleBox(info["summary"], body, collapsed=info["state"] != "none")
            v.addWidget(body_box)

        # 操作の行。アイコン 1 つ = 操作 1 つ(Web のチャット画面と同じ並び)。名前はツールチップに出す。
        v.addLayout(self._build_answer_actions(text, memory_id, sources or [], body_box))

        _normalize_fonts(container)
        insert_at = max(0, self._chat_layout.count() - 1)
        self._chat_layout.insertWidget(insert_at, container)

    def _build_answer_actions(self, answer: str, memory_id, sources: list, sources_box) -> QHBoxLayout:
        """
        回答の下の操作行: コピー・いいね・悪いね・共有・読み上げ・再試行・ブックマーク・参照元。
        評価・共有・ブックマークは、回答の記録(memoryId)があるときだけ(Cloudflare モード)。
        """
        question = self._last_query
        row = QHBoxLayout()
        row.setSpacing(2)

        def toast(text: str) -> None:
            self._set_status(text)

        def on_copy(checked=False, a=answer, q=question, s=sources):
            mods = QApplication.keyboardModifiers()
            text = _answer_markdown(q, a, s) if mods & Qt.ShiftModifier else a
            QApplication.clipboard().setText(text)
            toast("出典つきの Markdown をコピーしました" if mods & Qt.ShiftModifier else "回答をコピーしました")

        row.addWidget(_action_button("copy", "回答をコピー(Shift を押しながらで、出典つきの Markdown)", on_copy))

        if memory_id:
            up = _action_button("thumbUp", "役に立った", checkable=True)
            down = _action_button("thumbDown", "役に立たなかった", checkable=True)

            def on_rate(rating: str, mine, other, mid=memory_id):
                # 評価は 1 回だけ送る(送ったあとは、2 つとも押せなくする。以前の動作のまま)
                mine.setChecked(True)
                mine.setEnabled(False)
                other.setEnabled(False)
                self._on_rate(mid, rating)

            up.clicked.connect(lambda checked=False: on_rate("up", up, down))
            down.clicked.connect(lambda checked=False: on_rate("down", down, up))
            row.addWidget(up)
            row.addWidget(down)

            def on_share(checked=False, mid=memory_id):
                base = _cf_base_url(self._cfg)
                link = (base + "/#answer=" + str(mid)) if base else ""
                if not link:
                    toast("共有リンクを作れません(接続先が未設定です)")
                    return
                QApplication.clipboard().setText(link)
                toast("回答へのリンクをコピーしました(開けるのは、あなた自身=同じ APIキー だけです)")

            row.addWidget(_action_button("share", "回答へのリンクをコピー(開けるのは、あなた自身=同じ APIキー だけです)", on_share))

        if self._speaker.available:
            speak = _action_button("speaker", "回答を読み上げる(もう一度押すと止まる)", checkable=True)

            def on_speak(checked=False, a=answer, b=speak):
                b.setChecked(self._speaker.toggle(a))

            speak.clicked.connect(on_speak)
            row.addWidget(speak)

        def on_retry(checked=False, q=question):
            if not q or (self._worker and self._worker.isRunning()):
                toast("回答をつくっている途中です" if q else "再試行できる質問がありません")
                return
            self._input.setPlainText(q)
            self._on_send()

        row.addWidget(_action_button("refresh", "同じ質問で、回答をもう一度つくる", on_retry))

        if memory_id:
            mark = _action_button("bookmark", "お気に入りに登録(もう一度押すと外す)", checkable=True)

            def on_mark(checked=False, mid=memory_id, b=mark):
                want = b.isChecked()
                if self._client.pin(mid, want):
                    toast("お気に入りに登録しました" if want else "お気に入りから外しました")
                else:
                    b.blockSignals(True)
                    b.setChecked(not want)
                    _action_set_active(b, not want)
                    b.blockSignals(False)
                    toast("お気に入りの登録に失敗しました")

            mark.clicked.connect(on_mark)
            row.addWidget(mark)

        if sources_box is not None:
            def on_sources(checked=False, box=sources_box):
                box.set_collapsed(False)
                self._scroll_to_bottom()

            row.addWidget(_action_button("docSearch", "参照した情報源と根拠を開く", on_sources))

        row.addStretch()
        return row

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
        """下部ステータスラベルのテキストを更新する。長い文は省略し、全文はツールチップに出す。"""
        self._status.setText(elide_text(text))
        self._status.setToolTip(text if len(text) > _STATUS_MAX_CHARS else "")


# ─── Houdini エントリポイント ─────────────────────────────────────────────────

def onCreateInterface():
    """
    Houdini Python Panel のエントリポイント。
    Python Panel Editor の "Entry Point" フィールドにこの関数名を設定する。
    パネルが開かれるたびに呼ばれ、返したウィジェットがパネルに表示される。
    """
    panel = RAGChatbotPanel()
    return panel
