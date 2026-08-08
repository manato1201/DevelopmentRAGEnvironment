"""
tutorial_agent.py — houdini21 チュートリアル自動生成オーケストレーター

docs/content-generation.md §2 の設計に基づく:
  ① RAG検索: houdini21 namespace のみから取得（license-compliance のホワイト
     リスト方針。他 namespace は参照しない）。取得先は rag_mode で切り替える:
       - "local": ローカルブリッジ /search（rag_local_bridge.py）
       - "cloud": GAS WebApp（gas_cloud_rag.js）を mode:'raw' で呼び、
         最終回答生成をスキップして検索結果のみ取得する
     どちらのモードでも取得後に db フィールドが houdini21 のものだけに
     絞り込む（GAS側は許可namespaceが無いと "all" に自動フォールバックする
     ため、呼び出し側でも二重にホワイトリストを強制する）
  ② エージェントループ: MODEL 定数のClaudeモデル + HOUDINI_TOOLS（最大MAX_ITERATIONS回）
     プロンプトキャッシュ: システムプロンプト・ツール定義・RAGコンテキストを
     cache_control で固定
     Claude API呼び出しは必ず GAS（gas_cloud_rag.js、action:'claude_messages'）
     経由で行う。生のANTHROPIC_API_KEYはクライアントに持たせず、GASが
     APIキーごとのClaude専用トークン予算（claudeCapacity/claudeBalance）を
     サーバー側で強制する。gas_url/gas_api_key（Settingsタブ、rag_mode=local
     でも共通）が未設定だと生成を開始できない（docs/cloud-rag.md §8.14）
  ③ コスト上限: 累積 COST_LIMIT_USD を超えたら自動打ち切り（usage から実測計算。
     ローカル側の推定値であり、実際の課金上限はGAS側のclaudeCapacityが強制する）
  ④ 生成完了後 NodeGraphAsset JSON をエクスポート
  ⑤ Markdown はプレビュー用に返すだけ。保存は UI 側（ユーザー確認後）

Anthropic SDK には依存せず urllib のみで API を呼ぶ
（Houdini 同梱 Python に追加パッケージを要求しないため）。
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from houdini_tools import HOUDINI_TOOLS, HoudiniToolExecutor

# ─── 定数 ────────────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-5"     # 設計判断（§4.1）。変更はコストが変わるため要ユーザー確認
MAX_ITERATIONS = 40           # 反復上限（§2.6）
COST_LIMIT_USD = 5.00         # ローカル側の実測コスト打ち切り上限（§2.7）。実際の利用上限は
                               # GAS側のclaudeCapacity（管理画面で調整）が唯一の正であり、
                               # これはネットワーク断・GAS未応答時などに暴走を防ぐための
                               # クライアント側のフェイルセーフに過ぎない
GRACE_ITERATIONS = 3          # 反復上限までこの回数以内になったら仕上げを促す（§2.6打ち切り改善）
GRACE_COST_FRACTION = 0.85    # 累積コストがCOST_LIMIT_USDのこの割合を超えたら仕上げを促す
MAX_TOKENS_PER_TURN = 4096
RAG_NAMESPACES = ["houdini21"]  # 生成機能が参照してよい namespace のホワイトリスト（§5）
RAG_LIMIT = 6
CLOUD_RAG_DB_KEY = "houdini21"  # Cloud RAG（GAS）に問い合わせる際の dbKey

# MODEL の単価（USD / 1M tokens）。コスト上限判定の実測計算に使う。
# claude-sonnet-5 は標準価格が $3/$15（導入価格 $2/$10 は2026-08-31まで、
# 過大評価になるだけで安全側なのでここでは標準価格を採用）
_PRICE = {
    "input": 3.00,
    "output": 15.00,
    "cache_write": 3.75,
    "cache_read": 0.30,
}

# よく使うSopノードタイプの一覧。list_available_node_types の呼び出しを毎回
# しなくても済むように、頻出タイプ名をシステムプロンプトに直接埋め込んでおく
# （過去の実機検証で、序盤のノードタイプ検索だけで反復予算の3割超を消費した
# ことが分かっているため。ここに無い/不確かなタイプは引き続き
# list_available_node_types で確認すること）。
_COMMON_NODE_TYPES_BLOCK = """- 基本形状: box, sphere, grid, tube, torus
- 変形・ノイズ: mountain::2.0, noise::2.0, attribwrangle, attribrandomize::2.0
- 散布・複製: scatter::2.0, copytopoints::2.0
- 結合・切り出し: merge, blast, boolean::2.0
- 属性操作: attribwrangle, attribcreate::2.0, attribdelete::2.0, attribpromote::2.0
- 曲線: curve::2.0, resample::2.0, sweep::2.0, polyframe::2.0
- ボリューム/VDB: vdbfrompolygons, cloudnoise::2.0, volumetrim, convertvdb
- パーティクル(SOP内 popnet): popnet, popsource, popforce, popdrag, popwrangle, popkill, popcollisiondetect, popadvectbyvolume, popattractforce, popreplicate, popsolver
- シミュレーション(DOP): pyrosolver::2.0, dopnet, sourcevolume::2.0, vellumsolver, rbdpackedobject, staticobject
- スクリプト: pythonscript"""

# ノードタイプ検索(list_available_node_types)が続いた際に一度だけ差し込むテキスト。
# 「よく使うノードタイプ」に無いタイプ名(例: 電子パーティクル等のPOP系)を探し続けて
# 何も作らずに反復を消費してしまう問題（実機で確認済み）への対策。
_SEARCH_LOOP_NUDGE_TEXT = (
    "[システム通知] list_available_node_types の呼び出しが続いています。"
    "これ以上調べずに、今分かっている中で最も可能性が高いタイプ名で create_node を"
    "試してください。タイプ名が間違っていても cook_node のエラーメッセージから"
    "自己修正できます。検索だけで作業を終わらせないでください。"
)
_SEARCH_LOOP_NUDGE_THRESHOLD = 3  # 連続してこの回数以上検索したら促す

# ツールを一度も呼ばずに（＝ノードを1つも作らずに）テキストのみで終了しようとした
# 場合に差し込むテキスト。何も作られていないのに「完了」と誤認されるのを防ぐ。
# 実機検証で、抽象的な題材（例:「電子パーティクル」）だと list_available_node_types
# で該当ノードを探し続けた末に1回の救済（旧: 1回だけ）でも心が折れて再度テキストのみで
# 終了し、そのまま「モデルがツールを呼ばず終了しました」でハード打ち切りになる
# ケースが確認された。これは無限ループやデッドロックではなく、単に諦めるタイミングが
# 早すぎる問題だったため、救済回数を2回に増やし、2回目はより具体的に
# 「代替案（基本形状の組み合わせ）で妥協してでも作れ」と指示する内容に変えた。
_EMPTY_HANDED_NUDGE_TEXT = (
    "[システム通知] まだノードを1つも作成していません。テキストだけで終了せず、"
    "create_node から作業を始めてください。ノードタイプ名が分からない場合は"
    "最も可能性の高い名前で試し、cook_node のエラーを見て修正してください。"
)
_EMPTY_HANDED_NUDGE_TEXT_2 = (
    "[システム通知] 依然としてノードが1つも作成されていません。トピックがHoudiniの"
    "具体的なノードタイプ名と一致しなくても構いません。完璧な再現は諦めて、"
    "sphere/tube/torus 等の基本形状と scatter::2.0 / copytopoints::2.0 / mountain::2.0 "
    "などを組み合わせた「それらしい」見た目で妥協してください。今すぐ create_node を"
    "呼んでください。これ以上ノードタイプを探し続けることは禁止します。"
)
_EMPTY_HANDED_MAX_RESCUES = 2  # この回数までは「まだ何も作られていない」を救済する

# 打ち切り時のグレースフル終了（§2.6）: 反復/コスト上限が近づいた際に一度だけ差し込む
# ユーザー役テキスト。今の状態のまま仕上げるよう促し、未完成のままハード打ち切りになる
# 事態を減らす。
_GRACE_NUDGE_TEXT = (
    "[システム通知] 残りの反復回数またはコスト予算が少なくなっています。"
    "新しい大きな作業は始めず、今組み立て済みのグラフをそのまま仕上げてください。"
    "cook_node でエラーが無いことだけ確認したら、多少シンプルな内容でも構わないので"
    "finish_tutorial を呼んでチュートリアルを完成させてください。"
)

_SYSTEM_PROMPT_TEMPLATE = """あなたは Houdini のエキスパートで、初心者向けチュートリアルを作成するエージェントです。
与えられたツールで Houdini のノードグラフを実際に組み立て、動作確認済みのチュートリアルを作成します。

## 絶対ルール
- ノード操作はサンドボックス `{sandbox_path}` 内でのみ行われます。ノードパスは常にサンドボックス相対（例: `geo1/grid1`）で指定してください。
- 以下の「よく使うノードタイプ」に無いタイプ名が少しでも不確かな場合は、create_node の前に必ず list_available_node_types で正確な名前を確認してください（例: `mountain` ではなく `mountain::2.0`）。既知のタイプ名について毎回確認する必要はありません。
- SOP を作るには、まずサンドボックス直下に Object カテゴリの `geo` ノードを作成し、その中に SOP ノードを作成します。
- グラフを組み終えたら必ず最終ノードを cook_node で評価し、エラーがあれば修正して再 cook してください。エラーが残ったまま finish_tutorial を呼んではいけません。
- 表示させたい最終ノードには set_parameter 等で手を加える必要はありません（ディスプレイフラグは不要）。ただし複数の要素（例: 地形と、その上に散布した岩）を同時に見せたい場合は、Merge ノードで結合してから表示フラグを立ててください（片方しか見えない状態で終わらせないこと）。
- pyro/fire/クロス/パーティクル/流体/剛体等のシミュレーション系ノードを cook_node する際は、システム側が自動的に複数フレーム分evaluateして時間発展する挙動を検証します（1フレームだけでは正しく動くか分からないためです）。
- list_available_node_types で調べ続けるより、最も可能性の高いタイプ名で create_node を試す方が早いことが多いです（間違っていても cook_node のエラーから自己修正できます）。ノードを1つも作らずにテキストだけで応答して終了することは禁止です。必ず何らかのツールを呼んでください。
- トピックが「電子パーティクル」「銀河」のような、Houdiniの具体的なノードタイプ名にそのまま対応しない抽象的・比喩的な題材であっても構いません。その名前のノードタイプを探し続けるのではなく、基本形状（sphere/tube/torus等）・散布や複製（scatter::2.0, copytopoints::2.0）・ノイズや変形（mountain::2.0等）を組み合わせて「それらしい見た目」を表現する方針に切り替えてください。完璧な再現より、まず何かを組み立てて完成させることを優先してください。

## よく使うノードタイプ（このリストにあれば list_available_node_types は不要）
{common_node_types}

## 完了の手順（2段階の自己確認）
1. リクエストと参考ドキュメントからチュートリアルの構成を決める（3〜8ノード程度の到達可能なスコープに収める）
2. ノードを作成・接続・パラメータ設定する
3. cook_node でエラー確認 → 自己修正
4. エラーゼロを確認したら finish_tutorial を呼ぶ。steps には実際に行った操作を初心者が再現できる粒度で書き、pitfalls には生成中に遭遇したエラーと対処を書く。next_steps には「このパラメータを変えたら/このノードを足したら何が変わるか」を具体的に3〜5個挙げ、読んだ人が自分のプロジェクトに応用するための手がかりにする（手順の要約の繰り返しにしないこと）。sources_used には実際に参考にした「参考ドキュメント」の番号（下記の[1][2]...）を記入する（使っていなければ空配列）
5. finish_tutorial の直後に現在のビューポート画像が送られます。**その画像を確認し、意図した見た目になっているか自己検証してから、必ず confirm_tutorial を呼んでください。** 見た目に問題があれば looks_correct=false にして修正し、finish_tutorial からやり直してください

## 参考ドキュメント（houdini21 ナレッジベース。番号は sources_used で引用する際に使う）
{rag_context}"""


# ─── 結果オブジェクト ─────────────────────────────────────────────────────────────

class TutorialResult:
    """generate() の戻り値。UI がプレビュー・保存に使う。"""

    def __init__(self) -> None:
        self.markdown: str = ""
        self.graph: dict = {}
        self.title: str = ""
        self.slug: str = "tutorial"
        self.sandbox_path: str = ""
        # HoudiniToolExecutor.export_step_screenshots() の結果（各ステップ実行
        # 直後に撮ったビューポート/ネットワークエディタのPNGパス一覧）。
        self.step_screenshots: list[dict] = []
        self.cost_usd: float = 0.0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_write_tokens: int = 0
        self.cache_read_tokens: int = 0
        # GASが返す、このAPIキーの「実際の」Claudeトークン残高/上限（サーバー側で強制される値）。
        # None = 未取得（GASが古い/claudeQuotaを返さなかった）または無制限キー。
        self.claude_balance: int | None = None
        self.claude_capacity: int | None = None
        # 自動回復の間隔（時間）と次回回復予定時刻（ISO文字列）。null = 自動回復オフ
        # （無制限キー、または管理者が回復間隔を設定していない=手動チャージのみ）。
        self.claude_reset_interval_hours: int | None = None
        self.claude_reset_at: str | None = None
        # GASがclaudeQuotaを一度でも返したか（無制限キーはbalance/capacityが両方Noneに
        # なるため、それだけでは「未取得」と「無制限」を区別できない。このフラグで判定する）。
        self.claude_quota_known: bool = False
        self.iterations: int = 0
        self.completed: bool = False   # finish_tutorial まで到達したか
        self.abort_reason: str = ""    # 打ち切り理由（上限到達など）
        # sources[i] に "cited": bool が付与される（finish_tutorial の sources_used で
        # 報告された番号と対応）。RAGが実際にどれだけ生成に寄与したかの研究データ。
        self.sources: list[dict] = []
        # finish_tutorial の sources_used（1始まりの引用番号一覧）をそのまま保持する。
        self.rag_sources_cited: list[int] = []
        # 引用率（cited済みsource数 / 全source数）。sourcesが空ならNone。
        self.rag_extraction_rate: float | None = None

    def file_basename(self) -> str:
        date = datetime.datetime.now().strftime("%Y%m%d")
        return f"{self.slug}_{date}"

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens + self.output_tokens
            + self.cache_write_tokens + self.cache_read_tokens
        )


# ─── エージェント本体 ─────────────────────────────────────────────────────────────

class TutorialAgent:
    """
    RAG検索 → エージェントループ → Markdown/JSON 組み立て。

    progress_cb(text) で UI に進行状況を通知する（QThread から Signal 発行される）。
    executor_factory はテスト用フック（省略時は HoudiniToolExecutor を生成）。
    """

    def __init__(
        self,
        bridge_port: int = 8766,
        project_dir: str = "",
        rag_mode: str = "local",
        gas_url: str = "",
        gas_api_key: str = "",
        progress_cb: Callable[[str], None] | None = None,
        executor_factory: Callable[..., HoudiniToolExecutor] | None = None,
    ) -> None:
        self._port = bridge_port
        self._project_dir = project_dir
        self._rag_mode = rag_mode if rag_mode in ("local", "cloud") else "local"
        self._gas_url = gas_url
        self._gas_api_key = gas_api_key
        self._progress = progress_cb or (lambda _: None)
        self._executor_factory = executor_factory or HoudiniToolExecutor
        self.executor: HoudiniToolExecutor | None = None  # 生成後もサンドボックス削除用に保持

    # ── 公開 API ────────────────────────────────────────────────────────────────

    def generate(self, topic: str) -> TutorialResult:
        result = TutorialResult()

        # Claude APIは必ずGAS（gas_cloud_rag.js）経由で呼ぶ。生のANTHROPIC_API_KEYを
        # クライアントに持たせない構成にすることで、APIキーごとのトークン上限を
        # クライアント側から迂回できないようにしている（docs/cloud-rag.md §8.14）。
        if not self._gas_url or not self._gas_api_key:
            raise RuntimeError(
                "GAS WebApp URL / APIキーが未設定です。Settingsタブで設定してください"
                "（houdini21チュートリアル生成はClaude APIをGAS経由で呼ぶため必須です）。"
            )

        # ① RAG検索（houdini21 namespace のみ）
        self._progress(f"RAG検索中（houdini21 ナレッジベース / {self._rag_mode}）...")
        rag_texts, result.sources = self._rag_search(topic)
        if rag_texts:
            self._progress(f"参考ドキュメント {len(result.sources)} 件を取得しました")
        else:
            self._progress("参考ドキュメントが取得できませんでした（コンテキストなしで続行）")

        # ② サンドボックス作成
        log_dir = Path(self._project_dir) / "logs" / "tutorial_agent" if self._project_dir else None
        screenshot_dir = (
            Path(self._project_dir) / "logs" / "tutorial_agent" / "screenshots"
            if self._project_dir else None
        )
        self.executor = self._executor_factory(log_dir=log_dir, screenshot_dir=screenshot_dir)
        result.sandbox_path = self.executor.sandbox_path
        self._progress(f"サンドボックス作成: {result.sandbox_path}")

        # ③ エージェントループ
        system_blocks, tools, messages = self._build_initial_prompt(topic, rag_texts)
        try:
            self._run_loop(system_blocks, tools, messages, result)
        finally:
            result.iterations = self._count_iterations()

        # ④ 成果物組み立て（打ち切りでも途中経過を提示する）
        result.graph = self.executor.export_node_graph()
        result.step_screenshots = self.executor.export_step_screenshots()
        finish = self.executor.finish_data or {}
        result.completed = self.executor.finish_data is not None
        result.title = finish.get("title") or f"Houdiniチュートリアル: {topic}"
        result.slug = self._sanitize_slug(finish.get("slug", ""), topic)
        self._apply_rag_attribution(finish, result, result.completed)
        result.markdown = self._assemble_markdown(topic, finish, result)

        status = "完了" if result.completed else f"打ち切り（{result.abort_reason}）"
        self._progress(
            f"生成{status}: {result.iterations} イテレーション / ${result.cost_usd:.3f}"
        )
        return result

    def destroy_sandbox(self) -> None:
        if self.executor is not None:
            self.executor.destroy_sandbox()

    @staticmethod
    def _apply_rag_attribution(finish: dict, result: "TutorialResult", completed: bool) -> None:
        """
        finish_tutorial の sources_used（Claudeが実際に参考にしたと報告した番号一覧）を
        result.sources に反映する。RAGがチュートリアル生成にどれだけ実際に寄与したかを
        示す研究データとして使う（Cloud RAGチャットのparseExtractionRate_と同じ考え方の
        Houdini生成版）。

        completed=False（finish_tutorialに到達せず打ち切られた）の場合は、
        sources_used はそもそもモデルに一度も尋ねられていない。この場合まで
        cited_numbers=[] → 抽出率0%として表示すると、「モデルが参考ドキュメントを
        検討した上で1件も使わなかった」ように見えてしまい誤解を招く（実機で
        「引用0とは何か」という混乱として報告された）。打ち切り時は計測不能
        として rag_extraction_rate を None のままにし、_assemble_markdown 側で
        「未計測」であることを明示する。
        """
        if not completed:
            result.rag_sources_cited = []
            result.rag_extraction_rate = None
            return
        cited_raw = finish.get("sources_used")
        cited_numbers = sorted({int(n) for n in cited_raw if isinstance(n, (int, float))}) if isinstance(cited_raw, list) else []
        result.rag_sources_cited = cited_numbers
        cited_set = set(cited_numbers)
        for i, source in enumerate(result.sources, start=1):
            source["cited"] = i in cited_set
        if result.sources:
            result.rag_extraction_rate = sum(1 for s in result.sources if s.get("cited")) / len(result.sources)
        else:
            result.rag_extraction_rate = None

    # ── RAG検索 ─────────────────────────────────────────────────────────────────

    def _rag_search(self, topic: str) -> tuple[list[str], list[dict]]:
        """rag_mode に応じてローカルブリッジ or GAS（Cloud RAG）から houdini21 namespace の生チャンクを取得する。"""
        if self._rag_mode == "cloud":
            return self._rag_search_cloud(topic)
        return self._rag_search_local(topic)

    def _rag_search_local(self, topic: str) -> tuple[list[str], list[dict]]:
        """ローカルブリッジの /search から houdini21 namespace の生チャンクを取得する。"""
        try:
            body = json.dumps({
                "query": topic,
                "limit": RAG_LIMIT,
                "namespaces": RAG_NAMESPACES,
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"http://localhost:{self._port}/search",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            return data.get("texts", []), data.get("sources", [])
        except Exception as exc:
            self._progress(f"RAG検索エラー（続行します）: {exc}")
            return [], []

    def _rag_search_cloud(self, topic: str) -> tuple[list[str], list[dict]]:
        """
        GAS WebApp を mode:'raw' で呼び、最終回答生成（Gemini呼び出し）をスキップして
        houdini21 namespace の検索結果だけを取得する。

        GAS 側は APIキーに houdini21 の権限がないと dbKey を "all" にフォールバック
        してしまうため、応答の sources を db=="houdini21" のものだけに絞り込むことで
        ホワイトリスト方針（他 namespace は参照しない）をクライアント側でも強制する。
        """
        if not self._gas_url:
            self._progress("Cloud RAG検索エラー: GAS WebApp URLが未設定です（続行します）")
            return [], []
        try:
            body = json.dumps({
                "query": topic,
                "dbKey": CLOUD_RAG_DB_KEY,
                "history": [],
                "apiKey": self._gas_api_key,
                "mode": "raw",
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self._gas_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())

            status = data.get("status", "error")
            if status not in ("ok",):
                self._progress(f"Cloud RAG検索エラー（{status}）。続行します: {data.get('answer', '')}")
                return [], []

            raw_sources = [
                s for s in data.get("sources", [])
                if s.get("db") == CLOUD_RAG_DB_KEY
            ]
            if not raw_sources:
                self._progress(
                    "Cloud RAGにhoudini21のドキュメントが見つかりませんでした"
                    "（APIキーにhoudini21の権限があるか確認してください）"
                )
                return [], []

            texts = [f"検索結果（{len(raw_sources)} 件）:"]
            sources = []
            for i, s in enumerate(raw_sources[:RAG_LIMIT]):
                texts.append(f"\n[{i + 1}] ファイル: {s.get('title', '')}\n{s.get('text', '')}")
                sources.append({"title": s.get("title", ""), "db": s.get("db", ""), "score": s.get("score", 0)})
            return texts, sources
        except Exception as exc:
            self._progress(f"Cloud RAG検索エラー（続行します）: {exc}")
            return [], []

    # ── プロンプト構築 ──────────────────────────────────────────────────────────

    def _build_initial_prompt(
        self, topic: str, rag_texts: list[str]
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """
        システム・ツール・初期メッセージを構築する。
        固定部分（システムプロンプト＝RAGコンテキスト込み・ツール定義）に
        cache_control を付け、2回目以降のターンのコストを抑える（§4.2）。
        """
        rag_context = "\n\n".join(rag_texts) if rag_texts else "（参考ドキュメントなし）"
        system_text = _SYSTEM_PROMPT_TEMPLATE.format(
            sandbox_path=self.executor.sandbox_path,
            rag_context=rag_context,
            common_node_types=_COMMON_NODE_TYPES_BLOCK,
        )
        system_blocks = [{
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }]

        tools = [dict(t) for t in HOUDINI_TOOLS]
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}

        messages = [{
            "role": "user",
            "content": f"次のトピックのHoudiniチュートリアルを作成してください: {topic}",
        }]
        return system_blocks, tools, messages

    # ── ループ ──────────────────────────────────────────────────────────────────

    def _run_loop(
        self,
        system_blocks: list[dict],
        tools: list[dict],
        messages: list[dict],
        result: TutorialResult,
    ) -> None:
        grace_warned = False        # GRACE_NUDGE_TEXTは1生成につき1回だけ出す
        search_nudge_active = False  # 現在の検索連打ストリークで既に促したか（create_nodeで解除）
        empty_handed_rescues = 0    # 何も作らずテキストのみで終了しようとした際の救済回数
        cache_marked_content: list | None = None  # ローリングキャッシュ用（下記コメント参照）
        for iteration in range(1, MAX_ITERATIONS + 1):
            # ローリングプロンプトキャッシュ: messages は反復のたびに増え続けるが、
            # cache_control は system_blocks / tools（固定部分）にしか付けていなかった
            # ため、会話履歴そのもの（tool_result・アシスタント応答の蓄積）は毎ターン
            # 通常入力価格（$3/M）で再送信・再課金されていた。反復が進むほど履歴が
            # 線形に伸びるため、生成1回あたりのコストは反復回数のほぼ2乗で増える
            # ことになり、これが実機で「1生成$3超え」の主因と判明した。
            # ここでは「直前のターンまでの会話」の末尾に cache_control を付け直す
            # ことで、その部分をキャッシュ読み込み価格（$0.30/M、通常の1/10）で
            # 再利用できるようにする。付け直す際は古い位置のマーカーを外す
            # （Anthropic APIは cache_control breakpoint を最大4つまでしか許可せず、
            # system+toolsで既に2つ使っているため、会話側は1つだけを使い回す）。
            if messages:
                last_content = messages[-1].get("content")
                if isinstance(last_content, list) and last_content:
                    last_content[-1] = {**last_content[-1], "cache_control": {"type": "ephemeral"}}
                    if cache_marked_content is not None and cache_marked_content is not last_content:
                        cache_marked_content[-1] = {
                            k: v for k, v in cache_marked_content[-1].items() if k != "cache_control"
                        }
                    cache_marked_content = last_content

            response = self._call_api(system_blocks, tools, messages)
            quota = response.get("claudeQuota")
            if quota is not None:
                result.claude_quota_known = True
                result.claude_balance = quota.get("balance")
                result.claude_capacity = quota.get("capacity")
                result.claude_reset_interval_hours = quota.get("resetIntervalHours")
                result.claude_reset_at = quota.get("resetAt")
            usage = response.get("usage", {})
            result.cost_usd += self._usage_cost(usage)
            result.input_tokens += usage.get("input_tokens", 0)
            result.output_tokens += usage.get("output_tokens", 0)
            result.cache_write_tokens += usage.get("cache_creation_input_tokens", 0)
            result.cache_read_tokens += usage.get("cache_read_input_tokens", 0)

            content = response.get("content", [])
            messages.append({"role": "assistant", "content": content})

            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if not tool_uses:
                # テキストのみの応答 = モデルが作業を終えたと判断。ただし1つも
                # ノードを作らずに終えようとした場合は、誤って「完了」扱いする前に
                # 一度だけ再開を促す（実機で「検索だけして何も作らず終了」する
                # ケースが確認されたための救済措置）。executorが無い場合（テスト等で
                # _run_loopのみを直接動かすケース）は進捗を判定できないため対象外とする。
                if self.executor is not None:
                    has_created_any_node = any(
                        e["tool"] == "create_node" and not e["is_error"]
                        for e in self.executor.step_log
                    )
                    if not has_created_any_node and empty_handed_rescues < _EMPTY_HANDED_MAX_RESCUES:
                        empty_handed_rescues += 1
                        nudge_text = (
                            _EMPTY_HANDED_NUDGE_TEXT if empty_handed_rescues == 1
                            else _EMPTY_HANDED_NUDGE_TEXT_2
                        )
                        messages.append({
                            "role": "user",
                            "content": [{"type": "text", "text": nudge_text}],
                        })
                        self._progress(
                            f"何も作成せず終了しようとしたため、作業開始を促しました"
                            f"（{empty_handed_rescues}/{_EMPTY_HANDED_MAX_RESCUES}）"
                        )
                        continue
                result.abort_reason = "モデルがツールを呼ばず終了しました"
                return

            tool_results = []
            for block in tool_uses:
                name, args = block["name"], block.get("input", {})
                self._progress(f"[{iteration}/{MAX_ITERATIONS}] {name}({self._short(args)})")
                output, is_error = self.executor.execute(name, args)
                # 視覚的自己検証ステップ: finish_tutorial実行直後に撮られたビューポート画像が
                # あれば、その回のtool_resultにテキストと一緒に画像として添付する。Claude自身が
                # 画像を見て見た目を確認したうえでconfirm_tutorialを呼ぶ（houdini_tools.py参照）。
                screenshot_b64 = getattr(self.executor, "last_screenshot_b64", None)
                if name == "finish_tutorial" and screenshot_b64:
                    tool_content: object = [
                        {"type": "text", "text": output},
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/png", "data": screenshot_b64,
                        }},
                    ]
                    self.executor.last_screenshot_b64 = None  # 使い終わったので消費する
                else:
                    tool_content = output
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": tool_content,
                    "is_error": is_error,
                })

            # list_available_node_types 連打対策: 直近の呼び出しがこのツールだけで
            # _SEARCH_LOOP_NUDGE_THRESHOLD 回以上続いたら、検索を止めて作成を試すよう
            # 一度だけ促す。create_node が呼ばれたらストリークは解除され、次に別の
            # 検索連打が起きたら再度促せるようにする。
            content_blocks = list(tool_results)
            consecutive_lookups = 0
            for entry in reversed(self.executor.step_log):
                if entry["tool"] == "list_available_node_types":
                    consecutive_lookups += 1
                else:
                    break
            if consecutive_lookups == 0:
                search_nudge_active = False
            elif not search_nudge_active and consecutive_lookups >= _SEARCH_LOOP_NUDGE_THRESHOLD:
                content_blocks.append({"type": "text", "text": _SEARCH_LOOP_NUDGE_TEXT})
                search_nudge_active = True
                self._progress("ノードタイプ検索が続いているため、作成を促しました")

            # 打ち切り時のグレースフル終了: 残り反復数またはコストが少なくなった時点で、
            # まだ確定していなければ「今の状態で仕上げてください」と一度だけ促す。
            # これにより、ハード打ち切りで未完成のまま終わる代わりに、多少粗くても
            # 完結したチュートリアルになる可能性を上げる。
            remaining_iterations = MAX_ITERATIONS - iteration
            near_iteration_limit = remaining_iterations <= GRACE_ITERATIONS
            near_cost_limit = result.cost_usd >= COST_LIMIT_USD * GRACE_COST_FRACTION
            still_in_progress = self.executor.finish_data is None and self.executor.pending_finish is None
            if not grace_warned and still_in_progress and (near_iteration_limit or near_cost_limit):
                content_blocks.append({"type": "text", "text": _GRACE_NUDGE_TEXT})
                grace_warned = True
                self._progress("残り予算が少ないため、仕上げを促しました")
            messages.append({"role": "user", "content": content_blocks})

            if self.executor.finish_data is not None:
                return  # confirm_tutorial(looks_correct=true) で確定済み

            if result.cost_usd > COST_LIMIT_USD:
                result.abort_reason = f"コスト上限 ${COST_LIMIT_USD:.2f} 超過"
                self._progress(f"コスト上限に達したため打ち切ります（${result.cost_usd:.3f}）")
                return

        result.abort_reason = f"反復上限 {MAX_ITERATIONS} 回到達"
        self._progress("反復上限に達したため打ち切ります")

    def _call_api(
        self, system_blocks: list[dict],
        tools: list[dict], messages: list[dict],
    ) -> dict:
        """
        Claude Messages API を、GAS WebApp（gas_cloud_rag.js）経由で呼ぶ。

        このHoudiniクライアントは生のANTHROPIC_API_KEYを一切保持しない。実キーは
        GASのスクリプトプロパティにのみ保存され、GAS側がAPIキーごとのClaude専用
        トークン予算（claudeCapacity/claudeBalance）を強制する。クライアント側の
        Settings設定を書き換えても上限を迂回できないようにするための構成
        （docs/cloud-rag.md §8.14参照）。過負荷系リトライはGAS側で行うため、
        ここでは単純に1回呼ぶだけでよい。
        """
        payload = json.dumps({
            "action": "claude_messages",
            "apiKey": self._gas_api_key,
            "model": MODEL,
            "max_tokens": MAX_TOKENS_PER_TURN,
            "system": system_blocks,
            "tools": tools,
            "messages": messages,
            "purpose": "houdini21_tutorial_agent",
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            self._gas_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GAS呼び出しエラー {exc.code}: {detail}") from exc

        status = data.get("status", "error")
        if status == "quota_exceeded":
            raise RuntimeError(
                data.get("error", {}).get("message")
                or "Claudeトークンの利用上限に達しています。管理者にチャージを依頼してください。"
            )
        if status == "rate_limited":
            raise RuntimeError(
                data.get("error", {}).get("message") or "リクエストが多すぎます。しばらく待ってから再試行してください。"
            )
        if status == "auth_error":
            raise RuntimeError(
                data.get("error", {}).get("message") or "認証エラー: GAS APIキーが無効です。Settingsタブを確認してください。"
            )
        if status != "ok":
            raise RuntimeError(data.get("error", {}).get("message") or f"GAS Claudeプロキシエラー: {data}")
        return data

    @staticmethod
    def _usage_cost(usage: dict) -> float:
        return (
            usage.get("input_tokens", 0) * _PRICE["input"]
            + usage.get("output_tokens", 0) * _PRICE["output"]
            + usage.get("cache_creation_input_tokens", 0) * _PRICE["cache_write"]
            + usage.get("cache_read_input_tokens", 0) * _PRICE["cache_read"]
        ) / 1_000_000

    def _count_iterations(self) -> int:
        return len(self.executor.step_log) if self.executor else 0

    @staticmethod
    def _short(args: dict, limit: int = 80) -> str:
        text = json.dumps(args, ensure_ascii=False)
        return text if len(text) <= limit else text[:limit] + "…"

    # ── Markdown 組み立て ───────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_slug(slug: str, topic: str) -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
        if slug:
            return slug[:60]
        # モデルが slug を返さなかった場合はトピックの ASCII 化を試みる
        ascii_topic = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9-]", "-", ascii_topic.lower()).strip("-")
        return slug[:60] or "tutorial"

    def _assemble_markdown(self, topic: str, finish: dict, result: TutorialResult) -> str:
        """
        localRAG/_templates/tutorial.md のフロントマター形式に合わせて組み立てる。
        watchdog（auto_index.py）がそのままインデックス化できる形式。
        """
        today = datetime.date.today()
        expires = today + datetime.timedelta(days=180)

        node_lines = []
        for node in result.graph.get("nodes", []):
            params = ", ".join(f"{k}={v}" for k, v in node.get("params", {}).items())
            suffix = f"  （{params}）" if params else ""
            node_lines.append(f"- `{node['id']}` : {node['kind']}{suffix}")
        edge_lines = [
            f"- `{e['source']}` → `{e['target']}` (in:{e['targetInput']})"
            for e in result.graph.get("edges", [])
        ]

        # "[エラー] " は cook_node の失敗行にのみ付与される接頭辞。cook成功メッセージ
        # 「cook 成功: ...（エラー・警告なし）」にも "エラー" という部分文字列が
        # 含まれるため、これと区別するには "[エラー]" まで含めて判定する必要がある。
        cook_errors = [
            entry for entry in (self.executor.step_log if self.executor else [])
            if entry["tool"] == "cook_node" and "[エラー]" in str(entry["result"])
        ]

        pitfalls = finish.get("pitfalls", "")
        if not pitfalls and cook_errors:
            pitfalls = "\n".join(
                f"- {e['result'].splitlines()[1].strip() if len(e['result'].splitlines()) > 1 else e['result']}"
                for e in cook_errors[:5]
            )

        # completed=False（打ち切り）の場合は sources_used が一度もモデルに尋ねられて
        # いないため、「✅引用済み/⬜未引用」のバッジを付けると実際には評価していない
        # のに評価済みのように見えて誤解を招く。バッジ無しでタイトルだけ列挙する。
        if result.completed:
            source_lines = [
                f"- [{i}] {'✅ 引用済み' if s.get('cited') else '⬜ 未引用'} "
                f"{s.get('title', '')}（{s.get('db', '')}）"
                for i, s in enumerate(result.sources, start=1)
            ] or ["- （参考ドキュメントなし）"]
        else:
            source_lines = [
                f"- [{i}] {s.get('title', '')}（{s.get('db', '')}）"
                for i, s in enumerate(result.sources, start=1)
            ] or ["- （参考ドキュメントなし）"]

        if not result.completed:
            extraction_note = (
                "\n利用率: 未計測（打ち切りのため finish_tutorial の sources_used が"
                "報告されませんでした。「引用0件」ではなく「未評価」です）"
                if result.sources else ""
            )
        elif result.rag_extraction_rate is not None:
            extraction_note = (
                f"\n利用率: {result.rag_extraction_rate:.0%}"
                f"（引用 {len(result.rag_sources_cited)}/{len(result.sources)} 件）"
            )
        else:
            extraction_note = ""

        status_note = ""
        if not result.completed:
            status_note = (
                f"\n> **注意:** この生成は途中で打ち切られました（{result.abort_reason}）。"
                "ノード構成は未完成の可能性があります。\n"
            )

        return f"""---
title: {result.title}
namespace: tutorials
status: active
created: {today.isoformat()}
updated: {today.isoformat()}
expires: {expires.isoformat()}
tags: [houdini, ai-generated, houdini21]
rag_indexed: false
---
{status_note}
## 概要

{finish.get("overview", f"リクエスト「{topic}」から自動生成されたチュートリアルです。")}

## 手順

{finish.get("steps", "（打ち切りのため手順は未完成です。下記のノード構成を参照してください）")}

## コード・ノード構成

サンドボックス: `{result.sandbox_path}`

### ノード
{chr(10).join(node_lines) or "- （ノードなし）"}

### 接続
{chr(10).join(edge_lines) or "- （接続なし）"}

ノードグラフ JSON: `{result.file_basename()}.json`（NodeGraphAsset 形式）

## ハマりポイント

{pitfalls or "特になし"}

## 応用・発展のヒント

{finish.get("next_steps") or (
    "（打ち切りのため未生成です）" if not result.completed
    else "特になし（パラメータを変えて色々試してみましょう）"
)}

## 参考
{extraction_note}
{chr(10).join(source_lines)}

---
*自動生成: model={MODEL} / iterations={result.iterations} / cost=${result.cost_usd:.3f} / sandbox={result.sandbox_path}*
"""
