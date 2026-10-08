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
  /* U6: テーマは data-theme="light|dark" で手動指定。未指定（自動）ならOS設定に追従する。 */
  @media (prefers-color-scheme: light) {
    :root:not([data-theme]) {
      color-scheme: light;
      --bg: #ffffff; --panel: #f7f5ff; --border: #e4e1ea;
      --text: #14121a; --muted: #6b6470; --muted2: #857e8c;
      --accent: #6a3ef0; --highlight: #b8790f; --teal: #0f6656;
      --user-bubble: #efe9ff; --assistant-bubble: transparent;
      --good: #0f6656; --bad: #d94f3f;
    }
  }
  :root[data-theme="light"] {
    color-scheme: light;
    --bg: #ffffff; --panel: #f7f5ff; --border: #e4e1ea;
    --text: #14121a; --muted: #6b6470; --muted2: #857e8c;
    --accent: #6a3ef0; --highlight: #b8790f; --teal: #0f6656;
    --user-bubble: #efe9ff; --assistant-bubble: transparent;
    --good: #0f6656; --bad: #d94f3f;
  }
  /* U1: 数字は等幅（桁揃え）。追加トークンは2つだけ。 */
  :root { --font-num: tabular-nums; --row-sub: var(--muted); }
  .score-pct, #myBudget, .kpi-card .kpi-value, .kpi-card .kpi-sub, .pager, .ns-count, .answer-foot { font-variant-numeric: var(--font-num); }
  .icon { width: 1em; height: 1em; vertical-align: -.15em; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
  .answer-foot { font-size: .74rem; color: var(--row-sub); margin-top: .3rem; }
  .empty-state { text-align: center; color: var(--muted); font-size: .88rem; padding: 1.2rem .5rem; }
  .empty-dots { display: inline-flex; gap: 6px; margin-top: .6rem; }
  .empty-dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--muted); animation: drift 2.4s ease-in-out infinite; }
  .empty-dots i:nth-child(2) { animation-delay: .4s; } .empty-dots i:nth-child(3) { animation-delay: .8s; }
  @keyframes drift { 0%,100% { transform: translateY(0); opacity: .4; } 50% { transform: translateY(-5px); opacity: 1; } }
  @media (prefers-reduced-motion: reduce) { .empty-dots i { animation: none; } }
  #themeToggle { white-space: nowrap; }
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
  /* 管理タブだけ.pane-scrollの960px中央寄せを解除する（2026-09-13追加）。
     履歴/お気に入り/チャットは読みやすさ重視の文章コンテンツなので960px幅の
     中央寄せが適切だが、管理タブはサイドバー+表という横に広いレイアウトのため、
     同じ制限をかけるとサイドバーが画面中央付近まで押し出され、表の表示領域も
     狭くなってしまう（実機報告：「中央の幅もっと広げてほしい」「サイドバーは
     左端くらいまで移動させて確保したい」）。 */
  .admin-pane-scroll { max-width: 1800px; margin: 0; }
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

  /* 権限の詳細化（2026-09-10追加）: editorロールには管理者専用セクションを一切見せない。
     実際の権限チェックは各/admin/*エンドポイント側（requireAdmin/requireKnowledgeEditor）が
     唯一の正であり、これはあくまでUIの見た目を整えるためのもの（既存のnav.tabs button
     [data-tab="admin"].hidden-tabと同じ方針）。 */
  /* !important: このクラスをボタン（display:inline-flex等）とサブパネル
     （.admin-subpanel.active { display:block }）の両方に使い回すため、要素ごとの
     既定表示指定に必ず勝つようにしておく（2026-09-10: サブナビ導入に伴う対策）。 */
  body[data-role="editor"] .admin-only-section { display: none !important; }
  .role-badge { display: inline-block; padding: .1rem .55rem; border-radius: 999px; font-size: .72rem; font-weight: 600; border: 1px solid var(--border); }
  .role-badge.admin { color: var(--accent); border-color: var(--accent); }
  .role-badge.editor { color: var(--teal); border-color: var(--teal); }
  .role-badge.member, .role-badge.guest { color: var(--muted); }
  .role-select { background: var(--panel); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: .2rem .4rem; font-size: .78rem; font-family: inherit; }

  /* 別プロジェクト管理コンソールのOverview/Billingページ（添付画像）を参考にしたKPIカード
     （2026-09-10追加）。既存のDala方針（枠線ゼロ・無シャドウ）は保ちつつ、hairlineの
     区切りだけを使った軽量なカードにしている。 */
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: .8rem; margin-bottom: 1.2rem; }
  .kpi-card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: .9rem 1rem; }
  .kpi-card .kpi-label { font-size: .74rem; color: var(--muted); margin-bottom: .3rem; }
  .kpi-card .kpi-value { font-size: 1.4rem; font-weight: 700; letter-spacing: -.01em; }
  .kpi-card .kpi-sub { font-size: .72rem; color: var(--muted); margin-top: .2rem; }

  /* 管理タブのサブナビ（2026-09-10追加、2026-09-11に横並びピルから左サイドバーへ変更）。
     「ユーザーによって見たいもの/見なくていいものが違う」というフィードバックを受け、
     従来1本の長いスクロールだった管理タブをガイド/Overview/ナレッジ登録/ユーザー・権限/
     namespace管理/利用状況・コスト/システムの7グループに分割した。グループ数が増え
     横並びピルだと窮屈になったため、GitHub/Slack/NotionのSettings画面と同じ「深い
     設定領域は左サイドバー」という構成に変更。トップレベルのnav.tabs（チャット/グラフ
     等）はチャット利用が主目的で項目数も少ないため、横並びのままにしている。 */
  /* 2026-09-13修正: .autorefresh-boxが.admin-subnavと並ぶ独立したフレックス
     アイテムになっており（.admin-layoutの直接の子）、意図した「サイドバーの下部」
     ではなく別カラムとして扱われ、結果としてコンテンツ側の幅を圧迫していた不具合の
     修正（実機報告：「サブメニューを左端にし、中央の情報を広く確保してください」）。
     サブナビと自動更新コントロールを.admin-sidebarという1つの縦積みコンテナに
     まとめ、.admin-layoutの子は「サイドバー1個・コンテンツ1個」の2つだけにした。
     これでサイドバーは常に左端の固定幅1カラムに収まり、コンテンツ側が残り幅を
     すべて使えるようになる。 */
  .admin-layout { display: flex; gap: 1.6rem; align-items: flex-start; }
  .admin-sidebar { display: flex; flex-direction: column; flex-shrink: 0; width: 168px; }
  .admin-subnav {
    display: flex; flex-direction: column; gap: .1rem;
    border-right: 1px solid var(--border); padding-right: 1rem;
  }
  .admin-subnav button {
    background: none; border: none; border-left: 2px solid transparent; border-radius: 0;
    color: var(--muted); padding: .55rem .7rem; font-size: .84rem; font-weight: 600; cursor: pointer;
    font-family: inherit; text-align: left; white-space: normal;
  }
  .admin-subnav button.active { color: var(--accent); border-left-color: var(--accent); background: var(--panel); border-radius: 0 8px 8px 0; }
  .admin-content { flex: 1; min-width: 0; }
  .admin-subpanel { display: none; }
  .admin-subpanel.active { display: block; }
  .autorefresh-box { display: flex; flex-direction: column; gap: .4rem; margin-top: 1rem; padding-top: .8rem; border-top: 1px solid var(--border); border-right: 1px solid var(--border); padding-right: 1rem; font-size: .8rem; color: var(--muted2); }
  .autorefresh-box label { display: flex; align-items: center; gap: .4rem; }
  /* 管理タブの中でだけ、狭い画面ではサイドバーを諦めて横並びに戻す（親ページ全体を
     レスポンシブ対応するのは大掛かりなため、この場所限定の妥協策）。 */
  @media (max-width: 720px) {
    .admin-layout { flex-direction: column; }
    .admin-sidebar { width: auto; }
    .admin-subnav { flex-direction: row; flex-wrap: wrap; border-right: none; border-bottom: 1px solid var(--border); padding-right: 0; padding-bottom: .5rem; }
    .admin-subnav button.active { border-left-color: transparent; border-bottom: 2px solid var(--accent); border-radius: 0; background: none; }
    .autorefresh-box { flex-direction: row; align-items: center; border-right: none; padding-right: 0; }
  }
  .guide-block { margin-bottom: 1.4rem; }
  .guide-block h3 { font-size: .88rem; font-weight: 600; margin: 0 0 .4rem; color: var(--text); }
  .guide-block p, .guide-block li { font-size: .82rem; color: var(--muted2); line-height: 1.7; }
  .guide-block ul { margin: .3rem 0; padding-left: 1.2rem; }
  .role-table { width: 100%; border-collapse: collapse; font-size: .8rem; margin-top: .4rem; }
  .role-table th, .role-table td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--border); }
  .role-table th { color: var(--muted); font-weight: 600; font-size: .72rem; }

  /* Overview/Knowledgeの2カラムミニリスト（別プロジェクト参考画像の"Plan Distribution"/
     "Top Agents by Token Usage"に相当、2026-09-10追加）。 */
  .overview-cols { display: flex; gap: 1.2rem; flex-wrap: wrap; margin-top: 1rem; }
  .overview-col { flex: 1; min-width: 220px; }
  .overview-col h3 { font-size: .82rem; font-weight: 600; margin: 0 0 .5rem; color: var(--text); }
  .mini-list { list-style: none; margin: 0; padding: 0; }
  .mini-list li { display: flex; justify-content: space-between; align-items: center; padding: .4rem 0; border-bottom: 1px solid var(--border); font-size: .82rem; }
  .mini-list li:last-child { border-bottom: none; }
  .mini-list .mini-label { display: flex; align-items: center; gap: .5rem; color: var(--muted2); }
  .mini-list .mini-value { font-weight: 600; }
  .mini-list .empty { color: var(--muted); font-size: .8rem; padding: .4rem 0; }

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

  /* ---------- ポップアップ（モーダル、2026-10-08追加。別プロジェクトのAddKnowledgeModal等を参考） ---------- */
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.62); z-index: 900; display: flex; align-items: center; justify-content: center; padding: 1rem; }
  .modal { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 14px; width: min(680px, 100%); max-height: calc(100vh - 2rem); display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,.5); outline: none; }
  .modal.wide { width: min(860px, 100%); }
  .modal-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; padding: 1rem 1.2rem .6rem; }
  .modal-header h3 { margin: 0; font-size: 1.05rem; }
  .modal-close { background: none; border: none; color: var(--muted); font-size: 1.1rem; cursor: pointer; padding: .2rem .5rem; border-radius: 6px; }
  .modal-close:hover { color: var(--text); background: var(--panel); }
  .modal-steps { display: flex; gap: .4rem; padding: 0 1.2rem .7rem; flex-wrap: wrap; }
  .modal-step { display: flex; align-items: center; gap: .4rem; font-size: .78rem; color: var(--muted); padding: .2rem .6rem; border: 1px solid var(--border); border-radius: 999px; }
  .modal-step .idx { width: 1.15rem; height: 1.15rem; border-radius: 50%; background: var(--border); color: var(--text); display: inline-flex; align-items: center; justify-content: center; font-size: .7rem; }
  .modal-step.active { color: var(--text); border-color: var(--accent); }
  .modal-step.active .idx { background: var(--accent); color: #fff; }
  .modal-step.done .idx { background: var(--teal); color: #fff; }
  .modal-body { padding: .4rem 1.2rem 1rem; overflow-y: auto; flex: 1; }
  .modal-footer { display: flex; justify-content: flex-end; align-items: center; gap: .6rem; padding: .8rem 1.2rem; border-top: 1px solid var(--border); }
  .modal-footer .grow { flex: 1; color: var(--muted); font-size: .8rem; }
  .method-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: .6rem; margin: .4rem 0 1rem; }
  .method-card { text-align: left; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: .8rem; cursor: pointer; color: var(--text); font-family: inherit; display: flex; flex-direction: column; gap: .25rem; }
  .method-card:hover { border-color: var(--muted); }
  .method-card.selected { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .method-card .icon { font-size: 1.4rem; }
  .method-card small { color: var(--muted); font-size: .76rem; }
  .modal-grid { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 1rem; }
  @media (max-width: 720px) { .modal-grid { grid-template-columns: 1fr; } }
  .modal-tips { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: .7rem .8rem; font-size: .78rem; color: var(--muted2); align-self: start; }
  .modal-tips h4 { margin: 0 0 .4rem; font-size: .8rem; color: var(--text); }
  .modal-tips ul { margin: 0; padding-left: 1.1rem; }
  .modal-tips li { margin-bottom: .3rem; }
  .dropzone { border: 2px dashed var(--border); border-radius: 12px; padding: 1.2rem; text-align: center; color: var(--muted); }
  .dropzone.drag-over { border-color: var(--accent); background: var(--panel); }
  .dropzone p { margin: .2rem 0; }
  .file-list { list-style: none; margin: .7rem 0 0; padding: 0; text-align: left; }
  .file-row { display: flex; align-items: center; gap: .5rem; padding: .35rem .5rem; border: 1px solid var(--border); border-radius: 8px; margin-bottom: .35rem; font-size: .82rem; background: var(--bg); }
  .file-row .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
  .file-row .size { color: var(--muted); font-size: .74rem; }
  .file-row .icon-btn { background: none; border: none; color: var(--muted); cursor: pointer; font-size: .9rem; }
  .file-row .icon-btn:hover { color: var(--bad); }
  .file-row.vertical { flex-direction: column; align-items: stretch; }
  .file-row .line { display: flex; align-items: center; gap: .5rem; }
  .file-row .err { color: var(--bad); font-size: .76rem; margin: .1rem 0 0 1.6rem; word-break: break-all; }
  .file-row .detail { color: var(--muted); font-size: .76rem; margin: .1rem 0 0 1.6rem; word-break: break-all; }
  .badge { font-size: .7rem; padding: .05rem .5rem; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); white-space: nowrap; }
  .badge.running { color: var(--highlight); border-color: var(--highlight); }
  .badge.ok { color: var(--teal); border-color: var(--teal); }
  .badge.error { color: var(--bad); border-color: var(--bad); }
  .progress-track { height: 8px; border-radius: 999px; background: var(--border); overflow: hidden; margin: .6rem 0; }
  .progress-bar { height: 100%; background: var(--accent); transition: width .25s; }
  .qa-pair { border: 1px solid var(--border); border-radius: 10px; padding: .6rem; margin-bottom: .6rem; background: var(--panel); }
  .qa-pair .head { display: flex; justify-content: space-between; align-items: center; font-size: .8rem; margin-bottom: .3rem; }
  .qa-pair textarea { width: 100%; box-sizing: border-box; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: .4rem; font-family: inherit; font-size: .85rem; margin-bottom: .3rem; resize: vertical; }
  .modal-note { font-size: .8rem; color: var(--muted); margin: .4rem 0; }
  .modal-error { font-size: .82rem; color: var(--bad); margin: .5rem 0; }
  .modal-fields label { display: block; font-size: .78rem; color: var(--muted); margin: .5rem 0 .2rem; }
  .modal-fields input[type="text"], .modal-fields input[type="number"], .modal-fields select, .modal-fields textarea { width: 100%; box-sizing: border-box; background: var(--panel); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: .4rem .5rem; font-family: inherit; font-size: .85rem; }
  .modal-fields .radio-row, .modal-fields .check-row { display: flex; align-items: center; gap: .4rem; font-size: .84rem; color: var(--text); margin: .25rem 0; }
  .modal-fields .radio-row input, .modal-fields .check-row input { width: auto; }
  .modal-fields details { margin-top: .6rem; border: 1px solid var(--border); border-radius: 8px; padding: .4rem .7rem; }
  .modal-fields summary { cursor: pointer; font-size: .82rem; color: var(--muted2); }
  .mcp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: .6rem; margin: .4rem 0; }
  .mcp-card { text-align: left; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: .8rem; cursor: pointer; color: var(--text); font-family: inherit; }
  .mcp-card:hover { border-color: var(--accent); }
  .mcp-card strong { display: flex; align-items: center; gap: .5rem; margin-bottom: .2rem; }
  .mcp-card small { color: var(--muted); font-size: .76rem; }
  .mcp-tools { list-style: none; margin: .5rem 0; padding: 0; max-height: 260px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; }
  .mcp-tools li { padding: .4rem .6rem; border-bottom: 1px solid var(--border); font-size: .8rem; }
  .mcp-tools li:last-child { border-bottom: none; }
  .mcp-tools label { display: flex; gap: .5rem; align-items: flex-start; cursor: pointer; }
  .mcp-tools small { display: block; color: var(--muted); font-size: .74rem; margin-top: .1rem; }
  .mcp-status-list { list-style: none; margin: .5rem 0; padding: 0; }
  .mcp-status-list li { display: flex; align-items: center; gap: .5rem; padding: .3rem 0; font-size: .85rem; }
  .tool-calls { font-size: .76rem; color: var(--muted); margin-top: .3rem; }

  /* ---------- 別プロジェクトを参考にした画面構成（2026-10-08）：アクションバー・カード・システム選択・詳細 ---------- */
  .btn.outline { background: transparent; border: 1px solid var(--accent); color: var(--accent); }
  .btn.outline:hover { background: var(--panel); color: var(--accent); }
  .kb-toolbar { display: flex; gap: .6rem; flex-wrap: wrap; padding-bottom: 1rem; }
  .section.card { border: 1px solid var(--border); border-radius: 12px; padding: 1rem 1.2rem 1.1rem; margin-bottom: 1.2rem; }
  .card-head { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; margin-bottom: .7rem; }
  .card-head h2 { margin: 0; font-size: 1rem; flex: 1; min-width: 12rem; }
  .card-head select, .card-head input { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: .4rem .6rem; font-family: inherit; font-size: .85rem; }
  .kb-name { max-width: 30rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .kb-doc-icon { margin-right: .45rem; }
  .pager { display: flex; align-items: center; justify-content: space-between; gap: 1rem; font-size: .8rem; color: var(--muted); margin-top: .7rem; flex-wrap: wrap; }
  .pager .pages { display: flex; align-items: center; gap: .5rem; }
  .pager select { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: .2rem .4rem; font-family: inherit; }
  .conn-list { list-style: none; margin: .4rem 0; padding: 0; }
  .conn-row { display: flex; align-items: center; gap: .6rem; padding: .6rem .4rem; border-bottom: 1px solid var(--border); cursor: pointer; flex-wrap: wrap; border-radius: 6px; }
  .conn-row:hover, .conn-row:focus-visible { background: var(--panel); outline: none; }
  .conn-row:last-child { border-bottom: none; }
  .conn-desc { color: var(--muted); font-size: .78rem; }
  .conn-empty { color: var(--muted); font-size: .85rem; padding: .4rem 0; }
  .chip { font-size: .75rem; padding: .1rem .65rem; border-radius: 999px; background: var(--panel); border: 1px solid var(--border); color: var(--muted2); }
  .chip.ok { color: var(--teal); border-color: var(--teal); }
  /* 登録ポップアップ：3つの帯状のステップ（別プロジェクトのナレッジ追加と同じ見せ方） */
  .modal-steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem; padding: 0 1.2rem .8rem; }
  .modal-step { padding: .55rem .8rem; border-radius: 10px; border: none; background: var(--panel); font-size: .85rem; }
  .modal-step.active { background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--text); }
  .modal-step.done { background: color-mix(in srgb, var(--teal) 16%, transparent); }
  .method-card { align-items: center; text-align: center; padding: 1rem .8rem; }
  .method-card .icon { font-size: 1.7rem; }
  .method-card strong { font-size: .95rem; }
  .modal-tips ul { padding-left: 0; list-style: none; }
  .modal-tips li { display: flex; gap: .45rem; }
  .tip-check { color: var(--teal); font-weight: 700; }
  /* 連携するシステム：選択グリッド */
  .sys-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: .7rem; }
  .sys-card { display: flex; align-items: center; gap: .8rem; text-align: left; background: var(--bg); border: 1px solid var(--border); border-radius: 12px; padding: .9rem 1rem; cursor: pointer; color: var(--text); font-family: inherit; }
  .sys-card:hover, .sys-card:focus-visible { border-color: var(--accent); outline: none; }
  .sys-icon { font-size: 1.4rem; width: 2.4rem; height: 2.4rem; display: inline-flex; align-items: center; justify-content: center; border-radius: 10px; background: var(--panel); flex: none; }
  .sys-icon.big { width: 4rem; height: 4rem; font-size: 2rem; background: var(--bg); }
  .sys-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: .15rem; }
  .sys-text strong { font-size: .92rem; display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
  .sys-text small { color: var(--muted); font-size: .76rem; }
  .sys-chevron { color: var(--muted); font-size: 1.5rem; }
  /* 連携するシステム：詳細（アカウント・アクセス範囲・セキュリティ） */
  .sys-hero { display: flex; gap: 1rem; align-items: center; background: color-mix(in srgb, var(--accent) 9%, var(--panel)); border-radius: 12px; padding: 1rem; margin-bottom: .8rem; }
  .sys-hero h4 { margin: 0 0 .2rem; font-size: 1.05rem; display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
  .sys-hero p { margin: .1rem 0; font-size: .85rem; color: var(--muted2); }
  .sys-hero p.sys-account { color: var(--accent); font-weight: 600; }
  .sys-rows { display: flex; flex-direction: column; gap: .5rem; }
  .sys-row { display: grid; grid-template-columns: 9.5rem 1fr; gap: .8rem; align-items: center; }
  .sys-row-label { font-size: .85rem; font-weight: 700; }
  .sys-val { background: var(--panel); border-radius: 8px; padding: .55rem .8rem; font-size: .84rem; color: var(--muted2); }
  .sys-panel { border: 1px solid var(--border); border-radius: 10px; padding: .8rem 1rem; margin-top: .8rem; }
  .sys-panel h4 { margin: 0 0 .4rem; font-size: .9rem; }
  @media (max-width: 640px) { .sys-row { grid-template-columns: 1fr; } .modal-steps { grid-template-columns: 1fr; } }
</style>
</head>
<body class="locked">

<header>
  <div class="header-row">
    <h1>RAG Chat（Cloudflare POC）</h1>
    <input type="password" id="apiKey" placeholder="APIキー（Bearer トークン）" autocomplete="off">
    <select id="namespaceFocus" title="検索対象を個別DBに絞り込む（精度向上）">
      <option value="">全DB横断検索</option>
    </select>
    <select id="level">
      <option value="">レベル: すべて</option>
      <option value="basic">basic</option>
      <option value="applied">applied</option>
      <option value="advanced">advanced</option>
    </select>
    <span id="myBudget" class="hint" title="自分のAPIキーのトークン予算残量"></span>
    <button type="button" id="themeToggle" title="テーマ切替（自動 / ライト / ダーク）">テーマ: 自動</button>
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
    <label id="mcpToggleWrap" class="attach-preview" style="display:none; cursor:pointer;" title="検索結果で足りないとき、接続済みの外部サービス（公式MCP）の読み取り専用ツールで調べます。回答に、使ったサービスが表示されます"><input type="checkbox" id="mcpToggle"> <span id="mcpToggleLabel">外部サービスも使う</span></label>
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
  <div class="pane-scroll admin-pane-scroll">
    <!-- サブナビをサイドバー化（2026-09-11）：グループ数が7まで増え、横並びピルだと
         窮屈になってきたための変更。GitHub/Slack/NotionのSettings画面と同じく
         「アプリ全体のトップナビは横並びのまま、深い設定領域だけ左サイドバー」という
         構成にした（管理タブ以外・トップレベルのnav.tabsはチャット利用が主目的なので
         横並びのまま変更していない）。JS側のセレクタ（.admin-subnav button /
         .admin-subpanel）は変更していないため、クリック時の切り替えロジックは
         そのまま流用できる。 -->
    <div class="admin-layout">
    <div class="admin-sidebar">
    <!-- サブナビ（2026-09-10追加）: 「ユーザーによって見たいもの/見なくていいものが
         違うので表示をもっと分割すべき」というフィードバックへの対応。ガイドと
         ナレッジ登録グループはeditorロールでも見え、それ以外はadmin-only-section
         （CSS側でeditorには非表示）にしている。 -->
    <nav class="admin-subnav">
      <button data-subtab="guide" class="active">ガイド</button>
      <button data-subtab="overview" class="admin-only-section">Overview</button>
      <button data-subtab="knowledge">ナレッジ登録</button>
      <button data-subtab="integrations">連携</button>
      <button data-subtab="users" class="admin-only-section">ユーザー・権限</button>
      <button data-subtab="namespaces" class="admin-only-section">namespace管理</button>
      <button data-subtab="usage" class="admin-only-section">利用状況・コスト</button>
      <button data-subtab="system" class="admin-only-section">システム</button>
    </nav>

    <!-- ダッシュボードの自動更新（2026-09-12追加）。コスト暴走をリアルタイムで
         監視しやすくするための機能。表示中のサブタブに応じて対象を絞って再読み込みする
         （常に全サブタブを更新すると、見ていない画面のぶんまで無駄な通信が走るため）。
         2026-09-13: .admin-subnavと同じ.admin-sidebar内に入れ、サイドバーとして
         1カラムにまとまるよう修正（元は.admin-layoutの直接の子で、意図せず
         コンテンツ側の幅を圧迫する独立カラムになっていた）。 -->
    <div class="admin-only-section autorefresh-box">
      <label><input type="checkbox" id="autoRefreshToggle"> 自動更新</label>
      <select id="autoRefreshInterval" class="role-select">
        <option value="30000">30秒毎</option>
        <option value="60000" selected>1分毎</option>
        <option value="300000">5分毎</option>
      </select>
    </div>
    </div><!-- /.admin-sidebar -->

    <div class="admin-content">
    <!-- ガイド: admin/editor共通。各グループの役割とロールごとに何ができるかをまとめた
         静的な説明（houdini/python_panels/rag_chatbot.pyの「はじめに」タブと同じ方針）。 -->
    <div class="admin-subpanel active" data-subtab="guide">
      <div class="guide-block">
        <h3>管理タブについて</h3>
        <p>ナレッジベースの登録・システム設定・利用状況の確認をまとめて行うタブです。上のサブナビで見たいグループだけを表示できます。表示されるグループは自分のロールによって変わります（下表参照）。</p>
      </div>
      <div class="guide-block">
        <h3>ロールごとにできること</h3>
        <table class="role-table">
          <thead><tr><th>ロール</th><th>できること</th><th>見えるグループ</th></tr></thead>
          <tbody>
            <tr><td><span class="role-badge admin">admin</span></td><td>すべての操作（ユーザー/キー管理・namespace管理・バックアップ・ヘルスチェック・利用状況/コスト閲覧・KBロールバックを含む）</td><td>全グループ</td></tr>
            <tr><td><span class="role-badge editor">editor</span></td><td>ナレッジ登録・KB同期の実行と履歴閲覧のみ</td><td>ガイド・ナレッジ登録</td></tr>
            <tr><td><span class="role-badge member">member</span></td><td>チャット・グラフ・履歴・お気に入りの利用のみ（管理タブ自体が非表示）</td><td>-</td></tr>
          </tbody>
        </table>
        <p class="hint">実際の権限チェックは各操作のサーバー側エンドポイントが行っており、この画面の表示/非表示はあくまで見た目の都合です。</p>
      </div>
      <div class="guide-block">
        <h3>各グループの役割</h3>
        <ul>
          <li><b>Overview</b> — namespace数・発行済みキー数・今月のRAG/Claude利用状況のサマリー。</li>
          <li><b>ナレッジ登録</b> — Drive/Notion同期・URL/YouTube/ファイル/FAQ/QA CSVの登録と、その同期履歴の確認。</li>
          <li><b>ユーザー・権限</b> — APIキーの発行・ロール変更・削除・有効期限の設定。</li>
          <li><b>namespace管理</b> — namespaceの作成・参考資料数上限・トークン予算しきい値の設定。</li>
          <li><b>利用状況・コスト</b> — RAGトークン使用量、Claude/Gemini APIの推定コスト、監査ログ、回答への評価統計。</li>
          <li><b>システム</b> — 設定バックアップ、ヘルスチェック・アラート通知、KBロールバック（元に戻せない操作）。</li>
        </ul>
      </div>
    </div>

    <!-- Overview: admin専用 -->
    <div class="admin-subpanel admin-only-section" data-subtab="overview">
      <div class="section">
        <h2>Overview</h2>
        <p class="hint">namespace・利用中キー・今月のRAG/Claude利用状況のサマリーです。</p>
        <div class="kpi-grid" id="adminOverviewKpis"></div>
        <div class="overview-cols">
          <div class="overview-col">
            <h3>ロール別キー内訳</h3>
            <ul class="mini-list" id="adminRoleBreakdown"></ul>
          </div>
          <div class="overview-col">
            <h3>ナレッジ登録量ランキング（namespace別）</h3>
            <ul class="mini-list" id="adminTopNamespaces"></ul>
          </div>
        </div>
      </div>
    </div>

    <!-- ナレッジ登録: admin/editor共通 -->
    <div class="admin-subpanel" data-subtab="knowledge">
      <div class="section kb-toolbar">
        <button class="btn primary" id="openKnowledgeModalBtn">＋ ナレッジを追加</button>
        <button class="btn outline" id="openSystemsModalBtn">🔗 ＋ 連携するシステムを追加</button>
      </div>

      <div class="section card" id="kbListCard">
        <div class="card-head">
          <h2>📖 登録済みナレッジ</h2>
          <select id="kbListNs" aria-label="namespace"></select>
          <input type="search" id="kbListSearch" placeholder="ナレッジを検索…">
          <button class="btn" id="kbListRefresh">更新</button>
        </div>
        <div class="table-scroll"><table class="admin-table" id="kbListTable"><thead><tr><th>ナレッジ名</th><th>種類</th><th>更新日時</th><th>操作</th></tr></thead><tbody></tbody></table></div>
        <div class="pager">
          <span id="kbListCount"></span>
          <span class="pages"><button class="btn" id="kbListPrev">‹</button><span id="kbListPageNo">1 / 1</span><button class="btn" id="kbListNext">›</button></span>
          <label>表示件数 <select id="kbListSize"><option value="10">10</option><option value="20" selected>20</option><option value="50">50</option><option value="100">100</option></select></label>
        </div>
        <p class="hint">登録時のopId単位でまとめて取り消す場合は、システムタブの「KBロールバック」を使います。</p>
      </div>

      <div class="section card" id="connectedSystemsCard">
        <div class="card-head"><h2>🧩 連携中のシステム</h2></div>
        <ul class="conn-list" id="connectedSystemsList"><li class="conn-empty">確認中…</li></ul>
        <p class="hint">※ 連携はこの管理画面（デプロイ全体）で共有されます。チャットから使えるのは、管理者が「チャットで使う」を許可した公式MCPの読み取り専用ツールだけです。</p>
      </div>

      <div class="section">
        <h2>namespaceごとのナレッジ登録状況</h2>
        <p class="hint">別プロジェクト管理コンソールの「Knowledge by Agent」を参考に追加（2026-09-10）。ファイル数・チャンク数はchunks_ftsから、最終更新日時は同期成功ログから集計しています。</p>
        <button class="btn" id="refreshKbOverview">再読み込み</button>
        <div class="table-scroll"><table class="admin-table" id="kbOverviewTable"><thead><tr><th>namespace</th><th>ファイル数</th><th>チャンク数</th><th>同期元</th><th>最終更新</th></tr></thead><tbody></tbody></table></div>
      </div>

      <div class="section">
        <h2>重複コンテンツの確認・削除</h2>
        <p class="hint">同じ内容がfile名違いで複数回登録されていないか確認します（URL登録とクロールの重複登録、Notion/Driveとの二重同期など）。先頭チャンクの本文＋文字数が完全一致するものだけを「重複」として検出します（近似一致は誤削除を避けるため対象外）。</p>
        <div class="field-row"><label>namespace</label><input type="text" id="dupCheckNamespace" placeholder="例: shared:houdini_docs"></div>
        <button class="btn" id="dupCheckBtn">重複チェック</button>
        <div id="dupCheckResult" class="hint"></div>
        <div id="dupCheckGroups"></div>
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
        <h2>同期履歴</h2>
        <button class="btn" id="refreshKbHistory">再読み込み</button>
        <div class="table-scroll"><table class="admin-table" id="kbHistoryTable"><thead><tr><th>日時</th><th>opId</th><th>種別</th><th>namespace</th><th>ファイル</th><th>状態</th><th>詳細</th></tr></thead><tbody></tbody></table></div>
      </div>
    </div>

    <!-- 連携: editor/admin共通（Slack/Gmailの通知テストのみadmin専用。2026-09-17追加） -->
    <div class="admin-subpanel" data-subtab="integrations">
      <div class="section">
        <h2>Jira</h2>
        <p class="hint">プロジェクトの課題（要約・説明・種別・ステータス）をnamespaceへ一括登録します。設定済みのプロジェクトは毎日自動で差分同期されます（更新された課題だけを追加登録。初回の全件取り込みは下の「Jira同期を実行」で行ってください）。</p>
        <div id="jiraOAuthStatus" class="hint">確認中…</div>
        <button class="btn primary" id="jiraConnectBtn">🔗 Jiraと接続する</button>
        <button class="btn danger" id="jiraDisconnectBtn" style="display:none;">接続を解除</button>
        <p class="hint" style="margin-top:.4rem;">上のボタンでブラウザ認証するだけで接続できます（推奨）。技術者向けに、APIトークンをJIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKENとしてsecret登録する方式も引き続き使えます（README参照）。</p>
        <div class="field-row"><label>namespace</label><input type="text" id="jiraNamespace" placeholder="例: shared:project_x"></div>
        <div class="field-row"><label>プロジェクトキー</label><input type="text" id="jiraProjectKey" placeholder="例: PROJ"> <button class="btn danger" id="jiraClearBtn" title="連携を解除">解除</button></div>
        <div class="field-row"><label>候補から選ぶ</label><select id="jiraProjectPicker"><option value="">（「候補を取得」を押してください）</option></select> <button class="btn" id="jiraLoadProjectsBtn">候補を取得</button></div>
        <div class="field-row"><label>絞り込み条件（任意）</label><input type="text" id="jiraExtraJql" placeholder='例: status = "Done"（JQL形式）'></div>
        <button class="btn" id="jiraSetSourceBtn">同期元を設定</button>
        <button class="btn" id="jiraTestConnectionBtn">接続テスト</button>
        <div style="margin-top:.6rem;">
          <button class="btn primary" id="jiraSyncBtn">Jira同期を実行</button>
          <button class="btn" id="jiraRetryFailedBtn" disabled>失敗課題だけ再同期</button>
        </div>
        <div id="jiraSyncProgress" class="hint" style="white-space:pre-line;"></div>
      </div>

      <div class="section">
        <h2>Backlog</h2>
        <p class="hint">プロジェクトの課題（要約・説明・種別・ステータス）をnamespaceへ一括登録します。設定済みのプロジェクトは毎日自動で差分同期されます（Jiraと同様、初回の全件取り込みは手動で行ってください）。</p>
        <div id="backlogOAuthStatus" class="hint">確認中…</div>
        <div class="field-row"><label>スペースURL</label><input type="text" id="backlogSpaceInput" placeholder="例: yourspace.backlog.com"></div>
        <button class="btn primary" id="backlogConnectBtn">🔗 Backlogと接続する</button>
        <button class="btn danger" id="backlogDisconnectBtn" style="display:none;">接続を解除</button>
        <p class="hint" style="margin-top:.4rem;">上のスペースURLを入力してボタンを押すだけで接続できます（推奨）。技術者向けに、APIキーをBACKLOG_SPACE_URL/BACKLOG_API_KEYとしてsecret登録する方式も引き続き使えます（README参照）。</p>
        <div class="field-row"><label>namespace</label><input type="text" id="backlogNamespace" placeholder="例: shared:project_x"></div>
        <div class="field-row"><label>プロジェクトキー/ID</label><input type="text" id="backlogProjectId" placeholder="例: PROJ"> <button class="btn danger" id="backlogClearBtn" title="連携を解除">解除</button></div>
        <div class="field-row"><label>候補から選ぶ</label><select id="backlogProjectPicker"><option value="">（「候補を取得」を押してください）</option></select> <button class="btn" id="backlogLoadProjectsBtn">候補を取得</button></div>
        <div class="field-row"><label>絞り込みキーワード（任意）</label><input type="text" id="backlogKeywordFilter" placeholder="要約・説明の部分一致"></div>
        <button class="btn" id="backlogSetSourceBtn">同期元を設定</button>
        <button class="btn" id="backlogTestConnectionBtn">接続テスト</button>
        <div style="margin-top:.6rem;">
          <button class="btn primary" id="backlogSyncBtn">Backlog同期を実行</button>
          <button class="btn" id="backlogRetryFailedBtn" disabled>失敗課題だけ再同期</button>
        </div>
        <div id="backlogSyncProgress" class="hint" style="white-space:pre-line;"></div>
      </div>

      <div class="section">
        <h2>Googleカレンダー</h2>
        <p class="hint">予定（タイトル・日時・場所・説明）を過去7日〜未来90日分登録します。設定済みのカレンダーは毎日自動で同期されます。</p>
        <div id="calendarOAuthStatus" class="hint">確認中…</div>
        <button class="btn primary" id="calendarConnectBtn">🔗 Googleと接続する</button>
        <button class="btn danger" id="calendarDisconnectBtn" style="display:none;">接続を解除</button>
        <p class="hint" style="margin-top:.4rem;">上のボタンでご自身のGoogleアカウントを認証するだけで、そのアカウントが見えるカレンダーを連携できます（推奨）。技術者向けに、対象カレンダーをサービスアカウント（GOOGLE_SERVICE_ACCOUNT_JSONのclient_email）へ「閲覧者」共有する従来方式も引き続き使えます（README参照）。</p>
        <div class="field-row"><label>namespace</label><input type="text" id="calendarNamespace" placeholder="例: shared:team_schedule"></div>
        <div class="field-row"><label>カレンダーID</label><input type="text" id="calendarId" placeholder="例: xxxx@group.calendar.google.com"> <button class="btn danger" id="calendarClearBtn" title="連携を解除">解除</button></div>
        <div class="field-row"><label>候補から選ぶ</label><select id="calendarPicker"><option value="">（「候補を取得」を押してください）</option></select> <button class="btn" id="calendarLoadListBtn">候補を取得</button></div>
        <p class="hint">従来方式（サービスアカウント共有）の場合、共有した覚えのあるカレンダーでも候補に出てこないことがあります。その場合はIDを直接入力してください。</p>
        <button class="btn" id="calendarSetSourceBtn">同期元を設定</button>
        <button class="btn" id="calendarTestConnectionBtn">接続テスト</button>
        <div style="margin-top:.6rem;">
          <button class="btn primary" id="calendarSyncBtn">カレンダー同期を実行</button>
          <button class="btn" id="calendarRetryFailedBtn" disabled>失敗予定だけ再同期</button>
        </div>
        <div id="calendarSyncProgress" class="hint" style="white-space:pre-line;"></div>
      </div>

      <div class="section">
        <h2>Googleマップ</h2>
        <p class="hint">場所名・住所で検索し、住所・電話番号・営業時間などをnamespaceへ登録します（継続同期ではなく単発登録）。事前にGOOGLE_MAPS_API_KEYのsecret設定が必要です。</p>
        <button class="btn" id="mapsTestConnectionBtn">接続テスト</button>
        <div id="mapsTestConnectionResult" class="hint"></div>
        <div class="field-row" style="margin-top:.6rem;"><label>namespace</label><input type="text" id="mapsNamespace" placeholder="例: shared:store_info"></div>
        <div class="field-row"><label>場所名・住所</label><input type="text" id="mapsQuery" placeholder="例: 東京都渋谷区〇〇店"></div>
        <button class="btn primary" id="mapsImportBtn">登録</button>
        <div id="mapsImportResult" class="hint"></div>

        <p class="hint" style="margin-top:1rem;">複数件まとめて登録する場合は、1行に1件（場所名・住所）ずつ入力してください。</p>
        <div class="field-row"><label>namespace</label><input type="text" id="mapsCsvNamespace" placeholder="例: shared:store_info"></div>
        <textarea id="mapsCsvText" rows="6" style="width:100%; font-family:monospace; font-size:.8rem; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:.5rem;" placeholder="東京都渋谷区〇〇店&#10;大阪府大阪市△△支店"></textarea>
        <button class="btn primary" id="mapsCsvImportBtn" style="margin-top:.5rem;">一括登録を実行</button>
        <div id="mapsCsvProgress" class="hint" style="white-space:pre-line;"></div>
      </div>

      <div class="section">
        <h2>公式MCP連携（Notion・Atlassian）</h2>
        <p class="hint">各社が公開する公式のMCPサーバーに接続し、そのツールをRAGチャットから使えるようにします（2026-10-08追加。別プロジェクトの公式MCP連携を参考）。認証はOAuth 2.1で、こちらでOAuthアプリを作る必要はありません。接続・ツール選択は管理者のみ、使えるのは読み取り専用のツールだけです。</p>
        <ul class="mcp-status-list" id="mcpStatusList"><li class="hint">確認中…</li></ul>
        <button class="btn primary" id="mcpOpenBtn">MCP連携を管理…</button>
        <button class="btn" id="mcpRefreshBtn">状態を再読み込み</button>
      </div>

      <div class="section admin-only-section">
        <h2>通知連携（Slack / Gmail）</h2>
        <p class="hint">管理者向けの通知・アラート先です。</p>
        <div id="slackOAuthStatus" class="hint">確認中…</div>
        <button class="btn primary" id="slackConnectBtn">🔗 Slackワークスペースに追加</button>
        <button class="btn danger" id="slackDisconnectBtn" style="display:none;">接続を解除</button>
        <p class="hint" style="margin-top:.4rem;">上のボタンで通知先チャンネルを選ぶだけで接続できます（推奨）。技術者向けに、Incoming Webhook URLをSLACK_WEBHOOK_URLとしてsecret登録する従来方式も引き続き使えます。Gmail（サービスアカウント経由）は引き続きシークレット設定が必要です（README参照）。</p>
        <button class="btn" id="integrationsTestAlertBtn" style="margin-top:.6rem;">テスト通知を送信</button>
        <div id="integrationsTestAlertResult" class="hint"></div>
      </div>
    </div>

    <!-- ユーザー・権限: admin専用 -->
    <div class="admin-subpanel admin-only-section" data-subtab="users">
      <div class="section">
        <h2>ユーザー概要</h2>
        <p class="hint">別プロジェクト管理コンソールのUsersページを参考に追加（2026-09-10）。</p>
        <div class="kpi-grid" id="usersOverviewKpis"></div>
      </div>

      <div class="section">
        <h2>新しいAPIキーを発行</h2>
        <div class="field-row"><label>名前</label><input type="text" id="newKeyName" placeholder="例: Unity Client, Alice"></div>
        <div class="field-row"><label>権限</label>
          <select id="newKeyRole" class="role-select">
            <option value="admin">管理者（全権限）</option>
            <option value="editor">ナレッジ登録権限者（ナレッジ登録・KB同期のみ）</option>
            <option value="member" selected>一般ユーザー（チャットのみ）</option>
          </select>
        </div>
        <div class="field-row"><label>RAGトークン上限</label><input type="number" id="newKeyCapacity" value="100000"></div>
        <div class="field-row"><label>Claude予算（チュートリアル生成等）</label><input type="number" id="newKeyClaudeCapacity" placeholder="空欄=無制限"></div>
        <div class="field-row"><label>有効期限</label>
          <select id="newKeyExpiry" class="role-select">
            <option value="0" selected>無期限</option>
            <option value="30">30日</option>
            <option value="90">90日</option>
            <option value="180">180日</option>
            <option value="365">1年</option>
          </select>
        </div>
        <div class="field-row"><label>アクセス可能namespace</label><div class="checks" id="newKeyNamespaces"></div></div>
        <button class="btn primary" id="createKeyBtn">APIキーを発行</button>
        <div id="newKeyResult"></div>
      </div>

      <div class="section">
        <h2>発行済みキー一覧</h2>
        <div class="field-row">
          <label>検索</label>
          <input type="text" id="keysSearch" placeholder="名前で絞り込み">
          <select id="keysRoleFilter" class="role-select">
            <option value="">すべてのロール</option>
            <option value="admin">管理者</option>
            <option value="editor">編集者</option>
            <option value="member">一般ユーザー</option>
          </select>
          <button class="btn" id="refreshKeys">再読み込み</button>
        </div>
        <div class="table-scroll"><table class="admin-table" id="keysTable"><thead><tr><th>名前</th><th>ロール</th><th>RAG予算</th><th>使用率</th><th>Claude予算（チュートリアル生成等）</th><th>最終利用</th><th>有効期限</th><th>作成日</th><th></th></tr></thead><tbody></tbody></table></div>
      </div>
    </div>

    <!-- namespace管理: admin専用 -->
    <div class="admin-subpanel admin-only-section" data-subtab="namespaces">
      <div class="section">
        <h2>namespace管理</h2>
        <div class="field-row"><label>namespace ID</label><input type="text" id="newNsId" placeholder="例: shared:new_topic"></div>
        <div class="field-row"><label>scope</label><select id="newNsScope"><option value="shared">shared</option><option value="personal">personal</option></select></div>
        <button class="btn primary" id="createNsBtn">作成</button>
        <button class="btn" id="refreshNs" style="margin-left:.5rem;">再読み込み</button>
        <p class="hint">参考資料数上限：この件数を超える分は検索結果から間引かれます（空欄=上限なし）。複数DBを横断検索した際、無関係なDBのチャンクが結果を圧迫するのを防ぐのに使えます。個人namespaceの名前欄には発行時に付けた表示名が出ます。</p>
        <div class="table-scroll"><table class="admin-table" id="nsTable"><thead><tr><th>namespace</th><th>scope</th><th>owner</th><th>参考資料数上限</th><th></th></tr></thead><tbody></tbody></table></div>
      </div>

      <div class="section">
        <h2>namespace別トークン予算・使用量</h2>
        <p class="hint">監視・アラート用のしきい値です（2026-09-12追加）。1クエリが複数namespaceを横断検索した場合、そのトークン数は関与した全namespaceに計上される概算のため、正確な予算「強制」ではありません。超過時はヘルスチェック（30分毎）でSlack/Gmailに通知されます。</p>
        <div class="field-row">
          <label>期間</label>
          <select id="nsUsageDays">
            <option value="7">直近7日間</option>
            <option value="30" selected>直近30日間</option>
            <option value="90">直近90日間</option>
          </select>
          <button class="btn" id="refreshNsUsage">再読み込み</button>
          <button class="btn" id="exportNsUsageCsv">CSVエクスポート</button>
        </div>
        <div class="table-scroll"><table class="admin-table" id="nsUsageTable"><thead><tr><th>namespace</th><th>使用量（概算）</th><th>予算</th><th>状態</th><th>予算を設定</th></tr></thead><tbody></tbody></table></div>
      </div>
    </div>

    <!-- 利用状況・コスト: admin専用 -->
    <div class="admin-subpanel admin-only-section" data-subtab="usage">
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
        <h2>Claude API使用量・コスト</h2>
        <p class="hint">Houdiniチュートリアル生成等が呼ぶ/claude/messagesプロキシの使用量です（RAGチャット自体の生成はGeminiのため含みません）。金額はAnthropic公表単価に基づく推定です。</p>
        <div class="field-row">
          <label>期間</label>
          <select id="claudeCostDays">
            <option value="7">直近7日間</option>
            <option value="30" selected>直近30日間</option>
            <option value="90">直近90日間</option>
          </select>
          <button class="btn" id="refreshClaudeCost">再読み込み</button>
          <button class="btn" id="exportClaudeCostCsv">CSVエクスポート</button>
        </div>
        <div class="kpi-grid" id="claudeCostKpis"></div>
        <div class="table-scroll"><table class="admin-table" id="claudeCostByModelTable"><thead><tr><th>モデル</th><th>呼び出し回数</th><th>入力トークン</th><th>出力トークン</th><th>推定コスト</th></tr></thead><tbody></tbody></table></div>
      </div>

      <div class="section">
        <h2>Gemini API使用量・コスト</h2>
        <p class="hint">RAGチャット自体の回答生成（query.ts/search.ts）の使用量です。金額はGoogle公表単価に基づく推定で、ナレッジ登録時の埋め込み（ベクトル化）コストは含みません（Gemini埋め込みAPIのレスポンスにトークン数が含まれないため未計測、2026-09-10追加）。</p>
        <div class="field-row">
          <label>期間</label>
          <select id="geminiCostDays">
            <option value="7">直近7日間</option>
            <option value="30" selected>直近30日間</option>
            <option value="90">直近90日間</option>
          </select>
          <button class="btn" id="refreshGeminiCost">再読み込み</button>
          <button class="btn" id="exportGeminiCostCsv">CSVエクスポート</button>
        </div>
        <div class="kpi-grid" id="geminiCostKpis"></div>
        <div class="table-scroll"><table class="admin-table" id="geminiCostByModelTable"><thead><tr><th>モデル</th><th>呼び出し回数</th><th>入力トークン</th><th>出力トークン</th><th>推定コスト</th></tr></thead><tbody></tbody></table></div>
      </div>

      <div class="section">
        <h2>監査ログ</h2>
        <p class="hint">クエリ本文は保存していません（SHA-256ハッシュのみ）。コスト暴走や不審なアクセスパターンに気づくための一覧です（2026-09-12追加）。</p>
        <div class="field-row">
          <label>件数</label>
          <select id="auditLogLimit">
            <option value="50" selected>50件</option>
            <option value="100">100件</option>
            <option value="200">200件</option>
          </select>
          <label>ユーザー名</label>
          <input type="text" id="auditLogUserId" placeholder="任意（発行済みキー一覧の名前で部分一致）">
          <label>namespace</label>
          <input type="text" id="auditLogNamespace" placeholder="任意（部分一致）">
          <button class="btn" id="refreshAuditLog">再読み込み</button>
          <button class="btn" id="exportAuditLogCsv">CSVエクスポート</button>
        </div>
        <div class="table-scroll"><table class="admin-table" id="auditLogTable"><thead><tr><th>日時</th><th>ユーザー</th><th>namespace</th><th>レベル</th><th>参考件数</th><th>レイテンシ</th><th>トークン</th><th>モデル</th></tr></thead><tbody></tbody></table></div>
      </div>

      <div class="section">
        <h2>Houdiniチュートリアルの評価</h2>
        <p class="hint">Houdiniパネルで付けられた良い/悪い評価・理由タグ・メモと、生成時の自動指標（反復回数・コスト・cookエラー数）です。管理者だけが閲覧できます（2026-10-05追加）。</p>
        <div class="field-row">
          <label>期間</label>
          <select id="tutorialFeedbackDays">
            <option value="30">直近30日間</option>
            <option value="90" selected>直近90日間</option>
            <option value="365">直近1年</option>
          </select>
          <label>評価</label>
          <select id="tutorialFeedbackRating">
            <option value="" selected>すべて</option>
            <option value="1">良い</option>
            <option value="-1">悪い</option>
          </select>
          <label>ユーザー名</label>
          <input type="text" id="tutorialFeedbackUser" placeholder="任意（部分一致）">
          <button class="btn" id="refreshTutorialFeedback">再読み込み</button>
          <button class="btn" id="exportTutorialFeedbackCsv">CSVエクスポート</button>
        </div>
        <div class="kpi-grid" id="tutorialFeedbackKpis"></div>
        <h3>モデル別</h3>
        <div class="table-scroll"><table class="admin-table" id="tutorialFeedbackByModel"><thead><tr><th>モデル</th><th>件数</th><th>良い / 悪い</th><th>好評率</th><th>平均反復</th><th>平均コスト</th><th>平均cookエラー</th></tr></thead><tbody></tbody></table></div>
        <h3>レベル別</h3>
        <div class="table-scroll"><table class="admin-table" id="tutorialFeedbackByLevel"><thead><tr><th>レベル</th><th>件数</th><th>良い / 悪い</th><th>好評率</th><th>平均反復</th><th>平均コスト</th><th>平均cookエラー</th></tr></thead><tbody></tbody></table></div>
        <h3>領域別</h3>
        <div class="table-scroll"><table class="admin-table" id="tutorialFeedbackByDomain"><thead><tr><th>領域</th><th>件数</th><th>良い / 悪い</th><th>好評率</th><th>平均反復</th><th>平均コスト</th><th>平均cookエラー</th></tr></thead><tbody></tbody></table></div>
        <h3>理由タグ別</h3>
        <div class="table-scroll"><table class="admin-table" id="tutorialFeedbackByTag"><thead><tr><th>タグ</th><th>件数</th><th>良い / 悪い</th><th>好評率</th><th>平均反復</th><th>平均コスト</th><th>平均cookエラー</th></tr></thead><tbody></tbody></table></div>
        <h3>評価の一覧</h3>
        <div class="table-scroll"><table class="admin-table" id="tutorialFeedbackTable"><thead><tr><th>日時</th><th>ユーザー</th><th>評価</th><th>チュートリアル</th><th>モデル / レベル</th><th>タグ</th><th>メモ</th><th>自動指標</th></tr></thead><tbody></tbody></table></div>
      </div>

      <div class="section">
        <h2>評価統計</h2>
        <button class="btn" id="refreshRatingStats">再読み込み</button>
        <p id="ratingSummary" class="hint">-</p>
        <div class="table-scroll"><table class="admin-table" id="ratingByUserTable"><thead><tr><th>ユーザー</th><th>件数</th><th>役に立った</th><th>役に立たなかった</th></tr></thead><tbody></tbody></table></div>
      </div>
    </div>

    <!-- システム: admin専用 -->
    <div class="admin-subpanel admin-only-section" data-subtab="system">
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
        <h2>KBロールバック</h2>
        <p class="hint">同期履歴の「opId」を指定すると、そのopIdで登録された全ファイルをnamespaceから削除できます（元に戻せません）。</p>
        <div class="field-row"><label>opId</label><input type="text" id="rollbackOpId" placeholder="例: op_1234567890_ab12cd"></div>
        <button class="btn danger" id="rollbackBtn">ロールバック実行</button>
        <div id="rollbackResult" class="hint"></div>
      </div>
    </div>
    </div><!-- /.admin-content -->
    </div><!-- /.admin-layout -->
  </div>
</div>

<div id="toastStack"></div>

<script>
(function () {
  const $ = (id) => document.getElementById(id);
  let currentUserRole = null; // "admin"|"editor"|"member"|"guest"|null（未認証）。setAuthGate()が更新する。

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

  // 監査ログ・コスト集計等をCSVでダウンロードする共通ヘルパー（2026-09-12追加、
  // 月次の請求根拠資料や社内共有向け）。BOM付きUTF-8にしているのはExcelで開いたときに
  // 日本語が文字化けしないようにするため。値は既にAPIから取得済みのものをそのまま
  // 書き出すだけで、再取得はしない（表示中の内容とエクスポート内容を一致させるため）。
  function downloadCsv(filename, headers, rows) {
    const escapeCell = (v) => {
      const s = v === null || v === undefined ? "" : String(v);
      // 改行文字にマッチさせたい箇所はバックスラッシュを2個重ねている。この関数は
      // chatUiHtml()の巨大な外側テンプレートリテラル内にあるため、単一バックスラッシュの
      // エスケープはここ（外側のTypeScriptコンパイラ）で実際の制御文字に解決されてしまい、
      // 正規表現リテラルの構文が壊れる（このファイルの歴史的なバグと同じ原因。この説明
      // コメント自体にも単一バックスラッシュの具体的な文字を書かないよう注意すること
      // ——過去に一度、まさにこの説明コメントの中に書いた1個のバックスラッシュ表記が
      // 同じ理由で壊れた前例がある）。二重にすることで、ブラウザ側の正規表現エンジンに
      // 渡る時点までエスケープシーケンスの文字列のまま残る。
      return /[",\\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const lines = [headers.map(escapeCell).join(",")];
    rows.forEach((row) => lines.push(row.map(escapeCell).join(",")));
    const blob = new Blob(["﻿" + lines.join("\\r\\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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
    // 権限の詳細化（2026-09-10追加）: セクション単位の表示/非表示はCSS側
    // （body[data-role="editor"] .admin-only-section）で行うため、ここでroleを
    // data属性として持たせておく。実際の権限チェックはサーバー側の各エンドポイントが
    // 唯一の正で、これもタブ表示同様あくまでUIの都合。
    document.body.dataset.role = role || "";
    currentUserRole = role || null;
    if (message !== undefined) {
      const gate = document.getElementById("authGate");
      if (gate) gate.textContent = message;
    }
    const adminBtn = document.querySelector('nav.tabs button[data-tab="admin"]');
    if (!adminBtn) return;
    // editor（ナレッジ登録権限者）も管理タブ自体は開けるが、admin-only-sectionは
    // 上記CSSで非表示になる（ナレッジ登録系のセクションだけが見える）。
    const canSeeAdminTab = role === "admin" || role === "editor";
    adminBtn.classList.toggle("hidden-tab", !canSeeAdminTab);
    if (!canSeeAdminTab && adminBtn.classList.contains("active")) {
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
      namespaceFocusEl.innerHTML = '<option value="">全DB横断検索</option>';
      data.namespaces.slice().sort().forEach((ns) => {
        const opt = document.createElement("option");
        opt.value = ns;
        opt.textContent = namespaceLabel(ns);
        namespaceFocusEl.appendChild(opt);
      });
      if (data.namespaces.includes(prevValue)) namespaceFocusEl.value = prevValue;
      loadMyBudget();
      refreshMcpAvailability();
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
      if (btn.dataset.tab === "admin") {
        // ナレッジ登録系（同期履歴）はeditorロールでも見えるセクションなので常に読み込む。
        // それ以外は管理者専用セクション（CSS側でeditorには非表示）のため、editorキーで
        // 呼んでも403になるだけの無駄なリクエストを避ける（権限の詳細化、2026-09-10）。
        loadKbHistory(); loadKbOverview();
        if (currentUserRole === "admin") {
          loadAdminOverview();
          loadNamespaceChecks();
          loadKeys();
          loadNamespaces();
          loadNamespaceUsage();
          loadUsageStats();
          loadClaudeCostStats();
          loadGeminiCostStats();
          loadAuditLog();
          loadRatingStats();
          loadTutorialFeedback();
        }
      }
      else clearNewKey(); // 管理タブを離れたら、発行直後のAPIキー表示が残らないようにする
    });
  });

  // 管理タブのサブナビ（2026-09-10追加）。トップレベルのnav.tabsと全く同じ操作感
  // （クリックでactiveクラスを付け替えるだけ）にしている。表示/非表示の権限判定は
  // 各ボタン・パネルに付いたadmin-only-sectionクラス（CSS側）に任せているため、
  // ここではクリックされたものを表示するだけでよい。
  const adminSubButtons = document.querySelectorAll(".admin-subnav button");
  const adminSubPanels = document.querySelectorAll(".admin-subpanel");
  adminSubButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      adminSubButtons.forEach((b) => b.classList.remove("active"));
      adminSubPanels.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.querySelector('.admin-subpanel[data-subtab="' + btn.dataset.subtab + '"]').classList.add("active");
      // 「連携」タブを開くたびに接続状況を再確認する（OAuth接続直後の戻り先でもあるため、
      // 2026-09-22追加）。
      if (btn.dataset.subtab === "integrations") { loadOAuthStatus(); loadMcpStatus(); }
      if (btn.dataset.subtab === "knowledge") { initKbList(); refreshConnectedSystems(); }
    });
  });

  // ダッシュボードの自動更新（2026-09-12追加）。「今開いているサブタブ」だけを対象に
  // 再読み込みする（他のサブタブぶんまで無駄な通信を発生させないため）。設定は
  // localStorageに覚えておき、次回管理タブを開いたときも同じ設定のままにする。
  let autoRefreshTimer = null;
  function currentAdminSubtab() {
    const active = document.querySelector(".admin-subnav button.active");
    return active ? active.dataset.subtab : null;
  }
  function runAutoRefresh() {
    const subtab = currentAdminSubtab();
    if (subtab === "overview") loadAdminOverview();
    else if (subtab === "usage") { loadUsageStats(); loadClaudeCostStats(); loadGeminiCostStats(); loadAuditLog(); loadRatingStats(); loadTutorialFeedback(); }
    else if (subtab === "namespaces") { loadNamespaces(); loadNamespaceUsage(); }
    else if (subtab === "users") loadKeys();
    else if (subtab === "knowledge") { loadKbOverview(); loadKbHistory(); }
  }
  function stopAutoRefresh() {
    if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null; }
  }
  function startAutoRefresh() {
    stopAutoRefresh();
    const intervalMs = Number($("autoRefreshInterval").value) || 60000;
    autoRefreshTimer = setInterval(runAutoRefresh, intervalMs);
  }
  const autoRefreshToggleEl = $("autoRefreshToggle");
  const autoRefreshIntervalEl = $("autoRefreshInterval");
  try {
    autoRefreshToggleEl.checked = localStorage.getItem("ragPocAutoRefresh") === "1";
    const savedInterval = localStorage.getItem("ragPocAutoRefreshInterval");
    if (savedInterval) autoRefreshIntervalEl.value = savedInterval;
  } catch { /* localStorage不可の環境では既定（オフ・1分毎）のまま */ }
  // ページ読み込み直後は常にチャットタブが表示されている（管理タブがアクティブな
  // 状態でロードされることは無い）ため、ここではトグルの状態を復元するだけにして
  // タイマーは起動しない。実際の起動は下の「管理タブをクリックしたら」のリスナーに
  // 任せる（そうしないと、チャットを使っているだけの間もバックグラウンドで
  // 無駄なポーリングが走り続けてしまう、2026-09-12レビューで発見）。
  autoRefreshToggleEl.addEventListener("change", () => {
    try { localStorage.setItem("ragPocAutoRefresh", autoRefreshToggleEl.checked ? "1" : "0"); } catch { /* noop */ }
    if (autoRefreshToggleEl.checked) startAutoRefresh(); else stopAutoRefresh();
  });
  autoRefreshIntervalEl.addEventListener("change", () => {
    try { localStorage.setItem("ragPocAutoRefreshInterval", autoRefreshIntervalEl.value); } catch { /* noop */ }
    if (autoRefreshToggleEl.checked) startAutoRefresh();
  });
  // 管理タブを離れたら止める（他のタブを見ている間もバックグラウンドで通信し続ける
  // 意味が無いため）。管理タブへ戻ったときはトグルがオンならstartAutoRefresh()で
  // 再開させる。
  document.querySelector('nav.tabs button[data-tab="admin"]').addEventListener("click", () => {
    if (autoRefreshToggleEl.checked) startAutoRefresh();
  });
  tabButtons.forEach((btn) => {
    if (btn.dataset.tab !== "admin") btn.addEventListener("click", stopAutoRefresh);
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

  // U1: アイコンは線幅1.5pxの1セットのインラインSVGのみ（絵文字は使わない）。
  // パスはすべて固定文字列で、外部入力は渡さない。
  const ICON_PATHS = {
    check: "M3.5 8.5l3 3 6-7",
    star: "M8 2l1.8 3.7 4 .6-2.9 2.8.7 4L8 11.2 4.4 13.1l.7-4L2.2 6.3l4-.6z",
    sources: "M3 4h10M3 8h10M3 12h6",
  };
  function iconEl(name) {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", ICON_PATHS[name]);
    svg.appendChild(path);
    return svg;
  }

  // U6: テーマ手動切替（自動 → ライト → ダーク）。選択はlocalStorageに保存する（不可環境では握りつぶす）。
  const THEME_LABELS = { auto: "自動", light: "ライト", dark: "ダーク" };
  function applyTheme(mode) {
    if (mode === "light" || mode === "dark") document.documentElement.setAttribute("data-theme", mode);
    else document.documentElement.removeAttribute("data-theme");
    const btn = document.getElementById("themeToggle");
    if (btn) btn.textContent = "テーマ: " + THEME_LABELS[mode === "light" || mode === "dark" ? mode : "auto"];
  }
  (function initTheme() {
    let saved = "auto";
    try { saved = localStorage.getItem("ragPocTheme") || "auto"; } catch { /* 不可環境は自動 */ }
    applyTheme(saved);
    const btn = document.getElementById("themeToggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") || "auto";
      const next = cur === "auto" ? "light" : cur === "light" ? "dark" : "auto";
      applyTheme(next);
      try { localStorage.setItem("ragPocTheme", next); } catch { /* noop */ }
    });
  })();

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
      setPinLabel(pinBtn, !!existingPinned);
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
        if (s.cited) citedBadge.appendChild(iconEl("check"));
        citedBadge.appendChild(document.createTextNode(s.cited ? "引用" : "未引用"));
        li.appendChild(citedBadge);
        sourceLiRefs[i] = li;
        ul.appendChild(li);
      });
      details.appendChild(ul);
      wrap.appendChild(details);
    }

    // U4: 回答の下に、出典件数とAI生成であることを固定表示する。
    const foot = document.createElement("div");
    foot.className = "answer-foot";
    foot.textContent = "出典 " + (sources ? sources.length : 0) + "件・AIが生成した回答です";
    wrap.appendChild(foot);

    // U5: 0件ヒット時だけ、小さな空状態を出す（通常画面には遊びを入れない）。
    if (!sources || sources.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.appendChild(document.createTextNode("深い海に迷ってしまいました。別のキーワードを試してみてください"));
      const dots = document.createElement("div");
      dots.className = "empty-dots";
      for (let i = 0; i < 3; i++) dots.appendChild(document.createElement("i"));
      empty.appendChild(dots);
      wrap.appendChild(empty);
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

  function setPinLabel(btn, pinned) {
    btn.textContent = "";
    btn.appendChild(iconEl("star"));
    btn.appendChild(document.createTextNode(pinned ? " お気に入り済み" : " お気に入り"));
  }

  async function togglePin(memoryId, pinned, btn) {
    try {
      await api("/memory/pin", { id: memoryId, pinned });
      btn.classList.toggle("active-pin", pinned);
      setPinLabel(btn, pinned);
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
      const useMcp = $("mcpToggle") && $("mcpToggle").checked && $("mcpToggleWrap").style.display !== "none";
      const data = await api("/query", { query: text, limit: 5, level: levelEl.value, namespaces: focusNs ? [focusNs] : undefined, image: imageToSend || undefined, useMcp: useMcp || undefined });
      renderAssistantMessage(messagesEl, text, data.answer, data.sources, data.extractionRate, data.extractionDetail, data.memoryId, null, false);
      if (data.toolCalls && data.toolCalls.length > 0) {
        // 使った外部サービスのツールを回答の下に出す（textContentのみ）
        const note = document.createElement("div");
        note.className = "tool-calls";
        note.textContent = "🔧 使った外部サービス: " + data.toolCalls.map((c) => c.providerLabel + "「" + c.tool + "」" + (c.ok ? "" : "（失敗）")).join(" / ");
        const last = messagesEl.lastElementChild;
        if (last) last.appendChild(note);
      }
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

  // Claude API使用量・コスト（2026-09-10追加）。RAGチャット自体はGeminiで生成するため、
  // このセクションはHoudiniチュートリアル生成が使う/claude/messagesプロキシ分のみを扱う。
  function kpiCard(label, value, sub) {
    const card = document.createElement("div");
    card.className = "kpi-card";
    const l = document.createElement("div"); l.className = "kpi-label"; l.textContent = label;
    const v = document.createElement("div"); v.className = "kpi-value"; v.textContent = value;
    card.appendChild(l); card.appendChild(v);
    if (sub) {
      const s = document.createElement("div"); s.className = "kpi-sub"; s.textContent = sub;
      card.appendChild(s);
    }
    return card;
  }

  // Claude/Gemini共通のコスト統計ロード処理（2026-09-10リファクタリング：Gemini分
  // 追加にあたって、endpoint/要素ID差分だけをパラメータ化した汎用版に統合した）。
  // csvBtnId（2026-09-12追加）: 渡すと「CSVエクスポート」ボタンを配線する。表示中の
  // byModel内訳をそのまま書き出すだけで、エクスポート専用の再取得はしない。
  function makeCostStatsLoader(endpoint, daysSelectId, kpiBoxId, tableId, csvBtnId) {
    let lastData = null;
    if (csvBtnId) {
      $(csvBtnId).addEventListener("click", () => {
        if (!lastData || lastData.byModel.length === 0) { showToast("エクスポートするデータがありません", "error"); return; }
        downloadCsv(
          tableId + "-" + new Date().toISOString().slice(0, 10) + ".csv",
          ["モデル", "呼び出し回数", "入力トークン", "出力トークン", "推定コスト(USD)"],
          lastData.byModel.map((m) => [m.model, m.calls, m.inputTokens, m.outputTokens, m.costUsd.toFixed(4)]),
        );
      });
    }
    return async function loadCostStats() {
      if (!apiKeyEl.value.trim()) return;
      const days = Number($(daysSelectId).value) || 30;
      const kpiBox = $(kpiBoxId);
      const tbody = $(tableId).querySelector("tbody");
      try {
        const data = await api(endpoint, { days });
        lastData = data;
        kpiBox.innerHTML = "";
        kpiBox.appendChild(kpiCard("推定コスト合計", "$" + data.totalCostUsd.toFixed(2), "直近" + data.days + "日間"));
        kpiBox.appendChild(kpiCard("合計トークン数", data.totalTokens.toLocaleString()));
        kpiBox.appendChild(kpiCard("呼び出し回数", data.totalCalls.toLocaleString()));
        tbody.innerHTML = "";
        if (data.byModel.length === 0) {
          tbody.innerHTML = '<tr><td colspan=5>この期間の利用はありません</td></tr>';
        } else {
          data.byModel.forEach((m) => {
            appendRow(tbody, [m.model, m.calls, m.inputTokens.toLocaleString(), m.outputTokens.toLocaleString(), "$" + m.costUsd.toFixed(3)]);
          });
        }
      } catch (e) {
        kpiBox.innerHTML = "";
        tbody.innerHTML = '<tr><td colspan=5>取得に失敗しました: ' + e.message + '</td></tr>';
      }
    };
  }
  const loadClaudeCostStats = makeCostStatsLoader("/admin/usage/claude-cost", "claudeCostDays", "claudeCostKpis", "claudeCostByModelTable", "exportClaudeCostCsv");
  $("refreshClaudeCost").addEventListener("click", loadClaudeCostStats);
  $("claudeCostDays").addEventListener("change", loadClaudeCostStats);

  const loadGeminiCostStats = makeCostStatsLoader("/admin/usage/gemini-cost", "geminiCostDays", "geminiCostKpis", "geminiCostByModelTable", "exportGeminiCostCsv");
  $("refreshGeminiCost").addEventListener("click", loadGeminiCostStats);
  $("geminiCostDays").addEventListener("change", loadGeminiCostStats);

  // 監査ログ（2026-09-12追加）。CSVエクスポート用に直近の取得結果をキャッシュしておく
  // （エクスポート時に再取得せず、画面に表示中の内容とファイルの内容を一致させるため）。
  let lastAuditLogEntries = [];
  async function loadAuditLog() {
    const tbody = $("auditLogTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=8>読み込み中…</td></tr>";
    try {
      const data = await api("/admin/audit-log", {
        limit: Number($("auditLogLimit").value) || 50,
        user: $("auditLogUserId").value.trim() || undefined,
        namespace: $("auditLogNamespace").value.trim() || undefined,
      });
      lastAuditLogEntries = data.entries;
      tbody.innerHTML = "";
      if (data.entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan=8>該当するログがありません</td></tr>';
        return;
      }
      data.entries.forEach((e) => {
        const when = new Date(e.created_at * 1000).toLocaleString();
        // namespace列: 横断検索したクエリはnamespace_idがカンマ区切りで複数入り、
        // 生の文字列をそのままセルに入れると（空白が無いため）word-break:break-allで
        // 1文字ずつ折り返され表が壊れる不具合があった（2026-09-13、実機報告）。
        // 最初の1件＋残り件数だけを表示し、全件はtitle属性のホバーで確認できるようにする。
        const nsList = (e.namespace_id || "").split(",").filter(Boolean);
        const nsLabel = nsList.length === 0 ? "-"
          : nsList.length === 1 ? nsList[0]
          : nsList[0] + " +" + (nsList.length - 1) + "件";
        const tr = appendRow(tbody, [when, e.displayName || e.user_id]);
        const nsCell = document.createElement("td");
        nsCell.textContent = nsLabel;
        if (nsList.length > 1) nsCell.title = nsList.join(", ");
        tr.appendChild(nsCell);
        const restCells = [
          e.difficulty || "-",
          e.result_count,
          e.latency_ms != null ? e.latency_ms + "ms" : "-",
          e.tokens_used,
          e.model || "-",
        ];
        restCells.forEach((v) => {
          const td = document.createElement("td");
          td.textContent = v;
          tr.appendChild(td);
        });
      });
    } catch (err) {
      tbody.innerHTML = '<tr><td colspan=8>取得に失敗しました: ' + err.message + '</td></tr>';
    }
  }
  $("refreshAuditLog").addEventListener("click", loadAuditLog);
  $("exportAuditLogCsv").addEventListener("click", () => {
    if (lastAuditLogEntries.length === 0) { showToast("エクスポートするログがありません", "error"); return; }
    downloadCsv(
      "audit-log-" + new Date().toISOString().slice(0, 10) + ".csv",
      ["日時", "ユーザー", "namespace", "レベル", "参考件数", "レイテンシ(ms)", "トークン", "モデル"],
      lastAuditLogEntries.map((e) => [
        new Date(e.created_at * 1000).toLocaleString(),
        e.displayName || e.user_id,
        e.namespace_id || "",
        e.difficulty || "",
        e.result_count,
        e.latency_ms ?? "",
        e.tokens_used,
        e.model || "",
      ]),
    );
  });

  // Overview KPIサマリー（別プロジェクト管理コンソールの添付参考画像を元にしたレイアウト、
  // 2026-09-10追加）。既存の各エンドポイントを束ねて叩くだけで、専用の集計APIは
  // 追加していない（呼び出し回数は増えるが、管理タブを開いた時の1回だけなので許容範囲）。
  // ミニリストの1行を組み立てる共通ヘルパー（ロール内訳・namespaceランキングで共用、
  // 2026-09-10追加）。labelContentはDOM要素かテキストのどちらでも渡せる。
  function miniListItem(labelContent, value) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.className = "mini-label";
    if (typeof labelContent === "string") label.textContent = labelContent;
    else label.appendChild(labelContent);
    const val = document.createElement("span");
    val.className = "mini-value";
    val.textContent = value;
    li.appendChild(label);
    li.appendChild(val);
    return li;
  }

  const ROLE_LABELS = { admin: "管理者", editor: "編集者", member: "一般ユーザー", guest: "ゲスト" };

  async function loadAdminOverview() {
    const box = $("adminOverviewKpis");
    const roleBox = $("adminRoleBreakdown");
    const topNsBox = $("adminTopNamespaces");
    box.innerHTML = "";
    roleBox.innerHTML = "";
    topNsBox.innerHTML = "";
    try {
      const [nsData, keysData, ragUsage, claudeCost, geminiCost, kbOverview] = await Promise.all([
        api("/admin/namespaces/list", {}),
        api("/admin/keys/list", {}),
        api("/admin/usage/stats", { days: 30 }),
        api("/admin/usage/claude-cost", { days: 30 }),
        api("/admin/usage/gemini-cost", { days: 30 }),
        api("/admin/kb/overview", {}),
      ]);
      const tokensThisMonth = ragUsage.daily.reduce((sum, d) => sum + (d.tokens || 0), 0);
      const totalCost = claudeCost.totalCostUsd + geminiCost.totalCostUsd;
      box.appendChild(kpiCard("namespace数", nsData.namespaces.length));
      box.appendChild(kpiCard("発行済みキー数", keysData.keys.length));
      box.appendChild(kpiCard("RAGトークン使用量", tokensThisMonth.toLocaleString(), "直近30日間"));
      box.appendChild(kpiCard("推定コスト合計（Gemini+Claude）", "$" + totalCost.toFixed(2), "直近30日間"));

      // ロール別キー内訳（別プロジェクトの"Plan Distribution"に相当）
      const roleCounts = {};
      keysData.keys.forEach((k) => { roleCounts[k.role] = (roleCounts[k.role] || 0) + 1; });
      const roleKeys = Object.keys(roleCounts);
      if (roleKeys.length === 0) {
        roleBox.innerHTML = '<li class="empty">発行済みキーがありません</li>';
      } else {
        roleKeys.forEach((role) => {
          const badge = document.createElement("span");
          badge.className = "role-badge " + role;
          badge.textContent = ROLE_LABELS[role] || role;
          roleBox.appendChild(miniListItem(badge, roleCounts[role] + "件"));
        });
      }

      // namespace別ナレッジ登録量ランキング（別プロジェクトの"Top Agents by Token Usage"に相当）
      const topNamespaces = kbOverview.namespaces.slice(0, 5);
      if (topNamespaces.length === 0) {
        topNsBox.innerHTML = '<li class="empty">登録されたナレッジがありません</li>';
      } else {
        topNamespaces.forEach((n) => {
          topNsBox.appendChild(miniListItem(n.namespace, n.chunkCount.toLocaleString() + "チャンク"));
        });
      }
    } catch (e) {
      box.innerHTML = '<p class="hint error">Overviewの取得に失敗しました: ' + e.message + '</p>';
    }
  }

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
      const claudeCapacityRaw = $("newKeyClaudeCapacity").value.trim();
      const data = await api("/admin/keys/create", {
        displayName: $("newKeyName").value.trim(),
        role: $("newKeyRole").value,
        namespaces,
        ragCapacity: Number($("newKeyCapacity").value) || 100000,
        claudeCapacity: claudeCapacityRaw === "" ? undefined : Number(claudeCapacityRaw),
        expiresInDays: Number($("newKeyExpiry").value) || 0,
      });
      showNewKey(data.apiKey);
      loadKeys();
    } catch (e) {
      clearNewKey();
      $("newKeyResult").innerHTML = '<p class="hint error">' + e.message + '</p>';
    }
  });

  // 検索・ロール絞り込み（2026-09-10追加）はサーバーへ都度問い合わせず、直近の
  // /admin/keys/list結果をクライアント側でフィルタするだけにしている（キー数が
  // 数百件規模になるまでは十分軽量で、絞り込みのたびに通信が走らない方が快適）。
  let allKeysCache = [];

  function renderKeysTable(keys) {
    const tbody = $("keysTable").querySelector("tbody");
    tbody.innerHTML = "";
    if (keys.length === 0) {
      tbody.innerHTML = '<tr><td colspan=9>該当するキーがありません</td></tr>';
      return;
    }
    keys.forEach((k) => {
      const created = new Date(k.created_at * 1000).toLocaleString();
      const tr = appendRow(tbody, [k.display_name]);

      // ロール列: バッジ表示＋インライン変更用select（権限の詳細化、2026-09-10追加）。
      // 従来は作成時にしかロールを指定できなかった（/admin/keys/update-role新設）。
      const roleCell = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = "role-badge " + k.role;
      badge.textContent = k.role;
      roleCell.appendChild(badge);
      const roleSelect = document.createElement("select");
      roleSelect.className = "role-select";
      roleSelect.style.marginLeft = ".4rem";
      // 2026-09-10: guestは選択肢から外した（管理者・編集者・メンバーの3つで十分、
      // というフィードバックへの対応）。既存にguestロールの行が残っていた場合でも
      // バッジ表示自体は引き続きできるよう、role-badge.member,.guestのCSSは残している。
      ["admin", "editor", "member"].forEach((r) => {
        const opt = document.createElement("option");
        opt.value = r; opt.textContent = r;
        if (r === k.role) opt.selected = true;
        roleSelect.appendChild(opt);
      });
      roleSelect.addEventListener("change", async () => {
        const newRole = roleSelect.value;
        try {
          await api("/admin/keys/update-role", { userId: k.user_id, role: newRole });
          showToast(k.display_name + " のロールを " + newRole + " に変更しました", "success");
          loadKeys();
        } catch (e) {
          showToast("ロール変更に失敗しました: " + e.message, "error");
          roleSelect.value = k.role;
        }
      });
      roleCell.appendChild(roleSelect);
      tr.appendChild(roleCell);

      const budgetCell = document.createElement("td");
      budgetCell.textContent = k.rag_limit != null ? (k.rag_used + '/' + k.rag_limit) : '無制限';
      tr.appendChild(budgetCell);

      const donutCell = document.createElement("td");
      tr.appendChild(donutCell);
      if (k.rag_limit != null) {
        const donutCanvas = document.createElement("canvas");
        donutCell.appendChild(donutCanvas);
        drawDonut(donutCanvas, k.rag_used, k.rag_limit);
      }

      // Claude予算（houdiniチュートリアル生成等が/claude/messagesを叩く際のサーバー側強制上限、
      // budget.tsのreserveBudget参照。2026-09-23追加）。RAGと違い未設定＝無制限がデフォルトの
      // ため、入力欄を空にして「設定」を押すと limitTokens: null を送って無制限に戻す。
      const claudeCell = document.createElement("td");
      tr.appendChild(claudeCell);
      const claudeText = document.createElement("span");
      claudeText.textContent = k.claude_limit != null ? (k.claude_used + '/' + k.claude_limit) : '無制限';
      claudeCell.appendChild(claudeText);
      const claudeInput = document.createElement("input");
      claudeInput.type = "number";
      claudeInput.min = "0";
      claudeInput.style.width = "90px";
      claudeInput.style.marginLeft = ".4rem";
      claudeInput.placeholder = "空欄=無制限";
      if (k.claude_limit != null) claudeInput.value = k.claude_limit;
      const claudeSetBtn = document.createElement("button");
      claudeSetBtn.className = "btn"; claudeSetBtn.textContent = "設定";
      claudeSetBtn.style.marginLeft = ".3rem";
      claudeSetBtn.onclick = async () => {
        const v = claudeInput.value.trim();
        try {
          await api("/admin/keys/set-capacity", {
            userId: k.user_id,
            budgetType: "claude",
            limitTokens: v === "" ? null : Number(v),
          });
          showToast(k.display_name + " のClaude予算を更新しました", "success");
          loadKeys();
        } catch (e) { showToast("設定に失敗しました: " + e.message, "error"); }
      };
      claudeCell.appendChild(claudeInput);
      claudeCell.appendChild(claudeSetBtn);

      // 最終利用日時（2026-09-10追加、別プロジェクト Usersページの"Last Login"に相当）。
      // audit_log全体のMAX(created_at)なのでClaudeプロキシ利用も含む（keyAdmin.ts参照）。
      const lastActiveCell = document.createElement("td");
      lastActiveCell.textContent = k.last_active ? new Date(k.last_active * 1000).toLocaleString() : "利用履歴なし";
      tr.appendChild(lastActiveCell);

      // 有効期限列: 表示＋インライン変更用select（2026-09-12追加）。期限切れ・
      // 期限間近（7日以内）は警告バッジで目立たせる（healthCheck.tsの日次アラートと
      // 同じ判定基準に揃えている）。
      const expiryCell = document.createElement("td");
      const nowSec = Math.floor(Date.now() / 1000);
      if (k.expires_at) {
        const badge = document.createElement("span");
        const daysLeft = Math.ceil((k.expires_at - nowSec) / 86400);
        if (daysLeft < 0) {
          badge.className = "role-badge"; badge.style.color = "var(--bad)"; badge.style.borderColor = "var(--bad)";
          badge.textContent = "期限切れ";
        } else if (daysLeft <= 7) {
          badge.className = "role-badge"; badge.style.color = "var(--highlight)"; badge.style.borderColor = "var(--highlight)";
          badge.textContent = "あと" + daysLeft + "日";
        } else {
          badge.className = "role-badge";
          badge.textContent = new Date(k.expires_at * 1000).toLocaleDateString();
        }
        expiryCell.appendChild(badge);
      } else {
        const span = document.createElement("span");
        span.className = "hint";
        span.textContent = "無期限";
        expiryCell.appendChild(span);
      }
      const expirySelect = document.createElement("select");
      expirySelect.className = "role-select";
      expirySelect.style.marginLeft = ".4rem";
      [["0", "無期限"], ["30", "30日"], ["90", "90日"], ["180", "180日"], ["365", "1年"]].forEach(([v, label]) => {
        const opt = document.createElement("option");
        opt.value = v; opt.textContent = label;
        expirySelect.appendChild(opt);
      });
      expirySelect.addEventListener("change", async () => {
        const days = Number(expirySelect.value);
        try {
          await api("/admin/keys/set-expiry", { userId: k.user_id, expiresInDays: days || null });
          showToast(k.display_name + " の有効期限を更新しました", "success");
          loadKeys();
        } catch (e) {
          showToast("有効期限の変更に失敗しました: " + e.message, "error");
        }
      });
      expiryCell.appendChild(expirySelect);
      tr.appendChild(expiryCell);

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
  }

  function applyKeysFilter() {
    const q = $("keysSearch").value.trim().toLowerCase();
    const roleFilter = $("keysRoleFilter").value;
    const filtered = allKeysCache.filter((k) => {
      if (roleFilter && k.role !== roleFilter) return false;
      if (q && !k.display_name.toLowerCase().includes(q)) return false;
      return true;
    });
    renderKeysTable(filtered);
  }
  $("keysSearch").addEventListener("input", applyKeysFilter);
  $("keysRoleFilter").addEventListener("change", applyKeysFilter);

  // ユーザー概要KPI（別プロジェクト Usersページの「総ユーザー数/管理者数/編集者数/
  // ナレッジ登録者数」に相当、2026-09-10追加）。
  function renderUsersOverviewKpis(keys) {
    const box = $("usersOverviewKpis");
    box.innerHTML = "";
    const counts = { admin: 0, editor: 0, member: 0, guest: 0 };
    keys.forEach((k) => { counts[k.role] = (counts[k.role] || 0) + 1; });
    box.appendChild(kpiCard("総キー数", keys.length));
    box.appendChild(kpiCard("管理者", counts.admin));
    box.appendChild(kpiCard("編集者", counts.editor));
    box.appendChild(kpiCard("一般ユーザー", counts.member + counts.guest));
  }

  async function loadKeys() {
    const tbody = $("keysTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=9>読み込み中…</td></tr>";
    try {
      const data = await api("/admin/keys/list", {});
      allKeysCache = data.keys;
      renderUsersOverviewKpis(data.keys);
      applyKeysFilter();
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan=8>取得に失敗しました: ' + e.message + '</td></tr>';
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
        // 個人namespaceはID（APIキーのハッシュ値）だけでは誰のものか判別できないため、
        // 発行時の表示名があれば併記する（2026-09-10フィードバック）。
        const label = n.display_name ? n.display_name + "（" + n.namespace_id + "）" : n.namespace_id;
        const tr = appendRow(tbody, [label, n.scope, n.owner_user_id || "-"]);
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

  // ---------- 管理タブ：namespace別トークン予算・使用量（2026-09-12追加） ----------
  let lastNsUsage = [];
  async function loadNamespaceUsage() {
    const tbody = $("nsUsageTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=5>読み込み中…</td></tr>";
    const days = Number($("nsUsageDays").value) || 30;
    try {
      const data = await api("/admin/namespaces/usage", { days });
      lastNsUsage = data.namespaces;
      tbody.innerHTML = "";
      if (data.namespaces.length === 0) {
        tbody.innerHTML = '<tr><td colspan=5>この期間の利用はありません</td></tr>';
        return;
      }
      data.namespaces.forEach((n) => {
        const tr = appendRow(tbody, [n.namespace, n.used.toLocaleString()]);

        const budgetCell = document.createElement("td");
        budgetCell.textContent = n.tokenBudget != null ? n.tokenBudget.toLocaleString() : "未設定";
        tr.appendChild(budgetCell);

        const statusCell = document.createElement("td");
        if (n.tokenBudget == null) {
          statusCell.textContent = "-";
        } else if (n.overBudget) {
          const badge = document.createElement("span");
          badge.className = "role-badge";
          badge.style.color = "var(--bad)";
          badge.style.borderColor = "var(--bad)";
          badge.textContent = "超過";
          statusCell.appendChild(badge);
        } else {
          const badge = document.createElement("span");
          badge.className = "role-badge editor";
          badge.textContent = "OK";
          statusCell.appendChild(badge);
        }
        tr.appendChild(statusCell);

        const setCell = document.createElement("td");
        tr.appendChild(setCell);
        const budgetInput = document.createElement("input");
        budgetInput.type = "number";
        budgetInput.min = "0";
        budgetInput.style.width = "90px";
        if (n.tokenBudget != null) budgetInput.value = n.tokenBudget;
        const setBtn = document.createElement("button");
        setBtn.className = "btn"; setBtn.textContent = "設定";
        setBtn.style.marginLeft = ".3rem";
        setBtn.onclick = async () => {
          const v = budgetInput.value.trim();
          try {
            await api("/admin/namespaces/set-budget", { namespaceId: n.namespace, tokenBudget: v === "" ? null : Number(v) });
            showToast(n.namespace + " の予算を更新しました", "success");
            loadNamespaceUsage();
          } catch (e) { showToast("設定に失敗しました: " + e.message, "error"); }
        };
        setCell.appendChild(budgetInput);
        setCell.appendChild(setBtn);
      });
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan=5>取得に失敗しました: ' + e.message + '</td></tr>';
    }
  }
  $("refreshNsUsage").addEventListener("click", loadNamespaceUsage);
  $("nsUsageDays").addEventListener("change", loadNamespaceUsage);
  $("exportNsUsageCsv").addEventListener("click", () => {
    if (lastNsUsage.length === 0) { showToast("エクスポートするデータがありません", "error"); return; }
    downloadCsv(
      "namespace-usage-" + new Date().toISOString().slice(0, 10) + ".csv",
      ["namespace", "使用量（概算）", "予算", "超過"],
      lastNsUsage.map((n) => [n.namespace, n.used, n.tokenBudget ?? "", n.overBudget ? "超過" : "OK"]),
    );
  });

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
      loadKbHistory(); loadKbOverview();
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
      loadKbHistory(); loadKbOverview();
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

  // ---------- 管理タブ：連携（Jira/Backlog/Googleカレンダー/Googleマップ、2026-09-17追加） ----------
  // Notion/Drive同期のrunSync()と同じバッチポーリングだが、対象IDやレスポンスの
  // 件数フィールド名（totalPages/totalFiles/totalIssues/totalEvents）が呼び出し先ごとに
  // 違うため、専用の汎用版を用意する（既存のrunSync自体は変更しない）。
  async function runIntegrationSync(opts) {
    const namespace = $(opts.namespaceId).value.trim();
    if (!namespace) { showToast("namespaceを入力してください", "error"); return; }
    const progressEl = $(opts.progressId);
    const retryBtn = opts.retryBtnId ? $(opts.retryBtnId) : null;
    if (retryBtn) retryBtn.disabled = true;
    let opId = null, startIndex = 0, totalDocs = 0, totalChunks = 0, errorCount = 0;
    progressEl.textContent = "同期中…";
    try {
      while (true) {
        const body = { namespace, startIndex, batchSize: opts.batchSize };
        if (opId) body.opId = opId;
        const data = await api(opts.endpoint, body);
        opId = data.opId;
        totalDocs += data.documents;
        totalChunks += data.chunks;
        (data.results || []).forEach((r) => { if (r.status === "error") errorCount++; });
        const total = data.totalPages ?? data.totalFiles ?? data.totalIssues ?? data.totalEvents ?? "?";
        const last = data.results && data.results.length > 0 ? data.results[data.results.length - 1] : null;
        const lastMark = last ? (last.status === "ok" ? "✅" : last.status === "skipped" ? "⏭️" : "⚠️") : "";
        const lastLine = last ? "\\n直前: " + lastMark + " " + last.file + "（" + last.detail + "）" : "";
        progressEl.textContent = "進捗: " + data.processedRange[1] + "/" + total + "（累計 " + totalDocs + "件・" + totalChunks + "チャンク）" + lastLine;
        if (data.nextIndex === null || data.nextIndex === undefined) break;
        startIndex = data.nextIndex;
      }
      const failNote = errorCount > 0 ? "（失敗 " + errorCount + "件）" : "";
      progressEl.textContent = "完了: " + totalDocs + "件・" + totalChunks + "チャンク登録" + failNote;
      if (retryBtn) retryBtn.disabled = errorCount === 0;
      loadKbOverview();
      return opId;
    } catch (e) {
      progressEl.textContent = "エラー: " + e.message;
      if (retryBtn) retryBtn.disabled = !opId;
      return opId;
    }
  }

  async function runIntegrationRetry(opts, opId) {
    if (!opId) return;
    const namespace = $(opts.namespaceId).value.trim();
    const progressEl = $(opts.progressId);
    const retryBtn = $(opts.retryBtnId);
    retryBtn.disabled = true;
    progressEl.textContent = "失敗課題を再同期中…";
    try {
      const data = await api(opts.retryEndpoint, { namespace, opId });
      const remainingErrors = (data.results || []).filter((r) => r.status === "error").length;
      progressEl.textContent = "再同期完了: " + data.documents + "件・" + data.chunks + "チャンク登録" + (remainingErrors > 0 ? "（依然失敗 " + remainingErrors + "件）" : "");
      retryBtn.disabled = remainingErrors === 0;
      loadKbOverview();
    } catch (e) {
      progressEl.textContent = "エラー: " + e.message;
      retryBtn.disabled = false;
    }
  }

  // 接続テストボタン共通処理（2026-09-19追加）: 「連携」タブで設定ミスに同期実行前に
  // 気づけるようにするための軽量な疎通確認（実際の登録は行わない）。
  function wireTestConnectionBtn(btnId, resultId, endpoint, buildBody) {
    $(btnId).addEventListener("click", async () => {
      $(resultId).textContent = "確認中…";
      try {
        const data = await api(endpoint, buildBody ? buildBody() : {});
        $(resultId).textContent = data.message || "接続成功";
      } catch (e) {
        $(resultId).textContent = "エラー: " + e.message;
      }
    });
  }

  // 「解除」ボタン共通処理: 連携を外す（設定値をクリアする）。誤操作対策で確認ダイアログを挟む。
  function wireClearSourceBtn(btnId, namespaceId, fieldInputId, clearFieldName) {
    $(btnId).addEventListener("click", async () => {
      const namespace = $(namespaceId).value.trim();
      if (!namespace) { showToast("namespaceを入力してください", "error"); return; }
      if (!confirm("この連携を解除しますか？（登録済みのドキュメントは削除されません）")) return;
      try {
        await api("/admin/kb/set-source", { namespace, [clearFieldName]: true });
        $(fieldInputId).value = "";
        showToast("連携を解除しました", "success");
      } catch (e) { showToast("解除に失敗しました: " + e.message, "error"); }
    });
  }

  // 「候補を取得」ボタン共通処理（2026-09-23追加）: OAuth・従来方式どちらの認証でも、接続済みの
  // 認証情報でプロバイダのAPIを叩き、見えるプロジェクト/カレンダー一覧をドロップダウンに表示する。
  // プロジェクトキーやカレンダーIDの手入力を無くし、Claudeのコネクタのような「接続したら選ぶだけ」
  // に近づけるための機能。手入力欄自体は削除せず残す（一覧取得に失敗した場合の後方互換フォールバック。
  // 特にGoogleカレンダーのサービスアカウント方式は、共有されたカレンダーが必ずしも一覧APIに
  // 出てこないことがあるため）。extraParamsは/admin/kb/test-connection/calendar同様、
  // namespace等を追加送信したい場合に使う。
  function wireResourcePicker(loadBtnId, selectId, targetInputId, endpoint, mapItem, extraParams) {
    $(loadBtnId).addEventListener("click", async () => {
      const select = $(selectId);
      select.innerHTML = '<option value="">読み込み中…</option>';
      try {
        const data = await api(endpoint, extraParams ? extraParams() : {});
        const items = mapItem(data);
        select.innerHTML = "";
        if (items.length === 0) {
          select.innerHTML = '<option value="">候補が見つかりませんでした（手入力してください）</option>';
          return;
        }
        const placeholder = document.createElement("option");
        placeholder.value = ""; placeholder.textContent = "候補を選択（" + items.length + "件）";
        select.appendChild(placeholder);
        items.forEach((it) => {
          const opt = document.createElement("option");
          opt.value = it.value; opt.textContent = it.label;
          select.appendChild(opt);
        });
      } catch (e) {
        select.innerHTML = '<option value="">取得に失敗しました（手入力してください）</option>';
        showToast("候補の取得に失敗しました: " + e.message, "error");
      }
    });
    $(selectId).addEventListener("change", () => {
      const v = $(selectId).value;
      if (v) $(targetInputId).value = v;
    });
  }
  wireResourcePicker("jiraLoadProjectsBtn", "jiraProjectPicker", "jiraProjectKey", "/admin/jira/list-projects",
    (data) => data.projects.map((p) => ({ value: p.key, label: p.key + " - " + p.name })));
  wireResourcePicker("backlogLoadProjectsBtn", "backlogProjectPicker", "backlogProjectId", "/admin/backlog/list-projects",
    (data) => data.projects.map((p) => ({ value: p.key, label: p.key + " - " + p.name })));
  wireResourcePicker("calendarLoadListBtn", "calendarPicker", "calendarId", "/admin/calendar/list-calendars",
    (data) => data.calendars.map((c) => ({ value: c.id, label: c.summary + " (" + c.id + ")" })));

  $("jiraSetSourceBtn").addEventListener("click", async () => {
    try {
      await api("/admin/kb/set-source", {
        namespace: $("jiraNamespace").value.trim(),
        jiraProjectKey: $("jiraProjectKey").value.trim() || undefined,
        jiraExtraJql: $("jiraExtraJql").value.trim() || undefined,
      });
      showToast("同期元を設定しました", "success");
    } catch (e) { showToast("設定に失敗しました: " + e.message, "error"); }
  });
  wireClearSourceBtn("jiraClearBtn", "jiraNamespace", "jiraProjectKey", "clearJira");
  wireTestConnectionBtn("jiraTestConnectionBtn", "jiraSyncProgress", "/admin/kb/test-connection/jira");
  let lastJiraOpId = null;
  const jiraOpts = { namespaceId: "jiraNamespace", progressId: "jiraSyncProgress", retryBtnId: "jiraRetryFailedBtn", endpoint: "/admin/sync/jira", retryEndpoint: "/admin/sync/jira/retry-failed", batchSize: 10 };
  $("jiraSyncBtn").addEventListener("click", async () => { lastJiraOpId = await runIntegrationSync(jiraOpts); });
  $("jiraRetryFailedBtn").addEventListener("click", () => runIntegrationRetry(jiraOpts, lastJiraOpId));

  $("backlogSetSourceBtn").addEventListener("click", async () => {
    try {
      await api("/admin/kb/set-source", {
        namespace: $("backlogNamespace").value.trim(),
        backlogProjectId: $("backlogProjectId").value.trim() || undefined,
        backlogKeywordFilter: $("backlogKeywordFilter").value.trim() || undefined,
      });
      showToast("同期元を設定しました", "success");
    } catch (e) { showToast("設定に失敗しました: " + e.message, "error"); }
  });
  wireClearSourceBtn("backlogClearBtn", "backlogNamespace", "backlogProjectId", "clearBacklog");
  wireTestConnectionBtn("backlogTestConnectionBtn", "backlogSyncProgress", "/admin/kb/test-connection/backlog");
  let lastBacklogOpId = null;
  const backlogOpts = { namespaceId: "backlogNamespace", progressId: "backlogSyncProgress", retryBtnId: "backlogRetryFailedBtn", endpoint: "/admin/sync/backlog", retryEndpoint: "/admin/sync/backlog/retry-failed", batchSize: 10 };
  $("backlogSyncBtn").addEventListener("click", async () => { lastBacklogOpId = await runIntegrationSync(backlogOpts); });
  $("backlogRetryFailedBtn").addEventListener("click", () => runIntegrationRetry(backlogOpts, lastBacklogOpId));

  $("calendarSetSourceBtn").addEventListener("click", async () => {
    try {
      await api("/admin/kb/set-source", {
        namespace: $("calendarNamespace").value.trim(),
        calendarId: $("calendarId").value.trim() || undefined,
      });
      showToast("同期元を設定しました", "success");
    } catch (e) { showToast("設定に失敗しました: " + e.message, "error"); }
  });
  wireClearSourceBtn("calendarClearBtn", "calendarNamespace", "calendarId", "clearCalendar");
  wireTestConnectionBtn("calendarTestConnectionBtn", "calendarSyncProgress", "/admin/kb/test-connection/calendar", () => ({ namespace: $("calendarNamespace").value.trim() }));
  let lastCalendarOpId = null;
  const calendarOpts = { namespaceId: "calendarNamespace", progressId: "calendarSyncProgress", retryBtnId: "calendarRetryFailedBtn", endpoint: "/admin/sync/calendar", retryEndpoint: "/admin/sync/calendar/retry-failed", batchSize: 10 };
  $("calendarSyncBtn").addEventListener("click", async () => { lastCalendarOpId = await runIntegrationSync(calendarOpts); });
  $("calendarRetryFailedBtn").addEventListener("click", () => runIntegrationRetry(calendarOpts, lastCalendarOpId));

  wireTestConnectionBtn("mapsTestConnectionBtn", "mapsTestConnectionResult", "/admin/kb/test-connection/maps");

  $("mapsImportBtn").addEventListener("click", async () => {
    const namespace = $("mapsNamespace").value.trim();
    const query = $("mapsQuery").value.trim();
    if (!namespace || !query) { $("mapsImportResult").textContent = "namespaceと場所名・住所を入力してください"; return; }
    $("mapsImportResult").textContent = "検索中…";
    try {
      const data = await api("/admin/kb/import-place", { namespace, query });
      $("mapsImportResult").textContent = "登録しました: " + data.title + "（" + data.chunks + "チャンク）";
      loadKbOverview();
    } catch (e) {
      $("mapsImportResult").textContent = "エラー: " + e.message;
    }
  });

  // ---------- Googleマップ 複数件一括登録（2026-09-19追加、qaCsvImportBtnと同じ方式） ----------
  $("mapsCsvImportBtn").addEventListener("click", async () => {
    const namespace = $("mapsCsvNamespace").value.trim();
    const queriesText = $("mapsCsvText").value;
    if (!namespace || !queriesText.trim()) { $("mapsCsvProgress").textContent = "namespaceと場所のリストを入力してください"; return; }
    const progressEl = $("mapsCsvProgress");
    let opId = null, startIndex = 0, totalDocs = 0, totalChunks = 0, errorCount = 0;
    progressEl.textContent = "登録中…";
    try {
      while (true) {
        const body = { namespace, queriesText, startIndex, batchSize: 5 };
        if (opId) body.opId = opId;
        const data = await api("/admin/kb/import-places-csv", body);
        opId = data.opId;
        totalDocs += data.documents;
        totalChunks += data.chunks;
        (data.results || []).forEach((r) => { if (r.status === "error") errorCount++; });
        progressEl.textContent = "進捗: " + data.processedRange[1] + "/" + data.totalQueries + "（累計 " + totalDocs + "件・" + totalChunks + "チャンク）";
        if (data.nextIndex === null || data.nextIndex === undefined) break;
        startIndex = data.nextIndex;
      }
      const failNote = errorCount > 0 ? "（失敗 " + errorCount + "件）" : "";
      progressEl.textContent = "完了: " + totalDocs + "件・" + totalChunks + "チャンク登録" + failNote;
      loadKbHistory(); loadKbOverview();
    } catch (e) {
      progressEl.textContent = "エラー: " + e.message;
    }
  });

  $("integrationsTestAlertBtn").addEventListener("click", async () => {
    $("integrationsTestAlertResult").textContent = "送信中…";
    try {
      const data = await api("/admin/health/test-alert", {});
      $("integrationsTestAlertResult").textContent = "Slack: " + data.results.slack + " / Gmail: " + data.results.gmail;
    } catch (e) {
      $("integrationsTestAlertResult").textContent = "エラー: " + e.message;
    }
  });

  // ---------- OAuthクリック接続化（Jira/Backlog/Googleカレンダー/Slack、2026-09-22追加） ----------
  // OAuth開始エンドポイントはブラウザの直接ナビゲーション（別タブ扱いにはせず、そのまま
  // 遷移してコールバック後に自動で戻ってくる）で叩く必要があり、fetch()のような
  // Authorizationヘッダー付き呼び出しができない。そのため、既にlocalStorageに保存済みの
  // APIキーをこの一回だけクエリパラメータとして渡す（oauthConnections.ts参照）。
  function startOAuthConnect(service, extraParams) {
    const key = (apiKeyEl.value || localStorage.getItem("ragPocApiKey") || "").trim();
    if (!key) { showToast("先にAPIキーを入力してください", "error"); return; }
    let url = "/admin/oauth/" + service + "/start?key=" + encodeURIComponent(key);
    if (extraParams) {
      for (const k in extraParams) url += "&" + k + "=" + encodeURIComponent(extraParams[k]);
    }
    window.location.href = url;
  }

  async function loadOAuthStatus() {
    const services = [
      { key: "jira", statusId: "jiraOAuthStatus", connectId: "jiraConnectBtn", disconnectId: "jiraDisconnectBtn" },
      { key: "backlog", statusId: "backlogOAuthStatus", connectId: "backlogConnectBtn", disconnectId: "backlogDisconnectBtn" },
      { key: "google_calendar", statusId: "calendarOAuthStatus", connectId: "calendarConnectBtn", disconnectId: "calendarDisconnectBtn" },
      { key: "slack", statusId: "slackOAuthStatus", connectId: "slackConnectBtn", disconnectId: "slackDisconnectBtn" },
    ];
    try {
      const data = await api("/admin/oauth/status", {});
      services.forEach((s) => {
        const info = data[s.key];
        const statusEl = $(s.statusId);
        const connectBtn = $(s.connectId);
        const disconnectBtn = $(s.disconnectId);
        if (!statusEl) return; // 念のためのnullガード（通常はどのロールでもDOM自体は常に存在する）
        if (info && info.connected) {
          statusEl.textContent = "✅ 接続済み" + (info.label ? "（" + info.label + "）" : "");
          statusEl.style.color = "#15846e";
          if (connectBtn) connectBtn.style.display = "none";
          if (disconnectBtn) disconnectBtn.style.display = "";
        } else {
          statusEl.textContent = "未接続";
          statusEl.style.color = "";
          if (connectBtn) connectBtn.style.display = "";
          if (disconnectBtn) disconnectBtn.style.display = "none";
        }
      });
    } catch (e) {
      services.forEach((s) => { if ($(s.statusId)) $(s.statusId).textContent = "確認に失敗しました: " + e.message; });
    }
  }

  $("jiraConnectBtn").addEventListener("click", () => startOAuthConnect("jira"));
  $("jiraDisconnectBtn").addEventListener("click", async () => {
    if (!confirm("Jiraとの接続を解除しますか？")) return;
    try { await api("/admin/oauth/jira/disconnect", {}); showToast("解除しました", "success"); loadOAuthStatus(); }
    catch (e) { showToast("解除に失敗しました: " + e.message, "error"); }
  });

  $("backlogConnectBtn").addEventListener("click", () => {
    const space = $("backlogSpaceInput").value.trim();
    if (!space) { showToast("スペースURLを入力してください", "error"); return; }
    startOAuthConnect("backlog", { space });
  });
  $("backlogDisconnectBtn").addEventListener("click", async () => {
    if (!confirm("Backlogとの接続を解除しますか？")) return;
    try { await api("/admin/oauth/backlog/disconnect", {}); showToast("解除しました", "success"); loadOAuthStatus(); }
    catch (e) { showToast("解除に失敗しました: " + e.message, "error"); }
  });

  $("calendarConnectBtn").addEventListener("click", () => startOAuthConnect("google_calendar"));
  $("calendarDisconnectBtn").addEventListener("click", async () => {
    if (!confirm("Googleカレンダーとの接続を解除しますか？")) return;
    try { await api("/admin/oauth/google_calendar/disconnect", {}); showToast("解除しました", "success"); loadOAuthStatus(); }
    catch (e) { showToast("解除に失敗しました: " + e.message, "error"); }
  });

  $("slackConnectBtn").addEventListener("click", () => startOAuthConnect("slack"));
  $("slackDisconnectBtn").addEventListener("click", async () => {
    if (!confirm("Slackとの接続を解除しますか？")) return;
    try { await api("/admin/oauth/slack/disconnect", {}); showToast("解除しました", "success"); loadOAuthStatus(); }
    catch (e) { showToast("解除に失敗しました: " + e.message, "error"); }
  });

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

  // ---------- 管理タブ：namespaceごとのナレッジ登録状況（2026-09-10追加） ----------
  async function loadKbOverview() {
    const tbody = $("kbOverviewTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=5>読み込み中…</td></tr>";
    try {
      const data = await api("/admin/kb/overview", {});
      tbody.innerHTML = "";
      if (data.namespaces.length === 0) {
        tbody.innerHTML = '<tr><td colspan=5>登録されたナレッジがありません</td></tr>';
        return;
      }
      data.namespaces.forEach((n) => {
        const sources = [];
        if (n.hasNotionSource) sources.push("Notion");
        if (n.hasDriveSource) sources.push("Drive");
        if (n.hasJiraSource) sources.push("Jira");
        if (n.hasBacklogSource) sources.push("Backlog");
        if (n.hasCalendarSource) sources.push("カレンダー");
        const sourceLabel = sources.length > 0 ? sources.join("・") : "手動登録のみ";
        const lastUpdated = n.lastUpdated ? new Date(n.lastUpdated * 1000).toLocaleString() : "-";
        appendRow(tbody, [n.namespace, n.fileCount, n.chunkCount, sourceLabel, lastUpdated]);
      });
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan=5>取得に失敗しました: ' + e.message + '</td></tr>';
    }
  }
  $("refreshKbOverview").addEventListener("click", loadKbOverview);

  // ---------- 管理タブ：重複コンテンツの確認・削除（2026-09-15追加） ----------
  async function checkDuplicateDocs() {
    const namespace = $("dupCheckNamespace").value.trim();
    if (!namespace) { $("dupCheckResult").textContent = "namespaceを入力してください"; return; }
    $("dupCheckResult").textContent = "確認中…";
    $("dupCheckGroups").innerHTML = "";
    try {
      const data = await api("/admin/kb/find-duplicates", { namespace });
      if (data.groups.length === 0) {
        $("dupCheckResult").textContent = "重複しているドキュメントは見つかりませんでした";
        return;
      }
      $("dupCheckResult").textContent = data.groups.length + "組の重複が見つかりました。残すファイル以外を削除してください。";
      data.groups.forEach((group) => {
        const wrap = document.createElement("div");
        wrap.className = "table-scroll";
        wrap.style.marginTop = ".6rem";
        const table = document.createElement("table");
        table.className = "admin-table";
        table.innerHTML = "<thead><tr><th>ファイル名（重複組）</th><th></th></tr></thead>";
        const tbody = document.createElement("tbody");
        // group.filesはfile名（未検証の外部由来文字列）なので、docListTableと同様
        // appendRow経由でtextContent挿入する（stored XSS対策）。
        group.files.forEach((file) => {
          const tr = appendRow(tbody, [file, ""]);
          const delBtn = document.createElement("button");
          delBtn.className = "btn danger";
          delBtn.textContent = "削除";
          delBtn.addEventListener("click", async () => {
            if (!confirm(file + " を削除しますか？（元に戻せません）")) return;
            delBtn.disabled = true;
            try {
              const delData = await api("/admin/kb/delete-document", { namespace, file });
              showToast(file + " を削除しました（" + delData.deletedChunks + "チャンク）", "success");
              tr.remove();
              loadKbOverview();
            } catch (e) {
              showToast("削除に失敗しました: " + e.message, "error");
              delBtn.disabled = false;
            }
          });
          tr.lastElementChild.appendChild(delBtn);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        $("dupCheckGroups").appendChild(wrap);
      });
    } catch (e) {
      $("dupCheckResult").textContent = "取得に失敗しました: " + e.message;
    }
  }
  $("dupCheckBtn").addEventListener("click", checkDuplicateDocs);

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

  // ---------- 管理タブ：Houdiniチュートリアルの評価（2026-10-05追加） ----------
  // 評価者が書いたメモ等は外部入力なので、必ずtextContentで描画する（innerHTMLに入れない）。
  let lastTutorialFeedback = [];
  function feedbackPct(rate) { return rate == null ? "-" : Math.round(rate * 100) + "%"; }
  function feedbackNum(v, digits, prefix) { return v == null ? "-" : (prefix || "") + Number(v).toFixed(digits); }
  function fillFeedbackBuckets(tableId, buckets) {
    const tbody = $(tableId).querySelector("tbody");
    tbody.innerHTML = "";
    if (buckets.length === 0) { tbody.innerHTML = "<tr><td colspan=7>データがありません</td></tr>"; return; }
    buckets.forEach((b) => {
      appendRow(tbody, [b.key, b.total, b.good + " / " + b.bad, feedbackPct(b.goodRate),
        feedbackNum(b.avgIterations, 1), feedbackNum(b.avgCostUsd, 3, "$"), feedbackNum(b.avgCookErrors, 1)]);
    });
  }
  function feedbackMetricsText(m) {
    const parts = [];
    if (m.iterations != null) parts.push("反復 " + m.iterations);
    if (m.cost_usd != null) parts.push("$" + Number(m.cost_usd).toFixed(3));
    if (m.cook_errors != null) parts.push("cookエラー " + m.cook_errors);
    if (m.completed === false) parts.push("打ち切り");
    if (m.domain && m.domain !== "general") parts.push(m.domain);
    return parts.join(" / ") || "-";
  }
  async function loadTutorialFeedback() {
    const tbody = $("tutorialFeedbackTable").querySelector("tbody");
    tbody.innerHTML = "<tr><td colspan=8>読み込み中…</td></tr>";
    const days = Number($("tutorialFeedbackDays").value) || 90;
    const ratingValue = $("tutorialFeedbackRating").value;
    try {
      const [stats, list] = await Promise.all([
        api("/admin/tutorial-feedback/stats", { days }),
        api("/admin/tutorial-feedback/list", {
          days,
          limit: 200,
          rating: ratingValue ? Number(ratingValue) : undefined,
          user: $("tutorialFeedbackUser").value.trim() || undefined,
        }),
      ]);
      const kpis = $("tutorialFeedbackKpis");
      kpis.innerHTML = "";
      kpis.appendChild(kpiCard("評価件数", stats.total));
      kpis.appendChild(kpiCard("好評率", feedbackPct(stats.goodRate), "良い " + stats.good + " / 悪い " + stats.bad));
      fillFeedbackBuckets("tutorialFeedbackByModel", stats.byModel);
      fillFeedbackBuckets("tutorialFeedbackByLevel", stats.byLevel);
      fillFeedbackBuckets("tutorialFeedbackByDomain", stats.byDomain);
      fillFeedbackBuckets("tutorialFeedbackByTag", stats.byTag);
      lastTutorialFeedback = list.entries;
      tbody.innerHTML = "";
      if (list.entries.length === 0) { tbody.innerHTML = "<tr><td colspan=8>該当する評価がありません</td></tr>"; return; }
      list.entries.forEach((e) => {
        const tr = appendRow(tbody, [
          new Date(e.updatedAt * 1000).toLocaleString(),
          e.displayName || e.userId.slice(0, 8),
          e.rating === 1 ? "良い" : "悪い",
          e.title || e.tutorialKey,
          (e.model || "-") + " / " + (e.level || "-"),
          e.tags.join(", ") || "-",
          e.note || "-",
          feedbackMetricsText(e.metrics),
        ]);
        // 長い文字列はホバーで全文を確認できるようにする
        tr.children[3].title = (e.topic ? "トピック: " + e.topic + String.fromCharCode(10) : "") + (e.overview || "");
        tr.children[6].title = e.note || "";
      });
    } catch (err) {
      tbody.innerHTML = "<tr><td colspan=8>取得に失敗しました: " + err.message + "</td></tr>";
    }
  }
  $("refreshTutorialFeedback").addEventListener("click", loadTutorialFeedback);
  $("tutorialFeedbackDays").addEventListener("change", loadTutorialFeedback);
  $("tutorialFeedbackRating").addEventListener("change", loadTutorialFeedback);
  $("exportTutorialFeedbackCsv").addEventListener("click", () => {
    if (lastTutorialFeedback.length === 0) { showToast("エクスポートする評価がありません", "error"); return; }
    downloadCsv(
      "tutorial-feedback-" + new Date().toISOString().slice(0, 10) + ".csv",
      ["日時", "ユーザー", "評価", "題名", "トピック", "モデル", "レベル", "ナレッジ", "タグ", "メモ", "反復", "コスト(USD)", "cookエラー", "領域"],
      lastTutorialFeedback.map((e) => [
        new Date(e.updatedAt * 1000).toLocaleString(), e.displayName || e.userId.slice(0, 8),
        e.rating === 1 ? "good" : "bad", e.title, e.topic, e.model || "", e.level || "", e.ragName || "",
        e.tags.join("; "), e.note, e.metrics.iterations ?? "", e.metrics.cost_usd ?? "", e.metrics.cook_errors ?? "", e.metrics.domain ?? "",
      ]),
    );
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

  // ---------- 共通：ポップアップ（モーダル、2026-10-08追加） ----------
  // 別プロジェクトのAddKnowledgeModal / SystemConnectionModalを参考にした。Escと背景クリックで
  // 閉じる・Tabキーの循環・閉じたら元のフォーカスへ戻す。処理中（setLocked）は閉じられない。
  function mk(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function openModal(options) {
    const previous = document.activeElement;
    const backdrop = mk("div", "modal-backdrop");
    const dialog = mk("section", "modal" + (options.wide ? " wide" : ""));
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.tabIndex = -1;
    const header = mk("div", "modal-header");
    const titles = mk("div");
    const heading = mk("h3", "", options.title || "");
    const sub = mk("p", "hint", options.subtitle || "");
    sub.style.margin = "0";
    titles.appendChild(heading);
    titles.appendChild(sub);
    const closeBtn = mk("button", "modal-close", "✕");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "閉じる");
    header.appendChild(titles);
    header.appendChild(closeBtn);
    const body = mk("div", "modal-body");
    const footer = mk("div", "modal-footer");
    dialog.appendChild(header);
    dialog.appendChild(body);
    dialog.appendChild(footer);
    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    let locked = false;
    const handle = {
      body, footer, dialog, alive: true,
      setTitle(text) { heading.textContent = text; },
      setSubtitle(text) { sub.textContent = text; },
      setLocked(value) { locked = value; closeBtn.style.visibility = value ? "hidden" : "visible"; },
      close() {
        if (!handle.alive) return;
        handle.alive = false;
        backdrop.remove();
        document.body.style.overflow = overflow;
        if (previous && previous.focus) previous.focus();
        if (options.onClose) options.onClose();
      },
    };
    closeBtn.addEventListener("click", () => { if (!locked) handle.close(); });
    backdrop.addEventListener("mousedown", (event) => { if (event.target === backdrop && !locked) handle.close(); });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !locked) { event.stopPropagation(); handle.close(); return; }
      if (event.key !== "Tab") return;
      const focusable = dialog.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex='0']");
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    dialog.focus();
    return handle;
  }

  function modalButton(label, className, onClick) {
    const button = mk("button", "btn" + (className ? " " + className : ""), label);
    button.type = "button";
    if (onClick) button.addEventListener("click", onClick);
    return button;
  }

  // ---------- チャット画像添付でも使う共通ヘルパー ----------
  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  // ---------- 管理タブ：ナレッジを追加（ポップアップ、2026-10-08追加） ----------
  // 以前は「URL手動登録」「再帰クロール」「YouTube」「ファイルアップロード」「FAQ単発」
  // 「QA CSV一括」が縦に並び、どれもnamespaceを毎回手入力していた。別プロジェクトの
  // 「ナレッジを追加」と同じ3ステップ（①方法と内容 → ②確認 → ③登録）のポップアップに統合し、
  // namespaceは選択式にした。複数ファイル・複数URL・複数Q&Aをまとめて登録でき、結果は1件ずつ表示する。
  const KB_NS_STORAGE = "ragPocKbNamespace";
  const KB_METHODS = [
    { key: "file", icon: "📄", title: "ファイル", description: "PDF・Word・PowerPoint・音声・動画" },
    { key: "url", icon: "🌐", title: "URL", description: "Webページ・サイト配下・YouTube" },
    { key: "qa", icon: "❓", title: "Q&A", description: "質問と回答を入力、またはCSV" },
  ];
  const KB_TIPS = {
    file: [
      "PDF・Word（.docx）・PowerPoint（.pptx）に対応しています",
      "音声・動画は自動で文字起こしされます（時間がかかることがあります）",
      "複数のファイルをまとめて追加できます",
    ],
    url: [
      "1行に1件、複数のURLをまとめて登録できます",
      "YouTubeのURLは字幕を自動で取得します",
      "「配下ページも含む」で同じサイト内のリンク先も登録できます（最大ページ数は自由に指定できます）",
      "再クロール時は「登録済みはスキップ」でAPIコストを抑えられます",
    ],
    qa: [
      "質問は簡潔に、回答は正確に書きましょう",
      "想定される質問は網羅的に洗い出しましょう",
      "CSV（1行目に question, answer の列名）で一括登録もできます",
    ],
  };
  const KB_AV_EXT = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".mov", ".webm", ".mkv", ".avi"];
  const KB_DOC_EXT = [".pdf", ".docx", ".pptx"];
  const KB_NL = String.fromCharCode(10);

  function kbExt(name) {
    const i = name.lastIndexOf(".");
    return i < 0 ? "" : name.slice(i).toLowerCase();
  }
  function kbFileAllowed(file) {
    const ext = kbExt(file.name);
    return KB_DOC_EXT.includes(ext) || KB_AV_EXT.includes(ext) || /^(audio|video)[/]/.test(file.type || "");
  }
  function kbFormatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  }
  function kbIsYoutube(url) {
    return /^https?:[/][/](www[.]|m[.])?(youtube[.]com|youtu[.]be)[/]/i.test(url);
  }
  function kbLooksLikeUrl(text) {
    return /^https?:[/][/][^ ]+$/i.test(text);
  }

  async function kbLoadNamespaces() {
    try {
      const data = await api("/me/namespaces", {});
      return (data.namespaces || []).slice().sort();
    } catch (e) {
      return [];
    }
  }

  // 1件の登録を実行して、画面に出す詳細文字列を返す。失敗は例外。
  async function kbRunItem(item, namespace, setDetail) {
    if (item.kind === "file") {
      setDetail("アップロード・変換中…");
      const fileBase64 = await readFileAsBase64(item.file);
      const data = await api("/admin/kb/upload-doc", { namespace, fileBase64, mimeType: item.file.type || "application/octet-stream", fileName: item.file.name });
      return data.chunks + "チャンク登録" + (data.skipped > 0 ? "（" + data.skipped + "件スキップ）" : "");
    }
    if (item.kind === "youtube") {
      setDetail("文字起こし中…（動画の長さによっては数十秒かかります）");
      const data = await api("/admin/kb/import-youtube", { namespace, youtubeUrl: item.url, title: item.title || undefined });
      return data.chunks + "チャンク登録" + (data.skipped > 0 ? "（" + data.skipped + "件スキップ）" : "");
    }
    if (item.kind === "url") {
      setDetail("取得・登録中…");
      const data = await api("/admin/kb/import-url", { namespace, url: item.url, title: item.title || undefined });
      return data.chunks + "チャンク登録" + (data.skipped > 0 ? "（" + data.skipped + "件スキップ）" : "");
    }
    if (item.kind === "crawl") {
      // サーバーが1リクエストで少数ページずつ処理するので、opIdで続きを呼び直す（Workers Freeプランの制限対策）
      let opId = null;
      let processed = 0, chunks = 0, errors = 0, skipped = 0, maxPages = item.options.maxPages, stopped = "";
      while (true) {
        const body = opId ? { opId } : {
          namespace, url: item.url, depth: item.options.depth, maxPages: item.options.maxPages,
          pathPrefix: item.options.pathPrefix || undefined, excludePatterns: item.options.excludePatterns || undefined,
          skipExisting: item.options.skipExisting,
        };
        const data = await api("/admin/kb/crawl-url", body);
        opId = data.opId;
        processed = data.processedCount;
        maxPages = data.maxPages;
        if (data.stoppedEarly) stopped = data.stoppedEarly;
        data.results.forEach((r) => {
          chunks += r.chunks;
          if (r.status === "error") errors++;
          if (r.status === "skipped_existing") skipped++;
        });
        setDetail("取得中… " + processed + "/" + maxPages + "ページ（" + chunks + "チャンク登録）");
        if (data.done) break;
      }
      const summary = processed + "ページ処理・" + chunks + "チャンク登録" + (skipped ? "・" + skipped + "件スキップ" : "") + (errors ? "・" + errors + "件エラー" : "") + "（opId: " + opId + "）" + (stopped ? " ※ " + stopped : "");
      if (processed > 0 && errors === processed) throw new Error("全ページの取得に失敗しました。" + summary);
      return summary;
    }
    if (item.kind === "faq") {
      setDetail("登録中…");
      const data = await api("/admin/kb/add-faq", { namespace, question: item.question, answer: item.answer, alsoWriteToNotion: item.alsoNotion });
      return data.chunks + "チャンク登録" + (data.notionPageId ? "（Notionページも作成）" : "");
    }
    if (item.kind === "csv") {
      let opId = null, startIndex = 0, docs = 0, chunks = 0;
      while (true) {
        const body = { namespace, csvText: item.csvText, startIndex, batchSize: 5 };
        if (opId) body.opId = opId;
        const data = await api("/admin/kb/import-qa-csv", body);
        opId = data.opId;
        docs += data.documents;
        chunks += data.chunks;
        setDetail("進捗: " + data.processedRange[1] + "/" + data.totalRows + "行");
        if (data.nextIndex === null || data.nextIndex === undefined) break;
        startIndex = data.nextIndex;
      }
      return docs + "件・" + chunks + "チャンク登録（opId: " + opId + "）";
    }
    throw new Error("未対応の種類です: " + item.kind);
  }

  async function openKnowledgeModal() {
    const modal = openModal({ title: "ナレッジを追加", subtitle: "登録先を選び、方法を選んで内容を入力してください", wide: true, onClose: () => { if (anyDone) refreshKnowledgeLists(); } });
    let anyDone = false;
    const S = {
      screen: "input", method: null, namespace: localStorage.getItem(KB_NS_STORAGE) || "", namespaces: [], customNs: false,
      files: [], urlText: "", urlTitle: "", crawl: false, depth: 1, maxPages: 30, pathPrefix: "", exclude: "", skipExisting: true,
      pairs: [{ question: "", answer: "" }], alsoNotion: false, csvName: "", csvText: "", csvRows: 0,
      items: [], status: [], detail: [], message: [], error: "", stop: false,
    };
    S.namespaces = await kbLoadNamespaces();
    if (!S.namespace || (S.namespaces.length > 0 && !S.namespaces.includes(S.namespace))) {
      S.namespace = S.namespaces.includes(S.namespace) ? S.namespace : (S.namespaces.find((n) => n.indexOf("shared:") === 0) || S.namespaces[0] || "");
    }
    if (S.namespaces.length === 0) S.customNs = true;

    function stepIndex() { return S.screen === "input" ? (S.method ? 1 : 0) : 2; }
    function addFiles(list) {
      const known = new Set(S.files.map((f) => f.name + ":" + f.size));
      const rejected = [];
      Array.from(list).forEach((file) => {
        if (!file.size) return;
        if (!kbFileAllowed(file)) { rejected.push(file.name); return; }
        if (!known.has(file.name + ":" + file.size)) S.files.push(file);
      });
      S.error = rejected.length ? "対応していない形式のため追加しませんでした: " + rejected.join(", ") : "";
      render();
    }
    function urlLines() {
      return S.urlText.split(KB_NL).map((line) => line.trim()).filter(Boolean);
    }
    function validPairs() { return S.pairs.filter((p) => p.question.trim() && p.answer.trim()); }
    function incompletePairs() { return S.pairs.filter((p) => (p.question.trim() || p.answer.trim()) && !(p.question.trim() && p.answer.trim())).length; }
    function canProceed() {
      if (!S.namespace.trim()) return false;
      if (S.method === "file") return S.files.length > 0;
      if (S.method === "url") return urlLines().length > 0;
      if (S.method === "qa") return validPairs().length > 0 || S.csvText.trim().length > 0;
      return false;
    }
    function buildItems() {
      if (S.method === "file") return S.files.map((file) => ({ kind: "file", icon: "📄", label: file.name + "（" + kbFormatSize(file.size) + "）", file }));
      if (S.method === "url") {
        const lines = urlLines();
        return lines.map((url) => {
          const title = lines.length === 1 ? S.urlTitle.trim() : "";
          if (kbIsYoutube(url)) return { kind: "youtube", icon: "▶️", label: url, url, title };
          if (S.crawl) {
            return { kind: "crawl", icon: "🕸️", label: url + "（配下ページも含む・最大" + S.maxPages + "ページ）", url,
              options: { depth: S.depth, maxPages: S.maxPages, pathPrefix: S.pathPrefix.trim(), excludePatterns: S.exclude.trim(), skipExisting: S.skipExisting } };
          }
          return { kind: "url", icon: "🌐", label: url, url, title };
        });
      }
      const items = validPairs().map((p) => ({ kind: "faq", icon: "❓", label: p.question.trim(), question: p.question.trim(), answer: p.answer.trim(), alsoNotion: S.alsoNotion }));
      if (S.csvText.trim()) items.push({ kind: "csv", icon: "📊", label: (S.csvName || "貼り付けたCSV") + "（約" + S.csvRows + "行）", csvText: S.csvText });
      return items;
    }

    async function startRun(onlyIndexes) {
      S.screen = "progress";
      S.stop = false;
      S.error = "";
      modal.setLocked(true);
      const targets = onlyIndexes || S.items.map((_, i) => i);
      targets.forEach((i) => { S.status[i] = "pending"; S.detail[i] = ""; S.message[i] = ""; });
      render();
      for (const index of targets) {
        if (S.stop) break;
        S.status[index] = "running";
        render();
        try {
          const result = await kbRunItem(S.items[index], S.namespace, (text) => { S.detail[index] = text; render(); });
          S.status[index] = "done";
          S.detail[index] = result;
          anyDone = true;
        } catch (e) {
          S.status[index] = "error";
          S.message[index] = e.message || String(e);
        }
        render();
      }
      targets.forEach((i) => { if (S.status[i] === "pending") S.status[i] = "skipped"; });
      S.screen = "done";
      modal.setLocked(false);
      render();
    }

    function renderStepper(parent) {
      const steps = mk("div", "modal-steps");
      ["登録方法の選択", "コンテンツの登録", "確認・実行"].forEach((label, i) => {
        const cls = i === stepIndex() ? " active" : i < stepIndex() ? " done" : "";
        const step = mk("div", "modal-step" + cls);
        step.appendChild(mk("span", "idx", String(i + 1)));
        step.appendChild(mk("span", "", label));
        steps.appendChild(step);
      });
      parent.appendChild(steps);
    }

    function renderNamespacePicker(parent) {
      const wrap = mk("div", "modal-fields");
      wrap.appendChild(mk("label", "", "登録先 namespace"));
      const row = mk("div");
      row.style.display = "flex";
      row.style.gap = ".5rem";
      if (S.namespaces.length > 0) {
        const select = document.createElement("select");
        S.namespaces.forEach((ns) => {
          const option = mk("option", "", ns);
          option.value = ns;
          option.selected = !S.customNs && ns === S.namespace;
          select.appendChild(option);
        });
        const custom = mk("option", "", "その他（手入力）…");
        custom.value = "__custom__";
        custom.selected = S.customNs;
        select.appendChild(custom);
        select.addEventListener("change", () => {
          if (select.value === "__custom__") { S.customNs = true; S.namespace = ""; }
          else { S.customNs = false; S.namespace = select.value; localStorage.setItem(KB_NS_STORAGE, S.namespace); }
          render();
        });
        row.appendChild(select);
      }
      if (S.customNs) {
        const input = document.createElement("input");
        input.type = "text";
        input.placeholder = "例: shared:houdini_docs";
        input.value = S.namespace;
        input.addEventListener("input", () => { S.namespace = input.value.trim(); updateFooter(); });
        row.appendChild(input);
      }
      wrap.appendChild(row);
      parent.appendChild(wrap);
    }

    function renderFileInput(parent) {
      const zone = mk("div", "dropzone");
      zone.appendChild(mk("p", "", "ファイルをドラッグ＆ドロップするか、ボタンで選択してください"));
      zone.appendChild(mk("p", "hint", "PDF・Word（.docx）・PowerPoint（.pptx）・音声・動画"));
      const input = document.createElement("input");
      input.type = "file";
      input.multiple = true;
      input.hidden = true;
      input.accept = ".pdf,.docx,.pptx,audio/*,video/*";
      input.addEventListener("change", () => { if (input.files && input.files.length) addFiles(input.files); input.value = ""; });
      zone.appendChild(input);
      zone.appendChild(modalButton("ファイルを選択", "primary", () => input.click()));
      zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("drag-over"); });
      zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
      zone.addEventListener("drop", (event) => { event.preventDefault(); zone.classList.remove("drag-over"); if (event.dataTransfer && event.dataTransfer.files.length) addFiles(event.dataTransfer.files); });
      if (S.files.length > 0) {
        const list = mk("ul", "file-list");
        S.files.forEach((file, index) => {
          const li = mk("li", "file-row");
          li.appendChild(mk("span", "", "📄"));
          li.appendChild(mk("span", "name", file.name));
          li.appendChild(mk("span", "size", kbFormatSize(file.size)));
          const remove = mk("button", "icon-btn", "✕");
          remove.type = "button";
          remove.setAttribute("aria-label", "削除");
          remove.addEventListener("click", () => { S.files.splice(index, 1); render(); });
          li.appendChild(remove);
          list.appendChild(li);
        });
        zone.appendChild(list);
      }
      parent.appendChild(zone);
    }

    function renderUrlInput(parent) {
      const wrap = mk("div", "modal-fields");
      wrap.appendChild(mk("label", "", "URL（1行に1件）"));
      const area = document.createElement("textarea");
      area.rows = 4;
      area.placeholder = "https://example.com/docs/" + KB_NL + "https://www.youtube.com/watch?v=...";
      area.value = S.urlText;
      area.addEventListener("input", () => { S.urlText = area.value; updateFooter(); });
      wrap.appendChild(area);
      if (urlLines().length === 1) {
        wrap.appendChild(mk("label", "", "タイトル（任意）"));
        const title = document.createElement("input");
        title.type = "text";
        title.placeholder = "省略時はURL（または取得したページ名）";
        title.value = S.urlTitle;
        title.addEventListener("input", () => { S.urlTitle = title.value; });
        wrap.appendChild(title);
      }
      const scope = mk("div");
      scope.appendChild(mk("label", "", "登録の範囲（YouTube以外のURLに適用）"));
      [[false, "このページのみ"], [true, "配下ページも含む（同じサイト内のリンク先も登録）"]].forEach(([value, text]) => {
        const row = mk("label", "radio-row");
        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "kbCrawlScope";
        radio.checked = S.crawl === value;
        radio.addEventListener("change", () => { S.crawl = value; render(); });
        row.appendChild(radio);
        row.appendChild(document.createTextNode(text));
        scope.appendChild(row);
      });
      wrap.appendChild(scope);
      if (S.crawl) {
        const details = document.createElement("details");
        details.open = true;
        details.appendChild(mk("summary", "", "クロールの詳細設定"));
        details.appendChild(mk("label", "", "深さ"));
        const depth = document.createElement("select");
        [[0, "0（起点URLのみ）"], [1, "1（起点＋直接リンク先）"], [2, "2"], [3, "3"]].forEach(([value, text]) => {
          const option = mk("option", "", text);
          option.value = String(value);
          option.selected = S.depth === value;
          depth.appendChild(option);
        });
        depth.addEventListener("change", () => { S.depth = Number(depth.value); });
        details.appendChild(depth);
        details.appendChild(mk("label", "", "最大ページ数（上限なし。多いほど時間とAPIコストがかかります）"));
        const maxPages = document.createElement("input");
        maxPages.type = "number";
        maxPages.min = "1";
        maxPages.step = "1";
        maxPages.value = String(S.maxPages);
        maxPages.addEventListener("input", () => { const n = parseInt(maxPages.value, 10); S.maxPages = Number.isFinite(n) && n > 0 ? n : 1; });
        details.appendChild(maxPages);
        details.appendChild(mk("label", "", "パス絞り込み（任意）"));
        const prefix = document.createElement("input");
        prefix.type = "text";
        prefix.placeholder = "例: /docs/houdini/（空欄なら同一オリジン全体）";
        prefix.value = S.pathPrefix;
        prefix.addEventListener("input", () => { S.pathPrefix = prefix.value; });
        details.appendChild(prefix);
        details.appendChild(mk("label", "", "除外パターン（任意・カンマ区切り・部分一致）"));
        const exclude = document.createElement("input");
        exclude.type = "text";
        exclude.placeholder = "例: /download/, .pdf";
        exclude.value = S.exclude;
        exclude.addEventListener("input", () => { S.exclude = exclude.value; });
        details.appendChild(exclude);
        const skipRow = mk("label", "check-row");
        const skip = document.createElement("input");
        skip.type = "checkbox";
        skip.checked = S.skipExisting;
        skip.addEventListener("change", () => { S.skipExisting = skip.checked; });
        skipRow.appendChild(skip);
        skipRow.appendChild(document.createTextNode("同じnamespaceに同名で登録済みのページはスキップする（再クロール時のAPIコスト削減）"));
        details.appendChild(skipRow);
        wrap.appendChild(details);
      }
      parent.appendChild(wrap);
    }

    function renderQaInput(parent) {
      const wrap = mk("div", "modal-fields");
      // 未入力の行の警告。入力のたびに更新する（再描画だと入力中のフォーカスが外れるため）
      const warn = mk("p", "modal-error");
      function refreshQaWarning() {
        const count = incompletePairs();
        warn.textContent = "質問・回答のどちらかが未入力の行が" + count + "件あります。このまま進むと、それらは登録されません。";
        warn.style.display = count > 0 ? "" : "none";
      }
      S.pairs.forEach((pair, index) => {
        const box = mk("div", "qa-pair");
        const head = mk("div", "head");
        head.appendChild(mk("strong", "", "Q&A " + (index + 1)));
        if (S.pairs.length > 1) {
          const remove = mk("button", "icon-btn", "✕");
          remove.type = "button";
          remove.addEventListener("click", () => { S.pairs.splice(index, 1); render(); });
          head.appendChild(remove);
        }
        box.appendChild(head);
        const q = document.createElement("textarea");
        q.rows = 2;
        q.placeholder = "質問（例: HyDEとは何ですか？）";
        q.value = pair.question;
        q.addEventListener("input", () => { pair.question = q.value; refreshQaWarning(); updateFooter(); });
        const a = document.createElement("textarea");
        a.rows = 3;
        a.placeholder = "回答";
        a.value = pair.answer;
        a.addEventListener("input", () => { pair.answer = a.value; refreshQaWarning(); updateFooter(); });
        box.appendChild(q);
        box.appendChild(a);
        wrap.appendChild(box);
      });
      wrap.appendChild(warn);
      refreshQaWarning();
      const actions = mk("div");
      actions.style.display = "flex";
      actions.style.gap = ".5rem";
      actions.style.flexWrap = "wrap";
      actions.appendChild(modalButton("＋ Q&Aを追加", "", () => { S.pairs.push({ question: "", answer: "" }); render(); }));
      const csvInput = document.createElement("input");
      csvInput.type = "file";
      csvInput.accept = ".csv,text/csv";
      csvInput.hidden = true;
      csvInput.addEventListener("change", async () => {
        const file = csvInput.files && csvInput.files[0];
        csvInput.value = "";
        if (!file) return;
        const text = await file.text();
        setCsv(file.name, text);
      });
      actions.appendChild(csvInput);
      actions.appendChild(modalButton("CSVを読み込む", "", () => csvInput.click()));
      wrap.appendChild(actions);
      const details = document.createElement("details");
      details.open = S.csvText.length > 0;
      details.appendChild(mk("summary", "", "CSVを貼り付ける（ヘッダー行に question, answer 列）"));
      const area = document.createElement("textarea");
      area.rows = 5;
      area.style.fontFamily = "monospace";
      area.placeholder = "question,answer" + KB_NL + "HyDEとは,仮の回答を先に生成してから検索する手法です";
      area.value = S.csvText;
      area.addEventListener("input", () => { setCsv(S.csvName, area.value, true); });
      details.appendChild(area);
      if (S.csvText.trim()) details.appendChild(mk("p", "modal-note", "CSV: 約" + S.csvRows + "行を一括登録します" + (S.csvName ? "（" + S.csvName + "）" : "")));
      wrap.appendChild(details);
      const notion = mk("label", "check-row");
      const notionBox = document.createElement("input");
      notionBox.type = "checkbox";
      notionBox.checked = S.alsoNotion;
      notionBox.addEventListener("change", () => { S.alsoNotion = notionBox.checked; });
      notion.appendChild(notionBox);
      notion.appendChild(document.createTextNode("このnamespaceの同期先Notion DBにもページを作成する（Q&Aの手入力分のみ。namespaceにNotion DB設定が必要）"));
      wrap.appendChild(notion);
      parent.appendChild(wrap);
    }

    function setCsv(name, text, typing) {
      S.csvName = typing ? "" : name;
      S.csvText = text;
      const lines = text.split(KB_NL).filter((line) => line.trim());
      S.csvRows = Math.max(lines.length - 1, 0);
      const header = (lines[0] || "").toLowerCase();
      S.error = text.trim() && !(header.indexOf("question") >= 0 && header.indexOf("answer") >= 0) ? "CSVのヘッダー行に question と answer の列が必要です" : "";
      if (typing) updateFooter(); else render();
    }

    function renderItems(parent, showStatus) {
      const list = mk("ul", "file-list");
      S.items.forEach((item, index) => {
        const li = mk("li", "file-row vertical");
        const line = mk("div", "line");
        line.appendChild(mk("span", "", item.icon));
        line.appendChild(mk("span", "name", item.label));
        if (showStatus) {
          const status = S.status[index];
          const labels = { pending: "待機中", running: "登録中…", done: "完了", error: "失敗", skipped: "中断" };
          const badge = mk("span", "badge " + (status === "done" ? "ok" : status === "error" ? "error" : status === "running" ? "running" : ""), labels[status] || "");
          line.appendChild(badge);
        }
        li.appendChild(line);
        if (showStatus && S.detail[index] && S.status[index] !== "error") li.appendChild(mk("div", "detail", S.detail[index]));
        if (showStatus && S.status[index] === "error" && S.message[index]) li.appendChild(mk("div", "err", S.message[index]));
        list.appendChild(li);
      });
      parent.appendChild(list);
    }

    function counts() {
      return {
        done: S.status.filter((s) => s === "done").length,
        error: S.status.filter((s) => s === "error").length,
        skipped: S.status.filter((s) => s === "skipped").length,
      };
    }

    function updateFooter() {
      modal.footer.innerHTML = "";
      if (S.screen === "input") {
        modal.footer.appendChild(modalButton("キャンセル", "", () => modal.close()));
        const next = modalButton("次へ", "primary", () => { S.items = buildItems(); S.status = S.items.map(() => "pending"); S.detail = S.items.map(() => ""); S.message = S.items.map(() => ""); S.screen = "review"; S.error = ""; render(); });
        next.disabled = !canProceed() || (S.method === "qa" && S.error !== "");
        modal.footer.appendChild(next);
      } else if (S.screen === "review") {
        modal.footer.appendChild(modalButton("戻る", "", () => { S.screen = "input"; render(); }));
        modal.footer.appendChild(modalButton("登録開始", "primary", () => startRun(null)));
      } else if (S.screen === "progress") {
        const note = mk("span", "grow", "登録中です。画面を閉じずにお待ちください");
        modal.footer.appendChild(note);
        modal.footer.appendChild(modalButton("残りを中断", "", () => { S.stop = true; }));
      } else {
        const c = counts();
        modal.footer.appendChild(mk("span", "grow", c.done + "/" + S.items.length + "件を登録しました" + (c.error ? "（失敗 " + c.error + "件）" : "") + (c.skipped ? "（中断 " + c.skipped + "件）" : "")));
        const retry = S.status.map((s, i) => (s === "error" || s === "skipped" ? i : -1)).filter((i) => i >= 0);
        if (retry.length > 0) modal.footer.appendChild(modalButton("失敗・中断した分だけ再実行", "", () => startRun(retry)));
        modal.footer.appendChild(modalButton("続けて追加", "", () => { S.screen = "input"; S.method = null; S.files = []; S.urlText = ""; S.urlTitle = ""; S.pairs = [{ question: "", answer: "" }]; S.csvName = ""; S.csvText = ""; S.csvRows = 0; S.error = ""; render(); }));
        modal.footer.appendChild(modalButton("閉じる", "primary", () => modal.close()));
      }
    }

    function render() {
      const body = modal.body;
      body.innerHTML = "";
      renderStepper(body);
      if (S.screen === "input") {
        modal.setSubtitle("登録先: " + (S.namespace || "（未選択）"));
        renderNamespacePicker(body);
        const cards = mk("div", "method-cards");
        KB_METHODS.forEach((method) => {
          const card = mk("button", "method-card" + (S.method === method.key ? " selected" : ""));
          card.type = "button";
          card.appendChild(mk("span", "icon", method.icon));
          card.appendChild(mk("strong", "", method.title));
          card.appendChild(mk("small", "", method.description));
          card.addEventListener("click", () => { S.method = method.key; S.error = ""; render(); });
          cards.appendChild(card);
        });
        body.appendChild(cards);
        if (S.method) {
          const grid = mk("div", "modal-grid");
          const main = mk("div");
          if (S.method === "file") renderFileInput(main);
          else if (S.method === "url") renderUrlInput(main);
          else renderQaInput(main);
          grid.appendChild(main);
          const tips = mk("aside", "modal-tips");
          tips.appendChild(mk("h4", "", "ⓘ 登録のポイント"));
          const ul = mk("ul");
          KB_TIPS[S.method].forEach((tip) => { const li = mk("li"); li.appendChild(mk("span", "tip-check", "✓")); li.appendChild(mk("span", "", tip)); ul.appendChild(li); });
          tips.appendChild(ul);
          grid.appendChild(tips);
          body.appendChild(grid);
        }
      } else if (S.screen === "review") {
        modal.setSubtitle("登録先: " + S.namespace);
        body.appendChild(mk("p", "modal-note", "次の" + S.items.length + "件を「" + S.namespace + "」へ登録します。内容を確認して「登録開始」を押してください。"));
        renderItems(body, false);
      } else {
        modal.setSubtitle("登録先: " + S.namespace);
        const c = counts();
        const finished = c.done + c.error + c.skipped;
        if (S.screen === "progress") {
          const percent = S.items.length ? Math.round(((finished + (S.status.indexOf("running") >= 0 ? 0.5 : 0)) / S.items.length) * 100) : 0;
          const track = mk("div", "progress-track");
          const bar = mk("div", "progress-bar");
          bar.style.width = percent + "%";
          track.appendChild(bar);
          body.appendChild(track);
          body.appendChild(mk("p", "modal-note", finished + "/" + S.items.length + " 件処理（" + percent + "%）"));
        } else {
          body.appendChild(mk("p", "modal-note", c.error || c.skipped ? "登録結果（一部が完了していません）" : "登録が完了しました"));
        }
        renderItems(body, true);
      }
      if (S.error) body.appendChild(mk("p", "modal-error", S.error));
      updateFooter();
    }

    function refreshKnowledgeLists() {
      loadKbHistory();
      loadKbOverview();
      if (kbList.ready) loadKbList();
      refreshConnectedSystems();
    }
    render();
  }
  $("openKnowledgeModalBtn").addEventListener("click", openKnowledgeModal);

  // ---------- 管理タブ：連携するシステム（ポップアップ、2026-10-08追加） ----------
  // 別プロジェクトの「連携するシステムを追加」（システムの選択グリッド → 詳細ポップアップ）を参考にした。
  // 公式MCP（Notion・Atlassian）と、ナレッジ同期用のOAuth接続（Jira・Backlog・Googleカレンダー・Slack）を
  // 同じ入口から選べる。同期するプロジェクト等の細かい設定は、従来どおり「連携」タブで行う。
  const SYSTEM_DEFS = [
    { id: "mcp:notion", kind: "mcp", provider: "notion", name: "Notion", brand: "Notion", icon: "📓",
      description: "ページの検索・閲覧（公式MCP）",
      access: "Notionのページ・データベースを検索・閲覧できます。チャットで使えるのは読み取り専用のツールだけで、書き込みを行うツールは使われません。" },
    { id: "mcp:atlassian", kind: "mcp", provider: "atlassian", name: "Atlassian（Jira / Confluence）", brand: "Atlassian", icon: "🧭",
      description: "課題・ページの検索と閲覧（公式MCP）",
      access: "Jiraの課題・Confluenceのページを検索・閲覧できます。チャットで使えるのは読み取り専用のツールだけで、作成・更新を行うツールは使われません。" },
    { id: "oauth:jira", kind: "oauth", service: "jira", name: "Jira（課題の同期）", brand: "Atlassian", icon: "🎫",
      description: "課題をナレッジとして毎日同期",
      access: "Jiraのプロジェクトの課題（要約・説明・種別・ステータス）を読み取り、ナレッジとして登録します。読み取り専用（read:jira-work）です。" },
    { id: "oauth:backlog", kind: "oauth", service: "backlog", needsSpace: true, name: "Backlog（課題の同期）", brand: "Backlog", icon: "🗂",
      description: "課題をナレッジとして毎日同期",
      access: "Backlogのプロジェクトの課題を読み取り、ナレッジとして登録します。認証の前に、スペースURL（例: yourspace.backlog.com）を入力してください。" },
    { id: "oauth:google_calendar", kind: "oauth", service: "google_calendar", name: "Google カレンダー", brand: "Google", icon: "📅",
      description: "予定をナレッジとして毎日同期",
      access: "選んだカレンダーの予定（タイトル・日時・場所・説明）を、過去7日〜未来90日分、読み取って登録します。" },
    { id: "oauth:slack", kind: "oauth", service: "slack", adminOnly: true, name: "Slack（通知）", brand: "Slack", icon: "💬",
      description: "ヘルスチェック・アラートの通知先",
      access: "選んだチャンネルへ、ヘルスチェックのアラートなどの通知を送ります（管理者のみ）。" },
    { id: "plan", kind: "plan", name: "その他のシステム", brand: "", icon: "➕",
      description: "GitHub・Zoom・Google公式MCPなど（準備中）", access: "" },
  ];

  async function loadSystemStates() {
    const state = { mcp: {}, oauth: {} };
    const [mcpRes, oauthRes] = await Promise.allSettled([api("/admin/mcp/status", {}), api("/admin/oauth/status", {})]);
    if (mcpRes.status === "fulfilled") mcpRes.value.providers.forEach((p) => { state.mcp[p.id] = p; });
    if (oauthRes.status === "fulfilled") state.oauth = oauthRes.value;
    return state;
  }

  // 1つのシステムの状態。connected / reauth / chip（アカウント・サイト名など）
  function systemInfo(def, state) {
    if (def.kind === "mcp") {
      const p = state.mcp[def.provider];
      if (!p) return { connected: false, reauth: false, chip: "", chatEnabled: false };
      return { connected: p.connected, reauth: p.status === "reauth_required", chip: "", chatEnabled: p.chatEnabled };
    }
    if (def.kind === "oauth") {
      const o = state.oauth[def.service];
      return { connected: !!(o && o.connected), reauth: false, chip: o && o.connected ? (o.label || "") : "", chatEnabled: false };
    }
    return { connected: false, reauth: false, chip: "", chatEnabled: false };
  }

  function statusBadge(info) {
    if (info.reauth) return mk("span", "badge error", "要再認証");
    if (info.connected) return mk("span", "badge ok", "連携済み");
    return null;
  }

  // 「連携中のシステム」カード（ナレッジ登録タブ）
  async function refreshConnectedSystems() {
    const list = $("connectedSystemsList");
    if (!list) return;
    try {
      const state = await loadSystemStates();
      list.innerHTML = "";
      const rows = SYSTEM_DEFS.filter((d) => d.kind !== "plan").map((d) => ({ d, info: systemInfo(d, state) })).filter((r) => r.info.connected || r.info.reauth);
      if (rows.length === 0) {
        list.appendChild(mk("li", "conn-empty", "連携しているシステムはまだありません。「連携するシステムを追加」から接続できます。"));
        return;
      }
      rows.forEach(({ d, info }) => {
        const li = mk("li", "conn-row");
        li.tabIndex = 0;
        li.appendChild(statusBadge(info));
        li.appendChild(mk("strong", "", d.name));
        if (info.chip) li.appendChild(mk("span", "chip", info.chip));
        if (info.chatEnabled) li.appendChild(mk("span", "chip ok", "チャットで使用中"));
        li.appendChild(mk("span", "conn-desc", d.description));
        const open = () => openSystemsModal(d.id);
        li.addEventListener("click", open);
        li.addEventListener("keydown", (event) => { if (event.key === "Enter") open(); });
        list.appendChild(li);
      });
    } catch (e) {
      list.innerHTML = "";
      list.appendChild(mk("li", "conn-empty", "状態を取得できませんでした: " + e.message));
    }
  }

  async function openSystemsModal(focusId) {
    const isAdmin = currentUserRole === "admin";
    const modal = openModal({ title: "連携するシステムを追加", subtitle: "連携したいシステムを選択してください。選択後、各サービスの認証画面に移行します。", wide: true,
      onClose: () => { refreshConnectedSystems(); loadMcpStatus(); loadOAuthStatus(); } });
    let state = await loadSystemStates();
    let selected = SYSTEM_DEFS.find((d) => d.id === focusId) || null;

    function renderGrid() {
      modal.setTitle("連携するシステムを追加");
      modal.setSubtitle("連携したいシステムを選択してください。選択後、各サービスの認証画面に移行します。");
      modal.body.innerHTML = "";
      modal.footer.innerHTML = "";
      const grid = mk("div", "sys-grid");
      SYSTEM_DEFS.forEach((def) => {
        const info = systemInfo(def, state);
        const card = mk("button", "sys-card");
        card.type = "button";
        card.appendChild(mk("span", "sys-icon", def.icon));
        const text = mk("span", "sys-text");
        const title = mk("strong", "", def.name);
        const badge = statusBadge(info);
        if (badge) title.appendChild(badge);
        text.appendChild(title);
        text.appendChild(mk("small", "", def.description));
        card.appendChild(text);
        card.appendChild(mk("span", "sys-chevron", "›"));
        card.addEventListener("click", () => { selected = def; renderDetail(); });
        grid.appendChild(card);
      });
      modal.body.appendChild(grid);
      modal.footer.appendChild(modalButton("キャンセル", "", () => modal.close()));
    }

    function detailRow(icon, label, value) {
      const row = mk("div", "sys-row");
      row.appendChild(mk("span", "sys-row-label", icon + " " + label));
      row.appendChild(mk("span", "sys-val", value));
      return row;
    }

    function renderDetail() {
      const def = selected;
      const info = systemInfo(def, state);
      modal.body.innerHTML = "";
      modal.footer.innerHTML = "";
      if (def.kind === "plan") {
        modal.setTitle("その他のシステム");
        modal.setSubtitle("今後対応を予定しているシステムです。");
        const list = mk("ul", "modal-note");
        ["GitHub・Zoom など、他社の公式MCPサーバー（自動登録に対応しているもの）", "Google公式MCP（Gmail・Calendar・Drive。Developer Previewへの参加が必要）", "書き込みを行うツールのチャット利用（実行前の確認ダイアログが必要）"].forEach((text) => list.appendChild(mk("li", "", text)));
        modal.body.appendChild(list);
        modal.body.appendChild(mk("p", "modal-note", "サービスを足すには、src/mcp/providers.ts に公式MCPサーバーのURLを1件登録します（詳しくは docs/mcp-client.md）。"));
        modal.footer.appendChild(modalButton("← 一覧へ", "", () => { selected = null; renderGrid(); }));
        return;
      }
      modal.setTitle(def.name + "と連携");
      modal.setSubtitle(def.name + "をこのシステムに連携します。認証後、許可した情報を検索・同期に利用できるようになります。");

      const hero = mk("div", "sys-hero");
      hero.appendChild(mk("span", "sys-icon big", def.icon));
      const heroText = mk("div");
      const heroTitle = mk("h4", "", def.name);
      const badge = statusBadge(info);
      if (badge) heroTitle.appendChild(badge);
      heroText.appendChild(heroTitle);
      heroText.appendChild(mk("p", "", def.description));
      if (info.connected && info.chip) heroText.appendChild(mk("p", "sys-account", "連携アカウント：" + info.chip));
      hero.appendChild(heroText);
      modal.body.appendChild(hero);
      if (info.reauth) modal.body.appendChild(mk("p", "modal-error", "連携の有効期限が切れたか、取り消されました。もう一度認証してください。"));

      const rows = mk("div", "sys-rows");
      rows.appendChild(detailRow("👤", "対象", "この管理画面（デプロイ全体）。連携した方の権限で動きます"));
      rows.appendChild(detailRow("🔗", "連携サービス", def.name));
      rows.appendChild(detailRow("🔒", "アクセス範囲", def.access));
      rows.appendChild(detailRow("🛡", "セキュリティ", "認証は" + def.brand + "側で行われ、パスワードはこのシステムには渡りません。許可した内容はいつでも解除できます。"));
      modal.body.appendChild(rows);

      const canOperate = def.kind === "mcp" ? isAdmin : (def.adminOnly ? isAdmin : true);
      if (!canOperate) modal.body.appendChild(mk("p", "modal-note", "接続・設定は管理者だけが行えます。"));

      let spaceInput = null;
      if (def.needsSpace && !info.connected && canOperate) {
        const field = mk("div", "modal-fields");
        field.appendChild(mk("label", "", "スペースURL"));
        spaceInput = document.createElement("input");
        spaceInput.type = "text";
        spaceInput.placeholder = "例: yourspace.backlog.com";
        field.appendChild(spaceInput);
        modal.body.appendChild(field);
      }

      if (def.kind === "mcp" && isAdmin && info.connected) {
        const panel = mk("div", "sys-panel");
        panel.appendChild(mk("h4", "", "チャットで使うツール"));
        const row = mk("label", "check-row");
        row.style.display = "flex";
        row.style.gap = ".4rem";
        const toggle = document.createElement("input");
        toggle.type = "checkbox";
        toggle.checked = info.chatEnabled;
        toggle.addEventListener("change", async () => {
          try { await api("/admin/mcp/set-chat", { provider: def.provider, enabled: toggle.checked }); showToast(toggle.checked ? "チャットで使うようにしました" : "チャットでは使わないようにしました", "success"); state = await loadSystemStates(); }
          catch (e) { toggle.checked = !toggle.checked; showToast("変更に失敗しました: " + e.message, "error"); }
        });
        row.appendChild(toggle);
        row.appendChild(document.createTextNode("RAGチャットでこのサービスのツールを使う（読み取り専用のみ）"));
        panel.appendChild(row);
        const toolsBox = mk("div");
        toolsBox.appendChild(mk("p", "modal-note", "ツール一覧を取得しています…"));
        panel.appendChild(toolsBox);
        modal.body.appendChild(panel);
        loadSystemTools(def, toolsBox, false);
      }
      if (def.kind === "oauth") {
        const panel = mk("div", "sys-panel");
        panel.appendChild(mk("h4", "", "同期の設定"));
        panel.appendChild(mk("p", "modal-note", "同期するプロジェクト・カレンダー・通知先などは、「連携」タブで設定します。"));
        panel.appendChild(modalButton("「連携」タブを開く", "", () => { modal.close(); const tab = document.querySelector('button[data-subtab="integrations"]'); if (tab) tab.click(); }));
        modal.body.appendChild(panel);
      }

      modal.footer.appendChild(modalButton("キャンセル", "", () => { selected = null; renderGrid(); }));
      if (canOperate) {
        const disconnectable = def.kind === "mcp" ? (info.connected || info.reauth) : info.connected;
        if (disconnectable) {
          modal.footer.appendChild(modalButton("連携を解除", "danger", async () => {
            if (!confirm(def.name + "との連携を解除しますか？")) return;
            try {
              await api(def.kind === "mcp" ? "/admin/mcp/disconnect" : "/admin/oauth/" + def.service + "/disconnect", def.kind === "mcp" ? { provider: def.provider } : {});
              showToast("解除しました", "success");
              state = await loadSystemStates();
              renderDetail();
            } catch (e) { showToast("解除に失敗しました: " + e.message, "error"); }
          }));
        }
        const label = info.connected || info.reauth ? "再認証する" : def.brand + "で認証する" + (def.kind === "mcp" ? "（公式MCP）" : "");
        modal.footer.appendChild(modalButton(label, "primary", () => {
          if (def.kind === "mcp") { startOAuthConnect("mcp/" + def.provider); return; }
          if (def.needsSpace) {
            const space = spaceInput ? spaceInput.value.trim() : "";
            if (!space) { showToast("スペースURLを入力してください", "error"); return; }
            startOAuthConnect(def.service, { space });
            return;
          }
          startOAuthConnect(def.service);
        }));
      }
    }

    if (selected) renderDetail(); else renderGrid();
  }

  async function loadSystemTools(def, box, refresh) {
    try {
      const data = await api("/admin/mcp/tools", { provider: def.provider, refresh });
      box.innerHTML = "";
      box.appendChild(mk("p", "modal-note", "使うツールを選びます（未選択のものは使われません）。モデルに見せるツールは少ないほど選びやすくなります。"));
      const list = mk("ul", "mcp-tools");
      const checks = [];
      data.tools.forEach((tool) => {
        const li = mk("li");
        const label = mk("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = tool.enabled;
        checks.push([tool.name, input]);
        label.appendChild(input);
        const text = mk("span");
        const name = mk("strong", "", tool.name);
        name.appendChild(document.createTextNode(" "));
        name.appendChild(mk("span", "badge " + (tool.readOnly ? "ok" : ""), tool.readOnly ? "読み取り" : "書き込みの可能性（チャットでは使われません）"));
        text.appendChild(name);
        text.appendChild(mk("small", "", (tool.description || "").slice(0, 160)));
        label.appendChild(text);
        li.appendChild(label);
        list.appendChild(li);
      });
      box.appendChild(list);
      const actions = mk("div");
      actions.style.display = "flex";
      actions.style.gap = ".5rem";
      actions.appendChild(modalButton("ツールの選択を保存", "primary", async () => {
        try { await api("/admin/mcp/set-tools", { provider: def.provider, tools: checks.filter((c) => c[1].checked).map((c) => c[0]) }); showToast("保存しました", "success"); }
        catch (e) { showToast("保存に失敗しました: " + e.message, "error"); }
      }));
      actions.appendChild(modalButton("一覧を再取得", "", () => { box.innerHTML = ""; box.appendChild(mk("p", "modal-note", "取得しています…")); loadSystemTools(def, box, true); }));
      box.appendChild(actions);
    } catch (e) {
      box.innerHTML = "";
      box.appendChild(mk("p", "modal-error", "ツール一覧を取得できませんでした: " + e.message));
    }
  }

  $("openSystemsModalBtn").addEventListener("click", () => openSystemsModal(null));

  // 「連携」タブの公式MCPセクション（状態の一覧）
  let mcpProviders = [];
  async function loadMcpStatus() {
    const list = $("mcpStatusList");
    if (!list) return;
    try {
      const data = await api("/admin/mcp/status", {});
      mcpProviders = data.providers;
      list.innerHTML = "";
      mcpProviders.forEach((p) => {
        const li = mk("li");
        li.appendChild(mk("strong", "", p.label));
        li.appendChild(mk("span", "badge " + (p.connected ? "ok" : p.status === "reauth_required" ? "error" : ""), p.status === "reauth_required" ? "要再認証" : p.connected ? "接続済み" : "未接続"));
        if (p.connected && p.chatEnabled) li.appendChild(mk("span", "badge ok", "チャットで使用中"));
        list.appendChild(li);
      });
    } catch (e) {
      list.innerHTML = "";
      list.appendChild(mk("li", "hint", "状態を取得できませんでした: " + e.message));
    }
  }
  $("mcpOpenBtn").addEventListener("click", () => openSystemsModal(null));
  $("mcpRefreshBtn").addEventListener("click", loadMcpStatus);

  // ---------- 管理タブ：登録済みナレッジ（一覧・検索・削除、2026-10-08） ----------
  // 以前は「登録済みファイル一覧・個別削除」でnamespaceを手入力して読み込む形だった。
  // 別プロジェクトの「登録済みナレッジ」カードを参考に、namespaceを選択式にし、検索・ページ送り・
  // 種類と更新日時の表示を足した。削除は従来どおり1件ずつ（opId単位の一括取り消しはシステムタブ）。
  const kbList = { items: [], page: 1, size: 20, query: "", ns: "", ready: false };
  const KB_SOURCE_LABELS = { manual: "手動登録", notion: "Notion", drive: "Google Drive", jira: "Jira", backlog: "Backlog", calendar: "カレンダー" };
  function kbKind(item) {
    const ext = kbExt(item.file);
    if (ext === ".pdf") return "PDF";
    if (ext === ".docx") return "Word";
    if (ext === ".pptx") return "PowerPoint";
    if (KB_AV_EXT.includes(ext)) return "音声・動画";
    return KB_SOURCE_LABELS[item.source] || "テキスト";
  }

  async function initKbList() {
    const select = $("kbListNs");
    if (!select || kbList.ready) return;
    const namespaces = await kbLoadNamespaces();
    select.innerHTML = "";
    namespaces.forEach((ns) => { const option = mk("option", "", ns); option.value = ns; select.appendChild(option); });
    const saved = localStorage.getItem(KB_NS_STORAGE) || "";
    kbList.ns = namespaces.includes(saved) ? saved : (namespaces.find((n) => n.indexOf("shared:") === 0) || namespaces[0] || "");
    select.value = kbList.ns;
    kbList.ready = true;
    loadKbList();
  }

  async function loadKbList() {
    if (!kbList.ns) { renderKbList("登録先のnamespaceがありません"); return; }
    $("kbListCount").textContent = "読み込み中…";
    try {
      const data = await api("/admin/kb/list-documents", { namespace: kbList.ns });
      kbList.items = data.documents || (data.files || []).map((file) => ({ file, source: null, updatedAt: null }));
      kbList.page = 1;
      renderKbList("");
    } catch (e) {
      kbList.items = [];
      renderKbList("取得に失敗しました: " + e.message);
    }
  }

  function renderKbList(message) {
    const tbody = $("kbListTable").querySelector("tbody");
    tbody.innerHTML = "";
    const query = kbList.query.trim().toLowerCase();
    const filtered = kbList.items.filter((item) => !query || item.file.toLowerCase().indexOf(query) >= 0);
    const pages = Math.max(1, Math.ceil(filtered.length / kbList.size));
    kbList.page = Math.min(kbList.page, pages);
    const start = (kbList.page - 1) * kbList.size;
    const slice = filtered.slice(start, start + kbList.size);
    if (slice.length === 0) {
      const tr = document.createElement("tr");
      const td = mk("td", "", message || (query ? "該当するナレッジがありません" : "登録済みのナレッジはありません"));
      td.colSpan = 4;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    slice.forEach((item) => {
      const tr = document.createElement("tr");
      const name = mk("td", "kb-name");
      name.appendChild(mk("span", "kb-doc-icon", "📄"));
      name.appendChild(document.createTextNode(item.file));
      name.title = item.file;
      tr.appendChild(name);
      tr.appendChild(mk("td", "", kbKind(item)));
      tr.appendChild(mk("td", "", item.updatedAt ? new Date(item.updatedAt * 1000).toLocaleString() : "-"));
      const actions = mk("td");
      const del = modalButton("削除", "danger", async () => {
        if (!confirm(item.file + " を削除しますか？（元に戻せません）")) return;
        del.disabled = true;
        try {
          const result = await api("/admin/kb/delete-document", { namespace: kbList.ns, file: item.file });
          showToast(item.file + " を削除しました（" + result.deletedChunks + "チャンク）", "success");
          kbList.items = kbList.items.filter((x) => x.file !== item.file);
          renderKbList("");
          loadKbOverview();
        } catch (e) {
          showToast("削除に失敗しました: " + e.message, "error");
          del.disabled = false;
        }
      });
      actions.appendChild(del);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
    const from = filtered.length === 0 ? 0 : start + 1;
    $("kbListCount").textContent = from + "–" + (start + slice.length) + " / " + filtered.length + " 件";
    $("kbListPageNo").textContent = kbList.page + " / " + pages;
    $("kbListPrev").disabled = kbList.page <= 1;
    $("kbListNext").disabled = kbList.page >= pages;
  }

  if ($("kbListNs")) {
    $("kbListNs").addEventListener("change", () => { kbList.ns = $("kbListNs").value; localStorage.setItem(KB_NS_STORAGE, kbList.ns); loadKbList(); });
    $("kbListSearch").addEventListener("input", () => { kbList.query = $("kbListSearch").value; kbList.page = 1; renderKbList(""); });
    $("kbListSize").addEventListener("change", () => { kbList.size = Number($("kbListSize").value) || 20; kbList.page = 1; renderKbList(""); });
    $("kbListPrev").addEventListener("click", () => { kbList.page -= 1; renderKbList(""); });
    $("kbListNext").addEventListener("click", () => { kbList.page += 1; renderKbList(""); });
    $("kbListRefresh").addEventListener("click", () => { kbList.ready ? loadKbList() : initKbList(); });
  }

  // チャットの「外部サービスも使う」スイッチ。管理者が「チャットで使う」をオンにしたサービスが
  // 1つでもあるときだけ表示する（外部へは通信せず、D1の接続状態だけを見る）。
  async function refreshMcpAvailability() {
    const wrap = $("mcpToggleWrap");
    if (!wrap) return;
    try {
      const data = await api("/me/mcp", {});
      wrap.style.display = data.available ? "flex" : "none";
      $("mcpToggleLabel").textContent = "外部サービスも使う（" + data.providers.map((p) => p.label).join("・") + "）";
    } catch (e) {
      wrap.style.display = "none";
    }
  }

  // ---------- 管理タブ：KBロールバック ----------
  $("rollbackBtn").addEventListener("click", async () => {
    const opId = $("rollbackOpId").value.trim();
    if (!opId) { $("rollbackResult").textContent = "opIdを入力してください"; return; }
    if (!confirm("opId=" + opId + " で登録された内容をすべて削除します。元に戻せません。よろしいですか？")) return;
    $("rollbackResult").textContent = "実行中…";
    try {
      const data = await api("/admin/kb/rollback", { opId });
      $("rollbackResult").textContent = "完了: " + data.deletedFiles + "ファイル・" + data.deletedChunks + "チャンクを削除しました";
      loadKbHistory(); loadKbOverview();
    } catch (e) {
      $("rollbackResult").textContent = "エラー: " + e.message;
    }
  });
})();
</script>
</body>
</html>`;
}
