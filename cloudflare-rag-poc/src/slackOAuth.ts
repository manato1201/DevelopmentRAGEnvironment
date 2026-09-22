import type { Env } from "./types";
import { oauthResultPage, jsonResponse } from "./http";
import {
  authenticateFromQueryKey,
  createPendingState,
  consumePendingState,
  getConnection,
  saveConnection,
  clearConnection,
  oauthRedirectUri,
} from "./oauthConnections";
import { requireKnowledgeEditor } from "./auth";

// Slack OAuth v2、公式の「ワークスペースに追加」フローの実装（2026-09-22追加）。
// incoming-webhookスコープで認可すると、Slack側がoauth.v2.accessの応答に
// 完成済みのWebhook URL（incoming_webhook.url）をそのまま返してくれるため、
// リフレッシュトークンの管理が一切不要（Webhook URL自体は失効しない）。
// 4つのOAuth連携の中で最も単純。
//
// 事前準備（技術者が一度だけ）: https://api.slack.com/apps でアプリを作成し、
// 「OAuth & Permissions」でリダイレクトURL（handleSlackOAuthStartがリダイレクトする先）を
// 登録、Bot Token Scopesに incoming-webhook を追加する。得られたClient ID/Secretを
// SLACK_OAUTH_CLIENT_ID/SLACK_OAUTH_CLIENT_SECRETとしてsecret登録する。
const SLACK_OAUTH_SCOPE = "incoming-webhook";
const SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize";
const SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access";

export async function handleSlackOAuthStart(req: Request, env: Env): Promise<Response> {
  if (!env.SLACK_OAUTH_CLIENT_ID) {
    return oauthResultPage(false, "Slack OAuthアプリが未設定です（SLACK_OAUTH_CLIENT_IDをsecretで設定してください）");
  }
  const user = await authenticateFromQueryKey(req, env);
  if (!user) return oauthResultPage(false, "認証に失敗しました。管理画面からやり直してください。");
  try {
    requireKnowledgeEditor(user);
  } catch {
    return oauthResultPage(false, "この操作にはナレッジ登録権限が必要です。");
  }

  const state = await createPendingState(env, "slack", {});
  const url = new URL(SLACK_AUTHORIZE_URL);
  url.searchParams.set("client_id", env.SLACK_OAUTH_CLIENT_ID);
  url.searchParams.set("scope", SLACK_OAUTH_SCOPE);
  url.searchParams.set("redirect_uri", oauthRedirectUri(req, "slack"));
  url.searchParams.set("state", state);
  return Response.redirect(url.toString(), 302);
}

export async function handleSlackOAuthCallback(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const errorParam = url.searchParams.get("error");
  if (errorParam) return oauthResultPage(false, `Slack側で認可が拒否またはキャンセルされました（${errorParam}）。`);
  if (!code || !state) return oauthResultPage(false, "パラメータが不足しています（code/state）。");
  const pending = await consumePendingState(env, "slack", state);
  if (pending === null) {
    return oauthResultPage(false, "認可フローの有効期限が切れたか、不正なリクエストです。管理画面からやり直してください。");
  }
  if (!env.SLACK_OAUTH_CLIENT_ID || !env.SLACK_OAUTH_CLIENT_SECRET) {
    return oauthResultPage(false, "Slack OAuthアプリが未設定です。");
  }

  try {
    const tokenRes = await fetch(SLACK_TOKEN_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: env.SLACK_OAUTH_CLIENT_ID,
        client_secret: env.SLACK_OAUTH_CLIENT_SECRET,
        code,
        redirect_uri: oauthRedirectUri(req, "slack"),
      }),
    });
    const data = (await tokenRes.json()) as {
      ok: boolean;
      error?: string;
      team?: { id: string; name: string };
      incoming_webhook?: { url: string; channel: string };
    };
    if (!tokenRes.ok || !data.ok || !data.incoming_webhook) {
      return oauthResultPage(false, `トークン取得に失敗しました: ${data.error ?? tokenRes.status}`);
    }

    await saveConnection(env, "slack", {
      accessToken: null, // incoming-webhook運用ではbotトークン自体は使わない。webhook URLをextraに保存する
      extra: {
        webhookUrl: data.incoming_webhook.url,
        channel: data.incoming_webhook.channel,
        teamName: data.team?.name ?? "",
      },
    });
    return oauthResultPage(true, `Slack（${data.team?.name ?? ""} / #${data.incoming_webhook.channel}）と接続しました。`);
  } catch (err) {
    return oauthResultPage(false, `接続中にエラーが発生しました: ${err instanceof Error ? err.message : String(err)}`);
  }
}

export async function handleSlackOAuthDisconnect(req: Request, env: Env, user: import("./types").AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  await clearConnection(env, "slack");
  return jsonResponse(200, { status: "ok" });
}

export async function handleSlackOAuthStatus(req: Request, env: Env): Promise<Response> {
  const conn = await getConnection(env, "slack");
  if (!conn) return jsonResponse(200, { connected: false });
  const teamName = conn.extra.teamName as string | undefined;
  const channel = conn.extra.channel as string | undefined;
  return jsonResponse(200, {
    connected: true,
    label: [teamName, channel ? `#${channel}` : ""].filter(Boolean).join(" / ") || "Slack",
    connectedAt: conn.connectedAt,
  });
}

// alerts.tsが実際にSlackへ送る前に呼ぶ。OAuth接続（管理画面の「接続する」ボタン）が
// あればそのWebhook URLを、無ければnullを返して従来のSLACK_WEBHOOK_URL secretへ
// フォールバックさせる。
export async function resolveSlackWebhookUrl(env: Env): Promise<string | null> {
  const conn = await getConnection(env, "slack");
  return (conn?.extra.webhookUrl as string | undefined) ?? null;
}
