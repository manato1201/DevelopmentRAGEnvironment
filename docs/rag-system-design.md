# RAG 環境 システム設計ドキュメント

**更新日:** 2026-06-25  
**対象読者:** ゲーム開発チームのメンバー（エンジニア・非エンジニア問わず）

---

## 目次

1. [システム全体アーキテクチャ](#1-システム全体アーキテクチャ)
2. [各コンポーネントの説明](#2-各コンポーネントの説明)
3. [クラウド RAG vs ローカル RAG の使い分け](#3-クラウド-rag-vs-ローカル-rag-の使い分け)
4. [ベクトル検索とは](#4-ベクトル検索とは)
5. [グラフビューとは](#5-グラフビューとは)
6. [Unity / Houdini クライアント設計](#6-unity--houdini-クライアント設計)
7. [セキュリティ設計](#7-セキュリティ設計)
8. [実装フェーズ一覧](#8-実装フェーズ一覧)
9. [参考リンク](#9-参考リンク)

---

## 1. システム全体アーキテクチャ

システム全体を俯瞰すると、次のようなデータの流れになっています。

```
┌─────────────────────────────┐  ┌────────────────────────────────┐
│   Unity 6 EditorWindow      │  │  Houdini 21+ Python Panel      │
│  （Chat / Graph / Settings）│  │  （Chat / Graph / Settings）   │
└──────────┬──────────────────┘  └──────────────┬─────────────────┘
           │                                     │
     Cloud モード                          Local モード
           │ HTTPS POST                          │ HTTP POST
           ▼                                     ▼
┌──────────────────────┐       ┌─────────────────────────────────┐
│ GAS WebApp           │       │ rag_local_bridge.py             │
│ Notion 7DB           │       │ （HTTP → MCP 変換ブリッジ）     │
│ Gemini 2.5 Flash     │       │ ポート: localhost:8766           │
│ Google Sheets（ログ）│       └─────────────┬───────────────────┘
└──────────┬───────────┘                     │ MCP stdio
           │                                 ▼
           │                 ┌───────────────────────────────────┐
           │                 │ mcp-rag-server                    │
           │                 │ ChromaDB（ベクトルDB）            │
           │                 │ multilingual-e5-large（埋め込み） │
           │                 │ Claude Haiku（回答生成）           │
           │                 └─────────────────────────────────--┘
           │
     グラフ表示                        グラフ表示
           │ ?action=graph                   │ GET /graph
           ▼                                 ▼
┌──────────────────────┐       ┌─────────────────────────────────┐
│ GAS buildGraphData_()│       │ rag_graph_export.py             │
│ D3.js 可視化         │       │ Spring Layout → JSON 生成       │
└──────────────────────┘       └─────────────────────────────────┘
```

---

## 2. 各コンポーネントの説明

### GAS WebApp（クラウド側の司令塔）

**GAS（Google Apps Script）** は Google が提供するサーバーレス（サーバーを自分で用意しなくてよい）スクリプト環境です。

このシステムでは GAS が以下をすべて担当しています：

1. Unity・Houdini からの質問を受け取る
2. Notion のデータベースを検索して関連ドキュメントを取得する
3. 取得したドキュメントと質問を Gemini AI に送って回答を生成する
4. 回答を Unity・Houdini に返す
5. チャット履歴を Google Sheets に記録する

### Notion 7DB（クラウド側のドキュメント置き場）

チームで共有するドキュメントを 7 つのデータベースに分けて管理しています。

| DB 名 | 内容 |
|-------|------|
| Tool Docs DB | Unity・Houdini・DirectX12 などのツール仕様 |
| Game Info DB | ゲーム設計書・共有ゲーム情報 |
| Research DB | 論文・技術記事（手動で精査したもの） |
| Team Notes DB | ゼミ資料・議事録・方針 |
| Chat Logs DB | チャット履歴 |
| Tutorials DB | チュートリアル生成結果 |
| Personal Notes DB | 個人メモ・進捗 |

### mcp-rag-server（ローカル側の検索エンジン）

[karaage0703/mcp-rag-server](https://github.com/karaage0703/mcp-rag-server) をベースに、このプロジェクト向けに改造したものです。

**主な役割:**
- `localRAG/` フォルダ内のドキュメントをベクトル（数値の配列）に変換して保存する
- 質問を受け取ったとき、似たドキュメントを高速に検索して返す
- Claude Code などの AI ツールからは MCP（Model Context Protocol）という専用通信方式で呼ばれる

**オリジナルからの主な変更点:**
- ベクトル DB を PostgreSQL/pgvector から **ChromaDB** に変更（Docker 不要、Windows で即動く）
- Windows 11 ネイティブ対応（WSL2 不要）
- **ハイブリッド検索**を追加: ベクトル検索（意味の近さ）＋ BM25（キーワード一致）を組み合わせて精度向上

### rag_local_bridge.py（MCP を HTTP に変換する中継役）

`mcp-rag-server` は AI ツール専用の MCP 通信方式で動いています。しかし Unity（C#）や Houdini（Python）は MCP に対応していません。

そこで **rag_local_bridge.py** が中継役として動き、Unity/Houdini からの HTTP リクエストを MCP コマンドに変換して `mcp-rag-server` に渡します。

```
Unity C# / Houdini Python
    ↓ HTTP POST（誰でも使える通信方式）
rag_local_bridge.py（:8766 で待機）
    ↓ MCP stdio（AI ツール専用通信）
mcp-rag-server
    ↓ 検索結果
rag_local_bridge.py
    ↓ HTTP JSON レスポンス
Unity C# / Houdini Python
```

**なぜ必要か:** Unity の C# や Houdini の Python から MCP を直接呼ぶにはかなりの実装が必要です。HTTP ならどの言語でも 5 行程度で書けるため、中継サーバーを 1 つ作る方が全体のコスト（実装量）が低くなります。

### rag_graph_export.py（グラフデータ生成スクリプト）

ChromaDB に保存されているドキュメント間の類似度（どのくらい似ているか）を計算し、ネットワーク図として表示するための JSON ファイルを生成します。

**Spring Layout（バネレイアウト）** というアルゴリズムを使って、似ているドキュメントが近くに配置されるよう自動的に座標を決めています。

---

## 3. クラウド RAG vs ローカル RAG の使い分け

| 比較項目 | クラウド RAG | ローカル RAG |
|----------|-------------|-------------|
| ドキュメント置き場 | Notion（オンライン） | localRAG/ フォルダ（PC 内） |
| 検索・回答エンジン | Gemini 2.5 Flash（Google） | Claude Haiku（Anthropic） |
| ネット接続 | 必要 | 不要 |
| チームで共有 | できる | できない（個人のみ） |
| 向いている情報 | ツール仕様・設計書・技術記事 | チャット履歴・個人メモ・下書き |
| Unity/Houdini での切り替え | Settings タブで選択 | Settings タブで選択 |

---

## 4. ベクトル検索とは

「ベクトル（vector）」とは数値の配列のことです。テキストをベクトルに変換することを「埋め込み（embedding）」と呼びます。

このシステムでは `multilingual-e5-large` というモデルが、テキストを 1024 個の数値の配列に変換しています。

**なぜこれが役立つのか:**  
意味が似ているテキストは、変換後の数値配列が近い値になります。これを利用して「意味の近さ」でドキュメントを検索できます。

```
例）
「Unity の物理演算を使う方法」
→ [0.12, 0.87, -0.23, ...]（1024 次元）

「Unity Rigidbody コンポーネントのチュートリアル」
→ [0.13, 0.85, -0.21, ...]（1024 次元、近い！）

「Houdini の VEX スクリプト」
→ [0.71, -0.34, 0.55, ...]（1024 次元、遠い）
```

このシステムでは、ベクトル検索に加えてキーワード検索（BM25）も組み合わせる **ハイブリッド検索** を採用しています。意味の近さとキーワードの一致の両方で探すため、片方だけより精度が上がります。

---

## 5. グラフビューとは

ドキュメント間の「意味の近さ」をネットワーク図（グラフ）として可視化する機能です。

- **ノード（丸い点）** = 1 つのドキュメント
- **エッジ（線）** = ドキュメント間の関係（類似度が高いほど近くに配置）

**どこで見られるか:**

| 環境 | 表示方法 |
|------|----------|
| Unity 6 | RAG Chatbot ウィンドウの Graph タブ（IMGUI Painter2D で描画） |
| Houdini 21+ | graph_view.py パネル（QGraphicsView で描画、ノードをドラッグ移動可能） |
| クラウド | GAS WebApp の `?action=graph` エンドポイント（D3.js で描画） |
| ローカル | `rag_graph_export.py` が生成した JSON をクライアントが受け取って描画 |

---

## 6. Unity / Houdini クライアント設計

### IRAGClient インターフェース

Unity の C# コードでは、クラウドとローカルを切り替えられるよう **インターフェース（interface）** を使っています。インターフェースとは「このメソッド（関数）を必ず実装してね」という約束事です。

```
IRAGClient（インターフェース：約束事）
├── CloudRAGClient（クラウド用の実装）
│   └── GAS WebApp へ HTTPS POST
└── LocalRAGClient（ローカル用の実装）
    └── localhost:8766 へ HTTP POST
```

Settings タブでどちらを使うか選ぶと、内部で `CloudRAGClient` か `LocalRAGClient` かが切り替わります。チャット画面のコードはどちらが選ばれているかを気にせず動くので、将来新しい接続先が増えても簡単に対応できます。

### CloudRAGClient

GAS WebApp の URL に HTTPS（暗号化された HTTP）で POST リクエストを送ります。

- 送るデータ: 質問テキスト・対象 DB・会話履歴
- 受け取るデータ: AI の回答テキスト

### LocalRAGClient

`rag_local_bridge.py` が起動している `localhost:8766` に HTTP で POST リクエストを送ります。

- 送るデータ: 質問テキスト・Namespace（フォルダ名）
- 受け取るデータ: 検索結果・AI の回答テキスト

### RAGChatbotWindow（Unity EditorWindow）

Unity 6 のエディタ拡張として作られた 3 タブ構成のウィンドウです。

| タブ | 内容 |
|------|------|
| **Chat** | AI とのチャット（マルチターン対応：会話の文脈を保持） |
| **Graph** | ドキュメント間の関係をネットワーク図で表示 |
| **Settings** | Cloud / Local の切り替え・接続先 URL・API キー設定 |

### Houdini Python Panel

Houdini 21+ の PySide6（Python 用の GUI ライブラリ）で作られたパネルです。

- `rag_chatbot.py`: チャット UI（Chat / Settings タブ）
- `graph_view.py`: グラフビュー（ノードをマウスでドラッグして配置を変えられる）

---

## 7. セキュリティ設計

### API キーの管理方法

API キー（外部サービスにアクセスするためのパスワード）の保管場所は、環境ごとに使い分けています。

| 環境 | 保管場所 | 理由 |
|------|----------|------|
| ローカルスクリプト（Python） | OS の環境変数 | ファイルに書くと Git に混入するリスクがある |
| Unity エディタ | `EditorPrefs`（Unity の設定ファイル） | プロジェクトファイルとは別の場所に保存されるため Git に含まれない |
| Houdini | `rag_config.json`（Houdini の設定フォルダ内） | プロジェクトとは別のフォルダに置くことで Git に含まれない |
| GAS | GAS のスクリプトプロパティ | Google のサーバー側に保存、コードに直書きしない |

### .env ファイルを使わないポリシー

`.env` ファイルに API キーを書いてしまうと、`.gitignore` の設定ミス 1 つで GitHub に流出するリスクがあります。  
このプロジェクトでは各ツールのネイティブな設定ストレージ（OS 環境変数・EditorPrefs・JSON 設定ファイル）を使うことで、**そもそもキーがファイルとして存在しない** 状態にしています。

開発開始時の初期設定用として `.env.example`（値が空のテンプレート）は存在しますが、実際のキーを記入した `.env` は絶対に Git にコミットしません。

---

## 8. 実装フェーズ一覧

すべてのフェーズは完了済みです。

| フェーズ | 内容 | 主な成果物 |
|----------|------|-----------|
| **Phase 1** | クラウド RAG 基盤構築 | Notion 7DB・GAS WebApp・Gemini 連携・マルチターン対応 |
| **Phase 2** | ローカル HTTP ブリッジ | `scripts/rag_local_bridge.py`（:8766 で待機） |
| **Phase 3** | Unity C# クライアント | `IRAGClient` インターフェース・`CloudRAGClient`・`LocalRAGClient` |
| **Phase 4** | Unity EditorWindow | `RAGChatbotWindow.cs`（Chat / Settings タブ） |
| **Phase 5** | Unity グラフビュー | `RAGGraphView.cs`（IMGUI Painter2D）・`/graph` エンドポイント |
| **Phase 6** | Houdini Python Panel | `rag_chatbot.py`（PySide6 チャット UI） |
| **Phase 7** | Houdini グラフビュー | `graph_view.py`（QGraphicsView、ノードドラッグ対応） |
| **Phase 8** | GAS グラフ API + D3.js | `buildGraphData_()` 関数・`?action=graph` エンドポイント |

---

## 9. 参考リンク

| リソース | URL |
|----------|-----|
| manato1201/mcp-rag-server（使用フォーク） | https://github.com/manato1201/mcp-rag-server |
| karaage0703/mcp-rag-server（オリジナル） | https://github.com/karaage0703/mcp-rag-server |
| mcp-rag-server 解説記事 | https://zenn.dev/mkj/articles/30eeb69bf84b3f |
| Notion API リファレンス | https://developers.notion.com/ |
| Gemini API ドキュメント | https://ai.google.dev/gemini-api/docs |
| uv — Python パッケージマネージャー | https://docs.astral.sh/uv/ |
| multilingual-e5-large（埋め込みモデル） | https://huggingface.co/intfloat/multilingual-e5-large |
