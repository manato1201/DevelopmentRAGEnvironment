import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { ForbiddenError, requireAdmin, requireKnowledgeEditor } from "./auth";
import { authenticateFromQueryKey } from "./oauthConnections";

// 連携（Jira / Backlog / カレンダー / Drive / Gmail / Notion）の同期先の統制（2026-10-09追加）。
//
// 「いらないデータで知識ベースが汚れる」のを防ぐため、連携の書き込み先を次の2種類に分ける。
//   ・共有namespace … 管理者が許可リスト（sync_allowed_namespaces）に入れたものだけ。接続はデプロイ全体で
//     共有する1つ（owner_id=''）。editorは、自分に許可されたnamespaceに限る。
//   ・個人用namespace（personal:<user_id>）… 本人だけ。接続も本人専用（owner_id=ユーザーID）で、
//     書き込み先は個人用の索引（他人からは検索できない）。許可リストは要らない。
// 許可リストの編集は管理者だけ。

export interface SyncScope {
  // '' = デプロイ全体で共有する接続、それ以外 = その人専用の接続（oauth_connections.owner_id）
  ownerId: string;
}

const PERSONAL_PREFIX = "personal:";

export function isPersonalNamespace(namespace: string): boolean {
  return namespace.startsWith(PERSONAL_PREFIX);
}

// namespace名から接続の持ち主を決める（cronなど、ユーザーが居ない場面で使う）。
export function ownerOfNamespace(namespace: string): string {
  return isPersonalNamespace(namespace) ? namespace.slice(PERSONAL_PREFIX.length) : "";
}

export async function isAllowedTarget(env: Env, namespace: string): Promise<boolean> {
  const row = await env.DB.prepare("SELECT 1 AS ok FROM sync_allowed_namespaces WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ ok: number }>();
  return !!row;
}

// 連携がnamespaceへ同期（または同期元を設定）してよいかを判定し、使う接続の持ち主を返す。
export async function authorizeSync(env: Env, user: AuthedUser, namespace: string): Promise<SyncScope> {
  if (isPersonalNamespace(namespace)) {
    if (user.role === "guest") throw new ForbiddenError("ゲストは連携を使えません");
    if (namespace !== `${PERSONAL_PREFIX}${user.userId}`) {
      throw new ForbiddenError("他のユーザーの個人用namespaceには同期できません");
    }
    return { ownerId: user.userId };
  }
  requireKnowledgeEditor(user);
  if (user.role !== "admin" && !user.allowedNamespaces.includes(namespace)) {
    throw new ForbiddenError(`namespace(${namespace})への書き込み権限がありません`);
  }
  if (!(await isAllowedTarget(env, namespace))) {
    throw new ForbiddenError(
      `namespace(${namespace})は連携の同期先として許可されていません。管理者が「連携の同期先」に追加すると使えます`,
    );
  }
  return { ownerId: "" };
}

// namespaceを指定しない操作（候補の取得など）。mine=trueなら本人専用の接続、そうでなければ共有の接続。
export function scopeFor(user: AuthedUser, mine: boolean | undefined): SyncScope {
  if (mine) {
    if (user.role === "guest") throw new ForbiddenError("ゲストは連携を使えません");
    return { ownerId: user.userId };
  }
  requireKnowledgeEditor(user);
  return { ownerId: "" };
}

// namespaceを持つ操作はauthorizeSync、持たない操作（候補の取得・接続テスト）はmineフラグで接続の持ち主を決める。
export async function scopeForRequest(env: Env, user: AuthedUser, body: { namespace?: string; mine?: boolean }): Promise<SyncScope> {
  const namespace = (body.namespace || "").trim();
  if (namespace) return authorizeSync(env, user, namespace);
  return scopeFor(user, body.mine);
}

// OAuth開始（ブラウザの直接ナビゲーション、?key= で認証）で、接続の持ち主を決める。
//   ?owner=me … 本人専用の接続（ゲスト以外）。 それ以外 … デプロイ全体で共有する接続（ナレッジ登録権限が必要）。
export async function startOwner(
  req: Request,
  env: Env,
): Promise<{ ok: true; ownerId: string } | { ok: false; message: string }> {
  const user = await authenticateFromQueryKey(req, env);
  if (!user) return { ok: false, message: "認証に失敗しました。管理画面からやり直してください。" };
  if (new URL(req.url).searchParams.get("owner") === "me") {
    if (user.role === "guest") return { ok: false, message: "ゲストは連携を使えません。" };
    return { ok: true, ownerId: user.userId };
  }
  try {
    requireKnowledgeEditor(user);
  } catch {
    return { ok: false, message: "共有の接続にはナレッジ登録権限が必要です（自分専用の接続は「自分用」から行えます）。" };
  }
  return { ok: true, ownerId: "" };
}

// 同期前のプレビュー（何が登録されるかの一覧。書き込みは一切しない）の共通の返し方。
export interface PreviewItem {
  title: string;
  detail?: string;
}
const PREVIEW_MAX_ITEMS = 30;
export function previewBody(namespace: string, scope: SyncScope, total: number, items: PreviewItem[], note = "") {
  return {
    status: "ok",
    namespace,
    personal: scope.ownerId !== "",
    total,
    items: items.slice(0, PREVIEW_MAX_ITEMS),
    truncated: total > PREVIEW_MAX_ITEMS,
    note,
  };
}
export const PREVIEW_LIMIT = PREVIEW_MAX_ITEMS;

// cron用: 共有namespaceは許可リストに入っているものだけ。個人用はそのまま。
export async function cronMayWrite(env: Env, namespace: string): Promise<boolean> {
  return isPersonalNamespace(namespace) || (await isAllowedTarget(env, namespace));
}

// ---- 許可リストの管理（POST /admin/sync-targets/*） ----

// 一覧: ナレッジ登録権限者なら見られる（同期先を選ぶ手がかり）。
export async function handleListSyncTargets(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const [allowed, shared] = await Promise.all([
    env.DB.prepare("SELECT namespace_id, created_at FROM sync_allowed_namespaces ORDER BY namespace_id").all<{ namespace_id: string; created_at: number }>(),
    env.DB.prepare("SELECT namespace_id FROM namespaces WHERE scope = 'shared' ORDER BY namespace_id").all<{ namespace_id: string }>(),
  ]);
  const allowedIds = (allowed.results ?? []).map((r) => r.namespace_id);
  return jsonResponse(200, {
    status: "ok",
    allowed: allowed.results ?? [],
    candidates: (shared.results ?? []).map((r) => r.namespace_id).filter((id) => !allowedIds.includes(id)),
  });
}

export async function handleAddSyncTarget(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { namespace?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  if (isPersonalNamespace(namespace)) {
    return jsonResponse(400, { error: "個人用namespaceは許可リストに入れません（本人の接続・本人の索引にだけ同期します）" });
  }
  const ns = await env.DB.prepare("SELECT scope FROM namespaces WHERE namespace_id = ?").bind(namespace).first<{ scope: string }>();
  if (!ns) return jsonResponse(400, { error: `namespace(${namespace})が存在しません` });
  await env.DB.prepare("INSERT OR IGNORE INTO sync_allowed_namespaces (namespace_id, added_by, created_at) VALUES (?, ?, ?)")
    .bind(namespace, user.userId, Math.floor(Date.now() / 1000))
    .run();
  return jsonResponse(200, { status: "ok" });
}

// 許可リストから外す。そのnamespaceの自動同期もすべてオフに戻す（許可が無いまま同期が続かないように）。
export async function handleRemoveSyncTarget(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { namespace?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  await env.DB.prepare("DELETE FROM sync_allowed_namespaces WHERE namespace_id = ?").bind(namespace).run();
  await env.DB.prepare("UPDATE kb_sources SET auto_jira = 0, auto_backlog = 0, auto_calendar = 0 WHERE namespace_id = ?").bind(namespace).run();
  return jsonResponse(200, { status: "ok" });
}
