import type { AuthedUser, Env } from "./types";
import { requireKnowledgeEditor } from "./auth";
import { authorizeSync } from "./syncTargets";
import { jsonResponse } from "./http";

interface KbSourceRow {
  notion_database_id: string | null;
  drive_folder_id: string | null;
  jira_project_key: string | null;
  backlog_project_id: string | null;
  calendar_id: string | null;
  gmail_query: string | null;
  auto_jira: number;
  auto_backlog: number;
  auto_calendar: number;
  jira_extra_jql: string | null;
  backlog_keyword_filter: string | null;
}

// フィールド1つ分の「今回の値」を決定する: clear指定があればNULL（解除）、値が送られてきて
// いればその値、どちらでもなければ既存値のまま（2026-09-19追加。以前はSQLのCOALESCEで
// 「送られてこなければ既存値を維持」だけを表現していたが、それだと一度設定した値を
// 後から解除する手段が無かった＝実機フィードバックで「Jiraの連携を外したい」に対応できない
// 不備だったため、解除を明示的に扱えるよう書き直した）。
function resolveSourceField(clear: boolean | undefined, incoming: string | undefined, existing: string | null | undefined): string | null {
  if (clear) return null;
  const trimmed = incoming?.trim();
  if (trimmed) return trimmed;
  return existing ?? null;
}

// POST /admin/kb/set-source — namespaceごとの同期元（Notion DB ID / Drive フォルダID /
// Jiraプロジェクトキー / Backlogプロジェクト / GoogleカレンダーID）と、Jira/Backlogの
// 絞り込み条件を設定する（既存GAS adminSetNotionDbId/adminSetDriveFolder相当。
// Jira/Backlog/カレンダーは2026-09-17追加、絞り込み条件とclearXxxによる解除は2026-09-19追加）。
// 各フィールドは「省略＝変更しない」「値を送る＝更新」「clearXxx: true＝解除（NULLに戻す）」
// の3パターンを取れる。
export async function handleSetKbSource(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as {
    namespace?: string;
    notionDatabaseId?: string;
    driveFolderId?: string;
    jiraProjectKey?: string;
    backlogProjectId?: string;
    calendarId?: string;
    gmailQuery?: string;
    jiraExtraJql?: string;
    backlogKeywordFilter?: string;
    clearNotion?: boolean;
    clearDrive?: boolean;
    clearJira?: boolean;
    clearBacklog?: boolean;
    clearCalendar?: boolean;
    clearGmail?: boolean;
    // 毎日の自動同期（明示的にオンにしたものだけ動く。既定はオフ）
    autoJira?: boolean;
    autoBacklog?: boolean;
    autoCalendar?: boolean;
    clearJiraExtraJql?: boolean;
    clearBacklogKeywordFilter?: boolean;
  };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  // 同期元を設定してよいnamespaceか（共有は管理者が許可したものだけ、個人用は本人だけ）
  await authorizeSync(env, user, namespace);

  const ns = await env.DB.prepare("SELECT namespace_id FROM namespaces WHERE namespace_id = ?").bind(namespace).first();
  if (!ns) return jsonResponse(400, { error: `namespace(${namespace})が存在しません。先にnamespacesテーブルへ登録してください` });

  const existing = await env.DB.prepare(
    "SELECT notion_database_id, drive_folder_id, jira_project_key, backlog_project_id, calendar_id, gmail_query, auto_jira, auto_backlog, auto_calendar, jira_extra_jql, backlog_keyword_filter FROM kb_sources WHERE namespace_id = ?",
  )
    .bind(namespace)
    .first<KbSourceRow>();

  const notionDatabaseId = resolveSourceField(body.clearNotion, body.notionDatabaseId, existing?.notion_database_id);
  const driveFolderId = resolveSourceField(body.clearDrive, body.driveFolderId, existing?.drive_folder_id);
  const jiraProjectKey = resolveSourceField(body.clearJira, body.jiraProjectKey, existing?.jira_project_key);
  const backlogProjectId = resolveSourceField(body.clearBacklog, body.backlogProjectId, existing?.backlog_project_id);
  const calendarId = resolveSourceField(body.clearCalendar, body.calendarId, existing?.calendar_id);
  const gmailQuery = resolveSourceField(body.clearGmail, body.gmailQuery, existing?.gmail_query);
  // 自動同期のフラグ: 指定があればそれ、無ければ既存のまま。同期元を解除したら、その自動同期もオフに戻す。
  const flag = (cleared: boolean | undefined, value: boolean | undefined, previous: number | undefined): number =>
    cleared ? 0 : value === undefined ? (previous ?? 0) : value ? 1 : 0;
  const autoJira = flag(body.clearJira, body.autoJira, existing?.auto_jira);
  const autoBacklog = flag(body.clearBacklog, body.autoBacklog, existing?.auto_backlog);
  const autoCalendar = flag(body.clearCalendar, body.autoCalendar, existing?.auto_calendar);
  const jiraExtraJql = resolveSourceField(body.clearJiraExtraJql, body.jiraExtraJql, existing?.jira_extra_jql);
  const backlogKeywordFilter = resolveSourceField(body.clearBacklogKeywordFilter, body.backlogKeywordFilter, existing?.backlog_keyword_filter);

  await env.DB.prepare(
    `INSERT INTO kb_sources
       (namespace_id, notion_database_id, drive_folder_id, jira_project_key, backlog_project_id, calendar_id, gmail_query, auto_jira, auto_backlog, auto_calendar, jira_extra_jql, backlog_keyword_filter)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(namespace_id) DO UPDATE SET
       notion_database_id = excluded.notion_database_id,
       drive_folder_id = excluded.drive_folder_id,
       jira_project_key = excluded.jira_project_key,
       backlog_project_id = excluded.backlog_project_id,
       calendar_id = excluded.calendar_id,
       gmail_query = excluded.gmail_query,
       auto_jira = excluded.auto_jira,
       auto_backlog = excluded.auto_backlog,
       auto_calendar = excluded.auto_calendar,
       jira_extra_jql = excluded.jira_extra_jql,
       backlog_keyword_filter = excluded.backlog_keyword_filter`
  )
    .bind(namespace, notionDatabaseId, driveFolderId, jiraProjectKey, backlogProjectId, calendarId, gmailQuery, autoJira, autoBacklog, autoCalendar, jiraExtraJql, backlogKeywordFilter)
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
// 別プロジェクト管理コンソールの「Knowledge by Agent」参考画像を元に、ナレッジ登録タブに
// 「どのnamespaceにどれだけ登録済みか」が一目で分かる集計を追加した）。
// chunks_fts（1チャンク=1行、ingest.ts/kbIngest.tsの両方から書き込まれる）から
// ファイル数・チャンク数を、kb_log（status='ok'の最新行）から最終更新日時を、
// kb_sourcesから同期元設定の有無を、それぞれnamespace単位でJS側で結合する
// （3つとも別々のテーブルで、SQL1本のJOINだと集計とNULL処理が煩雑になるため）。
// Jira/Backlog/カレンダー（2026-09-17追加）もここに含めないと、「連携」タブで
// 同期元を設定した直後でもこの一覧では「手動登録のみ」のまま表示されてしまう不整合が
// あったため、追加時に合わせて反映する（2026-09-19、リファクタリング時に発見・修正）。
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
      "SELECT namespace_id, notion_database_id, drive_folder_id, jira_project_key, backlog_project_id, calendar_id, gmail_query, auto_jira, auto_backlog, auto_calendar FROM kb_sources",
    ).all<{
      namespace_id: string;
      notion_database_id: string | null;
      drive_folder_id: string | null;
      jira_project_key: string | null;
      backlog_project_id: string | null;
      calendar_id: string | null;
      gmail_query: string | null;
      auto_jira: number;
      auto_backlog: number;
      auto_calendar: number;
    }>(),
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
      hasJiraSource: !!source?.jira_project_key,
      hasBacklogSource: !!source?.backlog_project_id,
      hasCalendarSource: !!source?.calendar_id,
      hasGmailSource: !!source?.gmail_query,
      autoSync: [source?.auto_jira ? "jira" : "", source?.auto_backlog ? "backlog" : "", source?.auto_calendar ? "calendar" : ""].filter(Boolean),
    };
  });
  namespaces.sort((a, b) => b.chunkCount - a.chunkCount);

  return jsonResponse(200, { namespaces, status: "ok" });
}
