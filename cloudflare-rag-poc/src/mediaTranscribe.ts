import type { Env } from "./types";
import { generateContentWithParts } from "./embeddings";
import { uploadGeminiFile, waitForGeminiFileActive, deleteGeminiFile } from "./geminiFile";

const TRANSCRIBE_PROMPT =
  "この音声・動画の内容を日本語で文字起こししてください。話者や時刻の情報は不要で、発言内容のテキストのみを、できるだけ原文に忠実に出力してください。";

// 音声/動画ファイルの文字起こし（既存GAS _transcribeAudioVideoBlob_相当）。
// Gemini File APIに一度アップロードしてから参照する（インラインでは大きすぎるため）。
// 動画はGemini側での処理に時間がかかるため、ACTIVEになるまで待ってから呼び出す。
export async function transcribeAudioVideo(
  env: Env,
  bytes: ArrayBuffer,
  mimeType: string,
  displayName: string,
): Promise<string> {
  const file = await uploadGeminiFile(env, bytes, mimeType, displayName);
  try {
    const active = file.state === "ACTIVE" ? file : await waitForGeminiFileActive(env, file.name);
    const result = await generateContentWithParts(env, [
      { fileData: { mimeType: active.mimeType, fileUri: active.uri } },
      { text: TRANSCRIBE_PROMPT },
    ]);
    return result.text;
  } finally {
    await deleteGeminiFile(env, file.name);
  }
}

// YouTube動画の文字起こし（既存GAS adminKbImportYoutube相当）。GeminiはYouTube URLを
// 直接fileDataとして受け付けられるため、ダウンロード・アップロードは不要。
export async function transcribeYoutubeUrl(env: Env, youtubeUrl: string): Promise<string> {
  const result = await generateContentWithParts(env, [
    { fileData: { fileUri: youtubeUrl } },
    { text: TRANSCRIBE_PROMPT },
  ]);
  return result.text;
}
