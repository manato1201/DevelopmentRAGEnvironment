/**
 * Cloud RAG Chatbot — Google Apps Script
 *
 * セットアップ手順:
 * 1. script.google.com で新規プロジェクト作成（またはスプレッドシートから）
 * 2. このファイルの内容をコピーしてエディタに貼り付け
 * 3. 「プロジェクトの設定」→「スクリプトプロパティ」に以下を設定:
 *    - NOTION_API_KEY : Notion Integration Token
 *    - GEMINI_API_KEY : Google AI Studio で発行
 *    - DB_TOOL_DOCS   : 249e442a-47dd-4a8d-95a8-8b856fb91ef6
 *    - DB_GAME_INFO   : f201f73c-45dc-44cb-b8d7-a7be81b3644c
 *    - DB_RESEARCH    : 714d4d4a-6a85-4aa1-845c-32dc3e1a2b1f
 *    - DB_TEAM_NOTES  : f898bf03-8c9f-40e0-9e1b-a28432703d69
 * 4. 「デプロイ」→「新しいデプロイ」→ 種類: ウェブアプリ
 * 5. デプロイ → WebApp URL が自動で埋め込まれる（手動設定不要）
 */

// ─────────────────────────────────────────────
// 定数
// ─────────────────────────────────────────────
const DB_KEYS = {
  tool_docs:  'DB_TOOL_DOCS',
  game_info:  'DB_GAME_INFO',
  research:   'DB_RESEARCH',
  team_notes: 'DB_TEAM_NOTES'
};

// ─────────────────────────────────────────────
// Notion 検索
// ─────────────────────────────────────────────

/**
 * 指定DBをNotionで検索してcontextを返す
 * @param {string} query  検索クエリ
 * @param {string} dbKey  DB識別キー（'tool_docs' 等）
 * @param {number} limit  上位件数（デフォルト5）
 * @returns {string} 上位件のsummaryを連結したcontext
 */
function searchNotion(query, dbKey, limit) {
  limit = limit || 5;
  const props = PropertiesService.getScriptProperties();
  const notionKey = props.getProperty('NOTION_API_KEY');
  const dbId = props.getProperty(DB_KEYS[dbKey]);

  if (!dbId) throw new Error('不明なDBキー: ' + dbKey);

  const url = 'https://api.notion.com/v1/databases/' + dbId + '/query';
  const payload = {
    filter: {
      or: [
        { property: 'title',   title:        { contains: query } },
        { property: 'summary', rich_text:    { contains: query } },
        { property: 'tags',    multi_select: { contains: query } }
      ]
    },
    page_size: limit
  };

  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    headers: {
      'Authorization':   'Bearer ' + notionKey,
      'Notion-Version':  '2022-06-28',
      'Content-Type':    'application/json'
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  if (res.getResponseCode() !== 200) {
    Logger.log('Notion API error: ' + res.getContentText());
    return '（Notion検索エラー: ' + res.getResponseCode() + '）';
  }

  const data = JSON.parse(res.getContentText());
  if (!data.results || data.results.length === 0) {
    return '関連ドキュメントが見つかりませんでした。';
  }

  return data.results.map(function(page, i) {
    const title   = page.properties.title?.title?.[0]?.plain_text ?? '無題';
    const summary = page.properties.summary?.rich_text?.[0]?.plain_text ?? '（要約なし）';
    const srcUrl  = page.properties.source_url?.url ?? '';
    return '[' + (i + 1) + '] ' + title + '\n' + summary + (srcUrl ? '\n参照: ' + srcUrl : '');
  }).join('\n\n');
}

/**
 * 全DBを横断検索して最大 limit 件のcontextを返す
 * @param {string} query
 * @param {number} limit  各DBから取得する件数（デフォルト2）
 * @returns {string}
 */
function searchAllDbs(query, limit) {
  limit = limit || 2;
  const results = [];
  Object.keys(DB_KEYS).forEach(function(key) {
    try {
      const ctx = searchNotion(query, key, limit);
      if (ctx && ctx !== '関連ドキュメントが見つかりませんでした。') {
        results.push('=== ' + key + ' ===\n' + ctx);
      }
    } catch (e) {
      Logger.log('searchAllDbs error (' + key + '): ' + e.message);
    }
  });
  return results.length > 0 ? results.join('\n\n') : '関連ドキュメントが見つかりませんでした。';
}

// ─────────────────────────────────────────────
// Gemini 呼び出し
// ─────────────────────────────────────────────

/**
 * Gemini 2.0 Flash を呼び出す
 * @param {string} prompt
 * @returns {string} 回答テキスト
 */
function callGemini(prompt) {
  const props = PropertiesService.getScriptProperties();
  const apiKey = props.getProperty('GEMINI_API_KEY');
  const url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=' + apiKey;

  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.3 }
    }),
    muteHttpExceptions: true
  });

  if (res.getResponseCode() !== 200) {
    Logger.log('Gemini API error: ' + res.getContentText());
    return '（Gemini APIエラー: ' + res.getResponseCode() + '）';
  }

  const data = JSON.parse(res.getContentText());
  return data.candidates?.[0]?.content?.parts?.[0]?.text ?? '回答を取得できませんでした。';
}

// ─────────────────────────────────────────────
// RAG メイン処理
// ─────────────────────────────────────────────

/**
 * RAGのメイン処理: Notion検索 → context構築 → Gemini呼び出し
 * @param {string} query   ユーザーの質問
 * @param {string} dbKey   対象DB（'all' で全DB横断）
 * @returns {string} 回答テキスト
 */
function ragQuery(query, dbKey) {
  const context = (dbKey === 'all') ? searchAllDbs(query) : searchNotion(query, dbKey);

  const prompt = '以下のドキュメントを参考に、日本語で正確に回答してください。\n' +
    'ドキュメントに情報がない場合はその旨を伝えてください。\n\n' +
    '【参考ドキュメント】\n' + context + '\n\n' +
    '【質問】\n' + query;

  return callGemini(prompt);
}

// ─────────────────────────────────────────────
// WebApp エントリポイント
// ─────────────────────────────────────────────

function doGet() {
  // ScriptApp はサーバーサイドのみ利用可能。URL を文字列置換でHTMLに埋め込む。
  const webAppUrl = ScriptApp.getService().getUrl();
  const html = getChatHtml().replace('__ENDPOINT__', webAppUrl);
  return HtmlService.createHtmlOutput(html)
    .setTitle('RAG チャット')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    const query = body.query;
    const dbKey = body.dbKey || 'tool_docs';
    if (!query) throw new Error('query は必須です');

    const answer = ragQuery(query, dbKey);
    return ContentService
      .createTextOutput(JSON.stringify({ answer: answer, status: 'ok' }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    Logger.log('doPost error: ' + err.message);
    return ContentService
      .createTextOutput(JSON.stringify({ answer: 'エラー: ' + err.message, status: 'error' }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ─────────────────────────────────────────────
// チャット UI
// ─────────────────────────────────────────────

function getChatHtml() {
  return '<!DOCTYPE html>\n' +
'<html lang="ja">\n' +
'<head>\n' +
'<meta charset="UTF-8">\n' +
'<meta name="viewport" content="width=device-width,initial-scale=1">\n' +
'<title>RAG チャット</title>\n' +
'<style>\n' +
'  body { font-family: sans-serif; max-width: 720px; margin: 0 auto; padding: 20px; background: #f5f5f5; }\n' +
'  h1 { font-size: 18px; margin-bottom: 16px; }\n' +
'  .controls { display: flex; gap: 8px; margin-bottom: 12px; }\n' +
'  select, input { flex: 1; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }\n' +
'  button { padding: 8px 20px; background: #0070f3; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }\n' +
'  button:hover { background: #0051cc; }\n' +
'  #chat { background: #fff; border: 1px solid #ddd; border-radius: 8px; height: 420px; overflow-y: auto; padding: 16px; margin-bottom: 12px; }\n' +
'  .msg { margin-bottom: 14px; }\n' +
'  .msg.user .bubble { background: #0070f3; color: #fff; margin-left: auto; }\n' +
'  .msg.bot  .bubble { background: #f0f0f0; color: #333; }\n' +
'  .bubble { display: inline-block; max-width: 85%; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }\n' +
'  .msg.user { text-align: right; }\n' +
'  .thinking { color: #999; font-style: italic; }\n' +
'</style>\n' +
'</head>\n' +
'<body>\n' +
'<h1>🔍 RAG チャット</h1>\n' +
'<div class="controls">\n' +
'  <select id="db">\n' +
'    <option value="all">🌐 全DB横断検索</option>\n' +
'    <option value="tool_docs">🛠️ Tool Docs（Unity / Houdini / DX12）</option>\n' +
'    <option value="game_info">🎮 Game Info（ゲーム情報）</option>\n' +
'    <option value="research">📄 Research（論文・技術記事）</option>\n' +
'    <option value="team_notes">📝 Team Notes（ゼミ・議事録）</option>\n' +
'  </select>\n' +
'</div>\n' +
'<div id="chat"></div>\n' +
'<div class="controls">\n' +
'  <input id="q" type="text" placeholder="質問を入力... (Enter で送信)" onkeydown="if(event.key===\'Enter\')send()">\n' +
'  <button onclick="send()">送信</button>\n' +
'</div>\n' +
'<script>\n' +
'const ENDPOINT = \'__ENDPOINT__\';\n' +
'\n' +
'function addMsg(role, text) {\n' +
'  const chat = document.getElementById(\'chat\');\n' +
'  const div = document.createElement(\'div\');\n' +
'  div.className = \'msg \' + role;\n' +
'  const bubble = document.createElement(\'div\');\n' +
'  bubble.className = \'bubble\' + (role === \'bot\' && text === \'考え中...\' ? \' thinking\' : \'\');\n' +
'  bubble.textContent = text;\n' +
'  div.appendChild(bubble);\n' +
'  chat.appendChild(div);\n' +
'  chat.scrollTop = chat.scrollHeight;\n' +
'  return bubble;\n' +
'}\n' +
'\n' +
'async function send() {\n' +
'  const q = document.getElementById(\'q\').value.trim();\n' +
'  const dbKey = document.getElementById(\'db\').value;\n' +
'  if (!q) return;\n' +
'  document.getElementById(\'q\').value = \'\';\n' +
'  addMsg(\'user\', q);\n' +
'  const botBubble = addMsg(\'bot\', \'考え中...\');\n' +
'\n' +
'  try {\n' +
'    const res = await fetch(ENDPOINT, {\n' +
'      method: \'POST\',\n' +
'      body: JSON.stringify({ query: q, dbKey: dbKey })\n' +
'    });\n' +
'    const data = await res.json();\n' +
'    botBubble.className = \'bubble\';\n' +
'    botBubble.textContent = data.answer;\n' +
'  } catch (err) {\n' +
'    botBubble.className = \'bubble\';\n' +
'    botBubble.textContent = \'通信エラー: \' + err.message;\n' +
'  }\n' +
'}\n' +
'</script>\n' +
'</body>\n' +
'</html>';
}

// ─────────────────────────────────────────────
// デバッグ用ヘルパー（GASエディタから直接実行）
// ─────────────────────────────────────────────

/** GASエディタから実行してNotion検索をテスト */
function testNotionSearch() {
  const result = searchNotion('Houdini VEX', 'tool_docs', 3);
  Logger.log(result);
}

/** GASエディタから実行してGeminiをテスト */
function testGemini() {
  const result = callGemini('「こんにちは」と日本語で挨拶してください。');
  Logger.log(result);
}

/** GASエディタから実行してRAG全体をテスト */
function testRagQuery() {
  const result = ragQuery('HoudiniのVEXでポイントクラウドを操作するには？', 'tool_docs');
  Logger.log(result);
}
