# ローカルRAG環境セットアップガイド

**対象:** Windows 11 + WSL2 (Ubuntu) + Docker  
**所要時間:** セットアップ約30分 / インデックス化4時間以上  
**更新日:** 2026-06-10

---

## 目次

1. [前提条件](#1-前提条件)
2. [WSL2セットアップ](#2-wsl2セットアップ)
3. [Dockerインストール](#3-dockerインストール)
4. [pgvector起動](#4-pgvector起動)
5. [mcp-rag-serverセットアップ](#5-mcp-rag-serverセットアップ)
6. [Houdiniヘルプデータの配置](#6-houdiniヘルプデータの配置)
7. [インデックス化](#7-インデックス化)
8. [MCPサーバー設定](#8-mcpサーバー設定)
9. [トラブルシューティング](#9-トラブルシューティング)

---

## 1. 前提条件

| 項目 | 要件 |
|------|------|
| OS | Windows 11 |
| Docker Desktop | 不要（WSL2内にDockerを直接インストール） |
| Houdini | インストール済み（helpデータ取得のため） |
| Claude Desktop | インストール済み |
| ディスク空き | 10GB以上推奨 |

---

## 2. WSL2セットアップ

### Step 1 — Ubuntuをインストール

PowerShellを**管理者権限**で起動して実行：

```powershell
wsl --install -d Ubuntu
```

インストール完了後、Ubuntuが起動するのでユーザー名とパスワードを設定する。

> **注意:** 再起動を求められた場合は再起動してからUbuntuを起動する。

### Step 2 — systemdの有効化

```bash
sudo tee /etc/wsl.conf << 'EOF'
[boot]
systemd=true
EOF
```

設定反映のためWSLを再起動：

```powershell
# PowerShellで実行
wsl --shutdown
```

その後Ubuntuを再度起動する。

### Step 3 — パッケージ更新

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 3. Dockerインストール

### Step 1 — 必要なパッケージを入れる

```bash
sudo apt install -y ca-certificates curl gnupg lsb-release
```

### Step 2 — Docker公式GPGキーを追加

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc > /dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

### Step 3 — Dockerリポジトリを追加

```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### Step 4 — Dockerをインストール

```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Step 5 — sudoなしで使えるようにする

```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Step 6 — 動作確認

```bash
docker --version
docker run hello-world
```

`Hello from Docker!` が表示されれば成功。

---

## 4. pgvector起動

### Step 1 — コンテナ起動

```bash
docker run --name postgres-pgvector \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 \
  -d pgvector/pgvector:pg17
```

### Step 2 — データベース作成

```bash
docker exec -it postgres-pgvector \
  psql -U postgres -c "CREATE DATABASE ragdb;"
```

### Step 3 — 確認

```bash
docker ps
```

`postgres-pgvector` が `Up` 状態であれば成功。

> **Tips:** WSL再起動後にコンテナが停止している場合は `docker start postgres-pgvector` で再起動できる。

---

## 5. mcp-rag-serverセットアップ

### Step 1 — uvのインストール

Ubuntuターミナルで実行：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

### Step 2 — リポジトリをクローン

```bash
cd ~
git clone https://github.com/karaage0703/mcp-rag-server
cd mcp-rag-server
uv sync
```

### Step 3 — .envファイルを作成

```bash
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

### Step 4 — 確認

```bash
cat .env
```

---

## 6. Houdiniヘルプデータの配置

### Step 1 — ソースディレクトリ作成【Ubuntu】

```bash
mkdir -p ~/mcp-rag-server/data/source
```

### Step 2 — Houdini helpのzipを探す【Windows】

エクスプローラーで以下を開く（バージョン番号は環境に合わせて変更）：

```
C:\Program Files\Side Effects Software\Houdini 21.0.506\houdini\help
```

### Step 3 — WSLのsourceフォルダへコピー【Windows】

エクスプローラーのアドレスバーに以下を貼り付けてアクセス：

```
\\wsl.localhost\Ubuntu\home\tk_render\mcp-rag-server\data\source
```

コピーするzipファイル（優先度順）：

| ファイル名 | 内容 | 優先度 |
|-----------|------|--------|
| `nodes.zip` | ノードリファレンス | ★★★ 最重要 |
| `expressions.zip` | 式・関数 | ★★★ |
| `commands.zip` | HScriptコマンド | ★★★ |
| `hapi.zip` | Houdini Engine API | ★★☆ |
| `vex.zip` | VEXリファレンス | ★★☆ |
| `basics.zip` | 基本操作 | ★☆☆ 余裕があれば |
| `render.zip` | レンダリング | ★☆☆ 余裕があれば |
| `network.zip` | ネットワーク操作 | ★☆☆ 余裕があれば |

### Step 4 — 配置確認【Ubuntu】

```bash
ls ~/mcp-rag-server/data/source/
```

### Step 5 — zip展開スクリプトを実行【Ubuntu】

```bash
cd ~/mcp-rag-server
cat > extract_zip.py << 'EOF'
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
EOF

python3 extract_zip.py
```

### Step 6 — .txt以外を削除【Ubuntu】

```bash
cd ~/mcp-rag-server
cat > delete_non_txt.py << 'EOF'
import os

def delete_non_txt_files(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if not file.endswith(".txt"):
                try:
                    os.remove(os.path.join(root, file))
                    print(f"削除: {file}")
                except Exception as e:
                    print(f"エラー: {file} - {e}")

delete_non_txt_files("data/source")
EOF

python3 delete_non_txt.py
```

### Step 7 — 削除後に確認【Ubuntu】

```bash
find data/source -name "*.txt" | wc -l
```

数百〜数千のtxtファイルが確認できれば成功。

---

## 7. インデックス化

> **注意:** 初回インデックス化は**4時間以上**かかる。時間に余裕があるときに実行すること。

### インデックス化の実行【Ubuntu】

バックグラウンド実行（ログをファイルに保存）：

```bash
cd ~/mcp-rag-server
nohup uv run python -m src.cli index > index.log 2>&1 &
echo "PID: $!"
```

### 進捗確認

```bash
tail -f ~/mcp-rag-server/index.log
```

処理済みファイル数の確認：

```bash
grep "INFO" ~/mcp-rag-server/index.log | wc -l
```

---

## 8. MCPサーバー設定

### Step 1 — MCPサーバーの動作確認【Ubuntu】

```bash
cd ~/mcp-rag-server
uv run python -m src.main
```

`Starting MCP server...` のような表示が出れば成功。`Ctrl+C` で停止。

### Step 2 — Claude Desktopの設定ファイルを開く【Windows】

Everythingで以下を検索：

```
claude_desktop_config.json
```

### Step 3 — 設定ファイルを編集【Windows】

`claude_desktop_config.json` を以下に書き換える（ユーザー名を自分のものに変更）：

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

> `tk_render` の部分を自分のUbuntuユーザー名に変更すること。

### Step 4 — 動作確認【Claude Desktop】

Claude Desktopを完全に再起動後、以下のプロンプトで確認：

```
mcp-rag-serverで "vellum solver" について検索して、
パラメータ一覧と使い方を英語で検索し日本語で教えてください。
```

Claude Desktopの設定で `running` になっていれば完了。

---

## 9. トラブルシューティング

### Dockerコンテナが起動しない

```bash
# コンテナの状態確認
docker ps -a

# 停止中なら再起動
docker start postgres-pgvector

# ログ確認
docker logs postgres-pgvector
```

### uvコマンドが見つからない

```bash
source $HOME/.local/bin/env
# または
export PATH="$HOME/.local/bin:$PATH"
```

`.bashrc` に追記して永続化：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Claude DesktopでMCPがrunningにならない

1. `claude_desktop_config.json` のユーザー名が正しいか確認
2. Ubuntuで `uv run python -m src.main` が単体で動くか確認
3. pgvectorコンテナが起動しているか `docker ps` で確認
4. Claude Desktopを完全終了（タスクトレイから）して再起動

### インデックス化が止まった

```bash
# プロセス確認
ps aux | grep "src.cli"

# 再実行（差分インデックス化なので途中から再開される）
cd ~/mcp-rag-server
nohup uv run python -m src.cli index > index.log 2>&1 &
```
