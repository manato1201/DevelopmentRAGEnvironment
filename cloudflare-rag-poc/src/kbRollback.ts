import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { logKb } from "./kbIngest";

const DELETE_CHUNK = 20; // getByIds()の1回あたり上限（20件）に合わせた保守的な値。deleteByIds()の実際の上限は未確認のため同じ値を流用する

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

// POST /admin/kb/rollback — 指定したopId（同期・一括登録操作のID）で登録されたファイルを
// namespaceから取り消す（既存GAS adminKbRollback相当）。kb_logに記録された「成功」エントリの
// file名からchunks_ftsの実チャンクIDを引き、D1・Vectorize両方から削除する。
// 注意：埋め込み前の生データは保持していないため、取り消し後に再度使いたい場合は再同期が必要。
export async function handleKbRollback(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { opId?: string };
  const opId = (body.opId || "").trim();
  if (!opId) return jsonResponse(400, { error: "opId は必須です" });

  const logRes = await env.DB.prepare(
    "SELECT DISTINCT namespace_id, file FROM kb_log WHERE op_id = ? AND status = 'ok' AND file IS NOT NULL",
  )
    .bind(opId)
    .all<{ namespace_id: string; file: string }>();
  const entries = logRes.results ?? [];
  if (entries.length === 0) {
    return jsonResponse(404, { error: `opId(${opId})に該当する成功済みの登録が見つかりません` });
  }

  let deletedFiles = 0;
  let deletedChunks = 0;
  const namespace = entries[0].namespace_id;

  for (const e of entries) {
    const chunkRes = await env.DB.prepare(
      "SELECT chunk_id FROM chunks_fts WHERE namespace = ? AND file = ?",
    )
      .bind(e.namespace_id, e.file)
      .all<{ chunk_id: string }>();
    const ids = (chunkRes.results ?? []).map((r) => r.chunk_id);
    if (ids.length === 0) continue;

    for (const idsChunk of chunk(ids, DELETE_CHUNK)) {
      await env.VEC_SHARED.deleteByIds(idsChunk);
    }
    await env.DB.prepare("DELETE FROM chunks_fts WHERE namespace = ? AND file = ?")
      .bind(e.namespace_id, e.file)
      .run();

    deletedFiles += 1;
    deletedChunks += ids.length;
  }

  await logKb(env, opId, namespace, "manual", null, "ok", `ロールバック実行: ${deletedFiles}ファイル・${deletedChunks}チャンクを削除`);

  return jsonResponse(200, { status: "ok", deletedFiles, deletedChunks });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
