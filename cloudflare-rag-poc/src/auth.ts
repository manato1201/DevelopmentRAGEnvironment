import type { AuthedUser, Env } from "./types";
import { sha256Hex } from "./embeddings";

// リクエストの Authorization: Bearer <APIキー> を検証し、D1のusersテーブルと突き合わせる。
// APIキーそのものはD1に保存せず、ハッシュ値のみを保存・比較する（既存GAS実装の方針を踏襲）。
export async function authenticate(
  req: Request,
  env: Env,
): Promise<AuthedUser | null> {
  const authHeader = req.headers.get("authorization") || "";
  const match = authHeader.match(/^Bearer\s+(.+)$/i);
  if (!match) return null;

  const apiKey = match[1].trim();
  if (!apiKey) return null;

  const userId = await sha256Hex(apiKey);

  const userRow = await env.DB.prepare(
    "SELECT user_id, role FROM users WHERE user_id = ?",
  )
    .bind(userId)
    .first<{ user_id: string; role: "admin" | "member" | "guest" }>();

  if (!userRow) return null;

  // このユーザーがアクセスできるnamespace = 全shared + 自分がowner_user_idの個人namespace
  const nsRows = await env.DB.prepare(
    "SELECT namespace_id FROM namespaces WHERE scope = 'shared' OR owner_user_id = ?",
  )
    .bind(userId)
    .all<{ namespace_id: string }>();

  return {
    userId,
    role: userRow.role,
    allowedNamespaces: (nsRows.results ?? []).map((r) => r.namespace_id),
  };
}

// docs/cloud-local-unification-plan.md §6-1（物理分離）の実装上の要点：
// 「アクセス制御を通過しない限り、そもそも個人用Vectorizeインデックスに到達できない」
// を関数の型レベルでも表現する — 呼び出し側は必ずこの関数の戻り値（許可済みnamespace一覧）
// を経由してからVEC_PERSONALへ問い合わせること。
export function splitNamespacesByScope(namespaces: string[]): {
  shared: string[];
  personal: string[];
} {
  const shared: string[] = [];
  const personal: string[] = [];
  for (const ns of namespaces) {
    if (ns.startsWith("personal:")) personal.push(ns);
    else shared.push(ns);
  }
  return { shared, personal };
}
