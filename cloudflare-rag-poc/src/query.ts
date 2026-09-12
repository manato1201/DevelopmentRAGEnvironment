import type { AuthedUser, Env, QueryRequest, QueryResponse, SourceEntry } from "./types";
import { jsonResponse } from "./http";
import { generateAnswer, sha256Hex } from "./embeddings";
import { BudgetExceededError, reserveBudget, reconcileBudget } from "./budget";
import { assertNotRateLimited } from "./rateLimit";
import { buildContextTexts, resolveEffectiveNamespaces, retrieve } from "./retrieve";
import { saveMemory } from "./memory";
import { startAuditLog, finalizeAuditLog } from "./auditLog";

// クエリ添付画像（VLM入力）の既定上限。既存GASのDEFAULT_MAX_QUERY_IMAGE_MBと同じ値。
const MAX_QUERY_IMAGE_BYTES = 8 * 1024 * 1024;

// budget.tsのreserveBudget用の見積もりトークン数。HyDE仮回答＋最終回答生成の実測値は
// 通常これより十分小さいが、上振れに備えてやや多めに見積もる（実測との差分は
// reconcileBudgetで払い戻す・追加加算する）。
const RAG_RESERVE_ESTIMATE = 4000;

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

  // queryHashはリクエスト開始時点で分かる情報だけから計算できるため、高価な処理
  // （HyDE・埋め込み・検索・生成）の前に先にaudit_log行を書き込む（rateLimit.tsの
  // 説明・auditLog.tsのコメント参照。2026-09-04、同時多発リクエストがレート制限を
  // すり抜けられた不備を修正）。
  const queryHash = await sha256Hex(query);
  const auditId = await startAuditLog(env, user.userId, effective.join(","), queryHash, level || null);

  const reserved = await reserveBudget(env, user.userId, "rag", RAG_RESERVE_ESTIMATE);
  if (!reserved) throw new BudgetExceededError("rag");

  let sourcesWithCitation: SourceEntry[];
  let extractionRate: number;
  let cited: number;
  let sourcesLength: number;
  let answerText: string;
  let tokensUsed: number;
  let inputTokens: number;
  let outputTokens: number;
  try {
    const { ranked, hydeTokensUsed } = await retrieve(env, user, query, effective, level, limit);
    const { texts, sources } = buildContextTexts(ranked);

    const answerResult = await generateAnswer(env, query, texts, history, image);
    const parsed = parseExtractionRate(answerResult.text, sources.length);
    cited = parsed.cited;
    sourcesWithCitation = sources.map((s, i) => ({ ...s, cited: parsed.citationCounts[i] > 0, citationCount: parsed.citationCounts[i] }));
    extractionRate = sources.length > 0 ? Math.round((cited / sources.length) * 100) : 0;
    sourcesLength = sources.length;
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
    resultCount: sourcesLength,
    latencyMs: null,
    tokensUsed,
    inputTokens,
    outputTokens,
    model: env.GENERATION_MODEL || "gemini-flash-latest",
  });

  const memoryId = await saveMemory(env, user.userId, query, answerText, sourcesWithCitation, effective);

  return jsonResponse(200, {
    answer: answerText,
    sources: sourcesWithCitation,
    status: "ok",
    namespaces: effective,
    extractionRate,
    extractionDetail: `${cited}/${sourcesLength}`,
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
