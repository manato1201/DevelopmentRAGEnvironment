import type { AuthedUser, Env, KbSyncResult } from "./types";
import { requireAdmin } from "./auth";
import { listNotionPages, getPageText } from "./notion";
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

// POST /admin/sync/notion — 既存GAS syncNotionToSheets相当。
// 大きいデータベースは1回で終わらないため、バッチ処理＋カーソル方式にしている。
// body: { namespace, startIndex?（省略時0）, batchSize?（省略時5）, opId?（継続呼び出し時に指定） }
// レスポンスの nextIndex が null なら完了、数値ならその値をstartIndexにして再度呼び出すこと。
export async function handleSyncNotion(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);

  const body = (await req.json()) as { namespace?: string; startIndex?: number; batchSize?: number; opId?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  const source = await env.DB.prepare("SELECT notion_database_id FROM kb_sources WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ notion_database_id: string | null }>();
  if (!source?.notion_database_id) {
    return jsonResponse(400, { error: `namespace(${namespace})にNotionデータベースIDが設定されていません。先に /admin/kb/set-source で設定してください` });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();

  const pages = await listNotionPages(env, source.notion_database_id);
  const batch = pages.slice(startIndex, startIndex + batchSize);

  let documents = 0;
  let chunks = 0;
  const skipped: Array<{ file: string; reason: string }> = [];

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
        await logKb(env, opId, namespace, "notion", page.title, "skipped", outcome.reason);
        continue;
      }
      chunks += outcome.chunks;
      documents += 1;
      const skipNote = outcome.skippedVectors > 0 ? `（${outcome.skippedVectors}チャンクは登録失敗のためスキップ）` : "";
      await logKb(env, opId, namespace, "notion", page.title, "ok", `${outcome.chunks}チャンク登録${skipNote}`);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: page.title, reason: detail });
      await logKb(env, opId, namespace, "notion", page.title, "error", detail);
    }
  }

  const nextIndex = startIndex + batchSize < pages.length ? startIndex + batchSize : null;
  if (nextIndex === null) {
    await notifySyncComplete(env, opId, namespace, "notion");
  }

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    totalPages: pages.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  } satisfies KbSyncResult & { totalPages: number; processedRange: [number, number]; nextIndex: number | null });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
