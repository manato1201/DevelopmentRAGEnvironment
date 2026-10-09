import type { AuthedUser, Env } from "./types";
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

// Google DriveとGmailのOAuth 2.0クリック接続（2026-10-09追加）。Googleカレンダー
// （calendarOAuth.ts）と同じ作り方で、OAuthクライアントはGmail送信用に登録済みのもの
// （GMAIL_OAUTH_CLIENT_ID / GMAIL_OAUTH_CLIENT_SECRET）を共用する。新しいsecretは要らない。
// GCP側で必要なのは、承認済みリダイレクトURIに次の2つを足し、同意画面のスコープに
// drive.readonly / gmail.readonly を加えることだけ（docs/google-integrations.md参照）。
//
// どちらも読み取り専用スコープ。メールやファイルの書き込み・削除はできない。
export type GoogleOAuthService = "google_drive" | "gmail";

const GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const REFRESH_MARGIN_SEC = 300;

interface ServiceConfig {
  scope: string;
  label: string;
  profileUrl: string;
  profileEmail: (data: Record<string, unknown>) => string | null;
}

const SERVICES: Record<GoogleOAuthService, ServiceConfig> = {
  google_drive: {
    scope: "https://www.googleapis.com/auth/drive.readonly",
    label: "Google Drive",
    profileUrl: "https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)",
    profileEmail: (d) => ((d.user as { emailAddress?: string } | undefined)?.emailAddress ?? null),
  },
  gmail: {
    scope: "https://www.googleapis.com/auth/gmail.readonly",
    label: "Gmail",
    profileUrl: "https://gmail.googleapis.com/gmail/v1/users/me/profile",
    profileEmail: (d) => (typeof d.emailAddress === "string" ? d.emailAddress : null),
  },
};

export async function handleGoogleOAuthStart(req: Request, env: Env, service: GoogleOAuthService): Promise<Response> {
  const cfg = SERVICES[service];
  if (!env.GMAIL_OAUTH_CLIENT_ID) {
    return oauthResultPage(false, "Google OAuthアプリが未設定です（GMAIL_OAUTH_CLIENT_IDをsecretで設定してください。Gmail送信・カレンダー連携と共用します）");
  }
  const user = await authenticateFromQueryKey(req, env);
  if (!user) return oauthResultPage(false, "認証に失敗しました。管理画面からやり直してください。");
  try {
    requireKnowledgeEditor(user);
  } catch {
    return oauthResultPage(false, "この操作にはナレッジ登録権限が必要です。");
  }

  const state = await createPendingState(env, service, {});
  const url = new URL(GOOGLE_AUTHORIZE_URL);
  url.searchParams.set("client_id", env.GMAIL_OAUTH_CLIENT_ID);
  url.searchParams.set("redirect_uri", oauthRedirectUri(req, service));
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", cfg.scope);
  url.searchParams.set("access_type", "offline");
  url.searchParams.set("prompt", "consent");
  url.searchParams.set("state", state);
  return Response.redirect(url.toString(), 302);
}

export async function handleGoogleOAuthCallback(req: Request, env: Env, service: GoogleOAuthService): Promise<Response> {
  const cfg = SERVICES[service];
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const errorParam = url.searchParams.get("error");
  if (errorParam) return oauthResultPage(false, `Google側で認可が拒否またはキャンセルされました（${errorParam}）。`);
  if (!code || !state) return oauthResultPage(false, "パラメータが不足しています（code/state）。");
  const pending = await consumePendingState(env, service, state);
  if (pending === null) {
    return oauthResultPage(false, "認可フローの有効期限が切れたか、不正なリクエストです。管理画面からやり直してください。");
  }
  if (!env.GMAIL_OAUTH_CLIENT_ID || !env.GMAIL_OAUTH_CLIENT_SECRET) {
    return oauthResultPage(false, "Google OAuthアプリが未設定です。");
  }

  try {
    const tokenRes = await fetch(GOOGLE_TOKEN_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: env.GMAIL_OAUTH_CLIENT_ID,
        client_secret: env.GMAIL_OAUTH_CLIENT_SECRET,
        code,
        redirect_uri: oauthRedirectUri(req, service),
      }),
    });
    if (!tokenRes.ok) {
      return oauthResultPage(false, `トークン取得に失敗しました (${tokenRes.status}): ${await tokenRes.text()}`);
    }
    const tokenData = (await tokenRes.json()) as { access_token: string; refresh_token?: string; expires_in: number };
    if (!tokenData.refresh_token) {
      return oauthResultPage(
        false,
        "リフレッシュトークンを取得できませんでした。Googleアカウントの「サードパーティ製アプリとサービス」設定で" +
          "このアプリへのアクセスを一度削除してから、もう一度接続し直してください。",
      );
    }

    // 接続したアカウント（メールアドレス）を表示用に控える。失敗しても接続自体は有効。
    let account: string | null = null;
    try {
      const profileRes = await fetch(cfg.profileUrl, { headers: { Authorization: `Bearer ${tokenData.access_token}` } });
      if (profileRes.ok) account = cfg.profileEmail((await profileRes.json()) as Record<string, unknown>);
    } catch {
      /* 表示用の付随情報なので無視 */
    }

    await saveConnection(env, service, {
      accessToken: tokenData.access_token,
      refreshToken: tokenData.refresh_token,
      expiresAt: Math.floor(Date.now() / 1000) + tokenData.expires_in,
      extra: account ? { account } : {},
    });
    return oauthResultPage(true, `${cfg.label}と接続しました。同期する対象の設定は、管理画面のナレッジ登録タブで行ってください。`);
  } catch (err) {
    return oauthResultPage(false, `接続中にエラーが発生しました: ${err instanceof Error ? err.message : String(err)}`);
  }
}

export async function handleGoogleOAuthDisconnect(env: Env, user: AuthedUser, service: GoogleOAuthService): Promise<Response> {
  requireKnowledgeEditor(user);
  await clearConnection(env, service);
  return jsonResponse(200, { status: "ok" });
}

export async function googleOAuthStatus(env: Env, service: GoogleOAuthService): Promise<{ connected: boolean; label?: string }> {
  const conn = await getConnection(env, service);
  if (!conn) return { connected: false };
  const account = typeof conn.extra.account === "string" ? conn.extra.account : "";
  return { connected: true, label: account || SERVICES[service].label };
}

// 同期処理が実際のAPI呼び出し前に呼ぶ。OAuth接続があれば（必要なら自動更新して）アクセス
// トークンを返し、無ければnullを返す（Driveは従来のサービスアカウント方式へフォールバックする）。
export async function resolveGoogleOAuthAccessToken(env: Env, service: GoogleOAuthService): Promise<string | null> {
  const conn = await getConnection(env, service);
  if (!conn || !conn.accessToken) return null;

  const needsRefresh = conn.expiresAt !== null && conn.expiresAt < Math.floor(Date.now() / 1000) + REFRESH_MARGIN_SEC;
  if (needsRefresh && conn.refreshToken && env.GMAIL_OAUTH_CLIENT_ID && env.GMAIL_OAUTH_CLIENT_SECRET) {
    const res = await fetch(GOOGLE_TOKEN_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: env.GMAIL_OAUTH_CLIENT_ID,
        client_secret: env.GMAIL_OAUTH_CLIENT_SECRET,
        refresh_token: conn.refreshToken,
      }),
    });
    if (res.ok) {
      const data = (await res.json()) as { access_token: string; expires_in: number };
      await saveConnection(env, service, {
        accessToken: data.access_token,
        expiresAt: Math.floor(Date.now() / 1000) + data.expires_in,
      });
      return data.access_token;
    }
    // リフレッシュ失敗時は古いアクセストークンのまま試行する（calendarOAuth.tsと同じ理由）。
  }
  return conn.accessToken;
}
