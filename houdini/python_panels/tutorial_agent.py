"""
tutorial_agent.py — Houdini チュートリアル自動生成オーケストレーター（検索対象はHoudiniのバージョン別namespace）

docs/content-generation.md §2 の設計に基づく:
  ① RAG検索: houdini21 namespace のみから取得（license-compliance のホワイト
     リスト方針。他 namespace は参照しない）。取得先は rag_mode で切り替える:
       - "local": ローカルブリッジ /search（rag_local_bridge.py）
       - "cloud": GAS WebApp（gas_cloud_rag.js）を mode:'raw' で呼び、
         最終回答生成をスキップして検索結果のみ取得する
       - "cloudflare": Cloudflare Workers（cloudflare-rag-poc、/search）を呼ぶ
         （2026-08-26追加。GAS Cloud RAGの後継）
     "cloud"モードは取得後に db フィールドが houdini21 のものだけに絞り込む
     （GAS側は許可namespaceが無いと "all" に自動フォールバックするため、呼び出し
     側でも二重にホワイトリストを強制する）。"cloudflare"モードはサーバー側の
     namespace許可制御がGASのような抜け道を持たないため二重フィルタ不要
  ② エージェントループ: DEFAULT_MODEL（既定claude-sonnet-5、TutorialAgent(model=...)で
     claude-sonnet-5-5 / claude-opus-5-5 / claude-haiku-4-5に変更可）+ HOUDINI_TOOLS（最大MAX_ITERATIONS回）
     プロンプトキャッシュ: システムプロンプト・ツール定義・RAGコンテキストを
     cache_control で固定
     Claude API呼び出しは claude_backend で切り替える（既定"gas"、後方互換）:
       - "gas": GAS（gas_cloud_rag.js、action:'claude_messages'）経由
       - "cloudflare": Cloudflare Workers（cloudflare-rag-poc、/claude/messages）
         経由（2026-08-26追加。GAS Claudeプロキシの後継）
     どちらの場合も生のANTHROPIC_API_KEYはクライアントに持たせず、サーバー側が
     APIキーごとのClaude専用トークン予算を強制する（GAS: claudeCapacity/claudeBalance、
     Cloudflare: token_budgets/budget_type='claude'）。対応する gas_url/gas_api_key
     または cf_url/cf_api_key（Settingsタブ）が未設定だと生成を開始できない
     （docs/cloud-rag.md §8.14）
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
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from houdini_tools import HOUDINI_TOOLS, HoudiniToolExecutor

# ─── 定数 ────────────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "claude-sonnet-5"  # 設計判断（§4.1）。既定値。generate()単価/品質に影響するため
                                    # 変更時はTutorialAgent(model=...)で明示的に指定する
# 反復上限（§2.6）。初期値25 → 40 → 80（2026-10-05）。パーティクル・シミュレーション系は、
# dopnetの中のノードが多く、cookのたびに複数フレームを評価して直す往復が増えるため、40回では
# 仕上げの前に打ち切られやすかった。上限を上げても、finish_tutorial / confirm_tutorial に
# 到達すればそこで終わるので、簡単な題材のコストは増えない。コスト上限（下のCOST_LIMIT_USD）は
# 据え置き。反復が増えても、キャッシュ読み取りが主体なので1回あたりは安い
# （Sonnet 5.5で80回のループが概ね$2前後）。
MAX_ITERATIONS = 80
COST_LIMIT_USD = 5.00         # ローカル側の実測コスト打ち切り上限（§2.7）。実際の利用上限は
                               # GAS側のclaudeCapacity（管理画面で調整）が唯一の正であり、
                               # これはネットワーク断・GAS未応答時などに暴走を防ぐための
                               # クライアント側のフェイルセーフに過ぎない
GRACE_ITERATIONS = 5          # 反復上限までこの回数以内になったら仕上げを促す（§2.6打ち切り改善。3→5: 上限を上げたので余裕を持たせる）
GRACE_COST_FRACTION = 0.85    # 累積コストがCOST_LIMIT_USDのこの割合を超えたら仕上げを促す
# 1ターンの出力上限。Sonnet 5.5 / Opus 5.5 はthinking（思考）も max_tokens に数えられ、常に有効なため、
# 以前の4096だと思考だけで使い切って、ツール呼び出し（VEXコード等を含む入力）が途中で切れる恐れがある
# （2026-10-05に16000へ。非ストリーミングで使える現実的な上限）。
MAX_TOKENS_PER_TURN = 16000
RAG_NAMESPACES = ["houdini21"]  # 生成機能が参照してよい namespace のホワイトリスト（§5）
RAG_LIMIT = 6
CLOUD_RAG_DB_KEY = "houdini21"  # Cloud RAG（GAS）に問い合わせる際の dbKey
CLOUDFLARE_RAG_NAMESPACES = ["shared:houdini21"]  # Cloudflare RAG（cloudflare-rag-poc）側のnamespace名
                                    # （2026-08-26追加。GASのCloud RAGの後継として、GAS/Cloudflare
                                    # どちらも選べるようにした。RAG_NAMESPACESとは別名になっている点に注意）

# 2026-10-04追加: 検索対象のナレッジ（Houdiniのバージョン別namespace）を決める。
# 以前は上の定数（houdini21固定）を使っており、設定画面の「DB」欄（gas_db_key＝チャット用）を
# houdini22にしても、チュートリアル生成は常にhoudini21を検索していた（Cloudflareには
# shared:houdini22が8,700チャンク以上あるのに、houdini21は144チャンクだけだった）。
# 設定値 tutorial_rag_namespace が空なら、起動中のHoudiniのメジャーバージョンに合わせる。
# ライセンス方針（生成機能が参照してよいのはHoudini公式ドキュメント系のnamespaceのみ）を
# 保つため、houdini<数字> 以外の値は受け付けず自動判定に戻す。
_RAG_NAME_RE = re.compile(r"^(?:shared:)?(houdini\d+)$")


def detect_houdini_rag_name() -> str:
    """起動中のHoudiniのバージョンから houdini<メジャー> を返す（hou が無ければ houdini21）。"""
    try:
        import hou

        return f"houdini{int(hou.applicationVersion()[0])}"
    except Exception:  # noqa: BLE001 -- hou無し（テスト等）は従来の既定値
        return "houdini21"


def resolve_rag_name(setting: str = "") -> str:
    """設定値（"houdini22" / "shared:houdini22" / 空=自動）を houdini<数字> の形に正規化する。"""
    match = _RAG_NAME_RE.match((setting or "").strip().lower())
    return match.group(1) if match else detect_houdini_rag_name()

# 2026-09-13追加: /claude/messages呼び出しでWorkerに一度も届かないままCloudflare
# エッジ（workers.dev共有ドメインのBot Fight Mode等）に弾かれる事象を実機で確認した
# （Workers Observabilityのイベントログに一切記録が残らないことから、Worker到達前の
# ブロックだと確定）。urllib標準のUser-Agent（"Python-urllib/3.x"）が弾かれやすい
# 一因と考えられるため、一般的なHTTPクライアントらしいUser-Agentを付与し、かつ
# このブロック特有のパターン（401/403だがWorker自身のJSON応答ではない）を検知した
# 場合に限り、短い間隔で自動リトライする（Workerに届いていないためトークン予算の
# 二重消費にはならない）。
_HTTP_USER_AGENT = "HoudiniTutorialAgent/1.0 (+cloudflare-rag-poc)"
_CF_EDGE_BLOCK_RETRIES = 2
_CF_EDGE_BLOCK_BACKOFF_SEC = (2.0, 5.0)

# モデル別単価（USD / 1M tokens）。コスト上限判定の実測計算と、UIに出す生成コストに使う。
# 公式の料金ページ（platform.claude.com/docs/en/about-claude/pricing）で2026-10-05に確認した値。
# dictのkey順がそのままUI（Settingsタブ）の表示順。cache_writeは5分キャッシュの書き込み単価
# （入力の1.25倍）、cache_readはキャッシュ読み取り（通常は入力の0.1倍。Opus 5.5だけ0.05倍）。
# - claude-sonnet-5: $2/$10。発売時は2026-08-31までの導入価格とされ、以前ここでは「9/1から$3/$15に
#   上がる」前提で$3/$15を使っていたが、公式に「$2/$10が標準価格になり値上げは行わない」と改められた。
#   旧値のまま計算するとコスト表示が実際より約1.5倍高く出ていた（2026-10-05修正）。
# - claude-sonnet-5-5: Sonnet 5の後継。単価は同じ$2/$10。
# - claude-opus-5-5: $4/$20（Opus 5の$5/$25より安い）。キャッシュ読み取りが$0.20と安く、本ツールの
#   ようにキャッシュ読み取りが入力の大半を占める用途では差がさらに縮む。
# - claude-haiku-4-5: $1/$5。
_MODEL_PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {
        "input": 2.00,
        "output": 10.00,
        "cache_write": 2.50,
        "cache_read": 0.20,
    },
    "claude-sonnet-5-5": {
        "input": 2.00,
        "output": 10.00,
        "cache_write": 2.50,
        "cache_read": 0.20,
    },
    "claude-opus-5-5": {
        "input": 4.00,
        "output": 20.00,
        "cache_write": 5.00,
        "cache_read": 0.20,
    },
    "claude-haiku-4-5": {
        "input": 1.00,
        "output": 5.00,
        "cache_write": 1.25,
        "cache_read": 0.10,
    },
}
# モデル別のeffort（思考の深さ）。2026-10-05追加。Sonnet 5.5の既定は"high"だが、公式は多段の
# ツール利用タスク（本ツールのエージェントループ）の出発点として"medium"を勧めている
# （Anthropicの検証では、エージェント系のコーディングで medium が Sonnet 5 の high を上回り、
# コストは5分の1未満）。Opus 5.5は既定が"medium"だが、既定の変更に左右されないよう明示する。
# effortを受け付けないモデル（Haiku 4.5）や、未検証のSonnet 5には送らない（空=モデルの既定）。
# 値を変えて試すときはここだけ直す。Cloudflare Worker（/claude/messages）が中継する。
_MODEL_EFFORT: dict[str, str] = {
    "claude-sonnet-5-5": "medium",
    "claude-opus-5-5": "medium",
}
# UI（Settingsタブ）のモデル選択プルダウンに出す順序・選択肢
AVAILABLE_MODELS: tuple[str, ...] = tuple(_MODEL_PRICES.keys())

# よく使うSopノードタイプの一覧（2026-09-26: Houdini 21.0.700/22.0.429の実機（hython）で全て存在を確認済み。
# 以前は noise::2.0/attribrandomize::2.0/volumetrim/popnet/pythonscript など、どちらの版にも
# 存在しない名前が混ざっており、モデルが存在しないタイプを探し続ける一因になっていた）。
# list_available_node_types の呼び出しを毎回
# しなくても済むように、頻出タイプ名をシステムプロンプトに直接埋め込んでおく
# （過去の実機検証で、序盤のノードタイプ検索だけで反復予算の3割超を消費した
# ことが分かっているため。ここに無い/不確かなタイプは引き続き
# list_available_node_types で確認すること）。
_COMMON_NODE_TYPES_BLOCK = """- 基本形状: box, sphere, grid, tube, torus
- 変形・ノイズ: mountain::2.0, attribnoise::2.0, attribwrangle, attribrandomize
- 散布・複製: scatter::2.0, copytopoints::2.0
- 結合・切り出し: merge, blast, boolean::2.0
- 属性操作: attribwrangle, attribcreate::2.0, attribdelete, attribpromote
- 曲線: curve::2.0, resample, sweep::2.0, polyframe
- ボリューム/VDB: vdbfrompolygons, cloudnoise, volumewrangle, volumevop, convertvdb
- パーティクル: POP系はDOPノードなので SOP 直下には作れない。geo の中に dopnet を作り、その中に popobject, popsolver::2.0, popsource::2.0, popforce, popdrag, popwrangle, popkill, popcollisiondetect, popadvectbyvolumes, popattract, popreplicate を作る（簡易に見せるだけなら scatter::2.0 + copytopoints::2.0 の方が確実）
- シミュレーション(DOP): pyrosolver::2.0, dopnet, vellumsolver, rbdpackedobject, staticobject
- スクリプト: python（Python SOP）
- UV: uvunwrap, uvlayout（実体は uvlayout::3.0）, uvproject（H22以降は uvrelax, labs::autouv::1.0 も）
- マテリアル: サンドボックス直下に matnet を作り、中に principledshader::2.0（基本色 basecolor、粗さ rough 等）を作る。SOP の material ノードの shop_materialpath1 にパス（例 `../../matnet1/principledshader1`）を設定して割り当てる
- Copernicus（画像処理）: サンドボックス直下に copnet を作り、中に Cop カテゴリのノードを作る（list_available_node_types は category=Cop）。例: cellularnoise, fractalnoise, worleynoise, blur, colorcorrect, ramp, checkerboard, constant, null。`noise` という名前は Copernicus には存在しない
- Solaris(LOP): サンドボックス直下に lopnet を作り、中に sphere, plane, materiallibrary, assignmaterial など。マテリアルは materiallibrary の中に subnet を作り、その中に principledshader::2.0 や mtlx* を作る（`mtlxbuilder` というタイプは無い）
- TOP: topnet の中に wedge, pythonscript, waitforall。cook_node は作業項目の生成までで、実行はされない
- CHOP: chopnet の中に wave, math, null
- VOP: SOP の attribvop の中（geometryvopglobal1 / geometryvopoutput1 が最初からある）に turbnoise, add など。connect_nodes は input_name / output_name で指定する"""

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

# 2026-09-13追加: finish_tutorialは呼んだがconfirm_tutorialを呼ばないままテキストのみで
# 終了しようとするケースを実機で確認した（ノードは正しく作成・cookできているのに、
# 視覚的自己検証の最後の一歩だけ忘れる）。ノードが1つも無い場合の救済
# （_EMPTY_HANDED_NUDGE_TEXT）とは別枠で、下書きが残っているのに終了しようとした場合に
# 一度だけ再開を促す。
_UNCONFIRMED_FINISH_NUDGE_TEXT = (
    "[システム通知] finish_tutorial は呼びましたが、まだ confirm_tutorial を呼んでいません。"
    "直前に見せられたビューポート画像を確認し、意図した見た目になっていれば"
    "confirm_tutorial(looks_correct=true) を呼んでください。問題があれば修正してから"
    "finish_tutorial を呼び直し、その後 confirm_tutorial を呼んでください。"
    "confirm_tutorial を呼ぶまで生成は完了しません。"
)
# 2026-09-26: 1→2回に増やし、2回目は「もう修正は不要、今すぐconfirmだけ呼ぶ」と明示する。
# 実機ログで、1回目の救済の後にモデルが修正を再開してfinish_tutorialを呼び直し（下書きが
# 未確定に戻る）、再びテキストのみで終えて救済回数切れ→打ち切り、という流れを確認した。
_UNCONFIRMED_FINISH_NUDGE_TEXT_2 = (
    "[システム通知] confirm_tutorial がまだ呼ばれていません。これ以上のノード修正や"
    "finish_tutorial の呼び直しは不要です。画像が完璧でなくても構いません。今すぐ "
    "confirm_tutorial だけを呼んでください（意図どおりなら looks_correct=true。"
    "明らかな問題が残っているなら looks_correct=false とし、note に理由を書く）。"
)
_UNCONFIRMED_FINISH_MAX_RESCUES = 2

# 2026-09-20追加: リファクタリング時に発見したギャップへの対策。上の2つの救済
# （「何も作らず終了」「finish_tutorial下書きが未確定のまま終了」）は、それぞれ
# 「ノードが1つも無い」「finish_tutorialは呼んだ」を前提にしており、その中間
# ケース——ノードは作成済み（cook成功済みかもしれない）だがfinish_tutorial自体を
# 一度も呼ばずにテキストのみで終了しようとした場合——はどちらにも該当せず
# 無条件でハード打ち切りになっていた。この場合best_unconfirmed_draft()も
# （finish_tutorialが一度も呼ばれていないため）下書きが1件も無く空を返すため、
# 実際にはノードが組み上がっているのにタイトル・概要・手順が汎用フォールバックの
# ままになってしまう。
_UNFINISHED_WORK_NUDGE_TEXT = (
    "[システム通知] ノードは作成済みですが、finish_tutorial をまだ呼んでいません。"
    "cook_node でエラーが無いことを確認したら、finish_tutorial を呼んでチュートリアル"
    "内容（title/slug/overview/steps等）を提出してください。テキストだけで終了せず、"
    "必ず finish_tutorial を呼んでください。"
)
_UNFINISHED_WORK_MAX_RESCUES = 1

# 打ち切り時のグレースフル終了（§2.6）: 反復/コスト上限が近づいた際に一度だけ差し込む
# ユーザー役テキスト。今の状態のまま仕上げるよう促し、未完成のままハード打ち切りになる
# 事態を減らす。
_GRACE_NUDGE_TEXT = (
    "[システム通知] 残りの反復回数またはコスト予算が少なくなっています。"
    "新しい大きな作業は始めず、今組み立て済みのグラフをそのまま仕上げてください。"
    "cook_node でエラーが無いことだけ確認したら、多少シンプルな内容でも構わないので"
    "finish_tutorial を呼んでチュートリアルを完成させてください。"
    # 2026-09-13追加: 時間・予算が少ない状況ではモデルがfinish_tutorialを呼んだ後の
    # confirm_tutorial呼び出しを省略しやすい（実機で、finish_tutorialを複数回呼んだ末に
    # confirm_tutorialを一度も呼ばずツール呼び出し自体をやめてしまう事例を確認した）。
    # 急いでいる状況こそ明示的に念押しする。
    "finish_tutorial の直後に見せられるビューポート画像を確認し、"
    "必ず confirm_tutorial も呼んでください（confirm_tutorialまで呼ばないと生成は完了しません）。"
)

# Phase1レベリング（IMPROVEMENT_PLAN.md §Phase1）: 同一トピックを basic→applied→advanced の
# 順で生成する際、各段のシステムプロンプトに差し込む指示文。「どのレベルを生成するか」の決定
# 自体はscore_engine.pyの理解度スコア（呼び出し側）に委ね、tutorial_agent.pyはレベルを受け取って
# 生成するだけに責務を絞る（決定ロジックをここに持ち込まない）。
_LEVEL_INSTRUCTIONS: dict[str, str] = {
    "basic":    "初心者が最初に触るノード構成に限定してください。3〜5ノード程度で、パラメータもデフォルトに近い値のまま使うことを優先します。",
    "applied":  "basic段の構成を前提に、パラメータ調整や分岐（例: ノイズの重ね掛け、条件による分岐）を1〜2個追加してください。",
    "advanced": "applied段を前提に、実務で使う応用パターン（VEXコード・式・複数ノードの連携等）を含めてください。",
}
_DEFAULT_LEVEL = "basic"

_SYSTEM_PROMPT_TEMPLATE = """あなたは Houdini のエキスパートで、初心者向けチュートリアルを作成するエージェントです。
与えられたツールで Houdini のノードグラフを実際に組み立て、動作確認済みのチュートリアルを作成します。

## レベル: {level}（basic → applied → advanced の一貫進行の一部として生成しています）
{level_instruction}
{prior_level_summary}
{reference_section}
{requirements_section}
{domain_sections}

## 絶対ルール
- ノード操作はサンドボックス `{sandbox_path}` 内でのみ行われます。ノードパスは常にサンドボックス相対（例: `geo1/grid1`）で指定してください。
- 以下の「よく使うノードタイプ」に無いタイプ名が少しでも不確かな場合は、create_node の前に必ず list_available_node_types で正確な名前を確認してください（例: `mountain` ではなく `mountain::2.0`）。既知のタイプ名について毎回確認する必要はありません。
- SOP を作るには、まずサンドボックス直下に Object カテゴリの `geo` ノードを作成し、その中に SOP ノードを作成します。
- グラフを組み終えたら必ず最終ノードを cook_node で評価し、エラーがあれば修正して再 cook してください。エラーが残ったまま finish_tutorial を呼んではいけません。
- ビューポートの表示（ディスプレイ/レンダーフラグ）はシステムが自動で管理します。connect_nodes で接続した先の末端ノード（出力先が無いノード）と、cook_node したノードが表示されます。display/render は set_parameter で設定できるパラメータではありません（試しても失敗します）。複数の要素（例: 地形と、その上に散布した岩）を同時に見せたい場合は、Merge ノードで結合して末端にしてください（片方しか見えない状態で終わらせないこと）。すべてのノードを最終的な1本の流れにつなぐこと（つなぎ忘れたノードは結果に反映されません）。
- pyro/fire/クロス/パーティクル/流体/剛体等のシミュレーション系ノードを cook_node する際は、システム側が自動的に複数フレーム分evaluateして時間発展する挙動を検証します（1フレームだけでは正しく動くか分からないためです）。
- list_available_node_types で調べ続けるより、最も可能性の高いタイプ名で create_node を試す方が早いことが多いです（間違っていても cook_node のエラーから自己修正できます）。ノードを1つも作らずにテキストだけで応答して終了することは禁止です。必ず何らかのツールを呼んでください。
- トピックが「電子パーティクル」「銀河」のような、Houdiniの具体的なノードタイプ名にそのまま対応しない抽象的・比喩的な題材であっても構いません。その名前のノードタイプを探し続けるのではなく、基本形状（sphere/tube/torus等）・散布や複製（scatter::2.0, copytopoints::2.0）・ノイズや変形（mountain::2.0等）を組み合わせて「それらしい見た目」を表現する方針に切り替えてください。完璧な再現より、まず何かを組み立てて完成させることを優先してください。
- cook_node が成功しても中身が正しいとは限りません。cook_node の後に inspect_geometry で、点が0個でないか・範囲がおかしくないか・必要な属性が付いているか・画像が一定値でないかを数値で確かめてください（SOP / COP / LOP）。
- ランプ（グラデーション・カーブ）のパラメータは value ではなく set_parameter の ramp（pos と value の配列）で設定します（value だと点が1個に潰れます）。
- connect_nodes の入力は、VOPなど意味が名前で決まるノードでは input_name / output_name で指定します（番号の取り違えは cook が通ってしまい気づけません）。入力名は get_node_info で分かります。

## よく使うノードタイプ（このリストにあれば list_available_node_types は不要）
{common_node_types}

## 完了の手順（2段階の自己確認）
1. リクエストと参考ドキュメントからチュートリアルの構成を決める（3〜8ノード程度の到達可能なスコープに収める）
2. ノードを作成・接続・パラメータ設定する
3. cook_node でエラー確認 → 自己修正
4. エラーゼロを確認したら finish_tutorial を呼ぶ。steps には実際に行った操作を初心者が再現できる粒度で書き、pitfalls には生成中に遭遇したエラーと対処を書く。next_steps には「このパラメータを変えたら/このノードを足したら何が変わるか」を具体的に3〜5個挙げ、読んだ人が自分のプロジェクトに応用するための手がかりにする（手順の要約の繰り返しにしないこと）。sources_used には実際に参考にした「参考ドキュメント」の番号（下記の[1][2]...）を記入する（使っていなければ空配列）
5. finish_tutorial の直後に現在のビューポート画像が送られます。**その画像を確認し、意図した見た目になっているか自己検証してから、必ず confirm_tutorial を呼んでください。** 見た目に問題があれば looks_correct=false にして修正し、finish_tutorial からやり直してください

## 参考ドキュメント（{kb_label} ナレッジベース。番号は sources_used で引用する際に使う）
{rag_context}"""



_GSPLAT_SECTION = """
## ガウシアンスプラット（GSplat）について
Houdini 22 のガウシアンスプラットは、3DGS標準の属性を持つ「ポイント」です（専用のプリミティブではありません）。
「ガウシアンスプラット風」の見た目（球や光る粒で代用する等）で済ませてはいけません。必ず次の方法で本物のGSplatを扱ってください。
- 既存データの読み込み: 3DGS形式の .ply は File SOP（file）の file にパスを渡すだけで読み込めます（P と f_dc_0〜2, opacity, scale_0〜2, rot_0〜3 のポイント属性になる）。
- 手続き的に生成: scatter::2.0 などでポイントを作り、attribwrangle で次の属性を与えます: f@opacity（不透明度。大きいほど不透明）, f@scale_0 / f@scale_1 / f@scale_2（各軸の大きさ。対数値なので -3〜-5 程度が小さな粒）, f@rot_0〜f@rot_3（クォータニオン。回転なしは 1,0,0,0）, f@f_dc_0 / f@f_dc_1 / f@f_dc_2（色。球面調和の0次係数で、0付近が中間色。正負で色味が変わる）。
- 最後に必ず bakegsplat（Bake GSplats）を接続し、これを末端にします。3DGS属性を Houdini/Karma が扱える形（orient, scale, Cd, GS_Alpha）へ変換するノードです（実機で変換の成功と Karma 用の属性付与を確認済み）。
- 関連ノード: COP の rasterizegsplats（GSplatを画像にする。Cop カテゴリ）、SOP の labs::normals_from_gsplats::1.0 / labs::delight_gsplats::1.0、LOP の labs::relight_gsplats::1.1。
- 写真からの再構成（学習）は Houdini 内では行いません。学習済みの .ply が無い場合は、手続き生成＋bakegsplat で「GSplatの属性と変換の仕組み」を学べる内容にしてください。
- 完成後、steps の冒頭に「このセットアップでどの属性がGSplatの何を決めているか」を短く書くこと。
"""

_ANIMATION_SECTION = """
## アニメーション・リギング
- 動きは set_parameter の expression（Hscript式。例 `sin($F*0.2)*3`、`fit($F,1,48,0,5)`）または keyframes（[{"frame":1,"value":0},{"frame":24,"value":5}]、interpolation は linear/bezier/constant/ease）で付けます。タプル（t, r, s）ではなく成分（tx, ty, tz, rx...）ごとに指定します。固定値を入れるだけでは動きません。
- cook_node は、時間で変わるノードを自動で複数フレーム評価します。動きが途中で壊れないかの確認になります。
- ビューポート動画のクリップは cook_node のときに撮られます。動きを見せたいノードを最後に cook_node してください。
- 骨格・キャラクター（KineFX）: kinefx::skeleton（Skeleton）, kinefx::rigpose（Rig Pose）, kinefx::skeletonblend::3.0, kinefx::biped_setup, kinefx::characterio::2.0（file）。キャラクターの読み込み: kinefx::fbxcharacterimport（fbxfile / アニメ付きは animfbxfile）, kinefx::gltfcharacterimport（gltffile）, kinefx::usdcharacterimport（usdfile）。これらは出力が3本（output1〜3）あるので、cook して中身を確認し、connect_nodes の output_index を使い分けてください。アニメーションだけ読む kinefx::fbxanimimport もあります。
- APEX（SOPノードとして作れる）: apex::autorigbuilder, apex::autorigcomponent::3.0, apex::mapcharacter, apex::rigpose, apex::packcharacter, apex::unpackcharacter, apex::invokegraph, apex::sceneanimate, apex::sceneaddcharacter。apex::graph の「グラフの中身」はこのツールでは編集できないので、APEXのSOPノードを接続して構成します。
- ノード名や入力の意味が不確かなときは、list_available_node_types（category=Sop、filter に kinefx や apex）と get_node_info で確認してから接続すること。
- 見た目の確認では、静止画1枚ではなく、動かした結果（複数フレームで値が変わっていること）をツールの返答の評価値で確かめること。
"""

_REFERENCE_SECTION = """
## 参考画像について
ユーザーが完成イメージの参考画像を添付しています（最初のメッセージ）。テキストのトピックだけでは伝わらない見た目の意図が含まれています。
- 作り始める前に、画像から読み取れる特徴（全体の形・要素の構成・色・質感・密度・スケール感）を3〜5点に整理し、それを再現できるノード構成を選ぶこと。
- Houdiniのノードで再現できる範囲に収める。写実的な質感の完全再現は目指さず、形・構成・色の傾向を優先する。
- finish_tutorial の直後に見せられるビューポート画像を、この参考画像と見比べて confirm_tutorial を判断する。形・色・構成が大きくズレていれば looks_correct=false にして直す。note には参考画像との違いを書く。
- finish_tutorial の steps の冒頭（最初の手順の前）に、「参考画像から読み取った特徴」を短い箇条書きで入れる。
- テキストのトピックと画像が食い違う場合は、トピック（テキスト）を優先し、食い違いを pitfalls に書く。
"""

_MODEL_EXTENSIONS = (
    ".fbx", ".glb", ".gltf", ".usd", ".usda", ".usdc", ".usdz", ".obj", ".bgeo", ".bgeo.sc", ".abc", ".ply",
)


def build_target_model_section(path: str) -> str:
    """ユーザーが選んだ対象モデルを、プロンプトに入れる節にする（無ければ空文字）。"""
    if not path:
        return ""
    p = Path(path)
    name = p.name
    lower = name.lower()
    ext = next((e for e in sorted(_MODEL_EXTENSIONS, key=len, reverse=True) if lower.endswith(e)), p.suffix.lower())
    posix = str(p).replace("\\", "/")
    if ext == ".fbx":
        how = "kinefx::fbxcharacterimport の fbxfile（アニメーションも入っているなら animfbxfile も）に設定する。静的なメッシュとして使うだけなら File SOP でもよい"
    elif ext in (".glb", ".gltf"):
        how = "kinefx::gltfcharacterimport の gltffile に設定する（静的メッシュだけなら File SOP でもよい）"
    elif ext in (".usd", ".usda", ".usdc", ".usdz"):
        how = "kinefx::usdcharacterimport の usdfile に設定する"
    else:
        how = "File SOP（file）の file に設定して読み込む"
    return f"""
## 対象モデル（ユーザーが選択）
このチュートリアルは、次のモデルファイルを使って行います。
- ファイル: {name}
- 絶対パス: {posix}
- 読み込み方: {how}
- 読み取り専用です。書き換え・削除・別の場所への保存はしないこと。
- このモデルを使わずに、別の形（箱や球など）を作って代用しないこと。読み込めない場合は、cook_node のエラーを読んで原因を直し、直せなければ pitfalls に理由を書く。
"""


_GSPLAT_PATTERN = re.compile(r"gaussian|gsplat|splat|3dgs|ガウシアン|スプラット|スプラッド", re.IGNORECASE)
_ANIMATION_PATTERN = re.compile(
    r"animat|アニメ|\brig(ging)?\b|リグ|skelet|スケルトン|kinefx|\bapex\b|キーフレーム|keyframe|モーション|motion|ボーン|\bbones?\b|歩行|歩かせ|歩く|走らせ|キャラクター|\bwalk|\bcharacter",
    re.IGNORECASE,
)


_HOUDINI22_SECTION = """
## Houdini 22 の新機能（実機でノードの作成と cook を確認済み。名前はこのとおりに使う）
- Copernicus（copnet の中。category=Cop）が大幅に増えました。
  - ノイズ・パターン: cellularnoise, curlnoise, fractalnoise, worleynoise, turingpatterns, cellpattern
  - 汚れ・質感（grunge）: grunge_rustysurface, grunge_moisture, grunge_drips, grunge_moldspots, grunge_wipetrails
  - ハイトフィールド: monotoheightfield → heightfield_erode / heightfield_terrace / heightfield_slump / heightfield_strata（入力は画像。noise 系 → monotoheightfield → 侵食、の流れ）
  - 時間: timeloop, timeshift, timeblend / 効果: starglow, dropshadow, convolvefilter / テスト用ジオメトリ: testgeometry_capybara など
  - 入力が必要なノードが多いので、get_node_info で入力名を確認してから接続すること
- SOP: implicitsurface（暗黙サーフェス。_convert / _eval / _slice 等の関連ノードあり）, uvrelax, labs::autouv::1.0, blastbyattribute, curveanimate, walkonsurface（第2入力は多角形メッシュ）, voronoifracture::3.0, rbdmaterialfracture::4.0, rbdmetalfracture, guidedeform::2.0, camera / cameraedit
- LOP(Solaris): plane, scatterinstances, pointinstancer, texturemateriallibrary, imagefilter, relocate。入力の意味は get_node_info で確認する
- DOP: rbdreplicator。ROP: gltf::2.0（書き出しは行わない）
- TOP の ML 系（ml_traingsplats など）と neural 系 COP はモデルや GPU を要するため、ノードを作るだけにして実行しない
"""


def build_houdini22_section(rag_name: str) -> str:
    """Houdini 22 以降で動いているときだけ、新機能の節を足す。"""
    major = None
    try:
        import hou  # Houdini の中でだけ成功する

        major = int(hou.applicationVersion()[0])
    except Exception:  # noqa: BLE001
        match = re.fullmatch(r"houdini(\d+)", rag_name or "")
        major = int(match.group(1)) if match else None
    return _HOUDINI22_SECTION if major is not None and major >= 22 else ""


def build_domain_sections(topic: str, requirements: str, target_model: str) -> str:
    """トピック・条件・対象モデルから、必要な専門知識の節（GSplat / アニメーション・リギング）を選ぶ。"""
    text = f"{topic}\n{requirements}"
    parts = []
    if _GSPLAT_PATTERN.search(text):
        parts.append(_GSPLAT_SECTION)
    if target_model or _ANIMATION_PATTERN.search(text):
        parts.append(_ANIMATION_SECTION)
    return "".join(parts)


def build_requirements_section(requirements: str) -> str:
    requirements = (requirements or "").strip()
    if not requirements:
        return ""
    return f"""
## ユーザー指定の必須条件（最優先）
{requirements}
- この条件はトピックより優先します。条件にある技法・ノードは、それ「風」の代用で済ませず、実際に使うこと。
- 満たせなかった場合は、何ができなかったか・なぜかを finish_tutorial の pitfalls に必ず書くこと。
"""

# ─── 参考画像（テキスト＋画像での生成、2026-10-05追加） ───────────────────────────────
# テキストのトピックだけだと、ユーザーの求める完成イメージからズレることがある。完成イメージの
# 参考画像（スクショ・写真・ラフ等）を一緒に渡せるようにする。Claudeには画像ブロックとして
# 最初のユーザーメッセージに載せる。GAS経由・Cloudflare経由のどちらも messages をそのまま
# Claudeへ中継するので、追加の対応は要らない。
MAX_REFERENCE_IMAGES = 4
_REFERENCE_IMAGE_MAX_EDGE = 1280  # 長辺。1280x720 ≒ 1,200トークン程度に収まる（大きいほど高コスト）


def load_reference_images(paths: list[str], max_images: int = MAX_REFERENCE_IMAGES) -> tuple[list[dict], list[str]]:
    """
    画像ファイルを Claude の image ブロックに変換する。戻り値は (ブロック一覧, 読み込めたファイル名一覧)。
    長辺を _REFERENCE_IMAGE_MAX_EDGE に縮小し、JPEG（使えなければPNG）に再エンコードしてコストと
    通信量を抑える。透明PNGは白背景に合成する（JPEG化で黒く潰れないように）。読めないファイルは
    黙って飛ばす（生成そのものは止めない）。Qtが無い環境（テスト等）では何も読まない。
    """
    try:
        import base64

        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QColor, QImage, QPainter
    except Exception:  # noqa: BLE001
        return [], []

    blocks: list[dict] = []
    names: list[str] = []
    for raw in list(paths)[:max_images]:
        try:
            image = QImage(str(raw))
            if image.isNull():
                continue
            if max(image.width(), image.height()) > _REFERENCE_IMAGE_MAX_EDGE:
                image = image.scaled(
                    _REFERENCE_IMAGE_MAX_EDGE, _REFERENCE_IMAGE_MAX_EDGE,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
            flat = QImage(image.size(), QImage.Format_RGB32)
            flat.fill(QColor("white"))
            painter = QPainter(flat)
            painter.drawImage(0, 0, image)
            painter.end()

            data, media_type = QByteArray(), "image/jpeg"
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            if not flat.save(buffer, "JPEG", 85):  # Houdini同梱のQtにJPEGプラグインが無い場合はPNG
                data, media_type = QByteArray(), "image/png"
                buffer = QBuffer(data)
                buffer.open(QIODevice.WriteOnly)
                if not flat.save(buffer, "PNG"):
                    continue
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type,
                           "data": base64.b64encode(bytes(data)).decode("ascii")},
            })
            names.append(Path(str(raw)).name)
        except Exception:  # noqa: BLE001 -- 1枚読めなくても残りで続行
            continue
    return blocks, names


# ─── 結果オブジェクト ─────────────────────────────────────────────────────────────

class TutorialResult:
    """generate() の戻り値。UI がプレビュー・保存に使う。"""

    def __init__(self) -> None:
        self.markdown: str = ""
        self.graph: dict = {}
        self.title: str = ""
        self.slug: str = "tutorial"
        self.sandbox_path: str = ""
        # Phase1レベリング（basic|applied|advanced）。frontmatterのdifficultyフィールドと
        # build_level_chain() の prior_level_summary 引き継ぎに使う。
        self.level: str = _DEFAULT_LEVEL
        self.rag_name: str = "houdini21"  # 検索したナレッジ（動画のブランド表示・タグに使う）
        self.reference_image_count: int = 0  # 生成に使った参考画像の枚数
        self.requirements: str = ""  # 生成時にユーザーが指定した必須条件
        self.target_model: str = ""  # アニメ・リギング用に選んだ対象モデルのファイル名
        self.next_steps: str = ""  # finish_tutorialのnext_steps（応用・発展のヒント）
        self.pitfalls: str = ""    # finish_tutorialのpitfalls（ハマりポイント）
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
        # 生成時に自動で記録する品質指標（tutorial_feedback.write_metrics が <名前>_metrics.json に書く）。
        # 人手の評価が無くても、モデル・レベル・領域別の傾向を集計できるようにする（2026-10-05）。
        self.metrics: dict = {}
        self.completed: bool = False   # confirm_tutorial(looks_correct=true) まで到達したか
        self.abort_reason: str = ""    # 打ち切り理由（上限到達など）
        # confirm_tutorialが呼ばれないまま打ち切られ、代わりにbest_unconfirmed_draft()の
        # 下書きをtitle/overview/steps等に採用した場合True（2026-09-13追加）。completed
        # はFalseのままだが、保存内容が汎用フォールバックではなく実際の下書きであることを
        # 示す。_assemble_markdownがこのフラグを見て本文に注意書きを追加する。
        self.used_unconfirmed_draft: bool = False
        # sources[i] に "cited": bool が付与される（finish_tutorial の sources_used で
        # 報告された番号と対応）。RAGが実際にどれだけ生成に寄与したかの研究データ。
        self.sources: list[dict] = []
        # finish_tutorial の sources_used（1始まりの引用番号一覧）をそのまま保持する。
        self.rag_sources_cited: list[int] = []
        # 引用率（cited済みsource数 / 全source数）。sourcesが空ならNone。
        self.rag_extraction_rate: float | None = None
        # generate()の壁時計経過秒数（2026-09-20追加）。トピック入力時の「過去の生成の
        # 平均コスト・所要時間」見積もり表示（token_usage.py）用。RAG検索・サンドボックス
        # 作成・エージェントループ・Markdown組み立てまで全体を計測する（ユーザーが実際に
        # 待つ時間の実感に合わせるため、API呼び出し部分だけを計測するより意味がある）。
        self.elapsed_seconds: float = 0.0

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
        model: str = DEFAULT_MODEL,
        claude_backend: str = "gas",
        cf_url: str = "",
        cf_api_key: str = "",
        rag_namespace: str = "",
        reference_images: list[str] | None = None,
        requirements: str = "",
        target_model: str = "",
        progress_cb: Callable[[str], None] | None = None,
        executor_factory: Callable[..., HoudiniToolExecutor] | None = None,
    ) -> None:
        self._port = bridge_port
        self._project_dir = project_dir
        self._rag_mode = rag_mode if rag_mode in ("local", "cloud", "cloudflare") else "local"
        self._gas_url = gas_url
        self._gas_api_key = gas_api_key
        # claude_backend: Claude Messages APIをどちら経由で呼ぶか（2026-08-26追加）。
        # 既定は既存動作を変えない"gas"。cloudflare-rag-poc側にClaude APIプロキシ
        # （/claude/messages）を追加したことでの移行先。GASのようなCloudトークン予算
        # 強制は、Cloudflare側ではtoken_budgets（budget_type='claude'）が担う。
        self._claude_backend = claude_backend if claude_backend in ("gas", "cloudflare") else "gas"
        self._cf_url = cf_url
        self._cf_api_key = cf_api_key
        # 検索対象のナレッジ（houdini21 / houdini22 ...）。resolve_rag_name参照。
        self._rag_name = resolve_rag_name(rag_namespace)
        # 完成イメージの参考画像（ファイルパス）。generate()の冒頭で読み込む。
        self._reference_paths = list(reference_images or [])
        self._reference_blocks: list[dict] = []
        self._reference_names: list[str] = []
        # 生成時にユーザーが指定する「必須条件」（自由記述）と、アニメ・リギング用の対象モデル
        # （ファイルパス）。どちらもプロンプトに差し込む（build_requirements_section / build_target_model_section）。
        self._requirements = (requirements or "").strip()
        self._target_model = (target_model or "").strip()
        # 未知のモデル名（設定ファイルの旧値・手編集など）はデフォルトにフォールバック
        self._model = model if model in _MODEL_PRICES else DEFAULT_MODEL
        self._progress = progress_cb or (lambda _: None)
        self._executor_factory = executor_factory or HoudiniToolExecutor
        self.executor: HoudiniToolExecutor | None = None  # 生成後もサンドボックス削除用に保持

    # ── 公開 API ────────────────────────────────────────────────────────────────

    def set_progress_callback(self, cb: Callable[[str], None]) -> None:
        """
        progress_cb をコンストラクタ後に差し替える（2026-09-20追加）。
        tutorial_view.py の単発生成パスは、TutorialWorker（QThread）が持つ
        Signal.emit を progress_cb に使いたいが、TutorialWorkerの構築には
        TutorialAgentのインスタンスが先に必要という順序上の制約がある。
        以前はこれを self._agent._progress = ... という「プライベート属性への
        外部からの直接代入」で回避していたが、名前が変わればサイレントに壊れる
        脆い書き方だったため、正式な公開APIとして切り出した。
        """
        self._progress = cb or (lambda _: None)

    def generate(
        self,
        topic: str,
        level: str = _DEFAULT_LEVEL,
        prior_level_summary: str = "",
    ) -> TutorialResult:
        """
        level: "basic" | "applied" | "advanced"（IMPROVEMENT_PLAN.md Phase1）。
        どのレベルを生成するかの判断は呼び出し側（UI / score_engine.py）の責務で、
        ここでは受け取ったレベルに応じてプロンプトを差し替えるだけに留める。
        prior_level_summary: 前段（basic→appliedの場合はbasicの結果）の要約。
        basic生成時は空文字を渡す。_summarize_for_next_level() で組み立てる。
        """
        if level not in _LEVEL_INSTRUCTIONS:
            level = _DEFAULT_LEVEL
        start_time = time.monotonic()
        result = TutorialResult()
        result.level = level
        result.rag_name = self._rag_name
        self._reference_blocks, self._reference_names = load_reference_images(self._reference_paths)
        result.reference_image_count = len(self._reference_blocks)
        result.requirements = self._requirements
        result.target_model = Path(self._target_model).name if self._target_model else ""
        if self._reference_paths:
            if self._reference_blocks:
                self._progress(f"参考画像 {len(self._reference_blocks)} 枚を添えて生成します: {', '.join(self._reference_names)}")
            else:
                self._progress("参考画像を読み込めませんでした（テキストのみで続行）")

        if self._requirements:
            self._progress(f"生成条件を指定して生成します: {self._requirements[:80]}")
        if self._target_model:
            if Path(self._target_model).is_file():
                self._progress(f"対象モデルを使って生成します: {Path(self._target_model).name}")
            else:
                self._progress(f"対象モデルが見つかりません（モデル無しで続行）: {self._target_model}")
                self._target_model = ""

        # Claude APIは必ずGASまたはCloudflare経由で呼ぶ（claude_backendで選択）。生の
        # ANTHROPIC_API_KEYをクライアントに持たせない構成にすることで、APIキーごとの
        # トークン上限をクライアント側から迂回できないようにしている
        # （docs/cloud-rag.md §8.14、Cloudflare側はtoken_budgets/budget_type='claude'）。
        if self._claude_backend == "cloudflare":
            if not self._cf_url or not self._cf_api_key:
                raise RuntimeError(
                    "Cloudflare RAG WebApp URL / APIキーが未設定です。Settingsタブで設定してください"
                    "（houdini21チュートリアル生成はClaude APIをCloudflare経由で呼ぶため必須です）。"
                )
        elif not self._gas_url or not self._gas_api_key:
            raise RuntimeError(
                "GAS WebApp URL / APIキーが未設定です。Settingsタブで設定してください"
                "（houdini21チュートリアル生成はClaude APIをGAS経由で呼ぶため必須です）。"
            )

        # ① RAG検索（houdini<バージョン> namespace のみ）
        self._progress(f"RAG検索中（{self._rag_name} ナレッジベース / {self._rag_mode} / レベル={level}）...")
        rag_texts, result.sources = self._rag_search(topic, level)
        # Cloudflare/ローカルブリッジの /search は file / namespace キーで返すが、Markdownの参考欄は
        # title / db を読むため、そのままだと「[1] ⬜ 未引用 （）」と題名が空になっていた。
        for s in result.sources:
            s.setdefault("title", s.get("file", ""))
            s.setdefault("db", s.get("namespace", ""))
        if rag_texts:
            self._progress(f"参考ドキュメント {len(result.sources)} 件を取得しました（{self._rag_name}）")
        else:
            self._progress(
                f"参考ドキュメントが取得できませんでした（コンテキストなしで続行）。検索対象: {self._rag_name}"
            )

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
        if prior_level_summary:
            self._progress(f"前段の要約をプロンプトに引き継ぎました（{len(prior_level_summary)} 文字）")
        system_blocks, tools, messages = self._build_initial_prompt(
            topic, rag_texts, level, prior_level_summary
        )
        try:
            self._run_loop(system_blocks, tools, messages, result)
        finally:
            result.iterations = self._count_iterations()

        # ④ 成果物組み立て（打ち切りでも途中経過を提示する）
        result.graph = self.executor.export_node_graph()
        result.step_screenshots = self.executor.export_step_screenshots()
        result.completed = self.executor.finish_data is not None
        finish = self.executor.finish_data
        if finish is None:
            # confirm_tutorialが一度も呼ばれず打ち切られた場合、以前は無条件に
            # finish={}（＝タイトルはトピック名の汎用フォールバック、概要・手順は
            # 空）になっていた。実機で、モデルが良い下書きを複数回書いた後、最後だけ
            # title="テスト"のようなプレースホルダーで終わってしまい、それまでの
            # 良い下書きが丸ごと捨てられる事例を確認した（2026-09-13）。
            # best_unconfirmed_draft()は全下書きの中から本文量最大のものを選ぶため、
            # このケースでも以前のまともな下書きを拾える。
            finish = self.executor.best_unconfirmed_draft()
            result.used_unconfirmed_draft = finish is not None
        finish = finish or {}
        result.title = finish.get("title") or f"Houdiniチュートリアル: {topic}"
        result.slug = self._sanitize_slug(finish.get("slug", ""), topic)
        result.next_steps = finish.get("next_steps", "")
        result.pitfalls = finish.get("pitfalls", "")
        self._apply_rag_attribution(finish, result, result.completed)
        result.markdown = self._assemble_markdown(topic, finish, result)
        result.elapsed_seconds = time.monotonic() - start_time
        result.metrics = self._collect_metrics(result, topic)

        status = "完了" if result.completed else f"打ち切り（{result.abort_reason}）"
        self._progress(
            f"生成{status}: {result.iterations} イテレーション / ${result.cost_usd:.3f} "
            f"/ {result.elapsed_seconds:.0f}秒"
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

    @staticmethod
    def _summarize_for_next_level(result: "TutorialResult") -> str:
        """
        basic→applied→advanced のレベルチェーン（build_level_chain）で、前段の
        結果を次段のシステムプロンプトへ引き継ぐための短い要約を組み立てる。
        finish_tutorial の生の出力全体を渡すと次段のプロンプトが無駄に長くなる
        （かつプロンプトキャッシュの恩恵も薄い一回限りの追加コンテキストになる）
        ため、steps/pitfalls/next_stepsを圧縮せず「前段で何を作ったか」
        「次段が引き継ぐべき示唆」だけに絞る。打ち切り（completed=False）の場合は
        次段のプロンプトを不必要に複雑にしないよう空文字を返す。
        """
        if not result.completed:
            return ""
        parts = [f"前段（{result.level}）で作成したチュートリアル: {result.title}"]
        if result.pitfalls:
            parts.append(f"前段で遭遇したハマりポイント（同じ轍を踏まないこと）:\n{result.pitfalls}")
        if result.next_steps:
            parts.append(f"前段が示した発展の方向性（このレベルではこれを一段深める）:\n{result.next_steps}")
        return "\n\n".join(parts)

    # ── RAG検索 ─────────────────────────────────────────────────────────────────

    def _rag_search(self, topic: str, level: str = _DEFAULT_LEVEL) -> tuple[list[str], list[dict]]:
        """rag_mode に応じてローカルブリッジ / GAS（Cloud RAG）/ Cloudflare（cloudflare-rag-poc）
        いずれかから houdini21 namespace の生チャンクを取得する。"""
        if self._rag_mode == "cloudflare":
            return self._rag_search_cloudflare(topic, level)
        if self._rag_mode == "cloud":
            return self._rag_search_cloud(topic)
        return self._rag_search_local(topic, level)

    def _rag_search_local(self, topic: str, level: str = _DEFAULT_LEVEL) -> tuple[list[str], list[dict]]:
        """
        ローカルブリッジの /search から houdini21 namespace の生チャンクを取得する。
        level（Phase1レベリング）は rag_local_bridge.py の /search に渡し、
        difficulty が一致するドキュメントを優先的に検索対象にする（difficulty未設定の
        ドキュメントは level 指定時も通過するため、後方互換は保たれる）。
        """
        try:
            body = json.dumps({
                "query": topic,
                "limit": RAG_LIMIT,
                "namespaces": [self._rag_name],
                "level": level,
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

        Phase1レベリング（IMPROVEMENT_PLAN.md）の level フィルタは rag_local_bridge.py
        （Local RAG）側にのみ実装されており、gas_cloud_rag.js（Cloud RAG）側は未対応の
        ため、ここでは level を渡していない（Cloud モードでは全レベル対象のまま）。
        """
        if not self._gas_url:
            self._progress("Cloud RAG検索エラー: GAS WebApp URLが未設定です（続行します）")
            return [], []
        try:
            body = json.dumps({
                "query": topic,
                "dbKey": self._rag_name,
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
                if s.get("db") == self._rag_name
            ]
            if not raw_sources:
                self._progress(
                    f"Cloud RAGに{self._rag_name}のドキュメントが見つかりませんでした"
                    f"（APIキーに{self._rag_name}の権限があるか確認してください）"
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

    def _rag_search_cloudflare(self, topic: str, level: str = _DEFAULT_LEVEL) -> tuple[list[str], list[dict]]:
        """
        Cloudflare Workers RAG（cloudflare-rag-poc）の /search から
        houdini21 相当のnamespace（shared:houdini21）の生チャンクを取得する
        （GAS Cloud RAGの後継、2026-08-26追加）。

        Cloudflare側はnamespaceアクセス制御がAPIキーごとの許可リストで厳格に
        行われ、GASのような「権限が無いと"all"に自動フォールバックする」挙動が
        無いため、_rag_search_cloud のような応答側でのdb二重フィルタは不要（サーバー側の
        namespaceパラメータそのものが唯一のホワイトリストとして機能する）。
        レスポンス形式は rag_local_bridge.py の /search と同じ {texts, sources} なので、
        そのまま _rag_search_local と同じ扱いでよい。
        """
        if not self._cf_url or not self._cf_api_key:
            self._progress("Cloudflare RAG検索エラー: URL/APIキーが未設定です（続行します）")
            return [], []
        try:
            body = json.dumps({
                "query": topic,
                "limit": RAG_LIMIT,
                "namespaces": [f"shared:{self._rag_name}"],
                "level": level,
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{self._cf_url.rstrip('/')}/search",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._cf_api_key}",
                    "User-Agent": _HTTP_USER_AGENT,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            texts, sources = data.get("texts", []), data.get("sources", [])
            if not sources:
                self._progress(
                    f"Cloudflare RAGの shared:{self._rag_name} から該当ドキュメントが0件でした"
                    "（APIキーにこのnamespaceの権限があるか、ナレッジが同期済みか確認してください）"
                )
            return texts, sources
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._progress(f"Cloudflare RAG検索エラー {exc.code}（続行します）: {detail}")
            return [], []
        except Exception as exc:
            self._progress(f"Cloudflare RAG検索エラー（続行します）: {exc}")
            return [], []

    # ── プロンプト構築 ──────────────────────────────────────────────────────────

    def _build_initial_prompt(
        self,
        topic: str,
        rag_texts: list[str],
        level: str = _DEFAULT_LEVEL,
        prior_level_summary: str = "",
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """
        システム・ツール・初期メッセージを構築する。
        固定部分（システムプロンプト＝RAGコンテキスト込み・ツール定義）に
        cache_control を付け、2回目以降のターンのコストを抑える（§4.2）。

        level/prior_level_summary は Phase1レベリング用。prior_level_summary は
        basic生成時は空文字（該当セクション自体を出さない）、applied/advanced生成時は
        _summarize_for_next_level() が組み立てた前段の要約が入る。
        """
        rag_context = "\n\n".join(rag_texts) if rag_texts else "（参考ドキュメントなし）"
        prior_summary_block = (
            f"## 前段（このトピックの一つ手前のレベル）の要約\n{prior_level_summary}"
            if prior_level_summary else ""
        )
        system_text = _SYSTEM_PROMPT_TEMPLATE.format(
            sandbox_path=self.executor.sandbox_path,
            kb_label=self._rag_name,
            rag_context=rag_context,
            common_node_types=_COMMON_NODE_TYPES_BLOCK,
            level=level,
            level_instruction=_LEVEL_INSTRUCTIONS.get(level, _LEVEL_INSTRUCTIONS[_DEFAULT_LEVEL]),
            prior_level_summary=prior_summary_block,
            reference_section=_REFERENCE_SECTION if self._reference_blocks else "",
            requirements_section=build_requirements_section(self._requirements),
            domain_sections=build_target_model_section(self._target_model)
            + build_domain_sections(topic, self._requirements, self._target_model)
            + build_houdini22_section(self._rag_name)
            + self._feedback_sections(topic),
        )
        system_blocks = [{
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }]

        tools = [dict(t) for t in HOUDINI_TOOLS]
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}

        if self._reference_blocks:
            content: list[dict] | str = []
            for index, (name, block) in enumerate(zip(self._reference_names, self._reference_blocks), start=1):
                content.append({"type": "text", "text": f"[参考画像 {index}: {name}]"})
                content.append(block)
            content.append({
                "type": "text",
                "text": (
                    f"{self._task_text(topic)}\n\n"
                    "上の画像は、私が求めている完成イメージの参考です。見た目の特徴を読み取って、"
                    "それに近づくようにノードを組んでください。"
                ),
            })
        else:
            content = self._task_text(topic)
        messages = [{"role": "user", "content": content}]
        return system_blocks, tools, messages

    def _task_text(self, topic: str) -> str:
        """最初のユーザーメッセージ本文（トピック＋必須条件＋対象モデル）。"""
        text = f"次のトピックのHoudiniチュートリアルを作成してください: {topic}"
        if self._requirements:
            text += f"\n\n必須条件（必ず守ること）: {self._requirements}"
        if self._target_model:
            text += f"\n\n対象モデル: {Path(self._target_model).name}（システムプロンプトの「対象モデル」を参照）"
        return text

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
        unconfirmed_finish_rescues = 0  # finish_tutorial下書き未確定のまま終了しようとした際の救済回数
        unfinished_work_rescues = 0  # ノードは作成済みだがfinish_tutorial自体を未呼び出しのまま終了しようとした際の救済回数
        cache_marked_content: list | None = None  # ローリングキャッシュ用（下記コメント参照）
        for iteration in range(1, MAX_ITERATIONS + 1):
            # ローリングプロンプトキャッシュ: messages は反復のたびに増え続けるが、
            # cache_control は system_blocks / tools（固定部分）にしか付けていなかった
            # ため、会話履歴そのもの（tool_result・アシスタント応答の蓄積）は毎ターン
            # 通常の入力価格で再送信・再課金されていた。反復が進むほど履歴が
            # 線形に伸びるため、生成1回あたりのコストは反復回数のほぼ2乗で増える
            # ことになり、これが実機で「1生成$3超え」の主因と判明した。
            # ここでは「直前のターンまでの会話」の末尾に cache_control を付け直す
            # ことで、その部分をキャッシュ読み込み価格（通常の入力価格の1/10。Opus 5.5は1/20）で
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

            stop_reason = response.get("stop_reason")
            if stop_reason == "refusal":
                # Sonnet 5.5 / Opus 5.5 などは安全分類器が応答を拒否することがある（HTTP 200、
                # stop_reason="refusal"。contentは空や途中まで）。ツール呼び出しが無いので、
                # そのままだと「作業を終えた」と誤認して救済の催促を重ねてしまう。分類つきで打ち切る。
                details = response.get("stop_details") or {}
                category = details.get("category") or "不明"
                result.abort_reason = f"モデルが安全上の理由で応答を拒否しました（分類: {category}）"
                self._progress(f"モデルが応答を拒否したため打ち切ります（分類: {category}）。別のモデルでの再生成を試してください")
                log_event = getattr(self.executor, "log_event", None)
                if log_event is not None:
                    log_event({"event": "refusal", "category": category, "explanation": details.get("explanation"), "iteration": iteration})
                return
            if stop_reason == "max_tokens":
                self._progress("警告: 1ターンの出力上限に達しました（思考や長いコードで使い切った可能性があります）")

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
                    if (
                        self.executor.pending_finish is not None
                        and unconfirmed_finish_rescues < _UNCONFIRMED_FINISH_MAX_RESCUES
                    ):
                        unconfirmed_finish_rescues += 1
                        nudge_text = (
                            _UNCONFIRMED_FINISH_NUDGE_TEXT if unconfirmed_finish_rescues == 1
                            else _UNCONFIRMED_FINISH_NUDGE_TEXT_2
                        )
                        messages.append({
                            "role": "user",
                            "content": [{"type": "text", "text": nudge_text}],
                        })
                        self._progress(
                            f"finish_tutorialの下書きが未確定のまま終了しようとしたため、"
                            f"confirm_tutorialを促しました（{unconfirmed_finish_rescues}/{_UNCONFIRMED_FINISH_MAX_RESCUES}）"
                        )
                        continue
                    if (
                        has_created_any_node
                        and self.executor.pending_finish is None
                        and unfinished_work_rescues < _UNFINISHED_WORK_MAX_RESCUES
                    ):
                        # ノードは作成済みだが finish_tutorial 自体を一度も呼んでいない
                        # まま終了しようとしたケース（上の2つの救済のどちらにも
                        # 該当しない中間ケース、2026-09-20追加）。
                        unfinished_work_rescues += 1
                        messages.append({
                            "role": "user",
                            "content": [{"type": "text", "text": _UNFINISHED_WORK_NUDGE_TEXT}],
                        })
                        self._progress(
                            f"ノード作成済みだがfinish_tutorial未呼び出しのまま終了しようとしたため、"
                            f"提出を促しました（{unfinished_work_rescues}/{_UNFINISHED_WORK_MAX_RESCUES}）"
                        )
                        continue
                result.abort_reason = "モデルがツールを呼ばず終了しました"
                # 原因調査用: 打ち切り時にモデルが最後に何と言っていたかを残す（2026-09-26追加。
                # 以前は無言で打ち切られ、「なぜ確定せずやめたのか」がログから分からなかった）。
                final_text = " ".join(
                    b.get("text", "") for b in content if b.get("type") == "text"
                ).strip()
                if final_text:
                    self._progress(f"モデルの最後の発言: {' '.join(final_text.split())[:200]}")
                log_event = getattr(self.executor, "log_event", None)
                if log_event is not None:
                    log_event({
                        "event": "ended_without_tool_call",
                        "assistant_text": final_text[:2000],
                        "pending_finish": self.executor.pending_finish is not None,
                        "iteration": iteration,
                    })
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
        """claude_backend に応じてGASまたはCloudflare経由でClaude Messages APIを呼ぶ。"""
        if self._claude_backend == "cloudflare":
            return self._call_api_cloudflare(system_blocks, tools, messages)
        return self._call_api_gas(system_blocks, tools, messages)

    def _call_api_cloudflare(
        self, system_blocks: list[dict],
        tools: list[dict], messages: list[dict],
    ) -> dict:
        """
        Claude Messages API を、Cloudflare Workers（cloudflare-rag-poc、/claude/messages）
        経由で呼ぶ（GAS Claudeプロキシの後継、2026-08-26追加）。

        GAS版と同様、生のANTHROPIC_API_KEYはクライアントに持たせない。Cloudflare側は
        APIキーごとのClaude専用トークン予算（token_budgets, budget_type='claude'）を
        サーバー側で強制する。GASの{status:'quota_exceeded'|'rate_limited'|...}という
        レスポンス内ステータスと異なり、Cloudflare側はHTTPステータスコード
        （429=予算超過/レート制限、401/403=認証エラー）でエラーを表現するため、
        エラーハンドリングの構造がGAS版と異なる点に注意。
        成功時のレスポンスは生のAnthropic Messageオブジェクトそのもの
        （contentやusageを直接読める）なので、呼び出し元（_run_loop）はGAS版と同じ
        コードでそのまま読める。
        """
        request_body = {
            "model": self._model,
            "max_tokens": MAX_TOKENS_PER_TURN,
            "system": system_blocks,
            "tools": tools,
            "messages": messages,
        }
        if not tools:
            request_body.pop("tools")  # 教訓の要約など、ツールを使わない呼び出しではtoolsを送らない
        effort = _MODEL_EFFORT.get(self._model)
        if effort:
            request_body["output_config"] = {"effort": effort}
        payload = json.dumps(request_body, ensure_ascii=False).encode("utf-8")

        attempt = 0
        while True:
            req = urllib.request.Request(
                f"{self._cf_url.rstrip('/')}/claude/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._cf_api_key}",
                    "User-Agent": _HTTP_USER_AGENT,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                # 2026-09-13: 401/403を「APIキーが無効」と即断していたが、実際には
                # 応答本文がJSONではなくCloudflareエッジ自体の遮断ページ（例:
                # "error code: 1010"）であるケースが実機で確認された（Workers
                # Observabilityにイベントが一切残らないことから、認証ロジック
                # （auth.ts）どころかWorker自体に到達する前のブロックだと確定した）。
                # Worker未到達＝トークン予算は消費されていないため、この特定パターン
                # （401/403だがWorker自身のJSON応答ではない）に限り安全に自動リトライ
                # できる。JSON解析に失敗した場合は「APIキーが無効」という誤った案内も
                # しないようにする。
                try:
                    parsed = json.loads(detail)
                    message = parsed.get("error", detail)
                    is_our_json = True
                except (json.JSONDecodeError, AttributeError):
                    message = detail
                    is_our_json = False
                if exc.code == 429:
                    raise RuntimeError(
                        f"Claudeトークンの利用上限またはレート制限に達しています: {message}"
                    ) from exc
                if exc.code in (401, 403):
                    if is_our_json:
                        raise RuntimeError(
                            f"認証エラー: Cloudflare APIキーが無効です。Settingsタブを確認してください: {message}"
                        ) from exc
                    if attempt < _CF_EDGE_BLOCK_RETRIES:
                        wait_sec = _CF_EDGE_BLOCK_BACKOFF_SEC[min(attempt, len(_CF_EDGE_BLOCK_BACKOFF_SEC) - 1)]
                        self._progress(
                            f"Cloudflareのエッジにリクエストが一時的に遮断された可能性があります"
                            f"（{wait_sec:.0f}秒後にリトライします、{attempt + 1}/{_CF_EDGE_BLOCK_RETRIES}回目）"
                        )
                        time.sleep(wait_sec)
                        attempt += 1
                        continue
                    raise RuntimeError(
                        "Cloudflareのセキュリティ機能（Bot Fight Mode／WAF等）にリクエストが"
                        "遮断された可能性があります（APIキー自体は無効でない可能性が高いです）。"
                        "Cloudflareダッシュボードのセキュリティイベントを確認してください。"
                        f" 応答本文の先頭: {message[:200]}"
                    ) from exc
                raise RuntimeError(f"Cloudflare Claudeプロキシエラー {exc.code}: {message}") from exc

    def _call_api_gas(
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
            "model": self._model,
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

    def _usage_cost(self, usage: dict) -> float:
        price = _MODEL_PRICES[self._model]
        return (
            usage.get("input_tokens", 0) * price["input"]
            + usage.get("output_tokens", 0) * price["output"]
            + usage.get("cache_creation_input_tokens", 0) * price["cache_write"]
            + usage.get("cache_read_input_tokens", 0) * price["cache_read"]
        ) / 1_000_000

    def _feedback_sections(self, topic: str) -> str:
        """
        過去の評価から作るプロンプトの節（2026-10-05）。ユーザーが承認した教訓と、似たトピックで
        高評価だった構成。どちらも無ければ空文字（従来どおりのプロンプト）。評価の仕組みの失敗で
        生成が止まらないよう、例外は握りつぶして空にする。使った件数は指標に残す（後で
        「教訓を入れた生成と入れない生成」を比べるため）。
        """
        self._lessons_used = 0
        self._examples_used = 0
        if not self._project_dir:
            return ""
        try:
            import tutorial_feedback as fb

            lessons = fb.approved_lessons(self._project_dir)
            examples = fb.select_good_examples(Path(self._project_dir) / "localRAG" / "tutorials", topic)
            self._lessons_used, self._examples_used = len(lessons), len(examples)
            if lessons or examples:
                self._progress(f"過去の評価を反映します（教訓 {len(lessons)} 件 / 高評価の参考例 {len(examples)} 件）")
            return fb.build_lessons_section(self._project_dir) + fb.build_examples_section(examples)
        except Exception as exc:  # noqa: BLE001 -- 評価の機能で生成を止めない
            self._progress(f"過去の評価の読み込みに失敗（無視して続行）: {exc}")
            return ""

    def _collect_metrics(self, result: "TutorialResult", topic: str) -> dict:
        """生成の自動指標。数値・真偽・短い文字列だけ（そのままCloudflareへ送れる形）。"""
        step_log = list(self.executor.step_log) if self.executor else []
        cook_calls = [e for e in step_log if e.get("tool") == "cook_node"]
        cook_errors = sum(1 for e in cook_calls if "[エラー]" in str(e.get("result", "")))
        rejections = sum(
            1 for e in step_log
            if e.get("tool") == "confirm_tutorial" and (e.get("input") or {}).get("looks_correct") is False
        )
        node_types = [n.get("kind", "") for n in result.graph.get("nodes", [])] if result.graph else []
        try:
            import hou  # Houdini の中でだけ成功する

            houdini_version = hou.applicationVersionString()
        except Exception:  # noqa: BLE001
            houdini_version = ""
        try:
            from tutorial_feedback import detect_domain

            domain = detect_domain(topic, self._requirements, node_types)
        except Exception:  # noqa: BLE001
            domain = "general"
        return {
            "topic": topic[:300],
            "model": self._model,
            "level": result.level,
            "rag_name": result.rag_name,
            "houdini_version": houdini_version,
            "domain": domain,
            "iterations": result.iterations,
            "tool_calls": len(step_log),
            "cook_calls": len(cook_calls),
            "cook_errors": cook_errors,
            "confirm_rejections": rejections,
            "node_count": len(node_types),
            "completed": result.completed,
            "used_unconfirmed_draft": result.used_unconfirmed_draft,
            "abort_reason": result.abort_reason[:120],
            "cost_usd": round(result.cost_usd, 4),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "elapsed_seconds": round(result.elapsed_seconds, 1),
            "rag_extraction_rate": result.rag_extraction_rate if result.rag_extraction_rate is not None else -1,
            "reference_images": result.reference_image_count,
            "has_requirements": bool(self._requirements),
            "has_target_model": bool(self._target_model),
            "lessons_used": getattr(self, "_lessons_used", 0),
            "examples_used": getattr(self, "_examples_used", 0),
        }

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

        # 生成時の指定（必須条件・対象モデル）をfrontmatterに残す。値は1行のJSON文字列にして、
        # コロンや改行を含んでもYAMLとして壊れないようにする。
        extra_frontmatter = ""
        if result.requirements:
            extra_frontmatter += "requirements: " + json.dumps(result.requirements.replace(chr(10), " "), ensure_ascii=False) + chr(10)
        if result.target_model:
            extra_frontmatter += "target_model: " + json.dumps(result.target_model, ensure_ascii=False) + chr(10)
        status_note = ""
        if not result.completed:
            status_note = (
                f"\n> **注意:** この生成は途中で打ち切られました（{result.abort_reason}）。"
                "ノード構成は未完成の可能性があります。\n"
            )
            if result.used_unconfirmed_draft:
                status_note += (
                    "> 以下の概要・手順は、モデルが見た目の最終確認（confirm_tutorial）を"
                    "行う前の下書きをそのまま使用しています。実際のノード構成と内容が"
                    "一致しているか、目視でご確認ください。\n"
                )

        # 2026-09-14追加: 打ち切り（result.completed=False）の場合はstatus: archivedにする。
        # scripts/auto_index.py（watchdog自動インデクサー）はarchivedを「スキップ
        # （インデックス化しない）」として扱うため、打ち切られた——本文に
        # 「> 注意: 打ち切られました」という警告バナーしか無い可能性がある——
        # チュートリアルがRAGナレッジベースに紛れ込むのを防げる。実機で、この
        # バナー付きのままstatus: activeで保存され、動画まで自動生成されてしまう
        # 事例が報告されたための対応（動画生成自体のガードはtutorial_view.py参照）。
        frontmatter_status = "active" if result.completed else "archived"
        return f"""---
title: {result.title}
namespace: tutorials
status: {frontmatter_status}
created: {today.isoformat()}
updated: {today.isoformat()}
expires: {expires.isoformat()}
tags: [houdini, ai-generated, {result.rag_name}]
difficulty: {result.level}
reference_images: {result.reference_image_count}
{extra_frontmatter}rag_indexed: false
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
*自動生成: model={self._model} / iterations={result.iterations} / cost=${result.cost_usd:.3f} / sandbox={result.sandbox_path}*
"""


# ─── レベルチェーン生成（IMPROVEMENT_PLAN.md Phase1） ─────────────────────────────

_LEVEL_CHAIN_ORDER: tuple[str, ...] = ("basic", "applied", "advanced")


def build_level_chain(
    topic: str,
    bridge_port: int = 8766,
    project_dir: str = "",
    rag_mode: str = "local",
    gas_url: str = "",
    gas_api_key: str = "",
    model: str = DEFAULT_MODEL,
    claude_backend: str = "gas",
    cf_url: str = "",
    cf_api_key: str = "",
    rag_namespace: str = "",
    reference_images: list[str] | None = None,
    requirements: str = "",
    target_model: str = "",
    progress_cb: Callable[[str], None] | None = None,
    executor_factory: Callable[..., HoudiniToolExecutor] | None = None,
    levels: tuple[str, ...] = _LEVEL_CHAIN_ORDER,
) -> list[tuple[TutorialAgent, TutorialResult]]:
    """
    同一トピックを basic→applied→advanced の順で逐次生成し、前段の
    finish_tutorial 出力（next_steps/pitfalls）の要約を次段のシステムプロンプト
    へ引き継ぐ（IMPROVEMENT_PLAN.md §Phase1）。

    レベルごとに新しい TutorialAgent インスタンスを作る。TutorialAgent.generate()
    は呼ぶたびに新しいサンドボックス（executor）を作る設計のため、同じインスタンスを
    使い回すと self.executor が最後のレベルのものだけに上書きされ、途中レベルの
    サンドボックスを個別に削除できなくなってしまう。戻り値に (agent, result) の
    ペアを含めているのはそのためで、呼び出し側（UI）は各レベルの
    agent.destroy_sandbox() を個別に呼べる。

    途中のレベルで例外が発生した場合はそこで打ち切り、それまでに得られた
    (agent, result) のリストを返す（呼び出し元で例外を再送出はしない —
    basic は成功したが advanced の生成中に接続が切れた、といったケースでも
    それまでの結果を無駄にしないため）。
    """
    results: list[tuple[TutorialAgent, TutorialResult]] = []
    prior_summary = ""
    for level in levels:
        agent = TutorialAgent(
            bridge_port=bridge_port,
            project_dir=project_dir,
            rag_mode=rag_mode,
            gas_url=gas_url,
            gas_api_key=gas_api_key,
            model=model,
            claude_backend=claude_backend,
            cf_url=cf_url,
            cf_api_key=cf_api_key,
            rag_namespace=rag_namespace,
            reference_images=reference_images,
            requirements=requirements,
            target_model=target_model,
            progress_cb=progress_cb,
            executor_factory=executor_factory,
        )
        try:
            result = agent.generate(topic, level=level, prior_level_summary=prior_summary)
        except Exception as exc:
            if progress_cb:
                progress_cb(f"レベルチェーン: {level} の生成に失敗したため打ち切ります: {exc}")
            break
        results.append((agent, result))
        prior_summary = TutorialAgent._summarize_for_next_level(result)
    return results
