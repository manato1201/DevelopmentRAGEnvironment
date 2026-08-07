/**
 * Cloud RAG Chatbot — Google Apps Script  v4 (APIキー認証統一版)
 *
 * ── スクリプトプロパティ ──────────────────────────────────────────────
 *   NOTION_API_KEY     Notion Integration Token
 *   GEMINI_API_KEY     Google AI Studio API Key
 *   ANTHROPIC_API_KEY  Anthropic Console で発行したAPIキー。houdini21チュートリアル
 *                      生成（action:'claude_messages'）用。クライアントには渡さず、
 *                      GASだけが保持する（§8.14参照）
 *   SHEETS_ID          ベクトル保存用スプレッドシートID
 *   NAMESPACE_CONFIG   namespace定義（JSON、省略可。テナント導入手順書参照）
 *   DB_TOOL_DOCS / DB_GAME_INFO / DB_RESEARCH / DB_TEAM_NOTES
 *   DB_AFURI / DB_BRAINTQ / DB_FOURTEEN  (各Notion DB ID。キー名は
 *   NAMESPACE_CONFIG のnamespaceキーから "DB_" + 大文字化 で自動導出される)
 *
 *   API_KEYS_CONFIG    ← 自動管理（管理画面で操作）
 *
 *   （以下は任意設定。未設定なら既定値・既定オフで動作し、既存デプロイに影響しない）
 *   RATE_LIMIT_MAX_REQUESTS     APIキーごとの1分間あたり最大リクエスト数（例: 30）
 *   TOKEN_USAGE_RETENTION_DAYS RAG_TokenUsageの保持日数。これを過ぎた行はadminPurgeExpiredTokenUsage()で削除対象になる
 *   CLAUDE_USAGE_RETENTION_DAYS RAG_ClaudeUsageの保持日数。これを過ぎた行はadminPurgeExpiredClaudeUsage()で削除対象になる
 *   NOTION_PARENT_PAGE_ID       管理画面「🗄 DB管理」タブでNotion DBを新規自動作成する際の
 *                               作成先ページID（未設定でも既存DB IDの手入力によるnamespace追加は可能）
 *   MIN_SCORE_<NS大文字>        namespaceごとの検索類似度閾値の上書き（例: MIN_SCORE_BRAINTQ=0.65）
 *   MEMORY_RETENTION_DAYS       RAG_Memoryの保持日数。これを過ぎた行は adminPurgeExpiredMemory() で削除対象になる
 *   HEALTH_ALERT_EMAIL          エラー率・レイテンシ異常時のアラート送信先メールアドレス
 *
 * ── デプロイドリフト検知 ─────────────────────────────────────────────
 *   このファイルを複数のGASプロジェクトへ手動コピペでデプロイする運用の場合、
 *   GAS_CODE_VERSION定数（このファイル上部）を編集のたびに更新すること。
 *   各デプロイの管理画面（⚙ 管理タブ上部）、または doPost に
 *   { "action": "version" } をPOSTした応答で値を突き合わせれば、
 *   デプロイし忘れているデプロイ先に気づける。
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
// namespaceごとにRAG_Memory（会話ログ）へ記録するかどうか。既定はtrue（従来通り）。
// 問診・健康関連など機微な内容を扱うnamespaceは、NAMESPACE_CONFIGで
// {"logMemory": false} を指定することでログ保存自体を止められる。
var NAMESPACE_LOG_MEMORY_MAP = {};
// namespaceごとにBM25+RRFハイブリッド検索を使うか。既定はfalse（従来通りコサイン類似度のみ）。
// NAMESPACE_CONFIGで {"hybridSearch": true} を指定したnamespaceだけ有効になる。
var NAMESPACE_HYBRID_MAP = {};
Object.keys(_NAMESPACE_CONFIG_).forEach(function(ns) {
  var suffix = _namespacePropSuffix_(ns);
  DB_KEY_MAP[ns]    = 'DB_' + suffix;
  DRIVE_KEY_MAP[ns] = 'DRIVE_' + suffix;
  DB_LABELS[ns]     = (_NAMESPACE_CONFIG_[ns] && _NAMESPACE_CONFIG_[ns].label) || ns;
  NAMESPACE_SOURCE_MAP[ns] = (_NAMESPACE_CONFIG_[ns] && _NAMESPACE_CONFIG_[ns].source) || 'notion';
  NAMESPACE_LOG_MEMORY_MAP[ns] =
    !(_NAMESPACE_CONFIG_[ns] && _NAMESPACE_CONFIG_[ns].logMemory === false);
  NAMESPACE_HYBRID_MAP[ns] = !!(_NAMESPACE_CONFIG_[ns] && _NAMESPACE_CONFIG_[ns].hybridSearch);
});

/** このnamespaceの問い合わせをRAG_Memoryに記録してよいか（既定true。dbKey='all'等の未知キーもtrue扱い） */
function _shouldLogMemory_(dbKey) {
  return NAMESPACE_LOG_MEMORY_MAP.hasOwnProperty(dbKey) ? NAMESPACE_LOG_MEMORY_MAP[dbKey] : true;
}

/** このnamespaceでBM25+RRFハイブリッド検索を使うか（既定false。dbKey='all'横断検索では無効） */
function _usesHybridSearch_(dbKey) {
  return !!NAMESPACE_HYBRID_MAP[dbKey];
}

/** このnamespaceがNotionを使うか（"notion" / "both"。既定はnotion） */
function _usesNotion_(dbKey) { return NAMESPACE_SOURCE_MAP[dbKey] !== 'drive'; }
/** このnamespaceがDriveを使うか（"drive" / "both"） */
function _usesDrive_(dbKey) {
  var s = NAMESPACE_SOURCE_MAP[dbKey];
  return s === 'drive' || s === 'both';
}

// gas_cloud_rag.js を編集するたびに手動で更新すること。複数のGASプロジェクトに
// 同じコードを手動コピペでデプロイしている場合、各デプロイの管理画面（⚙ 管理 →
// 🔑 APIキー管理タブ上部）に表示されるこの値を突き合わせることで、「片方だけ
// 更新し忘れた」というデプロイドリフトに気づけるようにする。
var GAS_CODE_VERSION = '2026-07-24-01';

var ALL_NAMESPACES    = Object.keys(DB_KEY_MAP);
var SHEET_NAME        = 'RAG_Index';
var MEMORY_SHEET      = 'RAG_Memory';
var TOKEN_USAGE_SHEET = 'RAG_TokenUsage';
var CLAUDE_USAGE_SHEET = 'RAG_ClaudeUsage';
var IDX_CACHE_KEY     = 'rag_idx_v3'; // v3: 各行にBM25用のtokensを追加（v2形式との互換なし、キー名変更で自然に無効化）
var CACHE_TTL         = 21600;
var CACHE_CHUNK       = 90000;

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

function _bytesToHex_(bytes) {
  var hex = '';
  for (var i = 0; i < bytes.length; i++) {
    var b = bytes[i];
    if (b < 0) b += 256;
    var h = b.toString(16);
    hex += (h.length === 1 ? '0' + h : h);
  }
  return hex;
}

/** APIキーの平文をSHA-256ハッシュに変換する（API_KEYS_CONFIGに平文を残さないため） */
function _hashApiKey_(key) {
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, key, Utilities.Charset.UTF_8);
  return _bytesToHex_(digest);
}

/** APIキーエントリの表示用プレフィックス（新形式keyPreview優先、旧形式keyへの後方互換あり） */
function _keyPreviewOf_(k) {
  return k.keyPreview || (k.key ? k.key.substring(0, 8) : '');
}

// ─────────────────────────────────────────────
// トークン予算の自動回復（RAG=Gemini用capacity/balance、Claude用
// claudeCapacity/claudeBalanceの両バケットに共通）
//
// GASには常駐プロセスが無いため、時間主導トリガーではなく「次にそのAPIキーで
// 何か（クエリ・Claude呼び出し・管理操作）が呼ばれた時に、期限が来ていれば
// その場でリセットする」遅延評価方式にしている（isRateLimited_と同じ考え方）。
// resetAtを過ぎた回数分だけ繰り越し計算し、次回のresetAtを未来の時刻まで
// 進める（サーバーが長時間呼ばれなかった場合でも狂わない）。
// ─────────────────────────────────────────────

/**
 * 1バケット分の自動回復を必要なら適用する。変更した場合はtrueを返す
 * （呼び出し元がAPI_KEYS_CONFIGを保存し直す必要があることを示す）。
 * capacity未設定（無制限）または intervalField 未設定（自動回復オフ）なら何もしない。
 */
function _applyScheduledReset_(k, capField, balField, intervalField, atField) {
  if (k[capField] == null) return false;
  var interval = Number(k[intervalField]) || 0;
  if (interval <= 0) return false;

  var now = Date.now();
  var atRaw = k[atField];
  var at = atRaw ? new Date(atRaw).getTime() : NaN;
  if (!atRaw || isNaN(at)) {
    // 自動回復を有効化した直後などでresetAtがまだ無い場合は、次回の時刻を
    // セットするだけ（設定した瞬間に残高を満タンにする処理は
    // adminSetKeyCapacity/adminSetClaudeCapacity側で既に行っている）。
    k[atField] = new Date(now + interval * 3600 * 1000).toISOString();
    return true;
  }

  var intervalMs = interval * 3600 * 1000;
  var changed = false;
  while (now >= at) {
    k[balField] = k[capField];
    at += intervalMs;
    changed = true;
  }
  if (changed) k[atField] = new Date(at).toISOString();
  return changed;
}

/** キー1件分、RAG（Gemini）・Claude両バケットの自動回復を適用する */
function _applyScheduledResets_(k) {
  var a = _applyScheduledReset_(k, 'capacity', 'balance', 'resetIntervalHours', 'resetAt');
  var b = _applyScheduledReset_(k, 'claudeCapacity', 'claudeBalance', 'claudeResetIntervalHours', 'claudeResetAt');
  return a || b;
}

/**
 * APIキーを検証する。新規発行分はkeyHash（SHA-256）で照合し、平文はどこにも保存しない。
 * bootstrapFirstAdminKey()等で過去に発行された旧形式（平文keyフィールド）のエントリとも
 * 後方互換で照合できる。
 *
 * 見つかったキーには自動回復（_applyScheduledResets_）を必ず適用してから返す。
 * validateApiKey_はdoPost/ragQueryWithKey/requireAdmin_など全ての経路が通る
 *唯一の入口なので、ここに集約することで「呼び出し忘れ」を防いでいる。
 */
function validateApiKey_(key) {
  if (!key) return null;
  var hash = _hashApiKey_(key);
  var keys = getApiKeysConfig_();
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    var matches = k.keyHash ? k.keyHash === hash : (!k.keyHash && k.key === key); // 旧形式（平文）との後方互換
    if (!matches) continue;
    if (_applyScheduledResets_(k)) saveApiKeysConfig_(keys);
    return k;
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
  if (!_hasQuotaRemaining_(config)) {
    throw new Error('トークンの利用上限に達しています。管理者にチャージを依頼してください。');
  }
  var result = ragQueryInternal_(query, dbKey, history, config.namespaces || [], apiKey, { sourceLimit: config.sourceLimit });
  try { result.memoryId = saveMemory_(apiKey, query, result.answer, result.sources, dbKey); } catch(e) {}
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
  var stats = {
    total: 0, up: 0, down: 0, unrated: 0, downByDb: {},
    avgScoreUp: null, avgScoreDown: null,
  };
  if (!sheet) return stats;

  var data = sheet.getDataRange().getValues();
  var scoreSumUp = 0, scoreCountUp = 0, scoreSumDown = 0, scoreCountDown = 0;
  for (var i = 1; i < data.length; i++) {
    var rating = String(data[i][6]);
    stats.total++;
    if (rating === 'up') stats.up++;
    else if (rating === 'down') stats.down++;
    else stats.unrated++;

    var sources = [];
    try { sources = JSON.parse(String(data[i][5]) || '[]'); } catch(e) {}

    if (rating === 'down') {
      sources.forEach(function(s) {
        var db = s.db || '(不明)';
        stats.downByDb[db] = (stats.downByDb[db] || 0) + 1;
      });
    }

    // スコアはsaveMemory_で新しく記録されるようになったフィールド。
    // 旧データ（score未記録）はここで自動的に読み飛ばされる。
    sources.forEach(function(s) {
      if (typeof s.score !== 'number') return;
      if (rating === 'up')   { scoreSumUp   += s.score; scoreCountUp++;   }
      if (rating === 'down') { scoreSumDown += s.score; scoreCountDown++; }
    });
  }
  if (scoreCountUp   > 0) stats.avgScoreUp   = scoreSumUp   / scoreCountUp;
  if (scoreCountDown > 0) stats.avgScoreDown = scoreSumDown / scoreCountDown;
  return stats;
}

// ─────────────────────────────────────────────
// トークン使用量トラッキング（APIキー単位の管理用集計）
//
// RAG_Memoryとは別シートに記録する。mode:"raw"（Function Calling経由、
// 実運用の大半を占める想定）はプライバシー・レイテンシ対策として質問文/回答文を
// 一切保存しない設計（saveMemory_を通らない）だが、使用量集計はraw/full両方で
// 必要なため、質問文/回答文を含まない軽量な記録として独立させている。
// 埋め込み（embedContent）はAPIレスポンスにusageMetadataが含まれないため
// トークン数を実測できない。embedChars* は入力文字数（あくまで目安、正確な
// トークン数ではない）。
// ─────────────────────────────────────────────

function getTokenUsageSheet_() {
  var sheetsId = getProps_().getProperty('SHEETS_ID');
  if (!sheetsId) return null;
  try {
    var ss    = SpreadsheetApp.openById(sheetsId);
    var sheet = ss.getSheetByName(TOKEN_USAGE_SHEET);
    if (!sheet) {
      sheet = ss.insertSheet(TOKEN_USAGE_SHEET);
      sheet.appendRow([
        'timestamp', 'apiKeyPrefix', 'dbKey', 'mode',
        'hydeTokens', 'answerTokens', 'embedCharsQuery', 'embedCharsHypo', 'totalMeasuredTokens',
      ]);
      sheet.getRange(1, 1, 1, 9).setFontWeight('bold');
    }
    return sheet;
  } catch(e) {
    Logger.log('getTokenUsageSheet_ error: ' + e.message);
    return null;
  }
}

function recordTokenUsage_(apiKey, dbKey, mode, hydeTokens, answerTokens, embedCharsQuery, embedCharsHypo) {
  try {
    var sheet = getTokenUsageSheet_();
    if (!sheet) return;
    var prefix = String(apiKey || '').substring(0, 8);
    var total  = (hydeTokens || 0) + (answerTokens || 0);
    sheet.appendRow([
      new Date().toISOString(), prefix, dbKey || '', mode || 'full',
      hydeTokens || 0, answerTokens || 0, embedCharsQuery || 0, embedCharsHypo || 0, total,
    ]);
  } catch(e) {
    Logger.log('recordTokenUsage_ error: ' + e.message);
  }
  // シート書き込みの成否に関わらず、予算消費は別処理として必ず試みる
  try {
    _consumeKeyBudget_(apiKey, (hydeTokens || 0) + (answerTokens || 0));
  } catch(e) {
    Logger.log('_consumeKeyBudget_ error: ' + e.message);
  }
}

/**
 * APIキー（apiKeyPrefix）ごとのトークン使用量集計（管理者のみ）。
 * totalMeasuredTokensはHyDE生成+最終回答生成の実測合計（埋め込み分は含まない）。
 * displayNameはAPI_KEYS_CONFIGと突き合わせて解決する。
 */
function adminTokenUsageStats(apiKey) {
  requireAdmin_(apiKey);
  var sheet = getTokenUsageSheet_();
  var byKey = {};
  if (!sheet) return { rows: [] };

  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    var prefix = String(data[i][1]);
    if (!prefix) continue;
    if (!byKey[prefix]) {
      byKey[prefix] = {
        apiKeyPrefix: prefix, queries: 0, rawQueries: 0, fullQueries: 0,
        hydeTokens: 0, answerTokens: 0, embedCharsTotal: 0, totalMeasuredTokens: 0,
      };
    }
    var row = byKey[prefix];
    row.queries++;
    if (String(data[i][3]) === 'raw') row.rawQueries++; else row.fullQueries++;
    row.hydeTokens          += Number(data[i][4]) || 0;
    row.answerTokens        += Number(data[i][5]) || 0;
    row.embedCharsTotal     += (Number(data[i][6]) || 0) + (Number(data[i][7]) || 0);
    row.totalMeasuredTokens += Number(data[i][8]) || 0;
  }

  // API_KEYS_CONFIGのdisplayNameと突き合わせる（削除済み・未知キーはprefixのまま表示）
  var nameByPrefix = {};
  getApiKeysConfig_().forEach(function(k) {
    nameByPrefix[_keyPreviewOf_(k)] = k.displayName || '';
  });

  var rows = Object.keys(byKey).map(function(prefix) {
    var r = byKey[prefix];
    r.displayName = nameByPrefix[prefix] || '(不明なキー)';
    return r;
  });
  rows.sort(function(a, b) { return b.totalMeasuredTokens - a.totalMeasuredTokens; });
  return { rows: rows };
}

/**
 * RAG_TokenUsageの保持期限（日数）を過ぎた行を削除する。
 * スクリプトプロパティ TOKEN_USAGE_RETENTION_DAYS が未設定（0以下）なら何もしない。
 */
function purgeExpiredTokenUsage_() {
  var days = parseInt(getProps_().getProperty('TOKEN_USAGE_RETENTION_DAYS') || '0', 10);
  if (!days || days <= 0) return { purged: 0, enabled: false };
  var sheet = getTokenUsageSheet_();
  if (!sheet) return { purged: 0, enabled: true };

  var cutoff = new Date().getTime() - days * 24 * 60 * 60 * 1000;
  var data   = sheet.getDataRange().getValues();
  var toDelete = [];
  for (var r = 1; r < data.length; r++) {
    var ts = Date.parse(String(data[r][0]));
    if (!isNaN(ts) && ts < cutoff) toDelete.push(r + 1);
  }
  toDelete.sort(function(a, b) { return b - a; });
  toDelete.forEach(function(ri) { sheet.deleteRow(ri); });
  return { purged: toDelete.length, enabled: true };
}

/** 管理UI/手動実行用: RAG_TokenUsageの期限切れ行を即時削除する */
function adminPurgeExpiredTokenUsage(apiKey) {
  requireAdmin_(apiKey);
  return purgeExpiredTokenUsage_();
}

// ─────────────────────────────────────────────
// Claudeトークン使用量トラッキング（RAG_TokenUsageと対称の別シート）
//
// RAG_TokenUsage（Gemini/HyDE用）とは記録項目が異なる（inputTokens/outputTokens/
// cacheWriteTokens/cacheReadTokensの実測値のみで、HyDEや埋め込み文字数の概念は
// Claude側には無い）ため、あえて別シート・別関数として対称に実装している。
// ─────────────────────────────────────────────

function getClaudeUsageSheet_() {
  var sheetsId = getProps_().getProperty('SHEETS_ID');
  if (!sheetsId) return null;
  try {
    var ss    = SpreadsheetApp.openById(sheetsId);
    var sheet = ss.getSheetByName(CLAUDE_USAGE_SHEET);
    if (!sheet) {
      sheet = ss.insertSheet(CLAUDE_USAGE_SHEET);
      sheet.appendRow([
        'timestamp', 'apiKeyPrefix', 'model', 'purpose',
        'inputTokens', 'outputTokens', 'cacheWriteTokens', 'cacheReadTokens', 'totalMeasuredTokens',
      ]);
      sheet.getRange(1, 1, 1, 9).setFontWeight('bold');
    }
    return sheet;
  } catch(e) {
    Logger.log('getClaudeUsageSheet_ error: ' + e.message);
    return null;
  }
}

function recordClaudeUsage_(apiKey, model, purpose, usage) {
  usage = usage || {};
  var inputTokens  = usage.input_tokens || 0;
  var outputTokens = usage.output_tokens || 0;
  var cacheWrite   = usage.cache_creation_input_tokens || 0;
  var cacheRead    = usage.cache_read_input_tokens || 0;
  var total        = inputTokens + outputTokens + cacheWrite + cacheRead;
  try {
    var sheet = getClaudeUsageSheet_();
    if (sheet) {
      var prefix = String(apiKey || '').substring(0, 8);
      sheet.appendRow([
        new Date().toISOString(), prefix, model || '', purpose || '',
        inputTokens, outputTokens, cacheWrite, cacheRead, total,
      ]);
    }
  } catch(e) {
    Logger.log('recordClaudeUsage_ error: ' + e.message);
  }
  // シート書き込みの成否に関わらず、予算消費（input+outputのみ。キャッシュ分は
  // 実コストが小さいためRAG側のrecordTokenUsage_と同じ考え方で予算対象からは外す）
  try {
    _consumeClaudeBudget_(apiKey, inputTokens + outputTokens);
  } catch(e) {
    Logger.log('_consumeClaudeBudget_ error: ' + e.message);
  }
  return total;
}

/** APIキー（apiKeyPrefix）ごとのClaudeトークン使用量集計（管理者のみ） */
function adminClaudeUsageStats(apiKey) {
  requireAdmin_(apiKey);
  var sheet = getClaudeUsageSheet_();
  var byKey = {};
  if (!sheet) return { rows: [] };

  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    var prefix = String(data[i][1]);
    if (!prefix) continue;
    if (!byKey[prefix]) {
      byKey[prefix] = {
        apiKeyPrefix: prefix, calls: 0,
        inputTokens: 0, outputTokens: 0, cacheTokens: 0, totalMeasuredTokens: 0,
      };
    }
    var row = byKey[prefix];
    row.calls++;
    row.inputTokens         += Number(data[i][4]) || 0;
    row.outputTokens        += Number(data[i][5]) || 0;
    row.cacheTokens         += (Number(data[i][6]) || 0) + (Number(data[i][7]) || 0);
    row.totalMeasuredTokens += Number(data[i][8]) || 0;
  }

  var nameByPrefix = {};
  getApiKeysConfig_().forEach(function(k) {
    nameByPrefix[_keyPreviewOf_(k)] = k.displayName || '';
  });

  var rows = Object.keys(byKey).map(function(prefix) {
    var r = byKey[prefix];
    r.displayName = nameByPrefix[prefix] || '(不明なキー)';
    return r;
  });
  rows.sort(function(a, b) { return b.totalMeasuredTokens - a.totalMeasuredTokens; });
  return { rows: rows };
}

/**
 * RAG_ClaudeUsageの保持期限（日数）を過ぎた行を削除する。
 * スクリプトプロパティ CLAUDE_USAGE_RETENTION_DAYS が未設定（0以下）なら何もしない。
 */
function purgeExpiredClaudeUsage_() {
  var days = parseInt(getProps_().getProperty('CLAUDE_USAGE_RETENTION_DAYS') || '0', 10);
  if (!days || days <= 0) return { purged: 0, enabled: false };
  var sheet = getClaudeUsageSheet_();
  if (!sheet) return { purged: 0, enabled: true };

  var cutoff = new Date().getTime() - days * 24 * 60 * 60 * 1000;
  var data   = sheet.getDataRange().getValues();
  var toDelete = [];
  for (var r = 1; r < data.length; r++) {
    var ts = Date.parse(String(data[r][0]));
    if (!isNaN(ts) && ts < cutoff) toDelete.push(r + 1);
  }
  toDelete.sort(function(a, b) { return b - a; });
  toDelete.forEach(function(ri) { sheet.deleteRow(ri); });
  return { purged: toDelete.length, enabled: true };
}

/** 管理UI/手動実行用: RAG_ClaudeUsageの期限切れ行を即時削除する */
function adminPurgeExpiredClaudeUsage(apiKey) {
  requireAdmin_(apiKey);
  return purgeExpiredClaudeUsage_();
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
  var keys = getApiKeysConfig_();
  // 一覧表示のたびに自動回復の期限切れをチェックし、期限が来ている分は反映しておく
  // （そのキー自体が呼ばれるまで待つと、管理画面に古い残高が表示され続けてしまう）。
  var changed = false;
  keys.forEach(function(k) { if (_applyScheduledResets_(k)) changed = true; });
  if (changed) saveApiKeysConfig_(keys);

  return keys.map(function(k) {
    return {
      keyPreview:  _keyPreviewOf_(k) + '...',
      displayName: k.displayName || '',
      namespaces:  k.namespaces  || [],
      isAdmin:     k.isAdmin     || false,
      createdAt:   k.createdAt   || '',
      capacity:    (k.capacity == null) ? null : k.capacity,
      balance:     (k.capacity == null) ? null : (typeof k.balance === 'number' ? k.balance : k.capacity),
      resetIntervalHours: (k.capacity == null) ? null : (k.resetIntervalHours || null),
      resetAt:            (k.capacity == null) ? null : (k.resetAt || null),
      claudeCapacity: (k.claudeCapacity == null) ? null : k.claudeCapacity,
      claudeBalance:  (k.claudeCapacity == null) ? null : (typeof k.claudeBalance === 'number' ? k.claudeBalance : k.claudeCapacity),
      claudeResetIntervalHours: (k.claudeCapacity == null) ? null : (k.claudeResetIntervalHours || null),
      claudeResetAt:            (k.claudeCapacity == null) ? null : (k.claudeResetAt || null),
      sourceLimit: k.sourceLimit || null,  // null = 既定値（DEFAULT_SOURCE_LIMIT）を使用
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
    keyHash:     _hashApiKey_(newKey),
    keyPreview:  newKey.substring(0, 8),
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
    return _keyPreviewOf_(k) !== prefix;
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
    if (_keyPreviewOf_(k) === prefix) { k.namespaces = newNamespaces; found = true; }
  });
  if (!found) throw new Error('キーが見つかりません: ' + keyPreview);
  saveApiKeysConfig_(keys);
  return { ok: true };
}

// ─────────────────────────────────────────────
// APIキーごとのトークン上限（予算）管理
//
// chatbot_token_control（別リポジトリ）のFirestoreベースのcapacity/deposit方式と
// 同じ考え方を、GAS側のストレージ（API_KEYS_CONFIG）だけで完結させたもの。
// 外部データストアを増やさない方針のため、Firestoreは使わず既存の
// PropertiesService(API_KEYS_CONFIG)にcapacity（上限）とbalance（残高）を
// 追加するだけにしている。
//
// capacity: null/未設定 = 無制限（既定。既存キーへの後方互換）
// balance:  残高。クエリのたびにrecordTokenUsage_内で消費した実測トークン数分だけ減らす。
//           capacity変更時は満タン（=capacity）にリセットする。
// 事前チェック（doPost）はGemini呼び出し前に行うが、そのクエリ自体の消費量は
// 呼び出し後でないと分からないため、「既に残高が尽きているか」だけを判定する
// （isRateLimited_と同様、厳密な使用量の先読みはできない前提の簡易実装）。
// ─────────────────────────────────────────────

/** true: 予算内（許容） / false: 残高が尽きている（拒否すべき）。capacity未設定なら常にtrue */
function _hasQuotaRemaining_(config) {
  if (!config || config.capacity == null) return true;
  var balance = typeof config.balance === 'number' ? config.balance : config.capacity;
  return balance > 0;
}

/** クエリ1件で消費したトークン数分だけ、該当APIキーのbalanceを減らす（capacity未設定のキーは何もしない） */
function _consumeKeyBudget_(apiKey, amount) {
  if (!amount || amount <= 0) return;
  var keys = getApiKeysConfig_();
  var hash = _hashApiKey_(apiKey);
  var changed = false;
  keys.forEach(function(k) {
    var matches = k.keyHash ? k.keyHash === hash : (k.key === apiKey);
    if (!matches || k.capacity == null) return;
    var current = typeof k.balance === 'number' ? k.balance : k.capacity;
    k.balance = Math.max(0, current - amount);
    changed = true;
  });
  if (changed) saveApiKeysConfig_(keys);
}

/**
 * キーのトークン上限を設定（管理者のみ）。capacityにnull/未指定を渡すと無制限に戻す。
 * 上限を変更した時点でbalanceは満タン（=capacity）にリセットする。
 * resetIntervalHoursを指定すると、その時間ごとに残高が自動で満タンに回復するように
 * なる（null/0/未指定なら自動回復オフ＝手動チャージのみ）。
 */
function adminSetKeyCapacity(apiKey, keyPreview, capacity, resetIntervalHours) {
  requireAdmin_(apiKey);
  var prefix = keyPreview.replace('...', '');
  var keys   = getApiKeysConfig_();
  var found  = false;
  keys.forEach(function(k) {
    if (_keyPreviewOf_(k) !== prefix) return;
    found = true;
    if (capacity === null || capacity === undefined || capacity === '') {
      k.capacity = null;
      delete k.balance;
      delete k.resetIntervalHours;
      delete k.resetAt;
    } else {
      var cap = Number(capacity);
      if (!isFinite(cap) || cap < 0) throw new Error('上限は0以上の数値で指定してください');
      k.capacity = cap;
      k.balance  = cap;
      var interval = Number(resetIntervalHours) || 0;
      if (interval > 0) {
        k.resetIntervalHours = interval;
        k.resetAt = new Date(Date.now() + interval * 3600 * 1000).toISOString();
      } else {
        delete k.resetIntervalHours;
        delete k.resetAt;
      }
    }
  });
  if (!found) throw new Error('キーが見つかりません: ' + keyPreview);
  saveApiKeysConfig_(keys);
  return { ok: true };
}

/** キーの残高にチャージ（上限を超えない範囲で加算、管理者のみ）。無制限キーには使えない */
function adminChargeKeyBalance(apiKey, keyPreview, amount) {
  requireAdmin_(apiKey);
  var amt = Number(amount);
  if (!isFinite(amt) || amt <= 0) throw new Error('チャージ量は正の数値で指定してください');
  var prefix = keyPreview.replace('...', '');
  var keys   = getApiKeysConfig_();
  var found  = false, newBalance = null;
  keys.forEach(function(k) {
    if (_keyPreviewOf_(k) !== prefix) return;
    found = true;
    if (k.capacity == null) throw new Error('無制限のキーにはチャージ不要です: ' + keyPreview);
    var current = typeof k.balance === 'number' ? k.balance : k.capacity;
    k.balance = Math.max(0, Math.min(k.capacity, current + amt));
    newBalance = k.balance;
  });
  if (!found) throw new Error('キーが見つかりません: ' + keyPreview);
  saveApiKeysConfig_(keys);
  return { ok: true, balance: newBalance };
}

/**
 * キーごとの参考情報（引用元）取得件数を設定する（管理者のみ）。null/未指定/0を渡すと
 * 既定値（DEFAULT_SOURCE_LIMIT）に戻す。上限はMAX_SOURCE_LIMITでクランプされる
 * （検索1回あたりのコンテキスト量・トークン消費が暴走しないようにするフェイルセーフ）。
 */
function adminSetSourceLimit(apiKey, keyPreview, limit) {
  requireAdmin_(apiKey);
  var prefix = keyPreview.replace('...', '');
  var keys   = getApiKeysConfig_();
  var found  = false;
  keys.forEach(function(k) {
    if (_keyPreviewOf_(k) !== prefix) return;
    found = true;
    if (limit === null || limit === undefined || limit === '') {
      delete k.sourceLimit;
    } else {
      var n = Number(limit);
      if (!isFinite(n) || n < 1) throw new Error('参考情報の件数は1以上の数値で指定してください');
      k.sourceLimit = Math.min(Math.round(n), MAX_SOURCE_LIMIT);
    }
  });
  if (!found) throw new Error('キーが見つかりません: ' + keyPreview);
  saveApiKeysConfig_(keys);
  return { ok: true };
}

// ─────────────────────────────────────────────
// APIキーごとのClaudeトークン上限（予算） — RAG（Gemini）用capacity/balanceとは
// 別バケットで管理する。houdini21チュートリアル生成（tutorial_agent.py）が
// Claude APIを直接叩かず、必ずこのGAS経由（doPost action:'claude_messages'）で
// 呼ぶようにすることで、クライアント側で上限を自己申告・改ざんできない構成にする
// （§8.14参照）。フィールド名・関数の作りはRAG用のcapacity/balanceと意図的に対称にしてある。
// ─────────────────────────────────────────────

/** true: 予算内（許容） / false: 残高が尽きている（拒否すべき）。claudeCapacity未設定なら常にtrue */
function _hasClaudeQuotaRemaining_(config) {
  if (!config || config.claudeCapacity == null) return true;
  var balance = typeof config.claudeBalance === 'number' ? config.claudeBalance : config.claudeCapacity;
  return balance > 0;
}

/** Claude呼び出し1回で消費したトークン数分だけ、該当APIキーのclaudeBalanceを減らす（claudeCapacity未設定のキーは何もしない） */
function _consumeClaudeBudget_(apiKey, amount) {
  if (!amount || amount <= 0) return;
  var keys = getApiKeysConfig_();
  var hash = _hashApiKey_(apiKey);
  var changed = false;
  keys.forEach(function(k) {
    var matches = k.keyHash ? k.keyHash === hash : (k.key === apiKey);
    if (!matches || k.claudeCapacity == null) return;
    var current = typeof k.claudeBalance === 'number' ? k.claudeBalance : k.claudeCapacity;
    k.claudeBalance = Math.max(0, current - amount);
    changed = true;
  });
  if (changed) saveApiKeysConfig_(keys);
}

/**
 * キーのClaudeトークン上限を設定（管理者のみ）。claudeCapacityにnull/未指定を渡すと無制限に戻す。
 * 上限を変更した時点でclaudeBalanceは満タン（=claudeCapacity）にリセットする。
 * resetIntervalHoursを指定すると、その時間ごとに残高が自動で満タンに回復するように
 * なる（null/0/未指定なら自動回復オフ＝手動チャージのみ）。
 */
function adminSetClaudeCapacity(apiKey, keyPreview, capacity, resetIntervalHours) {
  requireAdmin_(apiKey);
  var prefix = keyPreview.replace('...', '');
  var keys   = getApiKeysConfig_();
  var found  = false;
  keys.forEach(function(k) {
    if (_keyPreviewOf_(k) !== prefix) return;
    found = true;
    if (capacity === null || capacity === undefined || capacity === '') {
      k.claudeCapacity = null;
      delete k.claudeBalance;
      delete k.claudeResetIntervalHours;
      delete k.claudeResetAt;
    } else {
      var cap = Number(capacity);
      if (!isFinite(cap) || cap < 0) throw new Error('上限は0以上の数値で指定してください');
      k.claudeCapacity = cap;
      k.claudeBalance  = cap;
      var interval = Number(resetIntervalHours) || 0;
      if (interval > 0) {
        k.claudeResetIntervalHours = interval;
        k.claudeResetAt = new Date(Date.now() + interval * 3600 * 1000).toISOString();
      } else {
        delete k.claudeResetIntervalHours;
        delete k.claudeResetAt;
      }
    }
  });
  if (!found) throw new Error('キーが見つかりません: ' + keyPreview);
  saveApiKeysConfig_(keys);
  return { ok: true };
}

/** キーのClaude残高にチャージ（上限を超えない範囲で加算、管理者のみ）。無制限キーには使えない */
function adminChargeClaudeBalance(apiKey, keyPreview, amount) {
  requireAdmin_(apiKey);
  var amt = Number(amount);
  if (!isFinite(amt) || amt <= 0) throw new Error('チャージ量は正の数値で指定してください');
  var prefix = keyPreview.replace('...', '');
  var keys   = getApiKeysConfig_();
  var found  = false, newBalance = null;
  keys.forEach(function(k) {
    if (_keyPreviewOf_(k) !== prefix) return;
    found = true;
    if (k.claudeCapacity == null) throw new Error('無制限のキーにはチャージ不要です: ' + keyPreview);
    var current = typeof k.claudeBalance === 'number' ? k.claudeBalance : k.claudeCapacity;
    k.claudeBalance = Math.max(0, Math.min(k.claudeCapacity, current + amt));
    newBalance = k.claudeBalance;
  });
  if (!found) throw new Error('キーが見つかりません: ' + keyPreview);
  saveApiKeysConfig_(keys);
  return { ok: true, balance: newBalance };
}

// ─────────────────────────────────────────────
// レート制限
//
// APIキーごとに、直近1分間のリクエスト数をCacheServiceで数え、
// 上限を超えたら検索処理（Gemini API呼び出し）そのものをスキップして拒否する。
// スクリプトプロパティ RATE_LIMIT_MAX_REQUESTS が未設定なら無効（既定オフ）。
// ─────────────────────────────────────────────

var RATE_LIMIT_WINDOW_SEC = 60;

/** true: 上限超過（拒否すべき） / false: 許容範囲内（既定オフ時も常にfalse） */
function isRateLimited_(apiKey) {
  var maxReqRaw = getProps_().getProperty('RATE_LIMIT_MAX_REQUESTS');
  if (!maxReqRaw) return false; // 未設定なら無効（既定オフ・既存デプロイに影響しない）
  var maxReq = parseInt(maxReqRaw, 10);
  if (!maxReq || maxReq <= 0) return false;

  var cache  = CacheService.getScriptCache();
  var bucket = Math.floor(new Date().getTime() / 1000 / RATE_LIMIT_WINDOW_SEC);
  // apiKey自体をキャッシュキーに使わない（キャッシュの内容が漏れた場合の露出経路を増やさないため）
  var key    = 'ratelimit_' + _hashApiKey_(apiKey).substring(0, 16) + '_' + bucket;
  var count  = parseInt(cache.get(key) || '0', 10) + 1;
  cache.put(key, String(count), RATE_LIMIT_WINDOW_SEC * 2);
  return count > maxReq;
}

// ─────────────────────────────────────────────
// 監視・アラート
//
// クエリ1件ごとの成否・レイテンシを直近ウィンドウ分だけCacheServiceに
// 集計し、エラー率または最大レイテンシが閾値を超えたら管理者へメール通知する。
// スクリプトプロパティ HEALTH_ALERT_EMAIL が未設定なら何もしない（既定オフ）。
// ─────────────────────────────────────────────

var HEALTH_WINDOW_SEC          = 300;   // 集計ウィンドウ（5分）
var HEALTH_MIN_SAMPLES          = 5;    // このサンプル数未満では判定しない
var HEALTH_ERROR_RATE_THRESHOLD = 0.3;  // エラー率30%以上でアラート
var HEALTH_LATENCY_WARN_MS      = 15000; // 最大レイテンシ15秒以上でアラート
var HEALTH_ALERT_COOLDOWN_SEC   = 1800; // 同一アラートの再送を30分間抑制

function _healthWindowKey_() {
  var bucket = Math.floor(new Date().getTime() / 1000 / HEALTH_WINDOW_SEC);
  return 'health_' + bucket;
}

/** doPost内から呼ぶ。1件のクエリの成否・所要時間を直近ウィンドウの集計に加算する */
function recordHealthSample_(ok, latencyMs) {
  var cache = CacheService.getScriptCache();
  var key   = _healthWindowKey_();
  var raw   = cache.get(key);
  var data  = raw ? JSON.parse(raw) : { total: 0, errors: 0, maxLatency: 0 };
  data.total += 1;
  if (!ok) data.errors += 1;
  if (latencyMs > data.maxLatency) data.maxLatency = latencyMs;
  cache.put(key, JSON.stringify(data), HEALTH_WINDOW_SEC * 2);
  checkHealthAndAlert_(data);
}

function checkHealthAndAlert_(data) {
  if (data.total < HEALTH_MIN_SAMPLES) return;
  var errorRate = data.errors / data.total;
  var problems = [];
  if (errorRate >= HEALTH_ERROR_RATE_THRESHOLD) {
    problems.push('エラー率 ' + Math.round(errorRate * 100) + '%（' + data.errors + '/' + data.total + '件、直近' + (HEALTH_WINDOW_SEC / 60) + '分）');
  }
  if (data.maxLatency >= HEALTH_LATENCY_WARN_MS) {
    problems.push('最大レイテンシ ' + Math.round(data.maxLatency / 1000) + '秒');
  }
  if (problems.length === 0) return;
  sendHealthAlert_(problems.join(' / '));
}

function sendHealthAlert_(message) {
  var to = getProps_().getProperty('HEALTH_ALERT_EMAIL');
  if (!to) return; // 未設定なら通知しない（既定オフ）
  var cache = CacheService.getScriptCache();
  var cooldownKey = 'health_alert_sent';
  if (cache.get(cooldownKey)) return; // クールダウン中は再送しない
  try {
    MailApp.sendEmail(to, '[Cloud RAG] 異常検知アラート', message + '\n\n対象デプロイ: ' + ScriptApp.getScriptId());
    cache.put(cooldownKey, '1', HEALTH_ALERT_COOLDOWN_SEC);
  } catch(e) {
    Logger.log('sendHealthAlert_ error: ' + e.message);
  }
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
  var __healthStart = new Date().getTime();
  try {
    var body    = JSON.parse(e.postData.contents);
    var apiKey  = body.apiKey  || '';
    var action  = body.action  || 'query';

    // バージョン確認アクション: { action:'version' }（認証不要。デプロイドリフト検知用）
    if (action === 'version') {
      return ContentService.createTextOutput(JSON.stringify({ version: GAS_CODE_VERSION, status: 'ok' }))
        .setMimeType(ContentService.MimeType.JSON);
    }

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

    // Claude API プロキシ（houdini21チュートリアル生成等）:
    // { action:'claude_messages', apiKey, model, max_tokens, system, tools, messages, purpose }
    // クライアント（Houdini）は生のANTHROPIC_API_KEYを一切持たず、必ずこのGAS経由で
    // Claude APIを呼ぶ。これによりAPIキーごとのClaude専用トークン予算（claudeCapacity/
    // claudeBalance、RAG=Gemini用のcapacity/balanceとは別バケット）をクライアント側で
    // 改ざん・迂回できない形で強制する（§8.14参照）。
    if (action === 'claude_messages') {
      var claudeConfig = validateApiKey_(apiKey);
      if (!claudeConfig) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'auth_error', error: { message: '認証エラー: 無効なAPIキーです' },
        })).setMimeType(ContentService.MimeType.JSON);
      }
      if (isRateLimited_(apiKey)) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'rate_limited', error: { message: 'リクエストが多すぎます。しばらく待ってから再試行してください。' },
        })).setMimeType(ContentService.MimeType.JSON);
      }
      if (!_hasClaudeQuotaRemaining_(claudeConfig)) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'quota_exceeded', error: { message: 'Claudeトークンの利用上限に達しています。管理者にチャージを依頼してください。' },
        })).setMimeType(ContentService.MimeType.JSON);
      }
      var claudeResult = callClaudeProxy_(body);
      if (claudeResult.status === 'ok') {
        recordClaudeUsage_(apiKey, body.model || '', body.purpose || '', claudeResult.usage);
        // 消費後の残高をレスポンスに含める。クライアント（Houdini）はこれを
        // そのままゲージ表示に使う（ローカルで独自に上限を計算・保持させない）。
        var updatedConfig = validateApiKey_(apiKey);
        claudeResult.claudeQuota = {
          capacity: (updatedConfig && updatedConfig.claudeCapacity != null) ? updatedConfig.claudeCapacity : null,
          balance:  (updatedConfig && updatedConfig.claudeCapacity != null)
            ? (typeof updatedConfig.claudeBalance === 'number' ? updatedConfig.claudeBalance : updatedConfig.claudeCapacity)
            : null,
          resetIntervalHours: (updatedConfig && updatedConfig.claudeCapacity != null) ? (updatedConfig.claudeResetIntervalHours || null) : null,
          resetAt:            (updatedConfig && updatedConfig.claudeCapacity != null) ? (updatedConfig.claudeResetAt || null) : null,
        };
      }
      return ContentService.createTextOutput(JSON.stringify(claudeResult))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // YouTube文字起こしの自動登録（scripts/youtube_transcribe.py 等の外部ツールから呼ぶ）:
    // { action:'admin_kb_import_youtube', apiKey, dbKey, videoUrl, transcript }
    // adminKbImportYoutube() 自体は google.script.run 専用（管理画面のブラウザからしか
    // 呼べない）ため、外部スクリプトが字幕の無い動画をGemini等で文字起こしした結果を
    // そのままCloud RAGへ登録できるようにする窓口。管理者キー必須・レート制限あり。
    if (action === 'admin_kb_import_youtube') {
      var kbConfig = validateApiKey_(apiKey);
      if (!kbConfig) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'auth_error', error: { message: '認証エラー: 無効なAPIキーです' },
        })).setMimeType(ContentService.MimeType.JSON);
      }
      if (!kbConfig.isAdmin) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'forbidden', error: { message: '管理者権限が必要です' },
        })).setMimeType(ContentService.MimeType.JSON);
      }
      if (isRateLimited_(apiKey)) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'rate_limited', error: { message: 'リクエストが多すぎます。しばらく待ってから再試行してください。' },
        })).setMimeType(ContentService.MimeType.JSON);
      }
      try {
        var kbResult = adminKbImportYoutube(apiKey, body.dbKey || '', body.videoUrl || '', body.transcript || '');
        kbResult.status = 'ok';
        return ContentService.createTextOutput(JSON.stringify(kbResult))
          .setMimeType(ContentService.MimeType.JSON);
      } catch (kbErr) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'error', error: { message: kbErr.message },
        })).setMimeType(ContentService.MimeType.JSON);
      }
    }

    // 類似度グラフの取得（graph_view.py の GraphFetchWorker から呼ぶ）:
    // { action:'graph', apiKey }
    // getGraphDataWithKey() 自体は google.script.run 専用（管理画面のブラウザからしか
    // 呼べない）ため、Houdini が Cloud RAG モードでも Graph タブのデータを取得できる
    // ようにする窓口。buildGraphData_() 自体は管理者チェックをしておらず
    // config.namespaces でフィルタするだけなので、このブランチも管理者専用にはせず、
    // 通常のクエリ（query action）と同じ認証・レート制限の流儀を踏襲する。
    // 戻り値の形（nodes/edges/status）は rag_local_bridge.py の /graph エンドポイントと
    // 完全に同一なので、レンダリング側（graph_view.py）は変更不要。
    if (action === 'graph') {
      var graphConfig = validateApiKey_(apiKey);
      if (!graphConfig) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'auth_error', error: { message: '認証エラー: 無効なAPIキーです' },
        })).setMimeType(ContentService.MimeType.JSON);
      }
      if (isRateLimited_(apiKey)) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'rate_limited', error: { message: 'リクエストが多すぎます。しばらく待ってから再試行してください。' },
        })).setMimeType(ContentService.MimeType.JSON);
      }
      var graphResult = buildGraphData_(graphConfig.namespaces || null);
      graphResult.status = 'ok';
      return ContentService.createTextOutput(JSON.stringify(graphResult))
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

    if (isRateLimited_(apiKey)) {
      return ContentService.createTextOutput(JSON.stringify({
        answer: 'リクエストが多すぎます。しばらく待ってから再試行してください。',
        sources: [], status: 'rate_limited',
      })).setMimeType(ContentService.MimeType.JSON);
    }

    if (!_hasQuotaRemaining_(config)) {
      return ContentService.createTextOutput(JSON.stringify({
        answer: 'トークンの利用上限に達しています。管理者にチャージを依頼してください。',
        sources: [], status: 'quota_exceeded',
      })).setMimeType(ContentService.MimeType.JSON);
    }

    var result  = ragQueryInternal_(query, dbKey, history, allowed, apiKey, { skipAnswer: isRaw, sourceLimit: config.sourceLimit });
    var memId   = '';
    if (!isRaw) {
      try { memId = saveMemory_(apiKey, query, result.answer, result.sources, dbKey); } catch(e) {}
    }
    try { recordHealthSample_(true, new Date().getTime() - __healthStart); } catch(e) {}
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
    try { recordHealthSample_(false, new Date().getTime() - __healthStart); } catch(e) {}
    return ContentService.createTextOutput(JSON.stringify({
      answer: 'エラー: ' + err.message, sources: [], status: 'error',
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

// ─────────────────────────────────────────────
// RAG コア
// ─────────────────────────────────────────────

// 参考情報（引用元）の件数はAPIキーごとに設定できる（API_KEYS_CONFIGの`sourceLimit`）。
// 未設定なら既定値5。上限を設けるのは、1回のクエリで取得・注入するコンテキストが
// 増えるほど回答生成コールの入力トークン（=RAG/Claudeトークン予算の消費）が増えるため、
// 誤って極端な値を設定してもコスト・レイテンシが暴走しないようにするフェイルセーフ。
var DEFAULT_SOURCE_LIMIT = 5;
var MAX_SOURCE_LIMIT      = 20;

function _clampSourceLimit_(n) {
  var v = parseInt(n, 10);
  if (!v || v < 1) return DEFAULT_SOURCE_LIMIT;
  return Math.min(v, MAX_SOURCE_LIMIT);
}

function ragQueryInternal_(query, dbKey, history, allowedNamespaces, apiKey, opts) {
  opts = opts || {};
  var skipAnswer  = !!opts.skipAnswer;
  var sourceLimit = _clampSourceLimit_(opts.sourceLimit);
  dbKey = sanitizeDbKey_(dbKey);
  history = history || [];
  if (!allowedNamespaces || allowedNamespaces.length === 0) {
    return { answer: 'アクセス可能なDBがありません。管理者にAPIキーの権限付与を依頼してください。', sources: [] };
  }
  if (dbKey && dbKey !== 'all' && allowedNamespaces.indexOf(dbKey) === -1) {
    dbKey = 'all';
  }

  // HyDE で検索精度を向上させた埋め込みを生成してから検索（dbKey でドメインを指定）
  var hyde    = hydeExpand_(query, dbKey);
  var results = searchByEmbedding_(query, dbKey, sourceLimit, allowedNamespaces, hyde.emb);

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
    recordTokenUsage_(apiKey, dbKey, 'raw', hyde.hydeTokens, 0, hyde.embedCharsQuery, hyde.embedCharsHypo);
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

  var genResult = callGemini_(contents);
  var answer    = genResult.text;

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
  recordTokenUsage_(apiKey, dbKey, 'full', hyde.hydeTokens, genResult.tokens, hyde.embedCharsQuery, hyde.embedCharsHypo);
  return { answer: answer, sources: sources, extractionRate: extraction.rate, extractionDetail: extraction.citedCount + '/' + extraction.total };
}

// ─────────────────────────────────────────────
// 検索
// ─────────────────────────────────────────────

/**
 * MIN_SCORE閾値を返す。スクリプトプロパティ MIN_SCORE_<namespace大文字> で
 * namespaceごとに上書きできる（例: MIN_SCORE_BRAINTQ=0.55）。未設定なら
 * 従来通りの既定値（単一DB指定0.58 / 全DB横断0.62）にフォールバックする。
 * adminRatingStatsのavgScoreUp/avgScoreDownを見て手動でチューニングする運用を想定。
 */
function minScoreFor_(dbKey) {
  var fallback = (dbKey && dbKey !== 'all') ? 0.58 : 0.62;
  if (!dbKey || dbKey === 'all' || !DB_KEY_MAP[dbKey]) return fallback;
  var override = getProps_().getProperty('MIN_SCORE_' + _namespacePropSuffix_(dbKey));
  var parsed = parseFloat(override);
  return isNaN(parsed) ? fallback : parsed;
}

// ─────────────────────────────────────────────
// corpus増加への対策: 2値量子化による近似ショートリスト
//
// 従来はnamespace内の全行に対して768次元の浮動小数コサイン類似度を計算する
// 総当たりスキャンだったため、corpusが増えるほど1クエリあたりの計算量が線形に
// 増える弱点があった（Google Sheets自体はChromaDBのようなHNSW索引を持たない）。
// ここでは各埋め込みを符号ビット（各次元の正負）だけの2値シグネチャに圧縮し、
// 安価なハミング距離で「厳密計算する候補」を絞り込む（候補生成→厳密再スコアの
// 2段構成）。シグネチャはインデックスキャッシュ構築時に1回だけ計算してキャッシュに
// 含めるため、クエリごとの追加コストはハミング距離の計算のみで済む。
// corpusが小さいうち（SHORTLIST_THRESHOLD以下）は従来通り全件を厳密計算するため、
// 現状規模での挙動・精度は変わらない。
// ─────────────────────────────────────────────
var SHORTLIST_THRESHOLD  = 300;  // namespace内の行数がこれを超えたら2段検索に切り替える
var SHORTLIST_MIN_POOL   = 300;  // 厳密計算に残す候補の最小件数
var SHORTLIST_MULTIPLIER = 15;   // 厳密計算に残す候補件数 = limit * この倍率（下限はMIN_POOL）

/** 埋め込みベクトルを16bitチャンクの配列に量子化する（各次元の符号ビットのみ使用） */
function _packSignature_(emb) {
  var sig = [], cur = 0, bits = 0;
  for (var i = 0; i < emb.length; i++) {
    cur = (cur << 1) | (emb[i] >= 0 ? 1 : 0);
    bits++;
    if (bits === 16) { sig.push(cur & 0xFFFF); cur = 0; bits = 0; }
  }
  if (bits > 0) sig.push((cur << (16 - bits)) & 0xFFFF);
  return sig;
}

function _popcount16_(x) {
  x = x - ((x >> 1) & 0x5555);
  x = (x & 0x3333) + ((x >> 2) & 0x3333);
  x = (x + (x >> 4)) & 0x0f0f;
  return (x + (x >> 8)) & 0xff;
}

/** 2つの2値シグネチャ間のハミング距離（値が小さいほど類似） */
function _hammingDistance_(sigA, sigB) {
  var dist = 0;
  for (var i = 0; i < sigA.length; i++) dist += _popcount16_((sigA[i] ^ sigB[i]) & 0xFFFF);
  return dist;
}

/**
 * rows（namespaceでフィルタ済みの行）に対してコサイン類似度でMIN_SCORE以上の
 * ベクトル候補を返す。行数がSHORTLIST_THRESHOLDを超える場合は、先にハミング距離で
 * 近似ショートリストを作り、厳密なコサイン類似度計算はそのショートリストのみに対して
 * 行うことで計算量を抑える（結果の意味・スコアの計算方法自体は変えていない）。
 */
function _vectorCandidatesFor_(qv, rows, minScore, limit) {
  var pool = rows;
  if (rows.length > SHORTLIST_THRESHOLD) {
    var qSig = _packSignature_(qv);
    var ranked = rows.map(function(row) {
      if (!row.sig) row.sig = _packSignature_(row.emb); // 旧キャッシュ由来でsig未計算の行への保険
      return { row: row, dist: _hammingDistance_(qSig, row.sig) };
    });
    ranked.sort(function(a, b) { return a.dist - b.dist; });
    var poolSize = Math.min(rows.length, Math.max(SHORTLIST_MIN_POOL, limit * SHORTLIST_MULTIPLIER));
    pool = ranked.slice(0, poolSize).map(function(r) { return r.row; });
  }
  var out = [];
  pool.forEach(function(row) {
    var score = cosineSimilarity_(qv, row.emb);
    if (score < minScore) return;
    out.push({ score: score, db: row.db, title: row.title, text: row.text });
  });
  return out;
}

function searchByEmbedding_(query, dbKey, limit, allowedNamespaces, preEmb) {
  limit = limit || 5;
  var qv = preEmb || embedQuery_(query);
  if (!qv) return [];
  var idx = loadIndex_();
  if (!idx.length) return [];

  var MIN_SCORE = minScoreFor_(dbKey);
  var FETCH_K   = limit * 3;    // ページ重複排除前の候補数

  var filtered = [];
  idx.forEach(function(row) {
    if (allowedNamespaces && allowedNamespaces.indexOf(row.db) === -1) return;
    if (dbKey && dbKey !== 'all' && row.db !== dbKey) return;
    filtered.push(row);
  });

  var candidates;
  if (_usesHybridSearch_(dbKey)) {
    // BM25+RRFハイブリッド: ベクトル候補（MIN_SCOREでフィルタ）とBM25候補
    // （キーワード一致の実証があるためスコアでフィルタしない）をRRFでマージする。
    // BM25はキーワード一致の照合コストが低いため、ショートリストの対象にせず全件を見る。
    var vectorCandidates = _vectorCandidatesFor_(qv, filtered, MIN_SCORE, FETCH_K);
    vectorCandidates.sort(function(a, b) { return b.score - a.score; });

    var bm25Candidates = _bm25SearchCandidates_(query, filtered, FETCH_K);
    candidates = _rrfMerge_(vectorCandidates.slice(0, FETCH_K), bm25Candidates, FETCH_K);
  } else {
    candidates = _vectorCandidatesFor_(qv, filtered, MIN_SCORE, FETCH_K);
    candidates.sort(function(a, b) { return b.score - a.score; });
  }

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

// ─────────────────────────────────────────────
// BM25 + RRF ハイブリッド検索
//
// GASには形態素解析ライブラリ（SudachiPy等）が無い。当初はLocal RAG
// （scripts/vector_database.py の _tokenize）のregexフォールバックと同じ
// 「CJK連続runを1トークンとして扱う」方式を移植したが、実際の質問文
// （例:「コネクトラインについて教えて」）は助詞込みで句読点が無いため
// 全体が1つの巨大トークンになってしまい、ドキュメント側の短いトークン
// （例:「コネクトライン」）と一切一致しないことがテストで判明した。
// そのため、CJKの連続runは2文字スライド窓のbigramに分割する方式に変更した
// （検索エンジンのCJK対応で広く使われる標準的な手法）。多少ノイズは増えるが、
// 助詞の有無に関わらず固有名詞・キーワード部分の重なりでBM25スコアが機能する。
// 英数字・型番（BTQ-116等）は従来通りそのままトークン化する。
// ─────────────────────────────────────────────

function _bm25Tokenize_(text) {
  var tokens = [];
  var alphaMatches = String(text).match(/[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*/g) || [];
  alphaMatches.forEach(function(t) { if (t.length > 1) tokens.push(t.toLowerCase()); });
  var cjkMatches = String(text).match(/[぀-ヿ一-鿿]{2,}/g) || [];
  cjkMatches.forEach(function(run) {
    if (run.length <= 2) { tokens.push(run); return; }
    for (var i = 0; i < run.length - 1; i++) tokens.push(run.substring(i, i + 2));
  });
  var seen = {}, out = [];
  tokens.forEach(function(t) { if (!seen[t]) { seen[t] = true; out.push(t); } });
  return out.length ? out : String(text).split(/\s+/).filter(function(s) { return s; });
}

/** BM25スコア（Okapi BM25、k1=1.5, b=0.75の標準的な値） */
function _bm25Score_(queryTokens, docTokens, df, avgdl, N) {
  var k1 = 1.5, b = 0.75;
  var docLen = docTokens.length || 1;
  var termFreq = {};
  docTokens.forEach(function(t) { termFreq[t] = (termFreq[t] || 0) + 1; });
  var score = 0;
  queryTokens.forEach(function(qt) {
    var f = termFreq[qt] || 0;
    if (f === 0) return;
    var n = df[qt] || 0;
    var idf = Math.log(1 + (N - n + 0.5) / (n + 0.5));
    score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * (docLen / avgdl)));
  });
  return score;
}

/**
 * filtered（namespace/dbKeyで絞り込み済みの候補、row.tokensを含む）に対して
 * BM25スコアを計算し、スコア>0（クエリ語を1つ以上含む）の候補を上位limit件返す。
 */
function _bm25SearchCandidates_(query, filtered, limit) {
  var queryTokens = _bm25Tokenize_(query);
  if (!queryTokens.length || !filtered.length) return [];

  var N = filtered.length;
  var df = {};
  filtered.forEach(function(row) {
    var seen = {};
    (row.tokens || []).forEach(function(t) {
      if (seen[t]) return;
      seen[t] = true;
      df[t] = (df[t] || 0) + 1;
    });
  });
  var totalLen = 0;
  filtered.forEach(function(row) { totalLen += (row.tokens || []).length; });
  var avgdl = totalLen / N || 1;

  var scored = filtered.map(function(row) {
    return {
      score: _bm25Score_(queryTokens, row.tokens || [], df, avgdl, N),
      db: row.db, title: row.title, text: row.text,
    };
  }).filter(function(c) { return c.score > 0; });
  scored.sort(function(a, b) { return b.score - a.score; });
  return scored.slice(0, limit);
}

/**
 * Reciprocal Rank Fusion でベクトル検索とBM25の結果をマージする。
 * RRF score = 1/(k + vector_rank) + 1/(k + bm25_rank)、k=60（Local RAGと同じ標準値）。
 */
function _rrfMerge_(vectorResults, bm25Results, limit) {
  var rrfScores = {}, itemMap = {};
  var k = 60;
  function keyOf(r) { return r.db + '::' + r.title; }

  vectorResults.forEach(function(r, rank) {
    var key = keyOf(r);
    rrfScores[key] = (rrfScores[key] || 0) + 1 / (k + rank + 1);
    itemMap[key] = r;
  });
  bm25Results.forEach(function(r, rank) {
    var key = keyOf(r);
    rrfScores[key] = (rrfScores[key] || 0) + 1 / (k + rank + 1);
    if (!itemMap[key]) itemMap[key] = r;
  });

  var merged = Object.keys(rrfScores).map(function(key) {
    var item = itemMap[key];
    return { score: rrfScores[key], db: item.db, title: item.title, text: item.text };
  });
  merged.sort(function(a, b) { return b.score - a.score; });
  return merged.slice(0, limit);
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

/**
 * 戻り値は { emb, hydeTokens, embedCharsQuery, embedCharsHypo }。
 * hydeTokensはHyDE仮説文書生成（generateContent）のusageMetadata.totalTokenCountの実測値。
 * embedContentのレスポンスにはusageMetadataが含まれないため、埋め込み2回分は
 * トークン数を実測できず、代わりに入力文字数（目安値。正確なトークン数ではない）を返す。
 * ユーザーごとのトークン使用量集計（recordTokenUsage_）で使う。
 */
function hydeExpand_(query, dbKey) {
  var embedCharsQuery = Math.min(query.length, 2000);
  try {
    var apiKey = getProps_().getProperty('GEMINI_API_KEY');
    var url    = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=' + apiKey;
    var prompt = hydePromptFor_(dbKey) + query;
    var payload = JSON.stringify({
      contents: [{ role: 'user', parts: [{ text: prompt }]}],
      generationConfig: { temperature: 0.1, maxOutputTokens: 256 },
    });
    var res = UrlFetchApp.fetch(url, { method: 'post', contentType: 'application/json', payload: payload, muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) {
      return { emb: embedQuery_(query), hydeTokens: 0, embedCharsQuery: embedCharsQuery, embedCharsHypo: 0 };
    }
    var genBody    = JSON.parse(res.getContentText());
    var hypoDoc    = genBody.candidates[0].content.parts[0].text;
    var hydeTokens = (genBody.usageMetadata && genBody.usageMetadata.totalTokenCount) || 0;
    var embedCharsHypo = Math.min(hypoDoc.length, 2000);
    // クエリと仮説文書の埋め込みは互いに独立しているため、直列fetchではなくfetchAllで並列実行する
    var embResps = UrlFetchApp.fetchAll([
      embedRequest_(query, 'RETRIEVAL_QUERY'),
      embedRequest_(hypoDoc, 'RETRIEVAL_DOCUMENT'),
    ]);
    var queryEmb = parseEmbedResponse_(embResps[0]);
    var hypoEmb  = parseEmbedResponse_(embResps[1]);
    if (!queryEmb || !hypoEmb) {
      return { emb: queryEmb, hydeTokens: hydeTokens, embedCharsQuery: embedCharsQuery, embedCharsHypo: embedCharsHypo };
    }
    // 固有事実ドメインはクエリ80%+仮説20%（仮説のハルシネーション影響を抑制）、
    // 技術ドメインはクエリ40%+仮説60%（仮説文書が語彙ギャップを橋渡しする効果を活かす）
    var queryWeight = FACT_HEAVY_DOMAINS.indexOf(dbKey) !== -1 ? 0.8 : 0.4;
    var hypoWeight  = 1 - queryWeight;
    var merged = queryEmb.map(function(v, i) { return v * queryWeight + hypoEmb[i] * hypoWeight; });
    return { emb: merged, hydeTokens: hydeTokens, embedCharsQuery: embedCharsQuery, embedCharsHypo: embedCharsHypo };
  } catch(e) {
    Logger.log('HyDE fallback: ' + e.message);
    return { emb: embedQuery_(query), hydeTokens: 0, embedCharsQuery: embedCharsQuery, embedCharsHypo: 0 };
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

/**
 * dbKeyのnamespaceがlogMemory:falseの場合は何も保存せず空文字を返す
 * （問診・健康関連など機微な内容を扱うnamespace向け。docs/cloud-rag.md参照）。
 */
function saveMemory_(apiKey, query, answer, sources, dbKey) {
  if (dbKey && !_shouldLogMemory_(dbKey)) return '';
  try {
    var sheet  = getMemorySheet_();
    if (!sheet) return '';
    var id     = new Date().getTime().toString(36) + Math.random().toString(36).slice(2, 5);
    var prefix = apiKey.substring(0, 8);
    var ts     = new Date().toISOString();
    // score も保存しておくことで、adminRatingStats側で👍/👎とスコアの相関を見て
    // MIN_SCORE閾値のチューニング判断ができるようにする。
    var srcStr = JSON.stringify((sources || []).slice(0, 5).map(function(s) {
      return { title: s.title, db: s.db, score: s.score };
    }));
    sheet.appendRow([id, prefix, ts, query.substring(0, 500), answer.substring(0, 1000), srcStr, '', 0.5]);
    return id;
  } catch(e) {
    Logger.log('saveMemory_ error: ' + e.message);
    return '';
  }
}

/**
 * RAG_Memoryの保持期限（日数）を過ぎた行を削除する。
 * スクリプトプロパティ MEMORY_RETENTION_DAYS が未設定（0以下）なら何もしない
 * （既定オフ・既存デプロイの挙動は変えない）。
 */
function purgeExpiredMemory_() {
  var days = parseInt(getProps_().getProperty('MEMORY_RETENTION_DAYS') || '0', 10);
  if (!days || days <= 0) return { purged: 0, enabled: false };
  var sheet = getMemorySheet_();
  if (!sheet) return { purged: 0, enabled: true };

  var cutoff = new Date().getTime() - days * 24 * 60 * 60 * 1000;
  var data   = sheet.getDataRange().getValues();
  var toDelete = [];
  for (var r = 1; r < data.length; r++) {
    var ts = Date.parse(String(data[r][2]));
    if (!isNaN(ts) && ts < cutoff) toDelete.push(r + 1);
  }
  toDelete.sort(function(a, b) { return b - a; });
  toDelete.forEach(function(ri) { sheet.deleteRow(ri); });
  return { purged: toDelete.length, enabled: true };
}

/** 管理UI/手動実行用: RAG_Memoryの期限切れ行を即時削除する */
function adminPurgeExpiredMemory(apiKey) {
  requireAdmin_(apiKey);
  return purgeExpiredMemory_();
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
// Claude (Anthropic) プロキシ
//
// houdini21チュートリアル生成（tutorial_agent.py）用。クライアントは生の
// ANTHROPIC_API_KEYを持たず、この関数がスクリプトプロパティ ANTHROPIC_API_KEY を
// 使って代理でMessages APIを呼ぶ。doPost側で認証・レート制限・Claude専用トークン
// 予算（claudeCapacity/claudeBalance）を先にチェックしてから呼ばれる。
// ─────────────────────────────────────────────

/**
 * bodyはHoudini側から届いた { model, max_tokens, system, tools, messages } をそのまま使う
 * （thinking等の追加パラメータもそのまま透過する）。
 * 戻り値は成功時 { status:'ok', content, stop_reason, usage, model, ... }（Claude APIの
 * レスポンスをそのまま展開しstatusを付加）、失敗時 { status:'error', error:{message} }。
 */
function callClaudeProxy_(body) {
  var apiKey = getProps_().getProperty('ANTHROPIC_API_KEY');
  if (!apiKey) {
    return { status: 'error', error: { message: 'ANTHROPIC_API_KEY が未設定です（GASのスクリプトプロパティを確認してください）' } };
  }
  var payload = JSON.stringify({
    model:      body.model,
    max_tokens: body.max_tokens,
    system:     body.system,
    tools:      body.tools,
    messages:   body.messages,
  });
  var maxRetries = 3, baseDelay = 2000, maxDelay = 20000;
  var lastError = null;
  for (var i = 0; i < maxRetries; i++) {
    var res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
      method: 'post', contentType: 'application/json',
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      payload: payload, muteHttpExceptions: true,
    });
    var code = res.getResponseCode();
    if (code === 200) {
      var claudeBody = JSON.parse(res.getContentText());
      claudeBody.status = 'ok';
      return claudeBody;
    }
    if ((code === 429 || code === 500 || code === 529) && i < maxRetries - 1) {
      var wait = Math.min(baseDelay * Math.pow(2, i), maxDelay) + Math.floor(Math.random() * 1000);
      Utilities.sleep(wait);
      lastError = 'Claude API 過負荷（' + code + '）';
      continue;
    }
    return { status: 'error', error: { message: 'Claude APIエラー ' + code + ': ' + res.getContentText().substring(0, 300) } };
  }
  return { status: 'error', error: { message: lastError || 'Claude APIリトライ上限到達' } };
}

// ─────────────────────────────────────────────
// Gemini
// ─────────────────────────────────────────────

/** 戻り値は { text, tokens }。tokensはusageMetadata.totalTokenCountの実測値（取得できなければ0）。 */
function callGemini_(contents) {
  var apiKey  = getProps_().getProperty('GEMINI_API_KEY');
  var url     = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=' + apiKey;
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
    if (code === 200) {
      var body = JSON.parse(res.getContentText());
      return {
        text: body.candidates[0].content.parts[0].text,
        tokens: (body.usageMetadata && body.usageMetadata.totalTokenCount) || 0,
      };
    }
    if ((code === 429 || code === 503) && i < maxRetries - 1) {
      var ra   = parseInt(((res.getHeaders() || {})['Retry-After'] || '0'), 10);
      var wait = ra > 0 ? ra * 1000 : Math.min(baseDelay * Math.pow(2, i), maxDelay) + Math.floor(Math.random() * 1000);
      Utilities.sleep(wait);
      continue;
    }
    return { text: '（Gemini APIエラー: ' + code + '）', tokens: 0 };
  }
  return { text: '（リトライ上限に達しました）', tokens: 0 };
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
    var title = data[i][2];
    var text  = String(data[i][3]).substring(0, 600);
    // BM25用のトークン・corpus増加対策の2値シグネチャ（_packSignature_）も
    // 合わせて事前計算しキャッシュに含める（毎クエリでの再計算を避ける）。
    // hybridSearch未使用のnamespaceでも計算コストは小さいため常に付与する。
    var embArr = JSON.parse(embStr);
    rows.push({
      db: data[i][1], title: title, text: text, emb: embArr,
      tokens: _bm25Tokenize_(title + ' ' + text),
      sig: _packSignature_(embArr),
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

/**
 * sheet.getRange(row, col, numRows, numCols).setValues(rows) は、対象範囲が
 * シートの現在の最大行数（getMaxRows()、シートの「グリッドサイズ」であって
 * 使用中の行数ではない）を超えていると「範囲の座標がシートのサイズから外れて
 * います」という例外になる。シートは新しい行に値を入れれば自動で増えるように
 * 見えるが、これはUIやappendRow()での挙動であり、getRange()で既存の範囲を
 * 超えて直接書き込む場合は事前にinsertRowsAfter()等で明示的に行を確保する
 * 必要がある。この関数は必要な分だけ事前に行を確保してから書き込む。
 */
function _appendRowsSafely_(sheet, rows, numCols) {
  if (!rows || rows.length === 0) return;
  var startRow = sheet.getLastRow() + 1;
  var neededThrough = startRow + rows.length - 1;
  var maxRows = sheet.getMaxRows();
  if (neededThrough > maxRows) {
    sheet.insertRowsAfter(maxRows, neededThrough - maxRows);
  }
  sheet.getRange(startRow, 1, rows.length, numCols).setValues(rows);
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

  var reqKeys = [], listReqs = [], dbIdByKey = {};
  Object.keys(DB_KEY_MAP).forEach(function(key) {
    var dbId = props.getProperty(DB_KEY_MAP[key]);
    if (!dbId) { Logger.log('DB未設定: ' + key); return; }
    reqKeys.push(key);
    dbIdByKey[key] = dbId;
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
    var body  = JSON.parse(res.getContentText());
    var pages = body.results || [];

    // 101件目以降がある場合はhas_more/next_cursorで残りを取得する。
    // 並列取得できるのは1ページ目まで（2ページ目以降はcursorが前ページの結果に
    // 依存するため直列にならざるを得ない）。安全のため最大1000ページ（10万件相当）で打ち切る。
    var hasMore = body.has_more, cursor = body.next_cursor, pageCount = 1;
    while (hasMore && cursor && pageCount < 1000) {
      var nextRes = UrlFetchApp.fetch('https://api.notion.com/v1/databases/' + dbIdByKey[key] + '/query', {
        method: 'post', headers: nHeaders, contentType: 'application/json',
        payload: JSON.stringify({ page_size: 100, start_cursor: cursor }), muteHttpExceptions: true,
      });
      if (nextRes.getResponseCode() !== 200) {
        Logger.log('[' + key + '] 追加ページ取得エラー（' + pages.length + '件までで打ち切り）: ' + nextRes.getResponseCode());
        break;
      }
      var nextBody = JSON.parse(nextRes.getContentText());
      pages = pages.concat(nextBody.results || []);
      hasMore = nextBody.has_more;
      cursor  = nextBody.next_cursor;
      pageCount++;
    }

    Logger.log('[' + key + '] ' + pages.length + 'ページ' + (pageCount > 1 ? '（' + pageCount + 'リクエストに分割）' : ''));
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
  _appendRowsSafely_(sheet, newRows, 6);
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
  _appendRowsSafely_(sheet, newRows, 6);
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
  // file.getBlob()はファイル全体をメモリに読み込む（音声・動画やスキャンPDF等は
  // 数十MB〜になりうる）。読み込んでから捨てるのではなく、Driveのメタデータだけで
  // 取得できるfile.getSize()で事前にサイズを確認し、上限超過ならgetBlob()自体を
  // 呼ばずにスキップする。ここを怠ると「メモリ不足のためエラーが発生しました」という
  // GASネイティブのエラーで実行全体が落ち、この1ファイルの失敗では済まなくなる。
  var isMedia = mime.indexOf('audio/') === 0 || mime.indexOf('video/') === 0;
  var maxBytes = isMedia ? _maxAudioVideoBytes_() : _maxDriveConvertBytes_();
  var size = file.getSize();
  if (size > maxBytes) {
    throw new Error(
      'ファイルサイズが大きすぎます（' + Math.round(size / 1024 / 1024) + 'MB > 上限' +
      Math.round(maxBytes / 1024 / 1024) + 'MB）。' +
      (isMedia
        ? 'scripts/youtube_transcribe.py等でローカルから文字起こしし、テキストを貼り付けてください（スクリプトプロパティMAX_AUDIO_VIDEO_MBで上限を調整できます）。'
        : 'ファイルを分割するか抜粋して再アップロードしてください（スクリプトプロパティMAX_DRIVE_CONVERT_MBで上限を調整できます）。')
    );
  }
  return _convertBinaryBlobToText_(file.getBlob(), file.getName());
}

/** Drive同期を今すぐ実行する（管理者のみ、WebAppから呼び出し可能） */
function adminSyncDrive(apiKey) {
  requireAdmin_(apiKey);
  return syncDriveToSheets();
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
// namespace管理（管理者向け）
//
// これまで新規namespaceの追加・Notion DB IDの紐付けはGASエディタの
// スクリプトプロパティ画面での手作業（NAMESPACE_CONFIGのJSON直接編集）が
// 必須だった。ここでは管理画面から namespace の追加・編集・Notion DB の
// 新規作成/紐付けまで行えるようにする。
// ─────────────────────────────────────────────

var NAMESPACE_NAME_RE = /^[a-z][a-z0-9_]{1,29}$/;

/**
 * NAMESPACE_CONFIGスクリプトプロパティに1 namespace分のパッチをマージして保存する。
 * NAMESPACE_CONFIG未設定（デフォルト構成のまま）の場合は、まずDEFAULT_NAMESPACE_CONFIG_を
 * ベースにコピーしてから保存する（既存namespaceの設定を失わないため）。
 * 変更はこの関数を呼んだ実行内では反映されない（DB_KEY_MAP等はスクリプト読み込み時に
 * 一度だけ計算されるグローバル変数のため）。次回のGAS実行（次のリクエスト）から有効になる。
 */
function _saveNamespaceConfigEntry_(ns, patch) {
  var merged = {};
  Object.keys(_NAMESPACE_CONFIG_).forEach(function(k) { merged[k] = _NAMESPACE_CONFIG_[k]; });
  merged[ns] = Object.assign({}, merged[ns] || {}, patch);
  getProps_().setProperty('NAMESPACE_CONFIG', JSON.stringify(merged));
  return merged;
}

/** 全namespaceの現在の設定を一覧で返す（管理者のみ）。DB管理タブの表示に使う。 */
function adminListNamespaces(apiKey) {
  requireAdmin_(apiKey);
  var props = getProps_();
  return ALL_NAMESPACES.map(function(ns) {
    return {
      ns:            ns,
      label:         DB_LABELS[ns] || ns,
      source:        NAMESPACE_SOURCE_MAP[ns] || 'notion',
      hybridSearch:  !!NAMESPACE_HYBRID_MAP[ns],
      logMemory:     NAMESPACE_LOG_MEMORY_MAP[ns] !== false,
      notionDbId:    props.getProperty(DB_KEY_MAP[ns]) || '',
      driveFolderId: props.getProperty(DRIVE_KEY_MAP[ns]) || '',
    };
  });
}

/**
 * 新規namespaceを追加する（管理者のみ）。
 * opts: { source, hybridSearch, logMemory, notionDbId, createNotionDb, driveFolderId }
 * createNotionDb:true の場合、NOTION_PARENT_PAGE_ID配下に新規Notion DBを自動作成して紐付ける
 * （notionDbIdが指定されていればそちらを優先し、新規作成はしない）。
 */
function adminCreateNamespace(apiKey, ns, label, opts) {
  requireAdmin_(apiKey);
  opts = opts || {};
  ns = String(ns || '').trim();
  label = String(label || '').trim();
  if (!NAMESPACE_NAME_RE.test(ns)) {
    throw new Error('namespaceは英小文字で始まる半角英数字・アンダースコアのみ、2〜30文字で指定してください: ' + ns);
  }
  if (ALL_NAMESPACES.indexOf(ns) !== -1) {
    throw new Error('このnamespaceは既に存在します: ' + ns);
  }
  if (!label) throw new Error('ラベルは必須です');

  var patch = { label: label };
  if (opts.source === 'drive' || opts.source === 'both') patch.source = opts.source;
  if (opts.hybridSearch) patch.hybridSearch = true;
  if (opts.logMemory === false) patch.logMemory = false;
  _saveNamespaceConfigEntry_(ns, patch);

  var suffix = _namespacePropSuffix_(ns);
  var result = { ns: ns, notionDbId: '', driveFolderId: '' };

  if (opts.createNotionDb && !opts.notionDbId) {
    result.notionDbId = _createNotionDatabase_(label);
    getProps_().setProperty('DB_' + suffix, result.notionDbId);
  } else if (opts.notionDbId) {
    result.notionDbId = String(opts.notionDbId).trim();
    getProps_().setProperty('DB_' + suffix, result.notionDbId);
  }

  if (opts.driveFolderId) {
    var folderId = String(opts.driveFolderId).trim();
    try { DriveApp.getFolderById(folderId); }
    catch(e) { throw new Error('Driveフォルダにアクセスできません。共有設定を確認してください: ' + folderId); }
    result.driveFolderId = folderId;
    getProps_().setProperty('DRIVE_' + suffix, result.driveFolderId);
  }

  return result;
}

/** 既存namespaceのラベル・source・hybridSearch・logMemoryを更新する（管理者のみ） */
function adminUpdateNamespace(apiKey, ns, patch) {
  requireAdmin_(apiKey);
  patch = patch || {};
  if (ALL_NAMESPACES.indexOf(ns) === -1) throw new Error('存在しないnamespaceです: ' + ns);
  var label = String(patch.label || '').trim();
  if (!label) throw new Error('ラベルは必須です');

  // source・hybridSearch・logMemoryは常に明示的に上書きする（例えばsourceを
  // 'notion'に戻す・hybridSearchをOFFに戻す操作も反映されるように。
  // _saveNamespaceConfigEntry_はパッチをマージするだけなので、値を省略すると
  // 既存の値が残ってしまい既定値に戻せなくなる）
  var clean = {
    label:        label,
    source:       (patch.source === 'drive' || patch.source === 'both') ? patch.source : 'notion',
    hybridSearch: !!patch.hybridSearch,
    logMemory:    patch.logMemory !== false,
  };
  _saveNamespaceConfigEntry_(ns, clean);
  return { ok: true };
}

/** namespaceに対応するNotion DB IDを設定・解除する（管理者のみ。adminSetDriveFolderのNotion版） */
function adminSetNotionDbId(apiKey, ns, dbId) {
  requireAdmin_(apiKey);
  if (!DB_KEY_MAP[ns]) throw new Error('無効なnamespaceです: ' + ns);
  var props = getProps_();
  dbId = (dbId || '').trim();
  if (!dbId) {
    props.deleteProperty(DB_KEY_MAP[ns]);
    return { ok: true, cleared: true };
  }
  props.setProperty(DB_KEY_MAP[ns], dbId);
  return { ok: true, cleared: false };
}

/**
 * Notion APIで新規データベースを作成する。スクリプトプロパティNOTION_PARENT_PAGE_ID
 * （新規DBの作成先の親ページID）が必須。作成するDBは既存のnamespace用DBと同じ標準スキーマ
 * （title / summary(rich_text) / tags(multi_select) / source_url(url)）を持つ。
 * 親ページに対してNotion Integrationの接続（共有設定）が事前に必要（Notion側の手動操作）。
 */
function _createNotionDatabase_(title) {
  var parentPageId = getProps_().getProperty('NOTION_PARENT_PAGE_ID');
  if (!parentPageId) {
    throw new Error('NOTION_PARENT_PAGE_ID が未設定です。新規DBの作成先とするNotionページのIDをスクリプトプロパティに設定し、そのページにIntegrationを接続してください。');
  }
  var payload = {
    parent: { type: 'page_id', page_id: parentPageId },
    title:  [{ type: 'text', text: { content: title } }],
    properties: {
      title:      { title: {} },
      summary:    { rich_text: {} },
      tags:       { multi_select: {} },
      source_url: { url: {} },
    },
  };
  var res = UrlFetchApp.fetch('https://api.notion.com/v1/databases', {
    method: 'post', headers: notionHeaders_(), contentType: 'application/json',
    payload: JSON.stringify(payload), muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    throw new Error('Notion DBの作成に失敗しました: ' + res.getContentText().substring(0, 300));
  }
  return JSON.parse(res.getContentText()).id;
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
 * RAG_Memory・KB_Log・RAG_TokenUsage・API_KEYS_CONFIG をGoogle Driveの専用
 * フォルダにタイムスタンプ付きでエクスポートする（管理者のみ、GASエディタから手動実行）。
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

  var usageSheet = getTokenUsageSheet_();
  if (usageSheet && usageSheet.getLastRow() > 0) {
    var usageFile = folder.createFile('RAG_TokenUsage_' + timestamp + '.csv', sheetToCsv_(usageSheet), MimeType.CSV);
    filesCreated.push(usageFile.getName());
  }

  var claudeUsageSheet = getClaudeUsageSheet_();
  if (claudeUsageSheet && claudeUsageSheet.getLastRow() > 0) {
    var claudeUsageFile = folder.createFile('RAG_ClaudeUsage_' + timestamp + '.csv', sheetToCsv_(claudeUsageSheet), MimeType.CSV);
    filesCreated.push(claudeUsageFile.getName());
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
  _appendRowsSafely_(sheet, rows, 6);
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
 * 変換元のバイナリMIMEタイプから、変換先とすべきGoogle Workspaceネイティブ形式を判定する。
 * v2の`convert:true`（ターゲット未指定）は拡張子から自動でこれと同じ判定をしていたが、
 * v3では変換先をresource.mimeTypeとして明示しないと変換自体が起きない。
 */
function _targetGoogleMimeFor_(sourceMime) {
  var m = (sourceMime || '').toLowerCase();
  if (m.indexOf('spreadsheet') !== -1 || m.indexOf('excel') !== -1) {
    return 'application/vnd.google-apps.spreadsheet';
  }
  if (m.indexOf('presentation') !== -1 || m.indexOf('powerpoint') !== -1) {
    return 'application/vnd.google-apps.presentation';
  }
  // PDF・画像・Word・その他はGoogleドキュメントに変換する（PDF/画像はこの変換時にOCRが自動で掛かる）
  return 'application/vnd.google-apps.document';
}

/**
 * バイナリblobをGoogle Workspaceネイティブ形式へ変換して保存する（PDF/画像はOCR付き）。
 *
 * Drive Advanced ServiceはGASエディタでの有効化時にv2/v3どちらのバージョンで追加したかで
 * メソッド名・パラメータの意味が異なるため、実行時にどちらが生えているかで吸収する。
 *   - v2: Files.insert({title,...}, blob, {convert:true, ocr:true}) で自動的に適切な
 *     ネイティブ形式に変換され、{id, mimeType, ...} が返る。
 *   - v3: Files.create({name,...}, blob, opts)。v2の`convert`パラメータはv3には無く、
 *     resource.mimeTypeに変換先を明示することで変換が起きる（PDF/画像→Googleドキュメント
 *     への変換時にOCRが自動で掛かる）。既定では`id`しか返らないため`fields`を明示指定する。
 *     この違いに気づかず`convert:true`をそのままoptionsとして渡していたため、v3環境では
 *     変換が一切起きず、未変換のPDF生バイナリをUTF-8として読んで文字化けする不具合があった。
 */
function _driveFilesCreate_(displayName, blob) {
  var targetMime = _targetGoogleMimeFor_(blob.getContentType());
  if (typeof Drive.Files.create === 'function') {
    return Drive.Files.create(
      { name: displayName, mimeType: targetMime },
      blob,
      { fields: 'id,mimeType', ocrLanguage: 'ja' }
    );
  }
  if (typeof Drive.Files.insert === 'function') {
    return Drive.Files.insert({ title: displayName }, blob, { convert: true, ocr: true });
  }
  throw new Error('Drive.Files.create/insert が見つかりません。Drive APIの有効化状態を確認してください。');
}

function _driveFilesRemove_(fileId) {
  if (typeof Drive.Files.remove === 'function') { Drive.Files.remove(fileId); return; }
  if (typeof Drive.Files.delete === 'function') { Drive.Files.delete(fileId); return; }
  throw new Error('Drive.Files.remove/delete が見つかりません。');
}

/**
 * バイナリ（PDF・Word・Excel・PowerPoint・画像等）を Drive API でOCR変換してテキスト抽出する。
 * 変換で作られる一時ファイルは抽出後に削除する。音声・動画はDriveのOCR変換の対象外
 * （OCRは画像・文書用で、音声波形の書き起こしはできない）なので、_transcribeAudioVideoBlob_
 * （Gemini Files APIでの文字起こし）に振り分ける。
 */
function _convertBinaryBlobToText_(blob, displayName) {
  var mime = (blob.getContentType() || '').toLowerCase();
  if (mime.indexOf('audio/') === 0 || mime.indexOf('video/') === 0) {
    return _transcribeAudioVideoBlob_(blob, displayName);
  }
  if (typeof Drive === 'undefined') {
    throw new Error('この形式の取り込みには Drive API が必要です。GASエディタ左の「サービス +」から Drive API を追加してください');
  }
  var converted = _driveFilesCreate_('[RAG一時] ' + displayName, blob);
  try {
    // 変換が実際に起きていれば converted.mimeType は必ず application/vnd.google-apps.*
    // になる。そうなっていない場合（＝変換に失敗し元のバイナリのまま保存された場合）に
    // 「テキストが空だから」と未変換の生バイナリをUTF-8として読んでしまうと、PDF等の
    // バイナリが文字化けしたテキストとしてそのままRAGに登録されてしまう（実際に発生した
    // 不具合）。変換が起きていないことが分かった時点で、はっきりエラーにする。
    if (String(converted.mimeType || '').indexOf('application/vnd.google-apps.') !== 0) {
      throw new Error(
        'Driveでのファイル形式変換に失敗しました（変換後もmimeTypeが「' + converted.mimeType +
        '」のままでした）。パスワード保護・破損したファイルの可能性があります。'
      );
    }
    return _extractNativeGoogleText_(converted.id, converted.mimeType);
  } finally {
    try { _driveFilesRemove_(converted.id); }
    catch(e) { try { DriveApp.getFileById(converted.id).setTrashed(true); } catch(e2) {} }
  }
}

// バイナリファイルの取り込みサイズには3つの制約が絡む:
//   ① UrlFetchApp 1回のPOSTペイロードは50MBまで（GASの固定クオータ）
//      → resumable upload protocolのchunked commandで分割送信すれば回避できる
//        （GEMINI_UPLOAD_CHUNK_BYTES単位で複数回POSTする）
//   ② GASの1回の実行時間は6分まで（アップロード＋Gemini側の処理待ち＋文字起こし生成の合計）
//      → コード側で回避できない絶対的な上限。ファイルサイズよりも「音声・動画の長さ」に効く
//   ③ GAS（V8ランタイム）自体のメモリ上限
//      → blob.getBytes()でファイル全体をJSの数値配列としてメモリに展開する時点で、
//        生バイト数の数倍のヒープを消費しうる。これは①のような「分割送信」では回避できない
//        （メモリ不足はgetBytes()やDrive変換の時点、＝アップロードが始まる前に起きるため）。
//        実際に「メモリ不足のためエラーが発生しました」というGAS側のネイティブなエラーで
//        実行ごと落ちることがあり、通常のtry/catchでは捕捉できない。
// そのため、①をchunkingで回避しても③が実質的な上限になる。既定値は保守的に設定し、
// スクリプトプロパティ MAX_AUDIO_VIDEO_MB / MAX_DRIVE_CONVERT_MB で環境に応じて調整できる
// ようにしている（同じGASプロジェクトでもアカウントや同時実行状況で余裕は変わりうるため）。
var GEMINI_UPLOAD_CHUNK_BYTES        = 8 * 1024 * 1024; // 1回のUrlFetchApp POSTで送るチャンクサイズ
var DEFAULT_MAX_AUDIO_VIDEO_MB       = 15; // 音声・動画（Gemini文字起こし経由）の既定上限
var DEFAULT_MAX_DRIVE_CONVERT_MB     = 25; // PDF/Office/画像（Drive変換経由）の既定上限

function _mbOverride_(propName, fallbackMb) {
  var parsed = parseInt(getProps_().getProperty(propName) || '', 10);
  return (parsed > 0 ? parsed : fallbackMb) * 1024 * 1024;
}

/** 音声・動画（Gemini Files API経由）の取り込み上限バイト数 */
function _maxAudioVideoBytes_() { return _mbOverride_('MAX_AUDIO_VIDEO_MB', DEFAULT_MAX_AUDIO_VIDEO_MB); }

/** PDF/Office/画像（Drive変換経由）の取り込み上限バイト数 */
function _maxDriveConvertBytes_() { return _mbOverride_('MAX_DRIVE_CONVERT_MB', DEFAULT_MAX_DRIVE_CONVERT_MB); }

/**
 * Gemini Files APIへresumable upload protocolでアップロードする。50MBを超える
 * ペイロードは1回のUrlFetchApp POSTで送れないため、GEMINI_UPLOAD_CHUNK_BYTES単位で
 * 分割し、最後のチャンクだけ command:'upload, finalize' を付けて送信する。
 */
function _uploadBytesToGeminiFile_(bytes, mimeType, displayName, apiKey) {
  var startRes = UrlFetchApp.fetch(
    'https://generativelanguage.googleapis.com/upload/v1beta/files?key=' + apiKey,
    {
      method: 'post',
      contentType: 'application/json',
      headers: {
        'X-Goog-Upload-Protocol': 'resumable',
        'X-Goog-Upload-Command': 'start',
        'X-Goog-Upload-Header-Content-Length': String(bytes.length),
        'X-Goog-Upload-Header-Content-Type': mimeType,
      },
      payload: JSON.stringify({ file: { display_name: displayName } }),
      muteHttpExceptions: true,
    }
  );
  if (startRes.getResponseCode() >= 300) {
    throw new Error('Gemini Files APIへのアップロード開始に失敗しました: ' + startRes.getContentText().substring(0, 300));
  }
  var startHeaders = startRes.getAllHeaders();
  var uploadUrl = startHeaders['X-Goog-Upload-URL'] || startHeaders['x-goog-upload-url'];
  if (!uploadUrl) throw new Error('Gemini Files APIのアップロードURLが取得できませんでした。');

  var offset = 0, uploadRes;
  while (offset < bytes.length) {
    var end     = Math.min(offset + GEMINI_UPLOAD_CHUNK_BYTES, bytes.length);
    var chunk   = bytes.slice(offset, end);
    var isLast  = end === bytes.length;
    uploadRes = UrlFetchApp.fetch(uploadUrl, {
      method: 'post',
      headers: {
        'Content-Length': String(chunk.length),
        'X-Goog-Upload-Offset': String(offset),
        'X-Goog-Upload-Command': isLast ? 'upload, finalize' : 'upload',
      },
      payload: chunk,
      muteHttpExceptions: true,
    });
    if (uploadRes.getResponseCode() >= 300) {
      throw new Error('Gemini Files APIへのアップロードに失敗しました（offset=' + offset + '）: ' + uploadRes.getContentText().substring(0, 300));
    }
    offset = end;
  }
  var fileInfo = (JSON.parse(uploadRes.getContentText()) || {}).file || {};
  if (!fileInfo.uri) throw new Error('Gemini Files APIの応答からファイルURIを取得できませんでした。');
  return fileInfo;
}

/**
 * 音声・動画ファイルをGemini Files APIにアップロードし、generateContentで文字起こし
 * （動画は画面に表示されている技術情報の補足も依頼する）する。GEMINI_API_KEYを使う。
 */
function _transcribeAudioVideoBlob_(blob, displayName) {
  var apiKey = getProps_().getProperty('GEMINI_API_KEY');
  if (!apiKey) throw new Error('GEMINI_API_KEY が未設定です。音声・動画の文字起こしにはGemini APIキーが必要です。');

  // 注意: この時点でblobは呼び出し元（Drive/手動アップロード）で既に構築済みのため、
  // ここでのサイズ判定は「手遅れ」になりうる（メモリ不足は多くの場合blob構築時点で
  // 起きる）。呼び出し元（extractDriveFileText_ / adminKbUploadDoc）側で、blobを
  // 作る前にサイズを確認して弾くのが主な防御線。ここでは二重チェックとして残す。
  var maxBytes = _maxAudioVideoBytes_();
  var bytes = blob.getBytes();
  if (bytes.length > maxBytes) {
    throw new Error(
      'ファイルサイズが大きすぎます（' + Math.round(bytes.length / 1024 / 1024) + 'MB）。' +
      'GAS経由での音声・動画取り込みは' + Math.round(maxBytes / 1024 / 1024) + 'MB程度までです' +
      '（スクリプトプロパティMAX_AUDIO_VIDEO_MBで調整可）。' +
      '長い動画・講演等はscripts/youtube_transcribe.py等でローカルから文字起こしし、' +
      'そのテキストを「文字起こしを貼り付け」欄に貼ってください。'
    );
  }
  var mimeType = blob.getContentType() || 'application/octet-stream';

  var fileInfo = _uploadBytesToGeminiFile_(bytes, mimeType, displayName, apiKey);
  var fileUri  = fileInfo.uri;
  var fileName = fileInfo.name;

  // ACTIVEになるまで待つ（音声・動画は変換にやや時間がかかることがある。ファイルが
  // 大きいほど処理時間も伸びるため、GASの6分実行上限を考慮して待ち回数は控えめにしている）
  if (fileName) {
    for (var i = 0; i < 15; i++) {
      var stateRes = UrlFetchApp.fetch(
        'https://generativelanguage.googleapis.com/v1beta/' + fileName + '?key=' + apiKey,
        { muteHttpExceptions: true }
      );
      if (stateRes.getResponseCode() >= 300) break;
      var state = (JSON.parse(stateRes.getContentText()) || {}).state;
      if (state === 'ACTIVE') break;
      if (state === 'FAILED') throw new Error('Gemini側でのファイル処理に失敗しました（FAILED）。');
      Utilities.sleep(2000);
    }
  }

  // 文字起こし（動画は画面表示の技術情報の補足も依頼する）
  var prompt = mimeType.indexOf('video/') === 0
    ? 'この動画を日本語で書き起こしてください。話されている内容は要約せず逐語的に書き取り、画面に表示' +
      'されている重要な技術情報（UI操作・パラメータ名・数値等）があれば「[画面表示: ...]」として補足' +
      'してください。製品名・技術用語・型番は、聞き取れた/読み取れた通りの表記でそのまま残してください。'
    : 'この音声を日本語で文字起こししてください。要約や意訳はせず、話されている内容をできるだけ逐語的に' +
      '書き取ってください。製品名・技術用語・型番は、聞き取れた通りの表記でそのまま残してください。';

  var genRes = UrlFetchApp.fetch(
    'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=' + apiKey,
    {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({
        contents: [{
          role: 'user',
          parts: [
            { text: prompt },
            { file_data: { mime_type: mimeType, file_uri: fileUri } },
          ],
        }],
        generationConfig: { temperature: 0.1 },
      }),
      muteHttpExceptions: true,
    }
  );
  if (genRes.getResponseCode() >= 300) {
    throw new Error('Geminiでの文字起こしに失敗しました: ' + genRes.getContentText().substring(0, 300));
  }
  var genBody = JSON.parse(genRes.getContentText());
  var part = ((((genBody.candidates || [])[0] || {}).content || {}).parts || [])[0];
  var text = part && part.text;
  if (!text) throw new Error('Geminiの応答から文字起こしを取り出せませんでした。');
  return text.trim();
}

function adminKbUploadDoc(apiKey, dbKey, filename, base64Data, mimeType) {
  kbCheckDb_(apiKey, dbKey);
  // Utilities.base64Decode()自体がファイル全体をメモリに展開する重い処理なので、
  // デコード前にBase64文字列の長さから概算サイズ（decoded ≈ base64.length * 3/4）を
  // 出し、上限超過ならデコードせずに弾く（デコードしてから捨てるのでは遅い）。
  var mime = (mimeType || '').toLowerCase();
  var isMedia = mime.indexOf('audio/') === 0 || mime.indexOf('video/') === 0;
  var maxBytes = isMedia ? _maxAudioVideoBytes_() : _maxDriveConvertBytes_();
  var approxBytes = Math.floor((base64Data || '').length * 3 / 4);
  if (approxBytes > maxBytes) {
    throw new Error(
      'ファイルサイズが大きすぎます（約' + Math.round(approxBytes / 1024 / 1024) + 'MB > 上限' +
      Math.round(maxBytes / 1024 / 1024) + 'MB）。' +
      (isMedia
        ? '大きい音声・動画は「🗄 DB管理」タブでDriveフォルダに置いて「今すぐ同期」を使うか、scripts/youtube_transcribe.pyでローカルから文字起こししてください。'
        : 'ファイルを分割するか抜粋して再アップロードしてください。')
    );
  }
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

  // Notion ページをアーカイブ（ゴミ箱へ。Notion側から復元は可能）。
  // 実際にAPIが成功したかどうか（レスポンスコード200）を見て件数をカウントする
  // （以前はtry/catchで例外だけ握りつぶし、失敗しても「成功」扱いで返していた）。
  var notionArchived = 0, notionFailed = [];
  notionIds.forEach(function(pid) {
    try {
      var res = UrlFetchApp.fetch('https://api.notion.com/v1/pages/' + pid, {
        method: 'patch', headers: notionHeaders_(), contentType: 'application/json',
        payload: JSON.stringify({ archived: true }), muteHttpExceptions: true,
      });
      if (res.getResponseCode() === 200) notionArchived++;
      else notionFailed.push(pid);
    } catch(e) { notionFailed.push(pid); }
  });

  // Driveファイルをゴミ箱へ（Drive側から復元は可能）
  var driveDeleted = 0, driveFailed = [];
  driveIds.forEach(function(fid) {
    try { DriveApp.getFileById(fid).setTrashed(true); driveDeleted++; }
    catch(e) { driveFailed.push(fid); }
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
    // 一部でもNotion/Driveの削除に失敗した場合はokをfalseにし、失敗したID一覧を
    // failedTargetsで返す（管理画面側で「一部失敗」を表示できるように）。
    // インデックス行の削除自体は対象ID全件に対して行うため、失敗があってもRAG_Indexからは
    // 検索対象外になる（Notion/Drive側の実体だけが残ってしまう状態）。
    ok: notionFailed.length === 0 && driveFailed.length === 0,
    opId: String(data[rowIdx][0]),
    archivedPages: notionArchived,
    deletedDriveFiles: driveDeleted,
    deletedRows: toDelete.length,
    failedTargets: notionFailed.map(function(id) { return { source: 'notion', id: id }; })
      .concat(driveFailed.map(function(id) { return { source: 'drive', id: id }; })),
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
'.breakdown-legend{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:5px}',
'.breakdown-legend-item{display:flex;align-items:center;gap:4px;font-size:9.5px;color:var(--text-light)}',
'.breakdown-legend-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0}',
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
'.mini-gauge-wrap{display:flex;align-items:center;gap:8px}',
'.mini-gauge{width:34px;height:34px;border-radius:50%;flex-shrink:0;position:relative;',
'  background:conic-gradient(var(--accent) calc(var(--pct,0)*1%), var(--dborder) 0)}',
'.mini-gauge::before{content:"";position:absolute;inset:4px;background:var(--dark2);border-radius:50%}',
'.mini-gauge span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;',
'  font-size:.58rem;font-weight:700;color:#e2e8f0}',
'.mini-gauge.low{background:conic-gradient(var(--warn) calc(var(--pct,0)*1%), var(--dborder) 0)}',
'.mini-gauge.claude{background:conic-gradient(#c084fc calc(var(--pct,0)*1%), var(--dborder) 0)}',
'.mini-gauge.claude.low{background:conic-gradient(var(--warn) calc(var(--pct,0)*1%), var(--dborder) 0)}',
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
'  <div style="font-size:.72rem;color:#64748b;margin-bottom:8px">コードバージョン: <code>' + GAS_CODE_VERSION + '</code>（他のデプロイと突き合わせてデプロイ漏れがないか確認できます）</div>',
'  <div id="admin-flash" class="admin-flash"></div>',
'  <div class="admin-sub-bar">',
'    <button class="admin-sub-btn active" id="asub-keys-btn" onclick="switchAdminSub(\'keys\')">🔑 APIキー管理</button>',
'    <button class="admin-sub-btn" id="asub-kb-btn" onclick="switchAdminSub(\'kb\')">📚 ナレッジ登録</button>',
'    <button class="admin-sub-btn" id="asub-drive-btn" onclick="switchAdminSub(\'drive\')">🗄 DB管理</button>',
'    <button class="admin-sub-btn" id="asub-ratings-btn" onclick="switchAdminSub(\'ratings\')">📊 評価</button>',
'    <button class="admin-sub-btn" id="asub-usage-btn" onclick="switchAdminSub(\'usage\')">💰 使用量</button>',
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
'      <thead><tr><th>キー（先頭8文字）</th><th>名前</th><th>Namespace</th><th>RAGトークン（Gemini）</th><th>Claudeトークン</th><th>参考情報件数</th><th></th></tr></thead>',
'      <tbody id="key-tbody"><tr><td colspan="6" style="color:#64748b;padding:12px">読み込み中...</td></tr></tbody>',
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
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:10px">PDF・Word・Excel・PowerPoint・画像（文字入り）・音声・動画を選ぶと、内容を読み取って覚えます（音声・動画はGeminiで文字起こしします）。この欄は音声・動画は上限15MB、それ以外は25MB程度（メモリ制約のため保守的な既定値。スクリプトプロパティで調整可）。大きいファイルは「🗄 DB管理」タブでDriveフォルダに置いて「今すぐ同期」するか、音声・動画はscripts/youtube_transcribe.pyでローカルから文字起こしする方法をおすすめします。</p>',
'    <input type="file" id="kb-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.png,.jpg,.jpeg,.mp3,.wav,.m4a,.mp4,.mov,.webm" style="color:#94a3b8;font-size:.8rem;margin-bottom:10px;max-width:100%">',
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
'  <!-- サブタブ: DB管理 -->',
'  <div class="admin-sub-panel" id="asub-drive">',
'  <div class="admin-section">',
'    <h3>➕ 新規DB（namespace）を追加</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:12px">従来はGASエディタのスクリプトプロパティ画面でNAMESPACE_CONFIGのJSONを直接編集する必要があったが、ここから追加できる。Notion DBは既存のIDを指定するか、下の「Notionで新規DBを自動作成する」を使えば新規作成もできる（要NOTION_PARENT_PAGE_ID設定・親ページへのIntegration接続）。</p>',
'    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">',
'      <div><label style="font-size:.74rem;color:#94a3b8">namespace（英数字・アンダースコアのみ）</label><input class="admin-input" id="new-ns-key" type="text" placeholder="product_docs"></div>',
'      <div><label style="font-size:.74rem;color:#94a3b8">ラベル</label><input class="admin-input" id="new-ns-label" type="text" placeholder="📦 製品ドキュメント"></div>',
'    </div>',
'    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">',
'      <div><label style="font-size:.74rem;color:#94a3b8">登録先（source）</label>',
'        <select class="admin-input" id="new-ns-source"><option value="notion">Notion</option><option value="drive">Drive単独</option><option value="both">両方</option></select>',
'      </div>',
'      <div style="display:flex;align-items:flex-end;padding-bottom:8px"><label style="font-size:.8rem;color:#e2e8f0"><input type="checkbox" id="new-ns-hybrid"> BM25+RRFハイブリッド検索を有効化</label></div>',
'    </div>',
'    <div style="margin-bottom:10px">',
'      <label style="font-size:.74rem;color:#94a3b8">Notion DB</label><br>',
'      <label style="font-size:.8rem;color:#e2e8f0;margin-right:16px"><input type="radio" name="new-ns-db-mode" value="existing" checked onchange="toggleNewNsDbMode()"> 既存DBのIDを入力</label>',
'      <label style="font-size:.8rem;color:#e2e8f0"><input type="radio" name="new-ns-db-mode" value="auto" onchange="toggleNewNsDbMode()"> Notionで新規DBを自動作成する</label>',
'      <input class="admin-input" id="new-ns-dbid" type="text" placeholder="Notion DB ID（空欄可）" style="margin-top:6px">',
'    </div>',
'    <div style="margin-bottom:14px"><label style="font-size:.74rem;color:#94a3b8">Driveフォルダ ID（任意）</label><input class="admin-input" id="new-ns-folder" type="text" placeholder="空欄可"></div>',
'    <button class="btn-admin btn-primary" onclick="createNamespace()">追加する</button>',
'    <div id="new-ns-status" style="font-size:.78rem;margin-top:10px;color:#94a3b8"></div>',
'  </div>',
'  <div class="admin-section">',
'    <h3>📋 既存DB一覧</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:12px">ラベル・登録先・Notion DB ID・DriveフォルダIDは行ごとに編集して「保存」で反映できる。Driveフォルダは、このGASを実行しているGoogleアカウントと共有しておく必要がある。</p>',
'    <table class="admin-table">',
'      <thead><tr><th>namespace</th><th>ラベル</th><th>source</th><th>Notion DB ID</th><th>DriveフォルダID</th><th>Hybrid</th><th></th></tr></thead>',
'      <tbody id="namespace-tbody"><tr><td colspan="7" style="color:#64748b;padding:12px">「DB管理」タブを開くと読み込まれます</td></tr></tbody>',
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
'  <div class="admin-section">',
'    <h3>🧹 会話ログ（RAG_Memory）の保持期限クリーンアップ</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:12px">スクリプトプロパティ<code>MEMORY_RETENTION_DAYS</code>（日数）を設定している場合のみ、期限切れの会話ログを削除します。未設定の場合はボタンを押しても何も削除されません（既定オフ）。問診等の機微な内容を扱うnamespaceは、<code>NAMESPACE_CONFIG</code>で<code>logMemory:false</code>を指定すればそもそも記録されなくなります。</p>',
'    <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0" onclick="purgeMemoryNow()">今すぐクリーンアップする</button>',
'    <div id="purge-memory-status" style="font-size:.78rem;margin-top:10px;color:#94a3b8"></div>',
'  </div>',
'  </div>',
'  <!-- サブタブ: 評価 -->',
'  <div class="admin-sub-panel" id="asub-ratings">',
'  <div class="admin-section">',
'    <h3>📊 評価（👍/👎）の集計</h3>',
'    <p style="font-size:.78rem;color:#94a3b8;margin-bottom:14px">この集計はMIN_SCORE閾値・HyDE重み等のグローバルなチューニングパラメータには自動反映されません。👎が多いDBがあれば、そのDBのHyDEドメインヒント（<code>hydePromptFor_</code>）や検索閾値（<code>MIN_SCORE</code>）を見直す判断材料にしてください。👍/👎それぞれの平均スコアが近い・👎の方が高いようであれば、MIN_SCOREが低すぎる可能性があります。閾値はスクリプトプロパティ<code>MIN_SCORE_&lt;namespace大文字&gt;</code>（例: <code>MIN_SCORE_BRAINTQ</code>）でnamespaceごとに上書きできます。詳細は「使い方」タブ、またはdocs/cloud-rag.md §7.5を参照。</p>',
'    <div id="ratings-summary" style="display:flex;gap:24px;margin-bottom:16px;font-size:.85rem;color:#e2e8f0">読み込み中...</div>',
'    <h3 style="font-size:.85rem;margin-bottom:8px">👎 が多いDB（要チューニング候補）</h3>',
'    <table class="admin-table">',
'      <thead><tr><th>DB</th><th style="text-align:right">👎件数</th></tr></thead>',
'      <tbody id="ratings-bydb-tbody"><tr><td colspan="2" style="color:#64748b">「評価」タブを開くと読み込まれます</td></tr></tbody>',
'    </table>',
'    <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0;margin-top:12px" onclick="loadRatingStats()">更新</button>',
'  </div>',
'  </div>',
'  <!-- サブタブ: 使用量 -->',
'  <div class="admin-sub-panel" id="asub-usage">',
'  <div class="admin-section">',
'    <h3>💰 RAG（Gemini）トークン使用量</h3>',
'    <p style="font-size:.78rem;color:#94a3b8;margin-bottom:14px">HyDE仮説文書生成・最終回答生成（generateContent）はGemini APIのusageMetadataから実測したトークン数です。埋め込み（embedContent）はレスポンスにusageMetadataが含まれないため実測できず、「埋め込み文字数」は目安（正確なトークン数ではない）として参考表示しています。mode:"raw"（Function Calling経由）は最終回答生成を行わないため、その分のトークンは発生しません。</p>',
'    <table class="admin-table">',
'      <thead><tr><th>APIキー</th><th style="text-align:right">クエリ数</th><th style="text-align:right">raw/full</th><th style="text-align:right">実測トークン合計</th><th style="text-align:right">埋め込み文字数(目安)</th></tr></thead>',
'      <tbody id="usage-tbody"><tr><td colspan="5" style="color:#64748b">「使用量」タブを開くと読み込まれます</td></tr></tbody>',
'    </table>',
'    <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0;margin-top:12px" onclick="loadTokenUsageStats()">更新</button>',
'  </div>',
'  <div class="admin-section">',
'    <h3>🧹 RAG使用量ログの保持期限クリーンアップ</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:12px">スクリプトプロパティ<code>TOKEN_USAGE_RETENTION_DAYS</code>（日数）を設定している場合のみ、期限切れの使用量ログを削除します。未設定の場合はボタンを押しても何も削除されません（既定オフ）。</p>',
'    <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0" onclick="purgeTokenUsageNow()">今すぐクリーンアップする</button>',
'    <div id="purge-usage-status" style="font-size:.78rem;margin-top:10px;color:#94a3b8"></div>',
'  </div>',
'  <div class="admin-section">',
'    <h3>🟣 Claudeトークン使用量（houdini21チュートリアル生成）</h3>',
'    <p style="font-size:.78rem;color:#94a3b8;margin-bottom:14px">Claude APIをこのGAS経由（action:"claude_messages"）で呼んだ実測トークン数です。クライアント（Houdini）は生のANTHROPIC_API_KEYを持たないため、この数値がAPIキーごとの実際のClaude利用量です。</p>',
'    <table class="admin-table">',
'      <thead><tr><th>APIキー</th><th style="text-align:right">呼び出し回数</th><th style="text-align:right">input</th><th style="text-align:right">output</th><th style="text-align:right">cache</th><th style="text-align:right">合計</th></tr></thead>',
'      <tbody id="claude-usage-tbody"><tr><td colspan="6" style="color:#64748b">「使用量」タブを開くと読み込まれます</td></tr></tbody>',
'    </table>',
'    <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0;margin-top:12px" onclick="loadClaudeUsageStats()">更新</button>',
'  </div>',
'  <div class="admin-section">',
'    <h3>🧹 Claude使用量ログの保持期限クリーンアップ</h3>',
'    <p style="font-size:.76rem;color:#64748b;margin-bottom:12px">スクリプトプロパティ<code>CLAUDE_USAGE_RETENTION_DAYS</code>（日数）を設定している場合のみ、期限切れの使用量ログを削除します。未設定の場合はボタンを押しても何も削除されません（既定オフ）。</p>',
'    <button class="btn-admin" style="background:var(--dark3);color:#e2e8f0" onclick="purgeClaudeUsageNow()">今すぐクリーンアップする</button>',
'    <div id="purge-claude-usage-status" style="font-size:.78rem;margin-top:10px;color:#94a3b8"></div>',
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
'    <div style="margin-bottom:16px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">RAG（Gemini）トークン上限（空欄=無制限。変更すると残高は満タンにリセットされます）</label>',
'      <input class="admin-input" id="edit-ns-capacity" type="number" min="0" step="1000" placeholder="例: 100000">',
'      <label style="font-size:.72rem;color:#64748b;display:block;margin:6px 0 4px">自動回復間隔（時間。空欄=自動回復なし・要手動チャージ）</label>',
'      <input class="admin-input" id="edit-ns-reset-hours" type="number" min="0" step="1" placeholder="例: 24">',
'    </div>',
'    <div style="margin-bottom:16px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">Claudeトークン上限（空欄=無制限。変更すると残高は満タンにリセットされます）</label>',
'      <input class="admin-input" id="edit-ns-claude-capacity" type="number" min="0" step="1000" placeholder="例: 100000">',
'      <label style="font-size:.72rem;color:#64748b;display:block;margin:6px 0 4px">自動回復間隔（時間。空欄=自動回復なし・要手動チャージ）</label>',
'      <input class="admin-input" id="edit-ns-claude-reset-hours" type="number" min="0" step="1" placeholder="例: 24">',
'    </div>',
'    <div style="margin-bottom:16px">',
'      <label style="font-size:.75rem;color:#64748b;display:block;margin-bottom:4px">参考情報（引用元）の件数（空欄=既定5件。最大' + MAX_SOURCE_LIMIT + '件）</label>',
'      <input class="admin-input" id="edit-ns-source-limit" type="number" min="1" max="' + MAX_SOURCE_LIMIT + '" step="1" placeholder="例: 5">',
'      <p style="font-size:.68rem;color:#64748b;margin-top:4px">増やすほど1回のクエリで参照する文書が増え、回答生成の入力トークン（コスト）も増えます</p>',
'    </div>',
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
'  var legend = document.createElement("div"); legend.className = "breakdown-legend";',
'  cited.forEach(function(s, i) {',
'    var pct = Math.round(Math.max(s.score, 0.01) / total * 100);',
'    var color = BREAKDOWN_PALETTE_[i % BREAKDOWN_PALETTE_.length];',
'    var seg = document.createElement("div"); seg.className = "breakdown-seg";',
'    seg.style.width = pct + "%";',
'    seg.style.background = color;',
'    seg.title = s.title + "（" + s.db + "）: " + pct + "%";',
'    bar.appendChild(seg);',
'    // 色分けだけだとどれがどれか分からないため、バーの下に色見本付きの凡例を出す',
'    var li = document.createElement("div"); li.className = "breakdown-legend-item";',
'    var dot = document.createElement("span"); dot.className = "breakdown-legend-dot"; dot.style.background = color;',
'    li.appendChild(dot);',
'    li.appendChild(document.createTextNode(s.title + "（" + pct + "%）"));',
'    legend.appendChild(li);',
'  });',
'  wrap.appendChild(label); wrap.appendChild(bar); wrap.appendChild(legend);',
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
'  // s.scoreの生値は検索方式で意味が全く異なる（BM25+RRFハイブリッドはRRF融合スコアで',
'  // 理論上の最大値が約3.3%しかなく、コサイン類似度と単純に同じ0-100%表示をすると',
'  // 常に低い%になり誤解を招く）。そのため表示は「この回答内での最高スコアを100%とした',
'  // 相対値」に統一する。',
'  var maxScore = sources.reduce(function(m, s) { return Math.max(m, s.score); }, 0.0001);',
'  sources.forEach(function(s, i) {',
'    var rel  = s.score / maxScore;',
'    var pct  = (rel * 100).toFixed(1);',
'    var cls  = rel >= 0.75 ? "high" : rel >= 0.5 ? "mid" : "low";',
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
'  ["keys","kb","drive","ratings","usage","guide"].forEach(function(t) {',
'    var panel = document.getElementById("asub-"+t);',
'    var btn   = document.getElementById("asub-"+t+"-btn");',
'    if (panel) panel.classList.toggle("active", t === tab);',
'    if (btn)   btn.classList.toggle("active",   t === tab);',
'  });',
'  if (tab === "kb") kbInitCloud();',
'  if (tab === "drive") driveInit();',
'  if (tab === "ratings") loadRatingStats();',
'  if (tab === "usage") { loadTokenUsageStats(); loadClaudeUsageStats(); }',
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
'        "<div>評価済みの👍率: <strong>" + upPct + "%</strong></div>" +',
'        (s.avgScoreUp   !== null ? "<div style=\\"color:#4ade80\\">👍平均スコア: " + s.avgScoreUp.toFixed(3)   + "</div>" : "") +',
'        (s.avgScoreDown !== null ? "<div style=\\"color:#f87171\\">👎平均スコア: " + s.avgScoreDown.toFixed(3) + "</div>" : "");',
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

'function loadTokenUsageStats() {',
'  var tbody = document.getElementById("usage-tbody");',
'  google.script.run',
'    .withSuccessHandler(function(res) {',
'      var rows = res.rows || [];',
'      if (!rows.length) {',
'        tbody.innerHTML = \'<tr><td colspan="5" style="color:#64748b">記録がまだありません</td></tr>\';',
'        return;',
'      }',
'      tbody.innerHTML = rows.map(function(r) {',
'        return "<tr><td>" + r.displayName + " <span style=\\"color:#64748b;font-size:.72rem\\">(" + r.apiKeyPrefix + "...)</span></td>" +',
'          "<td style=\\"text-align:right\\">" + r.queries + "</td>" +',
'          "<td style=\\"text-align:right;color:#64748b\\">" + r.rawQueries + " / " + r.fullQueries + "</td>" +',
'          "<td style=\\"text-align:right\\"><strong>" + r.totalMeasuredTokens.toLocaleString() + "</strong></td>" +',
'          "<td style=\\"text-align:right;color:#64748b\\">" + r.embedCharsTotal.toLocaleString() + "</td></tr>";',
'      }).join("");',
'    })',
'    .withFailureHandler(function(e) { tbody.innerHTML = \'<tr><td colspan="5" style="color:var(--warn)">読み込み失敗: \' + e.message + "</td></tr>"; })',
'    .adminTokenUsageStats(_apiKey);',
'}',

'function purgeTokenUsageNow() {',
'  var status = document.getElementById("purge-usage-status");',
'  status.textContent = "確認中です…";',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      if (!r.enabled) { status.textContent = "TOKEN_USAGE_RETENTION_DAYSが未設定のため、何も削除していません。"; return; }',
'      status.textContent = "✅ " + r.purged + "件削除しました。";',
'    })',
'    .withFailureHandler(function(e) { status.textContent = "❌ " + e.message; })',
'    .adminPurgeExpiredTokenUsage(_apiKey);',
'}',

'function loadClaudeUsageStats() {',
'  var tbody = document.getElementById("claude-usage-tbody");',
'  google.script.run',
'    .withSuccessHandler(function(res) {',
'      var rows = res.rows || [];',
'      if (!rows.length) {',
'        tbody.innerHTML = \'<tr><td colspan="6" style="color:#64748b">記録がまだありません</td></tr>\';',
'        return;',
'      }',
'      tbody.innerHTML = rows.map(function(r) {',
'        return "<tr><td>" + r.displayName + " <span style=\\"color:#64748b;font-size:.72rem\\">(" + r.apiKeyPrefix + "...)</span></td>" +',
'          "<td style=\\"text-align:right\\">" + r.calls + "</td>" +',
'          "<td style=\\"text-align:right;color:#64748b\\">" + r.inputTokens.toLocaleString() + "</td>" +',
'          "<td style=\\"text-align:right;color:#64748b\\">" + r.outputTokens.toLocaleString() + "</td>" +',
'          "<td style=\\"text-align:right;color:#64748b\\">" + r.cacheTokens.toLocaleString() + "</td>" +',
'          "<td style=\\"text-align:right\\"><strong>" + r.totalMeasuredTokens.toLocaleString() + "</strong></td></tr>";',
'      }).join("");',
'    })',
'    .withFailureHandler(function(e) { tbody.innerHTML = \'<tr><td colspan="6" style="color:var(--warn)">読み込み失敗: \' + e.message + "</td></tr>"; })',
'    .adminClaudeUsageStats(_apiKey);',
'}',

'function purgeClaudeUsageNow() {',
'  var status = document.getElementById("purge-claude-usage-status");',
'  status.textContent = "確認中です…";',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      if (!r.enabled) { status.textContent = "CLAUDE_USAGE_RETENTION_DAYSが未設定のため、何も削除していません。"; return; }',
'      status.textContent = "✅ " + r.purged + "件削除しました。";',
'    })',
'    .withFailureHandler(function(e) { status.textContent = "❌ " + e.message; })',
'    .adminPurgeExpiredClaudeUsage(_apiKey);',
'}',

'// resetAt/resetIntervalHoursから「次回回復」表示テキストを作る。自動回復が設定されていなければ手動チャージが必要な旨を表示。',
'function renderResetInfo_(resetIntervalHours, resetAt) {',
'  if (!resetIntervalHours) return \'<span style="color:#64748b;font-size:.68rem">自動回復なし（手動チャージ）</span>\';',
'  var when = resetAt ? new Date(resetAt).toLocaleString("ja-JP") : "—";',
'  return \'<span style="font-size:.68rem;color:#94a3b8">次回回復: \' + when + \'（\' + resetIntervalHours + \'時間毎）</span>\';',
'}',

'// RAG（Gemini）/ Claude 共通のミニ円ゲージ描画。capacity==nullなら「無制限」表示。',
'function renderQuotaGauge_(balance, capacity, extraCls, resetIntervalHours, resetAt) {',
'  if (capacity == null) return \'<span style="color:#64748b">無制限</span>\';',
'  var pct = capacity > 0 ? Math.round((balance / capacity) * 100) : 0;',
'  var cls = "mini-gauge" + (extraCls ? " " + extraCls : "") + (pct <= 15 ? " low" : "");',
'  return \'<div class="mini-gauge-wrap"><div class="\' + cls + \'" style="--pct:\' + pct + \'"><span>\' + pct + \'%</span></div>\' +',
'    \'<div><span style="font-size:.72rem;color:#94a3b8">\' + Number(balance).toLocaleString() + " / " + Number(capacity).toLocaleString() + \'</span><br>\' +',
'    renderResetInfo_(resetIntervalHours, resetAt) + \'</div></div>\';',
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
'        var ragCap    = renderQuotaGauge_(k.balance, k.capacity, "", k.resetIntervalHours, k.resetAt);',
'        var claudeCap = renderQuotaGauge_(k.claudeBalance, k.claudeCapacity, "claude", k.claudeResetIntervalHours, k.claudeResetAt);',
'        var ragChargeBtn = (k.capacity == null) ? "" :',
'          \'<button class="btn-admin btn-sm" style="background:#334155;color:#e2e8f0" onclick="chargeKeyBalance(\\\'\' + k.keyPreview + \'\\\')">RAGチャージ</button>\';',
'        var claudeChargeBtn = (k.claudeCapacity == null) ? "" :',
'          \'<button class="btn-admin btn-sm" style="background:#334155;color:#e2e8f0" onclick="chargeClaudeBalance(\\\'\' + k.keyPreview + \'\\\')">Claudeチャージ</button>\';',
'        tr.innerHTML =',
'          \'<td style="font-family:monospace">\' + k.keyPreview + \'</td>\' +',
'          \'<td>\' + k.displayName + adm + \'</td>\' +',
'          \'<td style="font-size:.72rem;color:#94a3b8">\' + ns + \'</td>\' +',
'          \'<td style="font-size:.76rem">\' + ragCap + \'</td>\' +',
'          \'<td style="font-size:.76rem">\' + claudeCap + \'</td>\' +',
'          \'<td style="font-size:.76rem;color:#94a3b8;text-align:center">\' + (k.sourceLimit || ' + DEFAULT_SOURCE_LIMIT + ') + \'件\' + (k.sourceLimit ? "" : "（既定）") + \'</td>\' +',
'          \'<td style="display:flex;gap:6px;flex-wrap:wrap">\' +',
'            \'<button class="btn-admin btn-sm" style="background:#334155;color:#e2e8f0" onclick="openEditNs(\\\'\' + k.keyPreview + \'\\\',\' + currentNsJson.replace(/\'/g,"\\\\\'") + \',\' + (k.capacity == null ? "null" : k.capacity) + \',\' + (k.claudeCapacity == null ? "null" : k.claudeCapacity) + \',\' + (k.resetIntervalHours == null ? "null" : k.resetIntervalHours) + \',\' + (k.claudeResetIntervalHours == null ? "null" : k.claudeResetIntervalHours) + \',\' + (k.sourceLimit == null ? "null" : k.sourceLimit) + \')">編集</button>\' +',
'            ragChargeBtn + claudeChargeBtn +',
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
'var _editNsOrigCapacity = null;',
'var _editNsOrigClaudeCapacity = null;',
'var _editNsOrigResetHours = null;',
'var _editNsOrigClaudeResetHours = null;',
'var _editNsOrigSourceLimit = null;',
'function openEditNs(preview, currentNs, currentCapacity, currentClaudeCapacity, currentResetHours, currentClaudeResetHours, currentSourceLimit) {',
'  _editNsPreview = preview;',
'  _editNsOrigCapacity = (currentCapacity === undefined) ? null : currentCapacity;',
'  _editNsOrigClaudeCapacity = (currentClaudeCapacity === undefined) ? null : currentClaudeCapacity;',
'  _editNsOrigResetHours = (currentResetHours === undefined) ? null : currentResetHours;',
'  _editNsOrigClaudeResetHours = (currentClaudeResetHours === undefined) ? null : currentClaudeResetHours;',
'  _editNsOrigSourceLimit = (currentSourceLimit === undefined) ? null : currentSourceLimit;',
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
'  document.getElementById("edit-ns-capacity").value = (currentCapacity == null) ? "" : currentCapacity;',
'  document.getElementById("edit-ns-claude-capacity").value = (currentClaudeCapacity == null) ? "" : currentClaudeCapacity;',
'  document.getElementById("edit-ns-reset-hours").value = (currentResetHours == null) ? "" : currentResetHours;',
'  document.getElementById("edit-ns-claude-reset-hours").value = (currentClaudeResetHours == null) ? "" : currentClaudeResetHours;',
'  document.getElementById("edit-ns-source-limit").value = (currentSourceLimit == null) ? "" : currentSourceLimit;',
'  modal.classList.add("show");',
'}',
'function closeEditNs() {',
'  var modal = document.getElementById("edit-ns-modal");',
'  if (modal) modal.classList.remove("show");',
'  _editNsPreview = null;',
'  _editNsOrigCapacity = null;',
'  _editNsOrigClaudeCapacity = null;',
'  _editNsOrigResetHours = null;',
'  _editNsOrigClaudeResetHours = null;',
'  _editNsOrigSourceLimit = null;',
'}',
'function saveEditNs() {',
'  if (!_editNsPreview) return;',
'  var ns = Array.from(document.querySelectorAll("#edit-ns-checkboxes input:checked")).map(function(i) { return i.value; });',
'  var capRaw = document.getElementById("edit-ns-capacity").value.trim();',
'  var newCapacity = capRaw === "" ? null : Number(capRaw);',
'  var claudeCapRaw = document.getElementById("edit-ns-claude-capacity").value.trim();',
'  var newClaudeCapacity = claudeCapRaw === "" ? null : Number(claudeCapRaw);',
'  var resetHoursRaw = document.getElementById("edit-ns-reset-hours").value.trim();',
'  var newResetHours = resetHoursRaw === "" ? null : Number(resetHoursRaw);',
'  var claudeResetHoursRaw = document.getElementById("edit-ns-claude-reset-hours").value.trim();',
'  var newClaudeResetHours = claudeResetHoursRaw === "" ? null : Number(claudeResetHoursRaw);',
'  var sourceLimitRaw = document.getElementById("edit-ns-source-limit").value.trim();',
'  var newSourceLimit = sourceLimitRaw === "" ? null : Number(sourceLimitRaw);',
'  var preview = _editNsPreview;',
'  var origCapacity = _editNsOrigCapacity;',
'  var origClaudeCapacity = _editNsOrigClaudeCapacity;',
'  var origResetHours = _editNsOrigResetHours;',
'  var origClaudeResetHours = _editNsOrigClaudeResetHours;',
'  var origSourceLimit = _editNsOrigSourceLimit;',
'  function applyCapacityChanges() {',
'    var tasks = [];',
'    if (newCapacity !== origCapacity || newResetHours !== origResetHours) {',
'      tasks.push(new Promise(function(resolve, reject) {',
'        google.script.run',
'          .withSuccessHandler(resolve)',
'          .withFailureHandler(reject)',
'          .adminSetKeyCapacity(_apiKey, preview, newCapacity, newResetHours);',
'      }));',
'    }',
'    if (newClaudeCapacity !== origClaudeCapacity || newClaudeResetHours !== origClaudeResetHours) {',
'      tasks.push(new Promise(function(resolve, reject) {',
'        google.script.run',
'          .withSuccessHandler(resolve)',
'          .withFailureHandler(reject)',
'          .adminSetClaudeCapacity(_apiKey, preview, newClaudeCapacity, newClaudeResetHours);',
'      }));',
'    }',
'    if (newSourceLimit !== origSourceLimit) {',
'      tasks.push(new Promise(function(resolve, reject) {',
'        google.script.run',
'          .withSuccessHandler(resolve)',
'          .withFailureHandler(reject)',
'          .adminSetSourceLimit(_apiKey, preview, newSourceLimit);',
'      }));',
'    }',
'    if (!tasks.length) { adminFlash("namespace を更新しました"); closeEditNs(); loadAdminKeys(); return; }',
'    Promise.all(tasks)',
'      .then(function() { adminFlash("namespace / トークン上限を更新しました"); closeEditNs(); loadAdminKeys(); })',
'      .catch(function(e) { adminFlash((e && e.message) || String(e), true); });',
'  }',
'  google.script.run',
'    .withSuccessHandler(applyCapacityChanges)',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminUpdateKey(_apiKey, preview, ns);',
'}',

'function chargeClaudeBalance(preview) {',
'  var amountRaw = prompt(preview + " にチャージするClaudeトークン数を入力してください（上限は超えません）");',
'  if (amountRaw === null) return;',
'  var amount = Number(amountRaw);',
'  if (!isFinite(amount) || amount <= 0) { adminFlash("正の数値を入力してください", true); return; }',
'  google.script.run',
'    .withSuccessHandler(function() { adminFlash("チャージしました"); loadAdminKeys(); })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminChargeClaudeBalance(_apiKey, preview, amount);',
'}',

'function chargeKeyBalance(preview) {',
'  var amountRaw = prompt(preview + " にチャージするトークン数を入力してください（上限は超えません）");',
'  if (amountRaw === null) return;',
'  var amount = Number(amountRaw);',
'  if (!isFinite(amount) || amount <= 0) { adminFlash("正の数値を入力してください", true); return; }',
'  google.script.run',
'    .withSuccessHandler(function() { adminFlash("チャージしました"); loadAdminKeys(); })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminChargeKeyBalance(_apiKey, preview, amount);',
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
'    // ナレッジ登録タブは管理者専用（#tab-adminの中、isAdminでなければボタン自体が非表示）なので、',
'    // 自分のAPIキーに紐づくnamespaces（チャットで使えるDBの制限）ではなく常に全namespaceを表示する。',
'    // ここを_user.namespacesにしていると、DB管理で新規作成したnamespaceがまだ自分のキーの',
'    // namespaces一覧に追加されていない場合、ナレッジ登録の宛先に出てこない不具合になる。',
'    var nsList = ALL_NAMESPACES;',
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
'  var isMedia = f.type.indexOf("audio/") === 0 || f.type.indexOf("video/") === 0;',
'  var limitMb = isMedia ? 15 : 25;',
'  if (f.size > limitMb * 1024 * 1024) { kbStatus("kb-file-status", "ファイルが大きすぎます（この欄は" + (isMedia ? "音声・動画" : "この形式") + "で上限" + limitMb + "MB程度。大きいファイルはDriveに置いて「🗄 DB管理」タブの「今すぐ同期」を使ってください）", "#f87171"); return; }',
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
'      if (r.ok) {',
'        adminFlash("取り消しました（ページ " + r.archivedPages + " 件・インデックス " + r.deletedRows + " 行）");',
'      } else {',
'        adminFlash("一部失敗しました（成功: ページ" + r.archivedPages + "件/Drive" + r.deletedDriveFiles + "件、失敗: " + r.failedTargets.length + "件。手動確認してください）", true);',
'      }',
'      kbLoadHistory();',
'    })',
'    .withFailureHandler(function(e) { adminFlash(e.message, true); })',
'    .adminKbRollback(_apiKey, opId);',
'}',

'// ── DB管理（namespace / Notion DB / Driveフォルダ） ──',
'function driveInit() {',
'  loadNamespaces();',
'}',

'function toggleNewNsDbMode() {',
'  var mode = document.querySelector(\'input[name="new-ns-db-mode"]:checked\').value;',
'  var input = document.getElementById("new-ns-dbid");',
'  input.disabled = (mode === "auto");',
'  if (mode === "auto") input.value = "";',
'}',

'function createNamespace() {',
'  var ns     = document.getElementById("new-ns-key").value.trim();',
'  var label  = document.getElementById("new-ns-label").value.trim();',
'  var source = document.getElementById("new-ns-source").value;',
'  var hybrid = document.getElementById("new-ns-hybrid").checked;',
'  var dbMode = document.querySelector(\'input[name="new-ns-db-mode"]:checked\').value;',
'  var dbId   = document.getElementById("new-ns-dbid").value.trim();',
'  var folder = document.getElementById("new-ns-folder").value.trim();',
'  var status = document.getElementById("new-ns-status");',
'  status.textContent = "追加中…";',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      status.textContent = "✅ 追加しました: " + r.ns + (r.notionDbId ? "（Notion DB: " + r.notionDbId + "）" : "");',
'      document.getElementById("new-ns-key").value = "";',
'      document.getElementById("new-ns-label").value = "";',
'      document.getElementById("new-ns-dbid").value = "";',
'      document.getElementById("new-ns-folder").value = "";',
'      loadNamespaces();',
'    })',
'    .withFailureHandler(function(e) { status.textContent = "❌ " + e.message; })',
'    .adminCreateNamespace(_apiKey, ns, label, {',
'      source: source, hybridSearch: hybrid,',
'      createNotionDb: (dbMode === "auto"), notionDbId: dbId, driveFolderId: folder,',
'    });',
'}',

'function loadNamespaces() {',
'  var tbody = document.getElementById("namespace-tbody");',
'  google.script.run',
'    .withSuccessHandler(function(list) {',
'      if (!list.length) { tbody.innerHTML = \'<tr><td colspan="7" style="color:#64748b">namespaceがありません</td></tr>\'; return; }',
'      tbody.innerHTML = list.map(function(r) {',
'        function opt(v, text) { return "<option value=\\"" + v + "\\"" + (r.source === v ? " selected" : "") + ">" + text + "</option>"; }',
'        return "<tr>" +',
'          \'<td style="font-family:monospace;font-size:.76rem">\' + r.ns + "</td>" +',
'          \'<td><input class="admin-input" id="ns-label-\' + r.ns + \'" type="text" value="\' + r.label.replace(/"/g, "&quot;") + \'"></td>\' +',
'          \'<td><select class="admin-input" id="ns-source-\' + r.ns + \'">\' + opt("notion", "Notion") + opt("drive", "Drive") + opt("both", "両方") + "</select></td>" +',
'          \'<td><input class="admin-input" id="ns-dbid-\' + r.ns + \'" type="text" placeholder="未設定" value="\' + r.notionDbId + \'"></td>\' +',
'          \'<td><input class="admin-input" id="ns-folder-\' + r.ns + \'" type="text" placeholder="未設定" value="\' + r.driveFolderId + \'"></td>\' +',
'          \'<td style="text-align:center"><input type="checkbox" id="ns-hybrid-\' + r.ns + \'"\' + (r.hybridSearch ? " checked" : "") + "></td>" +',
'          \'<td><button class="btn-admin btn-primary btn-sm" onclick="saveNamespaceRow(\\\'\' + r.ns + \'\\\')">保存</button></td>\' +',
'        "</tr>";',
'      }).join("");',
'    })',
'    .withFailureHandler(function(e) { tbody.innerHTML = \'<tr><td colspan="7" style="color:var(--warn)">読み込み失敗: \' + e.message + "</td></tr>"; })',
'    .adminListNamespaces(_apiKey);',
'}',

'function saveNamespaceRow(ns) {',
'  var label  = document.getElementById("ns-label-" + ns).value.trim();',
'  var source = document.getElementById("ns-source-" + ns).value;',
'  var hybrid = document.getElementById("ns-hybrid-" + ns).checked;',
'  var dbId   = document.getElementById("ns-dbid-" + ns).value.trim();',
'  var folder = document.getElementById("ns-folder-" + ns).value.trim();',
'  adminFlash("保存中…");',
'  google.script.run',
'    .withSuccessHandler(function() {',
'      google.script.run',
'        .withSuccessHandler(function() {',
'          google.script.run',
'            .withSuccessHandler(function() { adminFlash("保存しました: " + label); loadNamespaces(); })',
'            .withFailureHandler(function(e) { adminFlash("Driveフォルダの保存に失敗: " + e.message, true); })',
'            .adminSetDriveFolder(_apiKey, ns, folder);',
'        })',
'        .withFailureHandler(function(e) { adminFlash("Notion DB IDの保存に失敗: " + e.message, true); })',
'        .adminSetNotionDbId(_apiKey, ns, dbId);',
'    })',
'    .withFailureHandler(function(e) { adminFlash("保存に失敗: " + e.message, true); })',
'    .adminUpdateNamespace(_apiKey, ns, { label: label, source: source, hybridSearch: hybrid });',
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

'function purgeMemoryNow() {',
'  var status = document.getElementById("purge-memory-status");',
'  status.textContent = "確認中です…";',
'  google.script.run',
'    .withSuccessHandler(function(r) {',
'      if (!r.enabled) { status.textContent = "MEMORY_RETENTION_DAYSが未設定のため、何も削除していません。"; return; }',
'      status.textContent = "✅ " + r.purged + "件削除しました。";',
'    })',
'    .withFailureHandler(function(e) { status.textContent = "❌ " + e.message; })',
'    .adminPurgeExpiredMemory(_apiKey);',
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
    keyHash:     _hashApiKey_(newKey),
    keyPreview:  newKey.substring(0, 8),
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
