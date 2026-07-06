/**
 * Cloud RAG Chatbot — Google Apps Script  v4 (APIキー認証統一版)
 *
 * ── スクリプトプロパティ ──────────────────────────────────────────────
 *   NOTION_API_KEY     Notion Integration Token（Notionソースを使う namespace がある場合のみ必須）
 *   GEMINI_API_KEY     Google AI Studio API Key
 *   SHEETS_ID          ベクトル保存用スプレッドシートID
 *
 *   DB_TOOL_DOCS / DB_GAME_INFO / DB_RESEARCH / DB_TEAM_NOTES
 *   DB_AFURI / DB_BRAINTQ / DB_FOURTEEN / DB_HOUDINI21  (各Notion DB ID)
 *
 *   DRIVE_TOOL_DOCS / DRIVE_GAME_INFO / DRIVE_RESEARCH / DRIVE_TEAM_NOTES
 *   DRIVE_AFURI / DRIVE_BRAINTQ / DRIVE_FOURTEEN / DRIVE_HOUDINI21
 *     ← Notionの代わりに Google Drive フォルダで管理したい namespace について設定する
 *       （Driveの共有フォルダID。DB_* とDRIVE_*が両方設定されている場合はNotionを優先）
 *       フォルダ内の Markdown(.md/.txt) / Google ドキュメントが同期対象。
 *       frontmatter（--- title/summary/tags/source_url ---）を解析してNotionと同じ形式で扱う。
 *
 *   API_KEYS_CONFIG    ← 自動管理（管理画面で操作）
 *
 * ── 初回セットアップ ─────────────────────────────────────────────────
 *   1. 上記スクリプトプロパティを設定
 *   2. GASエディタで bootstrapFirstAdminKey() を実行
 *      → ログに管理者APIキーが表示される（一度だけ）
 *   3. WebAppをデプロイ:
 *        次のユーザーとして実行: 自分 (Me)
 *        アクセスできるユーザー: Googleアカウントを持つ全員
 *   4. WebAppのURLにブラウザでアクセスし、管理者キーでログイン
 *   5. 管理タブからユーザーキー / クライアントキーを発行
 * ────────────────────────────────────────────────────────────────────
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
  houdini21:  'DB_HOUDINI21',
};

// Notion の代替ソース。DB_KEY_MAP側（Notion database_id）が未設定の namespace について、
// こちらのスクリプトプロパティ（Googleドライブの共有フォルダID）が設定されていれば
// Driveフォルダ内の Markdown / Google ドキュメントを同期対象にする。
var DRIVE_KEY_MAP = {
  tool_docs:  'DRIVE_TOOL_DOCS',
  game_info:  'DRIVE_GAME_INFO',
  research:   'DRIVE_RESEARCH',
  team_notes: 'DRIVE_TEAM_NOTES',
  afuri:      'DRIVE_AFURI',
  braintq:    'DRIVE_BRAINTQ',
  fourteen:   'DRIVE_FOURTEEN',
  houdini21:  'DRIVE_HOUDINI21',
};

var DB_LABELS = {
  tool_docs:  '🛠️ Tool Docs',
  game_info:  '🎮 Game Info',
  research:   '📄 Research',
  team_notes: '📝 Team Notes',
  afuri:      '🍜 AFURI',
  braintq:    '🧠 BrainTQ',
  fourteen:   '⛳ Fourteen',
  houdini21:  '🌀 Houdini21',
};

var ALL_NAMESPACES   = Object.keys(DB_KEY_MAP);
var SHEET_NAME       = 'RAG_Index';
var MEMORY_SHEET     = 'RAG_Memory';
var IDX_CACHE_KEY    = 'rag_idx_v2';
var CACHE_TTL        = 21600;
var CACHE_CHUNK      = 90000;

// 許可された DB キーの一覧。不正値は "all" にフォールバックして安全に処理する。
var VALID_DB_KEYS_ = ["all","tool_docs","game_info","research","team_notes","afuri","braintq","fourteen","houdini21"];

/** dbKey が有効かチェックし、不正なら "all" を返す */
function sanitizeDbKey_(dbKey) {
  if (!dbKey || VALID_DB_KEYS_.indexOf(dbKey) === -1) return "all";
  return dbKey;
}

// ─────────────────────────────────────────────
// ストレージヘルパー
// ─────────────────────────────────────────────

function getProps_() {
  return PropertiesService.getScriptProperties();
}

function getApiKeysConfig_() {
  var raw = getProps_().getProperty('API_KEYS_CONFIG') || '[]';
  try { return JSON.parse(raw); } catch(e) { return []; }
}

function saveApiKeysConfig_(keys) {
  getProps_().setProperty('API_KEYS_CONFIG', JSON.stringify(keys));
}

// ─────────────────────────────────────────────
// 認証ヘルパー
// ─────────────────────────────────────────────

function validateApiKey_(key) {
  if (!key) return null;
  var keys = getApiKeysConfig_();
  for (var i = 0; i < keys.length; i++) {
    if (keys[i].key === key) return keys[i];
  }
  return null;
}

function requireAdmin_(apiKey) {
  var config = validateApiKey_(apiKey);
  if (!config)          throw new Error('認証エラー: 無効なAPIキーです');
  if (!config.isAdmin)  throw new Error('管理者権限が必要です');
  return config;
}

// ─────────────────────────────────────────────
// google.script.run から呼ぶ公開関数
// ─────────────────────────────────────────────

/** APIキーを検証してユーザー情報を返す（ログイン時に呼ぶ） */
function getNamespacesForKey(apiKey) {
  var config = validateApiKey_(apiKey);
  if (!config) return null;
  return {
    displayName: config.displayName || 'ユーザー',
    namespaces:  config.namespaces  || [],
    isAdmin:     config.isAdmin     || false,
  };
}

/** チャットクエリ（ブラウザ用） */
function ragQueryWithKey(query, dbKey, history, apiKey) {
  var config = validateApiKey_(apiKey);
  if (!config) throw new Error('認証エラー: 無効なAPIキーです');
  var result = ragQueryInternal_(query, dbKey, history, config.namespaces || [], apiKey);
  try { result.memoryId = saveMemory_(apiKey, query, result.answer, result.sources); } catch(e) {}
  return result;
}

/** 履歴取得（ブラウザ用） */
function getUserMemory(apiKey, limit) {
  var config = validateApiKey_(apiKey);
  if (!config) throw new Error('認証エラー: 無効なAPIキーです');
  limit = limit || 30;
  try {
    var sheet = getMemorySheet_();
    if (!sheet) return { records: [] };
    var prefix = apiKey.substring(0, 8);
    var data   = sheet.getDataRange().getValues();
    var records = [];
    for (var i = data.length - 1; i >= 1 && records.length < limit; i--) {
      if (String(data[i][1]) !== prefix) continue;
      records.push({
        id:        String(data[i][0]),
        timestamp: String(data[i][2]),
        query:     String(data[i][3]),
        answer:    String(data[i][4]),
        sources:   data[i][5] ? JSON.parse(data[i][5]) : [],
        rating:    String(data[i][6]),
      });
    }
    return { records: records };
  } catch(e) {
    return { records: [], error: e.message };
  }
}

/** 評価保存（ブラウザ用） */
function rateMemoryEntry(apiKey, id, rating) {
  var config = validateApiKey_(apiKey);
  if (!config) throw new Error('認証エラー: 無効なAPIキーです');
  try {
    var sheet  = getMemorySheet_();
    if (!sheet) return { ok: false };
    var prefix = apiKey.substring(0, 8);
    var data   = sheet.getDataRange().getValues();
    for (var i = data.length - 1; i >= 1; i--) {
      if (String(data[i][0]) === id && String(data[i][1]) === prefix) {
        sheet.getRange(i + 1, 7).setValue(rating);
        // 評価に基づいて priority を更新 (👍=1.0, 👎=0.0)
        var priority = (rating === 'up') ? 1.0 : 0.0;
        sheet.getRange(i + 1, 8).setValue(priority);
        return { ok: true };
      }
    }
    return { ok: false };
  } catch(e) {
    return { ok: false, error: e.message };
  }
}

/** グラフデータ（ブラウザ用） */
function getGraphDataWithKey(apiKey) {
  var config = validateApiKey_(apiKey);
  if (!config) throw new Error('認証エラー: 無効なAPIキーです');
  return buildGraphData_(config.namespaces || null);
}

/** キー一覧（管理者のみ） */
function adminListKeys(apiKey) {
  requireAdmin_(apiKey);
  return getApiKeysConfig_().map(function(k) {
    return {
      keyPreview:  k.key.substring(0, 8) + '...',
      displayName: k.displayName || '',
      namespaces:  k.namespaces  || [],
      isAdmin:     k.isAdmin     || false,
      createdAt:   k.createdAt   || '',
    };
  });
}

/** キー発行（管理者のみ） — 新しいキーを平文で一度だけ返す */
function adminCreateKey(apiKey, displayName, namespaces, isAdmin) {
  requireAdmin_(apiKey);
  if (!displayName) throw new Error('名前は必須です');
  var invalidNs = (namespaces || []).filter(function(n) { return ALL_NAMESPACES.indexOf(n) === -1; });
  if (invalidNs.length) throw new Error('無効なnamespace: ' + invalidNs.join(', '));

  var newKey = Utilities.getUuid().replace(/-/g, ''); // 32文字hex
  var keys   = getApiKeysConfig_();
  keys.push({
    key:         newKey,
    displayName: displayName,
    namespaces:  namespaces  || [],
    isAdmin:     isAdmin     || false,
    createdAt:   new Date().toISOString(),
  });
  saveApiKeysConfig_(keys);
  return newKey;
}

/** キー削除（管理者のみ） */
function adminDeleteKey(apiKey, keyPreview) {
  requireAdmin_(apiKey);
  var prefix = keyPreview.replace('...', '');
  var keys   = getApiKeysConfig_().filter(function(k) {
    return k.key.substring(0, 8) !== prefix;
  });
  saveApiKeysConfig_(keys);
  return { ok: true };
}

/** キーのnamespace更新（管理者のみ） */
function adminUpdateKey(apiKey, keyPreview, newNamespaces) {
  requireAdmin_(apiKey);
  var invalidNs = (newNamespaces || []).filter(function(n) { return ALL_NAMESPACES.indexOf(n) === -1; });
  if (invalidNs.length) throw new Error('無効なnamespace: ' + invalidNs.join(', '));
  var prefix = keyPreview.replace('...', '');
  var keys   = getApiKeysConfig_();
  var found  = false;
  keys.forEach(function(k) {
    if (k.key.substring(0, 8) === prefix) { k.namespaces = newNamespaces; found = true; }
  });
  if (!found) throw new Error('キーが見つかりません: ' + keyPreview);
  saveApiKeysConfig_(keys);
  return { ok: true };
}

// ─────────────────────────────────────────────
// ナレッジ管理（管理タブ「📚 ナレッジ管理」用）
// ─────────────────────────────────────────────
//
// FAQ手入力・Q&A CSV一括インポート・ファイルアップロード(Word/Excel/PPT/PDF/画像)の
// 3経路でRAG_Indexに知識を追加する。IT知識がない担当者でもブラウザだけで完結するよう、
// 変換・チャンク分割・埋め込み生成はすべてサーバー側（GAS）で行う。
//
// ファイルアップロードには Advanced Drive Service が必要:
//   GASエディタ →「サービス」(+ボタン) →「Drive API」を追加
//   （docs/cloud-rag.md §5.4 参照）

var KNOWLEDGE_LOG_SHEET = 'RAG_KnowledgeLog';

/** ナレッジ変更履歴シートを取得（未作成なら作成しヘッダーを書く） */
function getKnowledgeLogSheet_() {
  var ss    = SpreadsheetApp.openById(getProps_().getProperty('SHEETS_ID'));
  var sheet = ss.getSheetByName(KNOWLEDGE_LOG_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(KNOWLEDGE_LOG_SHEET);
    sheet.appendRow(['timestamp', 'type', 'db', 'label', 'chunkCount', 'pageIds']);
  }
  return sheet;
}

/**
 * ナレッジ登録の履歴を1件記録する。pageIdsを残しておくことで、
 * 将来的に「直前の登録をロールバック（該当page_idの行を削除）」を実装しやすくする。
 */
function logKnowledgeChange_(type, dbKey, label, chunkCount, pageIds) {
  try {
    getKnowledgeLogSheet_().appendRow([
      new Date().toISOString(), type, dbKey, label, chunkCount, JSON.stringify(pageIds || []),
    ]);
  } catch (e) {
    Logger.log('ナレッジ履歴の記録に失敗: ' + e.message);
  }
}

/** テキストをチャンク分割→Gemini埋め込み生成→RAG_Indexへ追記する共通処理 */
function writeKnowledgeChunks_(pageId, dbKey, title, fullText) {
  var props    = getProps_();
  var sheet    = getSheet_();
  var embedUrl = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=' + props.getProperty('GEMINI_API_KEY');
  var chunks   = chunkText_(fullText, 500, 100);
  if (chunks.length === 0) return 0;

  var lastEdited = new Date().toISOString();
  var newRows = [];
  var BATCH_SIZE = 10;
  for (var b = 0; b < chunks.length; b += BATCH_SIZE) {
    var batch     = chunks.slice(b, b + BATCH_SIZE);
    var embedReqs = batch.map(function(c) {
      return { url: embedUrl, method: 'post', contentType: 'application/json',
        payload: JSON.stringify({ model: 'models/gemini-embedding-001', content: { parts: [{ text: c.substring(0, 2000) }] }, outputDimensionality: 768, taskType: 'RETRIEVAL_DOCUMENT' }),
        muteHttpExceptions: true };
    });
    UrlFetchApp.fetchAll(embedReqs).forEach(function(res, j) {
      if (res.getResponseCode() !== 200) return;
      var emb = JSON.parse(res.getContentText()).embedding.values;
      var k   = b + j;
      newRows.push([pageId + '::' + k, dbKey, title, batch[j], lastEdited, JSON.stringify(emb)]);
    });
    if (b + BATCH_SIZE < chunks.length) Utilities.sleep(200);
  }
  if (newRows.length > 0) sheet.getRange(sheet.getLastRow() + 1, 1, newRows.length, 6).setValues(newRows);
  invalidateIndexCache_();
  return newRows.length;
}

/** 簡易CSVパーサー（ダブルクォート内のカンマ・改行に対応。外部ライブラリ不使用） */
function parseCsv_(text) {
  var rows = [], row = [], field = '', inQuotes = false;
  for (var i = 0; i < text.length; i++) {
    var c = text.charAt(i);
    if (inQuotes) {
      if (c === '"') {
        if (text.charAt(i + 1) === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else {
      if (c === '"') inQuotes = true;
      else if (c === ',') { row.push(field); field = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text.charAt(i + 1) === '\n') i++;
        row.push(field); field = '';
        if (!(row.length === 1 && row[0] === '')) rows.push(row);
        row = [];
      } else field += c;
    }
  }
  if (field !== '' || row.length > 0) { row.push(field); rows.push(row); }
  return rows;
}

/**
 * アップロードされたファイル（base64）からテキストを抽出する。
 * .md/.txtはそのまま読み込み、それ以外（Word/Excel/PPT/PDF/画像）は
 * Advanced Drive Service で Google形式へ変換（画像・PDFはOCR）してから抽出する。
 */
function extractTextFromUpload_(base64Data, fileName, mimeType) {
  var blob = Utilities.newBlob(Utilities.base64Decode(base64Data), mimeType, fileName);

  if (mimeType === 'text/plain' || mimeType === 'text/markdown' || /\.(md|txt)$/i.test(fileName)) {
    return blob.getDataAsString('UTF-8');
  }

  if (typeof Drive === 'undefined') {
    throw new Error('この形式の変換には Advanced Drive Service が必要です。GASエディタの「サービス」から Drive API を追加してください（docs/cloud-rag.md §5.4 参照）');
  }

  var converted = Drive.Files.insert(
    { title: fileName, mimeType: mimeType },
    blob,
    { convert: true, ocr: true, ocrLanguage: 'ja' }
  );

  var text = '';
  try {
    if (converted.mimeType === 'application/vnd.google-apps.document') {
      text = DocumentApp.openById(converted.id).getBody().getText();
    } else if (converted.mimeType === 'application/vnd.google-apps.spreadsheet') {
      text = SpreadsheetApp.openById(converted.id).getSheets().map(function(sh) {
        return sh.getDataRange().getValues().map(function(row) { return row.join('\t'); }).join('\n');
      }).join('\n\n');
    } else if (converted.mimeType === 'application/vnd.google-apps.presentation') {
      text = SlidesApp.openById(converted.id).getSlides().map(function(slide) {
        return slide.getShapes().map(function(shape) {
          try { return shape.getText().asString(); } catch (e) { return ''; }
        }).join('\n');
      }).join('\n\n');
    }
  } finally {
    try { Drive.Files.remove(converted.id); } catch (e) { /* 変換用一時ファイルの削除失敗は無視 */ }
  }
  return text;
}

/** FAQ手入力（管理者のみ）。1件のQ&AをRAG_Indexに追加する */
function adminAddFaq(apiKey, dbKey, question, answer) {
  requireAdmin_(apiKey);
  if (ALL_NAMESPACES.indexOf(dbKey) === -1) throw new Error('無効なnamespace: ' + dbKey);
  question = (question || '').trim();
  answer   = (answer   || '').trim();
  if (!question || !answer) throw new Error('QuestionとAnswerは両方必須です');

  var pageId = 'faq_' + Utilities.getUuid();
  var count  = writeKnowledgeChunks_(pageId, dbKey, 'FAQ: ' + question, 'Q: ' + question + '\nA: ' + answer);
  logKnowledgeChange_('faq', dbKey, question, count, [pageId]);
  return { ok: true, chunks: count };
}

/** Q&A CSV一括インポート（管理者のみ）。ヘッダーに question/answer 列が必要 */
function adminImportFaqCsv(apiKey, dbKey, csvText) {
  requireAdmin_(apiKey);
  if (ALL_NAMESPACES.indexOf(dbKey) === -1) throw new Error('無効なnamespace: ' + dbKey);

  var rows = parseCsv_(csvText);
  if (rows.length < 2) throw new Error('CSVにヘッダー行とデータ行が必要です');

  var header = rows[0].map(function(h) { return h.trim().toLowerCase(); });
  var qIdx = header.indexOf('question');
  var aIdx = header.indexOf('answer');
  if (qIdx === -1 || aIdx === -1) throw new Error('ヘッダーに question 列と answer 列が必要です（例: question,answer）');

  var pageIds = [], total = 0, ok = 0, err = 0;
  for (var i = 1; i < rows.length; i++) {
    var q = (rows[i][qIdx] || '').trim();
    var a = (rows[i][aIdx] || '').trim();
    if (!q || !a) continue;
    total++;
    try {
      var pageId = 'faq_' + Utilities.getUuid();
      writeKnowledgeChunks_(pageId, dbKey, 'FAQ: ' + q, 'Q: ' + q + '\nA: ' + a);
      pageIds.push(pageId);
      ok++;
    } catch (e) {
      err++;
    }
  }
  logKnowledgeChange_('faq_csv', dbKey, total + '件中' + ok + '件成功', ok, pageIds);
  return { ok: true, total: total, success: ok, error: err };
}

/** ファイルアップロードによるナレッジ登録（管理者のみ）。Word/Excel/PPT/PDF/画像/Markdown対応 */
function adminUploadKnowledgeFile(apiKey, base64Data, fileName, mimeType, dbKey) {
  requireAdmin_(apiKey);
  if (ALL_NAMESPACES.indexOf(dbKey) === -1) throw new Error('無効なnamespace: ' + dbKey);

  var text = extractTextFromUpload_(base64Data, fileName, mimeType);
  if (!text || !text.trim()) throw new Error('ファイルからテキストを抽出できませんでした: ' + fileName);

  var pageId = 'upload_' + Utilities.getUuid();
  var count  = writeKnowledgeChunks_(pageId, dbKey, fileName, text);
  logKnowledgeChange_('upload', dbKey, fileName, count, [pageId]);
  return { ok: true, chunks: count };
}

/** ナレッジ登録の更新履歴を取得（管理者のみ） */
function adminGetKnowledgeLog(apiKey, limit) {
  requireAdmin_(apiKey);
  limit = limit || 30;
  var data = getKnowledgeLogSheet_().getDataRange().getValues();
  var out  = [];
  for (var i = data.length - 1; i >= 1 && out.length < limit; i--) {
    out.push({
      timestamp:  String(data[i][0]),
      type:       String(data[i][1]),
      db:         String(data[i][2]),
      label:      String(data[i][3]),
      chunkCount: Number(data[i][4]) || 0,
    });
  }
  return out;
}

// ─────────────────────────────────────────────
// WebApp エントリポイント
// ─────────────────────────────────────────────

function doGet(e) {
  return HtmlService.createHtmlOutput(getChatHtml_())
    .setTitle('RAG チャット')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function doPost(e) {
  try {
    var body    = JSON.parse(e.postData.contents);
    var apiKey  = body.apiKey  || '';
    var action  = body.action  || 'query';

    // 評価アクション: { action:'rate', apiKey, memoryId, rating:'up'|'down' }
    if (action === 'rate') {
      var config = validateApiKey_(apiKey);
      if (!config) {
        return ContentService.createTextOutput(JSON.stringify({ ok: false, status: 'auth_error' }))
          .setMimeType(ContentService.MimeType.JSON);
      }
      var rateResult = rateMemoryEntry(apiKey, body.memoryId || '', body.rating || '');
      rateResult.status = rateResult.ok ? 'ok' : 'error';
      return ContentService.createTextOutput(JSON.stringify(rateResult))
        .setMimeType(ContentService.MimeType.JSON);
    }

    var query   = body.query;
    var dbKey   = body.dbKey   || 'all';
    var history = body.history || [];

    if (!query) throw new Error('query は必須です');

    var config = validateApiKey_(apiKey);
    if (!config) {
      return ContentService.createTextOutput(JSON.stringify({
        answer: '認証エラー: 無効なAPIキーです', sources: [], status: 'auth_error',
      })).setMimeType(ContentService.MimeType.JSON);
    }

    var allowed = config.namespaces || [];
    if (dbKey !== 'all' && allowed.indexOf(dbKey) === -1) {
      return ContentService.createTextOutput(JSON.stringify({
        answer: 'アクセス権限がありません: ' + dbKey,
        sources: [], status: 'forbidden', allowedNamespaces: allowed,
      })).setMimeType(ContentService.MimeType.JSON);
    }

    var result  = ragQueryInternal_(query, dbKey, history, allowed, apiKey);
    var memId   = '';
    try { memId = saveMemory_(apiKey, query, result.answer, result.sources); } catch(e) {}
    return ContentService.createTextOutput(JSON.stringify({
      answer:            result.answer,
      sources:           result.sources,
      extractionRate:    result.extractionRate,
      extractionDetail:  result.extractionDetail,
      status:            'ok',
      allowedNamespaces: allowed,
      memoryId:          memId,
    })).setMimeType(ContentService.MimeType.JSON);

  } catch(err) {
    Logger.log('doPost error: ' + err.message);
    return ContentService.createTextOutput(JSON.stringify({
      answer: 'エラー: ' + err.message, sources: [], status: 'error',
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

// ─────────────────────────────────────────────
// RAG コア
// ─────────────────────────────────────────────

function ragQueryInternal_(query, dbKey, history, allowedNamespaces, apiKey) {
  dbKey = sanitizeDbKey_(dbKey);
  history = history || [];
  if (!allowedNamespaces || allowedNamespaces.length === 0) {
    return { answer: 'アクセス可能なDBがありません。管理者にAPIキーの権限付与を依頼してください。', sources: [] };
  }
  if (dbKey && dbKey !== 'all' && allowedNamespaces.indexOf(dbKey) === -1) {
    dbKey = 'all';
  }

  // HyDE で検索精度を向上させた埋め込みを生成してから検索（dbKey でドメインを指定）
  var hydeEmb = hydeExpand_(query, dbKey);
  var results = searchByEmbedding_(query, dbKey, 5, allowedNamespaces, hydeEmb);
  var context = results.length === 0
    ? '（関連ドキュメントが見つかりませんでした）'
    : results.map(function(r, i) {
        return '### [' + (i+1) + '] ' + r.title + '（DB: ' + r.db + ' / 関連度: ' + (r.score*100).toFixed(1) + '%）\n' + r.text;
      }).join('\n\n');

  // 過去Q&Aをコンテキストに追加（自己学習）
  if (apiKey) {
    try {
      var mems = searchMemory_(query, apiKey, 2);
      var filteredMems = mems.filter(function(m) {
        // priority < 0.3 の低評価エントリはコンテキスト注入から除外
        return m.priority === undefined || m.priority >= 0.3;
      });
      if (filteredMems.length > 0) {
        context += '\n\n### 参考: あなたの過去の関連Q&A\n' +
          filteredMems.map(function(m) {
            return 'Q: ' + m.query + '\nA: ' + m.answer.substring(0, 400);
          }).join('\n\n');
      }
    } catch(e) {}
  }

  var contents = [
    { role: 'user',  parts: [{ text: '以下の参考ドキュメントを確認しました。回答中で参照したドキュメントは必ず [1][2] のように番号で明記してください。\n\n' + context }] },
    { role: 'model', parts: [{ text: '参考ドキュメントを確認しました。引用番号を明記してご質問にお答えします。' }] },
  ];
  history.slice(-6).forEach(function(h) {
    contents.push({ role: h.role === 'bot' ? 'model' : 'user', parts: [{ text: h.text }] });
  });
  contents.push({ role: 'user', parts: [{ text: query }] });

  var answer = callGemini_(contents);

  // 情報抽出度: 回答中の [1][2] 引用を解析
  var extraction = parseExtractionRate_(answer, results.length);

  var seen = {}, sources = [];
  results.forEach(function(r, i) {
    var key = r.db + '::' + r.title;
    if (!seen[key]) {
      seen[key] = true;
      sources.push({ title: r.title, db: r.db, score: r.score, cited: extraction.cited[i] });
    }
  });
  return { answer: answer, sources: sources, extractionRate: extraction.rate, extractionDetail: extraction.citedCount + '/' + extraction.total };
}

// ─────────────────────────────────────────────
// 検索
// ─────────────────────────────────────────────

function searchByEmbedding_(query, dbKey, limit, allowedNamespaces, preEmb) {
  limit = limit || 5;
  var qv = preEmb || embedQuery_(query);
  if (!qv) return [];
  var idx = loadIndex_();
  if (!idx.length) return [];

  // DB指定時は低め（多様なチャンクが少ない小規模DBに対応）、全DB横断は高め
  var MIN_SCORE = (dbKey && dbKey !== 'all') ? 0.58 : 0.62;
  var FETCH_K   = limit * 3;    // ページ重複排除前の候補数

  var candidates = [];
  idx.forEach(function(row) {
    if (allowedNamespaces && allowedNamespaces.indexOf(row.db) === -1) return;
    if (dbKey && dbKey !== 'all' && row.db !== dbKey) return;
    var score = cosineSimilarity_(qv, row.emb);
    if (score < MIN_SCORE) return;
    candidates.push({ score: score, db: row.db, title: row.title, text: row.text });
  });
  candidates.sort(function(a, b) { return b.score - a.score; });

  // ページ単位重複排除: 同タイトルは最高スコアのチャンクのみ残す
  var titleSeen = {}, deduped = [];
  candidates.slice(0, FETCH_K).forEach(function(r) {
    if (!titleSeen[r.title]) { titleSeen[r.title] = true; deduped.push(r); }
  });
  return deduped.slice(0, limit);
}

function cosineSimilarity_(a, b) {
  var dot = 0, na = 0, nb = 0;
  for (var i = 0; i < a.length; i++) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
  var d = Math.sqrt(na) * Math.sqrt(nb);
  return d === 0 ? 0 : dot / d;
}

/**
 * HyDE (Hypothetical Document Embedding)
 * クエリに対して仮説的な回答文書を生成し、クエリ埋め込みと平均を取ることで
 * ドキュメント空間に近い埋め込みを生成する。検索精度を大幅に改善する。
 */
/**
 * dbKey に応じたドメインヒントを返す
 * HyDE の仮説文書をDBの内容に合わせるためのプロンプト調整
 */
function hydePromptFor_(dbKey) {
  var hints = {
    houdini21:  'Houdiniの技術ドキュメントとして、ノード名・パラメータ名・VEX関数名を含めて技術的に',
    tool_docs:  '技術ドキュメントとして、API名・設定値・コード例を含めて具体的に',
    game_info:  'ゲーム情報として、タイトル・仕様・特徴を含めて具体的に',
    research:   '研究・論文の要約として、専門用語・手法・結果を含めて学術的に',
    team_notes: 'チームのメモ・議事録として、決定事項・担当者・日付を含めて',
    afuri:      '飲食店・メニュー情報として、料理名・食材・価格・住所・営業時間を含めて',
    braintq:    'サービス・施設情報として、特徴・利用方法・料金を含めて',
    fourteen:   'ゴルフ場・施設情報として、コース・設備・予約方法を含めて',
  };
  return (hints[dbKey] || '情報ドキュメントとして具体的に') + '、次の質問への回答になる短い説明文（3〜5文）を書いてください:\n\n';
}

// LLMが固有名詞・実店舗情報などの具体的事実を知らないドメイン。
// HyDEの仮説文書がハルシネーションを起こし埋め込みを誤誘導するため、クエリ側の重みを高くする。
var FACT_HEAVY_DOMAINS = ['afuri', 'braintq', 'fourteen'];

function hydeExpand_(query, dbKey) {
  try {
    var apiKey = getProps_().getProperty('GEMINI_API_KEY');
    var url    = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=' + apiKey;
    var prompt = hydePromptFor_(dbKey) + query;
    var payload = JSON.stringify({
      contents: [{ role: 'user', parts: [{ text: prompt }]}],
      generationConfig: { temperature: 0.1, maxOutputTokens: 256 },
    });
    var res = UrlFetchApp.fetch(url, { method: 'post', contentType: 'application/json', payload: payload, muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) return embedQuery_(query);
    var hypoDoc  = JSON.parse(res.getContentText()).candidates[0].content.parts[0].text;
    var queryEmb = embedQuery_(query);
    var hypoEmb  = embedDoc_(hypoDoc);
    if (!queryEmb || !hypoEmb) return queryEmb;
    // 固有事実ドメインはクエリ80%+仮説20%（仮説のハルシネーション影響を抑制）、
    // 技術ドメインはクエリ40%+仮説60%（仮説文書が語彙ギャップを橋渡しする効果を活かす）
    var queryWeight = FACT_HEAVY_DOMAINS.indexOf(dbKey) !== -1 ? 0.8 : 0.4;
    var hypoWeight  = 1 - queryWeight;
    return queryEmb.map(function(v, i) { return v * queryWeight + hypoEmb[i] * hypoWeight; });
  } catch(e) {
    Logger.log('HyDE fallback: ' + e.message);
    return embedQuery_(query);
  }
}

/**
 * 情報抽出度の算出
 * 回答テキスト中の [1][2] 形式のソース引用を解析し、
 * 何件のソースが実際に回答で使われたか（引用率）を返す。
 */
function parseExtractionRate_(answer, total) {
  var cited = {};
  var re = /\[(\d+)\]/g, m;
  while ((m = re.exec(answer)) !== null) {
    var n = parseInt(m[1], 10);
    if (n >= 1 && n <= total) cited[n - 1] = true;
  }
  var citedArr = [];
  for (var i = 0; i < total; i++) citedArr.push(!!cited[i]);
  var citedCount = Object.keys(cited).length;
  return {
    rate:       total > 0 ? Math.round(citedCount / total * 100) : 0,
    citedCount: citedCount,
    total:      total,
    cited:      citedArr,
  };
}

// ─────────────────────────────────────────────
// グラフ
// ─────────────────────────────────────────────

function buildGraphData_(allowedNamespaces) {
  var sheet  = getSheet_();
  var data   = sheet.getDataRange().getValues();
  var docs   = {};
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
  var docList = Object.values ? Object.values(docs) : Object.keys(docs).map(function(k) { return docs[k]; });
  var edges = [], seen = {};
  for (var i = 0; i < docList.length; i++) {
    var scores = [];
    for (var j = 0; j < docList.length; j++) {
      if (i === j) continue;
      scores.push({ j: j, score: cosineSimilarity_(docList[i].emb, docList[j].emb) });
    }
    scores.sort(function(a, b) { return b.score - a.score; });
    for (var k = 0; k < Math.min(3, scores.length); k++) {
      if (scores[k].score < 0.82) break;
      var srcId   = docList[i].id, tgtId = docList[scores[k].j].id;
      var ekey    = srcId < tgtId ? srcId + '|' + tgtId : tgtId + '|' + srcId;
      var crossDb = docList[i].db !== docList[scores[k].j].db;
      if (!seen[ekey]) {
        seen[ekey] = true;
        edges.push({ source: srcId, target: tgtId, score: Math.round(scores[k].score * 1000) / 1000, cross_db: crossDb });
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
// ユーザーメモリ（自己学習）
// ─────────────────────────────────────────────

function getMemorySheet_() {
  var sheetsId = getProps_().getProperty('SHEETS_ID');
  if (!sheetsId) return null;
  try {
    var ss    = SpreadsheetApp.openById(sheetsId);
    var sheet = ss.getSheetByName(MEMORY_SHEET);
    if (!sheet) {
      sheet = ss.insertSheet(MEMORY_SHEET);
      sheet.appendRow(['id', 'apiKeyPrefix', 'timestamp', 'query', 'answer', 'sources', 'rating', 'priority']);
      sheet.getRange(1, 1, 1, 8).setFontWeight('bold');
    }
    return sheet;
  } catch(e) {
    Logger.log('getMemorySheet_ error: ' + e.message);
    return null;
  }
}

function saveMemory_(apiKey, query, answer, sources) {
  try {
    var sheet  = getMemorySheet_();
    if (!sheet) return '';
    var id     = new Date().getTime().toString(36) + Math.random().toString(36).slice(2, 5);
    var prefix = apiKey.substring(0, 8);
    var ts     = new Date().toISOString();
    var srcStr = JSON.stringify((sources || []).slice(0, 5).map(function(s) { return { title: s.title, db: s.db }; }));
    sheet.appendRow([id, prefix, ts, query.substring(0, 500), answer.substring(0, 1000), srcStr, '', 0.5]);
    return id;
  } catch(e) {
    Logger.log('saveMemory_ error: ' + e.message);
    return '';
  }
}

function searchMemory_(query, apiKey, limit) {
  limit = limit || 3;
  try {
    var sheet = getMemorySheet_();
    if (!sheet) return [];
    var prefix = apiKey.substring(0, 8);
    var data   = sheet.getDataRange().getValues();
    if (data.length < 2) return [];
    var words  = query.toLowerCase().split(/[\s、。！？!?,.\r\n]+/).filter(function(w) { return w.length >= 2; });
    if (!words.length) return [];
    var candidates = [];
    var start = Math.max(1, data.length - 300);
    for (var i = data.length - 1; i >= start; i--) {
      if (String(data[i][1]) !== prefix) continue;

      // 👎 評価済みエントリは除外 (rating列=index 6, 値="down")
      var rating = String(data[i][6]);
      if (rating === 'down') continue;

      var storedQ = String(data[i][3]).toLowerCase();
      var storedA = String(data[i][4]).toLowerCase();
      var overlapCount = 0;
      words.forEach(function(w) { if (storedQ.indexOf(w) !== -1 || storedA.indexOf(w) !== -1) overlapCount++; });

      // priority による重み付け (priority列=index 7、存在しない場合は0.5)
      var priority = parseFloat(data[i][7]);
      if (isNaN(priority)) priority = 0.5;

      // 最終スコア = overlap * (1 + priority)
      var weightedScore = overlapCount * (1 + priority);

      // 最低スコア閾値: 重み付きスコアが 1.5 未満は除外
      if (weightedScore < 1.5) continue;

      candidates.push({ score: weightedScore, query: String(data[i][3]), answer: String(data[i][4]) });
    }
    candidates.sort(function(a, b) { return b.score - a.score; });
    return candidates.slice(0, limit);
  } catch(e) {
    Logger.log('searchMemory_ error: ' + e.message);
    return [];
  }
}

// ─────────────────────────────────────────────
// Gemini
// ─────────────────────────────────────────────

function callGemini_(contents) {
  var apiKey  = getProps_().getProperty('GEMINI_API_KEY');
  var url     = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=' + apiKey;
  var payload = JSON.stringify({
    system_instruction: { parts: [{ text:
      'あなたはゲーム開発チームの知識ベースを持つAIアシスタントです。\n' +
      '日本語で**簡潔に**回答してください（目安: 400文字以内）。\n' +
      '重要な点のみ箇条書き（-）または短い見出し（##）でまとめてください。\n' +
      '知識ベースに情報がない場合のみ「情報がありません」と答えてください。\n' +
      '「参考: あなたの過去の関連Q&A」が含まれる場合は、それもユーザーの文脈として活用してください。'
    }]},
    contents:         contents,
    generationConfig: { temperature: 0.4, maxOutputTokens: 2048 },
  });
  var maxRetries = 10, baseDelay = 1000, maxDelay = 30000;
  for (var i = 0; i < maxRetries; i++) {
    var res  = UrlFetchApp.fetch(url, {
      method: 'post', contentType: 'application/json',
      payload: payload, muteHttpExceptions: true,
    });
    var code = res.getResponseCode();
    if (code === 200) return JSON.parse(res.getContentText()).candidates[0].content.parts[0].text;
    if ((code === 429 || code === 503) && i < maxRetries - 1) {
      var ra   = parseInt(((res.getHeaders() || {})['Retry-After'] || '0'), 10);
      var wait = ra > 0 ? ra * 1000 : Math.min(baseDelay * Math.pow(2, i), maxDelay) + Math.floor(Math.random() * 1000);
      Utilities.sleep(wait);
      continue;
    }
    return '（Gemini APIエラー: ' + code + '）';
  }
  return '（リトライ上限に達しました）';
}

// ─────────────────────────────────────────────
// Embedding
// ─────────────────────────────────────────────

function embed_(text, taskType) {
  var apiKey  = getProps_().getProperty('GEMINI_API_KEY');
  var url     = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=' + apiKey;
  var payload = {
    model:   'models/gemini-embedding-001',
    content: { parts: [{ text: text.substring(0, 2000) }] },
    outputDimensionality: 768,
  };
  if (taskType) payload.taskType = taskType;
  var res = UrlFetchApp.fetch(url, {
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify(payload), muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) { Logger.log('Embed error: ' + res.getContentText().substring(0, 200)); return null; }
  return JSON.parse(res.getContentText()).embedding.values;
}

function embedDoc_(text)   { return embed_(text, 'RETRIEVAL_DOCUMENT'); }
function embedQuery_(text) { return embed_(text, 'RETRIEVAL_QUERY');    }

// ─────────────────────────────────────────────
// インデックスキャッシュ
// ─────────────────────────────────────────────

function loadIndex_() {
  var cache = CacheService.getScriptCache();
  var n     = parseInt(cache.get(IDX_CACHE_KEY + '_n') || '0', 10);
  if (n > 0) {
    var keys = [], vals, json = '', ok = true;
    for (var i = 0; i < n; i++) keys.push(IDX_CACHE_KEY + '_' + i);
    vals = cache.getAll(keys);
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
    rows.push({ db: data[i][1], title: data[i][2], text: String(data[i][3]).substring(0, 600), emb: JSON.parse(embStr) });
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
// Google Sheets ヘルパー
// ─────────────────────────────────────────────

function getSheet_() {
  var sheetsId = getProps_().getProperty('SHEETS_ID');
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
// Notion 同期（GASエディタから手動実行）
// ─────────────────────────────────────────────

// 後方互換のためのエイリアス。docs・過去の運用手順で "syncNotionToSheets" として
// 案内しているため関数名はそのまま残し、実体は Notion/Drive 両対応の syncAllSources_ に委譲する。
function syncNotionToSheets() {
  return syncAllSources_();
}

/**
 * namespace ごとに、Notion（DB_KEY_MAP）と Google Drive（DRIVE_KEY_MAP）の
 * どちらのスクリプトプロパティが設定されているかを見て取得元を振り分け、
 * RAG_Index シートを更新する。両方とも未設定の namespace はスキップする。
 * 同じ namespace に両方設定されている場合は Notion を優先する。
 */
function syncAllSources_() {
  var props    = getProps_();
  var sheet    = getSheet_();
  var data     = sheet.getDataRange().getValues();
  var nHeaders = {
    'Authorization':  'Bearer ' + props.getProperty('NOTION_API_KEY'),
    'Notion-Version': '2022-06-28',
    'Content-Type':   'application/json',
  };
  var embedUrl = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=' + props.getProperty('GEMINI_API_KEY');

  var existingMap = {};
  for (var i = 1; i < data.length; i++) {
    var baseId = String(data[i][0]).split('::')[0];
    if (!existingMap[baseId]) existingMap[baseId] = { rowIndices: [], lastEdited: data[i][4] };
    existingMap[baseId].rowIndices.push(i + 1);
  }

  var notionKeys = [], driveKeys = [];
  Object.keys(DB_KEY_MAP).forEach(function(key) {
    if (props.getProperty(DB_KEY_MAP[key]))         notionKeys.push(key);
    else if (props.getProperty(DRIVE_KEY_MAP[key]))  driveKeys.push(key);
    else Logger.log('DB未設定: ' + key);
  });

  var rowsToDelete = [], updateList = [], totalSkip = 0;

  // ── Notion ソース（Phase1: ページ一覧を並列取得） ──────────────────────────
  if (notionKeys.length > 0) {
    var listReqs = notionKeys.map(function(key) {
      var dbId = props.getProperty(DB_KEY_MAP[key]);
      return {
        url: 'https://api.notion.com/v1/databases/' + dbId + '/query',
        method: 'post', headers: nHeaders, contentType: 'application/json',
        payload: JSON.stringify({ page_size: 100 }), muteHttpExceptions: true,
      };
    });
    Logger.log('Phase1(Notion): ' + notionKeys.length + 'DB を並列取得...');
    var listResps = UrlFetchApp.fetchAll(listReqs);
    listResps.forEach(function(res, i) {
      var key = notionKeys[i];
      if (res.getResponseCode() !== 200) { Logger.log('[' + key + '] エラー: ' + res.getResponseCode()); return; }
      var pages = JSON.parse(res.getContentText()).results || [];
      Logger.log('[' + key + '] ' + pages.length + 'ページ');
      pages.forEach(function(page) {
        var pd = extractPageData_(page, key);
        if (!pd) return;
        var ex = existingMap[pd.page_id];
        if (ex && ex.lastEdited === pd.last_edited) { totalSkip++; return; }
        if (ex) rowsToDelete = rowsToDelete.concat(ex.rowIndices);
        updateList.push({ pd: pd, source: 'notion' });
      });
    });
  }

  // ── Google Drive ソース（フォルダ内の Markdown / Google ドキュメントを走査） ──
  if (driveKeys.length > 0) {
    Logger.log('Drive: ' + driveKeys.length + 'DB を取得...');
    driveKeys.forEach(function(key) {
      var folderId = props.getProperty(DRIVE_KEY_MAP[key]);
      var result   = fetchDriveFolderPages_(folderId, key, existingMap);
      Logger.log('[' + key + '] (Drive) ' + result.total + 'ファイル  更新:' + result.updateList.length);
      updateList   = updateList.concat(result.updateList);
      rowsToDelete = rowsToDelete.concat(result.rowsToDelete);
      totalSkip   += result.totalSkip;
    });
  }

  Logger.log('更新対象: ' + updateList.length + 'ページ  スキップ: ' + totalSkip);
  if (updateList.length === 0) { invalidateIndexCache_(); return; }

  // ── Notion本文取得（Phase2: ブロックの2段階ページネーション） ───────────────
  // Drive側は fetchDriveFolderPages_ 内で本文取得済みのため item.body に直接入っている。
  var notionItems = updateList.filter(function(item) { return item.source === 'notion'; });
  if (notionItems.length > 0) {
    var bodyReqs = notionItems.map(function(item) {
      return {
        url: 'https://api.notion.com/v1/blocks/' + item.pd.page_id + '/children?page_size=100',
        method: 'get', headers: nHeaders, muteHttpExceptions: true,
      };
    });
    var bodyResps   = UrlFetchApp.fetchAll(bodyReqs);
    var TEXT_TYPES  = { paragraph:1, heading_1:1, heading_2:1, heading_3:1, bulleted_list_item:1, numbered_list_item:1, quote:1, callout:1, toggle:1, code:1 };

    var extractLines_ = function(blocks) {
      return blocks.reduce(function(acc, b) {
        if (!TEXT_TYPES[b.type]) return acc;
        var line = ((b[b.type] || {}).rich_text || []).map(function(t) { return t.plain_text || ''; }).join('');
        if (line.trim()) acc.push(line);
        return acc;
      }, []);
    };

    var bodies = bodyResps.map(function(res, i) {
      if (res.getResponseCode() !== 200) return '';
      var d     = JSON.parse(res.getContentText());
      var lines = extractLines_(d.results || []);
      if (!d.has_more) return lines.join('\n').substring(0, 8000);
      notionItems[i].p2cursor = d.next_cursor;
      notionItems[i].p1lines  = lines;
      return null;
    });

    var p2idx = [], p2reqs = [];
    notionItems.forEach(function(item, i) {
      if (!item.p2cursor) return;
      p2idx.push(i);
      p2reqs.push({ url: 'https://api.notion.com/v1/blocks/' + item.pd.page_id + '/children?page_size=100&start_cursor=' + item.p2cursor, method: 'get', headers: nHeaders, muteHttpExceptions: true });
    });
    if (p2reqs.length > 0) {
      UrlFetchApp.fetchAll(p2reqs).forEach(function(res, j) {
        var idx   = p2idx[j];
        var extra = (res.getResponseCode() === 200) ? extractLines_(JSON.parse(res.getContentText()).results || []) : [];
        bodies[idx] = notionItems[idx].p1lines.concat(extra).join('\n').substring(0, 8000);
      });
    }
    notionItems.forEach(function(item, i) {
      item.body = bodies[i] === null ? '' : bodies[i];
    });
  }

  // ── チャンク化・埋め込み生成・シート書き込み（ソース共通） ─────────────────
  var allChunks = [];
  updateList.forEach(function(item) {
    var full   = item.pd.meta_text + (item.body ? '\n\n' + item.body : '');
    var chunks = chunkText_(full, 500, 100);
    chunks.forEach(function(chunk, k) {
      allChunks.push({ text: chunk, page_id: item.pd.page_id, db: item.pd.db, title: item.pd.title, last_edited: item.pd.last_edited, k: k });
    });
  });

  var BATCH_SIZE = 10, newRows = [], totalOk = 0, totalErr = 0;
  for (var b = 0; b < allChunks.length; b += BATCH_SIZE) {
    var batch     = allChunks.slice(b, b + BATCH_SIZE);
    var embedReqs = batch.map(function(c) {
      return { url: embedUrl, method: 'post', contentType: 'application/json',
        payload: JSON.stringify({ model: 'models/gemini-embedding-001', content: { parts: [{ text: c.text.substring(0, 2000) }] }, outputDimensionality: 768, taskType: 'RETRIEVAL_DOCUMENT' }),
        muteHttpExceptions: true };
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

  rowsToDelete.sort(function(a, b) { return b - a; });
  rowsToDelete.forEach(function(ri) { sheet.deleteRow(ri); });
  if (newRows.length > 0) sheet.getRange(sheet.getLastRow() + 1, 1, newRows.length, 6).setValues(newRows);
  Logger.log('完了  チャンク:' + totalOk + '  スキップ:' + totalSkip + '  エラー:' + totalErr);
  invalidateIndexCache_();
}

function extractPageData_(page, dbKey) {
  var props   = page.properties || {};
  var title   = ((props.title   || {}).title     || []).map(function(t) { return t.plain_text || ''; }).join('');
  if (!title) return null;
  var summary = ((props.summary || {}).rich_text  || []).map(function(t) { return t.plain_text || ''; }).join('');
  var tags    = ((props.tags    || {}).multi_select || []).map(function(t) { return t.name || ''; });
  var url_    = (props.source_url || {}).url || '';
  var parts   = ['# ' + title];
  if (summary)     parts.push(summary);
  if (tags.length) parts.push('タグ: ' + tags.join(', '));
  if (url_)        parts.push('参照: ' + url_);
  return { page_id: page.id, db: dbKey, title: title, meta_text: parts.join('\n'), last_edited: page.last_edited_time || '' };
}

/**
 * Markdown先頭の簡易frontmatter（--- key: value ... ---）を解析する。
 * localRAG/_templates/ の各テンプレートと同じ `title` / `summary` / `tags` / `source_url`
 * キーのみサポートする軽量パーサー（フルYAML対応ではない）。
 */
function parseFrontmatter_(text) {
  var m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/.exec(text);
  if (!m) return { meta: {}, body: text };
  var meta = {};
  m[1].split('\n').forEach(function(line) {
    var kv = /^([a-zA-Z_][\w-]*)\s*:\s*(.*)$/.exec(line);
    if (kv) meta[kv[1]] = kv[2].trim();
  });
  return { meta: meta, body: m[2] };
}

/** Google Drive のファイル1件を Notion の extractPageData_ と同じ形の pd オブジェクトに変換する */
function extractDrivePageData_(file, dbKey, rawText) {
  var parsed  = parseFrontmatter_(rawText);
  var meta    = parsed.meta;
  var title   = meta.title || file.getName().replace(/\.(md|txt)$/i, '');
  var tags    = meta.tags ? meta.tags.replace(/[\[\]]/g, '').split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];
  var parts   = ['# ' + title];
  if (meta.summary)    parts.push(meta.summary);
  if (tags.length)     parts.push('タグ: ' + tags.join(', '));
  if (meta.source_url) parts.push('参照: ' + meta.source_url);
  return {
    page_id:     'drive_' + file.getId(),
    db:          dbKey,
    title:       title,
    meta_text:   parts.join('\n'),
    body:        parsed.body,
    last_edited: file.getLastUpdated().toISOString(),
  };
}

/**
 * Google Drive フォルダ配下の Markdown（.md/.txt）・Google ドキュメントを走査し、
 * Notionと同じ差分同期ロジック（既存 page_id との last_edited 比較）で更新対象を抽出する。
 * PDF・画像など非対応形式のファイルは無視する。サブフォルダは辿らない（フラット走査）。
 */
function fetchDriveFolderPages_(folderId, dbKey, existingMap) {
  var updateList = [], rowsToDelete = [], totalSkip = 0, total = 0;
  var folder;
  try {
    folder = DriveApp.getFolderById(folderId);
  } catch (e) {
    Logger.log('[' + dbKey + '] Driveフォルダが見つかりません（ID誤りまたは共有未設定）: ' + folderId);
    return { updateList: updateList, rowsToDelete: rowsToDelete, totalSkip: totalSkip, total: total };
  }

  var files = folder.getFiles();
  while (files.hasNext()) {
    var file = files.next();
    var mime = file.getMimeType();
    var name = file.getName();
    var isSupported = (mime === MimeType.GOOGLE_DOCS) || (mime === 'text/markdown') || (mime === 'text/plain') || /\.(md|txt)$/i.test(name);
    if (!isSupported) continue;
    total++;

    var rawText = (mime === MimeType.GOOGLE_DOCS)
      ? DocumentApp.openById(file.getId()).getBody().getText()
      : file.getBlob().getDataAsString('UTF-8');

    var pd = extractDrivePageData_(file, dbKey, rawText);
    var ex = existingMap[pd.page_id];
    if (ex && ex.lastEdited === pd.last_edited) { totalSkip++; continue; }
    if (ex) rowsToDelete = rowsToDelete.concat(ex.rowIndices);
    updateList.push({ pd: pd, source: 'drive', body: pd.body });
  }

  return { updateList: updateList, rowsToDelete: rowsToDelete, totalSkip: totalSkip, total: total };
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
// HTML 生成
// ─────────────────────────────────────────────

function getChatHtml_() {
  var allNsJson = JSON.stringify(ALL_NAMESPACES);
  var dbLabelsJson = JSON.stringify(DB_LABELS);

  return [
'<!DOCTYPE html>',
'<html lang="ja">',
'<head>',
'<meta charset="UTF-8">',
'<meta name="viewport" content="width=device-width,initial-scale=1">',
'<title>RAG チャット</title>',
'<style>',
':root{',
'  --primary:#6366f1;--primary-dark:#4f46e5;--bg:#f1f5f9;--white:#fff;',
'  --text:#1e293b;--text-light:#64748b;--border:#e2e8f0;',
'  --user-grad:linear-gradient(135deg,#6366f1,#8b5cf6);',
'  --shadow:0 1px 4px rgba(0,0,0,.08);',
'  --dark:#0f1117;--dark2:#1a1d27;--dark3:#242838;--dborder:#2e3348;',
'  --accent:#6c8ef7;--accent2:#4ade80;--warn:#f87171;',
'}',
'*{box-sizing:border-box;margin:0;padding:0}',
'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;height:100vh;display:flex;flex-direction:column;width:100%;min-width:320px;padding:0 clamp(8px,2vw,24px);box-sizing:border-box}',

'/* ── ログイン画面 ── */',
'#login-screen{',
'  flex:1;display:flex;align-items:center;justify-content:center;',
'  background:linear-gradient(135deg,#0f1117 0%,#1a1d27 100%);',
'}',
'.login-card{',
'  background:#1a1d27;border:1px solid #2e3348;border-radius:16px;',
'  padding:40px 36px;width:360px;text-align:center;',
'  box-shadow:0 8px 32px rgba(0,0,0,.4);',
'}',
'.login-icon{font-size:48px;margin-bottom:16px}',
'.login-card h2{font-size:1.2rem;font-weight:700;color:#e2e8f0;margin-bottom:6px}',
'.login-card p{font-size:.8rem;color:#64748b;margin-bottom:24px}',
'.login-input{',
'  width:100%;padding:10px 14px;background:#0f1117;border:1.5px solid #2e3348;',
'  border-radius:8px;color:#e2e8f0;font-size:.9rem;font-family:monospace;',
'  outline:none;transition:border-color .2s;margin-bottom:12px;',
'}',
'.login-input:focus{border-color:var(--accent)}',
'.login-btn{',
'  width:100%;padding:11px;background:var(--accent);color:#fff;border:none;',
'  border-radius:8px;font-size:.9rem;font-weight:600;cursor:pointer;',
'  transition:background .2s;font-family:inherit;',
'}',
'.login-btn:hover{background:var(--primary-dark)}',
'.login-btn:disabled{background:#334155;cursor:not-allowed}',
'.login-error{font-size:.78rem;color:var(--warn);margin-top:10px;min-height:18px}',

'/* ── チャット画面 ── */',
'#chat-screen{display:none;flex-direction:column;flex:1;overflow:hidden;background:var(--bg)}',
'header{background:var(--white);border-bottom:1px solid var(--border);padding:10px 16px;',
'  display:flex;align-items:center;gap:10px;box-shadow:var(--shadow);flex-shrink:0}',
'.hicon{width:36px;height:36px;background:var(--user-grad);border-radius:10px;',
'  display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}',
'.htext{flex:1;min-width:0}.htext h1{font-size:15px;font-weight:700;color:var(--text)}',
'.htext p{font-size:11px;color:var(--text-light)}',
'.user-badge{font-size:.75rem;padding:3px 9px;border-radius:99px;background:#ede9fe;color:#6d28d9;white-space:nowrap}',
'.logout-btn{font-size:.75rem;padding:5px 12px;border-radius:6px;background:transparent;color:#64748b;',
'  border:1px solid #e2e8f0;cursor:pointer;font-family:inherit;white-space:nowrap;transition:all .15s;display:flex;align-items:center;gap:4px}',
'.logout-btn:hover{background:#fee2e2;color:#991b1b;border-color:#fecaca}',

'/* タブ */',
'.tab-bar{display:flex;background:var(--white);border-bottom:1px solid var(--border);flex-shrink:0}',
'.tab-btn{flex:1;padding:9px 0;font-size:13px;font-weight:600;border:none;background:none;',
'  cursor:pointer;color:var(--text-light);border-bottom:2px solid transparent;',
'  font-family:inherit;transition:all .15s}',
'.tab-btn.active{color:var(--primary);border-bottom-color:var(--primary)}',
'.tab-btn:hover:not(.active){color:var(--text);background:#f8fafc}',
'#tab-chat{display:flex;flex-direction:column;flex:1;overflow:hidden}',
'#tab-graph{display:none;flex-direction:column;flex:1;overflow:hidden;background:#0f172a;color:#e2e8f0}',
'#tab-history{display:none;flex:1;overflow-y:auto;background:var(--bg);padding:16px}',
'#tab-admin{display:none;flex:1;overflow-y:auto;background:var(--dark);color:#e2e8f0;padding:20px}',

'/* 履歴カード */',
'.hist-card{background:var(--white);border:1px solid var(--border);border-radius:12px;padding:14px 16px;margin-bottom:12px;cursor:pointer;transition:box-shadow .15s}',
'.hist-card:hover{box-shadow:0 2px 12px rgba(0,0,0,.1)}',
'.hist-meta{font-size:11px;color:var(--text-light);margin-bottom:6px;display:flex;align-items:center;gap:8px}',
'.hist-q{font-size:13px;font-weight:600;color:var(--text);margin-bottom:6px;line-height:1.4}',
'.hist-a{font-size:12px;color:var(--text-light);line-height:1.6;display:none}',
'.hist-a.open{display:block}',
'.hist-sources{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}',
'.hist-src-tag{font-size:10px;background:#ede9fe;color:#6d28d9;padding:1px 7px;border-radius:99px}',
'.hist-rating{display:flex;gap:6px;margin-top:8px}',
'.rating-btn{background:none;border:1px solid var(--border);border-radius:6px;cursor:pointer;',
'  padding:3px 10px;font-size:13px;transition:all .15s}',
'.rating-btn:hover{border-color:var(--primary)}',
'.rating-btn.selected-up{background:#dcfce7;border-color:#16a34a}',
'.rating-btn.selected-down{background:#fee2e2;border-color:#dc2626}',
'#history-status{text-align:center;color:var(--text-light);font-size:13px;padding:30px 0}',

'/* DB選択 */',
'.dbwrap{padding:8px 14px;background:var(--white);border-bottom:1px solid var(--border);flex-shrink:0}',
'select{width:100%;padding:7px 11px;border:1px solid var(--border);border-radius:8px;',
'  font-size:13px;color:var(--text);background:var(--white);cursor:pointer;outline:none}',
'select:focus{border-color:var(--primary)}',

'/* チャット */',
'#chat{flex:1;overflow-y:auto;padding:18px 14px;display:flex;flex-direction:column;gap:14px}',
'.welcome{text-align:center;padding:50px 20px;color:var(--text-light)}',
'.welcome-icon{font-size:48px;margin-bottom:12px}',
'.welcome h2{font-size:16px;color:var(--text);margin-bottom:7px;font-weight:700}',
'.welcome p{font-size:12px;line-height:1.6}',
'.msg{display:flex;gap:8px;max-width:90%}',
'.msg.user{align-self:flex-end;flex-direction:row-reverse}',
'.msg.bot{align-self:flex-start}',
'.av{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;',
'  font-size:15px;flex-shrink:0;background:#f8fafc;border:1px solid var(--border);margin-top:2px}',
'.msg.user .av{background:var(--user-grad);border:none}',
'.bwrap{display:flex;flex-direction:column;gap:5px;min-width:0}',
'.bubble{padding:10px 14px;border-radius:16px;font-size:14px;line-height:1.75;word-break:break-word}',
'.msg.user .bubble{background:var(--user-grad);color:#fff;border-bottom-right-radius:4px}',
'.msg.bot .bubble{background:var(--white);color:var(--text);border-bottom-left-radius:4px;',
'  box-shadow:var(--shadow);border:1px solid var(--border)}',
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
'.src-toggle{font-size:11px;color:var(--text-light);cursor:pointer;display:inline-flex;',
'  align-items:center;gap:3px;background:none;border:none;padding:2px 0;font-family:inherit}',
'.src-toggle:hover{color:var(--primary)}',
'.src-list{display:none;margin-top:5px;background:var(--white);border:1px solid var(--border);',
'  border-radius:10px;overflow:hidden;box-shadow:var(--shadow)}',
'.src-list.open{display:block}',
'.src-item{padding:7px 11px;font-size:12px;border-bottom:1px solid var(--border);',
'  display:flex;align-items:center;gap:8px}',
'.src-item:last-child{border-bottom:none}',
'.src-db{font-size:11px;background:#ede9fe;color:#6d28d9;padding:2px 7px;border-radius:10px;white-space:nowrap;flex-shrink:0}',
'.src-score{color:var(--text-light);margin-left:auto;font-size:11px;font-weight:600;white-space:nowrap}',
'.src-score.high{color:#16a34a}.src-score.mid{color:#d97706}.src-score.low{color:#94a3b8}',
'.src-cited{font-size:10px;background:#dcfce7;color:#16a34a;padding:1px 6px;border-radius:99px;white-space:nowrap;flex-shrink:0}',
'.src-not-cited{font-size:10px;background:#f1f5f9;color:#94a3b8;padding:1px 6px;border-radius:99px;white-space:nowrap;flex-shrink:0}',
'.extract-summary{font-size:11px;color:var(--text-light);padding:5px 11px;background:#f8fafc;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:6px}',
'.extract-bar{height:4px;border-radius:2px;background:#e2e8f0;flex:1;overflow:hidden}',
'.extract-fill{height:100%;border-radius:2px;background:#6366f1;transition:width .4s}',
'.input-area{padding:10px 14px;background:var(--white);border-top:1px solid var(--border);',
'  display:flex;gap:8px;align-items:flex-end;flex-shrink:0}',
'textarea{flex:1;padding:9px 13px;border:1.5px solid var(--border);border-radius:12px;',
'  font-size:14px;font-family:inherit;color:var(--text);resize:none;outline:none;',
'  max-height:120px;min-height:42px;line-height:1.6;transition:border-color .2s;background:var(--white)}',
'textarea:focus{border-color:var(--primary)}',
'#sbtn{width:42px;height:42px;background:var(--primary);color:#fff;border:none;',
'  border-radius:12px;cursor:pointer;font-size:18px;display:flex;align-items:center;',
'  justify-content:center;transition:background .2s;flex-shrink:0}',
'#sbtn:hover{background:var(--primary-dark)}#sbtn:disabled{background:#c7d2fe;cursor:not-allowed}',

'/* グラフ */',
'.graph-toolbar{padding:8px 14px;display:flex;align-items:center;gap:8px;border-bottom:1px solid #1e293b;flex-shrink:0;flex-wrap:wrap}',
'.graph-toolbar button{padding:5px 14px;border:1px solid #334155;border-radius:8px;',
'  background:#1e293b;color:#e2e8f0;cursor:pointer;font-size:12px;font-family:inherit;transition:background .15s}',
'.graph-toolbar button:hover{background:#334155}',
'.graph-toolbar button.active{background:var(--primary);border-color:var(--primary);color:#fff}',
'#graph-status{font-size:11px;color:#94a3b8;margin-left:auto}',
'.graph-main{flex:1;display:flex;overflow:hidden}',
'#graph-svg{flex:1;min-width:0;display:block}',
'#node-panel{width:0;overflow:hidden;background:#111827;border-left:1px solid #1e293b;',
'  transition:width .25s;flex-shrink:0;display:flex;flex-direction:column}',
'#node-panel.open{width:260px}',
'.node-panel-header{padding:12px 14px;border-bottom:1px solid #1e293b;display:flex;align-items:center;justify-content:space-between}',
'.node-panel-title{font-size:.85rem;font-weight:700;color:#e2e8f0;word-break:break-word}',
'.node-panel-close{background:none;border:none;color:#64748b;cursor:pointer;font-size:16px;padding:0;line-height:1}',
'.node-panel-close:hover{color:#e2e8f0}',
'.node-panel-body{padding:12px 14px;flex:1;overflow-y:auto;font-size:.78rem}',
'.node-db-badge{display:inline-block;padding:2px 8px;border-radius:99px;color:#fff;font-size:.7rem;font-weight:600;margin:6px 0 10px}',
'.node-connections{margin-top:8px}',
'.node-connections h4{font-size:.72rem;color:#64748b;margin-bottom:6px;font-weight:500;text-transform:uppercase;letter-spacing:.05em}',
'.conn-item{display:flex;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid #1e293b}',
'.conn-item:last-child{border-bottom:none}',
'.conn-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}',
'.conn-name{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#94a3b8}',
'.conn-score{font-size:.7rem;color:#64748b;white-space:nowrap}',
'/* 管理サブタブ */',
'.admin-sub-bar{display:flex;background:var(--dark2);border-bottom:1px solid var(--dborder);',
'  margin:-20px -clamp(8px,2vw,24px) 20px;padding:0 clamp(8px,2vw,24px);flex-shrink:0}',
'.admin-sub-btn{padding:11px 20px;font-size:.82rem;font-weight:600;border:none;background:none;',
'  cursor:pointer;color:#64748b;border-bottom:2px solid transparent;font-family:inherit;transition:all .15s;white-space:nowrap}',
'.admin-sub-btn.active{color:var(--accent);border-bottom-color:var(--accent)}',
'.admin-sub-btn:hover:not(.active){color:#e2e8f0;background:rgba(255,255,255,.04)}',
'.admin-sub-panel{display:none}.admin-sub-panel.active{display:block}',

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
'.ns-chk label{display:flex;align-items:center;gap:4px;font-size:.75rem;padding:3px 8px;',
'  border-radius:99px;border:1px solid var(--dborder);background:var(--dark3);cursor:pointer;color:#94a3b8}',
'.ns-chk label:has(input:checked){border-color:var(--accent2);background:#0d2018;color:var(--accent2)}',
'.btn-admin{padding:6px 14px;border:none;border-radius:6px;cursor:pointer;font-size:.8rem;font-weight:600;transition:opacity .15s}',
'.btn-admin:hover{opacity:.85}',
'.btn-primary{background:var(--accent);color:#fff}',
'.btn-danger{background:var(--warn);color:#fff}',
'.btn-sm{padding:3px 8px;font-size:.72rem}',
'.admin-flash{padding:8px 14px;border-radius:6px;font-size:.8rem;margin-bottom:10px;display:none}',
'.admin-flash.ok{background:#14532d;border:1px solid var(--accent2);color:var(--accent2)}',
'.admin-flash.err{background:#450a0a;border:1px solid var(--warn);color:var(--warn)}',
'.badge-admin{font-size:.7rem;background:#312e81;color:#a5b4fc;padding:1px 6px;border-radius:99px;margin-left:4px}',

'/* キー表示モーダル */',
'.key-modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:100;align-items:center;justify-content:center}',
'.key-modal-overlay.show{display:flex}',
'.key-modal{background:var(--dark2);border:1px solid var(--dborder);border-radius:12px;padding:24px;max-width:480px;width:90%}',
'.key-box{background:var(--dark3);border:1px solid var(--accent);border-radius:6px;padding:12px;',
'  font-family:monospace;font-size:.85rem;word-break:break-all;color:var(--accent2);margin:12px 0}',
'</style>',
'</head>',
'<body>',

'<!-- ログイン画面 -->',
'<div id="login-screen">',
'  <div class="login-card">',
'    <div class="login-icon">🔍</div>',
'    <h2>RAG チャット</h2>',
'    <p>APIキーを入力してください</p>',
'    <input class="login-input" id="key-input" type="password" placeholder="APIキー（32文字）">',
'    <button class="login-btn" id="login-btn" onclick="doLogin()">ログイン</button>',
'    <div class="login-error" id="login-error"></div>',
'  </div>',
'</div>',

'<!-- チャット画面 -->',
'<div id="chat-screen">',
'<header>',
'  <div class="hicon">🔍</div>',
'  <div class="htext"><h1>RAG チャット</h1><p>Notion × Gemini ベクトル検索</p></div>',
'  <span class="user-badge" id="user-name-badge">—</span>',
'  <button class="logout-btn" onclick="doLogout()">⏻ ログアウト</button>',
'</header>',
'<div class="tab-bar" id="tab-bar">',
'  <button class="tab-btn active" onclick="switchTab(\'chat\')">💬 チャット</button>',
'  <button class="tab-btn" onclick="switchTab(\'graph\')">🕸 グラフ</button>',
'  <button class="tab-btn" onclick="switchTab(\'history\')">📚 履歴</button>',
'  <button class="tab-btn" id="admin-tab-btn" style="display:none" onclick="switchTab(\'admin\')">⚙ 管理</button>',
'</div>',
'<div id="tab-chat">',
'  <div class="dbwrap"><select id="db"></select></div>',
'  <div id="chat">',
'    <div class="welcome">',
'      <div class="welcome-icon">🧠</div>',
'      <h2>何でも聞いてください</h2>',
'      <p>Notionの知識ベースをベクトル検索で参照し、Geminiが回答します</p>',
'    </div>',
'  </div>',
'  <div class="input-area">',
'    <textarea id="q" placeholder="質問を入力... (Ctrl+Enter で送信)" rows="1"></textarea>',
'    <button id="sbtn" onclick="send()">↑</button>',
'  </div>',
'</div>',
'<div id="tab-graph">',
'  <div class="graph-toolbar">',
'    <button onclick="loadGraph()">更新</button>',
'    <button onclick="fitGraph()">全体</button>',
'    <button id="btn-cross-db" class="active" onclick="toggleCrossDb()">DB跨ぎ表示</button>',
'    <span id="graph-status">「更新」を押してグラフを取得</span>',
'  </div>',
'  <div class="graph-main">',
'    <svg id="graph-svg"></svg>',
'    <div id="node-panel">',
'      <div class="node-panel-header">',
'        <span class="node-panel-title" id="panel-title">ノード詳細</span>',
'        <button class="node-panel-close" onclick="closeNodePanel()">✕</button>',
'      </div>',
'      <div class="node-panel-body">',
'        <div id="panel-db-badge" class="node-db-badge"></div>',
'        <div id="panel-full-title" style="color:#e2e8f0;font-size:.82rem;margin-bottom:12px;line-height:1.5"></div>',
'        <div class="node-connections">',
'          <h4>関連ノード</h4>',
'          <div id="panel-connections"></div>',
'        </div>',
'      </div>',
'    </div>',
'  </div>',
'</div>',
'<div id="tab-history">',
'  <div id="history-status">「履歴」タブを開くと読み込まれます</div>',
'  <div id="history-list"></div>',
'</div>',
'<div id="tab-admin">',
'  <div id="admin-flash" class="admin-flash"></div>',
'  <div class="admin-sub-bar">',
'    <button class="admin-sub-btn active" id="asub-keys-btn" onclick="switchAdminSub(\'keys\')">🔑 APIキー管理</button>',
'    <button class="admin-sub-btn" id="asub-knowledge-btn" onclick="switchAdminSub(\'knowledge\')">📚 ナレッジ管理</button>',
'    <button class="admin-sub-btn" id="asub-guide-btn" onclick="switchAdminSub(\'guide\')">📖 使い方</button>',
'  </div>',
'  <!-- サブタブ: APIキー管理 -->',
'  <div class="admin-sub-panel active" id="asub-keys">',
'  <div class="admin-section">',
'    <h3>新しいキーを発行</h3>',
'    <div style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:end;margin-bottom:12px">',
'      <div><label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">名前</label>',
'      <input class="admin-input" id="new-key-name" type="text" placeholder="例: Unity Client, Alice"></div>',
'      <label style="font-size:.78rem;color:#94a3b8;display:flex;align-items:center;gap:5px;cursor:pointer;padding-bottom:2px;white-space:nowrap">',
'        <input type="checkbox" id="new-key-admin"><span>管理者権限</span></label>',
'    </div>',
'    <div style="margin-bottom:14px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:6px">アクセス可能なNamespace</label>',
'      <div class="ns-check-wrap" id="new-key-ns"></div>',
'    </div>',
'    <button class="btn-admin btn-primary" onclick="createKey()">APIキーを発行</button>',
'  </div>',
'  <div class="admin-section">',
'    <h3>発行済みキー一覧</h3>',
'    <table class="admin-table">',
'      <thead><tr><th>キー（先頭8文字）</th><th>名前</th><th>Namespace</th><th></th></tr></thead>',
'      <tbody id="key-tbody"><tr><td colspan="4" style="color:#64748b;padding:12px">読み込み中...</td></tr></tbody>',
'    </table>',
'  </div>',
'  </div>',
'  <!-- サブタブ: ナレッジ管理 -->',
'  <div class="admin-sub-panel" id="asub-knowledge">',
'  <div class="admin-section">',
'    <h3>❓ FAQ手入力</h3>',
'    <p style="font-size:.78rem;color:#64748b;margin-bottom:10px">1件ずつ質問と回答を登録します。すぐに検索対象になります。</p>',
'    <div style="margin-bottom:10px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">登録先 Namespace</label>',
'      <select class="admin-input" id="faq-ns"></select>',
'    </div>',
'    <div style="margin-bottom:10px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">Question</label>',
'      <input class="admin-input" id="faq-question" type="text" placeholder="例: 定休日はいつですか？">',
'    </div>',
'    <div style="margin-bottom:14px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">Answer</label>',
'      <textarea class="admin-input" id="faq-answer" rows="3" placeholder="例: 毎週水曜日です"></textarea>',
'    </div>',
'    <button class="btn-admin btn-primary" onclick="submitFaq()">登録する</button>',
'  </div>',
'  <div class="admin-section">',
'    <h3>📋 Q&amp;A CSV一括インポート</h3>',
'    <p style="font-size:.78rem;color:#64748b;margin-bottom:10px">1行目にヘッダー（<code>question,answer</code>）が必要です。1ファイルで複数のFAQをまとめて登録できます。</p>',
'    <div style="margin-bottom:10px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">登録先 Namespace</label>',
'      <select class="admin-input" id="csv-ns"></select>',
'    </div>',
'    <div style="margin-bottom:14px">',
'      <input type="file" id="csv-file" accept=".csv,text/csv">',
'    </div>',
'    <button class="btn-admin btn-primary" onclick="submitCsv()">インポート実行</button>',
'    <div id="csv-status" style="font-size:.78rem;color:#94a3b8;margin-top:8px"></div>',
'  </div>',
'  <div class="admin-section">',
'    <h3>📎 ファイルアップロード</h3>',
'    <p style="font-size:.78rem;color:#64748b;margin-bottom:10px">Word・Excel・PowerPoint・PDF・画像・Markdownに対応。アップロードすると自動でテキストを抽出し、検索対象に追加します（画像・PDFはOCRで文字起こしします）。</p>',
'    <div style="margin-bottom:10px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">登録先 Namespace</label>',
'      <select class="admin-input" id="upload-ns"></select>',
'    </div>',
'    <div style="margin-bottom:14px">',
'      <input type="file" id="upload-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.md,.txt,image/*">',
'    </div>',
'    <button class="btn-admin btn-primary" onclick="submitUpload()">アップロード実行</button>',
'    <div id="upload-status" style="font-size:.78rem;color:#94a3b8;margin-top:8px"></div>',
'  </div>',
'  <div class="admin-section">',
'    <h3>🕒 更新履歴</h3>',
'    <table class="admin-table">',
'      <thead><tr><th>日時</th><th>種別</th><th>Namespace</th><th>内容</th><th>チャンク数</th></tr></thead>',
'      <tbody id="knowledge-log-tbody"><tr><td colspan="5" style="color:#64748b;padding:12px">「ナレッジ管理」タブを開くと読み込まれます</td></tr></tbody>',
'    </table>',
'  </div>',
'  </div>',
'  <!-- サブタブ: 使い方 -->',
'  <div class="admin-sub-panel" id="asub-guide">',
'  <div class="admin-section" style="color:#94a3b8">',
'    <h3>外部クライアント (HTTP POST) の使い方</h3>',
'    <p style="margin-bottom:10px">Unity・Houdini・Python・curl など、HTTP POST が使えるクライアントであれば何でも対応しています。</p>',
'    <p style="font-size:.8rem;margin-bottom:6px;color:#64748b">▼ リクエスト</p>',
'    <pre style="background:#0f1117;padding:14px;border-radius:8px;font-size:.78rem;overflow-x:auto;line-height:1.7">',
'POST https://script.google.com/macros/s/SCRIPT_ID/exec\n',
'Content-Type: application/json\n\n',
'{\n',
'  "query":   "AFURIのラーメンは？",\n',
'  "apiKey":  "YOUR_32_CHAR_KEY",\n',
'  "dbKey":   "all",   // "afuri" 等で特定DB、"all" で横断\n',
'  "history": []       // [{role:"user",text:"..."}, ...]\n',
'}',
'    </pre>',
'    <p style="font-size:.8rem;margin-top:14px;margin-bottom:6px;color:#64748b">▼ レスポンス (status: "ok")</p>',
'    <pre style="background:#0f1117;padding:14px;border-radius:8px;font-size:.78rem;overflow-x:auto;line-height:1.7">',
'{\n',
'  "status":            "ok",\n',
'  "answer":            "回答テキスト",\n',
'  "sources":           [{"title":"...","db":"afuri","score":0.91}],\n',
'  "allowedNamespaces": ["afuri","braintq"]\n',
'}',
'    </pre>',
'    <p style="font-size:.8rem;margin-top:14px;margin-bottom:6px;color:#64748b">▼ エラー時のステータス</p>',
'    <table class="admin-table" style="margin-top:0">',
'      <thead><tr><th>status</th><th>原因</th></tr></thead>',
'      <tbody>',
'        <tr><td style="font-family:monospace;color:#f87171">auth_error</td><td>APIキーが無効</td></tr>',
'        <tr><td style="font-family:monospace;color:#fb923c">forbidden</td><td>指定DBへのアクセス権限なし</td></tr>',
'        <tr><td style="font-family:monospace;color:#f87171">error</td><td>サーバー内部エラー</td></tr>',
'      </tbody>',
'    </table>',
'  </div>',
'  </div>',
'</div>',
'</div>',

'<!-- キー表示モーダル -->',
'<div class="key-modal-overlay" id="key-modal">',
'  <div class="key-modal">',
'    <h3 style="margin-bottom:8px;color:#e2e8f0">✅ APIキー発行完了</h3>',
'    <p style="font-size:.8rem;color:#64748b">このキーは一度だけ表示されます。今すぐコピーしてください。</p>',
'    <div class="key-box" id="modal-key-text">—</div>',
'    <p style="font-size:.75rem;color:var(--warn);margin-bottom:14px">⚠ このダイアログを閉じると二度と確認できません</p>',
'    <div style="display:flex;gap:8px">',
'      <button class="btn-admin btn-primary" onclick="copyModalKey()">📋 コピー</button>',
'      <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0" onclick="closeKeyModal()">閉じる</button>',
'    </div>',
'  </div>',
'</div>',
'',
'<!-- namespace編集モーダル -->',
'<div class="key-modal-overlay" id="edit-ns-modal">',
'  <div class="key-modal">',
'    <h3 style="margin-bottom:4px;color:#e2e8f0">🔑 namespace 編集</h3>',
'    <p style="font-size:.78rem;color:#64748b;margin-bottom:14px">キー: <span id="edit-ns-preview" style="font-family:monospace;color:#94a3b8"></span></p>',
'    <div id="edit-ns-checkboxes" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:16px;padding:10px;background:var(--dark3);border-radius:8px;border:1px solid var(--dborder)"></div>',
'    <div style="display:flex;gap:8px">',
'      <button class="btn-admin btn-primary" onclick="saveEditNs()">保存</button>',
'      <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0" onclick="closeEditNs()">キャンセル</button>',
'    </div>',
'  </div>',
'</div>',

'<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>',
'<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>',
'<script>',
'var ALL_NAMESPACES = ' + allNsJson + ';',
'var DB_LABELS = ' + dbLabelsJson + ';',
'var _apiKey = null;',
'var _user   = null;',
'var chatHistory = [];',
'if(typeof marked !== "undefined") marked.setOptions({breaks:true, gfm:true});',

'// ── ログイン ──',
'(function init() {',
'  var saved = localStorage.getItem("rag_api_key");',
'  if (saved) { verifyAndLogin(saved); }',
'})();',

'function doLogin() {',
'  var key = document.getElementById("key-input").value.trim();',
'  if (!key) { showLoginError("APIキーを入力してください"); return; }',
'  document.getElementById("login-btn").disabled = true;',
'  verifyAndLogin(key);',
'}',

'function verifyAndLogin(key) {',
'  google.script.run',
'    .withSuccessHandler(function(info) {',
'      if (!info) {',
'        localStorage.removeItem("rag_api_key");',
'        showLoginError("無効なAPIキーです");',
'        document.getElementById("login-btn").disabled = false;',
'        return;',
'      }',
'      _apiKey = key;',
'      _user   = info;',
'      localStorage.setItem("rag_api_key", key);',
'      onLoginSuccess();',
'    })',
'    .withFailureHandler(function(err) {',
'      showLoginError("エラー: " + (err.message || String(err)));',
'      document.getElementById("login-btn").disabled = false;',
'    })',
'    .getNamespacesForKey(key);',
'}',

'function showLoginError(msg) {',
'  document.getElementById("login-error").textContent = msg;',
'}',

'function onLoginSuccess() {',
'  document.getElementById("login-screen").style.display = "none";',
'  var cs = document.getElementById("chat-screen");',
'  cs.style.display = "flex";',
'  cs.style.flexDirection = "column";',
'  document.getElementById("user-name-badge").textContent = _user.displayName;',
'  buildDbDropdown(_user.namespaces);',
'  var adminBtn = document.getElementById("admin-tab-btn");',
'  if (adminBtn) adminBtn.style.display = _user.isAdmin ? "" : "none";',
'  if (_user.isAdmin) { buildNsCheckboxes(); loadAdminKeys(); }',
'}',

'function doLogout() {',
'  localStorage.removeItem("rag_api_key");',
'  _apiKey = null; _user = null; _historyLoaded = false;',
'  document.getElementById("history-list").innerHTML = "";',
'  document.getElementById("history-status").textContent = "「履歴」タブを開くと読み込まれます";',
'  document.getElementById("chat-screen").style.display = "none";',
'  document.getElementById("login-screen").style.display = "flex";',
'  document.getElementById("key-input").value = "";',
'  document.getElementById("login-error").textContent = "";',
'  document.getElementById("login-btn").disabled = false;',
'  var adminBtn = document.getElementById("admin-tab-btn");',
'  if (adminBtn) adminBtn.style.display = "none";',
'  switchTab("chat");',
'}',

'function buildDbDropdown(namespaces) {',
'  var sel = document.getElementById("db");',
'  sel.innerHTML = \'<option value="all">🌐 全DB横断検索</option>\';',
'  namespaces.forEach(function(ns) {',
'    var opt = document.createElement("option");',
'    opt.value = ns;',
'    opt.textContent = DB_LABELS[ns] || ns;',
'    sel.appendChild(opt);',
'  });',
'}',



'function buildNsCheckboxes() {',
'  var wrap = document.getElementById("new-key-ns");',
'  if (!wrap) return;',
'  wrap.innerHTML = "";',
'  ALL_NAMESPACES.forEach(function(ns) {',
'    var span = document.createElement("span");',
'    span.className = "ns-chk";',
'    span.innerHTML = \'<label><input type="checkbox" value="\' + ns + \'" id="nsc-\' + ns + \'"><span>\' + ns + \'</span></label>\';',
'    wrap.appendChild(span);',
'  });',
'}',

'// ── タブ ──',
'function switchTab(tab) {',
'  ["chat","graph","history","admin"].forEach(function(t) {',
'    var el = document.getElementById("tab-"+t);',
'    if (el) el.style.display = "none";',
'  });',
'  var target = document.getElementById("tab-"+tab);',
'  if (target) {',
'    if (tab === "history") {',
'      target.style.display = "block";',
'      loadHistory();',
'    } else {',
'      target.style.display = "flex";',
'      target.style.flexDirection = "column";',
'    }',
'    if (tab === "graph" && !window._graphLoaded) loadGraph();',
'  }',
'  document.querySelectorAll(".tab-btn").forEach(function(b) {',
'    var isActive = (tab==="chat"&&b.textContent.includes("チャット"))',
'      ||(tab==="graph"&&b.textContent.includes("グラフ"))',
'      ||(tab==="history"&&b.textContent.includes("履歴"))',
'      ||(tab==="admin"&&b.textContent.includes("管理"));',
'    b.classList.toggle("active", isActive);',
'  });',
'}',

'// ── チャット ──',
'var ta = document.getElementById("q");',
'ta.addEventListener("input", function() { this.style.height="auto"; this.style.height=Math.min(this.scrollHeight,120)+"px"; });',
'ta.addEventListener("keydown", function(e) { if((e.ctrlKey||e.metaKey)&&e.key==="Enter") send(); });',

'function md(text) { return (typeof marked !== "undefined") ? marked.parse(text||"") : (text||""); }',

'function addMsg(role, content, sources) {',
'  var chatEl = document.getElementById("chat");',
'  var welcome = chatEl.querySelector(".welcome");',
'  if (welcome) welcome.remove();',
'  var msg    = document.createElement("div"); msg.className = "msg " + role;',
'  var av     = document.createElement("div"); av.className  = "av";',
'  av.textContent = role === "user" ? "👤" : "🤖";',
'  var wrap   = document.createElement("div"); wrap.className = "bwrap";',
'  var bubble = document.createElement("div"); bubble.className = "bubble";',
'  if (role === "bot" && content === "loading") {',
'    bubble.innerHTML = \'<div class="dots"><span></span><span></span><span></span></div>\';',
'  } else if (role === "bot") {',
'    bubble.innerHTML = md(content);',
'  } else {',
'    bubble.textContent = content;',
'  }',
'  wrap.appendChild(bubble);',
'  if (sources && sources.length > 0) wrap.appendChild(buildSources_(sources));',
'  msg.appendChild(av); msg.appendChild(wrap);',
'  chatEl.appendChild(msg); chatEl.scrollTop = chatEl.scrollHeight;',
'  return { bubble: bubble, wrap: wrap };',
'}',

'function buildSources_(sources, extractionRate) {',
'  var div = document.createElement("div"); div.className = "sources";',
'  var citedCount = sources.filter(function(s) { return s.cited; }).length;',
'  var hasExtract = extractionRate !== undefined && extractionRate !== null;',
'  var extractLabel = hasExtract ? "  💡 抽出度: " + citedCount + "/" + sources.length + " (" + extractionRate + "%)" : "";',
'  var btn = document.createElement("button"); btn.className = "src-toggle";',
'  btn.innerHTML = "📎 参考情報 " + sources.length + "件" + extractLabel + " ▾";',
'  var list = document.createElement("div"); list.className = "src-list";',
'  // 情報抽出度バー',
'  if (hasExtract) {',
'    var bar = document.createElement("div"); bar.className = "extract-summary";',
'    bar.innerHTML = \'<span>情報抽出度</span><div class="extract-bar"><div class="extract-fill" style="width:\' + extractionRate + \'%"></div></div><span style="font-weight:600;color:\' + (extractionRate >= 75 ? "#16a34a" : extractionRate >= 50 ? "#d97706" : "#94a3b8") + \'">\' + extractionRate + \'%</span>\';',
'    list.appendChild(bar);',
'  }',
'  sources.forEach(function(s, i) {',
'    var pct  = (s.score * 100).toFixed(1);',
'    var cls  = s.score >= 0.75 ? "high" : s.score >= 0.5 ? "mid" : "low";',
'    var citedBadge = s.cited !== undefined',
'      ? (s.cited ? \'<span class="src-cited">✓ 引用</span>\' : \'<span class="src-not-cited">未引用</span>\')',
'      : "";',
'    var item = document.createElement("div"); item.className = "src-item";',
'    item.innerHTML = (i+1) + ". " + s.title +',
'      \'<span class="src-db">\' + s.db + \'</span>\' +',
'      citedBadge +',
'      \'<span class="src-score \' + cls + \'">\' + pct + \'%</span>\';',
'    list.appendChild(item);',
'  });',
'  btn.onclick = function() {',
'    list.classList.toggle("open");',
'    btn.innerHTML = "📎 参考情報 " + sources.length + "件" + extractLabel + " " + (list.classList.contains("open") ? "▴" : "▾");',
'  };',
'  div.appendChild(btn); div.appendChild(list);',
'  return div;',
'}',

'var isSending = false;',
'function send() {',
'  if (isSending) return;',
'  var q     = ta.value.trim();',
'  var dbKey = document.getElementById("db").value;',
'  if (!q) return;',
'  ta.value = ""; ta.style.height = "auto";',
'  isSending = true; document.getElementById("sbtn").disabled = true;',
'  addMsg("user", q);',
'  var bot  = addMsg("bot", "loading");',
'  var snap = chatHistory.slice();',
'  google.script.run',
'    .withSuccessHandler(function(result) {',
'      isSending = false; document.getElementById("sbtn").disabled = false;',
'      bot.bubble.innerHTML = md(result.answer || "");',
'      if (result.sources && result.sources.length) bot.wrap.appendChild(buildSources_(result.sources, result.extractionRate));',
'      chatHistory.push({role:"user", text:q});',
'      chatHistory.push({role:"bot",  text:result.answer||""});',
'      if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);',
'      document.getElementById("chat").scrollTop = 99999;',
'    })',
'    .withFailureHandler(function(err) {',
'      isSending = false; document.getElementById("sbtn").disabled = false;',
'      bot.bubble.textContent = "エラー: " + (err.message || "Unknown error");',
'    })',
'    .ragQueryWithKey(q, dbKey, snap, _apiKey);',
'}',

'// ── 履歴 ──',
'var _historyLoaded = false;',
'function loadHistory() {',
'  if (_historyLoaded) return;',
'  var status = document.getElementById("history-status");',
'  status.textContent = "読み込み中...";',
'  google.script.run',
'    .withSuccessHandler(function(res) {',
'      _historyLoaded = true;',
'      var list = document.getElementById("history-list");',
'      list.innerHTML = "";',
'      if (!res.records || res.records.length === 0) {',
'        status.textContent = "まだ会話履歴がありません";',
'        return;',
'      }',
'      status.textContent = "";',
'      res.records.forEach(function(r) {',
'        var card = document.createElement("div");',
'        card.className = "hist-card";',
'        var ts = r.timestamp ? new Date(r.timestamp).toLocaleString("ja-JP") : "";',
'        var srcHtml = (r.sources || []).map(function(s) {',
'          return \'<span class="hist-src-tag">\' + s.db + \'</span>\';',
'        }).join("");',
'        var upSel   = r.rating === "up"   ? " selected-up"   : "";',
'        var downSel = r.rating === "down" ? " selected-down" : "";',
'        card.innerHTML =',
'          \'<div class="hist-meta"><span>🕐 \' + ts + \'</span></div>\' +',
'          \'<div class="hist-q">\' + escHtml(r.query) + \'</div>\' +',
'          \'<div class="hist-a" id="ha-\' + r.id + \'">\' + md(r.answer) + \'</div>\' +',
'          \'<div class="hist-sources">\' + srcHtml + \'</div>\' +',
'          \'<div class="hist-rating">\' +',
'          \'<button class="rating-btn\' + upSel + \'" onclick="rateEntry(event,\\\'\' + r.id + \'\\\',\\\'up\\\')">👍</button>\' +',
'          \'<button class="rating-btn\' + downSel + \'" onclick="rateEntry(event,\\\'\' + r.id + \'\\\',\\\'down\\\')">👎</button>\' +',
'          \'</div>\';',
'        card.querySelector(".hist-q").onclick = function() {',
'          var a = document.getElementById("ha-" + r.id);',
'          a.classList.toggle("open");',
'        };',
'        list.appendChild(card);',
'      });',
'    })',
'    .withFailureHandler(function(err) {',
'      document.getElementById("history-status").textContent = "エラー: " + (err.message || String(err));',
'    })',
'    .getUserMemory(_apiKey, 30);',
'}',

'function rateEntry(ev, id, rating) {',
'  ev.stopPropagation();',
'  var btn = ev.currentTarget;',
'  var card = btn.closest(".hist-card");',
'  card.querySelectorAll(".rating-btn").forEach(function(b) {',
'    b.classList.remove("selected-up", "selected-down");',
'  });',
'  btn.classList.add(rating === "up" ? "selected-up" : "selected-down");',
'  google.script.run',
'    .withFailureHandler(function(e) { console.error(e); })',
'    .rateMemoryEntry(_apiKey, id, rating);',
'}',

'function escHtml(s) {',
'  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");',
'}',

'// ── グラフ ──',
'var _graphSim = null, _graphLoaded = false, _graphData = null, _showCrossDb = true;',
'var DB_COLORS = {tool_docs:"#6366f1",game_info:"#10b981",research:"#f59e0b",team_notes:"#ef4444",afuri:"#f97316",braintq:"#8b5cf6",fourteen:"#06b6d4"};',

'function loadGraph() {',
'  var status = document.getElementById("graph-status");',
'  status.textContent = "グラフデータ取得中...";',
'  google.script.run',
'    .withSuccessHandler(function(data) {',
'      if (!data || !data.nodes) { status.textContent = "データが空です"; return; }',
'      _graphData = data; _graphLoaded = true;',
'      renderGraph(data);',
'    })',
'    .withFailureHandler(function(err) { status.textContent = "エラー: " + (err.message || String(err)); })',
'    .getGraphDataWithKey(_apiKey);',
'}',

'function fitGraph() { if (window._d3zoom && window._d3svg) window._d3svg.transition().call(window._d3zoom.transform, d3.zoomIdentity); }',

'function toggleCrossDb() {',
'  _showCrossDb = !_showCrossDb;',
'  var btn = document.getElementById("btn-cross-db");',
'  btn.classList.toggle("active", _showCrossDb);',
'  btn.textContent = _showCrossDb ? "DB跨ぎ表示" : "同一DBのみ";',
'  if (_graphData) renderGraph(_graphData);',
'}',

'function closeNodePanel() { document.getElementById("node-panel").classList.remove("open"); }',

'function showNodeDetail(d, allEdges) {',
'  var panel = document.getElementById("node-panel");',
'  panel.classList.add("open");',
'  document.getElementById("panel-title").textContent = d.label;',
'  document.getElementById("panel-full-title").textContent = d.label;',
'  var badge = document.getElementById("panel-db-badge");',
'  badge.textContent = d.db;',
'  badge.style.background = DB_COLORS[d.db] || "#64748b";',
'  var conns = allEdges.filter(function(e) {',
'    return (e.source.id || e.source) === d.id || (e.target.id || e.target) === d.id;',
'  }).map(function(e) {',
'    var otherId    = ((e.source.id || e.source) === d.id) ? (e.target.id || e.target) : (e.source.id || e.source);',
'    var otherLabel = (e.source.id || e.source) === d.id ? (e.target.label || otherId) : (e.source.label || otherId);',
'    var otherDb    = (e.source.id || e.source) === d.id ? (e.target.db || "") : (e.source.db || "");',
'    return { label: otherLabel, db: otherDb, score: e.score };',
'  }).sort(function(a,b) { return b.score - a.score; });',
'  var html = "";',
'  conns.forEach(function(c) {',
'    html += \'<div class="conn-item">\' +',
'      \'<span class="conn-dot" style="background:\' + (DB_COLORS[c.db]||"#64748b") + \'"></span>\' +',
'      \'<span class="conn-name">\' + c.label + \'</span>\' +',
'      \'<span class="conn-score">\' + (c.score*100).toFixed(1) + \'%</span>\' +',
'      \'</div>\';',
'  });',
'  document.getElementById("panel-connections").innerHTML = html || \'<span style="color:#475569">接続なし</span>\';',
'}',

'function renderGraph(data) {',
'  if (_graphSim) _graphSim.stop();',
'  closeNodePanel();',
'  var svgEl = document.getElementById("graph-svg");',
'  var w = svgEl.clientWidth || 600, h = svgEl.clientHeight || 400;',
'  var svg = d3.select("#graph-svg").attr("width", w).attr("height", h);',
'  svg.selectAll("*").remove(); window._d3svg = svg;',
'  var g = svg.append("g");',
'  var zoom = d3.zoom().scaleExtent([0.1, 6]).on("zoom", function(ev) { g.attr("transform", ev.transform); });',
'  svg.call(zoom); window._d3zoom = zoom;',
'  var nodes = data.nodes.map(function(d) { return Object.assign({}, d); });',
'  var filteredEdges = (data.edges || []).filter(function(e) { return _showCrossDb || !e.cross_db; });',
'  var links = filteredEdges.map(function(e) { return { source: e.source, target: e.target, score: e.score, cross_db: e.cross_db }; });',
'  var link = g.append("g").selectAll("line").data(links).enter().append("line")',
'    .attr("stroke", function(d) { return d.cross_db ? "#6b7280" : "#475569"; })',
'    .attr("stroke-opacity", function(d) { return d.cross_db ? 0.2 : 0.3 + d.score * 0.5; })',
'    .attr("stroke-width", function(d) { return d.cross_db ? 1 : 1.5; })',
'    .attr("stroke-dasharray", function(d) { return d.cross_db ? "4,3" : "none"; });',
'  var node = g.append("g").selectAll("g").data(nodes).enter().append("g")',
'    .call(d3.drag()',
'      .on("start", function(ev, d) { if (!ev.active) _graphSim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })',
'      .on("drag",  function(ev, d) { d.fx = ev.x; d.fy = ev.y; })',
'      .on("end",   function(ev, d) { if (!ev.active) _graphSim.alphaTarget(0); d.fx = null; d.fy = null; }))',
'    .on("click", function(ev, d) { showNodeDetail(d, link.data()); });',
'  node.append("circle").attr("r", 12)',
'    .attr("fill", function(d) { return DB_COLORS[d.db] || "#64748b"; })',
'    .attr("stroke", "#0f172a").attr("stroke-width", 1.5)',
'    .on("mouseover", function() { d3.select(this).attr("r", 16).attr("stroke", "#fbbf24"); })',
'    .on("mouseout",  function() { d3.select(this).attr("r", 12).attr("stroke", "#0f172a"); });',
'  node.append("text")',
'    .text(function(d) { return d.label.length > 12 ? d.label.slice(0, 12) + "…" : d.label; })',
'    .attr("x", 15).attr("y", 4).attr("font-size", "10px").attr("fill", "#cbd5e1");',
'  _graphSim = d3.forceSimulation(nodes)',
'    .force("link",      d3.forceLink(links).id(function(d) { return d.id; }).distance(function(d) { return d.cross_db ? 200 : 80; }).strength(function(d) { return d.cross_db ? 0.05 : d.score; }))',
'    .force("charge",    d3.forceManyBody().strength(-250))',
'    .force("center",    d3.forceCenter(w/2, h/2))',
'    .force("collision", d3.forceCollide(20))',
'    .on("tick", function() {',
'      link.attr("x1", function(d) { return d.source.x; }).attr("y1", function(d) { return d.source.y; })',
'          .attr("x2", function(d) { return d.target.x; }).attr("y2", function(d) { return d.target.y; });',
'      node.attr("transform", function(d) { return "translate(" + d.x + "," + d.y + ")"; });',
'    });',
'  var sameDbCount = links.filter(function(l) { return !l.cross_db; }).length;',
'  var crossCount  = links.filter(function(l) { return l.cross_db; }).length;',
'  document.getElementById("graph-status").textContent =',
'    nodes.length + "ノード / " + links.length + "エッジ" +',
'    (crossCount > 0 ? " (DB跨ぎ:" + crossCount + ")" : "");',
'}',

'// ── 管理サブタブ ──',
'function switchAdminSub(tab) {',
'  ["keys","knowledge","guide"].forEach(function(t) {',
'    var panel = document.getElementById("asub-"+t);',
'    var btn   = document.getElementById("asub-"+t+"-btn");',
'    if (panel) panel.classList.toggle("active", t === tab);',
'    if (btn)   btn.classList.toggle("active",   t === tab);',
'  });',
'  if (tab === "knowledge") {',
'    populateNsSelects();',
'    loadKnowledgeLog();',
'  }',
'}',

'// ── 管理画面 ──',
'function loadAdminKeys() {',
'  if (!_user || !_user.isAdmin) return;',
'  google.script.run',
'    .withSuccessHandler(function(keys) {',
'      var tbody = document.getElementById("key-tbody");',
'      if (!tbody) return;',
'      tbody.innerHTML = "";',
'      (keys || []).forEach(function(k) {',
'        var tr  = document.createElement("tr");',
'        var ns  = (k.namespaces || []).join(", ") || "(なし)";',
'        var adm = k.isAdmin ? \'<span class="badge-admin">管理者</span>\' : "";',
'        var currentNsJson = JSON.stringify(k.namespaces || []).replace(/"/g, "&quot;");',
'        tr.innerHTML =',
'          \'<td style="font-family:monospace">\' + k.keyPreview + \'</td>\' +',
'          \'<td>\' + k.displayName + adm + \'</td>\' +',
'          \'<td style="font-size:.72rem;color:#94a3b8">\' + ns + \'</td>\' +',
'          \'<td style="display:flex;gap:6px">\' +',
'            \'<button class="btn-admin btn-sm" style="background:#334155;color:#e2e8f0" onclick="openEditNs(\\\'\' + k.keyPreview + \'\\\',\' + currentNsJson.replace(/\'/g,"\\\\\'") + \')">編集</button>\' +',
'            \'<button class="btn-admin btn-danger btn-sm" onclick="deleteKey(\\\'\' + k.keyPreview + \'\\\')">削除</button></td>\';',
'        tbody.appendChild(tr);',
'      });',
'    })',
'    .withFailureHandler(function(e) { adminFlash("キー取得失敗: " + e.message, true); })',
'    .adminListKeys(_apiKey);',
'}',

'function createKey() {',
'  var name   = document.getElementById("new-key-name").value.trim();',
'  var ns     = Array.from(document.querySelectorAll("#new-key-ns input:checked")).map(function(i) { return i.value; });',
'  var isAdm  = document.getElementById("new-key-admin").checked;',
'  if (!name) { adminFlash("名前を入力してください", true); return; }',
'  google.script.run',
'    .withSuccessHandler(function(newKey) {',
'      document.getElementById("modal-key-text").textContent = newKey;',
'      document.getElementById("key-modal").classList.add("show");',
'      document.getElementById("new-key-name").value = "";',
'      document.getElementById("new-key-admin").checked = false;',
'      document.querySelectorAll("#new-key-ns input").forEach(function(i) { i.checked = false; });',
'      loadAdminKeys();',
'    })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminCreateKey(_apiKey, name, ns, isAdm);',
'}',

'function deleteKey(preview) {',
'  if (!confirm(preview + " を削除しますか？")) return;',
'  google.script.run',
'    .withSuccessHandler(function() { adminFlash("削除しました"); loadAdminKeys(); })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminDeleteKey(_apiKey, preview);',
'}',
'',
'var _editNsPreview = null;',
'function openEditNs(preview, currentNs) {',
'  _editNsPreview = preview;',
'  var modal = document.getElementById("edit-ns-modal");',
'  if (!modal) return;',
'  var wrap = document.getElementById("edit-ns-checkboxes");',
'  wrap.innerHTML = "";',
'  ALL_NAMESPACES.forEach(function(ns) {',
'    var chk = document.createElement("label");',
'    chk.style.cssText = "display:inline-flex;align-items:center;gap:4px;margin:3px 6px 3px 0;font-size:.8rem;color:#e2e8f0;cursor:pointer";',
'    var input = document.createElement("input");',
'    input.type = "checkbox"; input.value = ns;',
'    input.checked = currentNs.indexOf(ns) !== -1;',
'    chk.appendChild(input);',
'    chk.appendChild(document.createTextNode(DB_LABELS[ns] || ns));',
'    wrap.appendChild(chk);',
'  });',
'  document.getElementById("edit-ns-preview").textContent = preview;',
'  modal.classList.add("show");',
'}',
'function closeEditNs() {',
'  var modal = document.getElementById("edit-ns-modal");',
'  if (modal) modal.classList.remove("show");',
'  _editNsPreview = null;',
'}',
'function saveEditNs() {',
'  if (!_editNsPreview) return;',
'  var ns = Array.from(document.querySelectorAll("#edit-ns-checkboxes input:checked")).map(function(i) { return i.value; });',
'  google.script.run',
'    .withSuccessHandler(function() { adminFlash("namespace を更新しました"); closeEditNs(); loadAdminKeys(); })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminUpdateKey(_apiKey, _editNsPreview, ns);',
'}',

'function copyModalKey() {',
'  var key = document.getElementById("modal-key-text").textContent;',
'  navigator.clipboard.writeText(key).then(function() { adminFlash("コピーしました"); });',
'}',

'// ── ナレッジ管理 ──',
'function populateNsSelects() {',
'  ["faq-ns","csv-ns","upload-ns"].forEach(function(id) {',
'    var sel = document.getElementById(id);',
'    if (!sel || sel.options.length > 0) return;',
'    ALL_NAMESPACES.forEach(function(ns) {',
'      var opt = document.createElement("option");',
'      opt.value = ns; opt.textContent = DB_LABELS[ns] || ns;',
'      sel.appendChild(opt);',
'    });',
'  });',
'}',

'function submitFaq() {',
'  var ns = document.getElementById("faq-ns").value;',
'  var q  = document.getElementById("faq-question").value.trim();',
'  var a  = document.getElementById("faq-answer").value.trim();',
'  if (!q || !a) { adminFlash("QuestionとAnswerを入力してください", true); return; }',
'  google.script.run',
'    .withSuccessHandler(function(res) {',
'      adminFlash("FAQを登録しました（" + res.chunks + "チャンク）");',
'      document.getElementById("faq-question").value = "";',
'      document.getElementById("faq-answer").value = "";',
'      loadKnowledgeLog();',
'    })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminAddFaq(_apiKey, ns, q, a);',
'}',

'function readFileAsBase64_(file, cb) {',
'  var reader = new FileReader();',
'  reader.onload = function() { cb(reader.result.split(",")[1]); };',
'  reader.readAsDataURL(file);',
'}',
'function readFileAsText_(file, cb) {',
'  var reader = new FileReader();',
'  reader.onload = function() { cb(reader.result); };',
'  reader.readAsText(file, "UTF-8");',
'}',

'function submitCsv() {',
'  var ns   = document.getElementById("csv-ns").value;',
'  var file = document.getElementById("csv-file").files[0];',
'  var status = document.getElementById("csv-status");',
'  if (!file) { adminFlash("CSVファイルを選択してください", true); return; }',
'  status.textContent = "インポート中...";',
'  readFileAsText_(file, function(text) {',
'    google.script.run',
'      .withSuccessHandler(function(res) {',
'        status.textContent = "";',
'        adminFlash(res.total + "件中 " + res.success + "件を登録しました" + (res.error > 0 ? "（失敗: " + res.error + "件）" : ""));',
'        document.getElementById("csv-file").value = "";',
'        loadKnowledgeLog();',
'      })',
'      .withFailureHandler(function(e) { status.textContent = ""; adminFlash(e.message, true); })',
'      .adminImportFaqCsv(_apiKey, ns, text);',
'  });',
'}',

'function submitUpload() {',
'  var ns   = document.getElementById("upload-ns").value;',
'  var file = document.getElementById("upload-file").files[0];',
'  var status = document.getElementById("upload-status");',
'  if (!file) { adminFlash("ファイルを選択してください", true); return; }',
'  status.textContent = "アップロード・解析中...（ファイルによっては数十秒かかります）";',
'  readFileAsBase64_(file, function(base64) {',
'    google.script.run',
'      .withSuccessHandler(function(res) {',
'        status.textContent = "";',
'        adminFlash(file.name + " を登録しました（" + res.chunks + "チャンク）");',
'        document.getElementById("upload-file").value = "";',
'        loadKnowledgeLog();',
'      })',
'      .withFailureHandler(function(e) { status.textContent = ""; adminFlash(e.message, true); })',
'      .adminUploadKnowledgeFile(_apiKey, base64, file.name, file.type || "application/octet-stream", ns);',
'  });',
'}',

'function loadKnowledgeLog() {',
'  google.script.run',
'    .withSuccessHandler(function(rows) {',
'      var tbody = document.getElementById("knowledge-log-tbody");',
'      if (!tbody) return;',
'      if (!rows || rows.length === 0) {',
'        tbody.innerHTML = \'<tr><td colspan="5" style="color:#64748b;padding:12px">まだ履歴がありません</td></tr>\';',
'        return;',
'      }',
'      tbody.innerHTML = "";',
'      rows.forEach(function(r) {',
'        var tr = document.createElement("tr");',
'        var ts = r.timestamp ? new Date(r.timestamp).toLocaleString("ja-JP") : "";',
'        tr.innerHTML =',
'          "<td style=\\"font-size:.75rem;color:#94a3b8\\">" + ts + "</td>" +',
'          "<td>" + r.type + "</td>" +',
'          "<td>" + (DB_LABELS[r.db] || r.db) + "</td>" +',
'          "<td style=\\"max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap\\">" + r.label + "</td>" +',
'          "<td>" + r.chunkCount + "</td>";',
'        tbody.appendChild(tr);',
'      });',
'    })',
'    .withFailureHandler(function(e) { adminFlash("履歴取得失敗: " + e.message, true); })',
'    .adminGetKnowledgeLog(_apiKey, 30);',
'}',

'function closeKeyModal() { document.getElementById("key-modal").classList.remove("show"); }',

'function adminFlash(msg, isErr) {',
'  var el = document.getElementById("admin-flash");',
'  if (!el) return;',
'  el.textContent = msg;',
'  el.className = "admin-flash " + (isErr ? "err" : "ok");',
'  el.style.display = "block";',
'  setTimeout(function() { el.style.display = "none"; }, 3000);',
'}',
'</script>',
'</body></html>',
  ].join('\n');
}

// ─────────────────────────────────────────────
// 初回セットアップ（GASエディタから実行）
// ─────────────────────────────────────────────

/**
 * 初回のみ実行。管理者APIキーをログに出力する。
 * キーを安全な場所に保存してから、ブラウザでログイン。
 */
function bootstrapFirstAdminKey() {
  var existing = getApiKeysConfig_();
  var hasAdmin = false;
  for (var i = 0; i < existing.length; i++) {
    if (existing[i].isAdmin) { hasAdmin = true; break; }
  }
  if (hasAdmin) {
    Logger.log('管理者キーは既に存在します。追加発行する場合は管理画面から行ってください。');
    return;
  }
  var newKey = Utilities.getUuid().replace(/-/g, '');
  existing.push({
    key:         newKey,
    displayName: '管理者',
    namespaces:  ALL_NAMESPACES,
    isAdmin:     true,
    createdAt:   new Date().toISOString(),
  });
  saveApiKeysConfig_(existing);
  Logger.log('========================================');
  Logger.log('管理者APIキー (一度だけ表示)');
  Logger.log(newKey);
  Logger.log('このキーを安全な場所に保存してください。');
  Logger.log('========================================');
}

// ─────────────────────────────────────────────
// デバッグ用（GASエディタから実行）
// ─────────────────────────────────────────────

function testEmbedding() {
  var vec = embed_('テスト');
  Logger.log(vec ? ('✅ OK  次元数: ' + vec.length) : '❌ NG');
}

function testSearch() {
  var results = searchByEmbedding_('AFURIのラーメン', 'afuri', 3, null);
  results.forEach(function(r) {
    Logger.log('[' + (r.score*100).toFixed(1) + '%] ' + r.title + ' (' + r.db + ')');
  });
}

function testRagQuery() {
  var result = ragQueryInternal_('AFURIについて教えてください', 'afuri', [], ALL_NAMESPACES);
  Logger.log('=== 回答 ===\n' + result.answer);
}
