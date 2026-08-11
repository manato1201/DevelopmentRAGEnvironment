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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    ) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        # 生成失敗時など、接続状態ランプ（rag_chatbot.py側、タブ全体で共有）に
        # 即時再確認を促すためのコールバック。ランプ自体はこのウィジェットの
        # 責務ではなくなったため、通知だけ行う。
        self._on_connection_event = on_connection_event or (lambda: None)
        self._worker: TutorialWorker | TutorialChainWorker | None = None
        self._agent = None            # 生成後もサンドボックス削除用に保持（単発生成モード）
        self._result = None           # TutorialResult（保存待ち。単発生成モードのみ）
        # 3段階連続生成（build_level_chain）モードで作られた (agent, result) の一覧。
        # チェーンモードは各レベルを自動保存するため、ここは「サンドボックス削除」用の
        # 参照保持だけが目的（単発生成モードでは常に空のまま）。
        self._chain_agents: list = []
        self._destroy_worker: _DestroySandboxWorker | None = None
        self._image_index_workers: list = []  # GC 防止のため参照を保持（rag_chatbot.pyのRateWorkerと同じ流儀）
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

    def _refresh_usage(self) -> None:
        bridge_dir = self._cfg_getter().get("local_bridge_dir", "")
        self._usage_widget.refresh(bridge_dir)

    # ── 生成 ────────────────────────────────────────────────────────────────────

    def _on_chain_toggled(self, checked: bool) -> None:
        # チェーンモードは常に3レベル全部を生成するため、単発用のレベル選択は無意味になる
        self._level_combo.setEnabled(not checked)

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
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn):
            btn.setEnabled(False)
        self._generate_btn.setEnabled(False)

        if self._chain_checkbox.isChecked():
            self._status.setText("3段階連続生成中（basic→applied→advanced）...")
            chain_kwargs = {
                "bridge_port": cfg.get("local_port", 8766),
                "project_dir": cfg.get("local_bridge_dir", ""),
                "rag_mode":    cfg.get("mode", "local"),
                "gas_url":     cfg.get("gas_url", ""),
                "gas_api_key": cfg.get("gas_api_key", ""),
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
            rag_mode=cfg.get("mode", "local"),
            gas_url=cfg.get("gas_url", ""),
            gas_api_key=cfg.get("gas_api_key", ""),
        )
        level = self._level_combo.currentText()
        self._worker = TutorialWorker(self._agent, topic, level=level)
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
            video_status = self._launch_video_for_result(result, md_path, json_path)
            status_parts.append(f"{result.level}: {md_path.name} 保存済み / {video_status}")
            self._index_screenshots_async(result)

        self._refresh_usage()
        self._preview.setMarkdown("\n\n---\n\n".join(preview_parts))
        # サンドボックスは3つ分（各レベル1つずつ）残る。「サンドボックス削除」は
        # _chain_agents 全件をまとめて削除する（_on_delete_sandbox 参照）。
        self._delete_sandbox_btn.setEnabled(True)
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
        """
        try:
            from video_factory_bridge import launch_video_generation

            return launch_video_generation(
                md_path=md_path,
                json_path=json_path,
                sandbox_path=result.sandbox_path,
                step_screenshots=result.step_screenshots,
                exe_path=self._cfg_getter().get("video_factory_exe_path", ""),
            )
        except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
            return f"動画生成の起動に失敗: {exc}"

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
        video_status = self._launch_video_for_result(self._result, md_path, json_path)
        self._status.setText(f"{self._status.text()} / {video_status}")
        self._index_screenshots_async(self._result)

    def _on_discard(self) -> None:
        self._result = None
        self._preview.clear()
        self._save_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._status.setText("破棄しました（サンドボックスは残っています。不要なら「サンドボックス削除」）")

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

    def __init__(self, cfg_getter: Callable[[], dict], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._current_graph: dict | None = None
        self._simple_mode: bool = True
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

        self._status = QLabel("")
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
        self._detail.setWordWrap(True)
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
        for path in files:
            label = path.stem
            difficulty = self._peek_difficulty(path)
            if difficulty:
                label = f"{label}  [{difficulty}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(path))
            self._list.addItem(item)
        self._status.setText(f"{len(files)} 件")

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
