# LocalRAG 配布・導入手順ガイド

**対象:** 新しいPCまたは別のメンバーへ LocalRAG 環境を渡す場合  
**所要時間:** 約15〜20分（モデルダウンロード込み）  
**更新日:** 2026-06-30

> このドキュメントは `docs/local-rag-setup.md`（初回セットアップ詳細版）の配布特化の要約版です。  
> 詳細はそちらを参照してください。

> **変更履歴:** 2026-06-30 — 外部リポジトリ `mcp-rag-server` への依存を解消。検索エンジン一式をこのリポジトリにベンダー統合したため、クローンするリポジトリは1つだけになった。

---

## 配布物チェックリスト

渡す側が事前に準備するもの：

- [ ] `DevelopmentRAGEnvironment` リポジトリへのアクセス（GitHub）。これ1つで完結（外部リポジトリのアクセス権は不要）
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

# このリポジトリ1つだけで完結（ドキュメント・スクリプト・検索エンジンすべて含む）
git clone https://github.com/manato1201/DevelopmentRAGEnvironment
```

---

### Step 3 — 依存パッケージの同期

```powershell
cd DevelopmentRAGEnvironment
uv sync
```

`pyproject.toml` に ChromaDB・sentence-transformers・rank-bm25・sudachipy 等の依存がすべて宣言されているため、これだけで完結する。`requires-python` は `>=3.13` を指定済み（sentencepiece の wheel が提供される最小バージョン）。

> 初回は `sentence-transformers` 等のダウンロードで数分かかる。

---

### Step 4 — 環境変数の設定（任意）

`.env` ファイルは使用しない（`load_dotenv()` 非対応）。必要な環境変数は OS の環境変数として設定するか、起動コマンドの前に付与する。デフォルト値のままで問題なければこの手順はスキップしてよい。

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

---

### Step 5 — Obsidian vault の設定

1. Obsidian を起動
2. 「Open folder as vault」で `DevelopmentRAGEnvironment\localRAG\` を選択
3. テンプレートプラグインを有効化:  
   設定 → コアプラグイン → テンプレート: オン  
   テンプレートフォルダの場所: `_templates`

---

### Step 6 — 初回インデックス化

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

> **注意:** 初回は `intfloat/multilingual-e5-large`（約1.2GB）をダウンロードするため時間がかかる。

差分のみインデックス化する場合:
```powershell
uv run python scripts\rag_cli.py index --incremental
```

---

### Step 7 — watchdog（自動インデックス化）の設定

```powershell
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python scripts/auto_index.py"
```

以降は Obsidian でノートを保存するたびに自動インデックスされる。

---

### Step 8 — Claude Desktop への登録

1. `claude_desktop_config.json` を開く  
   （Everythingで検索、またはパス: `%APPDATA%\Claude\claude_desktop_config.json`）

2. 以下を追記：

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

3. Claude Desktop を完全再起動
4. 設定画面（右上⚙️）で `local-rag-server` が `running` になれば完了

---

### Step 9 — 動作確認

Claude Desktop または Claude Code で以下を実行：

```
local-rag-server でインデックス内のドキュメント数を確認して
```

```
local-rag-server で「Houdini VEX」について検索して
```

検索結果が返ってくれば成功。

---

## トラブルシューティング早見表

| 症状 | 原因 | 対処 |
|------|------|------|
| `sentencepiece` のビルド失敗 | `requires-python` が `>=3.13` になっていない | `pyproject.toml` を確認。Python 3.13 以降なら wheel あり |
| 日本語クエリが文字化け / `TextEncodeInput` エラー | `scripts/rag_mcp_server.py` の UTF-8 パッチが効いていない | ファイル冒頭の `io.TextIOWrapper` パッチを確認 |
| インデックス化後も検索に反映されない | HNSW キャッシュが古い | MCPサーバー（Claude Desktop）またはブリッジを再起動 |
| `KeyError: 'chunk_index'` / `'document_id'` | `scripts/vector_database.py` の戻り値形式不一致 | `search()` 等がトップレベルでキーを返しているか確認 |
| `'NoneType' object has no attribute 'get_or_create_collection'` | `initialize_database()` が `connect()` を呼んでいない | `scripts/vector_database.py` を確認 |
| ChromaDB コレクション名エラー `Got: C:\` | `SOURCE_DIR` 環境変数が未設定/相対パスでない | Step 4 を再確認。デフォルトでは `localRAG/` が使われる |

詳細は `docs/local-rag-setup.md` のセクション10を参照。

---

## 再配布時の注意点

- `data/chroma/` ディレクトリ（ベクトルDB）は git 管理外（`.gitignore`）
  - 別PCへのDB移行は `Compress-Archive -Path .\data\chroma -DestinationPath chroma_backup.zip` でバックアップ
- API キー等は環境変数のみで管理し、ファイルに書き出さない（`.env` は使用しない方針）
- `localRAG/` 内のノートは個人情報を含む可能性があるため配布範囲を確認
