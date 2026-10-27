import type { AuthedUser, Env, SourceEntry } from "./types";
import { jsonResponse } from "./http";

export interface MemoryEntry {
  id: number;
  query: string;
  answer: string;
  sources: SourceEntry[];
  namespaces: string[];
  rating: number | null;
  pinned: boolean;
  createdAt: number;
}

// 会話1往復を保存する（既存GAS saveMemory_相当）。/query成功後に呼ぶ。
export async function saveMemory(
  env: Env,
  userId: string,
  query: string,
  answer: string,
  sources: SourceEntry[],
  namespaces: string[],
  threadId: string | null = null,
  explainLevel: string | null = null, // "auto:applied" / "fixed:basic" / null（説明レベルの指定なし）。管理画面の集計用
): Promise<number> {
  const res = await env.DB.prepare(
    "INSERT INTO memory (user_id, query, answer, sources_json, namespaces, rating, created_at, thread_id, explain_level) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)"
  )
    .bind(userId, query, answer, JSON.stringify(sources), namespaces.join(","), Math.floor(Date.now() / 1000), threadId, explainLevel)
    .run();
  return res.meta.last_row_id as number;
}

type MemoryRow = { id: number; query: string; answer: string; sources_json: string; namespaces: string | null; rating: number | null; pinned: number; created_at: number };

function toMemoryEntry(r: MemoryRow): MemoryEntry {
  return {
    id: r.id,
    query: r.query,
    answer: r.answer,
    sources: JSON.parse(r.sources_json) as SourceEntry[],
    namespaces: r.namespaces ? r.namespaces.split(",") : [],
    rating: r.rating,
    pinned: r.pinned === 1,
    createdAt: r.created_at,
  };
}

// 直近の会話履歴を取得する（既存GAS getUserMemory相当。Webチャット画面の履歴表示に使う）。
export async function getUserMemory(env: Env, userId: string, limit: number): Promise<MemoryEntry[]> {
  const res = await env.DB.prepare(
    "SELECT id, query, answer, sources_json, namespaces, rating, pinned, created_at FROM memory WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
  )
    .bind(userId, limit)
    .all<MemoryRow>();

  return (res.results ?? []).map(toMemoryEntry);
}

// お気に入り登録した過去のQ&Aを取得する（2026-09-04追加。直近履歴の表示件数制限とは無関係に、
// ピン留めしたものは古くても一覧できるようにする）。
export async function getPinnedMemory(env: Env, userId: string): Promise<MemoryEntry[]> {
  const res = await env.DB.prepare(
    "SELECT id, query, answer, sources_json, namespaces, rating, pinned, created_at FROM memory WHERE user_id = ? AND pinned = 1 ORDER BY created_at DESC"
  )
    .bind(userId)
    .all<MemoryRow>();

  return (res.results ?? []).map(toMemoryEntry);
}

// 過去の回答への評価（役に立った/立たなかった）を記録する（既存GAS rateMemoryEntry相当）。
// 他人のmemoryを評価できないよう、user_idも条件に含める。
export async function rateMemoryEntry(env: Env, userId: string, id: number, rating: number): Promise<boolean> {
  const res = await env.DB.prepare("UPDATE memory SET rating = ? WHERE id = ? AND user_id = ?")
    .bind(rating, id, userId)
    .run();
  return (res.meta.changes ?? 0) > 0;
}

// お気に入り登録／解除（2026-09-04追加）。ratingと同じく他人のmemoryは操作できない。
export async function setMemoryPinned(env: Env, userId: string, id: number, pinned: boolean): Promise<boolean> {
  const res = await env.DB.prepare("UPDATE memory SET pinned = ? WHERE id = ? AND user_id = ?")
    .bind(pinned ? 1 : 0, id, userId)
    .run();
  return (res.meta.changes ?? 0) > 0;
}

export async function handleMemoryList(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { limit?: number };
  const limit = body.limit ?? 20;
  const entries = await getUserMemory(env, user.userId, limit);
  return jsonResponse(200, { entries, status: "ok" });
}

export async function handleMemoryRate(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { id?: number; rating?: number };
  if (typeof body.id !== "number" || typeof body.rating !== "number") {
    return jsonResponse(400, { error: "id と rating（数値）は必須です" });
  }
  const ok = await rateMemoryEntry(env, user.userId, body.id, body.rating);
  if (!ok) return jsonResponse(404, { error: "該当する履歴が見つかりません" });
  return jsonResponse(200, { status: "ok" });
}

export async function handleMemoryPin(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { id?: number; pinned?: boolean };
  if (typeof body.id !== "number" || typeof body.pinned !== "boolean") {
    return jsonResponse(400, { error: "id（数値）と pinned（真偽値）は必須です" });
  }
  const ok = await setMemoryPinned(env, user.userId, body.id, body.pinned);
  if (!ok) return jsonResponse(404, { error: "該当する履歴が見つかりません" });
  return jsonResponse(200, { status: "ok" });
}

// 回答1件を、本人のものだけ取り出す（回答へのリンク「#answer=<id>」を開いたときに使う。2026-10-22追加）。
export async function getMemoryById(env: Env, userId: string, id: number): Promise<MemoryEntry | null> {
  const row = await env.DB.prepare(
    "SELECT id, query, answer, sources_json, namespaces, rating, pinned, created_at FROM memory WHERE id = ? AND user_id = ?"
  )
    .bind(id, userId)
    .first<MemoryRow>();
  return row ? toMemoryEntry(row) : null;
}

export async function handleMemoryGet(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { id?: number };
  if (typeof body.id !== "number" || !Number.isInteger(body.id)) return jsonResponse(400, { error: "id（整数）は必須です" });
  const entry = await getMemoryById(env, user.userId, body.id);
  if (!entry) return jsonResponse(404, { error: "該当する履歴が見つかりません（他の人の回答へのリンクは開けません）" });
  return jsonResponse(200, { entry, status: "ok" });
}

// お気に入りの読み込み（書き出したJSONを戻す。2026-10-22追加）。本人の履歴として保存し、お気に入りにする。
// 外から来た文字列なので、件数・長さ・形を絞る（出典は表示に使う項目だけを残す）。
export const MAX_IMPORT_ENTRIES = 50;
const MAX_IMPORT_QUERY = 2000;
const MAX_IMPORT_ANSWER = 20000;
const MAX_IMPORT_SOURCES = 20;

function cleanSources(value: unknown): SourceEntry[] {
  if (!Array.isArray(value)) return [];
  const out: SourceEntry[] = [];
  for (const item of value.slice(0, MAX_IMPORT_SOURCES)) {
    if (!item || typeof item !== "object") continue;
    const s = item as Record<string, unknown>;
    if (typeof s.file !== "string" || typeof s.namespace !== "string") continue;
    const entry: SourceEntry = { file: s.file.slice(0, 300), namespace: s.namespace.slice(0, 100), score: typeof s.score === "number" ? s.score : 0 };
    if (typeof s.difficulty === "string") entry.difficulty = s.difficulty.slice(0, 20);
    if (typeof s.cited === "boolean") entry.cited = s.cited;
    if (typeof s.citationCount === "number") entry.citationCount = s.citationCount;
    if (typeof s.excerpt === "string") entry.excerpt = s.excerpt.slice(0, 400);
    if (typeof s.ingestedAt === "number") entry.ingestedAt = s.ingestedAt;
    out.push(entry);
  }
  return out;
}

export async function handleMemoryImport(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  if (user.role === "guest") return jsonResponse(403, { error: "ゲストは読み込みを使えません" });
  const body = (await req.json().catch(() => ({}))) as { entries?: unknown };
  if (!Array.isArray(body.entries) || body.entries.length === 0) return jsonResponse(400, { error: "entries（1件以上の配列）は必須です" });
  if (body.entries.length > MAX_IMPORT_ENTRIES) return jsonResponse(400, { error: `一度に読み込めるのは${MAX_IMPORT_ENTRIES}件までです` });
  let imported = 0;
  for (const raw of body.entries) {
    if (!raw || typeof raw !== "object") continue;
    const e = raw as Record<string, unknown>;
    if (typeof e.query !== "string" || typeof e.answer !== "string" || !e.query.trim() || !e.answer.trim()) continue;
    const sources = cleanSources(e.sources);
    const namespaces = [...new Set(sources.map((s) => s.namespace))];
    const id = await saveMemory(env, user.userId, e.query.slice(0, MAX_IMPORT_QUERY), e.answer.slice(0, MAX_IMPORT_ANSWER), sources, namespaces);
    await setMemoryPinned(env, user.userId, id, true);
    imported += 1;
  }
  return jsonResponse(200, { imported, skipped: body.entries.length - imported, status: "ok" });
}

export async function handlePinnedList(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const entries = await getPinnedMemory(env, user.userId);
  return jsonResponse(200, { entries, status: "ok" });
}
