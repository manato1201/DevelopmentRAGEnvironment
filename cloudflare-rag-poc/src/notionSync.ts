import type { AuthedUser, Env, KbSyncResult } from "./types";
import { jsonResponse } from "./http";
import { requireKnowledgeEditor } from "./auth";
import { listNotionPages, getPageText } from "./notion";
import type { NotionPageSummary } from "./notion";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId, withAbortTimeout } from "./chunking";
import { notifySyncComplete } from "./syncNotify";

// depth=8への引き上げでネストが深いページのブロック取得回数が増えたため、Drive側と同様に
// 1ページあたりの処理に上限を設ける（2026-08-27）。
//
// 2026-08-29修正: 当初この上限はgetPageText（ブロック取得）だけに掛かっており、
// 後段のingestDocument（チャンクごとのGemini埋め込み）は無制限だった。Drive側と
// 同じ理由でチャンク数の多いページが際限なく処理時間を延ばせてしまうため、
// withTimeout（Promise.raceで待つのをやめるだけ、実体はキャンセルしない）から
// withAbortTimeout（fetchに渡したAbortSignalで実際にキャンセルする）へ切り替え、
// ページ取得＋埋め込みの全体を1つの枠で包み、上限自体も引き上げる。
const PER_PAGE_TIMEOUT_MS = 100_000;

// 1回のWorker呼び出しで処理するページ数。Cloudflareのサブリクエスト数上限
// （1リクエストあたりfetch呼び出し合計。有料プランで1,000）に引っかからないよう、
// 1ページあたり数回のfetch（ブロック取得＋チャンクごとの埋め込み）がかかることを踏まえて
// 保守的な値にしている。実際にHoudini21（80ページ）の同期で上限超過を確認した対策。
const DEFAULT_BATCH_SIZE = 5;

// batch内の各ページをGeminiで埋め込み＋D1書き込みする共通処理。通常のページング同期
// （handleSyncNotion）と、失敗ページだけを狙い撃ちする再同期（handleRetryFailedNotion）の
// 両方から呼ばれる（2026-09-04リトライ機能追加時に抽出）。
async function processNotionBatch(
  env: Env,
  namespace: string,
  opId: string,
  batch: NotionPageSummary[],
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

  for (const page of batch) {
    try {
      // ページ取得＋埋め込み＋D1書き込みまでを1つのタイムアウトで包む
      // （2026-08-29: 理由はDrive側のPER_FILE_TIMEOUT_MSのコメント参照）。
      const outcome = await withAbortTimeout(
        async (signal): Promise<
          | { kind: "skip"; reason: string }
          | { kind: "ok"; chunks: number; skippedVectors: number }
        > => {
          const text = await getPageText(env, page.id, 8, signal);
          if (!text.trim()) return { kind: "skip", reason: "本文が空です" };
          const result = await ingestDocument(env, namespace, page.title, text, "notion", signal);
          return { kind: "ok", chunks: result.chunks, skippedVectors: result.skippedVectors.length };
        },
        PER_PAGE_TIMEOUT_MS,
        `${page.title}の処理`,
      );
      if (outcome.kind === "skip") {
        skipped.push({ file: page.title, reason: outcome.reason });
        results.push({ file: page.title, status: "skipped", detail: outcome.reason });
        await logKb(env, opId, namespace, "notion", page.title, "skipped", outcome.reason);
        continue;
      }
      chunks += outcome.chunks;
      documents += 1;
      const skipNote = outcome.skippedVectors > 0 ? `（${outcome.skippedVectors}チャンクは登録失敗のためスキップ）` : "";
      const detail = `${outcome.chunks}チャンク登録${skipNote}`;
      results.push({ file: page.title, status: "ok", detail });
      await logKb(env, opId, namespace, "notion", page.title, "ok", detail);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: page.title, reason: detail });
      results.push({ file: page.title, status: "error", detail });
      await logKb(env, opId, namespace, "notion", page.title, "error", detail);
    }
  }

  return { documents, chunks, skipped, results };
}

async function resolveNotionDatabase(env: Env, namespace: string): Promise<string> {
  const source = await env.DB.prepare("SELECT notion_database_id FROM kb_sources WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ notion_database_id: string | null }>();
  if (!source?.notion_database_id) {
    throw new Error(`namespace(${namespace})にNotionデータベースIDが設定されていません。先に /admin/kb/set-source で設定してください`);
  }
  return source.notion_database_id;
}

// POST /admin/sync/notion — 既存GAS syncNotionToSheets相当。
// 大きいデータベースは1回で終わらないため、バッチ処理＋カーソル方式にしている。
// body: { namespace, startIndex?（省略時0）, batchSize?（省略時5）, opId?（継続呼び出し時に指定） }
// レスポンスの nextIndex が null なら完了、数値ならその値をstartIndexにして再度呼び出すこと。
export async function handleSyncNotion(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const body = (await req.json()) as { namespace?: string; startIndex?: number; batchSize?: number; opId?: string; notifyOnErrorOnly?: boolean };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  let databaseId: string;
  try {
    databaseId = await resolveNotionDatabase(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();

  const pages = await listNotionPages(env, databaseId);
  const batch = pages.slice(startIndex, startIndex + batchSize);

  const { documents, chunks, skipped, results } = await processNotionBatch(env, namespace, opId, batch);

  const nextIndex = startIndex + batchSize < pages.length ? startIndex + batchSize : null;
  if (nextIndex === null) {
    await notifySyncComplete(env, opId, namespace, "notion", body.notifyOnErrorOnly);
  }

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    results,
    totalPages: pages.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  } satisfies KbSyncResult & { totalPages: number; processedRange: [number, number]; nextIndex: number | null });
}

// POST /admin/sync/notion/retry-failed — 直近の同期（opId）で失敗(error)したページだけを
// 対象に再実行する（2026-09-04追加。Drive側のhandleRetryFailedDriveと同じ設計）。
// body: { namespace, opId }
export async function handleRetryFailedNotion(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const body = (await req.json()) as { namespace?: string; opId?: string };
  const namespace = (body.namespace || "").trim();
  const sourceOpId = (body.opId || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  if (!sourceOpId) return jsonResponse(400, { error: "opId は必須です" });

  let databaseId: string;
  try {
    databaseId = await resolveNotionDatabase(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const failedRows = await env.DB.prepare(
    "SELECT DISTINCT file FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'notion' AND status = 'error'",
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
      totalPages: 0,
      processedRange: [0, 0],
      nextIndex: null,
    } satisfies KbSyncResult & { totalPages: number; processedRange: [number, number]; nextIndex: number | null });
  }

  const allPages = await listNotionPages(env, databaseId);
  const targets = allPages.filter((p) => failedTitles.has(p.title));

  // logKbは追記のみでerror行を消さないため、先に今回対象の古いerror行を消しておく
  // （Drive側と同じ理由。2026-09-04、実装直後の自己レビューで発見：これをしないと
  // 直ったページの古いerror行がいつまでも残り、次回の再同期で無駄に再処理し続ける）。
  const placeholders = targets.map(() => "?").join(",");
  if (targets.length > 0) {
    await env.DB.prepare(
      `DELETE FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'notion' AND status = 'error' AND file IN (${placeholders})`,
    )
      .bind(sourceOpId, namespace, ...targets.map((p) => p.title))
      .run();
  }

  // 元のopIdに追記する（Drive側と同じ理由：kb_historyで同期とそのリトライを紐付けやすくする）。
  const { documents, chunks, skipped, results } = await processNotionBatch(env, namespace, sourceOpId, targets);

  return jsonResponse(200, {
    status: "ok",
    opId: sourceOpId,
    documents,
    chunks,
    skipped,
    results,
    totalPages: targets.length,
    processedRange: [0, targets.length],
    nextIndex: null,
  } satisfies KbSyncResult & { totalPages: number; processedRange: [number, number]; nextIndex: number | null });
}
