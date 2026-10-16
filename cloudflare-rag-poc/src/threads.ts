import type { AuthedUser, Env, SourceEntry } from "./types";
import type { MemoryEntry } from "./memory";
import { jsonResponse } from "./http";
import { ForbiddenError } from "./auth";

// 会話のスレッド（2026-10-16追加、migrations/0026）。自分の会話だけを扱う（他人のスレッドは見えない・触れない）。
const THREAD_ID_RE = /^[A-Za-z0-9_-]{8,64}$/;
const TITLE_MAX = 60;

export function isValidThreadId(id: unknown): id is string {
  return typeof id === "string" && THREAD_ID_RE.test(id);
}

function titleFromQuery(query: string): string {
  const oneLine = query.trim().replace(/\s+/g, " ");
  return oneLine.length > TITLE_MAX ? oneLine.slice(0, TITLE_MAX - 1) + "…" : oneLine;
}

// 質問を保存する前に呼ぶ。スレッドが無ければ（最初の質問の文を題名にして）作り、あれば更新日時を進める。
// 他のユーザーが持つthread_idが渡された場合は、そのスレッドには触らず、nullを返す（スレッドに入れない）。
export async function touchThread(env: Env, userId: string, threadId: unknown, firstQuery: string): Promise<string | null> {
  if (!isValidThreadId(threadId)) return null;
  const now = Math.floor(Date.now() / 1000);
  const existing = await env.DB.prepare("SELECT user_id FROM threads WHERE thread_id = ?").bind(threadId).first<{ user_id: string }>();
  if (existing) {
    if (existing.user_id !== userId) return null;
    await env.DB.prepare("UPDATE threads SET updated_at = ? WHERE thread_id = ? AND user_id = ?").bind(now, threadId, userId).run();
    return threadId;
  }
  await env.DB.prepare("INSERT INTO threads (thread_id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)")
    .bind(threadId, userId, titleFromQuery(firstQuery) || "（無題）", now, now)
    .run();
  return threadId;
}

function requireMember(user: AuthedUser): void {
  if (user.role === "guest") throw new ForbiddenError("ゲストは会話の履歴を使えません");
}

// LIKEのワイルドカードを無効にする（検索語の % と _ をそのまま探す）。エスケープ文字は ! を使う。
function likePattern(q: string): string {
  return "%" + q.replace(/[!%_]/g, (c) => "!" + c) + "%";
}

// POST /threads/list — body: { q?（題名・質問・回答の本文を検索）, limit?（既定50、最大200） }
export async function handleThreadList(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  const body = (await req.json().catch(() => ({}))) as { q?: string; limit?: number };
  const q = (body.q || "").trim().slice(0, 100);
  const limit = Math.max(1, Math.min(Number.isFinite(body.limit) ? Math.floor(body.limit as number) : 50, 200));
  const binds: Array<string | number> = [user.userId];
  let where = "t.user_id = ?";
  if (q) {
    const pat = likePattern(q);
    where += ` AND (t.title LIKE ? ESCAPE '!' OR EXISTS (SELECT 1 FROM memory m WHERE m.thread_id = t.thread_id AND m.user_id = t.user_id AND (m.query LIKE ? ESCAPE '!' OR m.answer LIKE ? ESCAPE '!')))`;
    binds.push(pat, pat, pat);
  }
  const res = await env.DB.prepare(
    `SELECT t.thread_id, t.title, t.created_at, t.updated_at,
            (SELECT COUNT(*) FROM memory m WHERE m.thread_id = t.thread_id AND m.user_id = t.user_id) AS turns
       FROM threads t WHERE ${where} ORDER BY t.updated_at DESC LIMIT ?`,
  )
    .bind(...binds, limit)
    .all<{ thread_id: string; title: string; created_at: number; updated_at: number; turns: number }>();
  const legacy = await env.DB.prepare("SELECT COUNT(*) AS c FROM memory WHERE user_id = ? AND thread_id IS NULL").bind(user.userId).first<{ c: number }>();
  return jsonResponse(200, {
    status: "ok",
    threads: (res.results ?? []).map((r) => ({ threadId: r.thread_id, title: r.title, turns: r.turns, createdAt: r.created_at, updatedAt: r.updated_at })),
    legacyCount: legacy?.c ?? 0,
  });
}

// POST /threads/get — body: { threadId }。そのスレッドの質問と回答を古い順に返す（自分のスレッドだけ）。
export async function handleThreadGet(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  const body = (await req.json().catch(() => ({}))) as { threadId?: string };
  if (!isValidThreadId(body.threadId)) return jsonResponse(400, { error: "threadId が不正です" });
  const thread = await env.DB.prepare("SELECT thread_id, title FROM threads WHERE thread_id = ? AND user_id = ?").bind(body.threadId, user.userId).first<{ thread_id: string; title: string }>();
  if (!thread) return jsonResponse(404, { error: "スレッドが見つかりません" });
  const res = await env.DB.prepare(
    "SELECT id, query, answer, sources_json, namespaces, rating, pinned, created_at FROM memory WHERE thread_id = ? AND user_id = ? ORDER BY created_at ASC, id ASC",
  )
    .bind(body.threadId, user.userId)
    .all<{ id: number; query: string; answer: string; sources_json: string; namespaces: string | null; rating: number | null; pinned: number; created_at: number }>();
  const entries: MemoryEntry[] = (res.results ?? []).map((r) => ({
    id: r.id,
    query: r.query,
    answer: r.answer,
    sources: JSON.parse(r.sources_json) as SourceEntry[],
    namespaces: r.namespaces ? r.namespaces.split(",") : [],
    rating: r.rating,
    pinned: r.pinned === 1,
    createdAt: r.created_at,
  }));
  return jsonResponse(200, { status: "ok", threadId: thread.thread_id, title: thread.title, entries });
}

// POST /threads/rename — body: { threadId, title }
export async function handleThreadRename(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  const body = (await req.json().catch(() => ({}))) as { threadId?: string; title?: string };
  const title = (body.title || "").trim().slice(0, TITLE_MAX);
  if (!isValidThreadId(body.threadId) || !title) return jsonResponse(400, { error: "threadId と title は必須です" });
  const res = await env.DB.prepare("UPDATE threads SET title = ? WHERE thread_id = ? AND user_id = ?").bind(title, body.threadId, user.userId).run();
  if ((res.meta.changes ?? 0) === 0) return jsonResponse(404, { error: "スレッドが見つかりません" });
  return jsonResponse(200, { status: "ok" });
}

// POST /threads/delete — body: { threadId }。スレッドと、その中の質問と回答を消す（自分のものだけ）。
export async function handleThreadDelete(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  const body = (await req.json().catch(() => ({}))) as { threadId?: string };
  if (!isValidThreadId(body.threadId)) return jsonResponse(400, { error: "threadId が不正です" });
  await env.DB.prepare("DELETE FROM memory WHERE thread_id = ? AND user_id = ?").bind(body.threadId, user.userId).run();
  await env.DB.prepare("DELETE FROM threads WHERE thread_id = ? AND user_id = ?").bind(body.threadId, user.userId).run();
  return jsonResponse(200, { status: "ok" });
}
