# ローカルRAG環境セットアップガイド（独立版）

**対象:** Windows 11（WSL2・Docker不要）
**所要時間:** 約15分
**更新日:** 2026-06-30

> **変更履歴:**
> - 2026-06-30 — 外部リポジトリ `mcp-rag-server` への依存を解消。検索エンジン一式（`document_processor.py` / `embedding_generator.py` / `rag_service.py` / `mcp_server.py`）をこのリポジトリに統合し、単体で完結する構成に変更。
> - 2026-06-16 — pgvector（Docker必須）からChromaDB（Dockerなし）に移行。旧手順は `docs/local-rag-chromadb-migration.md` を参照。

---

## 目次

1. [前提条件](#1-前提条件)
2. [uv のインストール](#2-uv-のインストール)
3. [依存パッケージの同期](#3-依存パッケージの同期)
4. [環境変数の設定](#4-環境変数の設定)
5. [Obsidian vault の設定](#5-obsidian-vault-の設定)
6. [インデックス化](#6-インデックス化)
7. [watchdog（自動インデックス化）の起動](#7-watchdog-の起動)
8. [使い方（2つの経路）](#8-使い方)
9. [動作確認](#9-動作確認)
10. [トラブルシューティング](#10-トラブルシューティング)
11. [セキュリティ強化機能](#11-セキュリティ強化機能)

---

## 1. 前提条件

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

---

## 2. uv のインストール

PowerShell で実行：

```powershell
winget install --id=astral-sh.uv -e
```

確認：

```powershell
uv --version
```

---

## 3. 依存パッケージの同期

このリポジトリの `pyproject.toml` に検索エンジンの依存（ChromaDB・sentence-transformers・rank-bm25・sudachipy 等）が含まれています。クローン不要・コピー不要で、`uv sync` だけで完結します。

```powershell
cd C:\Users\YOUR_USERNAME\Desktop\GameDevelopment\DevelopmentRAGEnvironment
uv sync
```

> 初回は `sentence-transformers` 等の依存ダウンロードで数分かかります。

---

## 4. 環境変数の設定

`.env` ファイルは使用しません（`load_dotenv()` 非対応）。必要な環境変数は OS の環境変数として設定するか、起動コマンドの前に付与してください。

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

デフォルト値のままで問題なければ、この手順はスキップして構いません。

---

## 5. Obsidian vault の設定

Obsidian を開き、`localRAG\` フォルダを vault として登録する。

```
DevelopmentRAGEnvironment\localRAG\   ← Obsidian でこのフォルダを開く
├── chat_logs\        ← namespace: chat_logs
├── tutorials\        ← namespace: tutorials
├── personal_notes\   ← namespace: personal_notes
│   ├── progress\
│   └── ideas\
├── private_docs\     ← namespace: private_docs
├── _rag_dashboard\   ← 管理専用（インデックス対象外）
└── _templates\       ← テンプレート（インデックス対象外）
```

**テンプレートプラグインの設定:**

設定 → コアプラグイン → テンプレート: オン
設定 → テンプレート → テンプレートフォルダの場所: `_templates`

---

## 6. インデックス化

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

差分のみインデックス化する場合:
```powershell
uv run python scripts\rag_cli.py index --incremental
```

ドキュメント数を確認:
```powershell
uv run python scripts\rag_cli.py count
```

> **スキップされるフォルダ:** `_rag_dashboard\`・`_templates\`・`.processed\` は自動除外される。

---

## 7. watchdog の起動

```powershell
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python scripts/auto_index.py"
```

起動後は Obsidian でノートを保存するたびに自動インデックス化される。
`_rag_dashboard\index_status.md` と `namespace_map.md` が自動更新されることで確認できる。

---

## 8. 使い方

検索エンジンへのアクセス経路は2つあります。用途に応じて使い分けてください。

### 8.1 Claude Desktop に MCP サーバーとして直接登録する

個人で Claude Desktop / Claude Code から直接検索したい場合。

`claude_desktop_config.json`（Everythingで検索）を以下に書き換える：

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

Claude Desktop を完全再起動後、設定画面で `running` になれば完了。

### 8.2 HTTP ブリッジ経由（Unity / Houdini 向け）

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
uv run python scripts\rag_local_bridge.py
# → localhost:8766 で待機開始
```

Unity・Houdini の RAG Chatbot UI から `localhost:8766` に接続して使用する。詳細は [README.md](../README.md) を参照。

---

## 9. 動作確認

### MCP 登録（8.1）の場合

Claude Desktop または Claude Code で以下を実行：

```
local-rag-server でインデックス内のドキュメント数を確認して
```

```
local-rag-server で「Houdini VEX」について検索して
```

### HTTP ブリッジ（8.2）の場合

```powershell
Invoke-RestMethod http://localhost:8766/health
```

---

## 10. トラブルシューティング

### `uv sync` で sentencepiece のビルドが失敗する

`pyproject.toml` の `requires-python` が `>=3.13` になっているか確認。Python 3.13 以降であれば wheel が提供されている。

### `'NoneType' object has no attribute 'get_or_create_collection'`

`vector_database.py` の `initialize_database()` が `self.connect()` を呼んでいるか確認（`scripts/vector_database.py` は変更していなければ問題なし）。

### ChromaDB のコレクション名エラー (`Got: C:\`)

`SOURCE_DIR` 環境変数が正しく設定されていない。絶対パスで設定されているか確認。デフォルトでは `localRAG/` が使われる。

### watchdog が反応しない

```powershell
# uv run 経由で起動されているか確認
Get-Process python
# 止まっていれば再起動
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python scripts/auto_index.py"
```

### インデックス化で `_rag_dashboard` が処理される

`_namespace_from_path` が `SOURCE_DIR` 環境変数を読んで相対パスに変換しているか確認。

```powershell
# 処理済みキャッシュをクリアして再インデックス
Remove-Item -Recurse -Force localRAG\_rag_dashboard\.processed
uv run python scripts\rag_cli.py index
```

### 検索時に `KeyError: 'chunk_index'` / `KeyError: 'document_id'` が出る

`scripts/vector_database.py` の `search()` / `get_adjacent_chunks()` / `get_document_by_file_path()` が
これらのキーをトップレベルで返しているか確認。

### 日本語クエリが文字化け / `TextEncodeInput` エラー（MCP 登録時のみ）

`scripts/rag_mcp_server.py` の冒頭に UTF-8 パッチ（`io.TextIOWrapper`）が含まれているか確認。Windows のデフォルトエンコーディングは CP932 のため、これがないと stdin/stdout で日本語が文字化けする。

```
# エラーメッセージ例
TextEncodeInput must be Union[TextInputSequence, ...]
受信クエリ: '繝輔か繝ｼ繝...'  ← 文字化けしている
```

### インデックス化後も検索結果が増えない

ChromaDB の HNSW インデックスはメモリにロードされるため、別プロセスが upsert しても起動中のサーバー側には反映されない。
**インデックス化後は必ず MCP サーバー / ブリッジを再起動する。**

Claude Desktop: タスクトレイから完全終了 → 再起動
`rag_local_bridge.py`: プロセスを再起動

---

## 11. セキュリティ強化機能

NIST SP 800-207（Zero Trust Architecture）に基づいた機能が `scripts/` に追加されています。ローカルブリッジ（`rag_local_bridge.py`）を起動すると自動的に有効になります（8.1 の MCP 直接登録では未適用）。

### 11.1 監査ログ（audit_logger.py）

ローカル RAG への全クエリが `logs/rag_audit.jsonl` に記録されます。

```json
{"timestamp":"2026-06-29T12:00:00.000Z","action":"search","namespace":"tool_docs","query_hash":"a1b2c3d4","result_count":5,"latency_ms":120,"allowed":true}
```

確認方法：
```powershell
Get-Content logs\rag_audit.jsonl -Tail 10
```

### 11.2 PEP アクセス制御（pep.py）

ローカルブリッジに送るリクエストの `user_role` フィールドに応じて、検索できる名前空間が制限されます。

| user_role | アクセス可能な名前空間 |
|-----------|----------------------|
| `admin` | すべて |
| `developer` | tool_docs / game_info / research / team_notes / houdini21 |
| `user` | tool_docs / game_info / research / houdini21 |

### 11.3 セマンティック分割（document_pipeline.py）

ドキュメントインデックス化時に `--semantic` フラグを付けると、見出し単位ではなくトークン単位のオーバーラップ分割を使います。

```powershell
# 従来の見出しベース分割
python scripts\document_pipeline.py localRAG\tutorials\houdini_basics.md

# セマンティック分割（512トークン/64重複）
python scripts\document_pipeline.py --semantic localRAG\tutorials\houdini_basics.md
```

### 11.4 理解度スコア（score_engine.py）

ユーザーのトピック別習熟度スコアが `data/auth.db` に自動的に蓄積されます。ブリッジ起動後、`/api/score` エンドポイントでスコアを確認・更新できます。

```powershell
# スコア確認（ブリッジ起動後）
Invoke-RestMethod "http://localhost:8766/api/score?user_id=my_user" `
  -Headers @{"X-API-Key"="(APIキー)"}

# スコア更新（success=true で +0.1、false で -0.05）
Invoke-RestMethod "http://localhost:8766/api/score" -Method POST `
  -Headers @{"X-API-Key"="(APIキー)"} `
  -ContentType "application/json" `
  -Body '{"user_id":"my_user","topic":"SOP","success":true}'
```
