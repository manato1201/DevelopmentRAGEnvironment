import type { AuthedUser, Env, QueryRequest, QueryResponse, SourceEntry } from "./types";
import { jsonResponse } from "./http";
import { buildAnswerPrompt, generateAnswer, generateAnswerStream, sha256Hex } from "./embeddings";
import { answerWithMcpTools, type McpPendingAction, type McpToolCallLog } from "./mcp/chat";
import { BudgetExceededError, reserveBudget, reconcileBudget } from "./budget";
import { assertNotRateLimited } from "./rateLimit";
import { buildContextTexts, resolveEffectiveNamespaces, retrieve } from "./retrieve";
import { normalizeContextHint } from "./houdiniContext";
import { saveMemory } from "./memory";
import { touchThread } from "./threads";
import { startAuditLog, finalizeAuditLog } from "./auditLog";

// クエリ添付画像（VLM入力）の既定上限。既存GASのDEFAULT_MAX_QUERY_IMAGE_MBと同じ値。
const MAX_QUERY_IMAGE_BYTES = 8 * 1024 * 1024;

// budget.tsのreserveBudget用の見積もりトークン数。HyDE仮回答＋最終回答生成の実測値は
// 通常これより十分小さいが、上振れに備えてやや多めに見積もる（実測との差分は
// reconcileBudgetで払い戻す・追加加算する）。
const RAG_RESERVE_ESTIMATE = 4000;

// 検索（準備）までの結果。生成はこの後（finishQuery）で行う。
interface PreparedQuery {
  query: string;
  history: Array<{ role: string; content: string }>;
  image?: { mimeType: string; data: string };
  effective: string[];
  level: string;
  auditId: number;
  texts: string[];
  sources: SourceEntry[];
  excerpts: string[]; // 各出典の本文の抜粋（ドロワー用。生成の後でsourcesに付ける）
  ingestedAts: Array<number | undefined>; // 各出典の登録日時（鮮度表示用）
  hydeTokensUsed: number;
}

// 入力の確認・レート制限・予算の確保・検索まで（生成の前）。早期に返す応答（入力不備・アクセス可能な
// namespaceなし）は response で返す。検索で失敗したときは、確保した予算を払い戻して例外を投げる。
async function prepareQuery(
  env: Env,
  user: AuthedUser,
  body: QueryRequest,
): Promise<{ response: Response } | { prepared: PreparedQuery }> {
  const query = (body.query || "").trim();
  // 会話の文脈は、直近6件・1件800文字までにする（プロンプトの肥大化と、巨大な入力の持ち込みを防ぐ）。
  const history = (body.history ?? [])
    .slice(-6)
    .map((h) => ({ role: h.role === "assistant" ? "assistant" : "user", content: String(h.content ?? "").slice(0, 800) }));
  const limit = body.limit ?? 5;
  const level = body.level || "";

  if (!query) return { response: jsonResponse(400, { error: "query は必須です" }) };

  // 質問に添付された画像（既存GASの`image: {mimeType, data}`と同一契約、2026-08-27追加）。
  // 検索・埋め込みには使わず、最終回答生成のときだけGeminiに渡す。
  const image = body.image?.data && body.image?.mimeType ? body.image : undefined;
  if (image) {
    const imageBytes = Math.floor((image.data.length * 3) / 4); // base64→バイト数の概算
    if (imageBytes > MAX_QUERY_IMAGE_BYTES) {
      return { response: jsonResponse(400, { error: `添付画像が大きすぎます（上限 ${Math.floor(MAX_QUERY_IMAGE_BYTES / 1024 / 1024)}MB）。` }) };
    }
  }

  const effective = resolveEffectiveNamespaces(user, body.namespaces);

  await assertNotRateLimited(env, user.userId);

  if (effective.length === 0) {
    return {
      response: jsonResponse(200, {
        answer: "アクセス可能なnamespaceがありません。",
        sources: [],
        status: "ok",
        namespaces: effective,
        extractionRate: 0,
        extractionDetail: "0/0",
      } satisfies QueryResponse),
    };
  }

  // queryHashはリクエスト開始時点で分かる情報だけから計算できるため、高価な処理
  // （HyDE・埋め込み・検索・生成）の前に先にaudit_log行を書き込む（rateLimit.tsの
  // 説明・auditLog.tsのコメント参照。2026-09-04、同時多発リクエストがレート制限を
  // すり抜けられた不備を修正）。
  const queryHash = await sha256Hex(query);
  const auditId = await startAuditLog(env, user.userId, effective.join(","), queryHash, level || null);

  const reserved = await reserveBudget(env, user.userId, "rag", RAG_RESERVE_ESTIMATE);
  if (!reserved) throw new BudgetExceededError("rag");

  try {
    const { ranked, hydeTokensUsed, contextNote } = await retrieve(env, user, query, effective, level, limit, normalizeContextHint(body.context));
    const { texts, sources } = buildContextTexts(ranked, contextNote);
    return {
      prepared: {
        query,
        history,
        image,
        effective,
        level,
        auditId,
        texts,
        sources,
        excerpts: ranked.map((r) => (r.metadata.text ?? "").slice(0, 400)),
        ingestedAts: ranked.map((r) => r.metadata.ingested_at),
        hydeTokensUsed,
      },
    };
  } catch (err) {
    // 予約した見積もり分は、検索で失敗した以上ここで払い戻す
    await reconcileBudget(env, user.userId, "rag", RAG_RESERVE_ESTIMATE, 0);
    throw err;
  }
}

// 回答の生成から後始末まで。onDeltaを渡すと、生成された本文を届いた分ずつ呼び出し元へ渡す
// （ストリーミング。外部サービスのツール（useMcp）を使うときは対象外で、一括で返す）。
async function finishQuery(
  env: Env,
  user: AuthedUser,
  body: QueryRequest,
  prepared: PreparedQuery,
  onDelta?: (text: string) => void,
): Promise<QueryResponse> {
  const { query, history, image, effective, auditId, texts, sources, hydeTokensUsed } = prepared;
  let toolCalls: McpToolCallLog[] = [];
  let pendingActions: McpPendingAction[] = [];
  let answerText: string;
  let sourcesWithCitation: SourceEntry[];
  let extractionRate: number;
  let cited: number;
  let tokensUsed: number;
  let inputTokens: number;
  let outputTokens: number;
  try {
    // 外部サービスのMCPツールも使う指定（useMcp）。使えるツールが無ければ従来どおり検索結果だけで答える。
    const mcpResult = body.useMcp
      ? await answerWithMcpTools(env, user.userId, buildAnswerPrompt(query, texts, history, true), image)
      : null;
    const answerResult = mcpResult
      ? { text: mcpResult.text, promptTokens: mcpResult.promptTokens, candidateTokens: mcpResult.candidateTokens }
      : onDelta
        ? await generateAnswerStream(env, query, texts, history, onDelta, image)
        : await generateAnswer(env, query, texts, history, image);
    if (mcpResult) {
      toolCalls = mcpResult.toolCalls;
      pendingActions = mcpResult.pendingActions;
    }
    const parsed = parseExtractionRate(answerResult.text, sources.length);
    cited = parsed.cited;
    sourcesWithCitation = sources.map((s, i) => ({
      ...s,
      cited: parsed.citationCounts[i] > 0,
      citationCount: parsed.citationCounts[i],
      excerpt: prepared.excerpts[i],
      ingestedAt: prepared.ingestedAts[i],
    }));
    extractionRate = sources.length > 0 ? Math.round((cited / sources.length) * 100) : 0;
    answerText = answerResult.text;
    // Gemini API使用量・コスト可視化（2026-09-10追加、Claude側と同じ仕組みをRAG側にも
    // 適用）。HyDE呼び出し自体のinput/output内訳は取得していないため、安全側で
    // 全量をinput側に寄せている（HyDEは短い仮回答を生成するだけで出力トークンの
    // 比率が小さく、見積もり誤差への影響は限定的と判断）。
    inputTokens = hydeTokensUsed + answerResult.promptTokens;
    outputTokens = answerResult.candidateTokens;
    tokensUsed = inputTokens + outputTokens;
  } catch (err) {
    // 予約した見積もり分は、実際には(部分的にせよ)完走しなかった以上ここで払い戻す
    // （厳密には検索段階までは実コストが発生しているが、失敗したリクエストにまで
    // 課金し続けるより「失敗時は全額払い戻す」方が実利にかなうと判断）。
    await reconcileBudget(env, user.userId, "rag", RAG_RESERVE_ESTIMATE, 0);
    throw err;
  }

  await reconcileBudget(env, user.userId, "rag", RAG_RESERVE_ESTIMATE, tokensUsed);
  await finalizeAuditLog(env, auditId, {
    resultCount: sources.length,
    latencyMs: null,
    tokensUsed,
    inputTokens,
    outputTokens,
    model: env.GENERATION_MODEL || "gemini-flash-latest",
  });

  const threadId = await touchThread(env, user.userId, body.threadId, query);
  const memoryId = await saveMemory(env, user.userId, query, answerText, sourcesWithCitation, effective, threadId);

  return {
    answer: answerText,
    sources: sourcesWithCitation,
    status: "ok",
    namespaces: effective,
    extractionRate,
    extractionDetail: `${cited}/${sources.length}`,
    memoryId,
    ...(toolCalls.length > 0 ? { toolCalls } : {}),
    ...(pendingActions.length > 0 ? { pendingActions } : {}),
  } satisfies QueryResponse;
}

// POST /query — 既存 rag_local_bridge.py の /query と同一契約。LLMを介した最終回答まで生成する
// （/searchは検索結果のみを返す「生」のエンドポイント、/queryはチャット用の完成回答を返す）。
export async function handleQuery(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as QueryRequest;
  const prep = await prepareQuery(env, user, body);
  if ("response" in prep) return prep.response;
  return jsonResponse(200, await finishQuery(env, user, body, prep.prepared));
}

// POST /query/stream — 回答を生成しながら届ける（Server-Sent Events、2026-10-16追加）。
// 入力の不備・レート制限・予算超過など、生成の前に決まるものは通常のJSON応答（4xx）で返す。
// 生成が始まってからは、次のイベントを順に送る:
//   sources … 検索で見つかった出典（回答より先に出せる）  { sources, namespaces }
//   delta   … 回答の本文の続き                            { text }
//   done    … 完成した応答（/queryと同じ形）              { ...QueryResponse }
//   error   … 生成の途中で失敗した                        { error }
// 外部サービスのツール（useMcp）を使うときは、生成を一括で行い、通常のJSONで返す（クライアントは
// content-typeで判別する）。
export async function handleQueryStream(req: Request, env: Env, user: AuthedUser, ctx?: ExecutionContext): Promise<Response> {
  const body = (await req.json()) as QueryRequest;
  const prep = await prepareQuery(env, user, body);
  if ("response" in prep) return prep.response;
  const prepared = prep.prepared;
  if (body.useMcp) return jsonResponse(200, await finishQuery(env, user, body, prepared));

  const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();
  const send = (event: string, data: unknown): Promise<void> =>
    writer.write(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)).catch(() => undefined);

  const run = (async () => {
    try {
      await send("sources", {
        sources: prepared.sources.map((s, i) => ({ ...s, excerpt: prepared.excerpts[i], ingestedAt: prepared.ingestedAts[i] })),
        namespaces: prepared.effective,
      });
      // 書き込みの完了は待たずに（遅いクライアントで生成を止めない）、順序は保ったまま流す
      let chain: Promise<void> = Promise.resolve();
      const result = await finishQuery(env, user, body, prepared, (text) => {
        chain = chain.then(() => send("delta", { text }));
      });
      await chain;
      await send("done", result);
    } catch (err) {
      await send("error", { error: err instanceof Error ? err.message : String(err) });
    } finally {
      await writer.close().catch(() => undefined);
    }
  })();
  if (ctx) ctx.waitUntil(run);

  return new Response(readable, {
    headers: { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache, no-transform" },
  });
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

// 画面を介さずに（Slackなどから）質問して、回答と出典を得る。レート制限・トークン予算・namespaceの権限は
// 通常の質問と同じ。失敗は例外ではなく { ok: false, error } で返す。
export async function answerQuestion(
  env: Env,
  user: AuthedUser,
  body: QueryRequest,
): Promise<{ ok: true; answer: string; sources: SourceEntry[] } | { ok: false; error: string }> {
  try {
    const prep = await prepareQuery(env, user, body);
    if ("response" in prep) {
      const data = (await prep.response.json()) as { answer?: string; sources?: SourceEntry[]; error?: string };
      return prep.response.status === 200 && data.answer ? { ok: true, answer: data.answer, sources: data.sources ?? [] } : { ok: false, error: data.error || "質問を処理できませんでした" };
    }
    const result = await finishQuery(env, user, body, prep.prepared);
    return { ok: true, answer: result.answer, sources: result.sources };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
