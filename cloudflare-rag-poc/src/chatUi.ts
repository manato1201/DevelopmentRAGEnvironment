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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@200;400;600;700&display=swap" rel="stylesheet">
<style>
  /*
    2026-09-04: 添付のDalaスタイルガイドを元に配色・タイポグラフィを刷新。
    このアプリは情報密度の高い機能的なダッシュボード/チャットツールであり、Dala側は
    余白を大きく取ったマーケティングLPなので、トークン（配色・角丸・トラッキング）と
    「単色アクセント＋ゴーストボタン＋無シャドウのフラットな黒背景」という設計思想は
    忠実に踏襲しつつ、113pxの巨大見出しや粒子群のヒーロービジュアルはこのUIの用途に
    そぐわないため持ち込んでいない。またDalaは英字の大文字トラッキングラベルを多用するが
    本アプリの文言はほぼ日本語（大文字/小文字の概念が無い）のため、text-transform:uppercase
    は適用していない（トラッキング自体は日本語にも効くため、そちらは踏襲）。
    フォームや管理画面のテーブルはDala本来の「枠線ゼロ」を厳密に適用すると実用上
    見分けが付かなくなるため、input/テーブル行の区切りだけは低コントラストな1pxの
    hairlineを残している（可読性・操作性を優先した意図的な逸脱）。
  */
  :root {
    color-scheme: dark;
    --bg: #000000; --panel: #0c0c0e; --border: #242429;
    --text: #ffffff; --muted: #9a9a9a; --muted2: #bdbdbd;
    --accent: #8052ff; --highlight: #ffb829; --teal: #15846e;
    --user-bubble: #130f22; --assistant-bubble: transparent;
    --good: #15846e; --bad: #ff6f5e;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #ffffff; --panel: #f7f5ff; --border: #e4e1ea;
      --text: #14121a; --muted: #6b6470; --muted2: #857e8c;
      --accent: #6a3ef0; --highlight: #b8790f; --teal: #0f6656;
      --user-bubble: #efe9ff; --assistant-bubble: transparent;
      --good: #0f6656; --bad: #d94f3f;
    }
  }
  * { box-sizing: border-box; }
  html, body { overflow-x: hidden; max-width: 100%; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: "Inter", -apple-system, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
    display: flex; flex-direction: column; height: 100vh;
  }
  header { border-bottom: 1px solid var(--border); padding: .7rem 1.2rem; }
  .header-row { display: flex; align-items: center; gap: .8rem; flex-wrap: wrap; margin-bottom: .5rem; }
  header h1 {
    font-size: 1.05rem; font-weight: 600; margin: 0; white-space: nowrap; letter-spacing: -.01em;
    display: flex; align-items: center; gap: .5rem;
  }
  header h1::before {
    content: ""; display: inline-block; width: 9px; height: 9px;
    background: var(--accent); clip-path: polygon(50% 0%, 0% 100%, 100% 100%);
  }
  header input[type="password"], header select, header input[type="text"], header input[type="number"] {
    background: var(--panel); border: 1px solid var(--border); color: var(--text);
    border-radius: 10px; padding: .45rem .7rem; font-size: .85rem; font-family: inherit;
  }
  header input[type="password"] { flex: 1; min-width: 160px; }
  header input:focus, header select:focus { outline: none; border-color: var(--accent); }
  header button, .btn {
    background: none; border: none; color: var(--muted);
    border-radius: 999px; padding: .45rem .9rem; font-size: .85rem; font-family: inherit;
    font-weight: 600; cursor: pointer; transition: color .15s ease;
  }
  header button:hover, .btn:hover { color: var(--text); }
  .btn.primary { background: var(--accent); color: #fff; }
  .btn.primary:hover { color: #fff; opacity: .88; }
  .btn.danger { color: var(--bad); }
  .btn:disabled { opacity: .4; cursor: default; }
  nav.tabs { display: flex; gap: .2rem; }
  nav.tabs button {
    background: none; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    color: var(--muted); padding: .5rem .9rem; font-size: .88rem; font-weight: 600; cursor: pointer;
  }
  nav.tabs button.active { color: var(--accent); border-bottom-color: var(--accent); }

  .tabpanel { display: none; flex: 1; min-height: 0; flex-direction: column; }
  .tabpanel.active { display: flex; }

  /* APIキー未入力/未認証の間は機能を一切見せない（2026-08-29追加）。
     nav.tabsとtabpanelだけを隠し、header自体（APIキー入力欄）は隠さない
     ——そうしないとキーを入力する手段自体が消えてしまうため。 */
  body.locked nav.tabs, body.locked .tabpanel { display: none !important; }
  #authGate { display: none; padding: 3rem 1rem; text-align: center; color: var(--muted); font-size: 1rem; margin: 0; }
  body.locked #authGate { display: block; }
  nav.tabs button[data-tab="admin"].hidden-tab { display: none; }

  #messages { flex: 1; overflow-y: auto; padding: 1.2rem; max-width: 860px; margin: 0 auto; width: 100%; }
  .msg { margin-bottom: 1.1rem; max-width: 90%; }
  .msg.user { margin-left: auto; }
  .msg .bubble { padding: .7rem 1rem; border-radius: 18px; font-size: .92rem; line-height: 1.6; white-space: pre-wrap; }
  .msg.user .bubble { background: var(--user-bubble); }
  .msg.assistant .bubble { background: var(--assistant-bubble); padding-left: 0; padding-right: 0; }
  .meta { display: flex; align-items: center; gap: .6rem; margin-top: .4rem; font-size: .78rem; color: var(--muted); flex-wrap: wrap; }
  .extraction { padding: .1rem .55rem; border-radius: 999px; border: 1px solid var(--border); }
  .extraction.low { color: var(--bad); }
  .extraction.high { color: var(--teal); }
  .rate-btn { background: none; border: none; border-radius: 999px; cursor: pointer; color: var(--muted); padding: .15rem .5rem; font-family: inherit; }
  .rate-btn:hover { color: var(--text); }
  .rate-btn.active-up { color: var(--teal); }
  .rate-btn.active-down { color: var(--bad); }
  .rate-btn.active-pin { color: var(--highlight); }
  details.sources { margin-top: .5rem; font-size: .8rem; color: var(--muted); }
  details.sources summary { cursor: pointer; }
  details.sources ul { margin: .4rem 0 0; padding-left: 1.2rem; }
  details.sources li { margin-bottom: .3rem; }
  .source-composition { margin: .5rem 0; }
  .composition-title { font-size: .72rem; color: var(--muted); margin-bottom: .25rem; }
  .composition-bar { display: flex; height: 6px; border-radius: 999px; overflow: hidden; background: var(--border); }
  .composition-bar span { height: 100%; }
  .composition-legend { display: flex; flex-wrap: wrap; gap: .5rem .8rem; margin-top: .35rem; font-size: .72rem; }
  .composition-legend .item { display: inline-flex; align-items: center; gap: .3rem; }
  .composition-legend .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .ns-pill { display: inline-block; padding: 0 .5rem; border-radius: 999px; font-size: .7rem; font-weight: 600; color: #14121a; }
  .score-pct { font-size: .72rem; color: var(--muted); }
  .cited-badge { font-size: .7rem; padding: 0 .5rem; border-radius: 999px; border: 1px solid var(--border); }
  .cited-badge.cited { color: var(--teal); }
  .cited-badge.uncited { color: var(--muted); }
  .citation-link { color: var(--highlight); cursor: pointer; text-decoration: underline; }
  .citation-highlight {
    background: var(--accent); color: #fff; border-radius: 4px;
    transition: background 1.5s ease, box-shadow 1.5s ease;
    box-shadow: 0 0 0 3px var(--accent);
  }
  /* トースト通知（2026-09-09追加）: alert()呼び出しの置き換え。既存のexportBtnの
     「コピーしました」的な簡易フィードバックをこの1コンポーネントに集約する。 */
  #toastStack {
    position: fixed; bottom: 1.2rem; right: 1.2rem;
    display: flex; flex-direction: column; gap: .5rem; z-index: 999;
  }
  .toast {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: .6rem 1rem; font-size: .82rem; color: var(--text);
    opacity: 0; transform: translateY(8px);
    transition: opacity .2s ease, transform .2s ease;
  }
  .toast.show { opacity: 1; transform: translateY(0); }
  .toast.error { border-color: var(--bad); color: var(--bad); }
  .toast.success { border-color: var(--teal); color: var(--teal); }
  /* ヘルスチェック結果の視覚化（2026-09-09追加）: セクション左端に健全度バーを出す。 */
  .section.health-ok { border-left: 3px solid var(--teal); padding-left: 1rem; }
  .section.health-warn { border-left: 3px solid var(--highlight); padding-left: 1rem; }
  .section.health-bad { border-left: 3px solid var(--bad); padding-left: 1rem; }
  #composer {
    border-top: 1px solid var(--border); padding: .8rem 1.2rem;
    display: flex; flex-direction: column; gap: .5rem; max-width: 860px; margin: 0 auto; width: 100%;
  }
  .composer-row { display: flex; gap: .6rem; }
  #composer textarea {
    flex: 1; resize: none; background: var(--panel); border: 1px solid var(--border); color: var(--text);
    border-radius: 18px; padding: .65rem .9rem; font-size: .92rem; font-family: inherit; min-height: 2.6rem; max-height: 8rem;
  }
  #composer textarea:focus { outline: none; border-color: var(--accent); }
  #composer button { background: var(--accent); border: none; color: #fff; border-radius: 999px; padding: 0 1.3rem; font-size: .9rem; font-weight: 600; font-family: inherit; cursor: pointer; }
  #composer button:disabled { opacity: .4; cursor: default; }
  .attach-btn {
    display: flex; align-items: center; justify-content: center; width: 2.6rem; min-width: 2.6rem;
    background: none; border: 1px solid var(--border); border-radius: 999px; cursor: pointer; font-size: 1.1rem; color: var(--muted);
  }
  .attach-btn:hover { color: var(--text); border-color: var(--muted); }
  .attach-preview { display: flex; align-items: center; gap: .5rem; font-size: .8rem; color: var(--muted); }
  .attach-preview button { background: none; border: none; color: var(--bad); cursor: pointer; font-size: .85rem; padding: 0; }
  #status { text-align: center; color: var(--muted); font-size: .8rem; padding: .3rem; }
  .error { color: var(--bad); }

  .pane-scroll { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 1.2rem; max-width: 960px; margin: 0 auto; width: 100%; }
  .section { border-bottom: 1px solid var(--border); padding: 0 0 1.6rem; margin-bottom: 1.6rem; max-width: 100%; }
  .section:last-child { border-bottom: none; }
  .section h2 { font-size: 1rem; font-weight: 600; margin: 0 0 .9rem; letter-spacing: -.01em; }
  .field-row { display: flex; gap: .6rem; flex-wrap: wrap; margin-bottom: .6rem; align-items: center; }
  .field-row label { font-size: .78rem; color: var(--muted); min-width: 110px; }
  .field-row input[type="text"], .field-row input[type="number"] {
    flex: 1; min-width: 160px; background: var(--panel); border: 1px solid var(--border); color: var(--text);
    border-radius: 10px; padding: .45rem .7rem; font-size: .85rem; font-family: inherit;
  }
  .field-row input:focus { outline: none; border-color: var(--accent); }
  .checks { display: flex; gap: .5rem; flex-wrap: wrap; }
  .checks label { display: flex; align-items: center; gap: .3rem; font-size: .8rem; background: var(--panel); border: 1px solid var(--border); border-radius: 999px; padding: .3rem .7rem; }
  .table-scroll { overflow-x: auto; max-width: 100%; }
  table.admin-table { width: 100%; border-collapse: collapse; font-size: .82rem; table-layout: fixed; }
  table.admin-table th, table.admin-table td { text-align: left; padding: .5rem .5rem; border-bottom: 1px solid var(--border); word-break: break-all; }
  table.admin-table th { color: var(--muted); font-weight: 600; font-size: .72rem; letter-spacing: .02em; }
  .keybox { background: var(--panel); border: 1px solid var(--teal); border-radius: 12px; padding: .6rem .8rem; font-family: monospace; font-size: .85rem; word-break: break-all; margin-top: .5rem; }
  .keybox-row { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin-top: .35rem; }
  .keybox-row code { word-break: break-all; }
  .hint { color: var(--muted); font-size: .78rem; margin: .3rem 0 0; }
  #kbSyncProgress { white-space: pre-line; }
  #myBudget { white-space: nowrap; display: inline-flex; align-items: center; }
  .budget-low { color: var(--bad); font-weight: 600; }
  .radial-progress { vertical-align: middle; margin-right: .2rem; }

  #graphContainer { flex: 1; position: relative; overflow: hidden; background: var(--bg); }
  #graphContainer canvas { display: block; }
  .graph-toolbar { display: flex; gap: .6rem; align-items: center; padding: .6rem 1.2rem; border-bottom: 1px solid var(--border); font-size: .82rem; color: var(--muted); }
  #graphDetail {
    position: absolute; top: .8rem; right: .8rem; width: 260px; max-height: calc(100% - 1.6rem);
    overflow-y: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
    padding: .8rem 1rem; font-size: .8rem; display: none;
  }
  #graphDetail.visible { display: block; }
  #graphDetail h3 { font-size: .88rem; margin: 0 0 .4rem; word-break: break-word; }
  #graphDetail .ns { color: var(--muted); margin-bottom: .5rem; }
  #graphDetail ul { margin: .3rem 0 0; padding-left: 1.1rem; }
  #graphDetail li { margin-bottom: .2rem; word-break: break-word; }
  #graphDetail .close-btn { position: absolute; top: .5rem; right: .6rem; background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1rem; }

  #graphControls {
    position: absolute; top: .8rem; left: .8rem; width: 220px; max-height: calc(100% - 1.6rem);
    overflow-y: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
    padding: .8rem 1rem; font-size: .78rem;
  }
  #graphControls h4 { font-size: .8rem; margin: 0 0 .4rem; color: var(--muted); }
  #graphControls .slider-row { margin-bottom: .8rem; }
  #graphControls .slider-row label { display: flex; justify-content: space-between; color: var(--muted); margin-bottom: .2rem; }
  #graphControls input[type="range"] { width: 100%; accent-color: var(--accent); }
  #graphPlayPause { width: 100%; margin-bottom: .8rem; }
  #graphLegend { list-style: none; margin: 0; padding: 0; }
  #graphLegend li { display: flex; align-items: center; gap: .4rem; padding: .2rem 0; cursor: pointer; }
  #graphLegend .swatch { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  #graphLegend .ns-label { flex: 1; word-break: break-all; }
  #graphLegend .ns-count { color: var(--muted); }

  .usage-chart-wrap { overflow-x: auto; }
  #usageChart { display: block; }
  .donut-cell { display: flex; align-items: center; gap: .5rem; }

  /* チャット空状態のヒーロービジュアル（2026-09-04追加）。まだ何も質問していない間だけ、
     このユーザーが実際にアクセスできるナレッジベースのノードを小さな三角形の粒子群として
     アンビエント表示する（Dalaスタイルガイドの「粒子群」モチーフを、装飾ではなく
     実データで表現したもの）。最初の質問を送った時点で#messagesに切り替える。 */
  #chatHero { flex: 1; display: none; min-height: 0; width: 100%; }
  #tab-chat.chat-empty #chatHero { display: block; }
  #tab-chat.chat-empty #messages { display: none; }
</style>
</head>
<body class="locked">

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
    <span id="myBudget" class="hint" title="自分のAPIキーのトークン予算残量"></span>
  </div>
  <nav class="tabs">
    <button data-tab="chat" class="active">チャット</button>
    <button data-tab="graph">グラフ</button>
    <button data-tab="history">履歴</button>
    <button data-tab="pinned">お気に入り</button>
    <button data-tab="admin">管理</button>
  </nav>
</header>

<div id="authGate" class="hint">APIキーを入力してください</div>

<!-- チャットタブ -->
<div class="tabpanel active" id="tab-chat">
  <div class="graph-toolbar"><button class="btn" id="exportSessionBtn">会話全体をエクスポート</button></div>
  <canvas id="chatHero"></canvas>
  <div id="messages"></div>
  <div id="status"></div>
  <div id="composer">
    <div id="imageAttachPreview" class="attach-preview" style="display:none;"></div>
    <div class="composer-row">
      <label class="attach-btn" title="画像を添付する（VLM入力。8MBまで、検索には使わず最終回答生成時にだけ渡す）">📎<input type="file" id="imageAttachInput" accept="image/*" style="display:none;"></label>
      <textarea id="input" placeholder="質問を入力（Enterで送信、Shift+Enterで改行）" rows="1"></textarea>
      <button id="send">送信</button>
    </div>
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

<!-- お気に入りタブ -->
<div class="tabpanel" id="tab-pinned">
  <div class="pane-scroll" id="pinnedPane">
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
      <div class="field-row"><label><input type="checkbox" id="kbNotifyErrorOnly" style="width:auto;"> Slack通知はエラーがあった時だけ</label></div>
      <div style="margin-top:.8rem;">
        <button class="btn primary" id="kbSyncNotionBtn">Notion同期を実行</button>
        <button class="btn primary" id="kbSyncDriveBtn">Drive同期を実行</button>
        <button class="btn" id="kbRetryFailedBtn" disabled>失敗ファイルだけ再同期</button>
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
      <h2>FAQ単発登録</h2>
      <p class="hint">質問と回答を1件だけ登録します。まとめて登録したい場合は下のQA CSV一括登録を使ってください。</p>
      <div class="field-row"><label>namespace</label><input type="text" id="faqNamespace" placeholder="例: shared:tool_docs"></div>
      <div class="field-row"><label>質問</label><input type="text" id="faqQuestion" placeholder="例: HyDEとは何ですか？"></div>
      <div class="field-row"><label>回答</label><input type="text" id="faqAnswer" placeholder="例: 仮の回答を先に生成してから検索する手法です"></div>
      <label style="display:flex; align-items:center; gap:.4rem; margin:.4rem 0;"><input type="checkbox" id="faqAlsoNotion"> このnamespaceの同期先Notion DBにもページを作成する（namespaceにNotion DB設定が必要）</label>
      <button class="btn primary" id="faqAddBtn">登録</button>
      <div id="faqAddResult" class="hint"></div>
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

<div id="toastStack"></div>

<script>
(function () {
  const $ = (id) => document.getElementById(id);

  // トースト通知（2026-09-09追加）: alert()はUIをブロックし既存のダークテーマとも
  // 視覚的に統一感がなかったため、この1関数に集約してalert()呼び出しを置き換える。
  // #toastStackは上のHTMLに常設しているが、念のためfallbackも用意しておく。
  function createToastStack() {
    const stack = document.createElement("div");
    stack.id = "toastStack";
    document.body.appendChild(stack);
    return stack;
  }
  function showToast(message, kind) {
    const stack = $("toastStack") || createToastStack();
    const toast = document.createElement("div");
    toast.className = "toast " + (kind || "");
    toast.textContent = message;
    stack.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));
    setTimeout(() => {
      toast.classList.remove("show");
      toast.addEventListener("transitionend", () => toast.remove(), { once: true });
    }, 3200);
  }
  const apiKeyEl = $("apiKey");
  const levelEl = $("level");
  const namespaceFocusEl = $("namespaceFocus");

  apiKeyEl.value = localStorage.getItem("ragPocApiKey") || "";
  // "change"（フォーカスが外れて初めて発火）→"input"（キー入力・貼り付けで発火）と
  // 2回直したが、それでも直らなかった。ブラウザのパスワードマネージャー/自動入力が
  // 値をプログラム的にセットする場合、多くの実装でinput/changeどちらのイベントも
  // 一切発火しないことが知られている（実機のスクリーンショットに🔑パスワード
  // マネージャーアイコンが写っており、これが実際の原因だった可能性が高い）。
  // イベントに一切依存せず、値そのものを短い間隔でポーリングして変化を検出する
  // 方式に変更する。これなら自動入力・拡張機能経由の入力を含め、値がどう
  // セットされても確実に検出できる（2026-08-31）。
  let lastSeenApiKey = apiKeyEl.value.trim();
  setInterval(() => {
    const current = apiKeyEl.value.trim();
    if (current === lastSeenApiKey) return;
    lastSeenApiKey = current;
    localStorage.setItem("ragPocApiKey", current);
    loadNamespaceFocus();
  }, 600);

  // APIキー入力前は機能を一切見せない・管理者以外には管理タブを見せない（2026-08-29追加）。
  // 実際の権限チェックはサーバー側の各/admin/*エンドポイントのrequireAdmin()が唯一の正で
  // あり、これはあくまでUIの見た目を整えるためのもの（隠しているだけのタブを直接叩かれても
  // サーバー側で弾かれる）。document.querySelectorを直接使い、後方で宣言されるtabButtons等
  // に依存しない自己完結な実装にしている。
  // messageは省略可（省略時はゲート文言を変更しない）。以前はキー未入力時も無効な
  // キーが拒否された場合も全く同じ「APIキーを入力してください」のままで、ユーザーから
  // 見ると「入力しても何も起きない」ようにしか見えなかった（実機報告、2026-08-31）。
  // 状態ごとに違う文言を出すことで、少なくとも何が起きているかは分かるようにする。
  function setAuthGate(unlocked, role, message) {
    document.body.classList.toggle("locked", !unlocked);
    if (message !== undefined) {
      const gate = document.getElementById("authGate");
      if (gate) gate.textContent = message;
    }
    const adminBtn = document.querySelector('nav.tabs button[data-tab="admin"]');
    if (!adminBtn) return;
    const isAdmin = role === "admin";
    adminBtn.classList.toggle("hidden-tab", !isAdmin);
    if (!isAdmin && adminBtn.classList.contains("active")) {
      // 管理タブを開いたまま非管理者キーに切り替えられた場合はチャットタブへ退避する
      adminBtn.classList.remove("active");
      document.querySelectorAll(".tabpanel").forEach((p) => p.classList.remove("active"));
      const chatBtn = document.querySelector('nav.tabs button[data-tab="chat"]');
      if (chatBtn) chatBtn.classList.add("active");
      const chatPanel = document.getElementById("tab-chat");
      if (chatPanel) chatPanel.classList.add("active");
    }
  }

  // Cloudflareエッジ側の一時的なエラー（503等）やレスポンスがHTMLになるケースは、
  // 実際には数秒待って再試行すると成功することが多い一過性の障害であることが多い。
  // 毎回ユーザーに手動でbatchSizeを下げて再試行させるのではなく、まず自動で
  // 数回リトライしてから諦めるようにした（2026-08-27）。
  const RETRYABLE_STATUS = new Set([502, 503, 504]);
  async function apiOnce(path, body) {
    const res = await fetch(path, {
      method: "POST",
      // 空かどうかの判定は全箇所.trim()しているのに、実際にサーバーへ送る値だけ
      // trimしていなかった。コピー元によっては前後に改行/スペースが混ざることがあり
      // （見た目は同じキーに見える）、その場合ここだけ生の値を送るせいでサーバー側の
      // キー照合が一致せず認証が通らない、という「入力しても何も起きない」不具合の
      // 実質的な原因だったと考えられる（2026-08-31）。
      headers: { "Authorization": "Bearer " + apiKeyEl.value.trim(), "Content-Type": "application/json" },
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
        // 同期はbatchSize=1固定のため「batchSizeを下げて」という助言はもう成立しない
        // （2026-09-04、CPU時間制限引き上げで対処したため文言も更新）。
        e.message += "（自動再試行しましたが失敗しました。しばらく時間をおいて再試行するか、失敗したファイルだけ再同期を試してください）";
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
    if (!apiKeyEl.value.trim()) { setAuthGate(false, null, "APIキーを入力してください"); return; }
    setAuthGate(false, null, "APIキーを確認中…");
    const prevValue = namespaceFocusEl.value;
    try {
      const data = await api("/me/namespaces", {});
      setAuthGate(true, data.role);
      namespaceFocusEl.innerHTML = '<option value="">🌐 全DB横断検索</option>';
      data.namespaces.slice().sort().forEach((ns) => {
        const opt = document.createElement("option");
        opt.value = ns;
        opt.textContent = namespaceLabel(ns);
        namespaceFocusEl.appendChild(opt);
      });
      if (data.namespaces.includes(prevValue)) namespaceFocusEl.value = prevValue;
      loadMyBudget();
      loadChatHero();
    } catch (e) {
      // APIキーが無効、またはネットワークエラー。理由が分かるようゲートの文言に出す
      // （以前はここも無言で「APIキーを入力してください」に戻していたため、
      // 「入力しても何も起きない」ように見えていた）。
      setAuthGate(false, null, "認証に失敗しました: " + e.message);
    }
  }

  // トークン予算のパーセンテージをSVG円環ゲージとして描画する（2026-09-09追加）。
  // 既存コードはXSS対策としてtextContent/appendChildを徹底しinnerHTMLをほぼ
  // 使っていないため、文字列結合+innerHTMLではなくSVG要素をDOM APIで直接組み立てる。
  function budgetRadialSvg(pct, isLow) {
    const r = 8, c = 2 * Math.PI * r;
    const clamped = Math.max(0, Math.min(100, pct));
    const offset = c * (1 - clamped / 100);
    const color = isLow ? "var(--bad)" : "var(--accent)";
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", "20");
    svg.setAttribute("height", "20");
    svg.setAttribute("viewBox", "0 0 20 20");
    svg.setAttribute("class", "radial-progress");
    const track = document.createElementNS(NS, "circle");
    track.setAttribute("cx", "10");
    track.setAttribute("cy", "10");
    track.setAttribute("r", String(r));
    track.setAttribute("fill", "none");
    track.setAttribute("stroke", "var(--border)");
    track.setAttribute("stroke-width", "2");
    const fg = document.createElementNS(NS, "circle");
    fg.setAttribute("cx", "10");
    fg.setAttribute("cy", "10");
    fg.setAttribute("r", String(r));
    fg.setAttribute("fill", "none");
    fg.setAttribute("stroke", color);
    fg.setAttribute("stroke-width", "2");
    fg.setAttribute("stroke-dasharray", String(c));
    fg.setAttribute("stroke-dashoffset", String(offset));
    fg.setAttribute("stroke-linecap", "round");
    fg.setAttribute("transform", "rotate(-90 10 10)");
    svg.appendChild(track);
    svg.appendChild(fg);
    return svg;
  }

  // 自分のAPIキーのトークン予算残量を表示する（2026-09-04追加）。従来は管理者しか
  // 使用量を見れず、一般ユーザーはBudgetExceededError（429）に当たって初めて上限の
  // 存在を知る状態だった。無制限（予算レコード無し）の場合は何も表示しない。
  async function loadMyBudget() {
    const el = $("myBudget");
    el.innerHTML = "";
    try {
      const data = await api("/me/budget", {});
      const entries = [["RAG", data.rag], ["Claude", data.claude]].filter(([, b]) => b.limit != null);
      if (entries.length === 0) return; // 予算未設定（無制限）のキーは何も表示しない
      const titleLines = [];
      entries.forEach(([label, b], i) => {
        if (i > 0) el.appendChild(document.createTextNode(" ／ "));
        const pct = b.limit > 0 ? Math.round((100 * b.remaining) / b.limit) : 0;
        const isLow = pct <= 10;
        el.appendChild(budgetRadialSvg(pct, isLow));
        const span = document.createElement("span");
        span.className = isLow ? "budget-low" : "";
        span.textContent = label + " 残り" + pct + "%";
        el.appendChild(span);
        titleLines.push(label + ": " + b.used.toLocaleString() + " / " + b.limit.toLocaleString() + " 使用");
      });
      el.title = titleLines.join("\\n");
    } catch {
      el.innerHTML = "";
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
      if (btn.dataset.tab === "pinned") loadPinned();
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

  // 現在のセッション内でのQ&A履歴（「会話全体をエクスポート」用、2026-09-04追加）。
  // 履歴タブ/お気に入りタブから読み込んだ過去の会話はここには含めない
  // （今このタブで交わした会話をまとめてエクスポートする、という用途のため）。
  const sessionLog = [];

  // ---------- チャット空状態のヒーロービジュアル ----------
  // まだ質問していない間だけ、このユーザーが実際にアクセスできるナレッジベースの
  // ノードを小さな三角形の粒子群としてアンビエント表示する（2026-09-04追加。
  // Dalaスタイルガイドの「粒子群」モチーフを、ダミーの装飾ではなく実データ
  // （/graphの結果）で表現したもの）。namespace色はグラフ/出典表示と共通のnsColor()を使う。
  let heroAnimId = null;
  let heroResizeHandler = null;

  async function loadChatHero() {
    if (heroAnimId !== null) return; // 既に開始済み（タブ切替のたびに再認証されても二重開始しない）
    try {
      const data = await api("/graph", { maxNodes: 150 });
      if (!data.nodes || data.nodes.length === 0) return; // ノードが無ければ何も出さない（空欄のまま）
      // クラス付与を先に行い、canvasをdisplay:blockにしてからサイズを測る（startHeroAnimation
      // 内のresize()はgetBoundingClientRect()でサイズを取るため、display:noneのままだと
      // 0x0で確定してしまい何も描画されない不具合があった。2026-09-04修正）。
      $("tab-chat").classList.add("chat-empty");
      startHeroAnimation(data.nodes);
    } catch {
      // 背景演出はあくまで付加価値なので、失敗しても機能には影響させない
    }
  }

  function stopChatHero() {
    $("tab-chat").classList.remove("chat-empty");
    if (heroAnimId !== null) { cancelAnimationFrame(heroAnimId); heroAnimId = null; }
    if (heroResizeHandler) { window.removeEventListener("resize", heroResizeHandler); heroResizeHandler = null; }
  }

  function startHeroAnimation(nodes) {
    const canvas = $("chatHero");
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    function resize() {
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    heroResizeHandler = resize;
    window.addEventListener("resize", heroResizeHandler);

    const particles = nodes.map((n) => ({
      x: Math.random(),
      y: Math.random(),
      r: 3 + Math.random() * 5,
      color: nsColor(n.namespace),
      phase: Math.random() * Math.PI * 2,
      speed: 0.4 + Math.random() * 0.6,
      driftX: (Math.random() - 0.5) * 0.00012,
      driftY: (Math.random() - 0.5) * 0.00012,
    }));

    function drawTriangle(cx, cy, size, color, alpha) {
      ctx.beginPath();
      ctx.moveTo(cx, cy - size);
      ctx.lineTo(cx - size * 0.87, cy + size * 0.5);
      ctx.lineTo(cx + size * 0.87, cy + size * 0.5);
      ctx.closePath();
      ctx.strokeStyle = color;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }

    function frame(t) {
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      particles.forEach((p) => {
        p.x += p.driftX;
        p.y += p.driftY;
        if (p.x < 0) p.x += 1; else if (p.x > 1) p.x -= 1;
        if (p.y < 0) p.y += 1; else if (p.y > 1) p.y -= 1;
        const alpha = 0.25 + 0.35 * (0.5 + 0.5 * Math.sin(t * 0.0005 * p.speed + p.phase));
        drawTriangle(p.x * rect.width, p.y * rect.height, p.r, p.color, alpha);
      });
      ctx.globalAlpha = 1;
      heroAnimId = requestAnimationFrame(frame);
    }
    heroAnimId = requestAnimationFrame(frame);
  }

  function setStatus(text, isError) {
    statusEl.textContent = text || "";
    statusEl.className = isError ? "error" : "";
  }

  // 履歴/お気に入りタブでは、クエリ実行時に計算されたextractionRate/extractionDetailを
  // そのまま保持していないため、保存済みのsources（各s.cited）から同じ計算をやり直す
  // （query.tsのparseExtractionRate相当の計算をクライアント側で再現。2026-09-04、
  // 0%固定表示で出典バッジと矛盾していた不備を修正）。
  function computeExtraction(sources) {
    if (!sources || sources.length === 0) return { rate: 0, detail: "0/0" };
    const cited = sources.filter((s) => s.cited).length;
    return { rate: Math.round((100 * cited) / sources.length), detail: cited + "/" + sources.length };
  }

  // 管理タブの各テーブル行を安全に構築する（textContentで挿入するため、ファイル名や
  // 表示名などサーバー由来の未検証文字列が誤ってHTMLとして解釈されることがない。
  // 2026-09-04、innerHTML文字列結合で組み立てていた各テーブルをこれに統一）。
  function appendRow(tbody, values) {
    const tr = document.createElement("tr");
    values.forEach((v) => {
      const td = document.createElement("td");
      td.textContent = v;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
    return tr;
  }

  function extractionClass(rate) {
    if (rate >= 70) return "high";
    if (rate < 40) return "low";
    return "";
  }

  // 回答＋出典一覧をMarkdown文字列に組み立てる（コピー機能・共有用）。
  // 注意: このファイル全体が外側でTypeScriptの1つの大きなテンプレートリテラルに
  // 包まれているため、ここで改行エスケープをバックスラッシュ1個だけで書くと、外側の
  // コンパイラの時点で実際の改行文字に変換されてしまう。その結果ブラウザに配信される
  // スクリプト側ではダブルクォート文字列の途中に生の改行が入ることになり、
  // SyntaxErrorでスクリプト全体が起動不能になる（実機で発生・確認、2026-09-03。
  // このコメント自身も一度この書き方をして同じ壊れ方をしたため、コメント中でも
  // 改行エスケープの実例を直接書かないようにしている）。ブラウザ側JSに改行エスケープを
  // 文字として残すには、ここでは常にバックスラッシュを2個重ねて書く必要がある。
  function buildMarkdownExport(question, answer, sources) {
    let md = "";
    if (question) md += "## 質問\\n\\n" + question + "\\n\\n";
    md += "## 回答\\n\\n" + answer + "\\n";
    if (sources && sources.length > 0) {
      md += "\\n## 出典\\n\\n";
      sources.forEach((s, i) => {
        const cited = s.cited ? "引用" : "未引用";
        md += "" + (i + 1) + ". " + s.file + "（" + s.namespace + "、" + cited + "）\\n";
      });
    }
    return md;
  }

  function renderAssistantMessage(container, question, answer, sources, extractionRate, extractionDetail, memoryId, existingRating, existingPinned) {
    const wrap = document.createElement("div");
    wrap.className = "msg assistant";

    // 出典一覧（この関数の下の方で構築）へのジャンプ先。回答文中の[n]をクリックした際に
    // 対応する<li>を開いてハイライトする（2026-09-04追加、citation-link参照）。
    let sourcesDetailsEl = null;
    const sourceLiRefs = [];
    function jumpToSource(n) {
      const li = sourceLiRefs[n - 1];
      if (!li) return;
      if (sourcesDetailsEl) sourcesDetailsEl.open = true;
      li.scrollIntoView({ behavior: "smooth", block: "nearest" });
      li.classList.add("citation-highlight");
      setTimeout(() => li.classList.remove("citation-highlight"), 1500);
    }

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    // 回答文中の[1]や[2]をクリック可能にし、出典一覧の該当行へジャンプできるようにする。
    // 引用番号以外の地の文はこれまで通りtextContent相当（テキストノード）のまま扱い、
    // モデル出力をHTMLとして解釈しない（XSS対策）。
    const citationRe = /\[(\d+)\]/g;
    let lastIndex = 0;
    let m;
    while ((m = citationRe.exec(answer)) !== null) {
      if (m.index > lastIndex) bubble.appendChild(document.createTextNode(answer.slice(lastIndex, m.index)));
      const n = Number(m[1]);
      if (sources && n >= 1 && n <= sources.length) {
        const link = document.createElement("span");
        link.className = "citation-link";
        link.textContent = m[0];
        link.onclick = () => jumpToSource(n);
        bubble.appendChild(link);
      } else {
        bubble.appendChild(document.createTextNode(m[0]));
      }
      lastIndex = m.index + m[0].length;
    }
    bubble.appendChild(document.createTextNode(answer.slice(lastIndex)));
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

      // お気に入り登録（2026-09-04追加）。ratingとは独立に「あとで見返したい」を残せるようにする。
      const pinBtn = document.createElement("button");
      pinBtn.className = "rate-btn" + (existingPinned ? " active-pin" : "");
      pinBtn.textContent = existingPinned ? "★お気に入り" : "☆お気に入り";
      pinBtn.onclick = () => togglePin(memoryId, !pinBtn.classList.contains("active-pin"), pinBtn);
      meta.appendChild(pinBtn);
    }

    // 出典付きの回答をそのままチームに共有したいことがあるため、Markdown形式で
    // クリップボードにコピーするボタンを用意する（2026-08-31）。
    const exportBtn = document.createElement("button");
    exportBtn.className = "rate-btn";
    exportBtn.textContent = "Markdownコピー";
    exportBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(buildMarkdownExport(question, answer, sources));
        exportBtn.textContent = "コピーしました";
      } catch {
        exportBtn.textContent = "コピー失敗";
      }
      setTimeout(() => { exportBtn.textContent = "Markdownコピー"; }, 2000);
    });
    meta.appendChild(exportBtn);
    wrap.appendChild(meta);

    if (sources && sources.length > 0) {
      const details = document.createElement("details");
      sourcesDetailsEl = details;
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
        sourceLiRefs[i] = li;
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
      showToast("評価の送信に失敗しました: " + e.message, "error");
    }
  }

  async function togglePin(memoryId, pinned, btn) {
    try {
      await api("/memory/pin", { id: memoryId, pinned });
      btn.classList.toggle("active-pin", pinned);
      btn.textContent = pinned ? "★お気に入り" : "☆お気に入り";
    } catch (e) {
      showToast("お気に入り登録に失敗しました: " + e.message, "error");
    }
  }

  // ---------- 質問への画像添付（VLM入力。既存GASのimage:{mimeType,data}と同一契約） ----------
  let pendingImage = null; // { mimeType, data(base64) } | null
  const imageAttachInput = $("imageAttachInput");
  const imageAttachPreview = $("imageAttachPreview");
  const MAX_ATTACH_IMAGE_BYTES = 8 * 1024 * 1024;

  function clearPendingImage() {
    pendingImage = null;
    imageAttachInput.value = "";
    imageAttachPreview.style.display = "none";
    imageAttachPreview.innerHTML = "";
  }
  imageAttachInput.addEventListener("change", async () => {
    const file = imageAttachInput.files[0];
    if (!file) return;
    if (file.size > MAX_ATTACH_IMAGE_BYTES) {
      setStatus("添付画像が大きすぎます（上限8MB）", true);
      imageAttachInput.value = "";
      return;
    }
    const data = await readFileAsBase64(file);
    pendingImage = { mimeType: file.type || "image/png", data };
    imageAttachPreview.style.display = "flex";
    imageAttachPreview.innerHTML = "";
    imageAttachPreview.appendChild(document.createTextNode("📎 " + file.name + " を添付中"));
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.textContent = "✕";
    clearBtn.addEventListener("click", clearPendingImage);
    imageAttachPreview.appendChild(clearBtn);
  });

  async function send() {
    const text = inputEl.value.trim();
    if (!text) return;
    if (!apiKeyEl.value.trim()) { setStatus("APIキーを入力してください", true); return; }
    const imageToSend = pendingImage;
    inputEl.value = "";
    inputEl.style.height = "auto";
    clearPendingImage();
    stopChatHero();
    renderUserMessage(messagesEl, text);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    sendBtn.disabled = true;
    setStatus("検索・回答生成中…");
    try {
      const focusNs = namespaceFocusEl.value;
      const data = await api("/query", { query: text, limit: 5, level: levelEl.value, namespaces: focusNs ? [focusNs] : undefined, image: imageToSend || undefined });
      renderAssistantMessage(messagesEl, text, data.answer, data.sources, data.extractionRate, data.extractionDetail, data.memoryId, null, false);
      sessionLog.push({ question: text, answer: data.answer, sources: data.sources });
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

  // 今のセッションで交わした一問一答をまとめて1つのMarkdownファイルとしてダウンロードする
  // （2026-09-04追加。1問1答単位のコピーは既にあるが、会議後の記録用途などまとめて
  // 保存したい場面には向かなかった）。
  $("exportSessionBtn").addEventListener("click", () => {
    if (sessionLog.length === 0) { showToast("まだ会話がありません", "error"); return; }
    const md = sessionLog.map((entry) => buildMarkdownExport(entry.question, entry.answer, entry.sources)).join("\\n---\\n\\n");
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "rag-chat-" + new Date().toISOString().slice(0, 19).replace(/:/g, "-") + ".md";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });

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
        const ext = computeExtraction(entry.sources);
        renderAssistantMessage(pane, entry.query, entry.answer, entry.sources, ext.rate, ext.detail, entry.id, entry.rating, entry.pinned);
      });
    } catch (e) {
      pane.innerHTML = '<p class="hint error">読み込みに失敗しました: ' + e.message + '</p>';
    }
  }

  // ---------- お気に入りタブ ----------
  async function loadPinned() {
    const pane = $("pinnedPane");
    if (!apiKeyEl.value.trim()) { pane.innerHTML = '<p class="hint error">APIキーを入力してください</p>'; return; }
    pane.innerHTML = '<p class="hint">読み込み中…</p>';
    try {
      const data = await api("/memory/pinned", {});
      pane.innerHTML = "";
      if (data.entries.length === 0) { pane.innerHTML = '<p class="hint">お気に入り登録した回答はまだありません</p>'; return; }
      data.entries.forEach((entry) => {
        renderUserMessage(pane, entry.query);
        const ext = computeExtraction(entry.sources);
        renderAssistantMessage(pane, entry.query, entry.answer, entry.sources, ext.rate, ext.detail, entry.id, entry.rating, entry.pinned);
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
  // ブランドカラー（violet/amber/teal）を先頭に置き、以降は同系統でまとめつつ多数の
  // namespaceでも見分けが付くよう広げた配色（2026-09-04、Dalaスタイル刷新に合わせて再選定）。
  const NS_PALETTE = ["#8052ff", "#ffb829", "#15846e", "#5b8def", "#e0555f", "#9b6fd0", "#3ec1c9", "#e0a03e", "#d64f8a", "#4fc9a5", "#8d99a6", "#c97a3d"];
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
      const data = await api("/graph", { maxNodes: 1000 });
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
    const accent = getComputedStyle(document.body).getPropertyValue("--accent").trim() || "#8052ff";
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
    const color = ratio > 0.9 ? (getComputedStyle(document.body).getPropertyValue("--bad").trim() || "#ff6f5e")
      : (getComputedStyle(document.body).getPropertyValue("--accent").trim() || "#8052ff");
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
        appendRow(tbody, [u.displayName || u.userId, u.queries, u.tokens]);
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
        const created = new Date(k.created_at * 1000).toLocaleString();
        const tr = appendRow(tbody, [k.display_name, k.role, k.rag_limit != null ? (k.rag_used + '/' + k.rag_limit) : '無制限']);
        const donutCell = document.createElement("td");
        tr.appendChild(donutCell);
        if (k.rag_limit != null) {
          const donutCanvas = document.createElement("canvas");
          donutCell.appendChild(donutCanvas);
          drawDonut(donutCanvas, k.rag_used, k.rag_limit);
        }
        const createdCell = document.createElement("td");
        createdCell.textContent = created;
        tr.appendChild(createdCell);
        const actionsCell = document.createElement("td");
        tr.appendChild(actionsCell);
        const delBtn = document.createElement("button");
        delBtn.className = "btn danger"; delBtn.textContent = "削除";
        delBtn.onclick = async () => {
          if (!confirm(k.display_name + " を削除しますか？")) return;
          try { await api("/admin/keys/delete", { userId: k.user_id }); loadKeys(); }
          catch (e) { showToast("削除に失敗しました: " + e.message, "error"); }
        };
        actionsCell.appendChild(delBtn);
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
    } catch (e) { showToast("作成に失敗しました: " + e.message, "error"); }
  });

  async function loadNamespaces() {
    const tbody = $("nsTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=5>読み込み中…</td></tr>";
    try {
      const data = await api("/admin/namespaces/list", {});
      tbody.innerHTML = "";
      data.namespaces.forEach((n) => {
        const tr = appendRow(tbody, [n.namespace_id, n.scope, n.owner_user_id || "-"]);
        const limitCell = document.createElement("td");
        tr.appendChild(limitCell);
        const actionsCell = document.createElement("td");
        tr.appendChild(actionsCell);
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
          } catch (e) { showToast("設定に失敗しました: " + e.message, "error"); }
        };
        limitCell.appendChild(limitInput);
        limitCell.appendChild(limitBtn);
        const delBtn = document.createElement("button");
        delBtn.className = "btn danger"; delBtn.textContent = "削除";
        delBtn.onclick = async () => {
          if (!confirm(n.namespace_id + " を削除しますか？")) return;
          try { await api("/admin/namespaces/delete", { namespaceId: n.namespace_id }); loadNamespaces(); }
          catch (e) { showToast("削除に失敗しました: " + e.message, "error"); }
        };
        actionsCell.appendChild(delBtn);
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
      showToast("同期元を設定しました", "success");
    } catch (e) { showToast("設定に失敗しました: " + e.message, "error"); }
  });

  // 直近の同期のopId/ソースを覚えておき、「失敗ファイルだけ再同期」ボタンから使う
  // （2026-09-04追加）。
  let lastSyncOpId = null;
  let lastSyncSource = null;

  // 「エラー時のみ通知」チェックボックスの状態はlocalStorageに覚えておき、次回開いた
  // ときも同じ設定のままにする（2026-09-04追加）。
  const notifyErrorOnlyEl = $("kbNotifyErrorOnly");
  try {
    notifyErrorOnlyEl.checked = localStorage.getItem("ragPocNotifyErrorOnly") === "1";
  } catch { /* localStorage不可の環境では既定（オフ）のまま */ }
  notifyErrorOnlyEl.addEventListener("change", () => {
    try { localStorage.setItem("ragPocNotifyErrorOnly", notifyErrorOnlyEl.checked ? "1" : "0"); } catch { /* noop */ }
  });

  async function runSync(endpoint, batchSize) {
    const namespace = $("kbNamespace").value.trim();
    if (!namespace) { showToast("namespaceを入力してください", "error"); return; }
    const source = endpoint.indexOf("notion") !== -1 ? "notion" : "drive";
    const progressEl = $("kbSyncProgress");
    const retryBtn = $("kbRetryFailedBtn");
    retryBtn.disabled = true;
    let opId = null, startIndex = 0, totalDocs = 0, totalChunks = 0, errorCount = 0;
    progressEl.textContent = "同期中…";
    try {
      while (true) {
        const body = { namespace, startIndex, batchSize, notifyOnErrorOnly: notifyErrorOnlyEl.checked };
        if (opId) body.opId = opId;
        const data = await api(endpoint, body);
        opId = data.opId;
        totalDocs += data.documents;
        totalChunks += data.chunks;
        (data.results || []).forEach((r) => { if (r.status === "error") errorCount++; });
        const total = data.totalPages ?? data.totalFiles ?? "?";
        const last = data.results && data.results.length > 0 ? data.results[data.results.length - 1] : null;
        const lastMark = last ? (last.status === "ok" ? "✅" : last.status === "skipped" ? "⏭️" : "⚠️") : "";
        const lastLine = last ? "\\n直前: " + lastMark + " " + last.file + "（" + last.detail + "）" : "";
        progressEl.textContent = "進捗: " + data.processedRange[1] + "/" + total + "（累計 " + totalDocs + "件・" + totalChunks + "チャンク）" + lastLine;
        if (data.nextIndex === null || data.nextIndex === undefined) break;
        startIndex = data.nextIndex;
      }
      const failNote = errorCount > 0 ? "（失敗 " + errorCount + "件）" : "";
      progressEl.textContent = "完了: " + totalDocs + "件・" + totalChunks + "チャンク登録" + failNote;
      lastSyncOpId = opId;
      lastSyncSource = source;
      retryBtn.disabled = errorCount === 0;
      loadKbHistory();
    } catch (e) {
      progressEl.textContent = "エラー: " + e.message;
      lastSyncOpId = opId;
      lastSyncSource = source;
      retryBtn.disabled = !opId;
    }
  }

  $("kbRetryFailedBtn").addEventListener("click", async () => {
    if (!lastSyncOpId || !lastSyncSource) return;
    const namespace = $("kbNamespace").value.trim();
    const progressEl = $("kbSyncProgress");
    const retryBtn = $("kbRetryFailedBtn");
    retryBtn.disabled = true;
    progressEl.textContent = "失敗ファイルを再同期中…";
    try {
      const data = await api("/admin/sync/" + lastSyncSource + "/retry-failed", { namespace, opId: lastSyncOpId });
      const remainingErrors = (data.results || []).filter((r) => r.status === "error").length;
      progressEl.textContent = "再同期完了: " + data.documents + "件・" + data.chunks + "チャンク登録" + (remainingErrors > 0 ? "（依然失敗 " + remainingErrors + "件）" : "");
      retryBtn.disabled = remainingErrors === 0;
      loadKbHistory();
    } catch (e) {
      progressEl.textContent = "エラー: " + e.message;
      retryBtn.disabled = false;
    }
  });
  // 当初Notionはテキストのみで変換が軽いためbatchSize=5にしていたが、ページ内の
  // チャンク数が多いとGemini埋め込みだけで1ページ100秒近くかかることがあり
  // （2026-08-29、PER_PAGE_TIMEOUT_MS引き上げの経緯参照）、5件×100秒では
  // 1リクエストが極端に長くなりうる。Drive側と同じくbatchSize=1にして
  // 1リクエストを短く保つ。
  $("kbSyncNotionBtn").addEventListener("click", () => runSync("/admin/sync/notion", 1));
  $("kbSyncDriveBtn").addEventListener("click", () => runSync("/admin/sync/drive", 1));

  async function loadKbHistory() {
    const tbody = $("kbHistoryTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=7>読み込み中…</td></tr>";
    try {
      const data = await api("/admin/kb/history", { limit: 30 });
      tbody.innerHTML = "";
      data.entries.forEach((e) => {
        const when = new Date(e.created_at * 1000).toLocaleString();
        // file/detailはDrive/Notion側の実データ（ファイル名・エラー詳細）に由来する未検証の
        // 文字列なので、appendRow経由でtextContent挿入する（2026-09-04、悪意あるHTMLタグを
        // 含むファイル名が管理画面でHTMLとして実行されるstored XSSの可能性を修正）。
        appendRow(tbody, [when, e.op_id, e.source, e.namespace_id, e.file || "-", e.status, e.detail || ""]);
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
        appendRow(tbody, [u.displayName || u.userId, u.total, u.good, u.bad]);
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
  // エッジライト（2026-09-09追加）: 結果に応じてセクション左端に健全度バーを表示する。
  const healthSection = $("healthCheckBtn").closest(".section");
  function setHealthEdgeLight(state) {
    healthSection.classList.remove("health-ok", "health-warn", "health-bad");
    if (state) healthSection.classList.add(state);
  }
  $("healthCheckBtn").addEventListener("click", async () => {
    $("healthCheckResult").textContent = "実行中…";
    try {
      const data = await api("/admin/health/check", {});
      if (data.issues.length === 0) {
        $("healthCheckResult").textContent = "問題は見つかりませんでした";
        setHealthEdgeLight("health-ok");
      } else {
        $("healthCheckResult").textContent = data.issues.map((i) => "[" + i.severity + "] " + i.message).join(" / ");
        const hasError = data.issues.some((i) => i.severity === "error");
        setHealthEdgeLight(hasError ? "health-bad" : "health-warn");
      }
    } catch (e) {
      $("healthCheckResult").textContent = "エラー: " + e.message;
      setHealthEdgeLight("health-bad");
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

  // ---------- 管理タブ：FAQ単発登録 ----------
  $("faqAddBtn").addEventListener("click", async () => {
    const namespace = $("faqNamespace").value.trim();
    const question = $("faqQuestion").value.trim();
    const answer = $("faqAnswer").value.trim();
    const alsoWriteToNotion = $("faqAlsoNotion").checked;
    const resultEl = $("faqAddResult");
    if (!namespace || !question || !answer) { resultEl.textContent = "namespace・質問・回答を入力してください"; return; }
    resultEl.textContent = "登録中…";
    try {
      const data = await api("/admin/kb/add-faq", { namespace, question, answer, alsoWriteToNotion });
      resultEl.textContent = "完了: " + data.chunks + "チャンク登録" + (data.notionPageId ? "（Notionページも作成: " + data.notionPageId + "）" : "");
      $("faqQuestion").value = "";
      $("faqAnswer").value = "";
      loadKbHistory();
    } catch (e) {
      resultEl.textContent = "エラー: " + e.message;
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
