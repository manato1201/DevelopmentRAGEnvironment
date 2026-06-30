# コンテンツ動的生成 — 設計ドキュメント

**ステータス:** 設計中（実装未着手）
**更新日:** 2026-06-30

> LocalRAG／CloudRAGを使ったチャットボット機能の次段階として、RAGで取得した知識をもとに**コンテンツを動的に生成**する機能群。houdini21（Houdiniチュートリアル自動生成）とBrainTQ（ミニゲーム動的生成）の2つを「コンテンツ動的生成」という1つのトピックにまとめて扱う。アーキテクチャ・セットアップは [docs/local-rag.md](local-rag.md) / [docs/cloud-rag.md](cloud-rag.md) を前提とする。

---

## 目次

1. [概要](#1-概要)
2. [houdini21 — Houdiniチュートリアル自動生成](#2-houdini21--houdiniチュートリアル自動生成)
3. [BrainTQ — ミニゲーム動的生成](#3-braintq--ミニゲーム動的生成)（設計中）
4. [共通の設計判断](#4-共通の設計判断)

---

## 1. 概要

これまでのRAGチャットボットは「質問 → 検索 → 回答」の1往復で完結していた。コンテンツ動的生成はこれを発展させ、RAGで取得した知識をもとに**LLMが実際にツールを操作しながら検証済みの成果物を作る**エージェントループに踏み込む。

| | houdini21 | BrainTQ |
|---|---|---|
| 生成対象 | Houdiniノードグラフ＋ステップバイステップのチュートリアル | ミニゲーム（詳細は設計中） |
| 操作対象 | Houdini（`hou`モジュール） | 未定 |
| 検証手段 | cookエラーの自己修正ループ | 未定 |
| 状態 | 設計確定・実装着手前 | 設計開始前 |

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

---

## 3. BrainTQ — ミニゲーム動的生成（設計中）

未着手。houdini21の設計が確定し次第、同様の形式で詰める。

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
