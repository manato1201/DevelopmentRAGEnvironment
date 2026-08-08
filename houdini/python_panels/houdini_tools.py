"""
houdini_tools.py — houdini21 チュートリアル生成用 hou モジュールラッパー

tutorial_agent.py のエージェントループから呼ばれるツール群。
Anthropic tool-use 形式のスキーマ（HOUDINI_TOOLS）と、それを実行する
HoudiniToolExecutor を提供する。

安全設計（docs/content-generation.md §2.6）:
  ・全ノード操作は /obj/ai_tutorial_<timestamp> サンドボックスサブネット内に限定
  ・サンドボックス外パスの指定は実行前に拒否し、監査ログに記録
  ・全ツール呼び出しを JSONL 監査ログ（logs/tutorial_agent/）に追記
  ・hou 操作は hdefereval で Houdini メインスレッドにディスパッチ
    （QThread から呼んでもクラッシュしない）

このモジュール自体は import 時に hou を要求しない（テスト用に差し替え可能）。
"""

from __future__ import annotations

import base64
import datetime
import json
import re
import threading
from pathlib import Path
from typing import Any, Callable


# ─── Anthropic tool-use スキーマ ─────────────────────────────────────────────────
# ツール定義はエージェントループの固定部分としてプロンプトキャッシュされるため、
# description は多少長くても2回目以降のコストにはほぼ影響しない。

HOUDINI_TOOLS: list[dict] = [
    {
        "name": "create_node",
        "description": (
            "サンドボックスサブネット内に新しいノードを作成する。"
            "node_type はカテゴリ内での正確なタイプ名（例: 'grid', 'mountain::2.0'）。"
            "タイプ名が不確かな場合は必ず先に list_available_node_types で確認すること。"
            "parent を省略するとサンドボックス直下に作成される。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_type": {
                    "type": "string",
                    "description": "作成するノードのタイプ名（例: 'grid', 'copytopoints::2.0'）",
                },
                "name": {
                    "type": "string",
                    "description": "ノード名（省略時は自動命名）。英数字とアンダースコアのみ",
                },
                "parent": {
                    "type": "string",
                    "description": "親ノードのサンドボックス相対パス（省略時はサンドボックス直下）",
                },
            },
            "required": ["node_type"],
        },
    },
    {
        "name": "set_parameter",
        "description": (
            "ノードのパラメータに値を設定する。parm は Houdini 内部パラメータ名"
            "（例: 'tx', 'scale', 'rows'）。タプルパラメータ（例: 't', 'size'）に対しては "
            "value に空白区切り文字列（例: '0 1 0'）を渡すと各成分に展開される。"
            "パラメータ名が不明な場合は get_node_info で確認できる。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "対象ノードのサンドボックス相対パス（例: 'grid1'）",
                },
                "parm": {
                    "type": "string",
                    "description": "パラメータの内部名",
                },
                "value": {
                    "type": ["string", "number", "boolean"],
                    "description": "設定する値。タプルには空白区切り文字列",
                },
            },
            "required": ["node", "parm", "value"],
        },
    },
    {
        "name": "connect_nodes",
        "description": "2つのノードを接続する（from_node の出力 → to_node の入力）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_node": {
                    "type": "string",
                    "description": "接続元ノードのサンドボックス相対パス",
                },
                "to_node": {
                    "type": "string",
                    "description": "接続先ノードのサンドボックス相対パス",
                },
                "input_index": {
                    "type": "integer",
                    "description": "接続先の入力インデックス（デフォルト 0）",
                },
                "output_index": {
                    "type": "integer",
                    "description": "接続元の出力インデックス（デフォルト 0）",
                },
            },
            "required": ["from_node", "to_node"],
        },
    },
    {
        "name": "cook_node",
        "description": (
            "ノードを強制的に cook（評価）してエラーと警告を取得する。"
            "グラフを組み終えたら必ず最終ノードを cook し、エラーがあれば修正して再度 cook すること。"
            "エラーが空になるまで finish_tutorial を呼んではならない。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "cook するノードのサンドボックス相対パス",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "list_available_node_types",
        "description": (
            "指定カテゴリで利用可能なノードタイプを検索する。"
            "Houdini のノードタイプ名はバージョン依存（例: 'mountain' は存在せず 'mountain::2.0'）"
            "のため、create_node の前に正確な名前をこのツールで確認すること。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "ノードカテゴリ: 'Sop' | 'Object' | 'Dop' | 'Vop' | 'Cop2' | 'Top'",
                },
                "filter": {
                    "type": "string",
                    "description": "タイプ名・説明に含まれる文字列で絞り込み（例: 'noise'）",
                },
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_node_info",
        "description": (
            "既存ノードの状態（タイプ・デフォルト値から変更されたパラメータ・入出力接続・"
            "エラー/警告・利用可能なパラメータ名一覧）を取得する。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "対象ノードのサンドボックス相対パス",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "delete_node",
        "description": "不要になったノードをサンドボックス内から削除する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "削除するノードのサンドボックス相対パス",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "finish_tutorial",
        "description": (
            "チュートリアル生成を完了する（下書きを提出する）。最終ノードの cook がエラーなしで"
            "通ってから呼ぶこと。steps / pitfalls は Markdown 形式で記述する（見出しレベルは "
            "### 以下を使用）。"
            "呼び出すと、現在のビューポートの画像が見せられる（見た目の自己確認用）。その画像を"
            "確認したうえで、必ず続けて confirm_tutorial を呼ぶこと（finish_tutorial だけでは"
            "生成は完了しない）。画像を見て問題があれば confirm_tutorial(looks_correct=false) "
            "を呼び、ノードを修正してから再度 finish_tutorial → confirm_tutorial をやり直すこと。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "チュートリアルのタイトル（日本語）",
                },
                "slug": {
                    "type": "string",
                    "description": "ファイル名用スラッグ（英小文字・数字・ハイフンのみ。例: 'rock-scatter-basic'）",
                },
                "overview": {
                    "type": "string",
                    "description": "概要（何を作るか・学べること。2〜4文）",
                },
                "steps": {
                    "type": "string",
                    "description": "手順の Markdown。実際に実行したノード作成・パラメータ設定を番号付きで解説",
                },
                "pitfalls": {
                    "type": "string",
                    "description": "ハマりポイントの Markdown。生成中に遭遇した cook エラーと対処を含める",
                },
                "next_steps": {
                    "type": "string",
                    "description": (
                        "応用・発展アイデアの Markdown 箇条書き（3〜5個）。手順の単なる繰り返しではなく、"
                        "「このパラメータを変えると見た目がどう変わるか」「他のノード/技法と組み合わせると"
                        "何が作れるか」「このセットアップを自分の別のシーン・目的にどう転用できるか」を、"
                        "読んだ人が『自分のプロジェクトでこう使えそうだ』と具体的にイメージできる粒度で書く。"
                        "「もっと調べてみましょう」のような一般論で終わらせず、変更するパラメータ名や"
                        "追加するノードタイプなど具体的な手がかりを含めること。"
                    ),
                },
                "sources_used": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "システムプロンプトの「参考ドキュメント」で振られた番号（[1], [2] ...）のうち、"
                        "実際にチュートリアルの内容を組み立てる際に参考にしたものの番号一覧。"
                        "参考ドキュメントを使わなかった場合は空配列にする。"
                    ),
                },
            },
            "required": ["title", "slug", "overview", "steps"],
        },
    },
    {
        "name": "confirm_tutorial",
        "description": (
            "finish_tutorial を呼んだ直後に見せられるビューポート画像を確認したあとに、必ず呼ぶこと。"
            "画像が意図した見た目になっていれば looks_correct=true でチュートリアル生成を確定する。"
            "見た目に問題がある場合（例: 期待した要素が画面に見えない、明らかに崩れている等）は"
            "looks_correct=false にする。その場合は続けてノードの修正（例: 複数の要素を同時に見せたい"
            "場合はMergeノードを追加して表示フラグを設定する等）を行い、その後もう一度 finish_tutorial"
            "を呼んでから再度この confirm_tutorial を呼び直すこと。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "looks_correct": {
                    "type": "boolean",
                    "description": "ビューポート画像が意図した見た目になっているか",
                },
                "note": {
                    "type": "string",
                    "description": "（任意）画像を見た上での補足コメント・気づいた点",
                },
            },
            "required": ["looks_correct"],
        },
    },
]


# ─── メインスレッドディスパッチ ─────────────────────────────────────────────────

def _run_in_main_thread(fn: Callable[[], Any]) -> Any:
    """
    hou 操作を Houdini のメインスレッドで実行する。
    hou のノード操作は UI スレッド以外から呼ぶと不安定なため、
    QThread（TutorialWorker）から呼ばれる場合は hdefereval 経由でディスパッチする。
    hdefereval が無い環境（テスト・スタンドアロン）ではそのまま実行する。
    """
    try:
        import hdefereval
        return hdefereval.executeInMainThreadWithResult(fn)
    except ImportError:
        return fn()


def _json_safe(value) -> Any:
    """パラメータ値を JSON 化可能な型に変換する（hou.Ramp 等は文字列化）。"""
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


# ─── ツール実行エンジン ─────────────────────────────────────────────────────────

class SandboxViolation(Exception):
    """サンドボックス外のノードパスが指定されたときに送出される。"""


class HoudiniToolExecutor:
    """
    HOUDINI_TOOLS の実行エンジン。

    サンドボックス保証:
      ・コンストラクタで /obj 直下に ai_tutorial_<timestamp> サブネットを作成
      ・全ツールのノードパスは _resolve() でサンドボックス内に解決され、
        外を指すパス（絶対パス・'..' を含むパス）は SandboxViolation として拒否
      ・拒否を含む全呼び出しが JSONL 監査ログに残る（安全性の事後検証用）

    hou_module 引数はテスト用のフック。省略時は import hou する。
    """

    SANDBOX_PREFIX = "ai_tutorial_"

    # 実行後にスクリーンショットを撮る価値があるツール（グラフ/シーンの見た目を
    # 変えるもの）。list_available_node_types/get_node_info は読み取り専用。
    # finish_tutorial/confirm_tutorial は別枠（_capture_finish_screenshot）で
    # ビューポート単体の確認用スクリーンショットを撮るため対象外。
    _SCREENSHOT_WORTHY_TOOLS = frozenset(
        {"create_node", "set_parameter", "connect_nodes", "cook_node", "delete_node"}
    )

    # ノードタイプ名にこれらの文字列が含まれていれば「シミュレーションノード」と
    # みなす（pyro/fire/煙/クロス/パーティクル/流体/剛体等）。cook_node は単一フレーム
    # 評価では時間発展する挙動を検証できないため、これらは複数フレーム評価する。
    _SIMULATION_TYPE_HINTS = (
        "pyrosolver", "dopnet", "dynamics", "vellum", "cloth",
        "particle", "popnet", "popsolver", "flip", "rbdsolver", "grains",
    )
    _SIM_COOK_FRAME_COUNT = 10  # シミュレーション検証のため現在フレームから何フレーム進めるか

    def __init__(
        self,
        log_dir: Path | None = None,
        hou_module=None,
        screenshot_dir: Path | None = None,
    ) -> None:
        if hou_module is None:
            import hou as hou_module  # Houdini 内でのみ成功する
        self._hou = hou_module

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._sandbox_name = f"{self.SANDBOX_PREFIX}{timestamp}"
        self._sandbox = _run_in_main_thread(self._create_sandbox)
        self.sandbox_path: str = self._sandbox.path()

        self.finish_data: dict | None = None  # confirm_tutorial(looks_correct=true) 確定後にセットされる
        # finish_tutorial の入力の「下書き」。confirm_tutorial が呼ばれるまでの一時保持。
        # 見た目の自己確認（視覚的自己検証ステップ）を経てから finish_data に格上げされる。
        self._pending_finish: dict | None = None
        # 直前の finish_tutorial 呼び出しで撮ったビューポート画像（base64 PNG）。
        # tutorial_agent.py 側がこれを読み、その1回だけ tool_result に画像として添付する。
        self.last_screenshot_b64: str | None = None
        self.step_log: list[dict] = []        # Markdown 組み立て用の全呼び出し履歴
        # 各ステップ実行直後に撮ったビューポート/ネットワークエディタの
        # スクリーンショット一覧（動画生成側で手順ごとの画面を見せるため）。
        # {"step": int, "tool": str, "viewport": str|None, "network": str|None}
        self.step_screenshots: list[dict] = []
        self._lock = threading.Lock()

        # スクリーンショット保存先。渡された screenshot_dir の下に
        # このサンドボックス専用のサブフォルダを作る（ログと同じ方針で、
        # 作成に失敗しても生成自体は止めない）。
        self._screenshot_dir: Path | None = None
        if screenshot_dir is not None:
            try:
                resolved = Path(screenshot_dir) / self._sandbox_name
                resolved.mkdir(parents=True, exist_ok=True)
                self._screenshot_dir = resolved
            except OSError:
                self._screenshot_dir = None

        # 監査ログ（JSONL）。書き込み不能でも生成自体は止めない
        self._log_path: Path | None = None
        if log_dir is not None:
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                self._log_path = log_dir / f"{self._sandbox_name}.jsonl"
                self._append_audit({"event": "sandbox_created", "path": self.sandbox_path})
            except OSError:
                self._log_path = None

    # ── サンドボックス管理 ──────────────────────────────────────────────────────

    def _create_sandbox(self):
        obj = self._hou.node("/obj")
        sandbox = obj.createNode("subnet", self._sandbox_name)
        sandbox.setComment("AI生成チュートリアル用サンドボックス（tutorial_agent）")
        sandbox.moveToGoodPosition()
        return sandbox

    def destroy_sandbox(self) -> None:
        """ユーザーが明示的に「削除」を選んだ場合のみ呼ばれる。"""
        def _destroy():
            node = self._hou.node(self.sandbox_path)
            if node is not None:
                node.destroy()
        _run_in_main_thread(_destroy)
        self._append_audit({"event": "sandbox_destroyed", "path": self.sandbox_path})

    def _resolve(self, rel_path: str):
        """
        サンドボックス相対パスをノードに解決する。
        サンドボックス外を指すパスは SandboxViolation。
        絶対パスはサンドボックス配下を指している場合のみ許可する。
        """
        rel_path = (rel_path or "").strip()
        if not rel_path:
            raise SandboxViolation("ノードパスが空です")
        if ".." in rel_path.split("/"):
            raise SandboxViolation(f"'..' を含むパスは許可されません: {rel_path}")

        if rel_path.startswith("/"):
            # 絶対パス: サンドボックス自身か配下のみ許可
            if rel_path != self.sandbox_path and not rel_path.startswith(self.sandbox_path + "/"):
                raise SandboxViolation(
                    f"サンドボックス外のパスは操作できません: {rel_path}"
                )
            full_path = rel_path
        else:
            full_path = f"{self.sandbox_path}/{rel_path}"

        node = self._hou.node(full_path)
        if node is None:
            raise ValueError(f"ノードが見つかりません: {full_path}")
        # シンボリックな別名等でサンドボックス外に解決された場合も拒否する
        real = node.path()
        if real != self.sandbox_path and not real.startswith(self.sandbox_path + "/"):
            raise SandboxViolation(f"サンドボックス外のノードです: {real}")
        return node

    def _rel(self, node) -> str:
        """ノードのサンドボックス相対パスを返す（ログ・応答の表記用）。"""
        path = node.path()
        if path.startswith(self.sandbox_path + "/"):
            return path[len(self.sandbox_path) + 1:]
        return path

    # ── 監査ログ ────────────────────────────────────────────────────────────────

    def _append_audit(self, record: dict) -> None:
        record = {"ts": datetime.datetime.now().isoformat(), **record}
        if self._log_path is None:
            return
        try:
            with self._lock, open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # ログ書き込み失敗で生成を止めない

    # ── ツールディスパッチ ──────────────────────────────────────────────────────

    def execute(self, tool_name: str, tool_input: dict) -> tuple[str, bool]:
        """
        ツールを実行して (結果テキスト, is_error) を返す。
        例外はすべて捕捉して結果テキストに変換する（エージェントの自己修正材料になる）。
        SandboxViolation は監査ログに violation として記録する。
        """
        handler = getattr(self, f"_tool_{tool_name}", None)
        if handler is None:
            result, is_error = f"未知のツールです: {tool_name}", True
        else:
            try:
                result, is_error = _run_in_main_thread(lambda: handler(tool_input)), False
            except SandboxViolation as exc:
                result, is_error = f"[サンドボックス違反] {exc}", True
                self._append_audit({
                    "event": "sandbox_violation",
                    "tool": tool_name, "input": tool_input, "error": str(exc),
                })
            except Exception as exc:
                result, is_error = f"エラー: {exc}", True

        entry = {
            "tool": tool_name, "input": tool_input,
            "result": result, "is_error": is_error,
        }
        self.step_log.append(entry)
        self._append_audit({"event": "tool_call", **entry})

        if not is_error and tool_name in self._SCREENSHOT_WORTHY_TOOLS:
            self._capture_step_screenshot(tool_name, result)
        if not is_error and tool_name == "finish_tutorial":
            self._capture_finish_screenshot()

        return result, is_error

    @property
    def pending_finish(self) -> dict | None:
        """finish_tutorialは呼ばれたがconfirm_tutorialでまだ確定していない下書き（無ければNone）。"""
        return self._pending_finish

    def _capture_finish_screenshot(self) -> None:
        """
        finish_tutorial 呼び出し直後にビューポートを撮影し、base64 PNG として保持する
        （視覚的自己検証ステップ）。tutorial_agent.py 側がこれを読み、その回の tool_result に
        画像として添付してClaude自身に見た目を確認させ、confirm_tutorial で最終確定させる。
        撮影に失敗しても生成は止めない（last_screenshot_b64がNoneのままになるだけで、
        その場合Claudeは画像無しでconfirm_tutorialを判断することになる）。
        """
        self.last_screenshot_b64 = None
        if self._screenshot_dir is None:
            return
        try:
            import screen_capture
        except ImportError:
            return

        def _capture():
            path = self._screenshot_dir / "finish_check.png"
            log_path = self._screenshot_dir / "capture.log"
            if screen_capture.capture_viewport(path, log_path=log_path):
                try:
                    self.last_screenshot_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
                except OSError:
                    pass

        try:
            _run_in_main_thread(_capture)
        except Exception:  # noqa: BLE001 -- best-effort, never raise
            pass

    def _capture_step_screenshot(self, tool_name: str, tool_result: str) -> None:
        """
        ツール呼び出し成功直後にビューポート/ネットワークエディタを撮影する
        （ベストエフォート）。動画生成側で各手順のノード操作を個別に見せられる
        ようにするための per-step キャプチャ。tool_result（例:「作成しました:
        stairs_geo/step_shape（タイプ: box）」）もあわせて保存する -- 動画側は
        Markdown の「### N.」というClaude自身が後から書いた"要約"ステップ番号
        と、この実行単位のステップ番号が全く別物であることを前提に、この
        result テキストを直接そのスライドの説明文として使う（要約番号と実行
        番号を突き合わせようとすると、実機テストで無関係な画面が表示される
        不具合が確認された）。
        screen_capture のimport失敗・撮影失敗のいずれでもチュートリアル生成
        そのものは止めない。
        """
        if self._screenshot_dir is None:
            return
        try:
            import screen_capture
        except ImportError:
            return

        def _capture():
            step_index = len(self.step_screenshots) + 1
            log_path = self._screenshot_dir / "capture.log"
            viewport_path = self._screenshot_dir / f"step_{step_index:03d}_viewport.png"
            network_path = self._screenshot_dir / f"step_{step_index:03d}_network.png"
            # Capture the viewport BEFORE switching pane tabs: flipbook()
            # renders internally regardless of which tab is visually active
            # in a shared pane group, but focus_network_on() below now
            # calls setIsCurrentTab() to bring NetworkEditor to the front
            # (needed for its own capture to show the right content) --
            # doing that first would risk Scene View no longer being the
            # visible tab if the two share a pane group.
            got_viewport = screen_capture.capture_viewport(viewport_path, log_path=log_path)

            # cook_node re-evaluates the graph, which for simulation nodes
            # (pyro, fire, cloth, particles) plays out over time -- a short
            # multi-frame clip shows that far better than one still frame.
            # Scoped to cook_node only, and kept small/low-res, so this
            # doesn't blow up per-video weight/cost across the whole run.
            clip_frames: list = []
            clip_fps = 0
            if tool_name == "cook_node":
                clip_frames, clip_fps = screen_capture.capture_viewport_clip(
                    self._screenshot_dir, f"step_{step_index:03d}_clip", log_path=log_path
                )

            screen_capture.focus_network_on(self.sandbox_path, log_path=log_path)
            got_network = screen_capture.capture_network_editor(network_path, log_path=log_path)
            self.step_screenshots.append({
                "step": step_index,
                "tool": tool_name,
                "result": tool_result,
                "viewport": str(viewport_path) if got_viewport else None,
                "network": str(network_path) if got_network else None,
                "viewport_clip_frames": [str(p) for p in clip_frames],
                "viewport_clip_fps": clip_fps,
            })

        try:
            _run_in_main_thread(_capture)
        except Exception:  # noqa: BLE001 -- best-effort, never raise
            pass

    # ── 各ツール実装 ────────────────────────────────────────────────────────────

    def _tool_create_node(self, args: dict) -> str:
        parent = self._resolve(args["parent"]) if args.get("parent") else self._sandbox
        name = args.get("name") or None
        if name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            return f"ノード名が不正です（英数字とアンダースコアのみ）: {name}"
        try:
            node = parent.createNode(args["node_type"], name)
        except Exception as exc:
            return (
                f"ノード作成失敗（タイプ名 '{args['node_type']}' が不正な可能性）: {exc}\n"
                "list_available_node_types で正確なタイプ名を確認してください。"
            )
        node.moveToGoodPosition()
        return f"作成しました: {self._rel(node)}（タイプ: {node.type().name()}）"

    def _tool_set_parameter(self, args: dict) -> str:
        node = self._resolve(args["node"])
        parm_name = args["parm"]
        value = args["value"]

        parm = node.parm(parm_name)
        if parm is not None:
            parm.set(self._coerce_scalar(parm, value))
            return f"{self._rel(node)}.{parm_name} = {value}"

        tuple_parm = node.parmTuple(parm_name)
        if tuple_parm is not None:
            components = str(value).split()
            if len(components) != len(tuple_parm):
                return (
                    f"タプル {parm_name} は {len(tuple_parm)} 成分です。"
                    f"空白区切りで {len(tuple_parm)} 個の値を渡してください（受領: {value}）"
                )
            tuple_parm.set(tuple(float(c) for c in components))
            return f"{self._rel(node)}.{parm_name} = ({', '.join(components)})"

        available = ", ".join(p.name() for p in node.parms()[:40])
        return (
            f"パラメータ '{parm_name}' が見つかりません。"
            f"利用可能なパラメータ（先頭40件）: {available}"
        )

    @staticmethod
    def _coerce_scalar(parm, value):
        """パラメータのテンプレート型に合わせて値を変換する。"""
        try:
            import hou
            data_type = parm.parmTemplate().dataType()
            if data_type == hou.parmData.Int:
                return int(float(value))
            if data_type == hou.parmData.Float:
                return float(value)
            return str(value)
        except Exception:
            return value  # 型情報が取れない場合はそのまま渡す（hou 側で変換）

    def _tool_connect_nodes(self, args: dict) -> str:
        src = self._resolve(args["from_node"])
        dst = self._resolve(args["to_node"])
        input_index = int(args.get("input_index", 0))
        output_index = int(args.get("output_index", 0))
        dst.setInput(input_index, src, output_index)
        return (
            f"接続しました: {self._rel(src)}[out:{output_index}] → "
            f"{self._rel(dst)}[in:{input_index}]"
        )

    def _is_simulation_node(self, node) -> bool:
        """pyro/fire/クロス/パーティクル/流体/剛体等のシミュレーション系ノードかどうか。
        単一フレームのcookでは時間発展する挙動を検証できないため複数フレーム評価する。"""
        type_name = node.type().name().lower()
        return any(hint in type_name for hint in self._SIMULATION_TYPE_HINTS)

    def _cook_simulation_frames(self, node) -> int:
        """
        現在のグローバルフレームから _SIM_COOK_FRAME_COUNT フレーム分、順番に
        フレームを進めながらcookする（シミュレーションは前のフレームの結果に
        依存するため、途中のフレームを飛ばさず1フレームずつ進める必要がある）。
        呼び出し前のフレームは必ず復元する（ユーザーの作業状態を変えないため）。
        戻り値: 実際に評価したフレーム数。
        """
        hou = self._hou
        original_frame = hou.frame()
        evaluated = 0
        try:
            start = int(original_frame)
            for f in range(start, start + self._SIM_COOK_FRAME_COUNT):
                hou.setFrame(f)
                try:
                    node.cook(force=True)
                except Exception:
                    pass
                evaluated += 1
        finally:
            hou.setFrame(original_frame)
        return evaluated

    def _tool_cook_node(self, args: dict) -> str:
        node = self._resolve(args["node"])
        is_sim = self._is_simulation_node(node)
        frames_evaluated = 0
        if is_sim:
            frames_evaluated = self._cook_simulation_frames(node)
        else:
            try:
                node.cook(force=True)
            except Exception:
                pass  # cook 例外の詳細は errors() から取得する
        errors = list(node.errors())
        warnings = list(node.warnings())
        sim_note = (
            f"（シミュレーションノードのため{frames_evaluated}フレーム分evaluateして確認しました）"
            if is_sim else ""
        )
        if not errors and not warnings:
            return f"cook 成功: {self._rel(node)}（エラー・警告なし）{sim_note}"
        lines = [f"cook 結果: {self._rel(node)}{sim_note}"]
        for e in errors:
            lines.append(f"  [エラー] {e}")
        for w in warnings:
            lines.append(f"  [警告] {w}")
        return "\n".join(lines)

    def _tool_list_available_node_types(self, args: dict) -> str:
        category_map = {
            "sop": "sopNodeTypeCategory",
            "object": "objNodeTypeCategory",
            "obj": "objNodeTypeCategory",
            "dop": "dopNodeTypeCategory",
            "vop": "vopNodeTypeCategory",
            "cop2": "cop2NodeTypeCategory",
            "top": "topNodeTypeCategory",
        }
        cat_key = args["category"].lower()
        getter_name = category_map.get(cat_key)
        if getter_name is None:
            return f"未知のカテゴリです: {args['category']}（Sop/Object/Dop/Vop/Cop2/Top）"
        category = getattr(self._hou, getter_name)()

        keyword = (args.get("filter") or "").lower()
        matches = []
        for type_name, node_type in category.nodeTypes().items():
            desc = node_type.description()
            if keyword and keyword not in type_name.lower() and keyword not in desc.lower():
                continue
            matches.append(f"{type_name}  —  {desc}")
        if not matches:
            return f"'{args.get('filter', '')}' に一致するノードタイプがありません"
        matches.sort()
        shown = matches[:40]
        suffix = f"\n（他 {len(matches) - 40} 件省略。filter で絞り込んでください）" if len(matches) > 40 else ""
        return "\n".join(shown) + suffix

    def _tool_get_node_info(self, args: dict) -> str:
        node = self._resolve(args["node"])
        lines = [f"ノード: {self._rel(node)}（タイプ: {node.type().name()}）"]

        changed = [
            f"  {p.name()} = {p.eval()}"
            for p in node.parms() if not p.isAtDefault()
        ]
        lines.append("デフォルトから変更されたパラメータ:")
        lines.extend(changed[:30] or ["  （なし）"])

        inputs = [
            f"  in[{i}] ← {self._rel(inp)}" if inp else f"  in[{i}] ← （未接続）"
            for i, inp in enumerate(node.inputs())
        ]
        lines.append("入力接続:")
        lines.extend(inputs or ["  （入力なし）"])

        errors = list(node.errors())
        warnings = list(node.warnings())
        if errors or warnings:
            lines.append("エラー/警告:")
            lines.extend(f"  [エラー] {e}" for e in errors)
            lines.extend(f"  [警告] {w}" for w in warnings)

        parm_names = ", ".join(p.name() for p in node.parms()[:60])
        lines.append(f"利用可能なパラメータ名（先頭60件）: {parm_names}")
        return "\n".join(lines)

    def _tool_delete_node(self, args: dict) -> str:
        node = self._resolve(args["node"])
        if node.path() == self.sandbox_path:
            raise SandboxViolation("サンドボックス自体は削除できません")
        rel = self._rel(node)
        node.destroy()
        return f"削除しました: {rel}"

    def _tool_finish_tutorial(self, args: dict) -> str:
        # ここでは即座にfinish_dataを確定しない（下書きとして保持するのみ）。
        # 視覚的自己検証ステップ: この直後にビューポート画像が見せられるので、
        # それを確認したうえでconfirm_tutorialを呼んで初めてfinish_dataが確定する。
        self._pending_finish = dict(args)
        return (
            "チュートリアル内容を受け付けました（まだ確定していません）。"
            "このあとビューポートの画像が送られるので、意図した見た目になっているか確認し、"
            "問題なければ confirm_tutorial(looks_correct=true) を呼んでください。"
            "問題があれば修正してから、もう一度 finish_tutorial を呼び直してください。"
        )

    def _tool_confirm_tutorial(self, args: dict) -> str:
        if self._pending_finish is None:
            return "finish_tutorial をまだ呼んでいません。先に finish_tutorial を呼んでください。"
        if args.get("looks_correct", False):
            self.finish_data = self._pending_finish
            self._pending_finish = None
            return "確認しました。チュートリアル生成を完了します。"
        self._pending_finish = None
        return "了解しました。見た目の問題を修正してから、もう一度 finish_tutorial を呼んでください。"

    # ── NodeGraphAsset エクスポート ─────────────────────────────────────────────

    def export_node_graph(self) -> dict:
        """
        サンドボックス内のノード構成を NodeGraphAsset 互換 JSON に変換する。
        Node-Management（Blender版）の nodes/edges/params/position スキーマに合わせる。
        ネストしたサブネットも parent フィールド付きで再帰的に含める。
        """
        def _export():
            nodes: list[dict] = []
            edges: list[dict] = []

            def visit(parent, parent_id: str | None):
                for child in parent.children():
                    node_id = self._rel(child)
                    pos = child.position()
                    entry = {
                        "id": node_id,
                        "kind": child.type().name(),
                        "label": child.name(),
                        # Houdini のネットワーク座標は y が上向きなので反転して保存
                        "position": [round(pos[0], 3), round(-pos[1], 3)],
                        "params": {
                            p.name(): _json_safe(p.eval())
                            for p in child.parms() if not p.isAtDefault()
                        },
                    }
                    if parent_id:
                        entry["parent"] = parent_id
                    nodes.append(entry)

                    for connection in child.inputConnections():
                        src = connection.inputNode()
                        if src is None:
                            continue
                        edges.append({
                            "source": self._rel(src),
                            "sourceOutput": connection.outputIndex(),
                            "target": node_id,
                            "targetInput": connection.inputIndex(),
                        })
                    if child.children():
                        visit(child, node_id)

            visit(self._sandbox, None)
            return {
                "version": 1,
                "app": "houdini",
                "sandbox": self.sandbox_path,
                "created": datetime.datetime.now().isoformat(),
                "nodes": nodes,
                "edges": edges,
            }

        graph = _run_in_main_thread(_export)
        self._append_audit({
            "event": "graph_exported",
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
        })
        return graph

    def export_step_screenshots(self) -> list[dict]:
        """
        _capture_step_screenshot() が蓄積した per-step スクリーンショット一覧を
        返す（新しい順ではなく、実行順のまま）。動画側の --houdini-screenshots
        マニフェストはこれをそのままJSON化したもの。
        """
        return list(self.step_screenshots)
