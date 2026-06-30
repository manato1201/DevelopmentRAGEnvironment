# ローカルRAG（LocalRAG）統合ガイド

**統合元:** local-rag-setup.md + environment-setup.md + document-pipeline-guide.md + ui-implementation-design.md(Local部分) + distribution-guide.md + rag-system-design.md(Local部分) + 歴史的資料3本（要約）
**更新日:** 2026-06-30

> クラウドRAG（Notion + GAS WebApp + Gemini）については [docs/cloud-rag.md](cloud-rag.md) を参照してください。本ドキュメントはローカルRAG（このリポジトリ単体で完結する Windows ネイティブ検索エンジン）専用です。

---

## 目次

1. [概要](#1-概要)
2. [アーキテクチャ](#2-アーキテクチャ)
3. [セットアップ](#3-セットアップ)
4. [ドキュメント分割パイプライン](#4-ドキュメント分割パイプライン)
5. [使い方（2つの経路）](#5-使い方2つの経路)
6. [セキュリティ機能](#6-セキュリティ機能)
7. [UI実装詳細](#7-ui実装詳細)
8. [配布ガイド](#8-配布ガイド)
9. [設計の経緯](#9-設計の経緯)
10. [トラブルシューティング](#10-トラブルシューティング)

---

## 1. 概要

LocalRAG は、Obsidian vault（`localRAG/` フォルダ）内の Markdown ドキュメントを ChromaDB ベースのベクトル検索エンジンでインデックス化し、Claude Desktop / Unity / Houdini から検索できるようにする仕組みです。

このシステムには「クラウド版」と「ローカル版」の2種類があり、用途に応じて使い分けます。

| 比較項目 | クラウドRAG | ローカルRAG |
|----------|-------------|-------------|
| ドキュメント置き場 | Notion（オンライン） | `localRAG/` フォルダ（PC 内） |
| 検索・回答エンジン | Gemini 2.5 Flash（Google） | Claude Haiku（Anthropic） |
| ネット接続 | 必要 | 不要（検索自体はオフラインで完結） |
| チームで共有 | できる | できない（個人のみ） |
| 向いている情報 | ツール仕様・設計書・技術記事 | チャット履歴・個人メモ・下書き |
| Unity/Houdini での切り替え | Settings タブで選択 | Settings タブで選択 |

クラウドRAGの詳細（Notion 7DB・GAS WebApp・HyDE検索強化・情報抽出度メトリクス等）は [docs/cloud-rag.md](cloud-rag.md) を参照してください。

---

## 2. アーキテクチャ

### 2.1 2026-06-30 の構成変更（外部リポジトリ依存の解消）

以前は検索エンジンを他者の個人リポジトリ `mcp-rag-server`（`karaage0703` 氏、MIT ライセンス）として別途クローンし（`C:\Users\matuu\Desktop\GameDevelopment\mcp-rag-server` 等）、`rag_local_bridge.py` がサブプロセスとして起動し MCP JSON-RPC (stdio) で通信していました。これには「元リポジトリの削除・非公開化」「破壊的変更」「監査証跡の取りにくさ」「カスタマイズ管理の難しさ」といったリスクがありました。

**2026-06-30 時点でこの依存は完全に解消されています。** MIT ライセンスの許諾範囲内で検索エンジンのコードをこのリポジトリに直接ベンダリング（取り込み）し、外部リポジトリへの依存はなくなりました。`pyproject.toml` に検索エンジンの依存（ChromaDB・sentence-transformers・rank-bm25・sudachipy 等）がすべて直接宣言されており、このリポジトリで `uv sync` を一度実行するだけで完結します。

### 2.2 ベンダリングされたファイル

| ファイル | 内容 |
|---------|------|
| `scripts/document_processor.py` | ファイル読み込み・チャンク分割（旧 `mcp-rag-server/src/document_processor.py` を移植） |
| `scripts/embedding_generator.py` | sentence-transformers ラッパー（旧 `mcp-rag-server/src/embedding_generator.py` を移植、`load_dotenv()` は削除） |
| `scripts/rag_service.py` | document_processor + embedding_generator + vector_database を束ねるオーケストレーター。`create_rag_service_from_env()` ファクトリを提供 |
| `scripts/rag_cli.py` | インデックス用 CLI（旧 `mcp-rag-server` の `uv run python -m src.cli index` を置き換え） |
| `scripts/mcp_server.py` | MCP プロトコル実装（JSON-RPC over stdio）。Claude Desktop に直接登録したい場合に使用 |
| `scripts/rag_mcp_tools.py` | search / get_document_count の MCP ツールハンドラ |
| `scripts/rag_mcp_server.py` | MCP サーバーのエントリーポイント（旧 `mcp-rag-server/src/main.py` を置き換え） |
| `scripts/vector_database.py` | ChromaDB + BM25 ハイブリッド検索のストレージ層（既存・変更なし） |

`scripts/rag_local_bridge.py` も、サブプロセス + JSON-RPC で通信していた旧 `MCPClient` クラスを廃止し、`rag_service.py` を直接 in-process で呼び出す `LocalRAGClient` クラスに置き換えました。これに伴い CLI 引数 `--mcp-dir` も廃止されています。

> **ライセンスについて:** ベンダリング元の `mcp-rag-server` は MIT ライセンスです。改変・再配布・商用利用は自由で、ソース開示義務もありません。

### 2.3 データフロー全体図

```
┌─────────────────────────────────────────────────────────┐
│  【ローカルRAG層】  Windows 11 ローカル環境              │
│                                                         │
│  Python 3.13+  (DevelopmentRAGEnvironment に統合済み)    │
│    ├── ChromaDB          ← ベクトルDB                   │
│    ├── sentence-transformers ← 埋め込み生成             │
│    ├── markitdown        ← PDF/Word 変換                │
│    └── sudachipy         ← 日本語形態素解析             │
│                                                         │
│  rag_local_bridge.py  (HTTP :8766)                      │
│    ├── /admin  → 管理画面                               │
│    ├── /ui     → チャット画面                           │
│    └── /query  → Unity/Houdini からの API              │
│                                                         │
│  Anthropic API  (claude-haiku / claude-sonnet)          │
│  localRAG/      (ドキュメント vault, gitignore)         │
└─────────────────────────────────────────────────────────┘

  Unity / Houdini エディタ
    └── Local モード → localhost:8766 へ HTTP
```

```
Unity 6 EditorWindow / Houdini 21+ Python Panel
        │ Local モード（HTTP POST）
        ▼
rag_local_bridge.py（HTTP → in-process 変換ブリッジ）
ポート: localhost:8766
        │ LocalRAGClient（インプロセス直接呼び出し）
        ▼
rag_service.py（ベンダー統合済み）
  ├── ChromaDB（ベクトルDB）+ BM25（ハイブリッド検索）
  ├── multilingual-e5-large（埋め込み）
  └── Claude Haiku（回答生成）
        │
        ▼ グラフ表示（GET /graph）
rag_graph_export.py（Spring Layout → JSON 生成）
```

### 2.4 ChromaDB + BM25 ハイブリッド検索

「ベクトル（vector）」とは数値の配列のことで、テキストをベクトルに変換することを「埋め込み（embedding）」と呼びます。このシステムでは `multilingual-e5-large` というモデルが、テキストを 1024 個の数値の配列に変換します。意味が似ているテキストは変換後の数値配列が近い値になるため、これを利用して「意味の近さ」でドキュメントを検索できます。

```
例）
「Unity の物理演算を使う方法」
→ [0.12, 0.87, -0.23, ...]（1024 次元）

「Unity Rigidbody コンポーネントのチュートリアル」
→ [0.13, 0.85, -0.21, ...]（1024 次元、近い！）

「Houdini の VEX スクリプト」
→ [0.71, -0.34, 0.55, ...]（1024 次元、遠い）
```

LocalRAG はベクトル検索（意味の近さ）に加えて BM25（キーワード一致）も組み合わせる **ハイブリッド検索** を採用しており、意味の近さとキーワードの一致の両方で探すため片方だけより精度が上がります。

**オリジナル（mcp-rag-server）からの主な変更点:**
- ベクトル DB を PostgreSQL/pgvector から **ChromaDB** に変更（Docker 不要、Windows で即動く）
- Windows 11 ネイティブ対応（WSL2 不要）
- ハイブリッド検索（ベクトル + BM25）を追加
- 外部リポジトリ依存を解消し、コードをこのリポジトリにベンダー統合（2026-06-30）

### 2.5 グラフビュー

ドキュメント間の「意味の近さ」をネットワーク図として可視化する機能です。ノード（丸い点）が1つのドキュメント、エッジ（線）がドキュメント間の関係（類似度が高いほど近くに配置）を表します。LocalRAG では `rag_graph_export.py` が ChromaDB 内のドキュメント間類似度を計算し、Spring Layout（バネレイアウト）アルゴリズムで座標を決めた JSON を生成します。クライアント（Unity の `RAGGraphView.cs` や Houdini の `graph_view.py`）がこの JSON を受け取って描画します。

---

## 3. セットアップ

### 3.1 前提条件

| 項目 | 要件 |
|------|------|
| OS | Windows 11 |
| Docker | **不要** |
| WSL2 | **不要** |
| 外部リポジトリ | **不要**（このリポジトリ単体で完結） |
| Python | uv が自動管理（3.13 を使用） |
| Claude Desktop | インストール済み（MCP登録を使う場合） |
| Obsidian | インストール済み |
| ディスク空き | 5GB 以上推奨（埋め込みモデルのダウンロードを含む） |
| RAM | 8GB 以上（推奨 16GB 以上。`multilingual-e5-large` が約1.5GB 使用） |

### 3.2 uv のインストール

```powershell
winget install --id=astral-sh.uv -e
uv --version
```

### 3.3 依存パッケージの同期

このリポジトリの `pyproject.toml` に検索エンジンの依存（ChromaDB・sentence-transformers・rank-bm25・sudachipy 等）が含まれています。クローン不要・コピー不要で、`uv sync` だけで完結します。

```powershell
cd C:\Users\YOUR_USERNAME\Desktop\GameDevelopment\DevelopmentRAGEnvironment
uv sync
```

> 初回は `sentence-transformers` 等の依存ダウンロードで数分かかります。`requires-python` は `>=3.13` を指定済み（`sentencepiece` の wheel が提供される最小バージョン）。

主な依存パッケージ：

| パッケージ | バージョン | 用途 | ライセンス |
|-----------|-----------|------|-----------|
| `sentence-transformers` | 最新 | multilingual-e5-large 埋め込み生成 | Apache 2.0 |
| `chromadb` | >= 1.5.9 | ベクトルDB 本体 | Apache 2.0 |
| `markitdown[all]` | 最新 | PDF/Word/PPT → Markdown 変換 | MIT |
| `sudachipy` | >= 0.6.11 | 日本語形態素解析 | Apache 2.0 |
| `sudachidict-core` | >= 20260428 | 日本語辞書 | Apache 2.0 |
| `rank-bm25` | >= 0.2.2 | BM25 ハイブリッド検索 | Apache 2.0 |
| `mcp[cli]` | 最新 | MCP プロトコル | MIT |
| `watchdog` | >= 6.0.0 | ファイル変更監視 | Apache 2.0 |
| `numpy` | 最新 | ベクトル演算 | BSD 3-Clause |
| `sentencepiece` | >= 0.2.0 | トークナイザー | Apache 2.0 |
| `pyyaml` | >= 6.0.3 | YAML / 設定ファイル読み込み | MIT |
| `requests` | >= 2.34.2 | HTTP 通信 | Apache 2.0 |
| `python-dotenv` | >= 1.2.2 | 未使用（互換目的のみ。`load_dotenv()` は呼び出していない） | BSD 3-Clause |

別途インストールが必要なもの：`feedparser`（`pip install feedparser`、RSS/arXiv 収集スクリプト `rss_to_rag.py` 用）。

### 3.4 環境変数の設定

`.env` ファイルは使用しません（`load_dotenv()` 非対応）。必要な環境変数は OS の環境変数として設定するか、起動コマンドの前に付与してください。デフォルト値のままで問題なければスキップして構いません。

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `SOURCE_DIR` | `localRAG/` | インデックス化対象ディレクトリ |
| `PROCESSED_DIR` | `localRAG/_rag_dashboard/.processed` | 処理済みファイルの保存先 |
| `CHROMA_PATH` | `data/chroma` | ChromaDB データ保存先 |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | 埋め込みモデル名 |
| `EMBEDDING_DIM` | `1024` | 埋め込み次元数 |
| `EMBEDDING_PREFIX_QUERY` | `query:` | 検索クエリ用プレフィックス |
| `EMBEDDING_PREFIX_EMBEDDING` | `passage:` | 文書埋め込み用プレフィックス |
| `ANTHROPIC_API_KEY` | なし | `rag_local_bridge.py` 使用時に必須 |

環境変数のセット方法：

```powershell
# セッション中のみ有効
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# システム環境変数に永続登録（管理者権限不要）
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "User")
```

### 3.5 Obsidian vault の設定

Obsidian を開き、`localRAG\` フォルダを vault として登録します。フォルダ名がそのまま ChromaDB のコレクション名（namespace）になります。

```
DevelopmentRAGEnvironment\localRAG\   ← Obsidian でこのフォルダを開く
├── tool_docs\        ← namespace: tool_docs（ツール・ライブラリのドキュメント）
├── research\         ← namespace: research（調査・研究メモ）
├── team_notes\       ← namespace: team_notes（議事録・共有メモ）
├── personal_notes\   ← namespace: personal_notes（個人メモ）
│   ├── progress\
│   └── ideas\
├── game_info\        ← namespace: game_info（仕様書・デザインドキュメント）
├── houdini21\        ← namespace: houdini21（Houdini 21 専用ドキュメント、sync_houdini21_db.py で同期）
├── _rag_dashboard\   ← 管理専用（インデックス対象外）
└── _templates\       ← テンプレート（インデックス対象外）
```

**テンプレートプラグインの設定:** 設定 → コアプラグイン → テンプレート: オン／設定 → テンプレート → テンプレートフォルダの場所: `_templates`

### 3.6 インデックス化

```powershell
cd C:\Users\YOUR_USERNAME\Desktop\GameDevelopment\DevelopmentRAGEnvironment
uv run python scripts\rag_cli.py index
```

正常完了時のログ:
```
インデックス化が完了しました
- ドキュメント数: N
- 処理時間: N 秒
```

差分のみインデックス化する場合：

```powershell
uv run python scripts\rag_cli.py index --incremental
```

ドキュメント数を確認：

```powershell
uv run python scripts\rag_cli.py count
```

> **スキップされるフォルダ:** `_rag_dashboard\`・`_templates\`・`.processed\` は自動除外されます。

### 3.7 watchdog（自動インデックス化）の起動

```powershell
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python scripts/auto_index.py"
```

起動後は Obsidian でノートを保存するたびに自動インデックス化されます。`_rag_dashboard\index_status.md` と `namespace_map.md` が自動更新されることで確認できます（詳細は「[9. 設計の経緯](#9-設計の経緯)」参照）。

### 3.8 houdini21DB を LocalRAG に同期する（sync_houdini21_db.py）

Notion houdini21DB のページを `localRAG/houdini21/` フォルダへ Markdown ファイルとして書き出すスクリプトです。

```powershell
$env:NOTION_API_KEY = "secret_xxx"
uv run python scripts\sync_houdini21_db.py

# プレビューのみ（変更なし）
uv run python scripts\sync_houdini21_db.py --dry-run

# 同期＋ChromaDBインデックス化
uv run python scripts\sync_houdini21_db.py --index
```

> **注意:** このスクリプトも `load_dotenv()` を使用しません。`NOTION_API_KEY` は PowerShell セッションで直接セットしてください。

| オプション | 動作 |
|-----------|------|
| （なし） | houdini21DB の全ページを `localRAG/houdini21/` へ同期 |
| `--dry-run` | 書き出し対象のページ一覧を表示するのみ（ファイル変更なし） |
| `--index` | 同期後に ChromaDB へのインデックス化も実行 |

---

## 4. ドキュメント分割パイプライン

`document_pipeline.py` は、Claude API を使わずに任意のファイルを RAG 検索可能な状態にするためのドキュメント追加パイプラインです。外部 API を一切使わず、インターネット不要で完結します。

```
【入力】 PDF / Word / PowerPoint / Markdown / テキスト
      ↓
【変換】 markitdown（ローカル実行・外部API不要）
      ↓
【チャンキング】 見出しベース（デフォルト）or セマンティック（トークンベース）
      ↓
【出力】 localRAG/namespace/xxx.md
      ↓
【自動インデックス化】 auto_index.py が検知 → ChromaDB + multilingual-e5-large
      ↓
【検索可能】 Unity / Houdini / ブラウザから RAG クエリ
```

### 4.1 使い方

```powershell
# PDF を tool_docs namespace に追加
python scripts\document_pipeline.py add path/to/design.pdf --namespace tool_docs

# Word ファイルを research namespace に追加
python scripts\document_pipeline.py add path/to/report.docx --namespace research

# ディレクトリごと追加
python scripts\document_pipeline.py add path/to/docs_folder/ --namespace team_notes

# 追加と同時にインデックス化
python scripts\document_pipeline.py add path/to/file.pdf --namespace tool_docs --index

# 書き込まずに確認だけ（dry-run）
python scripts\document_pipeline.py add path/to/file.pdf --dry-run

# インデックス化だけ実行
python scripts\document_pipeline.py index

# テンプレート生成（meeting / research / tool / knowledge）
python scripts\document_pipeline.py template meeting --output localRAG\team_notes\
```

### 4.2 対応ファイル形式

| 形式 | 変換方法 | 備考 |
|------|---------|------|
| `.md` / `.txt` | そのまま読み込み | 最も高品質 |
| `.pdf` | markitdown で Markdown 変換 | テキストベース PDF は良好、スキャン PDF は注意 |
| `.pptx` / `.ppt` | markitdown でスライドテキスト抽出 | 図・画像の内容は取れない |
| `.docx` / `.doc` | markitdown で Markdown 変換 | 表・箇条書きも対応 |
| `.xlsx` / `.xls` | markitdown でテーブル変換 | データ量が多いと分割数が増える |
| `.html` | markitdown で本文抽出 | ナビ・広告は除去される |

### 4.3 チャンキング戦略

#### heading ベース（デフォルト・推奨）

```
# 見出し1
  → チャンク 1: "見出し1 > ..." という heading path 付きで保存

## 見出し2
  → チャンク 2: "見出し1 > 見出し2" という heading path 付きで保存
```

メリット: 意味的にまとまったチャンクになる／検索時に「どのセクションの話か」が分かる／長すぎるセクションは自動的に段落で再分割される。

チャンクサイズの調整：

```powershell
# チャンクを小さくする（より細かく検索したい場合）
python scripts\document_pipeline.py add file.pdf --max-chunk 400 --overlap 60

# チャンクを大きくする（文脈を広く持たせたい場合）
python scripts\document_pipeline.py add file.pdf --max-chunk 1200 --overlap 100
```

**推奨値:** 技術ドキュメント `--max-chunk 600` ／ ミーティングメモ `--max-chunk 400` ／ 長文レポート `--max-chunk 1000`

#### SemanticChunker（トークンベース・`--semantic` フラグ）

ドキュメントインデックス化時に `--semantic` フラグを付けると、見出し単位ではなくトークン単位のスライディングウィンドウ分割を使います。

```
chunk_size=512 トークン（単語で近似）
overlap=64 トークン（前後のコンテキストを保持）
各チャンクに SHA-256 source_hash を付与
```

```powershell
# 従来の見出しベース分割
python scripts\document_pipeline.py localRAG\tutorials\houdini_basics.md

# セマンティック分割（512トークン/64重複）
python scripts\document_pipeline.py --semantic localRAG\tutorials\houdini_basics.md
```

### 4.4 Namespace の選び方

| Namespace | 用途 | 例 |
|-----------|------|-----|
| `tool_docs` | ツール・ライブラリのドキュメント | Unity マニュアル、API リファレンス |
| `game_info` | ゲーム・プロジェクト情報 | 仕様書、デザインドキュメント |
| `research` | 調査・研究メモ | 論文要約、技術調査 |
| `team_notes` | チームの議事録・共有メモ | ミーティングメモ、決定事項 |
| `personal_notes` | 個人メモ | 学習メモ、アイデア |
| `houdini21` | Houdini 21 専用ドキュメント | `sync_houdini21_db.py` で Notion から同期 |

### 4.5 Claude なしで高品質ドキュメントを書くコツ

Claude が使えない状況でも、テンプレート（`localRAG/_templates/` 配下の `meeting.md` / `research.md` / `tool_doc.md` / `knowledge.md`）に沿って書くだけで高品質なドキュメントになります。

1. **見出しを必ず使う**（`#`, `##`, `###`）— 見出しベースで分割されるため検索精度が大幅に向上する
2. **1 ファイル = 1 トピック**にする — 話題を混ぜない
3. **frontmatter を書く** — `namespace`, `tags`, `status` を正確に記入すると管理が楽になる
4. **具体的なキーワードを本文に含める** — 実際に検索しそうな言葉で書く

| 作業 | Claude 使う | Claude なし |
|------|------------|------------|
| ファイル変換（PDF→MD等） | 不要 | markitdown で自動 |
| チャンキング | 不要 | heading ベース自動分割 |
| 埋め込み生成 | 不要 | multilingual-e5-large（ローカル） |
| ドキュメントの整理・要約 | あると便利 | テンプレートで代替 |
| 検索結果の回答生成 | 使用（rag_local_bridge）| ローカルLLM(Ollama)で代替可 |

---

## 5. 使い方（2つの経路）

検索エンジンへのアクセス経路は2つあります。用途に応じて使い分けてください。

### 5.1 Claude Desktop に MCP サーバーとして直接登録する

個人で Claude Desktop / Claude Code から直接検索したい場合に使います。

`claude_desktop_config.json`（Everythingで検索、またはパス `%APPDATA%\Claude\claude_desktop_config.json`）を以下に書き換えます。

```json
{
  "mcpServers": {
    "local-rag-server": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "C:\\Users\\YOUR_USERNAME\\Desktop\\GameDevelopment\\DevelopmentRAGEnvironment",
        "python",
        "scripts/rag_mcp_server.py"
      ]
    }
  }
}
```

Claude Desktop を完全再起動後、設定画面で `running` になれば完了です。動作確認：

```
local-rag-server でインデックス内のドキュメント数を確認して
local-rag-server で「Houdini VEX」について検索して
```

### 5.2 HTTP ブリッジ経由（Unity / Houdini 向け）

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
uv run python scripts\rag_local_bridge.py
# → localhost:8766 で待機開始
```

Unity・Houdini の RAG Chatbot UI から `localhost:8766` に接続して使用します（詳細は「[7. UI実装詳細](#7-ui実装詳細)」参照）。動作確認：

```powershell
Invoke-RestMethod http://localhost:8766/health
```

アクセス先一覧：

| URL | 用途 |
|-----|------|
| `http://localhost:8766/health` | サーバー状態確認 |
| `http://localhost:8766/admin` | 管理者画面（ユーザー管理） |
| `http://localhost:8766/ui` | ユーザーチャット画面 |
| `http://localhost:8766/query` | Unity/Houdini 向け API |

なぜブリッジが必要か：ローカルの検索エンジン（`rag_service.py`）は Python の関数として直接呼び出せますが、Unity（C#）や Houdini（別プロセスの Python）からは直接 import できません。`rag_local_bridge.py` が `LocalRAGClient`（インプロセスで `rag_service.py` を直接呼び出すクラス）経由でこの変換役を担います。HTTP ならどの言語でも数行で書けるため、中継サーバーを1つ作るほうが全体の実装コストが低くなります。

提供するエンドポイント一覧：

| エンドポイント | 処理内容 |
|--------------|---------|
| `GET /health` | ブリッジが生きているかチェック。インデックス済みドキュメント数も返す |
| `POST /query` | 質問を受け取り、`rag_service.py` で検索 → Claude Haiku が回答を生成 → JSON で返す |
| `GET /graph` | `rag_graph_export.py` をサブプロセスとして実行し、グラフ JSON を返す（依存関係分離のため直接インポートしない） |

### 5.3 Ollama による完全オフライン化（オプション）

Claude API なしで回答生成もしたい場合は Ollama を使います。

```powershell
winget install Ollama.Ollama
ollama pull llama3.2
ollama pull phi4      # 軽量・高速
```

Ollama の API は OpenAI 互換のため、`rag_local_bridge.py` の `_call_claude()` の endpoint を `http://localhost:11434/v1/chat/completions` に変更すれば Claude API 不要になります。

---

## 6. セキュリティ機能

NIST SP 800-207（Zero Trust Architecture）に基づいた機能が `scripts/` に追加されています。ローカルブリッジ（`rag_local_bridge.py`）を起動すると自動的に有効になります（5.1 の MCP 直接登録では未適用）。

### 6.1 監査ログ（`scripts/audit_logger.py`）— テネット7「可能な限り情報収集」

ローカル RAG への全クエリが `logs/rag_audit.jsonl` に JSON Lines 形式で記録されます。クエリ内容はプライバシー保護のため SHA-256 でハッシュ化して保存されます。

```json
{"timestamp":"2026-06-29T12:00:00.000Z","session_id":"abc12345","user_role":"developer","action":"search","namespace":"tool_docs","query_hash":"a1b2c3d4e5f6a7b8","result_count":5,"latency_ms":123,"allowed":true}
```

確認方法：

```powershell
Get-Content logs\rag_audit.jsonl -Tail 10
```

### 6.2 PEP アクセス制御（`scripts/pep.py`）— テネット3「最小権限」

ローカルブリッジに送るリクエストの `user_role` フィールドに応じて、検索できる名前空間が制限されます。

| user_role | アクセス可能な名前空間 |
|-----------|----------------------|
| `admin` | すべて（houdini21 含む） |
| `developer` | tool_docs / game_info / research / team_notes / houdini21 |
| `user` | tool_docs / game_info / research / houdini21 |

### 6.3 理解度スコア（`scripts/score_engine.py`）

ユーザーのトピック別習熟度スコアが `data/auth.db`（SQLite）に自動的に蓄積され、スコアに応じて RAG の検索範囲が自動調整されます。

| スコア範囲 | 検索する名前空間 | 応答レベル |
|-----------|----------------|-----------|
| 0.0〜0.29（初心者） | tool_docs のみ | ステップバイステップ |
| 0.3〜0.69（中級者） | tool_docs + game_info + research | 概念説明 |
| 0.7〜1.0（上級者） | research + team_notes | リファレンスのみ |

スコアは正解・理解時に +0.1、不正解・詰まった時に -0.05 で更新されます。ブリッジ起動後、`/api/score` エンドポイントでスコアを確認・更新できます。

```powershell
# スコア確認
Invoke-RestMethod "http://localhost:8766/api/score?user_id=my_user" `
  -Headers @{"X-API-Key"="(APIキー)"}

# スコア更新（success=true で +0.1、false で -0.05）
Invoke-RestMethod "http://localhost:8766/api/score" -Method POST `
  -Headers @{"X-API-Key"="(APIキー)"} `
  -ContentType "application/json" `
  -Body '{"user_id":"my_user","topic":"SOP","success":true}'
```

### 6.4 秘密情報の保存ルール（共通方針）

| 情報の種類 | 保存場所 | 補足 |
|-----------|---------|------|
| Anthropic API キー | 環境変数のみ（`ANTHROPIC_API_KEY`） | コードに絶対書かない |
| ローカルブリッジのポート番号 | コードのデフォルト値（8766） | ローカルネットワーク内のみ到達可能 |

`.env` ファイルは誤って Git にコミットされるリスクがあるため、このプロジェクトでは使用しません。API キーはすべて OS の環境変数に保存します（`load_dotenv()` は呼び出していません）。

---

## 7. UI実装詳細

LocalRAG への接続は Unity EditorWindow と Houdini Python Panel の両方からサポートされています。共通アーキテクチャとして `IRAGClient` インターフェースを介し、Cloud/Local どちらのモードでも同じ呼び出しコードで動作します。

```csharp
public interface IRAGClient
{
    Task<RAGResponse> QueryAsync(string query, string dbKey);
    Task<bool> HealthCheckAsync();
}
```

**なぜインターフェースを使うか:** ウィンドウ側は「`QueryAsync` を呼べばいい」とだけ知っていればよく、相手がクラウドかローカルかを意識する必要がなくなります。モードを切り替えても `RAGChatbotWindow.cs` のコードを変える必要がありません。

### 7.1 LocalRAGClient（Unity: `Assets/Editor/RAGChatbot/LocalRAGClient.cs`）

`localhost:8766` で動いているローカルブリッジサーバーに HTTP POST を送ります。

- `UnityWebRequest` を使って HTTP 通信（ローカルなので HTTPS 不要）
- リクエスト先: `http://localhost:{port}/query`（ポート番号はデフォルト 8766、Settings タブで変更可能）
- 送るデータ: 質問テキスト・Namespace（フォルダ名）
- 受け取るデータ: 検索結果・AI の回答テキスト
- `RateAsync` は no-op（Local モードには 👍/👎 評価先となる memoryId が存在しないため、評価ボタン自体が表示されない）

### 7.2 Houdini Python Panel での Local モード

`houdini/python_panels/rag_chatbot.py` が Unity 版と同じく Chat / Graph / Settings の3タブ構成で実装されています。Local モードでは `QueryWorker`（QThread）が別スレッドで `localhost:8766` への HTTP リクエストを行い、UI をブロックしません。Local モードを選択すると `BridgeStartWorker`（QThread）がローカルブリッジプロセスを自動起動します。設定は `%USERPROFILE%\.houdini\rag_chatbot_config.json` に JSON 形式で保存されます。

グラフタブ（`graph_view.py`）は `GraphFetchWorker`（QThread）が `/graph` エンドポイントに非同期でリクエストを送り、`NodeItem` / `EdgeItem`（PySide6 の `QGraphicsView`）として描画します。

### 7.3 rag_local_bridge.py の内部設計

`scripts/rag_local_bridge.py` は Python の `FastAPI` フレームワークで動く軽量なサーバーです。

```
Unity / Houdini
  ↓ HTTP POST（Unity / Houdini が話せる言語）
rag_local_bridge.py（localhost:8766）
  ↓ LocalRAGClient（インプロセス直接呼び出し）
rag_service.py（ローカル検索エンジン、ChromaDB ベース）
```

`LocalRAGClient` クラス（ブリッジ内部）は `rag_service.py` を**インプロセスで直接呼び出す**クラスです（旧 `MCPClient` の stdio JSON-RPC 方式を置き換えたもの）。`create_rag_service_from_env()` で生成したサービスインスタンスを直接保持し、サブプロセスを起動しません。検索・インデックス確認などの処理は Python の関数呼び出しとして直接実行されるため、JSON-RPC のシリアライズ/デシリアライズが不要で高速です。`GET /health` は保持しているサービスインスタンスに対してドキュメント数取得を直接呼び出して生存確認します。

なお `GET /graph` は `rag_graph_export.py` を `uv run` でサブプロセス実行して結果を受け取ります。直接インポートせずサブプロセスにしている理由は依存関係の分離（ブリッジとグラフ計算のライブラリ環境を分けるため）です。

### 7.4 情報抽出度・評価機能について

抽出度サマリー UI（引用バッジ・プログレスバー）、👍/👎 評価機能（priority 重み付け）は **クラウドRAG専用**の機能です（GAS `gas_cloud_rag.js` の `parseExtractionRate_()` / RAG_Memory シート連携）。LocalRAG では memoryId が存在しないため評価ボタンは表示されません。詳細は [docs/cloud-rag.md](cloud-rag.md) を参照してください。

---

## 8. 配布ガイド

新しいPCまたは別のメンバーへ LocalRAG 環境を渡す場合の手順です（所要時間: 約15〜20分、モデルダウンロード込み）。2026-06-30 の構成変更により、クローンするリポジトリは `DevelopmentRAGEnvironment` 1つだけで完結します（外部リポジトリのアクセス権は不要）。

### 配布物チェックリスト

渡す側が事前に準備するもの：

- [ ] `DevelopmentRAGEnvironment` リポジトリへのアクセス（GitHub）。これ1つで完結
- [ ] Obsidian vault フォルダ（`localRAG/` ディレクトリ）の共有 ※任意

### 受け取る側のセットアップ手順

**Step 1 — 前提ソフトウェアのインストール**

| ソフトウェア | インストール方法 | 確認コマンド |
|-------------|----------------|-------------|
| Git | https://git-scm.com/ | `git --version` |
| uv | `winget install --id=astral-sh.uv -e` | `uv --version` |
| Claude Desktop | https://claude.ai/download | アプリ起動で確認 |
| Obsidian | https://obsidian.md/ | アプリ起動で確認 |

**Step 2 — リポジトリのクローン**

```powershell
cd C:\Users\YOUR_USERNAME\Desktop\GameDevelopment
git clone https://github.com/manato1201/DevelopmentRAGEnvironment
```

**Step 3 — 依存パッケージの同期**

```powershell
cd DevelopmentRAGEnvironment
uv sync
```

**Step 4〜9** — 環境変数の設定（任意）→ Obsidian vault の設定 → 初回インデックス化 → watchdog 起動 → Claude Desktop への MCP 登録 → 動作確認。手順の詳細は「[3. セットアップ](#3-セットアップ)」「[5. 使い方](#5-使い方2つの経路)」と同一です。

> 初回は `intfloat/multilingual-e5-large`（約1.2GB）をダウンロードするため時間がかかります。

### 再配布時の注意点

- `data/chroma/`（ベクトルDB）は git 管理外（`.gitignore`）。別PCへのDB移行は次のコマンドでバックアップ・移行できます。
  ```powershell
  Compress-Archive -Path .\data\chroma -DestinationPath chroma_backup.zip
  ```
- API キー等は環境変数のみで管理し、ファイルに書き出さない（`.env` は使用しない方針）
- `localRAG/` 内のノートは個人情報を含む可能性があるため配布範囲を確認する

---

## 9. 設計の経緯

現在の構成（ChromaDB + 単一リポジトリ完結型）に至るまでの設計史です。詳細な手順はすべて現行アーキテクチャでは不要になっていますが、根底にある設計思想は今も有効なため概要のみ残します。

### 9.1 pgvector → ChromaDB 移行（2026-06-16）

LocalRAG の検索基盤は当初 PostgreSQL + pgvector（Docker 必須、WSL2 + Docker Desktop でセットアップ）でした。Docker コンテナの起動・停止管理や WSL2 環境構築の手間が大きく、`docker run --name postgres-pgvector ...` のような複数ステップが必要でした。

2026-06-16 に ChromaDB（ファイルベース、Docker 不要）へ移行し、セットアップが「`uv add chromadb` だけ」まで簡略化されました。データ構造の対応関係は以下の通りです。

| pgvector（旧） | ChromaDB（新） |
|--------------|--------------|
| `documents` テーブル | コレクション（namespace単位） |
| `namespace` カラム | コレクション名（フォルダ名が自動マッピング） |
| `embedding (vector)` | `embeddings` |
| `ivfflat` インデックス | `HNSW（hnswlib）` |

### 9.2 Obsidian を管理・可視化インターフェースにする設計思想

LocalRAG 運用初期から一貫している考え方として、**「Obsidian vault = RAG のソースディレクトリ」**として扱うことで、ファイルツリー自体をインデックス対象の一覧として可視化する、というものがあります。

課題として「何がインデックスされているか分からない」「namespace 別の状態が把握できない」「更新漏れが発生しやすい」があり、これを解決するために以下の設計が採用されました（現行の `scripts/auto_index.py` に引き継がれています）。

- **frontmatter による鮮度管理**: 各ノートに `status`（`active` / `stale` / `archived`）・`expires`（有効期限）・`rag_indexed` をYAML frontmatterで持たせ、期限切れノートは自動的に `stale` へ遷移させる
- **ダッシュボードノートの自動生成**: `_rag_dashboard/index_status.md`（namespace別件数・要確認ファイル一覧）、`namespace_map.md`（ファイル一覧とインデックス済み状態）を watchdog がインデックス化のたびに自動更新する
- **運用フロー**: Obsidian でノート編集 → watchdog が自動検知・差分インデックス化 → ダッシュボードノートが自動更新 → Obsidian 上で状態確認、という一連の流れを成立させる

旧資料が前提としていた WSL パス（`~/mcp-rag-server`、`MCP_RAG_DIR` 等）や `.env` への PostgreSQL 接続情報の記述は現行の Windows ネイティブ構成では使われませんが、frontmatter ベースの鮮度管理とダッシュボード自動生成という設計自体は現行の `scripts/auto_index.py` にそのまま受け継がれています。

### 9.3 Houdini ヘルプドキュメントの RAG 化（歴史的取り組み）

Houdini 20.5/21.0 のヘルプドキュメント（7,810ファイル、zip展開後 .txt）を pgvector + MCP で検索可能にする取り組みが行われていました。WSL2 + Docker + PostgreSQL/pgvector 環境で、ノード・式・コマンド・VEX 等のヘルプ zip を `data/source/` に展開し、`uv run python -m src.cli index` で約4〜6時間かけてインデックス化していました。

この取り組み自体は pgvector ベースの旧構成に依存しており、現行の ChromaDB + ベンダー統合構成では同じ手順は使われません。Houdini 関連ドキュメントの現行の扱いは、Notion houdini21DB から `sync_houdini21_db.py` で `localRAG/houdini21/` に同期する形に置き換わっています（[3.8](#38-houdini21db-を-localrag-に同期するsync_houdini21_dbpy) 参照）。「2段階推論パターン」（ノード名を先に列挙させてから個別に検索させると精度が上がる、等の問い合わせ工夫）は現在も Claude Desktop 経由の検索で有効な考え方です。

---

## 10. トラブルシューティング

### `uv sync` で sentencepiece のビルドが失敗する

`pyproject.toml` の `requires-python` が `>=3.13` になっているか確認してください。Python 3.13 以降であれば wheel が提供されています。

### `'NoneType' object has no attribute 'get_or_create_collection'`

`vector_database.py` の `initialize_database()` が `self.connect()` を呼んでいるか確認してください（`scripts/vector_database.py` は変更していなければ問題ありません）。

### ChromaDB のコレクション名エラー (`Got: C:\`)

`SOURCE_DIR` 環境変数が正しく設定されていません。絶対パスで設定されているか確認してください。デフォルトでは `localRAG/` が使われます。

### watchdog が反応しない

```powershell
# uv run 経由で起動されているか確認
Get-Process python
# 止まっていれば再起動
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python scripts/auto_index.py"
```

### インデックス化で `_rag_dashboard` が処理される

`_namespace_from_path` が `SOURCE_DIR` 環境変数を読んで相対パスに変換しているか確認してください。

```powershell
# 処理済みキャッシュをクリアして再インデックス
Remove-Item -Recurse -Force localRAG\_rag_dashboard\.processed
uv run python scripts\rag_cli.py index
```

### 検索時に `KeyError: 'chunk_index'` / `KeyError: 'document_id'` が出る

`scripts/vector_database.py` の `search()` / `get_adjacent_chunks()` / `get_document_by_file_path()` がこれらのキーをトップレベルで返しているか確認してください。

### 日本語クエリが文字化け / `TextEncodeInput` エラー（MCP 登録時のみ）

`scripts/rag_mcp_server.py` の冒頭に UTF-8 パッチ（`io.TextIOWrapper`）が含まれているか確認してください。Windows のデフォルトエンコーディングは CP932 のため、これがないと stdin/stdout で日本語が文字化けします。

```
# エラーメッセージ例
TextEncodeInput must be Union[TextInputSequence, ...]
受信クエリ: '繝輔か繝ｼ繝...'  ← 文字化けしている
```

### インデックス化後も検索結果が増えない

ChromaDB の HNSW インデックスはメモリにロードされるため、別プロセスが upsert しても起動中のサーバー側には反映されません。**インデックス化後は必ず MCP サーバー / ブリッジを再起動してください。**

- Claude Desktop: タスクトレイから完全終了 → 再起動
- `rag_local_bridge.py`: プロセスを再起動

### その他の症状一覧

| 症状 | 原因 | 対処 |
|------|------|------|
| `uv sync` でエラー | Python バージョン不一致 | `python --version` で確認。3.13+ が必要 |
| `chromadb` インストール失敗 | Visual C++ ランタイム不足 | Microsoft Visual C++ Redistributable をインストール |
| 埋め込みが遅い | CPU 推論（正常） | 初回は数分かかる。2回目以降はキャッシュで高速 |
| `401 Unauthorized` | API キー未設定 or 誤り | `auth_manager.py list` でユーザー確認 |
| `503 RAGService が起動していません` | `rag_service.py` の初期化に失敗した | ログを確認しブリッジを再起動 |
| RSS 収集でエラー | feedparser 未インストール | `pip install feedparser` |

---

## 参考リンク

| リソース | URL |
|----------|-----|
| karaage0703/mcp-rag-server（ベンダー統合元・オリジナル） | https://github.com/karaage0703/mcp-rag-server |
| mcp-rag-server 解説記事 | https://zenn.dev/mkj/articles/30eeb69bf84b3f |
| uv — Python パッケージマネージャー | https://docs.astral.sh/uv/ |
| multilingual-e5-large（埋め込みモデル） | https://huggingface.co/intfloat/multilingual-e5-large |
