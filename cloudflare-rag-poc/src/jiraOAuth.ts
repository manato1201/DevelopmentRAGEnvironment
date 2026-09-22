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

// Jira OAuth 2.0 (3LO)、Atlassianの公式ドキュメント通りの実装
// （2026-09-22追加、「wrangler secret putでAPIトークン発行」を「接続するボタンを押すだけ」
// に置き換える取り組みの一つ）。JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN（Basic認証）による
// 従来方式は後方互換のため残し、OAuth接続があればそちらを優先する（jiraSync.ts参照）。
//
// 事前準備（技術者が一度だけ）: https://developer.atlassian.com/console/myapps/ で
// OAuth 2.0 (3LO) アプリを作成し、コールバックURL（handleJiraOAuthStartがリダイレクトする
// 先）を登録、scopeに read:jira-work と offline_access を追加する。得られた
// Client ID/SecretをJIRA_OAUTH_CLIENT_ID/JIRA_OAUTH_CLIENT_SECRETとしてsecret登録する。
const JIRA_OAUTH_SCOPE = "read:jira-work offline_access";
const JIRA_AUTHORIZE_URL = "https://auth.atlassian.com/authorize";
const JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token";

interface JiraAccessibleResource {
  id: string; // cloudId
  url: string; // サイトのURL（表示用）
  name: string;
}

// POST /admin/oauth/jira/start が期待するAuthorizationヘッダーの代わりに、ブラウザの
// 直接ナビゲーションで受け取った ?key= を検証する（authenticateFromQueryKey参照）。
export async function handleJiraOAuthStart(req: Request, env: Env): Promise<Response> {
  if (!env.JIRA_OAUTH_CLIENT_ID) {
    return oauthResultPage(false, "Jira OAuthアプリが未設定です（JIRA_OAUTH_CLIENT_IDをsecretで設定してください）");
  }
  const user = await authenticateFromQueryKey(req, env);
  if (!user) return oauthResultPage(false, "認証に失敗しました。管理画面からやり直してください。");
  try {
    requireKnowledgeEditor(user);
  } catch {
    return oauthResultPage(false, "この操作にはナレッジ登録権限が必要です。");
  }

  const state = await createPendingState(env, "jira", {});
  const url = new URL(JIRA_AUTHORIZE_URL);
  url.searchParams.set("audience", "api.atlassian.com");
  url.searchParams.set("client_id", env.JIRA_OAUTH_CLIENT_ID);
  url.searchParams.set("scope", JIRA_OAUTH_SCOPE);
  url.searchParams.set("redirect_uri", oauthRedirectUri(req, "jira"));
  url.searchParams.set("state", state);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("prompt", "consent");
  return Response.redirect(url.toString(), 302);
}

export async function handleJiraOAuthCallback(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const errorParam = url.searchParams.get("error");
  if (errorParam) {
    return oauthResultPage(false, `Jira側で認可が拒否またはキャンセルされました（${errorParam}）。`);
  }
  if (!code || !state) return oauthResultPage(false, "パラメータが不足しています（code/state）。");
  const pending = await consumePendingState(env, "jira", state);
  if (pending === null) {
    return oauthResultPage(false, "認可フローの有効期限が切れたか、不正なリクエストです。管理画面からやり直してください。");
  }
  if (!env.JIRA_OAUTH_CLIENT_ID || !env.JIRA_OAUTH_CLIENT_SECRET) {
    return oauthResultPage(false, "Jira OAuthアプリが未設定です。");
  }

  try {
    const tokenRes = await fetch(JIRA_TOKEN_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        grant_type: "authorization_code",
        client_id: env.JIRA_OAUTH_CLIENT_ID,
        client_secret: env.JIRA_OAUTH_CLIENT_SECRET,
        code,
        redirect_uri: oauthRedirectUri(req, "jira"),
      }),
    });
    if (!tokenRes.ok) {
      return oauthResultPage(false, `トークン取得に失敗しました (${tokenRes.status}): ${await tokenRes.text()}`);
    }
    const tokenData = (await tokenRes.json()) as {
      access_token: string;
      refresh_token?: string;
      expires_in: number;
    };

    // Jira CloudのAPIはサイトのドメインではなくcloudId経由のURL
    // （https://api.atlassian.com/ex/jira/{cloudId}/...）で叩く必要があるため、
    // 接続直後に一度だけ問い合わせて保存しておく（jiraSync.ts参照）。
    const resourcesRes = await fetch("https://api.atlassian.com/oauth/token/accessible-resources", {
      headers: { Authorization: `Bearer ${tokenData.access_token}`, Accept: "application/json" },
    });
    if (!resourcesRes.ok) {
      return oauthResultPage(false, `Jiraサイト情報の取得に失敗しました (${resourcesRes.status})`);
    }
    const resources = (await resourcesRes.json()) as JiraAccessibleResource[];
    if (resources.length === 0) {
      return oauthResultPage(false, "このアカウントでアクセスできるJiraサイトが見つかりませんでした。");
    }
    // 複数サイトにアクセスできるアカウントの場合、最初のサイトを採用する（多くの利用者は
    // 1サイトのみのため、選択UIまでは作り込まない。将来複数サイト対応が必要になれば
    // extra.sitesの残りを使ってサイト切り替えUIを追加できる）。
    const site = resources[0];

    await saveConnection(env, "jira", {
      accessToken: tokenData.access_token,
      refreshToken: tokenData.refresh_token,
      expiresAt: Math.floor(Date.now() / 1000) + tokenData.expires_in,
      extra: { cloudId: site.id, siteUrl: site.url, siteName: site.name, siteCount: resources.length },
      connectedBy: undefined,
    });

    const extraNote = resources.length > 1 ? `（${resources.length}サイト中「${site.name}」を使用します）` : "";
    return oauthResultPage(true, `Jira（${site.name}）と接続しました${extraNote}。`);
  } catch (err) {
    return oauthResultPage(false, `接続中にエラーが発生しました: ${err instanceof Error ? err.message : String(err)}`);
  }
}

// POST /admin/kb/oauth/jira/disconnect — 通常の管理画面API呼び出し（Authorizationヘッダー
// 経由）で接続を解除する。以後jiraSync.tsはJIRA_BASE_URL等の従来方式にフォールバックする。
export async function handleJiraOAuthDisconnect(req: Request, env: Env, user: import("./types").AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  await clearConnection(env, "jira");
  return jsonResponse(200, { status: "ok" });
}

export async function handleJiraOAuthStatus(req: Request, env: Env): Promise<Response> {
  const conn = await getConnection(env, "jira");
  if (!conn) return jsonResponse(200, { connected: false });
  return jsonResponse(200, {
    connected: true,
    label: (conn.extra.siteName as string) ?? "Jira",
    connectedAt: conn.connectedAt,
  });
}

interface JiraAuthContext {
  baseUrl: string; // 例: https://api.atlassian.com/ex/jira/{cloudId}
  headers: Record<string, string>;
}

// リフレッシュトークンで新しいアクセストークンを取る猶予（期限の5分前から更新する）。
const REFRESH_MARGIN_SEC = 300;

// jiraSync.tsが実際のAPI呼び出し前に呼ぶ、認証コンテキストの解決関数。
// OAuth接続があればそれを（期限が近ければ自動更新してから）優先し、無ければnullを返して
// 呼び出し元に従来のJIRA_BASE_URL/Basic認証へフォールバックさせる。
export async function resolveJiraOAuthContext(env: Env): Promise<JiraAuthContext | null> {
  const conn = await getConnection(env, "jira");
  if (!conn || !conn.accessToken) return null;

  let accessToken = conn.accessToken;
  const needsRefresh = conn.expiresAt !== null && conn.expiresAt < Math.floor(Date.now() / 1000) + REFRESH_MARGIN_SEC;
  if (needsRefresh && conn.refreshToken && env.JIRA_OAUTH_CLIENT_ID && env.JIRA_OAUTH_CLIENT_SECRET) {
    const res = await fetch(JIRA_TOKEN_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        grant_type: "refresh_token",
        client_id: env.JIRA_OAUTH_CLIENT_ID,
        client_secret: env.JIRA_OAUTH_CLIENT_SECRET,
        refresh_token: conn.refreshToken,
      }),
    });
    if (res.ok) {
      const data = (await res.json()) as { access_token: string; refresh_token?: string; expires_in: number };
      accessToken = data.access_token;
      await saveConnection(env, "jira", {
        accessToken: data.access_token,
        refreshToken: data.refresh_token, // Atlassianはローテーションする場合があるため更新分を保存
        expiresAt: Math.floor(Date.now() / 1000) + data.expires_in,
      });
    }
    // リフレッシュ失敗時は古いアクセストークンのまま試行する（呼び出し元のAPIコールが
    // 401で失敗すれば、その時点でユーザーに「再接続してください」と伝わる。ここで
    // 例外を投げると「一時的なリフレッシュ失敗」と「本当に未接続」の区別がしにくくなる）。
  }

  const cloudId = conn.extra.cloudId as string | undefined;
  if (!cloudId) return null;
  return {
    baseUrl: `https://api.atlassian.com/ex/jira/${cloudId}`,
    headers: { Authorization: `Bearer ${accessToken}`, Accept: "application/json" },
  };
}
