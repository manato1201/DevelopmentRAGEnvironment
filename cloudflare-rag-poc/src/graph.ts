import type { AuthedUser, ChunkMetadata, Env } from "./types";
import { jsonResponse } from "./http";
import { resolveEffectiveNamespaces } from "./retrieve";
import { splitNamespacesByScope } from "./auth";

// GAS版の「グラフ」タブ（buildGraphData_/getGraphDataWithKey相当）に相当する、
// namespace横断の文書関係を可視化するためのデータを返す。
//
// 設計：各ファイルの「先頭チャンク（chunk_index=0）」のベクトルをVectorizeから
// まとめて取得し、コサイン類似度をWorker内で計算してエッジを作る。
// （ノードごとにVectorize.query()を呼ぶとサブリクエスト数が跳ね上がるため、
// 既存のKB同期で学んだ教訓を踏まえてこの方式にした）
//
// 2026-10-14: 表示ノードの上限を500にした（1000では描画・計算に時間がかかるようになったため）。
// 上限を超える場合は、先頭から切るのではなく、namespaceごとの文書数の比率に合わせて
// 各namespaceから抜き出す（最大剰余法。文書のあるnamespaceは最低1件は残す）。
// 抜き出しは chunk_id 順（ハッシュ由来なので偏りが無く、呼び出しごとに同じ結果になる）。
export const MAX_GRAPH_NODES = 500;
const DEFAULT_MAX_NODES = MAX_GRAPH_NODES;
const EDGE_THRESHOLD = 0.72;
const MAX_EDGES_PER_NODE = 5;
// Vectorize.getByIds()は1回あたり最大20件。20件ずつに分け、数本ずつ並列に呼ぶ。
const GET_BY_IDS_CHUNK = 20;
const GET_BY_IDS_PARALLEL = 4;

interface GraphNode {
  id: string;
  label: string;
  namespace: string;
  source?: string;
  size?: number;
  ingestedAt?: number;
}

interface GraphEdge {
  source: string;
  target: string;
  weight: number;
}

export interface NamespaceTotal {
  namespace: string;
  total: number;
}

// namespaceごとの文書数（total）の比率に合わせて、合計がmaxNodes以下になるよう枠（quota）を配る。
// 合計がmaxNodes以下なら全件。超える場合は最大剰余法で配分し、文書のあるnamespaceには
// 最低1件を保証する（namespace数がmaxNodesを超えるときは、文書数の多い順に1件ずつ）。
export function allocateQuotas(totals: NamespaceTotal[], maxNodes: number): Map<string, number> {
  const quotas = new Map<string, number>();
  const nonEmpty = totals.filter((t) => t.total > 0);
  const sum = nonEmpty.reduce((s, t) => s + t.total, 0);
  if (sum <= maxNodes) {
    nonEmpty.forEach((t) => quotas.set(t.namespace, t.total));
    return quotas;
  }
  if (nonEmpty.length >= maxNodes) {
    nonEmpty
      .slice()
      .sort((a, b) => b.total - a.total || a.namespace.localeCompare(b.namespace))
      .slice(0, maxNodes)
      .forEach((t) => quotas.set(t.namespace, 1));
    return quotas;
  }
  // 最低1件ずつを先に確保し、残りを比率で配る
  nonEmpty.forEach((t) => quotas.set(t.namespace, 1));
  const spare = maxNodes - nonEmpty.length;
  const room = nonEmpty.map((t) => ({ t, extra: t.total - 1 }));
  const roomSum = room.reduce((s, r) => s + r.extra, 0);
  const exact = room.map((r) => ({ ...r, share: roomSum > 0 ? (spare * r.extra) / roomSum : 0 }));
  let given = 0;
  exact.forEach((e) => {
    const base = Math.min(e.extra, Math.floor(e.share));
    quotas.set(e.t.namespace, 1 + base);
    given += base;
  });
  // 端数: 小数部分の大きい順に1件ずつ（余りがある namespace だけ）
  const byFraction = exact
    .map((e) => ({ e, frac: e.share - Math.floor(e.share) }))
    .sort((a, b) => b.frac - a.frac || b.e.t.total - a.e.t.total || a.e.t.namespace.localeCompare(b.e.t.namespace));
  for (const { e } of byFraction) {
    if (given >= spare) break;
    const current = quotas.get(e.t.namespace)!;
    if (current - 1 < e.extra) {
      quotas.set(e.t.namespace, current + 1);
      given++;
    }
  }
  return quotas;
}

// 長さ1に正規化したコピーを返す（コサイン類似度が内積になり、ペアごとの計算が軽くなる）。
function normalized(v: ArrayLike<number>): Float32Array {
  const out = new Float32Array(v.length);
  let norm = 0;
  for (let i = 0; i < v.length; i++) norm += v[i] * v[i];
  const inv = 1 / (Math.sqrt(norm) || 1);
  for (let i = 0; i < v.length; i++) out[i] = v[i] * inv;
  return out;
}

function dot(a: Float32Array, b: Float32Array): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}

function chunkArray<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

export async function handleGraph(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as {
    namespaces?: string[];
    maxNodes?: number;
  };
  const effective = resolveEffectiveNamespaces(user, body.namespaces);
  const requested = Number.isFinite(body.maxNodes) ? Math.floor(body.maxNodes as number) : DEFAULT_MAX_NODES;
  const maxNodes = Math.max(1, Math.min(requested, MAX_GRAPH_NODES));

  if (effective.length === 0) {
    return jsonResponse(200, { nodes: [], edges: [], totals: [], totalNodes: 0, status: "ok" });
  }

  const { shared, personal } = splitNamespacesByScope(effective);

  // 1) namespaceごとの文書数。kb_documents（namespaceにインデックス済み、1ドキュメント1行。
  //    migrations/0008）を使い、chunks_fts本体のフルスキャンを避ける。
  const totals: NamespaceTotal[] = [];
  if (shared.length > 0) {
    const placeholders = shared.map(() => "?").join(",");
    const res = await env.DB.prepare(
      `SELECT namespace, COUNT(*) AS total FROM kb_documents WHERE namespace IN (${placeholders}) GROUP BY namespace`,
    )
      .bind(...shared)
      .all<{ namespace: string; total: number }>();
    for (const r of res.results ?? []) totals.push({ namespace: r.namespace, total: r.total });
  }
  if (personal.length > 0) {
    const placeholders = personal.map(() => "?").join(",");
    const res = await env.DB.prepare(
      `SELECT namespace, COUNT(*) AS total FROM kb_documents WHERE namespace IN (${placeholders}) AND owner_user_id = ? GROUP BY namespace`,
    )
      .bind(...personal, user.userId)
      .all<{ namespace: string; total: number }>();
    for (const r of res.results ?? []) totals.push({ namespace: r.namespace, total: r.total });
  }
  const totalNodes = totals.reduce((s, t) => s + t.total, 0);
  if (totalNodes === 0) {
    return jsonResponse(200, { nodes: [], edges: [], totals: [], totalNodes: 0, status: "ok" });
  }

  // 2) 比率に合わせた枠を配り、各namespaceから抜き出す
  const quotas = allocateQuotas(totals, maxNodes);
  const nodes: GraphNode[] = [];
  const idsByScope: { shared: string[]; personal: string[] } = { shared: [], personal: [] };
  for (const [namespace, quota] of quotas) {
    if (quota <= 0) continue;
    const isPersonal = namespace.startsWith("personal:");
    const res = isPersonal
      ? await env.DB.prepare("SELECT chunk_id, file, namespace FROM kb_documents WHERE namespace = ? AND owner_user_id = ? ORDER BY chunk_id LIMIT ?")
          .bind(namespace, user.userId, quota)
          .all<{ chunk_id: string; file: string; namespace: string }>()
      : await env.DB.prepare("SELECT chunk_id, file, namespace FROM kb_documents WHERE namespace = ? ORDER BY chunk_id LIMIT ?")
          .bind(namespace, quota)
          .all<{ chunk_id: string; file: string; namespace: string }>();
    for (const r of res.results ?? []) {
      nodes.push({ id: r.chunk_id, label: r.file, namespace: r.namespace });
      (isPersonal ? idsByScope.personal : idsByScope.shared).push(r.chunk_id);
    }
  }

  // 3) ベクトルを取得（20件ずつ、数本ずつ並列）
  const vectorById = new Map<string, Float32Array>();
  const metadataById = new Map<string, ChunkMetadata>();
  async function fetchVectors(index: VectorizeIndex, ids: string[]): Promise<void> {
    const groups = chunkArray(ids, GET_BY_IDS_CHUNK);
    for (let i = 0; i < groups.length; i += GET_BY_IDS_PARALLEL) {
      const results = await Promise.all(groups.slice(i, i + GET_BY_IDS_PARALLEL).map((g) => index.getByIds(g)));
      for (const res of results) {
        for (const v of res) {
          vectorById.set(v.id, normalized(v.values as ArrayLike<number>));
          if (v.metadata) metadataById.set(v.id, v.metadata as unknown as ChunkMetadata);
        }
      }
    }
  }
  await fetchVectors(env.VEC_SHARED, idsByScope.shared);
  await fetchVectors(env.VEC_PERSONAL, idsByScope.personal);

  const validNodes = nodes.filter((n) => vectorById.has(n.id));
  for (const n of validNodes) {
    const meta = metadataById.get(n.id);
    if (meta) {
      n.source = meta.source;
      n.size = meta.size;
      n.ingestedAt = meta.ingested_at;
    }
  }

  // 4) エッジ（類似度が閾値以上の上位だけ）。無向グラフなので、同じペアは1本にまとめる。
  const edges: GraphEdge[] = [];
  const seen = new Set<string>();
  for (let i = 0; i < validNodes.length; i++) {
    const vi = vectorById.get(validNodes[i].id)!;
    const scored: Array<{ id: string; score: number }> = [];
    for (let j = 0; j < validNodes.length; j++) {
      if (i === j) continue;
      const score = dot(vi, vectorById.get(validNodes[j].id)!);
      if (score >= EDGE_THRESHOLD) scored.push({ id: validNodes[j].id, score });
    }
    scored.sort((a, b) => b.score - a.score);
    for (const s of scored.slice(0, MAX_EDGES_PER_NODE)) {
      const a = validNodes[i].id;
      const key = a < s.id ? `${a}|${s.id}` : `${s.id}|${a}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push({ source: a, target: s.id, weight: s.score });
    }
  }

  // 表示した数とnamespaceごとの内訳（凡例・件数表示用）
  const shownByNs = new Map<string, number>();
  for (const n of validNodes) shownByNs.set(n.namespace, (shownByNs.get(n.namespace) ?? 0) + 1);

  return jsonResponse(200, {
    nodes: validNodes,
    edges,
    status: "ok",
    truncated: totalNodes > validNodes.length,
    totalNodes,
    totals: totals
      .map((t) => ({ namespace: t.namespace, total: t.total, shown: shownByNs.get(t.namespace) ?? 0 }))
      .sort((a, b) => b.total - a.total),
  });
}
