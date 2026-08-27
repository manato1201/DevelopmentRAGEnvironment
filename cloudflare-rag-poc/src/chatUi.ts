// Webチャット画面（既存GAS getChatHtml_相当）。GASは1,700行超のHTMLを内蔵し、
// チャット/グラフ/履歴/管理の4タブ構成だった。このPOCも同じ4タブ構成に揃える
// （2026-08-25、実際のGAS版UIとのスクリーンショット比較を受けて全面刷新）。
export function chatUiHtml(): string {
  return /* html */ `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RAG Chat (Cloudflare POC)</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<style>
  :root {
    color-scheme: light dark;
    --bg: #0f1117; --panel: #171a23; --border: #2a2e3a;
    --text: #e6e8ee; --muted: #9aa1b4; --accent: #7aa2ff;
    --user-bubble: #26314d; --assistant-bubble: #171a23;
    --good: #6fd08c; --bad: #ef7a7a;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f7f8fb; --panel: #ffffff; --border: #e1e4ec;
      --text: #1b1e27; --muted: #5b6270; --accent: #3358d6;
      --user-bubble: #e7edff; --assistant-bubble: #ffffff;
      --good: #1f8a4c; --bad: #c23a3a;
    }
  }
  * { box-sizing: border-box; }
  html, body { overflow-x: hidden; max-width: 100%; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
    display: flex; flex-direction: column; height: 100vh;
  }
  header { border-bottom: 1px solid var(--border); padding: .6rem 1.2rem; }
  .header-row { display: flex; align-items: center; gap: .8rem; flex-wrap: wrap; margin-bottom: .5rem; }
  header h1 { font-size: 1rem; margin: 0; white-space: nowrap; }
  header input[type="password"], header select, header input[type="text"], header input[type="number"] {
    background: var(--panel); border: 1px solid var(--border); color: var(--text);
    border-radius: 8px; padding: .4rem .6rem; font-size: .85rem;
  }
  header input[type="password"] { flex: 1; min-width: 160px; }
  header button, .btn {
    background: var(--panel); border: 1px solid var(--border); color: var(--text);
    border-radius: 8px; padding: .4rem .8rem; font-size: .85rem; cursor: pointer;
  }
  header button:hover, .btn:hover { border-color: var(--accent); }
  .btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  .btn.danger { color: var(--bad); border-color: var(--bad); }
  nav.tabs { display: flex; gap: .3rem; }
  nav.tabs button {
    background: none; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    color: var(--muted); padding: .5rem .9rem; font-size: .88rem; cursor: pointer;
  }
  nav.tabs button.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }

  .tabpanel { display: none; flex: 1; min-height: 0; flex-direction: column; }
  .tabpanel.active { display: flex; }

  #messages { flex: 1; overflow-y: auto; padding: 1.2rem; max-width: 860px; margin: 0 auto; width: 100%; }
  .msg { margin-bottom: 1.1rem; max-width: 90%; }
  .msg.user { margin-left: auto; }
  .msg .bubble { padding: .7rem 1rem; border-radius: 12px; font-size: .92rem; line-height: 1.6; white-space: pre-wrap; }
  .msg.user .bubble { background: var(--user-bubble); }
  .msg.assistant .bubble { background: var(--assistant-bubble); border: 1px solid var(--border); }
  .meta { display: flex; align-items: center; gap: .6rem; margin-top: .4rem; font-size: .78rem; color: var(--muted); flex-wrap: wrap; }
  .extraction { padding: .1rem .5rem; border-radius: 999px; border: 1px solid var(--border); }
  .extraction.low { color: var(--bad); border-color: var(--bad); }
  .extraction.high { color: var(--good); border-color: var(--good); }
  .rate-btn { background: none; border: 1px solid var(--border); border-radius: 6px; cursor: pointer; color: var(--muted); padding: .1rem .4rem; }
  .rate-btn.active-up { color: var(--good); border-color: var(--good); }
  .rate-btn.active-down { color: var(--bad); border-color: var(--bad); }
  details.sources { margin-top: .5rem; font-size: .8rem; color: var(--muted); }
  details.sources summary { cursor: pointer; }
  details.sources ul { margin: .4rem 0 0; padding-left: 1.2rem; }
  details.sources li { margin-bottom: .3rem; }
  .source-composition { margin: .5rem 0; }
  .composition-title { font-size: .72rem; color: var(--muted); margin-bottom: .25rem; }
  .composition-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--border); }
  .composition-bar span { height: 100%; }
  .composition-legend { display: flex; flex-wrap: wrap; gap: .5rem .8rem; margin-top: .35rem; font-size: .72rem; }
  .composition-legend .item { display: inline-flex; align-items: center; gap: .3rem; }
  .composition-legend .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .ns-pill { display: inline-block; padding: 0 .4rem; border-radius: 999px; font-size: .7rem; color: #1b1e27; }
  .score-pct { font-size: .72rem; color: var(--muted); }
  .cited-badge { font-size: .7rem; padding: 0 .4rem; border-radius: 999px; border: 1px solid var(--border); }
  .cited-badge.cited { color: var(--good); border-color: var(--good); }
  .cited-badge.uncited { color: var(--muted); }
  #composer {
    border-top: 1px solid var(--border); padding: .8rem 1.2rem;
    display: flex; gap: .6rem; max-width: 860px; margin: 0 auto; width: 100%;
  }
  #composer textarea {
    flex: 1; resize: none; background: var(--panel); border: 1px solid var(--border); color: var(--text);
    border-radius: 10px; padding: .6rem .8rem; font-size: .92rem; font-family: inherit; min-height: 2.6rem; max-height: 8rem;
  }
  #composer button { background: var(--accent); border: none; color: #fff; border-radius: 10px; padding: 0 1.2rem; font-size: .9rem; cursor: pointer; }
  #composer button:disabled { opacity: .5; cursor: default; }
  #status { text-align: center; color: var(--muted); font-size: .8rem; padding: .3rem; }
  .error { color: var(--bad); }

  .pane-scroll { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 1.2rem; max-width: 960px; margin: 0 auto; width: 100%; }
  .section { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 1rem 1.2rem; margin-bottom: 1.2rem; max-width: 100%; }
  .section h2 { font-size: .95rem; margin: 0 0 .8rem; }
  .field-row { display: flex; gap: .6rem; flex-wrap: wrap; margin-bottom: .6rem; align-items: center; }
  .field-row label { font-size: .8rem; color: var(--muted); min-width: 110px; }
  .field-row input[type="text"], .field-row input[type="number"] {
    flex: 1; min-width: 160px; background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: .4rem .6rem; font-size: .85rem;
  }
  .checks { display: flex; gap: .5rem; flex-wrap: wrap; }
  .checks label { display: flex; align-items: center; gap: .3rem; font-size: .8rem; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: .25rem .5rem; }
  .table-scroll { overflow-x: auto; max-width: 100%; }
  table.admin-table { width: 100%; border-collapse: collapse; font-size: .82rem; table-layout: fixed; }
  table.admin-table th, table.admin-table td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--border); word-break: break-all; }
  table.admin-table th { color: var(--muted); font-weight: 600; }
  .keybox { background: var(--bg); border: 1px solid var(--good); border-radius: 8px; padding: .6rem .8rem; font-family: monospace; font-size: .85rem; word-break: break-all; margin-top: .5rem; }
  .keybox-row { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin-top: .35rem; }
  .keybox-row code { word-break: break-all; }
  .hint { color: var(--muted); font-size: .78rem; margin: .3rem 0 0; }

  #graphContainer { flex: 1; position: relative; overflow: hidden; background: var(--bg); }
  #graphContainer canvas { display: block; }
  .graph-toolbar { display: flex; gap: .6rem; align-items: center; padding: .6rem 1.2rem; border-bottom: 1px solid var(--border); font-size: .82rem; color: var(--muted); }
  #graphDetail {
    position: absolute; top: .8rem; right: .8rem; width: 260px; max-height: calc(100% - 1.6rem);
    overflow-y: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: .8rem 1rem; font-size: .8rem; display: none; box-shadow: 0 4px 16px rgba(0,0,0,.25);
  }
  #graphDetail.visible { display: block; }
  #graphDetail h3 { font-size: .88rem; margin: 0 0 .4rem; word-break: break-word; }
  #graphDetail .ns { color: var(--muted); margin-bottom: .5rem; }
  #graphDetail ul { margin: .3rem 0 0; padding-left: 1.1rem; }
  #graphDetail li { margin-bottom: .2rem; word-break: break-word; }
  #graphDetail .close-btn { position: absolute; top: .5rem; right: .6rem; background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1rem; }

  #graphControls {
    position: absolute; top: .8rem; left: .8rem; width: 220px; max-height: calc(100% - 1.6rem);
    overflow-y: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: .8rem 1rem; font-size: .78rem; box-shadow: 0 4px 16px rgba(0,0,0,.25);
  }
  #graphControls h4 { font-size: .8rem; margin: 0 0 .4rem; color: var(--muted); }
  #graphControls .slider-row { margin-bottom: .8rem; }
  #graphControls .slider-row label { display: flex; justify-content: space-between; color: var(--muted); margin-bottom: .2rem; }
  #graphControls input[type="range"] { width: 100%; }
  #graphPlayPause { width: 100%; margin-bottom: .8rem; }
  #graphLegend { list-style: none; margin: 0; padding: 0; }
  #graphLegend li { display: flex; align-items: center; gap: .4rem; padding: .2rem 0; cursor: pointer; }
  #graphLegend .swatch { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  #graphLegend .ns-label { flex: 1; word-break: break-all; }
  #graphLegend .ns-count { color: var(--muted); }

  .usage-chart-wrap { overflow-x: auto; }
  #usageChart { display: block; }
  .donut-cell { display: flex; align-items: center; gap: .5rem; }
</style>
</head>
<body>

<header>
  <div class="header-row">
    <h1>RAG Chat（Cloudflare POC）</h1>
    <input type="password" id="apiKey" placeholder="APIキー（Bearer トークン）" autocomplete="off">
    <select id="namespaceFocus" title="検索対象を個別DBに絞り込む（精度向上）">
      <option value="">🌐 全DB横断検索</option>
    </select>
    <select id="level">
      <option value="">レベル: すべて</option>
      <option value="basic">basic</option>
      <option value="applied">applied</option>
      <option value="advanced">advanced</option>
    </select>
  </div>
  <nav class="tabs">
    <button data-tab="chat" class="active">チャット</button>
    <button data-tab="graph">グラフ</button>
    <button data-tab="history">履歴</button>
    <button data-tab="admin">管理</button>
  </nav>
</header>

<!-- チャットタブ -->
<div class="tabpanel active" id="tab-chat">
  <div id="messages"></div>
  <div id="status"></div>
  <div id="composer">
    <textarea id="input" placeholder="質問を入力（Enterで送信、Shift+Enterで改行）" rows="1"></textarea>
    <button id="send">送信</button>
  </div>
</div>

<!-- グラフタブ -->
<div class="tabpanel" id="tab-graph">
  <div class="graph-toolbar">
    <button class="btn" id="graphRefresh">更新</button>
    <span id="graphStats">-</span>
    <span class="hint">ドラッグで回転・スクロールでズーム・ノードクリックで詳細表示</span>
  </div>
  <div id="graphContainer">
    <div id="graphControls">
      <button class="btn" id="graphPlayPause">⏸ 停止</button>
      <div class="slider-row">
        <label><span>反発力</span><span id="graphRepelVal">4000</span></label>
        <input type="range" id="graphRepel" min="500" max="12000" step="100" value="4000">
      </div>
      <div class="slider-row">
        <label><span>結集力</span><span id="graphCenterVal">0.0020</span></label>
        <input type="range" id="graphCenter" min="0" max="100" step="1" value="20">
      </div>
      <h4>DBごとの表示切替</h4>
      <ul id="graphLegend"></ul>
    </div>
    <div id="graphDetail">
      <button class="close-btn" id="graphDetailClose">×</button>
      <h3 id="graphDetailTitle"></h3>
      <div class="ns" id="graphDetailNs"></div>
      <div id="graphDetailType"></div>
      <div id="graphDetailSize"></div>
      <div id="graphDetailDate"></div>
      <div id="graphDetailDegree"></div>
      <ul id="graphDetailNeighbors"></ul>
    </div>
  </div>
</div>

<!-- 履歴タブ -->
<div class="tabpanel" id="tab-history">
  <div class="pane-scroll" id="historyPane">
    <p class="hint">このタブを開くと自動的に読み込まれます。</p>
  </div>
</div>

<!-- 管理タブ -->
<div class="tabpanel" id="tab-admin">
  <div class="pane-scroll">
    <div class="section">
      <h2>設定バックアップ</h2>
      <p class="hint">APIキー・namespace・KB同期元設定・トークン予算のスナップショットをJSONでダウンロードします（チャット履歴本文やベクトルデータは含みません。実データはD1の自動バックアップに任せています）。</p>
      <button class="btn" id="backupExportBtn">エクスポート</button>
      <div id="backupExportResult" class="hint"></div>
    </div>

    <div class="section">
      <h2>ヘルスチェック・アラート通知</h2>
      <p class="hint">Slack（Incoming Webhook）・Gmail（サービスアカウント経由）はいずれもシークレット設定が必要です（README参照）。未設定のチャンネルは「未設定」と表示されます。</p>
      <button class="btn" id="healthCheckBtn">ヘルスチェックを実行</button>
      <button class="btn" id="testAlertBtn">テスト通知を送信</button>
      <div id="healthCheckResult" class="hint"></div>
    </div>

    <div class="section">
      <h2>利用状況（トークン使用量）</h2>
      <div class="field-row">
        <label>期間</label>
        <select id="usageDays">
          <option value="7">直近7日間</option>
          <option value="14" selected>直近14日間</option>
          <option value="30">直近30日間</option>
        </select>
        <button class="btn" id="refreshUsage">再読み込み</button>
      </div>
      <div class="usage-chart-wrap"><canvas id="usageChart" width="900" height="220"></canvas></div>
      <div class="table-scroll"><table class="admin-table" id="usageByUserTable"><thead><tr><th>ユーザー</th><th>クエリ数</th><th>消費トークン</th></tr></thead><tbody></tbody></table></div>
    </div>

    <div class="section">
      <h2>評価統計</h2>
      <button class="btn" id="refreshRatingStats">再読み込み</button>
      <p id="ratingSummary" class="hint">-</p>
      <div class="table-scroll"><table class="admin-table" id="ratingByUserTable"><thead><tr><th>ユーザー</th><th>件数</th><th>役に立った</th><th>役に立たなかった</th></tr></thead><tbody></tbody></table></div>
    </div>

    <div class="section">
      <h2>新しいAPIキーを発行</h2>
      <div class="field-row"><label>名前</label><input type="text" id="newKeyName" placeholder="例: Unity Client, Alice"></div>
      <div class="field-row"><label>権限</label><label><input type="checkbox" id="newKeyAdmin"> 管理者権限</label></div>
      <div class="field-row"><label>RAGトークン上限</label><input type="number" id="newKeyCapacity" value="100000"></div>
      <div class="field-row"><label>アクセス可能namespace</label><div class="checks" id="newKeyNamespaces"></div></div>
      <button class="btn primary" id="createKeyBtn">APIキーを発行</button>
      <div id="newKeyResult"></div>
    </div>

    <div class="section">
      <h2>発行済みキー一覧</h2>
      <button class="btn" id="refreshKeys">再読み込み</button>
      <div class="table-scroll"><table class="admin-table" id="keysTable"><thead><tr><th>名前</th><th>ロール</th><th>RAG予算</th><th>使用率</th><th>作成日</th><th></th></tr></thead><tbody></tbody></table></div>
    </div>

    <div class="section">
      <h2>namespace管理</h2>
      <div class="field-row"><label>namespace ID</label><input type="text" id="newNsId" placeholder="例: shared:new_topic"></div>
      <div class="field-row"><label>scope</label><select id="newNsScope"><option value="shared">shared</option><option value="personal">personal</option></select></div>
      <button class="btn primary" id="createNsBtn">作成</button>
      <button class="btn" id="refreshNs" style="margin-left:.5rem;">再読み込み</button>
      <p class="hint">参考資料数上限：この件数を超える分は検索結果から間引かれます（空欄=上限なし）。複数DBを横断検索した際、無関係なDBのチャンクが結果を圧迫するのを防ぐのに使えます。</p>
      <div class="table-scroll"><table class="admin-table" id="nsTable"><thead><tr><th>namespace</th><th>scope</th><th>owner</th><th>参考資料数上限</th><th></th></tr></thead><tbody></tbody></table></div>
    </div>

    <div class="section">
      <h2>知識ベース同期</h2>
      <div class="field-row"><label>namespace</label><input type="text" id="kbNamespace" placeholder="例: shared:houdini21"></div>
      <div class="field-row"><label>Notion DB ID</label><input type="text" id="kbNotionId" placeholder="任意"></div>
      <div class="field-row"><label>Drive フォルダID</label><input type="text" id="kbDriveId" placeholder="任意"></div>
      <button class="btn" id="kbSetSourceBtn">同期元を設定</button>
      <div style="margin-top:.8rem;">
        <button class="btn primary" id="kbSyncNotionBtn">Notion同期を実行</button>
        <button class="btn primary" id="kbSyncDriveBtn">Drive同期を実行</button>
      </div>
      <div id="kbSyncProgress" class="hint"></div>
    </div>

    <div class="section">
      <h2>URLを手動登録</h2>
      <div class="field-row"><label>namespace</label><input type="text" id="urlImportNamespace" placeholder="例: shared:tool_docs"></div>
      <div class="field-row"><label>URL</label><input type="text" id="urlImportUrl" placeholder="https://..."></div>
      <div class="field-row"><label>タイトル（任意）</label><input type="text" id="urlImportTitle" placeholder="省略時はURLをそのまま使用"></div>
      <button class="btn primary" id="urlImportBtn">登録</button>
      <div id="urlImportResult" class="hint"></div>
    </div>

    <div class="section">
      <h2>YouTube動画を文字起こし登録</h2>
      <div class="field-row"><label>namespace</label><input type="text" id="ytImportNamespace" placeholder="例: shared:tool_docs"></div>
      <div class="field-row"><label>YouTube URL</label><input type="text" id="ytImportUrl" placeholder="https://www.youtube.com/watch?v=..."></div>
      <div class="field-row"><label>タイトル（任意）</label><input type="text" id="ytImportTitle" placeholder="省略時はURLをそのまま使用"></div>
      <button class="btn primary" id="ytImportBtn">文字起こし・登録</button>
      <div id="ytImportResult" class="hint"></div>
    </div>

    <div class="section">
      <h2>ファイルをアップロードして登録</h2>
      <p class="hint">対応形式: PDF・Word（.docx）・PowerPoint（.pptx）・音声・動画</p>
      <div class="field-row"><label>namespace</label><input type="text" id="fileUploadNamespace" placeholder="例: shared:tool_docs"></div>
      <div class="field-row"><label>ファイル</label><input type="file" id="fileUploadInput" accept=".pdf,.docx,.pptx,audio/*,video/*"></div>
      <button class="btn primary" id="fileUploadBtn">アップロード・登録</button>
      <div id="fileUploadResult" class="hint"></div>
    </div>

    <div class="section">
      <h2>QA CSV一括登録</h2>
      <p class="hint">ヘッダー行に question, answer 列を含むCSVを貼り付けてください。</p>
      <div class="field-row"><label>namespace</label><input type="text" id="qaCsvNamespace" placeholder="例: shared:tool_docs"></div>
      <textarea id="qaCsvText" rows="6" style="width:100%; font-family:monospace; font-size:.8rem; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:.5rem;" placeholder="question,answer&#10;質問1,回答1&#10;質問2,回答2"></textarea>
      <button class="btn primary" id="qaCsvImportBtn" style="margin-top:.5rem;">一括登録を実行</button>
      <div id="qaCsvProgress" class="hint"></div>
    </div>

    <div class="section">
      <h2>同期履歴</h2>
      <button class="btn" id="refreshKbHistory">再読み込み</button>
      <div class="table-scroll"><table class="admin-table" id="kbHistoryTable"><thead><tr><th>日時</th><th>opId</th><th>種別</th><th>namespace</th><th>ファイル</th><th>状態</th><th>詳細</th></tr></thead><tbody></tbody></table></div>
    </div>

    <div class="section">
      <h2>KBロールバック</h2>
      <p class="hint">同期履歴の「opId」を指定すると、そのopIdで登録された全ファイルをnamespaceから削除できます（元に戻せません）。</p>
      <div class="field-row"><label>opId</label><input type="text" id="rollbackOpId" placeholder="例: op_1234567890_ab12cd"></div>
      <button class="btn danger" id="rollbackBtn">ロールバック実行</button>
      <div id="rollbackResult" class="hint"></div>
    </div>
  </div>
</div>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  const apiKeyEl = $("apiKey");
  const levelEl = $("level");
  const namespaceFocusEl = $("namespaceFocus");

  apiKeyEl.value = localStorage.getItem("ragPocApiKey") || "";
  apiKeyEl.addEventListener("change", () => { localStorage.setItem("ragPocApiKey", apiKeyEl.value); loadNamespaceFocus(); });

  // Cloudflareエッジ側の一時的なエラー（503等）やレスポンスがHTMLになるケースは、
  // 実際には数秒待って再試行すると成功することが多い一過性の障害であることが多い。
  // 毎回ユーザーに手動でbatchSizeを下げて再試行させるのではなく、まず自動で
  // 数回リトライしてから諦めるようにした（2026-08-27）。
  const RETRYABLE_STATUS = new Set([502, 503, 504]);
  async function apiOnce(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Authorization": "Bearer " + apiKeyEl.value, "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      // タイムアウト等でCloudflare/プロキシ側がHTMLエラーページを返すと発生する
      const err = new Error("応答がJSONではありません（処理に時間がかかりすぎてタイムアウトした可能性があります）: HTTP " + res.status);
      err.status = res.status;
      err.retryable = true;
      throw err;
    }
    if (!res.ok) {
      const err = new Error(data.error || ("HTTP " + res.status));
      err.status = res.status;
      err.retryable = RETRYABLE_STATUS.has(res.status);
      throw err;
    }
    return data;
  }

  async function api(path, body, retriesLeft) {
    if (retriesLeft === undefined) retriesLeft = 2;
    try {
      return await apiOnce(path, body);
    } catch (e) {
      if (e.retryable && retriesLeft > 0) {
        const waitMs = (3 - retriesLeft) * 4000 + 3000; // 3s, 7s
        await new Promise((r) => setTimeout(r, waitMs));
        return api(path, body, retriesLeft - 1);
      }
      if (e.retryable) {
        e.message += "（自動再試行しましたが失敗しました。batchSizeを下げて再試行してください）";
      }
      throw e;
    }
  }

  // ---------- 個別DBに絞った検索（検索精度向上のため2026-08-26追加） ----------
  // /admin/namespaces/list は管理者専用のため、一般ユーザーでも自分の許可namespaceが
  // わかるよう /me/namespaces を使う。personal:<ハッシュ化されたuserId> は各APIキー発行時に
  // 自動作成される「自分専用」namespaceで、生のハッシュ値を出しても意味が無いため
  // 固定ラベルにする（実際に生ハッシュがそのまま表示されて分かりにくいと指摘を受けて修正）。
  function namespaceLabel(ns) {
    if (ns.startsWith("personal:")) return "🔒 個人用（自分専用）";
    const idx = ns.indexOf(":");
    return idx === -1 ? ns : ns.slice(idx + 1);
  }
  async function loadNamespaceFocus() {
    if (!apiKeyEl.value.trim()) return;
    const prevValue = namespaceFocusEl.value;
    try {
      const data = await api("/me/namespaces", {});
      namespaceFocusEl.innerHTML = '<option value="">🌐 全DB横断検索</option>';
      data.namespaces.slice().sort().forEach((ns) => {
        const opt = document.createElement("option");
        opt.value = ns;
        opt.textContent = namespaceLabel(ns);
        namespaceFocusEl.appendChild(opt);
      });
      if (data.namespaces.includes(prevValue)) namespaceFocusEl.value = prevValue;
    } catch (e) {
      // 取得失敗時は「全DB横断検索」のみのまま（致命的ではないので黙って諦める）
    }
  }
  loadNamespaceFocus();

  // ---------- タブ切り替え ----------
  const tabButtons = document.querySelectorAll("nav.tabs button");
  const tabPanels = document.querySelectorAll(".tabpanel");
  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      tabPanels.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "history") loadHistory();
      if (btn.dataset.tab === "graph") loadGraph();
      if (btn.dataset.tab === "admin") { loadNamespaceChecks(); loadKeys(); loadNamespaces(); loadKbHistory(); loadUsageStats(); loadRatingStats(); }
      else clearNewKey(); // 管理タブを離れたら、発行直後のAPIキー表示が残らないようにする
    });
  });

  // ---------- チャット ----------
  const messagesEl = $("messages");
  const statusEl = $("status");
  const inputEl = $("input");
  const sendBtn = $("send");

  function setStatus(text, isError) {
    statusEl.textContent = text || "";
    statusEl.className = isError ? "error" : "";
  }

  function extractionClass(rate) {
    if (rate >= 70) return "high";
    if (rate < 40) return "low";
    return "";
  }

  function renderAssistantMessage(container, answer, sources, extractionRate, extractionDetail, memoryId, existingRating) {
    const wrap = document.createElement("div");
    wrap.className = "msg assistant";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = answer;
    wrap.appendChild(bubble);

    const meta = document.createElement("div");
    meta.className = "meta";
    const badge = document.createElement("span");
    badge.className = "extraction " + extractionClass(extractionRate);
    badge.textContent = "出典引用率 " + extractionRate + "% (" + extractionDetail + ")";
    meta.appendChild(badge);

    if (memoryId) {
      const up = document.createElement("button");
      up.className = "rate-btn" + (existingRating === 1 ? " active-up" : "");
      up.textContent = "役に立った";
      const down = document.createElement("button");
      down.className = "rate-btn" + (existingRating === -1 ? " active-down" : "");
      down.textContent = "役に立たなかった";
      up.onclick = () => rate(memoryId, 1, up, down);
      down.onclick = () => rate(memoryId, -1, up, down);
      meta.appendChild(up);
      meta.appendChild(down);
    }
    wrap.appendChild(meta);

    if (sources && sources.length > 0) {
      const details = document.createElement("details");
      details.className = "sources";
      const summary = document.createElement("summary");
      summary.textContent = "参照した情報源（" + sources.length + "件）";
      details.appendChild(summary);

      // 実際に回答文中で引用された（[n]が1回以上出現した）出典が2件以上ある場合、
      // 「どの出典が根拠としてどれだけ重く使われたか」を引用回数の比率で示す。
      // namespace単位の内訳（下のブロック）は「どのDBから取れたか」を示すだけで、
      // 複数出典を実際にどう重み付けして使ったかは分からない、という指摘への対応（2026-08-27）。
      const citedSources = sources
        .map((s, i) => ({ ...s, idx: i, count: s.citationCount || 0 }))
        .filter((s) => s.count > 0);
      const totalCitations = citedSources.reduce((sum, s) => sum + s.count, 0);
      if (citedSources.length > 1 && totalCitations > 0) {
        const contribWrap = document.createElement("div");
        contribWrap.className = "source-composition";
        const label = document.createElement("div");
        label.className = "composition-title";
        label.textContent = "引用の内訳（実際に引用された回数の比率、延べ" + totalCitations + "回）";
        contribWrap.appendChild(label);
        const bar = document.createElement("div");
        bar.className = "composition-bar";
        const legend = document.createElement("div");
        legend.className = "composition-legend";
        citedSources.forEach((s) => {
          const color = NS_PALETTE[s.idx % NS_PALETTE.length];
          const pct = Math.round((100 * s.count) / totalCitations);
          const seg = document.createElement("span");
          seg.style.background = color;
          seg.style.width = pct + "%";
          bar.appendChild(seg);

          const item = document.createElement("span");
          item.className = "item";
          const dot = document.createElement("span");
          dot.className = "dot";
          dot.style.background = color;
          item.appendChild(dot);
          item.appendChild(document.createTextNode("[" + (s.idx + 1) + "] " + s.file + "（" + s.count + "回・" + pct + "%）"));
          legend.appendChild(item);
        });
        contribWrap.appendChild(bar);
        contribWrap.appendChild(legend);
        details.appendChild(contribWrap);
      }

      // 複数DBにまたがって抽出された場合のみ、内訳（DB構成比）バーを表示する
      const nsCounts = new Map();
      sources.forEach((s) => nsCounts.set(s.namespace, (nsCounts.get(s.namespace) || 0) + 1));
      if (nsCounts.size > 1) {
        const compWrap = document.createElement("div");
        compWrap.className = "source-composition";
        const bar = document.createElement("div");
        bar.className = "composition-bar";
        const legend = document.createElement("div");
        legend.className = "composition-legend";
        nsCounts.forEach((count, ns) => {
          const seg = document.createElement("span");
          seg.style.background = nsColor(ns);
          seg.style.width = (100 * count / sources.length) + "%";
          bar.appendChild(seg);

          const item = document.createElement("span");
          item.className = "item";
          const dot = document.createElement("span");
          dot.className = "dot";
          dot.style.background = nsColor(ns);
          item.appendChild(dot);
          item.appendChild(document.createTextNode(ns + " " + count + "件 (" + Math.round(100 * count / sources.length) + "%)"));
          legend.appendChild(item);
        });
        compWrap.appendChild(bar);
        compWrap.appendChild(legend);
        details.appendChild(compWrap);
      }

      const ul = document.createElement("ul");
      sources.forEach((s, i) => {
        const li = document.createElement("li");
        li.appendChild(document.createTextNode("[" + (i + 1) + "] " + s.file + " "));
        const pill = document.createElement("span");
        pill.className = "ns-pill";
        pill.style.background = nsColor(s.namespace);
        pill.textContent = s.namespace;
        li.appendChild(pill);
        if (s.score != null) {
          const pct = document.createElement("span");
          pct.className = "score-pct";
          pct.textContent = " " + s.score + "% ";
          li.appendChild(pct);
        }
        const citedBadge = document.createElement("span");
        citedBadge.className = "cited-badge " + (s.cited ? "cited" : "uncited");
        citedBadge.textContent = s.cited ? "✓引用" : "未引用";
        li.appendChild(citedBadge);
        ul.appendChild(li);
      });
      details.appendChild(ul);
      wrap.appendChild(details);
    }
    container.appendChild(wrap);
  }

  function renderUserMessage(container, text) {
    const wrap = document.createElement("div");
    wrap.className = "msg user";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    container.appendChild(wrap);
  }

  async function rate(memoryId, value, upBtn, downBtn) {
    try {
      await api("/memory/rate", { id: memoryId, rating: value });
      upBtn.classList.toggle("active-up", value === 1);
      downBtn.classList.toggle("active-down", value === -1);
    } catch (e) {
      alert("評価の送信に失敗しました: " + e.message);
    }
  }

  async function send() {
    const text = inputEl.value.trim();
    if (!text) return;
    if (!apiKeyEl.value.trim()) { setStatus("APIキーを入力してください", true); return; }
    inputEl.value = "";
    inputEl.style.height = "auto";
    renderUserMessage(messagesEl, text);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    sendBtn.disabled = true;
    setStatus("検索・回答生成中…");
    try {
      const focusNs = namespaceFocusEl.value;
      const data = await api("/query", { query: text, limit: 5, level: levelEl.value, namespaces: focusNs ? [focusNs] : undefined });
      renderAssistantMessage(messagesEl, data.answer, data.sources, data.extractionRate, data.extractionDetail, data.memoryId, null);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      setStatus("");
    } catch (e) {
      setStatus("エラー: " + e.message, true);
    } finally {
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }
  sendBtn.addEventListener("click", send);
  inputEl.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  inputEl.addEventListener("input", () => { inputEl.style.height = "auto"; inputEl.style.height = Math.min(inputEl.scrollHeight, 128) + "px"; });

  // ---------- 履歴タブ ----------
  async function loadHistory() {
    const pane = $("historyPane");
    if (!apiKeyEl.value.trim()) { pane.innerHTML = '<p class="hint error">APIキーを入力してください</p>'; return; }
    pane.innerHTML = '<p class="hint">読み込み中…</p>';
    try {
      const data = await api("/memory/list", { limit: 30 });
      pane.innerHTML = "";
      if (data.entries.length === 0) { pane.innerHTML = '<p class="hint">履歴はまだありません</p>'; return; }
      data.entries.forEach((entry) => {
        renderUserMessage(pane, entry.query);
        renderAssistantMessage(pane, entry.answer, entry.sources, 0, "-", entry.id, entry.rating);
      });
    } catch (e) {
      pane.innerHTML = '<p class="hint error">読み込みに失敗しました: ' + e.message + '</p>';
    }
  }

  // ---------- グラフタブ（3D、Three.js） ----------
  // ObsidianのGraph Viewを参考に、反発力/結集力をスライダーでライブ調整できる常時シミュレーション、
  // 再生/停止トグル、DB（namespace）ごとの表示切替、固定パレットによる色分けを実装する。
  const graphContainer = $("graphContainer");
  const graphDetail = $("graphDetail");
  let gRenderer = null, gScene = null, gCamera = null, gControls = null, gAnimHandle = null;
  let gRaycaster = null, gMouse = null;
  let gNodes = [], gEdges = [], gMeshes = [], gLineSegments = null, gActiveEdges = [];
  let gVisibleNs = new Set();
  let gPlaying = true;
  let gRepel = 4000, gCenter = 0.002;
  const LINK_TARGET_LEN = 60;
  const NS_PALETTE = ["#e8843c", "#5b8def", "#5cb85c", "#e0555f", "#9b6fd0", "#3ec1c9", "#e0c73e", "#e07fc0", "#8d99a6", "#c97a3d", "#4fc9a5", "#d64f8a"];
  let gNsColors = new Map();

  // namespace(DB)ごとに固定色を割り当てる。グラフタブ・チャットの出典表示など画面全体で共有し、
  // 初めて登場した順にパレットから割り振る（セッション内では常に同じ色になる）。
  function nsColor(namespace) {
    if (!gNsColors.has(namespace)) {
      gNsColors.set(namespace, NS_PALETTE[gNsColors.size % NS_PALETTE.length]);
    }
    return gNsColors.get(namespace);
  }

  // 1フレーム分の力学シミュレーション（斥力＋エッジのバネ力＋中心引力）。
  // gNodes[i].x/y/z/vx/vy/vzを直接更新する。反発力(gRepel)・結集力(gCenter)はスライダーでライブ変更可能。
  function simulationStep() {
    for (let i = 0; i < gNodes.length; i++) {
      const a = gNodes[i];
      for (let j = i + 1; j < gNodes.length; j++) {
        const b = gNodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        let dist2 = dx * dx + dy * dy + dz * dz || 0.01;
        const force = gRepel / dist2;
        const dist = Math.sqrt(dist2);
        dx /= dist; dy /= dist; dz /= dist;
        a.vx += dx * force; a.vy += dy * force; a.vz += dz * force;
        b.vx -= dx * force; b.vy -= dy * force; b.vz -= dz * force;
      }
    }
    gActiveEdges.forEach(([i, j]) => {
      const a = gNodes[i], b = gNodes[j];
      let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 0.01;
      const force = (dist - LINK_TARGET_LEN) * 0.02;
      dx /= dist; dy /= dist; dz /= dist;
      a.vx += dx * force; a.vy += dy * force; a.vz += dz * force;
      b.vx -= dx * force; b.vy -= dy * force; b.vz -= dz * force;
    });
    gNodes.forEach((p) => {
      p.vx += -p.x * gCenter; p.vy += -p.y * gCenter; p.vz += -p.z * gCenter;
      p.x += p.vx * 0.15; p.y += p.vy * 0.15; p.z += p.vz * 0.15;
      p.vx *= 0.85; p.vy *= 0.85; p.vz *= 0.85;
    });
  }

  function syncMeshPositions() {
    for (let i = 0; i < gNodes.length; i++) {
      gMeshes[i].position.set(gNodes[i].x, gNodes[i].y, gNodes[i].z);
    }
    if (gLineSegments) {
      const posAttr = gLineSegments.geometry.getAttribute("position");
      let k = 0;
      gActiveEdges.forEach(([i, j]) => {
        posAttr.setXYZ(k++, gNodes[i].x, gNodes[i].y, gNodes[i].z);
        posAttr.setXYZ(k++, gNodes[j].x, gNodes[j].y, gNodes[j].z);
      });
      posAttr.needsUpdate = true;
    }
  }

  // 現在表示中（gVisibleNsに含まれる）のノードだけを対象にエッジのジオメトリを作り直す。
  // 頂点数が変わる操作なのでDB表示切替のたびに呼ぶ（毎フレームは呼ばない）。
  function rebuildEdgeGeometry() {
    if (gLineSegments) {
      gScene.remove(gLineSegments);
      gLineSegments.geometry.dispose();
      gLineSegments.material.dispose();
      gLineSegments = null;
    }
    gActiveEdges = gEdges
      .map((e) => [e.sourceIdx, e.targetIdx])
      .filter(([i, j]) => i != null && j != null && gVisibleNs.has(gNodes[i].namespace) && gVisibleNs.has(gNodes[j].namespace));
    const positions = new Float32Array(gActiveEdges.length * 6);
    let k = 0;
    gActiveEdges.forEach(([i, j]) => {
      positions[k++] = gNodes[i].x; positions[k++] = gNodes[i].y; positions[k++] = gNodes[i].z;
      positions[k++] = gNodes[j].x; positions[k++] = gNodes[j].y; positions[k++] = gNodes[j].z;
    });
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    const mat = new THREE.LineBasicMaterial({ color: 0x888888, transparent: true, opacity: 0.35 });
    gLineSegments = new THREE.LineSegments(geom, mat);
    gScene.add(gLineSegments);
  }

  function applyVisibility() {
    gMeshes.forEach((mesh, i) => { mesh.visible = gVisibleNs.has(gNodes[i].namespace); });
    rebuildEdgeGeometry();
  }

  function renderLegend() {
    const counts = new Map();
    gNodes.forEach((n) => counts.set(n.namespace, (counts.get(n.namespace) || 0) + 1));
    const ul = $("graphLegend");
    ul.innerHTML = "";
    Array.from(counts.keys()).sort().forEach((ns) => {
      const li = document.createElement("li");
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = nsColor(ns);
      const label = document.createElement("span");
      label.className = "ns-label";
      label.textContent = ns;
      const count = document.createElement("span");
      count.className = "ns-count";
      count.textContent = String(counts.get(ns));
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = gVisibleNs.has(ns);
      cb.addEventListener("change", () => {
        if (cb.checked) gVisibleNs.add(ns); else gVisibleNs.delete(ns);
        applyVisibility();
      });
      li.appendChild(cb);
      li.appendChild(swatch);
      li.appendChild(label);
      li.appendChild(count);
      li.addEventListener("click", (ev) => { if (ev.target !== cb) cb.click(); });
      ul.appendChild(li);
    });
  }

  function disposeGraph() {
    if (gAnimHandle) cancelAnimationFrame(gAnimHandle);
    if (gRenderer) {
      gRenderer.dispose();
      if (gRenderer.domElement.parentElement) gRenderer.domElement.parentElement.removeChild(gRenderer.domElement);
    }
    gRenderer = null; gScene = null; gCamera = null; gControls = null;
    gNodes = []; gEdges = []; gMeshes = []; gLineSegments = null; gActiveEdges = [];
  }

  const SOURCE_LABELS = { notion: "Notion", drive: "Google Drive", manual: "手動登録" };
  function showNodeDetail(nodeData) {
    $("graphDetailTitle").textContent = nodeData.label;
    $("graphDetailNs").textContent = nodeData.namespace;
    $("graphDetailType").textContent = "Type: " + (SOURCE_LABELS[nodeData.source] || "不明（旧データ）");
    $("graphDetailSize").textContent = "Size: " + (nodeData.size != null ? nodeData.size + " 文字" : "不明（旧データ）");
    $("graphDetailDate").textContent = "適用日時: " + (nodeData.ingestedAt != null ? new Date(nodeData.ingestedAt * 1000).toLocaleString() : "不明（旧データ）");
    const neighborIds = new Set();
    gEdges.forEach((e) => {
      if (e.source === nodeData.id) neighborIds.add(e.target);
      if (e.target === nodeData.id) neighborIds.add(e.source);
    });
    $("graphDetailDegree").textContent = "接続数: " + neighborIds.size;
    const ul = $("graphDetailNeighbors");
    ul.innerHTML = "";
    const byId = new Map(gNodes.map((n) => [n.id, n]));
    Array.from(neighborIds).slice(0, 20).forEach((id) => {
      const li = document.createElement("li");
      const n = byId.get(id);
      li.textContent = n ? n.label : id;
      ul.appendChild(li);
    });
    graphDetail.classList.add("visible");
  }
  $("graphDetailClose").addEventListener("click", () => graphDetail.classList.remove("visible"));

  $("graphRepel").addEventListener("input", (ev) => {
    gRepel = Number(ev.target.value);
    $("graphRepelVal").textContent = String(gRepel);
  });
  $("graphCenter").addEventListener("input", (ev) => {
    gCenter = Number(ev.target.value) / 10000;
    $("graphCenterVal").textContent = gCenter.toFixed(4);
  });
  $("graphPlayPause").addEventListener("click", () => {
    gPlaying = !gPlaying;
    $("graphPlayPause").textContent = gPlaying ? "⏸ 停止" : "▶ 再生";
  });

  async function loadGraph() {
    $("graphStats").textContent = "読み込み中…";
    if (!apiKeyEl.value.trim()) { $("graphStats").textContent = "APIキーを入力してください"; return; }
    if (typeof THREE === "undefined") { $("graphStats").textContent = "3D描画ライブラリの読み込みに失敗しました"; return; }
    try {
      const data = await api("/graph", { maxNodes: 150 });
      $("graphStats").textContent = data.nodes.length + " ノード / " + data.edges.length + " エッジ" + (data.truncated ? "（上限により一部省略）" : "");
      if (data.nodes.length === 0) return;

      disposeGraph();

      const spread = 220;
      gNodes = data.nodes.map((n) => ({
        ...n,
        x: (Math.random() - 0.5) * spread, y: (Math.random() - 0.5) * spread, z: (Math.random() - 0.5) * spread,
        vx: 0, vy: 0, vz: 0,
      }));
      const indexById = new Map(gNodes.map((n, i) => [n.id, i]));
      gEdges = data.edges.map((e) => ({ ...e, sourceIdx: indexById.get(e.source), targetIdx: indexById.get(e.target) }));

      const uniqueNs = Array.from(new Set(gNodes.map((n) => n.namespace)));
      uniqueNs.forEach((ns) => nsColor(ns));
      gVisibleNs = new Set(uniqueNs);
      renderLegend();

      // 初期レイアウトをウォームスタート（現在のスライダー値で150回分先に計算しておく）
      for (let iter = 0; iter < 150; iter++) simulationStep();

      const degree = new Map();
      gEdges.forEach((e) => {
        degree.set(e.source, (degree.get(e.source) || 0) + 1);
        degree.set(e.target, (degree.get(e.target) || 0) + 1);
      });

      const width = graphContainer.clientWidth, height = graphContainer.clientHeight || 500;
      gScene = new THREE.Scene();
      gCamera = new THREE.PerspectiveCamera(60, width / height, 0.1, 2000);
      gCamera.position.set(0, 0, 400);
      gRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      gRenderer.setSize(width, height);
      gRenderer.setPixelRatio(window.devicePixelRatio || 1);
      graphContainer.insertBefore(gRenderer.domElement, graphContainer.firstChild);

      gControls = new THREE.OrbitControls(gCamera, gRenderer.domElement);
      gControls.enableDamping = true;
      gControls.dampingFactor = 0.08;

      gScene.add(new THREE.AmbientLight(0xffffff, 1.0));

      rebuildEdgeGeometry();

      // ノード（球体）。接続数が多いほど大きく、namespaceごとに固定パレットで色分けする
      gMeshes = gNodes.map((n) => {
        const deg = degree.get(n.id) || 0;
        const radius = 3 + Math.min(deg, 15) * 0.6;
        const color = new THREE.Color();
        color.setStyle(nsColor(n.namespace));
        const mesh = new THREE.Mesh(
          new THREE.SphereGeometry(radius, 12, 12),
          new THREE.MeshBasicMaterial({ color })
        );
        mesh.position.set(n.x, n.y, n.z);
        mesh.userData = n;
        gScene.add(mesh);
        return mesh;
      });

      gRaycaster = new THREE.Raycaster();
      gMouse = new THREE.Vector2();
      gRenderer.domElement.addEventListener("click", (ev) => {
        const rect = gRenderer.domElement.getBoundingClientRect();
        gMouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        gMouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
        gRaycaster.setFromCamera(gMouse, gCamera);
        const hits = gRaycaster.intersectObjects(gMeshes.filter((m) => m.visible));
        if (hits.length > 0) showNodeDetail(hits[0].object.userData);
      });

      gPlaying = true;
      $("graphPlayPause").textContent = "⏸ 停止";

      function animate() {
        gAnimHandle = requestAnimationFrame(animate);
        if (gPlaying) { simulationStep(); syncMeshPositions(); }
        gControls.update();
        gRenderer.render(gScene, gCamera);
      }
      animate();
    } catch (e) {
      $("graphStats").textContent = "エラー: " + e.message;
    }
  }
  $("graphRefresh").addEventListener("click", loadGraph);
  window.addEventListener("resize", () => {
    if (!gRenderer || !gCamera) return;
    const width = graphContainer.clientWidth, height = graphContainer.clientHeight || 500;
    gCamera.aspect = width / height;
    gCamera.updateProjectionMatrix();
    gRenderer.setSize(width, height);
  });

  // ---------- 管理タブ：利用状況グラフ ----------
  function drawUsageChart(daily) {
    const canvas = $("usageChart");
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.parentElement.clientWidth || 900;
    canvas.style.width = cssW + "px";
    canvas.width = cssW * dpr;
    canvas.height = 220 * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = cssW, h = 220;
    ctx.clearRect(0, 0, w, h);
    const muted = getComputedStyle(document.body).getPropertyValue("--muted").trim() || "#888";
    const accent = getComputedStyle(document.body).getPropertyValue("--accent").trim() || "#3358d6";
    if (daily.length === 0) {
      ctx.fillStyle = muted;
      ctx.font = "13px sans-serif";
      ctx.fillText("データがありません", 10, h / 2);
      return;
    }
    const padL = 46, padB = 24, padT = 10, padR = 10;
    const plotW = w - padL - padR, plotH = h - padT - padB;
    const maxTokens = Math.max(...daily.map((d) => d.tokens), 1);
    const barW = plotW / daily.length;

    ctx.strokeStyle = muted; ctx.globalAlpha = 0.3;
    ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, padT + plotH); ctx.lineTo(padL + plotW, padT + plotH); ctx.stroke();
    ctx.globalAlpha = 1;

    ctx.fillStyle = muted; ctx.font = "10px sans-serif"; ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const v = Math.round((maxTokens * i) / 4);
      const y = padT + plotH - (plotH * i) / 4;
      ctx.fillText(String(v), padL - 6, y + 3);
    }
    ctx.textAlign = "center";

    ctx.fillStyle = accent;
    daily.forEach((d, i) => {
      const barH = (d.tokens / maxTokens) * plotH;
      const x = padL + i * barW + barW * 0.15;
      const y = padT + plotH - barH;
      ctx.fillRect(x, y, barW * 0.7, barH);
    });

    ctx.fillStyle = muted;
    const labelStep = Math.max(1, Math.ceil(daily.length / 10));
    daily.forEach((d, i) => {
      if (i % labelStep !== 0 && i !== daily.length - 1) return;
      const x = padL + i * barW + barW / 2;
      ctx.fillText(d.day.slice(5), x, padT + plotH + 14);
    });
  }

  function drawDonut(canvas, used, limit) {
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const size = 28;
    canvas.width = size * dpr; canvas.height = size * dpr;
    canvas.style.width = size + "px"; canvas.style.height = size + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cx = size / 2, cy = size / 2, r = size / 2 - 3;
    const ratio = limit ? Math.min(used / limit, 1) : 0;
    const muted = getComputedStyle(document.body).getPropertyValue("--border").trim() || "#ccc";
    const color = ratio > 0.9 ? (getComputedStyle(document.body).getPropertyValue("--bad").trim() || "#c23a3a")
      : (getComputedStyle(document.body).getPropertyValue("--accent").trim() || "#3358d6");
    ctx.lineWidth = 4;
    ctx.strokeStyle = muted;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = color;
    ctx.beginPath(); ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + ratio * Math.PI * 2); ctx.stroke();
  }

  async function loadUsageStats() {
    if (!apiKeyEl.value.trim()) return;
    const days = Number($("usageDays").value) || 14;
    try {
      const data = await api("/admin/usage/stats", { days });
      drawUsageChart(data.daily);
      const tbody = $("usageByUserTable").querySelector("tbody");
      tbody.innerHTML = "";
      data.byUser.forEach((u) => {
        const tr = document.createElement("tr");
        tr.innerHTML = "<td>" + (u.displayName || u.userId) + "</td><td>" + u.queries + "</td><td>" + u.tokens + "</td>";
        tbody.appendChild(tr);
      });
    } catch (e) {
      $("usageByUserTable").querySelector("tbody").innerHTML = '<tr><td colspan=3>取得に失敗しました: ' + e.message + '</td></tr>';
    }
  }
  $("refreshUsage").addEventListener("click", loadUsageStats);
  $("usageDays").addEventListener("change", loadUsageStats);

  // ---------- 管理タブ：namespaceチェックボックス ----------
  async function loadNamespaceChecks() {
    const box = $("newKeyNamespaces");
    try {
      const data = await api("/admin/namespaces/list", {});
      box.innerHTML = "";
      data.namespaces.filter((n) => n.scope === "shared").forEach((n) => {
        const label = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.value = n.namespace_id;
        label.appendChild(cb);
        label.appendChild(document.createTextNode(n.namespace_id));
        box.appendChild(label);
      });
    } catch (e) {
      box.textContent = "namespace一覧の取得に失敗しました（管理者キーが必要です）";
    }
  }

  // 発行直後の生キーは、画面を離れても（タブ切替・再読み込みしない限り）表示されたままに
  // なっていた（肩越し閲覧・画面共有時の漏洩リスク）。コピー操作を挟める猶予は残しつつ、
  // 60秒後の自動非表示・明示的な「隠す」ボタン・管理タブを離れた時点でのクリアの
  // 3経路で確実に画面から消えるようにした（2026-08-27）。
  let newKeyHideTimer = null;
  let newKeyCountdownTimer = null;

  function clearNewKey() {
    if (newKeyHideTimer) { clearTimeout(newKeyHideTimer); newKeyHideTimer = null; }
    if (newKeyCountdownTimer) { clearInterval(newKeyCountdownTimer); newKeyCountdownTimer = null; }
    $("newKeyResult").innerHTML = "";
  }

  function showNewKey(apiKey) {
    clearNewKey();
    const box = $("newKeyResult");
    const wrap = document.createElement("div");
    wrap.className = "keybox";
    const label = document.createElement("div");
    label.textContent = "発行されたAPIキー（今だけ表示されます。必ずコピーしてから閉じてください）：";
    wrap.appendChild(label);

    const row = document.createElement("div");
    row.className = "keybox-row";
    const code = document.createElement("code");
    code.textContent = apiKey;
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.textContent = "コピー";
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(apiKey);
        copyBtn.textContent = "コピー済み";
      } catch {
        copyBtn.textContent = "コピー失敗（手動選択してください）";
      }
    });
    const hideBtn = document.createElement("button");
    hideBtn.type = "button";
    hideBtn.textContent = "隠す";
    hideBtn.addEventListener("click", clearNewKey);
    row.appendChild(code);
    row.appendChild(copyBtn);
    row.appendChild(hideBtn);
    wrap.appendChild(row);

    const countdown = document.createElement("p");
    countdown.className = "hint";
    wrap.appendChild(countdown);
    box.innerHTML = "";
    box.appendChild(wrap);

    let remaining = 60;
    countdown.textContent = "あと" + remaining + "秒で自動的に非表示になります";
    newKeyCountdownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining > 0) countdown.textContent = "あと" + remaining + "秒で自動的に非表示になります";
    }, 1000);
    newKeyHideTimer = setTimeout(clearNewKey, 60000);
  }

  $("createKeyBtn").addEventListener("click", async () => {
    const namespaces = Array.from($("newKeyNamespaces").querySelectorAll("input:checked")).map((c) => c.value);
    try {
      const data = await api("/admin/keys/create", {
        displayName: $("newKeyName").value.trim(),
        role: $("newKeyAdmin").checked ? "admin" : "member",
        namespaces,
        ragCapacity: Number($("newKeyCapacity").value) || 100000,
      });
      showNewKey(data.apiKey);
      loadKeys();
    } catch (e) {
      clearNewKey();
      $("newKeyResult").innerHTML = '<p class="hint error">' + e.message + '</p>';
    }
  });

  async function loadKeys() {
    const tbody = $("keysTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=6>読み込み中…</td></tr>";
    try {
      const data = await api("/admin/keys/list", {});
      tbody.innerHTML = "";
      data.keys.forEach((k) => {
        const tr = document.createElement("tr");
        const created = new Date(k.created_at * 1000).toLocaleString();
        tr.innerHTML = '<td>' + k.display_name + '</td><td>' + k.role + '</td><td>' +
          (k.rag_limit != null ? (k.rag_used + '/' + k.rag_limit) : '無制限') + '</td><td></td><td>' + created + '</td><td></td>';
        if (k.rag_limit != null) {
          const donutCell = tr.children[3];
          const donutCanvas = document.createElement("canvas");
          donutCell.appendChild(donutCanvas);
          drawDonut(donutCanvas, k.rag_used, k.rag_limit);
        }
        const delBtn = document.createElement("button");
        delBtn.className = "btn danger"; delBtn.textContent = "削除";
        delBtn.onclick = async () => {
          if (!confirm(k.display_name + " を削除しますか？")) return;
          try { await api("/admin/keys/delete", { userId: k.user_id }); loadKeys(); }
          catch (e) { alert("削除に失敗しました: " + e.message); }
        };
        tr.lastElementChild.appendChild(delBtn);
        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan=6>取得に失敗しました: ' + e.message + '</td></tr>';
    }
  }
  $("refreshKeys").addEventListener("click", loadKeys);

  $("createNsBtn").addEventListener("click", async () => {
    try {
      await api("/admin/namespaces/create", { namespaceId: $("newNsId").value.trim(), scope: $("newNsScope").value });
      $("newNsId").value = "";
      loadNamespaces();
      loadNamespaceChecks();
    } catch (e) { alert("作成に失敗しました: " + e.message); }
  });

  async function loadNamespaces() {
    const tbody = $("nsTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=5>読み込み中…</td></tr>";
    try {
      const data = await api("/admin/namespaces/list", {});
      tbody.innerHTML = "";
      data.namespaces.forEach((n) => {
        const tr = document.createElement("tr");
        tr.innerHTML = '<td>' + n.namespace_id + '</td><td>' + n.scope + '</td><td>' + (n.owner_user_id || "-") + '</td><td></td><td></td>';
        const limitCell = tr.children[3];
        const limitInput = document.createElement("input");
        limitInput.type = "number";
        limitInput.min = "0";
        limitInput.style.width = "70px";
        if (n.result_limit != null) limitInput.value = n.result_limit;
        const limitBtn = document.createElement("button");
        limitBtn.className = "btn"; limitBtn.textContent = "設定";
        limitBtn.style.marginLeft = ".3rem";
        limitBtn.onclick = async () => {
          const v = limitInput.value.trim();
          try {
            await api("/admin/namespaces/set-limit", { namespaceId: n.namespace_id, resultLimit: v === "" ? null : Number(v) });
            loadNamespaces();
          } catch (e) { alert("設定に失敗しました: " + e.message); }
        };
        limitCell.appendChild(limitInput);
        limitCell.appendChild(limitBtn);
        const delBtn = document.createElement("button");
        delBtn.className = "btn danger"; delBtn.textContent = "削除";
        delBtn.onclick = async () => {
          if (!confirm(n.namespace_id + " を削除しますか？")) return;
          try { await api("/admin/namespaces/delete", { namespaceId: n.namespace_id }); loadNamespaces(); }
          catch (e) { alert("削除に失敗しました: " + e.message); }
        };
        tr.lastElementChild.appendChild(delBtn);
        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan=5>取得に失敗しました: ' + e.message + '</td></tr>';
    }
  }
  $("refreshNs").addEventListener("click", loadNamespaces);

  $("kbSetSourceBtn").addEventListener("click", async () => {
    try {
      await api("/admin/kb/set-source", {
        namespace: $("kbNamespace").value.trim(),
        notionDatabaseId: $("kbNotionId").value.trim() || undefined,
        driveFolderId: $("kbDriveId").value.trim() || undefined,
      });
      alert("同期元を設定しました");
    } catch (e) { alert("設定に失敗しました: " + e.message); }
  });

  async function runSync(endpoint, batchSize) {
    const namespace = $("kbNamespace").value.trim();
    if (!namespace) { alert("namespaceを入力してください"); return; }
    const progressEl = $("kbSyncProgress");
    let opId = null, startIndex = 0, totalDocs = 0, totalChunks = 0;
    progressEl.textContent = "同期中…";
    try {
      while (true) {
        const body = { namespace, startIndex, batchSize };
        if (opId) body.opId = opId;
        const data = await api(endpoint, body);
        opId = data.opId;
        totalDocs += data.documents;
        totalChunks += data.chunks;
        const total = data.totalPages ?? data.totalFiles ?? "?";
        progressEl.textContent = "進捗: " + data.processedRange[1] + "/" + total + "（累計 " + totalDocs + "件・" + totalChunks + "チャンク）";
        if (data.nextIndex === null || data.nextIndex === undefined) break;
        startIndex = data.nextIndex;
      }
      progressEl.textContent = "完了: " + totalDocs + "件・" + totalChunks + "チャンク登録";
      loadKbHistory();
    } catch (e) {
      progressEl.textContent = "エラー: " + e.message;
    }
  }
  // NotionはテキストのみでPDF/PPTX変換のような重い処理が無いためbatchSize=5でも速いが、
  // Driveは同期時にPDF/PPTX/音声動画の変換（Gemini呼び出し込み）が挟まるため1件あたりが
  // 大幅に遅くなる。batchSize=5のままだと1リクエストが100秒を超え、ブラウザ/中継プロキシ側の
  // タイムアウトでHTMLエラーページが返り「Unexpected token '<'」というJSON解析エラーになる
  // ことを実機で確認した（2026-08-26）。Drive側はbatchSize=1にして1リクエストを短く保つ。
  $("kbSyncNotionBtn").addEventListener("click", () => runSync("/admin/sync/notion", 5));
  $("kbSyncDriveBtn").addEventListener("click", () => runSync("/admin/sync/drive", 1));

  async function loadKbHistory() {
    const tbody = $("kbHistoryTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=7>読み込み中…</td></tr>";
    try {
      const data = await api("/admin/kb/history", { limit: 30 });
      tbody.innerHTML = "";
      data.entries.forEach((e) => {
        const tr = document.createElement("tr");
        const when = new Date(e.created_at * 1000).toLocaleString();
        tr.innerHTML = '<td>' + when + '</td><td>' + e.op_id + '</td><td>' + e.source + '</td><td>' + e.namespace_id + '</td><td>' + (e.file || "-") + '</td><td>' + e.status + '</td><td>' + (e.detail || "") + '</td>';
        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan=7>取得に失敗しました: ' + e.message + '</td></tr>';
    }
  }
  $("refreshKbHistory").addEventListener("click", loadKbHistory);

  // ---------- 管理タブ：評価統計 ----------
  async function loadRatingStats() {
    try {
      const data = await api("/admin/rating-stats", {});
      $("ratingSummary").textContent = "合計 " + data.total + "件（役に立った: " + data.good + " / 役に立たなかった: " + data.bad + " / 未評価: " + data.unrated + "）";
      const tbody = $("ratingByUserTable").querySelector("tbody");
      tbody.innerHTML = "";
      data.byUser.forEach((u) => {
        const tr = document.createElement("tr");
        tr.innerHTML = "<td>" + (u.displayName || u.userId) + "</td><td>" + u.total + "</td><td>" + u.good + "</td><td>" + u.bad + "</td>";
        tbody.appendChild(tr);
      });
    } catch (e) {
      $("ratingSummary").textContent = "取得に失敗しました: " + e.message;
    }
  }
  $("refreshRatingStats").addEventListener("click", loadRatingStats);

  // ---------- 管理タブ：URL手動登録 ----------
  $("urlImportBtn").addEventListener("click", async () => {
    const namespace = $("urlImportNamespace").value.trim();
    const url = $("urlImportUrl").value.trim();
    const title = $("urlImportTitle").value.trim();
    if (!namespace || !url) { $("urlImportResult").textContent = "namespaceとURLを入力してください"; return; }
    $("urlImportResult").textContent = "取得・登録中…";
    try {
      const data = await api("/admin/kb/import-url", { namespace, url, title: title || undefined });
      $("urlImportResult").textContent = "完了: " + data.chunks + "チャンク登録" + (data.skipped > 0 ? "（" + data.skipped + "件スキップ）" : "");
      loadKbHistory();
    } catch (e) {
      $("urlImportResult").textContent = "エラー: " + e.message;
    }
  });

  // ---------- 管理タブ：設定バックアップ ----------
  $("backupExportBtn").addEventListener("click", async () => {
    $("backupExportResult").textContent = "エクスポート中…";
    try {
      const data = await api("/admin/backup/export", {});
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "rag-poc-backup-" + new Date().toISOString().slice(0, 10) + ".json";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      $("backupExportResult").textContent = "ダウンロードしました（" + data.namespaces.length + " namespace, " + data.users.length + " ユーザー）";
    } catch (e) {
      $("backupExportResult").textContent = "エラー: " + e.message;
    }
  });

  // ---------- 管理タブ：ヘルスチェック・アラート ----------
  $("healthCheckBtn").addEventListener("click", async () => {
    $("healthCheckResult").textContent = "実行中…";
    try {
      const data = await api("/admin/health/check", {});
      if (data.issues.length === 0) {
        $("healthCheckResult").textContent = "問題は見つかりませんでした";
      } else {
        $("healthCheckResult").textContent = data.issues.map((i) => "[" + i.severity + "] " + i.message).join(" / ");
      }
    } catch (e) {
      $("healthCheckResult").textContent = "エラー: " + e.message;
    }
  });
  $("testAlertBtn").addEventListener("click", async () => {
    $("healthCheckResult").textContent = "送信中…";
    try {
      const data = await api("/admin/health/test-alert", {});
      $("healthCheckResult").textContent = "Slack: " + data.results.slack + " / Gmail: " + data.results.gmail;
    } catch (e) {
      $("healthCheckResult").textContent = "エラー: " + e.message;
    }
  });

  // ---------- 管理タブ：YouTube文字起こし登録 ----------
  $("ytImportBtn").addEventListener("click", async () => {
    const namespace = $("ytImportNamespace").value.trim();
    const youtubeUrl = $("ytImportUrl").value.trim();
    const title = $("ytImportTitle").value.trim();
    if (!namespace || !youtubeUrl) { $("ytImportResult").textContent = "namespaceとYouTube URLを入力してください"; return; }
    $("ytImportResult").textContent = "文字起こし中…（動画の長さによっては数十秒かかります）";
    try {
      const data = await api("/admin/kb/import-youtube", { namespace, youtubeUrl, title: title || undefined });
      $("ytImportResult").textContent = "完了: " + data.chunks + "チャンク登録" + (data.skipped > 0 ? "（" + data.skipped + "件スキップ）" : "");
      loadKbHistory();
    } catch (e) {
      $("ytImportResult").textContent = "エラー: " + e.message;
    }
  });

  // ---------- 管理タブ：ファイルアップロード登録 ----------
  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }
  $("fileUploadBtn").addEventListener("click", async () => {
    const namespace = $("fileUploadNamespace").value.trim();
    const fileInput = $("fileUploadInput");
    const file = fileInput.files[0];
    if (!namespace || !file) { $("fileUploadResult").textContent = "namespaceとファイルを選択してください"; return; }
    $("fileUploadResult").textContent = "アップロード・変換中…（音声/動画は時間がかかることがあります）";
    try {
      const fileBase64 = await readFileAsBase64(file);
      const data = await api("/admin/kb/upload-doc", {
        namespace,
        fileBase64,
        mimeType: file.type || "application/octet-stream",
        fileName: file.name,
      });
      $("fileUploadResult").textContent = "完了: " + data.chunks + "チャンク登録" + (data.skipped > 0 ? "（" + data.skipped + "件スキップ）" : "");
      loadKbHistory();
    } catch (e) {
      $("fileUploadResult").textContent = "エラー: " + e.message;
    }
  });

  // ---------- 管理タブ：QA CSV一括登録 ----------
  $("qaCsvImportBtn").addEventListener("click", async () => {
    const namespace = $("qaCsvNamespace").value.trim();
    const csvText = $("qaCsvText").value;
    if (!namespace || !csvText.trim()) { $("qaCsvProgress").textContent = "namespaceとCSVを入力してください"; return; }
    const progressEl = $("qaCsvProgress");
    let opId = null, startIndex = 0, totalDocs = 0, totalChunks = 0;
    progressEl.textContent = "登録中…";
    try {
      while (true) {
        const body = { namespace, csvText, startIndex, batchSize: 5 };
        if (opId) body.opId = opId;
        const data = await api("/admin/kb/import-qa-csv", body);
        opId = data.opId;
        totalDocs += data.documents;
        totalChunks += data.chunks;
        progressEl.textContent = "進捗: " + data.processedRange[1] + "/" + data.totalRows + "（累計 " + totalDocs + "件・" + totalChunks + "チャンク）";
        if (data.nextIndex === null || data.nextIndex === undefined) break;
        startIndex = data.nextIndex;
      }
      progressEl.textContent = "完了: " + totalDocs + "件・" + totalChunks + "チャンク登録（opId: " + opId + "）";
      loadKbHistory();
    } catch (e) {
      progressEl.textContent = "エラー: " + e.message;
    }
  });

  // ---------- 管理タブ：KBロールバック ----------
  $("rollbackBtn").addEventListener("click", async () => {
    const opId = $("rollbackOpId").value.trim();
    if (!opId) { $("rollbackResult").textContent = "opIdを入力してください"; return; }
    if (!confirm("opId=" + opId + " で登録された内容をすべて削除します。元に戻せません。よろしいですか？")) return;
    $("rollbackResult").textContent = "実行中…";
    try {
      const data = await api("/admin/kb/rollback", { opId });
      $("rollbackResult").textContent = "完了: " + data.deletedFiles + "ファイル・" + data.deletedChunks + "チャンクを削除しました";
      loadKbHistory();
    } catch (e) {
      $("rollbackResult").textContent = "エラー: " + e.message;
    }
  });
})();
</script>
</body>
</html>`;
}
