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

export interface GenerateResult {
  text: string;
  promptTokens: number;
  candidateTokens: number;
}

// Gemini APIの1パート（テキスト／インラインバイナリ／アップロード済みファイル参照・YouTube URL）
export type GeminiPart =
  | { text: string }
  | { inlineData: { mimeType: string; data: string } }
  | { fileData: { mimeType?: string; fileUri: string } };

// Gemini generateContent（HyDE仮回答生成・最終回答生成・PDF/音声/動画の理解に共用。既存GAS callGemini_相当）。
// テキストのみの呼び出しは generateContent() から、PDF/音声/動画/YouTubeなどマルチモーダルな
// 呼び出しは generateContentWithParts() から使う（下記のPDF/DOCX/音声動画/YouTube変換で利用）。
export async function generateContentWithParts(env: Env, parts: GeminiPart[]): Promise<GenerateResult> {
  const model = env.GENERATION_MODEL || "gemini-flash-latest";
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${env.GEMINI_API_KEY}`;

  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      contents: [{ parts }],
    }),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Gemini generateContent APIエラー (${res.status}): ${detail}`);
  }

  const data = (await res.json()) as {
    candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
    usageMetadata?: { promptTokenCount?: number; candidatesTokenCount?: number };
  };
  const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
  if (typeof text !== "string") {
    throw new Error("Gemini generateContent APIのレスポンス形式が想定と異なります");
  }
  return {
    text,
    promptTokens: data.usageMetadata?.promptTokenCount ?? 0,
    candidateTokens: data.usageMetadata?.candidatesTokenCount ?? 0,
  };
}

async function generateContent(env: Env, prompt: string): Promise<GenerateResult> {
  return generateContentWithParts(env, [{ text: prompt }]);
}

// HyDE（Hypothetical Document Embeddings）: 質問文の代わりに「こう答えるだろう」という
// 仮の回答を先に生成し、それを埋め込みに使うことで、言い回しギャップを補正する
// （既存GAS hydeExpand_相当。docs/glossary.md「HyDE」参照）。
export async function hydeExpand(env: Env, query: string): Promise<GenerateResult> {
  const prompt = `次の質問に対して、実際の回答であるかのように簡潔な仮の説明文を1〜3文で書いてください。わからない場合でも、それらしい説明を書いてください。質問: ${query}`;
  return generateContent(env, prompt);
}

// 検索結果を踏まえた最終回答生成（既存GAS ragQueryInternal_の回答生成部分に相当）
export async function generateAnswer(
  env: Env,
  query: string,
  contextTexts: string[],
  history: Array<{ role: string; content: string }>
): Promise<GenerateResult> {
  const historyText = history.length > 0
    ? "これまでの会話:\n" + history.map((h) => `${h.role}: ${h.content}`).join("\n") + "\n\n"
    : "";
  const prompt =
    `${historyText}以下の検索結果だけを根拠に、質問に日本語で答えてください。` +
    `根拠にした情報には必ず番号（[1]や[2]など、検索結果に付いている番号）を付けて示してください。` +
    `検索結果に答えがない場合は、正直に「わかりません」と答えてください。\n\n` +
    `${contextTexts.join("\n")}\n\n質問: ${query}`;
  return generateContent(env, prompt);
}
