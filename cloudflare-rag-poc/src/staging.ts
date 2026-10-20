import type { AuthedUser, ChunkMetadata, Env } from "./types";
import { jsonResponse } from "./http";
import { ForbiddenError, requireAdmin, requireKnowledgeEditor } from "./auth";
import { logKb, makeChunkId, recordOp } from "./kbIngest";
import { newOpId } from "./chunking";
import { deleteChunkStatements, putChunkStatements, readDocumentChunks, runStatementGroups } from "./chunkRows";

// 取り込みのステージング（2026-10-16追加、migrations/0024）。
// 連携・クロールなどの取り込み先を「受け皿」namespaceにしておき、内容を確認してから本番のnamespaceへ移す
// （または破棄する）。本番側を連携の許可リストに入れなければ、連携は本番へ直接書けない。
// 対象は共有namespaceだけ（個人用は本人専用なのでステージングは要らない）。
const GET_BY_IDS_CHUNK = 20;

function chunkArray<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

// POST /admin/staging/list — 受け皿と本番の対応、受け皿にあるドキュメント数（ナレッジ登録権限者）
export async function handleListStaging(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const res = await env.DB.prepare(
    `SELECT s.staging_namespace_id AS staging, s.target_namespace_id AS target,
            (SELECT COUNT(*) FROM kb_documents d WHERE d.namespace = s.staging_namespace_id) AS pending
       FROM staging_targets s ORDER BY s.staging_namespace_id`,
  ).all<{ staging: string; target: string; pending: number }>();
  return jsonResponse(200, { status: "ok", pairs: res.results ?? [] });
}

// POST /admin/staging/set — 受け皿と本番の組を登録する（管理者のみ）。受け皿は連携の許可リストにも入れる。
// body: { staging, target }
export async function handleSetStaging(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { staging?: string; target?: string };
  const staging = (body.staging || "").trim();
  const target = (body.target || "").trim();
  if (!staging || !target) return jsonResponse(400, { error: "staging と target は必須です" });
  if (staging === target) return jsonResponse(400, { error: "受け皿と本番は別のnamespaceにしてください" });
  if (staging.startsWith("personal:") || target.startsWith("personal:")) {
    return jsonResponse(400, { error: "ステージングは共有namespaceだけで使えます" });
  }
  for (const ns of [staging, target]) {
    const row = await env.DB.prepare("SELECT 1 AS ok FROM namespaces WHERE namespace_id = ?").bind(ns).first();
    if (!row) return jsonResponse(400, { error: `namespace(${ns})が存在しません` });
  }
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare(
    `INSERT INTO staging_targets (staging_namespace_id, target_namespace_id, created_by, created_at) VALUES (?, ?, ?, ?)
     ON CONFLICT(staging_namespace_id) DO UPDATE SET target_namespace_id = excluded.target_namespace_id`,
  )
    .bind(staging, target, user.userId, now)
    .run();
  // 連携は受け皿にだけ書けるようにする。
  await env.DB.prepare("INSERT OR IGNORE INTO sync_allowed_namespaces (namespace_id, added_by, created_at) VALUES (?, ?, ?)")
    .bind(staging, user.userId, now)
    .run();
  const targetAllowed = !!(await env.DB.prepare("SELECT 1 AS ok FROM sync_allowed_namespaces WHERE namespace_id = ?").bind(target).first());
  return jsonResponse(200, { status: "ok", targetAllowed });
}

// POST /admin/staging/remove — 組を外す（管理者のみ。受け皿のドキュメントや許可リストはそのまま）。body: { staging }
export async function handleRemoveStaging(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { staging?: string };
  const staging = (body.staging || "").trim();
  if (!staging) return jsonResponse(400, { error: "staging は必須です" });
  await env.DB.prepare("DELETE FROM staging_targets WHERE staging_namespace_id = ?").bind(staging).run();
  return jsonResponse(200, { status: "ok" });
}

async function targetOf(env: Env, staging: string): Promise<string | null> {
  const row = await env.DB.prepare("SELECT target_namespace_id FROM staging_targets WHERE staging_namespace_id = ?")
    .bind(staging)
    .first<{ target_namespace_id: string }>();
  return row ? row.target_namespace_id : null;
}

// POST /admin/staging/docs — 受け皿にあるドキュメントの一覧（確認用。先頭チャンクの抜粋・登録元・日時つき）。
// body: { staging }
export async function handleStagingDocs(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json().catch(() => ({}))) as { staging?: string };
  const staging = (body.staging || "").trim();
  const target = staging ? await targetOf(env, staging) : null;
  if (!target) return jsonResponse(400, { error: `namespace(${staging})はステージングの受け皿として登録されていません` });

  const docs = await env.DB.prepare("SELECT chunk_id, file FROM kb_documents WHERE namespace = ? ORDER BY file LIMIT 200")
    .bind(staging)
    .all<{ chunk_id: string; file: string }>();
  const rows = docs.results ?? [];
  const excerptById = new Map<string, string>();
  for (const ids of chunkArray(rows.map((r) => r.chunk_id), GET_BY_IDS_CHUNK)) {
    for (const v of await env.VEC_SHARED.getByIds(ids)) {
      const meta = v.metadata as unknown as ChunkMetadata | undefined;
      if (meta?.text) excerptById.set(v.id, meta.text.slice(0, 300));
    }
  }
  const log = await env.DB.prepare(
    `SELECT file, source, MAX(created_at) AS updated_at FROM kb_log WHERE namespace_id = ? AND status = 'ok' AND file IS NOT NULL GROUP BY file`,
  )
    .bind(staging)
    .all<{ file: string; source: string; updated_at: number }>();
  const logByFile = new Map((log.results ?? []).map((r) => [r.file, r]));
  return jsonResponse(200, {
    status: "ok",
    staging,
    target,
    documents: rows.map((r) => ({
      file: r.file,
      excerpt: excerptById.get(r.chunk_id) ?? "",
      source: logByFile.get(r.file)?.source ?? null,
      updatedAt: logByFile.get(r.file)?.updated_at ?? null,
    })),
  });
}

// 1ドキュメントを受け皿から本番へ移す。新しい側を先に書き、書けてから古い側を消す。
// チャンクIDはnamespaceとfileから決まるので、本番に同名のドキュメントがあれば置き換わる。
async function moveDocument(env: Env, from: string, to: string, file: string): Promise<number> {
  const old = await readDocumentChunks(env, from, file);
  if (old.length === 0) return 0;

  const bodyById = new Map(old.map((r) => [r.chunk_id, r.body]));
  const vectors: Array<{ oldId: string; index: number; values: number[]; metadata: ChunkMetadata }> = [];
  for (const ids of chunkArray(old.map((r) => r.chunk_id), GET_BY_IDS_CHUNK)) {
    for (const v of await env.VEC_SHARED.getByIds(ids)) {
      const meta = v.metadata as unknown as ChunkMetadata | undefined;
      const index = Number(String(v.id).split(":").pop());
      if (!meta || !Number.isFinite(index)) continue;
      vectors.push({ oldId: v.id, index, values: Array.from(v.values as ArrayLike<number>), metadata: meta });
    }
  }
  if (vectors.length === 0) throw new Error(`「${file}」のベクトルが見つかりません（移せません）`);

  const moved = await Promise.all(
    vectors.map(async (v) => ({ ...v, newId: await makeChunkId(to, file, v.index) })),
  );
  // 1) 本番側へ書く（ベクトル→D1）
  const batches = chunkArray(moved, 20);
  for (const group of batches) {
    await env.VEC_SHARED.upsert(
      group.map((v) => ({
        id: v.newId,
        values: v.values,
        metadata: { ...v.metadata, namespace: to, scope: "shared", owner_user_id: undefined } as unknown as Record<string, VectorizeVectorMetadataValue>,
      })),
    );
  }
  const groups: D1PreparedStatement[][] = [];
  for (const v of moved) {
    const group = putChunkStatements(env, {
      chunkId: v.newId,
      file,
      namespace: to,
      scope: "shared",
      ownerUserId: null,
      difficulty: v.metadata.difficulty ?? null,
      body: bodyById.get(v.oldId) ?? v.metadata.text,
    });
    if (v.index === 0) {
      group.push(
        env.DB.prepare("INSERT OR REPLACE INTO kb_documents (chunk_id, file, namespace, scope, owner_user_id) VALUES (?, ?, ?, 'shared', NULL)").bind(v.newId, file, to),
      );
    }
    groups.push(group);
  }
  await runStatementGroups(env, groups);

  // 2) 受け皿側を消す
  for (const ids of chunkArray(moved.map((v) => v.oldId), 20)) await env.VEC_SHARED.deleteByIds(ids);
  await runStatementGroups(env, [
    [
      ...deleteChunkStatements(env, moved.map((v) => v.oldId)),
      env.DB.prepare("DELETE FROM kb_documents WHERE namespace = ? AND file = ?").bind(from, file),
    ],
  ]);
  return moved.length;
}

// POST /admin/staging/promote — 受け皿から選んだドキュメントを、対応する本番のnamespaceへ移す。
// 管理者、または本番のnamespaceに書き込み権限のあるナレッジ登録権限者。body: { staging, files: string[] }
export async function handlePromoteStaging(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json().catch(() => ({}))) as { staging?: string; files?: unknown };
  const staging = (body.staging || "").trim();
  const files = Array.isArray(body.files) ? (body.files as unknown[]).map((f) => String(f)).filter(Boolean) : [];
  if (files.length === 0) return jsonResponse(400, { error: "files（移すドキュメント名の配列）は必須です" });
  if (files.length > 50) return jsonResponse(400, { error: "一度に移せるのは50件までです" });
  const target = staging ? await targetOf(env, staging) : null;
  if (!target) return jsonResponse(400, { error: `namespace(${staging})はステージングの受け皿として登録されていません` });
  if (user.role !== "admin" && !user.allowedNamespaces.includes(target)) {
    throw new ForbiddenError(`移し先のnamespace(${target})への書き込み権限がありません`);
  }

  const opId = newOpId();
  await recordOp(env, opId, user.userId, "promote", target);
  const results: Array<{ file: string; status: "ok" | "error"; chunks: number; error?: string }> = [];
  for (const file of files) {
    try {
      const chunks = await moveDocument(env, staging, target, file);
      if (chunks === 0) {
        results.push({ file, status: "error", chunks: 0, error: "受け皿に見つかりません" });
        continue;
      }
      await logKb(env, opId, target, "manual", file, "ok", `ステージングから移動: ${chunks}チャンク（${staging} → ${target}）`);
      results.push({ file, status: "ok", chunks });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      await logKb(env, opId, target, "manual", file, "error", `ステージングからの移動に失敗: ${message}`);
      results.push({ file, status: "error", chunks: 0, error: message });
    }
  }
  return jsonResponse(200, { status: "ok", opId, target, results });
}
