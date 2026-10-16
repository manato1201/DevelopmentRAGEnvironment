import type { AuthedUser, Env } from "./types";
import { jsonResponse, clampInt } from "./http";
import { ForbiddenError, requireKnowledgeEditor } from "./auth";
import { authorizeSync, cronMayWrite, isPersonalNamespace } from "./syncTargets";
import { runCrawlBatch } from "./urlImport";

// 定期の再クロール（2026-10-16追加、migrations/0025）。
// ・明示的に有効にしたスケジュールだけが動く（既定は無効）。共有namespaceは、連携の同期先の許可リストに
//   入っているものだけ（authorizeSync）。個人用namespaceは本人だけ。
// ・変更の無いページは飛ばされる（crawl_page_hashes）ので、再クロールは変わったページだけを処理する。
// ・大きなサイトは1回では終わらないため、30分ごとのCronが、時間の予算の範囲で少しずつ進める。
//   途中の状態は active_op_id（crawl_jobs）に残る。管理画面の「中断したクロール」からも再開できる。
const FREQUENCY_SECONDS: Record<string, number> = { daily: 20 * 3600, weekly: 6 * 86400 + 12 * 3600 };
const TICK_BUDGET_MS = 20_000; // 1回のCronで、全スケジュールに使う時間の目安
const MAX_SCHEDULES_PER_NAMESPACE = 20;

interface ScheduleRow {
  id: number;
  namespace_id: string;
  url: string;
  depth: number;
  max_pages: number;
  path_prefix: string | null;
  exclude_patterns: string | null;
  frequency: string;
  enabled: number;
  created_by: string | null;
  created_at: number;
  last_run_at: number | null;
  active_op_id: string | null;
}

// 無効にする・削除するときの権限。許可リストからは外れていても、止める・消すことはできるようにする
// （個人用は本人だけ、共有は管理者か、そのnamespaceに書き込み権限のあるナレッジ登録権限者）。
function assertCanManage(user: AuthedUser, namespace: string): void {
  if (isPersonalNamespace(namespace)) {
    if (namespace !== `personal:${user.userId}`) throw new ForbiddenError("他のユーザーの個人用namespaceのスケジュールは操作できません");
    return;
  }
  if (user.role !== "admin" && !user.allowedNamespaces.includes(namespace)) {
    throw new ForbiddenError(`namespace(${namespace})への書き込み権限がありません`);
  }
}

function rowToJson(r: ScheduleRow) {
  return {
    id: r.id,
    namespace: r.namespace_id,
    url: r.url,
    depth: r.depth,
    maxPages: r.max_pages,
    pathPrefix: r.path_prefix || "",
    excludePatterns: r.exclude_patterns || "",
    frequency: r.frequency,
    enabled: r.enabled === 1,
    lastRunAt: r.last_run_at,
    running: !!r.active_op_id,
  };
}

// POST /admin/crawl-schedules/list — 自分が見てよいスケジュール（共有 + 自分の個人用）。
export async function handleListCrawlSchedules(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const res = await env.DB.prepare("SELECT * FROM crawl_schedules WHERE namespace_id NOT LIKE 'personal:%' OR namespace_id = ? ORDER BY namespace_id, id")
    .bind(`personal:${user.userId}`)
    .all<ScheduleRow>();
  return jsonResponse(200, { status: "ok", schedules: (res.results ?? []).map(rowToJson) });
}

// POST /admin/crawl-schedules/save — 追加（id無し）または更新（id有り）。
// body: { id?, namespace, url, depth?, maxPages?, pathPrefix?, excludePatterns?, frequency?, enabled? }
export async function handleSaveCrawlSchedule(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json().catch(() => ({}))) as {
    id?: number;
    namespace?: string;
    url?: string;
    depth?: number;
    maxPages?: number;
    pathPrefix?: string;
    excludePatterns?: string;
    frequency?: string;
    enabled?: boolean;
  };
  const namespace = (body.namespace || "").trim();
  const url = (body.url || "").trim();
  if (!namespace || !url) return jsonResponse(400, { error: "namespace と url は必須です" });
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return jsonResponse(400, { error: "http/https以外のURLは指定できません" });
  } catch {
    return jsonResponse(400, { error: "urlの形式が不正です" });
  }
  // 新しく作る・有効にするときは、書き込み先の確認（許可リスト）を通す。無効にするだけなら通さない。
  if (!body.id || body.enabled) await authorizeSync(env, user, namespace);
  else assertCanManage(user, namespace);
  const frequency = body.frequency === "daily" ? "daily" : "weekly";
  const depth = clampInt(body.depth, 1, 0, 3);
  const maxPages = clampInt(body.maxPages, 30, 1, 1000);
  const now = Math.floor(Date.now() / 1000);

  if (body.id) {
    const existing = await env.DB.prepare("SELECT namespace_id FROM crawl_schedules WHERE id = ?").bind(body.id).first<{ namespace_id: string }>();
    if (!existing) return jsonResponse(404, { error: "スケジュールが見つかりません" });
    if (existing.namespace_id !== namespace) assertCanManage(user, existing.namespace_id);
    await env.DB.prepare(
      `UPDATE crawl_schedules SET namespace_id = ?, url = ?, depth = ?, max_pages = ?, path_prefix = ?, exclude_patterns = ?, frequency = ?, enabled = ? WHERE id = ?`,
    )
      .bind(namespace, url, depth, maxPages, (body.pathPrefix || "").trim() || null, (body.excludePatterns || "").trim() || null, frequency, body.enabled ? 1 : 0, body.id)
      .run();
    return jsonResponse(200, { status: "ok", id: body.id });
  }

  const count = await env.DB.prepare("SELECT COUNT(*) AS c FROM crawl_schedules WHERE namespace_id = ?").bind(namespace).first<{ c: number }>();
  if ((count?.c ?? 0) >= MAX_SCHEDULES_PER_NAMESPACE) return jsonResponse(400, { error: `1つのnamespaceに登録できるスケジュールは${MAX_SCHEDULES_PER_NAMESPACE}件までです` });
  const res = await env.DB.prepare(
    `INSERT INTO crawl_schedules (namespace_id, url, depth, max_pages, path_prefix, exclude_patterns, frequency, enabled, created_by, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(namespace, url, depth, maxPages, (body.pathPrefix || "").trim() || null, (body.excludePatterns || "").trim() || null, frequency, body.enabled ? 1 : 0, user.userId, now)
    .run();
  return jsonResponse(200, { status: "ok", id: Number(res.meta.last_row_id) });
}

// POST /admin/crawl-schedules/delete — body: { id }
export async function handleDeleteCrawlSchedule(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json().catch(() => ({}))) as { id?: number };
  if (!body.id) return jsonResponse(400, { error: "id は必須です" });
  const row = await env.DB.prepare("SELECT namespace_id, active_op_id FROM crawl_schedules WHERE id = ?").bind(body.id).first<{ namespace_id: string; active_op_id: string | null }>();
  if (!row) return jsonResponse(200, { status: "ok" });
  assertCanManage(user, row.namespace_id);
  if (row.active_op_id) await env.DB.prepare("DELETE FROM crawl_jobs WHERE op_id = ?").bind(row.active_op_id).run();
  await env.DB.prepare("DELETE FROM crawl_schedules WHERE id = ?").bind(body.id).run();
  return jsonResponse(200, { status: "ok" });
}

export function isDue(row: Pick<ScheduleRow, "frequency" | "last_run_at" | "active_op_id">, now: number): boolean {
  if (row.active_op_id) return true; // 途中のものは続きを進める
  if (row.last_run_at === null) return true;
  return now - row.last_run_at >= (FREQUENCY_SECONDS[row.frequency] ?? FREQUENCY_SECONDS.weekly);
}

// Cron: 動かす時刻が来た、または途中のスケジュールを、時間の予算の範囲で進める。
// 1つの失敗が他を止めないよう、スケジュールごとにcatchする。許可リストから外れた共有namespaceは動かさない。
export async function runScheduledCrawls(env: Env, budgetMs = TICK_BUDGET_MS): Promise<{ ran: number; finished: number }> {
  const started = Date.now();
  const res = await env.DB.prepare("SELECT * FROM crawl_schedules WHERE enabled = 1 ORDER BY COALESCE(last_run_at, 0), id").all<ScheduleRow>();
  const now = Math.floor(Date.now() / 1000);
  let ran = 0;
  let finished = 0;
  for (const row of res.results ?? []) {
    if (Date.now() - started > budgetMs) break;
    if (!isDue(row, now)) continue;
    try {
      if (!isPersonalNamespace(row.namespace_id) && !(await cronMayWrite(env, row.namespace_id))) continue;
      ran++;
      let opId = row.active_op_id;
      let done = false;
      // 時間の予算が尽きるまで、1ページ（上限は1リクエストの時間の目安）ずつ進める
      while (Date.now() - started <= budgetMs && !done) {
        const batch = await runCrawlBatch(
          env,
          opId
            ? { opId, batchSize: 2 }
            : {
                namespace: row.namespace_id, url: row.url, depth: row.depth, maxPages: row.max_pages,
                pathPrefix: row.path_prefix || undefined, excludePatterns: row.exclude_patterns || undefined, batchSize: 2,
              },
          null,
        );
        const data = (await batch.json()) as { opId?: string; done?: boolean; error?: string };
        if (!batch.ok) {
          // 続きの記録が無い（完了済み・期限切れ）なら、次回は最初から。それ以外は次回のCronで再試行する。
          if (batch.status === 404) {
            await env.DB.prepare("UPDATE crawl_schedules SET active_op_id = NULL WHERE id = ?").bind(row.id).run();
          }
          break;
        }
        opId = data.opId ?? opId;
        done = data.done === true;
        await env.DB.prepare("UPDATE crawl_schedules SET active_op_id = ?, last_run_at = COALESCE(last_run_at, ?) WHERE id = ?")
          .bind(done ? null : opId, Math.floor(Date.now() / 1000), row.id)
          .run();
      }
      if (done) {
        finished++;
        await env.DB.prepare("UPDATE crawl_schedules SET active_op_id = NULL, last_run_at = ? WHERE id = ?").bind(Math.floor(Date.now() / 1000), row.id).run();
      }
    } catch {
      // このスケジュールは次回のCronでやり直す
    }
  }
  return { ran, finished };
}
