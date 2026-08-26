import type { ChunkMetadata, Env } from "./types";
import { splitNamespacesByScope } from "./auth";

export interface RankedChunk {
  id: string;
  metadata: ChunkMetadata;
  score?: number;
}

// BM25キーワード検索（D1 FTS5、既存GAS _bm25SearchCandidates_相当）。
// trigramトークナイザなので、MATCH句にはクエリ文字列をそのまま渡せば良い
// （SQLite側で自動的に3文字の部分文字列に分解してマッチングする）。
async function bm25Search(
  env: Env,
  query: string,
  namespaces: string[],
  ownerUserId: string | null,
  limit: number,
): Promise<RankedChunk[]> {
  if (namespaces.length === 0) return [];

  const placeholders = namespaces.map(() => "?").join(",");
  let sql = `SELECT chunk_id, file, namespace, scope, owner_user_id, difficulty, body
             FROM chunks_fts
             WHERE chunks_fts MATCH ? AND namespace IN (${placeholders})`;
  const binds: unknown[] = [query, ...namespaces];

  if (ownerUserId) {
    sql += " AND owner_user_id = ?";
    binds.push(ownerUserId);
  }
  sql += " ORDER BY rank LIMIT ?";
  binds.push(limit);

  const res = await env.DB.prepare(sql)
    .bind(...binds)
    .all<{
      chunk_id: string;
      file: string;
      namespace: string;
      scope: "shared" | "personal";
      owner_user_id: string | null;
      difficulty: string | null;
      body: string;
    }>();

  return (res.results ?? []).map((r, i) => ({
    id: r.chunk_id,
    metadata: {
      file: r.file,
      namespace: r.namespace,
      scope: r.scope,
      owner_user_id: r.owner_user_id ?? undefined,
      difficulty: r.difficulty ?? undefined,
      chunk_index: i,
      text: r.body,
    },
  }));
}

// RRF（Reciprocal Rank Fusion）: 複数の検索結果の「順位」を統合する
// （既存GAS _rrfMerge_相当。k=60は一般的なデフォルト値）。
function rrfMerge(rankedLists: RankedChunk[][], k = 60): RankedChunk[] {
  const scoreById = new Map<string, { score: number; chunk: RankedChunk }>();
  for (const list of rankedLists) {
    list.forEach((chunk, rank) => {
      const contribution = 1 / (k + rank + 1);
      const existing = scoreById.get(chunk.id);
      if (existing) {
        existing.score += contribution;
      } else {
        scoreById.set(chunk.id, { score: contribution, chunk });
      }
    });
  }
  return Array.from(scoreById.values())
    .sort((a, b) => b.score - a.score)
    .map((e) => ({ ...e.chunk, score: e.score }));
}

// ベクトル検索（Vectorize）とBM25検索（D1 FTS5）を両方実行し、RRFで統合する。
// 既存GASのハイブリッド検索（ベクトル+BM25をRRFで統合）と同じ設計。
export async function hybridSearch(
  env: Env,
  queryVector: number[],
  queryText: string,
  namespaces: string[],
  userId: string,
  limit: number,
): Promise<RankedChunk[]> {
  const { shared, personal } = splitNamespacesByScope(namespaces);
  const vectorRanked: RankedChunk[] = [];
  const bm25Ranked: RankedChunk[] = [];

  // Vectorizeは returnMetadata:"all" 指定時、topKの上限が50件（呼び出し側の`retrieve()`で
  // 既に3倍した値をここでさらに3倍していたため、limitが大きいと簡単に上限を超えて
  // VECTOR_QUERY_ERROR(40025)になっていた。実際にlimit=8のクエリで発生・発覚した）。
  const topK = Math.min(limit * 3, 50);

  if (shared.length > 0) {
    const vRes = await env.VEC_SHARED.query(queryVector, {
      topK,
      filter: { namespace: { $in: shared } },
      returnMetadata: "all",
    });
    vectorRanked.push(
      ...vRes.matches.map((m) => ({
        id: m.id,
        metadata: m.metadata as unknown as ChunkMetadata,
      })),
    );
    bm25Ranked.push(
      ...(await bm25Search(env, queryText, shared, null, topK)),
    );
  }

  if (personal.length > 0) {
    const vRes = await env.VEC_PERSONAL.query(queryVector, {
      topK,
      filter: { namespace: { $in: personal }, owner_user_id: userId },
      returnMetadata: "all",
    });
    vectorRanked.push(
      ...vRes.matches.map((m) => ({
        id: m.id,
        metadata: m.metadata as unknown as ChunkMetadata,
      })),
    );
    bm25Ranked.push(
      ...(await bm25Search(env, queryText, personal, userId, topK)),
    );
  }

  return rrfMerge([vectorRanked, bm25Ranked]).slice(0, limit);
}
