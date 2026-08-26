import type { AuthedUser, ChunkMetadata, Env } from "./types";
import { resolveEffectiveNamespaces } from "./retrieve";
import { splitNamespacesByScope } from "./auth";

// GAS版の「グラフ」タブ（buildGraphData_/getGraphDataWithKey相当）に相当する、
// namespace横断の文書関係を可視化するためのデータを返す。
//
// 設計：各ファイルの「先頭チャンク（chunk_index=0）」のベクトルをVectorizeから
// 1回のgetByIdsでまとめて取得し、コサイン類似度をWorker内で計算してエッジを作る。
// （ノードごとにVectorize.query()を呼ぶとサブリクエスト数が跳ね上がるため、
// 既存のKB同期で学んだ教訓を踏まえてこの方式にした）
const DEFAULT_MAX_NODES = 150;
const EDGE_THRESHOLD = 0.72;
const MAX_EDGES_PER_NODE = 5;

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

function cosineSimilarity(a: ArrayLike<number>, b: ArrayLike<number>): number {
  let dot = 0,
    na = 0,
    nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) || 1);
}

export async function handleGraph(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as {
    namespaces?: string[];
    maxNodes?: number;
  };
  const effective = resolveEffectiveNamespaces(user, body.namespaces);
  const maxNodes = Math.min(body.maxNodes ?? DEFAULT_MAX_NODES, 300);

  if (effective.length === 0) {
    return jsonResponse(200, { nodes: [], edges: [], status: "ok" });
  }

  const { shared, personal } = splitNamespacesByScope(effective);
  const nodes: GraphNode[] = [];
  const idsByScope: { shared: string[]; personal: string[] } = {
    shared: [],
    personal: [],
  };

  if (shared.length > 0) {
    const placeholders = shared.map(() => "?").join(",");
    const res = await env.DB.prepare(
      `SELECT chunk_id, file, namespace FROM chunks_fts WHERE namespace IN (${placeholders}) AND chunk_id LIKE '%:0' LIMIT ?`,
    )
      .bind(...shared, maxNodes)
      .all<{ chunk_id: string; file: string; namespace: string }>();
    for (const r of res.results ?? []) {
      nodes.push({ id: r.chunk_id, label: r.file, namespace: r.namespace });
      idsByScope.shared.push(r.chunk_id);
    }
  }

  if (personal.length > 0 && nodes.length < maxNodes) {
    const placeholders = personal.map(() => "?").join(",");
    const res = await env.DB.prepare(
      `SELECT chunk_id, file, namespace FROM chunks_fts WHERE namespace IN (${placeholders}) AND owner_user_id = ? AND chunk_id LIKE '%:0' LIMIT ?`,
    )
      .bind(...personal, user.userId, maxNodes - nodes.length)
      .all<{ chunk_id: string; file: string; namespace: string }>();
    for (const r of res.results ?? []) {
      nodes.push({ id: r.chunk_id, label: r.file, namespace: r.namespace });
      idsByScope.personal.push(r.chunk_id);
    }
  }

  if (nodes.length === 0) {
    return jsonResponse(200, { nodes: [], edges: [], status: "ok" });
  }

  // VectorizeIndex.getByIds()は1回あたり最大20件までしか受け付けないため、
  // 20件ずつに分割して呼ぶ（それでもノードごとにquery()するより遥かに少ない回数で済む）
  const GET_BY_IDS_CHUNK = 20;
  function chunk<T>(arr: T[], size: number): T[][] {
    const out: T[][] = [];
    for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
    return out;
  }

  const vectorById = new Map<string, VectorFloatArray | number[]>();
  const metadataById = new Map<string, ChunkMetadata>();
  for (const idsChunk of chunk(idsByScope.shared, GET_BY_IDS_CHUNK)) {
    const res = await env.VEC_SHARED.getByIds(idsChunk);
    for (const v of res) {
      vectorById.set(v.id, v.values);
      if (v.metadata)
        metadataById.set(v.id, v.metadata as unknown as ChunkMetadata);
    }
  }
  for (const idsChunk of chunk(idsByScope.personal, GET_BY_IDS_CHUNK)) {
    const res = await env.VEC_PERSONAL.getByIds(idsChunk);
    for (const v of res) {
      vectorById.set(v.id, v.values);
      if (v.metadata)
        metadataById.set(v.id, v.metadata as unknown as ChunkMetadata);
    }
  }

  const edges: GraphEdge[] = [];
  const validNodes = nodes.filter((n) => vectorById.has(n.id));
  for (const n of validNodes) {
    const meta = metadataById.get(n.id);
    if (meta) {
      n.source = meta.source;
      n.size = meta.size;
      n.ingestedAt = meta.ingested_at;
    }
  }

  for (let i = 0; i < validNodes.length; i++) {
    const scored: Array<{ id: string; score: number }> = [];
    const vi = vectorById.get(validNodes[i].id)!;
    for (let j = 0; j < validNodes.length; j++) {
      if (i === j) continue;
      const vj = vectorById.get(validNodes[j].id)!;
      const score = cosineSimilarity(vi, vj);
      if (score >= EDGE_THRESHOLD) scored.push({ id: validNodes[j].id, score });
    }
    scored.sort((a, b) => b.score - a.score);
    for (const s of scored.slice(0, MAX_EDGES_PER_NODE)) {
      // 無向グラフとして扱うため、逆向きの重複エッジは足さない
      const exists = edges.some(
        (e) =>
          (e.source === validNodes[i].id && e.target === s.id) ||
          (e.source === s.id && e.target === validNodes[i].id),
      );
      if (!exists)
        edges.push({ source: validNodes[i].id, target: s.id, weight: s.score });
    }
  }

  return jsonResponse(200, {
    nodes: validNodes,
    edges,
    status: "ok",
    truncated: nodes.length >= maxNodes,
  });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
