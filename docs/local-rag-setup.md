# ローカルRAG環境セットアップガイド（ChromaDB版）

**対象:** Windows 11（WSL2・Docker不要）  
**所要時間:** 約20分  
**更新日:** 2026-06-16

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
