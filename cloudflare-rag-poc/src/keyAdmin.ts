import type { AuthedUser, Env, UserRole } from "./types";
import { VALID_ROLES } from "./types";
import { requireAdmin } from "./auth";
import { sha256Hex } from "./embeddings";
import { jsonResponse } from "./http";

const DEFAULT_RAG_CAPACITY = 100000;

function generateApiKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

interface CreateKeyResult {
  apiKey: string;
  userId: string;
  displayName: string;
  role: UserRole;
  personalNamespace: string | null;
}

// キー発行の実処理。handleCreateKey（要admin）とhandleBootstrapAdmin（管理者が1人も
// いない場合のみ認証不要で通す、2026-08-27追加）の両方から呼ぶ共通ロジック。
// expiresInDays（2026-09-12追加）: 省略・0・null は無期限。指定するとcreated_atから
// その日数後に自動失効するキーを発行できる（auth.tsのauthenticate()が期限切れを拒否する）。
async function createKeyRecord(
  env: Env,
  opts: { displayName: string; role: UserRole; namespaces?: string[]; ragCapacity?: number; expiresInDays?: number | null },
): Promise<CreateKeyResult> {
  const role = opts.role;
  const apiKey = generateApiKey();
  const newUserId = await sha256Hex(apiKey);
  const now = Math.floor(Date.now() / 1000);
  // handleUpdateKeyExpiryと同じ "> 0" ガード（2026-09-12レビューで発見：ここだけ抜けていた）。
  // UIの固定セレクトボックスからは負数は来ないが、直接APIを叩いた場合に負数を渡すと
  // 発行直後から失効済みのキーができてしまう欠陥があった。
  const expiresAt = opts.expiresInDays && opts.expiresInDays > 0 ? now + opts.expiresInDays * 86400 : null;

  await env.DB.prepare("INSERT INTO users (user_id, display_name, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?)")
    .bind(newUserId, opts.displayName, role, now, expiresAt)
    .run();

  // 個人namespaceを自動作成する（既存の運用パターンに合わせる）。
  // guestロールには付与しない（2026-09-10フィードバック：ゲストは私物領域を持たせる
  // 想定の権限ではないため）。表示名はnamespace_id（ハッシュ値）だけでは「誰の」
  // 個人namespaceか管理画面から判別できなかったため、発行時のdisplayNameをそのまま
  // display_nameに入れておく（migrations/0011）。
  const personalNs = role === "guest" ? null : `personal:${newUserId}`;
  if (personalNs) {
    await env.DB.prepare("INSERT INTO namespaces (namespace_id, scope, owner_user_id, display_name) VALUES (?, 'personal', ?, ?)")
      .bind(personalNs, newUserId, opts.displayName)
      .run();
  }

  // 共有namespaceへのアクセス許可（明示的に指定されたもののみ。指定が無ければ何も見えない。
  // adminロールはauthenticate()側で全shared namespaceが無条件に見えるため実質未使用）
  for (const ns of opts.namespaces ?? []) {
    await env.DB.prepare("INSERT OR IGNORE INTO key_namespace_grants (user_id, namespace_id) VALUES (?, ?)")
      .bind(newUserId, ns)
      .run();
  }

  await env.DB.prepare(
    "INSERT INTO token_budgets (user_id, budget_type, limit_tokens, used_tokens) VALUES (?, 'rag', ?, 0)"
  )
    .bind(newUserId, opts.ragCapacity ?? DEFAULT_RAG_CAPACITY)
    .run();

  return { apiKey, userId: newUserId, displayName: opts.displayName, role, personalNamespace: personalNs };
}

// POST /admin/keys/create — 新規APIキーを発行する（既存GAS adminCreateKey相当）。
// 生のAPIキーはこの応答でしか手に入らない（ハッシュ値しか保存しないため、後から再表示できない）。
// body: { displayName, namespaces?: string[]（許可する共有namespace）, role?: 'admin'|'editor'|'member'|'guest', ragCapacity?: number, expiresInDays?: number（省略/0=無期限） }
export async function handleCreateKey(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);

  const body = (await req.json()) as {
    displayName?: string;
    namespaces?: string[];
    role?: UserRole;
    ragCapacity?: number;
    expiresInDays?: number;
  };
  const displayName = (body.displayName || "").trim();
  if (!displayName) return jsonResponse(400, { error: "displayName は必須です" });

  const result = await createKeyRecord(env, {
    displayName,
    role: body.role ?? "member",
    namespaces: body.namespaces,
    ragCapacity: body.ragCapacity,
    expiresInDays: body.expiresInDays,
  });
  return jsonResponse(200, { status: "ok", ...result });
}

// POST /admin/bootstrap — 管理者キーが1つも存在しない状態から、最初の1つを安全に作る
// （既存GAS bootstrapFirstAdminKey相当、2026-08-27追加）。
// 通常のAdmin APIは「管理者キーを持っている」ことが前提だが、初回セットアップ時点では
// そのキー自体が存在しないという鶏卵問題があった（これまでは手動でD1にINSERTして凌いでいた）。
// この関数だけは index.ts でauthenticate()より前に呼ばれ、Authorizationヘッダー無しで
// 到達できる。安全性は「管理者ロールのユーザーが1人もいない場合にしか成功しない」ことで
// 担保する（GAS版の`hasAdmin`チェックと同じ）。1人でも存在すれば通常のadminCreateKey経由に
// 誘導する。
export async function handleBootstrapAdmin(req: Request, env: Env): Promise<Response> {
  const existingAdmin = await env.DB.prepare("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").first();
  if (existingAdmin) {
    return jsonResponse(403, { error: "管理者キーは既に存在します。追加発行は管理タブ（要既存の管理者キー）から行ってください" });
  }

  const body = (await req.json().catch(() => ({}))) as { displayName?: string; ragCapacity?: number };
  const displayName = (body.displayName || "").trim() || "管理者";

  const result = await createKeyRecord(env, { displayName, role: "admin", ragCapacity: body.ragCapacity });
  return jsonResponse(200, { status: "ok", ...result });
}

// POST /admin/keys/list — 発行済みキーの一覧（生のキーは表示できない。既存GAS adminListKeys相当）。
// last_active（最終利用日時）は2026-09-10追加。AXChat:D管理コンソールのUsersページ
// 参考画像の「Last Login」相当。audit_log側にはClaudeプロキシ利用のログも混ざっている
// ため、その分もそのユーザーの「最後に何かした日時」として扱ってよく、区別していない。
export async function handleListKeys(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);

  const res = await env.DB.prepare(
    `SELECT u.user_id, u.display_name, u.role, u.created_at, u.expires_at,
            tb.limit_tokens AS rag_limit, tb.used_tokens AS rag_used,
            (SELECT MAX(a.created_at) FROM audit_log a WHERE a.user_id = u.user_id) AS last_active
     FROM users u
     LEFT JOIN token_budgets tb ON tb.user_id = u.user_id AND tb.budget_type = 'rag'
     ORDER BY u.created_at DESC`
  ).all();

  return jsonResponse(200, { keys: res.results ?? [], status: "ok" });
}

// POST /admin/keys/delete — キーを削除する（既存GAS adminDeleteKey相当）。関連する個人namespace・
// 予算・メモリ・namespace許可も連鎖的に削除する（FK制約があるため子から先に削除する必要がある）。
//
// 個人namespaceの実データ（Vectorizeベクトル・FTS/グラフ用チャンクインデックス・同期履歴）は、
// namespacesテーブルの行を消すだけでは残ってしまっていた（2026-09-10フィードバック：
// 「発行したものを削除するときに個人ネームスペースも合わせて消すように」）。
// ingest.ts（/ingest）がpersonal:<userId>宛のチャンクをchunks_fts/kb_documentsに記録しつつ
// VEC_PERSONALへ書き込んでいるため、削除も同じ場所を掃除する。
export async function handleDeleteKey(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { userId?: string };
  const userId = (body.userId || "").trim();
  if (!userId) return jsonResponse(400, { error: "userId は必須です" });
  if (userId === user.userId) return jsonResponse(400, { error: "自分自身のキーは削除できません" });

  const personalNs = `personal:${userId}`;
  const chunkRes = await env.DB.prepare("SELECT chunk_id FROM chunks_fts WHERE namespace = ?")
    .bind(personalNs)
    .all<{ chunk_id: string }>();
  const chunkIds = (chunkRes.results ?? []).map((r) => r.chunk_id);
  const DELETE_CHUNK = 20; // getByIds/deleteByIdsの1回あたり上限に合わせた保守的な値（kbRollback.tsと同じ理由）
  for (let i = 0; i < chunkIds.length; i += DELETE_CHUNK) {
    await env.VEC_PERSONAL.deleteByIds(chunkIds.slice(i, i + DELETE_CHUNK));
  }

  await env.DB.batch([
    env.DB.prepare("DELETE FROM chunks_fts WHERE namespace = ?").bind(personalNs),
    env.DB.prepare("DELETE FROM kb_documents WHERE namespace = ?").bind(personalNs),
    env.DB.prepare("DELETE FROM kb_sources WHERE namespace_id = ?").bind(personalNs),
    env.DB.prepare("DELETE FROM kb_log WHERE namespace_id = ?").bind(personalNs),
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

// POST /admin/keys/update-role — 既存キーのロールを変更する（2026-09-10追加）。
// 従来はロールを作成時にしか指定できず、後から変更する手段が無かった
// （'editor'ロール新設に伴い、既存の'member'キーをその場で'editor'へ昇格できるようにする）。
export async function handleUpdateKeyRole(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { userId?: string; role?: UserRole };
  const userId = (body.userId || "").trim();
  const role = body.role;
  if (!userId || !role) return jsonResponse(400, { error: "userId と role は必須です" });
  if (!VALID_ROLES.includes(role)) {
    return jsonResponse(400, { error: `roleは ${VALID_ROLES.join("|")} のいずれかである必要があります` });
  }
  if (userId === user.userId && role !== "admin") {
    return jsonResponse(400, { error: "自分自身の管理者権限は自分では外せません（別の管理者キーから変更してください）" });
  }

  await env.DB.prepare("UPDATE users SET role = ? WHERE user_id = ?").bind(role, userId).run();
  return jsonResponse(200, { status: "ok" });
}

// POST /admin/keys/set-expiry — 既存キーの有効期限を設定・変更・解除する（2026-09-12追加）。
// body: { userId, expiresInDays?: number（0以下またはnull/未指定=無期限に解除） }
// 発行済みキーへの後付け設定（発行時に決め忘れた場合や、契約延長で期限を延ばしたい場合）
// のためにcreateKeyRecordの一回きりの設定とは別に用意している。
export async function handleUpdateKeyExpiry(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { userId?: string; expiresInDays?: number | null };
  const userId = (body.userId || "").trim();
  if (!userId) return jsonResponse(400, { error: "userId は必須です" });

  const expiresAt = body.expiresInDays && body.expiresInDays > 0
    ? Math.floor(Date.now() / 1000) + body.expiresInDays * 86400
    : null;

  await env.DB.prepare("UPDATE users SET expires_at = ? WHERE user_id = ?").bind(expiresAt, userId).run();
  return jsonResponse(200, { status: "ok", expiresAt });
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
