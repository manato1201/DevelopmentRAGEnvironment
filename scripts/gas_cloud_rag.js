/**
 * Cloud RAG Chatbot — Google Apps Script
 * Gemini text-embedding-004 + Google Sheets ベクトルストア版
 *
 * ── スクリプトプロパティ ─────────────────────────────────────────────
 *   NOTION_API_KEY, GEMINI_API_KEY (既存)
 *   DB_TOOL_DOCS, DB_GAME_INFO, DB_RESEARCH, DB_TEAM_NOTES (既存)
 *   DB_AFURI, DB_BRAINTQ, DB_FOURTEEN (既存)
 *   SHEETS_ID  ← 新規: ベクトル保存用スプレッドシートID
 * ────────────────────────────────────────────────────────────────────
 */

var DB_KEY_MAP = {
  tool_docs:  'DB_TOOL_DOCS',
  game_info:  'DB_GAME_INFO',
  research:   'DB_RESEARCH',
  team_notes: 'DB_TEAM_NOTES',
  afuri:      'DB_AFURI',
  braintq:    'DB_BRAINTQ',
  fourteen:   'DB_FOURTEEN',
};

var SHEET_NAME    = 'RAG_Index';
var IDX_CACHE_KEY = 'rag_idx_v2'; // バージョンを変えるとキャッシュリセット
var CACHE_TTL     = 21600;        // 6時間
var CACHE_CHUNK   = 90000;        // 90KB/chunk（上限100KB）

// ─────────────────────────────────────────────
// Google Sheets ヘルパー
// ─────────────────────────────────────────────

function getSheet_() {
  var props    = PropertiesService.getScriptProperties();
  var sheetsId = props.getProperty('SHEETS_ID');
  if (!sheetsId) throw new Error('SHEETS_ID がスクリプトプロパティに未設定です');
  var ss    = SpreadsheetApp.openById(sheetsId);
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(['page_id', 'db', 'title', 'text', 'last_edited', 'embedding']);
    sheet.getRange(1, 1, 1, 6).setFontWeight('bold');
  }
  return sheet;
}

// ─────────────────────────────────────────────
// Notion ヘルパー
// ─────────────────────────────────────────────

function getNotionHeaders_() {
  var props = PropertiesService.getScriptProperties();
  return {
    'Authorization':  'Bearer ' + props.getProperty('NOTION_API_KEY'),
    'Notion-Version': '2022-06-28',
    'Content-Type':   'application/json',
  };
}

function fetchNotionPages_(dbId) {
  var pages = [], payload = { page_size: 100 };
  var url   = 'https://api.notion.com/v1/databases/' + dbId + '/query';
  while (true) {
    var res = UrlFetchApp.fetch(url, {
      method: 'post', headers: getNotionHeaders_(),
      payload: JSON.stringify(payload), muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) {
      Logger.log('Notion error: ' + res.getContentText().substring(0, 200)); break;
    }
    var data = JSON.parse(res.getContentText());
    pages = pages.concat(data.results || []);
    if (!data.has_more) break;
    payload.start_cursor = data.next_cursor;
    Utilities.sleep(300);
  }
  return pages;
}

function extractPageData_(page, dbKey) {
  var props   = page.properties || {};
  var title   = ((props.title   || {}).title      || []).map(function(t) { return t.plain_text || ''; }).join('');
  if (!title) return null;
  var summary = ((props.summary || {}).rich_text  || []).map(function(t) { return t.plain_text || ''; }).join('');
  var tags    = ((props.tags    || {}).multi_select || []).map(function(t) { return t.name || ''; });
  var url_    = (props.source_url || {}).url || '';
  var parts   = ['# ' + title];
  if (summary)     parts.push(summary);
  if (tags.length) parts.push('タグ: ' + tags.join(', '));
  if (url_)        parts.push('参照: ' + url_);
  return {
    page_id:     page.id,
    db:          dbKey,
    title:       title,
    meta_text:   parts.join('\n'), // メタデータのみ（本文は fetchPageBody_ で別取得）
    last_edited: page.last_edited_time || '',
  };
}

/**
 * Notion ページの本文ブロックをテキストに変換（最大3000文字）
 */
function fetchPageBody_(pageId) {
  var TEXT_TYPES = {
    paragraph: 1, heading_1: 1, heading_2: 1, heading_3: 1,
    bulleted_list_item: 1, numbered_list_item: 1, quote: 1, callout: 1, toggle: 1,
    code: 1,  // コードブロック（GameType enum等）も取得
  };
  var lines  = [];
  var cursor = null;

  // ページネーションで全ブロックを取得（最大200ブロック）
  for (var page = 0; page < 2; page++) {
    var url = 'https://api.notion.com/v1/blocks/' + pageId + '/children?page_size=100';
    if (cursor) url += '&start_cursor=' + cursor;
    var res = UrlFetchApp.fetch(url, { headers: getNotionHeaders_(), muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) break;
    var data   = JSON.parse(res.getContentText());
    var blocks = data.results || [];
    blocks.forEach(function(b) {
      if (!TEXT_TYPES[b.type]) return;
      var rt   = (b[b.type] || {}).rich_text || [];
      var line = rt.map(function(t) { return t.plain_text || ''; }).join('');
      if (line.trim()) lines.push(line);
    });
    if (!data.has_more) break;
    cursor = data.next_cursor;
    Utilities.sleep(200);
  }

  return lines.join('\n').substring(0, 8000); // LocalRAGの長文MDに合わせて拡張
}

/**
 * テキストをオーバーラップ付きで均等チャンク分割
 * @param {string} text
 * @param {number} size    チャンクサイズ（文字数）
 * @param {number} overlap 前チャンクとの重複文字数
 */
function chunkText_(text, size, overlap) {
  size    = size    || 350;
  overlap = overlap || 70;
  if (!text || text.length <= size) return text ? [text] : [];
  var chunks = [];
  var start  = 0;
  while (start < text.length) {
    chunks.push(text.substring(start, start + size));
    if (start + size >= text.length) break;
    start += size - overlap;
  }
  return chunks;
}

// ─────────────────────────────────────────────
// Gemini Embedding API
// ─────────────────────────────────────────────

// 日本リージョンで利用可能なモデル: gemini-embedding-001
// outputDimensionality: 768 に削減（デフォルト3072をSheets容量節約のため縮小）
function embed_(text, taskType) {
  var props  = PropertiesService.getScriptProperties();
  var apiKey = props.getProperty('GEMINI_API_KEY');
  var url    = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=' + apiKey;
  var payload = {
    model:                'models/gemini-embedding-001',
    content:              { parts: [{ text: text.substring(0, 2000) }] },
    outputDimensionality: 768,
  };
  if (taskType) payload.taskType = taskType;
  var res = UrlFetchApp.fetch(url, {
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    Logger.log('Embed error: ' + res.getContentText().substring(0, 200)); return null;
  }
  return JSON.parse(res.getContentText()).embedding.values;
}

function embedDoc_(text)   { return embed_(text, 'RETRIEVAL_DOCUMENT'); }
function embedQuery_(text) { return embed_(text, 'RETRIEVAL_QUERY');    }

// ─────────────────────────────────────────────
// 同期処理（GASエディタから手動実行）
// ─────────────────────────────────────────────

function syncNotionToSheets() {
  var props    = PropertiesService.getScriptProperties();
  var sheet    = getSheet_();
  var data     = sheet.getDataRange().getValues();
  var nHeaders = getNotionHeaders_();
  var embedUrl = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key='
                 + props.getProperty('GEMINI_API_KEY');

  // 既存チャンクマップ (baseId → { rowIndices, lastEdited })
  var existingMap = {};
  for (var i = 1; i < data.length; i++) {
    var baseId = String(data[i][0]).split('::')[0];
    if (!existingMap[baseId]) existingMap[baseId] = { rowIndices: [], lastEdited: data[i][4] };
    existingMap[baseId].rowIndices.push(i + 1);
  }

  // ─── Phase 1: 全DBのページ一覧を並列取得（fetchAll）─────────────────
  var reqKeys  = [];
  var listReqs = [];
  Object.keys(DB_KEY_MAP).forEach(function(key) {
    var dbId = props.getProperty(DB_KEY_MAP[key]);
    if (!dbId) { Logger.log('DB未設定: ' + key); return; }
    reqKeys.push(key);
    listReqs.push({
      url: 'https://api.notion.com/v1/databases/' + dbId + '/query',
      method: 'post', headers: nHeaders, contentType: 'application/json',
      payload: JSON.stringify({ page_size: 100 }), muteHttpExceptions: true,
    });
  });
  Logger.log('Phase1: ' + reqKeys.length + 'DB を並列取得...');
  var listResps = UrlFetchApp.fetchAll(listReqs);

  // ─── Phase 2: 更新対象ページを特定 & 本文を並列取得 ─────────────────
  var rowsToDelete = [];
  var updateList   = []; // [{ pd }]
  var totalSkip    = 0;

  listResps.forEach(function(res, i) {
    var key = reqKeys[i];
    if (res.getResponseCode() !== 200) {
      Logger.log('[' + key + '] リスト取得エラー: ' + res.getResponseCode()); return;
    }
    var pages = JSON.parse(res.getContentText()).results || [];
    Logger.log('[' + key + '] ' + pages.length + 'ページ');
    pages.forEach(function(page) {
      var pd = extractPageData_(page, key);
      if (!pd) return;
      var ex = existingMap[pd.page_id];
      if (ex && ex.lastEdited === pd.last_edited) { totalSkip++; return; }
      if (ex) rowsToDelete = rowsToDelete.concat(ex.rowIndices);
      updateList.push({ pd: pd });
    });
  });

  Logger.log('更新対象: ' + updateList.length + 'ページ  スキップ: ' + totalSkip);
  if (updateList.length === 0) {
    Logger.log('変更なし');
    invalidateIndexCache_();
    return;
  }

  // 本文の1ページ目を並列取得
  var bodyReqs = updateList.map(function(item) {
    return {
      url: 'https://api.notion.com/v1/blocks/' + item.pd.page_id + '/children?page_size=100',
      method: 'get', headers: nHeaders, muteHttpExceptions: true,
    };
  });
  Logger.log('Phase2: ' + updateList.length + 'ページの本文を並列取得...');
  var bodyResps = UrlFetchApp.fetchAll(bodyReqs);

  var TEXT_TYPES = {
    paragraph: 1, heading_1: 1, heading_2: 1, heading_3: 1,
    bulleted_list_item: 1, numbered_list_item: 1, quote: 1, callout: 1, toggle: 1, code: 1,
  };

  function extractLines_(blocks) {
    return blocks.reduce(function(acc, b) {
      if (!TEXT_TYPES[b.type]) return acc;
      var line = ((b[b.type] || {}).rich_text || []).map(function(t) { return t.plain_text || ''; }).join('');
      if (line.trim()) acc.push(line);
      return acc;
    }, []);
  }

  // 1ページ目を解析。has_more があるページは cursor を保持
  var bodies = bodyResps.map(function(res, i) {
    if (res.getResponseCode() !== 200) return '';
    var d     = JSON.parse(res.getContentText());
    var lines = extractLines_(d.results || []);
    if (!d.has_more) return lines.join('\n').substring(0, 8000);
    updateList[i].p2cursor = d.next_cursor;
    updateList[i].p1lines  = lines;
    return null; // 2ページ目待ち
  });

  // has_more があったページの2ページ目を並列取得
  var p2idx  = [], p2reqs = [];
  updateList.forEach(function(item, i) {
    if (!item.p2cursor) return;
    p2idx.push(i);
    p2reqs.push({
      url: 'https://api.notion.com/v1/blocks/' + item.pd.page_id + '/children?page_size=100&start_cursor=' + item.p2cursor,
      method: 'get', headers: nHeaders, muteHttpExceptions: true,
    });
  });
  if (p2reqs.length > 0) {
    Logger.log('本文2ページ目を並列取得: ' + p2reqs.length + 'ページ');
    UrlFetchApp.fetchAll(p2reqs).forEach(function(res, j) {
      var idx   = p2idx[j];
      var extra = (res.getResponseCode() === 200)
        ? extractLines_(JSON.parse(res.getContentText()).results || []) : [];
      bodies[idx] = updateList[idx].p1lines.concat(extra).join('\n').substring(0, 8000);
    });
  }
  // null（2ページ目がなかった = extractLines だけで完結）は空文字に
  bodies = bodies.map(function(b) { return b === null ? '' : b; });

  // ─── Phase 3: チャンク生成 & embedding を並列バッチ取得 ──────────────
  var allChunks = [];
  updateList.forEach(function(item, i) {
    var full   = item.pd.meta_text + (bodies[i] ? '\n\n' + bodies[i] : '');
    var chunks = chunkText_(full, 500, 100);
    Logger.log('  [' + item.pd.db + '] ' + item.pd.title + ' → ' + chunks.length + 'チャンク');
    chunks.forEach(function(chunk, k) {
      allChunks.push({ text: chunk, page_id: item.pd.page_id, db: item.pd.db,
                       title: item.pd.title, last_edited: item.pd.last_edited, k: k });
    });
  });

  var BATCH_SIZE = 10; // Gemini レートリミット対策
  var newRows = [], totalOk = 0, totalErr = 0;
  for (var b = 0; b < allChunks.length; b += BATCH_SIZE) {
    var batch = allChunks.slice(b, b + BATCH_SIZE);
    var embedReqs = batch.map(function(c) {
      return {
        url: embedUrl, method: 'post', contentType: 'application/json',
        payload: JSON.stringify({
          model: 'models/gemini-embedding-001',
          content: { parts: [{ text: c.text.substring(0, 2000) }] },
          outputDimensionality: 768, taskType: 'RETRIEVAL_DOCUMENT',
        }),
        muteHttpExceptions: true,
      };
    });
    UrlFetchApp.fetchAll(embedReqs).forEach(function(res, j) {
      var c = batch[j];
      if (res.getResponseCode() !== 200) {
        Logger.log('Embed error [' + c.title + ']: ' + res.getContentText().substring(0, 100));
        totalErr++; return;
      }
      var emb = JSON.parse(res.getContentText()).embedding.values;
      newRows.push([c.page_id + '::' + c.k, c.db, c.title, c.text, c.last_edited, JSON.stringify(emb)]);
      totalOk++;
    });
    if (b + BATCH_SIZE < allChunks.length) Utilities.sleep(200);
  }

  // ─── Phase 4: シート更新 ─────────────────────────────────────────────
  rowsToDelete.sort(function(a, b) { return b - a; });
  rowsToDelete.forEach(function(ri) { sheet.deleteRow(ri); });
  if (newRows.length > 0)
    sheet.getRange(sheet.getLastRow() + 1, 1, newRows.length, 6).setValues(newRows);

  Logger.log('完了  チャンク追加:' + totalOk + '  スキップ(ページ):' + totalSkip + '  エラー:' + totalErr);
  Logger.log('合計チャンク数: ' + (sheet.getLastRow() - 1));
  invalidateIndexCache_();
}

// ─────────────────────────────────────────────
// インデックスキャッシュ（CacheService）
// ─────────────────────────────────────────────

/**
 * キャッシュからインデックスを取得（なければSheetsから読んでキャッシュ保存）
 * @returns {Array} [{db, title, text, emb}, ...]
 */
function loadIndex_() {
  var cache = CacheService.getScriptCache();
  var n     = parseInt(cache.get(IDX_CACHE_KEY + '_n') || '0', 10);
  if (n > 0) {
    var keys = [];
    for (var i = 0; i < n; i++) keys.push(IDX_CACHE_KEY + '_' + i);
    var vals = cache.getAll(keys);
    var json = '', ok = true;
    for (var i = 0; i < n; i++) {
      var c = vals[IDX_CACHE_KEY + '_' + i];
      if (!c) { ok = false; break; }
      json += c;
    }
    if (ok) { try { return JSON.parse(json); } catch(e) {} }
  }
  return loadIndexFromSheet_();
}

/** Sheetsから読み込み → キャッシュ保存。テキストは600文字に制限 */
function loadIndexFromSheet_() {
  var sheet = getSheet_();
  var data  = sheet.getDataRange().getValues();
  var rows  = [];
  for (var i = 1; i < data.length; i++) {
    var embStr = data[i][5];
    if (!embStr) continue;
    rows.push({
      db:    data[i][1],
      title: data[i][2],
      text:  String(data[i][3]).substring(0, 600),
      emb:   JSON.parse(embStr),
    });
  }
  saveIndexToCache_(rows);
  return rows;
}

function saveIndexToCache_(rows) {
  var cache   = CacheService.getScriptCache();
  var json    = JSON.stringify(rows);
  var n       = Math.ceil(json.length / CACHE_CHUNK);
  var entries = {};
  entries[IDX_CACHE_KEY + '_n'] = String(n);
  for (var i = 0; i < n; i++)
    entries[IDX_CACHE_KEY + '_' + i] = json.substring(i * CACHE_CHUNK, (i + 1) * CACHE_CHUNK);
  try {
    cache.putAll(entries, CACHE_TTL);
    Logger.log('インデックスをキャッシュに保存  ' + rows.length + '件  ' + Math.round(json.length / 1024) + 'KB');
  } catch(e) {
    Logger.log('Cache write skipped（データが大きすぎる可能性）: ' + e.message);
  }
}

/** syncNotionToSheets 完了後に呼ぶ。次クエリでシートから再読み込みされる */
function invalidateIndexCache_() {
  CacheService.getScriptCache().remove(IDX_CACHE_KEY + '_n');
  Logger.log('インデックスキャッシュをクリアしました');
}

// ─────────────────────────────────────────────
// コサイン類似度 & ベクトル検索
// ─────────────────────────────────────────────

function cosineSimilarity_(a, b) {
  var dot = 0, na = 0, nb = 0;
  for (var i = 0; i < a.length; i++) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
  var d = Math.sqrt(na) * Math.sqrt(nb);
  return d === 0 ? 0 : dot / d;
}

/**
 * クエリをベクトル化して上位 limit 件を返す（キャッシュ利用）。
 * @returns {Array} [{score, db, title, text}, ...]
 */
function searchByEmbedding_(query, dbKey, limit) {
  limit = limit || 5;
  var qv  = embedQuery_(query);
  if (!qv) return [];
  var idx = loadIndex_();
  if (!idx.length) return [];
  var results = [];
  idx.forEach(function(row) {
    if (dbKey && dbKey !== 'all' && row.db !== dbKey) return;
    results.push({ score: cosineSimilarity_(qv, row.emb), db: row.db, title: row.title, text: row.text });
  });
  results.sort(function(a, b) { return b.score - a.score; });
  return results.slice(0, limit);
}

// ─────────────────────────────────────────────
// Gemini テキスト生成
// ─────────────────────────────────────────────

/**
 * Gemini をマルチターン会話形式で呼び出す
 * @param {Array} contents - [{role:'user'|'model', parts:[{text:'...'}]}, ...]
 */
function callGemini_(contents) {
  var props  = PropertiesService.getScriptProperties();
  var apiKey = props.getProperty('GEMINI_API_KEY');
  var url    = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=' + apiKey;
  var payload = JSON.stringify({
    system_instruction: { parts: [{ text:
      'あなたはゲーム開発チームの知識ベースを持つAIアシスタントです。\n' +
      '日本語で**簡潔に**回答してください（目安: 400文字以内）。\n' +
      '重要な点のみ箇条書き（-）または短い見出し（##）でまとめてください。\n' +
      '詳細な説明は省き、要点だけ伝えてください。\n' +
      '知識ベースに情報がない場合のみ「情報がありません」と答えてください。'
    }]},
    contents:         contents,
    generationConfig: { temperature: 0.4, maxOutputTokens: 1024 },
  });
  var maxRetries = 10, baseDelay = 1000, maxDelay = 30000;
  for (var i = 0; i < maxRetries; i++) {
    var res  = UrlFetchApp.fetch(url, {
      method: 'post', contentType: 'application/json',
      payload: payload, muteHttpExceptions: true,
    });
    var code = res.getResponseCode();
    if (code === 200) {
      return JSON.parse(res.getContentText()).candidates[0].content.parts[0].text;
    }
    if ((code === 429 || code === 503) && i < maxRetries - 1) {
      var ra   = parseInt(((res.getHeaders() || {})['Retry-After'] || '0'), 10);
      var wait = ra > 0 ? ra*1000 : Math.min(baseDelay * Math.pow(2, i), maxDelay) + Math.floor(Math.random()*1000);
      Logger.log('Gemini ' + code + ' retry in ' + wait + 'ms');
      Utilities.sleep(wait);
      continue;
    }
    Logger.log('Gemini error ' + code + ': ' + res.getContentText());
    return '（Gemini APIエラー: ' + code + '）';
  }
  return '（リトライ上限に達しました）';
}

// ─────────────────────────────────────────────
// RAG メイン処理
// ─────────────────────────────────────────────

/**
 * RAG クエリ（マルチターン対応）。{answer, sources} を返す。
 * @param {string} query   - 現在の質問
 * @param {string} dbKey   - DB絞り込み
 * @param {Array}  history - 過去の会話 [{role:'user'|'bot', text:'...'}]
 */
function ragQuery(query, dbKey, history) {
  history = history || [];

  // 現在の質問でベクトル検索（LocalRAGと同じ5チャンク）
  var results = searchByEmbedding_(query, dbKey, 5);

  var context = results.length === 0
    ? '（関連ドキュメントが見つかりませんでした）'
    : results.map(function(r, i) {
        return '### [' + (i+1) + '] ' + r.title + '（DB: ' + r.db + ' / 関連度: ' + (r.score*100).toFixed(1) + '%）\n' + r.text;
      }).join('\n\n');

  // Gemini contents 配列を構築（マルチターン）
  // 最初に「知識ベース注入」を user/model の仮想交換として差し込む
  var contents = [
    {
      role:  'user',
      parts: [{ text: '以下の参考ドキュメントを確認しました。これを元に質問に答えてください。\n\n' + context }],
    },
    {
      role:  'model',
      parts: [{ text: '参考ドキュメントを確認しました。ご質問にお答えします。' }],
    },
  ];

  // 会話履歴を追加（直近3往復まで：それ以上は文脈が古くトークン節約優先）
  var recentHistory = history.slice(-6);
  recentHistory.forEach(function(h) {
    contents.push({
      role:  h.role === 'bot' ? 'model' : 'user',
      parts: [{ text: h.text }],
    });
  });

  // 現在の質問を追加
  contents.push({ role: 'user', parts: [{ text: query }] });

  var answer = callGemini_(contents);

  // 同じページの複数チャンクが引っかかった場合、最高スコアのものだけを表示
  var seen    = {};
  var sources = [];
  results.forEach(function(r) {
    var key = r.db + '::' + r.title;
    if (!seen[key]) { seen[key] = true; sources.push({ title: r.title, db: r.db, score: r.score }); }
  });

  return { answer: answer, sources: sources };
}

// ─────────────────────────────────────────────
// WebApp エントリポイント
// ─────────────────────────────────────────────

/** google.script.run から呼ぶための公開ラッパー（_付き関数は呼べないため） */
function getGraphData() {
  return buildGraphData_();
}

function doGet(e) {
  return HtmlService.createHtmlOutput(getChatHtml())
    .setTitle('RAG チャット')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// ─────────────────────────────────────────────
// グラフデータ構築（doGet?action=graph 用）
// ─────────────────────────────────────────────

/**
 * RAG_Index シートから各ページ代表埋め込みを読み込み、
 * コサイン類似度 top-3 エッジを算出して返す。
 * CacheService に 30 分キャッシュ。
 */
function buildGraphData_() {
  var GRAPH_CACHE_KEY = 'rag_graph_v1';
  var GRAPH_CACHE_TTL = 1800;  // 30 分

  var cache  = CacheService.getScriptCache();
  var cached = cache.get(GRAPH_CACHE_KEY);
  if (cached) return JSON.parse(cached);

  var sheet = getSheet_();
  var data  = sheet.getDataRange().getValues();

  // 各 page_id の 0 番チャンク（page_id::0）を代表とする
  var docs = {};
  for (var i = 1; i < data.length; i++) {
    var row    = data[i];
    var cellId = String(row[0]);
    if (!row[5]) continue;                        // embedding なし
    if (cellId.split('::')[1] !== '0') continue; // 0 番チャンクのみ
    var baseId = cellId.split('::')[0];
    if (!docs[baseId]) {
      docs[baseId] = {
        id:    baseId,
        label: String(row[2]),
        db:    String(row[1]),
        emb:   JSON.parse(row[5]),
      };
    }
  }

  var docList = Object.values(docs);

  // コサイン類似度 top-3 エッジ（閾値 0.70）
  var edges = [];
  var seen  = {};
  for (var i = 0; i < docList.length; i++) {
    var scores = [];
    for (var j = 0; j < docList.length; j++) {
      if (i === j) continue;
      scores.push({ j: j, score: cosineSimilarity_(docList[i].emb, docList[j].emb) });
    }
    scores.sort(function(a, b) { return b.score - a.score; });
    for (var k = 0; k < Math.min(3, scores.length); k++) {
      if (scores[k].score < 0.70) break;
      var srcId = docList[i].id, tgtId = docList[scores[k].j].id;
      var key   = srcId < tgtId ? srcId + '|' + tgtId : tgtId + '|' + srcId;
      if (!seen[key]) {
        seen[key] = true;
        edges.push({ source: srcId, target: tgtId,
                     score: Math.round(scores[k].score * 1000) / 1000 });
      }
    }
  }

  var result = {
    nodes: docList.map(function(d) { return { id: d.id, label: d.label, db: d.db }; }),
    edges: edges,
    status: 'ok',
  };

  try {
    var json = JSON.stringify(result);
    if (json.length < 90000) cache.put(GRAPH_CACHE_KEY, json, GRAPH_CACHE_TTL);
  } catch (err) { /* キャッシュサイズ超過は無視 */ }

  return result;
}

function doPost(e) {
  try {
    var body    = JSON.parse(e.postData.contents);
    var query   = body.query;
    var dbKey   = body.dbKey || 'all';
    var history = body.history || [];
    if (!query) throw new Error('query は必須です');
    var result = ragQuery(query, dbKey, history);
    return ContentService
      .createTextOutput(JSON.stringify({ answer: result.answer, sources: result.sources, status: 'ok' }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    Logger.log('doPost error: ' + err.message);
    return ContentService
      .createTextOutput(JSON.stringify({ answer: 'エラー: ' + err.message, sources: [], status: 'error' }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ─────────────────────────────────────────────
// チャット UI
// ─────────────────────────────────────────────

function getChatHtml() {
  return '<!DOCTYPE html>\n<html lang="ja">\n<head>\n' +
'<meta charset="UTF-8">\n' +
'<meta name="viewport" content="width=device-width,initial-scale=1">\n' +
'<title>RAG チャット</title>\n' +
'<style>\n' +
':root{--primary:#6366f1;--primary-dark:#4f46e5;--bg:#f1f5f9;--white:#ffffff;--text:#1e293b;--text-light:#64748b;--border:#e2e8f0;--user-grad:linear-gradient(135deg,#6366f1,#8b5cf6);--bot-bg:#f8fafc;--shadow:0 1px 4px rgba(0,0,0,.08)}\n' +
'*{box-sizing:border-box;margin:0;padding:0}\n' +
'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);height:100vh;display:flex;flex-direction:column;max-width:820px;margin:0 auto}\n' +
'header{background:var(--white);border-bottom:1px solid var(--border);padding:12px 16px;display:flex;align-items:center;gap:10px;box-shadow:var(--shadow);flex-shrink:0}\n' +
'.hicon{width:36px;height:36px;background:var(--user-grad);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}\n' +
'.htext{flex:1;min-width:0}.htext h1{font-size:15px;font-weight:700;color:var(--text)}.htext p{font-size:11px;color:var(--text-light)}\n' +
'#clear-btn{padding:6px 12px;font-size:12px;background:none;border:1px solid var(--border);border-radius:8px;color:var(--text-light);cursor:pointer;white-space:nowrap;transition:all .15s;font-family:inherit}\n' +
'#clear-btn:hover{border-color:#ef4444;color:#ef4444;background:#fef2f2}\n' +
'.dbwrap{padding:8px 14px;background:var(--white);border-bottom:1px solid var(--border);flex-shrink:0}\n' +
'select{width:100%;padding:7px 11px;border:1px solid var(--border);border-radius:8px;font-size:13px;color:var(--text);background:var(--white);cursor:pointer;outline:none}\n' +
'select:focus{border-color:var(--primary)}\n' +
'#chat{flex:1;overflow-y:auto;padding:18px 14px;display:flex;flex-direction:column;gap:14px}\n' +
'.welcome{text-align:center;padding:50px 20px;color:var(--text-light)}\n' +
'.welcome-icon{font-size:48px;margin-bottom:12px}\n' +
'.welcome h2{font-size:16px;color:var(--text);margin-bottom:7px;font-weight:700}\n' +
'.welcome p{font-size:12px;line-height:1.6}\n' +
'.msg{display:flex;gap:8px;max-width:90%}\n' +
'.msg.user{align-self:flex-end;flex-direction:row-reverse}\n' +
'.msg.bot{align-self:flex-start}\n' +
'.av{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0;background:var(--bot-bg);border:1px solid var(--border);margin-top:2px}\n' +
'.msg.user .av{background:var(--user-grad);border:none}\n' +
'.bwrap{display:flex;flex-direction:column;gap:5px;min-width:0}\n' +
'.bubble{padding:10px 14px;border-radius:16px;font-size:14px;line-height:1.75;word-break:break-word}\n' +
'.msg.user .bubble{background:var(--user-grad);color:#fff;border-bottom-right-radius:4px}\n' +
'.msg.bot .bubble{background:var(--white);color:var(--text);border-bottom-left-radius:4px;box-shadow:var(--shadow);border:1px solid var(--border)}\n' +
'.msg.bot .bubble h1,.msg.bot .bubble h2,.msg.bot .bubble h3{font-size:14px;font-weight:700;margin:10px 0 4px;color:var(--text)}\n' +
'.msg.bot .bubble h2{border-bottom:1px solid var(--border);padding-bottom:4px}\n' +
'.msg.bot .bubble p{margin-bottom:8px}\n' +
'.msg.bot .bubble p:last-child{margin-bottom:0}\n' +
'.msg.bot .bubble ul,.msg.bot .bubble ol{padding-left:20px;margin-bottom:8px}\n' +
'.msg.bot .bubble li{margin-bottom:3px}\n' +
'.msg.bot .bubble strong{font-weight:700}\n' +
'.msg.bot .bubble code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-family:monospace;font-size:12px;color:#6366f1}\n' +
'.msg.bot .bubble pre{background:#1e293b;color:#e2e8f0;padding:12px 14px;border-radius:10px;overflow-x:auto;margin:8px 0;font-size:12px}\n' +
'.msg.bot .bubble pre code{background:none;padding:0;color:inherit}\n' +
'.msg.bot .bubble blockquote{border-left:3px solid var(--primary);padding-left:10px;color:var(--text-light);margin:6px 0}\n' +
'.msg-actions{display:flex;gap:6px;align-items:center;height:0;overflow:visible}\n' +
'.copy-btn{font-size:11px;padding:2px 8px;border:1px solid var(--border);border-radius:6px;background:var(--white);color:var(--text-light);cursor:pointer;white-space:nowrap;opacity:0;transition:opacity .15s;font-family:inherit}\n' +
'.msg.bot:hover .copy-btn{opacity:1}\n' +
'.copy-btn:hover{border-color:var(--primary);color:var(--primary)}\n' +
'.copy-btn.copied{border-color:#16a34a;color:#16a34a}\n' +
'.dots{display:flex;gap:5px;padding:6px 0}\n' +
'.dots span{width:7px;height:7px;background:#94a3b8;border-radius:50%;animation:db 1.2s ease-in-out infinite}\n' +
'.dots span:nth-child(2){animation-delay:.2s}.dots span:nth-child(3){animation-delay:.4s}\n' +
'@keyframes db{0%,80%,100%{transform:scale(.7);opacity:.5}40%{transform:scale(1);opacity:1}}\n' +
'.sources{margin-top:3px}\n' +
'.src-toggle{font-size:11px;color:var(--text-light);cursor:pointer;display:inline-flex;align-items:center;gap:3px;background:none;border:none;padding:2px 0;font-family:inherit}\n' +
'.src-toggle:hover{color:var(--primary)}\n' +
'.src-list{display:none;margin-top:5px;background:var(--white);border:1px solid var(--border);border-radius:10px;overflow:hidden;box-shadow:var(--shadow)}\n' +
'.src-list.open{display:block}\n' +
'.src-item{padding:7px 11px;font-size:12px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;color:var(--text)}\n' +
'.src-item:last-child{border-bottom:none}\n' +
'.src-db{font-size:11px;background:#ede9fe;color:#6d28d9;padding:2px 7px;border-radius:10px;white-space:nowrap;flex-shrink:0}\n' +
'.src-score{color:var(--text-light);margin-left:auto;font-size:11px;font-weight:600;white-space:nowrap}\n' +
'.src-score.high{color:#16a34a}.src-score.mid{color:#d97706}.src-score.low{color:#94a3b8}\n' +
'.input-area{padding:10px 14px;background:var(--white);border-top:1px solid var(--border);display:flex;gap:8px;align-items:flex-end;flex-shrink:0}\n' +
'textarea{flex:1;padding:9px 13px;border:1.5px solid var(--border);border-radius:12px;font-size:14px;font-family:inherit;color:var(--text);resize:none;outline:none;max-height:120px;min-height:42px;line-height:1.6;transition:border-color .2s;background:var(--white)}\n' +
'textarea:focus{border-color:var(--primary)}\n' +
'textarea::placeholder{color:#94a3b8}\n' +
'#sbtn{width:42px;height:42px;background:var(--primary);color:#fff;border:none;border-radius:12px;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;transition:background .2s;flex-shrink:0}\n' +
'#sbtn:hover{background:var(--primary-dark)}\n' +
'#sbtn:disabled{background:#c7d2fe;cursor:not-allowed}\n' +
'.turn-badge{font-size:11px;color:var(--text-light);text-align:center;margin:-6px 0;opacity:.6}\n' +
'.tab-bar{display:flex;gap:0;background:var(--white);border-bottom:1px solid var(--border);flex-shrink:0}\n' +
'.tab-btn{flex:1;padding:9px 0;font-size:13px;font-weight:600;border:none;background:none;cursor:pointer;color:var(--text-light);border-bottom:2px solid transparent;font-family:inherit;transition:all .15s}\n' +
'.tab-btn.active{color:var(--primary);border-bottom-color:var(--primary)}\n' +
'.tab-btn:hover:not(.active){color:var(--text);background:#f8fafc}\n' +
'#tab-chat{display:flex;flex-direction:column;flex:1;overflow:hidden}\n' +
'#tab-graph{display:none;flex-direction:column;flex:1;overflow:hidden;background:#0f172a;color:#e2e8f0}\n' +
'.graph-toolbar{padding:8px 14px;display:flex;align-items:center;gap:8px;border-bottom:1px solid #1e293b;flex-shrink:0}\n' +
'.graph-toolbar button{padding:5px 14px;border:1px solid #334155;border-radius:8px;background:#1e293b;color:#e2e8f0;cursor:pointer;font-size:12px;font-family:inherit;transition:all .15s}\n' +
'.graph-toolbar button:hover{background:#334155}\n' +
'#graph-status{font-size:11px;color:#94a3b8;margin-left:4px}\n' +
'#graph-svg{flex:1;width:100%;display:block}\n' +
'#node-detail{padding:8px 14px;font-size:12px;color:#94a3b8;border-top:1px solid #1e293b;flex-shrink:0;min-height:36px}\n' +
'</style>\n</head>\n<body>\n' +
'<header>\n' +
'  <div class="hicon">🔍</div>\n' +
'  <div class="htext"><h1>RAG チャット</h1><p>Notion × Gemini ベクトル検索</p></div>\n' +
'  <button id="clear-btn" onclick="clearChat()">🗑 会話をクリア</button>\n' +
'</header>\n' +
'<div class="tab-bar">\n' +
'  <button class="tab-btn active" onclick="switchTab(\'chat\')">💬 チャット</button>\n' +
'  <button class="tab-btn" id="graph-tab-btn" onclick="switchTab(\'graph\')">🕸 グラフ</button>\n' +
'</div>\n' +
'<div id="tab-chat">\n' +
'<div class="dbwrap">\n' +
'  <select id="db">\n' +
'    <option value="all">🌐 全DB横断検索</option>\n' +
'    <option value="tool_docs">🛠️ Tool Docs（Unity / Houdini / DX12）</option>\n' +
'    <option value="game_info">🎮 Game Info（ゲーム情報）</option>\n' +
'    <option value="research">📄 Research（論文・技術記事）</option>\n' +
'    <option value="team_notes">📝 Team Notes（ゼミ・議事録）</option>\n' +
'    <option value="afuri">🍜 AFURI（ラーメン）</option>\n' +
'    <option value="braintq">🧠 BrainTQ（脳トレアプリ）</option>\n' +
'    <option value="fourteen">⛳ Fourteen（ゴルフブランド）</option>\n' +
'  </select>\n' +
'</div>\n' +
'<div id="chat">\n' +
'  <div class="welcome">\n' +
'    <div class="welcome-icon">🧠</div>\n' +
'    <h2>何でも聞いてください</h2>\n' +
'    <p>Notionの知識ベースをベクトル検索で参照し、<br>Geminiが分析・統合して回答します<br><span style="font-size:11px;opacity:.7">会話の文脈を保持してマルチターン対応しています</span></p>\n' +
'  </div>\n' +
'</div>\n' +
'<div class="input-area">\n' +
'  <textarea id="q" placeholder="質問を入力... (Ctrl+Enter で送信)" rows="1"></textarea>\n' +
'  <button id="sbtn" onclick="send()">↑</button>\n' +
'</div>\n' +
'</div>\n' +   // #tab-chat 閉じ
'<div id="tab-graph">\n' +
'  <div class="graph-toolbar">\n' +
'    <button onclick="loadGraph()">更新</button>\n' +
'    <button onclick="fitGraph()">全体</button>\n' +
'    <span id="graph-status">「更新」を押してグラフを取得</span>\n' +
'  </div>\n' +
'  <svg id="graph-svg"></svg>\n' +
'  <div id="node-detail">ノードをクリックして詳細を表示</div>\n' +
'</div>\n' +
'<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>\n' +
'<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>\n' +
'<script>\n' +
'if(typeof marked!=="undefined")marked.setOptions({breaks:true,gfm:true});\n' +
'\n' +
'// 会話履歴（window.historyと衝突しないよう chatHistory と命名）\n' +
'var chatHistory=[];\n' +
'\n' +
'var ta=document.getElementById("q");\n' +
'ta.addEventListener("input",function(){this.style.height="auto";this.style.height=Math.min(this.scrollHeight,120)+"px";});\n' +
'ta.addEventListener("keydown",function(e){if((e.ctrlKey||e.metaKey)&&e.key==="Enter")send();});\n' +
'\n' +
'function md(text){return(typeof marked!=="undefined")?marked.parse(text||""):text;}\n' +
'\n' +
'function addMsg(role,content,sources){\n' +
'  var chat=document.getElementById("chat");\n' +
'  var welcome=chat.querySelector(".welcome");\n' +
'  if(welcome)welcome.remove();\n' +
'\n' +
'  // 2ターン目以降にターン番号を表示\n' +
'  var turnCount=chat.querySelectorAll(".msg.user").length;\n' +
'  if(role==="user"&&turnCount>0){\n' +
'    var badge=document.createElement("div");badge.className="turn-badge";\n' +
'    badge.textContent="─ 続けて質問 ─";\n' +
'    chat.appendChild(badge);\n' +
'  }\n' +
'\n' +
'  var msg=document.createElement("div");msg.className="msg "+role;\n' +
'  var av=document.createElement("div");av.className="av";\n' +
'  av.textContent=role==="user"?"👤":"🤖";\n' +
'  var wrap=document.createElement("div");wrap.className="bwrap";\n' +
'  var bubble=document.createElement("div");bubble.className="bubble";\n' +
'\n' +
'  if(role==="bot"&&content==="loading"){\n' +
'    bubble.innerHTML=\'<div class="dots"><span></span><span></span><span></span></div>\';\n' +
'  } else if(role==="bot"){\n' +
'    bubble.innerHTML=md(content);\n' +
'  } else {\n' +
'    bubble.textContent=content;\n' +
'  }\n' +
'\n' +
'  wrap.appendChild(bubble);\n' +
'\n' +
'  // コピーボタン（botメッセージのみ、ローディング中は後で追加）\n' +
'  if(role==="bot"&&content!=="loading"){\n' +
'    wrap.appendChild(buildActions_(bubble,content));\n' +
'  }\n' +
'\n' +
'  if(sources&&sources.length>0)wrap.appendChild(buildSources_(sources));\n' +
'  msg.appendChild(av);msg.appendChild(wrap);\n' +
'  chat.appendChild(msg);chat.scrollTop=chat.scrollHeight;\n' +
'  return{bubble:bubble,wrap:wrap,rawText:content};\n' +
'}\n' +
'\n' +
'function buildActions_(bubble,rawText){\n' +
'  var div=document.createElement("div");div.className="msg-actions";\n' +
'  var btn=document.createElement("button");btn.className="copy-btn";\n' +
'  btn.textContent="コピー";\n' +
'  btn.onclick=function(){\n' +
'    var text=bubble.innerText||rawText||"";\n' +
'    navigator.clipboard.writeText(text).then(function(){\n' +
'      btn.textContent="✓ コピー済";btn.classList.add("copied");\n' +
'      setTimeout(function(){btn.textContent="コピー";btn.classList.remove("copied");},2000);\n' +
'    }).catch(function(){});\n' +
'  };\n' +
'  div.appendChild(btn);\n' +
'  return div;\n' +
'}\n' +
'\n' +
'function buildSources_(sources){\n' +
'  var div=document.createElement("div");div.className="sources";\n' +
'  var btn=document.createElement("button");btn.className="src-toggle";\n' +
'  btn.innerHTML="📎 参考情報 "+sources.length+"件 ▾";\n' +
'  var list=document.createElement("div");list.className="src-list";\n' +
'  sources.forEach(function(s,i){\n' +
'    var pct=(s.score*100).toFixed(1);\n' +
'    var cls=s.score>=0.75?"high":s.score>=0.5?"mid":"low";\n' +
'    var item=document.createElement("div");item.className="src-item";\n' +
'    item.innerHTML=(i+1)+". "+s.title+\'<span class="src-db">\'+s.db+\'</span><span class="src-score \'+cls+\'">\'+ pct+\'%</span>\';\n' +
'    list.appendChild(item);\n' +
'  });\n' +
'  btn.onclick=function(){list.classList.toggle("open");btn.innerHTML="📎 参考情報 "+sources.length+"件 "+(list.classList.contains("open")?"▴":"▾");};\n' +
'  div.appendChild(btn);div.appendChild(list);\n' +
'  return div;\n' +
'}\n' +
'\n' +
'function clearChat(){\n' +
'  chatHistory=[];\n' +
'  var chat=document.getElementById("chat");\n' +
'  chat.innerHTML=\'<div class="welcome"><div class="welcome-icon">🧠</div><h2>何でも聞いてください</h2><p>Notionの知識ベースをベクトル検索で参照し、<br>Geminiが分析・統合して回答します<br><span style="font-size:11px;opacity:.7">会話の文脈を保持してマルチターン対応しています</span></p></div>\';\n' +
'}\n' +
'\n' +
'var isSending=false;\n' +
'function send(){\n' +
'  if(isSending)return;\n' +
'  var q=ta.value.trim();\n' +
'  var dbKey=document.getElementById("db").value;\n' +
'  if(!q)return;\n' +
'  ta.value="";ta.style.height="auto";\n' +
'  isSending=true;document.getElementById("sbtn").disabled=true;\n' +
'\n' +
'  addMsg("user",q);\n' +
'  var bot=addMsg("bot","loading");\n' +
'  var historySnapshot=chatHistory.slice(); // コピーして渡す\n' +
'\n' +
'  google.script.run\n' +
'    .withSuccessHandler(function(result){\n' +
'      isSending=false;document.getElementById("sbtn").disabled=false;\n' +
'      var answer=result.answer||"";\n' +
'      bot.bubble.innerHTML=md(answer);\n' +
'\n' +
'      // コピーボタンを追加\n' +
'      bot.wrap.insertBefore(buildActions_(bot.bubble,answer),bot.wrap.children[1]||null);\n' +
'\n' +
'      if(result.sources&&result.sources.length>0)\n' +
'        bot.wrap.appendChild(buildSources_(result.sources));\n' +
'\n' +
'      // 履歴に追加\n' +
'      chatHistory.push({role:"user",text:q});\n' +
'      chatHistory.push({role:"bot", text:answer});\n' +
'\n' +
'      document.getElementById("chat").scrollTop=99999;\n' +
'    })\n' +
'    .withFailureHandler(function(err){\n' +
'      isSending=false;document.getElementById("sbtn").disabled=false;\n' +
'      bot.bubble.textContent="エラー: "+(err.message||"Unknown error");\n' +
'    })\n' +
'    .ragQuery(q,dbKey,historySnapshot);\n' +
'}\n' +
'// ── タブ切り替え ─────────────────────────────────────────────────────────\n' +
'function switchTab(tab){\n' +
'  var isChat=(tab==="chat");\n' +
'  document.getElementById("tab-chat").style.display=isChat?"flex":"none";\n' +
'  document.getElementById("tab-graph").style.display=isChat?"none":"flex";\n' +
'  document.querySelectorAll(".tab-btn").forEach(function(b){\n' +
'    b.classList.toggle("active",b.textContent.includes(isChat?"チャット":"グラフ"));\n' +
'  });\n' +
'  if(!isChat && !window._graphLoaded) loadGraph();\n' +
'}\n' +
'\n' +
'// ── グラフ描画（D3.js）─────────────────────────────────────────────────\n' +
'var _graphSim=null;\n' +
'var _graphLoaded=false;\n' +
'var DB_COLORS={tool_docs:"#6366f1",game_info:"#10b981",research:"#f59e0b",team_notes:"#ef4444",afuri:"#f97316",braintq:"#8b5cf6",fourteen:"#06b6d4"};\n' +
'\n' +
'function loadGraph(){\n' +
'  var status=document.getElementById("graph-status");\n' +
'  status.textContent="グラフデータ取得中...";\n' +
'  google.script.run\n' +
'    .withSuccessHandler(function(data){\n' +
'      if(!data||!data.nodes){status.textContent="データが空です";return;}\n' +
'      renderGraph(data);\n' +
'      _graphLoaded=true;\n' +
'    })\n' +
'    .withFailureHandler(function(err){\n' +
'      status.textContent="エラー: "+(err.message||String(err));\n' +
'    })\n' +
'    .getGraphData();\n' +
'}\n' +
'\n' +
'function fitGraph(){\n' +
'  if(_graphSim) window._d3svg&&window._d3svg.transition().call(window._d3zoom.transform,d3.zoomIdentity);\n' +
'}\n' +
'\n' +
'function renderGraph(data){\n' +
'  if(_graphSim){_graphSim.stop();}\n' +
'  var svgEl=document.getElementById("graph-svg");\n' +
'  var w=svgEl.clientWidth||600, h=svgEl.clientHeight||400;\n' +
'  var svg=d3.select("#graph-svg").attr("width",w).attr("height",h);\n' +
'  svg.selectAll("*").remove();\n' +
'  window._d3svg=svg;\n' +
'\n' +
'  var g=svg.append("g");\n' +
'  var zoom=d3.zoom().scaleExtent([0.1,6]).on("zoom",function(ev){g.attr("transform",ev.transform);});\n' +
'  svg.call(zoom);\n' +
'  window._d3zoom=zoom;\n' +
'\n' +
'  var nodes=data.nodes.map(function(d){return Object.assign({},d);});\n' +
'  var links=data.edges.map(function(e){return{source:e.source,target:e.target,score:e.score};});\n' +
'\n' +
'  var link=g.append("g").selectAll("line").data(links).enter().append("line")\n' +
'    .attr("stroke","#475569").attr("stroke-opacity",function(d){return 0.3+d.score*0.5;}).attr("stroke-width",1.5);\n' +
'\n' +
'  var node=g.append("g").selectAll("g").data(nodes).enter().append("g")\n' +
'    .call(d3.drag().on("start",dragStart).on("drag",dragged).on("end",dragEnd))\n' +
'    .on("click",function(ev,d){\n' +
'      document.getElementById("node-detail").textContent=d.label+" | DB: "+d.db;\n' +
'    });\n' +
'\n' +
'  node.append("circle").attr("r",12)\n' +
'    .attr("fill",function(d){return DB_COLORS[d.db]||"#64748b";})\n' +
'    .attr("stroke","#0f172a").attr("stroke-width",1.5)\n' +
'    .on("mouseover",function(){d3.select(this).attr("r",16).attr("stroke","#fbbf24");})\n' +
'    .on("mouseout", function(){d3.select(this).attr("r",12).attr("stroke","#0f172a");});\n' +
'\n' +
'  node.append("text").text(function(d){return d.label.length>12?d.label.slice(0,12)+"…":d.label;})\n' +
'    .attr("x",15).attr("y",4).attr("font-size","10px").attr("fill","#cbd5e1");\n' +
'\n' +
'  _graphSim=d3.forceSimulation(nodes)\n' +
'    .force("link",d3.forceLink(links).id(function(d){return d.id;}).distance(80).strength(function(d){return d.score;}))\n' +
'    .force("charge",d3.forceManyBody().strength(-200))\n' +
'    .force("center",d3.forceCenter(w/2,h/2))\n' +
'    .force("collision",d3.forceCollide(18))\n' +
'    .on("tick",function(){\n' +
'      link.attr("x1",function(d){return d.source.x;}).attr("y1",function(d){return d.source.y;})\n' +
'          .attr("x2",function(d){return d.target.x;}).attr("y2",function(d){return d.target.y;});\n' +
'      node.attr("transform",function(d){return "translate("+d.x+","+d.y+")";});\n' +
'    });\n' +
'\n' +
'  document.getElementById("graph-status").textContent=\n' +
'    nodes.length+"ノード / "+links.length+"エッジ  ドラッグ:移動  ホイール:ズーム  クリック:詳細";\n' +
'}\n' +
'\n' +
'function dragStart(ev,d){if(!ev.active)_graphSim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y;}\n' +
'function dragged(ev,d){d.fx=ev.x;d.fy=ev.y;}\n' +
'function dragEnd(ev,d){if(!ev.active)_graphSim.alphaTarget(0);d.fx=null;d.fy=null;}\n' +
'</script>\n</body>\n</html>'
}

// ─────────────────────────────────────────────
// デバッグ用（GASエディタから実行）
// ─────────────────────────────────────────────

function testEmbedding() {
  var vec = embed_('テスト');
  if (vec) {
    Logger.log('✅ embedding-001 OK  次元数: ' + vec.length + '  先頭3値: ' + vec.slice(0, 3));
  } else {
    Logger.log('❌ embedding-001 もNGでした。利用可能モデル一覧を確認してください。');
    var props  = PropertiesService.getScriptProperties();
    var apiKey = props.getProperty('GEMINI_API_KEY');
    var res    = UrlFetchApp.fetch('https://generativelanguage.googleapis.com/v1beta/models?key=' + apiKey, { muteHttpExceptions: true });
    var models = JSON.parse(res.getContentText()).models || [];
    var embeds = models.filter(function(m) { return m.name.indexOf('embed') !== -1 || m.name.indexOf('Embed') !== -1; });
    Logger.log('Embedding対応モデル: ' + embeds.map(function(m) { return m.name; }).join(', '));
  }
}

function testSearch() {
  var results = searchByEmbedding_('柚子塩らーめんの店舗はどこ？', 'afuri', 3);
  results.forEach(function(r) {
    Logger.log('[' + (r.score*100).toFixed(1) + '%] ' + r.title + ' (' + r.db + ')');
  });
}

function testRagQuery() {
  var result = ragQuery('AFURIについて教えてください', 'afuri');
  Logger.log('=== 回答 ===\n' + result.answer);
  Logger.log('=== ソース ===');
  result.sources.forEach(function(s) {
    Logger.log('[' + (s.score*100).toFixed(1) + '%] ' + s.title);
  });
}
