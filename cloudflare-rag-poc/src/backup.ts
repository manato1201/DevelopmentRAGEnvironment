import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";

// POST /admin/backup/export — 設定系テーブルのJSONバックアップ（既存GAS backupCriticalData_ /
// adminBackupNow相当）。D1自体はCloudflare側で自動バックアップ（Point-in-Time Recovery）が
// あるため、実データ（chunks_fts本文・Vectorizeベクトル）まではここでは対象にしない。
// 「APIキー・namespace・KB同期元設定・予算をゼロから作り直す羽目にならないための、
// 軽量な設定スナップショット」という位置づけ。管理タブからJSONファイルとしてダウンロードできる。
export async function handleBackupExport(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);

  const [users, namespaces, kbSources, tokenBudgets, grants] = await Promise.all([
    env.DB.prepare("SELECT user_id, display_name, role, created_at FROM users").all(),
    env.DB.prepare("SELECT namespace_id, scope, owner_user_id, result_limit FROM namespaces").all(),
    env.DB.prepare("SELECT namespace_id, notion_database_id, drive_folder_id FROM kb_sources").all(),
    env.DB.prepare("SELECT user_id, budget_type, limit_tokens, used_tokens, reset_at, reset_interval_hours FROM token_budgets").all(),
    env.DB.prepare("SELECT user_id, namespace_id FROM key_namespace_grants").all(),
  ]);

  return jsonResponse(200, {
    status: "ok",
    exportedAt: Math.floor(Date.now() / 1000),
    note: "APIキーの生値・チャットログ本文・ベクトルデータは含みません（設定の復元用スナップショットです）",
    users: users.results ?? [],
    namespaces: namespaces.results ?? [],
    kbSources: kbSources.results ?? [],
    tokenBudgets: tokenBudgets.results ?? [],
    keyNamespaceGrants: grants.results ?? [],
  });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
