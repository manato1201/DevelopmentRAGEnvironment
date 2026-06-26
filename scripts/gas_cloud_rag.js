/**
 * Cloud RAG Chatbot — Google Apps Script  v3 (Auth対応版)
 *
 * ── スクリプトプロパティ ─────────────────────────────────────────────
 *   NOTION_API_KEY, GEMINI_API_KEY          (既存)
 *   DB_TOOL_DOCS, DB_GAME_INFO, DB_RESEARCH,
 *   DB_TEAM_NOTES, DB_AFURI, DB_BRAINTQ, DB_FOURTEEN (既存)
 *   SHEETS_ID          ← ベクトル保存用スプレッドシートID
 *
 *   --- 以下は自動管理（手動設定不要） ---
 *   ADMIN_EMAILS       ← カンマ区切り管理者Gmailアドレス (初回だけ手動設定)
 *   USERS_CONFIG       ← ユーザーJSON (管理画面で自動管理)
 *   API_KEYS_CONFIG    ← APIキーJSON  (管理画面で自動管理)
 * ────────────────────────────────────────────────────────────────────
 *
 * 初回セットアップ:
 *   1. スクリプトプロパティ ADMIN_EMAILS に自分のGmailを設定
 *   2. WebApp としてデプロイ（アクセス: Googleアカウントが必要な全員）
 *   3. ブラウザで開くと管理タブからユーザー/APIキーを追加できる
 */

// ─────────────────────────────────────────────
// 定数
// ─────────────────────────────────────────────

var DB_KEY_MAP = {
  tool_docs:  'DB_TOOL_DOCS',
  game_info:  'DB_GAME_INFO',
  research:   'DB_RESEARCH',
  team_notes: 'DB_TEAM_NOTES',
  afuri:      'DB_AFURI',
  braintq:    'DB_BRAINTQ',
  fourteen:   'DB_FOURTEEN',
};

var DB_LABELS = {
  tool_docs:  '🛠️ Tool Docs',
  game_info:  '🎮 Game Info',
  research:   '📄 Research',
  team_notes: '📝 Team Notes',
  afuri:      '🍜 AFURI',
  braintq:    '🧠 BrainTQ',
  fourteen:   '⛳ Fourteen',
};

var ALL_NAMESPACES = Object.keys(DB_KEY_MAP);
var SHEET_NAME    = 'RAG_Index';
var IDX_CACHE_KEY = 'rag_idx_v2';
var CACHE_TTL     = 21600;
var CACHE_CHUNK   = 90000;

// ─────────────────────────────────────────────
// 認証・ユーザー管理
// ─────────────────────────────────────────────

function getProps_() {
  return PropertiesService.getScriptProperties();
}

function getUsersConfig_() {
  var raw = getProps_().getProperty('USERS_CONFIG') || '[]';
  try { return JSON.parse(raw); } catch(e) { return []; }
}

function saveUsersConfig_(users) {
  getProps_().setProperty('USERS_CONFIG', JSON.stringify(users));
}

function getApiKeysConfig_() {
  var raw = getProps_().getProperty('API_KEYS_CONFIG') || '[]';
  try { return JSON.parse(raw); } catch(e) { return []; }
}

function saveApiKeysConfig_(keys) {
  getProps_().setProperty('API_KEYS_CONFIG', JSON.stringify(keys));
}

/**
 * 現在の Google セッションユーザーの認証情報を返す。
 * 未認証または権限なしは null。
 */
function getCurrentUserAuth_() {
  var email = Session.getActiveUser().getEmail();
  if (!email) return null;

  var adminEmails = (getProps_().getProperty('ADMIN_EMAILS') || '')
    .split(',').map(function(s) { return s.trim().toLowerCase(); })
    .filter(function(s) { return s; });

  var isAdmin = adminEmails.indexOf(email.toLowerCase()) !== -1;

  // 管理者は常に全 namespace へアクセス可
  if (isAdmin) {
    return { email: email, displayName: email, namespaces: ALL_NAMESPACES, isAdmin: true };
  }

  // 通常ユーザー: USERS_CONFIG に登録されているか確認
  var users = getUsersConfig_();
  for (var i = 0; i < users.length; i++) {
    if (users[i].email.toLowerCase() === email.toLowerCase()) {
      return {
        email: email,
        displayName: users[i].displayName || email,
        namespaces: users[i].namespaces || [],
        isAdmin: false,
      };
    }
  }

  return null; // 未登録ユーザー
}

/**
 * APIキーを検証して設定を返す。無効なら null。
 */
function validateApiKey_(key) {
  if (!key) return null;
  var keys = getApiKeysConfig_();
  for (var i = 0; i < keys.length; i++) {
    if (keys[i].key === key) return keys[i];
  }
  return null;
}

// ─────────────────────────────────────────────
// 管理者用 API（google.script.run から呼ぶ）
// ─────────────────────────────────────────────

function adminGetUsers() {
  var user = getCurrentUserAuth_();
  if (!user || !user.isAdmin) throw new Error('管理者権限が必要です');
  return getUsersConfig_();
}

function adminUpsertUser(email, displayName, namespaces) {
  var user = getCurrentUserAuth_();
  if (!user || !user.isAdmin) throw new Error('管理者権限が必要です');
  if (!email) throw new Error('メールアドレスは必須です');
  var invalidNs = namespaces.filter(function(n) { return ALL_NAMESPACES.indexOf(n) === -1; });
  if (invalidNs.length) throw new Error('無効なnamespace: ' + invalidNs.join(','));

  var users = getUsersConfig_();
  var found = false;
  for (var i = 0; i < users.length; i++) {
    if (users[i].email.toLowerCase() === email.toLowerCase()) {
      users[i].displayName = displayName;
      users[i].namespaces  = namespaces;
      found = true;
      break;
    }
  }
  if (!found) users.push({ email: email, displayName: displayName, namespaces: namespaces });
  saveUsersConfig_(users);
  return { ok: true };
}

function adminRemoveUser(email) {
  var user = getCurrentUserAuth_();
  if (!user || !user.isAdmin) throw new Error('管理者権限が必要です');
  var users = getUsersConfig_().filter(function(u) {
    return u.email.toLowerCase() !== email.toLowerCase();
  });
  saveUsersConfig_(users);
  return { ok: true };
}

function adminGetApiKeys() {
  var user = getCurrentUserAuth_();
  if (!user || !user.isAdmin) throw new Error('管理者権限が必要です');
  return getApiKeysConfig_().map(function(k) {
    return {
      keyPreview:  k.key.substring(0, 8) + '...',
      displayName: k.displayName,
      namespaces:  k.namespaces,
      createdAt:   k.createdAt || '',
    };
  });
}

function adminAddApiKey(displayName, namespaces) {
  var user = getCurrentUserAuth_();
  if (!user || !user.isAdmin) throw new Error('管理者権限が必要です');
  if (!displayName) throw new Error('名前は必須です');
  var invalidNs = namespaces.filter(function(n) { return ALL_NAMESPACES.indexOf(n) === -1; });
  if (invalidNs.length) throw new Error('無効なnamespace: ' + invalidNs.join(','));

  var newKey = Utilities.getUuid().replace(/-/g, ''); // 32文字hex
  var keys = getApiKeysConfig_();
  keys.push({
    key:         newKey,
    displayName: displayName,
    namespaces:  namespaces,
    createdAt:   new Date().toISOString(),
  });
  saveApiKeysConfig_(keys);
  return newKey; // 平文キーは一度だけ返す
}

function adminRemoveApiKey(keyPreview) {
  var user = getCurrentUserAuth_();
  if (!user || !user.isAdmin) throw new Error('管理者権限が必要です');
  var keys = getApiKeysConfig_().filter(function(k) {
    return k.key.substring(0, 8) !== keyPreview.replace('...', '');
  });
  saveApiKeysConfig_(keys);
  return { ok: true };
}

// ─────────────────────────────────────────────
// Google Sheets ヘルパー
// ─────────────────────────────────────────────

function getSheet_() {
  var props    = getProps_();
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
  return {
    'Authorization':  'Bearer ' + getProps_().getProperty('NOTION_API_KEY'),
    'Notion-Version': '2022-06-28',
    'Content-Type':   'application/json',
  };
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
    meta_text:   parts.join('\n'),
    last_edited: page.last_edited_time || '',
  };
}

function chunkText_(text, size, overlap) {
  size    = size    || 350;
  overlap = overlap || 70;
  if (!text || text.length <= size) return text ? [text] : [];
  var chunks = [], start = 0;
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

function embed_(text, taskType) {
  var apiKey = getProps_().getProperty('GEMINI_API_KEY');
  var url    = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=' + apiKey;
  var payload = {
    model:                'models/gemini-embedding-001',
    content:              { parts: [{ text: text.substring(0, 2000) }] },
    outputDimensionality: 768,
  };
  if (taskType) payload.taskType = taskType;
  var res = UrlFetchApp.fetch(url, {
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify(payload), muteHttpExceptions: true,
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
  var props    = getProps_();
  var sheet    = getSheet_();
  var data     = sheet.getDataRange().getValues();
  var nHeaders = getNotionHeaders_();
  var embedUrl = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key='
                 + props.getProperty('GEMINI_API_KEY');

  var existingMap = {};
  for (var i = 1; i < data.length; i++) {
    var baseId = String(data[i][0]).split('::')[0];
    if (!existingMap[baseId]) existingMap[baseId] = { rowIndices: [], lastEdited: data[i][4] };
    existingMap[baseId].rowIndices.push(i + 1);
  }

  // Phase 1: 全DB並列取得
  var reqKeys = [], listReqs = [];
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

  // Phase 2: 更新対象特定 & 本文並列取得
  var rowsToDelete = [], updateList = [], totalSkip = 0;
  listResps.forEach(function(res, i) {
    var key = reqKeys[i];
    if (res.getResponseCode() !== 200) {
      Logger.log('[' + key + '] エラー: ' + res.getResponseCode()); return;
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
  if (updateList.length === 0) { invalidateIndexCache_(); return; }

  var bodyReqs = updateList.map(function(item) {
    return {
      url: 'https://api.notion.com/v1/blocks/' + item.pd.page_id + '/children?page_size=100',
      method: 'get', headers: nHeaders, muteHttpExceptions: true,
    };
  });
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

  var bodies = bodyResps.map(function(res, i) {
    if (res.getResponseCode() !== 200) return '';
    var d = JSON.parse(res.getContentText());
    var lines = extractLines_(d.results || []);
    if (!d.has_more) return lines.join('\n').substring(0, 8000);
    updateList[i].p2cursor = d.next_cursor;
    updateList[i].p1lines  = lines;
    return null;
  });

  var p2idx = [], p2reqs = [];
  updateList.forEach(function(item, i) {
    if (!item.p2cursor) return;
    p2idx.push(i);
    p2reqs.push({
      url: 'https://api.notion.com/v1/blocks/' + item.pd.page_id + '/children?page_size=100&start_cursor=' + item.p2cursor,
      method: 'get', headers: nHeaders, muteHttpExceptions: true,
    });
  });
  if (p2reqs.length > 0) {
    UrlFetchApp.fetchAll(p2reqs).forEach(function(res, j) {
      var idx   = p2idx[j];
      var extra = (res.getResponseCode() === 200)
        ? extractLines_(JSON.parse(res.getContentText()).results || []) : [];
      bodies[idx] = updateList[idx].p1lines.concat(extra).join('\n').substring(0, 8000);
    });
  }
  bodies = bodies.map(function(b) { return b === null ? '' : b; });

  // Phase 3: チャンク & Embedding
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

  var BATCH_SIZE = 10;
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
      if (res.getResponseCode() !== 200) { totalErr++; return; }
      var emb = JSON.parse(res.getContentText()).embedding.values;
      newRows.push([c.page_id + '::' + c.k, c.db, c.title, c.text, c.last_edited, JSON.stringify(emb)]);
      totalOk++;
    });
    if (b + BATCH_SIZE < allChunks.length) Utilities.sleep(200);
  }

  // Phase 4: シート更新
  rowsToDelete.sort(function(a, b) { return b - a; });
  rowsToDelete.forEach(function(ri) { sheet.deleteRow(ri); });
  if (newRows.length > 0)
    sheet.getRange(sheet.getLastRow() + 1, 1, newRows.length, 6).setValues(newRows);

  Logger.log('完了  チャンク:' + totalOk + '  スキップ:' + totalSkip + '  エラー:' + totalErr);
  invalidateIndexCache_();
}

// ─────────────────────────────────────────────
// インデックスキャッシュ
// ─────────────────────────────────────────────

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
  try { cache.putAll(entries, CACHE_TTL); } catch(e) {}
}

function invalidateIndexCache_() {
  CacheService.getScriptCache().remove(IDX_CACHE_KEY + '_n');
}

// ─────────────────────────────────────────────
// 検索
// ─────────────────────────────────────────────

function cosineSimilarity_(a, b) {
  var dot = 0, na = 0, nb = 0;
  for (var i = 0; i < a.length; i++) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
  var d = Math.sqrt(na) * Math.sqrt(nb);
  return d === 0 ? 0 : dot / d;
}

/**
 * @param {string[]} allowedNamespaces  null = 全NS許可
 */
function searchByEmbedding_(query, dbKey, limit, allowedNamespaces) {
  limit = limit || 5;
  var qv  = embedQuery_(query);
  if (!qv) return [];
  var idx = loadIndex_();
  if (!idx.length) return [];
  var results = [];
  idx.forEach(function(row) {
    // namespace フィルタ
    if (allowedNamespaces && allowedNamespaces.indexOf(row.db) === -1) return;
    // DB絞り込み
    if (dbKey && dbKey !== 'all' && row.db !== dbKey) return;
    results.push({ score: cosineSimilarity_(qv, row.emb), db: row.db, title: row.title, text: row.text });
  });
  results.sort(function(a, b) { return b.score - a.score; });
  return results.slice(0, limit);
}

// ─────────────────────────────────────────────
// Gemini テキスト生成
// ─────────────────────────────────────────────

function callGemini_(contents) {
  var apiKey = getProps_().getProperty('GEMINI_API_KEY');
  var url    = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=' + apiKey;
  var payload = JSON.stringify({
    system_instruction: { parts: [{ text:
      'あなたはゲーム開発チームの知識ベースを持つAIアシスタントです。\n' +
      '日本語で**簡潔に**回答してください（目安: 400文字以内）。\n' +
      '重要な点のみ箇条書き（-）または短い見出し（##）でまとめてください。\n' +
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
      Utilities.sleep(wait);
      continue;
    }
    return '（Gemini APIエラー: ' + code + '）';
  }
  return '（リトライ上限に達しました）';
}

// ─────────────────────────────────────────────
// RAG メイン
// ─────────────────────────────────────────────

/**
 * ブラウザ側 google.script.run から呼ぶ。
 * セッションユーザーの namespace を自動適用。
 */
function ragQuery(query, dbKey, history) {
  var user    = getCurrentUserAuth_();
  var allowed = user ? user.namespaces : [];
  return ragQueryInternal_(query, dbKey, history, allowed);
}

/**
 * 内部 RAG 処理。allowedNamespaces が空なら検索不可。
 */
function ragQueryInternal_(query, dbKey, history, allowedNamespaces) {
  history = history || [];
  if (!allowedNamespaces || allowedNamespaces.length === 0) {
    return { answer: 'アクセス可能なDBがありません。管理者に権限付与を依頼してください。', sources: [] };
  }

  // dbKey がアクセス許可外なら all に戻す
  if (dbKey && dbKey !== 'all' && allowedNamespaces.indexOf(dbKey) === -1) {
    dbKey = 'all';
  }

  var results = searchByEmbedding_(query, dbKey, 5, allowedNamespaces);
  var context = results.length === 0
    ? '（関連ドキュメントが見つかりませんでした）'
    : results.map(function(r, i) {
        return '### [' + (i+1) + '] ' + r.title + '（DB: ' + r.db + ' / 関連度: ' + (r.score*100).toFixed(1) + '%）\n' + r.text;
      }).join('\n\n');

  var contents = [
    { role: 'user',  parts: [{ text: '以下の参考ドキュメントを確認しました。\n\n' + context }] },
    { role: 'model', parts: [{ text: '参考ドキュメントを確認しました。ご質問にお答えします。' }] },
  ];
  history.slice(-6).forEach(function(h) {
    contents.push({ role: h.role === 'bot' ? 'model' : 'user', parts: [{ text: h.text }] });
  });
  contents.push({ role: 'user', parts: [{ text: query }] });

  var answer  = callGemini_(contents);
  var seen    = {}, sources = [];
  results.forEach(function(r) {
    var key = r.db + '::' + r.title;
    if (!seen[key]) { seen[key] = true; sources.push({ title: r.title, db: r.db, score: r.score }); }
  });
  return { answer: answer, sources: sources };
}

// ─────────────────────────────────────────────
// グラフデータ
// ─────────────────────────────────────────────

function getGraphData() {
  // ブラウザから呼ばれる場合はユーザーのnamespaceでフィルタ
  var user    = getCurrentUserAuth_();
  var allowed = user ? user.namespaces : null;
  return buildGraphData_(allowed);
}

function buildGraphData_(allowedNamespaces) {
  var GRAPH_CACHE_KEY = 'rag_graph_v1';
  var GRAPH_CACHE_TTL = 1800;
  var cache  = CacheService.getScriptCache();

  var sheet = getSheet_();
  var data  = sheet.getDataRange().getValues();
  var docs  = {};
  for (var i = 1; i < data.length; i++) {
    var row    = data[i];
    var cellId = String(row[0]);
    if (!row[5]) continue;
    if (cellId.split('::')[1] !== '0') continue;
    var db = String(row[1]);
    if (allowedNamespaces && allowedNamespaces.indexOf(db) === -1) continue;
    var baseId = cellId.split('::')[0];
    if (!docs[baseId]) {
      docs[baseId] = { id: baseId, label: String(row[2]), db: db, emb: JSON.parse(row[5]) };
    }
  }
  var docList = Object.values(docs);
  var edges   = [], seen = {};
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
        edges.push({ source: srcId, target: tgtId, score: Math.round(scores[k].score * 1000) / 1000 });
      }
    }
  }
  return {
    nodes:  docList.map(function(d) { return { id: d.id, label: d.label, db: d.db }; }),
    edges:  edges,
    status: 'ok',
  };
}

// ─────────────────────────────────────────────
// WebApp エントリポイント
// ─────────────────────────────────────────────

function doGet(e) {
  var user = getCurrentUserAuth_();
  if (!user) {
    var html = '<html><head><meta charset="UTF-8">' +
      '<style>body{font-family:sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;background:#0f1117;color:#e2e8f0;margin:0}' +
      'h2{color:#f87171;margin-bottom:8px}.sub{color:#64748b;font-size:.9rem;margin-top:4px}</style></head><body>' +
      '<h2>🔒 アクセスが拒否されました</h2>' +
      '<p class="sub">このRAGシステムへのアクセス権限がありません。</p>' +
      '<p class="sub">管理者に Google アカウントのメールアドレスを伝えて登録を依頼してください。</p>' +
      '</body></html>';
    return HtmlService.createHtmlOutput(html).setTitle('RAG — アクセス拒否');
  }
  return HtmlService.createHtmlOutput(getChatHtml_(user))
    .setTitle('RAG チャット')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function doPost(e) {
  try {
    var body    = JSON.parse(e.postData.contents);
    var query   = body.query;
    var dbKey   = body.dbKey   || 'all';
    var history = body.history || [];
    var apiKey  = body.apiKey  || '';

    if (!query) throw new Error('query は必須です');

    // API キー認証（Unity/Houdini 等の外部クライアント用）
    var keyConfig = validateApiKey_(apiKey);
    if (!keyConfig) {
      return ContentService.createTextOutput(JSON.stringify({
        answer: '認証エラー: 無効なAPIキーです', sources: [], status: 'auth_error',
      })).setMimeType(ContentService.MimeType.JSON);
    }

    var allowed = keyConfig.namespaces || [];
    if (dbKey !== 'all' && allowed.indexOf(dbKey) === -1) {
      return ContentService.createTextOutput(JSON.stringify({
        answer: 'アクセス権限がありません: ' + dbKey, sources: [], status: 'forbidden',
        allowedNamespaces: allowed,
      })).setMimeType(ContentService.MimeType.JSON);
    }

    var result = ragQueryInternal_(query, dbKey, history, allowed);
    return ContentService.createTextOutput(JSON.stringify({
      answer:           result.answer,
      sources:          result.sources,
      status:           'ok',
      allowedNamespaces: allowed,
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    Logger.log('doPost error: ' + err.message);
    return ContentService.createTextOutput(JSON.stringify({
      answer: 'エラー: ' + err.message, sources: [], status: 'error',
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

// ─────────────────────────────────────────────
// HTML 生成
// ─────────────────────────────────────────────

function getChatHtml_(user) {
  // DB ドロップダウン（ユーザーの allowed namespace のみ）
  var dbOpts = '<option value="all">🌐 全DB横断検索</option>\n';
  user.namespaces.forEach(function(ns) {
    var label = DB_LABELS[ns] || ns;
    dbOpts += '<option value="' + ns + '">' + label + '</option>\n';
  });

  // ユーザー情報を JS に埋め込む
  var userJson = JSON.stringify({
    email:       user.email,
    displayName: user.displayName,
    namespaces:  user.namespaces,
    isAdmin:     user.isAdmin,
  });

  // 管理タブ（管理者のみ表示）
  var adminTab    = user.isAdmin ? '<button class="tab-btn" id="admin-tab-btn" onclick="switchTab(\'admin\')">⚙ 管理</button>' : '';
  var adminPanel  = user.isAdmin ? getAdminPanelHtml_() : '';

  return [
'<!DOCTYPE html>',
'<html lang="ja">',
'<head>',
'<meta charset="UTF-8">',
'<meta name="viewport" content="width=device-width,initial-scale=1">',
'<title>RAG チャット</title>',
'<style>',
':root{--primary:#6366f1;--primary-dark:#4f46e5;--bg:#f1f5f9;--white:#fff;--text:#1e293b;--text-light:#64748b;--border:#e2e8f0;--user-grad:linear-gradient(135deg,#6366f1,#8b5cf6);--bot-bg:#f8fafc;--shadow:0 1px 4px rgba(0,0,0,.08);--dark:#0f1117;--dark2:#1a1d27;--dark3:#242838;--dborder:#2e3348;--accent:#6c8ef7;--accent2:#4ade80;--warn:#f87171}',
'*{box-sizing:border-box;margin:0;padding:0}',
'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);height:100vh;display:flex;flex-direction:column;max-width:900px;margin:0 auto}',
'header{background:var(--white);border-bottom:1px solid var(--border);padding:10px 16px;display:flex;align-items:center;gap:10px;box-shadow:var(--shadow);flex-shrink:0}',
'.hicon{width:36px;height:36px;background:var(--user-grad);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}',
'.htext{flex:1;min-width:0}.htext h1{font-size:15px;font-weight:700;color:var(--text)}.htext p{font-size:11px;color:var(--text-light)}',
'.user-badge{font-size:.75rem;padding:3px 9px;border-radius:99px;background:#ede9fe;color:#6d28d9;white-space:nowrap}',
'.tab-bar{display:flex;background:var(--white);border-bottom:1px solid var(--border);flex-shrink:0}',
'.tab-btn{flex:1;padding:9px 0;font-size:13px;font-weight:600;border:none;background:none;cursor:pointer;color:var(--text-light);border-bottom:2px solid transparent;font-family:inherit;transition:all .15s}',
'.tab-btn.active{color:var(--primary);border-bottom-color:var(--primary)}',
'.tab-btn:hover:not(.active){color:var(--text);background:#f8fafc}',
'#tab-chat{display:flex;flex-direction:column;flex:1;overflow:hidden}',
'#tab-graph{display:none;flex-direction:column;flex:1;overflow:hidden;background:#0f172a;color:#e2e8f0}',
'#tab-admin{display:none;flex:1;overflow-y:auto;background:var(--dark);color:#e2e8f0;padding:20px}',
'.dbwrap{padding:8px 14px;background:var(--white);border-bottom:1px solid var(--border);flex-shrink:0}',
'select{width:100%;padding:7px 11px;border:1px solid var(--border);border-radius:8px;font-size:13px;color:var(--text);background:var(--white);cursor:pointer;outline:none}',
'select:focus{border-color:var(--primary)}',
'#chat{flex:1;overflow-y:auto;padding:18px 14px;display:flex;flex-direction:column;gap:14px}',
'.welcome{text-align:center;padding:50px 20px;color:var(--text-light)}',
'.welcome-icon{font-size:48px;margin-bottom:12px}',
'.welcome h2{font-size:16px;color:var(--text);margin-bottom:7px;font-weight:700}',
'.welcome p{font-size:12px;line-height:1.6}',
'.msg{display:flex;gap:8px;max-width:90%}',
'.msg.user{align-self:flex-end;flex-direction:row-reverse}',
'.msg.bot{align-self:flex-start}',
'.av{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0;background:var(--bot-bg);border:1px solid var(--border);margin-top:2px}',
'.msg.user .av{background:var(--user-grad);border:none}',
'.bwrap{display:flex;flex-direction:column;gap:5px;min-width:0}',
'.bubble{padding:10px 14px;border-radius:16px;font-size:14px;line-height:1.75;word-break:break-word}',
'.msg.user .bubble{background:var(--user-grad);color:#fff;border-bottom-right-radius:4px}',
'.msg.bot .bubble{background:var(--white);color:var(--text);border-bottom-left-radius:4px;box-shadow:var(--shadow);border:1px solid var(--border)}',
'.msg.bot .bubble h1,.msg.bot .bubble h2,.msg.bot .bubble h3{font-size:14px;font-weight:700;margin:10px 0 4px}',
'.msg.bot .bubble p{margin-bottom:8px}.msg.bot .bubble p:last-child{margin-bottom:0}',
'.msg.bot .bubble ul,.msg.bot .bubble ol{padding-left:20px;margin-bottom:8px}',
'.msg.bot .bubble code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-family:monospace;font-size:12px;color:#6366f1}',
'.msg.bot .bubble pre{background:#1e293b;color:#e2e8f0;padding:12px;border-radius:10px;overflow-x:auto;margin:8px 0;font-size:12px}',
'.msg.bot .bubble pre code{background:none;color:inherit;padding:0}',
'.dots{display:flex;gap:5px;padding:6px 0}',
'.dots span{width:7px;height:7px;background:#94a3b8;border-radius:50%;animation:db 1.2s ease-in-out infinite}',
'.dots span:nth-child(2){animation-delay:.2s}.dots span:nth-child(3){animation-delay:.4s}',
'@keyframes db{0%,80%,100%{transform:scale(.7);opacity:.5}40%{transform:scale(1);opacity:1}}',
'.sources{margin-top:3px}',
'.src-toggle{font-size:11px;color:var(--text-light);cursor:pointer;display:inline-flex;align-items:center;gap:3px;background:none;border:none;padding:2px 0;font-family:inherit}',
'.src-toggle:hover{color:var(--primary)}',
'.src-list{display:none;margin-top:5px;background:var(--white);border:1px solid var(--border);border-radius:10px;overflow:hidden;box-shadow:var(--shadow)}',
'.src-list.open{display:block}',
'.src-item{padding:7px 11px;font-size:12px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}',
'.src-item:last-child{border-bottom:none}',
'.src-db{font-size:11px;background:#ede9fe;color:#6d28d9;padding:2px 7px;border-radius:10px;white-space:nowrap;flex-shrink:0}',
'.src-score{color:var(--text-light);margin-left:auto;font-size:11px;font-weight:600;white-space:nowrap}',
'.src-score.high{color:#16a34a}.src-score.mid{color:#d97706}.src-score.low{color:#94a3b8}',
'.input-area{padding:10px 14px;background:var(--white);border-top:1px solid var(--border);display:flex;gap:8px;align-items:flex-end;flex-shrink:0}',
'textarea{flex:1;padding:9px 13px;border:1.5px solid var(--border);border-radius:12px;font-size:14px;font-family:inherit;color:var(--text);resize:none;outline:none;max-height:120px;min-height:42px;line-height:1.6;transition:border-color .2s;background:var(--white)}',
'textarea:focus{border-color:var(--primary)}',
'#sbtn{width:42px;height:42px;background:var(--primary);color:#fff;border:none;border-radius:12px;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;transition:background .2s;flex-shrink:0}',
'#sbtn:hover{background:var(--primary-dark)}',
'#sbtn:disabled{background:#c7d2fe;cursor:not-allowed}',
'.graph-toolbar{padding:8px 14px;display:flex;align-items:center;gap:8px;border-bottom:1px solid #1e293b;flex-shrink:0}',
'.graph-toolbar button{padding:5px 14px;border:1px solid #334155;border-radius:8px;background:#1e293b;color:#e2e8f0;cursor:pointer;font-size:12px;font-family:inherit}',
'#graph-status{font-size:11px;color:#94a3b8;margin-left:4px}',
'#graph-svg{flex:1;width:100%;display:block}',
'#node-detail{padding:8px 14px;font-size:12px;color:#94a3b8;border-top:1px solid #1e293b;flex-shrink:0;min-height:36px}',
'/* 管理画面 */',
'.admin-section{background:var(--dark2);border:1px solid var(--dborder);border-radius:10px;padding:18px;margin-bottom:20px}',
'.admin-section h3{font-size:.95rem;font-weight:700;color:var(--accent);margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--dborder)}',
'.admin-table{width:100%;border-collapse:collapse;font-size:.82rem}',
'.admin-table th{padding:8px 12px;text-align:left;color:#64748b;border-bottom:1px solid var(--dborder);font-weight:500}',
'.admin-table td{padding:8px 12px;border-bottom:1px solid var(--dborder);vertical-align:top}',
'.admin-table tr:hover td{background:var(--dark3)}',
'.admin-input{background:var(--dark3);border:1px solid var(--dborder);border-radius:6px;color:#e2e8f0;padding:7px 10px;font-size:.82rem;width:100%;outline:none}',
'.admin-input:focus{border-color:var(--accent)}',
'.ns-check-wrap{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}',
'.ns-chk label{display:flex;align-items:center;gap:4px;font-size:.75rem;padding:3px 8px;border-radius:99px;border:1px solid var(--dborder);background:var(--dark3);cursor:pointer;color:#94a3b8}',
'.ns-chk input:checked + span{color:var(--accent2)}',
'.ns-chk label:has(input:checked){border-color:var(--accent2);background:#0d2018}',
'.btn-admin{padding:6px 14px;border:none;border-radius:6px;cursor:pointer;font-size:.8rem;font-weight:600;transition:opacity .15s}',
'.btn-admin:hover{opacity:.85}',
'.btn-primary{background:var(--accent);color:#fff}',
'.btn-danger{background:var(--warn);color:#fff}',
'.btn-sm{padding:3px 8px;font-size:.72rem}',
'.admin-flash{padding:8px 14px;border-radius:6px;font-size:.8rem;margin-bottom:10px;display:none}',
'.admin-flash.ok{background:#14532d;border:1px solid var(--accent2);color:var(--accent2)}',
'.admin-flash.err{background:#450a0a;border:1px solid var(--warn);color:var(--warn)}',
'.key-modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:100;align-items:center;justify-content:center}',
'.key-modal-overlay.show{display:flex}',
'.key-modal{background:var(--dark2);border:1px solid var(--dborder);border-radius:12px;padding:24px;max-width:480px;width:90%}',
'.key-box{background:var(--dark3);border:1px solid var(--accent);border-radius:6px;padding:12px;font-family:monospace;font-size:.85rem;word-break:break-all;color:var(--accent2);margin:12px 0}',
'</style>',
'</head>',
'<body>',
'<header>',
'  <div class="hicon">🔍</div>',
'  <div class="htext"><h1>RAG チャット</h1><p>Notion × Gemini ベクトル検索</p></div>',
'  <span class="user-badge">' + user.displayName + '</span>',
'</header>',
'<div class="tab-bar">',
'  <button class="tab-btn active" onclick="switchTab(\'chat\')">💬 チャット</button>',
'  <button class="tab-btn" onclick="switchTab(\'graph\')">🕸 グラフ</button>',
adminTab,
'</div>',
// チャットタブ
'<div id="tab-chat">',
'<div class="dbwrap"><select id="db">' + dbOpts + '</select></div>',
'<div id="chat">',
'  <div class="welcome">',
'    <div class="welcome-icon">🧠</div>',
'    <h2>何でも聞いてください</h2>',
'    <p>Notionの知識ベースをベクトル検索で参照し、Geminiが回答します<br>',
'    <span style="font-size:11px;opacity:.7">アクセス可能: ' + user.namespaces.join(' / ') + '</span></p>',
'  </div>',
'</div>',
'<div class="input-area">',
'  <textarea id="q" placeholder="質問を入力... (Ctrl+Enter で送信)" rows="1"></textarea>',
'  <button id="sbtn" onclick="send()">↑</button>',
'</div>',
'</div>',
// グラフタブ
'<div id="tab-graph">',
'  <div class="graph-toolbar">',
'    <button onclick="loadGraph()">更新</button>',
'    <button onclick="fitGraph()">全体</button>',
'    <span id="graph-status">「更新」を押してグラフを取得</span>',
'  </div>',
'  <svg id="graph-svg"></svg>',
'  <div id="node-detail">ノードをクリックして詳細を表示</div>',
'</div>',
// 管理タブ
'<div id="tab-admin">',
adminPanel,
'</div>',
// API キー表示モーダル
'<div class="key-modal-overlay" id="key-modal">',
'  <div class="key-modal">',
'    <h3 style="margin-bottom:8px">✅ API キー発行完了</h3>',
'    <p style="font-size:.8rem;color:#64748b">このキーは一度だけ表示されます。今すぐコピーしてください。</p>',
'    <div class="key-box" id="modal-key-text">—</div>',
'    <p style="font-size:.75rem;color:var(--warn);margin-bottom:14px">⚠ このダイアログを閉じると二度と確認できません</p>',
'    <div style="display:flex;gap:8px">',
'      <button class="btn-admin btn-primary" onclick="copyModalKey()">📋 コピー</button>',
'      <button class="btn-admin" style="background:var(--dark3)" onclick="closeKeyModal()">閉じる</button>',
'    </div>',
'  </div>',
'</div>',
'<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>',
'<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>',
'<script>',
'var __USER__ = ' + userJson + ';',
'if(typeof marked!=="undefined")marked.setOptions({breaks:true,gfm:true});',
'var chatHistory=[];',
'var ta=document.getElementById("q");',
'ta.addEventListener("input",function(){this.style.height="auto";this.style.height=Math.min(this.scrollHeight,120)+"px";});',
'ta.addEventListener("keydown",function(e){if((e.ctrlKey||e.metaKey)&&e.key==="Enter")send();});',
'function md(text){return(typeof marked!=="undefined")?marked.parse(text||""):text;}',
'function addMsg(role,content,sources){',
'  var chat=document.getElementById("chat");',
'  var welcome=chat.querySelector(".welcome");',
'  if(welcome)welcome.remove();',
'  var msg=document.createElement("div");msg.className="msg "+role;',
'  var av=document.createElement("div");av.className="av";',
'  av.textContent=role==="user"?"👤":"🤖";',
'  var wrap=document.createElement("div");wrap.className="bwrap";',
'  var bubble=document.createElement("div");bubble.className="bubble";',
'  if(role==="bot"&&content==="loading"){',
'    bubble.innerHTML=\'<div class="dots"><span></span><span></span><span></span></div>\';',
'  }else if(role==="bot"){',
'    bubble.innerHTML=md(content);',
'  }else{bubble.textContent=content;}',
'  wrap.appendChild(bubble);',
'  if(sources&&sources.length>0)wrap.appendChild(buildSources_(sources));',
'  msg.appendChild(av);msg.appendChild(wrap);',
'  chat.appendChild(msg);chat.scrollTop=chat.scrollHeight;',
'  return{bubble:bubble,wrap:wrap};',
'}',
'function buildSources_(sources){',
'  var div=document.createElement("div");div.className="sources";',
'  var btn=document.createElement("button");btn.className="src-toggle";',
'  btn.innerHTML="📎 参考情報 "+sources.length+"件 ▾";',
'  var list=document.createElement("div");list.className="src-list";',
'  sources.forEach(function(s,i){',
'    var pct=(s.score*100).toFixed(1);',
'    var cls=s.score>=0.75?"high":s.score>=0.5?"mid":"low";',
'    var item=document.createElement("div");item.className="src-item";',
'    item.innerHTML=(i+1)+". "+s.title+\'<span class="src-db">\'+s.db+\'</span><span class="src-score \'+cls+\'">\'+ pct+\'%</span>\';',
'    list.appendChild(item);',
'  });',
'  btn.onclick=function(){list.classList.toggle("open");btn.innerHTML="📎 参考情報 "+sources.length+"件 "+(list.classList.contains("open")?"▴":"▾");};',
'  div.appendChild(btn);div.appendChild(list);',
'  return div;',
'}',
'var isSending=false;',
'function send(){',
'  if(isSending)return;',
'  var q=ta.value.trim();',
'  var dbKey=document.getElementById("db").value;',
'  if(!q)return;',
'  ta.value="";ta.style.height="auto";',
'  isSending=true;document.getElementById("sbtn").disabled=true;',
'  addMsg("user",q);',
'  var bot=addMsg("bot","loading");',
'  var snap=chatHistory.slice();',
'  google.script.run',
'    .withSuccessHandler(function(result){',
'      isSending=false;document.getElementById("sbtn").disabled=false;',
'      var answer=result.answer||"";',
'      bot.bubble.innerHTML=md(answer);',
'      if(result.sources&&result.sources.length>0)bot.wrap.appendChild(buildSources_(result.sources));',
'      chatHistory.push({role:"user",text:q});',
'      chatHistory.push({role:"bot", text:answer});',
'      document.getElementById("chat").scrollTop=99999;',
'    })',
'    .withFailureHandler(function(err){',
'      isSending=false;document.getElementById("sbtn").disabled=false;',
'      bot.bubble.textContent="エラー: "+(err.message||"Unknown error");',
'    })',
'    .ragQuery(q,dbKey,snap);',
'}',
'// タブ切り替え',
'function switchTab(tab){',
'  ["chat","graph","admin"].forEach(function(t){',
'    var el=document.getElementById("tab-"+t);',
'    if(el)el.style.display=(t===tab?(t==="chat"?"flex":"flex"):"none");',
'  });',
'  document.querySelectorAll(".tab-btn").forEach(function(b){',
'    b.classList.remove("active");',
'    if((tab==="chat"&&b.textContent.includes("チャット"))||(tab==="graph"&&b.textContent.includes("グラフ"))||(tab==="admin"&&b.textContent.includes("管理")))b.classList.add("active");',
'  });',
'  if(tab==="graph"&&!window._graphLoaded)loadGraph();',
'  if(tab==="admin")loadAdminData();',
'}',
'// グラフ',
'var _graphSim=null,_graphLoaded=false;',
'var DB_COLORS={tool_docs:"#6366f1",game_info:"#10b981",research:"#f59e0b",team_notes:"#ef4444",afuri:"#f97316",braintq:"#8b5cf6",fourteen:"#06b6d4"};',
'function loadGraph(){',
'  var status=document.getElementById("graph-status");',
'  status.textContent="グラフデータ取得中...";',
'  google.script.run',
'    .withSuccessHandler(function(data){',
'      if(!data||!data.nodes){status.textContent="データが空です";return;}',
'      renderGraph(data);_graphLoaded=true;',
'    })',
'    .withFailureHandler(function(err){status.textContent="エラー: "+(err.message||String(err));;})',
'    .getGraphData();',
'}',
'function fitGraph(){if(_graphSim&&window._d3zoom)window._d3svg&&window._d3svg.transition().call(window._d3zoom.transform,d3.zoomIdentity);}',
'function renderGraph(data){',
'  if(_graphSim)_graphSim.stop();',
'  var svgEl=document.getElementById("graph-svg");',
'  var w=svgEl.clientWidth||600,h=svgEl.clientHeight||400;',
'  var svg=d3.select("#graph-svg").attr("width",w).attr("height",h);',
'  svg.selectAll("*").remove();window._d3svg=svg;',
'  var g=svg.append("g");',
'  var zoom=d3.zoom().scaleExtent([0.1,6]).on("zoom",function(ev){g.attr("transform",ev.transform);});',
'  svg.call(zoom);window._d3zoom=zoom;',
'  var nodes=data.nodes.map(function(d){return Object.assign({},d);});',
'  var links=data.edges.map(function(e){return{source:e.source,target:e.target,score:e.score};});',
'  var link=g.append("g").selectAll("line").data(links).enter().append("line")',
'    .attr("stroke","#475569").attr("stroke-opacity",function(d){return 0.3+d.score*0.5;}).attr("stroke-width",1.5);',
'  var node=g.append("g").selectAll("g").data(nodes).enter().append("g")',
'    .call(d3.drag().on("start",function(ev,d){if(!ev.active)_graphSim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y;})',
'                   .on("drag",function(ev,d){d.fx=ev.x;d.fy=ev.y;})',
'                   .on("end",function(ev,d){if(!ev.active)_graphSim.alphaTarget(0);d.fx=null;d.fy=null;}))',
'    .on("click",function(ev,d){document.getElementById("node-detail").textContent=d.label+" | "+d.db;});',
'  node.append("circle").attr("r",12)',
'    .attr("fill",function(d){return DB_COLORS[d.db]||"#64748b";})',
'    .attr("stroke","#0f172a").attr("stroke-width",1.5)',
'    .on("mouseover",function(){d3.select(this).attr("r",16).attr("stroke","#fbbf24");})',
'    .on("mouseout",function(){d3.select(this).attr("r",12).attr("stroke","#0f172a");});',
'  node.append("text").text(function(d){return d.label.length>12?d.label.slice(0,12)+"…":d.label;})',
'    .attr("x",15).attr("y",4).attr("font-size","10px").attr("fill","#cbd5e1");',
'  _graphSim=d3.forceSimulation(nodes)',
'    .force("link",d3.forceLink(links).id(function(d){return d.id;}).distance(80).strength(function(d){return d.score;}))',
'    .force("charge",d3.forceManyBody().strength(-200))',
'    .force("center",d3.forceCenter(w/2,h/2))',
'    .force("collision",d3.forceCollide(18))',
'    .on("tick",function(){',
'      link.attr("x1",function(d){return d.source.x;}).attr("y1",function(d){return d.source.y;})',
'          .attr("x2",function(d){return d.target.x;}).attr("y2",function(d){return d.target.y;});',
'      node.attr("transform",function(d){return "translate("+d.x+","+d.y+")";});',
'    });',
'  document.getElementById("graph-status").textContent=nodes.length+"ノード / "+links.length+"エッジ";',
'}',
// 管理画面JS
'var _adminLoaded=false;',
'function loadAdminData(){',
'  if(!__USER__.isAdmin)return;',
'  loadAdminUsers();loadAdminKeys();',
'}',
'function loadAdminUsers(){',
'  google.script.run',
'    .withSuccessHandler(function(users){',
'      var tbody=document.getElementById("user-tbody");tbody.innerHTML="";',
'      (users||[]).forEach(function(u){',
'        var tr=document.createElement("tr");',
'        var ns=u.namespaces.join(", ")||"(なし)";',
'        tr.innerHTML=\'<td>\'+u.email+\'</td><td>\'+u.displayName+\'</td><td style="font-size:.75rem;color:#94a3b8">\'+ns+\'</td>\'+',
'          \'<td><button class="btn-admin btn-danger btn-sm" onclick="removeUser(\\\'\'+u.email+\'\\\')">\'+',
'          \'削除</button></td>\';',
'        tbody.appendChild(tr);',
'      });',
'    })',
'    .withFailureHandler(function(e){adminFlash("ユーザー取得失敗: "+e.message,true);})',
'    .adminGetUsers();',
'}',
'function loadAdminKeys(){',
'  google.script.run',
'    .withSuccessHandler(function(keys){',
'      var tbody=document.getElementById("key-tbody");tbody.innerHTML="";',
'      (keys||[]).forEach(function(k){',
'        var tr=document.createElement("tr");',
'        var ns=k.namespaces.join(", ")||"(なし)";',
'        tr.innerHTML=\'<td style="font-family:monospace">\'+k.keyPreview+\'</td><td>\'+k.displayName+\'</td>\'+',
'          \'<td style="font-size:.75rem;color:#94a3b8">\'+ns+\'</td>\'+',
'          \'<td><button class="btn-admin btn-danger btn-sm" onclick="removeApiKey(\\\'\'+k.keyPreview+\'\\\')">\'+',
'          \'削除</button></td>\';',
'        tbody.appendChild(tr);',
'      });',
'    })',
'    .withFailureHandler(function(e){adminFlash("キー取得失敗: "+e.message,true);})',
'    .adminGetApiKeys();',
'}',
'function addUser(){',
'  var email=document.getElementById("new-user-email").value.trim();',
'  var name=document.getElementById("new-user-name").value.trim();',
'  var ns=getCheckedNs("new-user-ns");',
'  if(!email){adminFlash("メールを入力してください",true);return;}',
'  google.script.run',
'    .withSuccessHandler(function(){adminFlash("ユーザーを追加しました");loadAdminUsers();document.getElementById("new-user-email").value="";document.getElementById("new-user-name").value="";})',
'    .withFailureHandler(function(e){adminFlash(e.message,true);})',
'    .adminUpsertUser(email,name||email,ns);',
'}',
'function removeUser(email){',
'  if(!confirm(email+" を削除しますか？"))return;',
'  google.script.run',
'    .withSuccessHandler(function(){adminFlash("削除しました");loadAdminUsers();})',
'    .withFailureHandler(function(e){adminFlash(e.message,true);})',
'    .adminRemoveUser(email);',
'}',
'function addApiKey(){',
'  var name=document.getElementById("new-key-name").value.trim();',
'  var ns=getCheckedNs("new-key-ns");',
'  if(!name){adminFlash("名前を入力してください",true);return;}',
'  google.script.run',
'    .withSuccessHandler(function(newKey){',
'      document.getElementById("modal-key-text").textContent=newKey;',
'      document.getElementById("key-modal").classList.add("show");',
'      document.getElementById("new-key-name").value="";',
'      loadAdminKeys();',
'    })',
'    .withFailureHandler(function(e){adminFlash(e.message,true);})',
'    .adminAddApiKey(name,ns);',
'}',
'function removeApiKey(preview){',
'  if(!confirm("このAPIキーを削除しますか？"))return;',
'  google.script.run',
'    .withSuccessHandler(function(){adminFlash("削除しました");loadAdminKeys();})',
'    .withFailureHandler(function(e){adminFlash(e.message,true);})',
'    .adminRemoveApiKey(preview);',
'}',
'function getCheckedNs(containerId){',
'  return Array.from(document.querySelectorAll("#"+containerId+" input:checked")).map(function(i){return i.value;});',
'}',
'function copyModalKey(){',
'  var key=document.getElementById("modal-key-text").textContent;',
'  navigator.clipboard.writeText(key).then(function(){adminFlash("コピーしました");});',
'}',
'function closeKeyModal(){document.getElementById("key-modal").classList.remove("show");}',
'function adminFlash(msg,isErr){',
'  var el=document.getElementById("admin-flash");',
'  el.textContent=msg;el.className="admin-flash "+(isErr?"err":"ok");el.style.display="block";',
'  setTimeout(function(){el.style.display="none";},3000);',
'}',
'</script>',
'</body></html>',
  ].join('\n');
}

/**
 * 管理パネルのHTML（isAdmin のときのみ挿入）
 */
function getAdminPanelHtml_() {
  var nsCheckboxes = function(containerId) {
    return ALL_NAMESPACES.map(function(ns) {
      return '<span class="ns-chk"><label><input type="checkbox" value="' + ns + '" id="' + containerId + '-' + ns + '"><span>' + ns + '</span></label></span>';
    }).join('');
  };

  return [
'<div id="admin-flash" class="admin-flash"></div>',
'<!-- ユーザー管理 -->',
'<div class="admin-section">',
'  <h3>ユーザー管理（Googleアカウント）</h3>',
'  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">',
'    <div><label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">メールアドレス</label>',
'    <input class="admin-input" id="new-user-email" type="email" placeholder="user@gmail.com"></div>',
'    <div><label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">表示名</label>',
'    <input class="admin-input" id="new-user-name" type="text" placeholder="Alice"></div>',
'  </div>',
'  <div style="margin-bottom:10px"><label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">アクセス可能な Namespace</label>',
'  <div class="ns-check-wrap" id="new-user-ns">' + nsCheckboxes('user') + '</div></div>',
'  <button class="btn-admin btn-primary" onclick="addUser()">追加 / 更新</button>',
'  <table class="admin-table" style="margin-top:16px">',
'    <thead><tr><th>メール</th><th>表示名</th><th>Namespace</th><th></th></tr></thead>',
'    <tbody id="user-tbody"><tr><td colspan="4" style="color:#64748b;padding:12px">読み込み中...</td></tr></tbody>',
'  </table>',
'</div>',
'<!-- APIキー管理 -->',
'<div class="admin-section">',
'  <h3>API キー管理（Unity / Houdini 等の外部クライアント用）</h3>',
'  <div style="display:grid;grid-template-columns:1fr;gap:10px;margin-bottom:12px">',
'    <div><label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">クライアント名</label>',
'    <input class="admin-input" id="new-key-name" type="text" placeholder="Unity Client"></div>',
'  </div>',
'  <div style="margin-bottom:10px"><label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">アクセス可能な Namespace</label>',
'  <div class="ns-check-wrap" id="new-key-ns">' + nsCheckboxes('key') + '</div></div>',
'  <button class="btn-admin btn-primary" onclick="addApiKey()">APIキーを発行</button>',
'  <table class="admin-table" style="margin-top:16px">',
'    <thead><tr><th>キー（先頭8文字）</th><th>名前</th><th>Namespace</th><th></th></tr></thead>',
'    <tbody id="key-tbody"><tr><td colspan="4" style="color:#64748b;padding:12px">読み込み中...</td></tr></tbody>',
'  </table>',
'  <p style="font-size:.75rem;color:#64748b;margin-top:10px">',
'  Unity/Houdini から使う場合は POST /exec に <code>{"query":"...","apiKey":"YOUR_KEY"}</code> を送信してください。</p>',
'</div>',
  ].join('\n');
}

// ─────────────────────────────────────────────
// デバッグ用（GASエディタから実行）
// ─────────────────────────────────────────────

function testEmbedding() {
  var vec = embed_('テスト');
  if (vec) {
    Logger.log('✅ OK  次元数: ' + vec.length + '  先頭3値: ' + vec.slice(0, 3));
  } else {
    Logger.log('❌ NG');
  }
}

function testSearch() {
  var results = searchByEmbedding_('柚子塩らーめんの店舗はどこ？', 'afuri', 3, null);
  results.forEach(function(r) {
    Logger.log('[' + (r.score*100).toFixed(1) + '%] ' + r.title + ' (' + r.db + ')');
  });
}

function testRagQuery() {
  var result = ragQueryInternal_('AFURIについて教えてください', 'afuri', [], ALL_NAMESPACES);
  Logger.log('=== 回答 ===\n' + result.answer);
}
