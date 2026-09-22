import type { AuthedUser, Env, KbSyncResult } from "./types";
import { jsonResponse } from "./http";
import { requireKnowledgeEditor } from "./auth";
import { getGoogleAccessToken, requireGoogleServiceAccountConfig } from "./googleAuth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId, withAbortTimeout } from "./chunking";
import { notifySyncComplete } from "./syncNotify";

// Googleカレンダーの予定をナレッジ登録元にする（2026-09-17追加、管理タブ「連携」
// サブタブ）。Drive同期と同じサービスアカウント方式（GOOGLE_SERVICE_ACCOUNT_JSON流用、
// 新規secret不要）で、対象カレンダーをサービスアカウントのメールアドレスに「閲覧者」
// 共有しておく運用を想定する（Driveフォルダ共有と同じ考え方。Domain-Wide Delegationの
// 設定は不要）。
//
// Drive/Notionと違い「全件」という概念がない（定期的な予定は将来にわたって際限なく続く）
// ため、時間窓（過去N日〜未来M日）を区切って対象にする。既定はJST基準で運用中の
// チームの実利用パターンを想定した保守的な値（過去7日・未来90日）。
const CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly";
const DEFAULT_BATCH_SIZE = 10;
const PER_EVENT_TIMEOUT_MS = 60_000;
const DEFAULT_TIME_MIN_DAYS = 7;
const DEFAULT_TIME_MAX_DAYS = 90;

interface CalendarEventSummary {
  id: string;
  title: string; // "予定名 (開始日時)" 形式。同名の繰り返し予定を日時で区別するため
  text: string;
}

function formatEventTime(dt: { date?: string; dateTime?: string } | undefined): string {
  if (!dt) return "";
  return dt.dateTime ?? dt.date ?? "";
}

async function listCalendarEvents(
  token: string,
  calendarId: string,
  timeMinDays: number,
  timeMaxDays: number,
): Promise<CalendarEventSummary[]> {
  const events: CalendarEventSummary[] = [];
  const now = Date.now();
  const timeMin = new Date(now - timeMinDays * 86400_000).toISOString();
  const timeMax = new Date(now + timeMaxDays * 86400_000).toISOString();
  let pageToken: string | undefined;

  do {
    const url = new URL(`https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(calendarId)}/events`);
    url.searchParams.set("singleEvents", "true"); // 繰り返し予定を個別インスタンスへ展開（recurring eventのマスタだけだと日時が分からないため）
    url.searchParams.set("orderBy", "startTime");
    url.searchParams.set("timeMin", timeMin);
    url.searchParams.set("timeMax", timeMax);
    url.searchParams.set("maxResults", "250");
    if (pageToken) url.searchParams.set("pageToken", pageToken);

    const res = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`Calendar events APIエラー (${res.status}): ${await res.text()}`);
    const data = (await res.json()) as {
      items: Array<{
        id: string;
        summary?: string;
        description?: string;
        location?: string;
        start?: { date?: string; dateTime?: string };
        end?: { date?: string; dateTime?: string };
        status?: string;
      }>;
      nextPageToken?: string;
    };

    for (const ev of data.items) {
      if (ev.status === "cancelled") continue; // キャンセル済みの予定はナレッジとして無意味なので除外
      const summary = ev.summary || "(タイトルなし)";
      const start = formatEventTime(ev.start);
      const text = [
        summary,
        start ? `開始: ${start}` : "",
        ev.location ? `場所: ${ev.location}` : "",
        ev.description ?? "",
      ]
        .filter(Boolean)
        .join("\n\n");
      events.push({ id: ev.id, title: start ? `${summary} (${start})` : summary, text });
    }
    pageToken = data.nextPageToken;
  } while (pageToken);

  return events;
}

async function processCalendarBatch(
  env: Env,
  namespace: string,
  opId: string,
  batch: CalendarEventSummary[],
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

  for (const event of batch) {
    try {
      const outcome = await withAbortTimeout(
        async (signal): Promise<
          | { kind: "skip"; reason: string }
          | { kind: "ok"; chunks: number; skippedVectors: number }
        > => {
          if (!event.text.trim()) return { kind: "skip", reason: "本文が空です" };
          const result = await ingestDocument(env, namespace, event.title, event.text, "google_calendar", signal);
          return { kind: "ok", chunks: result.chunks, skippedVectors: result.skippedVectors.length };
        },
        PER_EVENT_TIMEOUT_MS,
        `${event.title}の処理`,
      );
      if (outcome.kind === "skip") {
        skipped.push({ file: event.title, reason: outcome.reason });
        results.push({ file: event.title, status: "skipped", detail: outcome.reason });
        await logKb(env, opId, namespace, "google_calendar", event.title, "skipped", outcome.reason);
        continue;
      }
      chunks += outcome.chunks;
      documents += 1;
      const skipNote = outcome.skippedVectors > 0 ? `（${outcome.skippedVectors}チャンクは登録失敗のためスキップ）` : "";
      const detail = `${outcome.chunks}チャンク登録${skipNote}`;
      results.push({ file: event.title, status: "ok", detail });
      await logKb(env, opId, namespace, "google_calendar", event.title, "ok", detail);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: event.title, reason: detail });
      results.push({ file: event.title, status: "error", detail });
      await logKb(env, opId, namespace, "google_calendar", event.title, "error", detail);
    }
  }

  return { documents, chunks, skipped, results };
}

async function resolveCalendarId(env: Env, namespace: string): Promise<string> {
  const source = await env.DB.prepare("SELECT calendar_id FROM kb_sources WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ calendar_id: string | null }>();
  if (!source?.calendar_id) {
    throw new Error(`namespace(${namespace})にGoogleカレンダーIDが設定されていません。先に /admin/kb/set-source で設定してください`);
  }
  return source.calendar_id;
}

// POST /admin/sync/calendar — namespaceに紐づくGoogleカレンダーの予定を一括登録する。
// body: { namespace, startIndex?（省略時0）, batchSize?（省略時10）, opId?（継続呼び出し時に指定）,
//         timeMinDays?（省略時7、過去何日分から）, timeMaxDays?（省略時90、未来何日分まで） }
export async function handleSyncCalendar(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const body = (await req.json()) as {
    namespace?: string;
    startIndex?: number;
    batchSize?: number;
    opId?: string;
    notifyOnErrorOnly?: boolean;
    timeMinDays?: number;
    timeMaxDays?: number;
  };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  try {
    requireGoogleServiceAccountConfig(env);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  let calendarId: string;
  try {
    calendarId = await resolveCalendarId(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();
  const timeMinDays = body.timeMinDays ?? DEFAULT_TIME_MIN_DAYS;
  const timeMaxDays = body.timeMaxDays ?? DEFAULT_TIME_MAX_DAYS;

  let events: CalendarEventSummary[];
  try {
    const token = await getGoogleAccessToken(env, CALENDAR_SCOPE);
    events = await listCalendarEvents(token, calendarId, timeMinDays, timeMaxDays);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  const batch = events.slice(startIndex, startIndex + batchSize);

  const { documents, chunks, skipped, results } = await processCalendarBatch(env, namespace, opId, batch);

  const nextIndex = startIndex + batchSize < events.length ? startIndex + batchSize : null;
  if (nextIndex === null) {
    await notifySyncComplete(env, opId, namespace, "google_calendar", body.notifyOnErrorOnly);
  }

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    results,
    totalEvents: events.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  } satisfies KbSyncResult & { totalEvents: number; processedRange: [number, number]; nextIndex: number | null });
}

// POST /admin/sync/calendar/retry-failed — 直近の同期（opId）で失敗(error)した予定だけを
// 再実行する（Jira/Backlog/Drive/Notionと同じ設計。2026-09-19追加：初回実装時は
// 「時間窓の再取得が再同期を兼ねる」としてこのエンドポイントを省略していたが、それだと
// 1件だけ失敗した場合でも時間窓内の全予定を再登録＝成功済み分も無駄に再埋め込みすることに
// なり、Jira/Backlog/Drive/Notionとの一貫性を欠いていたため追加した）。
// body: { namespace, opId, timeMinDays?, timeMaxDays?（初回同期時と同じ値を指定すること） }
export async function handleRetryFailedCalendar(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const body = (await req.json()) as { namespace?: string; opId?: string; timeMinDays?: number; timeMaxDays?: number };
  const namespace = (body.namespace || "").trim();
  const sourceOpId = (body.opId || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  if (!sourceOpId) return jsonResponse(400, { error: "opId は必須です" });

  try {
    requireGoogleServiceAccountConfig(env);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  let calendarId: string;
  try {
    calendarId = await resolveCalendarId(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const failedRows = await env.DB.prepare(
    "SELECT DISTINCT file FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'google_calendar' AND status = 'error'",
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
      totalEvents: 0,
      processedRange: [0, 0],
      nextIndex: null,
    } satisfies KbSyncResult & { totalEvents: number; processedRange: [number, number]; nextIndex: number | null });
  }

  let allEvents: CalendarEventSummary[];
  try {
    const token = await getGoogleAccessToken(env, CALENDAR_SCOPE);
    allEvents = await listCalendarEvents(
      token,
      calendarId,
      body.timeMinDays ?? DEFAULT_TIME_MIN_DAYS,
      body.timeMaxDays ?? DEFAULT_TIME_MAX_DAYS,
    );
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  const targets = allEvents.filter((e) => failedTitles.has(e.title));

  const placeholders = targets.map(() => "?").join(",");
  if (targets.length > 0) {
    await env.DB.prepare(
      `DELETE FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'google_calendar' AND status = 'error' AND file IN (${placeholders})`,
    )
      .bind(sourceOpId, namespace, ...targets.map((e) => e.title))
      .run();
  }

  const { documents, chunks, skipped, results } = await processCalendarBatch(env, namespace, sourceOpId, targets);

  return jsonResponse(200, {
    status: "ok",
    opId: sourceOpId,
    documents,
    chunks,
    skipped,
    results,
    totalEvents: targets.length,
    processedRange: [0, targets.length],
    nextIndex: null,
  } satisfies KbSyncResult & { totalEvents: number; processedRange: [number, number]; nextIndex: number | null });
}

// Cron Trigger（index.tsのscheduled()）から呼ばれる、カレンダー連携済み全namespaceの自動同期。
// Jira/Backlogと違い「差分」という概念を持たせていない（2026-09-19追加）：カレンダーの
// 予定は件数が少なく、既存予定の説明文が後から編集されるケースもあるため、毎回
// 時間窓（既定: 過去7日〜未来90日）を丸ごと再取得するほうが単純かつ確実（更新漏れが
// 起きない）。同じ内容の再埋め込みが多少発生するが、ingestDocument側が同じfile名を
// 上書きするだけなので実害はない。
export async function runScheduledCalendarSync(env: Env): Promise<void> {
  try {
    requireGoogleServiceAccountConfig(env);
  } catch {
    return; // 未設定の環境では何もしない
  }

  const rows = await env.DB.prepare("SELECT namespace_id, calendar_id FROM kb_sources WHERE calendar_id IS NOT NULL").all<{
    namespace_id: string;
    calendar_id: string;
  }>();

  for (const row of rows.results ?? []) {
    try {
      const token = await getGoogleAccessToken(env, CALENDAR_SCOPE);
      const events = await listCalendarEvents(token, row.calendar_id, DEFAULT_TIME_MIN_DAYS, DEFAULT_TIME_MAX_DAYS);
      if (events.length === 0) continue;
      const opId = newOpId();
      await processCalendarBatch(env, row.namespace_id, opId, events);
      await notifySyncComplete(env, opId, row.namespace_id, "google_calendar", true);
    } catch {
      // 1 namespace の失敗が他のnamespaceの同期を止めないよう続行する（Jira/Backlogと同じ理由）。
    }
  }
}

// POST /admin/kb/test-connection/calendar — secretと設定値だけで接続確認する
// （実際の登録は行わない、2026-09-19追加）。
export async function handleTestCalendarConnection(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json()) as { namespace?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  try {
    requireGoogleServiceAccountConfig(env);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  let calendarId: string;
  try {
    calendarId = await resolveCalendarId(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
  try {
    const token = await getGoogleAccessToken(env, CALENDAR_SCOPE);
    const res = await fetch(`https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(calendarId)}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return jsonResponse(400, { error: `Calendar接続エラー (${res.status}): ${await res.text()}` });
    const cal = (await res.json()) as { summary?: string };
    return jsonResponse(200, { status: "ok", message: `接続成功（カレンダー「${cal.summary ?? calendarId}」を確認）` });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}
