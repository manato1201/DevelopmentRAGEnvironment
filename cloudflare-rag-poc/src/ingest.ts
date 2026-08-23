import type { AuthedUser, ChunkMetadata, Env } from "./types";
import { embedText } from "./embeddings";

// POST /ingest — 検証用の投入エンドポイント。本番のNotion/ChromaDB連携は一切行わない。
// 動作確認用に少数のテキストチャンクをGeminiで埋め込み、Vectorizeへ書き込む。
//
// body: { chunks: [{ text, file, namespace, difficulty? }] }
// namespaceが "personal:" で始まる場合はVEC_PERSONALへ、それ以外はVEC_SHAREDへ書き込む。
// 個人スコープへの書き込みは、リクエスト元ユーザー自身のnamespace（personal:<userId>）以外は拒否する
// （§6-1: 他人の個人スコープへ書き込めてしまうと物理分離の意味がなくなるため）。
export async function handleIngest(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as {
    chunks: Array<{ text: string; file: string; namespace: string; difficulty?: string }>;
  };

  if (!Array.isArray(body.chunks) || body.chunks.length === 0) {
    return jsonResponse(400, { error: "chunks は必須です（配列）" });
  }

  const sharedVectors: Array<{ id: string; values: number[]; metadata: ChunkMetadata }> = [];
  const personalVectors: Array<{ id: string; values: number[]; metadata: ChunkMetadata }> = [];

  for (let i = 0; i < body.chunks.length; i++) {
    const c = body.chunks[i];
    const isPersonal = c.namespace.startsWith("personal:");

    if (isPersonal && c.namespace !== `personal:${user.userId}`) {
      return jsonResponse(403, { error: `他ユーザーの個人スコープ(${c.namespace})へは書き込めません` });
    }

    const values = await embedText(env, c.text);
    const metadata: ChunkMetadata = {
      file: c.file,
      namespace: c.namespace,
      scope: isPersonal ? "personal" : "shared",
      owner_user_id: isPersonal ? user.userId : undefined,
      difficulty: c.difficulty,
      chunk_index: i,
      text: c.text,
    };
    const vector = { id: `${c.namespace}:${c.file}:${i}`, values, metadata: metadata as unknown as Record<string, VectorizeVectorMetadataValue> };

    if (isPersonal) personalVectors.push({ ...vector, metadata });
    else sharedVectors.push({ ...vector, metadata });
  }

  if (sharedVectors.length > 0) {
    await env.VEC_SHARED.upsert(sharedVectors.map((v) => ({ id: v.id, values: v.values, metadata: v.metadata as unknown as Record<string, VectorizeVectorMetadataValue> })));
  }
  if (personalVectors.length > 0) {
    await env.VEC_PERSONAL.upsert(personalVectors.map((v) => ({ id: v.id, values: v.values, metadata: v.metadata as unknown as Record<string, VectorizeVectorMetadataValue> })));
  }

  return jsonResponse(200, {
    status: "ok",
    inserted: { shared: sharedVectors.length, personal: personalVectors.length },
  });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
