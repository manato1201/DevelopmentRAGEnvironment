import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";

// POST /admin/kb/set-source — namespaceごとの同期元（Notion DB ID / Drive フォルダID）を設定する
// （既存GAS adminSetNotionDbId/adminSetDriveFolder相当）。
export async function handleSetKbSource(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);

  const body = (await req.json()) as { namespace?: string; notionDatabaseId?: string; driveFolderId?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  const ns = await env.DB.prepare("SELECT namespace_id FROM namespaces WHERE namespace_id = ?").bind(namespace).first();
  if (!ns) return jsonResponse(400, { error: `namespace(${namespace})が存在しません。先にnamespacesテーブルへ登録してください` });

  await env.DB.prepare(
    `INSERT INTO kb_sources (namespace_id, notion_database_id, drive_folder_id) VALUES (?, ?, ?)
     ON CONFLICT(namespace_id) DO UPDATE SET
       notion_database_id = COALESCE(excluded.notion_database_id, kb_sources.notion_database_id),
       drive_folder_id = COALESCE(excluded.drive_folder_id, kb_sources.drive_folder_id)`
  )
    .bind(namespace, body.notionDatabaseId ?? null, body.driveFolderId ?? null)
    .run();

  return jsonResponse(200, { status: "ok" });
}

// POST /admin/kb/history — 直近の同期・登録履歴を確認する（既存GAS adminKbHistory相当）。
export async function handleKbHistory(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { limit?: number; namespace?: string };
  const limit = body.limit ?? 50;

  const sql = body.namespace
    ? "SELECT * FROM kb_log WHERE namespace_id = ? ORDER BY created_at DESC LIMIT ?"
    : "SELECT * FROM kb_log ORDER BY created_at DESC LIMIT ?";
  const stmt = body.namespace ? env.DB.prepare(sql).bind(body.namespace, limit) : env.DB.prepare(sql).bind(limit);

  const res = await stmt.all();
  return jsonResponse(200, { entries: res.results ?? [], status: "ok" });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
