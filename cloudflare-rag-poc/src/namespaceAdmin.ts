import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { jsonResponse } from "./http";

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
  const res = await env.DB.prepare("SELECT namespace_id, scope, owner_user_id, result_limit, display_name, token_budget FROM namespaces ORDER BY scope, namespace_id").all();
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

// POST /admin/namespaces/set-budget — namespace単位の月間トークン予算しきい値を設定する
// （2026-09-12追加、監視・アラート用途）。監査ログのnamespace_idは1クエリが複数
// namespaceを横断検索した場合カンマ区切りで複数入るため、これは正確な予算「強制」では
// なく、handleNamespaceUsage()の集計に対する警告しきい値として使う。tokenBudgetに
// nullを渡すと解除できる。
export async function handleSetNamespaceBudget(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { namespaceId?: string; tokenBudget?: number | null };
  const namespaceId = (body.namespaceId || "").trim();
  if (!namespaceId) return jsonResponse(400, { error: "namespaceId は必須です" });

  const tokenBudget = body.tokenBudget === undefined || body.tokenBudget === null ? null : body.tokenBudget;
  const res = await env.DB.prepare("UPDATE namespaces SET token_budget = ? WHERE namespace_id = ?")
    .bind(tokenBudget, namespaceId)
    .run();
  if ((res.meta.changes ?? 0) === 0) {
    return jsonResponse(404, { error: `namespace(${namespaceId})が見つかりません` });
  }
  return jsonResponse(200, { status: "ok" });
}

export interface NamespaceUsageEntry {
  namespace: string;
  tokenBudget: number | null;
  used: number;
  overBudget: boolean;
}

// namespace別の推定トークン使用量を、設定した予算しきい値と突き合わせて計算する
// 共有ロジック（2026-09-12追加、healthCheck.tsのnamespace予算超過チェックと
// handleNamespaceUsageの両方が同じ集計を必要としたため切り出した。以前は2箇所に
// ほぼ同一のコードが重複していた）。
// audit_log.namespace_idは横断検索時カンマ区切りで複数namespaceが入るため、
// そのクエリのトークン数を関与した namespace 全部に計上する近似集計になる
// （複数namespaceに同時所属する分は重複計上される）。正確な按分ではなく
// 「このnamespaceがどれくらい負荷に関与しているか」の目安として扱うこと。
export async function computeNamespaceUsage(env: Env, days: number): Promise<NamespaceUsageEntry[]> {
  const sinceTs = Math.floor(Date.now() / 1000) - days * 86400;

  const [rowsRes, nsRes] = await Promise.all([
    env.DB.prepare(
      "SELECT namespace_id, SUM(tokens_used) AS tokens FROM audit_log WHERE created_at >= ? AND namespace_id != 'claude:proxy' GROUP BY namespace_id",
    )
      .bind(sinceTs)
      .all<{ namespace_id: string; tokens: number }>(),
    // 全namespaceを対象にする（token_budget未設定のものも含む）。budget設定済みだけに
    // 絞ると、まだ予算未設定だが実は使用量の多いnamespaceに管理者が気づけず、この画面
    // からその場で予算を設定することもできなくなるため（2026-09-12、実装時に発見）。
    env.DB.prepare("SELECT namespace_id, token_budget FROM namespaces").all<{
      namespace_id: string;
      token_budget: number | null;
    }>(),
  ]);

  const usageMap = new Map<string, number>();
  for (const row of rowsRes.results ?? []) {
    // namespace_idは横断検索時 "shared:a,shared:b" のようにカンマ区切りで入る
    for (const ns of row.namespace_id.split(",")) {
      const trimmed = ns.trim();
      if (!trimmed) continue;
      usageMap.set(trimmed, (usageMap.get(trimmed) ?? 0) + row.tokens);
    }
  }

  const namespaces = (nsRes.results ?? []).map((n) => {
    const used = usageMap.get(n.namespace_id) ?? 0;
    return {
      namespace: n.namespace_id,
      tokenBudget: n.token_budget,
      used,
      overBudget: n.token_budget != null && used > n.token_budget,
    };
  });
  namespaces.sort((a, b) => b.used - a.used);
  return namespaces;
}

// POST /admin/namespaces/usage — computeNamespaceUsage()をUIから叩けるようにする
// エンドポイント（2026-09-12追加）。使用量0かつ予算未設定のnamespace（個人namespaceが
// 増えるほど大半を占めるようになる想定）は情報量が無いため一覧から除外している
// （2026-09-12レビューで発見：全件返すとnamespace数の多い環境で表がノイズだらけになる）。
export async function handleNamespaceUsage(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { days?: number };
  const days = Math.min(Math.max(body.days ?? 30, 1), 90);

  const all = await computeNamespaceUsage(env, days);
  const namespaces = all.filter((n) => n.used > 0 || n.tokenBudget != null);

  return jsonResponse(200, { days, namespaces, status: "ok" });
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
