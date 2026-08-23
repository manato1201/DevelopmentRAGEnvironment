/**
 * gas_mcp_demo.js — MCP（Model Context Protocol）連携 / Googleサービス連携デモ・検証用スクリプト
 *
 * 目的:
 *   「GeminiでMCP連携してどこまで操作できるのか」、および「GASからGoogleサービスを
 *   ネイティブに操作する場合はどうか」を実機で確かめるための最小デモ。
 *   本番の gas_cloud_rag.js は一切変更しない、独立したスクリプトファイル
 *   （同じGASプロジェクトに追加してもよいし、検証用の別プロジェクトに貼ってもよい）。
 *   RAG本体（cloudRAG/gas_cloud_rag.js）には組み込まない方針のため、この分離を維持すること。
 *
 * 検証する2系統:
 *
 * 【A. MCP経由】（前半セクション）
 *   ① Google純正MCPサーバー（Calendar） — 実機検証の結果、GCPプロジェクトのAPI個別有効化・
 *      OAuth同意画面の設定・場合によっては組織のガバナンス承認まで必要と判明した
 *      （「Google純正だからすぐ使える」という前提への反証データ）
 *   ② サードパーティの公開MCPサーバー（DeepWiki, 認証不要） — 完全に成功。Google以外の
 *      MCPサーバーもGASから同じ仕組みで操作できることを確認済み
 *   ③ 任意のMCPサーバー（Script Properties で自分の対象を指定） — GitHub/Notion等
 *      OAuth必須のものを試したい場合の拡張枠
 *
 * 【B. ネイティブサービス経由】（後半セクション、§ネイティブGoogleサービスのデモ）
 *   Calendar/Gmail/Mapsは、GASの組み込みAdvanced Services（CalendarApp/MailApp/Maps）で
 *   直接操作すればMCPを経由する必要が無い（GCPプロジェクトのAPI有効化もOAuth同意画面の
 *   追加設定も不要）。Aで踏んだ壁の対比として、同じ3サービスをネイティブ経由で
 *   実装している: Calendar自動登録・Gmail通知・Maps表示（ジオコーディング+静的地図URL）。
 *   本番のRAGパイプライン（ナレッジ登録・監視処理）への組み込みはまだ行わず、
 *   単体で動作確認できるデモ関数として置いている。
 *
 * 実装方針（A. MCP経由について）:
 *   GASの UrlFetchApp は同期APIで、Server-Sent Events を「イベントとして逐次」
 *   受け取ることはできないが、レスポンス本文はストリームが閉じるまで待ってから
 *   まとめて文字列として取得できる。MCPのStreamable HTTPトランスポートは
 *   1回のリクエストに対して「1個のJSONを返して閉じる」実装が主流なので、
 *   text/event-stream 形式で返ってきても data: 行を自前でパースすれば
 *   GASだけでJSON-RPCのやり取りが成立する（本ファイルの mcpParseJsonRpcBody_）。
 *   ただしサーバーがコネクションを張りっぱなしにするタイプだと、GASの
 *   UrlFetchApp/実行時間の上限に達するまでブロックする点は制約として残る。
 *
 * 使い方（Apps Script エディタから）:
 *   1. スクリプトプロパティに GEMINI_API_KEY を設定（gas_cloud_rag.js と共通のキー名）
 *   2. appsscript.json の oauthScopes に以下を追加（A・B両方を試す場合の全量。
 *      実機検証で修正済み: CalendarAppは細分化スコープ（calendar.events等）を認識せず
 *      古典的なフル権限スコープが必要、Session.getActiveUser/getEffectiveUserは
 *      どちらもuserinfo.emailスコープが必須、と判明したための最終形）:
 *        https://www.googleapis.com/auth/script.external_request   … UrlFetchApp（A用）
 *        https://www.googleapis.com/auth/calendar.calendarlist.readonly  … Calendar MCP（A用）
 *        https://www.googleapis.com/auth/calendar.events.freebusy        … Calendar MCP（A用）
 *        https://www.googleapis.com/auth/calendar.events.readonly        … Calendar MCP（A用）
 *        https://www.googleapis.com/auth/calendar               … CalendarApp.createEvent()（B用・書き込み。
 *                                                                    calendar.eventsでは不足、フル権限が必要と実機で確認）
 *        https://www.googleapis.com/auth/script.send_mail        … MailApp.sendEmail()（B用）
 *        https://www.googleapis.com/auth/userinfo.email          … Session.getActiveUser()（B用。
 *                                                                    demoGmailNotify_の送信先未指定時のデフォルト解決に必要）
 *      【任意・別アドレスから送信したい場合のみ追加】
 *        https://mail.google.com/                                … GmailApp.sendEmail({from:alias})（B用。
 *                                                                    送信専用の狭いスコープが無く、Gmail読み書き削除
 *                                                                    を含むフル権限が必要。スクリプトプロパティ
 *                                                                    GMAIL_FROM_ALIAS未設定なら不要＝MailAppのまま）
 *      （Maps ServiceはOAuthスコープ不要・APIキー認証のため上記に含まれない。
 *      一度でもoauthScopesを明示すると自動スコープ推測が完全に無効になるため、
 *      A・B両方試すなら全部載せておくのが安全）
 *   3. 【A】testMcpCalendarOnly() / testMcpDeepWikiOnly() / testMcpMultiServer() を
 *      それぞれ実行し、実行ログで「どのツールが呼ばれ、何が返ってきたか」を確認する
 *   4. 【A】任意のMCPサーバーを試す場合は testMcpCustomServer() 用に
 *      スクリプトプロパティ MCP_CUSTOM_URL（必須）と MCP_CUSTOM_BEARER_TOKEN
 *      （そのサーバーがBearerトークン認証なら設定）を追加する
 *   5. 【B】testNativeCalendarRegister() / testNativeGmailNotify() /
 *      testNativeMonitorAlert() / testNativeMapsShow() をそれぞれ実行して確認する
 *   6. 【B・Maps】Maps表示を試す場合は MAPS_API_KEY スクリプトプロパティが事実上必須。
 *      Google Maps Static APIは2018年以降、課金設定済みのAPIキーが無いと画像を
 *      返さない仕様（キー無しは "For development purposes only" 透かし入り or
 *      エラー画像になる）。Google Cloud Console →「APIとサービス」→「認証情報」で
 *      APIキーを発行し、Maps Static APIの有効化・課金アカウント設定を行った上で
 *      スクリプトプロパティ MAPS_API_KEY に設定する（月200ドル無料枠あり、
 *      個人検証用途なら通常無料枠内）
 *   7. 【Web GUI】doGet() を実装済み。デプロイ→新しいデプロイ→種類「ウェブアプリ」→
 *      実行ユーザー「自分」・アクセス「自分のみ」でデプロイすると、①〜⑨全ての機能を
 *      ブラウザのボタン操作でテストできる（詳細は _uiHtml_ 関数を参照）
 */

// ─── 設定 ────────────────────────────────────────────────────────────────────

var MCP_DEMO_GEMINI_MODEL = 'gemini-3.6-flash';  // gas_cloud_rag.js と同じモデルに揃える

var MCP_DEMO_SERVERS = {
  // ① Google純正: Calendar MCP。認証は ScriptApp.getOAuthToken() のBearerトークンのみ
  //    （developers.google.com/workspace/calendar/api/guides/configure-mcp-server 準拠）
  CALENDAR: {
    label: 'Google Calendar MCP',
    url:   'https://calendarmcp.googleapis.com/mcp/v1',
    auth:  'google_oauth',
  },
  // ② サードパーティ: DeepWiki（GitHubリポジトリのドキュメントQ&A）。認証不要の公開デモサーバー
  DEEPWIKI: {
    label: 'DeepWiki MCP（サードパーティ・認証不要）',
    url:   'https://mcp.deepwiki.com/mcp',
    auth:  'none',
  },
  // ③ 任意のMCPサーバーを試すための拡張枠。スクリプトプロパティで指定する
  CUSTOM: {
    label: 'カスタムMCPサーバー（Script Propertiesで指定）',
    url:   null,  // 実行時に MCP_CUSTOM_URL から読む
    auth:  'custom_bearer',
  },
};

var MCP_DEMO_MAX_TURNS = 6;  // Gemini↔MCPの往復上限（GAS実行時間の暴走防止）

// ─── MCP JSON-RPC クライアント（UrlFetchApp のみで実装） ───────────────────────

/**
 * サーバー種別ごとの追加ヘッダーを組み立てる。
 * google_oauth: このスクリプトの実行者（＝OAuth同意したユーザー）のCalendarアクセス
 *   トークンをそのままBearerとして送る。GASならではの手軽さで、Google純正MCP
 *   サーバーに対しては別途OAuthアプリ登録が要らない。
 */
function mcpAuthHeader_(serverConfig) {
  if (serverConfig.auth === 'google_oauth') {
    return { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() };
  }
  if (serverConfig.auth === 'custom_bearer') {
    var token = PropertiesService.getScriptProperties().getProperty('MCP_CUSTOM_BEARER_TOKEN');
    return token ? { Authorization: 'Bearer ' + token } : {};
  }
  if (serverConfig.auth === 'inline_bearer') {
    // GUI（doGet）からトークンを直接受け取るケース。Script Propertiesを介さない。
    return serverConfig.token ? { Authorization: 'Bearer ' + serverConfig.token } : {};
  }
  return {};  // 'none'
}

/**
 * レスポンス本文をJSON-RPCオブジェクトとしてパースする。
 * Content-Typeが application/json ならそのままJSON.parse。
 * text/event-stream の場合は "data: {...}" 行を抽出してパースする
 * （1リクエストに複数dataイベントが来た場合はJSON-RPCの id が一致するものを優先し、
 * 見つからなければ最後のイベントを採用する）。
 */
function mcpParseJsonRpcBody_(text, contentType, expectedId) {
  var trimmed = (text || '').trim();
  if (!trimmed) return null;  // notifications/initialized の 202 Accepted 等、本文なしは許容
  if (contentType && contentType.indexOf('text/event-stream') !== -1) {
    var candidates = [];
    var lines = trimmed.split('\n');
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (line.indexOf('data:') !== 0) continue;
      var jsonText = line.substring(5).trim();
      if (!jsonText) continue;
      try { candidates.push(JSON.parse(jsonText)); } catch (e) { /* 無視して次の行へ */ }
    }
    if (candidates.length === 0) return null;
    if (expectedId !== undefined) {
      for (var j = 0; j < candidates.length; j++) {
        if (candidates[j].id === expectedId) return candidates[j];
      }
    }
    return candidates[candidates.length - 1];
  }
  return JSON.parse(trimmed);
}

/**
 * JSON-RPCリクエストを1回POSTする低レベル関数。
 * session が渡されていれば Mcp-Session-Id ヘッダーを付与する
 * （MCP仕様: initializeで払い出されたセッションIDは以降の全リクエストに必須）。
 */
function mcpPost_(session, method, params, isNotification) {
  var headers = {
    Accept: 'application/json, text/event-stream',
  };
  var extra = mcpAuthHeader_(session.config);
  for (var k in extra) headers[k] = extra[k];
  if (session.sessionId) headers['Mcp-Session-Id'] = session.sessionId;
  if (session.protocolVersion) headers['MCP-Protocol-Version'] = session.protocolVersion;

  var body = { jsonrpc: '2.0', method: method, params: params || {} };
  if (!isNotification) {
    session.nextId += 1;
    body.id = session.nextId;
  }

  var res = UrlFetchApp.fetch(session.config.url, {
    method: 'post',
    contentType: 'application/json',
    headers: headers,
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  });

  var code = res.getResponseCode();
  var respHeaders = res.getAllHeaders();
  var contentType = respHeaders['Content-Type'] || respHeaders['content-type'] || '';
  var rawText = res.getContentText();

  // HTTPステータスだけで即エラー扱いにしない。一部のMCPゲートウェイ（実測: Google
  // Calendar MCP）は認可レイヤーが403を返す一方で、本文には有効なJSON-RPC結果
  // （tools/listの結果など）が入っているケースが観測された。本文が正しくパース
  // できて result を持っていれば、ステータスコードが4xx/5xxでも警告ログに留めて
  // 処理を続行する。本文がJSONとしてすら読めない場合のみHTTPエラーとして投げる。
  var parsed = null;
  try {
    parsed = mcpParseJsonRpcBody_(rawText, contentType, body.id);
  } catch (e) {
    parsed = null;
  }

  if (parsed && parsed.error) {
    throw new Error('[' + session.config.label + '] MCPエラー(' + method + '): ' + JSON.stringify(parsed.error));
  }
  if (!parsed) {
    if (code >= 400) {
      throw new Error(
        '[' + session.config.label + '] MCP HTTPエラー ' + code + ': ' + rawText.substring(0, 1000)
      );
    }
    return null;  // notifications/initialized の 202 Accepted 等
  }
  if (code >= 400) {
    Logger.log(
      '[' + session.config.label + '] 警告: HTTPステータスは' + code + 'だが本文は正常なJSON-RPC結果を含んでいたため続行します（' + method + '）'
    );
  }

  // セッションIDはinitializeのレスポンスヘッダーで払い出される
  var sid = respHeaders['Mcp-Session-Id'] || respHeaders['mcp-session-id'];
  if (sid && !session.sessionId) session.sessionId = sid;

  return parsed.result;
}

/**
 * 診断用: このスクリプト実行時のOAuthトークンが実際にどのスコープを持っているかを
 * Google のtokeninfoエンドポイントで確認する。Calendar系スコープをappsscript.jsonに
 * 追加したのに403が出る場合、まずこれを実行してscopeフィールドに
 * calendar.events.readonly等が本当に含まれているか確認するとよい
 * （manifestを編集しただけで再認可（ブラウザの同意画面）を通っていないと、
 * 古いスコープのままのトークンが使われ続けることがある）。
 */
function debugOAuthScopes() {
  var token = ScriptApp.getOAuthToken();
  var res = UrlFetchApp.fetch(
    'https://oauth2.googleapis.com/tokeninfo?access_token=' + encodeURIComponent(token),
    { muteHttpExceptions: true }
  );
  Logger.log('tokeninfo (' + res.getResponseCode() + '): ' + res.getContentText());
}

/**
 * initialize → notifications/initialized のハンドシェイクを行い、セッションを開く。
 * protocolVersion はこちらから2025-06-18を提案し、サーバーが返してきた値を
 * 以降のMCP-Protocol-Versionヘッダーに使う（サーバー側が別バージョンで応答する
 * 可能性があるための素直なネゴシエーション追従）。
 */
function mcpOpenSession_(serverConfig) {
  var session = { config: serverConfig, sessionId: null, protocolVersion: null, nextId: 0 };
  var initResult = mcpPost_(session, 'initialize', {
    protocolVersion: '2025-06-18',
    capabilities: {},
    clientInfo: { name: 'houdini-rag-mcp-demo', version: '1.0' },
  }, false);
  session.protocolVersion = (initResult && initResult.protocolVersion) || '2025-06-18';
  try {
    mcpPost_(session, 'notifications/initialized', {}, true);
  } catch (e) {
    Logger.log('[' + serverConfig.label + '] notifications/initialized 失敗（無視して続行）: ' + e.message);
  }
  Logger.log('[' + serverConfig.label + '] セッション確立 (protocolVersion=' + session.protocolVersion + ', sessionId=' + (session.sessionId || 'なし') + ')');
  return session;
}

function mcpListTools_(session) {
  var result = mcpPost_(session, 'tools/list', {}, false);
  var tools = (result && result.tools) || [];
  Logger.log('[' + session.config.label + '] ツール一覧(' + tools.length + '件): ' + tools.map(function (t) { return t.name; }).join(', '));
  return tools;
}

function mcpCallTool_(session, name, args) {
  Logger.log('[' + session.config.label + '] tools/call: ' + name + ' args=' + JSON.stringify(args));
  var result = mcpPost_(session, 'tools/call', { name: name, arguments: args || {} }, false);
  Logger.log('[' + session.config.label + '] → 結果: ' + JSON.stringify(result).substring(0, 400));
  return result;
}

// ─── MCPツールスキーマ → Gemini functionDeclarations 変換 ──────────────────────

// Geminiのfunction calling parametersはOpenAPI 3.0のサブセットのみ受け付ける。
// 実機検証（Google Calendar MCP）で、これらのキーがネストした場所に出てくると
// 「Unknown name "..."」の400で拒否されることを確認した:
//   $defs / definitions（JSON Schema 2020-12のサブスキーマ定義。$refの参照先）
//   $ref（↑への参照。$defsをそのまま消すと壊れるので先に解決してから消す）
//   $schema, $id, additionalProperties, unevaluatedProperties, patternProperties, deprecated
//   readOnly / writeOnly（Calendar MCPのプロパティ注釈で実際に検出。ペアで同種のため両方除去）
//   x- で始まるベンダー拡張キー（例: x-google-enum-descriptions）
var _MCP_SCHEMA_STRIP_KEYS = [
  '$schema', '$id', '$ref', '$defs', 'definitions',
  'additionalProperties', 'unevaluatedProperties', 'patternProperties', 'deprecated',
  'readOnly', 'writeOnly',
];

/**
 * node内の $ref: "#/$defs/Foo" や "#/definitions/Foo" を defs 内の実体で
 * その場に展開する（浅いコピーで置き換え）。循環参照対策として深さ上限を設ける。
 */
function mcpResolveRefs_(node, defs, depth) {
  if (depth > 10 || !node || typeof node !== 'object') return node;
  if (Array.isArray(node)) {
    return node.map(function (item) { return mcpResolveRefs_(item, defs, depth + 1); });
  }
  if (typeof node.$ref === 'string') {
    var m = /^#\/(?:\$defs|definitions)\/(.+)$/.exec(node.$ref);
    if (m && defs && Object.prototype.hasOwnProperty.call(defs, m[1])) {
      // 参照先を再帰的に解決してから展開（参照先が別の参照を持つケースにも対応）
      return mcpResolveRefs_(defs[m[1]], defs, depth + 1);
    }
    return node;  // 解決できない参照はそのまま残す（後段でキーごと削除される）
  }
  var out = {};
  for (var key in node) {
    if (!Object.prototype.hasOwnProperty.call(node, key)) continue;
    out[key] = mcpResolveRefs_(node[key], defs, depth + 1);
  }
  return out;
}

/** _MCP_SCHEMA_STRIP_KEYS と "x-"始まりのキーを再帰的に取り除く。 */
function mcpStripUnsupportedKeys_(node, depth) {
  if (depth > 10 || !node || typeof node !== 'object') return node;
  if (Array.isArray(node)) {
    return node.map(function (item) { return mcpStripUnsupportedKeys_(item, depth + 1); });
  }
  var out = {};
  for (var key in node) {
    if (!Object.prototype.hasOwnProperty.call(node, key)) continue;
    if (_MCP_SCHEMA_STRIP_KEYS.indexOf(key) !== -1) continue;
    if (key.toLowerCase().indexOf('x-') === 0) continue;
    out[key] = mcpStripUnsupportedKeys_(node[key], depth + 1);
  }
  return out;
}

/**
 * MCPのinputSchema（標準JSON Schema）をGemini generateContentの
 * functionDeclarations.parameters が受け付ける形に変換する。
 * ① $ref を $defs/definitions の実体でその場に展開 → ② Geminiが知らない
 * キーワードを再帰的に除去、の2段階。型名（object/string等）は小文字のままでよい。
 */
function mcpSchemaToGeminiParameters_(inputSchema) {
  if (!inputSchema || typeof inputSchema !== 'object') {
    return { type: 'object', properties: {} };
  }
  var raw = JSON.parse(JSON.stringify(inputSchema));  // 破壊しないようdeep copy
  var defs = raw.$defs || raw.definitions || {};
  var resolved = mcpResolveRefs_(raw, defs, 0);
  var cleaned = mcpStripUnsupportedKeys_(resolved, 0);
  if (!cleaned.type) cleaned.type = 'object';
  return cleaned;
}

/**
 * 複数MCPセッション分のツールをまとめてGeminiのtools配列に変換する。
 * 戻り値: { geminiTools: [...], dispatch: { ツール名: session } }
 * ツール名が複数サーバーで重複した場合は最初に登録された方を優先し、ログに警告を出す
 * （現状のCalendar/DeepWikiの組では重複しない）。
 */
function mcpBuildGeminiToolset_(sessionsWithTools) {
  var declarations = [];
  var dispatch = {};
  sessionsWithTools.forEach(function (entry) {
    entry.tools.forEach(function (tool) {
      if (dispatch[tool.name]) {
        Logger.log('[警告] ツール名重複: ' + tool.name + '（' + entry.session.config.label + '側は無視）');
        return;
      }
      dispatch[tool.name] = entry.session;
      declarations.push({
        name: tool.name,
        description: tool.description || '',
        parameters: mcpSchemaToGeminiParameters_(tool.inputSchema),
      });
    });
  });
  return { geminiTools: [{ functionDeclarations: declarations }], dispatch: dispatch };
}

// ─── Gemini呼び出し（generateContent、function calling対応） ───────────────────

function callGeminiWithTools_(apiKey, contents, geminiTools) {
  var url = 'https://generativelanguage.googleapis.com/v1beta/models/' + MCP_DEMO_GEMINI_MODEL + ':generateContent?key=' + apiKey;
  var payload = {
    contents: contents,
    tools: geminiTools,
    generationConfig: { temperature: 0.2 },
  };
  var res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    throw new Error('Gemini APIエラー ' + res.getResponseCode() + ': ' + res.getContentText().substring(0, 500));
  }
  var body = JSON.parse(res.getContentText());
  var candidate = body.candidates && body.candidates[0];
  if (!candidate) throw new Error('Geminiから候補が返りませんでした: ' + JSON.stringify(body).substring(0, 300));
  return candidate.content;  // { role: 'model', parts: [...] }
}

// ─── エージェントループ本体 ───────────────────────────────────────────────────

/**
 * userPrompt に対して、mcpConfigs で指定した全MCPサーバーのツールを
 * Geminiに使わせながら回答させる。各往復の内容はLogger.logで逐次出力するので、
 * 実行後は Apps Script の「実行数」ログで「何が呼ばれ、何が返ったか」を追える。
 *
 * mcpConfigs: MCP_DEMO_SERVERS のエントリの配列（複数渡すとサーバー横断でツール選択させる）
 * 戻り値: 最終的なテキスト回答（上限往復に達した場合はその旨を含む）
 */
function runMcpGeminiAgent_(userPrompt, mcpConfigs) {
  var apiKey = PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
  if (!apiKey) throw new Error('GEMINI_API_KEY が未設定です（スクリプトプロパティに設定してください）。');

  var sessionsWithTools = mcpConfigs.map(function (config) {
    var session = mcpOpenSession_(config);
    var tools = mcpListTools_(session);
    return { session: session, tools: tools };
  });
  var toolset = mcpBuildGeminiToolset_(sessionsWithTools);

  var contents = [{ role: 'user', parts: [{ text: userPrompt }] }];
  Logger.log('=== ユーザー: ' + userPrompt);

  for (var turn = 0; turn < MCP_DEMO_MAX_TURNS; turn++) {
    var modelContent = callGeminiWithTools_(apiKey, contents, toolset.geminiTools);
    contents.push(modelContent);

    var functionCallParts = (modelContent.parts || []).filter(function (p) { return !!p.functionCall; });
    if (functionCallParts.length === 0) {
      var textParts = (modelContent.parts || []).filter(function (p) { return typeof p.text === 'string'; });
      var finalText = textParts.map(function (p) { return p.text; }).join('\n');
      Logger.log('=== 最終回答（' + (turn + 1) + '往復目）:\n' + finalText);
      return finalText;
    }

    // 1ターンで複数functionCallが来た場合も、結果は1つのuserメッセージにまとめて返す
    // （Anthropic系の"tool_resultはまとめて1メッセージで返す"のと同じ考え方。
    // 分割して返すとモデルが並列呼び出しをしなくなる傾向があるため）
    var responseParts = [];
    functionCallParts.forEach(function (part) {
      var call = part.functionCall;
      var session = toolset.dispatch[call.name];
      if (!session) {
        responseParts.push({ functionResponse: { name: call.name, response: { error: '未知のツール: ' + call.name } } });
        return;
      }
      var result;
      try {
        result = mcpCallTool_(session, call.name, call.args || {});
      } catch (e) {
        result = { isError: true, content: [{ type: 'text', text: 'MCP呼び出し失敗: ' + e.message }] };
      }
      responseParts.push({ functionResponse: { name: call.name, response: result || {} } });
    });
    contents.push({ role: 'user', parts: responseParts });
  }

  Logger.log('=== 往復上限(' + MCP_DEMO_MAX_TURNS + ')に到達したため打ち切りました');
  return '(往復上限に達したため未完了。MCP_DEMO_MAX_TURNSを増やすか、プロンプトを絞ってください)';
}

// ─── 実行エントリポイント（Apps Scriptエディタから直接「実行」する） ─────────────

/**
 * ①Google純正MCPの検証: Calendarに聞くだけの単独テスト。
 * 要: appsscript.jsonにCalendar系スコープを追加済みであること。
 */
function testMcpCalendarOnly() {
  var answer = runMcpGeminiAgent_(
    '今後の予定を3件、日時と件名だけ簡潔に教えてください。予定が無ければその旨を教えてください。',
    [MCP_DEMO_SERVERS.CALENDAR]
  );
  Logger.log('### testMcpCalendarOnly 結果 ###\n' + answer);
}

/**
 * ②サードパーティMCPの検証: 認証不要の公開MCPサーバー（DeepWiki）だけを使う単独テスト。
 * OAuth設定なしでそのまま実行できる（Googleのものが「すぐ使える」のに対し、
 * これは「他社のMCPサーバーも同じ仕組みで動くか」を確認するためのケース）。
 */
function testMcpDeepWikiOnly() {
  var answer = runMcpGeminiAgent_(
    'GitHubリポジトリ google-gemini/gemini-cli について、何のためのツールか3行で要約してください。',
    [MCP_DEMO_SERVERS.DEEPWIKI]
  );
  Logger.log('### testMcpDeepWikiOnly 結果 ###\n' + answer);
}

/**
 * ③複数MCPサーバー横断の検証: Google純正とサードパーティを同時に渡し、
 * どちらのツールを使うべきかをGemini自身に判断させる（両方に跨る質問にする）。
 * MCP連携で「どこまでできるか」を最も端的に示すテスト。
 */
function testMcpMultiServer() {
  var answer = runMcpGeminiAgent_(
    'まず私の直近の予定を1件だけ教えてください。次に、GitHubリポジトリ ' +
    'google-gemini/gemini-cli が何のためのツールか1行で教えてください。',
    [MCP_DEMO_SERVERS.CALENDAR, MCP_DEMO_SERVERS.DEEPWIKI]
  );
  Logger.log('### testMcpMultiServer 結果 ###\n' + answer);
}

/**
 * ④任意のMCPサーバーを試すための拡張枠。
 * スクリプトプロパティ MCP_CUSTOM_URL（必須）/ MCP_CUSTOM_BEARER_TOKEN（任意）を
 * 設定してから実行する。例: GitHub MCP（https://api.githubcopilot.com/mcp/、
 * 要Bearerトークン）やNotion MCP等、OAuth必須のサードパーティサーバーを試したい場合はこちら。
 */
function testMcpCustomServer() {
  var customUrl = PropertiesService.getScriptProperties().getProperty('MCP_CUSTOM_URL');
  if (!customUrl) {
    Logger.log('MCP_CUSTOM_URL が未設定です。スクリプトプロパティに試したいMCPサーバーのURLを設定してください。');
    return;
  }
  var config = { label: 'Custom MCP (' + customUrl + ')', url: customUrl, auth: 'custom_bearer' };
  var answer = runMcpGeminiAgent_(
    '利用可能なツールを使って、このサーバーが何を提供しているか簡潔に教えてください。',
    [config]
  );
  Logger.log('### testMcpCustomServer 結果 ###\n' + answer);
}

// ─────────────────────────────────────────────────────────────────────────
// ネイティブGoogleサービスのデモ（MCP不使用）
//
// CalendarApp / MailApp / Maps はGASの組み込みAdvanced Servicesであり、
// 前段のCalendar MCPで踏んだ壁（GCPプロジェクトのAPI個別有効化・OAuth同意画面の
// 追加設定・組織のガバナンス承認）を一切経由しない。GAS標準のOAuth（appsscript.json
// のoauthScopesで宣言したスコープをユーザーが1回認可するだけ）で完結する。
//
// 本番のRAGパイプライン（gas_cloud_rag.jsのadminKbImportQaCsv等）には まだ
// 組み込まない方針のため、ここでは単体動作確認のためのデモ関数として置くだけに留める。
// 実際にナレッジ登録フローへ組み込む場合は、adminKbImportQaCsv系の呼び出し末尾から
// demoCalendarAutoRegister_ 相当の処理を呼ぶ形になる（今回は未接続）。
// ─────────────────────────────────────────────────────────────────────────

/**
 * ナレッジ登録相当のイベントをCalendarに自動登録する（デモ）。
 * 「登録したら必ずカレンダーに追加する」という決定的な処理なので、LLM判断は不要。
 * 要スコープ: https://www.googleapis.com/auth/calendar（フル権限）。
 * 実機検証で判明: CalendarAppは細分化スコープ（calendar.events等）を認識せず、
 * 古典的な calendar または calendar.readonly のみを要求する（Advanced Servicesは
 * 新しい細分化スコープ体系に未対応のものがある）。
 */
function demoCalendarAutoRegister_(title, description, durationMinutes) {
  var cal   = CalendarApp.getDefaultCalendar();
  var start = new Date();
  var end   = new Date(start.getTime() + (durationMinutes || 30) * 60 * 1000);
  var event = cal.createEvent(title, start, end, { description: description || '' });
  Logger.log('[Calendar] イベント作成: id=' + event.getId() + ' title="' + event.getTitle() + '" start=' + event.getStartTime().toISOString());
  return { eventId: event.getId(), title: event.getTitle(), start: event.getStartTime().toISOString(), end: event.getEndTime().toISOString() };
}

/** デモ実行: ナレッジ登録が起きた想定でCalendarへ自動登録する */
function testNativeCalendarRegister() {
  var result = demoCalendarAutoRegister_(
    'ナレッジ登録: houdini21 Q&A CSV 5件',
    'RAGナレッジベースへの一括登録が完了しました（デモ実行）。',
    30
  );
  Logger.log('### testNativeCalendarRegister 結果 ###\n' + JSON.stringify(result));
}

/**
 * 通知メールを送信する（デモ）。
 *
 * 送信元アドレス自体はMailAppでは変更不可（常にスクリプト実行者のアドレス固定。
 * なりすまし防止のためGAS側の仕様上の制約）。変えられるのは表示名（name）のみ。
 *
 * 別アドレスから送りたい場合は GmailApp.sendEmail(..., {from: alias}) を使う。
 * ただし from には GmailApp.getAliases() が返す、自分のGmailで「他のメールアドレスから
 * 送信」設定・認証済みのアドレスしか指定できない（任意の他人のアドレスは不可）。
 * 未設定/未認証のエイリアスを指定した場合はエラーにせず警告ログを出し、
 * MailAppでの通常送信にフォールバックする。
 *
 * 使い方: スクリプトプロパティ GMAIL_FROM_ALIAS に、Gmail設定で認証済みの送信元アドレスを
 * 設定するとGmailApp経由に切り替わる。未設定なら従来通りMailApp（表示名のみ変更）。
 *
 * 要スコープ:
 *   - 常時: https://www.googleapis.com/auth/script.send_mail
 *         + https://www.googleapis.com/auth/userinfo.email
 *           （送信先未指定時にSession.getActiveUser()で自分のメアドを解決するため）
 *   - GMAIL_FROM_ALIAS使用時のみ追加: https://mail.google.com/
 *     （GmailAppはメール送信専用の狭いスコープが無く、読み書き削除を含むフル権限が必要。
 *     「送信元アドレスを変えたい」という目的に対してはかなり広い権限要求になる点に注意。
 *     表示名の変更だけで足りるならこのスコープは不要＝MailAppのままでよい）
 */
function demoGmailNotify_(subject, body, toEmail, fromName, aliasOverride) {
  var recipient    = toEmail || Session.getActiveUser().getEmail();  // 未指定なら実行者自身に送る
  var displayName  = fromName || 'RAGナレッジベース監視Bot';
  var fullSubject  = '[RAG監視デモ] ' + subject;
  // aliasOverride（GUI等から直接渡された場合）を優先し、無ければScript Propertiesを見る
  var aliasEmail   = aliasOverride || PropertiesService.getScriptProperties().getProperty('GMAIL_FROM_ALIAS');

  if (aliasEmail) {
    var aliases = GmailApp.getAliases();
    if (aliases.indexOf(aliasEmail) !== -1) {
      GmailApp.sendEmail(recipient, fullSubject, body, { from: aliasEmail, name: displayName });
      Logger.log('[Gmail] 通知送信(GmailApp/エイリアス): from=' + aliasEmail + ' 表示名="' + displayName + '" to=' + recipient);
      return { to: recipient, subject: subject, from: aliasEmail, displayName: displayName, via: 'GmailApp' };
    }
    Logger.log('[Gmail] 警告: GMAIL_FROM_ALIAS="' + aliasEmail + '" はGmailの「他のメールアドレスから送信」に' +
               '未登録/未認証のため使えません（登録済み: ' + (aliases.join(', ') || 'なし') + '）。MailAppにフォールバックします。');
  }

  MailApp.sendEmail({ to: recipient, subject: fullSubject, body: body, name: displayName });
  Logger.log('[Gmail] 通知送信(MailApp): to=' + recipient + ' 表示名="' + displayName + '"（送信元アドレスは変更不可）');
  return { to: recipient, subject: subject, displayName: displayName, via: 'MailApp' };
}

/** デモ実行: 通知メールを自分自身に送る */
function testNativeGmailNotify() {
  var result = demoGmailNotify_(
    'デモ通知',
    'これは gas_mcp_demo.js の testNativeGmailNotify() から送信されたテストメールです。',
    null
  );
  Logger.log('### testNativeGmailNotify 結果 ###\n' + JSON.stringify(result));
}

/**
 * 監視→アラートの決定的パイプライン（デモ）。閾値判定は普通のコードで行い、
 * 超過時のみメール送信する。「監視して問題があれば通知」の実体はこれで足りるため、
 * ここにLLM/MCPを挟む必要は無い。
 */
function demoMonitorAndAlert_(errorRate, thresholdPercent) {
  thresholdPercent = thresholdPercent || 5;  // 既定: エラー率5%超で通知
  if (errorRate <= thresholdPercent) {
    Logger.log('[監視] エラー率 ' + errorRate + '% は閾値 ' + thresholdPercent + '% 以下のため通知しません');
    return { alerted: false, errorRate: errorRate, threshold: thresholdPercent };
  }
  var result = demoGmailNotify_(
    '異常検知（エラー率 ' + errorRate + '%）',
    'エラー率が閾値（' + thresholdPercent + '%）を超えました。実測: ' + errorRate + '%\n\n（gas_mcp_demo.js の監視デモより）',
    null
  );
  return { alerted: true, errorRate: errorRate, threshold: thresholdPercent, mail: result };
}

/** デモ実行: 閾値超過ケース（通知される）と閾値内ケース（通知されない）の両方を試す */
function testNativeMonitorAlert() {
  var normal   = demoMonitorAndAlert_(2, 5);   // 閾値内 → 通知なし
  var abnormal = demoMonitorAndAlert_(12, 5);  // 閾値超過 → 通知あり
  Logger.log('### testNativeMonitorAlert 結果 ###\n通常時: ' + JSON.stringify(normal) + '\n異常時: ' + JSON.stringify(abnormal));
}

/**
 * 場所情報をジオコーディングし、静的地図のURLを生成する（デモ）。
 *
 * 実機検証で判明: Google Maps Static APIは2018年以降、課金設定済みのAPIキーが
 * 無いと画像を返さない仕様になっている（キー無しリクエストはエラー画像か、
 * 実用にならないレート制限が掛かった「For development purposes only」透かし入り
 * 画像になる）。そのため MAPS_API_KEY スクリプトプロパティの設定は事実上必須。
 * 未設定のままだと mapUrl は生成できても、実際にブラウザで開くと画像が表示されない
 * （<img>タグが壊れて見える）。ここではURLを返す前にサーバー側で実際に画像取得を
 * 検証し、失敗時は原因が分かるエラーメッセージで即座に落とす（ブラウザ側で
 * 壊れた画像を黙って表示させない）。
 *
 * APIキーの取得手順: Google Cloud Console → 「APIとサービス」→「認証情報」→
 * 「認証情報を作成」→「APIキー」。あわせて「Maps Static API」の有効化と、
 * 課金アカウントの設定が必要（月200ドル分の無料枠があり、個人検証用途では
 * 通常無料枠に収まる）。
 *
 * 追加のoauthScopesは不要（Maps ServiceはCalendar/Gmailと違い、OAuthではなく
 * 別体系のAPIキー認証のため）。
 */
function demoMapsShow_(placeName) {
  var apiKey = PropertiesService.getScriptProperties().getProperty('MAPS_API_KEY');
  if (apiKey) Maps.setAuthenticationByApiKey(apiKey);

  var geocoder = Maps.newGeocoder();
  var response = geocoder.geocode(placeName);
  if (response.status !== 'OK' || !response.results.length) {
    throw new Error('ジオコーディングに失敗しました（status=' + response.status + '）: ' + placeName);
  }
  var loc = response.results[0].geometry.location;
  var address = response.results[0].formatted_address;

  var map = Maps.newStaticMap()
    .setSize(640, 480)
    .setCenter(loc.lat, loc.lng)
    .setZoom(15)
    .addMarker(loc.lat, loc.lng);
  var mapUrl = map.getMapUrl();

  // 画像が実際に取得できるかをサーバー側で検証してから返す
  var check = UrlFetchApp.fetch(mapUrl, { muteHttpExceptions: true });
  var contentType = (check.getAllHeaders()['Content-Type'] || check.getAllHeaders()['content-type'] || '');
  if (check.getResponseCode() !== 200 || contentType.indexOf('image/') !== 0) {
    throw new Error(
      '地図画像を取得できませんでした（HTTP ' + check.getResponseCode() + ', Content-Type: ' + contentType + '）。' +
      (apiKey
        ? 'MAPS_API_KEYは設定されていますが、キーが無効か、Maps Static APIが有効化されていない可能性があります。'
        : 'MAPS_API_KEYが未設定です。Google Cloud ConsoleでAPIキーを発行し（Maps Static APIを有効化・課金設定込み）、' +
          'スクリプトプロパティ MAPS_API_KEY に設定してください。')
    );
  }

  Logger.log('[Maps] "' + placeName + '" → ' + address + ' (' + loc.lat + ', ' + loc.lng + ')\n地図URL: ' + mapUrl);
  return { query: placeName, address: address, lat: loc.lat, lng: loc.lng, mapUrl: mapUrl };
}

/** デモ実行: 場所名から座標・住所・地図URLを取得する */
function testNativeMapsShow() {
  var result = demoMapsShow_('東京タワー');
  Logger.log('### testNativeMapsShow 結果 ###\n' + JSON.stringify(result));
}

// ─────────────────────────────────────────────────────────────────────────
// Web GUI（doGet） — 各機能をブラウザのボタン操作でテストできるようにする
//
// デプロイ方法: Apps Scriptエディタ右上「デプロイ」→「新しいデプロイ」→
//   歯車アイコンで種類「ウェブアプリ」を選択 → 実行ユーザー「自分」→
//   アクセスできるユーザー「自分のみ」（推奨。他人と共有する場合のみ「全員」にするが、
//   その場合アクセスした全員の操作がデプロイした自分のGoogleアカウント権限
//   ＝Calendar書き込み・メール送信込みで実行される点に注意）→ デプロイ
// 発行されたURLを開くとこのページが表示される。gas_cloud_rag.js側にも
// 別のdoGetが定義されているため、両者が同じGASプロジェクトに同居すると
// 後から読み込んだ方で上書きされる（このファイルは単独プロジェクトで使う前提）。
// ─────────────────────────────────────────────────────────────────────────

function doGet(e) {
  return HtmlService.createHtmlOutput(_uiHtml_())
    .setTitle('MCP / Google連携 デモGUI')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/**
 * サーバー関数の実行結果とLogger出力をまとめてブラウザに返す共通ラッパー。
 * 各uiXxx関数はこれで包むだけで、実行ログパネル（[Google Calendar MCP]等の
 * タグ付き詳細trace）をGUI側にも表示できる。google.script.run の1呼び出しは
 * それぞれ独立したサーバー実行になるため、Logger.getLog() はその呼び出し内の
 * ログだけを返す（他のボタン操作のログと混ざらない）。
 */
function _uiCapture_(fn) {
  try {
    var result = fn();
    return { ok: true, result: result, log: Logger.getLog() };
  } catch (e) {
    return { ok: false, error: e.message, log: Logger.getLog() };
  }
}

// ── A. MCP経由（GUI用ラッパー） ────────────────────────────────────────────

function uiMcpCalendar(question) {
  return _uiCapture_(function () {
    return runMcpGeminiAgent_(
      question || '今後の予定を3件、日時と件名だけ簡潔に教えてください。予定が無ければその旨を教えてください。',
      [MCP_DEMO_SERVERS.CALENDAR]
    );
  });
}

function uiMcpDeepWiki(question) {
  return _uiCapture_(function () {
    return runMcpGeminiAgent_(
      question || 'GitHubリポジトリ google-gemini/gemini-cli について、何のためのツールか3行で要約してください。',
      [MCP_DEMO_SERVERS.DEEPWIKI]
    );
  });
}

function uiMcpMultiServer(question) {
  return _uiCapture_(function () {
    return runMcpGeminiAgent_(
      question || 'まず私の直近の予定を1件だけ教えてください。次に、GitHubリポジトリ google-gemini/gemini-cli が何のためのツールか1行で教えてください。',
      [MCP_DEMO_SERVERS.CALENDAR, MCP_DEMO_SERVERS.DEEPWIKI]
    );
  });
}

function uiMcpCustomServer(url, bearerToken, question) {
  return _uiCapture_(function () {
    var targetUrl = url || PropertiesService.getScriptProperties().getProperty('MCP_CUSTOM_URL');
    if (!targetUrl) throw new Error('MCPサーバーのURLを入力するか、スクリプトプロパティ MCP_CUSTOM_URL を設定してください。');
    var config = bearerToken
      ? { label: 'Custom MCP (' + targetUrl + ')', url: targetUrl, auth: 'inline_bearer', token: bearerToken }
      : { label: 'Custom MCP (' + targetUrl + ')', url: targetUrl, auth: 'custom_bearer' };
    return runMcpGeminiAgent_(
      question || '利用可能なツールを使って、このサーバーが何を提供しているか簡潔に教えてください。',
      [config]
    );
  });
}

/** OAuthトークンの現在の付与スコープを確認する（診断用） */
function uiDebugOAuthScopes() {
  return _uiCapture_(function () {
    var token = ScriptApp.getOAuthToken();
    var res = UrlFetchApp.fetch(
      'https://oauth2.googleapis.com/tokeninfo?access_token=' + encodeURIComponent(token),
      { muteHttpExceptions: true }
    );
    return JSON.parse(res.getContentText());
  });
}

// ── B. ネイティブサービス経由（GUI用ラッパー） ────────────────────────────────

function uiCalendarRegister(title, description) {
  return _uiCapture_(function () {
    return demoCalendarAutoRegister_(
      title || 'ナレッジ登録: houdini21 Q&A CSV 5件',
      description || 'RAGナレッジベースへの一括登録が完了しました（デモ実行）。',
      30
    );
  });
}

function uiGmailNotify(subject, body, toEmail, fromName, fromAlias) {
  return _uiCapture_(function () {
    return demoGmailNotify_(
      subject || 'デモ通知',
      body || 'これはWeb GUIから送信されたテストメールです。',
      toEmail || null,
      fromName || null,
      fromAlias || null
    );
  });
}

function uiMonitorAlert(errorRate, threshold) {
  return _uiCapture_(function () {
    var rate = (errorRate === '' || errorRate === undefined || errorRate === null) ? 12 : Number(errorRate);
    var th   = (threshold === '' || threshold === undefined || threshold === null) ? 5 : Number(threshold);
    return demoMonitorAndAlert_(rate, th);
  });
}

function uiMapsShow(placeName) {
  return _uiCapture_(function () {
    return demoMapsShow_(placeName || '東京タワー');
  });
}

/** doGetが返すHTML本体（CSS/クライアント側JS込みの単一ページ）。 */
function _uiHtml_() {
  return `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 1.5rem;
    background: #f4f5f7; color: #1b1e27;
    font-family: -apple-system, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
    line-height: 1.6;
  }
  .wrap { max-width: 880px; margin: 0 auto; }
  h1 { font-size: 1.35rem; margin: 0 0 .3rem; }
  .sub { color: #666; font-size: .85rem; margin-bottom: 1.5rem; }
  h2 {
    font-size: 1.05rem; margin: 2rem 0 .8rem;
    border-left: 4px solid #3358d6; padding-left: .6rem;
  }
  .card {
    background: #fff; border: 1px solid #e1e4ec; border-radius: 10px;
    padding: 1rem 1.2rem; margin-bottom: 1rem;
  }
  .card h3 { margin: 0 0 .3rem; font-size: 1rem; }
  .card .desc { color: #666; font-size: .82rem; margin: 0 0 .7rem; }
  .card label { display: block; font-size: .8rem; color: #444; margin: .5rem 0 .2rem; }
  .card input[type=text], .card input[type=number], .card input[type=password], .card textarea {
    width: 100%; padding: .45rem .6rem; border: 1px solid #d7dae2; border-radius: 6px;
    font-size: .88rem; font-family: inherit; resize: vertical;
  }
  .row { display: flex; gap: .6rem; flex-wrap: wrap; }
  .row > div { flex: 1; min-width: 160px; }
  .actions { display: flex; align-items: center; gap: .7rem; margin-top: .8rem; }
  button {
    background: #3358d6; color: #fff; border: none; border-radius: 6px;
    padding: .5rem 1.1rem; font-size: .88rem; cursor: pointer;
  }
  button:disabled { background: #9aa4c4; cursor: default; }
  button:hover:not(:disabled) { background: #2946b5; }
  .status { font-size: .82rem; color: #666; }
  .status.ok  { color: #1f8a4c; }
  .status.err { color: #c23a3a; }
  .status.busy { color: #b8860b; }
  .result { margin-top: .7rem; }
  .answer {
    background: #f8f9fc; border: 1px solid #e1e4ec; border-radius: 8px;
    padding: .7rem .9rem; font-size: .88rem; white-space: pre-wrap;
  }
  pre.json, pre.log {
    background: #171a23; color: #e6e8ee; border-radius: 8px;
    padding: .7rem .9rem; font-size: .78rem; overflow-x: auto; white-space: pre-wrap;
  }
  details { margin-top: .5rem; }
  summary { cursor: pointer; font-size: .8rem; color: #3358d6; }
  .map-img { max-width: 100%; border-radius: 8px; border: 1px solid #e1e4ec; display: block; }
  .caption { font-size: .8rem; color: #555; margin-top: .4rem; }
</style>
</head>
<body>
<div class="wrap">
  <h1>MCP / Google連携 デモGUI</h1>
  <div class="sub">gas_mcp_demo.js — 本番のRAGパイプラインとは独立した検証用ページです。</div>

  <h2>A. MCP経由</h2>

  <div class="card">
    <h3>① Google Calendar MCP</h3>
    <div class="desc">Google純正のCalendar MCPサーバーに接続し、Geminiにツールを使わせて予定を尋ねます。</div>
    <label>質問</label>
    <textarea id="q-mcpCalendar" rows="2">今後の予定を3件、日時と件名だけ簡潔に教えてください。予定が無ければその旨を教えてください。</textarea>
    <div class="actions">
      <button onclick="runTest(this,'uiMcpCalendar',[val('q-mcpCalendar')],'mcpCalendar')">実行</button>
      <span class="status" id="status-mcpCalendar"></span>
    </div>
    <div class="result" id="out-mcpCalendar"></div>
  </div>

  <div class="card">
    <h3>② DeepWiki MCP（サードパーティ・認証不要）</h3>
    <div class="desc">認証不要の公開MCPサーバー。Google以外のMCPサーバーも同じ仕組みで動くかの確認用。</div>
    <label>質問</label>
    <textarea id="q-mcpDeepWiki" rows="2">GitHubリポジトリ google-gemini/gemini-cli について、何のためのツールか3行で要約してください。</textarea>
    <div class="actions">
      <button onclick="runTest(this,'uiMcpDeepWiki',[val('q-mcpDeepWiki')],'mcpDeepWiki')">実行</button>
      <span class="status" id="status-mcpDeepWiki"></span>
    </div>
    <div class="result" id="out-mcpDeepWiki"></div>
  </div>

  <div class="card">
    <h3>③ 複数MCPサーバー横断</h3>
    <div class="desc">Calendar MCPとDeepWiki MCPを同時に渡し、どちらを使うかをGemini自身に判断させます。</div>
    <label>質問</label>
    <textarea id="q-mcpMulti" rows="2">まず私の直近の予定を1件だけ教えてください。次に、GitHubリポジトリ google-gemini/gemini-cli が何のためのツールか1行で教えてください。</textarea>
    <div class="actions">
      <button onclick="runTest(this,'uiMcpMultiServer',[val('q-mcpMulti')],'mcpMulti')">実行</button>
      <span class="status" id="status-mcpMulti"></span>
    </div>
    <div class="result" id="out-mcpMulti"></div>
  </div>

  <div class="card">
    <h3>④ 任意のMCPサーバー</h3>
    <div class="desc">GitHub MCP等、URLとBearerトークンが分かっているサーバーを自由に試せます（未入力ならスクリプトプロパティ MCP_CUSTOM_URL / MCP_CUSTOM_BEARER_TOKEN を使用）。</div>
    <div class="row">
      <div><label>サーバーURL</label><input type="text" id="q-customUrl" placeholder="https://api.githubcopilot.com/mcp/"></div>
      <div><label>Bearerトークン（任意）</label><input type="password" id="q-customToken" placeholder="未入力ならスクリプトプロパティを使用"></div>
    </div>
    <label>質問</label>
    <textarea id="q-customQ" rows="2">利用可能なツールを使って、このサーバーが何を提供しているか簡潔に教えてください。</textarea>
    <div class="actions">
      <button onclick="runTest(this,'uiMcpCustomServer',[val('q-customUrl'),val('q-customToken'),val('q-customQ')],'mcpCustom')">実行</button>
      <span class="status" id="status-mcpCustom"></span>
    </div>
    <div class="result" id="out-mcpCustom"></div>
  </div>

  <div class="card">
    <h3>⑤ OAuthスコープ確認（診断用）</h3>
    <div class="desc">今のOAuthトークンに実際どのスコープが付与されているかを確認します。権限エラーが出た時の切り分けに使ってください。</div>
    <div class="actions">
      <button onclick="runTest(this,'uiDebugOAuthScopes',[],'scopes')">実行</button>
      <span class="status" id="status-scopes"></span>
    </div>
    <div class="result" id="out-scopes"></div>
  </div>

  <h2>B. ネイティブサービス経由（MCP不使用）</h2>

  <div class="card">
    <h3>⑥ Calendar自動登録</h3>
    <div class="desc">CalendarApp.createEvent() で直接イベントを作成します（30分の予定として登録）。</div>
    <div class="row">
      <div><label>タイトル</label><input type="text" id="q-calTitle" value="ナレッジ登録: houdini21 Q&amp;A CSV 5件"></div>
    </div>
    <label>説明</label>
    <textarea id="q-calDesc" rows="2">RAGナレッジベースへの一括登録が完了しました（デモ実行）。</textarea>
    <div class="actions">
      <button onclick="runTest(this,'uiCalendarRegister',[val('q-calTitle'),val('q-calDesc')],'calRegister')">実行</button>
      <span class="status" id="status-calRegister"></span>
    </div>
    <div class="result" id="out-calRegister"></div>
  </div>

  <div class="card">
    <h3>⑦ Gmail通知</h3>
    <div class="desc">MailApp（既定）またはGmailApp（送信元エイリアス指定時）で通知メールを送信します。</div>
    <div class="row">
      <div><label>宛先（空欄で自分自身）</label><input type="text" id="q-mailTo" placeholder="未入力なら実行者自身"></div>
      <div><label>差出人表示名</label><input type="text" id="q-mailName" placeholder="RAGナレッジベース監視Bot"></div>
    </div>
    <label>件名</label>
    <input type="text" id="q-mailSubject" value="デモ通知">
    <label>本文</label>
    <textarea id="q-mailBody" rows="2">これはWeb GUIから送信されたテストメールです。</textarea>
    <label>送信元エイリアス（任意・要Gmail側で認証済み）</label>
    <input type="text" id="q-mailAlias" placeholder="未入力ならスクリプトプロパティ GMAIL_FROM_ALIAS を使用">
    <div class="actions">
      <button onclick="runTest(this,'uiGmailNotify',[val('q-mailTo'),val('q-mailSubject'),val('q-mailBody'),val('q-mailName'),val('q-mailAlias')],'mailNotify')">実行</button>
      <span class="status" id="status-mailNotify"></span>
    </div>
    <div class="result" id="out-mailNotify"></div>
  </div>

  <div class="card">
    <h3>⑧ 監視 → アラート（決定的パイプライン）</h3>
    <div class="desc">閾値判定は普通のコードで行い、超過時だけメール送信します（LLM/MCP不使用）。</div>
    <div class="row">
      <div><label>エラー率（%）</label><input type="number" id="q-monRate" value="12"></div>
      <div><label>閾値（%）</label><input type="number" id="q-monTh" value="5"></div>
    </div>
    <div class="actions">
      <button onclick="runTest(this,'uiMonitorAlert',[val('q-monRate'),val('q-monTh')],'monitor')">実行</button>
      <span class="status" id="status-monitor"></span>
    </div>
    <div class="result" id="out-monitor"></div>
  </div>

  <div class="card">
    <h3>⑨ Maps表示</h3>
    <div class="desc">場所名をジオコーディングし、静的地図を画像としてこの場で表示します。</div>
    <label>場所名</label>
    <input type="text" id="q-mapsPlace" value="東京タワー">
    <div class="actions">
      <button onclick="runTest(this,'uiMapsShow',[val('q-mapsPlace')],'maps',{map:true})">実行</button>
      <span class="status" id="status-maps"></span>
    </div>
    <div class="result" id="out-maps"></div>
  </div>

</div>
<script>
  function val(id) { return document.getElementById(id).value; }

  function setStatus(outId, text, cls) {
    var el = document.getElementById('status-' + outId);
    el.textContent = text;
    el.className = 'status ' + (cls || '');
  }

  function runTest(btnEl, fnName, args, outId, opts) {
    btnEl.disabled = true;
    setStatus(outId, '実行中…', 'busy');
    var out = document.getElementById('out-' + outId);
    out.innerHTML = '';
    google.script.run
      .withSuccessHandler(function (resp) {
        btnEl.disabled = false;
        renderResult(outId, resp, opts);
      })
      .withFailureHandler(function (err) {
        btnEl.disabled = false;
        setStatus(outId, '❌ サーバーエラー', 'err');
        out.textContent = err && err.message ? err.message : String(err);
      })[fnName].apply(null, args);
  }

  function renderResult(outId, resp, opts) {
    var out = document.getElementById('out-' + outId);
    out.innerHTML = '';
    setStatus(outId, resp.ok ? '✅ 成功' : ('❌ 失敗: ' + resp.error), resp.ok ? 'ok' : 'err');

    if (resp.ok && opts && opts.map && resp.result && resp.result.mapUrl) {
      var img = document.createElement('img');
      img.className = 'map-img';
      img.src = resp.result.mapUrl;
      out.appendChild(img);
      var cap = document.createElement('div');
      cap.className = 'caption';
      cap.textContent = resp.result.address + '（' + resp.result.lat + ', ' + resp.result.lng + '）';
      out.appendChild(cap);
    } else if (resp.ok && typeof resp.result === 'string') {
      var p = document.createElement('div');
      p.className = 'answer';
      p.textContent = resp.result;
      out.appendChild(p);
    } else if (resp.ok) {
      var pre = document.createElement('pre');
      pre.className = 'json';
      pre.textContent = JSON.stringify(resp.result, null, 2);
      out.appendChild(pre);
    }

    var details = document.createElement('details');
    var summary = document.createElement('summary');
    summary.textContent = '詳細ログ';
    details.appendChild(summary);
    var logPre = document.createElement('pre');
    logPre.className = 'log';
    logPre.textContent = resp.log || '(ログなし)';
    details.appendChild(logPre);
    out.appendChild(details);
  }
</script>
</body>
</html>`;
}
