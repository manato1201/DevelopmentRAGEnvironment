import type { AuthedUser, Env, SearchRequest, SearchResponse } from "./types";
import { jsonResponse } from "./http";
import { sha256Hex } from "./embeddings";
import { BudgetExceededError, reserveBudget, reconcileBudget } from "./budget";
import { assertNotRateLimited } from "./rateLimit";
import { buildContextTexts, resolveEffectiveNamespaces, retrieve } from "./retrieve";
import { startAuditLog, finalizeAuditLog } from "./auditLog";

// query.tsと同じ理由の見積もりトークン数（/searchはHyDEのみでLLM本回答生成は行わないため
// RAG_RESERVE_ESTIMATEより小さい値で十分）。
const SEARCH_RESERVE_ESTIMATE = 1000;

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

  // query.tsと同じ理由でaudit_log行を高価な処理の前に書き込む（2026-09-04）。
  const queryHash = await sha256Hex(query);
  const auditId = await startAuditLog(env, user.userId, effective.join(","), queryHash, level || null);

  const reserved = await reserveBudget(env, user.userId, "rag", SEARCH_RESERVE_ESTIMATE);
  if (!reserved) throw new BudgetExceededError("rag");

  let texts: string[];
  let sources: SearchResponse["sources"];
  let hydeTokensUsed: number;
  try {
    const result = await retrieve(env, user, query, effective, level, limit);
    hydeTokensUsed = result.hydeTokensUsed;
    ({ texts, sources } = buildContextTexts(result.ranked));
  } catch (err) {
    await reconcileBudget(env, user.userId, "rag", SEARCH_RESERVE_ESTIMATE, 0);
    throw err;
  }

  await reconcileBudget(env, user.userId, "rag", SEARCH_RESERVE_ESTIMATE, hydeTokensUsed);
  await finalizeAuditLog(env, auditId, { resultCount: sources.length, latencyMs: null, tokensUsed: hydeTokensUsed });

  return jsonResponse(200, { texts, sources, status: "ok" } satisfies SearchResponse);
}
