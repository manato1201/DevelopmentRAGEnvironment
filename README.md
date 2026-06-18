# RAG Environment

ローカル・クラウド両対応のRAG（Retrieval-Augmented Generation）環境のセットアップドキュメント・スクリプト集です。

## 概要

| 種別 | 構成 | 用途 |
|------|------|------|
| **ローカルRAG** | ChromaDB + mcp-rag-server（Docker・WSL2不要） | チャット履歴・個人メモ・進捗など共有NGな情報 |
| **クラウドRAG** | Notion + GAS + Gemini API | ツール仕様・ゲーム情報・技術記事など共有すべき情報 |

2つはセットで使うことを前提に設計されており、Claude Code / Claude Desktop からローカルと Notion の両方を同時に参照できます。

---

## クイックスタート

### ローカルRAG（mcp-rag-server）

**→ 初回セットアップ: [docs/local-rag-setup.md](docs/local-rag-setup.md)**  
**→ 別PCへの配布: [docs/distribution-guide.md](docs/distribution-guide.md)**

| 項目 | 内容 |
|------|------|
| OS | Windows 11（Docker・WSL2不要） |
| Python | uv が自動管理（**3.12 必須**） |
| ベクトルDB | ChromaDB（ローカルファイル） |
| 埋め込みモデル | `intfloat/multilingual-e5-large`（約1.2GB） |
| 所要時間 | セットアップ約30分 + 初回モデルDL |

```powershell
# 1. フォークをクローン
git clone https://github.com/manato1201/mcp-rag-server
cd mcp-rag-server

# 2. 依存関係インストール（Python 3.12 固定）
uv sync --python 3.12
uv add chromadb watchdog pyyaml

# 3. ChromaDB パッチを適用
copy ..\DevelopmentRAGEnvironment\scripts\vector_database.py src\vector_database.py
# rag_tools.py・main.py の編集は local-rag-setup.md を参照

# 4. .env を設定
copy ..\DevelopmentRAGEnvironment\.env.example .env
# YOUR_USERNAME を自分のユーザー名に変更

# 5. インデックス化
uv run python -m src.cli index
```

### クラウドRAG（Notion + GAS + Gemini）

**→ [docs/cloud-rag-setup.md](docs/cloud-rag-setup.md)**

| 項目 | 内容 |
|------|------|
| Notion DB | 4DB作成済み（Tool Docs / Game Info / Research / Team Notes） |
| GASコード | `scripts/gas_cloud_rag.js` |
| 一括投入ツール | `scripts/notion_bulk_add.py` |
| 所要時間 | 約60〜90分（GASデプロイ含む） |

---

## ディレクトリ構成

```
DevelopmentRAGEnvironment/
├── README.md
├── .env.example                    # 環境変数テンプレート
│
├── docs/
│   ├── local-rag-setup.md          # ローカルRAG セットアップ詳細
│   ├── distribution-guide.md       # 配布・導入手順（別PCへの展開）
│   ├── cloud-rag-setup.md          # クラウドRAG セットアップ
│   ├── local-rag-chromadb-migration.md  # pgvector→ChromaDB 移行記録
│   ├── rag-system-design.md        # システム設計（全体像）
│   └── obsidian-localrag-management.md  # Obsidian vault 管理
│
├── lecture/
│   ├── local-rag-lecture.html      # ローカルRAG 講義資料
│   └── cloud-rag-lecture.html      # クラウドRAG 講義資料
│
├── scripts/
│   ├── vector_database.py          # ChromaDB バックエンド（mcp-rag-server に適用）
│   ├── auto_index.py               # watchdog 自動インデックス化スクリプト
│   ├── gas_cloud_rag.js            # GAS WebApp コード（Notion + Gemini チャット）
│   ├── notion_bulk_add.py          # Notion DB への一括データ投入
│   ├── notion_bulk_input.yaml      # notion_bulk_add.py の入力サンプル
│   ├── extract_zip.py              # Houdini help zip 展開スクリプト
│   └── delete_non_txt.py           # .txt 以外削除スクリプト
│
└── localRAG/                       # Obsidian vault（インデックス対象）
    ├── personal_notes/             # 個人メモ・調査ノート
    ├── tutorials/                  # チュートリアル生成結果
    ├── chat_logs/                  # チャット履歴
    ├── private_docs/               # 共有不可ドキュメント
    ├── _rag_dashboard/             # インデックス管理（除外対象）
    └── _templates/                 # テンプレート（除外対象）
```

---

## 設計思想

```
クラウドに入れるもの（共有すべき情報）
├── ツール仕様: Unity / Houdini / DirectX12 / 環境設定
├── ゲーム情報: 共有設計書・仕様
├── 技術記事:   手動で精査したもの
└── 研究資料:   ゼミ資料・議事録

ローカルに入れるもの（個人情報）
├── チャット履歴: Claude等との会話ログ
├── 生成結果:     Houdiniチュートリアル生成結果
├── 個人メモ:     Obsidianノート・進捗・AFURI/BrainTQ等
└── 草稿・NG:     共有できない文書
```

クラウドへの書き込みはローカルからは行いません（読み取り専用）。

---

## スクリプトの使い方

### vector_database.py — ChromaDB バックエンド

mcp-rag-server の `src/vector_database.py` に差し替えて使う：

```powershell
copy scripts\vector_database.py ..\mcp-rag-server\src\vector_database.py
```

### auto_index.py — watchdog 自動インデックス化

mcp-rag-server のルートにコピーしてバックグラウンド起動：

```powershell
copy scripts\auto_index.py ..\mcp-rag-server\
cd ..\mcp-rag-server
Start-Process -NoNewWindow -FilePath "uv" -ArgumentList "run python auto_index.py"
```

### notion_bulk_add.py — Notion DB 一括投入

```powershell
# サンプルYAMLを編集してから実行
# まずドライランで確認
uv run python scripts\notion_bulk_add.py --input scripts\notion_bulk_input.yaml --dry-run

# 実際に投入
uv run python scripts\notion_bulk_add.py --input scripts\notion_bulk_input.yaml
```

`.env` に `NOTION_API_KEY` と `GEMINI_API_KEY` の設定が必要。

### gas_cloud_rag.js — GAS WebApp

GAS エディタ（script.google.com）に貼り付けて使う。  
詳細は `docs/cloud-rag-setup.md` のステップ4を参照。

### extract_zip.py / delete_non_txt.py — Houdini ヘルプ前処理

```powershell
copy scripts\extract_zip.py ..\mcp-rag-server\
copy scripts\delete_non_txt.py ..\mcp-rag-server\
cd ..\mcp-rag-server
uv run python extract_zip.py
uv run python delete_non_txt.py
```

---

## mcp-rag-server について

このプロジェクトでは [karaage0703/mcp-rag-server](https://github.com/karaage0703/mcp-rag-server) のフォーク [manato1201/mcp-rag-server](https://github.com/manato1201/mcp-rag-server) を使用しています。

**オリジナルからの主な変更点:**
- ベクトルDB: PostgreSQL/pgvector → **ChromaDB**（Docker不要）
- Windows 11 ネイティブ対応（WSL2不要）
- `main.py` に Windows CP932→UTF-8 パッチ適用済み
- `vector_database.py` に Obsidian vault ネームスペース対応・バグ修正3件

---

## 参考リンク

- [manato1201/mcp-rag-server](https://github.com/manato1201/mcp-rag-server) — 使用しているフォーク
- [karaage0703/mcp-rag-server](https://github.com/karaage0703/mcp-rag-server) — オリジナル
- [Notion API リファレンス](https://developers.notion.com/)
- [Google AI Studio（Gemini APIキー発行）](https://aistudio.google.com/)
- [uv — Python パッケージマネージャー](https://docs.astral.sh/uv/)
