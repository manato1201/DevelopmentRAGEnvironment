import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { ForbiddenError } from "./auth";

// 検索範囲のプリセット（2026-10-16追加、migrations/0027）。自分の分だけを扱う。
const MAX_PRESETS = 20;
const NAME_MAX = 30;

function requireMember(user: AuthedUser): void {
  if (user.role === "guest") throw new ForbiddenError("ゲストはプリセットを使えません");
}

// POST /me/presets/list
export async function handlePresetList(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  const res = await env.DB.prepare("SELECT name, namespaces_json FROM scope_presets WHERE user_id = ? ORDER BY name").bind(user.userId).all<{ name: string; namespaces_json: string }>();
  const presets = (res.results ?? []).map((r) => {
    let namespaces: string[] = [];
    try {
      const parsed = JSON.parse(r.namespaces_json) as unknown;
      if (Array.isArray(parsed)) namespaces = parsed.map(String);
    } catch {
      namespaces = [];
    }
    // いまアクセスできないnamespaceは、使うときに除く（権限が外れたものを残さない）
    return { name: r.name, namespaces: namespaces.filter((ns) => user.allowedNamespaces.includes(ns)) };
  });
  return jsonResponse(200, { status: "ok", presets });
}

// POST /me/presets/save — body: { name, namespaces: string[] }（同じ名前は上書き）
export async function handlePresetSave(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  const body = (await req.json().catch(() => ({}))) as { name?: string; namespaces?: unknown };
  const name = (body.name || "").trim().slice(0, NAME_MAX);
  const namespaces = Array.isArray(body.namespaces) ? [...new Set((body.namespaces as unknown[]).map(String))] : [];
  if (!name) return jsonResponse(400, { error: "name は必須です" });
  if (namespaces.length === 0) return jsonResponse(400, { error: "namespaces（1つ以上）は必須です" });
  const denied = namespaces.filter((ns) => !user.allowedNamespaces.includes(ns));
  if (denied.length > 0) return jsonResponse(403, { error: `アクセスできないnamespaceが含まれています: ${denied[0]}` });
  const existing = await env.DB.prepare("SELECT COUNT(*) AS c FROM scope_presets WHERE user_id = ?").bind(user.userId).first<{ c: number }>();
  const replacing = await env.DB.prepare("SELECT 1 AS ok FROM scope_presets WHERE user_id = ? AND name = ?").bind(user.userId, name).first();
  if (!replacing && (existing?.c ?? 0) >= MAX_PRESETS) return jsonResponse(400, { error: `プリセットは${MAX_PRESETS}個までです` });
  await env.DB.prepare(
    `INSERT INTO scope_presets (user_id, name, namespaces_json, created_at) VALUES (?, ?, ?, ?)
     ON CONFLICT(user_id, name) DO UPDATE SET namespaces_json = excluded.namespaces_json`,
  )
    .bind(user.userId, name, JSON.stringify(namespaces), Math.floor(Date.now() / 1000))
    .run();
  return jsonResponse(200, { status: "ok" });
}

// POST /me/presets/delete — body: { name }
export async function handlePresetDelete(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireMember(user);
  const body = (await req.json().catch(() => ({}))) as { name?: string };
  const name = (body.name || "").trim();
  if (!name) return jsonResponse(400, { error: "name は必須です" });
  await env.DB.prepare("DELETE FROM scope_presets WHERE user_id = ? AND name = ?").bind(user.userId, name).run();
  return jsonResponse(200, { status: "ok" });
}
