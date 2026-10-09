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
import { scopeFor, startOwner } from "./syncTargets";

// GoogleカレンダーのOAuth 2.0クリック接続（2026-09-22追加）。既存のDrive同期は
// サービスアカウント方式（GOOGLE_SERVICE_ACCOUNT_JSON、対象カレンダー/フォルダを
// サービスアカウントのメールアドレスへ共有してもらう必要がある）のままだが、
// カレンダーは「自分のカレンダーをボタン一つで連携したい」というニーズに合わせて
// OAuthユーザー同意フローに対応する。GCPのOAuthクライアントはリソースであって
// スコープに縛られないため、Gmail送信で既に登録済みのOAuthクライアント
// （GMAIL_OAUTH_CLIENT_ID/GMAIL_OAUTH_CLIENT_SECRET）をそのまま流用でき、
// 新規のOAuthアプリ登録は不要（承認済みリダイレクトURIに/admin/oauth/google_calendar/callback
// を追加するだけでよい）。
const CALENDAR_OAUTH_SCOPE = "https://www.googleapis.com/auth/calendar.readonly";
const GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";

export async function handleCalendarOAuthStart(req: Request, env: Env): Promise<Response> {
  if (!env.GMAIL_OAUTH_CLIENT_ID) {
    return oauthResultPage(false, "Google OAuthアプリが未設定です（GMAIL_OAUTH_CLIENT_IDをsecretで設定してください。Gmail連携と共用します）");
  }
  // 接続の持ち主: ?owner=me なら本人専用の接続、無ければデプロイ全体で共有する接続（ナレッジ登録権限が必要）。
  const who = await startOwner(req, env);
  if (!who.ok) return oauthResultPage(false, who.message);
  const ownerId = who.ownerId;

  const state = await createPendingState(env, "google_calendar", { owner_id: ownerId });
  const url = new URL(GOOGLE_AUTHORIZE_URL);
  url.searchParams.set("client_id", env.GMAIL_OAUTH_CLIENT_ID);
  url.searchParams.set("redirect_uri", oauthRedirectUri(req, "google_calendar"));
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", CALENDAR_OAUTH_SCOPE);
  url.searchParams.set("access_type", "offline"); // refresh_tokenを得るために必須
  url.searchParams.set("prompt", "consent"); // 2回目以降もrefresh_tokenを確実に得るため毎回同意画面を出す
  url.searchParams.set("state", state);
  return Response.redirect(url.toString(), 302);
}

export async function handleCalendarOAuthCallback(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const errorParam = url.searchParams.get("error");
  if (errorParam) return oauthResultPage(false, `Google側で認可が拒否またはキャンセルされました（${errorParam}）。`);
  if (!code || !state) return oauthResultPage(false, "パラメータが不足しています（code/state）。");
  const pending = await consumePendingState(env, "google_calendar", state);
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
        redirect_uri: oauthRedirectUri(req, "google_calendar"),
      }),
    });
    if (!tokenRes.ok) {
      return oauthResultPage(false, `トークン取得に失敗しました (${tokenRes.status}): ${await tokenRes.text()}`);
    }
    const tokenData = (await tokenRes.json()) as { access_token: string; refresh_token?: string; expires_in: number };
    if (!tokenData.refresh_token) {
      // 同じGoogleアカウントで既に一度同意済みだと、prompt=consentを付けてもrefresh_token
      // が返らないことがある（Googleの既知の挙動）。この場合は明示的にエラーにして、
      // 「Googleアカウント設定でこのアプリのアクセスを一度取り消してから再接続してください」
      // と案内する（無言でaccess_tokenだけ保存すると、1時間後に静かに動かなくなるため）。
      return oauthResultPage(
        false,
        "リフレッシュトークンを取得できませんでした。Googleアカウントの「サードパーティ製アプリとサービス」設定で" +
          "このアプリへのアクセスを一度削除してから、もう一度接続し直してください。",
      );
    }

    await saveConnection(env, "google_calendar", {
      ownerId: String(pending.owner_id ?? ""),
      accessToken: tokenData.access_token,
      refreshToken: tokenData.refresh_token,
      expiresAt: Math.floor(Date.now() / 1000) + tokenData.expires_in,
      extra: {},
    });
    return oauthResultPage(true, "Googleカレンダーと接続しました。カレンダーIDの設定は、管理画面のナレッジ登録タブ（「同期・通知の設定」）で行ってください。");
  } catch (err) {
    return oauthResultPage(false, `接続中にエラーが発生しました: ${err instanceof Error ? err.message : String(err)}`);
  }
}

export async function handleCalendarOAuthDisconnect(req: Request, env: Env, user: import("./types").AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { mine?: boolean };
  const { ownerId } = scopeFor(user, body.mine);
  await clearConnection(env, "google_calendar", ownerId);
  return jsonResponse(200, { status: "ok" });
}

export async function handleCalendarOAuthStatus(req: Request, env: Env): Promise<Response> {
  const conn = await getConnection(env, "google_calendar");
  if (!conn) return jsonResponse(200, { connected: false });
  return jsonResponse(200, { connected: true, label: "Google", connectedAt: conn.connectedAt });
}

const REFRESH_MARGIN_SEC = 300;

// calendarSync.tsが実際のAPI呼び出し前に呼ぶ。OAuth接続があれば（必要なら自動更新して）
// そのアクセストークンを返し、無ければnullを返して従来のサービスアカウント方式へ
// フォールバックさせる（getGoogleAccessToken、googleAuth.ts参照）。
export async function resolveCalendarOAuthAccessToken(env: Env, ownerId = ""): Promise<string | null> {
  const conn = await getConnection(env, "google_calendar", ownerId);
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
      await saveConnection(env, "google_calendar", {
        ownerId,
        accessToken: data.access_token,
        expiresAt: Math.floor(Date.now() / 1000) + data.expires_in,
      });
      return data.access_token;
    }
    // リフレッシュ失敗時は古いアクセストークンのまま試行する（jiraOAuth.tsと同じ理由）。
  }
  return conn.accessToken;
}
