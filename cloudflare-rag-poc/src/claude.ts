import Anthropic from "@anthropic-ai/sdk";
import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { assertNotRateLimited } from "./rateLimit";
import { BudgetExceededError, reserveBudget, reconcileBudget } from "./budget";
import { sha256Hex } from "./embeddings";
import { startAuditLog, finalizeAuditLog } from "./auditLog";

const DEFAULT_MODEL = "claude-sonnet-5";
const DEFAULT_MAX_TOKENS = 4096;

// 入力トークンの見積もり。messages全体の文字数/3（日本語混在を踏まえ安全側に厚め）が基本だが、
// 画像ブロックのbase64文字列（1枚で数十万文字）をそのまま数えると、1枚で数万トークンの
// 過大見積もりになり、予算が残っていても予約（reserveBudget）が通らなくなる。画像は
// 縮小済みでも1枚あたり約1,600トークンで課金されるため、base64本体は文字数に数えず、
// 1枚あたり固定値を加算する（実測との差分はreconcileBudgetで清算される）。
// 参考画像付きのチュートリアル生成（2026-10-05追加）と、finish_tutorial直後の
// ビューポート自己確認画像の両方が対象。
export const IMAGE_TOKEN_ESTIMATE = 1600;
export function estimateInputTokens(messages: unknown): number {
  let images = 0;
  const json = JSON.stringify(messages, (key, value) => {
    if (key === "data" && typeof value === "string" && value.length > 1000) {
      images += 1;
      return "";
    }
    return value;
  });
  return Math.ceil(json.length / 3) + images * IMAGE_TOKEN_ESTIMATE;
}

// output_config は effort（思考の深さ）だけを通す（2026-10-05追加）。クライアントから来た
// 任意のoutput_config（structured outputのformat等）をそのまま中継すると、このプロキシの
// 用途（Houdiniチュートリアル生成のツール実行ループ）を超えて使えてしまうため、
// 許可する値を絞って検証する。不正な値は黙って捨てて既定のeffortで動かす（400にはしない：
// effortは品質・コストの調整用で、無くても動くため）。
const ALLOWED_EFFORTS = ["low", "medium", "high", "xhigh", "max"] as const;
export type Effort = (typeof ALLOWED_EFFORTS)[number];
export function sanitizeEffort(outputConfig: unknown): Effort | undefined {
  const effort = (outputConfig as { effort?: unknown } | null | undefined)?.effort;
  return typeof effort === "string" && (ALLOWED_EFFORTS as readonly string[]).includes(effort)
    ? (effort as Effort)
    : undefined;
}

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
    output_config?: { effort?: string };
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
  const inputEstimate = estimateInputTokens(body.messages);
  const estimate = maxTokens + inputEstimate;
  const reserved = await reserveBudget(env, user.userId, "claude", estimate);
  if (!reserved) throw new BudgetExceededError("claude");

  const effort = sanitizeEffort(body.output_config);
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
      ...(effort ? { output_config: { effort } } : {}),
    });
  } catch (err) {
    await reconcileBudget(env, user.userId, "claude", estimate, 0);
    if (err instanceof Anthropic.APIError) {
      return jsonResponse(err.status ?? 500, { error: err.message });
    }
    return jsonResponse(500, { error: err instanceof Error ? err.message : String(err) });
  }

  const latencyMs = Date.now() - start;
  const inputTokens = response.usage?.input_tokens ?? 0;
  const outputTokens = response.usage?.output_tokens ?? 0;
  const totalTokens = inputTokens + outputTokens;
  await reconcileBudget(env, user.userId, "claude", estimate, totalTokens);
  await finalizeAuditLog(env, auditId, {
    resultCount: 0,
    latencyMs,
    tokensUsed: totalTokens,
    inputTokens,
    outputTokens,
    model: body.model || DEFAULT_MODEL,
  });

  return jsonResponse(200, response);
}
