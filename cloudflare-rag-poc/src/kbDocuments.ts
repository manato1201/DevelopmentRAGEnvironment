import type { AuthedUser, ChunkMetadata, Env } from "./types";
import { ForbiddenError, requireKnowledgeEditor } from "./auth";
import { jsonResponse } from "./http";

const DELETE_CHUNK = 20; // getByIds()の1回あたり上限（20件）に合わせた保守的な値。deleteByIds()の実際の上限は未確認のため同じ値を流用する

// 登録済みドキュメントの閲覧・削除の権限（2026-10-09）。個人用namespace（personal:<user_id>）は本人だけ
// （連携で個人用の索引に入れたものを、本人が確認・削除できるようにするため）。共有namespaceは従来どおり
// ナレッジ登録権限者。
function authorizeDocumentAccess(user: AuthedUser, namespace: string): void {
  if (namespace.startsWith("personal:")) {
    if (user.role === "guest" || namespace !== `personal:${user.userId}`) {
      throw new ForbiddenError("他のユーザーの個人用namespaceは操作できません");
    }
    return;
  }
  requireKnowledgeEditor(user);
}

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

// 指定namespace・file（ドキュメント単位）のチャンクをVectorize・chunks_fts・kb_documents
// の3箇所全てから削除する共通処理（kbRollback.tsのopId一括ロールバックと、この
// ファイルの個別削除ハンドラの両方から呼ばれる。2026-09-13、重複コード削減のため
// kbRollback.tsから抽出。抽出前はkb_documentsの削除が漏れており、ロールバック後も
// グラフビューに存在しないはずのドキュメントが「幽霊ノード」として残る不具合が
// あったため、あわせて修正している）。
export async function deleteDocumentChunks(env: Env, namespace: string, file: string): Promise<number> {
  const chunkRes = await env.DB.prepare("SELECT chunk_id FROM chunks_fts WHERE namespace = ? AND file = ?")
    .bind(namespace, file)
    .all<{ chunk_id: string }>();
  const ids = (chunkRes.results ?? []).map((r) => r.chunk_id);
  if (ids.length === 0) return 0;

  const index = namespace.startsWith("personal:") ? env.VEC_PERSONAL : env.VEC_SHARED;
  for (const idsChunk of chunk(ids, DELETE_CHUNK)) {
    await index.deleteByIds(idsChunk);
  }
  await env.DB.prepare("DELETE FROM chunks_fts WHERE namespace = ? AND file = ?").bind(namespace, file).run();
  await env.DB.prepare("DELETE FROM kb_documents WHERE namespace = ? AND file = ?").bind(namespace, file).run();
  return ids.length;
}

// POST /admin/kb/list-documents — namespace内の登録済みドキュメント（file名）一覧を返す。
// chunks_fts本体（UNINDEXED列への検索で実質フルスキャンになる。migrations/0002参照）では
// なくkb_documents（migrations/0008、namespaceにインデックス済み。1ドキュメント1行）を
// 使うことで、D1 FreeプランのRows read日次上限を消費する全チャンクスキャンを避ける。
// body: { namespace }
export async function handleListDocuments(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  authorizeDocumentAccess(user, namespace);

  const res = await env.DB.prepare("SELECT file FROM kb_documents WHERE namespace = ? ORDER BY file")
    .bind(namespace)
    .all<{ file: string }>();
  // 管理画面の一覧用に、ドキュメントごとの種類（登録元）と最終更新日時を付ける（2026-10-08）。
  // kb_log（成功した登録の記録）から引く。ログが無い（古い登録・ログ削除後）ものはnullのまま返す。
  // filesは従来の呼び出し元（名前だけを使うもの）のために残す。
  const logRes = await env.DB.prepare(
    `SELECT file, source, MAX(created_at) AS updated_at
     FROM kb_log WHERE namespace_id = ? AND status = 'ok' AND file IS NOT NULL
     GROUP BY file`,
  )
    .bind(namespace)
    .all<{ file: string; source: string; updated_at: number }>();
  const logByFile = new Map((logRes.results ?? []).map((r) => [r.file, r]));
  const files = (res.results ?? []).map((r) => r.file);
  const documents = files.map((file) => {
    const log = logByFile.get(file);
    return { file, source: log?.source ?? null, updatedAt: log?.updated_at ?? null };
  });
  return jsonResponse(200, { status: "ok", files, documents });
}

// POST /admin/kb/delete-document — namespace内の特定ドキュメント（file名一致）だけを削除
// する。opId単位で一括取り消すKBロールバック（handleKbRollback）と違い、クロール等で
// まとめて登録した複数ページのうち1件だけを取り消したい場合に使う（2026-09-13追加）。
// body: { namespace, file }
export async function handleDeleteDocument(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string; file?: string };
  const namespace = (body.namespace || "").trim();
  const file = (body.file || "").trim();
  if (namespace) authorizeDocumentAccess(user, namespace);
  if (!namespace || !file) return jsonResponse(400, { error: "namespace と file は必須です" });

  const deletedChunks = await deleteDocumentChunks(env, namespace, file);
  if (deletedChunks === 0) {
    return jsonResponse(404, { error: `namespace(${namespace})にfile(${file})という登録済みドキュメントが見つかりません` });
  }
  return jsonResponse(200, { status: "ok", deletedChunks });
}

// POST /admin/kb/find-duplicates — namespace内で内容が重複しているドキュメント（file）の
// 組を検出する（2026-09-15追加。同じページをURL登録とクロールの両方で登録した、
// Notion/Driveとの二重同期など、file名が違うだけで中身が同一の登録が実機で発生したため）。
//
// 判定方法: 各ドキュメントの先頭チャンク（chunk_index=0）の本文とドキュメント全体の
// 文字数が両方完全一致するかどうかで見る。全文をchunks_ftsから読み直す（UNINDEXED列への
// 検索で実質フルスキャンになる。deleteDocumentChunks手前のコメント/migrations/0008参照）
// 代わりに、ingestDocument()がVectorizeのメタデータへ既に書き込んでいるtext/sizeを
// getByIds（chunk_id主キー参照、chunks_ftsのフルスキャンを伴わない）で読む
// （graph.tsのノード取得と同じ経路）。先頭1000文字＋全体文字数が完全一致する別内容の
// 文書が偶然存在する確率は実用上無視できるため、意味的な類似度判定（近似一致）は
// あえて使わない＝削除という取り消せない操作につながる機能なので、誤検出を避ける方を
// 優先した設計。
// 実際の削除は既存の/admin/kb/delete-document（handleDeleteDocument）を呼び出す側
// （管理画面UI）に委ね、このエンドポイントは検出結果を返すだけに留める。
// body: { namespace }
export async function handleFindDuplicateDocuments(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json()) as { namespace?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  const res = await env.DB.prepare("SELECT chunk_id, file FROM kb_documents WHERE namespace = ?")
    .bind(namespace)
    .all<{ chunk_id: string; file: string }>();
  const rows = res.results ?? [];
  if (rows.length === 0) return jsonResponse(200, { status: "ok", groups: [] });

  const fileByChunkId = new Map(rows.map((r) => [r.chunk_id, r.file]));
  const fingerprintByFile = new Map<string, string>();
  for (const idsChunk of chunk(rows.map((r) => r.chunk_id), DELETE_CHUNK)) {
    const vecRes = await env.VEC_SHARED.getByIds(idsChunk);
    for (const v of vecRes) {
      const file = fileByChunkId.get(v.id);
      const meta = v.metadata as unknown as ChunkMetadata | undefined;
      if (!file || !meta) continue;
      fingerprintByFile.set(file, `${meta.size ?? "?"}::${meta.text}`);
    }
  }

  const filesByFingerprint = new Map<string, string[]>();
  for (const [file, fingerprint] of fingerprintByFile) {
    const files = filesByFingerprint.get(fingerprint) ?? [];
    files.push(file);
    filesByFingerprint.set(fingerprint, files);
  }

  const groups = Array.from(filesByFingerprint.values())
    .filter((files) => files.length > 1)
    .map((files) => ({ files: files.sort() }));

  return jsonResponse(200, { status: "ok", groups });
}
