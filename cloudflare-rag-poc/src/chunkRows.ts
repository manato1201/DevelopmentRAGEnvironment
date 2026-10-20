import type { Env } from "./types";

// chunks_fts（FTS5）の読み書きの入口（migrations/0030）。
// chunks_ftsはchunk_id/namespace/fileがUNINDEXED列で、これらでの検索・削除は毎回全件走査になる
// （D1の読み取り行数を使い切る原因だった）。そこで、chunk_id → FTSのrowid の対応表chunk_rows
// （chunk_id主キー、(namespace, file)に索引）を持ち、削除と参照はrowid経由で行う。
// chunks_fts / chunk_rows への書き込みは、必ずこのファイルの関数を通すこと（片方だけ更新すると対応がずれる）。

export interface ChunkRow {
  chunkId: string;
  file: string;
  namespace: string;
  scope: "shared" | "personal";
  ownerUserId: string | null;
  difficulty: string | null;
  body: string;
}

// 同じchunk_idの行を消してから入れ直す（再登録で重複しない）。
// 注意: 最後の「chunk_rowsへの記録」は、直前のchunks_fts挿入のlast_insert_rowid()を使う。
// 必ずこの4文を連続・同じバッチで実行する（runStatementGroupsは1グループを分割しない）。
export function putChunkStatements(
  env: Env,
  row: ChunkRow,
): D1PreparedStatement[] {
  return [
    ...deleteChunkStatements(env, [row.chunkId]),
    env.DB.prepare(
      "INSERT INTO chunks_fts (chunk_id, file, namespace, scope, owner_user_id, difficulty, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ).bind(
      row.chunkId,
      row.file,
      row.namespace,
      row.scope,
      row.ownerUserId,
      row.difficulty,
      row.body,
    ),
    env.DB.prepare(
      "INSERT OR REPLACE INTO chunk_rows (chunk_id, fts_rowid, namespace, file) VALUES (?, last_insert_rowid(), ?, ?)",
    ).bind(row.chunkId, row.namespace, row.file),
  ];
}

// chunk_idを指定して削除する（FTS本体 → 対応表の順）。
export function deleteChunkStatements(
  env: Env,
  chunkIds: string[],
): D1PreparedStatement[] {
  return chunkIds.flatMap((id) => [
    env.DB.prepare(
      "DELETE FROM chunks_fts WHERE rowid IN (SELECT fts_rowid FROM chunk_rows WHERE chunk_id = ?)",
    ).bind(id),
    env.DB.prepare("DELETE FROM chunk_rows WHERE chunk_id = ?").bind(id),
  ]);
}

// 1ドキュメント（namespace + file）のチャンクを削除する。
export function deleteDocumentChunkStatements(
  env: Env,
  namespace: string,
  file: string,
): D1PreparedStatement[] {
  return [
    env.DB.prepare(
      "DELETE FROM chunks_fts WHERE rowid IN (SELECT fts_rowid FROM chunk_rows WHERE namespace = ? AND file = ?)",
    ).bind(namespace, file),
    env.DB.prepare(
      "DELETE FROM chunk_rows WHERE namespace = ? AND file = ?",
    ).bind(namespace, file),
  ];
}

// namespace全体のチャンクを削除する。
export function deleteNamespaceChunkStatements(
  env: Env,
  namespace: string,
): D1PreparedStatement[] {
  return [
    env.DB.prepare(
      "DELETE FROM chunks_fts WHERE rowid IN (SELECT fts_rowid FROM chunk_rows WHERE namespace = ?)",
    ).bind(namespace),
    env.DB.prepare("DELETE FROM chunk_rows WHERE namespace = ?").bind(
      namespace,
    ),
  ];
}

export async function listChunkIds(
  env: Env,
  namespace: string,
  file?: string,
): Promise<string[]> {
  const res =
    file === undefined
      ? await env.DB.prepare(
          "SELECT chunk_id FROM chunk_rows WHERE namespace = ?",
        )
          .bind(namespace)
          .all<{ chunk_id: string }>()
      : await env.DB.prepare(
          "SELECT chunk_id FROM chunk_rows WHERE namespace = ? AND file = ?",
        )
          .bind(namespace, file)
          .all<{ chunk_id: string }>();
  return (res.results ?? []).map((r) => r.chunk_id);
}

// 1ドキュメントのチャンクの本文を、chunk_idつきで読む（FTS本体はrowid参照）。
export async function readDocumentChunks(
  env: Env,
  namespace: string,
  file: string,
): Promise<Array<{ chunk_id: string; body: string }>> {
  const res = await env.DB.prepare(
    "SELECT r.chunk_id AS chunk_id, f.body AS body FROM chunk_rows r JOIN chunks_fts f ON f.rowid = r.fts_rowid WHERE r.namespace = ? AND r.file = ?",
  )
    .bind(namespace, file)
    .all<{ chunk_id: string; body: string }>();
  return res.results ?? [];
}

// グループ単位でD1のbatch（1往復・1トランザクション）にまとめて実行する。1グループは分割しない
// （putChunkStatementsのように、隣り合う文の順序に意味があるものを1グループにする）。
export async function runStatementGroups(
  env: Env,
  groups: D1PreparedStatement[][],
  maxPerBatch = 50,
): Promise<void> {
  let current: D1PreparedStatement[] = [];
  const flush = async () => {
    if (current.length === 0) return;
    if (typeof env.DB.batch === "function") await env.DB.batch(current);
    else for (const s of current) await s.run();
    current = [];
  };
  for (const g of groups) {
    if (current.length + g.length > maxPerBatch) await flush();
    current.push(...g);
  }
  await flush();
}
