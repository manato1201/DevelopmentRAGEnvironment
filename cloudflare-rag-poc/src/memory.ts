import type { AuthedUser, Env, SourceEntry } from "./types";

export interface MemoryEntry {
  id: number;
  query: string;
  answer: string;
  sources: SourceEntry[];
  namespaces: string[];
  rating: number | null;
  createdAt: number;
}

// 会話1往復を保存する（既存GAS saveMemory_相当）。/query成功後に呼ぶ。
export async function saveMemory(
  env: Env,
  userId: string,
  query: string,
  answer: string,
  sources: SourceEntry[],
  namespaces: string[]
): Promise<number> {
  const res = await env.DB.prepare(
    "INSERT INTO memory (user_id, query, answer, sources_json, namespaces, rating, created_at) VALUES (?, ?, ?, ?, ?, NULL, ?)"
  )
    .bind(userId, query, answer, JSON.stringify(sources), namespaces.join(","), Math.floor(Date.now() / 1000))
    .run();
  return res.meta.last_row_id as number;
}

// 直近の会話履歴を取得する（既存GAS getUserMemory相当。Webチャット画面の履歴表示に使う）。
export async function getUserMemory(env: Env, userId: string, limit: number): Promise<MemoryEntry[]> {
  const res = await env.DB.prepare(
    "SELECT id, query, answer, sources_json, namespaces, rating, created_at FROM memory WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
  )
    .bind(userId, limit)
    .all<{ id: number; query: string; answer: string; sources_json: string; namespaces: string | null; rating: number | null; created_at: number }>();

  return (res.results ?? []).map((r) => ({
    id: r.id,
    query: r.query,
    answer: r.answer,
    sources: JSON.parse(r.sources_json) as SourceEntry[],
    namespaces: r.namespaces ? r.namespaces.split(",") : [],
    rating: r.rating,
    createdAt: r.created_at,
  }));
}

// 過去の回答への評価（役に立った/立たなかった）を記録する（既存GAS rateMemoryEntry相当）。
// 他人のmemoryを評価できないよう、user_idも条件に含める。
export async function rateMemoryEntry(env: Env, userId: string, id: number, rating: number): Promise<boolean> {
  const res = await env.DB.prepare("UPDATE memory SET rating = ? WHERE id = ? AND user_id = ?")
    .bind(rating, id, userId)
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

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
