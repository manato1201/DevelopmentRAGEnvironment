# ゲーム開発 RAG 環境

**更新日:** 2026-06-30

---

## RAG とは？

**RAG（Retrieval-Augmented Generation）** とは、AI に質問するとき、あらかじめ自分たちのドキュメントを検索して関連情報を見つけ、それを添えて回答させる仕組みです。  
「AI が自分のチームのドキュメントを参照しながら答えてくれる」と思えば OK です。

---

## このプロジェクトで作ったもの

ゲーム開発チーム向けに、2 種類の RAG 環境と、Unity・Houdini から使えるチャット UI を一から構築しました。

| 機能 | 概要 |
|------|------|
| **クラウド RAG** | Notion（ドキュメント管理）＋ Gemini AI（回答生成）をクラウドで動かす |
| **ローカル RAG** | 個人メモ・チャット履歴など外に出せない情報をローカル PC で管理 |
| **Unity 連携** | Unity 6 のエディタ内にチャット UI・グラフビューを組み込み |
| **Houdini 連携** | Houdini 21+ のパネルにチャット UI・グラフビューを組み込み |
| **グラフビュー** | ドキュメント間の関係をネットワーク図として可視化 |
| **HTTP ブリッジ** | Unity/Houdini からローカル RAG に繋ぐ中継サーバー |
| **👍/👎 評価機能** | Cloud RAG の回答に評価をつけて検索品質を自己改善 |
| **監査ログ** | 全クエリを JSONL 形式で記録（NIST SP 800-207 準拠） |
| **PEP アクセス制御** | ロール別にアクセス可能な名前空間を制限（最小権限原則） |
| **理解度スコア** | ユーザーごとのトピック習熟度に応じて検索範囲を自動調整 |
| **セマンティック分割** | トークン単位のオーバーラップチャンク分割で検索精度向上 |
| **HyDE 検索強化** | クエリ+仮説文書の加重平均埋め込みで語彙ミスマッチを解消（精度向上）|
| **情報抽出度メトリクス** | 回答中の引用数÷ソース数で抽出効率を可視化（✓引用バッジ・進捗バー）|
| **houdini21 名前空間** | Houdini 21ドキュメント専用DB（GAS・LocalRAG・Unity/Houdini UI統合）|

---

## クイックスタート

### クラウド RAG を使いたい

1. Notion に 8 つのデータベースを作成する
2. `scripts/gas_cloud_rag.js` を Google Apps Script に貼り付けてデプロイ
3. Unity または Houdini の Settings タブで GAS WebApp の URL を設定する

詳細 → [docs/cloud-rag.md](docs/cloud-rag.md)（講義資料 → [lecture/cloud-rag-lecture.html](lecture/cloud-rag-lecture.html)）

### ローカル RAG を使いたい

外部リポジトリのクローンは不要です。検索エンジン一式（ChromaDB・埋め込み生成・チャンク分割）がこのリポジトリ単体で完結します。

```powershell
# 1. 依存パッケージを同期
uv sync

# 2. ドキュメントをインデックス化
uv run python scripts\rag_cli.py index

# 3. ローカル HTTP ブリッジを起動（Unity/Houdini と繋ぐ）
$env:ANTHROPIC_API_KEY = "sk-ant-..."
uv run python scripts\rag_local_bridge.py
# → localhost:8766 で待機開始
```

詳細 → [docs/local-rag.md](docs/local-rag.md)（講義資料 → [lecture/local-rag-lecture.html](lecture/local-rag-lecture.html)）

### Unity から使いたい

1. `Assets/Editor/RAGChatbot/` フォルダをプロジェクトにコピー
2. Unity メニュー → **RAG → RAG Chatbot** を開く
3. Settings タブで接続先（Cloud / Local）を設定

### Houdini から使いたい

1. `houdini/python_panels/rag_chatbot.py` と `graph_view.py` を Houdini の Python Panels フォルダにコピー
2. Houdini の **Python Panel** メニューから RAG Chatbot を追加

### グラフ JSON を手動で生成したい

```powershell
# ChromaDB からドキュメントのグラフデータを生成
uv run python scripts\rag_graph_export.py
# → graph_data.json が生成される
```

### 新しいドキュメントを追加したい

詳細 → [lecture/local-rag-lecture.html](lecture/local-rag-lecture.html) の「新規ドキュメント追加ガイド」セクション

---

## ディレクトリ構成

```
DevelopmentRAGEnvironment/
├── README.md
├── .env.example                        # 環境変数テンプレート
│
├── Assets/                             # Unity プロジェクトファイル
│   └── Editor/
│       └── RAGChatbot/
│           ├── IRAGClient.cs           # Cloud/Local 切り替えインターフェース
│           ├── CloudRAGClient.cs       # GAS WebApp へ HTTPS 接続するクライアント
│           ├── LocalRAGClient.cs       # localhost:8766 へ HTTP 接続するクライアント
│           ├── RAGChatbotWindow.cs     # Chat / Graph / Settings の 3 タブ EditorWindow
│           ├── RAGGraphView.cs         # IMGUI Painter2D によるグラフ描画
│           ├── RAGGraphData.cs         # グラフ JSON のデータ構造定義
│           └── RAGMessage.cs           # チャットメッセージのデータ構造定義
│
├── houdini/                            # Houdini プロジェクトファイル
│   └── python_panels/
│       ├── rag_chatbot.py              # PySide6 製チャットパネル（Chat / Settings タブ）
│       └── graph_view.py              # QGraphicsView によるグラフビュー
│
├── scripts/                            # ユーティリティスクリプト
│   ├── rag_local_bridge.py             # ★ ローカル HTTP ブリッジ（Unity/Houdini → RAGService 直接呼び出し）
│   ├── rag_service.py                  # ★ RAG サービス統合層（document_processor + embedding_generator + vector_database）
│   ├── document_processor.py           # ★ ファイル読込・チャンク分割（旧 mcp-rag-server から移植）
│   ├── embedding_generator.py          # ★ 埋め込み生成（sentence-transformers ラッパー）
│   ├── vector_database.py              # ChromaDB + BM25 ハイブリッド検索バックエンド
│   ├── rag_cli.py                      # ★ インデックス化 CLI（index / clear / count）
│   ├── rag_mcp_server.py               # ★ Claude Desktop 直接登録用 MCP サーバー（独立版）
│   ├── mcp_server.py                   # ★ MCP プロトコル実装（JSON-RPC over stdio）
│   ├── rag_mcp_tools.py                # ★ MCP 用 search / get_document_count ツール
│   ├── rag_graph_export.py             # ★ ChromaDB からグラフ JSON を生成
│   ├── audit_logger.py                 # ★ JSONL 監査ログ（NIST SP 800-207 テネット7）
│   ├── pep.py                          # ★ Policy Enforcement Point（名前空間アクセス制御）
│   ├── document_pipeline.py            # ★ SemanticChunker 追加（トークン単位チャンク分割）
│   ├── score_engine.py                 # ★ 理解度スコアエンジン（トピック別習熟度 → 検索範囲自動調整）
│   ├── auto_index.py                   # watchdog による自動インデックス化
│   ├── gas_cloud_rag.js                # GAS WebApp コード（Notion + Gemini チャット）
│   ├── notion_bulk_add.py              # Notion DB への一括データ投入
│   ├── notion_bulk_input.yaml          # notion_bulk_add.py の入力サンプル
│   ├── notion_to_corpus.py             # Notion → Gemini Corpus 同期
│   ├── extract_zip.py                  # Houdini ヘルプ zip 展開
│   ├── delete_non_txt.py              # .txt 以外のファイルを削除
│   └── sync_houdini21_db.py            # ★ Notion houdini21DB → localRAG/houdini21/ 同期
│
├── docs/                               # 設計・セットアップ・用語・ライセンスドキュメント（4種に統合済み）
│   ├── cloud-rag.md                    # クラウド RAG 設計・セットアップ（旧 cloud-rag-setup.md + rag-system-design.md統合）
│   ├── local-rag.md                    # ローカル RAG 設計・セットアップ（旧 local-rag-setup.md 等7ファイル統合）
│   ├── terminology.md                  # 技術・用語解説
│   └── license-compliance.md           # ライセンス・権利関連
│
├── lecture/                            # 講義資料（HTML、4種に統合済み）
│   ├── cloud-rag-lecture.html          # ★ クラウド RAG 講義（コサイン類似度・Spring Layoutのcanvasアニメーション付き）
│   ├── local-rag-lecture.html          # ★ ローカル RAG 講義（内部構造・新規ドキュメント追加ガイド等を統合、チャンク分割のcanvasアニメーション付き）
│   ├── terminology.html                # 用語解説（講義版）
│   └── license-compliance.html         # ライセンス解説（講義版）
│
└── localRAG/                           # Obsidian vault（インデックス対象のドキュメント置き場）
    ├── personal_notes/                 # 個人メモ・調査ノート
    ├── tutorials/                      # チュートリアル生成結果
    ├── chat_logs/                      # チャット履歴
    ├── private_docs/                   # 共有不可ドキュメント
    ├── _rag_dashboard/                 # インデックス管理用（検索対象外）
    ├── _templates/                     # テンプレート（検索対象外）
    └── houdini21/                      # Houdini 21ドキュメント（sync_houdini21_db.py で同期）
```

★ マークは新たに追加・拡張されたファイルです。

---

## 設計思想

### なぜクラウドとローカルの 2 層構成にしたのか

すべての情報を 1 か所に集めると、個人のチャット履歴や未公開メモがチームメンバーに見えてしまいます。  
逆に、チームで共有すべきツール仕様や設計書をローカルだけに置くと、他のメンバーが参照できません。

そのため、**「公開してよい情報」と「個人情報」を物理的に分離**する設計にしました。

```
クラウドに入れるもの（チームで共有する情報）
├── Unity / Houdini / DirectX12 などのツール仕様
├── ゲーム設計書・共有ドキュメント
├── 技術記事（手動で精査したもの）
└── ゼミ資料・議事録

ローカルに入れるもの（個人情報・外に出せない情報）
├── AI とのチャット履歴
├── Houdini チュートリアルの生成結果
├── 個人の Obsidian ノート・進捗メモ
└── 共有できない草稿・下書き
```

### なぜ Unity・Houdini に直接組み込んだのか

ブラウザを別途開いて AI に質問するより、**作業中のツール内で直接質問できる**方が開発効率が上がります。  
また、Cloud モードと Local モードをワンクリックで切り替えられるよう、`IRAGClient` インターフェース（切り替え口）を設けて実装を抽象化しています。

### なぜ HTTP ブリッジ（rag_local_bridge.py）が必要なのか

検索エンジン（`rag_service.py`）は Python のクラスとして実装されています。Unity（C#）や Houdini（Python サブプロセス）から直接 import することはできないため、**HTTP という汎用的な通信方式で公開する中継サーバー**が必要です。

```
Unity C# / Houdini Python
        ↓ HTTP POST（誰でも使える通信）
rag_local_bridge.py（HTTP API として公開）
        ↓ 同一プロセス内で直接 import
rag_service.py（検索エンジン本体）
```

検索エンジン一式（`document_processor.py` / `embedding_generator.py` / `rag_service.py` / `vector_database.py`）はこのリポジトリに内蔵されており、外部リポジトリへの依存はありません。Claude Desktop から直接 MCP サーバーとして使いたい場合は `scripts/rag_mcp_server.py` を登録してください（[docs/local-rag.md](docs/local-rag.md) 参照）。

---

## セキュリティ強化機能（2026-06-29 追加）

NIST SP 800-207（Zero Trust Architecture）の設計を取り入れた以下の機能を追加しました。

| 機能 | ファイル | 概要 |
|------|---------|------|
| **監査ログ** | `scripts/audit_logger.py` | 全クエリを `logs/rag_audit.jsonl` に記録。クエリは SHA-256 でハッシュ化してプライバシー保護 |
| **PEP** | `scripts/pep.py` | ロール（admin / developer / user）ごとにアクセス可能な名前空間を制限 |
| **SemanticChunker** | `scripts/document_pipeline.py` | 512トークン/64オーバーラップのスライディングウィンドウ分割。`--semantic` フラグで有効化 |
| **理解度スコア** | `scripts/score_engine.py` | トピック別スコアに応じて検索範囲を自動調整（beginner→tool_docs のみ、expert→research+team_notes） |
| **👍/👎 評価** | Unity + Houdini UI / GAS | Cloud RAG の回答バブルに評価ボタン。👎 評価した回答は以後の検索から除外 |

### 👍/👎 評価の動作

```
1. Cloud モードで質問 → 回答バブルの下に 👍/👎 ボタンが表示
2. 👎 を押す → GAS の RAG_Memory シートで priority=0.0 に更新
3. 同じトピックを再度質問 → priority<0.3 のエントリが検索から除外
4. 回答品質が自動的に向上していく
```

---

## 検索品質向上機能（2026-06-29 追加）

| 機能 | 概要 |
|------|------|
| **HyDE（仮説文書埋め込み）** | クエリの語彙と文書の語彙のギャップを仮説文書で橋渡し。検索精度を大幅改善 |
| **ドメイン別HyDEプロンプト・重み** | DBごとに最適なドメインヒントを使用（Houdini技術/飲食店/研究論文等）。固有事実ドメイン（afuri/braintq/fourteen）はクエリ80%＋仮説20%、技術ドメインは40%＋60%（ハルシネーション対策） |
| **ページ単位重複排除** | 同一ページの複数チャンクのうち最高スコアのみを残し、多様なソースを優先表示 |
| **閾値フィルタ** | コサイン類似度0.58未満（全DB時0.62未満）の低品質チャンクを除外 |
| **情報抽出度** | 回答中の`[1][2]`引用を解析し、何件のソースが実際に活用されたかを表示 |
| **adminUpdateKey** | APIキーのnamespace権限を削除・再作成不要で更新できる管理機能 |
| **houdini21 namespace** | Houdini 21専用ドキュメントDB。GAS/LocalRAG/Unity/Houdini UIに統合済み |

---

## 参考リンク

| リソース | URL |
|----------|-----|
| karaage0703/mcp-rag-server（検索エンジンのベンダリング元、MIT） | https://github.com/karaage0703/mcp-rag-server |
| Notion API リファレンス | https://developers.notion.com/ |
| Google AI Studio（Gemini API キー発行） | https://aistudio.google.com/ |
| uv — Python パッケージマネージャー | https://docs.astral.sh/uv/ |
