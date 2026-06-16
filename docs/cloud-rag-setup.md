# クラウドRAG環境セットアップガイド

**構成:** Notion + Google Apps Script + Gemini API  
**所要時間:** 約60〜90分  
**更新日:** 2026-06-16

> **Notion DB作成済み（2026-06-16）:** 4つのDBはすでにワークスペースに作成されています。Step 2 はスキップ可能。

## Notion DB — 作成済みDB一覧

| DB名 | database_id | URL |
|------|-------------|-----|
| Tool Docs DB | `249e442a-47dd-4a8d-95a8-8b856fb91ef6` | [開く](https://app.notion.com/p/249e442a47dd4a8d95a88b856fb91ef6) |
| Game Info DB | `f201f73c-45dc-44cb-b8d7-a7be81b3644c` | [開く](https://app.notion.com/p/f201f73c45dc44cbb8d7a7be81b3644c) |
| Research DB | `714d4d4a-6a85-4aa1-845c-32dc3e1a2b1f` | [開く](https://app.notion.com/p/714d4d4a6a854aa1845c32dc3e1a2b1f) |
| Team Notes DB | `f898bf03-8c9f-40e0-9e1b-a28432703d69` | [開く](https://app.notion.com/p/f898bf038c9f40e09e1ba28432703d69) |

**親ページ:** [🗄️ Cloud RAG — ゲーム開発知識ベース](https://app.notion.com/p/38174fde7afd81eda23df9f7a7c19998)

---

## 目次

1. [前提条件](#1-前提条件)
2. [Notion DBの作成](#2-notion-dbの作成)
3. [Gemini APIキーの取得](#3-gemini-apiキーの取得)
4. [GASプロジェクトの作成](#4-gasプロジェクトの作成)
5. [Notion検索関数の実装](#5-notion検索関数の実装)
6. [Gemini呼び出しの実装](#6-gemini呼び出しの実装)
7. [チャットUIの実装](#7-チャットuiの実装)
8. [WebAppとして公開](#8-webappとして公開)
9. [初期データ投入](#9-初期データ投入)
10. [Notion MCPとの連携確認](#10-notion-mcpとの連携確認)
11. [トラブルシューティング](#11-トラブルシューティング)

---

## 1. 前提条件

| 項目 | 要件 |
|------|------|
| Notion | アカウントあり（無料プランで可） |
| Google アカウント | GAS・Gemini API用 |
| Gemini API キー | Google AI Studioで発行（無料枠あり） |
| Notion MCP | claude.aiに接続済み推奨 |

---

## 2. Notion DBの作成

用途別に**4つのDBを独立して作成**する。DB間を分離することで、GASの検索時に情報が混合しない。

### 2.1 DB一覧

| DB名 | 内容 | 主な追加方法 |
|------|------|-------------|
| `Tool Docs DB` | Unity・Houdini・DX12・環境設定 | 手動 / Pythonスクリプト |
| `Game Info DB` | ゲーム仕様・共有ゲーム情報 | 手動 |
| `Research DB` | 論文・技術記事（手動精査済み） | 手動 / Pythonスクリプト |
| `Team Notes DB` | ゼミ資料・議事録・方針 | 手動 |

### 2.2 共通スキーマ（全DBで統一）

各DBに以下のプロパティを作成する：

| プロパティ名 | 種類 | 説明 |
|-------------|------|------|
| `title` | タイトル | ページタイトル（デフォルト） |
| `source_url` | URL | 元記事・ドキュメントのURL |
| `tags` | マルチセレクト | `Unity` `Houdini` `RAG` 等 |
| `summary` | テキスト | AI生成の100字要約 ← **検索精度の核** |
| `collected_at` | 日付 | 追加日 |
| `category` | セレクト | どのDBか（`tool_docs` 等） |

### 2.3 database_idの確認方法

各DBのURLから `database_id` を取得する（GASで使用）：

```
https://www.notion.so/{workspace}/{database_id}?v=...
                                  ^^^^^^^^^^^^^^^^^^^
                                  ここが database_id（32文字）
```

4つのDBそれぞれのIDを控えておく。

---

## 3. Gemini APIキーの取得

1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. 「Get API key」→「Create API key」
3. 発行されたキーをメモ（後でGASのスクリプトプロパティに設定）

> **注意:** APIキーをコード内に直書きしない。GASのスクリプトプロパティを使う。

---

## 4. GASプロジェクトの作成

### 4.1 スプレッドシートから作成

1. Google スプレッドシートを新規作成
2. 「拡張機能」→「Apps Script」を開く
3. プロジェクト名を `cloud-rag-chatbot` に変更

### 4.2 スクリプトプロパティの設定

「プロジェクトの設定」→「スクリプトプロパティ」に以下を追加：

| プロパティ名 | 値 |
|-------------|-----|
| `NOTION_API_KEY` | Notionのインテグレーションキー |
| `GEMINI_API_KEY` | Google AI Studioで発行したキー |
| `DB_TOOL_DOCS` | `249e442a-47dd-4a8d-95a8-8b856fb91ef6` |
| `DB_GAME_INFO` | `f201f73c-45dc-44cb-b8d7-a7be81b3644c` |
| `DB_RESEARCH` | `714d4d4a-6a85-4aa1-845c-32dc3e1a2b1f` |
| `DB_TEAM_NOTES` | `f898bf03-8c9f-40e0-9e1b-a28432703d69` |

> **Notionインテグレーションキーの発行:**
> [notion.so/my-integrations](https://www.notion.so/my-integrations) → 「新しいインテグレーション」→ 各DBで「接続先」に追加

---

## 5. Notion検索関数の実装

GASエディタに以下を実装する：

```javascript
// 定数: DBのキーマップ
const DB_KEYS = {
  tool_docs:  'DB_TOOL_DOCS',
  game_info:  'DB_GAME_INFO',
  research:   'DB_RESEARCH',
  team_notes: 'DB_TEAM_NOTES'
};

/**
 * 指定DBをNotionで検索してcontextを返す
 * @param {string} query  - 検索クエリ
 * @param {string} dbKey  - DB識別キー（'tool_docs' 等）
 * @returns {string} 上位件のsummaryを連結したcontext
 */
function searchNotion(query, dbKey) {
  const props = PropertiesService.getScriptProperties();
  const notionKey = props.getProperty('NOTION_API_KEY');
  const dbId = props.getProperty(DB_KEYS[dbKey]);

  if (!dbId) throw new Error(`不明なDBキー: ${dbKey}`);

  const url = `https://api.notion.com/v1/databases/${dbId}/query`;
  const payload = {
    filter: {
      or: [
        { property: 'title',   title:       { contains: query } },
        { property: 'summary', rich_text:   { contains: query } },
        { property: 'tags',    multi_select: { contains: query } }
      ]
    },
    page_size: 5  // 上位5件
  };

  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    headers: {
      'Authorization': `Bearer ${notionKey}`,
      'Notion-Version': '2022-06-28',
      'Content-Type': 'application/json'
    },
    payload: JSON.stringify(payload)
  });

  const data = JSON.parse(res.getContentText());
  if (!data.results || data.results.length === 0) return '関連ドキュメントが見つかりませんでした。';

  // summaryを連結してcontextを構築
  return data.results.map((page, i) => {
    const title   = page.properties.title?.title?.[0]?.plain_text ?? '無題';
    const summary = page.properties.summary?.rich_text?.[0]?.plain_text ?? '（要約なし）';
    const url     = page.properties.source_url?.url ?? '';
    return `[${i + 1}] ${title}\n${summary}${url ? `\n参照: ${url}` : ''}`;
  }).join('\n\n');
}
```

---

## 6. Gemini呼び出しの実装

```javascript
/**
 * Gemini API を呼び出す
 * @param {string} prompt - 送信するプロンプト
 * @returns {string} Geminiの回答テキスト
 */
function callGemini(prompt) {
  const props = PropertiesService.getScriptProperties();
  const apiKey = props.getProperty('GEMINI_API_KEY');
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`;

  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.3 }  // RAG用途は低めに
    })
  });

  const data = JSON.parse(res.getContentText());
  return data.candidates?.[0]?.content?.parts?.[0]?.text ?? '回答を取得できませんでした。';
}

/**
 * RAGのメイン処理: Notion検索 → context構築 → Gemini呼び出し
 * @param {string} query  - ユーザーの質問
 * @param {string} dbKey  - 対象DB
 * @returns {string} 回答テキスト
 */
function ragQuery(query, dbKey) {
  const context = searchNotion(query, dbKey);

  const prompt = `以下のドキュメントを参考に、日本語で正確に回答してください。
ドキュメントに情報がない場合はその旨を伝えてください。

【参考ドキュメント】
${context}

【質問】
${query}`;

  return callGemini(prompt);
}
```

---

## 7. チャットUIの実装

```javascript
/**
 * WebApp のエントリポイント (GET): チャットUIを返す
 */
function doGet() {
  return HtmlService.createHtmlOutput(getChatHtml())
    .setTitle('RAG チャット')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * WebApp のエントリポイント (POST): RAGクエリを処理して回答を返す
 */
function doPost(e) {
  try {
    const { query, dbKey } = JSON.parse(e.postData.contents);
    if (!query || !dbKey) throw new Error('query と dbKey は必須です');

    const answer = ragQuery(query, dbKey);
    return ContentService
      .createTextOutput(JSON.stringify({ answer, status: 'ok' }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ answer: `エラー: ${err.message}`, status: 'error' }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * チャットUI の HTML を返す
 */
function getChatHtml() {
  return `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAG チャット</title>
<style>
  body { font-family: sans-serif; max-width: 720px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
  h1 { font-size: 18px; margin-bottom: 16px; }
  .controls { display: flex; gap: 8px; margin-bottom: 12px; }
  select, input { flex: 1; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
  button { padding: 8px 20px; background: #0070f3; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
  button:hover { background: #0051cc; }
  #chat { background: #fff; border: 1px solid #ddd; border-radius: 8px; height: 420px; overflow-y: auto; padding: 16px; margin-bottom: 12px; }
  .msg { margin-bottom: 14px; }
  .msg.user .bubble { background: #0070f3; color: #fff; margin-left: auto; }
  .msg.bot  .bubble { background: #f0f0f0; color: #333; }
  .bubble { display: inline-block; max-width: 85%; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
  .msg.user { text-align: right; }
</style>
</head>
<body>
<h1>RAG チャット</h1>
<div class="controls">
  <select id="db">
    <option value="tool_docs">Tool Docs（Unity / Houdini / DX12）</option>
    <option value="game_info">Game Info（ゲーム情報）</option>
    <option value="research">Research（論文・技術記事）</option>
    <option value="team_notes">Team Notes（ゼミ・議事録）</option>
  </select>
</div>
<div id="chat"></div>
<div class="controls">
  <input id="q" type="text" placeholder="質問を入力..." onkeydown="if(event.key==='Enter')send()">
  <button onclick="send()">送信</button>
</div>
<script>
const ENDPOINT = ''; // デプロイ後にWebAppのURLを貼る

function addMsg(role, text) {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = '<div class="bubble">' + text.replace(/</g,'&lt;') + '</div>';
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

async function send() {
  const q = document.getElementById('q').value.trim();
  const dbKey = document.getElementById('db').value;
  if (!q) return;
  document.getElementById('q').value = '';
  addMsg('user', q);
  addMsg('bot', '考え中...');

  const res = await fetch(ENDPOINT, {
    method: 'POST',
    body: JSON.stringify({ query: q, dbKey })
  });
  const data = await res.json();
  document.querySelectorAll('.msg.bot:last-child .bubble')[0].textContent = data.answer;
}
</script>
</body>
</html>`;
}
```

---

## 8. WebAppとして公開

1. GASエディタ右上「デプロイ」→「新しいデプロイ」
2. 種類: **ウェブアプリ**
3. 設定：
   - 説明: `cloud-rag-chatbot v1`
   - 次のユーザーとして実行: **自分**
   - アクセスできるユーザー: **自分のみ**（外部公開する場合は変更）
4. デプロイ後に表示されるWebApp URLをコピー
5. `getChatHtml()` 内の `ENDPOINT = ''` にURLを貼り付けて再デプロイ

---

## 9. 初期データ投入

### 9.1 Notion Web Clipper（手動・日常用）

1. Chromeに「Notion Web Clipper」拡張を追加
2. 保存したいページで拡張を起動 → 対象DBを選択して保存
3. 保存後、`summary` プロパティにGeminiで生成した要約を追記する

**summaryの生成プロンプト例:**
```
以下のドキュメントを100字以内で要約してください。
専門用語はそのまま残してください。

[ページ本文をペースト]
```

### 9.2 Pythonスクリプト（まとめて追加用）

`scripts/notion_bulk_add.py` を使うとURLリストからまとめてNotionに追加できる（別途実装）。

---

## 10. Notion MCPとの連携確認

Notion MCPがclaude.aiに接続済みであれば、Claude Codeから直接Notionを検索できる。

**Claude Codeでの使用例:**

```
Notion の Tool Docs DB で "HoudiniのVEX wrangle" を検索して、
基本的な使い方をまとめてください。
```

ローカルRAG（mcp-rag-server）との併用：

```
ローカルRAGの tutorials namespace と
NotionのTool Docs DBを両方参照して、
Houdiniのボロノイ分割について教えてください。
```

---

## 11. トラブルシューティング

### Notion APIが403を返す

- インテグレーションが各DBの「接続先」に追加されているか確認
- Notionの「設定」→「インテグレーション」→ 対象DBで「接続を追加」

### GASでエラーが出る

```javascript
// GASエディタのログ確認
Logger.log(searchNotion('Unity', 'tool_docs'));
```

「実行」→「実行ログ」でエラー内容を確認する。

### Geminiの回答が的外れ

- `summary` プロパティが空のページが多い → summaryを追記する
- クエリをより具体的にする（「Unity」より「Unity HDRP シェーダー」）

### WebAppにアクセスできない

- デプロイ時のアクセス権設定を確認
- スクリプトプロパティに全キーが設定されているか確認
- GASエディタで `doPost` を直接実行してエラーを確認
