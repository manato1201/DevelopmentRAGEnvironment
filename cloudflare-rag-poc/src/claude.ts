import Anthropic from "@anthropic-ai/sdk";
import type { AuthedUser, Env } from "./types";
import { assertNotRateLimited } from "./rateLimit";
import { assertBudgetAvailable, consumeBudget } from "./budget";
import { sha256Hex } from "./embeddings";

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
  await assertBudgetAvailable(env, user.userId, "claude");

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

  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
  const start = Date.now();

  let response: Anthropic.Message;
  try {
    response = await client.messages.create({
      model: body.model || DEFAULT_MODEL,
      max_tokens: body.max_tokens ?? DEFAULT_MAX_TOKENS,
      system: body.system,
      tools: body.tools,
      messages: body.messages,
      ...(body.thinking ? { thinking: body.thinking } : {}),
    });
  } catch (err) {
    if (err instanceof Anthropic.APIError) {
      return jsonResponse(err.status ?? 500, { error: err.message });
    }
    return jsonResponse(500, { error: err instanceof Error ? err.message : String(err) });
  }

  const latencyMs = Date.now() - start;
  const totalTokens = (response.usage?.input_tokens ?? 0) + (response.usage?.output_tokens ?? 0);
  await consumeBudget(env, user.userId, "claude", totalTokens);

  // 監査ログはRAG系と同じaudit_logテーブルを流用する（専用テーブルは追加しない）。
  // query_hashはクエリ本文の代わりにmessages全体のハッシュにしている（既存RAGAuditLoggerの
  // 「本文を残さない」方針を踏襲）。
  const queryHash = await sha256Hex(JSON.stringify(body.messages));
  await env.DB.prepare(
    "INSERT INTO audit_log (user_id, namespace_id, query_hash, difficulty, result_count, latency_ms, tokens_used, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
  )
    .bind(user.userId, "claude:proxy", queryHash, null, 0, latencyMs, totalTokens, Math.floor(Date.now() / 1000))
    .run();

  return jsonResponse(200, response);
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
