# コンテンツ動的生成 — 設計ドキュメント

**ステータス:** houdini21は実装済み・実機検証済み（2026-07-23、[検証レポート](houdini21-tutorial-gen-report.md)）／BrainTQは設計中（実装未着手）
**更新日:** 2026-06-30

> LocalRAG／CloudRAGを使ったチャットボット機能の次段階として、RAGで取得した知識をもとに**コンテンツを動的に生成**する機能群。houdini21（Houdiniチュートリアル自動生成）とBrainTQ（ミニゲーム動的生成）の2つを「コンテンツ動的生成」という1つのトピックにまとめて扱う。アーキテクチャ・セットアップは [docs/local-rag.md](local-rag.md) / [docs/cloud-rag.md](cloud-rag.md) を前提とする。

---

## 目次

1. [概要](#1-概要)
2. [houdini21 — Houdiniチュートリアル自動生成](#2-houdini21--houdiniチュートリアル自動生成)
   - 2.7. [Goal・完成条件・委任範囲](#27-goal完成条件委任範囲)
3. [BrainTQ — ミニゲーム動的生成](#3-braintq--ミニゲーム動的生成)（Phase 1 設計確定 / Phase 2 ロードマップ）
4. [共通の設計判断](#4-共通の設計判断)
5. [権利・ライセンスの取り扱い](#5-権利ライセンスの取り扱い)

---

## 1. 概要

これまでのRAGチャットボットは「質問 → 検索 → 回答」の1往復で完結していた。コンテンツ動的生成はこれを発展させ、RAGで取得した知識をもとに**LLMが実際にツールを操作しながら検証済みの成果物を作る**エージェントループに踏み込む。

| | houdini21 | BrainTQ |
|---|---|---|
| 生成対象 | Houdiniノードグラフ＋ステップバイステップのチュートリアル | Phase 1: 既存ミニゲーム向け問題コンテンツ／Phase 2: ミニゲームのScript・Prefab・GameControl.cs分岐 |
| 操作対象 | Houdini（`hou`モジュール） | Phase 1: なし（データ生成のみ）／Phase 2: Unity Editor |
| 検証手段 | cookエラーの自己修正ループ | Phase 1: スキーマ・範囲・重複バリデーション／Phase 2: 未構築（自動テスト基盤が現状ゼロ） |
| 状態 | 実装済み・実機検証済み（Local/Cloud RAG両対応） | Phase 1 設計確定・実装着手前／Phase 2 ロードマップとして文書化 |

両者に共通する設計判断（モデル選定・コスト管理・検証フロー）は[4章](#4-共通の設計判断)にまとめる。

---

## 2. houdini21 — Houdiniチュートリアル自動生成

> 実装・実機検証は完了済み。Cloud RAG対応の経緯とHoudini実機での検証結果は [houdini21-tutorial-gen-report.md](houdini21-tutorial-gen-report.md)（技術資料・mermaid図解付き／[HTML版](houdini21-tutorial-gen-report.html)）、講義資料は [lecture/houdini21-tutorial-gen-lecture.html](../lecture/houdini21-tutorial-gen-lecture.html) を参照。

### 2.1 全体構成

```
Houdiniチャットパネル（rag_chatbot.py）に「チュートリアル生成」モード追加
  │
  ├─ ① RAG検索: houdini21 namespace から関連ドキュメント取得
  │     Settingsタブのモード設定に従い取得先を切り替える:
  │       - local: rag_local_bridge.py の /search
  │       - cloud: gas_cloud_rag.js を mode:'raw' 呼び出し
  │                （最終回答生成をスキップし検索結果のみ取得）
  │     いずれのモードでも取得後に db=="houdini21" 以外を除外し、
  │     ホワイトリスト方針をクライアント側でも強制する
  │
  ├─ ② エージェントループ（MODEL定数のClaudeモデル + Tool Use）
  │     - houdini_tools.py（hou モジュールのラッパー）
  │     - サンドボックスサブネット内でのみノード操作
  │     - cookエラーを自己修正ループにフィードバック（最大MAX_ITERATIONS回）
  │     - プロンプトキャッシュ：システムプロンプト＋ツール定義＋RAGコンテキストを
  │       cache_control で固定し、繰り返しコストを抑制
  │     - Claude API呼び出しは必ず gas_cloud_rag.js 経由（action:'claude_messages'）。
  │       Houdiniクライアントは生のANTHROPIC_API_KEYを持たず、GAS側がAPIキーごとの
  │       Claude専用トークン予算（claudeCapacity/claudeBalance）を強制する。
  │       rag_mode="local"でもこの呼び出し自体はCloud（GAS）経由（docs/cloud-rag.md §8.14）
  │
  ├─ ③ 生成完了後、ノード構成を NodeGraphAsset 形式の JSON にエクスポート
  │     （hou.node()を辿ってnodes/edges/params/positionを抽出）
  │
  ├─ ④ チャット上でMarkdownチュートリアルをプレビュー → ユーザーが保存確認
  │
  └─ ⑤ 保存先：
        localRAG/tutorials/<slug>_<date>.md   （チュートリアル本文）
        localRAG/tutorials/<slug>_<date>.json （ノードグラフ、可視化用）
```

### 2.2 新規コンポーネント

| ファイル | 役割 |
|---|---|
| `houdini/python_panels/houdini_tools.py` | `hou`モジュールのラッパー。`create_node`・`set_parameter`・`connect_nodes`・`cook_node`（エラー検知）・`delete_node`・`list_available_node_types`・`get_node_info`・`finish_tutorial`をAnthropic tool-use形式のスキーマで定義 |
| `houdini/python_panels/tutorial_agent.py` | RAG検索→エージェントループ→Markdown保存のオーケストレーター |
| `rag_chatbot.py`への追加 | 「チュートリアル生成」モード／`/tutorial`コマンド。進行状況（どのツールを呼んでいるか）をリアルタイム表示 |
| ノードグラフJSONエクスポーター | 完成したノード構成を NodeGraphAsset 互換のJSONへ変換 |
| Houdiniパネルの「過去のチュートリアル」タブ | 保存済みチュートリアルの一覧 → 選択するとノードグラフを`QGraphicsView`で表示 |
| `houdini/python_panels/token_usage.py` | チュートリアル生成の累積トークン消費量を`logs/houdini_token_usage.jsonl`に永続化し、Tutorialタブ上部に「残量ドーナツゲージ」（`QPainter`直描画）として可視化。予算はSettingsタブの「トークン予算」で変更可能（既定500,000トークン） |

### 2.3 ツールスキーマ（houdini_tools.py）

| ツール | 役割 |
|---|---|
| `create_node` | サンドボックス内にノード作成 |
| `set_parameter` | パラメータ設定 |
| `connect_nodes` | ノード間接続 |
| `cook_node` | 実行してエラー/警告を取得（自己修正の起点） |
| `list_available_node_types` | 正確なノードタイプ名を検索（Claudeの記憶違い防止。例: `mountain` vs `mountain::2.0`） |
| `get_node_info` | 既存ノードの状態確認 |
| `delete_node` | クリーンアップ用 |
| `finish_tutorial` | 完了案の下書きを提出（即確定はしない。`sources_used`でRAG参考ソース番号も報告。`next_steps`で応用・発展アイデアを3〜5個報告 — 手順の要約に終始せず「自分のプロジェクトでどう使えるか」の手がかりを持たせるための追加、実機で生成物が「概要と手順しかなくロードマップとして弱い」と指摘されたための対応） |
| `confirm_tutorial` | `finish_tutorial`直後に送られるビューポート画像を確認したうえで、`looks_correct=true`なら完了確定・`false`なら`finish_tutorial`からやり直し |

`list_available_node_types`を入れている理由：Houdiniのノードタイプ名はバージョン依存の正確な文字列が必要で、Claudeが記憶だけで呼ぶと失敗しやすい。houdini21のRAGドキュメントと組み合わせて精度を上げる。実機検証で反復予算の30%超をこのツールの呼び出しが消費していたことが分かったため（[検証レポート](houdini21-tutorial-gen-report.md)）、システムプロンプトに頻出ノードタイプ一覧を埋め込み（プロンプトキャッシュされるため追加コストはほぼ無い）、既知のタイプ名については毎回の確認を不要にしている（`tutorial_agent.py`の`_COMMON_NODE_TYPES_BLOCK`）。

**完了フロー（視覚的自己検証）：** `finish_tutorial`は呼ばれた時点では下書き（`pending_finish`）として保持されるだけで、`TutorialResult`は確定しない。その回のtool_resultにビューポートのスクリーンショットが画像コンテンツブロックとして添付され（`houdini_tools.py`の`_capture_finish_screenshot`→`tutorial_agent.py`の`_run_loop`）、Claude自身が見た目を確認してから`confirm_tutorial(looks_correct=true)`を呼ぶことで初めて完了が確定する（`looks_correct=false`なら`pending_finish`はクリアされ、`finish_tutorial`からやり直しになる）。

**RAGソース帰属：** `finish_tutorial`の`sources_used`（実際に参考にしたソース番号の配列）を、生成完了後に`_apply_rag_attribution`が`result.sources`の各エントリの`cited`フラグと`result.rag_extraction_rate`（引用率）に変換し、生成Markdownの「## 参考」節に「✅ 引用済み / ⬜ 未引用」として表示する。Cloud RAGチャットの`parseExtractionRate_()`と同じ考え方のHoudini生成版で、RAGがチュートリアル生成にどれだけ実際に寄与したかを示す研究データとして使う。`_apply_rag_attribution`は`completed`（`finish_tutorial`まで到達したか）も受け取り、打ち切り時は`sources_used`自体が一度もモデルに尋ねられていないため`rag_extraction_rate`を`None`のまま据え置く。「引用0/N件」と「未計測」を区別しないと、実際には評価していないのに"モデルが検討した末に1件も使わなかった"ように誤読される（実機で確認済みの混乱）。

### 2.4 エージェントループ（疑似コード）

```python
sandbox = create_sandbox_subnet()  # /obj/ai_tutorial_<timestamp>　既存シーンを保護
rag_context = query_rag(namespace="houdini21", query=user_request)

messages = [system_prompt(rag_context, sandbox_path), user_request]
step_log = []

for i in range(MAX_ITER):  # 40回
    response = anthropic.messages.create(
        model="claude-sonnet-5", tools=HOUDINI_TOOLS, messages=messages
    )
    if tool_use_blocks:
        for block in tool_use_blocks:
            result = execute_tool(block.name, block.input, sandbox)  # houdini_tools.py
            step_log.append({tool, input, result})
            if block.name == "finish_tutorial" and executor.last_screenshot_b64:
                result = [text_block(result), image_block(executor.last_screenshot_b64)]  # 視覚的自己検証
            messages.append(tool_result(block.id, result))
        if near_iteration_or_cost_limit() and not grace_warned and still_in_progress():
            messages[-1].content.append(text_block(GRACE_NUDGE_TEXT))  # グレースフル終了
    elif text_only_response:
        break
    if executor.finish_data is not None:  # confirm_tutorial(looks_correct=true)で確定
        break

apply_rag_attribution(finish_data, result)  # sources_used → cited/引用率
tutorial_md = assemble_markdown(step_log, claude_explanation, rag_sources)
show_preview_in_chat(tutorial_md)  # ユーザーが「保存」を押したら localRAG/tutorials/ へ
node_graph_json = export_node_graph(sandbox)  # NodeGraphAsset形式
```

### 2.5 ノードグラフビュー

`Node-Management`（`GameDevelopment\Graduation\Node-Management`、Blenderノードグラフの保存・可視化ツール）の設計を転用する。

| Node-Management（Blender） | Houdini版への転用 |
|---|---|
| `types/nodeGraph.ts`のNodeGraphAsset（nodes/edges/params/position） | ほぼそのままHoudini版スキーマとして使う（`kind`=`node.type().name()`、`params`=`node.parms()`） |
| `blender-addon/exporter.py`（手動でクリップボードエクスポート） | `tutorial_agent.py`が生成完了後に自動でJSON化（手動操作不要） |
| `GraphViewer.tsx`（React Flow、color_tagでヘッダー色分け） | Houdiniパネル（PySide6）の新タブで`QGraphicsView`を使い、同じ配色思想で実装（既存の`graph_view.py`が文書関係グラフで`QGraphicsView`を使っているため実装パターンを流用可能） |
| SQLite + Webアプリ | 不要。生成のたびに`localRAG/tutorials/<slug>_<date>.json`として保存するだけで十分 |

**Cloud RAG対応（Graphタブ）：** `graph_view.py`の`GraphFetchWorker`はRAGモード（local/cloud）を見て、cloudの場合は`gas_cloud_rag.js`の`action:'graph'`エンドポイント（新規追加、`validateApiKey_`→`isRateLimited_`→`buildGraphData_`の標準パターン）へPOSTする。従来のlocal RAGブリッジへのGETのみに固定されていた制約を解消し、Cloud RAG使用時でも文書関係グラフが表示できるようになった。

**グラフレイアウトの不具合修正（実機で確認）：** Cloud RAGの`buildGraphData_`（gas_cloud_rag.js）はノードにx/y座標を付与せずに返す設計だったため、`RAGGraphScene.build()`の`nd.get("x", 0.5)`フォールバックにより全ノードが`(0.5, 0.5)`の同一点に重なって表示されていた（「グラフビューのレイアウトがひどい」として報告）。`graph_view.py`にクライアント側の`_spring_layout()`（`rag_graph_export.py`のLocal RAG用アルゴリズムをPython側に移植）を追加し、x/yが1つでも欠けていればレイアウトを計算して補うようにした。Local RAG（常にx/yを提供）の既存動作は変わらない。

**接続状態ランプ：** Cloud（GAS URL）/ Local（ブリッジ`/health`）への疎通を色（緑=OK/赤=接続なし/黄=確認中）とテキストで表示するランプ。当初はTutorialタブの中だけに表示していたが、他のタブを開いていると確認できず不親切なため、`rag_chatbot.py`側で`QTabWidget.setCornerWidget()`を使いタブバーの右端に移動し、どのタブを操作していても常時表示されるようにした（`_ConnectionLamp`/`_ConnectionCheckWorker`）。バックグラウンドスレッドで20秒ごとに自動再確認し、モード切替・設定保存・チュートリアル生成失敗の直後にも即時再確認する。

**Historyタブのグラフ・テキスト表示改善：** 生成されたHoudiniノードグラフ（数十〜200ノード規模）がそのままだと見づらい問題に対応するため、`tutorial_graph_simplify.py`（Qt非依存の純粋関数）で「線形ノード（分岐/合流せず、他ノードのparentでもないノード）の連鎖」を1つの集約ノードに折り畳む簡易表示アルゴリズムを実装し、ノード数30超では自動的に簡易表示（`tutorial_view.py`の「簡易/詳細」切り替え）を選ぶ。「Mermaidとしてコピー」ボタンで`graph_to_mermaid()`によるMermaid記法への変換・クリップボード出力もできる。生成テキスト側（Markdown表示）もフォント・行間・見出し等のスタイリングを追加して可読性を上げた（Markdown構造自体は変更なし）。

### 2.6 サンドボックス化・安全設計

- ユーザーの既存シーンを壊さないよう、`/obj/ai_tutorial_<timestamp>` のような専用サブネット内でのみノード作成・操作を行う
- 生成完了後もサンドボックスは残す（ユーザーが結果を直接確認できるように）。明示的に「削除」操作をチャット上で選べるようにする
- 反復上限は40回（コスト・暴走防止）。超えたら「途中までの状態」を提示して打ち切り（初期値25回だったが、実機検証で反復消費が想定より多いタスクがあったため40回に調整。経緯は[検証レポート](houdini21-tutorial-gen-report.md) §4参照）
- **打ち切り時のグレースフル終了：** 反復上限の残り3回以内、またはコスト上限の85%を超えた時点（`GRACE_ITERATIONS`/`GRACE_COST_FRACTION`、`tutorial_agent.py`）で、まだ`finish_tutorial`/`confirm_tutorial`が済んでいなければ「今の状態のまま仕上げてください」という一度だけのシステム通知（`_GRACE_NUDGE_TEXT`）を差し込む。ハード打ち切りで未完成のまま終わる代わりに、多少粗くても完結したチュートリアルになる可能性を上げる
- **シミュレーションノードの複数フレームcook：** pyro/DOP/cloth/particle/flip/RBD等のノードタイプ名（`_SIMULATION_TYPE_HINTS`、部分文字列マッチ）を検出した場合、`cook_node`は単一フレームではなく現在フレームから10フレーム分（`_SIM_COOK_FRAME_COUNT`）を順次evaluateしてから復元する（`houdini_tools.py`の`_cook_simulation_frames`）。シミュレーションは前フレームの結果に依存するため、時間発展する挙動を1フレームだけでは検証できないことへの対応
- **検索連打・空振り終了対策（実機で確認された不具合）：** `list_available_node_types`を3回以上連続で呼んでも`create_node`を呼ばない場合、一度だけ「検索を止めて作成を試して」と促す（`_SEARCH_LOOP_NUDGE_TEXT`、`create_node`が呼ばれるとストリークが解除され再度検索連打があれば再度促す）。また、ノードを1つも作らずに`tool_use`無しのテキストのみで終了しようとした場合も、即座に打ち切る前に一度だけ「作業を始めてください」と再開を促す（`_EMPTY_HANDED_NUDGE_TEXT`）。電子パーティクル等のPOP/DOP系トピックで検索が過剰発生していたため、`_COMMON_NODE_TYPES_BLOCK`にPOPノード（popforce/popdrag/popwrangle等）も追加した
- **サンドボックス削除時のHoudiniフリーズ対策：** `HoudiniToolExecutor.destroy_sandbox()`は`hdefereval.executeInMainThreadWithResult()`でメインスレッドへディスパッチする実装だが、「サンドボックス削除」ボタンのクリックハンドラ（既にメインスレッド）から直接呼ぶと自分自身へのディスパッチ待ちでデッドロックしてHoudiniが固まる（実機で確認済み）。`tutorial_view.py`の`_on_delete_sandbox`を`_DestroySandboxWorker`（QThread）経由の呼び出しに変更して解消
- 保存先ファイル名は `localRAG/tutorials/<slug>_<日付>.md`

### 2.7 Goal・完成条件・委任範囲

#### Goal（何ができたら完成か）

ユーザーの自然言語リクエストから、Houdiniのノードグラフを実際に組み立て、cookエラーのない状態のチュートリアル（Markdown + ノードグラフJSON）が自動生成される。

#### 完成の条件

| 項目 | 基準 |
|------|------|
| 成功率 | パイロット3〜5トピック（難易度違い）で **80%以上**が反復上限（25回）内に cookエラーなしで収束 |
| 成果物形式 | `localRAG/tutorials/<slug>_<date>.md` ＋ 同名 `.json`（NodeGraphAsset形式）のペアが必ず生成される |
| プレビュー | チャット上でMarkdownがプレビューされ、ユーザーが明示的に「保存」を押すまでファイル書き込みしない |
| 安全性 | 生成過程で `/obj/ai_tutorial_<timestamp>` 以外のノードに一切触れていないことをログで確認できる |
| コスト上限 | 1回の生成が **$5.00 を超えたら自動打ち切り**（ローカル側フェイルセーフ。実際の利用上限はGAS側の`claudeCapacity`が唯一の正で、管理画面から調整する）、ユーザーに途中経過を提示 |
| 知識還流 | 生成物が `localRAG/` 配下に置かれ watchdog が自動インデックス化することを確認済み |

#### 委任範囲

| 判断 | 実装担当の裁量 |
|------|-----------------|
| `houdini_tools.py` のツール実装・プロンプト設計 | 任せてよい |
| 反復上限・サンドボックス命名規則などの実装細部 | 任せてよい（本章の設計方針内） |
| モデル変更（Sonnet→Opus等）の**提案**まで | 任せてよい（実測データを揃えて提案） |
| モデル変更の**実行**（コストが変わる） | 要確認 |
| サンドボックス外のノード・既存シーンに触れる変更 | 絶対不可。設計上の制約であり、逸脱時は即報告 |
| 生成コンテンツを商用配布物に含める判断 | 要確認（[5章](#5-権利ライセンスの取り扱い)の権利問題に直結） |
| houdini21DB（RAGコーパス）への新規ドキュメント追加 | 要確認（出典検証が必要なため。詳細は[5章](#5-権利ライセンスの取り扱い)） |

---

## 3. BrainTQ — ミニゲーム動的生成

**対象リポジトリ:** `GameDevelopment\Enterprises\AXTechCare\BrainTQ_Chatbot\Assets\Scripts`
**BrainTQの正体:** 自社（AXTechCare）の脳トレ・認知トレーニングアプリ。Gemini Live APIによる音声相談チャットボット（TIPI-J/HHIE-S/MMSE等の医療系認知スクリーニングを実施）とミニゲーム群で構成される。

### 3.1 既存コードベース調査結果（設計の前提）

houdini21と同じ「LLMがツールを呼んでゼロから成果物を組み立てる」モデルをそのまま適用することは**現実的ではない**。実際のコードを精査した結果、以下の制約が判明した。

| 観点 | 調査結果 |
|---|---|
| ミニゲーム数 | 約150個のC#スクリプト |
| 基底クラスの一貫性 | `MiniGameBaseClass`（タイマー・一時停止・結果表示の共通フレームワーク）を継承しているのは150個中**14個のみ**。大半は同じパターンを手書きで再実装した独立`MonoBehaviour` |
| オーケストレーター | `GameControl.cs`（1653行）が`switch(gameID)`の巨大分岐でプレハブをInstantiate。`InGameControl.cs`（4705行）が全ゲーム共通UI（タイマー・結果画面・コイン報酬・脳年齢計算等）を一元管理 |
| プレハブ依存 | 各ミニゲームはUnity Editorで手作業ワイヤリングされた専用プレハブが必須。`[SerializeField]`参照（ボタン・スプライト・プレハブスロット等）は設計時バインドであり、**コードだけでは動くゲームにならない** |
| コンテンツ生成方式 | 調査対象（`CalculateFormulaControl.cs`）は問題を**完全に手続き的（ランダム生成）**に作っており、外部データを読み込む仕組みが存在しない |
| チャット連携 | チャットボット（`ChatBotControler.cs`等）とミニゲームシステムは完全に独立しており、両者を繋ぐ仕組みは一切存在しない |
| 自動テスト | ゼロ。NUnit/PlayModeテストは存在せず、品質保証は完全に人手のプレイテスト |
| 設計ドキュメント | プロジェクトルートやAssets配下にREADME・設計ドキュメントは存在しない |

これらの制約から、**2段階のロードマップ**として設計する。

### 3.2 Phase 1（着手対象）— コンテンツ生成パイプラインの実証

ミニゲームの「機構」そのものではなく、**既存テンプレートに流し込む「問題コンテンツ」をRAGで動的生成する**ことに絞る。スクリプト生成もプレハブ生成も不要なため、houdini21より大幅に小さいスコープで実装できる。

```
① パイロット対象の選定: Calculation（計算力）系ゲームを対象とする
   （CalculateControl.cs / CalculateFormulaControl.cs の構造を調査済み）

② 外部コンテンツ注入口の追加（最小限のコード改修）
   CalculateFormulaControl.Init() は現状ランダム生成のみ。
   List<CalculateControl.CalculateQuestion> を受け取るオーバーロードを追加し、
   外部コンテンツがあればそれを使用、なければ従来のランダム生成にフォールバック

③ RAG検索 → コンテンツ生成
   RAG検索（AXTechCareの文脈・トピック指定、例:「認知症予防に関連した計算問題」）
   → Claudeが CalculateQuestion 互換のJSON（choices[] / correctChoiceIndex）を構造化生成
   → バリデーション（数値範囲・難易度・重複チェック）
   → コンテンツパックJSONとして保存

④ Unity側がコンテンツパックJSONを読み込んでプレイ
```

この段階では **GameControl.cs の分岐にもプレハブにも触れない**。RAG→コンテンツ→Unityというパイプライン自体の実証が目的。

### 3.3 Phase 2（将来目標）— フルミニゲーム生成

Script・Prefabの型・`GameControl.cs`の分岐追加までを自然言語指定とドキュメントから自動生成する最終形。Phase 1の実証を経てから着手する。

| 要素 | 内容 |
|---|---|
| **ミニゲームDocumentマニュアル** | `MiniGameBaseClass`の契約（`SetInGameControl`/`StartGame`/イベントフック）・`InGameControl`が提供するAPI・`GameType`8分類（記憶力/計算力/空間認識/言語能力/予知処理/論理思考/集中力/視覚認識）・`GameDetails`登録形式・`GameControl.cs`の分岐パターンを整理し、RAG資産として整備する。これがhoudini21における houdini21DB（Notion RAGドキュメント）に相当する役割を持つ |
| **Script生成** | 規約に沿った新規C#スクリプトをLLMが生成。`MiniGameBaseClass`継承を必須として強制し、150個中14個しか使っていない一貫性のないパターンを新規生成では踏襲させない方針とする |
| **Prefab生成（最大の技術的障壁）** | Unityプレハブは手作業ワイヤリング前提であり、YAMLを直接生成させるのは非現実的。2つの方向性を検討： (a) 再利用可能なUIプリミティブ（ボタングリッド・タイマースライダー・テキスト表示等）のライブラリを用意し、実行時に手続き的に組み立てる方式（既存パターンからの逸脱が大きい） (b) Unity Editor拡張をLLMがツール呼び出しで操作し、GameObject階層を構築してプレハブとして保存する方式（Houdiniの`hou`モジュール操作と同型のアーキテクチャ） |
| **GameControl.cs分岐追加** | `switch(gameID)`への新規case追加＋`AllGames`静的リストへの`GameDetails`エントリ登録。スコープが明確な機械的改修であり、houdini21の`create_node`のような独立ツールとして実装しやすい |
| **検証基盤（現状ゼロから構築）** | 自動テストが存在しないため、houdini21の`cook_node`に相当する自己修正ループの土台がない。Unity Editorバッチモードでのコンパイルチェック＋生成プレハブをInstantiateして例外なく動作するか確認する簡易PlayModeテストを新規構築する必要がある |

### 3.4 Phase 1 → Phase 2 の橋渡し

Phase 1で構築する「RAG検索→構造化コンテンツ生成→バリデーション」のパイプラインは、Phase 2でもそのまま再利用できる（Script/Prefab生成の入力として使う問題コンテンツの生成自体は変わらないため）。また、Phase 1の改修作業（既存ゲームの構造を読み解き、外部注入口を設計する過程）そのものが、3.3の「ミニゲームDocumentマニュアル」の最初の素材になる。

---

## 4. 共通の設計判断

### 4.1 モデル選定

ツール呼び出しを伴うエージェントループには、単発チャット（現状Haiku使用）より高度な推論が必要なため **Claude Sonnet 5**（`tutorial_agent.py`の`MODEL`定数）を使用する。

### 4.2 コスト見積もり（houdini21の試算、参考値）

| 構成要素 | 概算トークン数 |
|---|---|
| システムプロンプト＋ツール定義8個 | 約1,300 |
| RAG検索コンテキスト（1トピック分） | 約2,000 |
| 1ツール呼び出し往復（Claude応答＋ツール結果） | 約250〜500 |

15ステップ程度の生成タスクで、**プロンプトキャッシュなしの場合は概算8万トークン・$0.25〜0.35/回**程度（Sonnet 4.6: $3/$15 per 1M tokens換算）。会話履歴を毎ターン再送する構造上、ステップ数に対してほぼ線形〜やや超線形に増える。

**プロンプトキャッシュ（`cache_control`）は必須。** 固定部分（システムプロンプト・ツール定義・RAGコンテキスト）をキャッシュすれば、2回目以降のターンはこの部分が約1/10のコストになる。

> **2026-08-08 追記（実機で1生成$3超を確認）：** 上記の「固定部分だけキャッシュ」では、反復のたびに伸びていく**会話履歴そのもの**（ツール結果・アシスタント応答の蓄積）が毎ターン通常入力価格（$3/M）で再送信され続けることを見落としていた。固定部分（〜数千トークン）に対して会話履歴は反復数に比例して数万トークンまで伸びるため、実質的にはコストの大半がキャッシュされていなかったことになる（1生成あたり反復回数のほぼ2乗でコストが増える構造）。`tutorial_agent.py`の`_run_loop`で、直前のターンまでの会話の末尾に`cache_control`を付け直す「ローリングキャッシュ」（Anthropicの4breakpoint制限内に収まるよう、古い位置のマーカーは毎ターン外す）を追加し、会話履歴もキャッシュ読み込み価格で再利用できるようにした。長い生成ほど削減効果は大きくなるはずだが、実測での検証が必要。

> 上記はいずれも設計段階の見積もりであり、実測値ではない。実装後にパイロット実行で検証すること（[4.3](#43-検証フロー)参照）。

### 4.3 検証フロー

実装が一通り動いたら、難易度の異なる2〜3個の生成タスクでパイロット実行し、以下を同時に確認する：

1. **トークン消費の実測値**（見積もりとの乖離を確認）
2. **生成品質**（houdini21の場合：ノードグラフが実際に正しく動くか／cookエラーなく完成するか）
3. **自己修正ループの収束性**（cookエラーから何往復で収束するか。収束しないと反復上限に張り付いてコストだけ膨らむ）

この検証結果をもとに、モデル選定（Sonnet継続 or Opus検討）・反復上限・プロンプト設計を再調整する。

### 4.4 保存先と知識ベースへの還流

生成された成果物（houdini21のチュートリアル等）は`localRAG/`配下に保存することで、watchdogによる自動インデックス化の対象になる。つまり**生成したコンテンツがそのまま将来のRAG検索資産になる**という自己拡張するフィードバックループを持つ。BrainTQの設計でも同様の還流構造を検討する。

---

## 5. 権利・ライセンスの取り扱い

RAG機能自体の商用展開（Cloud RAGのチーム外提供等）に伴うライセンスリスクが、コンテンツ生成機能の**生成物**に混入しないよう、発生源で遮断する設計方針を取る。

**要点（詳細は [docs/license-compliance.md](license-compliance.md) 参照）:**

- RAGコーパスのうち生成機能から参照してよい namespace をホワイトリスト化する（houdini21DBは出典棚卸し後にのみ許可、`tool_docs`/`research`等の一般namespaceは生成機能からは参照しない）
- 生成直前に RAG チャンクとの n-gram 一致率チェックを行い、出典からの逐語コピーが混入していないか機械的に検証する
- 生成物（チュートリアル・ノードグラフ・ミニゲームコンテンツ）の著作権は生成を実行した顧客に帰属する方針とし、利用規約に明記する
- houdini21DBのように外部ツールの公式ドキュメントに由来しうるコーパスは、コピーではなく独自の要約・説明になっているか一度棚卸しする

houdini21DB（§2章の生成機能が参照するRAGコーパス）への新規ドキュメント追加が「要確認」（[2.7](#27-goal完成条件委任範囲)）とされているのは、この出典検証が理由である。
