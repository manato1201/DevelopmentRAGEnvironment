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
            "アニメーションさせたいときは value の代わりに expression（時間で変わる式）か "
            "keyframes（フレームごとの値）を渡す。この2つはタプルではなく成分名（'tx','ty','tz'）で指定する。"
            "ランプ（Ramp: グラデーションやカーブ）のパラメータは value では設定できない（点が1個に潰れる）ので、"
            "ramp（ポイントの配列）で指定する。"
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
                    "description": "設定する値。タプルには空白区切り文字列。expression/keyframes を使うときは不要",
                },
                "expression": {
                    "type": "string",
                    "description": (
                        "Hscript の式（アニメーション用）。例: 'sin($F*0.2)*3'、'fit($F,1,48,0,5)'、"
                        "'$FF*0.1'。$F は現在のフレーム。数値パラメータにだけ使える"
                    ),
                },
                "keyframes": {
                    "type": "array",
                    "description": "キーフレーム（アニメーション用）。例: [{\"frame\":1,\"value\":0},{\"frame\":24,\"value\":5}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "frame": {"type": "number"},
                            "value": {"type": "number"},
                        },
                        "required": ["frame", "value"],
                    },
                },
                "interpolation": {
                    "type": "string",
                    "enum": ["bezier", "linear", "constant", "ease"],
                    "description": "keyframes の補間（既定 bezier）。ramp の補間にも使う（既定 linear。ease は滑らか）",
                },
                "ramp": {
                    "type": "array",
                    "description": (
                        "ランプパラメータ用。pos（0〜1）と value のポイントを2個以上。数値ランプは value が数、"
                        "カラーランプは value が [r,g,b]。例: [{\"pos\":0,\"value\":1},{\"pos\":0.5,\"value\":3},{\"pos\":1,\"value\":1}]"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "pos": {"type": "number"},
                            "value": {"type": ["number", "array"], "items": {"type": "number"}},
                        },
                        "required": ["pos", "value"],
                    },
                },
            },
            "required": ["node", "parm"],
        },
    },
    {
        "name": "connect_nodes",
        "description": (
            "2つのノードを接続する（from_node の出力 → to_node の入力）。"
            "入力の意味が名前で決まるノード（VOPなど）は、番号ではなく input_name で指定すること"
            "（例: turbnoise の入力0は pos ではなく type。番号の取り違えはcookが通ってしまい気づけない）。"
            "入力名は get_node_info で確認できる。"
        ),
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
                "input_name": {
                    "type": "string",
                    "description": "接続先の入力名（input_index の代わり。例: 'pos'）。get_node_info の in[i] \"名前\" で確認",
                },
                "output_name": {
                    "type": "string",
                    "description": "接続元の出力名（output_index の代わり。例: 'P'）",
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
                    "description": "ノードカテゴリ: 'Sop' | 'Object' | 'Dop' | 'Vop' | 'Cop'（Copernicus。copnet の中身） | 'Cop2'（旧COP） | 'Top' | 'Lop' | 'Chop'",
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
        "name": "inspect_geometry",
        "description": (
            "ノードの出力の「中身」を調べる。cook が成功しても、点が0個・範囲がおかしい・属性が付いていない・"
            "画像が一定値、といった失敗は分からないため、cook_node の後にこれで結果を確かめること。"
            "SOP: 点/プリミティブ数、バウンディングボックス、属性（型と値の範囲）、グループ。"
            "COP（Copernicus）: 解像度、チャンネル数、値の範囲（最小/最大/平均）、一定値かどうか。"
            "LOP: ステージ内のプリム一覧。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "調べるノードのサンドボックス相対パス（SOP / COP / LOP）",
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
            "場合はMergeノードで結合して接続する等）を行い、その後もう一度 finish_tutorial"
            "を呼んでから再度この confirm_tutorial を呼び直すこと。表示フラグはシステムが"
            "自動で設定する（connect_nodes で末端になったノードが表示される）ので、"
            "フラグを操作しようとする必要はない。"
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

    # best_unconfirmed_draft() が下書きを「プレースホルダー水準」とみなして棄却する
    # 閾値（title+overview+steps+pitfalls+next_stepsの合計文字数）。実機で、モデルが
    # confirm_tutorialを一度も呼ばずに生成を終え、しかも最後のfinish_tutorial呼び出しが
    # title="テスト"のようなプレースホルダー内容だった事例を確認した（2026-09-13）。
    _MIN_DRAFT_CONTENT_CHARS = 80

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
        # finish_tutorial の全呼び出し履歴（2026-09-13追加）。confirm_tutorialが一度も
        # 呼ばれないまま生成が打ち切られた場合のフォールバック選定（best_unconfirmed_draft）
        # に使う。_pending_finishは直近1件しか持たないため、「最後の下書きがたまたま
        # プレースホルダーだった」場合に以前の良い下書きへ戻れるよう、全件を残す。
        self._finish_drafts: list[dict] = []
        # 直前の finish_tutorial 呼び出しで撮ったビューポート画像（base64 PNG）。
        # tutorial_agent.py 側がこれを読み、その1回だけ tool_result に画像として添付する。
        self.last_screenshot_b64: str | None = None
        self.step_log: list[dict] = []        # Markdown 組み立て用の全呼び出し履歴
        # 各ステップ実行直後に撮ったビューポート/ネットワークエディタの
        # スクリーンショット一覧（動画生成側で手順ごとの画面を見せるため）。
        # {"step": int, "tool": str, "viewport": str|None, "network": str|None}
        self.step_screenshots: list[dict] = []
        # 最後に connect_nodes で「末端（出力先の無いノード）」になったノードのパス。
        # finish_tutorial 直前にここへ表示フラグを戻し、見た目の自己確認画像が
        # 途中の cook_node で表示を切り替えた中間ノードにならないようにする。
        self._display_candidate_path: str | None = None
        # 直近の set_parameter が変えた内容（旧値→新値）と、同じノードへの連続した
        # set_parameter を1枚のパラメータカードにまとめるための状態（動画用）。
        self._last_parm_change: dict | None = None
        self._param_group: dict | None = None
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
            self._capture_step_screenshot(tool_name, tool_input, result)
        if not is_error and tool_name == "finish_tutorial":
            self._capture_finish_screenshot()

        return result, is_error

    def log_event(self, record: dict) -> None:
        """呼び出し側（tutorial_agent.py）が生成の経過を監査ログ（JSONL）へ残すための公開口。"""
        self._append_audit(record)

    # ── ビューポート表示フラグの管理 ────────────────────────────────────────────

    def _show_in_viewport(self, node) -> None:
        """
        SOP の display/render フラグをこのノードへ移し、ビューポートにこのノードの結果を映す。

        2026-09-26追加（実機ログで判明）: createNode()で作ったSOPは最初の1個にしか表示
        フラグが付かず、その後に作ったノード・接続した末端ノードは表示されないままだった。
        そのためビューポート画像（動画素材・finish_tutorial直後の自己確認画像）が
        最初のノード（球）のまま変わらず、モデルが「意図した見た目にならない」と判断しても
        直す手段（フラグを設定するツール）が無く、confirm_tutorial に辿り着けず打ち切りに
        なっていた。システムプロンプトは「ディスプレイフラグは不要」と案内していたので、
        その約束をここで実際に成立させる。SOP以外（DOP/VOP等）にはフラグの意味が違うため触らない。
        """
        try:
            if node.type().category().name() != "Sop":
                return
        except Exception:  # noqa: BLE001
            return
        for setter_name in ("setDisplayFlag", "setRenderFlag"):
            setter = getattr(node, setter_name, None)
            if setter is None:
                continue
            try:
                setter(True)
            except Exception:  # noqa: BLE001 -- 表示切替の失敗で生成を止めない
                pass

    def _restore_final_display(self) -> None:
        """最後に接続した末端ノードへ表示フラグを戻す（finish_tutorial直後の自己確認画像用）。"""
        if not self._display_candidate_path:
            return
        node = self._hou.node(self._display_candidate_path)
        if node is not None:
            self._show_in_viewport(node)

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
            # 途中のcook_nodeで表示を中間ノードへ切り替えていても、自己確認画像は
            # 必ず最終（末端）ノードの結果を映す。
            self._restore_final_display()
            if screen_capture.capture_viewport(path, log_path=log_path):
                try:
                    self.last_screenshot_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
                except OSError:
                    pass

        try:
            _run_in_main_thread(_capture)
        except Exception:  # noqa: BLE001 -- best-effort, never raise
            pass

    def _step_focus_path(self, tool_name: str, tool_input: dict, tool_result: str) -> str | None:
        """
        このツール呼び出しが触ったノードの絶対パスを返す（無ければNone）。
        ネットワーク画面の撮影対象（そのノードが属するネットワーク）と強調表示に使う。
        delete_node は対象が既に消えているためNone（呼び出し側は親パスを別途求める）。
        """
        rel: str | None = None
        if tool_name == "create_node":
            match = re.match(r"作成しました: (\S+?)（", tool_result)
            rel = match.group(1) if match else None
        elif tool_name == "connect_nodes":
            rel = tool_input.get("to_node")
        elif tool_name in ("set_parameter", "cook_node"):
            rel = tool_input.get("node")
        if not rel:
            return None
        try:
            return self._resolve(rel).path()
        except Exception:  # noqa: BLE001
            return None

    def _step_network_path(self, tool_name: str, tool_input: dict, focus_path: str | None) -> str:
        """撮影するネットワーク（＝ノードを内包するコンテナ）のパス。特定できなければサンドボックス。"""
        if focus_path and "/" in focus_path:
            return focus_path.rsplit("/", 1)[0]
        if tool_name == "delete_node":
            rel = (tool_input.get("node") or "").strip()
            if "/" in rel:
                return f"{self.sandbox_path}/{rel.rsplit('/', 1)[0]}"
        return self.sandbox_path

    @staticmethod
    def _leaf(path: str | None) -> str:
        return (path or "").rstrip("/").rsplit("/", 1)[-1]

    def _step_instruction(self, tool_name: str, tool_input: dict, tool_result: str, focus_path: str | None,
                          changes: list[dict] | None) -> str:
        """
        このステップで学習者が行う操作を、1〜2文の短い日本語にする。動画のスライド左側の
        文章になる。以前はツールの結果文（「接続しました: A[out:0] → B[in:0]」）をそのまま出して
        いたため、見ても何をすればよいか分からなかった（2026-10-04）。
        """
        node = self._leaf(focus_path) or self._leaf(tool_input.get("node"))
        if tool_name == "create_node":
            name = self._leaf(focus_path) or tool_input.get("name") or tool_input.get("node_type", "")
            try:
                ntype = self._hou.node(focus_path).type()
                desc, tname = ntype.description(), ntype.name()
            except Exception:  # noqa: BLE001
                desc, tname = tool_input.get("node_type", ""), tool_input.get("node_type", "")
            if not tool_input.get("parent"):
                return f"Object レベルに「{desc}」ノードを作り、名前を {name} にする。この中で作業する"
            return f"「{desc}」ノード（{tname}）を作り、名前を {name} にする"
        if tool_name == "connect_nodes":
            src, dst = self._leaf(tool_input.get("from_node")), self._leaf(tool_input.get("to_node"))
            idx = int(tool_input.get("input_index", 0) or 0)
            if tool_input.get("input_name"):
                return f"{src} の出力を、{dst} の「{tool_input['input_name']}」入力につなぐ"
            if idx > 0:
                return f"{src} の出力を、{dst} の{idx + 1}番目の入力につなぐ"
            return f"{src} の出力を、{dst} の入力につなぐ"
        if tool_name == "set_parameter" and changes:
            if len(changes) == 1 and changes[0].get("code"):
                return f"{node} の「{changes[0]['label']}」欄に、次のコードを入力する"
            shown = "、".join(f"{c['label']} を {c['new']}" for c in changes[:3])
            more = f" ほか{len(changes) - 3}件" if len(changes) > 3 else ""
            return f"{node} のパラメータを設定: {shown}{more}"
        if tool_name == "cook_node":
            if "[エラー]" in tool_result:
                return f"{node} を評価（cook）するとエラーが出る。内容を読んで原因を直す"
            return f"{node} を評価（cook）して、エラーが出ないことを確認する"
        if tool_name == "delete_node":
            return f"不要になった {self._leaf(tool_input.get('node'))} を削除する"
        return tool_result

    def _capture_step_screenshot(self, tool_name: str, tool_input: dict, tool_result: str) -> None:
        """
        ツール呼び出し成功直後にビューポート/ネットワークエディタ（set_parameterでは
        パラメータカード）を撮影する（ベストエフォート）。動画生成側で各手順のノード操作を
        個別に見せられるようにするための per-step キャプチャ。

        動画側は Markdown の「### N.」というClaude自身が後から書いた"要約"ステップ番号と、
        この実行単位のステップ番号が全く別物であることを前提に、各ステップの
        "result" テキストを直接そのスライドの説明文として使う（要約番号と実行番号を
        突き合わせようとすると、実機テストで無関係な画面が表示される不具合が確認された）。
        2026-10-04: その "result" を、ツールの結果文ではなく「学習者が行う操作」の短い文章
        （_step_instruction）にした。元のツール結果は "tool_result" に残す。

        同じノードへの連続した set_parameter は1ステップ（1枚のパラメータカード）に
        まとめる。以前は7個のパラメータを設定すると7枚の似たスライドになっていた。
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
            log_path = self._screenshot_dir / "capture.log"
            focus_path = self._step_focus_path(tool_name, tool_input, tool_result)
            container_path = self._step_network_path(tool_name, tool_input, focus_path)

            # ---- 連続する set_parameter を同じステップにまとめる ----
            changes: list[dict] | None = None
            replace_last = False
            step_index = len(self.step_screenshots) + 1
            change = self._last_parm_change if tool_name == "set_parameter" else None
            if change is not None:
                group = self._param_group
                if (
                    group is not None and group["node"] == change["node_path"]
                    and self.step_screenshots and self.step_screenshots[-1].get("step") == group["step"]
                ):
                    for existing in group["changes"]:
                        if existing["name"] == change["name"]:
                            existing["new"] = change["new"]  # 同じ欄を2回設定したら最新値（旧値は最初のまま）
                            break
                    else:
                        group["changes"].append(change)
                    step_index = group["step"]
                    replace_last = True
                else:
                    self._param_group = group = {"node": change["node_path"], "changes": [change], "step": step_index}
                changes = group["changes"]
            else:
                self._param_group = None

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

            network_kind = "network"
            if changes:
                # set_parameter: どのパラメータをいくつからいくつに変えたかを見せるカード。
                try:
                    node = self._hou.node(change["node_path"])
                    changed = {c["name"] for c in changes}
                    others = [
                        (p.name(), (self._safe_eval(p)[:24] or "?"))
                        for p in node.parms()
                        if not p.isAtDefault() and p.name() not in changed and p.tuple().name() not in changed
                        and "\n" not in self._safe_eval(p)
                    ][:5]
                    got_network = screen_capture.render_parameter_card(
                        network_path, container_path, node.name(), node.type().description(),
                        changes, others, log_path=log_path,
                    )
                    network_kind = "parameter"
                except Exception as exc:  # noqa: BLE001
                    screen_capture._log(f"parameter card failed: {exc!r}", log_path)
                    got_network = False
            else:
                # ネットワーク画面は「実際に作業しているネットワーク」を映す。以前は常に
                # サンドボックス直下を撮っていたため、作業の実体がgeoノードの中にある
                # 場合（システムプロンプトがそう指示している）、geoの箱1個しか映らなかった。
                screen_capture.focus_network_on(container_path, log_path=log_path)
                got_network = screen_capture.capture_network_editor(
                    network_path,
                    log_path=log_path,
                    container_path=container_path,
                    focus_path=focus_path,
                    callout=tool_result,
                )
            entry = {
                "step": step_index,
                "tool": tool_name,
                "result": self._step_instruction(tool_name, tool_input, tool_result, focus_path, changes),
                "tool_result": tool_result,
                "viewport": str(viewport_path) if got_viewport else None,
                "network": str(network_path) if got_network else None,
                "network_kind": network_kind,
                "viewport_clip_frames": [str(p) for p in clip_frames],
                "viewport_clip_fps": clip_fps,
            }
            if replace_last:
                self.step_screenshots[-1] = entry
            else:
                self.step_screenshots.append(entry)

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

        self._last_parm_change = None
        if args.get("ramp"):
            return self._set_parameter_ramp(node, parm_name, args)
        if args.get("expression") is not None or args.get("keyframes"):
            return self._set_parameter_animation(node, parm_name, args)
        if "value" not in args:
            return "value、expression、keyframes のいずれかを指定してください"
        value = args["value"]
        parm = node.parm(parm_name)
        if parm is not None and self._is_ramp_parm(parm):
            # value を渡すとランプが「点1個」に潰れるのに「ok」と返っていた（2026-10-05に実機で発見）。
            return (
                f"'{parm_name}' はランプパラメータです。value では設定できません。"
                f"ramp 引数でポイントを渡してください（現在: {self._ramp_summary(parm)}）。"
                "例: ramp=[{\"pos\":0,\"value\":1},{\"pos\":1,\"value\":0}]"
            )
        if parm is not None:
            old_value = self._safe_eval(parm)
            parm.set(self._coerce_scalar(parm, value))
            self._last_parm_change = {
                "node_path": node.path(), "name": parm_name, "label": self._parm_label(parm),
                "old": old_value, "new": str(value), "code": self._is_code_parm(parm, value),
            }
            return f"{self._rel(node)}.{parm_name} = {value}"

        tuple_parm = node.parmTuple(parm_name)
        if tuple_parm is not None:
            components = str(value).split()
            if len(components) != len(tuple_parm):
                return (
                    f"タプル {parm_name} は {len(tuple_parm)} 成分です。"
                    f"空白区切りで {len(tuple_parm)} 個の値を渡してください（受領: {value}）"
                )
            old_value = " ".join(self._safe_eval(p) for p in tuple_parm)
            tuple_parm.set(tuple(float(c) for c in components))
            try:
                tuple_label = tuple_parm.parmTemplate().label() or parm_name
            except Exception:  # noqa: BLE001
                tuple_label = parm_name
            self._last_parm_change = {
                "node_path": node.path(), "name": parm_name, "label": tuple_label,
                "old": old_value, "new": " ".join(components), "code": False,
            }
            return f"{self._rel(node)}.{parm_name} = ({', '.join(components)})"

        available = ", ".join(p.name() for p in node.parms()[:40])
        return (
            f"パラメータ '{parm_name}' が見つかりません。"
            f"利用可能なパラメータ（先頭40件）: {available}"
        )

    def _set_parameter_animation(self, node, parm_name: str, args: dict) -> str:
        """
        数値パラメータに式（expression）またはキーフレーム（keyframes）を設定する（2026-10-05追加）。
        以前は set_parameter が固定値しか設定できず、「sin($F*0.2)*3」のような式を渡すと
        「numeric parm to a non-numeric value」で失敗し、アニメーションを一切作れなかった。
        設定後に数フレームを評価して値の変化を返す（モデルが「本当に動くか」を確認できる）。
        """
        hou = self._hou
        parm = node.parm(parm_name)
        if parm is None:
            tuple_parm = node.parmTuple(parm_name)
            if tuple_parm is not None:
                names = ", ".join(p.name() for p in tuple_parm)
                return f"{parm_name} はタプルです。式・キーフレームは成分ごとに設定してください（{names}）"
            available = ", ".join(p.name() for p in node.parms()[:40])
            return f"パラメータ '{parm_name}' が見つかりません。利用可能なパラメータ（先頭40件）: {available}"

        old_value = self._safe_eval(parm)
        expression = args.get("expression")
        keyframes = args.get("keyframes")
        if expression is not None:
            parm.deleteAllKeyframes()
            parm.setExpression(str(expression), hou.exprLanguage.Hscript)
            shown = f"= {expression}"
            summary = f"式 {expression}"
        else:
            interp = {"bezier": "bezier()", "linear": "linear()", "constant": "constant()", "ease": "ease()"}.get(
                str(args.get("interpolation") or "bezier"), "bezier()"
            )
            parm.deleteAllKeyframes()
            ordered = sorted(keyframes, key=lambda k: float(k["frame"]))
            for item in ordered:
                key = hou.Keyframe()
                key.setFrame(float(item["frame"]))
                key.setValue(float(item["value"]))
                key.setExpression(interp, hou.exprLanguage.Hscript)
                parm.setKeyframe(key)
            shown = "キーフレーム " + ", ".join(f"F{float(k['frame']):g}={float(k['value']):g}" for k in ordered)
            summary = f"{len(ordered)}個のキーフレーム（{args.get('interpolation') or 'bezier'}）"

        start = float(ordered[0]["frame"]) if expression is None else float(hou.frame())
        end = float(ordered[-1]["frame"]) if expression is None else start + 24
        samples = []
        for frame in (start, (start + end) / 2, end):
            try:
                samples.append(f"F{frame:g}={parm.evalAtFrame(frame):.4g}")
            except Exception as exc:  # noqa: BLE001
                return f"{self._rel(node)}.{parm_name} に{summary}を設定しましたが、評価でエラー: {exc}"
        # 不正な式（未知の関数・括弧の不整合など）は評価値が黙って0になり、例外にならず
        # node.errors() にだけ出る。0を「正常な値」と誤解させないため、ここで拾って返す。
        try:
            node.cook(force=True)
        except Exception:  # noqa: BLE001
            pass
        problems = [e for e in node.errors() if "expression" in e.lower() or parm_name in e]
        if problems:
            return (
                f"{self._rel(node)}.{parm_name} に{summary}を設定しましたが、式にエラーがあります: "
                f"{' / '.join(problems)}。式を直して設定し直してください（Hscriptの関数: sin, cos, fit, rand, noise など）"
            )
        self._last_parm_change = {
            "node_path": node.path(), "name": parm_name, "label": self._parm_label(parm),
            "old": old_value, "new": shown, "code": False,
        }
        return f"{self._rel(node)}.{parm_name} に{summary}を設定（{', '.join(samples)}）"

    def _is_ramp_parm(self, parm) -> bool:
        try:
            return parm.parmTemplate().type() == self._hou.parmTemplateType.Ramp
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _ramp_summary(parm) -> str:
        try:
            ramp = parm.eval()
            parts = []
            for key, value in zip(ramp.keys(), ramp.values()):
                if isinstance(value, (tuple, list)):
                    shown = "(" + ",".join(f"{c:.2g}" for c in value) + ")"
                else:
                    shown = f"{value:.4g}"
                parts.append(f"{key:.3g}→{shown}")
            return f"{len(parts)}点 " + ", ".join(parts)
        except Exception:  # noqa: BLE001
            return "?"

    def _set_parameter_ramp(self, node, parm_name: str, args: dict) -> str:
        """ランプ（グラデーション・カーブ）パラメータを、ポイントの配列で設定する（2026-10-05追加）。"""
        hou = self._hou
        parm = node.parm(parm_name)
        if parm is None or not self._is_ramp_parm(parm):
            ramps = [p.name() for p in node.parms() if self._is_ramp_parm(p)]
            hint = f"このノードのランプパラメータ: {', '.join(ramps)}" if ramps else "このノードにランプパラメータはありません"
            return f"'{parm_name}' はランプパラメータではありません。{hint}"
        is_color = parm.parmTemplate().parmType() == hou.rampParmType.Color
        basis_map = {
            "linear": hou.rampBasis.Linear, "bezier": hou.rampBasis.Bezier,
            "constant": hou.rampBasis.Constant, "ease": hou.rampBasis.MonotoneCubic,
        }
        basis = basis_map.get(str(args.get("interpolation") or "linear"), hou.rampBasis.Linear)
        points = sorted(args["ramp"], key=lambda p: float(p["pos"]))
        if len(points) < 2:
            return "ランプは2点以上のポイントが必要です"
        keys, values = [], []
        for point in points:
            keys.append(float(point["pos"]))
            value = point["value"]
            if is_color:
                comps = value.split() if isinstance(value, str) else value
                if not isinstance(comps, (list, tuple)) or len(comps) != 3:
                    return f"'{parm_name}' はカラーランプです。value は [r,g,b] の3成分で渡してください"
                values.append(tuple(float(c) for c in comps))
            else:
                if isinstance(value, (list, tuple)):
                    return f"'{parm_name}' は数値ランプです。value は数値で渡してください"
                values.append(float(value))
        old_value = self._ramp_summary(parm)
        parm.set(hou.Ramp((basis,) * len(keys), tuple(keys), tuple(values)))
        new_value = self._ramp_summary(parm)
        self._last_parm_change = {
            "node_path": node.path(), "name": parm_name, "label": self._parm_label(parm),
            "old": old_value, "new": new_value, "code": False,
        }
        return f"{self._rel(node)}.{parm_name} = ランプ {new_value}"

    @staticmethod
    def _port_names(node, kind: str) -> list[str]:
        try:
            return list(node.inputNames() if kind == "in" else node.outputNames())
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _port_label(names: list[str], index: int) -> str:
        """入出力名の表示。input1 / source のような名前に意味が無いものは出さない。"""
        if index < len(names) and names[index] and not re.fullmatch(r"(input|source|output)\d*", names[index]):
            return f" {names[index]}"
        return ""

    def _port_index(self, names: list[str], wanted: str, label: str, node) -> int:
        if wanted in names:
            return names.index(wanted)
        listing = ", ".join(f"{i}:{n}" for i, n in enumerate(names)) or "（名前を取得できません。番号で指定してください）"
        raise ValueError(f"{label}名 '{wanted}' が見つかりません。{node.name()} の{label}: {listing}")

    def _tool_inspect_geometry(self, args: dict) -> str:
        """cook後の「中身」を数値で返す（2026-10-05追加）。cookの成功だけでは、点が0個・一定値の画像・
        属性の付け忘れなどに気づけなかった。SOP / COP(Copernicus) / LOP に対応。"""
        node = self._resolve(args["node"])
        category = node.type().category().name()
        try:
            node.cook(force=False)
        except Exception:  # noqa: BLE001
            pass
        lines = [f"ノード: {self._rel(node)}（タイプ: {node.type().name()} / カテゴリ: {category}）"]
        lines += [f"  [エラー] {e}" for e in node.errors()]
        if category == "Sop":
            lines += self._inspect_sop(node)
        elif category == "Cop":
            lines += self._inspect_cop(node)
        elif category == "Lop":
            lines += self._inspect_lop(node)
        else:
            lines.append(f"このカテゴリ（{category}）の中身の検査には未対応です（Sop / Cop / Lop に対応）")
        return "\n".join(lines)

    _INSPECT_STAT_LIMIT = 200_000

    @staticmethod
    def _fmt_num(value) -> str:
        if isinstance(value, float):
            return f"{value:.4g}"
        return str(value)

    def _inspect_sop(self, node) -> list[str]:
        import itertools
        from collections import Counter

        hou = self._hou
        geo = node.geometry()
        if geo is None:
            return ["ジオメトリがありません（このノードは何も出力していません）"]
        n_points = geo.intrinsicValue("pointcount")
        n_prims = geo.intrinsicValue("primitivecount")
        n_verts = geo.intrinsicValue("vertexcount")
        lines = [f"点: {n_points} / プリミティブ: {n_prims} / 頂点: {n_verts}"]
        if n_points == 0 and n_prims == 0:
            lines.append("※ ジオメトリが空です（点もプリミティブも0個）。入力の接続・パラメータ・グループ指定を確認してください")
            return lines
        try:
            box = geo.boundingBox()
            size, center = box.sizevec(), box.center()
            lines.append(
                f"バウンディングボックス: サイズ ({size[0]:.4g}, {size[1]:.4g}, {size[2]:.4g}) / "
                f"中心 ({center[0]:.4g}, {center[1]:.4g}, {center[2]:.4g})"
            )
        except Exception:  # noqa: BLE001
            pass
        if n_prims:
            sample = list(itertools.islice(geo.iterPrims(), 20000))
            kinds = Counter(p.type().name() for p in sample)
            note = f"（先頭{len(sample)}件で集計）" if n_prims > len(sample) else ""
            lines.append("プリミティブの種類: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common(6)) + note)

        def describe(attrib, values_fn, count) -> str:
            data_type = attrib.dataType()
            type_name = str(data_type).split(".")[-1].lower()
            size = attrib.size()
            label = f"{attrib.name()}({type_name}{size if size > 1 else ''})"
            if data_type not in (hou.attribData.Float, hou.attribData.Int) or values_fn is None or count == 0:
                return label
            if count * size > self._INSPECT_STAT_LIMIT:
                return label + "[多数のため統計は省略]"
            try:
                values = values_fn(attrib.name())
            except Exception:  # noqa: BLE001
                return label
            if not values:
                return label
            if size == 1:
                return f"{label}[{self._fmt_num(min(values))}〜{self._fmt_num(max(values))}, 平均{sum(values) / len(values):.4g}]"
            comps = [values[i::size] for i in range(min(size, 3))]
            spans = " ".join(f"[{self._fmt_num(min(c))},{self._fmt_num(max(c))}]" for c in comps)
            return f"{label}{spans}"

        for title, attribs, fn, count in (
            ("ポイント属性", geo.pointAttribs(), geo.pointFloatAttribValues, n_points),
            ("プリミティブ属性", geo.primAttribs(), geo.primFloatAttribValues, n_prims),
            ("頂点属性", geo.vertexAttribs(), None, n_verts),
        ):
            shown = []
            for attrib in list(attribs)[:25]:
                if attrib.name() == "P":
                    continue
                fn_for = fn
                if fn is not None and attrib.dataType() == hou.attribData.Int:
                    fn_for = geo.pointIntAttribValues if title == "ポイント属性" else geo.primIntAttribValues
                shown.append(describe(attrib, fn_for, count))
            if shown:
                lines.append(f"{title}: " + ", ".join(shown))
        detail = []
        for attrib in list(geo.globalAttribs())[:12]:
            try:
                value = str(geo.attribValue(attrib.name()))
            except Exception:  # noqa: BLE001
                value = "?"
            detail.append(f"{attrib.name()}={value[:40]}")
        if detail:
            lines.append("ディテール属性: " + ", ".join(detail))
        groups = [g.name() for g in geo.pointGroups()][:10] + [g.name() for g in geo.primGroups()][:10]
        if groups:
            lines.append("グループ: " + ", ".join(groups))
        names = {a.name() for a in geo.pointAttribs()}
        if {"opacity", "scale_0", "rot_0", "f_dc_0"} <= names:
            lines.append("※ 3DGS属性を持つポイントです（GSplatのデータ）。表示・レンダーには bakegsplat での変換が必要です")
        elif "GS_Alpha" in names:
            lines.append("※ bakegsplat 済みのGSplatです（orient / scale / Cd / GS_Alpha）")
        return lines

    def _inspect_cop(self, node) -> list[str]:
        try:
            layer = node.layer()
        except Exception as exc:  # noqa: BLE001
            return [f"レイヤーを取得できませんでした: {exc}"]
        if layer is None:
            return ["レイヤーがありません（このCOPノードは画像を出力していません）"]
        lines = []
        try:
            res = layer.bufferResolution()
            storage = str(layer.storageType()).split(".")[-1]
            lines.append(f"解像度: {res[0]}x{res[1]} / チャンネル数: {layer.channelCount()} / 型: {storage}")
        except Exception:  # noqa: BLE001
            pass
        try:
            lines.append(
                f"値の範囲: 最小 {layer.computeMin()} / 最大 {layer.computeMax()} / 平均 {layer.computeAverage()}"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            if layer.isConstant():
                lines.append("※ 画像は一定値です（全ピクセルが同じ）。入力の接続やパラメータを確認してください")
        except Exception:  # noqa: BLE001
            pass
        return lines or ["画像の情報を取得できませんでした"]

    def _inspect_lop(self, node) -> list[str]:
        import itertools
        from collections import Counter

        try:
            stage = node.stage()
        except Exception as exc:  # noqa: BLE001
            return [f"ステージを取得できませんでした: {exc}"]
        if stage is None:
            return ["ステージがありません"]
        prims = [(str(p.GetPath()), p.GetTypeName()) for p in itertools.islice(stage.Traverse(), 2000)]
        prims = [p for p in prims if p[0] != "/HoudiniLayerInfo"]
        if not prims:
            return ["ステージにプリムがありません（空です）"]
        kinds = Counter(kind or "（型なし）" for _, kind in prims)
        lines = [f"プリム: {len(prims)}件 / 種類: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common(8))]
        lines += [f"  {path}  [{kind or '型なし'}]" for path, kind in prims[:30]]
        if len(prims) > 30:
            lines.append(f"  …ほか{len(prims) - 30}件")
        return lines

    def _cook_top_static(self, node) -> str:
        """
        TOPノードは cook() しても作業項目が生成されず、実際には何もしていないのに「cook成功」に
        見えていた（2026-10-05に実機で発見）。作業項目を「生成」して数を返す。ただし作業の「実行」
        （pythonscriptの実行・ファイル出力・プロセス起動）は副作用があり、サンドボックスの
        ノードパス制限では防げないため行わない。
        """
        generate_error = None
        try:
            node.generateStaticWorkItems(block=True)
        except Exception as exc:  # noqa: BLE001
            generate_error = repr(exc)
        chain, seen, stack = [], set(), [node]
        while stack:
            current = stack.pop()
            if current.path() in seen:
                continue
            seen.add(current.path())
            chain.append(current)
            stack.extend(i for i in current.inputs() if i is not None)
        counts = []
        total = 0
        for current in reversed(chain):
            try:
                pdg_node = current.getPDGNode()
                n_items = len(pdg_node.workItems) if pdg_node is not None else 0
            except Exception:  # noqa: BLE001
                n_items = 0
            total += n_items
            counts.append(f"  {self._rel(current)}: 作業項目 {n_items}件")
        errors = list(node.errors())
        warnings = list(node.warnings())
        if generate_error and not errors:
            errors = [f"作業項目の生成で例外: {generate_error}"]
        header = f"TOP の作業項目を生成: {self._rel(node)}（生成のみ。作業の実行はしていません）"
        lines = [header] + counts
        lines.append(
            "  ※ 実行（ファイル出力・プロセス起動）は行いません。partition / wait 系の作業項目は実行時に"
            "決まるため0件になることがあります"
        )
        if total == 0 and not errors:
            lines.append("  ※ 作業項目が0件です。上流にジェネレーター（wedge, genericgenerator, filepattern 等）があるか確認してください")
        lines += [f"  [エラー] {e}" for e in errors]
        lines += [f"  [警告] {w}" for w in warnings]
        if not errors:
            lines[0] = f"cook 成功（TOPは作業項目の生成まで）: {self._rel(node)}（エラーなし）"
        return "\n".join(lines)

    @staticmethod
    def _safe_eval(parm) -> str:
        """パラメータの現在値を、表示用の短い文字列にする（取れなければ空）。"""
        try:
            v = parm.eval()
            if isinstance(v, float):
                return f"{v:.6g}"
            return str(v)
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _parm_label(parm) -> str:
        """Houdiniの画面に出る表示名（例: "Size X"、"Divisions Z"）。"""
        try:
            base = parm.parmTemplate().label() or parm.name()
            if len(parm.tuple()) > 1:
                index = parm.componentIndex()
                base += " " + ("XYZW"[index] if index < 4 else str(index + 1))
            return base
        except Exception:  # noqa: BLE001
            return parm.name()

    @staticmethod
    def _is_code_parm(parm, value) -> bool:
        """VEX等のコード欄（複数行の文字列、または snippet 系）かどうか。"""
        return "\n" in str(value) or parm.name() in ("snippet", "python", "code")

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
        in_names = self._port_names(dst, "in")
        out_names = self._port_names(src, "out")
        if args.get("input_name"):
            input_index = self._port_index(in_names, str(args["input_name"]), "入力", dst)
        if args.get("output_name"):
            output_index = self._port_index(out_names, str(args["output_name"]), "出力", src)
        dst.setInput(input_index, src, output_index)
        # 接続先が末端（出力先が無いノード）なら、それがこのグラフの「今の結果」なので
        # ビューポートに映す（_show_in_viewport参照）。
        if not dst.outputs():
            self._display_candidate_path = dst.path()
            self._show_in_viewport(dst)
        # 入出力名も返す。番号だけの接続は、意図と違う入力（例: pos のつもりで type）へつないでも
        # cook が通ってしまうため、何につないだかをモデルが見て気づけるようにする。
        return (
            f"接続しました: {self._rel(src)}[out:{output_index}{self._port_label(out_names, output_index)}] → "
            f"{self._rel(dst)}[in:{input_index}{self._port_label(in_names, input_index)}]"
        )

    def _simulation_type_hint(self, node) -> str | None:
        """
        pyro/fire/クロス/パーティクル/流体/剛体等のシミュレーション系ノードなら、
        一致した _SIMULATION_TYPE_HINTS の文字列を返す（そうでなければNone）。
        単一フレームのcookでは時間発展する挙動を検証できないため複数フレーム評価する。
        2026-09-20追加: 以前はbool（一致したかどうか）だけを返していたが、動画生成の
        クリップ撮影が「なぜ発生した/しなかったか」を後から追いにくいという指摘が
        あったため、判定根拠（どのヒント文字列に一致したか）自体を呼び出し元
        （_tool_cook_nodeのsim_note）へ伝えられるようにした。
        """
        type_name = node.type().name().lower()
        for hint in self._SIMULATION_TYPE_HINTS:
            if hint in type_name:
                return hint
        return None

    def _cook_simulation_frames(self, node) -> tuple[int, str | None]:
        """
        現在のグローバルフレームから _SIM_COOK_FRAME_COUNT フレーム分、順番に
        フレームを進めながらcookする（シミュレーションは前のフレームの結果に
        依存するため、途中のフレームを飛ばさず1フレームずつ進める必要がある）。
        呼び出し前のフレームは必ず復元する（ユーザーの作業状態を変えないため）。
        戻り値: (実際に評価したフレーム数, 最後に発生した例外のrepr文字列。無ければNone)。
        例外を投げたフレームがあってもnode.errors()に反映されるとは限らないため
        （_tool_cook_node参照）、握りつぶさず呼び出し元へ伝える。
        """
        hou = self._hou
        original_frame = hou.frame()
        evaluated = 0
        last_exception: str | None = None
        try:
            start = int(original_frame)
            for f in range(start, start + self._SIM_COOK_FRAME_COUNT):
                hou.setFrame(f)
                try:
                    node.cook(force=True)
                except Exception as exc:
                    last_exception = repr(exc)
                evaluated += 1
        finally:
            hou.setFrame(original_frame)
        return evaluated, last_exception

    def _tool_cook_node(self, args: dict) -> str:
        node = self._resolve(args["node"])
        try:
            is_top = node.type().category().name() == "Top"
        except Exception:  # noqa: BLE001 -- カテゴリが取れないノードは通常のcookへ
            is_top = False
        if is_top:
            return self._cook_top_static(node)
        sim_hint = self._simulation_type_hint(node)
        is_sim = sim_hint is not None
        frames_evaluated = 0
        cook_exception: str | None = None
        if is_sim:
            frames_evaluated, cook_exception = self._cook_simulation_frames(node)
        else:
            try:
                node.cook(force=True)
            except Exception as exc:
                cook_exception = repr(exc)  # 詳細は下のガードで扱う（errors()が空の場合の保険）
            # 式・キーフレームで時間とともに変わるノード（アニメーション）は、1フレームだけでは
            # 動きの途中で出るエラーを見逃すため、シミュレーションと同様に複数フレーム評価する。
            try:
                if not cook_exception and node.isTimeDependent():
                    frames_evaluated, cook_exception = self._cook_simulation_frames(node)
                    sim_hint, is_sim = "time-dependent", True
            except Exception:  # noqa: BLE001
                pass
        errors = list(node.errors())
        warnings = list(node.warnings())
        if cook_exception and not errors:
            # node.cook()の失敗は通常node.errors()にも反映されるが、稀にerrors()が
            # 空のまま例外だけが飛ぶケースがあり得る。その場合に例外を握りつぶして
            # 「cook成功（エラー・警告なし）」と誤報しないよう、合成のエラー行として
            # 追加する（2026-09-20、リファクタリング時に発見）。
            errors = [f"cook()が例外を送出しました（このノードのerrors()には反映されていません）: {cook_exception}"]
        if is_sim and sim_hint == "time-dependent":
            sim_note = f"（時間とともに変化するノードなので{frames_evaluated}フレーム分evaluateして確認しました）"
        elif is_sim:
            sim_note = (
                f"（シミュレーションノード「{sim_hint}」と判定したため{frames_evaluated}"
                f"フレーム分evaluateして確認しました）"
            )
        else:
            sim_note = ""
        if not errors:
            # cookしたノードの結果を動画のビューポート素材（cook_node回は動画側が
            # ビューポート画像を優先する）に映すため、表示を一時的にこのノードへ切り替える。
            # finish_tutorial 直前に末端ノードへ戻す（_restore_final_display）。
            self._show_in_viewport(node)
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
            "cop2": "cop2NodeTypeCategory",  # 旧COP（copnet ではなく cop2net の中身）
            # Copernicus（H20.5以降の新COP）。`copnet` で作れるのはこちら。以前はこの一覧が
            # 無く、「cop2」で旧COPの名前（Copernicusに存在しない `noise` 等）を返していた。
            "cop": "copNodeTypeCategory",
            "top": "topNodeTypeCategory",
            "lop": "lopNodeTypeCategory",
            "chop": "chopNodeTypeCategory",
        }
        cat_key = args["category"].lower()
        getter_name = category_map.get(cat_key)
        if getter_name is None:
            return f"未知のカテゴリです: {args['category']}（Sop/Object/Dop/Vop/Cop/Cop2/Top/Lop/Chop。copnet の中身は Cop）"
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

        in_names = self._port_names(node, "in")
        connected = list(node.inputs())
        inputs = []
        for i in range(min(max(len(in_names), len(connected)), 16)):
            name = f' "{in_names[i]}"' if i < len(in_names) and in_names[i] else ""
            inp = connected[i] if i < len(connected) else None
            inputs.append(f"  in[{i}]{name} ← {self._rel(inp)}" if inp else f"  in[{i}]{name} ← （未接続）")
        lines.append("入力接続（番号と名前。connect_nodes は input_name でも指定できる）:")
        lines.extend(inputs or ["  （入力なし）"])
        out_names = self._port_names(node, "out")
        if len(out_names) > 1:
            lines.append("出力: " + ", ".join(f"out[{i}] {n}" for i, n in enumerate(out_names[:16])))

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
        draft = dict(args)
        self._pending_finish = draft
        self._finish_drafts.append(draft)
        return (
            "チュートリアル内容を受け付けました（まだ確定していません）。"
            "このあとビューポートの画像が送られるので、意図した見た目になっているか確認し、"
            "問題なければ confirm_tutorial(looks_correct=true) を呼んでください。"
            "問題があれば修正してから、もう一度 finish_tutorial を呼び直してください。"
        )

    def best_unconfirmed_draft(self) -> dict | None:
        """
        confirm_tutorial が一度も呼ばれずに生成が打ち切られた場合のフォールバック用。
        finish_tutorial は複数回呼ばれることがある（見た目の自己確認NGで書き直すケースを
        含む）が、実機で最後の呼び出しだけ title="テスト" のようなプレースホルダー的な
        内容になり、そのままconfirm_tutorialを呼ばずに生成が終わってしまう事例を確認した
        （2026-09-13）。最後の下書きを無条件に採用すると、こういうケースでかえって
        以前のまともな下書きより悪い内容を保存してしまうため、全下書きの中から本文量
        （title+overview+steps+pitfalls+next_stepsの合計文字数）が最大のものを選ぶ。
        どの下書きもプレースホルダー水準（_MIN_DRAFT_CONTENT_CHARS未満）しか無ければ
        Noneを返し、呼び出し元（tutorial_agent.py）は従来通りの汎用フォールバックを使う。
        """
        if not self._finish_drafts:
            return None

        def content_length(draft: dict) -> int:
            fields = ("title", "overview", "steps", "pitfalls", "next_steps")
            return sum(len(str(draft.get(f, ""))) for f in fields)

        # 文字数が同点の場合はインデックスが大きい（＝より新しい）方を優先する。
        # 書き直しは通常、cookエラーの修正など前の下書きの改善であるため。
        best_index, best = max(
            enumerate(self._finish_drafts),
            key=lambda pair: (content_length(pair[1]), pair[0]),
        )
        return best if content_length(best) >= self._MIN_DRAFT_CONTENT_CHARS else None

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
