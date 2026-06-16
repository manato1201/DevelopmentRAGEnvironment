# ローカルRAG ChromaDB 移行ガイド

**目的:** mcp-rag-server の pgvector（Docker必須）を ChromaDB（Dockerなし）に置き換える  
**所要時間:** 約15分  
**更新日:** 2026-06-16

---

## 変更概要

| Before | After |
|--------|-------|
| Docker + PostgreSQL + pgvector | ChromaDB（ファイルベース、Dockerなし） |
| port 5432 が開く | ポートなし、ファイルのみ |
| `.env` に PostgreSQL 設定 | `.env` に `CHROMA_PATH` のみ |

セットアップ手順が大幅に簡略化される：

```bash
# Before（旧手順）
wsl --install -d Ubuntu
# Docker インストール（GPGキー追加など5ステップ）
docker run --name postgres-pgvector ...

# After（新手順）
uv add chromadb   # これだけ
```

---

## 手順

### Step 1 — mcp-rag-server をクローン

```bash
cd ~
git clone https://github.com/karaage0703/mcp-rag-server
cd mcp-rag-server
uv sync
```

### Step 2 — chromadb / watchdog / pyyaml を追加

```bash
uv add chromadb watchdog pyyaml
```

### Step 3 — vector_database.py を差し替え

このリポジトリの `scripts/vector_database.py` をコピーする：

```bash
# DevelopmentRAGEnvironment のパスは環境に合わせて変更
cp ~/DevelopmentRAGEnvironment/scripts/vector_database.py src/vector_database.py
```

### Step 4 — rag_tools.py を編集

`src/rag_tools.py` の `create_rag_service_from_env` 関数内で
PostgreSQL 接続設定を ChromaDB に差し替える。

**変更前（PostgreSQL）:**

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

**変更後（ChromaDB）:**

```python
vector_database = VectorDatabase(
    {
        "chroma_path":   os.environ.get("CHROMA_PATH",    "./data/chroma"),
        "embedding_dim": os.environ.get("EMBEDDING_DIM",  "1024"),
    }
)
```

> 変更箇所はこの1ブロックだけ。他のコードは一切触らない。

### Step 5 — .env を設定

```bash
cp ~/DevelopmentRAGEnvironment/.env.example .env
```

`.env` を開いて `YOUR_USERNAME` と `SOURCE_DIR` を自分の環境に合わせて変更する：

```bash
CHROMA_PATH=./data/chroma
SOURCE_DIR=/home/tk_render/obsidian-vault
PROCESSED_DIR=/home/tk_render/obsidian-vault/_rag_dashboard/.processed
```

### Step 6 — 動作確認

```bash
# MCP サーバーが起動するか確認
uv run python -m src.main
# → "Starting MCP server..." が出れば成功。Ctrl+C で停止。

# 手動インデックス化テスト
mkdir -p data/source
echo "テストドキュメント" > data/source/test.txt
uv run python -m src.cli index
```

### Step 7 — watchdog（自動インデックス化）を起動

```bash
cp ~/DevelopmentRAGEnvironment/scripts/auto_index.py .
nohup python3 auto_index.py > auto_index.log 2>&1 &
echo "PID: $!"
tail -f auto_index.log
```

### Step 8 — Claude Desktop に登録

`claude_desktop_config.json` を以下に更新（`YOUR_USERNAME` を変更）：

```json
{
  "mcpServers": {
    "mcp-rag-server": {
      "command": "wsl",
      "args": [
        "bash", "-c",
        "/home/YOUR_USERNAME/.local/bin/uv run --directory /home/YOUR_USERNAME/mcp-rag-server python -m src.main"
      ]
    }
  }
}
```

---

## Obsidian vault 構成

SOURCE_DIR には以下の構造で Obsidian vault を配置する。
フォルダ名が自動的に ChromaDB のコレクション名（namespace）になる。

```
obsidian-vault/
├── chat_logs/           ← namespace: chat_logs
│   └── 2026-06-16_claude.md
├── tutorials/           ← namespace: tutorials
│   └── houdini_vex.md
├── personal_notes/      ← namespace: personal_notes
│   └── progress/
├── private_docs/        ← namespace: private_docs
│   └── draft.md
└── _rag_dashboard/      ← 管理専用（インデックス対象外）
    ├── index_status.md  ← 自動生成
    └── namespace_map.md ← 自動生成
```

### ノートの frontmatter テンプレート

```yaml
---
title: ノートタイトル
namespace: tutorials
status: active
created: 2026-06-16
updated: 2026-06-16
expires: 2026-12-16
tags: [houdini, vex]
rag_indexed: false
---
```

| `status` | 動作 |
|----------|------|
| `active` | インデックス化する（デフォルト） |
| `stale` | インデックス化するが警告ログ |
| `archived` | スキップ |

---

## データ構造（ChromaDB内部）

| pgvector（旧） | ChromaDB（新） | 備考 |
|--------------|--------------|------|
| `documents` テーブル | コレクション（namespace単位） | 1namespace = 1コレクション |
| `namespace` カラム | コレクション名 | フォルダ名が自動マッピング |
| `embedding (vector)` | `embeddings` | 同じモデル、同じ次元 |
| `document_id` | `id` | 同じ値 |
| `ivfflat` インデックス | `HNSW（hnswlib）` | 検索精度は同等 |

---

## トラブルシューティング

### `chromadb` が見つからない

```bash
uv add chromadb
```

### インデックス化でエラーが出る

```bash
# ログ確認
tail -50 index.log

# ChromaDB のデータをリセットして再インデックス
rm -rf data/chroma
uv run python -m src.cli index
```

### watchdog が反応しない

```bash
ps aux | grep auto_index
# プロセスがなければ再起動
nohup python3 auto_index.py > auto_index.log 2>&1 &
```

### rag_indexed が更新されない

`auto_index.py` の `write_frontmatter_field` は `rag_indexed: false` が frontmatter に存在する場合のみ更新する。
ノートに `rag_indexed: false` が含まれているか確認する。
