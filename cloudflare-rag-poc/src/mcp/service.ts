// MCP連携の入口（共通層。2026-10-08追加）。別プロジェクトの mcp/core/service.py にならう。
// ルート（routes.ts）とチャット（chat.ts）は、通信・認可・保存・ポリシーに直接触らず、
// ここの関数だけを呼ぶ。内部の順序は固定:
//   connection（D1から読む）→ credentials/auth（期限切れなら更新）→ protocol（サーバーと通信）
//   → permissions（ポリシー適用）→ audit（記録）。失敗は接続の状態（要再認証）へ反映する。

import type { Env } from "../types";
import * as auth from "./auth";
import type { Credential } from "./auth";
import {
  applyPolicy,
  offered,
  requireAllowed,
  type ClassifiedTool,
} from "./permissions";
import { openSession, type McpCallResult, type McpSession } from "./protocol";
import {
  McpAuthError,
  McpConfigError,
  McpError,
  McpNotConnectedError,
  McpToolNotAllowed,
  getProvider,
  providerIds,
  MCP_PROVIDERS,
  setupFor,
  type McpProvider,
} from "./providers";

type FetchLike = typeof fetch;

export const TOOLS_CACHE_SECONDS = 300;
export const MAX_TOOLS_PER_PROVIDER = 64;

export type ConnectionStatus = "connected" | "reauth_required";

export interface Connection {
  providerId: string;
  credential: Credential;
  status: ConnectionStatus;
  lastError: string;
  enabledTools: string[] | null; // null = ポリシーが許す全ツール
  chatEnabled: boolean;
  connectedAt: number;
  connectedBy: string | null;
}

interface ConnectionRow {
  provider_id: string;
  access_token: string;
  refresh_token: string | null;
  expires_at: number | null;
  resource_url: string;
  token_endpoint: string;
  client_json: string;
  status: ConnectionStatus;
  last_error: string;
  enabled_tools_json: string | null;
  chat_enabled: number;
  connected_at: number;
  connected_by: string | null;
}

// ── ツール一覧のキャッシュ（同じisolateが生きている間だけ。ツール定義はめったに変わらない） ──
const toolsCache = new Map<string, { at: number; tools: ClassifiedTool[] }>();

export function clearToolsCache(providerId?: string): void {
  if (providerId) toolsCache.delete(providerId);
  else toolsCache.clear();
}

// ── D1の読み書き ─────────────────────────────────────────────────────────────

function rowToConnection(row: ConnectionRow): Connection {
  let enabled: string[] | null = null;
  if (row.enabled_tools_json) {
    try {
      const parsed = JSON.parse(row.enabled_tools_json) as unknown;
      if (Array.isArray(parsed)) enabled = parsed.map(String);
    } catch {
      enabled = null;
    }
  }
  return {
    providerId: row.provider_id,
    credential: {
      accessToken: row.access_token,
      refreshToken: row.refresh_token ?? "",
      expiresAt: row.expires_at,
      resourceUrl: row.resource_url,
      tokenEndpoint: row.token_endpoint,
      client: JSON.parse(row.client_json),
    },
    status: row.status,
    lastError: row.last_error,
    enabledTools: enabled,
    chatEnabled: row.chat_enabled === 1,
    connectedAt: row.connected_at,
    connectedBy: row.connected_by,
  };
}

export async function getConnection(
  env: Env,
  providerId: string,
): Promise<Connection | null> {
  const row = await env.DB.prepare(
    "SELECT * FROM mcp_connections WHERE provider_id = ?",
  )
    .bind(providerId)
    .first<ConnectionRow>();
  return row ? rowToConnection(row) : null;
}

export async function saveConnection(
  env: Env,
  connection: Connection,
): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  const c = connection.credential;
  await env.DB.prepare(
    `INSERT INTO mcp_connections
       (provider_id, access_token, refresh_token, expires_at, resource_url, token_endpoint, client_json,
        status, last_error, enabled_tools_json, chat_enabled, connected_at, connected_by, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(provider_id) DO UPDATE SET
       access_token = excluded.access_token, refresh_token = excluded.refresh_token, expires_at = excluded.expires_at,
       resource_url = excluded.resource_url, token_endpoint = excluded.token_endpoint, client_json = excluded.client_json,
       status = excluded.status, last_error = excluded.last_error, enabled_tools_json = excluded.enabled_tools_json,
       chat_enabled = excluded.chat_enabled, connected_at = excluded.connected_at, connected_by = excluded.connected_by,
       updated_at = excluded.updated_at`,
  )
    .bind(
      connection.providerId,
      c.accessToken,
      c.refreshToken || null,
      c.expiresAt,
      c.resourceUrl,
      c.tokenEndpoint,
      JSON.stringify(c.client),
      connection.status,
      connection.lastError,
      connection.enabledTools === null
        ? null
        : JSON.stringify(connection.enabledTools),
      connection.chatEnabled ? 1 : 0,
      connection.connectedAt,
      connection.connectedBy,
      now,
    )
    .run();
}

export async function audit(
  env: Env,
  entry: {
    providerId: string;
    userId: string | null;
    action: string;
    status?: "ok" | "error";
    detail?: string;
  },
): Promise<void> {
  try {
    await env.DB.prepare(
      "INSERT INTO mcp_audit (provider_id, user_id, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
    )
      .bind(
        entry.providerId,
        entry.userId,
        entry.action,
        entry.status ?? "ok",
        (entry.detail ?? "").slice(0, 300),
        Math.floor(Date.now() / 1000),
      )
      .run();
  } catch {
    // 監査ログの失敗でツール実行そのものは止めない
  }
}

// ── 接続・解除・状態 ─────────────────────────────────────────────────────────

// 認証が要らない公開サーバーの「接続」。トークンは持たず、有効化の記録だけを残す。
export async function connectPublic(env: Env, providerId: string, userId: string): Promise<McpProvider> {
  const provider = getProvider(providerId);
  if (provider.auth !== "none") throw new McpConfigError("このサービスは認証が必要です");
  const previous = await getConnection(env, provider.id);
  await saveConnection(env, {
    providerId: provider.id,
    credential: { accessToken: "", refreshToken: "", expiresAt: null, resourceUrl: provider.url, tokenEndpoint: "", client: { client_id: "" } },
    status: "connected",
    lastError: "",
    enabledTools: previous?.enabledTools ?? null,
    chatEnabled: previous?.chatEnabled ?? false,
    connectedAt: Math.floor(Date.now() / 1000),
    connectedBy: userId,
  });
  clearToolsCache(provider.id);
  await audit(env, { providerId: provider.id, userId, action: "connect" });
  return provider;
}

export async function startAuthorization(
  env: Env,
  providerId: string,
  origin: string,
  userId: string,
  fetchImpl: FetchLike = fetch,
): Promise<string> {
  return auth.buildAuthorizeUrl(
    env,
    getProvider(providerId),
    origin,
    userId,
    fetchImpl,
  );
}

export async function completeAuthorization(
  env: Env,
  state: string,
  code: string,
  fetchImpl: FetchLike = fetch,
): Promise<McpProvider> {
  const payload = await auth.consumeState(env, state);
  const provider = getProvider(String(payload.provider_id));
  const credential = await auth.exchangeCode(
    code,
    payload,
    provider,
    fetchImpl,
  );
  const previous = await getConnection(env, provider.id);
  const connectedBy = payload.connected_by
    ? String(payload.connected_by)
    : null;
  await saveConnection(env, {
    providerId: provider.id,
    credential,
    status: "connected",
    lastError: "",
    // 再接続しても、ツール選択と「チャットで使う」の設定は引き継ぐ
    enabledTools: previous?.enabledTools ?? null,
    chatEnabled: previous?.chatEnabled ?? false,
    connectedAt: Math.floor(Date.now() / 1000),
    connectedBy,
  });
  clearToolsCache(provider.id);
  await audit(env, {
    providerId: provider.id,
    userId: connectedBy,
    action: "connect",
  });
  return provider;
}

export async function disconnect(
  env: Env,
  providerId: string,
  userId: string | null,
): Promise<void> {
  getProvider(providerId);
  await env.DB.prepare("DELETE FROM mcp_connections WHERE provider_id = ?")
    .bind(providerId)
    .run();
  clearToolsCache(providerId);
  await audit(env, { providerId, userId, action: "disconnect" });
}

export interface ProviderStatus {
  id: string;
  label: string;
  description: string;
  connected: boolean;
  status: ConnectionStatus | "disconnected";
  chatEnabled: boolean;
  enabledToolCount: number | null; // null = 全ツール
  connectedAt: number | null;
  setupRequired: boolean; // 接続の前に管理者のsecret設定が要る
  setupHint: string;
  noAuth: boolean; // 認証が要らない公開サーバー
}

export async function statuses(env: Env): Promise<ProviderStatus[]> {
  const rows = await env.DB.prepare(
    "SELECT * FROM mcp_connections",
  ).all<ConnectionRow>();
  const found = new Map(
    (rows.results ?? []).map((row) => [row.provider_id, rowToConnection(row)]),
  );
  return providerIds().map((id) => {
    const provider = MCP_PROVIDERS[id];
    const connection = found.get(id);
    return {
      id,
      label: provider.label,
      description: provider.description,
      connected: connection?.status === "connected",
      status: connection ? connection.status : "disconnected",
      chatEnabled: connection?.chatEnabled ?? false,
      enabledToolCount: connection?.enabledTools
        ? connection.enabledTools.length
        : null,
      connectedAt: connection?.connectedAt ?? null,
      setupRequired: setupFor(env, provider).needed,
      setupHint: setupFor(env, provider).hint,
      noAuth: provider.auth === "none",
    };
  });
}

// ── 認証情報の更新と、MCPセッションの確立 ─────────────────────────────────────

async function requireConnected(
  env: Env,
  providerId: string,
): Promise<Connection> {
  const connection = await getConnection(env, providerId);
  if (!connection) throw new McpNotConnectedError();
  if (connection.status !== "connected")
    throw new McpAuthError(
      "接続の有効期限が切れました。もう一度連携してください",
    );
  return connection;
}

async function markReauth(
  env: Env,
  connection: Connection,
  error: McpError,
): Promise<void> {
  connection.status = "reauth_required";
  connection.lastError = error.message.slice(0, 300);
  await saveConnection(env, connection);
  clearToolsCache(connection.providerId);
  await audit(env, {
    providerId: connection.providerId,
    userId: null,
    action: "reauth_required",
    status: "error",
    detail: error.message,
  });
}

async function open(
  env: Env,
  connection: Connection,
  provider: McpProvider,
  fetchImpl: FetchLike,
): Promise<McpSession> {
  if (auth.expiring(connection.credential)) {
    try {
      connection.credential = await auth.refresh(
        connection.credential,
        fetchImpl,
        provider.sendResource !== false,
      );
    } catch (err) {
      if (err instanceof McpAuthError) await markReauth(env, connection, err);
      throw err;
    }
    await saveConnection(env, connection);
  }
  try {
    return await openSession(
      provider.url,
      connection.credential.accessToken,
      fetchImpl,
    );
  } catch (err) {
    if (err instanceof McpAuthError) await markReauth(env, connection, err);
    throw err;
  }
}

// ── ツール ───────────────────────────────────────────────────────────────────

async function allTools(
  env: Env,
  providerId: string,
  refresh: boolean,
  fetchImpl: FetchLike,
): Promise<{ connection: Connection; tools: ClassifiedTool[] }> {
  const provider = getProvider(providerId);
  const connection = await requireConnected(env, providerId);
  const cached = toolsCache.get(providerId);
  if (
    cached &&
    !refresh &&
    Date.now() / 1000 - cached.at < TOOLS_CACHE_SECONDS
  ) {
    return { connection, tools: cached.tools };
  }
  const session = await open(env, connection, provider, fetchImpl);
  const tools = applyPolicy(provider, await session.listTools()).slice(
    0,
    MAX_TOOLS_PER_PROVIDER,
  );
  toolsCache.set(providerId, { at: Date.now() / 1000, tools });
  return { connection, tools };
}

export interface ToolSetting {
  name: string;
  description: string;
  readOnly: boolean;
  enabled: boolean;
}

// 管理画面用: ポリシーが許す全ツールと、それぞれが有効かどうか。
export async function toolSettings(
  env: Env,
  providerId: string,
  refresh = false,
  fetchImpl: FetchLike = fetch,
): Promise<ToolSetting[]> {
  const { connection, tools } = await allTools(
    env,
    providerId,
    refresh,
    fetchImpl,
  );
  return tools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    readOnly: tool.readOnly,
    enabled:
      connection.enabledTools === null ||
      connection.enabledTools.includes(tool.name),
  }));
}

export async function setEnabledTools(
  env: Env,
  providerId: string,
  names: string[],
): Promise<void> {
  const connection = await requireConnected(env, providerId);
  connection.enabledTools = [...new Set(names.map(String))].sort();
  await saveConnection(env, connection);
}

export async function setChatEnabled(
  env: Env,
  providerId: string,
  enabled: boolean,
): Promise<void> {
  const connection = await requireConnected(env, providerId);
  connection.chatEnabled = enabled;
  await saveConnection(env, connection);
}

export interface ChatTool {
  providerId: string;
  providerLabel: string;
  tool: ClassifiedTool;
}

// RAGチャットでモデルに見せるツール。「チャットで使う」がオンで接続中のサービスの、
// 有効化された読み取り専用ツールだけ。書き込み系は（確認の手段がまだ無いので）出さない。
// 1つのサービスの失敗（通信エラー・要再認証）で、他のサービスのツールまで使えなくしない。
export async function chatTools(
  env: Env,
  fetchImpl: FetchLike = fetch,
): Promise<ChatTool[]> {
  const rows = await env.DB.prepare(
    "SELECT provider_id FROM mcp_connections WHERE chat_enabled = 1 AND status = 'connected'",
  ).all<{ provider_id: string }>();
  const result: ChatTool[] = [];
  for (const row of rows.results ?? []) {
    if (!MCP_PROVIDERS[row.provider_id]) continue;
    try {
      const { connection, tools } = await allTools(
        env,
        row.provider_id,
        false,
        fetchImpl,
      );
      for (const tool of offered(tools, connection.enabledTools)) {
        if (tool.readOnly)
          result.push({
            providerId: row.provider_id,
            providerLabel: MCP_PROVIDERS[row.provider_id].label,
            tool,
          });
      }
    } catch {
      // 取得できないサービスは今回は見せない（状態は管理画面に出る）
    }
  }
  return result;
}

export async function callTool(
  env: Env,
  userId: string | null,
  providerId: string,
  toolName: string,
  args: Record<string, unknown>,
  options: { readOnlyOnly?: boolean } = {},
  fetchImpl: FetchLike = fetch,
): Promise<McpCallResult & { readOnly: boolean }> {
  const provider = getProvider(providerId);
  const { connection, tools } = await allTools(
    env,
    providerId,
    false,
    fetchImpl,
  );
  const selected = requireAllowed(tools, connection.enabledTools, toolName);
  if (options.readOnlyOnly && !selected.readOnly) {
    throw new McpToolNotAllowed(
      `このツールは書き込みを行う可能性があるため、ここでは実行できません: ${toolName}`,
    );
  }
  try {
    const session = await open(env, connection, provider, fetchImpl);
    const result = await session.callTool(toolName, args);
    await audit(env, {
      providerId,
      userId,
      action: toolName,
      status: result.isError ? "error" : "ok",
      detail: result.isError ? result.text : "",
    });
    return { ...result, readOnly: selected.readOnly };
  } catch (err) {
    await audit(env, {
      providerId,
      userId,
      action: toolName,
      status: "error",
      detail: err instanceof Error ? err.message : String(err),
    });
    throw err;
  }
}
