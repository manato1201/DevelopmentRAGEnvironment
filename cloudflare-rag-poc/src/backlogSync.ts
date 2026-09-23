import type { AuthedUser, Env, KbSyncResult } from "./types";
import { jsonResponse } from "./http";
import { requireKnowledgeEditor } from "./auth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId, withAbortTimeout } from "./chunking";
import { notifySyncComplete } from "./syncNotify";
import { resolveBacklogOAuthContext } from "./backlogOAuth";

// Backlog（Nulab）のプロジェクトをナレッジ登録元にする（2026-09-17追加、管理タブ「連携」
// サブタブ）。Notion/Drive/Jira同期と同じバッチ処理＋opId継続方式。
// BacklogのdescriptionはJiraと違いプレーンテキスト/Markdownなので、Jiraのような
// ADF変換は不要（Backlog固有の複雑さはプロジェクトキー→数値IDの解決のみ）。
const DEFAULT_BATCH_SIZE = 10;
const PER_ISSUE_TIMEOUT_MS = 60_000;
const BACKLOG_PAGE_SIZE = 100; // Backlog API の count 上限

function requireBacklogConfig(env: Env): void {
  if (!env.BACKLOG_SPACE_URL || !env.BACKLOG_API_KEY) {
    throw new Error("Backlog連携が未設定です（管理タブの「連携」からOAuthで接続するか、BACKLOG_SPACE_URL/BACKLOG_API_KEYをsecretで設定してください）");
  }
}

interface BacklogAuth {
  spaceUrl: string;
  headers: Record<string, string>;
  apiKey: string | null; // legacy方式のみ設定。URLへ?apiKey=として付与する（OAuth方式ではnull）
}

// 実際にBacklog APIを呼ぶ前に、認証方式を解決する（2026-09-22追加、backlogOAuth.ts参照）。
// OAuth接続（管理画面の「接続する」ボタン）があればそれを優先し、無ければ従来の
// BACKLOG_SPACE_URL + ?apiKey=方式にフォールバックする。
async function resolveBacklogAuth(env: Env): Promise<BacklogAuth> {
  const oauth = await resolveBacklogOAuthContext(env);
  if (oauth) return { spaceUrl: oauth.spaceUrl, headers: oauth.headers, apiKey: null };
  requireBacklogConfig(env);
  return { spaceUrl: env.BACKLOG_SPACE_URL as string, headers: {}, apiKey: env.BACKLOG_API_KEY as string };
}

function backlogUrl(auth: BacklogAuth, path: string): URL {
  const url = new URL(`${auth.spaceUrl}/api/v2${path}`);
  if (auth.apiKey) url.searchParams.set("apiKey", auth.apiKey);
  return url;
}

interface BacklogIssueSummary {
  key: string;
  title: string;
  text: string;
}

// kb_sourcesにはプロジェクトキー（人間が読める識別子、例: "MFP"）を保存させるが、
// Backlogのissues一覧APIはprojectId[]に数値の内部IDを要求するため、同期のたびに
// 一度だけ解決する（プロジェクト自体のGETはキー・ID両方を受け付ける）。
async function resolveBacklogProjectId(auth: BacklogAuth, projectIdOrKey: string): Promise<number> {
  const res = await fetch(backlogUrl(auth, `/projects/${encodeURIComponent(projectIdOrKey)}`).toString(), {
    headers: auth.headers,
  });
  if (!res.ok) throw new Error(`Backlogプロジェクト取得エラー (${res.status}): ${await res.text()}`);
  const data = (await res.json()) as { id: number };
  return data.id;
}

interface ListBacklogIssuesOptions {
  // 管理タブで設定したBacklog issues APIのkeywordパラメータ（要約・説明の部分一致検索）。
  // 2026-09-19追加、「プロジェクト全件ではなく絞り込みたい」への対応。
  keyword?: string | null;
  // 指定すると更新日時の新しい順に取得し、この時刻以前の課題が現れた時点でページングを
  // 打ち切る（Cron差分同期用、2026-09-19追加。Backlogのissues APIには直接の
  // 「updatedSince」パラメータが無いため、ソート順＋早期終了で代替する）。
  sinceUpdatedAtMs?: number;
}

async function listBacklogIssues(auth: BacklogAuth, projectId: number, opts: ListBacklogIssuesOptions = {}): Promise<BacklogIssueSummary[]> {
  const issues: BacklogIssueSummary[] = [];
  let offset = 0;
  const incremental = opts.sinceUpdatedAtMs !== undefined;

  while (true) {
    const url = backlogUrl(auth, "/issues");
    url.searchParams.set("projectId[]", String(projectId));
    url.searchParams.set("count", String(BACKLOG_PAGE_SIZE));
    url.searchParams.set("offset", String(offset));
    // 差分同期時は更新日時の新しい順（早期終了できるようにするため）、通常の全件同期時は
    // 従来通り作成日時の古い順（一覧の並びを変えないため）。
    url.searchParams.set("sort", incremental ? "updated" : "created");
    url.searchParams.set("order", incremental ? "desc" : "asc");
    if (opts.keyword?.trim()) url.searchParams.set("keyword", opts.keyword.trim());

    const res = await fetch(url.toString(), { headers: auth.headers });
    if (!res.ok) throw new Error(`Backlog issues APIエラー (${res.status}): ${await res.text()}`);
    const data = (await res.json()) as Array<{
      issueKey: string;
      summary: string;
      description: string | null;
      status?: { name?: string };
      issueType?: { name?: string };
      updated: string;
    }>;

    let reachedCutoff = false;
    for (const issue of data) {
      if (incremental && new Date(issue.updated).getTime() <= opts.sinceUpdatedAtMs!) {
        reachedCutoff = true;
        break; // 新しい順に並んでいるため、これ以降は全て対象外
      }
      const meta = [issue.issueType?.name, issue.status?.name].filter(Boolean).join(" / ");
      const text = [issue.summary, meta ? `(${meta})` : "", issue.description ?? ""].filter(Boolean).join("\n\n");
      issues.push({ key: issue.issueKey, title: `${issue.issueKey}: ${issue.summary}`, text });
    }

    offset += data.length;
    if (reachedCutoff || data.length < BACKLOG_PAGE_SIZE) break; // 返却件数がページサイズ未満＝最終ページ
  }

  return issues;
}

async function processBacklogBatch(
  env: Env,
  namespace: string,
  opId: string,
  batch: BacklogIssueSummary[],
): Promise<{
  documents: number;
  chunks: number;
  skipped: Array<{ file: string; reason: string }>;
  results: Array<{ file: string; status: "ok" | "skipped" | "error"; detail: string }>;
}> {
  let documents = 0;
  let chunks = 0;
  const skipped: Array<{ file: string; reason: string }> = [];
  const results: Array<{ file: string; status: "ok" | "skipped" | "error"; detail: string }> = [];

  for (const issue of batch) {
    try {
      const outcome = await withAbortTimeout(
        async (signal): Promise<
          | { kind: "skip"; reason: string }
          | { kind: "ok"; chunks: number; skippedVectors: number }
        > => {
          if (!issue.text.trim()) return { kind: "skip", reason: "本文が空です" };
          const result = await ingestDocument(env, namespace, issue.title, issue.text, "backlog", signal);
          return { kind: "ok", chunks: result.chunks, skippedVectors: result.skippedVectors.length };
        },
        PER_ISSUE_TIMEOUT_MS,
        `${issue.title}の処理`,
      );
      if (outcome.kind === "skip") {
        skipped.push({ file: issue.title, reason: outcome.reason });
        results.push({ file: issue.title, status: "skipped", detail: outcome.reason });
        await logKb(env, opId, namespace, "backlog", issue.title, "skipped", outcome.reason);
        continue;
      }
      chunks += outcome.chunks;
      documents += 1;
      const skipNote = outcome.skippedVectors > 0 ? `（${outcome.skippedVectors}チャンクは登録失敗のためスキップ）` : "";
      const detail = `${outcome.chunks}チャンク登録${skipNote}`;
      results.push({ file: issue.title, status: "ok", detail });
      await logKb(env, opId, namespace, "backlog", issue.title, "ok", detail);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: issue.title, reason: detail });
      results.push({ file: issue.title, status: "error", detail });
      await logKb(env, opId, namespace, "backlog", issue.title, "error", detail);
    }
  }

  return { documents, chunks, skipped, results };
}

interface BacklogSourceConfig {
  projectIdOrKey: string;
  keyword: string | null;
}

async function resolveBacklogProjectKey(env: Env, namespace: string): Promise<BacklogSourceConfig> {
  const source = await env.DB.prepare("SELECT backlog_project_id, backlog_keyword_filter FROM kb_sources WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ backlog_project_id: string | null; backlog_keyword_filter: string | null }>();
  if (!source?.backlog_project_id) {
    throw new Error(`namespace(${namespace})にBacklogプロジェクトが設定されていません。先に /admin/kb/set-source で設定してください`);
  }
  return { projectIdOrKey: source.backlog_project_id, keyword: source.backlog_keyword_filter };
}

// POST /admin/sync/backlog — namespaceに紐づくBacklogプロジェクトの課題を一括登録する。
// body: { namespace, startIndex?（省略時0）, batchSize?（省略時10）, opId?（継続呼び出し時に指定） }
export async function handleSyncBacklog(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const body = (await req.json()) as { namespace?: string; startIndex?: number; batchSize?: number; opId?: string; notifyOnErrorOnly?: boolean };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  let auth: BacklogAuth;
  try {
    auth = await resolveBacklogAuth(env);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  let backlogConfig: BacklogSourceConfig;
  try {
    backlogConfig = await resolveBacklogProjectKey(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();

  let issues: BacklogIssueSummary[];
  try {
    const projectId = await resolveBacklogProjectId(auth, backlogConfig.projectIdOrKey);
    issues = await listBacklogIssues(auth, projectId, { keyword: backlogConfig.keyword });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  const batch = issues.slice(startIndex, startIndex + batchSize);

  const { documents, chunks, skipped, results } = await processBacklogBatch(env, namespace, opId, batch);

  const nextIndex = startIndex + batchSize < issues.length ? startIndex + batchSize : null;
  if (nextIndex === null) {
    await notifySyncComplete(env, opId, namespace, "backlog", body.notifyOnErrorOnly);
  }

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    results,
    totalIssues: issues.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  } satisfies KbSyncResult & { totalIssues: number; processedRange: [number, number]; nextIndex: number | null });
}

// POST /admin/sync/backlog/retry-failed — 直近の同期（opId）で失敗(error)した課題だけを再実行する。
// body: { namespace, opId }
export async function handleRetryFailedBacklog(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const body = (await req.json()) as { namespace?: string; opId?: string };
  const namespace = (body.namespace || "").trim();
  const sourceOpId = (body.opId || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  if (!sourceOpId) return jsonResponse(400, { error: "opId は必須です" });

  let auth: BacklogAuth;
  try {
    auth = await resolveBacklogAuth(env);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  let backlogConfig: BacklogSourceConfig;
  try {
    backlogConfig = await resolveBacklogProjectKey(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const failedRows = await env.DB.prepare(
    "SELECT DISTINCT file FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'backlog' AND status = 'error'",
  )
    .bind(sourceOpId, namespace)
    .all<{ file: string }>();
  const failedTitles = new Set(failedRows.results.map((r) => r.file));
  if (failedTitles.size === 0) {
    return jsonResponse(200, {
      status: "ok",
      opId: sourceOpId,
      documents: 0,
      chunks: 0,
      skipped: [],
      results: [],
      totalIssues: 0,
      processedRange: [0, 0],
      nextIndex: null,
    } satisfies KbSyncResult & { totalIssues: number; processedRange: [number, number]; nextIndex: number | null });
  }

  let allIssues: BacklogIssueSummary[];
  try {
    const projectId = await resolveBacklogProjectId(auth, backlogConfig.projectIdOrKey);
    allIssues = await listBacklogIssues(auth, projectId, { keyword: backlogConfig.keyword });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  const targets = allIssues.filter((i) => failedTitles.has(i.title));

  const placeholders = targets.map(() => "?").join(",");
  if (targets.length > 0) {
    await env.DB.prepare(
      `DELETE FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'backlog' AND status = 'error' AND file IN (${placeholders})`,
    )
      .bind(sourceOpId, namespace, ...targets.map((i) => i.title))
      .run();
  }

  const { documents, chunks, skipped, results } = await processBacklogBatch(env, namespace, sourceOpId, targets);

  return jsonResponse(200, {
    status: "ok",
    opId: sourceOpId,
    documents,
    chunks,
    skipped,
    results,
    totalIssues: targets.length,
    processedRange: [0, targets.length],
    nextIndex: null,
  } satisfies KbSyncResult & { totalIssues: number; processedRange: [number, number]; nextIndex: number | null });
}

// Cron Trigger（index.tsのscheduled()）から呼ばれる、Backlog連携済み全namespaceの差分同期。
// Jira側のrunScheduledJiraSyncと同じ設計・同じ理由（2026-09-19追加）。
export async function runScheduledBacklogSync(env: Env): Promise<void> {
  try {
    await resolveBacklogAuth(env); // OAuth未接続かつ従来のsecretも未設定なら、ここで例外になる
  } catch {
    return; // 何も設定されていない環境では何もしない
  }

  const rows = await env.DB.prepare(
    "SELECT namespace_id, backlog_project_id, backlog_keyword_filter, backlog_last_synced_at FROM kb_sources WHERE backlog_project_id IS NOT NULL",
  ).all<{ namespace_id: string; backlog_project_id: string; backlog_keyword_filter: string | null; backlog_last_synced_at: number | null }>();

  for (const row of rows.results ?? []) {
    const runStartedAtMs = Date.now();
    try {
      // namespaceごとに解決し直す（Jira側のrunScheduledJiraSyncと同じ理由。トークンの
      // 途中失効を避ける、2026-09-22）。
      const auth = await resolveBacklogAuth(env);
      // 初回（backlog_last_synced_atが未設定）は「過去24時間分」だけを対象にする
      // （jiraSync.tsのrunScheduledJiraSyncと同じ方針。全件の初回取り込みは手動同期で行う）。
      const sinceUpdatedAtMs = row.backlog_last_synced_at ? row.backlog_last_synced_at * 1000 : runStartedAtMs - 86400_000;
      const projectId = await resolveBacklogProjectId(auth, row.backlog_project_id);
      const issues = await listBacklogIssues(auth, projectId, { keyword: row.backlog_keyword_filter, sinceUpdatedAtMs });
      if (issues.length === 0) {
        await env.DB.prepare("UPDATE kb_sources SET backlog_last_synced_at = ? WHERE namespace_id = ?")
          .bind(Math.floor(runStartedAtMs / 1000), row.namespace_id)
          .run();
        continue;
      }
      const opId = newOpId();
      await processBacklogBatch(env, row.namespace_id, opId, issues);
      await env.DB.prepare("UPDATE kb_sources SET backlog_last_synced_at = ? WHERE namespace_id = ?")
        .bind(Math.floor(runStartedAtMs / 1000), row.namespace_id)
        .run();
      await notifySyncComplete(env, opId, row.namespace_id, "backlog", true);
    } catch {
      // フェッチ自体が失敗した場合はbacklog_last_synced_atを更新しない＝次回Cronで同じ範囲から
      // やり直す（Jira側と同じ理由。取りこぼし防止）。
    }
  }
}

// POST /admin/backlog/list-projects — 接続済みの認証（OAuth・従来方式いずれか）で見える
// プロジェクト一覧を取得する（2026-09-23追加、jiraSync.tsのhandleListJiraProjectsと同じ狙い）。
export async function handleListBacklogProjects(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  let auth: BacklogAuth;
  try {
    auth = await resolveBacklogAuth(env);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  try {
    const res = await fetch(backlogUrl(auth, "/projects").toString(), { headers: auth.headers });
    if (!res.ok) return jsonResponse(400, { error: `Backlogプロジェクト一覧取得エラー (${res.status}): ${await res.text()}` });
    const data = (await res.json()) as Array<{ projectKey: string; name: string }>;
    return jsonResponse(200, { status: "ok", projects: data.map((p) => ({ key: p.projectKey, name: p.name })) });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}

// POST /admin/kb/test-connection/backlog — secretと設定値だけで接続確認する
// （実際の登録は行わない）。「連携」タブで設定ミスに同期実行前に気づけるようにするため
// （2026-09-19追加）。
export async function handleTestBacklogConnection(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  let auth: BacklogAuth;
  try {
    auth = await resolveBacklogAuth(env);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  try {
    const res = await fetch(backlogUrl(auth, "/space").toString(), { headers: auth.headers });
    if (!res.ok) return jsonResponse(400, { error: `Backlog接続エラー (${res.status}): ${await res.text()}` });
    const space = (await res.json()) as { name?: string };
    return jsonResponse(200, { status: "ok", message: `接続成功（スペース「${space.name ?? "?"}」に認証済み）` });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}
