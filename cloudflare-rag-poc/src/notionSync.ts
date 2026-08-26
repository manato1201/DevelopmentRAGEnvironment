import type { AuthedUser, Env, KbSyncResult } from "./types";
import { requireAdmin } from "./auth";
import { listNotionPages, getPageText } from "./notion";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId, withTimeout } from "./chunking";

// depth=8への引き上げでネストが深いページのブロック取得回数が増えたため、Drive側と同様に
// 1ページあたりの処理に上限を設ける（2026-08-27）。
const PER_PAGE_TIMEOUT_MS = 30_000;

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
      const text = await withTimeout(getPageText(env, page.id), PER_PAGE_TIMEOUT_MS, `${page.title}の取得`);
      if (!text.trim()) {
        skipped.push({ file: page.title, reason: "本文が空です" });
        await logKb(env, opId, namespace, "notion", page.title, "skipped", "本文が空");
        continue;
      }
      const result = await ingestDocument(env, namespace, page.title, text, "notion");
      chunks += result.chunks;
      documents += 1;
      const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
      await logKb(env, opId, namespace, "notion", page.title, "ok", `${result.chunks}チャンク登録${skipNote}`);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: page.title, reason: detail });
      await logKb(env, opId, namespace, "notion", page.title, "error", detail);
    }
  }

  const nextIndex = startIndex + batchSize < pages.length ? startIndex + batchSize : null;

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
