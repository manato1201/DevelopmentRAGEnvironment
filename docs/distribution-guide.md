# LocalRAG 配布・導入手順ガイド

**対象:** 新しいPCまたは別のメンバーへ LocalRAG 環境を渡す場合  
**所要時間:** 約30〜40分（モデルダウンロード込み）  
**更新日:** 2026-06-16

> このドキュメントは `docs/local-rag-setup.md`（初回セットアップ詳細版）の配布特化の要約版です。  
> 詳細はそちらを参照してください。

---

## 配布物チェックリスト

渡す側が事前に準備するもの：

- [ ] `DevelopmentRAGEnvironment` リポジトリへのアクセス（GitHub）
- [ ] `mcp-rag-server` フォークリポジトリへのアクセス（`manato1201/mcp-rag-server`）
- [ ] `.env` ファイルの記入見本（パスを空欄にしたもの）
- [ ] Obsidian vault フォルダ（`localRAG/` ディレクトリ）の共有 ※任意

---

## 受け取る側のセットアップ手順

### Step 1 — 前提ソフトウェアのインストール

以下がインストール済みであることを確認する：

| ソフトウェア | インストール方法 | 確認コマンド |
|-------------|----------------|-------------|
| Git | https://git-scm.com/ | `git --version` |
| uv（Pythonパッケージ管理） | `winget install --id=astral-sh.uv -e` | `uv --version` |
| Claude Desktop | https://claude.ai/download | アプリ起動で確認 |
| Obsidian | https://obsidian.md/ | アプリ起動で確認 |

---

### Step 2 — リポジトリのクローン

PowerShell で実行：

```powershell
# 作業ディレクトリを作成（例）
cd C:\Users\YOUR_USERNAME\Desktop\GameDevelopment

# このリポジトリ（ドキュメント・スクリプト群）
git clone https://github.com/manato1201/DevelopmentRAGEnvironment

# mcp-rag-server フォーク（ChromaDB対応版）
git clone https://github.com/manato1201/mcp-rag-server
```

---

### Step 3 — Python 環境のセットアップ

```powershell
cd mcp-rag-server

# Python 3.12 で仮想環境を作成（3.13 だと sentencepiece がビルド失敗）
uv sync --python 3.12

# ChromaDB・watchdog・yaml を追加
uv add chromadb watchdog pyyaml
```

> **確認:** `uv run python --version` が `Python 3.12.x` を返すこと

---

### Step 4 — ChromaDB パッチの適用

#### 4-1. vector_database.py を差し替え

```powershell
copy ..\DevelopmentRAGEnvironment\scripts\vector_database.py src\vector_database.py
```

#### 4-2. rag_tools.py を編集

`src\rag_tools.py` を開き、`create_rag_service_from_env` 関数内の PostgreSQL ブロックを以下に変更：

```python
# 変更後（ChromaDB）
vector_database = VectorDatabase(
    {
        "chroma_path":   os.environ.get("CHROMA_PATH",   "./data/chroma"),
        "embedding_dim": os.environ.get("EMBEDDING_DIM", "1024"),
    }
)
```

#### 4-3. main.py に UTF-8 パッチを追加

`src\main.py` を開き、ファイル先頭の `import sys` の直後に追加：

```python
import io
if hasattr(sys.stdin, 'buffer'):
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
```

> **このパッチが必要な理由:** Windows のデフォルトエンコーディングは CP932。日本語クエリが文字化けして検索不能になる。

---

### Step 5 — .env ファイルの設定

```powershell
copy ..\DevelopmentRAGEnvironment\.env.example .env
```

`.env` をテキストエディタで開き、`YOUR_USERNAME` を自分のユーザー名に変更：

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

### Step 6 — Obsidian vault の設定

1. Obsidian を起動
2. 「Open folder as vault」で `DevelopmentRAGEnvironment\localRAG\` を選択
3. テンプレートプラグインを有効化:  
   設定 → コアプラグイン → テンプレート: オン  
   テンプレートフォルダの場所: `_templates`

---

### Step 7 — 初回インデックス化

```powershell
cd C:\Users\YOUR_USERNAME\Desktop\GameDevelopment\mcp-rag-server
uv run python -m src.cli index
```

正常完了時のログ（文字化けするが数字で確認）:
```
インデックス化が完了しました
- ドキュメント数: N
- 処理時間: N 秒
```

> **注意:** 初回は `intfloat/multilingual-e5-large`（約1.2GB）をダウンロードするため時間がかかる。

---

### Step 8 — watchdog（自動インデックス化）の設定

```powershell
# auto_index.py をコピー
copy ..\DevelopmentRAGEnvironment\scripts\auto_index.py .

# バックグラウンドで起動
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python auto_index.py"
```

以降は Obsidian でノートを保存するたびに自動インデックスされる。

---

### Step 9 — Claude Desktop への登録

1. `claude_desktop_config.json` を開く  
   （Everythingで検索、またはパス: `%APPDATA%\Claude\claude_desktop_config.json`）

2. 以下を追記：

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

3. Claude Desktop を完全再起動
4. 設定画面（右上⚙️）で `mcp-rag-server` が `running` になれば完了

---

### Step 10 — 動作確認

Claude Desktop または Claude Code で以下を実行：

```
mcp-rag-server でインデックス内のドキュメント数を確認して
```

```
mcp-rag-server で「Houdini VEX」について検索して
```

検索結果が返ってくれば成功。

---

## トラブルシューティング早見表

| 症状 | 原因 | 対処 |
|------|------|------|
| `sentencepiece` のビルド失敗 | Python 3.13 が選択されている | `uv sync --python 3.12` |
| 日本語クエリが文字化け / `TextEncodeInput` エラー | `main.py` の UTF-8 パッチ未適用 | Step 4-3 を適用 |
| インデックス化後も検索に反映されない | HNSW キャッシュが古い | MCPサーバー（Claude Desktop）を再起動 |
| `KeyError: 'chunk_index'` | `vector_database.py` が古い | Step 4-1 を再実行 |
| `'NoneType' object has no attribute 'get_or_create_collection'` | `vector_database.py` が古い | Step 4-1 を再実行 |
| ChromaDB コレクション名エラー `Got: C:\` | `.env` の `SOURCE_DIR` が未設定 | Step 5 を再確認 |

詳細は `docs/local-rag-setup.md` のセクション10を参照。

---

## 再配布時の注意点

- `data/chroma/` ディレクトリ（ベクトルDB）は git 管理外（`.gitignore`）
  - 別PCへのDB移行は `Compress-Archive -Path .\data\chroma -DestinationPath chroma_backup.zip` でバックアップ
- `.env` ファイルはパスが個人依存のため **共有しない**（`.env.example` を使う）
- `localRAG/` 内のノートは個人情報を含む可能性があるため配布範囲を確認
