import type { Env } from "./types";

// Gemini File API（既存GAS _uploadBytesToGeminiFile_相当）。音声/動画のように
// インラインで渡すには大きすぎるデータをGemini側に一時アップロードし、generateContentから
// fileDataとして参照する。アップロードしたファイルはGoogle側で48時間後に自動削除されるが、
// 明示的にdeleteGeminiFile()で削除するのが望ましい。
// https://ai.google.dev/gemini-api/docs/files

const UPLOAD_BASE = "https://generativelanguage.googleapis.com/upload/v1beta/files";

export interface GeminiFile {
  name: string; // 例: "files/abc123"
  uri: string;
  mimeType: string;
  state: "PROCESSING" | "ACTIVE" | "FAILED" | string;
}

// resumable upload protocol：1) メタデータ付きでアップロードURLを取得 → 2) 実データを送る、の2段階
export async function uploadGeminiFile(
  env: Env,
  bytes: ArrayBuffer,
  mimeType: string,
  displayName: string,
): Promise<GeminiFile> {
  const startRes = await fetch(`${UPLOAD_BASE}?key=${env.GEMINI_API_KEY}`, {
    method: "POST",
    headers: {
      "X-Goog-Upload-Protocol": "resumable",
      "X-Goog-Upload-Command": "start",
      "X-Goog-Upload-Header-Content-Length": String(bytes.byteLength),
      "X-Goog-Upload-Header-Content-Type": mimeType,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ file: { display_name: displayName } }),
  });
  if (!startRes.ok) {
    throw new Error(`Gemini File APIアップロード開始エラー (${startRes.status}): ${await startRes.text()}`);
  }
  const uploadUrl = startRes.headers.get("X-Goog-Upload-URL");
  if (!uploadUrl) throw new Error("Gemini File APIからアップロードURLが返されませんでした");

  const uploadRes = await fetch(uploadUrl, {
    method: "POST",
    headers: {
      "Content-Length": String(bytes.byteLength),
      "X-Goog-Upload-Offset": "0",
      "X-Goog-Upload-Command": "upload, finalize",
    },
    body: bytes,
  });
  if (!uploadRes.ok) {
    throw new Error(`Gemini File APIアップロードエラー (${uploadRes.status}): ${await uploadRes.text()}`);
  }
  const data = (await uploadRes.json()) as { file: { name: string; uri: string; mimeType: string; state: string } };
  return data.file;
}

// 動画ファイルは処理に時間がかかりACTIVEになるまで待つ必要がある（既存GAS実装の
// ポーリング相当）。最大でおよそ waitMs 合計まで待機する。
export async function waitForGeminiFileActive(env: Env, name: string, waitMs = 60000): Promise<GeminiFile> {
  const start = Date.now();
  while (Date.now() - start < waitMs) {
    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/${name}?key=${env.GEMINI_API_KEY}`);
    if (!res.ok) throw new Error(`Gemini File API状態確認エラー (${res.status}): ${await res.text()}`);
    const file = (await res.json()) as GeminiFile;
    if (file.state === "ACTIVE") return file;
    if (file.state === "FAILED") throw new Error("Gemini側でのファイル処理に失敗しました");
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error("Gemini側でのファイル処理がタイムアウトしました（動画が長すぎる可能性があります）");
}

export async function deleteGeminiFile(env: Env, name: string): Promise<void> {
  await fetch(`https://generativelanguage.googleapis.com/v1beta/${name}?key=${env.GEMINI_API_KEY}`, {
    method: "DELETE",
  }).catch(() => {
    // 削除失敗は致命的ではない（48時間後に自動削除されるため）ので握りつぶす
  });
}
