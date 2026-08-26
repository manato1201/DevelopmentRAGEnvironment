import type { AuthedUser, ChunkMetadata, Env } from "./types";
import { embedText, sha256Hex } from "./embeddings";

// VectorizeのベクトルIDは64バイト上限。日本語ファイル名をそのままIDに使うと超過しうるため
// （src/kbIngest.tsと同じ理由）、ハッシュベースの固定長IDにする。
async function makeChunkId(namespaceId: string, file: string, chunkIndex: number): Promise<string> {
  const hash = (await sha256Hex(`${namespaceId}::${file}`)).slice(0, 40);
  return `${hash}:${chunkIndex}`;
}

// POST /ingest — 検証用の投入エンドポイント。本番のNotion/ChromaDB連携は一切行わない。
// 動作確認用に少数のテキストチャンクをGeminiで埋め込み、Vectorize（意味検索）と
// D1 FTS5（キーワード検索）の両方に書き込む。
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
  const ftsRows: Array<{ chunk_id: string; file: string; namespace: string; scope: string; owner_user_id: string | null; difficulty: string | null; body: string }> = [];

  for (let i = 0; i < body.chunks.length; i++) {
    const c = body.chunks[i];
    const isPersonal = c.namespace.startsWith("personal:");

    if (isPersonal && c.namespace !== `personal:${user.userId}`) {
      return jsonResponse(403, { error: `他ユーザーの個人スコープ(${c.namespace})へは書き込めません` });
    }

    const values = await embedText(env, c.text);
    const chunkId = await makeChunkId(c.namespace, c.file, i);
    const metadata: ChunkMetadata = {
      file: c.file,
      namespace: c.namespace,
      scope: isPersonal ? "personal" : "shared",
      owner_user_id: isPersonal ? user.userId : undefined,
      difficulty: c.difficulty,
      chunk_index: i,
      text: c.text,
      source: "manual",
      ingested_at: Math.floor(Date.now() / 1000),
    };
    const vector = { id: chunkId, values, metadata };

    if (isPersonal) personalVectors.push(vector);
    else sharedVectors.push(vector);

    ftsRows.push({
      chunk_id: chunkId,
      file: c.file,
      namespace: c.namespace,
      scope: metadata.scope,
      owner_user_id: metadata.owner_user_id ?? null,
      difficulty: c.difficulty ?? null,
      body: c.text,
    });
  }

  if (sharedVectors.length > 0) {
    await env.VEC_SHARED.upsert(sharedVectors.map((v) => ({ id: v.id, values: v.values, metadata: v.metadata as unknown as Record<string, VectorizeVectorMetadataValue> })));
  }
  if (personalVectors.length > 0) {
    await env.VEC_PERSONAL.upsert(personalVectors.map((v) => ({ id: v.id, values: v.values, metadata: v.metadata as unknown as Record<string, VectorizeVectorMetadataValue> })));
  }

  // 既存チャンクの再投入（テスト等）に備え、同じchunk_idのFTS行は一度消してから入れ直す
  for (const row of ftsRows) {
    await env.DB.prepare("DELETE FROM chunks_fts WHERE chunk_id = ?").bind(row.chunk_id).run();
    await env.DB.prepare(
      "INSERT INTO chunks_fts (chunk_id, file, namespace, scope, owner_user_id, difficulty, body) VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
      .bind(row.chunk_id, row.file, row.namespace, row.scope, row.owner_user_id, row.difficulty, row.body)
      .run();
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
