# クラウドRAG環境ガイド

**統合元:** cloud-rag-setup.md + rag-system-design.md（Cloud RAG部分）
**統合日:** 2026-06-30
**構成:** Notion + Google Apps Script + Gemini gemini-embedding-001 + Google Sheets

---

## 目次

1. [概要](#1-概要)
2. [アーキテクチャ](#2-アーキテクチャ)
3. [セットアップ手順](#3-セットアップ手順)
4. [検索品質向上機能](#4-検索品質向上機能)
5. [管理者機能](#5-管理者機能)
6. [クライアント連携（Unity / Houdini）](#6-クライアント連携unity--houdini)
7. [評価機能（👍/👎）](#7-評価機能)
8. [セキュリティ設計](#8-セキュリティ設計)
9. [トラブルシューティング](#9-トラブルシューティング)
10. [実装フェーズ一覧](#10-実装フェーズ一覧)
11. [参考リンク](#11-参考リンク)

---

## 1. 概要

このプロジェクトの RAG（Retrieval-Augmented Generation）環境は、**クラウド RAG** と **ローカル RAG** の二層構成になっている。本ドキュメントは、その片方である **クラウド RAG**（Notion + Google Apps Script + Gemini + Google Sheets）について解説する。ローカル RAG（ChromaDB・rag_service.py 等）については `docs/local-rag.md` を参照のこと。

### クラウド RAG vs ローカル RAG の使い分け

| 比較項目 | クラウド RAG | ローカル RAG |
|----------|-------------|-------------|
| ドキュメント置き場 | Notion（オンライン） | localRAG/ フォルダ（PC 内） |
| 検索・回答エンジン | Gemini 2.5 Flash（Google） | Claude Haiku（Anthropic） |
| ネット接続 | 必要 | 不要 |
| チームで共有 | できる | できない（個人のみ） |
| 向いている情報 | ツール仕様・設計書・技術記事 | チャット履歴・個人メモ・下書き |
| Unity/Houdini での切り替え | Settings タブで選択 | Settings タブで選択 |

クラウド RAG は、チームで共有すべきツール仕様・設計書・技術記事などをオンラインの Notion 上で一元管理し、どこからでも（ネット接続さえあれば）検索・質問できることを目的としている。一方、個人のチャット履歴やメモなど共有不要な情報はローカル RAG に置く、という棲み分けである。

---

## 2. アーキテクチャ

### 2.1 全体構成図

```
Notion (8DB)
    ↓ GAS: syncNotionToSheets()
Google Sheets (RAG_Index)
  [page_id | db | title | text | last_edited | embedding(768次元)]
    ↓ クエリ時: GAS がクエリをベクトル化 → コサイン類似度
Gemini gemini-embedding-001  ←→  gemini-2.5-flash（回答生成）
    ↓
チャット WebApp
```

> **注:** Gemini Corpus API（Semantic Retrieval）・`text-embedding-004` は日本リージョン非対応のため、
> `gemini-embedding-001`（768次元）+ Google Sheets によるベクトル検索を採用している。

システム全体を俯瞰すると、クラウド側は次のような経路で動く。

```
┌─────────────────────────────┐  ┌────────────────────────────────┐
│   Unity 6 EditorWindow      │  │  Houdini 21+ Python Panel      │
│  （Chat / Graph / Settings）│  │  （Chat / Graph / Settings）   │
└──────────┬──────────────────┘  └──────────────┬─────────────────┘
           │                                     │
     Cloud モード                          Cloud モード
           │ HTTPS POST                          │ HTTPS POST
           ▼                                     ▼
┌───────────────────────────────────────────────────────────────┐
│ GAS WebApp                                                    │
│ Notion 8DB（houdini21 含む）                                  │
│ Gemini gemini-embedding-001（埋め込み）/ gemini-2.5-flash（回答）│
│ Google Sheets（RAG_Index / RAG_Memory ログ）                  │
└──────────────────────┬──────────────────────────────────────┘
                        │
                  グラフ表示
                        │ ?action=graph
                        ▼
        ┌──────────────────────┐
        │ GAS buildGraphData_()│
        │ D3.js 可視化         │
        └──────────────────────┘
```

### 2.2 GAS WebApp（クラウド側の司令塔）

**GAS（Google Apps Script）** は Google が提供するサーバーレス（サーバーを自分で用意しなくてよい）スクリプト環境。このシステムでは GAS が以下をすべて担当している。

1. Unity・Houdini・ブラウザからの質問を受け取る
2. Notion のデータベースを検索して関連ドキュメントを取得する
3. 取得したドキュメントと質問を Gemini AI に送って回答を生成する
4. 回答をクライアントに返す
5. チャット履歴を Google Sheets に記録する

### 2.3 Notion 8DB（クラウド側のドキュメント置き場）

チームで共有するドキュメントを 8 つのデータベースに分けて管理している。

> **非公開情報について:** 各DBの `database_id` および Notion 上のURLは、Notionワークスペースへの直接的なアクセス手がかりになるため本ドキュメントには記載しない。セットアップ時は自分の Notion ワークスペースで発行した database_id を GAS のスクリプトプロパティ（§3.5）に設定すること。Google Drive で運用する場合（§3.5.1）の folder ID も同様に非公開情報として扱い、リポジトリやドキュメントには記載しない。

各 DB の主な用途:

| DB 名 | 内容 |
|-------|------|
| Tool Docs DB | Unity・Houdini・DirectX12 などのツール仕様 |
| Game Info DB | ゲーム設計書・共有ゲーム情報 |
| Research DB | 論文・技術記事（手動で精査したもの） |
| Team Notes DB | ゼミ資料・議事録・方針 |
| AFURI / BrainTQ / Fourteen DB | 各プロジェクト固有のドキュメント |
| houdini21 DB | Houdini 21 専用の技術ドキュメント |

### 2.4 namespace（名前空間）設計

各 DB は検索 API 上では「名前空間（namespace）」として扱われる。APIキーごとに、どの名前空間にアクセスできるかを制御できる（§5.1 参照）。houdini21 は他の DB とは独立した専用の名前空間として追加されており、APIキー編集 UI から個別に許可・剥奪が可能。

---

## 3. セットアップ手順

**所要時間:** 約60〜90分

> **Notion DB作成済み（2026-06-22）:** 8つのDBはすでにワークスペースに作成されている。下記 §3.2 はスキップ可能。

### 3.1 前提条件

| 項目 | 要件 |
|------|------|
| Notion | アカウントあり（無料プランで可） |
| Google アカウント | GAS・Gemini API用 |
| Gemini API キー | Google AI Studio で発行（無料枠あり） |
| Notion Integration | `notion_bulk_add.py` で使用中のものを流用可 |

### 3.2 Notion DBの作成

> **作成済みの場合はこのステップをスキップ。**

#### 3.2.1 共通スキーマ（全DBで統一）

| プロパティ名 | 種類 | 説明 |
|-------------|------|------|
| `title` | タイトル | ページタイトル（デフォルト） |
| `source_url` | URL | 元記事・ドキュメントのURL |
| `tags` | マルチセレクト | `Unity` `Houdini` 等 |
| `summary` | テキスト | 内容の要約（100〜200字） ← **検索精度に直結** |
| `collected_at` | 日付 | 追加日 |

#### 3.2.2 Notionインテグレーションの接続

[notion.so/my-integrations](https://www.notion.so/my-integrations) で発行した Integration Token を、各DBの「設定」→「接続」→「インテグレーションを追加」で紐付ける。

#### 3.2.3 houdini21 DB のセットアップ

houdini21DB は他のDBとは別に追加された専用DB。以下の手順でセットアップする。

1. Notion で houdini21DB を開き、右上「...」→「接続先」→ Notion Integration を追加する
2. URLから `database_id` をコピー（`https://www.notion.so/xxxxxxxx...` の 32文字部分）
3. GASエディタ → 「プロジェクトの設定」→「スクリプトプロパティ」で以下を追加：
   - プロパティ名: `DB_HOUDINI21`
   - 値: コピーした database_id
4. GASエディタで `syncNotionToSheets` を実行して houdini21 ページを同期する

> **確認:** 実行ログに `[houdini21] Notionページ取得中...` と表示されれば成功。

### 3.3 Gemini APIキーの取得

1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. 「Get API key」→「Create API key」
3. 発行されたキーをメモ（後でGASのスクリプトプロパティに設定）

> **注意:** APIキーをコード内に直書きしない。GASのスクリプトプロパティを使う。

### 3.4 GASプロジェクトの作成・コード貼り付け

1. [script.google.com](https://script.google.com) で「新しいプロジェクト」を作成
2. プロジェクト名を `cloud-rag-chatbot` に変更
3. エディタの内容を全削除し、`scripts/gas_cloud_rag.js` の内容をそのまま貼り付け
4. Ctrl+S で保存

### 3.5 スクリプトプロパティの設定

「プロジェクトの設定」→「スクリプトプロパティ」→「プロパティを追加」

| プロパティ名 | 値 |
|-------------|-----|
| `NOTION_API_KEY` | Notionのインテグレーションキー |
| `GEMINI_API_KEY` | Google AI Studio で発行したキー |
| `SHEETS_ID` | **次のステップで取得するID**（★必須・新規） |
| `DB_TOOL_DOCS` | 自分の Notion ワークスペースの Tool Docs DB の database_id |
| `DB_GAME_INFO` | 自分の Notion ワークスペースの Game Info DB の database_id |
| `DB_RESEARCH` | 自分の Notion ワークスペースの Research DB の database_id |
| `DB_TEAM_NOTES` | 自分の Notion ワークスペースの Team Notes DB の database_id |
| `DB_AFURI` | 自分の Notion ワークスペースの AFURI DB の database_id |
| `DB_BRAINTQ` | 自分の Notion ワークスペースの BrainTQ DB の database_id |
| `DB_FOURTEEN` | 自分の Notion ワークスペースの Fourteen DB の database_id |
| `DB_HOUDINI21` | Notion houdini21DB の database_id（§3.2.3 参照） |
| `API_KEYS_CONFIG` | **手動設定不要。** `bootstrapFirstAdminKey()` 実行時および管理画面からの操作により GAS が自動管理する。 |

> **database_id の調べ方:** 各DBをブラウザで開き、URL中の `https://www.notion.so/xxxxxxxx...?v=...` の `xxxxxxxx...` 部分（32文字、ハイフンなし）が database_id。

### 3.5.1 Notionの代わりに Google Drive を使う場合

namespaceごとに、Notionの代わりに Google Drive の共有フォルダでドキュメントを管理することもできる。「Notionアカウントを配布先が持っていない」「すでにGoogle Workspaceでチーム運用している」といったケースに向いている。Notionと混在も可能（例: `tool_docs`だけDrive、他はNotionのまま）。

**仕組み:** `syncNotionToSheets`（内部的には`syncAllSources_`）は、各namespaceについて `DB_<KEY>`（Notion database_id）が設定されていればNotionから、未設定で `DRIVE_<KEY>`（Driveフォルダ ID）が設定されていればDriveから取得する。両方設定されている場合はNotionを優先する。

#### 手順

1. Google Drive で namespaceごとにフォルダを作成する（例: `RAG_ToolDocs`, `RAG_Research` 等）
2. フォルダ内に Markdown ファイル（`.md`）または Google ドキュメントを配置する。各ファイルの1件が Notion の1ページに相当する
3. Markdownファイルの場合、先頭に以下のような frontmatter を書くとNotionと同じ形式（タイトル・要約・タグ・参照URL）で扱われる（省略した場合はファイル名がタイトルになる）:

```markdown
---
title: Rigidbody の基礎
summary: Unity の物理演算コンポーネントの概要と使い方
tags: Unity, Physics
source_url: https://docs.unity3d.com/...
---

ここから本文...
```

4. フォルダのURLから folder ID を取得する:

```
https://drive.google.com/drive/folders/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                        これが folder ID
```

5. GASエディタ →「プロジェクトの設定」→「スクリプトプロパティ」で該当namespaceの `DRIVE_<KEY>` に folder ID を設定する（例: `DRIVE_TOOL_DOCS`）。**同じnamespaceの `DB_<KEY>` は設定しない**（設定されているとNotionが優先されてDriveが無視される）
6. GASの実行アカウント（デプロイ時に「自分」として実行するアカウント）がそのDriveフォルダを閲覧できる状態にする（自分のGoogleアカウントで作成したフォルダなら追加設定は不要）
7. `syncNotionToSheets` を実行する。初回実行時にDriveへのアクセス許可を求められるので許可する。実行ログに `[tool_docs] (Drive) N ファイル 更新:N` のように表示されれば成功

> **対応ファイル形式:** `.md` / `.txt` / Google ドキュメント。PDF・画像・スプレッドシート等は無視される（対応外）。
> **サブフォルダ:** 辿らない（フラット走査）。サブフォルダに分けたい場合はnamespaceごとにフォルダを分けること。
> **差分同期:** ファイルの更新日時（`getLastUpdated()`）で比較するため、Notionと同様に変更のないファイルはスキップされる。

### 3.6 Google Sheets の準備

ベクトルインデックスを保存するスプレッドシートを用意する。

1. [Google スプレッドシート](https://sheets.google.com) で新規ファイルを作成（名前は何でも可）
2. URLから `SHEETS_ID` を取得：

```
https://docs.google.com/spreadsheets/d/XXXXXXXXXXXXXXXXXXXXXXXXXX/edit
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^
                                       これが SHEETS_ID
```

3. コピーした ID を §3.5 の `SHEETS_ID` プロパティに貼り付ける

> シートの中身は GAS が自動で作成するので、空のままで OK。

### 3.7 Notion→Sheetsの初回同期

GASエディタで初回インデックスを構築する。

#### 3.7.1 Embedding API の疎通確認

1. GASエディタで関数リストから `testEmbedding` を選択
2. 「実行」→「実行ログ」で以下のような出力を確認：

```
次元数: 768  先頭3値: 0.0123,0.0456,-0.0789
```

エラーが出る場合は `GEMINI_API_KEY` のスクリプトプロパティを確認。

#### 3.7.2 全DBを同期

1. 関数リストから `syncNotionToSheets` を選択
2. 「実行」（初回は権限承認ダイアログが出る → 許可する）
3. 実行ログに以下のような出力が出るまで待つ（2〜5分）：

```
[afuri] Notionページ取得中...
  4ページ
  → 阿夫利神社下社
  → 柚子塩らーめん
  ...
同期完了  更新:XX件  スキップ:0件  エラー:0件
インデックス合計: XX件
```

4. Google Sheets を開いて `RAG_Index` シートにデータが入っているか確認

#### 3.7.3 検索テスト

```
関数: testSearch
```

実行ログに検索結果が表示されれば完成。

### 3.8 WebAppとして公開

認証方式は **APIキー統一方式**。ブラウザ・Unity・Houdini・curl すべてで同じAPIキーを使用する。Google SSO（Session.getActiveUser）は使用しない。

#### 3.8.1 管理者APIキーの初期化

1. GASエディタで関数リストから `bootstrapFirstAdminKey` を選択して「実行」
2. 実行ログに管理者APIキー（32文字のhex文字列）が **一度だけ** 表示される
3. このキーを安全な場所（パスワードマネージャー等）に必ず保存する

> **注意:** ログを閉じると二度と確認できません。保存し忘れた場合はスクリプトプロパティから `API_KEYS_CONFIG` を削除して再実行してください。

#### 3.8.2 WebAppのデプロイ

1. GASエディタ右上「デプロイ」→「新しいデプロイ」
2. 種類: **ウェブアプリ**
3. 設定：
   - 説明: `cloud-rag v3 (api-key-auth)`
   - 次のユーザーとして実行: **自分 (Me)**
   - アクセスできるユーザー: **Googleアカウントを持つ全員**
4. 「デプロイ」→ WebApp URL が表示される（メモしておく）

#### 3.8.3 ログインと初期設定

1. WebApp URL をブラウザで開く → ログイン画面が表示される
2. §3.8.1 で保存した管理者APIキーを入力してログイン
3. 「管理」タブ → 「🔑 APIキー管理」サブタブを開く
4. 「新しいキーを発行」フォームでユーザー／クライアント用のキーを発行する

> **管理タブの表示条件:** `isAdmin=true` のキーでログインした場合のみ管理タブが表示される。通常ユーザーキーではチャット・グラフタブのみ利用可能。

### 3.9 Notionにページを追加したあとの更新方法

Notion でページを追加・編集したあとは、GAS で差分同期を実行する。

1. GASエディタを開く
2. 関数 `syncNotionToSheets` を選択して実行
3. ログで「更新: N件」と表示されれば反映完了

> **差分同期:** `last_edited_time` を比較するため、変更されていないページはスキップされ高速に動作する。

#### 3.9.1 並列同期の仕組み（v2実装）

`syncNotionToSheets` は `UrlFetchApp.fetchAll()` を使って並列化されている。

| フェーズ | 処理 | 旧（直列） | 新（並列） |
|---------|------|-----------|-----------|
| Phase 1 | 全DB ページ一覧取得 | 7回×直列 | `fetchAll` 1回（7並列） |
| Phase 2 | 更新ページの本文取得 | N回×直列+sleep | `fetchAll` 1〜2回（N並列） |
| Phase 3 | Embedding生成 | 1チャンクずつ+sleep | `fetchAll` 10件バッチ |

20ページ更新・60チャンクの場合の目安: 旧 ~22秒 → 新 ~2秒

### 3.10 LocalRAG → Notion 移行ツール

ローカルの Markdown ファイルを Notion DB に一括移行するスクリプト。

```bash
python scripts/localrag_to_notion.py \
  --notion-key secret_xxx \
  --db-id f201f73c-45dc-44cb-b8d7-a7be81b3644c \
  localRAG/personal_notes/*.md
```

**対応する Markdown 要素:**

| 要素 | Notion ブロック変換 |
|------|-------------------|
| `# ## ###` 見出し | heading_1 / heading_2 / heading_3 |
| `-` 箇条書き | bulleted_list_item |
| `1.` 番号付き | numbered_list_item |
| ` ```lang ``` ` コードブロック | code（言語マッピング自動変換） |
| `\| ... \|` テーブル行 | paragraph（"A / B / C" 形式） |
| 本文テキスト | paragraph |

**言語マッピング（Notion の厳格な allowlist に対応）:**

```
csharp → c#    cpp → c++    js → javascript    py → python    sh → shell
```

**冪等性:** 同名ページが既存の場合は自動アーカイブしてから再作成（重複なし）。

---

## 4. 検索品質向上機能

2026-06-29 に追加した検索精度向上機能群。HyDE・閾値フィルタ・重複排除・情報抽出度メトリクスの4本柱で構成される。

### 4.1 RAGクエリパイプライン（更新後）

```
クエリ受信
  → HyDE仮説文書生成（Gemini）
  → 加重平均埋め込み（ドメイン別の重み。下記参照）
  → ベクトル検索（threshold filter + page dedup）
  → LLM回答生成
  → 引用解析（extractionRate）
```

### 4.2 HyDE（Hypothetical Document Expansion）— `hydeExpand_()` in `gas_cloud_rag.js`

クエリ時に `hydeExpand_()` 関数が自動で呼ばれ、検索精度を向上させる。ユーザー側の設定変更は不要。

**課題:** クエリ「VEX スクリプトのループ構文」と文書「for ループを使った例」は意味が同じでも語彙が違うため、単純なベクトル検索では見つかりにくい。

**解決策:** クエリを受け取ったとき、まず Gemini に「このクエリに答えるような文書を仮に書いてください」と依頼して仮説文書（Hypothetical Document）を生成する。この仮説文書の埋め込みとクエリ埋め込みの加重平均を実際の検索ベクトルとして使う。

```
クエリ埋め込み × Wq
                          → 加重平均埋め込み → ベクトル検索
仮説文書埋め込み × Wh
```

#### ドメイン別 HyDE 重み付け（本番運用で発覚したハルシネーション対策）

当初は全DB一律でクエリ40%・仮説60%の重み付けを使用していたが、afuri / braintq / fourteen の各DBで仮説文書への依存度が高すぎることに起因するハルシネーション（仮説文書の内容に引っ張られて事実と異なる回答を生成する現象）が本番運用中に発覚した。そのため、ドメインごとに重みを使い分ける方式に変更されている。

| ドメイン | クエリ重み | 仮説重み | 理由 |
|---------|-----------|---------|------|
| afuri / braintq / fourteen | **0.8** | **0.2** | 仮説文書への過度な依存によるハルシネーションが確認されたため、元クエリの意図を強く保持する設定に変更 |
| houdini21 / tool_docs / research | 0.4 | 0.6 | 専門用語の語彙ブリッジが有効に働くドメインのため、仮説文書側の重みを高く維持 |

```
[afuri / braintq / fourteen]
クエリ埋め込み × 0.8 → 加重平均埋め込み → ベクトル検索
仮説文書埋め込み × 0.2

[houdini21 / tool_docs / research]
クエリ埋め込み × 0.4 → 加重平均埋め込み → ベクトル検索
仮説文書埋め込み × 0.6
```

#### ドメイン別 HyDE プロンプト

DBごとに異なるドメインヒントを使用することで、クロスドメイン汚染（Houdini質問に飲食店文書がヒットする等）を防止する。

| DB | ドメインヒント |
|----|---------------|
| tool_docs | Houdini/Unity技術文書 |
| houdini21 | Houdini 21専門技術 |
| research | 研究論文・技術記事 |
| game_info | ゲーム設計・仕様 |

### 4.3 MIN_SCOREフィルタ（閾値フィルタ）

| 検索モード | 閾値 | 理由 |
|-----------|-----|------|
| DB指定検索（単一DB） | コサイン類似度 0.58 以上のみ採用 | ノイズ除去 |
| 全DB横断検索（`all`） | コサイン類似度 0.62 以上のみ採用 | より厳格なフィルタ |

### 4.4 ページ単位重複排除

同一Notionページタイトル（page_id）の複数チャンクが検索にヒットした場合、最高スコアのチャンク1件のみを残し、残りを除外する。これにより検索結果の多様性（ソース数）が確保される。

### 4.5 maxOutputTokens の拡張

回答生成の上限を 1024 → **2048** トークンに拡張済み。

### 4.6 情報抽出度メトリクス — `parseExtractionRate_()` in `gas_cloud_rag.js`

回答中の `[1]`・`[2]` 形式の引用番号を解析し、実際に使用されたソース数を表示する。

```
extractionRate = 引用されたユニークソース数 ÷ 提供された総ソース数
例: 5件提供 → 回答中に[1][3][4]を引用 → 抽出度 3/5 = 0.60
```

Unity・Houdini UI では引用バッジ（✓ 3/5 ソース）と進捗バーで可視化される。

### 4.7 Cloud RAG 検索品質向上（評価メモリ連携）

| 改善点 | 内容 |
|--------|------|
| TF-IDF 風重み付きスコア | `overlapCount × (1 + priority)` で評価済みエントリを優先 |
| 👎 エントリ除外 | `rating === 'down'` のエントリを検索結果から完全除外 |
| 最低スコア閾値 | weightedScore < 1.5 のエントリを除外 |
| 低優先度エントリ除外 | priority < 0.3 のエントリをコンテキスト注入から除外 |
| dbKey バリデーション | 不正な dbKey は "all" に安全フォールバック |

---

## 5. 管理者機能

### 5.1 管理画面の構成

「管理」タブはサブタブ構成になっている。

| サブタブ | 内容 |
|---------|------|
| 🔑 APIキー管理 | 新規キー発行フォーム・発行済みキー一覧・失効操作・**名前空間権限の編集** |
| 📚 ナレッジ管理 | FAQ手入力・Q&A CSV一括インポート・ファイルアップロード（Word/Excel/PPT/PDF/画像）・更新履歴（§5.4参照） |
| 📖 使い方 | HTTP POST リクエスト形式・レスポンス形式・エラーコード一覧 |

### 5.2 既存APIキーの名前空間権限を編集する（adminUpdateKey）

`adminUpdateKey()` 関数（`gas_cloud_rag.js`）により、発行済みのAPIキーが参照できるDB（名前空間）をあとから変更できる。従来は権限を削除して再作成する必要があったが、この機能により一行の API 呼び出しで更新できるようになった。キー値を更新する際も既存のnamespace権限設定を保持したまま更新できる。

1. 管理画面 → 「🔑 APIキー管理」サブタブ → 発行済みキー一覧を表示
2. 変更したいキーの行にある「**編集**」ボタンをクリック
3. チェックボックスのモーダルが開く → 許可する名前空間にチェックを入れる（例: `houdini21` を追加）
4. 「保存」ボタンで確定 → `API_KEYS_CONFIG` が即座に更新される

> **注意:** 名前空間を削除すると、そのキーは該当DBにアクセスできなくなる。再付与は同じ手順で可能。

### 5.3 ナレッジ管理タブの使い方

「管理」タブ →「📚 ナレッジ管理」サブタブから、ITリテラシーを問わずブラウザだけでナレッジを追加できる。Notion編集やGASエディタの操作は不要。

| 機能 | 使い方 | 向いている用途 |
|------|--------|----------------|
| ❓ FAQ手入力 | Namespace選択 → Question/Answerを入力 →「登録する」 | 1件だけ素早く追加したい場合 |
| 📋 Q&A CSV一括インポート | Namespace選択 → 1行目に `question,answer` ヘッダーを持つCSVファイルを選択 →「インポート実行」 | すでに手元にあるFAQ一覧・問い合わせ履歴をまとめて登録したい場合 |
| 📎 ファイルアップロード | Namespace選択 → Word/Excel/PowerPoint/PDF/画像/Markdownファイルを選択 →「アップロード実行」 | 既存の資料・マニュアル・スキャン文書をそのまま取り込みたい場合 |
| 🕒 更新履歴 | サブタブを開くと自動表示。日時・種別・Namespace・内容・チャンク数の一覧 | いつ・何を登録したかを確認したい場合 |

登録されたFAQ・アップロード文書は、通常のNotion/Driveドキュメントと同じ`RAG_Index`シートに追加され、すぐに検索・回答生成の対象になる（サーバー側でテキスト抽出・チャンク分割・Gemini埋め込み生成まで自動で行われる）。**Unity・Houdiniクライアント側の変更は不要。** どちらもこのシートを検索しているだけなので、ここでナレッジを追加すればブラウザを操作した直後から両クライアントの回答に反映される。

> **CSVの列名は大文字小文字を区別しない。** `Question,Answer` でも `question,answer` でも動作する。列の順序は問わない（ヘッダー行から自動で列位置を検出する）。
> **画像・PDFの文字起こし精度:** OCR（`ocrLanguage: 'ja'`）を使うため、手書き文字や画質の悪いスキャンでは抽出精度が落ちる場合がある。抽出結果に不備がある場合は元ファイルの画質を上げるか、テキストとして手入力（FAQ手入力）する方が確実。

### 5.4 ファイルアップロードの事前準備（Advanced Drive Service）

ファイルアップロード機能（Word/Excel/PPT/PDF/画像の変換・OCR）には GAS の Advanced Drive Service が必要。**初回のみ**、以下の設定をGASエディタで行う。

1. GASエディタ左側メニューの「サービス」の隣にある「+」ボタンをクリック
2. 一覧から「Drive API」を選択して「追加」
3. 保存（Ctrl+S）

> Markdown（`.md`）・テキスト（`.txt`）ファイルのアップロードはこの設定なしでも動作する。Word/Excel/PPT/PDF/画像の変換にのみ必要。
> 設定を忘れた場合、アップロード実行時に「Advanced Drive Service が必要です」というエラーメッセージが表示される。

---

## 6. クライアント連携（Unity / Houdini）

### 6.1 IRAGClient インターフェース設計

Unity の C# コードでは、クラウドとローカルを切り替えられるよう **インターフェース（interface）** を使っている。インターフェースとは「このメソッド（関数）を必ず実装してね」という約束事のこと。

```
IRAGClient（インターフェース：約束事）
├── QueryAsync(query, history) → RAGResponse   # 質問して回答を受け取る
├── RateAsync(memoryId, rating)                 # 👍/👎 評価を送る
├── HealthCheckAsync()                          # サーバーが生きているか確認
│
├── CloudRAGClient（クラウド用の実装）
│   ├── GAS WebApp へ HTTPS POST（クエリ）
│   └── GAS WebApp へ HTTPS POST（評価: action="rate"）
└── LocalRAGClient（ローカル用の実装）
    ├── localhost:8766 へ HTTP POST
    └── RateAsync は no-op（Local は評価先なし）
```

Settings タブでどちらを使うか選ぶと、内部で `CloudRAGClient` か `LocalRAGClient` かが切り替わる。チャット画面のコードはどちらが選ばれているかを気にせず動く。

**CloudRAGClient の動作:**

- 送るデータ（クエリ）: 質問テキスト・対象 DB・会話履歴・API キー
- 受け取るデータ: AI の回答テキスト・参照ソース・**memoryId**（評価用）
- 送るデータ（評価）: `action="rate"`・memoryId・評価（"up"/"down"）

### 6.2 Unity クライアントのセットアップ

Unity エディタ内からRAGに質問できるチャットウィンドウの導入手順。

#### 6.2.1 ファイルのコピー

リポジトリの `Assets/Editor/RAGChatbot/` フォルダを、Unity プロジェクトの `Assets/Editor/` の中にコピーする。

```
（リポジトリ）
Assets/Editor/RAGChatbot/
  ├── RAGChatbotWindow.cs
  ├── RAGMessage.cs
  ├── IRAGClient.cs
  ├── CloudRAGClient.cs
  ├── LocalRAGClient.cs
  ├── RAGGraphData.cs
  └── RAGGraphView.cs

      ↓ コピー先

（Unity プロジェクト）
Assets/Editor/RAGChatbot/  ← ここに貼り付ける
```

#### 6.2.2 ウィンドウを開く

Unity エディタのメニューバーから **Window → RAG Chatbot** を選択する。

#### 6.2.3 GAS URL と APIキーの設定

1. ウィンドウ内の「Settings」タブを開く
2. 「GAS WebApp URL」欄に §3.8 で取得した WebApp の URL を貼り付ける
3. 「API Key」欄に §3.8.3 で発行したユーザー用APIキーを入力する
4. URL・APIキーは Unity の `EditorPrefs`（エディタ設定の保存領域）に自動保存されるため、次回以降の入力は不要

#### 6.2.4 クラウドモードで使う

1. 「Settings」タブの「モード」を **Cloud** に設定する
2. 「Chat」タブに移動して質問を入力する
3. GAS 経由で Gemini が回答を返してくれる

#### 6.2.5 RAGChatbotWindow の構成

Unity 6 のエディタ拡張として作られた 3 タブ構成のウィンドウ。

| タブ | 内容 |
|------|------|
| **Chat** | AI とのチャット（マルチターン対応）。Cloud モードでは回答バブルの下に 👍/👎 ボタンを表示 |
| **Graph** | ドキュメント間の関係をネットワーク図で表示（IMGUI Painter2D で描画） |
| **Settings** | Cloud / Local の切り替え・接続先 URL・API キー設定 |

#### 6.2.6 HTTP POST リクエスト形式（技術参照）

Cloud モードでは以下の JSON 形式で GAS WebApp に POST する。`apiKey` フィールドは必須。

```json
{
  "query": "質問テキスト",
  "apiKey": "YOUR_32_CHAR_KEY",
  "dbKey": "all",
  "history": []
}
```

**レスポンス（成功時）:**

```json
{
  "status": "ok",
  "answer": "回答テキスト",
  "sources": [{"title": "...", "db": "afuri", "score": 0.91}],
  "allowedNamespaces": ["afuri", "braintq"],
  "memoryId": "mem_a1b2c3d4"
}
```

> `memoryId` は 👍/👎 評価リクエストに使用する（§7 参照）。

**エラー時:**

| status | 意味 |
|--------|------|
| `auth_error` | APIキーが無効または存在しない |
| `forbidden` | 指定したDBへのアクセス権限がない |

> **ローカルモードについて:** モードを「Local」にすると、`localhost:8766` で動作するローカルブリッジサーバー経由でクエリを実行する。詳細は `docs/local-rag.md` を参照。

### 6.3 Houdini クライアントのセットアップ

Houdini の Python パネルとして RAG チャット UI を追加する手順。

#### 6.3.1 ファイルのコピー

リポジトリの `houdini/python_panels/` にある以下の2ファイルを、Houdini のユーザー設定フォルダにコピーする。

```
（コピー元）
houdini/python_panels/
  ├── rag_chatbot.py   ← メインパネル
  └── graph_view.py    ← グラフ表示パネル

（コピー先）
%USERPROFILE%\Documents\houdiniXX.X\python_panels\
                        ↑ XX.X は使用中のバージョン番号（例: houdini20.5）
```

**コピー先フォルダが存在しない場合:** `%USERPROFILE%\Documents\` の中に `houdiniXX.X\python_panels\` フォルダを手動で作成する。

#### 6.3.2 パネルの登録

1. Houdini を起動する
2. メニューバーから **Windows → Python Panel Editor** を開く
3. 左上の「New Panel」ボタンをクリックして新規パネルを作成する
4. パネル名を `RAG Chatbot` に設定する
5. エディタ欄の内容を全削除し、`rag_chatbot.py` の内容をそのまま貼り付ける
6. 「Entry Point」の項目を `onCreateInterface` に設定する
7. 「Accept」または「Apply」ボタンで保存する

> **Entry Point とは:** Houdini がパネルを初期化するときに最初に呼び出す関数名のこと。`onCreateInterface` を指定することで、Houdini がパネルを表示する際に UI の構築処理が自動的に実行される。

#### 6.3.3 GAS URL と APIキーの設定

1. パネルを開いて「Settings」タブに移動する
2. 「GAS WebApp URL」欄に §3.8 で取得した WebApp の URL を入力する
3. 「API Key」欄に §3.8.3 で発行したユーザー用APIキーを入力する
4. 「モード」を `cloud` に設定する
5. 設定は `%USERPROFILE%\.houdini\rag_chatbot_config.json` に自動保存される

#### 6.3.4 HTTP POST リクエスト形式（技術参照）

Cloud モードでは以下の JSON 形式で GAS WebApp に POST する。`apiKey` フィールドは必須。

```json
{
  "query": "質問テキスト",
  "apiKey": "YOUR_32_CHAR_KEY",
  "dbKey": "all",
  "history": []
}
```

**レスポンス（成功時）:**

```json
{
  "status": "ok",
  "answer": "回答テキスト",
  "sources": [{"title": "...", "db": "afuri", "score": 0.91}],
  "allowedNamespaces": ["afuri", "braintq"]
}
```

**エラー時:**

| status | 意味 |
|--------|------|
| `auth_error` | APIキーが無効または存在しない |
| `forbidden` | 指定したDBへのアクセス権限がない |

#### 6.3.5 動作確認

「Chat」タブで質問を入力して「送信」を押し、回答が返ってくれば設定完了。

> **グラフビューについて:** 「Graph」タブを開くと、知識ベースのページ関係グラフが表示される（QGraphicsView 描画、ノードをドラッグ移動可能）。初回描画には30秒〜1分かかる場合がある（§6.4 参照）。

Houdini パネル内部の構成:

- `rag_chatbot.py`: チャット UI（Chat / Settings タブ）。Cloud モードでは RAG 回答バブルの下に 👍/👎 ボタンを表示。評価は `RateWorker`（QThread）でバックグラウンド送信。
- `graph_view.py`: グラフビュー（ノードをマウスでドラッグして配置を変えられる）

### 6.4 グラフビューの使い方

グラフビューは、RAG_Index に登録されたページ同士の「意味的な近さ」を視覚化する機能。似た内容のページが近くに配置されるため、知識ベースの全体構造を一目で把握できる。

- **ノード（丸い点）** = 1 つのドキュメント
- **エッジ（線）** = ドキュメント間の関係（類似度が高いほど近くに配置）

**どこで見られるか:**

| 環境 | 表示方法 |
|------|----------|
| Unity 6 | RAG Chatbot ウィンドウの Graph タブ（IMGUI Painter2D で描画） |
| Houdini 21+ | graph_view.py パネル（QGraphicsView で描画、ノードをドラッグ移動可能） |
| クラウド（ブラウザ） | GAS WebApp の `?action=graph` エンドポイント（D3.js で描画） |

#### 6.4.1 グラフを表示する（ブラウザ）

1. WebApp の URL をブラウザで開く
2. 画面上部の「グラフ」タブをクリックする
3. 「更新」ボタンを押す

「更新」ボタンを押すと、ブラウザから `google.script.run.getGraphData()` が呼ばれ、GAS 側でグラフデータが計算されて返ってくる。

#### 6.4.2 内部でどう動いているか（読み飛ばし可）

```
ブラウザ（更新ボタン）
  ↓ google.script.run.getGraphData()
GAS: buildGraphData_()
  ├─ RAG_Index シートから各ページの代表埋め込みを読み込む
  │    └─ page_id::0 チャンク（ページ先頭部分のベクトル）を使用
  ├─ ページ間のコサイン類似度を計算
  │    └─ スコアが 0.82 以上のペアを上位3件エッジ（線）として追加
  └─ CacheService に結果を30分間保存
ブラウザ
  └─ D3.js の force simulation でノード（点）を自動配置
       └─ 近いノードほど引き合う力が働く
```

**コサイン類似度とは:** 2つのベクトルの「向きの近さ」を -1〜1 の値で表したもの。1.0 に近いほど内容が似ていて、0に近いほど無関係。ここでは 0.82 以上を「関連あり」とみなして線を引いている（不適切なDB間接続を抑制するため旧版の 0.70 から引き上げ）。

#### 6.4.3 グラフの操作方法

| 操作 | 動作 |
|------|------|
| ノード（丸）をクリック | 右側スライドパネルが開き、タイトル全文・DBバッジ（色付き）・関連ノード一覧と類似度スコアを表示 |
| ノードをドラッグ | ノードを手動で移動 |
| マウスホイール | ズームイン / ズームアウト |
| 背景をドラッグ | キャンバス全体をパン（スクロール） |
| 「DB跨ぎ表示」トグル | ON: 異なるDB間の接続を点線で表示 / OFF: 同一DB内のエッジのみ表示 |

---

## 7. 評価機能

### 7.1 仕組み

Cloud RAG で質問すると、回答が **RAG_Memory シート** に自動保存される。回答バブルの下に 👍/👎 ボタンが表示され、評価を送ると以後の検索品質に反映される。

```
質問 → 回答 + memoryId が返る
         ↓
      [👍] [👎] ボタンが回答バブルの下に表示
         ↓
  ボタンを押す → GAS に評価を POST
         ↓
  RAG_Memory シートの G列(rating) / H列(priority) が更新
         ↓
  次回の同じトピック検索で品質が向上
```

### 7.2 評価の動作

| 操作 | RAG_Memory シート | 次回検索への影響 |
|------|-----------------|----------------|
| 👍 を押す | priority = 1.0, rating = "up" | 検索スコアが重み付けされて上位に来やすくなる |
| 👎 を押す | priority = 0.0, rating = "down" | 検索結果から完全除外される |
| 評価しない | priority = 0.5（デフォルト） | 影響なし |

### 7.3 確認方法

評価後に Google Sheets の **RAG_Memory** シートを開き、H列（priority）の値が変わっていることを確認する。

### 7.4 評価の HTTP リクエスト形式（技術参照）

```json
POST <GAS WebApp URL>
{
  "action": "rate",
  "memoryId": "mem_a1b2c3d4",
  "rating": "up",
  "apiKey": "YOUR_32_CHAR_KEY"
}
```

**レスポンス:**
```json
{ "ok": true, "status": "ok" }
```

> **注意:** Unity・Houdini では評価ボタンが自動的にこのリクエストを送信するため、手動で呼ぶ必要はない。GAS の再デプロイを忘れずに行うこと。

Unity・Houdini 共通で動作する。Local RAG では memoryId が存在しないためボタンは表示されない。

---

## 8. セキュリティ設計

### 8.1 API キーの管理方法

API キー（外部サービスにアクセスするためのパスワード）の保管場所は、環境ごとに使い分けている。

| 環境 | 保管場所 | 理由 |
|------|----------|------|
| Unity エディタ | `EditorPrefs`（Unity の設定ファイル） | プロジェクトファイルとは別の場所に保存されるため Git に含まれない |
| Houdini | `rag_config.json`（Houdini の設定フォルダ内） | プロジェクトとは別のフォルダに置くことで Git に含まれない |
| GAS | GAS のスクリプトプロパティ | Google のサーバー側に保存、コードに直書きしない |

### 8.2 .env ファイルを使わないポリシー

`.env` ファイルに API キーを書いてしまうと、`.gitignore` の設定ミス 1 つで GitHub に流出するリスクがある。このプロジェクトでは各ツールのネイティブな設定ストレージ（EditorPrefs・JSON 設定ファイル・GASスクリプトプロパティ）を使うことで、**そもそもキーがファイルとして存在しない** 状態にしている。

### 8.3 NIST SP 800-207 Zero Trust Architecture 準拠機能（2026-06-29 追加）

NIST SP 800-207（Zero Trust Architecture）の原則に基づいた以下のセキュリティ機能を実装している。クラウド RAG・ローカル RAG 共通で適用される設計だが、ここではクラウド RAG に関わる範囲を記す。

#### RAGPolicyEnforcementPoint（`scripts/pep.py`）— テネット3「最小権限」

ロールに応じてアクセスできる名前空間を制限する。

| ロール | アクセス可能な名前空間 |
|--------|----------------------|
| admin | すべて（6つ、houdini21 含む） |
| developer | tool_docs / game_info / research / team_notes / houdini21 |
| user | tool_docs / game_info / research / houdini21 |

houdini21 名前空間は admin/developer/user の全ロールでアクセス許可されている。

#### RAGAuditLogger（`scripts/audit_logger.py`）— テネット7「可能な限り情報収集」

全 RAG クエリを `logs/rag_audit.jsonl` に JSON Lines 形式で記録する。クエリ内容はプライバシー保護のため SHA-256 でハッシュ化して保存する。

```json
{
  "timestamp": "2026-06-29T12:00:00.000Z",
  "session_id": "abc12345",
  "user_role": "developer",
  "action": "search",
  "namespace": "tool_docs",
  "query_hash": "a1b2c3d4e5f6a7b8",
  "result_count": 5,
  "latency_ms": 123,
  "allowed": true
}
```

### 8.4 houdini21 名前空間統合状況

houdini21 専用ドキュメントDBは、クラウド・ローカル双方のコンポーネントに統合済み。

| コンポーネント | 対応 |
|--------------|------|
| GAS WebApp | houdini21 DB を検索対象に追加 |
| LocalRAG（`scripts/rag_service.py`） | `localRAG/houdini21/` をインデックス対象に追加 |
| Unity UI | DB 選択リストに houdini21 を追加 |
| Houdini UI | DB 選択リストに houdini21 を追加 |
| PEP アクセス制御 | admin/developer/user 全ロールにアクセス許可 |

`sync_houdini21_db.py` が Notion の houdini21DB から `localRAG/houdini21/` フォルダに同期する役割を持つ。

---

## 9. トラブルシューティング

### syncNotionToSheets がエラーになる

**Notion 403エラー:**
- インテグレーションが各DBの「接続」に追加されているか確認
- Notionの各DB → 右上「...」→「接続先」→ インテグレーション名を追加

**SHEETS_ID エラー:**
- スクリプトプロパティに `SHEETS_ID` が設定されているか確認
- スプレッドシートのURLからIDを正しくコピーしているか確認

**Embedding エラー（GEMINI_API_KEY）:**
- `testEmbedding()` を実行して確認
- Google AI Studio でキーを再発行してプロパティを更新

### ナレッジ管理タブでファイルアップロードが失敗する

**「Advanced Drive Service が必要です」エラー:**
- GASエディタ →「サービス」の「+」→「Drive API」を追加していない（§5.4参照）

**「ファイルからテキストを抽出できませんでした」エラー:**
- スキャン画質が悪い・手書き文字が多いなどOCR精度の限界。元ファイルの画質を上げるか、FAQ手入力で代替する
- パスワード保護されたPDF/Officeファイルは開けないため、保護を解除してから再アップロードする

**CSVインポートで「ヘッダーに question 列と answer 列が必要です」エラー:**
- CSVの1行目に `question,answer` という列名があるか確認（大文字小文字は区別しないが、列名の誤字がないか確認）

### 回答の精度が低い

- Notionページの `summary` プロパティに内容を追記する（空だと検索精度が落ちる）
- ページの本文が少ない場合は `summary` に詳細を書く
- 固有名詞（BTQ-116、FR-3 等）をページタイトルや summary に明示する

### チャットUIが「考え中...」のまま止まる

- GASエディタで `testRagQuery()` を実行してログを確認
- `searchByEmbedding()` のシート読み込みに失敗している場合は `SHEETS_ID` を確認
- `callGemini()` がエラーの場合は `GEMINI_API_KEY` を確認

### 同期が途中で止まる（タイムアウト）

GASの実行時間制限（6分）を超えた場合。対応策：

1. DBを分けて分割実行（GASで `DB_KEY_MAP` を絞って実行）
2. Notionの `page_size` を減らす
3. 通常は50〜100ページ程度なら問題ない（並列化により大幅に改善済み）

### UIが「応答中」のまま固まる

`window.history` との変数名衝突が原因。`getChatHtml()` 内の JS変数が `history` だと、ブラウザの Navigation History API と競合して `history.slice()` が TypeError を投げ、`isSending=true` のまま UI がロックされる。

対処: JS変数名を `chatHistory` に統一すること（現行コードでは修正済み）。

### グラフビューで「エラー: データが空です」と表示される

Google Sheets の `RAG_Index` シートにデータが入っているか確認する。データが空の場合は §3.7 の手順で `syncNotionToSheets` を実行してインデックスを構築する。

### グラフビューの描画が遅い

初回表示時は `buildGraphData_()` がシート上の全埋め込みベクトルを読み込み、ページ間のコサイン類似度（ベクトルの「方向の近さ」を数値化したもの）を計算するため、30秒〜1分かかる場合がある。計算が終わると GAS の CacheService に30分間キャッシュされるため、2回目以降は数秒で表示される。

---

## 10. 実装フェーズ一覧

すべてのフェーズは完了済み（2026-06-29 時点）。クラウド RAG に関連するフェーズを中心に記載する（ローカル RAG 専用フェーズの詳細は `docs/local-rag.md` を参照）。

| フェーズ | 内容 | 主な成果物 |
|----------|------|-----------|
| **Phase 1** | クラウド RAG 基盤構築 | Notion 7DB・GAS WebApp・Gemini 連携・マルチターン対応 |
| **Phase 3** | Unity C# クライアント | `IRAGClient` インターフェース・`CloudRAGClient`・`LocalRAGClient` |
| **Phase 4** | Unity EditorWindow | `RAGChatbotWindow.cs`（Chat / Settings タブ） |
| **Phase 5** | Unity グラフビュー | `RAGGraphView.cs`（IMGUI Painter2D）・`/graph` エンドポイント |
| **Phase 6** | Houdini Python Panel | `rag_chatbot.py`（PySide6 チャット UI） |
| **Phase 7** | Houdini グラフビュー | `graph_view.py`（QGraphicsView、ノードドラッグ対応） |
| **Phase 8** | GAS グラフ API + D3.js | `buildGraphData_()` 関数・`?action=graph` エンドポイント |
| **Phase 9** | 監査ログ | `scripts/audit_logger.py`（NIST SP 800-207 テネット7） |
| **Phase 10** | PEP アクセス制御 | `scripts/pep.py`（名前空間スコープ・最小権限原則） |
| **Phase 13** | Cloud RAG 品質向上 | `gas_cloud_rag.js` TF-IDF スコア・priority フィルタ・dbKey バリデーション |
| **Phase 14** | 👍/👎 評価機能 | Unity + Houdini UI の評価ボタン・GAS rate アクション |
| **Phase 15** | HyDE 検索強化 | `hydeExpand_()` 関数・加重平均埋め込み・ドメイン別プロンプト |
| **Phase 16** | 閾値フィルタ・重複排除 | コサイン類似度閾値（0.58/0.62）・ページ単位dedup |
| **Phase 17** | 情報抽出度メトリクス | `parseExtractionRate_()` 関数・Unity/Houdini UI 引用バッジ・進捗バー |
| **Phase 18** | adminUpdateKey | `adminUpdateKey()` 管理機能（権限保持のままAPIキー更新） |
| **Phase 19** | houdini21 名前空間 | `sync_houdini21_db.py`・`localRAG/houdini21/`・GAS/LocalRAG/Unity/Houdini UI統合 |

---

## 11. 参考リンク

| リソース | URL |
|----------|-----|
| Notion API リファレンス | https://developers.notion.com/ |
| Gemini API ドキュメント | https://ai.google.dev/gemini-api/docs |
