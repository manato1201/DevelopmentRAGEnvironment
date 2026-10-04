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
import math
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QThread, Qt, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGraphicsItem,
    QGraphicsPathItem,
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

import token_usage
from tutorial_graph_simplify import graph_to_mermaid, layered_positions, simplify_graph

# ノード数がこれを超えるチュートリアルを開いたときは既定で「簡易表示」にする
# （197ノード級の生成物をそのまま全表示すると判読不能になるため）。
_SIMPLIFY_THRESHOLD = 30

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

    def __init__(self, agent, topic: str, level: str = "basic") -> None:
        super().__init__()
        self._agent = agent
        self._topic = topic
        self._level = level

    def run(self) -> None:
        try:
            result = self._agent.generate(self._topic, level=self._level)
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class TutorialChainWorker(QThread):
    """
    tutorial_agent.build_level_chain() を別スレッドで実行するワーカー。
    basic→applied→advanced を逐次生成する（IMPROVEMENT_PLAN.md Phase1）ため
    TutorialWorker より実行時間が長くなる（単発生成の最大3倍）。
    """
    progress = Signal(str)
    done     = Signal(object)  # list[tuple[TutorialAgent, TutorialResult]]
    failed   = Signal(str)

    def __init__(self, topic: str, chain_kwargs: dict) -> None:
        super().__init__()
        self._topic = topic
        self._chain_kwargs = chain_kwargs

    def run(self) -> None:
        try:
            from tutorial_agent import build_level_chain

            results = build_level_chain(
                self._topic, progress_cb=self.progress.emit, **self._chain_kwargs
            )
            self.done.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class _DestroySandboxWorker(QThread):
    """
    サンドボックス削除を別スレッドで行うワーカー。

    HoudiniToolExecutor.destroy_sandbox() は内部で hdefereval.executeInMainThreadWithResult()
    を使ってメインスレッドにディスパッチする。この呼び出し自体がすでにメインスレッド
    （UIのボタンクリックハンドラ）から行われると、メインスレッドが自分自身への
    ディスパッチ完了を待ってブロックし、Qtのイベントループが回らなくなって
    デッドロック（Houdiniのフリーズ）を起こす。「サンドボックス削除」を押すと
    Houdiniが固まる、という実機で確認された不具合の原因はこれで、対策として
    削除処理を必ずバックグラウンドスレッドから呼ぶようにする。

    agents は複数渡せる（3段階連続生成モードでは basic/applied/advanced 分の
    3サンドボックスをまとめて削除する）。1件でも失敗すればエラーメッセージを
    連結して failed で報告するが、成功した分の削除は取り消さない（部分的成功を
    許容する — 全部やり直すよりまし）。
    """
    done   = Signal()
    failed = Signal(str)

    def __init__(self, agents: list) -> None:
        super().__init__()
        self._agents = agents

    def run(self) -> None:
        errors: list[str] = []
        for agent in self._agents:
            try:
                agent.destroy_sandbox()
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            self.failed.emit("; ".join(errors))
        else:
            self.done.emit()


class _ImageIndexWorker(QThread):
    """
    保存したチュートリアルのステップスクリーンショットを、ローカルRAGブリッジの
    /index-images（CLIP画像埋め込み、IMPROVEMENT_PLAN.md Phase2）へ登録する。
    ベストエフォート: 失敗してもチュートリアル保存そのものには一切影響させない
    （結果はステータス表示にだけ反映する）。初回はCLIPモデルのロードが発生する
    ため、数十秒かかることがある。
    """
    done = Signal(str)  # ステータステキスト

    def __init__(self, port: int, namespace: str, image_paths: list[str], metadata_by_path: dict) -> None:
        super().__init__()
        self._port = port
        self._namespace = namespace
        self._image_paths = image_paths
        self._metadata_by_path = metadata_by_path

    def run(self) -> None:
        try:
            body = json.dumps({
                "namespace": self._namespace,
                "image_paths": self._image_paths,
                "metadata": self._metadata_by_path,
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"http://localhost:{self._port}/index-images",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            if data.get("success"):
                self.done.emit(f"画像 {data.get('image_count', 0)} 枚をインデックス化しました")
            else:
                self.done.emit(f"画像インデックス化に失敗: {data.get('error', '不明なエラー')}")
        except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
            self.done.emit(f"画像インデックス化に失敗: {exc}")


# ─── 生成タブ ────────────────────────────────────────────────────────────────────

class TutorialGeneratePanel(QWidget):
    """
    チュートリアル生成タブ。

    cfg_getter は現在の設定 dict を返す callable（rag_chatbot.py から渡される）。
    設定は生成開始時に評価するので、Settings タブでの変更が即反映される。
    """

    def __init__(
        self,
        cfg_getter: Callable[[], dict],
        parent: Optional[QWidget] = None,
        on_connection_event: Callable[[], None] | None = None,
        on_video_ready: Callable[[str, Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        # 生成失敗時など、接続状態ランプ（rag_chatbot.py側、タブ全体で共有）に
        # 即時再確認を促すためのコールバック。ランプ自体はこのウィジェットの
        # 責務ではなくなったため、通知だけ行う。
        self._on_connection_event = on_connection_event or (lambda: None)
        # 動画生成完了を「動画」タブ（VideoLibraryPanel）へ即時反映するためのコールバック
        # （2026-09-12追加）。従来は生成直後のプレビュー再生ボタン＝別ウィンドウの
        # QDialogでしか見られず、動画パスも保存済みJSONに記録していなかったため、
        # タブを離れる/Houdiniを再起動すると二度と見つけられなかった
        # （実機フィードバック：「はじめから動画タブのようなものを作った方がいい」）。
        self._on_video_ready = on_video_ready or (lambda title, path: None)
        self._worker: TutorialWorker | TutorialChainWorker | None = None
        self._agent = None            # 生成後もサンドボックス削除用に保持（単発生成モード）
        self._result = None           # TutorialResult（保存待ち。単発生成モードのみ）
        # 3段階連続生成（build_level_chain）モードで作られた (agent, result) の一覧。
        # チェーンモードは各レベルを自動保存するため、ここは「サンドボックス削除」用の
        # 参照保持だけが目的（単発生成モードでは常に空のまま）。
        self._chain_agents: list = []
        self._destroy_worker: _DestroySandboxWorker | None = None
        self._image_index_workers: list = []  # GC 防止のため参照を保持（rag_chatbot.pyのRateWorkerと同じ流儀）
        self._last_video_path: Path | None = None  # プレビュー再生対象（生成完了検出時に設定）
        # 直近のチェーン生成（3段階連続生成）で実際にディスクへ書き出した
        # (level, md_path, json_path) の一覧（2026-09-20追加）。チェーンモードは
        # プレビュー確認なしで自動保存するため、結果が気に入らなかった場合に
        # 手動でファイルを探して消す手間をなくす「生成した3件を削除」ボタン用。
        self._chain_saved_paths: list[tuple[str, Path, Path]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # 累積トークン消費量ゲージ
        self._usage_widget = token_usage.TokenUsageWidget()
        layout.addWidget(self._usage_widget)
        self._refresh_usage()

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

        # レベル選択行（IMPROVEMENT_PLAN.md Phase1: RAGレベリング）。
        # 「3段階連続生成」がオンのときはレベル選択は無視され、常に
        # basic→applied→advanced の順で3本まとめて生成・自動保存する。
        level_row = QHBoxLayout()
        level_row.addWidget(QLabel("レベル:"))
        self._level_combo = QComboBox()
        self._level_combo.addItems(["basic", "applied", "advanced"])
        self._level_combo.setToolTip(
            "basic: 初心者向け最小構成 / applied: basicにパラメータ調整・分岐を追加\n"
            "advanced: appliedにVEX/式等の実務パターンを追加"
        )
        level_row.addWidget(self._level_combo)
        self._chain_checkbox = QCheckBox("3段階連続生成（basic→applied→advanced、自動保存）")
        self._chain_checkbox.setToolTip(
            "オンにすると同一トピックでbasic/applied/advancedを順に生成し、"
            "前段の内容を次段のプロンプトへ引き継ぎます。生成時間・コストは単発の最大3倍。\n"
            "各レベルはプレビュー確認なしで自動的にlocalRAG/tutorials/へ保存されます。"
        )
        self._chain_checkbox.toggled.connect(self._on_chain_toggled)
        level_row.addWidget(self._chain_checkbox)
        level_row.addStretch()
        layout.addLayout(level_row)

        # 参考画像（テキスト＋画像での生成、2026-10-05追加）。テキストのトピックだけだと
        # 求める完成イメージからズレることがあるため、スクショ・写真・ラフ等を添えられる。
        # 添付は生成を開始してもクリアされない（同じ画像で作り直せる）。ラベルは長いファイル名で
        # パネルが横に広がらないよう fit_label で折り返す。
        self._reference_paths: list[str] = []
        ref_row = QHBoxLayout()
        self._ref_add_btn = QPushButton("参考画像を追加…")
        self._ref_add_btn.setToolTip("完成イメージの参考になる画像（png/jpg/webp等）を選びます。最大4枚。")
        self._ref_add_btn.clicked.connect(self._on_add_reference_images)
        self._ref_paste_btn = QPushButton("クリップボードの画像")
        self._ref_paste_btn.setToolTip("コピーしてある画像（スクリーンショット等）を参考画像として追加します。")
        self._ref_paste_btn.clicked.connect(self._on_paste_reference_image)
        self._ref_clear_btn = QPushButton("クリア")
        self._ref_clear_btn.clicked.connect(self._on_clear_reference_images)
        ref_row.addWidget(self._ref_add_btn)
        ref_row.addWidget(self._ref_paste_btn)
        ref_row.addWidget(self._ref_clear_btn)
        ref_row.addStretch()
        layout.addLayout(ref_row)
        self._ref_label = token_usage.fit_label(QLabel(""))
        self._ref_label.setStyleSheet("color:#7dd3fc;font-size:11px;")
        layout.addWidget(self._ref_label)
        self._refresh_reference_label()

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
        # 3段階連続生成（チェーンモード）は確認なしで自動保存するため、結果が
        # 気に入らなかった場合に保存済みファイル一式を手動で探さず消せるように
        # する（2026-09-20追加）。単発生成の「破棄」（保存前の内容をメモリ上で
        # 破棄するだけ）とは意味が異なるため別ボタンにしている。
        self._discard_chain_btn = QPushButton("生成した3件を削除")
        self._discard_chain_btn.clicked.connect(self._on_discard_chain_saves)
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn, self._discard_chain_btn):
            btn.setEnabled(False)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._status = token_usage.fit_label(QLabel(""))
        self._status.setStyleSheet("color:#aaa;font-size:11px;")
        layout.addWidget(self._status)

        # 動画生成の進捗表示・完了後のプレビュー再生（2026-08-31追加）。
        video_row = QHBoxLayout()
        self._video_progress = token_usage.fit_label(QLabel(""))
        self._video_progress.setStyleSheet("color:#7dd3fc;font-size:11px;")
        video_row.addWidget(self._video_progress, stretch=1)
        self._preview_btn = QPushButton("▶ プレビュー再生")
        self._preview_btn.setEnabled(False)
        self._preview_btn.clicked.connect(self._on_preview_video)
        video_row.addWidget(self._preview_btn)
        # 2026-09-13追加: Houdini埋め込みのQtWebEngineプレイヤーが「再生中のまま0:00から
        # 進まない」事例が報告された（ffmpegでの単体デコードは正常なため、ファイル破損では
        # なくHoudini本体とのGPUコンテキスト競合が濃厚）。埋め込み再生に問題があっても
        # 動画自体は見られるよう、OS標準プレイヤー（Houdiniと別プロセス）で開く手段を
        # 常に用意しておく。
        self._external_player_btn = QPushButton("外部プレイヤーで開く")
        self._external_player_btn.setEnabled(False)
        self._external_player_btn.clicked.connect(self._on_open_in_external_player)
        video_row.addWidget(self._external_player_btn)
        layout.addLayout(video_row)

    # ── 外部 API（/tutorial コマンド用） ────────────────────────────────────────

    def start_with_topic(self, topic: str) -> None:
        """Chat タブの /tutorial コマンドから呼ばれる。"""
        self._topic_edit.setText(topic)
        self._on_generate()

    def _refresh_usage(self) -> None:
        bridge_dir = self._cfg_getter().get("local_bridge_dir", "")
        self._usage_widget.refresh(bridge_dir)

    # ── 生成 ────────────────────────────────────────────────────────────────────

    def _on_chain_toggled(self, checked: bool) -> None:
        # チェーンモードは常に3レベル全部を生成するため、単発用のレベル選択は無意味になる
        self._level_combo.setEnabled(not checked)

    # ── 参考画像 ────────────────────────────────────────────────────────────────

    def _refresh_reference_label(self) -> None:
        if not self._reference_paths:
            self._ref_label.setText("参考画像: なし（テキストだけで生成します）")
            self._ref_label.setToolTip("")
            return
        names = ", ".join(Path(p).name for p in self._reference_paths)
        self._ref_label.setText(f"参考画像 {len(self._reference_paths)}枚: {names}（テキスト＋画像で生成します）")
        self._ref_label.setToolTip("\n".join(self._reference_paths))

    def _add_reference_paths(self, paths: list[str]) -> None:
        from tutorial_agent import MAX_REFERENCE_IMAGES

        for path in paths:
            if path in self._reference_paths:
                continue
            if len(self._reference_paths) >= MAX_REFERENCE_IMAGES:
                self._status.setText(f"参考画像は最大{MAX_REFERENCE_IMAGES}枚までです")
                break
            self._reference_paths.append(path)
        self._refresh_reference_label()

    def _on_add_reference_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "参考画像を選択", "", "画像 (*.png *.jpg *.jpeg *.webp *.bmp);;すべてのファイル (*)"
        )
        if paths:
            self._add_reference_paths(paths)

    def _on_paste_reference_image(self) -> None:
        image = QGuiApplication.clipboard().image()
        if image.isNull():
            self._status.setText("クリップボードに画像がありません（画像をコピーしてから押してください）")
            return
        import datetime
        import tempfile

        folder = Path(tempfile.gettempdir()) / "houdini_tutorial_refs"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"clipboard_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if not image.save(str(path), "PNG"):
            self._status.setText("クリップボードの画像を保存できませんでした")
            return
        self._add_reference_paths([str(path)])

    def _on_clear_reference_images(self) -> None:
        self._reference_paths = []
        self._refresh_reference_label()

    def _on_generate(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        topic = self._topic_edit.text().strip()
        if not topic:
            self._status.setText("トピックを入力してください")
            return

        cfg = self._cfg_getter()
        try:
            import tutorial_agent  # noqa: F401 -- 存在確認のみ（実際のimportは各分岐で行う）
        except ImportError as exc:
            self._status.setText(f"tutorial_agent の読み込みに失敗: {exc}")
            return

        self._progress_log.clear()
        self._preview.clear()
        self._result = None
        self._agent = None  # 前回（単発/チェーン問わず）の参照を残さない
        self._chain_agents = []
        self._chain_saved_paths = []
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn, self._discard_chain_btn):
            btn.setEnabled(False)
        self._generate_btn.setEnabled(False)

        if self._chain_checkbox.isChecked():
            self._status.setText("3段階連続生成中（basic→applied→advanced）...")
            chain_kwargs = {
                "bridge_port":    cfg.get("local_port", 8766),
                "project_dir":    cfg.get("local_bridge_dir", ""),
                # tutorial_rag_mode が未設定なら従来通りチャットの mode 設定に追随する
                # （後方互換。既存ユーザーの挙動は変わらない）
                "rag_mode":       cfg.get("tutorial_rag_mode") or cfg.get("mode", "local"),
                "gas_url":        cfg.get("gas_url", ""),
                "gas_api_key":    cfg.get("gas_api_key", ""),
                "model":          cfg.get("tutorial_model", "claude-sonnet-5"),
                "claude_backend": cfg.get("tutorial_claude_backend", "gas"),
                "cf_url":         cfg.get("cf_url", ""),
                "cf_api_key":     cfg.get("cf_api_key", ""),
                "rag_namespace":  cfg.get("tutorial_rag_namespace", ""),
                "reference_images": list(self._reference_paths),
            }
            self._worker = TutorialChainWorker(topic, chain_kwargs)
            self._worker.progress.connect(self._on_progress)
            self._worker.done.connect(self._on_chain_done)
            self._worker.failed.connect(self._on_failed)
            self._worker.start()
            return

        from tutorial_agent import TutorialAgent

        self._status.setText("生成中...")
        self._agent = TutorialAgent(
            bridge_port=cfg.get("local_port", 8766),
            project_dir=cfg.get("local_bridge_dir", ""),
            rag_mode=cfg.get("tutorial_rag_mode") or cfg.get("mode", "local"),
            gas_url=cfg.get("gas_url", ""),
            gas_api_key=cfg.get("gas_api_key", ""),
            model=cfg.get("tutorial_model", "claude-sonnet-5"),
            claude_backend=cfg.get("tutorial_claude_backend", "gas"),
            cf_url=cfg.get("cf_url", ""),
            cf_api_key=cfg.get("cf_api_key", ""),
            rag_namespace=cfg.get("tutorial_rag_namespace", ""),
            reference_images=list(self._reference_paths),
        )
        level = self._level_combo.currentText()
        self._worker = TutorialWorker(self._agent, topic, level=level)
        # progress_cb は QThread 内から呼ばれるため Signal 経由で UI スレッドに渡す。
        # TutorialWorkerの構築にはagentが先に必要なため、コンストラクタ引数ではなく
        # set_progress_callback()で後から差し替える（2026-09-20、以前は
        # self._agent._progress = ... という private属性への直接代入だった）。
        self._agent.set_progress_callback(self._worker.progress.emit)
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
        bridge_dir = self._cfg_getter().get("local_bridge_dir", "")
        token_usage.record_usage(bridge_dir, self._topic_edit.text().strip(), result)
        # result.claude_balance/capacity はGAS（gas_cloud_rag.js）がclaude_messages
        # 応答に含めて返した、そのAPIキーの実際の残高/上限。これが唯一の正なので、
        # ローカルではキャッシュ（表示専用）に保存するだけで判定には使わない。
        # 無制限キーはbalance/capacityが両方Noneになるため、claude_quota_known
        # （claudeQuotaが応答に含まれていたか）で判定する。
        if result.claude_quota_known:
            token_usage.save_server_quota(
                bridge_dir,
                result.claude_balance,
                result.claude_capacity,
                result.claude_reset_interval_hours,
                result.claude_reset_at,
            )
        self._refresh_usage()
        self._preview.setMarkdown(result.markdown)
        self._generate_btn.setEnabled(True)
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn):
            btn.setEnabled(True)
        state = "完了" if result.completed else f"途中経過（{result.abort_reason}）"
        self._status.setText(
            f"{state} — ${result.cost_usd:.3f} / {result.iterations} ステップ。"
            "内容を確認して「保存」を押してください（保存するまでファイルは書き込まれません）"
        )

    def _on_chain_done(self, results: list) -> None:
        """
        3段階連続生成（build_level_chain）の完了コールバック。単発生成と違い、
        3件のプレビュー確認を個別に求めるUXは複雑になりすぎるため、各レベルを
        その場で自動的に localRAG/tutorials/ へ保存する（チェックボックスの
        ツールチップで事前に明示している仕様）。
        """
        self._generate_btn.setEnabled(True)
        if not results:
            self._status.setText("3段階連続生成: すべてのレベルが失敗しました（進行ログを確認してください）")
            return

        tutorials_dir = self._tutorials_dir()
        preview_parts: list[str] = []
        status_parts: list[str] = []
        for agent, result in results:
            self._chain_agents.append(agent)
            bridge_dir = self._cfg_getter().get("local_bridge_dir", "")
            token_usage.record_usage(bridge_dir, self._topic_edit.text().strip(), result)
            if result.claude_quota_known:
                token_usage.save_server_quota(
                    bridge_dir, result.claude_balance, result.claude_capacity,
                    result.claude_reset_interval_hours, result.claude_reset_at,
                )
            preview_parts.append(f"# [{result.level}]\n\n{result.markdown}")

            if tutorials_dir is None:
                status_parts.append(f"{result.level}: 保存先未設定のため保存できませんでした")
                continue
            paths = self._write_result(result, tutorials_dir)
            if paths is None:
                status_parts.append(f"{result.level}: 保存失敗")
                continue
            md_path, json_path = paths
            self._chain_saved_paths.append((result.level, md_path, json_path))
            # 2026-09-20追加: _on_save()（単発生成）にはresult.completed=False（打ち切り）の
            # 場合に動画生成をデフォルトでスキップする確認ダイアログがあるが、このチェーン
            # モードは「各レベルを対話無しで自動保存する」設計（このメソッドのdocstring参照）
            # のため、同じダイアログは出せない。ダイアログの代わりに、打ち切られたレベルは
            # 自動的に動画生成をスキップすることで、_on_save側と同じ安全側のデフォルト
            # （「> 注意: 打ち切られました」という警告バナーがそのまま動画化されるのを防ぐ）
            # をチェーンモードでも保つ。以前はここにこの分岐が無く、チェーンモード経由でのみ
            # 打ち切り内容がそのまま動画化されてしまう抜け穴になっていた（リファクタリング時に発見）。
            if result.completed:
                video_status = self._launch_video_for_result(result, md_path, json_path)
                status_parts.append(f"{result.level}: {md_path.name} 保存済み / {video_status}")
            else:
                status_parts.append(
                    f"{result.level}: {md_path.name} 保存済み / "
                    f"打ち切り（{result.abort_reason}）のため動画生成をスキップしました"
                )
            self._index_screenshots_async(result)

        self._refresh_usage()
        self._preview.setMarkdown("\n\n---\n\n".join(preview_parts))
        # サンドボックスは3つ分（各レベル1つずつ）残る。「サンドボックス削除」は
        # _chain_agents 全件をまとめて削除する（_on_delete_sandbox 参照）。
        self._delete_sandbox_btn.setEnabled(True)
        self._discard_chain_btn.setEnabled(bool(self._chain_saved_paths))
        self._status.setText(" | ".join(status_parts))

    def _on_failed(self, msg: str) -> None:
        self._progress_log.append(f"エラー: {msg}")
        self._status.setText(f"生成失敗: {msg}")
        self._generate_btn.setEnabled(True)
        # サンドボックスが作られていた場合は削除だけ許可する
        if self._agent and self._agent.executor is not None:
            self._delete_sandbox_btn.setEnabled(True)
        # 生成失敗は接続断が原因のことが多いため、共有の接続状態ランプに即時再確認を促す
        self._on_connection_event()

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

    @staticmethod
    def _write_result(result, tutorials_dir: Path) -> tuple[Path, Path] | None:
        """
        result を tutorials_dir へ .md/.json として書き出す（ファイルI/Oのみ）。
        同名ファイルがある場合は連番サフィックスで衝突回避する（既存生成物を上書きしない）。
        単発生成（_on_save）と3段階連続生成（_on_chain_done）の両方から呼ばれる。
        """
        tutorials_dir.mkdir(parents=True, exist_ok=True)
        basename = result.file_basename()
        candidate = basename
        counter = 2
        while (tutorials_dir / f"{candidate}.md").exists():
            candidate = f"{basename}-{counter}"
            counter += 1

        md_path = tutorials_dir / f"{candidate}.md"
        json_path = tutorials_dir / f"{candidate}.json"
        try:
            md_path.write_text(result.markdown, encoding="utf-8")
            json_path.write_text(
                json.dumps(result.graph, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return None
        return md_path, json_path

    def _launch_video_for_result(self, result, md_path: Path, json_path: Path) -> str:
        """
        動画生成をバックグラウンドで自動起動する（ベストエフォート）。
        video_factory_bridge / screen_capture は LearningQt 側の video factory との
        連携用モジュールで、失敗してもチュートリアル保存そのものは既に成功済みなので
        例外は投げず、状態表示用の文字列として返すだけに留める。
        起動に成功した場合は、続けてログファイルのポーリングによる進捗表示を開始する
        （2026-08-31。以前は「バックグラウンドで開始しました」のまま数分待つだけだった）。
        """
        exe_path = self._cfg_getter().get("video_factory_exe_path", "")
        try:
            from video_factory_bridge import launch_video_generation

            status, log_path = launch_video_generation(
                md_path=md_path,
                json_path=json_path,
                sandbox_path=result.sandbox_path,
                step_screenshots=result.step_screenshots,
                exe_path=exe_path,
                db_key=getattr(result, "rag_name", ""),
            )
            if log_path is not None:
                self._start_video_progress_poll(log_path, Path(exe_path).parent, md_path)
            return status
        except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
            return f"動画生成の起動に失敗: {exc}"

    # ── 動画生成の進捗表示（ログファイルのポーリング） ────────────────────────────

    _VIDEO_PROGRESS_POLL_MS = 2000
    _VIDEO_PROGRESS_MAX_POLLS = 900  # 2秒間隔で最大30分。それ以上は諦めてポーリングだけ止める

    def _start_video_progress_poll(self, log_path: Path, output_dir: Path, md_path: Path) -> None:
        """
        video_factory_cloudrag_poc.exe が書く<slug>_video_factory.logを定期的に
        読み、"Rendered frame N / M" 行から進捗を、"Wrote "/"ERROR"行から完了・
        失敗をそれぞれ検出して self._video_progress ラベルへ反映する。
        完了検出時は"Wrote <ファイル名>.webm"からファイル名を取り出し、output_dir
        （video_factory_bridge.pyがPopenのcwdに固定したexe自身のディレクトリ）と
        結合してプレビューボタンを有効化する（2026-08-31）。
        プロセスの終了自体は追跡しない（設計方針は video_factory_bridge.py の
        モジュールdocstring参照）ため、あくまでログの中身だけを見るベストエフォート。

        md_path（2026-09-12追加）: 動画パスを<md_path.stem>.video.txtというサイドカー
        ファイルへ書き出すために使う。チュートリアル本体の.json（result.graph専用の
        構造）に混ぜず別ファイルにしているのは、既存のTutorialHistoryPanel._on_selectが
        .jsonの中身をNodeGraphAssetそのものとして直接パースしており、キーを1つ追加する
        だけでも構造が変わって過去に保存済みの全チュートリアルとの互換性が崩れるため。
        別ファイルなら既存コードには一切影響しない。合わせてon_video_readyコールバックで
        「動画」タブ（VideoLibraryPanel）へ即時反映する。
        """
        state = {"polls": 0}

        def poll() -> None:
            state["polls"] += 1
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return  # ログがまだ書かれ始めていない等。次回ポーリングに任せる

            wrote_match = re.search(r"Wrote (\S+\.webm)", text)
            if wrote_match:
                video_path = output_dir / wrote_match.group(1)
                self._video_progress.setText(f"動画生成: 完了（{video_path.name}）")
                if video_path.exists():
                    self._last_video_path = video_path
                    self._preview_btn.setEnabled(True)
                    self._external_player_btn.setEnabled(True)
                    sidecar_path = md_path.with_name(md_path.stem + ".video.txt")
                    try:
                        sidecar_path.write_text(str(video_path), encoding="utf-8")
                    except OSError:
                        pass  # サイドカー書き出し失敗は致命的ではない（プレビュー再生自体は動く）
                    self._on_video_ready(md_path.stem, video_path)
                return
            if "ERROR" in text or "エラー" in text:
                last_line = text.strip().splitlines()[-1] if text.strip() else ""
                self._video_progress.setText(f"動画生成: 失敗の可能性（{last_line[:80]}）")
                return

            match = None
            for line in reversed(text.splitlines()):
                m = re.search(r"Rendered frame (\d+) / (\d+)", line)
                if m:
                    match = m
                    break
            if match:
                done, total = int(match.group(1)), int(match.group(2))
                pct = int(done / total * 100) if total else 0
                self._video_progress.setText(f"動画生成: フレーム {done}/{total}（{pct}%）")
            else:
                self._video_progress.setText(f"動画生成: 準備中…（{log_path.name}）")

            if state["polls"] < self._VIDEO_PROGRESS_MAX_POLLS:
                QTimer.singleShot(self._VIDEO_PROGRESS_POLL_MS, poll)
            else:
                self._video_progress.setText(f"動画生成: 進捗表示を終了しました（{log_path.name}を直接確認してください）")

        QTimer.singleShot(self._VIDEO_PROGRESS_POLL_MS, poll)

    def _on_preview_video(self) -> None:
        """
        「▶ プレビュー再生」ボタンのコールバック。
        以前はQtWebEngineの埋め込みプレビュー（別ウィンドウのQDialog内に
        QWebEngineViewを生成）を使っていたが、Houdiniに埋め込まれたPythonパネル
        からQtWebEngineのネイティブウィンドウ（Chromiumのレンダラー/GPUプロセスが
        作る実ウィンドウで、通常のQtウィジェットとは異なりOSレベルの子ウィンドウを
        持つ）を生成すると、Houdini本体のドッキング/ペイン管理と競合し、パネル全体が
        異常に横長になったうえ、保存を含む一切の操作が不能になる致命的な不具合が
        実機で確認された（2026-09-14）。VideoLibraryPanelの埋め込みプレイヤーで
        全く同じ機構が原因だったため、こちらも含めて撤去し、常にOS標準の外部
        プレイヤーで開く方式へ統一した（_on_open_in_external_playerと同じ実装。
        ファイル自体はffmpegでのデコード検証済みで正常、外部プレイヤーでの再生も
        実機で確認済み）。
        """
        path = self._last_video_path
        if path is None or not path.exists():
            self._video_progress.setText("動画生成: プレビュー対象のファイルが見つかりません")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_open_in_external_player(self) -> None:
        """
        「外部プレイヤーで開く」ボタンのコールバック（2026-09-13追加）。
        Houdini埋め込みのQtWebEngineプレイヤーが再生できない・止まる場合の保険。
        OS標準の関連付けアプリ（Windowsなら通常Media Player等）はHoudiniとは別
        プロセスで動画を再生するため、Houdini本体とのGPUコンテキスト競合の影響を
        受けない。ファイル自体はffmpegでのデコード検証済みで正常。
        """
        path = self._last_video_path
        if path is None or not path.exists():
            self._video_progress.setText("動画生成: 再生対象のファイルが見つかりません")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _index_screenshots_async(self, result) -> None:
        """
        保存直後、result.step_screenshots のビューポート画像をベストエフォートで
        ローカルRAGへCLIP画像埋め込みとしてインデックス化する
        （IMPROVEMENT_PLAN.md Phase2）。/index-images は Local RAG ブリッジ専用の
        エンドポイントのため、Cloud RAG モードでは何もしない。失敗しても
        チュートリアル保存そのものには影響させない（ステータス表示に追記するだけ）。
        """
        cfg = self._cfg_getter()
        if cfg.get("mode") != "local":
            return
        image_paths = [s["viewport"] for s in result.step_screenshots if s.get("viewport")]
        if not image_paths:
            return
        metadata_by_path = {
            s["viewport"]: {
                "tutorial_title": result.title,
                "level":          result.level,
                "step":           s.get("step"),
                "tool":           s.get("tool"),
                "caption":        (s.get("result") or "")[:200],
            }
            for s in result.step_screenshots if s.get("viewport")
        }
        worker = _ImageIndexWorker(
            cfg.get("local_port", 8766), "tutorials", image_paths, metadata_by_path
        )
        worker.done.connect(lambda msg: self._status.setText(f"{self._status.text()} / {msg}"))
        self._image_index_workers.append(worker)  # GC 防止
        worker.start()

    def _on_save(self) -> None:
        if self._result is None:
            return
        tutorials_dir = self._tutorials_dir()
        if tutorials_dir is None:
            return

        # 2026-09-14追加: result.completed=False（confirm_tutorialまで到達しなかった
        # 打ち切り）の場合、動画生成をデフォルトでスキップするよう確認を挟む。以前は
        # 打ち切りでも無条件で動画生成まで進んでおり、本文の「> 注意: 打ち切られました」
        # という警告バナーがそのままスライド内容として動画化される（見た目には
        # 正常な解説スライドと区別がつかない）不具合が実機で報告された。ノード構成
        # 自体は途中まで正しく作れていることもあるため、ユーザーが希望すれば
        # 生成できる選択肢は残す（デフォルトはNo＝生成しない）。
        skip_video = False
        if not self._result.completed:
            answer = QMessageBox.question(
                self,
                "打ち切られた生成の保存",
                f"この生成は途中で打ち切られています（{self._result.abort_reason}）。\n"
                "ノード構成・チュートリアル文書は保存されますが、動画も生成しますか？\n"
                "（打ち切り内容がそのまま動画化されます。通常は「いいえ」を推奨）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            skip_video = answer != QMessageBox.Yes

        paths = self._write_result(self._result, tutorials_dir)
        if paths is None:
            self._status.setText("保存失敗")
            return
        md_path, json_path = paths

        self._save_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._status.setText(
            f"保存しました: {md_path.name} / {json_path.name}"
            "（watchdog が自動インデックス化します）"
        )
        if skip_video:
            self._status.setText(f"{self._status.text()} / 打ち切りのため動画生成をスキップしました")
        else:
            video_status = self._launch_video_for_result(self._result, md_path, json_path)
            self._status.setText(f"{self._status.text()} / {video_status}")
        self._index_screenshots_async(self._result)

    def _on_discard(self) -> None:
        self._result = None
        self._preview.clear()
        self._save_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._status.setText("破棄しました（サンドボックスは残っています。不要なら「サンドボックス削除」）")

    def _on_discard_chain_saves(self) -> None:
        """
        直近の3段階連続生成が自動保存した.md/.jsonファイル一式（あればスクリーンショット
        マニフェスト・動画パスのサイドカーも含む）を削除する（2026-09-20追加）。
        チェーンモードは確認なしで自動保存するため、結果が気に入らなかった場合に
        ファイルを手動で探して消す手間をなくすためのショートカット。動画生成が
        バックグラウンドで既に開始・完了している場合、生成済みの.webm自体は
        （video_factory_bridge.pyの出力先がexe自身のディレクトリ固定のため）ここでは
        追跡できず削除されない点に注意（動画は「動画」タブから個別に削除できる）。
        サンドボックス（Houdini側のノード）はここでは削除しない（別ボタン「サンドボックス
        削除」の責務のまま。ファイル削除とノード削除は別の取り消し操作として分けている）。
        """
        if not self._chain_saved_paths:
            return
        names = "\n".join(f"{level}: {md_path.name}" for level, md_path, _ in self._chain_saved_paths)
        answer = QMessageBox.question(
            self, "生成した3件を削除",
            f"以下の保存済みファイルを削除しますか？（元に戻せません）\n\n{names}",
        )
        if answer != QMessageBox.Yes:
            return
        failed = []
        for level, md_path, json_path in self._chain_saved_paths:
            for path in (
                md_path,
                json_path,
                md_path.with_name(md_path.stem + "_screenshots.json"),
                md_path.with_name(md_path.stem + ".video.txt"),
            ):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    failed.append(f"{level}（{path.name}）: {exc}")
        self._chain_saved_paths = []
        self._discard_chain_btn.setEnabled(False)
        if failed:
            self._status.setText("一部削除に失敗しました: " + "; ".join(failed))
        else:
            self._status.setText("生成した3件を削除しました（サンドボックス・動画ファイルは残っています）")

    def _on_delete_sandbox(self) -> None:
        # 3段階連続生成モードで作られたサンドボックスがあればそちらを優先する
        # （単発生成モードでは常に空リストのままなので self._agent にフォールバックする）。
        agents = self._chain_agents or ([self._agent] if self._agent is not None else [])
        if not agents:
            return
        paths = ", ".join(getattr(a.executor, "sandbox_path", "") for a in agents)
        answer = QMessageBox.question(
            self, "サンドボックス削除",
            f"{paths} を削除しますか？",
        )
        if answer != QMessageBox.Yes:
            return
        # destroy_sandbox()はhdefereval.executeInMainThreadWithResult()でメインスレッドへ
        # ディスパッチする実装になっており、ここ（UIのボタンハンドラ=既にメインスレッド）
        # から直接呼ぶとメインスレッドが自分自身へのディスパッチ完了を待ってデッドロック
        # する（実機で「サンドボックス削除でHoudiniがフリーズする」不具合として確認済み）。
        # バックグラウンドスレッドから呼ぶことで正しくメインスレッドへディスパッチされる。
        self._delete_sandbox_btn.setEnabled(False)
        self._status.setText("サンドボックスを削除中...")
        self._destroy_worker = _DestroySandboxWorker(agents)
        self._destroy_worker.done.connect(self._on_sandbox_destroyed)
        self._destroy_worker.failed.connect(self._on_sandbox_destroy_failed)
        self._destroy_worker.start()

    def _on_sandbox_destroyed(self) -> None:
        self._chain_agents = []  # 削除済みの参照を残さない（次回生成まで再利用させない）
        self._status.setText("サンドボックスを削除しました")

    def _on_sandbox_destroy_failed(self, msg: str) -> None:
        self._delete_sandbox_btn.setEnabled(True)
        self._status.setText(f"サンドボックス削除失敗: {msg}")


# ─── 動画ライブラリ（保存済みチュートリアルの動画一覧・再生） ───────────────────────
#
# 2026-09-12追加。従来、生成した動画を見る手段はTutorialGeneratePanelの
# 「▶ プレビュー再生」ボタン（別ウィンドウのQDialog）だけで、かつ動画パスは
# インスタンス変数（_last_video_path）にしか残らなかったため、タブを離れたり
# Houdiniを再起動すると同一セッションで生成した動画すら二度と見つけられなかった
# （実機フィードバック：「新しくタブで動画タブのようなものを追加してみては」）。
# このタブはTutorialGeneratePanelが動画完成時に書き出すサイドカーファイル
# （<名前>.video.txt、_start_video_progress_poll参照）を走査するので、Houdiniを
# 再起動した後でも過去に生成した動画を一覧・再生できる。


class VideoLibraryPanel(QWidget):
    """
    保存済みチュートリアルの動画を一覧表示し、選択したものを外部プレイヤーで
    再生するタブ。以前はQtWebEngineが使える環境でパネル内に埋め込んだプレイヤー
    （QWebEngineView）で直接再生していたが、Houdiniに埋め込まれたPythonパネル
    内でQtWebEngineのネイティブウィンドウをリスト選択のたびに自動アクティブ化
    すると、Houdini本体のドッキング/ペイン管理と競合し、パネル全体が異常に
    横長になったうえ保存を含む一切の操作が不能になる致命的な不具合が実機で
    確認された（2026-09-14）。TutorialGeneratePanel._on_preview_videoの旧実装と
    同じ根本原因のため、両方から埋め込みQtWebEngineを撤去し、常にOS標準の
    外部プレイヤーで開く方式へ統一した。
    """

    _THUMBNAIL_SIZE = QSize(96, 54)  # 16:9相当。QListWidgetのiconSizeと合わせて使う

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
        toolbar.addWidget(refresh_btn)
        # 選択した動画（複数選択可、Ctrl/Shiftクリック）だけを削除する（2026-09-12追加）。
        # 削除対象は動画ファイルとサイドカー（<名前>.video.txt）のみで、チュートリアル
        # 本体（.md/.json）やスクリーンショットマニフェストは対象外にしている
        # （「動画の一括削除」という要望のスコープを動画ファイル自体に絞るため）。
        self._delete_btn = QPushButton("選択した動画を削除")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_selected)
        toolbar.addWidget(self._delete_btn)
        # 2026-09-13追加: 埋め込みQtWebEngineプレイヤーが再生できない・止まる場合の保険
        # （TutorialGeneratePanel._on_open_in_external_playerと同じ理由）。
        self._external_player_btn = QPushButton("外部プレイヤーで開く")
        self._external_player_btn.setEnabled(False)
        self._external_player_btn.clicked.connect(self._on_open_in_external_player)
        toolbar.addWidget(self._external_player_btn)
        self._current_video_path: Path | None = None
        self._status = token_usage.fit_label(QLabel(""))
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;")
        toolbar.addWidget(self._status)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        self._list = QListWidget()
        self._list.setIconSize(self._THUMBNAIL_SIZE)
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list.currentItemChanged.connect(self._on_select)
        self._list.itemSelectionChanged.connect(
            lambda: self._delete_btn.setEnabled(len(self._list.selectedItems()) > 0)
        )
        splitter.addWidget(self._list)

        self._player_container = QWidget()
        player_layout = QVBoxLayout(self._player_container)
        player_layout.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QLabel("左の一覧から動画を選んでください")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color:#94a3b8;")
        player_layout.addWidget(self._placeholder)
        splitter.addWidget(self._player_container)
        splitter.setSizes([220, 640])
        layout.addWidget(splitter, stretch=1)

    def _tutorials_dir(self) -> Path | None:
        bridge_dir = self._cfg_getter().get("local_bridge_dir", "")
        if not bridge_dir:
            return None
        return Path(bridge_dir) / "localRAG" / "tutorials"

    def _find_thumbnail(self, tutorials_dir: Path, name: str) -> QIcon | None:
        """
        <名前>_screenshots.json（video_factory_bridge.pyがvideo factory exeへ渡す
        スクリーンショットマニフェスト。houdini_tools.pyのexport_step_screenshots()が
        {"step","tool","viewport","network"}形式で書く）から、最初に見つかる
        viewport画像（無ければnetwork画像）をサムネイルとして読み込む（2026-09-12追加）。
        マニフェストが無い・壊れている・画像が見つからない場合はNoneを返し、
        呼び出し側はテキストのみの行として扱う。
        """
        manifest_path = tutorials_dir / f"{name}_screenshots.json"
        try:
            shots = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for shot in shots:
            for key in ("viewport", "network"):
                img_path = shot.get(key)
                if img_path and Path(img_path).exists():
                    icon = QIcon(img_path)
                    if not icon.isNull():
                        return icon
        return None

    @staticmethod
    def _format_size(total_bytes: int) -> str:
        size = float(total_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}{unit}"
            size /= 1024
        return f"{size:.1f}GB"

    def refresh(self) -> None:
        """<名前>.video.txtサイドカーを走査して一覧を作り直す。"""
        current_path = None
        if self._list.currentItem() is not None:
            current_path = self._list.currentItem().data(Qt.UserRole)
        self._list.clear()

        tutorials_dir = self._tutorials_dir()
        if tutorials_dir is None:
            self._status.setText("Settings タブで Bridge Directory を設定してください")
            return
        if not tutorials_dir.exists():
            self._status.setText("まだ保存されたチュートリアルがありません")
            return

        sidecars = sorted(
            tutorials_dir.glob("*.video.txt"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        restored_item = None
        total_bytes = 0
        for sidecar in sidecars:
            try:
                video_path_str = sidecar.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not video_path_str:
                continue
            video_path = Path(video_path_str)
            if not video_path.exists():
                continue  # 動画ファイル自体が後から移動・削除された場合は一覧から除く
            name = sidecar.name[: -len(".video.txt")]
            file_size = video_path.stat().st_size
            total_bytes += file_size
            item = QListWidgetItem(f"{name}\n{self._format_size(file_size)}")
            item.setData(Qt.UserRole, str(video_path))
            item.setData(Qt.UserRole + 1, str(sidecar))  # 削除時にサイドカーも一緒に消すため
            thumbnail = self._find_thumbnail(tutorials_dir, name)
            if thumbnail is not None:
                item.setIcon(thumbnail)
            self._list.addItem(item)
            if current_path == str(video_path):
                restored_item = item

        self._status.setText(f"{self._list.count()} 件 / 合計 {self._format_size(total_bytes)}")
        if restored_item is not None:
            self._list.setCurrentItem(restored_item)
        self._delete_btn.setEnabled(len(self._list.selectedItems()) > 0)

    def _on_delete_selected(self) -> None:
        """
        選択中の動画ファイル＋サイドカーを削除する（2026-09-12追加）。チュートリアル
        本体（.md/.json）は残す＝あくまで「動画」だけの容量削減が目的のため、
        再生成すればいつでも動画だけ作り直せる（video_factory_exe_pathが設定済みなら）。
        """
        items = self._list.selectedItems()
        if not items:
            return
        names = "\n".join(item.text().split("\n")[0] for item in items)
        answer = QMessageBox.question(
            self, "動画を削除",
            f"以下の動画ファイルを削除します（チュートリアル本体は残ります）。元に戻せません。\n\n{names}",
        )
        if answer != QMessageBox.Yes:
            return
        failed = []
        for item in items:
            video_path = Path(item.data(Qt.UserRole))
            sidecar_path = Path(item.data(Qt.UserRole + 1))
            for path in (video_path, sidecar_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    failed.append(f"{path.name}: {exc}")
        self.refresh()
        if failed:
            self._status.setText(self._status.text() + "（一部削除失敗: " + "; ".join(failed) + "）")

    def show_video(self, name: str, video_path: Path) -> None:
        """
        指定した動画を選択状態にする（無ければ一覧の先頭に追加してから選択する）。
        TutorialGeneratePanelの生成完了コールバックとTutorialHistoryPanelの
        「▶ 動画を再生」ボタン、両方の入口として使う（2026-09-12追加）。同じ動画を
        複数回開いても一覧に重複行が増えないよう、追加前に既存行を探す。
        """
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == str(video_path):
                self._list.setCurrentItem(item)
                return
        self.add_video(name, video_path)

    def add_video(self, name: str, video_path: Path) -> None:
        """
        生成完了直後、ディスク再走査を待たずに一覧の先頭へ即時反映する
        （TutorialGeneratePanelのon_video_readyコールバックから呼ばれる）。
        サイドカーファイル自体は呼び出し元が既に書き出し済みなので、ここではリスト
        ウィジェットの更新のみを行う。サイドカーパス（Qt.UserRole+1）とサムネイルも
        refresh()と同じ形式で埋めておく（2026-09-12追加：これが無いと、refresh()を
        挟まずに追加された行を後から削除しようとした際にクラッシュする不具合があった）。

        注意: video_pathの親ディレクトリはvideo factory exe自身の出力先
        （video_factory_bridge.pyがPopenのcwdに固定した場所）であり、サイドカー・
        スクリーンショットマニフェストが置かれているtutorials_dir（.md/.json保存先）
        とは別の場所になりうる。tutorials_dirは必ずself._tutorials_dir()から取得する
        こと（video_path.parentを使う実装ミスを一度やって気づいた）。
        """
        tutorials_dir = self._tutorials_dir() or video_path.parent
        sidecar_path = tutorials_dir / f"{name}.video.txt"
        file_size = video_path.stat().st_size if video_path.exists() else 0
        item = QListWidgetItem(f"{name}\n{self._format_size(file_size)}")
        item.setData(Qt.UserRole, str(video_path))
        item.setData(Qt.UserRole + 1, str(sidecar_path))
        thumbnail = self._find_thumbnail(tutorials_dir, name)
        if thumbnail is not None:
            item.setIcon(thumbnail)
        self._list.insertItem(0, item)
        self._list.setCurrentItem(item)

        total_bytes = sum(
            Path(self._list.item(i).data(Qt.UserRole)).stat().st_size
            for i in range(self._list.count())
            if Path(self._list.item(i).data(Qt.UserRole)).exists()
        )
        self._status.setText(f"{self._list.count()} 件 / 合計 {self._format_size(total_bytes)}")

    def _on_select(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            self._current_video_path = None
            self._external_player_btn.setEnabled(False)
            return
        path = Path(current.data(Qt.UserRole))
        if not path.exists():
            self._placeholder.setText(f"ファイルが見つかりません: {path}")
            self._current_video_path = None
            self._external_player_btn.setEnabled(False)
            return

        self._current_video_path = path
        self._external_player_btn.setEnabled(True)
        self._placeholder.setText(f"{path.name}\n「外部プレイヤーで開く」で再生してください")

    def _on_open_in_external_player(self) -> None:
        """「外部プレイヤーで開く」ボタンのコールバック（2026-09-13追加）。
        TutorialGeneratePanel._on_open_in_external_playerと同じ理由・同じ実装。"""
        path = self._current_video_path
        if path is None or not path.exists():
            self._status.setText("再生対象のファイルが見つかりません")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# ─── ノードグラフビューア（NodeGraphAsset JSON） ─────────────────────────────────

_NODE_W, _NODE_H = 130.0, 34.0
_POS_SCALE = 150.0  # Houdini ネットワーク座標 → シーン座標のスケール（生の座標を使う経路のみ）

# layered_positions() が返す (col, row) の格子座標をシーン座標へ変換するスケール。
# _POS_SCALE で割ってから渡すのは、_NodeGraphScene.build() が全ノードの
# position に一律で _POS_SCALE を掛けるため（layered_positions 用に別の
# スケール定数を素通しできるよう、ここで打ち消しておく）。
_LAYER_COL_SPACING = 220.0  # パイプラインの段（層）間の間隔（横）
_LAYER_ROW_SPACING = 80.0   # 同じ層内でのノード間隔（縦）

# ノードカテゴリの目安色（kind のプレフィックスで判定できないため単色ベース＋subnet 区別）
_NODE_COLOR = "#3b6ea5"
_SUBNET_COLOR = "#7c5cbf"
# 簡易表示で直列チェーンを折り畳んだ集約ノード（kind="chain"）用の色。
# 「これは複数ノードを束ねた集約」であることが色でも分かるようにする。
_CHAIN_COLOR = "#3f7a4f"


class _GraphNodeItem(QGraphicsRectItem):
    """NodeGraphAsset の1ノードを矩形＋ラベルで表示する。"""

    def __init__(self, node: dict) -> None:
        super().__init__(-_NODE_W / 2, -_NODE_H / 2, _NODE_W, _NODE_H)
        self.node_data = node
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        kind = node.get("kind")
        if kind == "chain":
            color = _CHAIN_COLOR
        elif kind in ("subnet", "geo"):
            color = _SUBNET_COLOR
        else:
            color = _NODE_COLOR
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
        # 集約ノードはラベルが長くなる（例:「grid1 → mountain1 → scatter1（3ノード）」）ので
        # ラベル幅に合わせて矩形を広げる（通常ノードは既定幅のまま）。
        width = max(_NODE_W, br.width() + 16)
        if width != _NODE_W:
            self.setRect(-width / 2, -_NODE_H / 2, width, _NODE_H)
        label.setPos(-br.width() / 2, -br.height() - 2 + _NODE_H / 2 - 24)

        kind_label = QGraphicsSimpleTextItem(node.get("kind", ""), self)
        kind_font = QFont()
        kind_font.setPointSize(7)
        kind_label.setFont(kind_font)
        kind_label.setBrush(QBrush(QColor("#cbd5e1")))
        kbr = kind_label.boundingRect()
        kind_label.setPos(-kbr.width() / 2, 0)


_ARROW_SIZE = 7.0  # 矢印ヘッドの大きさ（データフローの向きを一目で分かるようにするため）


def _make_arrow_edge(x1: float, y1: float, x2: float, y2: float, pen: QPen) -> QGraphicsPathItem:
    """
    source→target の向きが分かる矢印付きエッジを作る。
    graph_view.py（知識グラフ）のエッジは無向（類似度）なので矢印は不要だが、
    こちらはノード間のデータフロー（入力→出力）を表すため、向きを示す矢印
    ヘッドを追加することで「どちらが上流か」が一目で分かるようにする。
    """
    path = QPainterPath()
    path.moveTo(x1, y1)
    path.lineTo(x2, y2)

    angle = math.atan2(y2 - y1, x2 - x1)
    for da in (math.pi / 7, -math.pi / 7):
        a = angle + math.pi - da
        path.moveTo(x2, y2)
        path.lineTo(x2 + _ARROW_SIZE * math.cos(a), y2 + _ARROW_SIZE * math.sin(a))

    item = QGraphicsPathItem(path)
    item.setPen(pen)
    item.setZValue(0)
    return item


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
                # layered_positions() は左→右のパイプラインとして配置するため、
                # 接続点も上下（旧: 生のHoudini座標が縦方向のパイプラインだった
                # 頃の名残）ではなく左右（矩形の右端→左端）にする。rect() から
                # 実際の矩形幅を読むことで、ラベルが長い集約ノード（幅が
                # _NODE_W より広い）でも矩形の外側から線が出るようにする。
                self.addItem(_make_arrow_edge(
                    src.pos().x() + src.rect().right(), src.pos().y(),
                    dst.pos().x() + dst.rect().left(), dst.pos().y(),
                    pen,
                ))

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

    def __init__(
        self,
        cfg_getter: Callable[[], dict],
        parent: Optional[QWidget] = None,
        on_open_video: Callable[[str, Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._current_graph: dict | None = None
        self._simple_mode: bool = True
        # 選択中チュートリアルに動画（<名前>.video.txtサイドカー）があれば「動画」タブへ
        # 切り替えて再生させるためのコールバック（2026-09-12追加、VideoLibraryPanel参照）。
        self._on_open_video = on_open_video or (lambda name, path: None)
        self._selected_video_path: Path | None = None
        self._selected_video_log_path: Path | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("更新")
        refresh_btn.setFixedWidth(60)
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        # タイトル・難易度での絞り込み。一覧はrefresh()で全件読み込み済みなので、
        # ディスクへは再アクセスせずQListWidgetItemの表示/非表示切替だけで済ませる
        # （2026-08-31、生成本数が増えるほど目的のチュートリアルを探しにくくなるため追加）。
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("タイトル・難易度で検索…")
        self._search_box.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search_box, stretch=1)

        # 簡易（直列チェーンを折り畳んだ集約表示） / 詳細（全ノード表示）の切替。
        # ノード数が多い（既定 30 超）チュートリアルを開いたときは簡易を既定選択にする
        # （197ノード級の生成物を全部展開すると判読不能になるため）。
        # ボタン名だけでは違いが伝わらない（実機で「違いが分からない」と報告された）ため、
        # ツールチップで具体的に何をする表示モードなのかを明記する。
        self._simple_btn = QPushButton("簡易")
        self._simple_btn.setCheckable(True)
        self._simple_btn.setChecked(True)
        self._simple_btn.setToolTip(
            "分岐・合流のない直列チェーン（例: grid1→mountain1→scatter1）を\n"
            "1つの緑色の集約ノードにまとめて表示します。ノード数が多いチュートリアルの\n"
            "全体の流れをざっと把握するのに向いています。"
        )
        self._detail_btn = QPushButton("詳細")
        self._detail_btn.setCheckable(True)
        self._detail_btn.setToolTip(
            "折り畳みをせず、Houdini上で実際に作られた全ノードを1つずつ表示します。\n"
            "各ノードの正確なパラメータや接続を確認したいときに使います。"
        )
        self._view_mode_group = QButtonGroup(self)
        self._view_mode_group.setExclusive(True)
        self._view_mode_group.addButton(self._simple_btn)
        self._view_mode_group.addButton(self._detail_btn)
        self._view_mode_group.buttonClicked.connect(self._on_view_mode_changed)
        toolbar.addWidget(self._simple_btn)
        toolbar.addWidget(self._detail_btn)

        self._copy_mermaid_btn = QPushButton("Mermaidとしてコピー")
        self._copy_mermaid_btn.clicked.connect(self._on_copy_mermaid)
        toolbar.addWidget(self._copy_mermaid_btn)

        # 選択中のチュートリアルに動画（<名前>.video.txtサイドカー）が見つかった場合のみ
        # 有効化する（2026-09-12追加）。押すと「動画」タブへ切り替えて再生する。
        self._open_video_btn = QPushButton("▶ 動画を再生")
        self._open_video_btn.setEnabled(False)
        self._open_video_btn.clicked.connect(self._on_open_video_clicked)
        toolbar.addWidget(self._open_video_btn)

        # 動画生成ログ（<名前>_video_factory.log、video_factory_bridge.py参照）を見る
        # ボタン（2026-09-20追加）。生成直後のTutorialタブでしかポーリング表示できず、
        # パネルを閉じた後や別のチュートリアルを見ている間は進捗を追えなかったという
        # 実機フィードバックへの対応。動画自体がまだ無い（生成中・失敗）場合でも、
        # ログファイルさえ残っていれば内容を確認できる。
        self._video_log_btn = QPushButton("動画生成ログを見る")
        self._video_log_btn.setEnabled(False)
        self._video_log_btn.clicked.connect(self._on_view_video_log)
        toolbar.addWidget(self._video_log_btn)

        self._status = token_usage.fit_label(QLabel(""))
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;")
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
        self._style_markdown_view(self._md_view)
        right.addWidget(self._md_view)
        right.setSizes([250, 350])

        splitter.addWidget(right)
        splitter.setSizes([200, 500])
        layout.addWidget(splitter, stretch=1)

        self._detail = QLabel("")
        self._detail.setStyleSheet(
            "background:#1e293b;color:#e2e8f0;padding:4px 8px;font-size:11px;"
        )
        token_usage.fit_label(self._detail)
        layout.addWidget(self._detail)

    @staticmethod
    def _style_markdown_view(view: QTextEdit) -> None:
        """
        Markdown 本文（_assemble_markdown が組み立てる構造はそのまま）の見た目だけを
        改善する。フォントサイズ・行間を広げ、見出し/コード/引用（ハマりポイント等）を
        視覚的に分離することで、「### ノード」「### 接続」のような長い一覧部分も
        読みやすくする。
        """
        view.setStyleSheet(
            "QTextEdit{"
            "background:#0f172a;color:#e2e8f0;border:none;padding:6px;"
            "font-family:'Segoe UI','Yu Gothic UI',sans-serif;font-size:13px;"
            "}"
        )
        view.document().setDefaultStyleSheet(
            "body{line-height:150%;}"
            "h1,h2{color:#93c5fd;border-bottom:1px solid #334155;"
            "padding-bottom:2px;margin-top:14px;}"
            "h3{color:#7dd3fc;margin-top:10px;}"
            "code{font-family:Consolas,'Yu Gothic UI',monospace;"
            "background:#1e293b;color:#fbbf24;padding:1px 4px;border-radius:3px;}"
            "pre{background:#1e293b;padding:6px;border-radius:4px;}"
            "blockquote{background:#1e293b;border-left:3px solid #f59e0b;"
            "padding:4px 8px;color:#fcd34d;margin-left:0;}"
            "hr{border:0;border-top:1px solid #334155;margin:10px 0;}"
            "li{margin-bottom:2px;}"
            "a{color:#38bdf8;}"
        )

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
        archived_count = 0
        for path in files:
            label = path.stem
            difficulty = self._peek_difficulty(path)
            if difficulty:
                label = f"{label}  [{difficulty}]"
            # 2026-09-14追加: frontmatterのstatusがarchived（=confirm_tutorialまで
            # 到達せず打ち切られた生成、tutorial_agent.py._assemble_markdown参照）の
            # ものを一覧上で分かるようにする。「Houdiniチュートリアル生成が正規に
            # 終了しているか一覧で確認したい」という実機フィードバックへの対応。
            if self._peek_status(path) == "archived":
                label = f"⚠ {label}（打ち切り）"
                archived_count += 1
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(path))
            self._list.addItem(item)
        status_text = f"{len(files)} 件"
        if archived_count:
            status_text += f"（うち打ち切り ⚠ {archived_count}件）"
        self._status.setText(status_text)
        self._apply_filter(self._search_box.text())

    def _apply_filter(self, text: str) -> None:
        """検索ボックスの文字列でリストの表示/非表示を切り替える（大文字小文字区別なし）。"""
        needle = text.strip().lower()
        visible = 0
        for i in range(self._list.count()):
            item = self._list.item(i)
            hit = not needle or needle in item.text().lower()
            item.setHidden(not hit)
            visible += 1 if hit else 0
        if needle:
            self._status.setText(f"{visible} / {self._list.count()} 件（「{text}」で絞り込み中）")

    @staticmethod
    def _peek_difficulty(path: Path) -> str:
        """
        frontmatterのdifficultyフィールド（IMPROVEMENT_PLAN.md Phase1）だけを
        一覧ラベル表示用に軽く読む。フルのYAMLパースは行わず先頭数行を走査する
        だけに留める（失敗しても空文字を返し、一覧表示自体は継続させる）。
        """
        try:
            with path.open("r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i > 20:
                        break
                    line = line.strip()
                    if line.startswith("difficulty:"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return ""

    @staticmethod
    def _peek_status(path: Path) -> str:
        """
        frontmatterのstatusフィールドだけを一覧ラベル表示用に軽く読む
        （_peek_difficultyと同じ方針。2026-09-14追加）。scripts/auto_index.pyの
        インデックス対象判定と同じ値（active/stale/archived）を返す。
        """
        try:
            with path.open("r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i > 20:
                        break
                    line = line.strip()
                    if line.startswith("status:"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return ""

    def _on_select(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        md_path = Path(current.data(Qt.UserRole))
        try:
            self._md_view.setMarkdown(md_path.read_text(encoding="utf-8"))
        except OSError as exc:
            self._md_view.setPlainText(f"読み込みエラー: {exc}")

        # 動画（<名前>.video.txtサイドカー）の有無を確認する（2026-09-12追加）。
        # VideoLibraryPanel.refresh()と同じ命名規則。
        self._selected_video_path = None
        video_sidecar = md_path.with_name(md_path.stem + ".video.txt")
        if video_sidecar.exists():
            try:
                video_path = Path(video_sidecar.read_text(encoding="utf-8").strip())
                if video_path.exists():
                    self._selected_video_path = video_path
            except OSError:
                pass
        self._open_video_btn.setEnabled(self._selected_video_path is not None)

        # 動画生成ログ（video_factory_bridge.launch_video_generationが書く
        # <名前>_video_factory.log）の有無を確認する（2026-09-20追加）。動画自体が
        # まだ無い（生成中・失敗）場合でもログだけは残っていることがあるため、
        # video_sidecarとは別に判定する。
        log_path = md_path.with_name(md_path.stem + "_video_factory.log")
        self._selected_video_log_path = log_path if log_path.exists() else None
        self._video_log_btn.setEnabled(self._selected_video_log_path is not None)

        json_path = md_path.with_suffix(".json")
        if json_path.exists():
            try:
                graph = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._current_graph = None
                self._graph_scene.clear()
                self._detail.setText(f"ノードグラフ読み込みエラー: {exc}")
                return
            self._current_graph = graph
            # ノード数が多い生成物は既定で簡易表示にする（判読不能な塊を避けるため）。
            node_count = len(graph.get("nodes", []))
            self._simple_mode = node_count > _SIMPLIFY_THRESHOLD
            self._simple_btn.setChecked(self._simple_mode)
            self._detail_btn.setChecked(not self._simple_mode)
            self._render_graph()
        else:
            self._current_graph = None
            self._graph_scene.clear()
            self._detail.setText("ノードグラフ JSON がありません")

    def _on_open_video_clicked(self) -> None:
        """「▶ 動画を再生」ボタン。「動画」タブへの切り替え＋該当動画の選択はコールバック
        （rag_chatbot.pyがVideoLibraryPanelへ橋渡しする）に委ねる（2026-09-12追加）。"""
        if self._selected_video_path is None:
            return
        current = self._list.currentItem()
        name = current.text() if current is not None else self._selected_video_path.stem
        self._on_open_video(name, self._selected_video_path)

    def _on_view_video_log(self) -> None:
        """
        「動画生成ログを見る」ボタン（2026-09-20追加）。動画自体の再生とは独立して、
        video_factory_cloudrag_poc.exe の生の出力（進捗行・エラー時のnarration
        synthesis failed等）をいつでも確認できるようにする。開くたびにファイルを
        読み直す（ダイアログ内に「更新」ボタンを設け、生成が進行中でも最新内容を
        再取得できるようにする）。
        """
        if self._selected_video_log_path is None:
            return
        log_path = self._selected_video_log_path

        dialog = QDialog(self)
        dialog.setWindowTitle(f"動画生成ログ: {log_path.name}")
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)

        view = QTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet("font-family:Consolas,monospace;font-size:11px;")

        def load_log() -> None:
            try:
                view.setPlainText(log_path.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                view.setPlainText(f"読み込みエラー: {exc}")
            sb = view.verticalScrollBar()
            sb.setValue(sb.maximum())

        load_log()
        layout.addWidget(view)

        button_row = QHBoxLayout()
        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(load_log)
        button_row.addWidget(refresh_btn)
        button_row.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(dialog.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        dialog.exec()

    def _on_view_mode_changed(self, _button) -> None:
        self._simple_mode = self._simple_btn.isChecked()
        self._render_graph()

    def _render_graph(self) -> None:
        """
        self._current_graph を現在の表示モード（簡易/詳細）に応じて
        _NodeGraphScene に描画する。簡易モードでは simplify_graph() で
        直列チェーンを折り畳んでからノード数を大幅に減らして表示する。

        座標は Houdini ネットワークエディタ上の生の位置をそのまま使わず、
        layered_positions() でグラフの接続構造（入力→出力）だけから
        再計算する。自動生成グラフは密集・重複しやすく、生の座標を
        そのまま描画すると判読不能な塊になる（実機で「グラフビューが
        ひどい」と報告された不具合）ため、パイプラインの流れに沿った
        層状レイアウトに置き換えている。
        """
        graph = self._current_graph
        if graph is None:
            self._graph_scene.clear()
            return
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if self._simple_mode:
            view_nodes, view_edges = simplify_graph(nodes, edges)
        else:
            view_nodes, view_edges = nodes, edges

        positions = layered_positions(view_nodes, view_edges)
        laid_out_nodes = [
            {
                **n,
                "position": [
                    positions[n["id"]][0] * _LAYER_COL_SPACING / _POS_SCALE,
                    positions[n["id"]][1] * _LAYER_ROW_SPACING / _POS_SCALE,
                ],
            }
            if n.get("id") in positions else n
            for n in view_nodes
        ]

        self._graph_scene.build({**graph, "nodes": laid_out_nodes, "edges": view_edges})
        self._graph_view.fitInView(
            self._graph_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30),
            Qt.KeepAspectRatio,
        )
        mode_label = "簡易" if self._simple_mode else "詳細"
        # 「簡易/詳細で何が違うか分からない」という報告への対策として、ノード数が
        # たまたま変わらない場合でも常にモードの意味を明示する（差分が出たときだけ
        # 補足していた従来仕様だと、差が小さいチュートリアルで違いが伝わらなかった）。
        mode_desc = "直列チェーンを1ノードに集約" if self._simple_mode else "全ノードを個別に表示"
        reduction = ""
        if self._simple_mode and len(nodes) != len(view_nodes):
            reduction = f"（元: {len(nodes)} ノード / {len(edges)} エッジ）"
        self._detail.setText(
            f"[{mode_label}表示: {mode_desc}] {len(view_nodes)} ノード / {len(view_edges)} エッジ {reduction}"
            f"  |  sandbox: {graph.get('sandbox', '')}"
        )

    def _on_copy_mermaid(self) -> None:
        if self._current_graph is None:
            self._status.setText("先にチュートリアルを選択してください")
            return
        nodes = self._current_graph.get("nodes", [])
        edges = self._current_graph.get("edges", [])
        text = graph_to_mermaid(nodes, edges, simplify=self._simple_mode)
        QGuiApplication.clipboard().setText(text)
        mode_label = "簡易" if self._simple_mode else "詳細"
        self._status.setText(f"Mermaid記法（{mode_label}）をクリップボードにコピーしました")

    def _on_node_selected(self, node: dict) -> None:
        if node.get("kind") == "chain":
            member_ids = [m.get("id", "") for m in node.get("members", [])]
            self._detail.setText(
                f"[集約ノード] {len(member_ids)} ノードを折り畳み: " + " → ".join(member_ids)
            )
            return
        params = ", ".join(f"{k}={v}" for k, v in node.get("params", {}).items()) or "（デフォルト）"
        self._detail.setText(f"{node.get('id')}  |  {node.get('kind')}  |  {params}")
