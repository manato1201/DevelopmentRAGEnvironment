import type { AuthedUser, Env, QueryRequest, QueryResponse, SourceEntry } from "./types";
import { generateAnswer, sha256Hex } from "./embeddings";
import { assertBudgetAvailable } from "./budget";
import { assertNotRateLimited } from "./rateLimit";
import { buildContextTexts, consumeBudget, resolveEffectiveNamespaces, retrieve } from "./retrieve";
import { saveMemory } from "./memory";

// クエリ添付画像（VLM入力）の既定上限。既存GASのDEFAULT_MAX_QUERY_IMAGE_MBと同じ値。
const MAX_QUERY_IMAGE_BYTES = 8 * 1024 * 1024;

// POST /query — 既存 rag_local_bridge.py の /query と同一契約。LLMを介した最終回答まで生成する
// （/searchは検索結果のみを返す「生」のエンドポイント、/queryはチャット用の完成回答を返す）。
export async function handleQuery(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as QueryRequest;
  const query = (body.query || "").trim();
  const history = body.history?.map((h) => ({ role: h.role, content: h.content })) ?? [];
  const limit = body.limit ?? 5;
  const level = body.level || "";

  if (!query) return jsonResponse(400, { error: "query は必須です" });

  // 質問に添付された画像（既存GASの`image: {mimeType, data}`と同一契約、2026-08-27追加）。
  // 検索・埋め込みには使わず、最終回答生成のときだけGeminiに渡す（下記generateAnswer呼び出し）。
  const image = body.image?.data && body.image?.mimeType ? body.image : undefined;
  if (image) {
    const imageBytes = Math.floor((image.data.length * 3) / 4); // base64→バイト数の概算
    if (imageBytes > MAX_QUERY_IMAGE_BYTES) {
      return jsonResponse(400, { error: `添付画像が大きすぎます（上限 ${Math.floor(MAX_QUERY_IMAGE_BYTES / 1024 / 1024)}MB）。` });
    }
  }

  const effective = resolveEffectiveNamespaces(user, body.namespaces);

  await assertNotRateLimited(env, user.userId);
  await assertBudgetAvailable(env, user.userId, "rag");

  if (effective.length === 0) {
    return jsonResponse(200, {
      answer: "アクセス可能なnamespaceがありません。",
      sources: [],
      status: "ok",
      namespaces: effective,
      extractionRate: 0,
      extractionDetail: "0/0",
    } satisfies QueryResponse);
  }

  const { ranked, hydeTokensUsed } = await retrieve(env, user, query, effective, level, limit);
  const { texts, sources } = buildContextTexts(ranked);

  const answerResult = await generateAnswer(env, query, texts, history, image);
  const { cited, citationCounts } = parseExtractionRate(answerResult.text, sources.length);
  const sourcesWithCitation: SourceEntry[] = sources.map((s, i) => ({ ...s, cited: citationCounts[i] > 0, citationCount: citationCounts[i] }));
  const extractionRate = sources.length > 0 ? Math.round((cited / sources.length) * 100) : 0;

  const tokensUsed = hydeTokensUsed + answerResult.promptTokens + answerResult.candidateTokens;
  await consumeBudget(env, user.userId, "rag", tokensUsed);

  const queryHash = await sha256Hex(query);
  await env.DB.prepare(
    "INSERT INTO audit_log (user_id, namespace_id, query_hash, difficulty, result_count, latency_ms, tokens_used, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
  )
    .bind(user.userId, effective.join(","), queryHash, level || null, sources.length, null, tokensUsed, Math.floor(Date.now() / 1000))
    .run();

  const memoryId = await saveMemory(env, user.userId, query, answerResult.text, sourcesWithCitation, effective);

  return jsonResponse(200, {
    answer: answerResult.text,
    sources: sourcesWithCitation,
    status: "ok",
    namespaces: effective,
    extractionRate,
    extractionDetail: `${cited}/${sources.length}`,
    memoryId,
  } satisfies QueryResponse);
}

// 回答文中に [1] [2] 等の出典番号が実際に含まれているか、何回参照されたかを数える
// （既存GAS parseExtractionRate_相当。回数まで数えるのは2026-08-27追加）。
// 「AIが出典を提示せずに答えている＝知ったかぶりの可能性」を検知するハルシネーション対策に加え、
// 複数出典を引用した際に「どの出典が根拠として重く使われたか」を示す貢献度表示にも使う。
function parseExtractionRate(answer: string, total: number): { cited: number; citationCounts: number[] } {
  const citationCounts = new Array(total).fill(0);
  const matches = answer.matchAll(/\[(\d+)\]/g);
  for (const m of matches) {
    const idx = parseInt(m[1], 10) - 1;
    if (idx >= 0 && idx < total) citationCounts[idx] += 1;
  }
  return { cited: citationCounts.filter((c) => c > 0).length, citationCounts };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
