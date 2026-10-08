import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { jsonResponse, clampInt } from "./http";

// Houdiniチュートリアル生成への評価（2026-10-05追加、migrations/0017）。
//   POST /tutorial-feedback/submit        … 評価の送信（認証済みの全ユーザー。自分の評価のみ作成・更新・削除）
//   POST /admin/tutorial-feedback/list    … 評価の一覧（admin専用）
//   POST /admin/tutorial-feedback/stats   … 評価の集計（admin専用）
// 閲覧・集計は管理者に限る。送信側は評価者本人のuser_idでしか書けない（他人の行は触れない）。

const MAX_TEXT = 300;
const MAX_NOTE = 2000;
const MAX_OVERVIEW = 600;
const MAX_TAGS = 10;
const MAX_TAG_LEN = 40;
const MAX_METRICS_BYTES = 8000;

export interface FeedbackSubmit {
  tutorialKey?: unknown;
  title?: unknown;
  topic?: unknown;
  level?: unknown;
  model?: unknown;
  ragName?: unknown;
  houdiniVersion?: unknown;
  rating?: unknown;
  tags?: unknown;
  note?: unknown;
  overview?: unknown;
  metrics?: unknown;
}

function text(value: unknown, max: number): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

export function sanitizeTags(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  for (const item of raw) {
    const tag = text(item, MAX_TAG_LEN);
    if (tag) seen.add(tag);
    if (seen.size >= MAX_TAGS) break;
  }
  return [...seen];
}

// metricsは数値・真偽値・短い文字列だけを通す（任意の入れ子データを保存させない）。
export function sanitizeMetrics(raw: unknown): Record<string, number | boolean | string> {
  const out: Record<string, number | boolean | string> = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!/^[A-Za-z0-9_]{1,40}$/.test(key)) continue;
    if (typeof value === "number" && Number.isFinite(value)) out[key] = value;
    else if (typeof value === "boolean") out[key] = value;
    else if (typeof value === "string") out[key] = value.slice(0, 120);
    if (Object.keys(out).length >= 40) break;
  }
  return out;
}

export async function handleTutorialFeedbackSubmit(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => null)) as FeedbackSubmit | null;
  if (!body) return jsonResponse(400, { error: "JSONボディが必要です" });

  const tutorialKey = text(body.tutorialKey, 200);
  if (!tutorialKey) return jsonResponse(400, { error: "tutorialKey は必須です" });
  const rating = Number(body.rating);
  if (![1, -1, 0].includes(rating)) {
    return jsonResponse(400, { error: "rating は 1（良い）/ -1（悪い）/ 0（取り消し）のいずれかです" });
  }

  // rating=0は評価の取り消し（自分の行のみ）。
  if (rating === 0) {
    await env.DB.prepare("DELETE FROM tutorial_feedback WHERE user_id = ? AND tutorial_key = ?")
      .bind(user.userId, tutorialKey)
      .run();
    return jsonResponse(200, { status: "ok", deleted: true });
  }

  const metrics = sanitizeMetrics(body.metrics);
  const metricsJson = JSON.stringify(metrics);
  if (metricsJson.length > MAX_METRICS_BYTES) {
    return jsonResponse(400, { error: "metrics が大きすぎます" });
  }
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare(
    `INSERT INTO tutorial_feedback
       (user_id, tutorial_key, title, topic, level, model, rag_name, houdini_version,
        rating, tags_json, note, overview, metrics_json, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(user_id, tutorial_key) DO UPDATE SET
       title = excluded.title, topic = excluded.topic, level = excluded.level, model = excluded.model,
       rag_name = excluded.rag_name, houdini_version = excluded.houdini_version,
       rating = excluded.rating, tags_json = excluded.tags_json, note = excluded.note,
       overview = excluded.overview, metrics_json = excluded.metrics_json, updated_at = excluded.updated_at`,
  )
    .bind(
      user.userId,
      tutorialKey,
      text(body.title, MAX_TEXT),
      text(body.topic, MAX_TEXT),
      text(body.level, 20) || null,
      text(body.model, 60) || null,
      text(body.ragName, 40) || null,
      text(body.houdiniVersion, 20) || null,
      rating,
      JSON.stringify(sanitizeTags(body.tags)),
      text(body.note, MAX_NOTE),
      text(body.overview, MAX_OVERVIEW),
      metricsJson,
      now,
      now,
    )
    .run();
  return jsonResponse(200, { status: "ok" });
}

interface FeedbackRow {
  feedback_id: number;
  user_id: string;
  displayName: string | null;
  tutorial_key: string;
  title: string;
  topic: string;
  level: string | null;
  model: string | null;
  rag_name: string | null;
  houdini_version: string | null;
  rating: number;
  tags_json: string;
  note: string;
  overview: string;
  metrics_json: string;
  created_at: number;
  updated_at: number;
}

function parseJson<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function shape(row: FeedbackRow) {
  return {
    id: row.feedback_id,
    userId: row.user_id,
    displayName: row.displayName,
    tutorialKey: row.tutorial_key,
    title: row.title,
    topic: row.topic,
    level: row.level,
    model: row.model,
    ragName: row.rag_name,
    houdiniVersion: row.houdini_version,
    rating: row.rating,
    tags: parseJson<string[]>(row.tags_json, []),
    note: row.note,
    overview: row.overview,
    metrics: parseJson<Record<string, number | boolean | string>>(row.metrics_json, {}),
    updatedAt: row.updated_at,
  };
}

const SELECT_COLUMNS = `f.feedback_id, f.user_id, u.display_name AS displayName, f.tutorial_key, f.title, f.topic,
       f.level, f.model, f.rag_name, f.houdini_version, f.rating, f.tags_json, f.note, f.overview,
       f.metrics_json, f.created_at, f.updated_at`;

export async function handleTutorialFeedbackList(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as {
    limit?: number;
    days?: number;
    rating?: number;
    model?: string;
    level?: string;
    user?: string;
  };
  const limit = clampInt(body.limit, 100, 1, 500);
  const conditions: string[] = [];
  const params: (string | number)[] = [];
  if (body.days != null) {
    conditions.push("f.updated_at >= ?");
    params.push(Math.floor(Date.now() / 1000) - clampInt(body.days, 30, 1, 3650) * 86400);
  }
  if (body.rating === 1 || body.rating === -1) {
    conditions.push("f.rating = ?");
    params.push(body.rating);
  }
  if (body.model) {
    conditions.push("f.model = ?");
    params.push(body.model);
  }
  if (body.level) {
    conditions.push("f.level = ?");
    params.push(body.level);
  }
  if (body.user) {
    conditions.push("u.display_name LIKE ?");
    params.push(`%${body.user}%`);
  }
  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
  params.push(limit);
  const res = await env.DB.prepare(
    `SELECT ${SELECT_COLUMNS}
     FROM tutorial_feedback f
     LEFT JOIN users u ON u.user_id = f.user_id
     ${where}
     ORDER BY f.updated_at DESC
     LIMIT ?`,
  )
    .bind(...params)
    .all<FeedbackRow>();
  return jsonResponse(200, { entries: (res.results ?? []).map(shape), status: "ok" });
}

interface Bucket {
  key: string;
  total: number;
  good: number;
  bad: number;
  goodRate: number | null;
  avgIterations: number | null;
  avgCostUsd: number | null;
  avgCookErrors: number | null;
}

function numberMetric(metrics: Record<string, number | boolean | string>, key: string): number | null {
  const value = metrics[key];
  return typeof value === "number" ? value : null;
}

function bucketize(rows: ReturnType<typeof shape>[], keyOf: (row: ReturnType<typeof shape>) => string[]): Bucket[] {
  const map = new Map<string, ReturnType<typeof shape>[]>();
  for (const row of rows) {
    for (const key of keyOf(row)) {
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(row);
    }
  }
  const average = (items: ReturnType<typeof shape>[], metric: string): number | null => {
    const values = items.map((r) => numberMetric(r.metrics, metric)).filter((v): v is number => v != null);
    return values.length === 0 ? null : values.reduce((a, b) => a + b, 0) / values.length;
  };
  return [...map.entries()]
    .map(([key, items]) => {
      const good = items.filter((r) => r.rating === 1).length;
      const bad = items.filter((r) => r.rating === -1).length;
      return {
        key,
        total: items.length,
        good,
        bad,
        goodRate: good + bad === 0 ? null : good / (good + bad),
        avgIterations: average(items, "iterations"),
        avgCostUsd: average(items, "cost_usd"),
        avgCookErrors: average(items, "cook_errors"),
      };
    })
    .sort((a, b) => b.total - a.total);
}

export async function handleTutorialFeedbackStats(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { days?: number };
  const since = Math.floor(Date.now() / 1000) - clampInt(body.days, 90, 1, 3650) * 86400;
  const res = await env.DB.prepare(
    `SELECT ${SELECT_COLUMNS}
     FROM tutorial_feedback f
     LEFT JOIN users u ON u.user_id = f.user_id
     WHERE f.updated_at >= ?
     ORDER BY f.updated_at DESC
     LIMIT 5000`,
  )
    .bind(since)
    .all<FeedbackRow>();
  const rows = (res.results ?? []).map(shape);
  const good = rows.filter((r) => r.rating === 1).length;
  const bad = rows.filter((r) => r.rating === -1).length;
  return jsonResponse(200, {
    total: rows.length,
    good,
    bad,
    goodRate: good + bad === 0 ? null : good / (good + bad),
    byModel: bucketize(rows, (r) => [r.model || "（不明）"]),
    byLevel: bucketize(rows, (r) => [r.level || "（不明）"]),
    byKnowledge: bucketize(rows, (r) => [r.ragName || "（不明）"]),
    byDomain: bucketize(rows, (r) => {
      const domain = r.metrics["domain"];
      return [typeof domain === "string" && domain ? domain : "general"];
    }),
    byTag: bucketize(rows, (r) => r.tags).slice(0, 30),
    status: "ok",
  });
}
