# ローカルRAG環境セットアップガイド（ChromaDB版）

**対象:** Windows 11（WSL2・Docker不要）  
**所要時間:** 約20分  
**更新日:** 2026-06-29

> **変更履歴:** 2026-06-16 — pgvector（Docker必須）からChromaDB（Dockerなし）に移行。  
> 旧手順は `docs/local-rag-chromadb-migration.md` を参照。

---

## 目次

1. [前提条件](#1-前提条件)
2. [uv のインストール](#2-uv-のインストール)
3. [mcp-rag-server セットアップ](#3-mcp-rag-server-セットアップ)
4. [ChromaDB パッチの適用](#4-chromadb-パッチの適用)
5. [Obsidian vault の設定](#5-obsidian-vault-の設定)
6. [インデックス化](#6-インデックス化)
7. [watchdog（自動インデックス化）の起動](#7-watchdog-の起動)
8. [Claude Desktop への登録](#8-claude-desktop-への登録)
9. [動作確認](#9-動作確認)
10. [トラブルシューティング](#10-トラブルシューティング)
11. [セキュリティ強化機能（2026-06-29 追加）](#11-セキュリティ強化機能)

---

## 1. 前提条件

| 項目 | 要件 |
|------|------|
| OS | Windows 11 |
| Docker | **不要** |
| WSL2 | **不要** |
| Python | uv が自動管理（3.12 を使用） |
| Claude Desktop | インストール済み |
| Obsidian | インストール済み |
| ディスク空き | 5GB 以上推奨 |

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

## 3. mcp-rag-server セットアップ

```powershell
cd C:\Users\YOUR_USERNAME\Desktop\GameDevelopment
git clone https://github.com/karaage0703/mcp-rag-server
cd mcp-rag-server

# Python 3.12 で仮想環境を作成（sentencepiece の wheel 問題を回避）
uv sync --python 3.12
uv add chromadb watchdog pyyaml
```

> **注意:** `uv sync` のみだと Python 3.13 が選択され sentencepiece のビルドが失敗する。
> 必ず `--python 3.12` を付けること。

---

## 4. ChromaDB パッチの適用

### Step 1 — vector_database.py を差し替え

```powershell
copy ..\DevelopmentRAGEnvironment\scripts\vector_database.py src\vector_database.py
```

### Step 2 — rag_tools.py を編集

`src\rag_tools.py` を開き、`create_rag_service_from_env` 関数内の PostgreSQL ブロックを以下に置き換える：

**変更前:**
```python
vector_database = VectorDatabase(
    {
        "host":     os.environ.get("POSTGRES_HOST",     "localhost"),
        "port":     os.environ.get("POSTGRES_PORT",     "5432"),
        "user":     os.environ.get("POSTGRES_USER",     "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", "password"),
        "database": os.environ.get("POSTGRES_DB",       "ragdb"),
    }
)
```

**変更後:**
```python
vector_database = VectorDatabase(
    {
        "chroma_path":   os.environ.get("CHROMA_PATH",   "./data/chroma"),
        "embedding_dim": os.environ.get("EMBEDDING_DIM", "1024"),
    }
)
```

### Step 3 — .env を設定

```powershell
copy ..\DevelopmentRAGEnvironment\.env.example .env
```

### Step 4 — main.py に Windows UTF-8 対応パッチを適用

`src\main.py` を開き、ファイル先頭の `import sys` の直後（dotenv/argparse の `from` より前）に以下を追加：

```python
import io

# Force UTF-8 for stdin/stdout on Windows (default is CP932, which corrupts Japanese)
if hasattr(sys.stdin, 'buffer'):
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
```

> **なぜ必要か:** Windows のデフォルトエンコーディングは CP932。MCP は stdin/stdout で JSON を読み書きするため、日本語クエリが文字化けして `TextEncodeInput must be Union[TextInputSequence, ...]` エラーになる。

`.env` の内容（`YOUR_USERNAME` を自分のユーザー名に変更）：

```env
CHROMA_PATH=./data/chroma

SOURCE_DIR=C:\Users\YOUR_USERNAME\Desktop\GameDevelopment\DevelopmentRAGEnvironment\localRAG
PROCESSED_DIR=C:\Users\YOUR_USERNAME\Desktop\GameDevelopment\DevelopmentRAGEnvironment\localRAG\_rag_dashboard\.processed

EMBEDDING_MODEL=intfloat/multilingual-e5-large
EMBEDDING_DIM=1024
EMBEDDING_PREFIX_QUERY=query:
EMBEDDING_PREFIX_EMBEDDING=passage:
```

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
cd C:\Users\YOUR_USERNAME\Desktop\GameDevelopment\mcp-rag-server
uv run python -m src.cli index
```

正常完了時のログ:
```
インデックス化が完了しました
- 処理ファイル数: N
- 総チャンク数: N
```

> **スキップされるフォルダ:** `_rag_dashboard\`・`_templates\`・`.processed\` は自動除外される。

---

## 7. watchdog の起動

```powershell
copy ..\DevelopmentRAGEnvironment\scripts\auto_index.py .

# バックグラウンドで起動
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python auto_index.py"
```

起動後は Obsidian でノートを保存するたびに自動インデックス化される。  
`_rag_dashboard\index_status.md` と `namespace_map.md` が自動更新されることで確認できる。

---

## 8. Claude Desktop への登録

`claude_desktop_config.json`（Everythingで検索）を以下に書き換える：

```json
{
  "mcpServers": {
    "mcp-rag-server": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "C:\\Users\\YOUR_USERNAME\\Desktop\\GameDevelopment\\mcp-rag-server",
        "python",
        "-m",
        "src.main"
      ]
    }
  }
}
```

Claude Desktop を完全再起動後、設定画面で `running` になれば完了。

---

## 9. 動作確認

Claude Desktop または Claude Code で以下を実行：

```
mcp-rag-server でインデックス内のドキュメント数を確認して
```

```
mcp-rag-server で「Houdini VEX」について検索して
```

---

## 10. トラブルシューティング

### sentencepiece のビルドが失敗する

Python 3.13 では wheel がないためビルドが失敗する。

```powershell
uv sync --python 3.12
```

### `'NoneType' object has no attribute 'get_or_create_collection'`

`scripts/vector_database.py` が古い。再度コピーして `initialize_database()` が `self.connect()` を呼んでいるか確認。

### ChromaDB のコレクション名エラー (`Got: C:\`)

`SOURCE_DIR` が `.env` に正しく設定されていない。絶対パスで設定されているか確認。

### watchdog が反応しない

```powershell
# uv run 経由で起動されているか確認
Get-Process python
# 止まっていれば再起動
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python auto_index.py"
```

### インデックス化で `_rag_dashboard` が処理される

`vector_database.py` のパッチが正しく適用されているか確認。  
`_namespace_from_path` が `SOURCE_DIR` 環境変数を読んで相対パスに変換しているはず。

```powershell
# 処理済みキャッシュをクリアして再インデックス
Remove-Item -Recurse -Force localRAG\_rag_dashboard\.processed
uv run python -m src.cli index
```

### MCP 検索時に `KeyError: 'chunk_index'` が出る

`vector_database.py` の `search()` が `chunk_index` をトップレベルに返していない旧バージョン。  
`scripts/vector_database.py` を再コピーして確認：

```python
# src/vector_database.py の search() 内 results.append(...) に以下が含まれるか確認
"chunk_index": meta.get("chunk_index", 0),
```

### MCP 検索時に `KeyError: 'document_id'` が出る

`get_adjacent_chunks()` / `get_document_by_file_path()` が `document_id` を返していない旧バージョン。  
最新の `scripts/vector_database.py` ではこれら両メソッドが `res["ids"]` を zip して `document_id` を含める実装になっている。

### 日本語クエリが文字化け / `TextEncodeInput` エラー

MCP サーバーが CP932 で stdin を読んでいる。`src\main.py` に UTF-8 パッチ（Step 4）が適用されているか確認。

```
# エラーメッセージ例
TextEncodeInput must be Union[TextInputSequence, ...]
received query: '繝輔か繝ｼ繝...'  ← 文字化けしている
```

### インデックス化後も MCP の検索結果が増えない

ChromaDB の HNSW インデックスはメモリにロードされるため、別プロセスが upsert しても MCP サーバー側に反映されない。  
**インデックス化後は必ず MCP サーバーを再起動する。**

Claude Desktop: タスクトレイから完全終了 → 再起動  
Claude Code: 接続を一度切断してから再接続

---

## 11. セキュリティ強化機能

NIST SP 800-207（Zero Trust Architecture）に基づいた機能が `scripts/` に追加されています。ローカルブリッジ（`rag_local_bridge.py`）を起動すると自動的に有効になります。

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
| `developer` | tool_docs / game_info / research / team_notes |
| `user` | tool_docs / game_info / research |

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
