# コンテンツ動的生成 — 設計ドキュメント

**ステータス:** 設計中（実装未着手）
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
| 状態 | 設計確定・実装着手前 | Phase 1 設計確定・実装着手前／Phase 2 ロードマップとして文書化 |

両者に共通する設計判断（モデル選定・コスト管理・検証フロー）は[4章](#4-共通の設計判断)にまとめる。

---

## 2. houdini21 — Houdiniチュートリアル自動生成

### 2.1 全体構成

```
Houdiniチャットパネル（rag_chatbot.py）に「チュートリアル生成」モード追加
  │
  ├─ ① RAG検索: houdini21 namespace から関連ドキュメント取得
  │
  ├─ ② エージェントループ（Claude Sonnet 4.6 + Tool Use）
  │     - houdini_tools.py（hou モジュールのラッパー）
  │     - サンドボックスサブネット内でのみノード操作
  │     - cookエラーを自己修正ループにフィードバック（最大25回）
  │     - プロンプトキャッシュ：システムプロンプト＋ツール定義＋RAGコンテキストを
  │       cache_control で固定し、繰り返しコストを抑制
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
| `finish_tutorial` | ループ終了シグナル |

`list_available_node_types`を入れている理由：Houdiniのノードタイプ名はバージョン依存の正確な文字列が必要で、Claudeが記憶だけで呼ぶと失敗しやすい。houdini21のRAGドキュメントと組み合わせて精度を上げる。

### 2.4 エージェントループ（疑似コード）

```python
sandbox = create_sandbox_subnet()  # /obj/ai_tutorial_<timestamp>　既存シーンを保護
rag_context = query_rag(namespace="houdini21", query=user_request)

messages = [system_prompt(rag_context, sandbox_path), user_request]
step_log = []

for i in range(MAX_ITER):  # 例: 25回
    response = anthropic.messages.create(
        model="claude-sonnet-4-6", tools=HOUDINI_TOOLS, messages=messages
    )
    if tool_use_blocks:
        for block in tool_use_blocks:
            result = execute_tool(block.name, block.input, sandbox)  # houdini_tools.py
            step_log.append({tool, input, result})
            messages.append(tool_result(block.id, result))
    elif finish_tutorial_called or text_only_response:
        break

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

### 2.6 サンドボックス化・安全設計

- ユーザーの既存シーンを壊さないよう、`/obj/ai_tutorial_<timestamp>` のような専用サブネット内でのみノード作成・操作を行う
- 生成完了後もサンドボックスは残す（ユーザーが結果を直接確認できるように）。明示的に「削除」操作をチャット上で選べるようにする
- 反復上限は25回（コスト・暴走防止）。超えたら「途中までの状態」を提示して打ち切り
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
| コスト上限 | 1回の生成が **$0.50 を超えたら自動打ち切り**、ユーザーに途中経過を提示 |
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

ツール呼び出しを伴うエージェントループには、単発チャット（現状Haiku使用）より高度な推論が必要なため **Claude Sonnet 4.6** を使用する。

### 4.2 コスト見積もり（houdini21の試算、参考値）

| 構成要素 | 概算トークン数 |
|---|---|
| システムプロンプト＋ツール定義8個 | 約1,300 |
| RAG検索コンテキスト（1トピック分） | 約2,000 |
| 1ツール呼び出し往復（Claude応答＋ツール結果） | 約250〜500 |

15ステップ程度の生成タスクで、**プロンプトキャッシュなしの場合は概算8万トークン・$0.25〜0.35/回**程度（Sonnet 4.6: $3/$15 per 1M tokens換算）。会話履歴を毎ターン再送する構造上、ステップ数に対してほぼ線形〜やや超線形に増える。

**プロンプトキャッシュ（`cache_control`）は必須。** 固定部分（システムプロンプト・ツール定義・RAGコンテキスト）をキャッシュすれば、2回目以降のターンはこの部分が約1/10のコストになる。体感3〜4割のコスト削減が見込めるが、実測での検証が必要。

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
