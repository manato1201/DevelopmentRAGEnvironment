import type { AuthedUser, Env, KbSyncResult } from "./types";
import { jsonResponse } from "./http";
import { authorizeSync, cronMayWrite, ownerOfNamespace, previewBody, scopeForRequest } from "./syncTargets";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId, withAbortTimeout } from "./chunking";
import { notifySyncComplete } from "./syncNotify";
import { resolveJiraOAuthContext } from "./jiraOAuth";

// Jira Cloud（Jira Software/Work Management）のプロジェクトをナレッジ登録元にする
// （2026-09-17追加、管理タブ「連携」サブタブ）。Notion/Drive同期と同じ
// バッチ処理＋opId継続方式（Cloudflare Workers FreeプランのCPU時間制限対策、
// driveSync.ts/notionSync.tsのコメント参照）。
const DEFAULT_BATCH_SIZE = 10; // 1課題あたりJira API呼び出しは検索結果に含まれるため実質0回・埋め込みのみのため、Notion/Driveより大きめにしている
const PER_ISSUE_TIMEOUT_MS = 60_000;

// 呼び出し元（handleSyncJira/handleRetryFailedJira）は必ず先にrequireJiraConfig()を呼んで
// から使うが、それに依存せずここでも自衛的に検証する（未設定のまま呼ばれた場合、
// テンプレートリテラルは`undefined`を静かに文字列化してしまい「認証エラー」として
// しか気づけなくなるため。backlogSync.tsのbacklogUrl()と同じ理由、2026-09-19リファクタリング時に修正）。
function jiraHeaders(env: Env): Record<string, string> {
  requireJiraConfig(env);
  const basic = btoa(`${env.JIRA_EMAIL}:${env.JIRA_API_TOKEN}`);
  return { Authorization: `Basic ${basic}`, Accept: "application/json" };
}

function requireJiraConfig(env: Env): void {
  if (!env.JIRA_BASE_URL || !env.JIRA_EMAIL || !env.JIRA_API_TOKEN) {
    throw new Error("Jira連携が未設定です（管理タブの「連携」からOAuthで接続するか、JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKENをsecretで設定してください）");
  }
}

interface JiraAuth {
  baseUrl: string;
  headers: Record<string, string>;
}

// 実際にJira APIを呼ぶ前に、認証方式を解決する（2026-09-22追加、jiraOAuth.ts参照）。
// OAuth接続（管理画面の「接続する」ボタン）があればそれを優先し、無ければ従来の
// JIRA_BASE_URL + Basic認証（メール+APIトークン）にフォールバックする。どちらも
// 無ければ、OAuth接続を促すメッセージ付きでエラーにする。
async function resolveJiraAuth(env: Env, ownerId = ""): Promise<JiraAuth> {
  const oauth = await resolveJiraOAuthContext(env, ownerId);
  if (oauth) return oauth;
  // 本人専用の接続は、共有のBasic認証にフォールバックしない（他人の権限で動かないため）。
  if (ownerId) throw new Error("あなたのJiraが未接続です。「自分用」の連携から接続してください");
  requireJiraConfig(env);
  return { baseUrl: env.JIRA_BASE_URL as string, headers: jiraHeaders(env) };
}

interface JiraIssueSummary {
  key: string;
  title: string; // "KEY: summary" 形式（file名として一意にするため、summaryだけだと同名課題があり得る）
  text: string;
}

// JQLのupdated比較に使う"YYYY-MM-DD HH:mm"形式へ変換する。JiraはこのDATE値をJiraサイトの
// タイムゾーン設定で解釈するため、UTC基準の時刻をそのまま渡すとサイトのタイムゾーンに
// よっては意図した時刻より「後」に解釈され、直近の更新を取りこぼす向きにズレる可能性がある
// （例: サイトがUTC-5なら、こちらが指定した時刻の5時間後を基準に絞り込まれてしまう）。
// そのため呼び出し側（runScheduledJiraSync）でsinceIso自体に安全マージンを引いてから渡す
// 運用にし、ここでは単純な文字列整形だけを行う（2026-09-19）。
function jiraDate(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

// Atlassian Document Format（Jiraのdescriptionのリッチテキスト形式）をプレーンテキストへ
// 再帰的に変換する。GAS版には存在しない要素（Jira Cloud固有のJSON構造）のため新規実装。
interface AdfNode {
  type?: string;
  text?: string;
  content?: AdfNode[];
}
function adfToText(node: AdfNode | null | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.text ?? "";
  const childText = (node.content ?? []).map(adfToText).join("");
  if (node.type === "paragraph" || node.type === "heading" || node.type === "listItem") {
    return childText + "\n";
  }
  return childText;
}

interface ListJiraIssuesOptions {
  // 管理タブで設定した追加のJQL条件（例: "status = Done"）。project=...条件へANDで連結する
  // （2026-09-19追加、「プロジェクト全件ではなく絞り込みたい」への対応）。
  extraJql?: string | null;
  // 指定するとJQLに"AND updated >= '...'"を追加し、それ以降に更新された課題だけを取得する
  // （Cron差分同期用、2026-09-19追加。runScheduledJiraSync参照）。
  sinceIso?: string;
}

// プロジェクト内の課題を取得する（JQLのstartAt/maxResultsによるページング）。
async function listJiraIssues(auth: JiraAuth, projectKey: string, opts: ListJiraIssuesOptions = {}): Promise<JiraIssueSummary[]> {
  const issues: JiraIssueSummary[] = [];
  const pageSize = 100;
  let startAt = 0;
  // projectKeyはURLSearchParamsで正しくエンコードされるため文字列結合でも安全。値自体は
  // kb_sources（/admin/kb/set-source経由、requireKnowledgeEditor必須）由来の信頼済み文字列。
  const clauses = [`project = "${projectKey}"`];
  if (opts.extraJql?.trim()) clauses.push(`(${opts.extraJql.trim()})`);
  if (opts.sinceIso) clauses.push(`updated >= "${jiraDate(opts.sinceIso)}"`);
  const jql = `${clauses.join(" AND ")} ORDER BY created ASC`;

  while (true) {
    const url = new URL(`${auth.baseUrl}/rest/api/3/search`);
    url.searchParams.set("jql", jql);
    url.searchParams.set("startAt", String(startAt));
    url.searchParams.set("maxResults", String(pageSize));
    url.searchParams.set("fields", "summary,description,status,issuetype,updated");

    const res = await fetch(url.toString(), { headers: auth.headers });
    if (!res.ok) throw new Error(`Jira search APIエラー (${res.status}): ${await res.text()}`);
    const data = (await res.json()) as {
      issues: Array<{
        key: string;
        fields: {
          summary: string;
          description: AdfNode | null;
          status?: { name?: string };
          issuetype?: { name?: string };
          updated?: string;
        };
      }>;
      total: number;
    };

    for (const issue of data.issues) {
      const meta = [issue.fields.issuetype?.name, issue.fields.status?.name].filter(Boolean).join(" / ");
      const description = adfToText(issue.fields.description).trim();
      const text = [issue.fields.summary, meta ? `(${meta})` : "", description].filter(Boolean).join("\n\n");
      issues.push({ key: issue.key, title: `${issue.key}: ${issue.fields.summary}`, text });
    }

    startAt += data.issues.length;
    if (data.issues.length === 0 || startAt >= data.total) break;
  }

  return issues;
}

async function processJiraBatch(
  env: Env,
  namespace: string,
  opId: string,
  batch: JiraIssueSummary[],
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
          const result = await ingestDocument(env, namespace, issue.title, issue.text, "jira", signal);
          return { kind: "ok", chunks: result.chunks, skippedVectors: result.skippedVectors.length };
        },
        PER_ISSUE_TIMEOUT_MS,
        `${issue.title}の処理`,
      );
      if (outcome.kind === "skip") {
        skipped.push({ file: issue.title, reason: outcome.reason });
        results.push({ file: issue.title, status: "skipped", detail: outcome.reason });
        await logKb(env, opId, namespace, "jira", issue.title, "skipped", outcome.reason);
        continue;
      }
      chunks += outcome.chunks;
      documents += 1;
      const skipNote = outcome.skippedVectors > 0 ? `（${outcome.skippedVectors}チャンクは登録失敗のためスキップ）` : "";
      const detail = `${outcome.chunks}チャンク登録${skipNote}`;
      results.push({ file: issue.title, status: "ok", detail });
      await logKb(env, opId, namespace, "jira", issue.title, "ok", detail);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: issue.title, reason: detail });
      results.push({ file: issue.title, status: "error", detail });
      await logKb(env, opId, namespace, "jira", issue.title, "error", detail);
    }
  }

  return { documents, chunks, skipped, results };
}

interface JiraSourceConfig {
  projectKey: string;
  extraJql: string | null;
}

async function resolveJiraProject(env: Env, namespace: string): Promise<JiraSourceConfig> {
  const source = await env.DB.prepare("SELECT jira_project_key, jira_extra_jql FROM kb_sources WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ jira_project_key: string | null; jira_extra_jql: string | null }>();
  if (!source?.jira_project_key) {
    throw new Error(`namespace(${namespace})にJiraプロジェクトキーが設定されていません。先に /admin/kb/set-source で設定してください`);
  }
  return { projectKey: source.jira_project_key, extraJql: source.jira_extra_jql };
}

// POST /admin/sync/jira — namespaceに紐づくJiraプロジェクトの課題を一括登録する。
// Notion/Drive同期と同じバッチ処理方式。
// body: { namespace, startIndex?（省略時0）, batchSize?（省略時10）, opId?（継続呼び出し時に指定） }
export async function handleSyncJira(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string; startIndex?: number; batchSize?: number; opId?: string; notifyOnErrorOnly?: boolean };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  const scope = await authorizeSync(env, user, namespace);

  let auth: JiraAuth;
  try {
    auth = await resolveJiraAuth(env, scope.ownerId);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  let jiraConfig: JiraSourceConfig;
  try {
    jiraConfig = await resolveJiraProject(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();

  const issues = await listJiraIssues(auth, jiraConfig.projectKey, { extraJql: jiraConfig.extraJql });
  const batch = issues.slice(startIndex, startIndex + batchSize);

  const { documents, chunks, skipped, results } = await processJiraBatch(env, namespace, opId, batch);

  const nextIndex = startIndex + batchSize < issues.length ? startIndex + batchSize : null;
  if (nextIndex === null) {
    await notifySyncComplete(env, opId, namespace, "jira", body.notifyOnErrorOnly);
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

// POST /admin/sync/jira/retry-failed — 直近の同期（opId）で失敗(error)した課題だけを再実行する
// （Drive/Notion側のhandleRetryFailedDrive/Notionと同じ設計）。
// body: { namespace, opId }
export async function handleRetryFailedJira(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string; opId?: string };
  const namespace = (body.namespace || "").trim();
  const sourceOpId = (body.opId || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  if (!sourceOpId) return jsonResponse(400, { error: "opId は必須です" });
  const scope = await authorizeSync(env, user, namespace);

  let auth: JiraAuth;
  try {
    auth = await resolveJiraAuth(env, scope.ownerId);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  let jiraConfig: JiraSourceConfig;
  try {
    jiraConfig = await resolveJiraProject(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const failedRows = await env.DB.prepare(
    "SELECT DISTINCT file FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'jira' AND status = 'error'",
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

  const allIssues = await listJiraIssues(auth, jiraConfig.projectKey, { extraJql: jiraConfig.extraJql });
  const targets = allIssues.filter((i) => failedTitles.has(i.title));

  const placeholders = targets.map(() => "?").join(",");
  if (targets.length > 0) {
    await env.DB.prepare(
      `DELETE FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'jira' AND status = 'error' AND file IN (${placeholders})`,
    )
      .bind(sourceOpId, namespace, ...targets.map((i) => i.title))
      .run();
  }

  const { documents, chunks, skipped, results } = await processJiraBatch(env, namespace, sourceOpId, targets);

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

// タイムゾーン解釈のズレ（jiraDate参照）を吸収するための安全マージン。実際のずれ幅は
// 最大でも世界のタイムゾーンオフセット範囲（UTC-12〜UTC+14）だが、往復のズレを両側で
// 吸収できるよう余裕を持って24時間としている。多少重複して取得しても、ingestDocument側が
// 同じfile名（"KEY: summary"）を上書きするだけで実害はない（2026-09-19）。
const CRON_SAFETY_MARGIN_MS = 24 * 3600_000;

// Cron Trigger（index.tsのscheduled()）から呼ばれる、Jira連携済み全namespaceの差分同期。
// 1 namespaceの失敗（Jira側の一時的なエラー等）が他のnamespaceの同期を止めないよう、
// namespaceごとにcatchして続行する（2026-09-19追加）。
export async function runScheduledJiraSync(env: Env): Promise<void> {
  // 「毎日自動で同期する」を明示的にオンにしたnamespaceだけが対象（2026-10-09〜、既定はオフ）。
  const rows = await env.DB.prepare(
    "SELECT namespace_id, jira_project_key, jira_extra_jql, jira_last_synced_at FROM kb_sources WHERE jira_project_key IS NOT NULL AND auto_jira = 1",
  ).all<{ namespace_id: string; jira_project_key: string; jira_extra_jql: string | null; jira_last_synced_at: number | null }>();

  for (const row of rows.results ?? []) {
    const runStartedAt = Math.floor(Date.now() / 1000);
    try {
      // namespaceごとに毎回解決し直す（OAuthアクセストークンが途中で期限切れに近づいた
      // 場合、resolveJiraAuth()内で自動更新させるため。cron 1回の実行でnamespace数が
      // 多いと処理時間が延び、最初に解決したトークンが後半で失効する恐れがあるため
      // 使い回さない、2026-09-22）。
      if (!(await cronMayWrite(env, row.namespace_id))) continue; // 許可リスト外の共有namespaceには書かない
      const auth = await resolveJiraAuth(env, ownerOfNamespace(row.namespace_id));
      // 初回（jira_last_synced_atが未設定）は「過去24時間分」だけを対象にする。
      // プロジェクト全件の初回取り込みは、管理タブの手動同期ボタン（handleSyncJira）で
      // 行う想定（Cronは日々の差分キャッチアップ専用、README参照）。
      const sinceMs = row.jira_last_synced_at
        ? row.jira_last_synced_at * 1000 - CRON_SAFETY_MARGIN_MS
        : Date.now() - 86400_000;
      const issues = await listJiraIssues(auth, row.jira_project_key, {
        extraJql: row.jira_extra_jql,
        sinceIso: new Date(sinceMs).toISOString(),
      });
      if (issues.length === 0) {
        await env.DB.prepare("UPDATE kb_sources SET jira_last_synced_at = ? WHERE namespace_id = ?")
          .bind(runStartedAt, row.namespace_id)
          .run();
        continue;
      }
      const opId = newOpId();
      await processJiraBatch(env, row.namespace_id, opId, issues);
      await env.DB.prepare("UPDATE kb_sources SET jira_last_synced_at = ? WHERE namespace_id = ?")
        .bind(runStartedAt, row.namespace_id)
        .run();
      // 日次実行のため、成功続きでの通知疲れを避け「エラーがあった時だけ」通知する
      // （kbSyncNotifyErrorOnlyチェックボックスの既定運用と揃える）。
      await notifySyncComplete(env, opId, row.namespace_id, "jira", true);
    } catch {
      // フェッチ自体が失敗した場合はjira_last_synced_atを更新しない＝次回Cronで同じ範囲から
      // やり直す（取りこぼし防止。個別課題の失敗は上のprocessJiraBatch内でログするだけで
      // ここまで例外は上がってこない）。
    }
  }
}

// POST /admin/jira/list-projects — 接続済みの認証（OAuth・従来方式いずれか）で見える
// プロジェクト一覧を取得する。管理タブの「連携」でプロジェクトキーを手入力する代わりに、
// ドロップダウンから選べるようにするため（2026-09-23追加）。
export async function handleListJiraProjects(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { namespace?: string; mine?: boolean };
  const scope = await scopeForRequest(env, user, body);
  let auth: JiraAuth;
  try {
    auth = await resolveJiraAuth(env, scope.ownerId);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  try {
    const projects: Array<{ key: string; name: string }> = [];
    let startAt = 0;
    while (true) {
      const url = new URL(`${auth.baseUrl}/rest/api/3/project/search`);
      url.searchParams.set("startAt", String(startAt));
      url.searchParams.set("maxResults", "50");
      const res = await fetch(url.toString(), { headers: auth.headers });
      if (!res.ok) return jsonResponse(400, { error: `Jiraプロジェクト一覧取得エラー (${res.status}): ${await res.text()}` });
      const data = (await res.json()) as {
        values: Array<{ key: string; name: string }>;
        isLast: boolean;
      };
      for (const p of data.values) projects.push({ key: p.key, name: p.name });
      if (data.isLast || data.values.length === 0) break;
      startAt += data.values.length;
    }
    return jsonResponse(200, { status: "ok", projects });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}

// POST /admin/kb/test-connection/jira — secretと設定値だけで接続確認する（実際の登録は
// 行わない）。「連携」タブで設定ミスに同期実行前に気づけるようにするため（2026-09-19追加）。
export async function handleTestJiraConnection(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { namespace?: string; mine?: boolean };
  const scope = await scopeForRequest(env, user, body);
  let auth: JiraAuth;
  try {
    auth = await resolveJiraAuth(env, scope.ownerId);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  try {
    const res = await fetch(`${auth.baseUrl}/rest/api/3/myself`, { headers: auth.headers });
    if (!res.ok) return jsonResponse(400, { error: `Jira接続エラー (${res.status}): ${await res.text()}` });
    const me = (await res.json()) as { displayName?: string };
    return jsonResponse(200, { status: "ok", message: `接続成功（${me.displayName ?? "認証済みユーザー"}として認証）` });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}

// POST /admin/sync/jira/preview — 同期するとどの課題が登録されるかの一覧（書き込みはしない）。
// body: { namespace }
export async function handlePreviewJira(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  const scope = await authorizeSync(env, user, namespace);
  try {
    const auth = await resolveJiraAuth(env, scope.ownerId);
    const config = await resolveJiraProject(env, namespace);
    const issues = await listJiraIssues(auth, config.projectKey, { extraJql: config.extraJql });
    return jsonResponse(
      200,
      previewBody(namespace, scope, issues.length, issues.map((i) => ({ title: i.title })), `プロジェクト ${config.projectKey}${config.extraJql ? "（絞り込み条件あり）" : ""}の課題`),
    );
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}
