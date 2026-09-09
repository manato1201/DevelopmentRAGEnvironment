import type { ChunkMetadata, Env } from "./types";
import { splitNamespacesByScope } from "./auth";

export interface RankedChunk {
  id: string;
  metadata: ChunkMetadata;
  score?: number;
}

// クエリ文字列をFTS5のMATCH構文として安全な形に変換する（2026-09-04追加）。
// trigramトークナイザはあくまで「トークン化」の方式であり、MATCH句の構文解析
// （フレーズの"、列指定の:、NOT/AND/ORの-や大文字キーワード、グルーピングの()）は
// トークナイザに関係なく常に効く。ユーザーの質問文をそのまま渡すと、ハイフンや
// コロンを含むごく普通の質問（例:「-fフラグの直し方」「比率: 3:1」）で
// `fts5: syntax error near ...`となり検索全体が失敗していた。
// 空白区切りの各語を個別に二重引用符で囲み（内部の"は""へエスケープ）、間は
// スペースのままにすることで、FTS5のデフォルトの「語ごとのAND」という意味は保ったまま、
// 各語の中身をリテラル文字列として扱わせ、構文エラーの原因になる記号を無害化する。
function escapeFtsQuery(query: string): string {
  const terms = query.trim().split(/\s+/).filter((t) => t.length > 0);
  if (terms.length === 0) return '""';
  return terms.map((t) => '"' + t.replace(/"/g, '""') + '"').join(" ");
}

// BM25キーワード検索（D1 FTS5、既存GAS _bm25SearchCandidates_相当）。
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
  const binds: unknown[] = [escapeFtsQuery(query), ...namespaces];

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

  // sharedとpersonalのベクトル検索・BM25検索は互いに独立しているため、全クエリ実行中
  // 毎回このパスを通ることを踏まえ、Promise.allで並列実行してレイテンシを縮める
  // （2026-09-04、逐次awaitになっていた不備を修正）。
  const [sharedVector, sharedBm25, personalVector, personalBm25] = await Promise.all([
    shared.length > 0
      ? env.VEC_SHARED.query(queryVector, { topK, filter: { namespace: { $in: shared } }, returnMetadata: "all" })
      : null,
    shared.length > 0 ? bm25Search(env, queryText, shared, null, topK) : [],
    personal.length > 0
      ? env.VEC_PERSONAL.query(queryVector, { topK, filter: { namespace: { $in: personal }, owner_user_id: userId }, returnMetadata: "all" })
      : null,
    personal.length > 0 ? bm25Search(env, queryText, personal, userId, topK) : [],
  ]);

  if (sharedVector) {
    vectorRanked.push(...sharedVector.matches.map((m) => ({ id: m.id, metadata: m.metadata as unknown as ChunkMetadata })));
  }
  bm25Ranked.push(...sharedBm25);
  if (personalVector) {
    vectorRanked.push(...personalVector.matches.map((m) => ({ id: m.id, metadata: m.metadata as unknown as ChunkMetadata })));
  }
  bm25Ranked.push(...personalBm25);

  return rrfMerge([vectorRanked, bm25Ranked]).slice(0, limit);
}
