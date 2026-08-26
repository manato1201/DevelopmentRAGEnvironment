import type { AuthedUser, Env, KbSyncResult } from "./types";
import { requireAdmin } from "./auth";
import { getGoogleAccessToken } from "./googleAuth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId } from "./chunking";
import { extractTextFromPdf, extractTextFromDocx, extractTextFromPptx } from "./docExtract";
import { transcribeAudioVideo } from "./mediaTranscribe";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
// Workers isolateのメモリ上限（128MB）に対する安全マージンとして、ダウンロード時点で弾く上限
const MAX_DOWNLOAD_BYTES = 90 * 1024 * 1024;

const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly";
// Notion同期と同じ理由（Cloudflareのサブリクエスト数上限対策）でバッチ処理にしている。
const DEFAULT_BATCH_SIZE = 5;

interface DriveFile {
  id: string;
  name: string;
  mimeType: string;
}

async function listDriveFiles(token: string, folderId: string): Promise<DriveFile[]> {
  const files: DriveFile[] = [];
  let pageToken: string | undefined;

  do {
    const url = new URL("https://www.googleapis.com/drive/v3/files");
    url.searchParams.set("q", `'${folderId}' in parents and trashed = false`);
    url.searchParams.set("fields", "nextPageToken, files(id, name, mimeType)");
    url.searchParams.set("pageSize", "1000");
    if (pageToken) url.searchParams.set("pageToken", pageToken);

    const res = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`Drive files.list APIエラー (${res.status}): ${await res.text()}`);
    const data = (await res.json()) as { files: DriveFile[]; nextPageToken?: string };
    files.push(...data.files);
    pageToken = data.nextPageToken;
  } while (pageToken);

  return files;
}

// Googleドキュメント/プレーンテキスト/Markdownはテキストとして直接取得。
// PDF・DOCX・PPTXはバイナリをダウンロードしてから変換、音声/動画はGemini File API経由で
// 文字起こしする（既存GAS _convertBinaryBlobToText_・_transcribeAudioVideoBlob_相当、
// 2026-08-26追加。詳細は src/docExtract.ts, src/mediaTranscribe.ts 参照）。
async function extractDriveFileText(env: Env, token: string, file: DriveFile): Promise<string | null> {
  if (file.mimeType === "application/vnd.google-apps.document") {
    const res = await fetch(`https://www.googleapis.com/drive/v3/files/${file.id}/export?mimeType=text/plain`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`Drive export APIエラー (${res.status}): ${await res.text()}`);
    return await res.text();
  }
  if (file.mimeType === "text/plain" || file.mimeType === "text/markdown") {
    const res = await fetch(`https://www.googleapis.com/drive/v3/files/${file.id}?alt=media`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`Drive download APIエラー (${res.status}): ${await res.text()}`);
    return await res.text();
  }

  const isPdf = file.mimeType === "application/pdf";
  const isDocx = file.mimeType === DOCX_MIME;
  const isPptx = file.mimeType === PPTX_MIME;
  const isAudioVideo = file.mimeType.startsWith("audio/") || file.mimeType.startsWith("video/");
  if (isPdf || isDocx || isPptx || isAudioVideo) {
    const res = await fetch(`https://www.googleapis.com/drive/v3/files/${file.id}?alt=media`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`Drive download APIエラー (${res.status}): ${await res.text()}`);
    // Content-Lengthを事前に見て、Workers isolateのメモリ上限（128MB）を超えそうな
    // ファイルはダウンロード自体を諦める。実際に大きいPPTXで"Memory limit exceeded
    // before EOF"（arrayBuffer()途中でのOOM）が発生したため、バッファ前に弾く対策（2026-08-26）。
    const contentLength = Number(res.headers.get("content-length") || 0);
    if (contentLength > MAX_DOWNLOAD_BYTES) {
      throw new Error(`ファイルが大きすぎます（${Math.round(contentLength / 1024 / 1024)}MB）。現在は約${MAX_DOWNLOAD_BYTES / 1024 / 1024}MBまでに対応しています`);
    }
    const bytes = await res.arrayBuffer();
    if (isPdf) return extractTextFromPdf(env, bytes, file.name);
    if (isDocx) return extractTextFromDocx(bytes);
    if (isPptx) return extractTextFromPptx(bytes);
    return transcribeAudioVideo(env, bytes, file.mimeType, file.name);
  }

  return null; // 未対応mimeType（画像等）
}

// POST /admin/sync/drive — 既存GAS syncDriveToSheets相当（PDF/DOCX等の変換・音声動画の文字起こしは未対応）。
// Notion同期と同じバッチ処理方式。
// body: { namespace, startIndex?（省略時0）, batchSize?（省略時5）, opId?（継続呼び出し時に指定） }
export async function handleSyncDrive(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);

  const body = (await req.json()) as { namespace?: string; startIndex?: number; batchSize?: number; opId?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  const source = await env.DB.prepare("SELECT drive_folder_id FROM kb_sources WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ drive_folder_id: string | null }>();
  if (!source?.drive_folder_id) {
    return jsonResponse(400, { error: `namespace(${namespace})にDriveフォルダIDが設定されていません。先に /admin/kb/set-source で設定してください` });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();

  const token = await getGoogleAccessToken(env, DRIVE_SCOPE);
  const files = await listDriveFiles(token, source.drive_folder_id);
  const batch = files.slice(startIndex, startIndex + batchSize);

  let documents = 0;
  let chunks = 0;
  const skipped: Array<{ file: string; reason: string }> = [];

  for (const file of batch) {
    try {
      const text = await extractDriveFileText(env, token, file);
      if (text === null) {
        skipped.push({ file: file.name, reason: `未対応のmimeType: ${file.mimeType}` });
        await logKb(env, opId, namespace, "drive", file.name, "skipped", `未対応mimeType: ${file.mimeType}`);
        continue;
      }
      if (!text.trim()) {
        skipped.push({ file: file.name, reason: "本文が空です" });
        await logKb(env, opId, namespace, "drive", file.name, "skipped", "本文が空");
        continue;
      }
      const result = await ingestDocument(env, namespace, file.name, text, "drive");
      chunks += result.chunks;
      documents += 1;
      const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
      await logKb(env, opId, namespace, "drive", file.name, "ok", `${result.chunks}チャンク登録${skipNote}`);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: file.name, reason: detail });
      await logKb(env, opId, namespace, "drive", file.name, "error", detail);
    }
  }

  const nextIndex = startIndex + batchSize < files.length ? startIndex + batchSize : null;

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    totalFiles: files.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  } satisfies KbSyncResult & { totalFiles: number; processedRange: [number, number]; nextIndex: number | null });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
