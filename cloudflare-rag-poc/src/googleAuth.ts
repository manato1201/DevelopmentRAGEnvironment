import type { Env } from "./types";

// サービスアカウントのJWT署名によるOAuth2アクセストークン取得（GASはUrlFetchApp+組み込みOAuthで
// 同等のことを透過的に行っているが、Workersには無いため自前で実装する）。
// GOOGLE_SERVICE_ACCOUNT_JSON シークレットには、GCPでダウンロードしたサービスアカウントの
// JSONキーファイルの中身をそのまま設定する（client_email・private_keyを含む）。

interface ServiceAccountKey {
  client_email: string;
  private_key: string;
}

function base64UrlEncode(data: ArrayBuffer | string): string {
  const bytes =
    typeof data === "string"
      ? new TextEncoder().encode(data)
      : new Uint8Array(data);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function pemToArrayBuffer(pem: string): ArrayBuffer {
  const b64 = pem
    .replace(/-----BEGIN PRIVATE KEY-----/, "")
    .replace(/-----END PRIVATE KEY-----/, "")
    .replace(/\s+/g, "");
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

async function signJwt(key: ServiceAccountKey, scope: string, subject?: string): Promise<string> {
  const header = { alg: "RS256", typ: "JWT" };
  const now = Math.floor(Date.now() / 1000);
  const claims: Record<string, unknown> = {
    iss: key.client_email,
    scope,
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  };
  // Gmail送信など「サービスアカウントが特定のGoogle Workspaceユーザーになりすまして操作する」
  // 場合はsubにそのユーザーのメールアドレスを指定する（ドメイン全体の委任＝Domain-Wide
  // Delegationがそのユーザーの属する組織側で許可されている必要がある。個人のgmail.comアカウント
  // では設定できないため、その場合は別方式（OAuthユーザー同意フロー等）が必要）。
  if (subject) claims.sub = subject;

  const unsigned = `${base64UrlEncode(JSON.stringify(header))}.${base64UrlEncode(JSON.stringify(claims))}`;

  const cryptoKey = await crypto.subtle.importKey(
    "pkcs8",
    pemToArrayBuffer(key.private_key),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    cryptoKey,
    new TextEncoder().encode(unsigned),
  );

  return `${unsigned}.${base64UrlEncode(signature)}`;
}

// scope例: "https://www.googleapis.com/auth/drive.readonly"
// subjectを指定すると、そのGoogle Workspaceユーザーになりすましてアクセスする
// （Gmail送信など。Domain-Wide Delegationの設定が別途必要）。
export async function getGoogleAccessToken(
  env: Env,
  scope: string,
  subject?: string,
): Promise<string> {
  const key = JSON.parse(env.GOOGLE_SERVICE_ACCOUNT_JSON) as ServiceAccountKey;
  const jwt = await signJwt(key, scope, subject);

  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }),
  });
  if (!res.ok) {
    throw new Error(
      `Google OAuth2トークン取得エラー (${res.status}): ${await res.text()}`,
    );
  }
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}
