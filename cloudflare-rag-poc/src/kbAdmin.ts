import type { AuthedUser, Env } from "./types";
import { requireKnowledgeEditor } from "./auth";
import { jsonResponse } from "./http";

// POST /admin/kb/set-source — namespaceごとの同期元（Notion DB ID / Drive フォルダID）を設定する
// （既存GAS adminSetNotionDbId/adminSetDriveFolder相当）。
export async function handleSetKbSource(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

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
  requireKnowledgeEditor(user);
  const body = (await req.json().catch(() => ({}))) as { limit?: number; namespace?: string };
  const limit = body.limit ?? 50;

  const sql = body.namespace
    ? "SELECT * FROM kb_log WHERE namespace_id = ? ORDER BY created_at DESC LIMIT ?"
    : "SELECT * FROM kb_log ORDER BY created_at DESC LIMIT ?";
  const stmt = body.namespace ? env.DB.prepare(sql).bind(body.namespace, limit) : env.DB.prepare(sql).bind(limit);

  const res = await stmt.all();
  return jsonResponse(200, { entries: res.results ?? [], status: "ok" });
}

// POST /admin/kb/overview — namespaceごとのナレッジ登録状況を一覧表示する（2026-09-10追加。
// AXChat:D管理コンソールの「Knowledge by Agent」参考画像を元に、ナレッジ登録タブに
// 「どのnamespaceにどれだけ登録済みか」が一目で分かる集計を追加した）。
// chunks_fts（1チャンク=1行、ingest.ts/kbIngest.tsの両方から書き込まれる）から
// ファイル数・チャンク数を、kb_log（status='ok'の最新行）から最終更新日時を、
// kb_sourcesから同期元設定の有無を、それぞれnamespace単位でJS側で結合する
// （3つとも別々のテーブルで、SQL1本のJOINだと集計とNULL処理が煩雑になるため）。
export async function handleKbOverview(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const [countsRes, lastUpdateRes, sourcesRes] = await Promise.all([
    env.DB.prepare(
      "SELECT namespace, COUNT(DISTINCT file) AS fileCount, COUNT(*) AS chunkCount FROM chunks_fts GROUP BY namespace",
    ).all<{ namespace: string; fileCount: number; chunkCount: number }>(),
    env.DB.prepare(
      "SELECT namespace_id, MAX(created_at) AS lastUpdated FROM kb_log WHERE status = 'ok' GROUP BY namespace_id",
    ).all<{ namespace_id: string; lastUpdated: number }>(),
    env.DB.prepare(
      "SELECT namespace_id, notion_database_id, drive_folder_id FROM kb_sources",
    ).all<{ namespace_id: string; notion_database_id: string | null; drive_folder_id: string | null }>(),
  ]);

  const lastUpdateMap = new Map((lastUpdateRes.results ?? []).map((r) => [r.namespace_id, r.lastUpdated]));
  const sourceMap = new Map((sourcesRes.results ?? []).map((r) => [r.namespace_id, r]));

  const namespaces = (countsRes.results ?? []).map((c) => {
    const source = sourceMap.get(c.namespace);
    return {
      namespace: c.namespace,
      fileCount: c.fileCount,
      chunkCount: c.chunkCount,
      lastUpdated: lastUpdateMap.get(c.namespace) ?? null,
      hasNotionSource: !!source?.notion_database_id,
      hasDriveSource: !!source?.drive_folder_id,
    };
  });
  namespaces.sort((a, b) => b.chunkCount - a.chunkCount);

  return jsonResponse(200, { namespaces, status: "ok" });
}
