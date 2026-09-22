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
