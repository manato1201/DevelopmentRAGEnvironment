// MCPサーバーへのOAuth 2.1認可（共通層。2026-10-08追加）。別プロジェクトの mcp/core/auth.py にならう。
//   - 探索（RFC 9728 保護リソースメタデータ / RFC 8414 認可サーバーメタデータ）
//   - クライアントの動的登録（RFC 7591）… こちらでOAuthアプリを作る・secretを設定する必要が無い
//   - PKCE（S256）とリソース指定（RFC 8707）
// 途中の状態（code_verifier等）はD1の oauth_pending_state に置く。ブラウザが戻ってくる
// コールバックは別のisolateで処理されうるため、メモリには持たない。

import type { Env } from "../types";
import { consumePendingState, createPendingState } from "../oauthConnections";
import { CLIENT_NAME } from "./protocol";
import { McpAuthError, McpError, staticClientFor, type McpProvider } from "./providers";

const TIMEOUT_MS = 30_000;

type FetchLike = typeof fetch;

export interface OAuthClient {
  client_id: string;
  client_secret?: string;
}

export interface Credential {
  accessToken: string;
  refreshToken: string;
  expiresAt: number | null; // unix秒
  resourceUrl: string;
  tokenEndpoint: string;
  client: OAuthClient;
}

interface AuthServerMetadata {
  issuer?: string;
  authorization_endpoint: string;
  token_endpoint: string;
  registration_endpoint?: string;
  resource_scopes: string[];
}

export function redirectUri(origin: string): string {
  return `${origin.replace(/\/+$/, "")}/admin/oauth/mcp/callback`;
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function pkce(): Promise<{ verifier: string; challenge: string }> {
  const verifier = base64Url(crypto.getRandomValues(new Uint8Array(48)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: base64Url(new Uint8Array(digest)) };
}

// メタデータが指すエンドポイントは、公式サーバーのメタデータ由来でも https だけを許す。
function requireHttps(url: string, what: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new McpError(`${what}のURLが不正です`);
  }
  if (parsed.protocol !== "https:") throw new McpError(`${what}はhttpsのURLだけ使えます`);
  return url;
}

async function getJson(url: string, fetchImpl: FetchLike): Promise<Record<string, unknown> | null> {
  try {
    const response = await fetchImpl(url, { headers: { Accept: "application/json" }, signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (response.status !== 200) return null;
    const data = (await response.json()) as unknown;
    return data && typeof data === "object" && !Array.isArray(data) ? (data as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export async function discover(serverUrl: string, fetchImpl: FetchLike = fetch): Promise<AuthServerMetadata> {
  const parsed = new URL(serverUrl);
  const origin = `${parsed.protocol}//${parsed.host}`;
  let authorizationServer = origin;
  let resourceScopes: string[] = [];
  for (const candidate of [
    `${origin}/.well-known/oauth-protected-resource${parsed.pathname}`,
    `${origin}/.well-known/oauth-protected-resource`,
  ]) {
    const resource = await getJson(candidate, fetchImpl);
    const servers = resource?.authorization_servers;
    if (Array.isArray(servers) && servers.length > 0) {
      authorizationServer = String(servers[0]).replace(/\/+$/, "");
      if (Array.isArray(resource?.scopes_supported)) resourceScopes = resource!.scopes_supported.map(String);
      break;
    }
  }
  for (const candidate of [
    `${authorizationServer}/.well-known/oauth-authorization-server`,
    `${authorizationServer}/.well-known/openid-configuration`,
  ]) {
    const metadata = await getJson(candidate, fetchImpl);
    if (metadata?.authorization_endpoint && metadata?.token_endpoint) {
      return {
        issuer: typeof metadata.issuer === "string" ? metadata.issuer : undefined,
        authorization_endpoint: requireHttps(String(metadata.authorization_endpoint), "認可エンドポイント"),
        token_endpoint: requireHttps(String(metadata.token_endpoint), "トークンエンドポイント"),
        registration_endpoint: metadata.registration_endpoint ? requireHttps(String(metadata.registration_endpoint), "登録エンドポイント") : undefined,
        resource_scopes: resourceScopes,
      };
    }
  }
  throw new McpError("MCPサーバーの認証情報を取得できませんでした。時間をおいてやり直してください");
}

// このWorkerが認可サーバーに登録したOAuthクライアント。キャッシュする（ボタンを押すたびに
// 登録すると、認可サーバー側にクライアントが増え続けるため）。
async function clientFor(env: Env, provider: McpProvider, metadata: AuthServerMetadata, callback: string, fetchImpl: FetchLike): Promise<OAuthClient> {
  // 自動登録に対応しないサーバー（GitHub・Slack・Google）は、事前に作ったOAuthアプリのsecretを使う。
  if (provider.staticClient) {
    const fixed = staticClientFor(env, provider);
    if (!fixed) throw new McpError("このサービスはOAuthアプリの準備が必要です。" + provider.staticClient.setupHint);
    return fixed;
  }
  const cacheKey = `${metadata.issuer ?? metadata.token_endpoint}|${callback}`;
  const cached = await env.DB.prepare("SELECT client_json FROM mcp_clients WHERE cache_key = ?")
    .bind(cacheKey)
    .first<{ client_json: string }>();
  if (cached) {
    try {
      const client = JSON.parse(cached.client_json) as OAuthClient;
      if (client.client_id) return client;
    } catch {
      // 壊れたキャッシュは作り直す
    }
  }
  if (!metadata.registration_endpoint) throw new McpError("このMCPサーバーはクライアントの自動登録に対応していません");
  let response: Response;
  try {
    response = await fetchImpl(metadata.registration_endpoint, {
      method: "POST",
      headers: { "content-type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        client_name: CLIENT_NAME,
        redirect_uris: [callback],
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"],
        token_endpoint_auth_method: "none",
      }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    throw new McpError(`クライアント登録に失敗しました: ${err instanceof Error ? err.message : String(err)}`);
  }
  if (response.status !== 200 && response.status !== 201) {
    throw new McpError(`クライアント登録に失敗しました: HTTP ${response.status}`);
  }
  const data = (await response.json()) as Record<string, unknown>;
  if (!data.client_id) throw new McpError("クライアント登録の応答が不正です");
  const client: OAuthClient = { client_id: String(data.client_id) };
  if (data.client_secret) client.client_secret = String(data.client_secret);
  await env.DB.prepare("INSERT OR REPLACE INTO mcp_clients (cache_key, client_json, created_at) VALUES (?, ?, ?)")
    .bind(cacheKey, JSON.stringify(client), Math.floor(Date.now() / 1000))
    .run();
  return client;
}

export async function buildAuthorizeUrl(
  env: Env,
  provider: McpProvider,
  origin: string,
  connectedBy: string,
  fetchImpl: FetchLike = fetch,
): Promise<string> {
  const metadata = await discover(provider.url, fetchImpl);
  const callback = redirectUri(origin);
  const client = await clientFor(env, provider, metadata, callback, fetchImpl);
  const { verifier, challenge } = await pkce();
  const state = await createPendingState(env, "mcp", {
    provider_id: provider.id,
    code_verifier: verifier,
    redirect_uri: callback,
    client,
    token_endpoint: metadata.token_endpoint,
    connected_by: connectedBy,
  });
  const url = new URL(metadata.authorization_endpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", client.client_id);
  url.searchParams.set("redirect_uri", callback);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  if (provider.sendResource !== false) url.searchParams.set("resource", provider.url);
  for (const [key, value] of Object.entries(provider.authParams ?? {})) url.searchParams.set(key, value);
  const scopes = provider.scopes.length > 0 ? provider.scopes : metadata.resource_scopes;
  if (scopes.length > 0) url.searchParams.set("scope", scopes.join(" "));
  return url.toString();
}

export async function consumeState(env: Env, state: string): Promise<Record<string, unknown>> {
  const payload = await consumePendingState(env, "mcp", state);
  if (payload === null) {
    throw new McpError("認可フローの有効期限が切れたか、不正なリクエストです。もう一度接続をやり直してください");
  }
  return payload;
}

async function tokenRequest(tokenEndpoint: string, client: OAuthClient, data: Record<string, string>, fetchImpl: FetchLike): Promise<Record<string, unknown>> {
  const body = new URLSearchParams({ ...data, client_id: client.client_id });
  if (client.client_secret) body.set("client_secret", client.client_secret);
  let response: Response;
  try {
    response = await fetchImpl(tokenEndpoint, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: body.toString(),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    throw new McpError(`トークンの取得に失敗しました: ${err instanceof Error ? err.message : String(err)}`);
  }
  if (response.status !== 200) throw new McpError(`トークンの取得に失敗しました: HTTP ${response.status}`);
  const token = (await response.json()) as Record<string, unknown>;
  if (!token.access_token) throw new McpError("トークンの応答が不正です");
  return token;
}

function credentialFromToken(token: Record<string, unknown>, previous: Credential): Credential {
  const expiresIn = Number(token.expires_in);
  return {
    accessToken: String(token.access_token),
    refreshToken: String(token.refresh_token || previous.refreshToken || ""),
    expiresAt: Number.isFinite(expiresIn) && expiresIn > 0 ? Math.floor(Date.now() / 1000) + expiresIn : null,
    resourceUrl: previous.resourceUrl,
    tokenEndpoint: previous.tokenEndpoint,
    client: previous.client,
  };
}

export async function exchangeCode(code: string, payload: Record<string, unknown>, provider: McpProvider, fetchImpl: FetchLike = fetch): Promise<Credential> {
  const client = payload.client as OAuthClient;
  const tokenEndpoint = String(payload.token_endpoint);
  const token = await tokenRequest(
    tokenEndpoint,
    client,
    {
      grant_type: "authorization_code",
      code,
      redirect_uri: String(payload.redirect_uri),
      code_verifier: String(payload.code_verifier),
      ...(provider.sendResource !== false ? { resource: provider.url } : {}),
    },
    fetchImpl,
  );
  const blank: Credential = { accessToken: "", refreshToken: "", expiresAt: null, resourceUrl: provider.url, tokenEndpoint, client };
  return credentialFromToken(token, blank);
}

// アクセストークンが期限切れ間近（60秒以内）か。
export function expiring(credential: Credential, now = Math.floor(Date.now() / 1000)): boolean {
  return credential.expiresAt !== null && credential.expiresAt - 60 <= now;
}

export async function refresh(credential: Credential, fetchImpl: FetchLike = fetch, sendResource = true): Promise<Credential> {
  if (!credential.refreshToken) throw new McpAuthError("接続の有効期限が切れました。もう一度連携してください");
  try {
    const token = await tokenRequest(
      credential.tokenEndpoint,
      credential.client,
      { grant_type: "refresh_token", refresh_token: credential.refreshToken, ...(sendResource ? { resource: credential.resourceUrl } : {}) },
      fetchImpl,
    );
    return credentialFromToken(token, credential);
  } catch (err) {
    if (err instanceof McpError) throw new McpAuthError("接続の更新に失敗しました。もう一度連携してください");
    throw err;
  }
}
