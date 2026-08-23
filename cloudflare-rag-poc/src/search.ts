import type { AuthedUser, ChunkMetadata, Env, SearchRequest, SearchResponse, SourceEntry } from "./types";
import { embedText, sha256Hex } from "./embeddings";
import { splitNamespacesByScope } from "./auth";

// POST /search — 既存 rag_local_bridge.py の /search と同一契約（docs/cloud-local-unification-plan.md §8.3）
export async function handleSearch(
  req: Request,
  env: Env,
  user: AuthedUser
): Promise<Response> {
  const body = (await req.json()) as SearchRequest;
  const query = (body.query || "").trim();
  const limit = body.limit ?? 6;
  const level = body.level || "";

  if (!query) {
    return jsonResponse(400, { error: "query は必須です" });
  }

  // 要求されたnamespaceと、ユーザーが実際にアクセス許可されているnamespaceの積集合を取る
  // （§6-1: アクセス制御を通過しない範囲のインデックスには問い合わせない）
  const requested = body.namespaces && body.namespaces.length > 0 ? body.namespaces : user.allowedNamespaces;
  const effective = requested.filter((ns) => user.allowedNamespaces.includes(ns));

  if (effective.length === 0) {
    return jsonResponse(200, { texts: ["（アクセス可能なnamespaceがありません）"], sources: [], status: "ok" } satisfies SearchResponse);
  }

  const { shared, personal } = splitNamespacesByScope(effective);

  const queryVector = await embedText(env, query);

  const matches: Array<{ score: number; metadata: ChunkMetadata }> = [];

  if (shared.length > 0) {
    const res = await env.VEC_SHARED.query(queryVector, {
      topK: limit * 3,
      filter: { namespace: { $in: shared } },
      returnMetadata: "all",
    });
    for (const m of res.matches) {
      matches.push({ score: m.score, metadata: m.metadata as unknown as ChunkMetadata });
    }
  }

  if (personal.length > 0) {
    // 個人スコープはowner_user_idも合わせてフィルタし、他ユーザーの個人データに
    // 絶対に到達しないことをクエリレベルでも保証する（namespace一致だけに頼らない）
    const res = await env.VEC_PERSONAL.query(queryVector, {
      topK: limit * 3,
      filter: { namespace: { $in: personal }, owner_user_id: user.userId },
      returnMetadata: "all",
    });
    for (const m of res.matches) {
      matches.push({ score: m.score, metadata: m.metadata as unknown as ChunkMetadata });
    }
  }

  // レベルフィルタ（Phase1レベリング。difficulty未設定は既存仕様通り通過させる）
  const filtered = level
    ? matches.filter((m) => !m.metadata.difficulty || m.metadata.difficulty === level)
    : matches;

  filtered.sort((a, b) => b.score - a.score);
  const top = filtered.slice(0, limit);

  const texts: string[] = [`検索結果（${top.length} 件）:`];
  const sources: SourceEntry[] = [];
  top.forEach((m, i) => {
    texts.push(`\n[${i + 1}] ファイル: ${m.metadata.file}\n${m.metadata.text}`);
    sources.push({
      file: m.metadata.file,
      namespace: m.metadata.namespace,
      difficulty: m.metadata.difficulty,
      score: m.score,
    });
  });

  const queryHash = await sha256Hex(query);
  await env.DB.prepare(
    "INSERT INTO audit_log (user_id, namespace_id, query_hash, difficulty, result_count, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
  )
    .bind(user.userId, effective.join(","), queryHash, level || null, sources.length, null, Math.floor(Date.now() / 1000))
    .run();

  return jsonResponse(200, { texts, sources, status: "ok" } satisfies SearchResponse);
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
