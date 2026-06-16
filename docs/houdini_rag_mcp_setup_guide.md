# Houdini Help RAG MCP 構築ガイド

> Houdini 20.5/21.0 のヘルプドキュメントを pgvector + MCP で検索可能にする手順書

---

## 全体構成

```
Houdini help .txt (7,810ファイル)
    ↓ zip展開 → .txt抽出
data/source/
    ↓ python -m src.cli index（約4〜6時間）
PostgreSQL + pgvector (Docker)
    ↓ MCP経由でベクトル検索
Claude Desktop / Cline / Cursor
```

---

## 前提環境

| 項目 | 内容 |
|---|---|
| OS | Windows 11 + WSL2 (Ubuntu 24.04) |
| GPU | RTX 3070（埋め込み推論に使用） |
| Houdini | 21.0.506 または 20.5.522 |
| MCPホスト | Claude Desktop |

---

## Step 0｜WSL2 の正しいセットアップ

> **⚠️ 重要：systemd を有効にしてから apt upgrade すること**
> 順番を間違えると systemd パッケージの設定が壊れます。

```bash
# 1. systemd を先に有効化
sudo tee /etc/wsl.conf << 'EOF'
[boot]
systemd=true
EOF
```

**PowerShell（Windows側）で再起動：**

```powershell
wsl --shutdown
```

Ubuntu を再度開いてから：

```bash
# 2. パッケージ更新
sudo apt update && sudo apt upgrade -y
```

---

## Step 1｜Docker のインストール

```bash
# 必要パッケージ
sudo apt install -y ca-certificates curl gnupg lsb-release

# GPGキー追加
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc > /dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc

# リポジトリ追加（amd64 / noble の場合）
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# インストール
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# sudo なしで使えるように
sudo usermod -aG docker $USER
newgrp docker

# 動作確認
docker run hello-world
```

**Docker Desktop との連携（推奨）：**

1. Docker Desktop → Settings → Resources → WSL Integration
2. Ubuntu のトグルをオン
3. Apply & Restart

---

## Step 2｜PostgreSQL + pgvector を起動

```bash
# コンテナ起動
docker run --name postgres-pgvector \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 \
  -d pgvector/pgvector:pg17

# データベース作成
docker exec -it postgres-pgvector \
  psql -U postgres -c "CREATE DATABASE ragdb;"

# 確認
docker ps
```

> **注意：** WSL を再起動した後はコンテナが止まっています。
> `docker start postgres-pgvector` で再起動してください。

---

## Step 3｜mcp-rag-server のセットアップ

```bash
# uv インストール
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# リポジトリ取得
cd ~
git clone https://github.com/karaage0703/mcp-rag-server
cd mcp-rag-server
uv sync

# .env 作成
tee .env << 'EOF'
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=ragdb

SOURCE_DIR=./data/source
PROCESSED_DIR=./data/processed

EMBEDDING_MODEL=intfloat/multilingual-e5-large
EMBEDDING_DIM=1024
EMBEDDING_PREFIX_QUERY="query: "
EMBEDDING_PREFIX_EMBEDDING="passage: "
EOF
```

---

## Step 4｜Houdini ヘルプデータの準備

### データのコピー先を作成

```bash
mkdir -p ~/mcp-rag-server/data/source
```

### Windows側：ヘルプフォルダを開く

```
C:\Program Files\Side Effects Software\Houdini 21.0.506\houdini\help\
```

以下の zip ファイルを WSL の `data/source/` にコピー：

```
\\wsl.localhost\Ubuntu\home\tk_render\mcp-rag-server\data\source
```

**優先コピー対象：**

- `nodes.zip`（5.8MB・最重要）
- `expressions.zip`
- `commands.zip`
- `vex.zip`
- `hapi.zip`
- `network.zip`
- `render.zip`
- `shelf.zip`
- `basics.zip`

### zip 展開

```python
# extract_zip.py
import os, zipfile

def extract_zip_files(directory):
    for filename in os.listdir(directory):
        if filename.endswith(".zip"):
            file_path = os.path.join(directory, filename)
            output_path = os.path.join(directory, filename[:-4])
            os.makedirs(output_path, exist_ok=True)
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    zf.extractall(output_path)
                os.remove(file_path)
                print(f"展開完了: {filename}")
            except Exception as e:
                print(f"エラー: {filename} - {e}")

extract_zip_files("data/source")
```

### .txt 以外を削除

```python
# delete_non_txt.py
import os

def delete_non_txt_files(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if not file.endswith(".txt"):
                try:
                    os.remove(os.path.join(root, file))
                except Exception as e:
                    print(f"エラー: {file} - {e}")

delete_non_txt_files("data/source")
```

```bash
python3 extract_zip.py
python3 delete_non_txt.py

# ファイル数確認（7000以上あればOK）
find data/source -name "*.txt" | wc -l
```

---

## Step 5｜インデックス化

> ⏱ **7810ファイルで約4〜6時間かかります**

```bash
cd ~/mcp-rag-server

# バックグラウンドで実行（推奨）
nohup uv run python -m src.cli index > index.log 2>&1 &
echo "PID: $!"

# 進捗確認
tail -f index.log
```

**差分インデックス（追加ファイルのみ更新）：**

```bash
uv run python -m src.cli index --incremental
```

**インデックスのリセット：**

```bash
uv run python -m src.cli clear
```

---

## Step 6｜MCPサーバーの設定

### Claude Desktop の設定ファイルを開く（Windows）

エクスプローラーのアドレスバーに入力：

```
%APPDATA%\Claude
```

`claude_desktop_config.json` を以下の内容にする：

```json
{
  "mcpServers": {
    "mcp-rag-server": {
      "command": "wsl",
      "args": [
        "bash",
        "-c",
        "/home/tk_render/.local/bin/uv run --directory /home/tk_render/mcp-rag-server python -m src.main"
      ]
    }
  }
}
```

> **ポイント：** `uv` のフルパスを指定する。`bash -c` での起動は PATH が初期化されないため `uv` が見つからないことがある。

Claude Desktop を再起動して、設定画面でサーバーが `running` になれば完了。

---

## 使い方

### 基本的なプロンプト例

```
mcp-rag-serverで "vellum solver" について英語で検索して、
パラメータ一覧と使い方を日本語でMarkdownファイルに出力してください。
```

### 2段階推論パターン（精度向上）

```
1. Houdini 21.0 で布シミュレーションをするために必要なノードを列挙してください。
2. 各ノードについて mcp-rag-server で英語で検索し、
   パラメータと注意点をまとめてください。
```

### トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `uv: command not found` | PATH が通っていない | `uv` のフルパスを設定ファイルに記載 |
| `database "ragdb" does not exist` | Dockerコンテナが停止 | `docker start postgres-pgvector` |
| 日本語クエリで文字コードエラー | エンコード問題 | 検索クエリを英語にする |
| 抽象的な質問で検索失敗 | ヘルプにそのまま載っていない | ノード名を先に列挙させてから検索 |
| Server disconnected | WSL再起動後のコンテナ停止 | Docker再起動を確認 |

---

## 参考リンク

- [mcp-rag-server（GitHub）](https://github.com/karaage0703/mcp-rag-server)
- [ローカルRAGを手軽に構築できるMCPサーバを作りました（Zenn）](https://zenn.dev/mkj/articles/30eeb69bf84b3f)
- [HoudiniヘルプをRAG MCP環境に読み込ませた（Zenn）](https://zenn.dev/nekoco/articles/f9ff33c70cb83c)
- [multilingual-e5-large（HuggingFace）](https://huggingface.co/intfloat/multilingual-e5-large)
- [pgvector（GitHub）](https://github.com/pgvector/pgvector)
