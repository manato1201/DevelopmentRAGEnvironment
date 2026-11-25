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
    QFrame,
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
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import gallery_upload
import panel_debug as _debug
import panel_paths
import token_usage
import video_progress
import video_script as video_script_mod
import video_short
from panel_actions import (
    COLOR_ACCENT,
    COLOR_MUTED,
    COLOR_TEXT,
    Speaker,
    action_button,
    button_qss,
    normalize_fonts,
    px,
    type_font,
    type_qss,
)
from panel_widgets import CollapsibleBox, make_separator, ui_state_get, ui_state_set
from report_dialog import ReportDialog
from tutorial_graph_simplify import graph_to_mermaid, layered_positions, simplify_graph

# ノード数がこれを超えるチュートリアルを開いたときは既定で「簡易表示」にする
# （197ノード級の生成物をそのまま全表示すると判読不能になるため）。
_SIMPLIFY_THRESHOLD = 30

class _HideWhenEmptyLabel(QLabel):
    """文字が空のあいだは、場所も取らない(折り返しあり・横幅はレイアウト任せ。token_usage.fit_label と同じ)。"""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        token_usage.fit_label(self)
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:  # noqa: N802 - Qt の名前
        super().setText(text)
        self.setVisible(bool(text))


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

class FeedbackUploadWorker(QThread):
    """評価をCloudflareへ送る（ベストエフォート。UIを止めないよう別スレッド）。"""
    finished_with = Signal(bool, str)

    def __init__(self, cf_url: str, cf_api_key: str, payload: dict, md_path: Path | None = None, rated_at: str = "") -> None:
        super().__init__()
        self._cf_url, self._cf_api_key, self._payload = cf_url, cf_api_key, payload
        self._md_path, self._rated_at = md_path, rated_at

    def run(self) -> None:
        import tutorial_feedback

        ok, message = tutorial_feedback.upload_feedback(self._cf_url, self._cf_api_key, self._payload)
        if self._md_path is not None:
            if ok:
                tutorial_feedback.mark_uploaded(self._md_path, self._rated_at)  # 送信済みの印（これが無い評価は、次の起動で再送）
            else:
                message += "（未送信として残しました。次にパネルを開いたとき、自動で再送します）"
        self.finished_with.emit(ok, message)


class FeedbackResendWorker(QThread):
    """起動時に、未送信の評価をまとめて再送する（静かに。失敗しても、画面には出さない）。"""
    finished_with = Signal(dict)

    def __init__(self, tutorials_dir: Path, cf_url: str, cf_api_key: str) -> None:
        super().__init__()
        self._tutorials_dir, self._cf_url, self._cf_api_key = tutorials_dir, cf_url, cf_api_key

    def run(self) -> None:
        import tutorial_feedback

        try:
            self.finished_with.emit(tutorial_feedback.resend_pending(self._tutorials_dir, self._cf_url, self._cf_api_key))
        except Exception:  # noqa: BLE001 -- 再送の失敗で、パネルを止めない
            self.finished_with.emit({"sent": 0, "remaining": -1, "skipped": False})


class VideoScriptWorker(QThread):
    """動画用の「解説の台本」（チュートリアルのレベルに合わせた説明の深さ）を作る（Claude呼び出しは数十秒かかるので、UIを止めないよう別スレッド）。
    台本が作れなくても、動画は従来どおり作れる（その場合 script_path は空）。"""
    done = Signal(str, str)  # (台本ファイルのパス or "", 状態の説明)

    def __init__(self, make_agent, md_path: Path, step_screenshots: list, images: dict | None = None) -> None:
        super().__init__()
        self._make_agent, self._md_path, self._steps = make_agent, md_path, step_screenshots
        self._images = images or {}

    def run(self) -> None:
        try:
            import video_script

            complete = None
            try:
                complete = self._make_agent().complete_text
            except Exception:  # noqa: BLE001 -- Claudeに繋がらなくても、定型の解説で台本は作れる
                complete = None
            path, message = video_script.prepare_script_file(self._md_path, self._steps, complete, self._images)
            self.done.emit(str(path) if path else "", message)
        except Exception as exc:  # noqa: BLE001
            self.done.emit("", f"台本: 作成に失敗しました（{exc}）。従来の動画になります")


class GalleryUploadWorker(QThread):
    """動画を、ダッシュボードの「動画」ページ（ギャラリー）へアップロードする（数十MBを送るので、別スレッド）。"""
    progress = Signal(str)
    bytes_progress = Signal(int, str)  # (全体の進み具合 0〜100, 送っている動画の題名)
    done = Signal(str)  # 画面に出す結果の1行

    def __init__(self, url: str, token: str, output_dir: Path, only_ids: set[str] | None) -> None:
        super().__init__()
        self._url, self._token, self._output_dir, self._only_ids = url, token, output_dir, only_ids

    def run(self) -> None:
        try:
            def on_bytes(sent: int, total: int, label: str) -> None:
                self.bytes_progress.emit(int(sent * 100 / total) if total else 0, label)

            result = gallery_upload.upload_missing(
                self._url, self._token, self._output_dir, self._only_ids,
                progress=self.progress.emit, on_bytes=on_bytes,
            )
            self.done.emit(gallery_upload.describe_result(result))
        except gallery_upload.GalleryUploadError as exc:
            self.done.emit(f"アップロードできませんでした: {exc}")
        except Exception as exc:  # noqa: BLE001 -- スレッドから例外を出さない
            self.done.emit(f"アップロードに失敗しました: {exc}")


class LessonDistillWorker(QThread):
    """低評価のメモから、Claudeに「避けること」の教訓候補を作らせる。"""
    done = Signal(list)    # list[str]
    failed = Signal(str)

    def __init__(self, agent, bad_entries: list[dict], existing: list[str]) -> None:
        super().__init__()
        self._agent, self._bad, self._existing = agent, bad_entries, existing

    def run(self) -> None:
        try:
            import tutorial_feedback

            system, messages = tutorial_feedback.build_distill_request(self._bad, self._existing)
            response = self._agent._call_api([{"type": "text", "text": system}], [], messages)
            text = "".join(b.get("text", "") for b in response.get("content", []) if b.get("type") == "text")
            self.done.emit(tutorial_feedback.parse_lessons(text))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class LessonsDialog(QDialog):
    """
    教訓（過去の評価から得た「避けること」）の編集ダイアログ。チェックを入れたものだけが、次回以降の
    生成のシステムプロンプトに入る（承認制。最大 MAX_APPROVED_LESSONS 件）。低評価のメモからClaudeに
    候補を作らせることもできるが、候補は未承認で追加し、内容を読んでから自分でチェックを入れる。
    """

    def __init__(self, parent, project_dir: str, tutorials_dir: Path | None, make_agent: Callable) -> None:
        super().__init__(parent)
        import tutorial_feedback

        self._fb = tutorial_feedback
        self._project_dir = project_dir
        self._tutorials_dir = tutorials_dir
        self._make_agent = make_agent
        self._worker: LessonDistillWorker | None = None
        self.setWindowTitle("教訓（過去の評価から得た「避けること」）")
        self.resize(640, 460)

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"チェックを入れた教訓だけが、次回以降の生成のプロンプトに入ります（最大{tutorial_feedback.MAX_APPROVED_LESSONS}件）。"
            "文をダブルクリックで編集できます。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#94a3b8;font-size:11px;")
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.itemChanged.connect(self._update_count)
        layout.addWidget(self._list, stretch=1)

        add_row = QHBoxLayout()
        self._add_edit = QLineEdit()
        self._add_edit.setPlaceholderText("教訓を自分で追加（例: ノード数は5個以内に収める）")
        self._add_edit.returnPressed.connect(self._on_add)
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton("選択を削除")
        del_btn.clicked.connect(self._on_delete)
        add_row.addWidget(self._add_edit, stretch=1)
        add_row.addWidget(add_btn)
        add_row.addWidget(del_btn)
        layout.addLayout(add_row)

        distill_row = QHBoxLayout()
        self._distill_btn = QPushButton("👎のメモから候補を作る（Claudeを1回呼びます）")
        self._distill_btn.clicked.connect(self._on_distill)
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color:#7dd3fc;font-size:11px;")
        distill_row.addWidget(self._distill_btn)
        distill_row.addWidget(self._count_label)
        distill_row.addStretch()
        layout.addLayout(distill_row)

        self._status = token_usage.fit_label(QLabel(""))
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;")
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        save_btn = QPushButton("保存して閉じる")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        for lesson in self._fb.load_lessons(project_dir):
            self._add_item(lesson["text"], lesson["approved"])
        self._update_count()

    def _add_item(self, text: str, approved: bool) -> None:
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
        item.setCheckState(Qt.Checked if approved else Qt.Unchecked)
        self._list.addItem(item)

    def _lessons(self) -> list[dict]:
        import datetime

        now = datetime.date.today().isoformat()
        return [
            {"text": self._list.item(i).text().strip()[: self._fb.MAX_LESSON_CHARS],
             "approved": self._list.item(i).checkState() == Qt.Checked, "created": now}
            for i in range(self._list.count()) if self._list.item(i).text().strip()
        ]

    def _update_count(self, *_args) -> None:
        approved = sum(1 for lesson in self._lessons() if lesson["approved"])
        limit = self._fb.MAX_APPROVED_LESSONS
        over = "（上限超過。先頭から使われます）" if approved > limit else ""
        self._count_label.setText(f"承認 {approved}/{limit}{over}")

    def _on_add(self) -> None:
        text = self._add_edit.text().strip()
        if text:
            self._add_item(text[: self._fb.MAX_LESSON_CHARS], True)
            self._add_edit.clear()
            self._update_count()

    def _on_delete(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self._update_count()

    def _on_distill(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        entries = [
            e for e in (self._fb.list_entries(self._tutorials_dir) if self._tutorials_dir else [])
            if e["rating"] == -1 and (e["note"] or e["tags"])
        ]
        if not entries:
            self._status.setText("タグかメモの付いた👎がまだありません。評価にタグやメモを付けてから試してください")
            return
        try:
            agent = self._make_agent()
        except Exception as exc:  # noqa: BLE001
            self._status.setText(f"Claudeの呼び出し準備に失敗: {exc}")
            return
        existing = [lesson["text"] for lesson in self._lessons()]
        self._distill_btn.setEnabled(False)
        self._status.setText(f"👎 {len(entries)} 件から候補を作っています…")
        self._worker = LessonDistillWorker(agent, entries, existing)
        self._worker.done.connect(self._on_distilled)
        self._worker.failed.connect(self._on_distill_failed)
        self._worker.start()

    def _on_distilled(self, candidates: list) -> None:
        self._distill_btn.setEnabled(True)
        known = {lesson["text"] for lesson in self._lessons()}
        added = 0
        for text in candidates:
            if text and text not in known:
                self._add_item(text, False)  # 候補は未承認。読んでから自分でチェックを入れる
                added += 1
        self._update_count()
        self._status.setText(
            f"{added} 件の候補を追加しました（未承認）。内容を確認して、使うものにチェックを入れてください"
            if added else "新しい候補はありませんでした（根拠が弱いか、既存の教訓と重複）"
        )

    def _on_distill_failed(self, message: str) -> None:
        self._distill_btn.setEnabled(True)
        self._status.setText(f"候補の作成に失敗: {message}")

    def _on_save(self) -> None:
        lessons = self._lessons()
        limit = self._fb.MAX_APPROVED_LESSONS
        if sum(1 for lesson in lessons if lesson["approved"]) > limit:
            self._status.setText(f"承認は最大{limit}件までです。チェックを減らしてください")
            return
        if not self._fb.save_lessons(self._project_dir, lessons):
            self._status.setText("保存に失敗しました（保存先フォルダを確認してください）")
            return
        self.accept()


def _build_light_agent(cfg: dict):
    """Claudeを1回呼ぶだけの用途（台本づくり・教訓の候補作り）のエージェント。生成時と同じ設定で、
    サンドボックスは作らない。TutorialGeneratePanel と TutorialHistoryPanel の両方が使う
    （2026-10-21: 台本づくりが、持っていない self._make_agent を呼んで動画生成が始まらなかった）。"""
    from tutorial_agent import TutorialAgent

    return TutorialAgent(
        bridge_port=cfg.get("local_port", 8766),
        project_dir=cfg.get("local_bridge_dir", ""),
        rag_mode=cfg.get("mode", "local"),
        model=cfg.get("tutorial_model", "claude-sonnet-5-5"),
        cf_url=cfg.get("cf_url", ""),
        cf_api_key=cfg.get("cf_api_key", ""),
        rag_namespace=cfg.get("tutorial_rag_namespace", ""),
    )


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
        self._script_workers: list[VideoScriptWorker] = []  # 台本づくりの実行中スレッド（参照を保持）
        # 直近のチェーン生成（3段階連続生成）で実際にディスクへ書き出した
        # (level, md_path, json_path) の一覧（2026-09-20追加）。チェーンモードは
        # プレビュー確認なしで自動保存するため、結果が気に入らなかった場合に
        # 手動でファイルを探して消す手間をなくす「生成した3件を削除」ボタン用。
        self._chain_saved_paths: list[tuple[str, Path, Path]] = []
        self._build_ui()
        normalize_fonts(self)  # px のフォントを pt に揃える(4K・拡大表示で文字と部品の大きさがずれないように)

    def _build_ui(self) -> None:
        # 画面の構成（2026-11-18 整理）。上から「何を作るか（トピック・条件・レベル）→ 生成」「詳細設定（折りたたみ）」
        # →「状態（いま何をしているか・動画の進み・コスト）」→「進行ログ / プレビュー」→「結果の操作（保存・動画・評価）」。
        # 全体を 1 つのスクロール領域に入れ、ペインが低いときは縦に詰めずにスクロールさせる。文字の大きさは
        # panel_actions のタイプスケール（heading / body / caption / code）、部品の寸法は px(n)。
        self.setFont(type_font("body"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self._scroll)
        body = QWidget()
        self._scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(px(8), px(8), px(8), px(8))
        layout.setSpacing(px(8))

        # ── 1. 何を作るか: トピック → 生成 ─────────────────────────────────────
        topic_box = QVBoxLayout()
        topic_box.setSpacing(px(4))
        topic_caption = QLabel("トピック")
        topic_caption.setStyleSheet(type_qss("heading", COLOR_TEXT))
        topic_box.addWidget(topic_caption)
        input_row = QHBoxLayout()
        input_row.setSpacing(px(6))
        self._topic_edit = QLineEdit()
        self._topic_edit.setMinimumHeight(px(32))
        self._topic_edit.setPlaceholderText("例: 岩を地形に散布するプロシージャルセットアップ")
        self._topic_edit.returnPressed.connect(self._on_generate)
        self._generate_btn = QPushButton("生成")
        self._generate_btn.setStyleSheet(button_qss("primary"))
        self._generate_btn.setMinimumSize(px(72), px(32))
        self._generate_btn.setCursor(Qt.PointingHandCursor)
        self._generate_btn.setToolTip("トピックと生成条件からチュートリアルを生成します（トピック欄で Enter でも始まります）")
        self._generate_btn.clicked.connect(self._on_generate)
        input_row.addWidget(self._topic_edit, stretch=1)
        input_row.addWidget(self._generate_btn)
        topic_box.addLayout(input_row)
        layout.addLayout(topic_box)

        # 生成条件（自由記述、2026-10-05追加）。トピックだけだと「ガウシアンスプラット」のような
        # 指定が「それ風」の代用で済まされることがあったため、必ず守らせたい条件を別欄で渡す。
        # 条件はトピックより優先され、満たせなかった場合は pitfalls に理由が書かれる。
        cond_box = QVBoxLayout()
        cond_box.setSpacing(px(4))
        cond_head = QHBoxLayout()
        cond_head.setSpacing(px(8))
        cond_label = QLabel("生成条件")
        cond_label.setStyleSheet(type_qss("heading", COLOR_TEXT))
        cond_hint = token_usage.fit_label(QLabel("任意。必ず守ってほしい条件（トピックより優先）"))
        cond_hint.setStyleSheet(type_qss("caption", COLOR_MUTED))
        cond_head.addWidget(cond_label)
        cond_head.addWidget(cond_hint, stretch=1)
        cond_box.addLayout(cond_head)
        self._requirements_edit = QTextEdit()
        self._requirements_edit.setAcceptRichText(False)
        self._requirements_edit.setFixedHeight(px(58))
        self._requirements_edit.setPlaceholderText(
            "例: ガウシアンスプラットを実際に使う / SOPだけで作る / Karmaは使わない"
        )
        self._requirements_edit.setToolTip(
            "ここに書いた条件はトピックより優先されます。条件にある技法は「それ風」の代用ではなく実際に使わせます。\n"
            "満たせなかった場合は、チュートリアルの「ハマりポイント」に理由が書かれます。"
        )
        cond_box.addWidget(self._requirements_edit)
        layout.addLayout(cond_box)

        # レベル選択行（IMPROVEMENT_PLAN.md Phase1: RAGレベリング）。
        # 「3段階連続生成」がオンのときはレベル選択は無視され、常に
        # basic→applied→advanced の順で3本まとめて生成・自動保存する。
        level_row = QHBoxLayout()
        level_row.setSpacing(px(8))
        level_label = QLabel("レベル")
        level_label.setStyleSheet(type_qss("heading", COLOR_TEXT))
        level_row.addWidget(level_label)
        self._level_combo = QComboBox()
        self._level_combo.addItems(["basic", "applied", "advanced"])
        self._level_combo.setToolTip(
            "basic（レッスン1）: 基本操作は分かる人向け。パラメータを動かして仕組みを理解する\n"
            "applied（レッスン2）: 実務で使える形（再利用・バリエーション・書き出し）。設計の理由まで説明\n"
            "advanced（レッスン3）: 設計の判断。別構成との比較・規模・壊れる条件を、数値で示す\n"
            "説明の言葉の難しさと深さ、解説動画のナレーションも、段階に合わせて変わります"
        )
        level_row.addWidget(self._level_combo)
        level_row.addStretch()
        layout.addLayout(level_row)
        self._chain_checkbox = QCheckBox("3段階まとめて生成（自動保存）")
        self._chain_checkbox.setToolTip(
            "オンにすると同一トピックでbasic→applied→advancedを順に生成し、"
            "前段の内容を次段のプロンプトへ引き継ぎます。生成時間・コストは単発の最大3倍。\n"
            "各レベルはプレビュー確認なしで自動的にlocalRAG/tutorials/へ保存されます。\n"
            "オンの間は、左のレベル選択は使われません。"
        )
        self._chain_checkbox.toggled.connect(self._on_chain_toggled)
        # 高速モード（2026-11-19）: 生成の時間を縮める（effort を下げ、レッスン設計を省き、手順書を短く）。説明は、短めになる。
        self._fast_checkbox = QCheckBox("高速モード（生成を速く。説明は短め）")
        self._fast_checkbox.setToolTip(
            "生成の時間を縮めます（思考を浅くし、レッスン設計を省き、手順書の本文を短くさせます）。\n"
            "品質への影響は、同じ題材で、通常モードと比べて確かめてください（保存される metrics に fast_mode が記録されます）。\n"
            "3段階まとめて生成には使われません。"
        )
        self._fast_checkbox.setChecked(bool(ui_state_get("tutorial_fast_mode", False)))
        self._fast_checkbox.toggled.connect(lambda on: ui_state_set("tutorial_fast_mode", bool(on)))
        layout.addWidget(self._fast_checkbox)
        layout.addWidget(self._chain_checkbox)  # 狭いペインでも折れ曲がらないよう、レベルの下に独立した行で置く

        # ── 2. 詳細設定（めったに触らないものは折りたたむ）──────────────────────
        # 参考画像（テキスト＋画像での生成、2026-10-05追加）。テキストのトピックだけだと
        # 求める完成イメージからズレることがあるため、スクショ・写真・ラフ等を添えられる。
        # 添付は生成を開始してもクリアされない（同じ画像で作り直せる）。ラベルは長いファイル名で
        # パネルが横に広がらないよう fit_label で折り返す。
        # 対象モデル（アニメーション・リギング用、2026-10-05追加）。選んだモデルファイルを
        # 読み込んで、その上でリグ・アニメーションを作らせる。読み取り専用で、サンドボックス内に
        # File SOP / KineFXのインポートノードとして読み込まれる（元ファイルは変更しない）。
        advanced = QWidget()
        adv_layout = QVBoxLayout(advanced)
        adv_layout.setContentsMargins(px(14), px(2), 0, px(4))
        adv_layout.setSpacing(px(4))

        self._reference_paths: list[str] = []
        ref_caption = QLabel("参考画像")
        ref_caption.setStyleSheet(type_qss("caption", COLOR_MUTED))
        adv_layout.addWidget(ref_caption)
        ref_row = QHBoxLayout()
        ref_row.setSpacing(px(6))
        self._ref_add_btn = QPushButton("画像を選ぶ…")
        self._ref_add_btn.setToolTip("完成イメージの参考になる画像（png/jpg/webp等）を選びます。最大4枚。")
        self._ref_add_btn.clicked.connect(self._on_add_reference_images)
        self._ref_paste_btn = QPushButton("貼り付け")
        self._ref_paste_btn.setToolTip("コピーしてある画像（スクリーンショット等）を参考画像として追加します。")
        self._ref_paste_btn.clicked.connect(self._on_paste_reference_image)
        self._ref_clear_btn = QPushButton("クリア")
        self._ref_clear_btn.setToolTip("選んだ参考画像をすべて外します。")
        self._ref_clear_btn.clicked.connect(self._on_clear_reference_images)
        ref_row.addWidget(self._ref_add_btn)
        ref_row.addWidget(self._ref_paste_btn)
        ref_row.addWidget(self._ref_clear_btn)
        ref_row.addStretch()
        adv_layout.addLayout(ref_row)
        self._ref_label = token_usage.fit_label(QLabel(""))
        self._ref_label.setStyleSheet(type_qss("caption", COLOR_ACCENT))
        adv_layout.addWidget(self._ref_label)

        self._target_model_path: str = ""
        model_caption = QLabel("対象モデル")
        model_caption.setStyleSheet(type_qss("caption", COLOR_MUTED))
        adv_layout.addWidget(model_caption)
        model_row = QHBoxLayout()
        model_row.setSpacing(px(6))
        self._model_pick_btn = QPushButton("モデルを選ぶ…")
        self._model_pick_btn.setToolTip(
            "アニメーション・リギングのチュートリアルで使うモデル（fbx / glb / gltf / usd / obj / bgeo / abc）を選びます。\n"
            "ファイルは読み取り専用で、書き換えません。"
        )
        self._model_pick_btn.clicked.connect(self._on_pick_target_model)
        self._model_clear_btn = QPushButton("クリア")
        self._model_clear_btn.setToolTip("選んだ対象モデルを外します。")
        self._model_clear_btn.clicked.connect(self._on_clear_target_model)
        model_row.addWidget(self._model_pick_btn)
        model_row.addWidget(self._model_clear_btn)
        model_row.addStretch()
        adv_layout.addLayout(model_row)
        self._model_label = token_usage.fit_label(QLabel(""))
        self._model_label.setStyleSheet(type_qss("caption", COLOR_ACCENT))
        adv_layout.addWidget(self._model_label)

        self._advanced_box = CollapsibleBox(
            self._ADVANCED_TITLE, advanced, collapsed=True, state_key="tutorial_generate_advanced", left_align=True
        )
        layout.addWidget(self._advanced_box)
        self._refresh_reference_label()
        self._refresh_model_label()

        # ── 3. 状態（いま何をしているか・動画の進み・コスト）を 1 か所に ───────────
        card = QFrame()
        card.setObjectName("tgCard")
        card.setStyleSheet("QFrame#tgCard{border:1px solid #334155;border-radius:%dpx;}" % px(6))
        self._state_card = card
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(px(10), px(8), px(10), px(8))
        card_layout.setSpacing(px(6))
        state_caption = QLabel("状態")
        state_caption.setStyleSheet(type_qss("heading", COLOR_TEXT))
        card_layout.addWidget(state_caption)
        self._status = token_usage.fit_label(QLabel("トピックを入力して「生成」を押してください"))
        self._status.setStyleSheet(type_qss("body", COLOR_TEXT))
        card_layout.addWidget(self._status)

        # 動画生成の進捗表示（2026-08-31追加）。
        # 2026-10-21: プログレスバー（台本 → 音声 → 描画 → 完了の全体の％。video_progress.py）。動画を作っていない間は隠す。
        self._video_bar = QProgressBar()
        self._video_bar.setRange(0, 100)
        self._video_bar.setTextVisible(True)
        self._video_bar.setFixedHeight(px(20))
        self._video_bar.setVisible(False)
        card_layout.addWidget(self._video_bar)
        self._script_timer = QTimer(self)
        self._script_timer.setInterval(1000)
        self._script_timer.timeout.connect(self._on_script_tick)
        self._script_elapsed = 0.0
        self._video_progress = _HideWhenEmptyLabel()
        self._video_progress.setStyleSheet(type_qss("caption", COLOR_ACCENT))
        card_layout.addWidget(self._video_progress)

        card_layout.addWidget(make_separator())
        # 累積トークン消費量ゲージ（小さく左に置き、文字を右に並べる）
        self._usage_widget = token_usage.TokenUsageWidget(compact=True)
        card_layout.addWidget(self._usage_widget)
        self._refresh_usage()
        layout.addWidget(card)

        # 生成中の注意（2026-11-24。生成は、Houdini のシーンを操作し、画面を撮る。その最中に触ると、撮り直しや崩れの元になる）
        self._busy_banner = QLabel("生成中です。Houdini の画面（ネットワーク・ビューポート・時間）は、触らないでください。終わると、この表示が消えます。")
        self._busy_banner.setWordWrap(True)
        self._busy_banner.setStyleSheet("QLabel{background:#7c4a03;color:#fef3c7;border-radius:%dpx;padding:%dpx %dpx;}" % (px(4), px(6), px(8)))
        self._busy_banner.setVisible(False)
        layout.addWidget(self._busy_banner)

        # ── 4. 進行ログとプレビューを縦分割（ペインが低いときは、全体のスクロールで見る）─
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setMinimumHeight(px(250))

        log_box = QWidget()
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(px(3))
        log_caption = QLabel("進行ログ")
        log_caption.setStyleSheet(type_qss("caption", COLOR_MUTED))
        log_layout.addWidget(log_caption)
        self._progress_log = QTextEdit()
        self._progress_log.setReadOnly(True)
        self._progress_log.setPlaceholderText("どのツールを呼んでいるかがここに表示されます")
        self._progress_log.setStyleSheet(type_qss("code"))
        self._progress_log.setMinimumHeight(px(70))
        log_layout.addWidget(self._progress_log)
        splitter.addWidget(log_box)

        preview_box = QWidget()
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(px(3))
        preview_caption = token_usage.fit_label(QLabel("プレビュー（「保存」を押すまで、ファイルは書き込まれません）"))
        preview_caption.setStyleSheet(type_qss("caption", COLOR_MUTED))
        preview_layout.addWidget(preview_caption)
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("生成が完了すると Markdown プレビューがここに表示されます")
        self._preview.setMinimumHeight(px(130))
        preview_layout.addWidget(self._preview)
        splitter.addWidget(preview_box)
        splitter.setSizes([px(130), px(340)])
        layout.addWidget(splitter, stretch=1)

        # ── 5. 結果の操作: 保存（主）・破棄（危険）→ 評価 → 動画 → 後片付け（危険）────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(px(6))
        self._save_btn = QPushButton("保存")
        self._save_btn.setToolTip("localRAG/tutorials/ に保存します（保存するまでファイルは書き込まれません）")
        self._save_btn.setStyleSheet(button_qss("primary"))
        self._save_btn.setMinimumSize(px(96), px(32))
        self._save_btn.clicked.connect(self._on_save)
        self._discard_btn = QPushButton("破棄")
        self._discard_btn.setToolTip("保存せずに、このプレビューを捨てます（サンドボックスは残ります）")
        self._discard_btn.setStyleSheet(button_qss("danger"))
        self._discard_btn.setMinimumHeight(px(32))
        self._discard_btn.clicked.connect(self._on_discard)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._discard_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 追加指示（2026-11-18）: できたチュートリアルに、「ここを変えて」「これを足して」と伝えて、続きを作る。
        # 前の結果を土台にして（題・概要・手順の見出しを必須条件に入れて）、もう一度生成する。新しい結果は、完全な手順になる。
        # 生成にかかる時間と費用は、1 回分かかる。保存していない前の結果は、破棄される。
        followup_content = QWidget()
        followup_layout = QVBoxLayout(followup_content)
        followup_layout.setContentsMargins(0, 0, 0, 0)
        followup_layout.setSpacing(px(4))
        self._followup_edit = QTextEdit()
        self._followup_edit.setAcceptRichText(False)
        self._followup_edit.setFixedHeight(px(54))
        self._followup_edit.setPlaceholderText("例: 光を青にして、粒の数を倍にする／最後に、公開パラメータを HDA にまとめる手順を足す")
        followup_layout.addWidget(self._followup_edit)
        followup_note = token_usage.fit_label(QLabel("前の結果を土台に、もう一度生成します（時間と費用が、1 回分かかります。保存していない前の結果は、破棄されます）"))
        followup_note.setStyleSheet(type_qss("caption", COLOR_MUTED))
        followup_layout.addWidget(followup_note)
        self._followup_btn = QPushButton("追加指示で作り直す")
        self._followup_btn.setEnabled(False)
        self._followup_btn.clicked.connect(self._on_followup)
        followup_layout.addWidget(self._followup_btn)
        self._followup_box = CollapsibleBox(
            "追加指示（この結果に足して、続きを作る）", followup_content, collapsed=True, state_key="tutorial_followup", left_align=True
        )
        layout.addWidget(self._followup_box)

        # 保存した直後だけ出す、控えめな評価の行（2026-10-28）。評価は任意。ポップアップにはせず、保存1回につき1度だけ。
        # 押さなければ、そのまま消える（履歴タブでも、あとから付けられる）。次の生成を始める・破棄するときにも消える。
        self._rate_row = QWidget()
        rate_layout = QHBoxLayout(self._rate_row)
        rate_layout.setContentsMargins(0, 0, 0, 0)
        rate_hint = token_usage.fit_label(QLabel("評価（任意）"))
        rate_hint.setStyleSheet(type_qss("caption", COLOR_MUTED))
        rate_hint.setToolTip("履歴タブでも、あとから付けられます")
        self._rate_good_btn = action_button("thumbUp", "良い(このチュートリアルを「良い」と評価して保存)")
        self._rate_bad_btn = action_button("thumbDown", "悪い(このチュートリアルを「悪い」と評価して保存)")
        for btn, rating in ((self._rate_good_btn, 1), (self._rate_bad_btn, -1)):
            btn.clicked.connect(lambda _checked=False, r=rating: self._on_quick_rate(r))
        rate_layout.addWidget(rate_hint, stretch=1)
        rate_layout.addWidget(self._rate_good_btn)
        rate_layout.addWidget(self._rate_bad_btn)
        self._rate_row.setVisible(False)
        layout.addWidget(self._rate_row)
        self._rate_md_path: Path | None = None
        self._rate_worker: FeedbackUploadWorker | None = None

        # 動画の再生。2026-09-13追加: Houdini埋め込みのQtWebEngineプレイヤーが「再生中のまま0:00から
        # 進まない」事例が報告された（ffmpegでの単体デコードは正常なため、ファイル破損では
        # なくHoudini本体とのGPUコンテキスト競合が濃厚）。埋め込み再生に問題があっても
        # 動画自体は見られるよう、OS標準プレイヤー（Houdiniと別プロセス）で開く手段を
        # 常に用意しておく。
        video_row = QHBoxLayout()
        video_row.setSpacing(px(6))
        self._preview_btn = QPushButton("▶ プレビュー再生")
        self._preview_btn.setToolTip("生成した解説動画を、パネルの中で再生します")
        self._preview_btn.setEnabled(False)
        self._preview_btn.clicked.connect(self._on_preview_video)
        video_row.addWidget(self._preview_btn)
        self._external_player_btn = QPushButton("外部で開く")
        self._external_player_btn.setToolTip("OS標準の動画プレイヤー（Houdiniとは別のプロセス）で開きます")
        self._external_player_btn.setEnabled(False)
        self._external_player_btn.clicked.connect(self._on_open_in_external_player)
        video_row.addWidget(self._external_player_btn)
        video_row.addStretch()
        layout.addLayout(video_row)

        # 後片付け（危険）。3段階連続生成（チェーンモード）は確認なしで自動保存するため、結果が
        # 気に入らなかった場合に保存済みファイル一式を手動で探さず消せるようにする（2026-09-20追加）。
        # 単発生成の「破棄」（保存前の内容をメモリ上で破棄するだけ）とは意味が異なるため別ボタンにしている。
        cleanup_row = QHBoxLayout()
        cleanup_row.setSpacing(px(6))
        self._delete_sandbox_btn = QPushButton("サンドボックス削除")
        self._delete_sandbox_btn.setToolTip("この生成で作った Houdini のサンドボックス（作業用の一時シーン）を削除します")
        self._delete_sandbox_btn.clicked.connect(self._on_delete_sandbox)
        self._discard_chain_btn = QPushButton("3件を削除")
        self._discard_chain_btn.setToolTip("直近の「3段階まとめて生成」で自動保存した3件（.md / .json など）を削除します")
        self._discard_chain_btn.clicked.connect(self._on_discard_chain_saves)
        for btn in (self._delete_sandbox_btn, self._discard_chain_btn):
            btn.setStyleSheet(button_qss("danger"))
        cleanup_row.addWidget(self._delete_sandbox_btn)
        cleanup_row.addWidget(self._discard_chain_btn)
        cleanup_row.addStretch()
        layout.addLayout(cleanup_row)
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn, self._discard_chain_btn):
            btn.setEnabled(False)

    _ADVANCED_TITLE = "詳細設定（参考画像・対象モデル）"

    def _refresh_advanced_title(self) -> None:
        """折りたたんだままでも、選んだものが分かるように、見出しに要約を出す。"""
        box = getattr(self, "_advanced_box", None)
        if box is None:
            return
        parts: list[str] = []
        if self._reference_paths:
            parts.append(f"参考画像 {len(self._reference_paths)}枚")
        if self._target_model_path:
            parts.append(f"モデル {Path(self._target_model_path).name}")
        box.set_title(self._ADVANCED_TITLE + (" — " + " / ".join(parts) if parts else ""))

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
        else:
            names = ", ".join(Path(p).name for p in self._reference_paths)
            self._ref_label.setText(f"参考画像 {len(self._reference_paths)}枚: {names}（テキスト＋画像で生成します）")
            self._ref_label.setToolTip("\n".join(self._reference_paths))
        self._refresh_advanced_title()

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

    def _refresh_model_label(self) -> None:
        if not self._target_model_path:
            self._model_label.setText("対象モデル: なし（アニメーション・リギングで使うモデルを選べます）")
            self._model_label.setToolTip("")
        else:
            self._model_label.setText(f"対象モデル: {Path(self._target_model_path).name}（このモデルを使って生成します）")
            self._model_label.setToolTip(self._target_model_path)
        self._refresh_advanced_title()

    def _on_pick_target_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "対象モデルを選択", "",
            "3Dモデル (*.fbx *.glb *.gltf *.usd *.usda *.usdc *.usdz *.obj *.bgeo *.sc *.abc *.ply);;すべてのファイル (*)",
        )
        if path:
            self._target_model_path = path
            self._refresh_model_label()

    def _on_clear_target_model(self) -> None:
        self._target_model_path = ""
        self._refresh_model_label()

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
        self._start_generation()

    def _start_generation(self, requirements_override: str | None = None) -> None:
        """生成を始める。requirements_override があるとき（追加指示で作り直すとき）は、入力欄の条件ではなく、それを必須条件にする
        （入力欄は書き換えない）。このときは、3段階連続生成にはしない。"""
        if self._worker and self._worker.isRunning():
            return
        topic = self._topic_edit.text().strip()
        if not topic:
            self._status.setText("トピックを入力してください")
            return
        followup = requirements_override is not None
        requirements = requirements_override if followup else self._requirements_edit.toPlainText().strip()

        cfg = self._cfg_getter()
        try:
            import tutorial_agent  # noqa: F401 -- 存在確認のみ（実際のimportは各分岐で行う）
        except ImportError as exc:
            self._status.setText(f"tutorial_agent の読み込みに失敗: {exc}")
            return

        self._hide_rating_row()
        self._progress_log.clear()
        self._preview.clear()
        self._result = None
        self._agent = None  # 前回（単発/チェーン問わず）の参照を残さない
        self._chain_agents = []
        self._chain_saved_paths = []
        for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn, self._discard_chain_btn, self._followup_btn):
            btn.setEnabled(False)
        self._generate_btn.setEnabled(False)
        self._set_busy(True)

        if self._chain_checkbox.isChecked() and not followup:
            self._status.setText("3段階連続生成中（basic→applied→advanced）...")
            chain_kwargs = {
                "bridge_port":    cfg.get("local_port", 8766),
                "project_dir":    cfg.get("local_bridge_dir", ""),
                # RAG検索先はチャットの mode 設定（local / cloudflare）に従う
                "rag_mode":       cfg.get("mode", "local"),
                "model":          cfg.get("tutorial_model", "claude-sonnet-5-5"),
                "cf_url":         cfg.get("cf_url", ""),
                "cf_api_key":     cfg.get("cf_api_key", ""),
                "rag_namespace":  cfg.get("tutorial_rag_namespace", ""),
                "reference_images": list(self._reference_paths),
                "requirements":   requirements,
                "target_model":   self._target_model_path,
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
            model=cfg.get("tutorial_model", "claude-sonnet-5-5"),
            cf_url=cfg.get("cf_url", ""),
            cf_api_key=cfg.get("cf_api_key", ""),
            rag_namespace=cfg.get("tutorial_rag_namespace", ""),
            reference_images=list(self._reference_paths),
            requirements=requirements,
            target_model=self._target_model_path,
            fast=self._fast_checkbox.isChecked(),
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

    def _on_followup(self) -> None:
        """追加指示で、前の結果を土台に、もう一度生成する（tutorial_followup.build_requirements）。"""
        if self._result is None or (self._worker and self._worker.isRunning()):
            return
        import tutorial_followup

        instruction = tutorial_followup.clean_instruction(self._followup_edit.toPlainText())
        if not instruction:
            self._status.setText("追加指示を入力してください")
            return
        result = self._result
        requirements = tutorial_followup.build_requirements(
            self._requirements_edit.toPlainText().strip(), self._topic_edit.text().strip(),
            getattr(result, "title", ""), getattr(result, "markdown", ""), instruction,
        )
        self._start_generation(requirements_override=requirements)
        self._progress_log.append(f"追加指示で作り直します: {instruction}")
        self._followup_edit.clear()

    def _on_progress(self, text: str) -> None:
        self._progress_log.append(text)
        sb = self._progress_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    @_debug.guard("生成", restore="_restore_after_error")
    def _on_done(self, result) -> None:
        self._set_busy(False)
        self._result = result
        bridge_dir = self._cfg_getter().get("local_bridge_dir", "")
        token_usage.record_usage(bridge_dir, self._topic_edit.text().strip(), result)
        # result.claude_balance/capacity は Cloudflare（/me/budget）が返した、そのAPIキーの
        # 実際の残高/上限。これが唯一の正なので、
        # ローカルではキャッシュ（表示専用）に保存するだけで判定には使わない。
        # 無制限キーはbalance/capacityが両方Noneになるため、claude_quota_known
        # （残高の取得に成功したか）で判定する。
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
        self._followup_btn.setEnabled(True)  # 追加指示で、続きを作れる
        state = "完了" if result.completed else f"途中経過（{result.abort_reason}）"
        self._status.setText(
            f"{state} — ${result.cost_usd:.3f} / {result.iterations} ステップ。"
            "内容を確認して「保存」を押してください（保存するまでファイルは書き込まれません）"
        )
        # 2026-11-17: 生成が終わったら、Guide タブを最新の手順にして、切り替える（切り替わりに気づかなかったという指摘）。
        # 保存前でも、手順は Guide タブで使える。切り替えない設定のときは、Guide タブの名前に印が付く。
        guide_note = self._announce_guide(result)
        if guide_note:
            self._status.setText(f"{self._status.text()} / {guide_note}")

    def _announce_guide(self, result) -> str:
        """生成の結果から手順を作って、Guide タブへ渡す（ベストエフォート。失敗しても、生成の結果の表示は止めない）。"""
        try:
            import guide_mode
            import guide_view

            guide = guide_mode.guide_from_result(result)
            if not guide["steps"]:
                return ""
            return guide_view.announce_generated(self, guide, guide_mode.guide_label(guide))
        except Exception:  # noqa: BLE001
            return ""

    def _announce_guide_saved(self, md_path: Path, switch: bool | None = None) -> str:
        """保存で書かれた案内データを、Guide タブで選ぶ（ベストエフォート）。"""
        try:
            import guide_mode
            import guide_view

            guide_path = guide_mode.guide_path_for(md_path)
            if not guide_path.exists():
                return ""
            return guide_view.announce_saved(self, guide_path, switch)
        except Exception:  # noqa: BLE001
            return ""

    @_debug.guard("生成", restore="_restore_after_error")
    def _on_chain_done(self, results: list) -> None:
        """
        3段階連続生成（build_level_chain）の完了コールバック。単発生成と違い、
        3件のプレビュー確認を個別に求めるUXは複雑になりすぎるため、各レベルを
        その場で自動的に localRAG/tutorials/ へ保存する（チェックボックスの
        ツールチップで事前に明示している仕様）。
        """
        self._set_busy(False)
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
        # 2026-11-17: 3段階とも保存したので、Guide タブを最新（最後に保存した手順）にして、切り替える
        if self._chain_saved_paths:
            guide_note = self._announce_guide_saved(self._chain_saved_paths[-1][1])
            if guide_note:
                self._status.setText(f"{self._status.text()} | {guide_note}")

    def _set_busy(self, busy: bool) -> None:
        """生成中の注意書き（Houdini を触らないで）を、出す・消す。"""
        banner = getattr(self, "_busy_banner", None)
        if banner is not None:
            banner.setVisible(busy)

    def _restore_after_error(self, exc: BaseException) -> None:
        """完了・失敗の処理の途中で例外が出たとき、ボタンを使える状態に戻す（無効のまま残ると、タブの切り替えしか効かなくなる。2026-11-24）。
        結果が既にあれば、保存・破棄なども使えるようにする。例外の内容は、デバッグの記録（メニュー ≡ →「デバッグ」）に残っている。"""
        self._set_busy(False)
        self._generate_btn.setEnabled(True)
        if self._result is not None:
            for btn in (self._save_btn, self._discard_btn, self._delete_sandbox_btn, self._followup_btn):
                btn.setEnabled(True)
        self._status.setText(f"生成の後処理でエラーが出ました（内容は、メニュー ≡ →「デバッグ」）: {type(exc).__name__}: {str(exc)[:120]}")

    @_debug.guard("生成", restore="_restore_after_error")
    def _on_failed(self, msg: str) -> None:
        self._set_busy(False)
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
                panel_paths.SAVE_DIR_MISSING + "。",
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
        # 生成時の自動指標を隣に残す（評価の集計・教訓の効果測定に使う。失敗しても保存は成功扱い）。
        metrics = getattr(result, "metrics", None)
        if metrics:
            try:
                import tutorial_feedback

                tutorial_feedback.write_metrics(md_path, metrics)
            except Exception:  # noqa: BLE001
                pass
        # 案内モード（Guide タブ）用の手順データ。手順書の前提条件・TIPS・課題も添える（失敗しても保存は成功扱い）。
        try:
            import guide_mode

            # サンドボックスのパスと、ノードの目的（手順書の「使うノード」）も添える（2026-11-17）
            guide = guide_mode.guide_from_result(result)
            if guide["steps"]:
                guide_mode.write_guide(guide_mode.guide_path_for(md_path), guide)
        except Exception:  # noqa: BLE001
            pass
        return md_path, json_path

    def _launch_video_for_result(self, result, md_path: Path, json_path: Path) -> str:
        """
        動画生成をバックグラウンドで自動起動する（ベストエフォート）。
        2026-10-19: 起動の前に、初心者向けの台本（video_script.py）を別スレッドで作る。以前は手順のスライドに
        ツールの実行結果文を出し、ナレーションはチュートリアル本文の朗読だったため、「解説」になっていなかった。
        台本が作れなくても動画は作る（その場合は従来どおり）。実行ファイルが未設定のときは、台本を作らず
        すぐに状態を返す（Claudeの呼び出しを無駄にしない）。
        例外は投げず、状態表示用の文字列として返す。
        """
        exe_path = self._cfg_getter().get("video_factory_exe_path", "")
        if not exe_path or not Path(exe_path).exists():
            return self._start_video_process(result, md_path, json_path, None)
        steps = list(getattr(result, "step_screenshots", None) or [])
        if not steps:
            return self._start_video_process(result, md_path, json_path, None)
        # 動画の長さ（2026-11-19）。2026-11-22: 既定は完全版（全部の手順を、1 手順ずつ解説する）。短縮版は、1 場面に複数の手順をまとめるので、
        # 解説が粗く、短すぎた。短縮版は、設定で選べる（全部の手順を、連続した少ない場面にまとめる。飛び飛びにはしない）。
        # 手順書・Guide は、どちらでも、全部の手順のまま。
        mode = video_short.length_mode(self._cfg_getter())
        video_steps = steps
        if mode == video_short.SHORT:
            usable = video_script_mod.usable_steps(steps)
            video_steps = video_short.group_steps(usable)
        self._video_length_note = video_short.describe(len(video_script_mod.usable_steps(steps)), len(video_steps), mode)
        self._video_progress.setText("動画生成: 解説の台本を作っています（数十秒かかります）…")
        self._set_video_bar(0, "台本づくり")
        self._script_elapsed = 0.0
        self._script_timer.start()
        # ノードの関係図（保存したグラフから描く）。動画の「考え方」などの説明スライドに、空のぼやけた板の
        # 代わりに出す。描けなければ、動画エンジンは完成画像で代用する。
        images: dict = {}
        try:
            import screen_capture

            diagram_path = md_path.with_name(md_path.stem + "_node_diagram.png")
            if screen_capture.render_graph_diagram(getattr(result, "graph", None) or {}, diagram_path):
                images["node_diagram"] = str(diagram_path)
        except Exception:  # noqa: BLE001 -- 図が描けなくても動画は作る
            images = {}
        worker = VideoScriptWorker(self._make_agent, md_path, video_steps, images)
        self._script_workers.append(worker)

        def on_done(script_path: str, message: str, w: VideoScriptWorker = worker) -> None:
            self._script_timer.stop()  # 例外が出ても、台本づくりの進み方の表示は、止める
            try:
                _debug.log("動画", "台本づくり: 完了")
                self._set_video_bar(video_progress.SCRIPT_END, "動画エンジンを起動")
                if w in self._script_workers:
                    self._script_workers.remove(w)
                status = self._start_video_process(
                    result, md_path, json_path, Path(script_path) if script_path else None, video_steps=video_steps, mode=mode)
                note = getattr(self, "_video_length_note", "")
                self._video_progress.setText(f"{message} / {status}" + (f" / {note}" if note else ""))
            except Exception as exc:  # noqa: BLE001 -- 画面に何も出ないまま止まらないように、記録して、表示する
                _debug.log("動画", f"台本づくりの完了の処理で例外 {_debug.exception_summary(exc)}")
                self._set_video_bar(0, "失敗", failed=True)
                self._video_progress.setText(f"動画生成: 起動の処理でエラーが出ました（内容は、メニュー ≡ →「デバッグ」）: {type(exc).__name__}")

        worker.done.connect(on_done)
        worker.start()
        return "動画生成: 台本を作成中です（完了後に動画の生成を始めます）"

    _VIDEO_BAR_STYLE = (
        "QProgressBar{border:1px solid #334155;border-radius:4px;background:#0f172a;color:#e2e8f0;"
        "text-align:center;" + type_qss("caption") + "}"
        "QProgressBar::chunk{background:%s;border-radius:3px;}"
    )

    def _set_video_bar(self, percent: int, text: str, failed: bool = False) -> None:
        """動画生成のプログレスバーを更新する（表示・％・段階の文字・失敗時の赤）。"""
        self._video_bar.setVisible(True)
        self._video_bar.setValue(max(0, min(100, int(percent))))
        self._video_bar.setFormat(f"{text}  %p%" if text else "%p%")
        self._video_bar.setStyleSheet(self._VIDEO_BAR_STYLE % ("#ef4444" if failed else "#38bdf8"))

    def _on_script_tick(self) -> None:
        """台本づくり（Claudeの呼び出し）の間、終わりが読めないので、時間の経過でゆっくり進める。"""
        self._script_elapsed += self._script_timer.interval() / 1000.0
        self._set_video_bar(video_progress.script_stage_percent(self._script_elapsed), "台本づくり")

    def _make_agent(self):
        """台本づくりでClaudeを呼ぶためのエージェント（サンドボックスは作らない）。"""
        return _build_light_agent(self._cfg_getter())

    def _start_video_process(
        self, result, md_path: Path, json_path: Path, script_path: Path | None, video_steps: list | None = None, mode: str = video_short.FULL,
    ) -> str:
        """動画エンジンを起動する（video_factory_bridge）。起動に成功したら進捗表示を始める。"""
        cfg = self._cfg_getter()
        exe_path = cfg.get("video_factory_exe_path", "")
        try:
            from video_factory_bridge import launch_video_generation

            status, log_path = launch_video_generation(
                md_path=md_path,
                json_path=json_path,
                sandbox_path=result.sandbox_path,
                step_screenshots=video_steps if video_steps is not None else result.step_screenshots,
                exe_path=exe_path,
                db_key=getattr(result, "rag_name", ""),
                script_path=script_path,
                extra_args=video_short.engine_args(mode),
                # 音声合成（Worker経由のGoogle Cloud TTS）。Cloudflare版の設定をそのまま使う
                tts_url=cfg.get("cf_url", ""),
                tts_key=cfg.get("cf_api_key", ""),
                # ダッシュボード（ギャラリー）へ、動画ができたら自動でアップロードする（設定があるときだけ）
                extra_env=gallery_upload.gallery_env(cfg),
            )
            if log_path is not None:
                self._start_video_progress_poll(
                    log_path, Path(exe_path).parent, md_path, upload_expected=bool(gallery_upload.gallery_env(cfg)))
            else:
                self._video_bar.setVisible(False)  # 起動できなかった（exe未設定など）。進捗は無い
            return status
        except Exception as exc:  # noqa: BLE001 -- best-effort, never raise
            return f"動画生成の起動に失敗: {exc}"

    @staticmethod
    def _voice_summary(log_text: str) -> str:
        """動画エンジンのログから、実際に使われた音声を取り出す。VOICEVOXが使えず従来の音声（SAPI）に
        なったときは、そのことが分かる文にする（以前は黙って従来の音声になり、気づけなかった）。"""
        voice = re.findall(r"Narration voice: (.+)", log_text)
        if voice:
            name = voice[-1].strip()
            if name.startswith("SAPI"):
                return f"音声: 従来の音声（{name}）。自然な声にするには、メニュー（≡） →「接続・アカウント」の URL / APIキーを設定するか、VOICEVOXを起動してください"
            return f"音声: {name}"
        engine = re.findall(r"Narration engine: (.+)", log_text)
        return f"音声: {engine[-1].strip()[:90]}" if engine else ""

    # ── 動画生成の進捗表示（ログファイルのポーリング） ────────────────────────────

    _VIDEO_PROGRESS_POLL_MS = 2000
    _VIDEO_PROGRESS_MAX_POLLS = 900  # 2秒間隔で最大30分。それ以上は諦めてポーリングだけ止める

    def _start_video_progress_poll(self, log_path: Path, output_dir: Path, md_path: Path, upload_expected: bool = False) -> None:
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
        self._set_video_bar(video_progress.ENGINE_START, "動画エンジンを準備中")

        def poll() -> None:
            try:
                poll_once()
            except Exception as exc:  # noqa: BLE001 -- 例外で、進捗の表示が止まったまま、何も出ない状態にしない
                _debug.log("動画", f"進捗の確認で例外 {_debug.exception_summary(exc)}")
                self._video_progress.setText(f"動画生成: 進捗の表示でエラーが出ました（動画は、できているかもしれません。{log_path.name} を確認してください）")

        def poll_once() -> None:
            state["polls"] += 1
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return  # ログがまだ書かれ始めていない等。次回ポーリングに任せる

            progress = video_progress.progress_from_log(text)
            self._set_video_bar(progress.percent, progress.label if not progress.failed else "失敗の可能性", progress.failed)

            wrote_match = re.search(r"Wrote (\S+\.webm)", text)
            if wrote_match:
                video_path = output_dir / wrote_match.group(1)
                voice_note = self._voice_summary(text)
                self._video_progress.setText(
                    f"動画生成: 完了（{video_path.name}）" + (f" / {voice_note}" if voice_note else "")
                )
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
                if upload_expected:
                    self._follow_gallery_upload(log_path, f"動画生成: 完了（{video_path.name}）")
                return
            # 失敗の判定は、エンジンが「ERROR:」で始まる行を出したときだけ（video_progress.py）。以前は、ログのどこかに
            # 「エラー」という文字があれば失敗扱いにしていたため、スライドの見出し（「エラーが出ないか確かめる」等）で
            # 誤って失敗と表示され、進捗の監視も止まっていた（2026-10-21、実機で確認。動画は正常に完成していた）。
            if progress.failed:
                self._video_progress.setText(f"動画生成: {progress.label}")
                return

            voice_note = self._voice_summary(text)
            self._video_progress.setText(
                f"動画生成: {progress.label}（全体の {progress.percent}%）" + (f" / {voice_note}" if voice_note else "")
            )

            if state["polls"] < self._VIDEO_PROGRESS_MAX_POLLS:
                QTimer.singleShot(self._VIDEO_PROGRESS_POLL_MS, poll)  # poll_once が例外で止まっても、次は呼ばない（poll が記録して表示する）
            else:
                self._video_progress.setText(f"動画生成: 進捗表示を終了しました（{log_path.name}を直接確認してください）")

        QTimer.singleShot(self._VIDEO_PROGRESS_POLL_MS, poll)

    _UPLOAD_POLL_MS = 3000
    _UPLOAD_POLL_MAX = 400  # 3 秒 × 400 = 20 分（長い動画を、分けて送る時間まで見る）

    def _follow_gallery_upload(self, log_path: Path, base_text: str) -> None:
        """動画ができたあと、エンジンが自動でギャラリーへ送った結果を、ログから読んで、画面に出す（2026-11-18）。
        以前は、アップロードが失敗しても（例: 動画が大きすぎて「Payload Too Large」）、ログにしか残らず、「ギャラリーに載っていない」ことに
        気づけなかった。失敗したときは、理由と、Movie タブの「未アップロードをすべて」で再送できることを伝える。"""
        state = {"polls": 0}

        def poll() -> None:
            state["polls"] += 1
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return
            status, reason = video_progress.upload_status(text)
            if status == "done":
                self._video_progress.setText(f"{base_text} / ギャラリーに載せました")
                return
            if status == "failed":
                self._video_progress.setText(
                    f"{base_text} / ギャラリーへの自動アップロードに失敗しました（{reason}）。"
                    "Movie タブの「未アップロードをすべて」で、もう一度送れます"
                )
                return
            if status == "none":
                self._video_progress.setText(
                    f"{base_text} / ギャラリーへは送られていません（接続先が渡されていません）。"
                    "メニュー（≡）→「接続・アカウント」の「動画・ギャラリー」を確かめてください"
                )
                return
            self._video_progress.setText(f"{base_text} / ギャラリーへアップロード中…")
            if state["polls"] < self._UPLOAD_POLL_MAX:
                QTimer.singleShot(self._UPLOAD_POLL_MS, poll)

        QTimer.singleShot(self._UPLOAD_POLL_MS, poll)

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
        self._show_rating_row(md_path)
        # 生成直後に Guide タブへ読み込んだ手順（未保存）を、保存したものに置き換える。切り替えはしない（保存の操作中なので）
        guide_note = self._announce_guide_saved(md_path, switch=False)
        if guide_note:
            self._status.setText(f"{self._status.text()} / {guide_note}")

    def _show_rating_row(self, md_path: Path) -> None:
        self._rate_md_path = md_path
        self._rate_row.setVisible(True)

    def _hide_rating_row(self) -> None:
        self._rate_md_path = None
        self._rate_row.setVisible(False)

    def _on_quick_rate(self, rating: int) -> None:
        """保存直後の1クリック評価。履歴タブの評価と同じ保存・送信を使う（タグ・メモは、履歴タブで付けられる）。"""
        import tutorial_feedback

        md_path = self._rate_md_path
        self._hide_rating_row()
        if md_path is None:
            return
        entry = tutorial_feedback.save_feedback(md_path, rating, [], "")
        if entry is None:
            self._status.setText(f"{self._status.text()} / 評価を保存できませんでした")
            return
        cfg = self._cfg_getter()
        self._rate_worker = FeedbackUploadWorker(
            cfg.get("cf_url", ""), cfg.get("cf_api_key", ""),
            tutorial_feedback.build_upload_payload(md_path, entry), md_path, entry.get("rated_at", ""),
        )
        self._rate_worker.finished_with.connect(lambda ok, message: self._status.setText(f"評価を保存しました / {message}"))
        self._rate_worker.start()

    def _on_discard(self) -> None:
        self._hide_rating_row()
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

    _THUMBNAIL_SIZE = QSize(192, 108)  # 16:9。一覧をパネル全幅で見せるため、以前（96x54）の倍にした

    def __init__(self, cfg_getter: Callable[[], dict], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cfg_getter = cfg_getter
        self._build_ui()
        normalize_fonts(self)  # px のフォントを pt に揃える(4K・拡大表示で文字と部品の大きさがずれないように)
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # 2 段にする（2026-11-18。以前は 5 つのボタンと状態が 1 行に並び、狭いペインで潰れていた）:
        #   上段 = 選んだ動画への操作（主 = ダッシュボードへ、副 = 外部プレイヤー、危険 = 削除）
        #   下段 = 一覧全体の操作（更新・未アップロードをすべて）と、状態の 1 行
        self._current_video_path: Path | None = None
        selection_row = QHBoxLayout()
        selection_row.setSpacing(px(6))
        # ダッシュボードの「動画」ページ（ギャラリー）へのアップロード（2026-10-22追加）。
        # 以前は、Houdini の中・ローカルで確認するだけで、ダッシュボードにはほとんど載っていなかった。
        self._upload_btn = QPushButton("選択をダッシュボードへ")
        self._upload_btn.setEnabled(False)
        self._upload_btn.setStyleSheet(button_qss("primary"))
        self._upload_btn.setToolTip("選択した動画を、ダッシュボードの動画ページへアップロードします（すでにあるものは省略。大きい動画は分けて送ります）")
        self._upload_btn.clicked.connect(lambda: self._start_upload(selected_only=True))
        selection_row.addWidget(self._upload_btn)
        # 2026-09-13追加: 埋め込みQtWebEngineプレイヤーが再生できない・止まる場合の保険
        # （TutorialGeneratePanel._on_open_in_external_playerと同じ理由）。
        self._external_player_btn = QPushButton("外部プレイヤーで開く")
        self._external_player_btn.setEnabled(False)
        self._external_player_btn.clicked.connect(self._on_open_in_external_player)
        selection_row.addWidget(self._external_player_btn)
        selection_row.addStretch()
        # 選択した動画（複数選択可、Ctrl/Shiftクリック）だけを削除する（2026-09-12追加）。
        # 削除対象は動画ファイルとサイドカー（<名前>.video.txt）のみで、チュートリアル
        # 本体（.md/.json）やスクリーンショットマニフェストは対象外にしている
        # （「動画の一括削除」という要望のスコープを動画ファイル自体に絞るため）。
        self._delete_btn = QPushButton("選択した動画を削除")
        self._delete_btn.setEnabled(False)
        self._delete_btn.setStyleSheet(button_qss("danger"))
        self._delete_btn.clicked.connect(self._on_delete_selected)
        selection_row.addWidget(self._delete_btn)
        layout.addLayout(selection_row)

        library_row = QHBoxLayout()
        library_row.setSpacing(px(6))
        refresh_btn = action_button("refresh", "一覧を更新")
        refresh_btn.clicked.connect(self.refresh)
        library_row.addWidget(refresh_btn)
        self._upload_all_btn = QPushButton("未アップロードをすべて")
        self._upload_all_btn.setToolTip("動画エンジンの出力にある動画のうち、ダッシュボードにまだ無いものを、すべてアップロードします")
        self._upload_all_btn.clicked.connect(lambda: self._start_upload(selected_only=False))
        library_row.addWidget(self._upload_all_btn)
        library_row.addStretch()
        layout.addLayout(library_row)
        self._upload_worker: GalleryUploadWorker | None = None
        self._status = token_usage.fit_label(QLabel(""))
        self._status.setStyleSheet(type_qss("caption", COLOR_MUTED))
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        # アップロードの進み具合（0〜100%）。アップロード中だけ表示する。
        self._upload_bar = QProgressBar()
        self._upload_bar.setRange(0, 100)
        self._upload_bar.setTextVisible(True)
        self._upload_bar.setFormat("%p%")
        self._upload_bar.setFixedHeight(px(16))
        self._upload_bar.setStyleSheet(self._UPLOAD_BAR_STYLE % "#22c55e")
        self._upload_bar.setVisible(False)
        layout.addWidget(self._upload_bar)

        # 一覧だけをパネル全幅で見せる。右側にあった「外部プレイヤーで開いてください」という
        # 案内だけのペインは、埋め込みプレイヤーを撤去した後は何も表示できず、一覧の幅を
        # 狭めるだけだったため撤去した。再生はボタンまたはダブルクリック。
        self._list = QListWidget()
        self._list.setIconSize(self._THUMBNAIL_SIZE)
        self._list.setSpacing(4)
        self._list.setWordWrap(True)
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list.setToolTip("ダブルクリックで外部プレイヤーで再生します（Ctrl/Shiftクリックで複数選択）")
        self._list.currentItemChanged.connect(self._on_select)
        self._list.itemDoubleClicked.connect(lambda _item: self._on_open_in_external_player())
        self._list.itemSelectionChanged.connect(
            lambda: self._delete_btn.setEnabled(len(self._list.selectedItems()) > 0)
        )
        self._list.itemSelectionChanged.connect(self._update_upload_buttons)
        layout.addWidget(self._list, stretch=1)

    _UPLOAD_BAR_STYLE = (
        "QProgressBar{border:1px solid #334155;border-radius:4px;background:#0f172a;color:#e2e8f0;"
        "text-align:center;font-size:10px;}"
        "QProgressBar::chunk{background:%s;border-radius:3px;}"
    )

    def _update_upload_buttons(self) -> None:
        busy = self._upload_worker is not None and self._upload_worker.isRunning()
        self._upload_btn.setEnabled(not busy and len(self._list.selectedItems()) > 0)
        self._upload_all_btn.setEnabled(not busy)

    def _start_upload(self, selected_only: bool) -> None:
        """動画をダッシュボードへアップロードする。selected_only=False なら、エンジンの出力にある未アップロードの全部。"""
        cfg = self._cfg_getter()
        url, token = cfg.get("gallery_url", ""), cfg.get("gallery_token", "")
        exe_path = cfg.get("video_factory_exe_path", "")
        if not url.strip() or not token.strip():
            self._status.setText("メニュー（≡） →「接続・アカウント」の「動画・ギャラリー」で、ギャラリーのURLとアップロードトークンを設定してください（運営から受け取った値です）")
            return
        if not exe_path:
            self._status.setText("メニュー（≡） →「接続・アカウント」の「動画・ギャラリー」で、Video Factory exe パス（動画エンジン）を設定してください")
            return
        output_dir = gallery_upload.output_dir_for(exe_path)
        only_ids: set[str] | None = None
        if selected_only:
            only_ids = set()
            missing = []
            for item in self._list.selectedItems():
                entry = gallery_upload.find_local_entry(output_dir, Path(item.data(Qt.UserRole)))
                if entry is None:
                    missing.append(item.text().split("\n")[0])
                else:
                    only_ids.add(str(entry["id"]))
            if not only_ids:
                self._status.setText("動画エンジンの出力に、対応する動画が見つかりません: " + ", ".join(missing))
                return
        self._status.setText("アップロードを始めます…")
        self._upload_bar.setValue(0)
        self._upload_bar.setFormat("%p%")
        self._upload_bar.setStyleSheet(self._UPLOAD_BAR_STYLE % "#22c55e")
        self._upload_bar.setVisible(True)
        self._upload_worker = GalleryUploadWorker(url, token, output_dir, only_ids)
        self._upload_worker.progress.connect(self._status.setText)
        self._upload_worker.bytes_progress.connect(self._on_upload_progress)
        self._upload_worker.done.connect(self._on_upload_done)
        self._upload_btn.setEnabled(False)
        self._upload_all_btn.setEnabled(False)
        self._upload_worker.start()

    def _on_upload_progress(self, percent: int, label: str) -> None:
        self._upload_bar.setValue(percent)
        if label:
            self._upload_bar.setFormat(f"%p%  {label}")

    def _on_upload_done(self, message: str) -> None:
        self._status.setText(message)
        # 完了（または失敗）を、バーの色でも示す。すべて送れていれば満タンのまま少し残し、次の操作で隠れる
        failed = "失敗" in message or "できませんでした" in message
        self._upload_bar.setStyleSheet(self._UPLOAD_BAR_STYLE % ("#ef4444" if failed else "#22c55e"))
        if not failed:
            self._upload_bar.setValue(100)
        self._update_upload_buttons()

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
            self._status.setText(panel_paths.SAVE_DIR_MISSING)
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
            self._status.setText(f"ファイルが見つかりません: {path.name}")
            self._current_video_path = None
            self._external_player_btn.setEnabled(False)
            return

        self._current_video_path = path
        self._external_player_btn.setEnabled(True)

    def _on_open_in_external_player(self) -> None:
        """「外部プレイヤーで開く」ボタンのコールバック（2026-09-13追加）。
        TutorialGeneratePanel._on_open_in_external_playerと同じ理由・同じ実装。"""
        path = self._current_video_path
        if path is None or not path.exists():
            self._status.setText("再生対象のファイルが見つかりません")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# ─── ノードグラフビューア（NodeGraphAsset JSON） ─────────────────────────────────

_NODE_W, _NODE_H = 130.0 * max(1.0, px(100) / 100.0), 34.0 * max(1.0, px(100) / 100.0)  # 拡大率に合わせる(文字が pt で大きくなるため)
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

    def fit_all(self) -> None:
        """シーン全体を表示に収める(拡大・パンで見失ったときの「全体を表示」)。ノードが 0 件のときは何もしない。"""
        scene = self.scene()
        if scene is None:
            return
        rect = scene.itemsBoundingRect()
        if rect.isNull() or rect.isEmpty():
            return
        self.fitInView(rect.adjusted(-30, -30, 30, 30), Qt.KeepAspectRatio)


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
        normalize_fonts(self)  # px のフォントを pt に揃える(4K・拡大表示で文字と部品の大きさがずれないように)
        self.refresh()
        # 未送信の評価の再送は、パネルが落ち着いてから、裏で1回だけ（画面は止めない）
        QTimer.singleShot(4000, self._resend_pending_feedback)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        refresh_btn = action_button("refresh", "一覧を更新")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        # タイトル・難易度での絞り込み。一覧はrefresh()で全件読み込み済みなので、
        # ディスクへは再アクセスせずQListWidgetItemの表示/非表示切替だけで済ませる
        # （2026-08-31、生成本数が増えるほど目的のチュートリアルを探しにくくなるため追加）。
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("タイトル・難易度で検索…")
        self._search_box.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search_box, stretch=1)

        # 評価の付け忘れを探すための絞り込み（2026-10-28）。促しはせず、探したいときに押してもらう。
        self._unrated_btn = QPushButton("未評価のみ")
        self._unrated_btn.setCheckable(True)
        self._unrated_btn.setToolTip("まだ👍/👎を付けていないチュートリアルだけを一覧に出します")
        self._unrated_btn.toggled.connect(lambda _checked: self._apply_filter(self._search_box.text()))
        toolbar.addWidget(self._unrated_btn)

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

        self._copy_mermaid_btn = action_button("share", "ノードグラフを Mermaid 記法でコピー(共有用。貼り付け先で図になります)")
        self._copy_mermaid_btn.clicked.connect(self._on_copy_mermaid)
        toolbar.addWidget(self._copy_mermaid_btn)

        # ホイールで拡大したりドラッグで動かして見失ったときに、グラフ全体を表示に収め直す。
        self._fit_graph_btn = action_button("fit", "ノードグラフ全体を表示")
        self._fit_graph_btn.clicked.connect(lambda: self._graph_view.fit_all())
        toolbar.addWidget(self._fit_graph_btn)

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
        self._build_feedback_ui(layout)

    # ── 評価（good/bad・タグ・メモ）と、そこからの学習（2026-10-05追加） ─────────────────

    def _build_feedback_ui(self, layout: QVBoxLayout) -> None:
        import tutorial_feedback

        self._fb = tutorial_feedback
        self._feedback_tags: set[str] = set()
        self._upload_worker: FeedbackUploadWorker | None = None
        self._resend_worker: FeedbackResendWorker | None = None
        self._loading_feedback = False

        row = QHBoxLayout()
        row.addWidget(QLabel("評価:"))
        self._good_btn = action_button("thumbUp", "良い(このチュートリアルを「良い」と評価して保存。理由タグ・メモは後から付けられます)", checkable=True)
        self._bad_btn = action_button("thumbDown", "悪い(「悪い」と評価して保存。理由タグやメモを付けると、教訓の候補作りに使えます)", checkable=True)
        for btn in (self._good_btn, self._bad_btn):
            btn.setEnabled(False)
        self._good_btn.clicked.connect(lambda: self._on_rating_clicked(1))
        self._bad_btn.clicked.connect(lambda: self._on_rating_clicked(-1))
        row.addWidget(self._good_btn)
        row.addWidget(self._bad_btn)

        # 選んだチュートリアルへの操作。アイコン 1 つ = 操作 1 つ(チャットの回答と同じ並び)。
        self._speaker = Speaker()
        self._copy_btn = action_button("copy", "チュートリアルの本文(Markdown)をコピー")
        self._copy_btn.clicked.connect(self._on_copy_markdown)
        self._speak_btn = action_button("speaker", "本文を読み上げる(もう一度押すと止まる)", checkable=True)
        self._speak_btn.clicked.connect(self._on_speak)
        self._mark_btn = action_button("bookmark", "お気に入りに登録(もう一度押すと外す)", checkable=True)
        self._mark_btn.clicked.connect(self._on_bookmark)
        self._src_btn = action_button("docSearch", "参照元・根拠の節へ移動(本文の「参照」「出典」「根拠」の見出し)")
        self._src_btn.clicked.connect(self._on_jump_sources)
        row.addWidget(self._copy_btn)
        if self._speaker.available:
            row.addWidget(self._speak_btn)
        else:
            self._speak_btn.hide()
        row.addWidget(self._mark_btn)
        row.addWidget(self._src_btn)

        self._tag_btn = QToolButton()
        self._tag_btn.setText("理由タグ ▾")
        self._tag_btn.setPopupMode(QToolButton.InstantPopup)
        self._tag_btn.setEnabled(False)
        menu = QMenu(self._tag_btn)
        self._tag_actions = {}
        for index, tag in enumerate(tutorial_feedback.FEEDBACK_TAGS):
            if index == len(tutorial_feedback.GOOD_TAGS):
                menu.addSeparator()
            action = menu.addAction(tag)
            action.setCheckable(True)
            action.toggled.connect(self._on_tags_changed)
            self._tag_actions[tag] = action
        self._tag_btn.setMenu(menu)
        row.addWidget(self._tag_btn)

        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("一言メモ（何が良かった／悪かったか）")
        self._note_edit.setEnabled(False)
        self._note_edit.returnPressed.connect(self._on_save_feedback)
        row.addWidget(self._note_edit, stretch=1)

        self._fb_save_btn = QPushButton("タグ・メモを保存")
        self._fb_save_btn.setEnabled(False)
        self._fb_save_btn.clicked.connect(self._on_save_feedback)
        self._fb_clear_btn = QPushButton("取り消し")
        self._fb_clear_btn.setEnabled(False)
        self._fb_clear_btn.clicked.connect(self._on_clear_feedback)
        row.addWidget(self._fb_save_btn)
        row.addWidget(self._fb_clear_btn)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self._report_btn = QPushButton("評価の集計…")
        self._report_btn.setToolTip("モデル・レベル・領域・理由タグ別の好評率と、平均コスト・反復回数などを表示します")
        self._report_btn.clicked.connect(self._on_show_report)
        self._lessons_btn = QPushButton("教訓…")
        self._lessons_btn.setToolTip("低評価から得た「避けること」を編集します。承認したものだけが次回の生成に入ります")
        self._lessons_btn.clicked.connect(self._on_open_lessons)
        self._fb_status = token_usage.fit_label(QLabel(""))
        self._fb_status.setStyleSheet("color:#94a3b8;font-size:11px;")
        row2.addWidget(self._report_btn)
        row2.addWidget(self._lessons_btn)
        row2.addWidget(self._fb_status, stretch=1)
        layout.addLayout(row2)

    def _on_copy_markdown(self) -> None:
        md_path = self._current_md_path()
        if md_path is None:
            self._status.setText("先にチュートリアルを選択してください")
            return
        try:
            QGuiApplication.clipboard().setText(md_path.read_text(encoding="utf-8"))
        except OSError as exc:
            self._status.setText(f"コピーできませんでした: {exc}")
            return
        self._status.setText("本文(Markdown)をクリップボードにコピーしました")

    def _on_speak(self) -> None:
        text = self._md_view.toPlainText().strip()
        if not text:
            self._speak_btn.setChecked(False)
            return
        self._speak_btn.setChecked(self._speaker.toggle(text))

    def _bookmarked(self) -> list[str]:
        from panel_widgets import ui_state_get

        value = ui_state_get("tutorial_bookmarks", [])
        return [str(v) for v in value] if isinstance(value, list) else []

    def _on_bookmark(self) -> None:
        from panel_widgets import ui_state_set

        md_path = self._current_md_path()
        if md_path is None:
            self._mark_btn.setChecked(False)
            return
        names = [n for n in self._bookmarked() if n != md_path.stem]
        if self._mark_btn.isChecked():
            names.append(md_path.stem)
        ui_state_set("tutorial_bookmarks", names)
        self._status.setText("お気に入りに登録しました" if self._mark_btn.isChecked() else "お気に入りから外しました")

    def _on_jump_sources(self) -> None:
        """本文の「参照」「出典」「根拠」を含む見出しへ移動する。無ければ、無いと伝える。"""
        doc = self._md_view.document()
        block = doc.begin()
        while block.isValid():
            text = block.text()
            if text and any(key in text for key in ("参照", "出典", "根拠", "参考")) and len(text) <= 40:
                cursor = self._md_view.textCursor()
                cursor.setPosition(block.position())
                self._md_view.setTextCursor(cursor)
                self._md_view.ensureCursorVisible()
                self._status.setText("参照元の節へ移動しました")
                return
            block = block.next()
        self._status.setText("このチュートリアルには、参照元の節がありません")

    def _current_md_path(self) -> Path | None:
        item = self._list.currentItem()
        return Path(item.data(Qt.UserRole)) if item is not None else None

    def _set_feedback_enabled(self, enabled: bool) -> None:
        for widget in (self._good_btn, self._bad_btn, self._copy_btn, self._speak_btn, self._mark_btn, self._src_btn,
                       self._tag_btn, self._note_edit, self._fb_save_btn, self._fb_clear_btn):
            widget.setEnabled(enabled)

    def _load_feedback_state(self, md_path: Path | None) -> None:
        """選択中のチュートリアルの評価をUIへ反映する（評価が無ければ未選択の状態）。"""
        self._loading_feedback = True
        try:
            self._set_feedback_enabled(md_path is not None)
            entry = self._fb.read_feedback(md_path) if md_path is not None else None
            self._good_btn.setChecked(bool(entry and entry["rating"] == 1))
            self._bad_btn.setChecked(bool(entry and entry["rating"] == -1))
            self._mark_btn.setChecked(md_path is not None and md_path.stem in self._bookmarked())
            tags = set(entry["tags"]) if entry else set()
            for tag, action in self._tag_actions.items():
                action.setChecked(tag in tags)
            self._feedback_tags = tags
            self._note_edit.setText(entry["note"] if entry else "")
            self._refresh_tag_button()
            if entry:
                self._fb_status.setText(f"評価済み（{entry.get('rated_at', '')}）")
            elif md_path is not None:
                self._fb_status.setText("未評価")
            else:
                self._fb_status.setText("")
        finally:
            self._loading_feedback = False

    def _refresh_tag_button(self) -> None:
        count = len(self._feedback_tags)
        self._tag_btn.setText(f"理由タグ（{count}）▾" if count else "理由タグ ▾")

    def _on_tags_changed(self, _checked: bool) -> None:
        if self._loading_feedback:
            return
        self._feedback_tags = {tag for tag, action in self._tag_actions.items() if action.isChecked()}
        self._refresh_tag_button()

    def _current_rating(self) -> int:
        return 1 if self._good_btn.isChecked() else (-1 if self._bad_btn.isChecked() else 0)

    def _on_rating_clicked(self, rating: int) -> None:
        """👍/👎のどちらかを選ぶと、その場で保存する（もう一方は外れる）。"""
        if self._loading_feedback:
            return
        self._good_btn.setChecked(rating == 1)
        self._bad_btn.setChecked(rating == -1)
        self._on_save_feedback()

    def _on_save_feedback(self) -> None:
        md_path = self._current_md_path()
        if md_path is None:
            return
        rating = self._current_rating()
        if rating == 0:
            self._fb_status.setText("先に👍か👎を選んでください")
            return
        entry = self._fb.save_feedback(md_path, rating, sorted(self._feedback_tags), self._note_edit.text())
        if entry is None:
            self._fb_status.setText("評価を保存できませんでした（フォルダの書き込み権限を確認してください）")
            return
        self._fb_status.setText("評価を保存しました。Cloudflareへ送信中…")
        self._refresh_current_label(md_path)
        self._start_feedback_upload(md_path, entry)

    def _on_clear_feedback(self) -> None:
        md_path = self._current_md_path()
        if md_path is None:
            return
        self._fb.save_feedback(md_path, 0, [], "")
        self._start_feedback_upload(md_path, {"rating": 0, "title": md_path.stem})
        self._load_feedback_state(md_path)
        self._refresh_current_label(md_path)
        self._fb_status.setText("評価を取り消しました")

    def _start_feedback_upload(self, md_path: Path, entry: dict) -> None:
        cfg = self._cfg_getter()
        payload = self._fb.build_upload_payload(md_path, entry) if entry.get("rating") else {
            "tutorialKey": md_path.stem, "rating": 0,
        }
        self._upload_worker = FeedbackUploadWorker(
            cfg.get("cf_url", ""), cfg.get("cf_api_key", ""), payload,
            md_path if entry.get("rating") else None, entry.get("rated_at", ""),
        )
        self._upload_worker.finished_with.connect(lambda ok, message: self._fb_status.setText(message))
        self._upload_worker.start()

    def _resend_pending_feedback(self) -> None:
        """未送信の評価を、バックグラウンドで再送する。送れたときだけ、状態欄に一言出す。"""
        tutorials_dir, cfg = self._tutorials_dir(), self._cfg_getter()
        if tutorials_dir is None or not cfg.get("cf_url") or not cfg.get("cf_api_key"):
            return
        if not self._fb.pending_uploads(tutorials_dir):
            return
        self._resend_worker = FeedbackResendWorker(tutorials_dir, cfg["cf_url"], cfg["cf_api_key"])
        self._resend_worker.finished_with.connect(self._on_resend_done)
        self._resend_worker.start()

    def _on_resend_done(self, result: dict) -> None:
        if result.get("sent"):
            self._fb_status.setText(f"未送信だった評価 {result['sent']}件を送信しました")

    def _refresh_current_label(self, md_path: Path) -> None:
        item = self._list.currentItem()
        if item is not None:
            item.setText(self._label_for(md_path))

    def _label_for(self, path: Path) -> str:
        label = path.stem
        difficulty = self._peek_difficulty(path)
        if difficulty:
            label = f"{label}  [{difficulty}]"
        if self._peek_status(path) == "archived":
            label = f"⚠ {label}（打ち切り）"
        entry = self._fb.read_feedback(path)
        if entry:
            label = ("👍 " if entry["rating"] == 1 else "👎 ") + label
        return label

    def _on_show_report(self) -> None:
        tutorials_dir = self._tutorials_dir()

        def load() -> list[dict]:
            return self._fb.list_entries(tutorials_dir) if tutorials_dir is not None else []

        ReportDialog(self, load).exec()

    def _make_agent(self):
        """教訓の候補作りでClaudeを呼ぶためのエージェント（生成時と同じ設定。サンドボックスは作らない）。"""
        return _build_light_agent(self._cfg_getter())

    def _on_open_lessons(self) -> None:
        project_dir = self._cfg_getter().get("local_bridge_dir", "")
        if not project_dir:
            self._fb_status.setText(panel_paths.SAVE_DIR_MISSING)
            return
        dialog = LessonsDialog(self, project_dir, self._tutorials_dir(), self._make_agent)
        if dialog.exec():
            approved = len(self._fb.approved_lessons(project_dir))
            self._fb_status.setText(f"教訓を保存しました（承認 {approved} 件が次回の生成に入ります）")

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
            self._status.setText(panel_paths.SAVE_DIR_MISSING)
            return
        if not tutorials_dir.exists():
            self._status.setText("まだ保存されたチュートリアルがありません")
            return
        files = sorted(tutorials_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        archived_count = 0
        for path in files:
            # 2026-09-14追加: frontmatterのstatusがarchived（=confirm_tutorialまで
            # 到達せず打ち切られた生成、tutorial_agent.py._assemble_markdown参照）の
            # ものを一覧上で分かるようにする。「Houdiniチュートリアル生成が正規に
            # 終了しているか一覧で確認したい」という実機フィードバックへの対応。
            # 2026-10-05: 評価済みなら先頭に👍/👎を付ける。ラベルの組み立ては_label_forに集約。
            label = self._label_for(path)
            if self._peek_status(path) == "archived":
                archived_count += 1
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 1, self._fb.read_feedback(path) is not None)  # 評価済みか（「未評価のみ」の絞り込み用）
            self._list.addItem(item)
        unrated = sum(1 for i in range(self._list.count()) if not self._list.item(i).data(Qt.UserRole + 1))
        status_text = f"{len(files)} 件（未評価 {unrated}件）"
        if archived_count:
            status_text += f"（うち打ち切り ⚠ {archived_count}件）"
        self._status.setText(status_text)
        self._apply_filter(self._search_box.text())

    def _apply_filter(self, text: str) -> None:
        """検索ボックスの文字列と「未評価のみ」で、リストの表示/非表示を切り替える（大文字小文字区別なし）。"""
        needle = text.strip().lower()
        only_unrated = self._unrated_btn.isChecked()
        visible = 0
        for i in range(self._list.count()):
            item = self._list.item(i)
            hit = (not needle or needle in item.text().lower()) and not (only_unrated and item.data(Qt.UserRole + 1))
            item.setHidden(not hit)
            visible += 1 if hit else 0
        if needle or only_unrated:
            how = "・".join(part for part in (f"「{text}」で絞り込み中" if needle else "", "未評価のみ" if only_unrated else "") if part)
            self._status.setText(f"{visible} / {self._list.count()} 件（{how}）")

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
            self._load_feedback_state(None)
            return
        md_path = Path(current.data(Qt.UserRole))
        self._load_feedback_state(md_path)
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
        self._graph_view.fit_all()
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
