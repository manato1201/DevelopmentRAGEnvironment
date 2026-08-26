import type { Env } from "./types";
import { getGmailAccessToken } from "./gmailOAuth";

// Slack Incoming Webhook（既存GAS sendHealthAlert_のSlack部分に相当）。
// SLACK_WEBHOOK_URL未設定の場合は何もしない（Slack連携を使わない構成でもエラーにしない）。
export async function sendSlackAlert(env: Env, text: string): Promise<void> {
  if (!env.SLACK_WEBHOOK_URL) return;
  const res = await fetch(env.SLACK_WEBHOOK_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok)
    throw new Error(
      `Slack Webhook送信エラー (${res.status}): ${await res.text()}`,
    );
}

function encodeMimeHeader(text: string): string {
  const base64 = btoa(unescape(encodeURIComponent(text)));
  return `=?UTF-8?B?${base64}?=`;
}

function base64UrlEncodeUtf8(str: string): string {
  const bytes = new TextEncoder().encode(str);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

// Gmail API経由のメール送信（既存GAS sendHealthAlert_のメール部分に相当）。
// 個人のGmailアカウントで一度だけOAuth同意して得たrefresh_tokenを使う方式（src/gmailOAuth.ts）。
// Gmail APIは送信元を認証済みアカウント自身に固定するため、Fromヘッダーの指定は不要（あっても無視される）。
// 必要なシークレット（GMAIL_OAUTH_CLIENT_ID等）・GMAIL_ALERT_TOのいずれか未設定なら何もしない。
export async function sendGmailAlert(
  env: Env,
  subjectLine: string,
  bodyText: string,
): Promise<void> {
  if (!env.GMAIL_OAUTH_REFRESH_TOKEN || !env.GMAIL_ALERT_TO) return;
  const token = await getGmailAccessToken(env);
  const message =
    `To: ${env.GMAIL_ALERT_TO}\r\n` +
    `Subject: ${encodeMimeHeader(subjectLine)}\r\n` +
    `Content-Type: text/plain; charset=UTF-8\r\n\r\n` +
    bodyText;
  const res = await fetch(
    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ raw: base64UrlEncodeUtf8(message) }),
    },
  );
  if (!res.ok)
    throw new Error(`Gmail API送信エラー (${res.status}): ${await res.text()}`);
}
