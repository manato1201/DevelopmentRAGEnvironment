# RAG 環境構築ガイド — 必要環境・依存関係リスト

> 対象: DevelopmentRAGEnvironment（ローカルRAG + クラウドRAG）  
> 更新日: 2026-06-25  
> OS: Windows 10/11（WSL2 も可）

---

## 全体構成図（二層構成）

```
┌─────────────────────────────────────────────────────────┐
│  【ローカルRAG層】  Windows 11 ローカル環境              │
│                                                         │
│  Python 3.13+  (DevelopmentRAGEnvironment)              │
│  Python 3.10+  (mcp-rag-server)                        │
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

┌─────────────────────────────────────────────────────────┐
│  【クラウドRAG層】  Google / Notion サービス群           │
│                                                         │
│  Notion（7DB）                                          │
│    ↓ GAS: syncNotionToSheets()                          │
│  Google Sheets（RAG_Index）                             │
│    ← 768次元ベクトルを保存・コサイン類似度検索          │
│    ↓                                                    │
│  Gemini gemini-embedding-001  ← 埋め込み生成            │
│  Gemini gemini-2.5-flash      ← 回答生成                │
│    ↓                                                    │
│  GAS WebApp（チャットUI）                               │
│    └── Unity / Houdini クライアントから接続可           │
└─────────────────────────────────────────────────────────┘

        Unity / Houdini エディタ
          ├── Cloud モード → GAS WebApp URL へ HTTP
          └── Local  モード → localhost:8766 へ HTTP
```

---

## 1. mcp-rag-server のフォーク方針

### なぜフォークが必要か

現在の `mcp-rag-server` は他者の個人リポジトリ（`karaage` 氏）をローカルに clone して使っている状態です。以下のリスクがあります。

| リスク | 内容 |
|--------|------|
| **削除・非公開化** | 元オーナーが予告なくリポジトリを消す可能性がある |
| **破壊的変更** | upstream の更新で動作が壊れる可能性がある |
| **商用利用の明示性** | 自社管理外のコードに直接依存しているため、監査・証跡が取りにくい |
| **カスタマイズ管理** | 独自改修を加えたい場合に管理できない |

### フォーク手順

#### Step 1: GitHub でフォーク

1. ブラウザで元リポジトリを開く（例: `https://github.com/karaage0703/mcp-rag-server`）
2. 右上の **Fork** ボタンをクリック
3. フォーク先を自分のアカウント（`manato1201`）に設定
4. リポジトリ名はそのまま `mcp-rag-server` 、または `rag-engine` など任意に変更可

#### Step 2: ローカルの clone 先を変更

```powershell
cd C:\Users\matuu\Desktop\GameDevelopment\mcp-rag-server

# 現在の remote を確認
git remote -v

# origin を自分のフォークに変更
git remote set-url origin https://github.com/manato1201/mcp-rag-server.git

# 元リポジトリを upstream として保持（任意 — upstream の更新を取り込みたい場合）
git remote add upstream https://github.com/karaage0703/mcp-rag-server.git

# 確認
git remote -v
```

#### Step 3: フォーク済みリポジトリに push

```powershell
git push origin main
```

#### Step 4: upstream の更新を取り込む（必要なとき）

```powershell
git fetch upstream
git merge upstream/main
# コンフリクトがあれば解消して push
git push origin main
```

### フォーク後の推奨対応

| 対応 | 理由 |
|------|------|
| `pyproject.toml` の `authors` を自分に更新 | 管理責任の明示 |
| `psycopg2-binary` を依存から削除（未使用） | 不要な依存を減らす |
| `CHANGELOG.md` を追加して独自変更を記録 | 監査・ロールバック対応 |
| プライベートリポジトリ化（商用時） | ソースコード非公開 |
| GitHub Actions で自動テストを設定（任意） | upstream マージ後の動作確認 |

### フォーク vs 完全独立（独自実装）の判断基準

```
元リポジトリの更新頻度が高く機能追加を享受したい → フォーク推奨
商用製品としてブランド・コードを完全に自社管理したい → 独自実装
```

現時点ではフォークで十分です。将来的に大幅な改修が必要になった場合に独自実装を検討してください。

---

## 2. OS・システム要件

| 項目 | 最低要件 | 推奨 | 備考 |
|------|---------|------|------|
| OS | Windows 10 22H2 | Windows 11 | Mac/Linux も可（パス変更が必要） |
| RAM | 8 GB | 16 GB 以上 | 埋め込みモデル（multilingual-e5-large）が約 1.5 GB 使用 |
| ストレージ | 10 GB 空き | 20 GB 以上 | モデルキャッシュ + ChromaDB |
| Python | 3.10 以上 | 3.13 | mcp-rag-server は 3.10+、本プロジェクトは 3.13+ |
| GPU | 不要 | あれば高速 | CPU 推論で動作する（CUDA 対応すると埋め込み生成が高速化） |

---

## 3. 必須ツール

| ツール | バージョン | インストール方法 | 用途 |
|--------|-----------|----------------|------|
| **Python** | 3.13+ | [python.org](https://www.python.org) | 本プロジェクト実行 |
| **Python** | 3.10+ | 同上（複数バージョン共存可） | mcp-rag-server 実行 |
| **uv** | 最新 | `pip install uv` | 仮想環境 + パッケージ管理 |
| **Git** | 2.x | [git-scm.com](https://git-scm.com) | リポジトリ管理 |

---

## 4. リポジトリ構成

### 必須（2リポジトリ）

```
C:\Users\matuu\Desktop\GameDevelopment\
  ├── mcp-rag-server\              ← フォーク済みRAGエンジン
  │   ├── src/
  │   │   ├── main.py             ← MCP サーバー起動点
  │   │   ├── cli.py              ← インデックス CLI
  │   │   └── document_processor.py
  │   ├── pyproject.toml
  │   └── .venv/                  ← uv sync で生成
  │
  └── DevelopmentRAGEnvironment\  ← 本プロジェクト
      ├── scripts/
      │   ├── rag_local_bridge.py ← HTTP API サーバー
      │   ├── auth_manager.py     ← 認証・アクセス制御
      │   ├── auto_index.py       ← ファイル監視・自動インデックス
      │   ├── document_pipeline.py← ドキュメント追加パイプライン
      │   └── rss_to_rag.py       ← RSS/arXiv 収集
      ├── scripts/static/
      │   ├── admin.html          ← 管理画面
      │   └── user_ui.html        ← ユーザーチャット画面
      ├── localRAG/               ← ドキュメント vault（gitignore）
      │   ├── tool_docs/
      │   ├── research/
      │   ├── team_notes/
      │   ├── personal_notes/
      │   └── game_info/
      └── data/
          └── auth.db             ← 認証DB（自動生成）
```

---

## 5. Python パッケージ

### mcp-rag-server（`uv sync` で自動インストール）

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
| `pyyaml` | >= 6.0.2 | 設定ファイル読み込み | MIT |
| `python-dotenv` | 最新 | 環境変数（mcp-rag-server 内部） | BSD 3-Clause |
| ~~`psycopg2-binary`~~ | — | PostgreSQL対応（**未使用・削除推奨**） | LGPL |

### DevelopmentRAGEnvironment（`uv sync` で自動インストール）

| パッケージ | バージョン | 用途 | ライセンス |
|-----------|-----------|------|-----------|
| `pyyaml` | >= 6.0.3 | YAML 処理 | MIT |
| `requests` | >= 2.34.2 | HTTP 通信 | Apache 2.0 |
| `python-dotenv` | >= 1.2.2 | 環境変数（旧スクリプト互換） | BSD 3-Clause |

### 別途インストールが必要なパッケージ

| パッケージ | インストールコマンド | 用途 | 使用スクリプト |
|-----------|-------------------|------|--------------|
| `feedparser` | `pip install feedparser` | RSS フィード取得 | `rss_to_rag.py` |

---

## 6. クラウドRAG 必要環境

クラウドRAGはローカルへのインストール不要。**Googleアカウント + Notionアカウント + ブラウザだけで動作する。**

### 6-1. 必要なアカウント・サービス

| サービス | 料金 | 用途 |
|---------|------|------|
| **Notion** | 無料プランで可 | ドキュメントDB（7つのDB）|
| **Google アカウント** | 無料 | GAS・Google Sheets・Gemini API |
| **Google AI Studio** | 無料枠あり | Gemini API キー発行 |

### 6-2. API キー（クラウドRAG用）

| API | 設定場所 | 必須 | 用途 |
|-----|---------|------|------|
| **Gemini API キー** | GAS スクリプトプロパティ `GEMINI_API_KEY` | **必須** | 埋め込み生成（gemini-embedding-001）+ 回答生成（gemini-2.5-flash）|
| **Notion Integration Token** | GAS スクリプトプロパティ `NOTION_API_KEY` | **必須** | Notion DB からページ取得 |

> **注意**: クラウドRAGの API キーはコードに直書きせず、GAS の「スクリプトプロパティ」に設定する。

### 6-3. Google Apps Script（GAS）

インストール不要。[script.google.com](https://script.google.com) でブラウザ上に作成する。

| 項目 | 内容 |
|------|------|
| 使用するファイル | `scripts/gas_cloud_rag.js`（リポジトリ内） |
| 実行時間制限 | 6分/実行（GAS の制約） |
| デプロイ形式 | **WebApp** として公開 |
| 実行ユーザー | 自分（GASオーナー） |
| アクセス権限 | 自分のみ / 全員（チーム公開時） |

**スクリプトプロパティ一覧（GASに設定が必要な値）:**

| プロパティ名 | 値 |
|------------|-----|
| `NOTION_API_KEY` | Notion Integration Token |
| `GEMINI_API_KEY` | Google AI Studio で発行したキー |
| `SHEETS_ID` | Google Sheets の ID（URLから取得） |
| `DB_TOOL_DOCS` | `249e442a-47dd-4a8d-95a8-8b856fb91ef6` |
| `DB_GAME_INFO` | `f201f73c-45dc-44cb-b8d7-a7be81b3644c` |
| `DB_RESEARCH` | `714d4d4a-6a85-4aa1-845c-32dc3e1a2b1f` |
| `DB_TEAM_NOTES` | `f898bf03-8c9f-40e0-9e1b-a28432703d69` |
| `DB_AFURI` | `a74822790ec34768bdef0917abae3e6f` |
| `DB_BRAINTQ` | `847b7db0f29f4190bee9f7ae7dd15514` |
| `DB_FOURTEEN` | `475cf278492a45ac90cbe4b8f11df1f5` |

### 6-4. Google Sheets（ベクトルインデックス）

インストール不要。[sheets.google.com](https://sheets.google.com) で新規作成するだけ。

| 項目 | 内容 |
|------|------|
| シート名 | `RAG_Index`（GASが自動生成） |
| 保存データ | `page_id / db / title / text / last_edited / embedding(768次元)` |
| 容量目安 | 100ページ ≈ 数MB（無料枠で十分） |
| 更新方法 | GASの `syncNotionToSheets()` を実行（差分同期） |

### 6-5. Notion DB（作成済み）

7つのDBはすでに作成済み。新規環境構築時は Notion Integration の「接続」を再設定するだけでよい。

| DB名 | 用途 |
|------|------|
| Tool Docs DB | ツール・ライブラリドキュメント |
| Game Info DB | ゲーム・プロジェクト情報 |
| Research DB | 調査・論文メモ |
| Team Notes DB | 議事録・チームメモ |
| AFURI DB | 阿夫利神社関連 |
| BrainTQ DB | BrainTQ関連 |
| Fourteen DB | Fourteen関連 |

**Notionページの必須プロパティ（検索精度に直結）:**

| プロパティ | 種類 | 重要度 |
|-----------|------|--------|
| `title` | タイトル | 必須 |
| `summary` | テキスト | **高**（空だと精度低下） |
| `source_url` | URL | 任意 |
| `tags` | マルチセレクト | 任意 |
| `collected_at` | 日付 | 任意 |

### 6-6. クライアント（Unity / Houdini）

クラウドRAGは GAS WebApp URL に HTTP リクエストを送るだけなので、追加インストールは不要。

**Unity クライアント:**

```
Assets/Editor/RAGChatbot/ フォルダをプロジェクトの Assets/Editor/ にコピー
  ├── RAGChatbotWindow.cs
  ├── CloudRAGClient.cs    ← GAS WebApp URL を設定
  ├── LocalRAGClient.cs    ← localhost:8766 を使用
  └── RAGGraphView.cs
```

設定: Unity エディタ → Window → RAG Chatbot → Settings タブ → GAS WebApp URL を入力

**Houdini クライアント:**

```
houdini/python_panels/ の以下を %USERPROFILE%\Documents\houdiniXX.X\python_panels\ にコピー
  ├── rag_chatbot.py
  └── graph_view.py
```

設定: Python Panel Editor → パネルに貼り付け → Settings タブ → GAS URL + モード設定

### 6-7. クラウドRAG セットアップ順序

```
1. Google AI Studio で Gemini API キーを取得
2. Notion で Integration Token を取得（既存のものを流用可）
3. Google Sheets を新規作成（空のまま）
4. script.google.com でGASプロジェクトを作成し、gas_cloud_rag.js を貼り付け
5. スクリプトプロパティに各キー・ID を設定
6. GAS で testEmbedding() を実行して疎通確認
7. GAS で syncNotionToSheets() を実行（初回同期、2〜5分）
8. GAS で WebApp としてデプロイ → URL を取得
9. Unity / Houdini のクライアントに URL を設定
```

---

## 7. 外部 API キー（ローカルRAG用）

| API | 環境変数名 | 必須 | 用途 | 取得先 |
|-----|-----------|------|------|--------|
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY` | **必須** | `/query` での回答生成 | console.anthropic.com |
| Gemini | `GEMINI_API_KEY` | 任意 | クラウド RAG（notion_to_corpus.py） | aistudio.google.com |
| Notion | `NOTION_API_KEY` | 任意 | Notion 連携スクリプト | notion.so/my-integrations |

### 環境変数のセット方法

```powershell
# セッション中のみ有効
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# システム環境変数に永続登録（管理者権限不要）
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "User")
```

> **注意**: `.env` ファイルは使用しない。`load_dotenv()` は削除済み。

---

## 8. データ・ストレージ

| パス | 内容 | Git 管理 |
|------|------|---------|
| `localRAG/` | ドキュメント vault（検索対象ファイル） | **gitignore（ローカルのみ）** |
| `mcp-rag-server/chroma_db/` | ChromaDB 永続化データ | **gitignore（ローカルのみ）** |
| `data/auth.db` | ユーザー認証 SQLite DB | **gitignore（ローカルのみ）** |
| `scripts/.rss_to_rag_seen.json` | RSS 既読管理 | **gitignore（ローカルのみ）** |

---

## 9. オプションツール

| ツール | 用途 | 必要な場面 |
|--------|------|-----------|
| **Claude Desktop** | MCP 経由で Claude から直接 RAG 検索 | Claude Desktop で会話しながら RAG を使いたい時 |
| **Ollama** | 完全オフライン化（Claude API なし） | インターネット不要環境・コスト削減 |
| **Research-Collector** | Zenn/arXiv/CEDEC 自動収集 | 情報収集を自動化したい時 |

### Ollama による完全オフライン化（オプション）

```powershell
# インストール
winget install Ollama.Ollama

# 日本語対応モデルをダウンロード
ollama pull llama3.2
ollama pull phi4      # 軽量・高速
```

`rag_local_bridge.py` の `_call_claude()` の endpoint を `http://localhost:11434/v1/chat/completions` に変更すれば Claude API 不要になります。

---

## 10. 起動手順（チェックリスト）

### ローカルRAG 初回セットアップ

```powershell
# [1] mcp-rag-server の依存関係インストール
cd C:\Users\matuu\Desktop\GameDevelopment\mcp-rag-server
uv sync

# [2] DevelopmentRAGEnvironment の依存関係インストール
cd C:\Users\matuu\Desktop\GameDevelopment\DevelopmentRAGEnvironment
uv sync
pip install feedparser   # RSS 収集を使う場合

# [3] namespace ディレクトリを作成
mkdir localRAG\tool_docs localRAG\research localRAG\team_notes localRAG\personal_notes localRAG\game_info

# [4] 管理者ユーザーを作成（API キーを必ず控える）
python scripts/auth_manager.py create-admin --name "Admin"
```

### ローカルRAG 通常起動

```powershell
# [1] 環境変数セット
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# [2] ブリッジ起動（メインターミナル）
cd C:\Users\matuu\Desktop\GameDevelopment\DevelopmentRAGEnvironment
python scripts/rag_local_bridge.py

# [3] ファイル監視（別ターミナル、任意）
python scripts/auto_index.py
```

### ローカルRAG アクセス先

| URL | 用途 |
|-----|------|
| `http://localhost:8766/health` | サーバー状態確認 |
| `http://localhost:8766/admin` | 管理者画面（ユーザー管理） |
| `http://localhost:8766/ui` | ユーザーチャット画面 |
| `http://localhost:8766/query` | Unity/Houdini 向け API |

### クラウドRAG セットアップ（初回）

```
1. Google AI Studio (aistudio.google.com) → Gemini API キーを取得
2. Notion (notion.so/my-integrations) → Integration Token を取得
3. Google Sheets (sheets.google.com) → 空のスプレッドシートを新規作成 → URLからSHEETS_IDをコピー
4. Google Apps Script (script.google.com) → 新規プロジェクト → gas_cloud_rag.js を貼り付け
5. GASのスクリプトプロパティに全キー・IDを設定（§6-3の表を参照）
6. GASで testEmbedding() を実行 → ログに「次元数: 768」が出れば OK
7. GASで syncNotionToSheets() を実行（2〜5分、初回は権限承認が必要）
8. GASで「デプロイ」→「新しいデプロイ」→ ウェブアプリ → URL を取得
9. Unity/Houdini クライアントの Settings タブに WebApp URL を入力
```

### クラウドRAG 更新手順（Notionに追記したとき）

```
GAS エディタ → syncNotionToSheets() を実行
→ 変更ページのみ差分更新（変更なしのページはスキップ）
```

---

## 11. トラブルシューティング

### ローカルRAG

| 症状 | 原因 | 対処 |
|------|------|------|
| `uv sync` でエラー | Python バージョン不一致 | `python --version` で確認。3.10+ が必要 |
| `chromadb` インストール失敗 | Visual C++ ランタイム不足 | Microsoft Visual C++ Redistributable をインストール |
| 埋め込みが遅い | CPU 推論（正常） | 初回は数分かかる。2回目以降はキャッシュで高速 |
| `401 Unauthorized` | API キー未設定 or 誤り | `auth_manager.py list` でユーザー確認 |
| `503 mcp-rag-server が起動していません` | mcp-rag-server のプロセスが落ちた | ブリッジを再起動 |
| RSS 収集でエラー | feedparser 未インストール | `pip install feedparser` |

### クラウドRAG

| 症状 | 原因 | 対処 |
|------|------|------|
| Notion 403エラー | Integration が DB の「接続」に追加されていない | 各DB → 右上「...」→「接続先」→ インテグレーション名を追加 |
| `SHEETS_ID エラー` | スクリプトプロパティ未設定 | スプレッドシートURLから正しくIDをコピーして設定 |
| Embedding エラー | Gemini APIキー不正 | `testEmbedding()` を実行して確認。キーを再発行 |
| 同期タイムアウト（6分超） | ページ数が多い | DBを分けて分割実行。通常100ページ以下なら問題なし |
| グラフが「データが空」 | RAG_Index が未構築 | `syncNotionToSheets()` を実行してインデックスを作成 |
| チャットが「考え中...」のまま | `chatHistory` 変数の競合 | `gas_cloud_rag.js` の JS変数名が `history` になっていないか確認（`chatHistory` に統一） |
