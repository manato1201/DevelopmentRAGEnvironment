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
