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

// Backlog（Nulab）OAuth 2.0、公式ドキュメント通りの実装（2026-09-22追加）。
// BacklogのOAuthは「スペースごと」（認可URL自体がスペースのサブドメインを含む）のため、
// 接続を開始する前に管理者にスペースURLを一度だけ入力してもらう必要がある
// （このスペースURL自体はAPIトークンのような秘匿情報ではないため、secretではなく
// 通常の入力欄でよい）。
//
// 事前準備（技術者が一度だけ）: Backlogの「個人設定」→「アプリケーション」→「登録」で
// OAuth2アプリを作成し、コールバックURL（handleBacklogOAuthStartがリダイレクトする先）を
// 登録する。得られたClient ID/SecretをBACKLOG_OAUTH_CLIENT_ID/BACKLOG_OAUTH_CLIENT_SECRET
// としてsecret登録する。
function normalizeSpaceUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const withScheme = /^https?:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const url = new URL(withScheme);
    return `https://${url.host}`;
  } catch {
    return null;
  }
}

export async function handleBacklogOAuthStart(req: Request, env: Env): Promise<Response> {
  if (!env.BACKLOG_OAUTH_CLIENT_ID) {
    return oauthResultPage(false, "Backlog OAuthアプリが未設定です（BACKLOG_OAUTH_CLIENT_IDをsecretで設定してください）");
  }
  const user = await authenticateFromQueryKey(req, env);
  if (!user) return oauthResultPage(false, "認証に失敗しました。管理画面からやり直してください。");
  try {
    requireKnowledgeEditor(user);
  } catch {
    return oauthResultPage(false, "この操作にはナレッジ登録権限が必要です。");
  }

  const spaceUrl = normalizeSpaceUrl(new URL(req.url).searchParams.get("space") || "");
  if (!spaceUrl) {
    return oauthResultPage(false, "Backlogのスペース名・URLを入力してください（例: yourspace.backlog.com）。");
  }

  const state = await createPendingState(env, "backlog", { spaceUrl });
  const url = new URL(`${spaceUrl}/OAuth2AccessRequest.action`);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", env.BACKLOG_OAUTH_CLIENT_ID);
  url.searchParams.set("redirect_uri", oauthRedirectUri(req, "backlog"));
  url.searchParams.set("state", state);
  return Response.redirect(url.toString(), 302);
}

export async function handleBacklogOAuthCallback(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const errorParam = url.searchParams.get("error");
  if (errorParam) return oauthResultPage(false, `Backlog側で認可が拒否またはキャンセルされました（${errorParam}）。`);
  if (!code || !state) return oauthResultPage(false, "パラメータが不足しています（code/state）。");
  const pending = await consumePendingState(env, "backlog", state);
  if (pending === null) {
    return oauthResultPage(false, "認可フローの有効期限が切れたか、不正なリクエストです。管理画面からやり直してください。");
  }
  const spaceUrl = pending.spaceUrl as string | undefined;
  if (!spaceUrl) return oauthResultPage(false, "スペースURLの情報が失われました。もう一度やり直してください。");
  if (!env.BACKLOG_OAUTH_CLIENT_ID || !env.BACKLOG_OAUTH_CLIENT_SECRET) {
    return oauthResultPage(false, "Backlog OAuthアプリが未設定です。");
  }

  try {
    const tokenRes = await fetch(`${spaceUrl}/api/v2/oauth2/token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: env.BACKLOG_OAUTH_CLIENT_ID,
        client_secret: env.BACKLOG_OAUTH_CLIENT_SECRET,
        code,
        redirect_uri: oauthRedirectUri(req, "backlog"),
      }),
    });
    if (!tokenRes.ok) {
      return oauthResultPage(false, `トークン取得に失敗しました (${tokenRes.status}): ${await tokenRes.text()}`);
    }
    const tokenData = (await tokenRes.json()) as { access_token: string; refresh_token?: string; expires_in: number };

    await saveConnection(env, "backlog", {
      accessToken: tokenData.access_token,
      refreshToken: tokenData.refresh_token,
      expiresAt: Math.floor(Date.now() / 1000) + tokenData.expires_in,
      extra: { spaceUrl },
    });
    return oauthResultPage(true, `Backlog（${spaceUrl}）と接続しました。`);
  } catch (err) {
    return oauthResultPage(false, `接続中にエラーが発生しました: ${err instanceof Error ? err.message : String(err)}`);
  }
}

export async function handleBacklogOAuthDisconnect(req: Request, env: Env, user: import("./types").AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  await clearConnection(env, "backlog");
  return jsonResponse(200, { status: "ok" });
}

export async function handleBacklogOAuthStatus(req: Request, env: Env): Promise<Response> {
  const conn = await getConnection(env, "backlog");
  if (!conn) return jsonResponse(200, { connected: false });
  return jsonResponse(200, {
    connected: true,
    label: (conn.extra.spaceUrl as string) ?? "Backlog",
    connectedAt: conn.connectedAt,
  });
}

interface BacklogAuth {
  spaceUrl: string;
  headers: Record<string, string>;
}

const REFRESH_MARGIN_SEC = 300;

// backlogSync.tsが実際のAPI呼び出し前に呼ぶ。OAuth接続があれば（必要なら自動更新して）
// それを返し、無ければnullを返して従来のBACKLOG_SPACE_URL/?apiKey=方式へフォールバックさせる。
export async function resolveBacklogOAuthContext(env: Env): Promise<BacklogAuth | null> {
  const conn = await getConnection(env, "backlog");
  if (!conn || !conn.accessToken) return null;
  const spaceUrl = conn.extra.spaceUrl as string | undefined;
  if (!spaceUrl) return null;

  let accessToken = conn.accessToken;
  const needsRefresh = conn.expiresAt !== null && conn.expiresAt < Math.floor(Date.now() / 1000) + REFRESH_MARGIN_SEC;
  if (needsRefresh && conn.refreshToken && env.BACKLOG_OAUTH_CLIENT_ID && env.BACKLOG_OAUTH_CLIENT_SECRET) {
    const res = await fetch(`${spaceUrl}/api/v2/oauth2/token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: env.BACKLOG_OAUTH_CLIENT_ID,
        client_secret: env.BACKLOG_OAUTH_CLIENT_SECRET,
        refresh_token: conn.refreshToken,
      }),
    });
    if (res.ok) {
      const data = (await res.json()) as { access_token: string; refresh_token?: string; expires_in: number };
      accessToken = data.access_token;
      await saveConnection(env, "backlog", {
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresAt: Math.floor(Date.now() / 1000) + data.expires_in,
      });
    }
    // リフレッシュ失敗時は古いアクセストークンのまま試行する（jiraOAuth.tsと同じ理由）。
  }

  return { spaceUrl, headers: { Authorization: `Bearer ${accessToken}` } };
}
