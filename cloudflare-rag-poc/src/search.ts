import type { AuthedUser, Env, SearchRequest, SearchResponse } from "./types";
import { sha256Hex } from "./embeddings";
import { assertBudgetAvailable } from "./budget";
import { assertNotRateLimited } from "./rateLimit";
import { buildContextTexts, consumeBudget, resolveEffectiveNamespaces, retrieve } from "./retrieve";

// POST /search — 既存 rag_local_bridge.py の /search と同一契約（docs/cloud-local-unification-plan.md §8.3）。
// ハイブリッド検索（Vectorize + D1 FTS5のBM25をRRFで統合）＋HyDEクエリ変換を行う。
export async function handleSearch(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as SearchRequest;
  const query = (body.query || "").trim();
  const limit = body.limit ?? 6;
  const level = body.level || "";

  if (!query) return jsonResponse(400, { error: "query は必須です" });

  const effective = resolveEffectiveNamespaces(user, body.namespaces);
  if (effective.length === 0) {
    return jsonResponse(200, { texts: ["（アクセス可能なnamespaceがありません）"], sources: [], status: "ok" } satisfies SearchResponse);
  }

  await assertNotRateLimited(env, user.userId);
  await assertBudgetAvailable(env, user.userId, "rag");

  const { ranked, hydeTokensUsed } = await retrieve(env, user, query, effective, level, limit);
  const { texts, sources } = buildContextTexts(ranked);

  await consumeBudget(env, user.userId, "rag", hydeTokensUsed);

  const queryHash = await sha256Hex(query);
  await env.DB.prepare(
    "INSERT INTO audit_log (user_id, namespace_id, query_hash, difficulty, result_count, latency_ms, tokens_used, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
  )
    .bind(user.userId, effective.join(","), queryHash, level || null, sources.length, null, hydeTokensUsed, Math.floor(Date.now() / 1000))
    .run();

  return jsonResponse(200, { texts, sources, status: "ok" } satisfies SearchResponse);
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
