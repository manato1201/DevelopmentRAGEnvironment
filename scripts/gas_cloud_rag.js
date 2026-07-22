/**
 * Cloud RAG Chatbot — Google Apps Script  v4 (APIキー認証統一版)
 *
 * ── スクリプトプロパティ ──────────────────────────────────────────────
 *   NOTION_API_KEY     Notion Integration Token
 *   GEMINI_API_KEY     Google AI Studio API Key
 *   SHEETS_ID          ベクトル保存用スプレッドシートID
 *   NAMESPACE_CONFIG   namespace定義（JSON、省略可。テナント導入手順書参照）
 *   DB_TOOL_DOCS / DB_GAME_INFO / DB_RESEARCH / DB_TEAM_NOTES
 *   DB_AFURI / DB_BRAINTQ / DB_FOURTEEN  (各Notion DB ID。キー名は
 *   NAMESPACE_CONFIG のnamespaceキーから "DB_" + 大文字化 で自動導出される)
 *
 *   API_KEYS_CONFIG    ← 自動管理（管理画面で操作）
 *
 * ── 初回セットアップ ─────────────────────────────────────────────────
 *   1. 上記スクリプトプロパティを設定（NAMESPACE_CONFIGは新規テナント導入時
 *      のみ設定。未設定なら下記のAXTechCare向けデフォルト構成が使われる）
 *   2. GASエディタで bootstrapFirstAdminKey() を実行
 *      → ログに管理者APIキーが表示される（一度だけ）
 *   3. WebAppをデプロイ:
 *        次のユーザーとして実行: 自分 (Me)
 *        アクセスできるユーザー: Googleアカウントを持つ全員
 *   4. WebAppのURLにブラウザでアクセスし、管理者キーでログイン
 *   5. 管理タブからユーザーキー / クライアントキーを発行
 *
 *   新規テナント（他プロジェクト・他社）へのテンプレートとして導入する
 *   場合は docs/tenant-onboarding.md を参照。
 * ────────────────────────────────────────────────────────────────────
 */

// ─────────────────────────────────────────────
// 定数（namespace構成）
// ─────────────────────────────────────────────

// NAMESPACE_CONFIG スクリプトプロパティが未設定の場合に使う、
// このデプロイ（AXTechCare本体）向けのデフォルト構成。
// 新規テナント導入時はコードを変更せず、NAMESPACE_CONFIG に
// 同じ形のJSONを設定することで namespace 構成を差し替えられる。
var DEFAULT_NAMESPACE_CONFIG_ = {
  tool_docs:  { label: '🛠️ Tool Docs' },
  game_info:  { label: '🎮 Game Info' },
  research:   { label: '📄 Research' },
  team_notes: { label: '📝 Team Notes' },
  afuri:      { label: '🍜 AFURI' },
  braintq:    { label: '🧠 BrainTQ' },
  fourteen:   { label: '⛳ Fourteen' },
  houdini21:  { label: '🌀 Houdini21' },
};

/** namespaceキーからスクリプトプロパティ名の接尾辞を作る（例: "tool_docs" → "TOOL_DOCS"） */
function _namespacePropSuffix_(ns) {
  return String(ns).toUpperCase().replace(/-/g, '_');
}

function _loadNamespaceConfig_() {
  var raw;
  try { raw = PropertiesService.getScriptProperties().getProperty('NAMESPACE_CONFIG'); }
  catch (e) { raw = null; }
  if (raw) {
    try {
      var parsed = JSON.parse(raw);
      if (parsed && Object.keys(parsed).length > 0) return parsed;
    } catch (e) { /* 不正なJSONはデフォルトにフォールバック */ }
  }
  return DEFAULT_NAMESPACE_CONFIG_;
}

var _NAMESPACE_CONFIG_ = _loadNamespaceConfig_();

// DB_KEY_MAP・DB_LABELS・DRIVE_KEY_MAP は _NAMESPACE_CONFIG_ から導出する。
// プロパティ名の命名規則（"DB_" / "DRIVE_" + namespace大文字）は、
// 既存のAXTechCareデプロイのスクリプトプロパティ名と完全に一致するため、
// NAMESPACE_CONFIG を設定しない既存デプロイの動作は変わらない。
var DB_KEY_MAP    = {};
var DB_LABELS     = {};
var DRIVE_KEY_MAP = {};
// namespaceごとの登録先モード: "notion"（既定・従来通り） / "drive"（Drive単独運用） / "both"（両方に登録）
var NAMESPACE_SOURCE_MAP = {};
Object.keys(_NAMESPACE_CONFIG_).forEach(function(ns) {
  var suffix = _namespacePropSuffix_(ns);
  DB_KEY_MAP[ns]    = 'DB_' + suffix;
  DRIVE_KEY_MAP[ns] = 'DRIVE_' + suffix;
  DB_LABELS[ns]     = (_NAMESPACE_CONFIG_[ns] && _NAMESPACE_CONFIG_[ns].label) || ns;
  NAMESPACE_SOURCE_MAP[ns] = (_NAMESPACE_CONFIG_[ns] && _NAMESPACE_CONFIG_[ns].source) || 'notion';
});

/** このnamespaceがNotionを使うか（"notion" / "both"。既定はnotion） */
function _usesNotion_(dbKey) { return NAMESPACE_SOURCE_MAP[dbKey] !== 'drive'; }
/** このnamespaceがDriveを使うか（"drive" / "both"） */
function _usesDrive_(dbKey) {
  var s = NAMESPACE_SOURCE_MAP[dbKey];
  return s === 'drive' || s === 'both';
}

var ALL_NAMESPACES   = Object.keys(DB_KEY_MAP);
var SHEET_NAME       = 'RAG_Index';
var MEMORY_SHEET     = 'RAG_Memory';
var IDX_CACHE_KEY    = 'rag_idx_v2';
var CACHE_TTL        = 21600;
var CACHE_CHUNK      = 90000;

// 許可された DB キーの一覧。不正値は "all" にフォールバックして安全に処理する。
var VALID_DB_KEYS_ = ["all"].concat(ALL_NAMESPACES);

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

/**
 * 評価（👍/👎）の集計（管理者のみ）。
 * MIN_SCORE閾値・HyDE重み等のグローバルなチューニングパラメータは評価に
 * 応じて自動調整されるわけではないため、この集計を見て人間が判断する
 * 運用を想定している（docs/cloud-rag.md §7.5 参照）。
 */
function adminRatingStats(apiKey) {
  requireAdmin_(apiKey);
  var sheet = getMemorySheet_();
  var stats = { total: 0, up: 0, down: 0, unrated: 0, downByDb: {} };
  if (!sheet) return stats;

  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    var rating = String(data[i][6]);
    stats.total++;
    if (rating === 'up') stats.up++;
    else if (rating === 'down') stats.down++;
    else stats.unrated++;

    if (rating === 'down') {
      try {
        var sources = JSON.parse(String(data[i][5]) || '[]');
        sources.forEach(function(s) {
          var db = s.db || '(不明)';
          stats.downByDb[db] = (stats.downByDb[db] || 0) + 1;
        });
      } catch(e) {}
    }
  }
  return stats;
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
    // mode:'raw' は Function Calling 等の低レイテンシ用途向け。最終回答生成をスキップし検索結果のみ返す。
    var isRaw   = body.mode === 'raw';

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

    var result  = ragQueryInternal_(query, dbKey, history, allowed, apiKey, { skipAnswer: isRaw });
    var memId   = '';
    if (!isRaw) {
      try { memId = saveMemory_(apiKey, query, result.answer, result.sources); } catch(e) {}
    }
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

function ragQueryInternal_(query, dbKey, history, allowedNamespaces, apiKey, opts) {
  opts = opts || {};
  var skipAnswer = !!opts.skipAnswer;
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

  // raw モード: Function Calling 等、呼び出し元が自分で最終回答を組み立てる場合に使う。
  // 検索結果のテキストだけを返し、最終回答生成のGemini呼び出し(直列で一番重い)を丸ごと省略してレイテンシを削減する。
  if (skipAnswer) {
    var seen_ = {}, rawSources = [];
    results.forEach(function(r) {
      var key = r.db + '::' + r.title;
      if (!seen_[key]) {
        seen_[key] = true;
        rawSources.push({ title: r.title, db: r.db, score: r.score, text: r.text });
      }
    });
    return { answer: '', sources: rawSources };
  }

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
    // クエリと仮説文書の埋め込みは互いに独立しているため、直列fetchではなくfetchAllで並列実行する
    var embResps = UrlFetchApp.fetchAll([
      embedRequest_(query, 'RETRIEVAL_QUERY'),
      embedRequest_(hypoDoc, 'RETRIEVAL_DOCUMENT'),
    ]);
    var queryEmb = parseEmbedResponse_(embResps[0]);
    var hypoEmb  = parseEmbedResponse_(embResps[1]);
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

function embedRequest_(text, taskType) {
  var apiKey  = getProps_().getProperty('GEMINI_API_KEY');
  var payload = {
    model:   'models/gemini-embedding-001',
    content: { parts: [{ text: text.substring(0, 2000) }] },
    outputDimensionality: 768,
  };
  if (taskType) payload.taskType = taskType;
  return {
    url: 'https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=' + apiKey,
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify(payload), muteHttpExceptions: true,
  };
}

function parseEmbedResponse_(res) {
  if (res.getResponseCode() !== 200) { Logger.log('Embed error: ' + res.getContentText().substring(0, 200)); return null; }
  return JSON.parse(res.getContentText()).embedding.values;
}

function embed_(text, taskType) {
  var req = embedRequest_(text, taskType);
  return parseEmbedResponse_(UrlFetchApp.fetch(req.url, req));
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

function syncNotionToSheets() {
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

  var rowsToDelete = [], updateList = [], totalSkip = 0;
  listResps.forEach(function(res, i) {
    var key = reqKeys[i];
    if (res.getResponseCode() !== 200) { Logger.log('[' + key + '] エラー: ' + res.getResponseCode()); return; }
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
  var bodyResps   = UrlFetchApp.fetchAll(bodyReqs);
  var TEXT_TYPES  = { paragraph:1, heading_1:1, heading_2:1, heading_3:1, bulleted_list_item:1, numbered_list_item:1, quote:1, callout:1, toggle:1, code:1 };

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
    var d     = JSON.parse(res.getContentText());
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
    p2reqs.push({ url: 'https://api.notion.com/v1/blocks/' + item.pd.page_id + '/children?page_size=100&start_cursor=' + item.p2cursor, method: 'get', headers: nHeaders, muteHttpExceptions: true });
  });
  if (p2reqs.length > 0) {
    UrlFetchApp.fetchAll(p2reqs).forEach(function(res, j) {
      var idx   = p2idx[j];
      var extra = (res.getResponseCode() === 200) ? extractLines_(JSON.parse(res.getContentText()).results || []) : [];
      bodies[idx] = updateList[idx].p1lines.concat(extra).join('\n').substring(0, 8000);
    });
  }
  bodies = bodies.map(function(b) { return b === null ? '' : b; });

  var allChunks = [];
  updateList.forEach(function(item, i) {
    var full   = item.pd.meta_text + (bodies[i] ? '\n\n' + bodies[i] : '');
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

// ─────────────────────────────────────────────
// Google Drive 同期（Notionに追加するデータソース）
//
// DRIVE_KEY_MAP で dbKey ごとに紐付けたフォルダ（直下のファイルのみ、
// サブフォルダは対象外）を走査し、Notion同期と同じ RAG_Index シートに
// チャンク化・埋め込みして追記する。page_id 相当は 'drive_' + ファイルID。
// 変更検知は Drive のファイル更新日時（getLastUpdated）を Notion の
// last_edited 相当として使い、前回と同じなら再変換をスキップする。
// ─────────────────────────────────────────────

/** Notion 同期（GASエディタから手動実行、または時間主導トリガー） */
function syncDriveToSheets() {
  var props = getProps_();
  var sheet = getSheet_();
  var data  = sheet.getDataRange().getValues();

  var existingMap = {};
  for (var i = 1; i < data.length; i++) {
    var baseId = String(data[i][0]).split('::')[0];
    if (!existingMap[baseId]) existingMap[baseId] = { rowIndices: [], lastEdited: data[i][4] };
    existingMap[baseId].rowIndices.push(i + 1);
  }

  var rowsToDelete = [], newRows = [], totalOk = 0, totalSkip = 0, totalErr = 0, foldersUsed = 0;

  Object.keys(DRIVE_KEY_MAP).forEach(function(dbKey) {
    var folderId = props.getProperty(DRIVE_KEY_MAP[dbKey]);
    if (!folderId) return;
    foldersUsed++;

    var folder;
    try { folder = DriveApp.getFolderById(folderId); }
    catch(e) { Logger.log('[drive:' + dbKey + '] フォルダを開けません: ' + e.message); totalErr++; return; }

    var files = folder.getFiles();
    while (files.hasNext()) {
      var file = files.next();
      if (file.isTrashed()) continue;
      var fileId      = 'drive_' + file.getId();
      var lastEdited  = file.getLastUpdated().toISOString();
      var existing    = existingMap[fileId];
      if (existing && existing.lastEdited === lastEdited) { totalSkip++; continue; }

      var text = '';
      try { text = extractDriveFileText_(file); }
      catch(e) { Logger.log('[drive] 抽出失敗 ' + file.getName() + ': ' + e.message); totalErr++; continue; }
      if (!text || !text.trim()) { totalErr++; continue; }

      if (existing) rowsToDelete = rowsToDelete.concat(existing.rowIndices);

      var chunks = chunkText_('# ' + file.getName() + '\n' + text.substring(0, 40000), 500, 100);
      chunks.forEach(function(chunk, k) {
        var emb = embedDoc_(chunk.substring(0, 2000));
        if (!emb) return;
        newRows.push([fileId + '::' + k, dbKey, file.getName(), chunk, lastEdited, JSON.stringify(emb)]);
        totalOk++;
      });
    }
  });

  rowsToDelete.sort(function(a, b) { return b - a; });
  rowsToDelete.forEach(function(ri) { sheet.deleteRow(ri); });
  if (newRows.length > 0) sheet.getRange(sheet.getLastRow() + 1, 1, newRows.length, 6).setValues(newRows);
  Logger.log('Drive同期完了  フォルダ:' + foldersUsed + '  チャンク:' + totalOk + '  スキップ:' + totalSkip + '  エラー:' + totalErr);
  invalidateIndexCache_();
  return { folders: foldersUsed, chunks: totalOk, skipped: totalSkip, errors: totalErr };
}

/** Driveファイル1件からテキストを抽出する。Googleネイティブ形式はそのまま、それ以外はOCR変換 */
function extractDriveFileText_(file) {
  var mime = file.getMimeType();
  var native = _extractNativeGoogleText_(file.getId(), mime);
  if (native) return native;
  if (mime === MimeType.PLAIN_TEXT || mime === 'text/markdown' || mime === MimeType.CSV) {
    return file.getBlob().getDataAsString('UTF-8');
  }
  return _convertBinaryBlobToText_(file.getBlob(), file.getName());
}

/** Drive同期を今すぐ実行する（管理者のみ、WebAppから呼び出し可能） */
function adminSyncDrive(apiKey) {
  requireAdmin_(apiKey);
  return syncDriveToSheets();
}

/** DBキーごとに設定されているDriveフォルダIDの一覧を返す（管理者のみ） */
function adminGetDriveFolders(apiKey) {
  requireAdmin_(apiKey);
  var props = getProps_();
  var out = {};
  Object.keys(DRIVE_KEY_MAP).forEach(function(dbKey) {
    out[dbKey] = props.getProperty(DRIVE_KEY_MAP[dbKey]) || '';
  });
  return out;
}

/** DBキーに対応するDriveフォルダIDを設定・解除する（管理者のみ） */
function adminSetDriveFolder(apiKey, dbKey, folderId) {
  requireAdmin_(apiKey);
  if (!DRIVE_KEY_MAP[dbKey]) throw new Error('無効なdbKeyです: ' + dbKey);
  var props = getProps_();
  folderId = (folderId || '').trim();
  if (!folderId) {
    props.deleteProperty(DRIVE_KEY_MAP[dbKey]);
    return { ok: true, cleared: true };
  }
  // フォルダIDの妥当性を確認（アクセスできない/存在しない場合はエラー）
  try { DriveApp.getFolderById(folderId); }
  catch(e) { throw new Error('このフォルダIDにアクセスできません。共有設定を確認してください: ' + folderId); }
  props.setProperty(DRIVE_KEY_MAP[dbKey], folderId);
  return { ok: true, cleared: false };
}

// ─────────────────────────────────────────────
// バックアップ（管理者向け）
//
// RAG_Index は Notion から syncNotionToSheets() で再生成できるが、
// RAG_Memory（ユーザーの過去Q&A・評価履歴）・KB_Log（ナレッジ登録履歴）・
// API_KEYS_CONFIG（発行済みAPIキー一覧）はこのスプレッドシート/スクリプト
// プロパティにしか存在しない、再生成不可能なデータである。
// GASエディタから backupCriticalData_() を手動実行するか、時間主導トリガー
// で定期実行することを想定している。
// ─────────────────────────────────────────────

/** シートの全内容をCSV文字列に変換する */
function sheetToCsv_(sheet) {
  var data = sheet.getDataRange().getValues();
  return data.map(function(row) {
    return row.map(function(cell) {
      var s = String(cell == null ? '' : cell).replace(/"/g, '""');
      return '"' + s + '"';
    }).join(',');
  }).join('\n');
}

/**
 * RAG_Memory・KB_Log・API_KEYS_CONFIG をGoogle Driveの専用フォルダに
 * タイムスタンプ付きでエクスポートする（管理者のみ、GASエディタから手動実行）。
 */
function backupCriticalData_() {
  var timestamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone() || 'Etc/UTC', 'yyyyMMdd_HHmmss');
  var folder = DriveApp.createFolder('rag_backup_' + timestamp);
  var filesCreated = [];

  var memSheet = getMemorySheet_();
  if (memSheet && memSheet.getLastRow() > 0) {
    var memFile = folder.createFile('RAG_Memory_' + timestamp + '.csv', sheetToCsv_(memSheet), MimeType.CSV);
    filesCreated.push(memFile.getName());
  }

  var kbSheet = getKbLogSheet_();
  if (kbSheet && kbSheet.getLastRow() > 0) {
    var kbFile = folder.createFile('KB_Log_' + timestamp + '.csv', sheetToCsv_(kbSheet), MimeType.CSV);
    filesCreated.push(kbFile.getName());
  }

  var apiKeysJson = JSON.stringify(getApiKeysConfig_(), null, 2);
  var keyFile = folder.createFile('API_KEYS_CONFIG_' + timestamp + '.json', apiKeysJson, MimeType.PLAIN_TEXT);
  filesCreated.push(keyFile.getName());

  Logger.log('バックアップ完了: ' + folder.getUrl() + '  ファイル: ' + filesCreated.join(', '));
  return { folderUrl: folder.getUrl(), files: filesCreated };
}

/** バックアップを管理画面（WebApp）から実行するための管理者API */
function adminBackupNow(apiKey) {
  requireAdmin_(apiKey);
  return backupCriticalData_();
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
// ナレッジ登録（管理者向け）
//
// 登録先は namespace の source 設定（NAMESPACE_SOURCE_MAP）に従う。
// 既定（"notion"）は従来通り Notion のみ、"drive" は Google ドライブのみ、
// "both" は両方に登録する（Driveにも同じ内容が溜まる）。
// 作成したページ/ドキュメントはその場でチャンク化・埋め込みして
// RAG_Index シートにも反映するため、次回の syncNotionToSheets /
// syncDriveToSheets を待たずに検索可能になる。
// 操作は KB_Log シートに記録し、ロールバック時は登録先（Notion/Drive）
// それぞれのアーカイブ・削除 + インデックス行の削除を行う。
// ─────────────────────────────────────────────

var KB_LOG_SHEET = 'KB_Log';

function notionHeaders_() {
  return {
    'Authorization':  'Bearer ' + getProps_().getProperty('NOTION_API_KEY'),
    'Notion-Version': '2022-06-28',
  };
}

function getKbLogSheet_() {
  var ss    = SpreadsheetApp.openById(getProps_().getProperty('SHEETS_ID'));
  var sheet = ss.getSheetByName(KB_LOG_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(KB_LOG_SHEET);
    sheet.appendRow(['op_id', 'timestamp', 'type', 'db', 'title', 'page_ids', 'status']);
    sheet.getRange(1, 1, 1, 7).setFontWeight('bold');
  }
  return sheet;
}

function kbNewOpId_() {
  return new Date().getTime().toString(36) + Math.random().toString(36).slice(2, 6);
}

/** namespaceのNotion DB IDを取得する（未設定ならnull） */
function kbNotionDbId_(dbKey) { return getProps_().getProperty(DB_KEY_MAP[dbKey]) || null; }
/** namespaceのDrive保存先フォルダIDを取得する（未設定ならnull） */
function kbDriveFolderId_(dbKey) { return getProps_().getProperty(DRIVE_KEY_MAP[dbKey]) || null; }

/** namespaceのsource設定に応じて、登録先が正しく設定されているか検証する（未設定ならthrow） */
function kbCheckDb_(apiKey, dbKey) {
  requireAdmin_(apiKey);
  if (!DB_KEY_MAP[dbKey]) throw new Error('保存先DBを選択してください: ' + dbKey);
  if (_usesNotion_(dbKey) && !kbNotionDbId_(dbKey)) {
    throw new Error('このDBのNotion IDが未設定です: ' + dbKey);
  }
  if (_usesDrive_(dbKey) && !kbDriveFolderId_(dbKey)) {
    throw new Error('このDBのDriveフォルダが未設定です: ' + dbKey);
  }
}

/** Notion にページを作成して { id, lastEdited } を返す */
function kbCreateNotionPage_(dbId, title, summary, sourceUrl, bodyText) {
  var properties = { title: { title: [{ text: { content: title.substring(0, 200) } }] } };
  if (summary)   properties.summary    = { rich_text: [{ text: { content: summary.substring(0, 1900) } }] };
  if (sourceUrl) properties.source_url = { url: sourceUrl };

  var children = [];
  var body = (bodyText || '').substring(0, 40000);
  for (var i = 0; i < body.length && children.length < 95; i += 1800) {
    children.push({ object: 'block', type: 'paragraph',
      paragraph: { rich_text: [{ text: { content: body.substring(i, i + 1800) } }] } });
  }

  function create_(props) {
    return UrlFetchApp.fetch('https://api.notion.com/v1/pages', {
      method: 'post', headers: notionHeaders_(), contentType: 'application/json',
      payload: JSON.stringify({ parent: { database_id: dbId }, properties: props, children: children }),
      muteHttpExceptions: true,
    });
  }
  var res = create_(properties);
  if (res.getResponseCode() === 400 && (summary || sourceUrl)) {
    // summary / source_url プロパティがないDBでは title のみで再試行
    res = create_({ title: properties.title });
  }
  if (res.getResponseCode() !== 200) {
    throw new Error('Notionページの作成に失敗しました: ' + res.getContentText().substring(0, 300));
  }
  var page = JSON.parse(res.getContentText());
  return { id: page.id, lastEdited: page.last_edited_time || new Date().toISOString() };
}

/** 作成したページをその場でチャンク化・埋め込みしてインデックスに追加する */
function kbIndexPage_(pageId, lastEdited, dbKey, title, fullText) {
  var sheet  = getSheet_();
  var chunks = chunkText_('# ' + title + '\n' + fullText, 500, 100);
  var rows   = [];
  chunks.forEach(function(chunk, k) {
    var emb = embedDoc_(chunk.substring(0, 2000));
    if (!emb) return;
    rows.push([pageId + '::' + k, dbKey, title, chunk, lastEdited, JSON.stringify(emb)]);
  });
  if (rows.length > 0) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 6).setValues(rows);
  }
  invalidateIndexCache_();
  return rows.length;
}

/**
 * 指定フォルダにGoogleドキュメントを新規作成する。
 * DocumentApp.create() はマイドライブ直下に作成するため、作成後に
 * 対象フォルダへ付け替える（GASの定石パターン）。
 * 戻り値は syncDriveToSheets の extractDriveFileText_ でそのまま再抽出できる形式。
 */
function kbCreateDriveDoc_(folderId, title, bodyText) {
  var doc = DocumentApp.create(title.substring(0, 200));
  doc.getBody().setText(bodyText || '');
  doc.saveAndClose();
  var file = DriveApp.getFileById(doc.getId());
  DriveApp.getFolderById(folderId).addFile(file);
  try { DriveApp.getRootFolder().removeFile(file); } catch(e) {}
  return { id: file.getId(), lastEdited: new Date().toISOString() };
}

/**
 * namespaceのsource設定（notion/drive/both）に応じて1件をNotion/Drive
 * （またはその両方）へ書き込み、即時インデックスする。KB_Logへの記録は
 * 呼び出し元（kbRegister_ または一括登録のループ）が行う。
 */
function kbWriteAndIndex_(dbKey, title, summary, sourceUrl, bodyText) {
  var fullText = (summary ? summary + '\n' : '') + bodyText;
  var targets  = []; // { source: 'notion'|'drive', id, lastEdited }
  var chunks   = 0;

  if (_usesNotion_(dbKey)) {
    var page = kbCreateNotionPage_(kbNotionDbId_(dbKey), title, summary, sourceUrl, bodyText);
    chunks += kbIndexPage_(page.id, page.lastEdited, dbKey, title, fullText);
    targets.push({ source: 'notion', id: page.id, lastEdited: page.lastEdited });
  }
  if (_usesDrive_(dbKey)) {
    var doc = kbCreateDriveDoc_(kbDriveFolderId_(dbKey), title, fullText);
    // syncDriveToSheets と同じ 'drive_' + fileId 形式のIDでインデックスし、
    // ロールバック・重複判定の互換性を保つ。
    chunks += kbIndexPage_('drive_' + doc.id, doc.lastEdited, dbKey, title, fullText);
    targets.push({ source: 'drive', id: doc.id, lastEdited: doc.lastEdited });
  }
  return { targets: targets, chunks: chunks };
}

/** 登録の共通パス（単発）: source設定に応じて書き込み → KB_Log 記録 */
function kbRegister_(dbKey, title, summary, sourceUrl, bodyText, type, opId) {
  opId = opId || kbNewOpId_();
  var result = kbWriteAndIndex_(dbKey, title, summary, sourceUrl, bodyText);
  getKbLogSheet_().appendRow([opId, new Date().toISOString(), type, dbKey,
                              title.substring(0, 100), JSON.stringify(result.targets), 'done']);
  return { opId: opId, targets: result.targets, title: title, chunks: result.chunks };
}

/** HTMLからテキストを抽出する簡易パーサ */
function kbStripHtml_(html) {
  var text = String(html || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<(br|\/p|\/div|\/li|\/h[1-6]|\/tr)[^>]*>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  return text.replace(/[ \t]+/g, ' ').replace(/\n\s*\n\s*\n+/g, '\n\n').trim();
}

/** URL取り込み（社内Wiki・Webページ） */
function adminKbImportUrl(apiKey, dbKey, url) {
  kbCheckDb_(apiKey, dbKey);
  if (!/^https?:\/\//.test(url || '')) throw new Error('URLは http:// または https:// で始まる必要があります');
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
  if (res.getResponseCode() !== 200) throw new Error('ページを取得できませんでした（HTTP ' + res.getResponseCode() + '）');
  var html  = res.getContentText();
  var m     = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  var title = m ? kbStripHtml_(m[1]).substring(0, 100) : url;
  var text  = kbStripHtml_(html);
  if (!text) throw new Error('ページからテキストを抽出できませんでした');
  return kbRegister_(dbKey, title || url, '', url, text.substring(0, 40000), 'url');
}

/** FAQ手入力 */
function adminKbAddFaq(apiKey, dbKey, question, answer) {
  kbCheckDb_(apiKey, dbKey);
  question = (question || '').trim();
  answer   = (answer   || '').trim();
  if (!question || !answer) throw new Error('質問と回答の両方を入力してください');
  var body = '質問: ' + question + '\n\n回答: ' + answer;
  return kbRegister_(dbKey, 'Q: ' + question.substring(0, 90), answer.substring(0, 200), '', body, 'faq');
}

/** Q&A CSV 一括登録（1列目=質問、2列目=回答。ヘッダー行は自動判定） */
function adminKbImportQaCsv(apiKey, dbKey, csvText) {
  kbCheckDb_(apiKey, dbKey);
  var rows = Utilities.parseCsv(csvText || '');
  if (!rows.length) throw new Error('CSVを読み取れませんでした');
  var start  = 0;
  var head0  = String(rows[0][0] || '').toLowerCase();
  var head1  = String((rows[0][1] || '')).toLowerCase();
  if (['question', '質問', 'q'].indexOf(head0) !== -1 || ['answer', '回答', 'a'].indexOf(head1) !== -1) start = 1;

  var pairs = [];
  for (var i = start; i < rows.length; i++) {
    var q = String(rows[i][0] || '').trim();
    var a = String(rows[i][1] || '').trim();
    if (q && a) pairs.push([q, a]);
  }
  if (!pairs.length) throw new Error('有効なQ&A行が見つかりませんでした（1列目=質問、2列目=回答）');
  if (pairs.length > 100) throw new Error('一度に登録できるのは100行までです（' + pairs.length + '行あります）。分割してください');

  var opId = kbNewOpId_(), allTargets = [], chunks = 0;
  pairs.forEach(function(p) {
    var result = kbWriteAndIndex_(dbKey, 'Q: ' + p[0].substring(0, 90), p[1].substring(0, 200), '',
                                  '質問: ' + p[0] + '\n\n回答: ' + p[1]);
    chunks += result.chunks;
    allTargets = allTargets.concat(result.targets);
  });
  getKbLogSheet_().appendRow([opId, new Date().toISOString(), 'qa_csv', dbKey,
                              'Q&A CSV ' + pairs.length + '件', JSON.stringify(allTargets), 'done']);
  return { opId: opId, pages: allTargets.length, chunks: chunks, title: 'Q&A CSV ' + pairs.length + '件' };
}

/** YouTube動画（字幕の自動取得を試み、失敗時は文字起こしの貼り付けを促す） */
function adminKbImportYoutube(apiKey, dbKey, videoUrl, transcript) {
  kbCheckDb_(apiKey, dbKey);
  var m = String(videoUrl || '').match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w\-]{6,})/);
  if (!m) throw new Error('YouTubeのURLを入力してください（例: https://www.youtube.com/watch?v=...）');
  var videoId = m[1];

  var text = (transcript || '').trim();
  if (!text) {
    // 公開字幕の取得を試みる（自動生成字幕は取得できないことが多い）
    var langs = ['ja', 'en'];
    for (var i = 0; i < langs.length && !text; i++) {
      try {
        var res = UrlFetchApp.fetch('https://video.google.com/timedtext?v=' + videoId + '&lang=' + langs[i],
                                    { muteHttpExceptions: true });
        if (res.getResponseCode() === 200) {
          var xml = res.getContentText();
          var parts = xml.match(/<text[^>]*>([\s\S]*?)<\/text>/g) || [];
          text = parts.map(function(t) { return kbStripHtml_(t); }).join(' ').trim();
        }
      } catch(e) {}
    }
  }
  if (!text) {
    throw new Error('この動画の字幕を自動取得できませんでした。動画の文字起こしテキストを「文字起こしを貼り付け」欄に貼ってから再実行してください');
  }
  return kbRegister_(dbKey, 'YouTube: ' + videoId, '', videoUrl, text.substring(0, 40000), 'youtube');
}

/**
 * ドキュメントアップロード（PDF・Word・Excel・PPT・画像）
 * Drive API（拡張サービス）でGoogle形式に変換してテキスト抽出する。
 * GASエディタの「サービス」から Drive API を追加しておくこと。
 */
/** Google形式ファイル（Doc/Sheet/Slide）からテキストを抽出する共通ヘルパー。非対応形式は空文字を返す */
function _extractNativeGoogleText_(fileId, mimeType) {
  if (mimeType === 'application/vnd.google-apps.document') {
    return DocumentApp.openById(fileId).getBody().getText();
  }
  if (mimeType === 'application/vnd.google-apps.spreadsheet') {
    var out = '';
    SpreadsheetApp.openById(fileId).getSheets().forEach(function(sh) {
      sh.getDataRange().getValues().forEach(function(row) {
        var line = row.filter(function(c) { return String(c).trim(); }).join(' | ');
        if (line) out += line + '\n';
      });
    });
    return out;
  }
  if (mimeType === 'application/vnd.google-apps.presentation') {
    var out2 = '';
    SlidesApp.openById(fileId).getSlides().forEach(function(slide) {
      slide.getShapes().forEach(function(shape) {
        try { out2 += shape.getText().asString() + '\n'; } catch(e) {}
      });
    });
    return out2;
  }
  return '';
}

/**
 * バイナリ（PDF・Word・Excel・PowerPoint・画像等）を Drive API でOCR変換してテキスト抽出する。
 * 変換で作られる一時ファイルは抽出後に削除する。
 */
function _convertBinaryBlobToText_(blob, displayName) {
  if (typeof Drive === 'undefined') {
    throw new Error('この形式の取り込みには Drive API が必要です。GASエディタ左の「サービス +」から Drive API を追加してください');
  }
  var converted = Drive.Files.insert({ title: '[RAG一時] ' + displayName }, blob, { convert: true, ocr: true });
  try {
    var text = _extractNativeGoogleText_(converted.id, converted.mimeType);
    if (!text) {
      try { text = DriveApp.getFileById(converted.id).getBlob().getDataAsString('UTF-8'); } catch(e) {}
    }
    return text;
  } finally {
    try { Drive.Files.remove(converted.id); }
    catch(e) { try { DriveApp.getFileById(converted.id).setTrashed(true); } catch(e2) {} }
  }
}

function adminKbUploadDoc(apiKey, dbKey, filename, base64Data, mimeType) {
  kbCheckDb_(apiKey, dbKey);
  var blob = Utilities.newBlob(Utilities.base64Decode(base64Data), mimeType || 'application/octet-stream', filename);
  var text = _convertBinaryBlobToText_(blob, filename);
  if (!text || !text.trim()) throw new Error('ファイルからテキストを抽出できませんでした: ' + filename);
  var title = String(filename).replace(/\.[^.]+$/, '');
  return kbRegister_(dbKey, title, '', '', text.substring(0, 40000), 'file');
}

/** 登録履歴 */
function adminKbHistory(apiKey, limit) {
  requireAdmin_(apiKey);
  limit = limit || 50;
  var data = getKbLogSheet_().getDataRange().getValues();
  var out  = [];
  for (var i = data.length - 1; i >= 1 && out.length < limit; i--) {
    var pages = 0;
    try { pages = JSON.parse(String(data[i][5]) || '[]').length; } catch(e) {}
    out.push({
      opId:      String(data[i][0]),
      timestamp: String(data[i][1]),
      type:      String(data[i][2]),
      db:        String(data[i][3]),
      title:     String(data[i][4]),
      pages:     pages,
      status:    String(data[i][6]),
    });
  }
  return out;
}

/** ロールバック: 登録先（Notionページ・Driveファイル）を削除し、インデックス行を削除する */
function adminKbRollback(apiKey, opId) {
  requireAdmin_(apiKey);
  var logSheet = getKbLogSheet_();
  var data     = logSheet.getDataRange().getValues();
  var rowIdx   = -1;
  for (var i = data.length - 1; i >= 1; i--) {
    if (opId) { if (String(data[i][0]) === opId) { rowIdx = i; break; } }
    else if (String(data[i][6]) === 'done') { rowIdx = i; break; }
  }
  if (rowIdx === -1) throw new Error('取り消せる操作が見つかりません');
  if (String(data[rowIdx][6]) !== 'done') throw new Error('この操作は既に取り消し済みです');

  var raw = [];
  try { raw = JSON.parse(String(data[rowIdx][5]) || '[]'); } catch(e) {}
  // 旧形式（Notionページidの文字列配列）・新形式（{source, id}オブジェクト配列）の両方に対応
  var targets = raw.map(function(t) {
    return (typeof t === 'string') ? { source: 'notion', id: t } : t;
  });
  var notionIds = [], driveIds = [];
  targets.forEach(function(t) {
    if (t.source === 'drive') driveIds.push(t.id); else notionIds.push(t.id);
  });

  // Notion ページをアーカイブ（ゴミ箱へ。Notion側から復元は可能）
  notionIds.forEach(function(pid) {
    try {
      UrlFetchApp.fetch('https://api.notion.com/v1/pages/' + pid, {
        method: 'patch', headers: notionHeaders_(), contentType: 'application/json',
        payload: JSON.stringify({ archived: true }), muteHttpExceptions: true,
      });
    } catch(e) {}
  });

  // Driveファイルをゴミ箱へ（Drive側から復元は可能）
  driveIds.forEach(function(fid) {
    try { DriveApp.getFileById(fid).setTrashed(true); } catch(e) {}
  });

  // インデックス行を削除（Notionはハイフン有無どちらの形式でも照合、Driveは 'drive_' + fileId で照合）
  var idSet = {};
  notionIds.forEach(function(p) { idSet[p] = true; idSet[String(p).replace(/-/g, '')] = true; });
  driveIds.forEach(function(f) { idSet['drive_' + f] = true; });
  var idxSheet = getSheet_();
  var idxData  = idxSheet.getDataRange().getValues();
  var toDelete = [];
  for (var r = 1; r < idxData.length; r++) {
    var base = String(idxData[r][0]).split('::')[0];
    if (idSet[base] || idSet[base.replace(/-/g, '')]) toDelete.push(r + 1);
  }
  toDelete.sort(function(a, b) { return b - a; });
  toDelete.forEach(function(ri) { idxSheet.deleteRow(ri); });

  logSheet.getRange(rowIdx + 1, 7).setValue('rolled_back');
  invalidateIndexCache_();
  return {
    ok: true, opId: String(data[rowIdx][0]),
    archivedPages: notionIds.length, deletedDriveFiles: driveIds.length, deletedRows: toDelete.length,
  };
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
'.breakdown-wrap{padding:7px 11px;background:#f8fafc;border-bottom:1px solid var(--border)}',
'.breakdown-label{font-size:10px;color:var(--text-light);margin-bottom:4px}',
'.breakdown-bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:#e2e8f0}',
'.breakdown-seg{height:100%;transition:width .4s;min-width:2px}',
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
'#mic-btn{width:42px;height:42px;background:var(--white);color:var(--text);border:1.5px solid var(--border);',
'  border-radius:12px;cursor:pointer;font-size:16px;display:flex;align-items:center;',
'  justify-content:center;transition:all .2s;flex-shrink:0}',
'#mic-btn:hover{border-color:var(--primary)}',
'#mic-btn.recording{background:#fee2e2;border-color:#dc2626;color:#dc2626;animation:mic-pulse 1s infinite}',
'@keyframes mic-pulse{0%,100%{opacity:1}50%{opacity:.5}}',
'.speak-btn{background:none;border:none;color:var(--text-light);cursor:pointer;font-size:13px;',
'  padding:2px 4px;margin-left:4px}',
'.speak-btn:hover{color:var(--primary)}',
'.speak-btn.speaking{color:var(--primary);animation:mic-pulse 1s infinite}',
'.voice-toggle{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text-light);',
'  cursor:pointer;user-select:none;white-space:nowrap}',
'.voice-toggle input{accent-color:var(--primary);cursor:pointer}',

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
'  <label class="voice-toggle" id="auto-read-wrap" style="display:none">',
'    <input type="checkbox" id="auto-read-check"> 🔊 自動読み上げ',
'  </label>',
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
'    <button id="mic-btn" onclick="toggleMic()" style="display:none" title="音声入力">🎤</button>',
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
'    <button class="admin-sub-btn" id="asub-kb-btn" onclick="switchAdminSub(\'kb\')">📚 ナレッジ登録</button>',
'    <button class="admin-sub-btn" id="asub-drive-btn" onclick="switchAdminSub(\'drive\')">🗂 Drive連携</button>',
'    <button class="admin-sub-btn" id="asub-ratings-btn" onclick="switchAdminSub(\'ratings\')">📊 評価</button>',
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
'  <!-- サブタブ: ナレッジ登録 -->',
'  <div class="admin-sub-panel" id="asub-kb">',
'  <div class="admin-section" style="border-color:var(--accent)">',
'    <h3>📁 覚えさせた知識のしまい先</h3>',
'    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">',
'      <select class="admin-input" id="kb-db" style="width:auto;min-width:200px"></select>',
'      <span style="font-size:.75rem;color:#64748b">※ 下のどの方法で追加しても、ここで選んだDB（Notion）に保存されます</span>',
'    </div>',
'  </div>',
'  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px">',
'  <div class="admin-section" style="margin-bottom:0">',
'    <h3>🌐 Webページを覚えさせる</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:10px">社内WikiやWebページのURLを貼り付けるだけで、内容を読み取って覚えます。</p>',
'    <input class="admin-input" id="kb-url" type="text" placeholder="https://... を貼り付け" style="margin-bottom:10px">',
'    <button class="btn-admin btn-primary" onclick="kbImportUrl()">このページを覚える</button>',
'    <div id="kb-url-status" style="font-size:.76rem;margin-top:8px;min-height:16px"></div>',
'  </div>',
'  <div class="admin-section" style="margin-bottom:0">',
'    <h3>📄 資料ファイルを覚えさせる</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:10px">PDF・Word・Excel・PowerPoint・画像（文字入り）を選ぶと、内容を読み取って覚えます。</p>',
'    <input type="file" id="kb-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.png,.jpg,.jpeg" style="color:#94a3b8;font-size:.8rem;margin-bottom:10px;max-width:100%">',
'    <button class="btn-admin btn-primary" onclick="kbUploadDoc()">このファイルを覚える</button>',
'    <div id="kb-file-status" style="font-size:.76rem;margin-top:8px;min-height:16px"></div>',
'  </div>',
'  <div class="admin-section" style="margin-bottom:0">',
'    <h3>❓ FAQを書いて覚えさせる</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:10px">「この質問が来たらこう答えてほしい」を1件ずつ登録できます。</p>',
'    <input class="admin-input" id="kb-faq-q" type="text" placeholder="質問（例: 営業時間は？）" style="margin-bottom:8px">',
'    <textarea class="admin-input" id="kb-faq-a" rows="3" placeholder="回答（例: 平日10時〜19時です）" style="margin-bottom:10px;resize:vertical;font-family:inherit"></textarea>',
'    <button class="btn-admin btn-primary" onclick="kbAddFaq()">このFAQを覚える</button>',
'    <div id="kb-faq-status" style="font-size:.76rem;margin-top:8px;min-height:16px"></div>',
'  </div>',
'  <div class="admin-section" style="margin-bottom:0">',
'    <h3>📋 Q&A表（CSV）をまとめて覚えさせる</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:10px">1列目=質問、2列目=回答のCSV（Excelから「CSVで保存」）で、最大100件を一度に登録できます。</p>',
'    <input type="file" id="kb-csv" accept=".csv,.txt" style="color:#94a3b8;font-size:.8rem;margin-bottom:10px;max-width:100%">',
'    <button class="btn-admin btn-primary" onclick="kbImportCsv()">このCSVを覚える</button>',
'    <div id="kb-csv-status" style="font-size:.76rem;margin-top:8px;min-height:16px"></div>',
'  </div>',
'  <div class="admin-section" style="margin-bottom:0">',
'    <h3>▶️ YouTube動画を覚えさせる</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:10px">動画URLを貼り付けると字幕の取得を試みます。取得できない場合は、動画の「文字起こしを表示」からコピーして下の欄に貼ってください。</p>',
'    <input class="admin-input" id="kb-yt-url" type="text" placeholder="https://www.youtube.com/watch?v=..." style="margin-bottom:8px">',
'    <textarea class="admin-input" id="kb-yt-transcript" rows="3" placeholder="（任意）文字起こしを貼り付け" style="margin-bottom:10px;resize:vertical;font-family:inherit"></textarea>',
'    <button class="btn-admin btn-primary" onclick="kbImportYoutube()">この動画を覚える</button>',
'    <div id="kb-yt-status" style="font-size:.76rem;margin-top:8px;min-height:16px"></div>',
'  </div>',
'  </div>',
'  <div class="admin-section" style="margin-top:16px">',
'    <h3>📜 覚えさせた履歴</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:10px">間違えて覚えさせたときは「なかったことにする」で、その学習だけを取り消せます（Notionページはゴミ箱に移動します）。</p>',
'    <table class="admin-table">',
'      <thead><tr><th>いつ</th><th>方法</th><th>内容</th><th>DB</th><th>状態</th><th></th></tr></thead>',
'      <tbody id="kb-hist-tbody"><tr><td colspan="6" style="color:#64748b;padding:12px">「ナレッジ登録」タブを開くと読み込まれます</td></tr></tbody>',
'    </table>',
'  </div>',
'  </div>',
'  <!-- サブタブ: Drive連携 -->',
'  <div class="admin-sub-panel" id="asub-drive">',
'  <div class="admin-section">',
'    <h3>🗂 Google Drive をデータソースに追加</h3>',
'    <p style="font-size:.78rem;color:#94a3b8;margin-bottom:6px">DBごとにGoogle Driveのフォルダを1つ紐付けると、そのフォルダ直下のファイル（PDF・Word・Excel・PowerPoint・Googleドキュメント等）もNotionと同じように検索対象になります。サブフォルダは対象外です。</p>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:14px">※ フォルダはこのGASを実行しているGoogleアカウントと共有しておく必要があります。PDF・Word等の変換にはGASエディタで Drive API サービスの追加が必要です。</p>',
'    <table class="admin-table">',
'      <thead><tr><th>DB</th><th>DriveフォルダID</th><th></th></tr></thead>',
'      <tbody id="drive-folder-tbody"><tr><td colspan="3" style="color:#64748b;padding:12px">「Drive連携」タブを開くと読み込まれます</td></tr></tbody>',
'    </table>',
'  </div>',
'  <div class="admin-section">',
'    <h3>🔄 今すぐ同期</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:12px">登録したフォルダを読み直し、変更があったファイルだけをチャンク化・埋め込みして反映します。ファイル数が多いと数分かかることがあります。</p>',
'    <button class="btn-admin btn-primary" onclick="driveSyncNow()">今すぐ同期する</button>',
'    <div id="drive-sync-status" style="font-size:.78rem;margin-top:10px;color:#94a3b8"></div>',
'  </div>',
'  <div class="admin-section">',
'    <h3>💾 重要データのバックアップ</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:12px">会話履歴（RAG_Memory）・ナレッジ登録履歴（KB_Log）・発行済みAPIキー一覧は、このスプレッドシート/スクリプトプロパティにしか存在せず、Notionから再生成できません。実行すると、このGASを実行しているGoogleアカウントのDriveに「rag_backup_日時」フォルダを作成してCSV/JSONで保存します。</p>',
'    <button class="btn-admin btn-primary" onclick="backupNow()">今すぐバックアップする</button>',
'    <div id="backup-status" style="font-size:.78rem;margin-top:10px;color:#94a3b8"></div>',
'  </div>',
'  </div>',
'  <!-- サブタブ: 評価 -->',
'  <div class="admin-sub-panel" id="asub-ratings">',
'  <div class="admin-section">',
'    <h3>📊 評価（👍/👎）の集計</h3>',
'    <p style="font-size:.78rem;color:#94a3b8;margin-bottom:14px">この集計はMIN_SCORE閾値・HyDE重み等のグローバルなチューニングパラメータには自動反映されません。👎が多いDBがあれば、そのDBのHyDEドメインヒント（<code>hydePromptFor_</code>）や検索閾値（<code>MIN_SCORE</code>）を見直す判断材料にしてください。詳細は「使い方」タブ、またはdocs/cloud-rag.md §7.5を参照。</p>',
'    <div id="ratings-summary" style="display:flex;gap:24px;margin-bottom:16px;font-size:.85rem;color:#e2e8f0">読み込み中...</div>',
'    <h3 style="font-size:.85rem;margin-bottom:8px">👎 が多いDB（要チューニング候補）</h3>',
'    <table class="admin-table">',
'      <thead><tr><th>DB</th><th style="text-align:right">👎件数</th></tr></thead>',
'      <tbody id="ratings-bydb-tbody"><tr><td colspan="2" style="color:#64748b">「評価」タブを開くと読み込まれます</td></tr></tbody>',
'    </table>',
'    <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0;margin-top:12px" onclick="loadRatingStats()">更新</button>',
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

'// ── 音声（バーバルコミュニケーション対応） ──',
'var _SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;',
'var _sttSupported = !!_SpeechRecognition;',
'var _ttsSupported = "speechSynthesis" in window;',
'var _recognizer = null;',
'var _recording  = false;',
'var _speakingBtn = null;',

'function toggleMic() {',
'  if (!_sttSupported) return;',
'  if (_recording) { _recognizer && _recognizer.stop(); return; }',
'  _recognizer = new _SpeechRecognition();',
'  _recognizer.lang = "ja-JP";',
'  _recognizer.interimResults = false;',
'  _recognizer.maxAlternatives = 1;',
'  var btn = document.getElementById("mic-btn");',
'  _recognizer.onstart = function() { _recording = true; btn.classList.add("recording"); };',
'  _recognizer.onresult = function(e) {',
'    var said = e.results[0][0].transcript;',
'    ta.value = (ta.value ? ta.value + " " : "") + said;',
'    ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 120) + "px";',
'  };',
'  _recognizer.onerror = function(e) {',
'    if (e.error !== "aborted" && e.error !== "no-speech") console.log("音声入力エラー: " + e.error);',
'  };',
'  _recognizer.onend = function() { _recording = false; btn.classList.remove("recording"); };',
'  _recognizer.start();',
'}',

'function speak(text) {',
'  if (!_ttsSupported) return null;',
'  window.speechSynthesis.cancel();',
'  var plain = String(text || "").replace(/[#*`_>-]/g, " ").replace(/\\s+/g, " ").trim();',
'  if (!plain) return null;',
'  var utter = new SpeechSynthesisUtterance(plain);',
'  utter.lang = "ja-JP"; utter.rate = 1.0;',
'  window.speechSynthesis.speak(utter);',
'  return utter;',
'}',

'function toggleSpeak(btn, text) {',
'  if (!_ttsSupported) return;',
'  if (_speakingBtn === btn && window.speechSynthesis.speaking) {',
'    window.speechSynthesis.cancel();',
'    btn.classList.remove("speaking"); _speakingBtn = null;',
'    return;',
'  }',
'  if (_speakingBtn) _speakingBtn.classList.remove("speaking");',
'  var utter = speak(text);',
'  if (!utter) return;',
'  _speakingBtn = btn; btn.classList.add("speaking");',
'  utter.onend = function() { btn.classList.remove("speaking"); if (_speakingBtn === btn) _speakingBtn = null; };',
'}',

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
'  if (_sttSupported) document.getElementById("mic-btn").style.display = "";',
'  if (_ttsSupported) document.getElementById("auto-read-wrap").style.display = "flex";',
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
'  if (_ttsSupported) window.speechSynthesis.cancel();',
'  if (_recording && _recognizer) _recognizer.stop();',
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
'    if (_ttsSupported) {',
'      var sbtn = document.createElement("button");',
'      sbtn.className = "speak-btn"; sbtn.title = "読み上げ"; sbtn.textContent = "🔊";',
'      sbtn.onclick = function() { toggleSpeak(sbtn, content); };',
'      bubble.appendChild(sbtn);',
'    }',
'  } else {',
'    bubble.textContent = content;',
'  }',
'  wrap.appendChild(bubble);',
'  if (sources && sources.length > 0) wrap.appendChild(buildSources_(sources));',
'  msg.appendChild(av); msg.appendChild(wrap);',
'  chatEl.appendChild(msg); chatEl.scrollTop = chatEl.scrollHeight;',
'  return { bubble: bubble, wrap: wrap };',
'}',

'// 引用元ごとの相対的な貢献度（スコア比）を積み上げバーで可視化する',
'var BREAKDOWN_PALETTE_ = ["#6366f1","#8b5cf6","#ec4899","#f59e0b","#10b981","#06b6d4","#f43f5e","#84cc16"];',
'function buildBreakdown_(sources) {',
'  var cited = sources.filter(function(s) { return s.cited; });',
'  if (cited.length < 2) return null;',
'  var total = cited.reduce(function(sum, s) { return sum + Math.max(s.score, 0.01); }, 0);',
'  var wrap  = document.createElement("div"); wrap.className = "breakdown-wrap";',
'  var label = document.createElement("div"); label.className = "breakdown-label";',
'  label.textContent = "📊 引用元の内訳（貢献度の比率）";',
'  var bar = document.createElement("div"); bar.className = "breakdown-bar";',
'  cited.forEach(function(s, i) {',
'    var pct = Math.round(Math.max(s.score, 0.01) / total * 100);',
'    var seg = document.createElement("div"); seg.className = "breakdown-seg";',
'    seg.style.width = pct + "%";',
'    seg.style.background = BREAKDOWN_PALETTE_[i % BREAKDOWN_PALETTE_.length];',
'    seg.title = s.title + "（" + s.db + "）: " + pct + "%";',
'    bar.appendChild(seg);',
'  });',
'  wrap.appendChild(label); wrap.appendChild(bar);',
'  return wrap;',
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
'  // 引用元の内訳（どこからどのくらい引き出したかを可視化）',
'  var breakdown = buildBreakdown_(sources);',
'  if (breakdown) list.appendChild(breakdown);',
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
'      var answerText = result.answer || "";',
'      bot.bubble.innerHTML = md(answerText);',
'      if (_ttsSupported) {',
'        var sbtn = document.createElement("button");',
'        sbtn.className = "speak-btn"; sbtn.title = "読み上げ"; sbtn.textContent = "🔊";',
'        sbtn.onclick = function() { toggleSpeak(sbtn, answerText); };',
'        bot.bubble.appendChild(sbtn);',
'        if (document.getElementById("auto-read-check").checked) speak(answerText);',
'      }',
'      if (result.sources && result.sources.length) bot.wrap.appendChild(buildSources_(result.sources, result.extractionRate));',
'      chatHistory.push({role:"user", text:q});',
'      chatHistory.push({role:"bot",  text:answerText});',
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
'  ["keys","kb","drive","ratings","guide"].forEach(function(t) {',
'    var panel = document.getElementById("asub-"+t);',
'    var btn   = document.getElementById("asub-"+t+"-btn");',
'    if (panel) panel.classList.toggle("active", t === tab);',
'    if (btn)   btn.classList.toggle("active",   t === tab);',
'  });',
'  if (tab === "kb") kbInitCloud();',
'  if (tab === "drive") driveInit();',
'  if (tab === "ratings") loadRatingStats();',
'}',

'function loadRatingStats() {',
'  var summary = document.getElementById("ratings-summary");',
'  var tbody   = document.getElementById("ratings-bydb-tbody");',
'  google.script.run',
'    .withSuccessHandler(function(s) {',
'      var rated = s.up + s.down;',
'      var upPct = rated ? Math.round(s.up / rated * 100) : 0;',
'      summary.innerHTML =',
'        "<div>合計: <strong>" + s.total + "</strong>件</div>" +',
'        "<div style=\\"color:#4ade80\\">👍 " + s.up + "件</div>" +',
'        "<div style=\\"color:#f87171\\">👎 " + s.down + "件</div>" +',
'        "<div style=\\"color:#64748b\\">未評価 " + s.unrated + "件</div>" +',
'        "<div>評価済みの👍率: <strong>" + upPct + "%</strong></div>";',
'      var entries = Object.keys(s.downByDb).map(function(db) { return [db, s.downByDb[db]]; });',
'      entries.sort(function(a, b) { return b[1] - a[1]; });',
'      if (!entries.length) {',
'        tbody.innerHTML = \'<tr><td colspan="2" style="color:#64748b">👎はまだありません</td></tr>\';',
'        return;',
'      }',
'      tbody.innerHTML = entries.map(function(e) {',
'        return "<tr><td>" + (DB_LABELS[e[0]] || e[0]) + "</td><td style=\\"text-align:right\\">" + e[1] + "</td></tr>";',
'      }).join("");',
'    })',
'    .withFailureHandler(function(e) { summary.textContent = "読み込み失敗: " + e.message; })',
'    .adminRatingStats(_apiKey);',
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

'function closeKeyModal() { document.getElementById("key-modal").classList.remove("show"); }',

'// ── ナレッジ登録 ──',
'var KB_TYPE_LABELS = { url: "🌐 Webページ", youtube: "▶️ YouTube", file: "📄 ファイル", faq: "❓ FAQ", qa_csv: "📋 Q&A CSV" };',
'var _kbCloudInited = false;',

'function kbInitCloud() {',
'  if (!_kbCloudInited) {',
'    _kbCloudInited = true;',
'    var sel = document.getElementById("kb-db");',
'    var nsList = (_user && _user.namespaces && _user.namespaces.length) ? _user.namespaces : ALL_NAMESPACES;',
'    sel.innerHTML = nsList.map(function(ns) {',
'      return \'<option value="\' + ns + \'">\' + (DB_LABELS[ns] || ns) + \'</option>\';',
'    }).join("");',
'  }',
'  kbLoadHistory();',
'}',

'function kbDb() { return document.getElementById("kb-db").value; }',

'function kbStatus(id, msg, color) {',
'  var el = document.getElementById(id);',
'  if (el) { el.textContent = msg; el.style.color = color || "#94a3b8"; }',
'}',

'function kbImportUrl() {',
'  var url = document.getElementById("kb-url").value.trim();',
'  if (!url) { kbStatus("kb-url-status", "URLを貼り付けてください", "#f87171"); return; }',
'  kbStatus("kb-url-status", "読み取り中です。少しお待ちください…", "#f59e0b");',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      kbStatus("kb-url-status", "✅ 覚えました: " + r.title + "（" + r.chunks + "チャンク）", "#4ade80");',
'      document.getElementById("kb-url").value = "";',
'      kbLoadHistory();',
'    })',
'    .withFailureHandler(function(e) { kbStatus("kb-url-status", "❌ " + e.message, "#f87171"); })',
'    .adminKbImportUrl(_apiKey, kbDb(), url);',
'}',

'function kbAddFaq() {',
'  var q = document.getElementById("kb-faq-q").value.trim();',
'  var a = document.getElementById("kb-faq-a").value.trim();',
'  if (!q || !a) { kbStatus("kb-faq-status", "質問と回答の両方を入力してください", "#f87171"); return; }',
'  kbStatus("kb-faq-status", "登録中…", "#f59e0b");',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      kbStatus("kb-faq-status", "✅ 覚えました", "#4ade80");',
'      document.getElementById("kb-faq-q").value = "";',
'      document.getElementById("kb-faq-a").value = "";',
'      kbLoadHistory();',
'    })',
'    .withFailureHandler(function(e) { kbStatus("kb-faq-status", "❌ " + e.message, "#f87171"); })',
'    .adminKbAddFaq(_apiKey, kbDb(), q, a);',
'}',

'function kbImportCsv() {',
'  var input = document.getElementById("kb-csv");',
'  if (!input.files.length) { kbStatus("kb-csv-status", "CSVファイルを選んでください", "#f87171"); return; }',
'  kbStatus("kb-csv-status", "登録中です。件数が多いと数分かかります…", "#f59e0b");',
'  var reader = new FileReader();',
'  reader.onload = function() {',
'    google.script.run',
'      .withSuccessHandler(function(r) {',
'        kbStatus("kb-csv-status", "✅ " + r.title + " を覚えました", "#4ade80");',
'        input.value = "";',
'        kbLoadHistory();',
'      })',
'      .withFailureHandler(function(e) { kbStatus("kb-csv-status", "❌ " + e.message, "#f87171"); })',
'      .adminKbImportQaCsv(_apiKey, kbDb(), String(reader.result));',
'  };',
'  reader.readAsText(input.files[0]);',
'}',

'function kbImportYoutube() {',
'  var url = document.getElementById("kb-yt-url").value.trim();',
'  var transcript = document.getElementById("kb-yt-transcript").value.trim();',
'  if (!url) { kbStatus("kb-yt-status", "動画のURLを貼り付けてください", "#f87171"); return; }',
'  kbStatus("kb-yt-status", "字幕を読み取り中…", "#f59e0b");',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      kbStatus("kb-yt-status", "✅ 覚えました（" + r.chunks + "チャンク）", "#4ade80");',
'      document.getElementById("kb-yt-url").value = "";',
'      document.getElementById("kb-yt-transcript").value = "";',
'      kbLoadHistory();',
'    })',
'    .withFailureHandler(function(e) { kbStatus("kb-yt-status", "❌ " + e.message, "#f87171"); })',
'    .adminKbImportYoutube(_apiKey, kbDb(), url, transcript);',
'}',

'function kbUploadDoc() {',
'  var input = document.getElementById("kb-file");',
'  if (!input.files.length) { kbStatus("kb-file-status", "ファイルを選んでください", "#f87171"); return; }',
'  var f = input.files[0];',
'  if (f.size > 20 * 1024 * 1024) { kbStatus("kb-file-status", "ファイルが大きすぎます（上限 20MB）", "#f87171"); return; }',
'  kbStatus("kb-file-status", "読み取り中です。少しお待ちください…", "#f59e0b");',
'  var reader = new FileReader();',
'  reader.onload = function() {',
'    var b64 = String(reader.result).split(",")[1] || "";',
'    google.script.run',
'      .withSuccessHandler(function(r) {',
'        kbStatus("kb-file-status", "✅ 覚えました: " + r.title + "（" + r.chunks + "チャンク）", "#4ade80");',
'        input.value = "";',
'        kbLoadHistory();',
'      })',
'      .withFailureHandler(function(e) { kbStatus("kb-file-status", "❌ " + e.message, "#f87171"); })',
'      .adminKbUploadDoc(_apiKey, kbDb(), f.name, b64, f.type);',
'  };',
'  reader.readAsDataURL(f);',
'}',

'function kbLoadHistory() {',
'  google.script.run',
'    .withSuccessHandler(function(hist) {',
'      var tbody = document.getElementById("kb-hist-tbody");',
'      if (!tbody) return;',
'      if (!hist || !hist.length) {',
'        tbody.innerHTML = \'<tr><td colspan="6" style="color:#64748b;padding:12px">まだ何も覚えさせていません</td></tr>\';',
'        return;',
'      }',
'      tbody.innerHTML = hist.map(function(op) {',
'        var done  = op.status === "done";',
'        var badge = done ? \'<span style="font-size:.7rem;background:#14532d;color:#4ade80;padding:2px 8px;border-radius:99px;white-space:nowrap">覚えています</span>\'',
'                         : \'<span style="font-size:.7rem;background:#3f3f46;color:#94a3b8;padding:2px 8px;border-radius:99px;white-space:nowrap">取り消し済み</span>\';',
'        var btn   = done ? \'<button class="btn-admin btn-danger btn-sm" onclick="kbRollback(\\\'\' + op.opId + \'\\\')">なかったことにする</button>\' : "";',
'        return "<tr>" +',
'          \'<td style="color:#64748b;white-space:nowrap;font-size:.74rem">\' + (op.timestamp || "").slice(0, 19).replace("T", " ") + "</td>" +',
'          \'<td style="white-space:nowrap">\' + (KB_TYPE_LABELS[op.type] || op.type) + "</td>" +',
'          \'<td><div style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="\' + (op.title || "") + \'">\' + (op.title || "") + "</div></td>" +',
'          \'<td style="font-size:.74rem">\' + (DB_LABELS[op.db] || op.db) + "</td>" +',
'          "<td>" + badge + "</td>" +',
'          "<td>" + btn + "</td></tr>";',
'      }).join("");',
'    })',
'    .withFailureHandler(function(e) { adminFlash("履歴取得失敗: " + e.message, true); })',
'    .adminKbHistory(_apiKey, 50);',
'}',

'function kbRollback(opId) {',
'  if (!confirm("この学習を取り消しますか？\\n（覚えた内容が検索に出なくなり、Notionページはゴミ箱に移動します）")) return;',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      adminFlash("取り消しました（ページ " + r.archivedPages + " 件・インデックス " + r.deletedRows + " 行）");',
'      kbLoadHistory();',
'    })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminKbRollback(_apiKey, opId);',
'}',

'// ── Drive連携 ──',
'var _driveInited = false;',
'function driveInit() {',
'  loadDriveFolders();',
'}',

'function loadDriveFolders() {',
'  var tbody = document.getElementById("drive-folder-tbody");',
'  google.script.run',
'    .withSuccessHandler(function(folders) {',
'      tbody.innerHTML = ALL_NAMESPACES.map(function(ns) {',
'        return "<tr>" +',
'          "<td>" + (DB_LABELS[ns] || ns) + "</td>" +',
'          \'<td><input class="admin-input" id="drive-folder-\' + ns + \'" type="text" placeholder="フォルダIDを貼り付け（空欄で解除）" value="\' + (folders[ns] || "") + \'"></td>\' +',
'          \'<td><button class="btn-admin btn-primary btn-sm" onclick="saveDriveFolder(\\\'\' + ns + \'\\\')">保存</button></td>\' +',
'        "</tr>";',
'      }).join("");',
'    })',
'    .withFailureHandler(function(e) { tbody.innerHTML = \'<tr><td colspan="3" style="color:#f87171">読み込み失敗: \' + e.message + "</td></tr>"; })',
'    .adminGetDriveFolders(_apiKey);',
'}',

'function saveDriveFolder(ns) {',
'  var input = document.getElementById("drive-folder-" + ns);',
'  var val = input.value.trim();',
'  google.script.run',
'    .withSuccessHandler(function(r) { adminFlash(r.cleared ? "解除しました" : "保存しました: " + (DB_LABELS[ns] || ns)); })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminSetDriveFolder(_apiKey, ns, val);',
'}',

'function driveSyncNow() {',
'  var status = document.getElementById("drive-sync-status");',
'  status.textContent = "同期中です。ファイル数によっては数分かかります…";',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      status.textContent = "✅ 完了: フォルダ" + r.folders + "件 / チャンク" + r.chunks + "件更新 / スキップ" + r.skipped + "件" + (r.errors ? " / エラー" + r.errors + "件" : "");',
'    })',
'    .withFailureHandler(function(e) { status.textContent = "❌ " + e.message; })',
'    .adminSyncDrive(_apiKey);',
'}',

'function backupNow() {',
'  var status = document.getElementById("backup-status");',
'  status.textContent = "バックアップ中です…";',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      status.innerHTML = "✅ 完了: <a href=\\"" + r.folderUrl + "\\" target=\\"_blank\\" style=\\"color:var(--accent)\\">Driveフォルダを開く</a>（" + r.files.length + "ファイル）";',
'    })',
'    .withFailureHandler(function(e) { status.textContent = "❌ " + e.message; })',
'    .adminBackupNow(_apiKey);',
'}',

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
