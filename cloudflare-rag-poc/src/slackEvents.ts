import type { Env } from "./types";
import { jsonResponse } from "./http";
import { loadAuthedUser } from "./auth";
import { answerQuestion, type AnswerResult } from "./query";
import { allowedTeams, answerWithRetry, formatSlackAnswer, verifySlackSignature } from "./slackBot";

// Slackのチャットで答える（2026-10-25追加）。ボットへのメンション（@bot 質問）と、ボットとのDMを受ける。
//   POST /slack/events（Slackの Event Subscriptions の Request URL）
// 安全のため:
//   ・署名（X-Slack-Signature）と時刻を必ず確認する（スラッシュコマンドと同じ。SLACK_SIGNING_SECRET が無ければ拒否）。
//   ・許可したワークスペース（SLACK_TEAM_IDS）だけ。質問は、ひもづいた本人の権限で動く（/rag link で連携する）。
//   ・外部サービス（MCP）は、DMだけで使う。チャンネルの返信は、その場の全員に見えるため、
//     Gmailや非公開チャンネルの内容が流れないように、チャンネルでは社内の検索（RAG）だけで答える。
//   ・書き込み（MCP）は、ここでは実行しない。確認が必要な操作は、ウェブ画面で確認する。
//   ・ボット自身の発言・他のボットの発言には答えない（返信が返信を呼ぶのを防ぐ）。Slackの再送は無視する。
//   ・ボットのトークン（SLACK_BOT_TOKEN）は、ログにも応答にも出さない。
const HISTORY_MAX_MESSAGES = 6;
const HISTORY_MAX_CHARS = 1500;
const PLACEHOLDER = "調べています…";

export interface SlackEventPayload {
  type?: string;
  challenge?: string;
  team_id?: string;
  authorizations?: Array<{ user_id?: string }>;
  event?: {
    type?: string;
    subtype?: string;
    channel?: string;
    channel_type?: string;
    user?: string;
    bot_id?: string;
    text?: string;
    ts?: string;
    thread_ts?: string;
    team?: string;
  };
}

export interface SlackIncoming {
  channel: string;
  ts: string;
  threadTs?: string; // 質問が属するスレッド（なければ undefined）
  replyThreadTs?: string; // 返信を置くスレッド（チャンネルでは、質問のスレッド。DMでは、スレッドで聞かれたときだけ）
  slackUser: string;
  teamId: string;
  text: string; // メンションを除いた質問文
  isDm: boolean;
}

// 「<@U0123ABCD> こんにちは」や「<@U0123|name>」のメンションを取り除く。
export function stripMentions(text: string): string {
  return String(text || "").replace(/<@[A-Z0-9]+(?:\|[^>]*)?>/g, "").replace(/\s+/g, " ").trim();
}

// 答える対象のイベントか。対象なら、必要な項目を取り出して返す。対象外（ボットの発言・編集・他の種類）は null。
export function classifyEvent(payload: SlackEventPayload): SlackIncoming | null {
  const event = payload.event;
  if (!event || payload.type !== "event_callback") return null;
  const isMention = event.type === "app_mention";
  const isDm = event.type === "message" && event.channel_type === "im";
  if (!isMention && !isDm) return null;
  if (event.bot_id || event.subtype) return null; // ボットの発言・編集・削除・参加の通知など
  const botUser = payload.authorizations?.[0]?.user_id;
  if (!event.user || (botUser && event.user === botUser)) return null;
  if (!event.channel || !event.ts || typeof event.text !== "string") return null;
  const teamId = payload.team_id || event.team || "";
  if (!teamId) return null;
  return {
    channel: event.channel,
    ts: event.ts,
    threadTs: event.thread_ts,
    replyThreadTs: isDm ? event.thread_ts : event.thread_ts || event.ts,
    slackUser: event.user,
    teamId,
    text: stripMentions(event.text),
    isDm,
  };
}

interface SlackMessage {
  type?: string;
  subtype?: string;
  user?: string;
  bot_id?: string;
  text?: string;
  ts?: string;
}

// Slackの発言の並びから、会話の履歴（質問と回答の順）を作る。いまの質問は含めない。古い順に、最後の数件だけ。
export function buildSlackHistory(messages: SlackMessage[], currentTs: string, botUserId?: string): Array<{ role: string; content: string }> {
  const out: Array<{ role: string; content: string }> = [];
  for (const m of messages) {
    if (m.type && m.type !== "message") continue;
    if (!m.ts || m.ts === currentTs || typeof m.text !== "string") continue;
    const content = stripMentions(m.text);
    if (!content || content.startsWith(PLACEHOLDER)) continue;
    const isBot = Boolean(m.bot_id) || (botUserId !== undefined && m.user === botUserId);
    out.push({ role: isBot ? "assistant" : "user", content: content.length > HISTORY_MAX_CHARS ? content.slice(0, HISTORY_MAX_CHARS) : content });
  }
  return out.slice(-HISTORY_MAX_MESSAGES);
}

export interface SlackEventDeps {
  fetchImpl?: typeof fetch;
  answer?: (env: Env, user: Parameters<typeof answerQuestion>[1], body: Parameters<typeof answerQuestion>[2]) => Promise<AnswerResult>;
}

async function slackApi(env: Env, method: string, body: Record<string, unknown>, fetchImpl: typeof fetch): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetchImpl(`https://slack.com/api/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json; charset=utf-8", authorization: `Bearer ${env.SLACK_BOT_TOKEN}` },
      body: JSON.stringify(body),
    });
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function fetchHistory(env: Env, incoming: SlackIncoming, botUserId: string | undefined, fetchImpl: typeof fetch) {
  // スレッドなら、そのスレッドの発言。DMでスレッドでなければ、直近の発言。チャンネルの新しいスレッドは、履歴なし。
  let result: Record<string, unknown> | null = null;
  let newestFirst = false;
  if (incoming.threadTs) {
    result = await slackApi(env, "conversations.replies", { channel: incoming.channel, ts: incoming.threadTs, limit: 12 }, fetchImpl);
  } else if (incoming.isDm) {
    result = await slackApi(env, "conversations.history", { channel: incoming.channel, limit: 10 }, fetchImpl);
    newestFirst = true;
  }
  // 権限（スコープ）が足りないなどで取れないときは、履歴なしで答える。
  if (!result || result.ok !== true || !Array.isArray(result.messages)) return [];
  const messages = (result.messages as SlackMessage[]).slice();
  if (newestFirst) messages.reverse();
  return buildSlackHistory(messages, incoming.ts, botUserId);
}

async function reply(env: Env, incoming: SlackIncoming, text: string, fetchImpl: typeof fetch, updateTs?: string) {
  if (updateTs) {
    const updated = await slackApi(env, "chat.update", { channel: incoming.channel, ts: updateTs, text }, fetchImpl);
    if (updated?.ok === true) return;
  }
  await slackApi(env, "chat.postMessage", { channel: incoming.channel, text, ...(incoming.replyThreadTs ? { thread_ts: incoming.replyThreadTs } : {}) }, fetchImpl);
}

async function respond(env: Env, incoming: SlackIncoming, botUserId: string | undefined, deps: SlackEventDeps): Promise<void> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const answer = deps.answer ?? answerQuestion;
  if (!allowedTeams(env).includes(incoming.teamId)) {
    await reply(env, incoming, "このSlackワークスペースは、まだ利用が許可されていません。管理者に連絡してください。", fetchImpl);
    return;
  }
  const binding = await env.DB.prepare("SELECT user_id FROM slack_bindings WHERE team_id = ? AND slack_user_id = ?").bind(incoming.teamId, incoming.slackUser).first<{ user_id: string }>();
  if (!binding) {
    await reply(env, incoming, "まだ連携されていません。ウェブ画面の「自分用の連携」→「Slackから質問する」で連携コードを発行し、`/rag link <コード>` を実行してください。", fetchImpl);
    return;
  }
  const user = await loadAuthedUser(env, binding.user_id);
  if (!user || user.role === "guest") {
    await reply(env, incoming, "このアカウントでは質問できません。連携をやり直してください。", fetchImpl);
    return;
  }
  if (!incoming.text) {
    await reply(env, incoming, "質問を書いてください。例: `@ボット houdini の動画生成について教えて`（DMでは、そのまま質問を送れます）", fetchImpl);
    return;
  }

  // すぐに「調べています…」を出し、答えができたらその発言を書き換える（Slackは3秒以内の受け付けを求める）。
  const placeholder = await slackApi(env, "chat.postMessage", { channel: incoming.channel, text: PLACEHOLDER, ...(incoming.replyThreadTs ? { thread_ts: incoming.replyThreadTs } : {}) }, fetchImpl);
  const placeholderTs = placeholder?.ok === true && typeof placeholder.ts === "string" ? placeholder.ts : undefined;

  let text: string;
  try {
    const history = await fetchHistory(env, incoming, botUserId, fetchImpl);
    const result = await answerWithRetry(env, user, { query: incoming.text, limit: 5, history, useMcp: incoming.isDm }, answer);
    if (!result.ok) {
      text = `質問できませんでした: ${result.error}`;
    } else {
      let body = result.answer;
      const used = [...new Set((result.toolCalls ?? []).filter((c) => c.ok).map((c) => c.providerLabel))];
      if (used.length > 0) body += `\n\n_使った外部サービス: ${used.join("、")}_`;
      if ((result.pendingActions ?? []).length > 0) body += "\n\n_確認が必要な操作があります。Slackからは実行できません。ウェブ画面のチャットで確認してください。_";
      text = formatSlackAnswer(body, result.sources);
    }
  } catch (err) {
    text = `質問できませんでした: ${err instanceof Error ? err.message : String(err)}`;
  }
  await reply(env, incoming, text, fetchImpl, placeholderTs);
}

// POST /slack/events — 認証（APIキー）ではなく、Slackの署名で確認する。index.tsで、authenticate()より前に呼ぶ。
export async function handleSlackEvents(req: Request, env: Env, ctx?: ExecutionContext, deps: SlackEventDeps = {}): Promise<Response> {
  const raw = await req.text();
  if (!env.SLACK_SIGNING_SECRET) return jsonResponse(503, { error: "Slackのチャットは未設定です（SLACK_SIGNING_SECRET）" });
  const ok = await verifySlackSignature(env.SLACK_SIGNING_SECRET, req.headers.get("x-slack-request-timestamp"), req.headers.get("x-slack-signature"), raw);
  if (!ok) return jsonResponse(401, { error: "署名を確認できませんでした" });

  let payload: SlackEventPayload;
  try {
    payload = JSON.parse(raw) as SlackEventPayload;
  } catch {
    return jsonResponse(400, { error: "リクエストが不正です" });
  }
  // Event Subscriptions の Request URL を登録するときの確認（署名の確認のあとだけ、答える）
  if (payload.type === "url_verification") return jsonResponse(200, { challenge: String(payload.challenge ?? "") });

  // 3秒以内に応答できないとSlackが再送する。再送は、すでに処理を始めているので無視する。
  if (req.headers.get("x-slack-retry-num")) return jsonResponse(200, { ok: true });
  if (!env.SLACK_BOT_TOKEN) return jsonResponse(200, { ok: true }); // 返信できないので、何もしない

  const incoming = classifyEvent(payload);
  if (!incoming) return jsonResponse(200, { ok: true });

  const work = respond(env, incoming, payload.authorizations?.[0]?.user_id, deps).catch(() => undefined);
  if (ctx) ctx.waitUntil(work);
  else await work;
  return jsonResponse(200, { ok: true });
}
