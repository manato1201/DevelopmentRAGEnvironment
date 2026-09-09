import Anthropic from "@anthropic-ai/sdk";
import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { assertNotRateLimited } from "./rateLimit";
import { BudgetExceededError, reserveBudget, reconcileBudget } from "./budget";
import { sha256Hex } from "./embeddings";
import { startAuditLog, finalizeAuditLog } from "./auditLog";

const DEFAULT_MODEL = "claude-sonnet-5";
const DEFAULT_MAX_TOKENS = 4096;

// POST /claude/messages — Claude Messages APIへの薄いプロキシ（既存GAS callClaudeProxy_相当）。
// Houdiniチュートリアル生成エージェント（tutorial_agent.py）が、ツール実行ループの各ターンで
// Claudeを呼ぶために使う。エージェントループ自体はPython側にあり、ここは「APIキーをクライアント
// に渡さずに済むようにするだけの、ステートレスな中継」という設計をGASから踏襲している
// （RAG検索とは無関係。RAG生成は引き続きGemini・/query・/searchのみで行う）。
export async function handleClaudeMessages(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  if (!env.ANTHROPIC_API_KEY) {
    return jsonResponse(500, { error: "ANTHROPIC_API_KEYが設定されていません（wrangler secret put ANTHROPIC_API_KEY）" });
  }

  await assertNotRateLimited(env, user.userId);

  const body = (await req.json()) as {
    model?: string;
    max_tokens?: number;
    system?: Anthropic.MessageCreateParams["system"];
    tools?: Anthropic.Tool[];
    messages: Anthropic.MessageParam[];
    thinking?: Anthropic.MessageCreateParams["thinking"];
  };
  if (!Array.isArray(body.messages) || body.messages.length === 0) {
    return jsonResponse(400, { error: "messages は必須です（配列）" });
  }

  // 監査ログはRAG系と同じaudit_logテーブルを流用する（専用テーブルは追加しない）。
  // query_hashはクエリ本文の代わりにmessages全体のハッシュにしている（既存RAGAuditLoggerの
  // 「本文を残さない」方針を踏襲）。query.ts/search.tsと同じ理由で高価な呼び出しの前に
  // 書き込む（2026-09-04）。
  const queryHash = await sha256Hex(JSON.stringify(body.messages));
  const auditId = await startAuditLog(env, user.userId, "claude:proxy", queryHash, null);

  // 入力(system+messages+tools)の実トークン数は呼び出し前には分からないため、文字数/3で
  // 大まかに見積もる（日本語混在を踏まえ安全側に厚めの係数）。出力側はmax_tokensが
  // 確定した上限なのでそのまま使う。実測との差分はreconcileBudgetで清算する。
  const maxTokens = body.max_tokens ?? DEFAULT_MAX_TOKENS;
  const inputEstimate = Math.ceil(JSON.stringify(body.messages).length / 3);
  const estimate = maxTokens + inputEstimate;
  const reserved = await reserveBudget(env, user.userId, "claude", estimate);
  if (!reserved) throw new BudgetExceededError("claude");

  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
  const start = Date.now();

  let response: Anthropic.Message;
  try {
    response = await client.messages.create({
      model: body.model || DEFAULT_MODEL,
      max_tokens: maxTokens,
      system: body.system,
      tools: body.tools,
      messages: body.messages,
      ...(body.thinking ? { thinking: body.thinking } : {}),
    });
  } catch (err) {
    await reconcileBudget(env, user.userId, "claude", estimate, 0);
    if (err instanceof Anthropic.APIError) {
      return jsonResponse(err.status ?? 500, { error: err.message });
    }
    return jsonResponse(500, { error: err instanceof Error ? err.message : String(err) });
  }

  const latencyMs = Date.now() - start;
  const totalTokens = (response.usage?.input_tokens ?? 0) + (response.usage?.output_tokens ?? 0);
  await reconcileBudget(env, user.userId, "claude", estimate, totalTokens);
  await finalizeAuditLog(env, auditId, { resultCount: 0, latencyMs, tokensUsed: totalTokens });

  return jsonResponse(200, response);
}
