# クラウドRAG環境セットアップガイド

**構成:** Notion + Google Apps Script + Gemini gemini-embedding-001 + Google Sheets  
**所要時間:** 約60〜90分  
**更新日:** 2026-06-24

> **Notion DB作成済み（2026-06-22）:** 7つのDBはすでにワークスペースに作成されています。Step 2 はスキップ可能。

## アーキテクチャ概要

```
Notion (7DB)
    ↓ GAS: syncNotionToSheets()
Google Sheets (RAG_Index)
  [page_id | db | title | text | last_edited | embedding(768次元)]
    ↓ クエリ時: GAS がクエリをベクトル化 → コサイン類似度
Gemini gemini-embedding-001  ←→  gemini-2.5-flash（回答生成）
    ↓
チャット WebApp
```

> **注:** Gemini Corpus API（Semantic Retrieval）・`text-embedding-004` は日本リージョン非対応のため、  
> `gemini-embedding-001`（768次元）+ Google Sheets によるベクトル検索を採用しています。

---

## Notion DB — 作成済みDB一覧

| DB名 | database_id | URL |
|------|-------------|-----|
| Tool Docs DB | `249e442a-47dd-4a8d-95a8-8b856fb91ef6` | [開く](https://app.notion.com/p/249e442a47dd4a8d95a88b856fb91ef6) |
| Game Info DB | `f201f73c-45dc-44cb-b8d7-a7be81b3644c` | [開く](https://app.notion.com/p/f201f73c45dc44cbb8d7a7be81b3644c) |
| Research DB | `714d4d4a-6a85-4aa1-845c-32dc3e1a2b1f` | [開く](https://app.notion.com/p/714d4d4a6a854aa1845c32dc3e1a2b1f) |
| Team Notes DB | `f898bf03-8c9f-40e0-9e1b-a28432703d69` | [開く](https://app.notion.com/p/f898bf038c9f40e09e1ba28432703d69) |
| AFURI DB | `a74822790ec34768bdef0917abae3e6f` | [開く](https://app.notion.com/p/a74822790ec34768bdef0917abae3e6f) |
| BrainTQ DB | `847b7db0f29f4190bee9f7ae7dd15514` | [開く](https://app.notion.com/p/847b7db0f29f4190bee9f7ae7dd15514) |
| Fourteen DB | `475cf278492a45ac90cbe4b8f11df1f5` | [開く](https://app.notion.com/p/475cf278492a45ac90cbe4b8f11df1f5) |

**親ページ:** [🗄️ Cloud RAG — ゲーム開発知識ベース](https://app.notion.com/p/38174fde7afd81eda23df9f7a7c19998)

---

## 目次

1. [前提条件](#1-前提条件)
2. [Notion DBの作成](#2-notion-dbの作成)（作成済みの場合はスキップ）
3. [Gemini APIキーの取得](#3-gemini-apiキーの取得)
4. [GASプロジェクトの作成・コード貼り付け](#4-gasプロジェクトの作成コード貼り付け)
5. [スクリプトプロパティの設定](#5-スクリプトプロパティの設定)
6. [Google Sheets の準備](#6-google-sheets-の準備)
7. [Notion→Sheetsの初回同期](#7-notionsheetsの初回同期)
8. [WebAppとして公開](#8-webappとして公開)
9. [Notionにページを追加したあとの更新方法](#9-notionにページを追加したあとの更新方法)
10. [トラブルシューティング](#10-トラブルシューティング)

---

## 1. 前提条件

| 項目 | 要件 |
|------|------|
| Notion | アカウントあり（無料プランで可） |
| Google アカウント | GAS・Gemini API用 |
| Gemini API キー | Google AI Studio で発行（無料枠あり） |
| Notion Integration | `notion_bulk_add.py` で使用中のものを流用可 |

---

## 2. Notion DBの作成

> **作成済みの場合はこのステップをスキップ。**

### 2.1 共通スキーマ（全DBで統一）

| プロパティ名 | 種類 | 説明 |
|-------------|------|------|
| `title` | タイトル | ページタイトル（デフォルト） |
| `source_url` | URL | 元記事・ドキュメントのURL |
| `tags` | マルチセレクト | `Unity` `Houdini` 等 |
| `summary` | テキスト | 内容の要約（100〜200字） ← **検索精度に直結** |
| `collected_at` | 日付 | 追加日 |

### 2.2 Notionインテグレーションの接続

[notion.so/my-integrations](https://www.notion.so/my-integrations) で発行した Integration Token を、各DBの「設定」→「接続」→「インテグレーションを追加」で紐付ける。

---

## 3. Gemini APIキーの取得

1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. 「Get API key」→「Create API key」
3. 発行されたキーをメモ（後でGASのスクリプトプロパティに設定）

> **注意:** APIキーをコード内に直書きしない。GASのスクリプトプロパティを使う。

---

## 4. GASプロジェクトの作成・コード貼り付け

1. [script.google.com](https://script.google.com) で「新しいプロジェクト」を作成
2. プロジェクト名を `cloud-rag-chatbot` に変更
3. エディタの内容を全削除し、`scripts/gas_cloud_rag.js` の内容をそのまま貼り付け
4. Ctrl+S で保存

---

## 5. スクリプトプロパティの設定

「プロジェクトの設定」→「スクリプトプロパティ」→「プロパティを追加」

| プロパティ名 | 値 |
|-------------|-----|
| `NOTION_API_KEY` | Notionのインテグレーションキー |
| `GEMINI_API_KEY` | Google AI Studio で発行したキー |
| `SHEETS_ID` | **次のステップで取得するID**（★必須・新規） |
| `DB_TOOL_DOCS` | `249e442a-47dd-4a8d-95a8-8b856fb91ef6` |
| `DB_GAME_INFO` | `f201f73c-45dc-44cb-b8d7-a7be81b3644c` |
| `DB_RESEARCH` | `714d4d4a-6a85-4aa1-845c-32dc3e1a2b1f` |
| `DB_TEAM_NOTES` | `f898bf03-8c9f-40e0-9e1b-a28432703d69` |
| `DB_AFURI` | `a74822790ec34768bdef0917abae3e6f` |
| `DB_BRAINTQ` | `847b7db0f29f4190bee9f7ae7dd15514` |
| `DB_FOURTEEN` | `475cf278492a45ac90cbe4b8f11df1f5` |

---

## 6. Google Sheets の準備

ベクトルインデックスを保存するスプレッドシートを用意する。

1. [Google スプレッドシート](https://sheets.google.com) で新規ファイルを作成（名前は何でも可）
2. URLから `SHEETS_ID` を取得：

```
https://docs.google.com/spreadsheets/d/XXXXXXXXXXXXXXXXXXXXXXXXXX/edit
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^
                                       これが SHEETS_ID
```

3. コピーした ID を Step 5 の `SHEETS_ID` プロパティに貼り付ける

> シートの中身は GAS が自動で作成するので、空のままで OK。

---

## 7. Notion→Sheetsの初回同期

GASエディタで初回インデックスを構築する。

### 7.1 Embedding API の疎通確認

1. GASエディタで関数リストから `testEmbedding` を選択
2. 「実行」→「実行ログ」で以下のような出力を確認：

```
次元数: 768  先頭3値: 0.0123,0.0456,-0.0789
```

エラーが出る場合は `GEMINI_API_KEY` のスクリプトプロパティを確認。

### 7.2 全DBを同期

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

### 7.3 検索テスト

```
関数: testSearch
```

実行ログに検索結果が表示されれば完成。

---

## 8. WebAppとして公開

1. GASエディタ右上「デプロイ」→「新しいデプロイ」
2. 種類: **ウェブアプリ**
3. 設定：
   - 説明: `cloud-rag v2 (embedding)`
   - 次のユーザーとして実行: **自分**
   - アクセスできるユーザー: **自分のみ**（チームで使う場合は次項を参照）
4. 「デプロイ」→ WebApp URL が表示される
5. URLをブラウザで開いてチャット UI が表示されれば完成

### 8.1 マルチユーザー公開（チーム共有）

チームメンバーにも使わせたい場合は、デプロイ設定のみ変更する。コード変更は不要。

1. 「デプロイ」→「デプロイを管理」→ 鉛筆アイコン（編集）
2. 設定を変更：

| 項目 | 設定値 |
|------|-------|
| 次のユーザーとして実行 | **自分**（そのまま） |
| アクセスできるユーザー | **全員** または **全員（Googleアカウント不要）** |

3. バージョン: **新バージョン** を選択 → デプロイ

> **なぜ「実行: 自分」のままでよいか:** 他ユーザーのリクエストもオーナーのアカウントで処理される。Notion/Gemini APIキーは Script Properties に格納されており、他ユーザーには見えない。

---

## 9. Notionにページを追加したあとの更新方法

Notion でページを追加・編集したあとは、GAS で差分同期を実行する：

1. GASエディタを開く
2. 関数 `syncNotionToSheets` を選択して実行
3. ログで「更新: N件」と表示されれば反映完了

> **差分同期:** `last_edited_time` を比較するため、変更されていないページはスキップされ高速に動作する。

### 9.1 並列同期の仕組み（v2実装）

`syncNotionToSheets` は `UrlFetchApp.fetchAll()` を使って並列化されている：

| フェーズ | 処理 | 旧（直列） | 新（並列） |
|---------|------|-----------|-----------|
| Phase 1 | 全DB ページ一覧取得 | 7回×直列 | `fetchAll` 1回（7並列） |
| Phase 2 | 更新ページの本文取得 | N回×直列+sleep | `fetchAll` 1〜2回（N並列） |
| Phase 3 | Embedding生成 | 1チャンクずつ+sleep | `fetchAll` 10件バッチ |

20ページ更新・60チャンクの場合の目安: 旧 ~22秒 → 新 ~2秒

---

## 10. トラブルシューティング

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

---

## 11. LocalRAG → Notion 移行ツール

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
