import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";

// POST /admin/usage/stats — 日次のトークン使用量集計（既存GAS adminTokenUsageStats相当）。
// 管理画面の折れ線/棒グラフ表示用。日付はUTC基準（SQLiteのunixepoch由来のためタイムゾーン変換はしない）。
export async function handleUsageStats(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { days?: number };
  const days = Math.min(Math.max(body.days ?? 14, 1), 90);
  const sinceTs = Math.floor(Date.now() / 1000) - days * 86400;

  const dailyRes = await env.DB.prepare(
    `SELECT date(created_at, 'unixepoch') AS day, SUM(tokens_used) AS tokens, COUNT(*) AS queries
     FROM audit_log
     WHERE created_at >= ?
     GROUP BY day
     ORDER BY day ASC`,
  )
    .bind(sinceTs)
    .all<{ day: string; tokens: number; queries: number }>();

  const byUserRes = await env.DB.prepare(
    `SELECT u.display_name AS displayName, u.user_id AS userId, SUM(a.tokens_used) AS tokens, COUNT(*) AS queries
     FROM audit_log a
     JOIN users u ON u.user_id = a.user_id
     WHERE a.created_at >= ?
     GROUP BY a.user_id
     ORDER BY tokens DESC`,
  )
    .bind(sinceTs)
    .all<{
      displayName: string;
      userId: string;
      tokens: number;
      queries: number;
    }>();

  return jsonResponse(200, {
    daily: dailyRes.results ?? [],
    byUser: byUserRes.results ?? [],
    days,
    status: "ok",
  });
}

// POST /admin/rating-stats — チャット履歴への評価（役に立った/立たなかった）の集計
// （既存GAS adminRatingStats相当）。memoryテーブルは既に評価を保持しているため追加スキーマ不要。
export async function handleRatingStats(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);

  const totalsRes = await env.DB.prepare(
    `SELECT
       COUNT(*) AS total,
       SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS good,
       SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) AS bad,
       SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) AS unrated
     FROM memory`,
  ).first<{ total: number; good: number; bad: number; unrated: number }>();

  const byUserRes = await env.DB.prepare(
    `SELECT u.display_name AS displayName, m.user_id AS userId,
            COUNT(*) AS total,
            SUM(CASE WHEN m.rating = 1 THEN 1 ELSE 0 END) AS good,
            SUM(CASE WHEN m.rating = -1 THEN 1 ELSE 0 END) AS bad
     FROM memory m
     JOIN users u ON u.user_id = m.user_id
     GROUP BY m.user_id
     ORDER BY total DESC`,
  ).all<{ displayName: string; userId: string; total: number; good: number; bad: number }>();

  return jsonResponse(200, {
    total: totalsRes?.total ?? 0,
    good: totalsRes?.good ?? 0,
    bad: totalsRes?.bad ?? 0,
    unrated: totalsRes?.unrated ?? 0,
    byUser: byUserRes.results ?? [],
    status: "ok",
  });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
