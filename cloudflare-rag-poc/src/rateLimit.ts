import type { Env } from "./types";

// レート制限（既存GAS isRateLimited_相当）。専用テーブルを追加せず、既存のaudit_log
// （/search・/queryの度に記録される）の直近件数を数える方式にした：
// 「直近WINDOW秒間にMAX_REQUESTS回まで」という単純な固定ウィンドウ制限。
const WINDOW_SEC = 60;
const MAX_REQUESTS = 30;

export class RateLimitedError extends Error {}

export async function assertNotRateLimited(
  env: Env,
  userId: string,
): Promise<void> {
  const since = Math.floor(Date.now() / 1000) - WINDOW_SEC;
  const res = await env.DB.prepare(
    "SELECT COUNT(*) AS cnt FROM audit_log WHERE user_id = ? AND created_at >= ?",
  )
    .bind(userId, since)
    .first<{ cnt: number }>();
  if ((res?.cnt ?? 0) >= MAX_REQUESTS) {
    throw new RateLimitedError(
      `レート制限を超えました（直近${WINDOW_SEC}秒間に${MAX_REQUESTS}回まで）。しばらく待ってから再試行してください。`,
    );
  }
}
