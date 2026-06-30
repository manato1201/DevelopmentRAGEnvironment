# 用語・技術解説ドキュメント

このプロジェクト（DevelopmentRAGEnvironment）で使用するすべての概念・用語を網羅した解説集。  
RAGシステム、セキュリティモデル、Houdini技術、Unity連携、インフラに分類して記述する。

---

## 目次

1. [RAGシステム基礎](#1-ragシステム基礎)
2. [ベクトル検索とインデックス](#2-ベクトル検索とインデックス)
3. [LLM連携](#3-llm連携)
4. [セキュリティ・認証モデル](#4-セキュリティ認証モデル)
5. [NISTフレームワーク](#5-nistフレームワーク)
6. [Cloud RAG（GAS+Gemini）](#6-cloud-raggas--gemini)
7. [Local RAG（ChromaDB+BM25）](#7-local-ragchromadb--bm25)
8. [監査ログと監視](#8-監査ログと監視)
9. [Houdini技術用語](#9-houdini技術用語)
10. [Unity連携用語](#10-unity連携用語)
11. [プロジェクト固有のコンポーネント](#11-プロジェクト固有のコンポーネント)
12. [インフラ・環境](#12-インフラ環境)

---

## 1. RAGシステム基礎

### RAG (Retrieval-Augmented Generation)
**検索拡張生成**。LLM（大規模言語モデル）の回答生成前に外部知識ベースから関連文書を検索し、そのコンテキストをプロンプトに注入する技術。  
- **利点**: モデルのパラメータに含まれない最新・専門知識を活用できる
- **本プロジェクト**: ゲーム開発知識（Houdini・Unity）に特化した二層RAGを構築

### 二層RAGアーキテクチャ
本プロジェクト固有の設計：
```
Layer 1: Cloud RAG  → GAS + Gemini + Notionデータベース
Layer 2: Local RAG  → ChromaDB + BM25 + Claude/Gemini API
```
- Cloud RAGは軽量・即応性・Notionとの統合を重視
- Local RAGはプライバシー・細粒度検索・ハイブリッド融合を重視

### チャンク (Chunk)
長文ドキュメントをRAGで扱うために分割した断片。適切なサイズが重要：
- 小さすぎる：文脈が失われる
- 大きすぎる：LLMのコンテキスト上限を圧迫、関連性が薄まる
- 本プロジェクト：`chunk_by_headings()`で見出し単位分割 / `SemanticChunker`でトークン数制御（512トークン/64オーバーラップ）

### エンベディング (Embedding)
テキストを高次元ベクトルに変換したもの。意味的に近いテキストは距離が近くなる。  
- 本プロジェクト（Local RAG）: ChromaDBのデフォルトエンベディング（Sentence-Transformers）

### コンテキストウィンドウ
LLMが一度に処理できるトークン数の上限。RAGはここにチャンクを詰め込む。  
- claude-haiku-4-5-20251001: 200K tokens
- gemini-2.5-flash: 1M tokens

---

## 2. ベクトル検索とインデックス

### ChromaDB
オープンソースのベクトルデータベース。SQLite上に構築されており、ローカルファイルシステムに永続化できる。  
- コレクション単位でインデックスを管理
- 本プロジェクトでは `data/chroma/` 以下に格納

### BM25 (Best Match 25)
TF-IDFを改良した古典的なキーワード検索アルゴリズム。ベクトル検索では拾えない完全一致・専門用語・固有名詞に強い。  
- `rank_bm25` ライブラリを使用

### ハイブリッド検索
ベクトル検索（意味的類似度）とBM25（キーワードマッチ）を組み合わせた検索手法。

### RRF (Reciprocal Rank Fusion)
複数の検索結果ランキングを統合する手法：  
```
score(d) = Σ 1 / (k + rank_i(d))
```
- k=60（定数）でランクの影響を平滑化
- 本プロジェクトでは ChromaDB + BM25 の結果をRRFで融合

### Namespace
検索スコープを制限する名前空間。本プロジェクトの定義：
| Namespace | 内容 |
|---|---|
| `tool_docs` | Houdini/Unity公式ドキュメント |
| `game_info` | ゲームデザイン・仕様情報 |
| `research` | 技術調査メモ・論文 |
| `team_notes` | チーム共有ノート |
| `personal_notes` | 個人メモ |

---

## 3. LLM連携

### Claude (Anthropic)
本プロジェクトのデフォルトLLM。Local RAGで使用。  
- モデル: `claude-haiku-4-5-20251001`（軽量・高速）
- API Key: 環境変数 `ANTHROPIC_API_KEY`

### Gemini (Google)
Cloud RAGのLLM。Local RAGでも切り替え可能。  
- モデル: `gemini-2.5-flash`
- API Key: 環境変数 `GEMINI_API_KEY`
- ライブラリ: `google.generativeai`

### LLMバックエンド切り替え
`rag_local_bridge.py` の `_LLM_BACKEND` 変数で制御：
```python
_LLM_BACKEND = os.environ.get("RAG_LLM_BACKEND", "claude")  # "claude" or "gemini"
```
Unity・Houdiniクライアントからも `/api/llm-backend` POST で変更可能。

### ストリーミングレスポンス
LLMの回答をトークン単位で逐次返す方式。レイテンシを体感的に下げる。  
本プロジェクトでは現状バッファリング方式（全文返却後に表示）。

---

## 4. セキュリティ・認証モデル

### AuthManager
`scripts/auth_manager.py` で定義。SQLite（`data/auth.db`）でユーザーとAPIキーを管理。

### APIキー認証
- クライアントはHTTPヘッダー `X-API-Key: <key>` でリクエスト
- `auth_manager.verify_key(api_key)` で検証
- 失敗時: 403 Forbidden

### ユーザーロール
| ロール | 検索可能Namespace |
|---|---|
| `admin` | 全Namespace |
| `developer` | `tool_docs` / `game_info` / `research` / `team_notes` |
| `user` | `tool_docs` / `game_info` / `research` |

### PEP (Policy Enforcement Point)
`scripts/pep.py` の `RAGPolicyEnforcementPoint` クラス。ロールと操作種別（read/write/delete）に基づいてアクセスを決定する。  
- `authorize(namespace, operation)` → bool
- `filter_namespaces(user_role, requested)` → 許可されたNamespaceリスト

### 最小権限の原則 (Principle of Least Privilege)
ユーザーには必要最小限のアクセス権のみを付与する設計原則。PEPで実現。

---

## 5. NISTフレームワーク

### NIST CSF (Cybersecurity Framework)
米国国立標準技術研究所が定めたサイバーセキュリティフレームワーク。5つの機能で構成：
1. **Identify** - 資産・リスクの特定
2. **Protect** - アクセス制御・認証
3. **Detect** - 異常検知・監査ログ
4. **Respond** - インシデント対応
5. **Recover** - 復旧・再発防止

本プロジェクトは Protect（AuthManager/PEP）と Detect（監査ログ）に焦点。

### NIST SP 800-53
情報システムのセキュリティコントロールカタログ。AC（Access Control）、AU（Audit）ファミリが本プロジェクトに関連。

---

## 6. Cloud RAG（GAS+Gemini）

### GAS (Google Apps Script)
Google WorkspaceのサーバーレスJavaScript実行環境。Cloud RAGのバックエンドとして使用。  
- `scripts/gas_cloud_rag.js` がメインスクリプト
- WebアプリとしてデプロイしてHTTPエンドポイントを提供

### Notionデータベース（Cloud RAGのメモリ）
Cloud RAGの長期記憶として使用。  
- `RAG_Memory` シートにQ&Aペアを格納（GAS側）
- Notion MCP経由でHoudini 21 DB（`houdini21DB`）を管理

### houdini21DB
本プロジェクトで作成したNotionデータベース。Houdini 21の公式ドキュメントを約80トピックに分割して格納。  
- Data Source ID: `ae209d58-b6b6-4678-ada1-ade17fb1ea27`
- スキーマ: `title / category / tags / difficulty / summary / source_url / collected_at`

### priority（優先度スコア）
Cloud RAGのQ&Aエントリに付与するスコア（0.0〜1.0）：
- 👍 評価で 1.0
- 👎 評価で 0.0
- デフォルト: 0.5
- priority < 0.3 のエントリはRAGコンテキストから除外

### TF-IDF風ランキング（Cloud RAG）
`searchMemory_()` での検索スコアリング：
- キーワードの出現頻度と文書頻度の逆数を組み合わせる
- `rating > 0` のエントリを優先、`rating = -1`（👎）を除外
- 最低スコア閾値: `score >= 2`

### HyDE（Hypothetical Document Embedding）
クエリをそのまま埋め込むのではなく、まず「もしこの質問への理想的な回答があったとしたら？」という仮説文書をLLMに生成させ、その仮説文書の埋め込みをクエリ埋め込みと加重平均して検索するテクニック。語彙ミスマッチ（ユーザーの言葉と文書の言葉が違う問題）を大幅に解消できる。本システムではクエリ40%＋仮説文書60%で混合する。

### hydeExpand_(query, dbKey)
`gas_cloud_rag.js`の内部関数。`hydePromptFor_(dbKey)`でドメイン別プロンプトを取得し、Geminiに仮説文書を生成させてその埋め込みを返す。返り値は加重平均済み埋め込みベクトルで、`searchByEmbedding_`の`preEmb`引数として渡される。

### hydePromptFor_(dbKey)
DBキーごとにHyDE仮説生成用のドメインヒントプロンプトを返す関数。例：`houdini21`→「Houdiniの技術ドキュメントとして、ノード名・パラメータ名・VEX関数名を含めて技術的に」。ドメインをまたいだ汚染（Houdiniの概念がAFURIラーメンの検索に混入するなど）を防ぐ。

### parseExtractionRate_(answer, total)
回答テキスト中の`[1][2][3]`などの引用マーカーを正規表現で抽出し、全ソース件数に対する引用済みソースの割合（情報抽出度）を計算する関数。`{ rate: 50, citedCount: 2, total: 4, cited: [true, false, true, false] }`形式で返す。

### 情報抽出度（extractionRate）
RAG回答でLLMが実際に引用したソースの割合。例：5件のソースを検索して回答に[1][3]の2件しか引用されなければ抽出度40%。抽出度が低い場合は検索結果がクエリに対して過剰または無関係だった可能性を示す。UIでは進捗バーと✓引用/未引用バッジで可視化。

### ページ単位重複排除（Page-level Deduplication）
同一ページ（タイトルが同じ）の複数チャンクが検索結果に並ぶ問題を解消する処理。スコアの最も高いチャンク1件のみを残し、多様なソースからの情報を提示できるようにする。`searchByEmbedding_`内で実装。

### 閾値フィルタ（Threshold Filtering）
`searchByEmbedding_`で低品質の検索結果を除外するためのコサイン類似度の最低基準値。DB指定時は0.58未満を除外、全DB横断検索時は0.62未満を除外。ノイズを削減して情報抽出度を向上させる。

### adminUpdateKey()
GAS管理者APIの関数。既存のAPIキーを削除・再作成せずに、そのキーが持つnamespace権限リストを更新できる。管理UIの「編集」ボタンから呼び出し、チェックボックスで許可namespaceを変更する。引数: `(apiKey, keyPreview, newNamespaces)`。

### houdini21 namespace
Houdini 21向けのドキュメントを管理するCloud RAGの名前空間。GASの`DB_KEY_MAP`に`DB_HOUDINI21`スクリプトプロパティとして設定し、LocalRAGの`VALID_NAMESPACES`、Unity/HoudiniクライアントのUIドロップダウンにも追加済み。NotionのhoudiniDB（80ページ）のページをGASシートに同期して利用する。

### sync_houdini21_db.py
NotionのhoudiniDBからページを取得し、`localRAG/houdini21/`フォルダにMarkdownファイルとして出力するスクリプト。環境変数`NOTION_API_KEY`を使用（`load_dotenv()`は使わない）。`--dry-run`（変更なし確認）と`--index`（インデックス化まで実行）オプションあり。

---

## 7. Local RAG（ChromaDB+BM25）

### rag_local_bridge.py
Local RAGのHTTPブリッジサーバー。Port 8766で起動。  
主要エンドポイント：
| Method | Path | 機能 |
|---|---|---|
| POST | `/query` | RAG検索+LLM回答 |
| POST | `/api/score` | 理解度スコア更新 |
| GET/POST | `/api/llm-backend` | LLMバックエンド確認/変更 |
| GET | `/admin/audit` | 監査ログ取得 |

### Hybrid Retrieval
```python
# 擬似コード
chroma_results = chroma.query(query_embedding, n_results=20)
bm25_results   = bm25_index.get_top_n(query_tokens, corpus, n=20)
fused          = rrf_fusion(chroma_results, bm25_results)
return fused[:TOP_K]
```

### document_pipeline.py
ドキュメントをChromaDBに投入するパイプライン。  
- `chunk_by_headings()`: Markdown見出しで分割（800文字/80文字オーバーラップ）
- `SemanticChunker`: トークン数ベースのスライディングウィンドウ分割（512/64）
- `process_file()`: ファイル単位で処理、`--semantic` フラグで SemanticChunker を使用

### source_hash
チャンクのSHA-256ハッシュ（先頭16文字）。重複投入防止と追跡に使用。

---

## 8. 監査ログと監視

### RAGAuditLogger
`scripts/audit_logger.py` の監査ログクラス。  
出力: `logs/rag_audit.jsonl`（JSON Lines形式）

ログフィールド：
| フィールド | 説明 |
|---|---|
| `timestamp` | ISO8601形式のUTC時刻 |
| `session_id` | セッション識別子 |
| `user_role` | ユーザーロール |
| `action` | 操作種別（query/save/delete） |
| `namespace` | 対象Namespace |
| `query_hash` | クエリのSHA-256先頭16文字 |
| `result_count` | 検索結果数 |
| `latency_ms` | レイテンシ（ミリ秒） |
| `allowed` | アクセス許可の可否 |

### JSON Lines (JSONL)
1行1JSONオブジェクトのファイル形式。ストリーミング書き込みと行単位の読み込みが容易。

### /admin/audit エンドポイント
`GET /admin/audit?limit=100` で最新N件の監査ログをJSON配列で返す。  
`allowed=false` の行はフロントエンドで赤くハイライト表示。

---

## 9. Houdini技術用語

### SOP (Surface Operators)
Houdiniのジオメトリ処理コンテキスト（/obj/geo 以下）。ポリゴン・カーブ・ボリュームを操作する基本コンテキスト。

### VEX
Houdini独自のシェーダー/手続き型プログラミング言語。C言語ライクで、GPU並列実行される。  
Wrangle SOPなど多数のノードで使用。

### VOP (VEX Operators)
VEXをビジュアルにノードで組む方法。GLSL/HLSLのノードベースエディタに相当。

### DOP (Dynamic Operators)
物理シミュレーションのコンテキスト。RBD、FLIP流体、Pyro煙炎、Vellumが動作する。

### FLIP (FLuid Implicit Particle)
粒子と格子を組み合わせた流体シミュレーション手法。Houdiniの水・流体の標準。

### Pyro
煙・炎・爆発のボリューメトリックシミュレーション。Sparse Pyroで大規模シミュが可能。

### Vellum
位置ベースダイナミクス（PBD）を使った布・ソフトボディ・髪・構造物のシミュレーション。

### KineFX
Houdini 18.5以降のキャラクターアニメーションフレームワーク。SOP内でリグ・スキニング・アニメーションを処理。

### Solaris / LOP (Lighting Operators)
HoudiniのUSD (Universal Scene Description) 編集コンテキスト。ライティング・レンダリング設定を管理。

### Karma XPU
HoudiniのメインレンダラーでHydra/USDベース。NVIDIA CUDA / AMD HIP / Intel GPU に対応。

### PDG (Procedural Dependency Graph)
タスクグラフを定義してWork Itemを並列処理するフレームワーク。TOPs（Task Operators）コンテキストで使用。

### HDA (Houdini Digital Asset)
ノードネットワークをカプセル化した再利用可能なカスタムノード形式（.hdaファイル）。

### USD (Universal Scene Description)
Pixarが開発したオープンな3Dシーン記述フォーマット。HoudiniのSolaris/LOPで使用。

### MaterialX
オープンなマテリアル記述フォーマット。Karma XPUでシェーダーをポータブルに定義するために使用。

### ROP (Render Operators)
Houdiniの出力/レンダリングコンテキスト（/out以下）。フレームレンダリング・ジオメトリキャッシュ出力を定義。

### CHOP (Channel Operators)
時系列データ・アニメーションカーブ・オーディオを操作するコンテキスト。

### POP (Particle Operators)
DOPコンテキスト内で動作するパーティクルシミュレーションシステム。

### Crowd Agent
KineFXリグとアニメーションクリップをパッケージ化したCrowdシミュレーションの基本単位。

### Height Field
VDBボリュームとして高さマップを保持する地形表現。Height Field SOPで操作。

### SideFX Labs
SideFXが無料提供するゲーム開発向けHDA集。Instant Meshes、Roof Generator、Road Generatorなどを含む。

---

## 10. Unity連携用語

### RAGChatbotWindow.cs
`Assets/Editor/RAGChatbot/RAGChatbotWindow.cs`。UnityのEditorWindowとして実装されたRAGチャットクライアント。

### IRAGClient.cs
RAGバックエンドへのインターフェース定義。Local/CloudのDI切り替えを想定。

### score_user_id
UnityクライアントでRAGを使用するユーザーのID。理解度スコア更新に使用。

### UpdateScoreAsync()
回答受信後に`/api/score` POSTを行い、理解度スコアを更新するメソッド。

### SetLlmBackendAsync()
SettingsタブからLLMバックエンドを変更するメソッド。

### LOD (Level of Detail)
距離に応じてメッシュの複雑度を切り替える最適化手法。HoudiniでLOD0-3を事前生成してFBXエクスポート。

---

## 11. プロジェクト固有のコンポーネント

### UnderstandingScoreEngine
`scripts/score_engine.py` の理解度スコアエンジン。  
- テーブル: `understanding_scores (user_id, topic, score REAL, updated_at)`
- 正解時: `score += 0.1`、誤答時: `score -= 0.05`
- スコア範囲: `[0.0, 1.0]`

### スコアに基づくNamespace選択
```
score < 0.3  → namespaces=["tool_docs"]          # 基礎のみ
score < 0.7  → namespaces=["tool_docs","game_info","research"]
score >= 0.7 → namespaces=["research","team_notes"]  # 上級
```

### Houdini パネル（rag_chatbot.py）
`houdini/python_panels/rag_chatbot.py`。Houdini Python PanelとしてPySide6で実装されたRAGチャットUI。  
バックエンドコンボボックスで Claude/Gemini を切り替え、ステータスバーに理解度スコアを表示。

---

## 12. インフラ・環境

### 環境変数（.envファイル不使用）
**重要**: `load_dotenv()` は使用禁止。`os.environ.get()` のみで取得する。
| 変数 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API認証 |
| `GEMINI_API_KEY` | Gemini API認証 |
| `RAG_LLM_BACKEND` | LLMバックエンド選択（"claude"/"gemini"） |
| `RAG_API_KEY` | Local RAGブリッジ認証キー |

### WSL2
Windows Subsystem for Linux 2。LocalRAGブリッジはWSL2 Ubuntu環境で動作。

### Docker
将来的なコンテナ化を想定。現状はWSL2のネイティブPython環境で動作。

### Obsidian
ユーザーのノート管理ツール。Obsidianのマークダウンファイルをドキュメントパイプラインで取り込む。

### GitHub
リポジトリ管理。メインブランチ: `main`。

### SQLite
`data/auth.db`：認証・ユーザー管理・理解度スコアの永続化に使用。

### JSONL (JSON Lines)
監査ログ形式。`logs/rag_audit.jsonl` に蓄積。1行1ログエントリ。

### Port 8766
Local RAGブリッジのデフォルトポート。`rag_local_bridge.py` が `BaseHTTPRequestHandler` で待ち受け。

---

*最終更新: 2026-06-29*
