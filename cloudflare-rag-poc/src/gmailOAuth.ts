import type { Env } from "./types";

// 個人のGmailアカウントでアラートメールを送るためのOAuthリフレッシュトークン方式。
// サービスアカウント＋Domain-Wide Delegation方式はGoogle Workspace限定の機能で、
// 個人のgmail.comアカウントでは設定できないことが判明したため、こちらに切り替えた
// （2026-08-26）。一度だけブラウザでOAuth同意を行い、得られたrefresh_tokenを
// シークレットとして保存しておけば、以降はWorker側で自動的にaccess_tokenを再取得できる。
export async function getGmailAccessToken(env: Env): Promise<string> {
  if (
    !env.GMAIL_OAUTH_CLIENT_ID ||
    !env.GMAIL_OAUTH_CLIENT_SECRET ||
    !env.GMAIL_OAUTH_REFRESH_TOKEN
  ) {
    throw new Error(
      "Gmail OAuthのクライアントID/シークレット/リフレッシュトークンが設定されていません",
    );
  }
  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: env.GMAIL_OAUTH_CLIENT_ID,
      client_secret: env.GMAIL_OAUTH_CLIENT_SECRET,
      refresh_token: env.GMAIL_OAUTH_REFRESH_TOKEN,
      grant_type: "refresh_token",
    }),
  });
  if (!res.ok) {
    throw new Error(
      `Gmail OAuth2トークン更新エラー (${res.status}): ${await res.text()}`,
    );
  }
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}
