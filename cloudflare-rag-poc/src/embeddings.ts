import type { Env } from "./types";

// Gemini Embedding API（要件通りGemini APIのみを使用。docs/cloud-local-unification-plan.md §5参照）
// https://ai.google.dev/api/embeddings
// text-embedding-004はGoogle側で廃止済み（2026-08-23確認：404 NOT_FOUND）。
// 後継のgemini-embedding-001はoutputDimensionalityを明示しないと3072次元で返ってくるため、
// Vectorizeインデックス（768次元で作成済み）と合わせて768を明示指定する。
const OUTPUT_DIMENSIONALITY = 768;

export async function embedText(env: Env, text: string): Promise<number[]> {
  const model = env.EMBEDDING_MODEL || "gemini-embedding-001";
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:embedContent?key=${env.GEMINI_API_KEY}`;

  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      content: { parts: [{ text }] },
      outputDimensionality: OUTPUT_DIMENSIONALITY,
    }),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Gemini embedding APIエラー (${res.status}): ${detail}`);
  }

  const data = (await res.json()) as { embedding?: { values?: number[] } };
  const values = data.embedding?.values;
  if (!values || !Array.isArray(values)) {
    throw new Error("Gemini embedding APIのレスポンス形式が想定と異なります");
  }
  return values;
}

// クエリのSHA-256ハッシュ（既存RAGAuditLogger仕様を踏襲：監査ログにクエリ本文を残さない）
export async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
