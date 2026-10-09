import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { ForbiddenError } from "./auth";
import { getConnection, type OAuthService } from "./oauthConnections";

// 「自分用」の連携（ユーザーごとの接続）の状態（2026-10-09追加）。
// 接続はサービスごとに本人専用（oauth_connections.owner_id = ユーザーID）。ここで返すのは本人のものだけ。
// ゲストは使えない。公式MCPの本人専用の接続の状態は /admin/mcp/status（scope: "user"）で返す。
const PER_USER_SERVICES: Array<{
  key: OAuthService;
  label: (extra: Record<string, unknown>) => string;
}> = [
  { key: "jira", label: (e) => String(e.siteName ?? "Jira") },
  { key: "backlog", label: (e) => String(e.spaceUrl ?? "Backlog") },
  { key: "google_calendar", label: () => "Google" },
  { key: "google_drive", label: (e) => String(e.account ?? "Google Drive") },
  { key: "gmail", label: (e) => String(e.account ?? "Gmail") },
];

// POST /me/connections — { personalNamespace, connections: { <service>: { connected, label } } }
export async function handleMyConnections(
  _req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  if (user.role === "guest")
    throw new ForbiddenError("ゲストは連携を使えません");
  const entries = await Promise.all(
    PER_USER_SERVICES.map(async ({ key, label }) => {
      const conn = await getConnection(env, key, user.userId);
      return [
        key,
        conn
          ? { connected: true, label: label(conn.extra) }
          : { connected: false },
      ] as const;
    }),
  );
  const source = await env.DB.prepare(
    "SELECT notion_database_id, drive_folder_id, jira_project_key, backlog_project_id, calendar_id, gmail_query, auto_jira, auto_backlog, auto_calendar FROM kb_sources WHERE namespace_id = ?",
  )
    .bind(`personal:${user.userId}`)
    .first<Record<string, string | number | null>>();
  return jsonResponse(200, {
    status: "ok",
    personalNamespace: `personal:${user.userId}`,
    connections: Object.fromEntries(entries),
    // 自分用namespaceの同期元の設定（画面の入力欄に戻すため）
    source: source ?? {},
  });
}
