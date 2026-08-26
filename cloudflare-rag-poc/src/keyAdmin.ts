import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { sha256Hex } from "./embeddings";

const DEFAULT_RAG_CAPACITY = 100000;

function generateApiKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// POST /admin/keys/create — 新規APIキーを発行する（既存GAS adminCreateKey相当）。
// 生のAPIキーはこの応答でしか手に入らない（ハッシュ値しか保存しないため、後から再表示できない）。
// body: { displayName, namespaces?: string[]（許可する共有namespace）, role?: 'admin'|'member'|'guest', ragCapacity?: number }
export async function handleCreateKey(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);

  const body = (await req.json()) as {
    displayName?: string;
    namespaces?: string[];
    role?: "admin" | "member" | "guest";
    ragCapacity?: number;
  };
  const displayName = (body.displayName || "").trim();
  if (!displayName) return jsonResponse(400, { error: "displayName は必須です" });

  const role = body.role ?? "member";
  const apiKey = generateApiKey();
  const newUserId = await sha256Hex(apiKey);
  const now = Math.floor(Date.now() / 1000);

  await env.DB.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES (?, ?, ?, ?)")
    .bind(newUserId, displayName, role, now)
    .run();

  // 個人namespaceを自動作成する（既存の運用パターンに合わせる）
  const personalNs = `personal:${newUserId}`;
  await env.DB.prepare("INSERT INTO namespaces (namespace_id, scope, owner_user_id) VALUES (?, 'personal', ?)")
    .bind(personalNs, newUserId)
    .run();

  // 共有namespaceへのアクセス許可（明示的に指定されたもののみ。指定が無ければ何も見えない）
  for (const ns of body.namespaces ?? []) {
    await env.DB.prepare("INSERT OR IGNORE INTO key_namespace_grants (user_id, namespace_id) VALUES (?, ?)")
      .bind(newUserId, ns)
      .run();
  }

  await env.DB.prepare(
    "INSERT INTO token_budgets (user_id, budget_type, limit_tokens, used_tokens) VALUES (?, 'rag', ?, 0)"
  )
    .bind(newUserId, body.ragCapacity ?? DEFAULT_RAG_CAPACITY)
    .run();

  return jsonResponse(200, {
    status: "ok",
    apiKey, // 生のキー。これを渡した相手が二度と見られないことを案内すること
    userId: newUserId,
    displayName,
    role,
    personalNamespace: personalNs,
  });
}

// POST /admin/keys/list — 発行済みキーの一覧（生のキーは表示できない。既存GAS adminListKeys相当）。
export async function handleListKeys(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);

  const res = await env.DB.prepare(
    `SELECT u.user_id, u.display_name, u.role, u.created_at,
            tb.limit_tokens AS rag_limit, tb.used_tokens AS rag_used
     FROM users u
     LEFT JOIN token_budgets tb ON tb.user_id = u.user_id AND tb.budget_type = 'rag'
     ORDER BY u.created_at DESC`
  ).all();

  return jsonResponse(200, { keys: res.results ?? [], status: "ok" });
}

// POST /admin/keys/delete — キーを削除する（既存GAS adminDeleteKey相当）。関連する個人namespace・
// 予算・メモリ・namespace許可も連鎖的に削除する（FK制約があるため子から先に削除する必要がある）。
export async function handleDeleteKey(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { userId?: string };
  const userId = (body.userId || "").trim();
  if (!userId) return jsonResponse(400, { error: "userId は必須です" });
  if (userId === user.userId) return jsonResponse(400, { error: "自分自身のキーは削除できません" });

  await env.DB.batch([
    env.DB.prepare("DELETE FROM memory WHERE user_id = ?").bind(userId),
    env.DB.prepare("DELETE FROM token_budgets WHERE user_id = ?").bind(userId),
    env.DB.prepare("DELETE FROM key_namespace_grants WHERE user_id = ?").bind(userId),
    env.DB.prepare("DELETE FROM namespaces WHERE owner_user_id = ?").bind(userId),
    env.DB.prepare("DELETE FROM users WHERE user_id = ?").bind(userId),
  ]);

  return jsonResponse(200, { status: "ok" });
}

// POST /admin/keys/update-namespaces — キーが見られる共有namespaceを差し替える（既存GAS adminUpdateKey相当）。
export async function handleUpdateKeyNamespaces(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { userId?: string; namespaces?: string[] };
  const userId = (body.userId || "").trim();
  if (!userId) return jsonResponse(400, { error: "userId は必須です" });

  await env.DB.prepare("DELETE FROM key_namespace_grants WHERE user_id = ?").bind(userId).run();
  for (const ns of body.namespaces ?? []) {
    await env.DB.prepare("INSERT OR IGNORE INTO key_namespace_grants (user_id, namespace_id) VALUES (?, ?)")
      .bind(userId, ns)
      .run();
  }

  return jsonResponse(200, { status: "ok" });
}

// POST /admin/keys/set-capacity — トークン予算の上限・自動リセット間隔を設定する
// （既存GAS adminSetKeyCapacity相当）。
export async function handleSetKeyCapacity(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as {
    userId?: string;
    budgetType?: "rag" | "claude";
    limitTokens?: number;
    resetIntervalHours?: number;
  };
  const userId = (body.userId || "").trim();
  const budgetType = body.budgetType ?? "rag";
  if (!userId || typeof body.limitTokens !== "number") {
    return jsonResponse(400, { error: "userId と limitTokens（数値）は必須です" });
  }

  const resetAt = body.resetIntervalHours ? Math.floor(Date.now() / 1000) + body.resetIntervalHours * 3600 : null;

  await env.DB.prepare(
    `INSERT INTO token_budgets (user_id, budget_type, limit_tokens, used_tokens, reset_at, reset_interval_hours)
     VALUES (?, ?, ?, 0, ?, ?)
     ON CONFLICT(user_id, budget_type) DO UPDATE SET
       limit_tokens = excluded.limit_tokens,
       reset_at = excluded.reset_at,
       reset_interval_hours = excluded.reset_interval_hours`
  )
    .bind(userId, budgetType, body.limitTokens, resetAt, body.resetIntervalHours ?? null)
    .run();

  return jsonResponse(200, { status: "ok" });
}

// POST /admin/keys/charge — 残量を即座に補充する（既存GAS adminChargeKeyBalance相当）。
export async function handleChargeKey(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { userId?: string; budgetType?: "rag" | "claude"; amount?: number };
  const userId = (body.userId || "").trim();
  const budgetType = body.budgetType ?? "rag";
  if (!userId || typeof body.amount !== "number") {
    return jsonResponse(400, { error: "userId と amount（数値）は必須です" });
  }

  await env.DB.prepare(
    "UPDATE token_budgets SET used_tokens = MAX(0, used_tokens - ?) WHERE user_id = ? AND budget_type = ?"
  )
    .bind(body.amount, userId, budgetType)
    .run();

  return jsonResponse(200, { status: "ok" });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
