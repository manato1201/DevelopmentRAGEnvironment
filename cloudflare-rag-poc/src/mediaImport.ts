import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId } from "./chunking";
import { extractTextFromPdf, extractTextFromDocx, extractTextFromPptx } from "./docExtract";
import { transcribeAudioVideo, transcribeYoutubeUrl } from "./mediaTranscribe";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation";

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

// POST /admin/kb/import-youtube — YouTube動画を文字起こしして登録する
// （既存GAS adminKbImportYoutube相当）。body: { namespace, youtubeUrl, title? }
export async function handleImportYoutube(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { namespace?: string; youtubeUrl?: string; title?: string };
  const namespace = (body.namespace || "").trim();
  const youtubeUrl = (body.youtubeUrl || "").trim();
  if (!namespace || !youtubeUrl) return jsonResponse(400, { error: "namespace と youtubeUrl は必須です" });

  const text = await transcribeYoutubeUrl(env, youtubeUrl);
  if (!text.trim()) return jsonResponse(400, { error: "文字起こし結果が空でした" });

  const title = (body.title || youtubeUrl).trim();
  const result = await ingestDocument(env, namespace, title, text, "manual");
  const opId = newOpId();
  const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
  await logKb(env, opId, namespace, "manual", title, "ok", `YouTube文字起こし登録: ${result.chunks}チャンク登録${skipNote}（${youtubeUrl}）`);

  return jsonResponse(200, { status: "ok", opId, title, chunks: result.chunks, skipped: result.skippedVectors.length });
}

// POST /admin/kb/upload-doc — PDF/DOCX/PPTX/音声/動画ファイルを直接アップロードして登録する
// （既存GAS adminKbUploadDoc相当）。Drive経由ではなく手元のファイルを登録したい場合に使う。
// body: { namespace, fileBase64, mimeType, fileName }
export async function handleUploadDoc(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as { namespace?: string; fileBase64?: string; mimeType?: string; fileName?: string };
  const namespace = (body.namespace || "").trim();
  const fileBase64 = body.fileBase64 || "";
  const mimeType = (body.mimeType || "").trim();
  const fileName = (body.fileName || "").trim();
  if (!namespace || !fileBase64 || !mimeType || !fileName) {
    return jsonResponse(400, { error: "namespace, fileBase64, mimeType, fileName は必須です" });
  }

  let bytes: ArrayBuffer;
  try {
    bytes = base64ToArrayBuffer(fileBase64);
  } catch {
    return jsonResponse(400, { error: "fileBase64のデコードに失敗しました" });
  }

  let text: string;
  try {
    if (mimeType === "application/pdf") text = await extractTextFromPdf(env, bytes, fileName);
    else if (mimeType === DOCX_MIME) text = await extractTextFromDocx(bytes);
    else if (mimeType === PPTX_MIME) text = await extractTextFromPptx(bytes);
    else if (mimeType.startsWith("audio/") || mimeType.startsWith("video/")) text = await transcribeAudioVideo(env, bytes, mimeType, fileName);
    else return jsonResponse(400, { error: `未対応のmimeTypeです: ${mimeType}` });
  } catch (err) {
    return jsonResponse(400, { error: `変換に失敗しました: ${err instanceof Error ? err.message : String(err)}` });
  }

  if (!text.trim()) return jsonResponse(400, { error: "本文を抽出できませんでした" });

  const result = await ingestDocument(env, namespace, fileName, text, "manual");
  const opId = newOpId();
  const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
  await logKb(env, opId, namespace, "manual", fileName, "ok", `アップロード登録: ${result.chunks}チャンク登録${skipNote}`);

  return jsonResponse(200, { status: "ok", opId, chunks: result.chunks, skipped: result.skippedVectors.length });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
