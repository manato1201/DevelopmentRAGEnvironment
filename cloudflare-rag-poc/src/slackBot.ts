import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { ForbiddenError, loadAuthedUser } from "./auth";
import { answerQuestion, type AnswerResult } from "./query";

// Slackから質問する（2026-10-16追加、migrations/0028）。スラッシュコマンド「/rag」を受ける。
//   /rag 質問文          … 質問する（答えは、聞いた本人にだけ見える。チャンネルには流れない）
//   /rag link <コード>   … ウェブ画面で発行した連携コードで、Slackのユーザーとこのシステムのユーザーをひもづける
//   /rag unlink          … 紐づけを解除する
//   /rag help            … 使い方
// 安全のため:
//   ・リクエストの署名（X-Slack-Signature）と時刻を必ず確認する。署名用のsecret（SLACK_SIGNING_SECRET）が
//     未設定なら、すべて拒否する。
//   ・紐づけできるSlackワークスペースは SLACK_TEAM_IDS（カンマ区切り）に入っているものだけ（未設定なら紐づけ不可）。
//   ・質問は、紐づいたユーザーの権限（アクセスできるnamespace・トークン予算・レート制限）で動く。
//   ・連携コードは10分・1回限り。APIキーをSlackに貼る必要は無い。
const SIGNATURE_TOLERANCE_SEC = 300;
const LINK_CODE_TTL_SEC = 600;
const SLACK_TEXT_MAX = 2800; // 1つのテキストブロックの上限（3000文字）に余裕を持たせる

function toHex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// 定数時間で比べる（署名の先頭から何文字合うかを、処理時間から推測されないように）。
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function verifySlackSignature(
  secret: string,
  timestamp: string | null,
  signature: string | null,
  rawBody: string,
  nowSec = Math.floor(Date.now() / 1000),
): Promise<boolean> {
  if (!secret || !timestamp || !signature) return false;
  const ts = Number(timestamp);
  if (!Number.isFinite(ts) || Math.abs(nowSec - ts) > SIGNATURE_TOLERANCE_SEC) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`v0:${timestamp}:${rawBody}`));
  return safeEqual(`v0=${toHex(mac)}`, signature);
}

function ephemeral(text: string): Response {
  return jsonResponse(200, { response_type: "ephemeral", text });
}

export function allowedTeams(env: Env): string[] {
  return (env.SLACK_TEAM_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);
}

function randomCode(): string {
  // 読み間違えにくい文字だけ（0/O/1/Iを除く）で8文字
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return [...bytes].map((b) => alphabet[b % alphabet.length]).join("");
}

function escapeSlack(text: string): string {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// モデルの回答（Markdown）を、Slackのmrkdwnに直す。コード（``` と `）の中はそのまま。
//   **太字** → *太字*　／　# 見出し → *見出し*　／　- 項目・* 項目 → • 項目　／　[文字](URL) → <URL|文字>
//   & < > はSlackの記法と紛れないように、エスケープする（回答に <@U…> や <!channel> が混ざっても、メンションにならない）。
export function toSlackMrkdwn(markdown: string): string {
  return String(markdown)
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, i) => {
      if (i % 2 === 1) return part; // コード
      return part
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/^(\s*)[-*]\s+/gm, "$1• ")
        .replace(/^#{1,6}\s+(.+)$/gm, "*$1*")
        .replace(/\*\*([^*\n]+)\*\*/g, "*$1*")
        .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, "<$2|$1>");
    })
    .join("");
}

// Slackのmrkdwnに載せる出典つきの文面にする。
export function formatSlackAnswer(answer: string, sources: Array<{ file: string; namespace: string; cited?: boolean }>): string {
  const lines = sources.slice(0, 8).map((s, i) => `${s.cited ? "•" : "◦"} [${i + 1}] ${escapeSlack(s.file)}（${escapeSlack(s.namespace)}）`);
  const body = `${toSlackMrkdwn(answer)}${lines.length > 0 ? `\n\n*出典*\n${lines.join("\n")}` : ""}\n\n_AIが生成した回答です。出典を確認してください。_`;
  return body.length > SLACK_TEXT_MAX ? body.slice(0, SLACK_TEXT_MAX - 1) + "…" : body;
}

// 質問に答える。Cloudflare側の一時的なデータベースの不調（D1_ERROR）のときだけ、1回やり直す。
export async function answerWithRetry(
  env: Env,
  user: AuthedUser,
  body: Parameters<typeof answerQuestion>[2],
  answer: (env: Env, user: AuthedUser, body: Parameters<typeof answerQuestion>[2]) => Promise<AnswerResult> = answerQuestion,
): Promise<AnswerResult> {
  let result = await answer(env, user, body);
  if (!result.ok && result.error.includes("D1_ERROR")) {
    await new Promise((resolve) => setTimeout(resolve, 600));
    result = await answer(env, user, body);
  }
  return result;
}

async function postToResponseUrl(responseUrl: string, text: string): Promise<void> {
  // response_urlはSlackが発行したURLだけに送る（任意のURLへ送らせない）
  try {
    const url = new URL(responseUrl);
    if (url.protocol !== "https:" || !(url.hostname === "hooks.slack.com" || url.hostname.endsWith(".slack.com"))) return;
  } catch {
    return;
  }
  await fetch(responseUrl, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ response_type: "ephemeral", replace_original: true, text }),
  }).catch(() => undefined);
}

// POST /slack/command — 認証（APIキー）ではなく、Slackの署名で確認する。index.tsで、authenticate()より前に呼ぶ。
export async function handleSlackCommand(req: Request, env: Env, ctx?: ExecutionContext): Promise<Response> {
  const raw = await req.text();
  if (!env.SLACK_SIGNING_SECRET) return jsonResponse(503, { error: "Slackからの質問は未設定です（SLACK_SIGNING_SECRET）" });
  const ok = await verifySlackSignature(env.SLACK_SIGNING_SECRET, req.headers.get("x-slack-request-timestamp"), req.headers.get("x-slack-signature"), raw);
  if (!ok) return jsonResponse(401, { error: "署名を確認できませんでした" });

  const form = new URLSearchParams(raw);
  const teamId = form.get("team_id") || "";
  const slackUser = form.get("user_id") || "";
  const text = (form.get("text") || "").trim();
  const responseUrl = form.get("response_url") || "";
  if (!teamId || !slackUser) return ephemeral("リクエストが不正です。");
  if (!allowedTeams(env).includes(teamId)) return ephemeral("このSlackワークスペースは、まだ利用が許可されていません。管理者に連絡してください。");

  const [first, ...rest] = text.split(/\s+/);
  const command = (first || "").toLowerCase();

  if (!text || command === "help") {
    return ephemeral(
      "*RAGに質問する*\n• `/rag 質問文` … 質問する（答えはあなたにだけ表示されます）\n• `/rag link <コード>` … ウェブ画面の「自分用の連携」→「Slackから質問する」で発行したコードで、あなたのアカウントとひもづけます\n• `/rag unlink` … ひもづけを解除します",
    );
  }

  if (command === "link") {
    const code = (rest[0] || "").toUpperCase();
    if (!code) return ephemeral("連携コードを入力してください。例: `/rag link ABCD2345`");
    const row = await env.DB.prepare("SELECT user_id, expires_at FROM slack_link_codes WHERE code = ?").bind(code).first<{ user_id: string; expires_at: number }>();
    // コードは1回限り。見つかったら（期限切れでも）消す。
    if (row) await env.DB.prepare("DELETE FROM slack_link_codes WHERE code = ?").bind(code).run();
    if (!row || row.expires_at < Math.floor(Date.now() / 1000)) return ephemeral("連携コードが無効か、期限が切れています。ウェブ画面で発行し直してください。");
    const user = await loadAuthedUser(env, row.user_id);
    if (!user || user.role === "guest") return ephemeral("このアカウントは、Slackと連携できません。");
    await env.DB.prepare(
      `INSERT INTO slack_bindings (team_id, slack_user_id, user_id, created_at) VALUES (?, ?, ?, ?)
       ON CONFLICT(team_id, slack_user_id) DO UPDATE SET user_id = excluded.user_id, created_at = excluded.created_at`,
    )
      .bind(teamId, slackUser, row.user_id, Math.floor(Date.now() / 1000))
      .run();
    return ephemeral("連携しました。これからは `/rag 質問文` で質問できます（あなたの権限で検索します）。");
  }

  if (command === "unlink") {
    await env.DB.prepare("DELETE FROM slack_bindings WHERE team_id = ? AND slack_user_id = ?").bind(teamId, slackUser).run();
    return ephemeral("連携を解除しました。");
  }

  const binding = await env.DB.prepare("SELECT user_id FROM slack_bindings WHERE team_id = ? AND slack_user_id = ?").bind(teamId, slackUser).first<{ user_id: string }>();
  if (!binding) return ephemeral("まだ連携されていません。ウェブ画面の「自分用の連携」→「Slackから質問する」で連携コードを発行し、`/rag link <コード>` を実行してください。");
  const user = await loadAuthedUser(env, binding.user_id);
  if (!user || user.role === "guest") return ephemeral("このアカウントでは質問できません。連携をやり直してください。");

  // Slackは3秒以内の応答を求める。まず受け付けたことを返し、答えはresponse_urlへ後から送る。
  const work = (async () => {
    let reply: string;
    try {
      const result = await answerWithRetry(env, user, { query: text, limit: 5 });
      reply = result.ok ? formatSlackAnswer(result.answer, result.sources) : `質問できませんでした: ${result.error}`;
    } catch (err) {
      reply = `質問できませんでした: ${err instanceof Error ? err.message : String(err)}`;
    }
    await postToResponseUrl(responseUrl, reply);
  })();
  if (ctx) ctx.waitUntil(work);
  else await work;
  return ephemeral("調べています…（答えはこの後、あなたにだけ表示されます）");
}

// ---- ウェブ画面側（APIキーで認証）----

function requireMember(user: AuthedUser): void {
  if (user.role === "guest") throw new ForbiddenError("ゲストはSlack連携を使えません");
}

// POST /me/slack/link-code — 連携コードを発行する（10分・1回限り。発行のたびに自分の古いコードは消す）。
export async function handleSlackLinkCode(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  if (!env.SLACK_SIGNING_SECRET || allowedTeams(env).length === 0) {
    return jsonResponse(400, { error: "Slackからの質問は、まだ設定されていません（管理者が SLACK_SIGNING_SECRET と SLACK_TEAM_IDS を設定します）" });
  }
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare("DELETE FROM slack_link_codes WHERE user_id = ? OR expires_at < ?").bind(user.userId, now).run();
  const code = randomCode();
  await env.DB.prepare("INSERT INTO slack_link_codes (code, user_id, expires_at) VALUES (?, ?, ?)").bind(code, user.userId, now + LINK_CODE_TTL_SEC).run();
  return jsonResponse(200, { status: "ok", code, expiresInSec: LINK_CODE_TTL_SEC });
}

// POST /me/slack/status — 設定済みか、いくつのSlackユーザーとひもづいているか
export async function handleSlackStatus(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  const rows = await env.DB.prepare("SELECT COUNT(*) AS c FROM slack_bindings WHERE user_id = ?").bind(user.userId).first<{ c: number }>();
  return jsonResponse(200, {
    status: "ok",
    configured: !!env.SLACK_SIGNING_SECRET && allowedTeams(env).length > 0,
    linked: rows?.c ?? 0,
    chatConfigured: !!env.SLACK_BOT_TOKEN, // メンション・DMで答える設定（SLACK_BOT_TOKEN）があるか
  });
}

// POST /me/slack/unlink — 自分のアカウントにひもづいたSlackユーザーをすべて外す
export async function handleSlackUnlink(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  await env.DB.prepare("DELETE FROM slack_bindings WHERE user_id = ?").bind(user.userId).run();
  return jsonResponse(200, { status: "ok" });
}
