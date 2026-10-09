// MCP連携のHTTPハンドラ（2026-10-08追加）。ここはリクエストの検証と権限判定だけを行い、
// 実際の処理は service.ts の関数を呼ぶだけにする（通信・認可・保存・ポリシーに直接触らない）。
//
// 権限: 接続・解除・ツール選択・「チャットで使う」の切り替え・ツールの試し実行は管理者のみ。
// 接続した人の権限で、このデプロイを使う全員のチャットが動かせてしまうため
// （別プロジェクトの「連携した人の権限で、そのエージェントを使う全員が動かせる」と同じ注意点）。
// 状態の閲覧はナレッジ登録権限者（admin/editor）まで。

import type { AuthedUser, Env } from "../types";
import { authenticateFromQueryKey } from "../oauthConnections";
import { ForbiddenError, requireAdmin, requireKnowledgeEditor } from "../auth";
import { jsonResponse, oauthResultPage } from "../http";
import { McpAuthError, McpError, McpNotConnectedError, McpToolNotAllowed, getProvider, MCP_PROVIDERS } from "./providers";
import * as service from "./service";

// 接続の持ち主を決める（2026-10-09〜）。scope:"user" なら本人専用の接続（ゲスト以外）、
// それ以外はデプロイ全体で共有する接続（管理者のみ）。
function ownerOf(user: AuthedUser, scope: unknown): string {
  if (scope === "user") {
    if (user.role === "guest") throw new ForbiddenError("ゲストは連携を使えません");
    return user.userId;
  }
  requireAdmin(user);
  return "";
}

function friendly(err: unknown): { status: number; message: string } {
  if (err instanceof McpNotConnectedError || err instanceof McpAuthError) return { status: 409, message: err.message };
  if (err instanceof McpToolNotAllowed) return { status: 403, message: err.message };
  if (err instanceof McpError) return { status: 502, message: err.message };
  return { status: 500, message: err instanceof Error ? err.message : String(err) };
}

async function guarded(run: () => Promise<Response>): Promise<Response> {
  try {
    return await run();
  } catch (err) {
    // ForbiddenError（権限不足）は呼び出し元（index.ts）が403に変換するのでそのまま投げ直す
    if (err instanceof Error && err.name === "ForbiddenError") throw err;
    const { status, message } = friendly(err);
    return jsonResponse(status, { error: message });
  }
}

// GET /admin/oauth/mcp/<provider>/start?key=<APIキー> — ブラウザの直接ナビゲーションなので
// Authorizationヘッダーは付けられず、クエリのkeyで認証する（他のOAuth開始と同じ）。
export async function handleMcpOAuthStart(req: Request, env: Env, providerId: string): Promise<Response> {
  const user = await authenticateFromQueryKey(req, env);
  if (!user) return oauthResultPage(false, "認証に失敗しました。管理画面からやり直してください。");
  // ?owner=me なら本人専用の接続（ゲスト以外）、無ければ共有の接続（管理者のみ）。
  let ownerId: string;
  try {
    ownerId = ownerOf(user, new URL(req.url).searchParams.get("owner") === "me" ? "user" : "shared");
  } catch {
    return oauthResultPage(false, "共有のMCP連携の接続は管理者だけが行えます（自分専用の接続は「自分用」から行えます）。");
  }
  if (!MCP_PROVIDERS[providerId]) return oauthResultPage(false, "未対応のMCPサーバーです。");
  try {
    if (MCP_PROVIDERS[providerId].auth === "none") {
      const provider = await service.connectPublic(env, providerId, user.userId, ownerId);
      return oauthResultPage(true, `${provider.label}を有効にしました（認証は不要です）。管理画面でツールを選んでください。`);
    }
    const url = await service.startAuthorization(env, providerId, new URL(req.url).origin, user.userId, fetch, ownerId);
    return Response.redirect(url, 302);
  } catch (err) {
    return oauthResultPage(false, friendly(err).message);
  }
}

// GET /admin/oauth/mcp/callback — 認可サーバーからのリダイレクト。認可はstate（単発・10分）だけで確認する。
export async function handleMcpOAuthCallback(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  const errorParam = url.searchParams.get("error");
  if (errorParam) return oauthResultPage(false, `接続先で認可が拒否またはキャンセルされました（${errorParam}）。`);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!code || !state) return oauthResultPage(false, "パラメータが不足しています（code/state）。");
  try {
    const provider = await service.completeAuthorization(env, state, code);
    return oauthResultPage(true, `${provider.label}と接続しました（公式MCP）。管理画面でツールを選んでください。`);
  } catch (err) {
    return oauthResultPage(false, friendly(err).message);
  }
}

// POST /admin/mcp/status — 全サービスの接続状態（ナレッジ登録権限者まで）
export async function handleMcpStatus(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { scope?: string };
  if (body.scope === "user") {
    if (user.role === "guest") throw new ForbiddenError("ゲストは連携を使えません");
    return jsonResponse(200, { providers: await service.statuses(env, user.userId), status: "ok" });
  }
  requireKnowledgeEditor(user);
  return jsonResponse(200, { providers: await service.statuses(env), status: "ok" });
}

export async function handleMcpDisconnect(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { provider?: string; scope?: string };
  const ownerId = ownerOf(user, body.scope);
  return guarded(async () => {
    await service.disconnect(env, String(body.provider || ""), user.userId, ownerId);
    return jsonResponse(200, { status: "ok" });
  });
}

export async function handleMcpTools(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { provider?: string; refresh?: boolean; scope?: string };
  const ownerId = ownerOf(user, body.scope);
  return guarded(async () => {
    getProvider(String(body.provider || ""));
    return jsonResponse(200, { tools: await service.toolSettings(env, String(body.provider), body.refresh === true, fetch, ownerId), status: "ok" });
  });
}

export async function handleMcpSetTools(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { provider?: string; tools?: unknown; scope?: string };
  const ownerId = ownerOf(user, body.scope);
  if (!Array.isArray(body.tools)) return jsonResponse(400, { error: "tools（ツール名の配列）は必須です" });
  return guarded(async () => {
    await service.setEnabledTools(env, String(body.provider || ""), body.tools as string[], ownerId);
    return jsonResponse(200, { status: "ok" });
  });
}

export async function handleMcpSetChat(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { provider?: string; enabled?: unknown; scope?: string };
  const ownerId = ownerOf(user, body.scope);
  if (typeof body.enabled !== "boolean") return jsonResponse(400, { error: "enabled（真偽値）は必須です" });
  return guarded(async () => {
    await service.setChatEnabled(env, String(body.provider || ""), body.enabled as boolean, ownerId);
    return jsonResponse(200, { status: "ok" });
  });
}

// POST /admin/mcp/call — ツールの試し実行（管理者のみ）。書き込みを行いうるツール（読み取り専用と
// 確認できないもの）は、confirmed:true が無ければ実行しない。確認はブラウザ側でも出すが、
// 強制はここ（サーバー側）で行う。
export async function handleMcpCall(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { provider?: string; tool?: string; arguments?: unknown; confirmed?: boolean; scope?: string };
  const ownerId = ownerOf(user, body.scope);
  const providerId = String(body.provider || "");
  const toolName = String(body.tool || "");
  if (!toolName) return jsonResponse(400, { error: "tool は必須です" });
  const args = body.arguments && typeof body.arguments === "object" && !Array.isArray(body.arguments) ? (body.arguments as Record<string, unknown>) : {};
  return guarded(async () => {
    const settings = await service.toolSettings(env, providerId, false, fetch, ownerId);
    const tool = settings.find((t) => t.name === toolName);
    if (!tool || !tool.enabled) return jsonResponse(403, { error: `使えないツールです: ${toolName}` });
    if (!tool.readOnly && body.confirmed !== true) {
      return jsonResponse(409, { error: "このツールは書き込みを行う可能性があります。確認（confirmed:true）が必要です", needsConfirmation: true });
    }
    const result = await service.callTool(env, user.userId, providerId, toolName, args, { ownerId });
    return jsonResponse(200, { result: { isError: result.isError, text: result.text, readOnly: result.readOnly }, status: "ok" });
  });
}

// POST /me/mcp — チャット画面が「外部サービスも使う」を出すかの判定用（全ユーザー可）。
// 外部へは通信せず、D1の接続状態だけを見る。
export async function handleMyMcp(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const shared = (await service.statuses(env)).filter((p) => p.connected && p.chatEnabled);
  const own = user.role === "guest" ? [] : (await service.statuses(env, user.userId)).filter((p) => p.connected && p.chatEnabled);
  const seen = new Set<string>();
  const providers = [...own, ...shared]
    .filter((p) => (seen.has(p.id) ? false : (seen.add(p.id), true)))
    .map((p) => ({ id: p.id, label: p.label }));
  return jsonResponse(200, { available: providers.length > 0, providers, status: "ok" });
}
