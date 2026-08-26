import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";

// POST /admin/namespaces/create — namespaceを新規作成する（既存GAS adminCreateNamespace相当）。
// body: { namespaceId, scope: 'shared'|'personal', ownerUserId?（scope='personal'の場合必須） }
export async function handleCreateNamespace(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { namespaceId?: string; scope?: "shared" | "personal"; ownerUserId?: string };
  const namespaceId = (body.namespaceId || "").trim();
  const scope = body.scope;

  if (!namespaceId || (scope !== "shared" && scope !== "personal")) {
    return jsonResponse(400, { error: "namespaceId と scope('shared'|'personal') は必須です" });
  }
  if (scope === "personal" && !body.ownerUserId) {
    return jsonResponse(400, { error: "scope='personal' の場合 ownerUserId は必須です" });
  }

  try {
    await env.DB.prepare("INSERT INTO namespaces (namespace_id, scope, owner_user_id) VALUES (?, ?, ?)")
      .bind(namespaceId, scope, scope === "personal" ? body.ownerUserId : null)
      .run();
  } catch (err) {
    return jsonResponse(409, { error: `作成に失敗しました（既に存在する可能性があります）: ${err instanceof Error ? err.message : String(err)}` });
  }

  return jsonResponse(200, { status: "ok" });
}

// POST /admin/namespaces/list — 既存GAS adminListNamespaces相当。
export async function handleListNamespaces(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const res = await env.DB.prepare("SELECT namespace_id, scope, owner_user_id, result_limit FROM namespaces ORDER BY scope, namespace_id").all();
  return jsonResponse(200, { namespaces: res.results ?? [], status: "ok" });
}

// POST /admin/namespaces/set-limit — namespace（DB）ごとの検索結果採用件数上限を設定する。
// 複数DBを横断検索した際、無関係なDBのチャンクが結果を圧迫するのを防ぐための調整用
// （2026-08-25追加）。resultLimitにnullを渡すと上限を解除できる。
export async function handleSetNamespaceLimit(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { namespaceId?: string; resultLimit?: number | null };
  const namespaceId = (body.namespaceId || "").trim();
  if (!namespaceId) return jsonResponse(400, { error: "namespaceId は必須です" });

  const resultLimit = body.resultLimit === undefined || body.resultLimit === null ? null : body.resultLimit;
  const res = await env.DB.prepare("UPDATE namespaces SET result_limit = ? WHERE namespace_id = ?")
    .bind(resultLimit, namespaceId)
    .run();
  if ((res.meta.changes ?? 0) === 0) {
    return jsonResponse(404, { error: `namespace(${namespaceId})が見つかりません` });
  }
  return jsonResponse(200, { status: "ok" });
}

// POST /admin/namespaces/delete — namespaceの登録を削除する。
// 注意：Vectorize/D1 FTS5に既に投入済みのチャンクは削除しない（この操作の対象外。
// 必要であれば個別にベクトルを削除すること。既存GASにも同等の完全カスケード削除は無い）。
export async function handleDeleteNamespace(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { namespaceId?: string };
  const namespaceId = (body.namespaceId || "").trim();
  if (!namespaceId) return jsonResponse(400, { error: "namespaceId は必須です" });

  await env.DB.batch([
    env.DB.prepare("DELETE FROM kb_sources WHERE namespace_id = ?").bind(namespaceId),
    env.DB.prepare("DELETE FROM key_namespace_grants WHERE namespace_id = ?").bind(namespaceId),
    env.DB.prepare("DELETE FROM namespaces WHERE namespace_id = ?").bind(namespaceId),
  ]);

  return jsonResponse(200, {
    status: "ok",
    warning: "Vectorize/FTS5に投入済みのチャンクは削除していません。必要な場合は別途削除してください。",
  });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
