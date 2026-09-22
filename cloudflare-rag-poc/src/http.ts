// 各ハンドラで個別に定義されていた同一実装のJSONレスポンスヘルパーを1箇所に集約する
// （2026-09-04。18ファイルに byte-for-byte 同一の関数が重複しており、レスポンス契約を
// 変える際に修正漏れが起きるリスクがあった）。
// 注意: backup.ts の jsonResponse は JSON.stringify(body, null, 2) で整形しており、
// ダウンロード用バックアップファイルを人間が読みやすくするための意図的な別実装のため
// 統合していない。
export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

// リクエストbodyの数値パラメータ（days/limit等）を安全にクランプする（2026-09-13追加。
// 各ハンドラが個別にMath.min(Math.max(body.x ?? 既定値, min), max)を書いており、直接API
// を叩かれてbody.xに文字列やbooleanが渡ると`??`はnullish判定しか行わないためすり抜け、
// NaNが混入して比較が常にfalseになる（例: `count < NaN`は常にfalse）事故が起きていた
// ——実際にurlImport.tsの再帰クロールでこの不具合が見つかり修正した際に切り出した）。
export function clampInt(raw: unknown, def: number, min: number, max: number): number {
  const n = Number(raw);
  return Math.min(Math.max(Number.isFinite(n) ? Math.trunc(n) : def, min), max);
}

// OAuthコールバック（jiraOAuth.ts/backlogOAuth.ts/calendarOAuth.ts/slackOAuth.ts）が
// 結果を表示する簡易HTMLページ用（2026-09-22追加）。コールバックは外部サービスからの
// リダイレクトで、管理画面のAPIキーもJS実行コンテキストも持たないため、JSON応答ではなく
// 人間がそのまま読めるページを返す。数秒後に管理画面（"/"）へ自動遷移する。
export function oauthResultPage(ok: boolean, message: string): Response {
  const title = ok ? "接続完了" : "接続エラー";
  const color = ok ? "#15846e" : "#e07a5f";
  return new Response(
    `<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">` +
      `<title>${title}</title>` +
      `<style>body{background:#0c0c0e;color:#e6e8ee;font-family:sans-serif;` +
      `display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}` +
      `.box{text-align:center;max-width:480px;padding:2rem;}` +
      `h1{color:${color};}</style></head><body><div class="box">` +
      `<h1>${title}</h1><p>${message}</p>` +
      `<p style="color:#888;font-size:.9rem;">このタブは自動的に管理画面へ戻ります…</p>` +
      `</div><script>setTimeout(function(){location.href="/";},2500);</script>` +
      `</body></html>`,
    { status: ok ? 200 : 400, headers: { "content-type": "text/html; charset=utf-8" } },
  );
}
