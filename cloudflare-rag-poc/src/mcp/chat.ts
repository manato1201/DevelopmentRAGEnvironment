// RAGチャットからMCPツールを使う（2026-10-08追加）。Geminiの関数呼び出しで、
// 検索結果だけで答えきれないときに、接続済みの公式MCPサーバー（Notion・Atlassian等）の
// 読み取り専用ツールを呼べるようにする。別プロジェクトではブラウザ側のライブチャットがツールを
// 登録して実行するが、このWorkerのチャットは /query がサーバー側で回答を作る方式なので、
// ツール呼び出しのループもサーバー側（ここ）に置く。
//
// 安全のため:
//   - 使えるのは「チャットで使う」がオンのサービスの、有効化されたツール。読み取り専用ツールは、そのまま実行する。
//   - 書き込みツール（作成・更新・削除・送信）は、本人専用の接続で、明示的に有効にしたものだけをモデルに見せる
//     （service.ts の chatTools）。モデルが呼んでも、ここでは実行しない。「確認待ち」を1件作って画面に返し、
//     利用者が「実行」を押したとき（/mcp/confirm）に、はじめて実行する（2026-10-22。approval.ts）。
//   - ツール呼び出しは最大 MAX_ROUNDS 往復・合計 MAX_CALLS 回まで。
//   - ツールの結果は信頼できない入力（外部サービスの文章）なので、指示としては扱わない旨を
//     プロンプトで伝える。

import type { Env } from "../types";
import { createApproval } from "./approval";
import { hasProperties, toGeminiSchema } from "./schema";
import { callTool, chatTools, type ChatTool } from "./service";

type FetchLike = typeof fetch;

export const MAX_ROUNDS = 4;
export const MAX_CALLS = 6;
export const MAX_PENDING = 3; // 1回の回答で、確認待ちにできる書き込みの上限
const RESULT_CHARS_FOR_MODEL = 6000;

export interface McpToolCallLog {
  providerId: string;
  providerLabel: string;
  tool: string;
  ok: boolean;
  error?: string;
}

// 利用者の確認を待っている書き込み（画面に「実行」「やめる」を出す）。引数は確認画面に出す分で、
// 実行されるのは、サーバーに保存した値（approval.ts）。
export interface McpPendingAction {
  approvalId: string;
  providerId: string;
  providerLabel: string;
  tool: string;
  arguments: Record<string, unknown>;
  expiresAt: number;
}

export interface McpAnswerResult {
  text: string;
  promptTokens: number;
  candidateTokens: number;
  toolCalls: McpToolCallLog[];
  pendingActions: McpPendingAction[];
}

// Geminiの関数名は [A-Za-z_][A-Za-z0-9_]* で64文字まで。
export function geminiToolName(providerId: string, toolName: string, taken: Set<string>): string {
  const base = `mcp_${providerId}_${toolName}`.replace(/[^A-Za-z0-9_]/g, "_").slice(0, 60);
  let name = base;
  for (let index = 2; taken.has(name); index++) name = `${base.slice(0, 56)}_${index}`;
  taken.add(name);
  return name;
}

interface GeminiPart {
  text?: string;
  thought?: boolean;
  functionCall?: { name: string; args?: Record<string, unknown> };
  inlineData?: { mimeType: string; data: string };
  [key: string]: unknown;
}

interface GeminiContent {
  role?: string;
  parts?: GeminiPart[];
}

export async function answerWithMcpTools(
  env: Env,
  userId: string,
  prompt: string,
  image?: { mimeType: string; data: string },
  fetchImpl: FetchLike = fetch,
): Promise<McpAnswerResult | null> {
  const available = await chatTools(env, fetchImpl, userId);
  if (available.length === 0) return null;

  const taken = new Set<string>();
  const byName = new Map<string, ChatTool>();
  const declarations = available.map((entry) => {
    const name = geminiToolName(entry.providerId, entry.tool.name, taken);
    byName.set(name, entry);
    const note = entry.tool.readOnly ? "" : "（書き込み。呼ぶと利用者の確認画面が出る。確認されるまで実行されない）";
    const description = `[${entry.providerLabel}]${note} ${entry.tool.description}`.slice(0, 900);
    return {
      name,
      description,
      parameters: toGeminiSchema(entry.tool.inputSchema),
    };
  });

  const model = env.GENERATION_MODEL || "gemini-flash-latest";
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${env.GEMINI_API_KEY}`;
  const firstParts: GeminiPart[] = [{ text: prompt }];
  if (image) firstParts.push({ inlineData: { mimeType: image.mimeType, data: image.data } });
  const contents: GeminiContent[] = [{ role: "user", parts: firstParts }];

  let promptTokens = 0;
  let candidateTokens = 0;
  let callsMade = 0;
  const toolCalls: McpToolCallLog[] = [];
  const pendingActions: McpPendingAction[] = [];

  for (let round = 0; round <= MAX_ROUNDS; round++) {
    // 最後の往復ではツールを渡さず、ここまでの情報で最終回答を書かせる。
    const withTools = round < MAX_ROUNDS;
    const response = await fetchImpl(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        contents,
        ...(withTools ? { tools: [{ functionDeclarations: declarations }] } : {}),
      }),
    });
    if (!response.ok) {
      throw new Error(`Gemini generateContent APIエラー (${response.status}): ${await response.text()}`);
    }
    const data = (await response.json()) as {
      candidates?: Array<{ content?: GeminiContent }>;
      usageMetadata?: { promptTokenCount?: number; candidatesTokenCount?: number };
    };
    promptTokens += data.usageMetadata?.promptTokenCount ?? 0;
    candidateTokens += data.usageMetadata?.candidatesTokenCount ?? 0;

    const content = data.candidates?.[0]?.content;
    const parts = content?.parts ?? [];
    const calls = parts.filter((part) => part.functionCall);
    if (calls.length === 0 || !withTools) {
      const text = parts
        .filter((part) => typeof part.text === "string" && !part.thought)
        .map((part) => part.text as string)
        .join("");
      return { text: text || "回答を生成できませんでした。", promptTokens, candidateTokens, toolCalls, pendingActions };
    }

    // モデルの返した内容は（思考の署名などを含めて）そのまま履歴に戻す。
    contents.push({ role: "model", parts });
    const responses: GeminiPart[] = [];
    for (const call of calls) {
      const functionCall = call.functionCall!;
      const entry = byName.get(functionCall.name);
      let output: Record<string, unknown>;
      if (!entry) {
        output = { error: `不明なツールです: ${functionCall.name}` };
      } else if (callsMade >= MAX_CALLS) {
        output = { error: "ツールの呼び出し回数の上限に達しました。ここまでの情報で答えてください。" };
      } else if (!entry.tool.readOnly) {
        // 書き込み: 実行しない。確認待ちを作って、モデルには「まだ実行していない」と伝える。
        if (pendingActions.length >= MAX_PENDING) {
          output = { error: "一度に確認できる書き込みの上限に達しました。残りは、確認が終わってから、もう一度依頼してください。" };
        } else {
          const args = hasProperties(entry.tool.inputSchema) ? (functionCall.args ?? {}) : {};
          const approval = await createApproval(env, {
            userId,
            ownerId: entry.ownerId,
            providerId: entry.providerId,
            tool: entry.tool.name,
            arguments: args,
          });
          pendingActions.push({
            approvalId: approval.id,
            providerId: entry.providerId,
            providerLabel: entry.providerLabel,
            tool: entry.tool.name,
            arguments: args,
            expiresAt: approval.expiresAt,
          });
          output = {
            status: "pending_user_confirmation",
            message:
              "まだ実行していません。利用者の画面に確認ボタンが出ています。実行したとは書かず、" +
              "「確認画面で内容を確かめて『実行』を押してください」と案内してください。",
          };
        }
      } else {
        callsMade += 1;
        const log: McpToolCallLog = { providerId: entry.providerId, providerLabel: entry.providerLabel, tool: entry.tool.name, ok: true };
        try {
          const args = hasProperties(entry.tool.inputSchema) ? (functionCall.args ?? {}) : {};
          const result = await callTool(env, userId, entry.providerId, entry.tool.name, args, { readOnlyOnly: true, ownerId: entry.ownerId }, fetchImpl);
          if (result.isError) {
            log.ok = false;
            log.error = result.text.slice(0, 200);
            output = { error: result.text.slice(0, RESULT_CHARS_FOR_MODEL) || "ツールがエラーを返しました" };
          } else {
            output = { result: result.text.slice(0, RESULT_CHARS_FOR_MODEL) };
          }
        } catch (err) {
          log.ok = false;
          log.error = (err instanceof Error ? err.message : String(err)).slice(0, 200);
          output = { error: log.error };
        }
        toolCalls.push(log);
      }
      responses.push({ functionResponse: { name: functionCall.name, response: output } });
    }
    contents.push({ role: "user", parts: responses });
  }
  // 到達しない（最後の往復は必ずreturnする）が、型のために置く。
  return { text: "回答を生成できませんでした。", promptTokens, candidateTokens, toolCalls, pendingActions };
}
