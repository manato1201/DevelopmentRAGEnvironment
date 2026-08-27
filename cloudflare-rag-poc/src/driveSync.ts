import type { AuthedUser, Env, KbSyncResult } from "./types";
import { requireAdmin } from "./auth";
import { getGoogleAccessToken } from "./googleAuth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId, withAbortTimeout } from "./chunking";

// PDFのFile APIアップロード＋動画のACTIVE待ちポーリングを含むと1件で数十秒かかることがあり、
// これがCloudflareエッジのリクエスト打ち切り（非JSON応答・HTTP 503）を引き起こしていた
// （2026-08-27、batchSize=1でも発生を確認）。1件あたりの処理に上限を設け、超過分は
// そのファイルだけスキップしてバッチ全体は正常応答できるようにする。
const PER_FILE_TIMEOUT_MS = 45_000;
import { extractTextFromPdf, extractTextFromDocxSource, extractTextFromPptxSource } from "./docExtract";
import type { ByteRangeSource } from "./docExtract";
import { transcribeAudioVideo } from "./mediaTranscribe";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
// Workers isolateのメモリ上限（128MB）に対する安全マージンとして、ダウンロード時点で弾く上限
const MAX_DOWNLOAD_BYTES = 90 * 1024 * 1024;

// Content-Lengthヘッダーに頼らず、実際に受信したバイト数をストリーミングで数えながら
// 上限を超えた時点で読み込みを打ち切る。Drive の alt=media レスポンスがchunked転送で
// Content-Lengthを返さないことがあり、ヘッダーだけのチェックでは大きいPPTXの
// "Memory limit exceeded before EOF"を防げなかった（実機で確認、2026-08-27）ための対策。
async function readBodyWithLimit(res: Response, maxBytes: number): Promise<ArrayBuffer> {
  if (!res.body) return res.arrayBuffer();
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        throw new Error(`ファイルが大きすぎます（${Math.round(total / 1024 / 1024)}MB超）。現在は約${Math.round(maxBytes / 1024 / 1024)}MBまでに対応しています`);
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const combined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return combined.buffer;
}

const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly";
// Notion同期と同じ理由（Cloudflareのサブリクエスト数上限対策）でバッチ処理にしている。
const DEFAULT_BATCH_SIZE = 5;

interface DriveFile {
  id: string;
  name: string;
  mimeType: string;
  size?: string; // Google Drive APIは文字列で返す（bytes）。Googleネイティブ形式は無し
}

// サイズの小さい順に並べ替えて返す（2026-08-27追加）。小さいファイルから先に処理することで、
// バッチの先頭で大きい/重い変換に時間を取られて後続がタイムアウトする事態を避け、
// 同じ処理時間内でより多くのファイルを確実に登録できるようにする。サイズ不明
// （Googleネイティブ形式のドキュメント等）は「小さい」側として先頭寄りに扱う。
async function listDriveFiles(token: string, folderId: string): Promise<DriveFile[]> {
  const files: DriveFile[] = [];
  let pageToken: string | undefined;

  do {
    const url = new URL("https://www.googleapis.com/drive/v3/files");
    url.searchParams.set("q", `'${folderId}' in parents and trashed = false`);
    url.searchParams.set("fields", "nextPageToken, files(id, name, mimeType, size)");
    url.searchParams.set("pageSize", "1000");
    if (pageToken) url.searchParams.set("pageToken", pageToken);

    const res = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`Drive files.list APIエラー (${res.status}): ${await res.text()}`);
    const data = (await res.json()) as { files: DriveFile[]; nextPageToken?: string };
    files.push(...data.files);
    pageToken = data.nextPageToken;
  } while (pageToken);

  files.sort((a, b) => Number(a.size || 0) - Number(b.size || 0));
  return files;
}

// Googleドキュメント/プレーンテキスト/Markdownはテキストとして直接取得。
// PDF・DOCX・PPTXはバイナリをダウンロードしてから変換、音声/動画はGemini File API経由で
// 文字起こしする（既存GAS _convertBinaryBlobToText_・_transcribeAudioVideoBlob_相当、
// 2026-08-26追加。詳細は src/docExtract.ts, src/mediaTranscribe.ts 参照）。
async function extractDriveFileText(env: Env, token: string, file: DriveFile, signal: AbortSignal): Promise<string | null> {
  if (file.mimeType === "application/vnd.google-apps.document") {
    const res = await fetch(`https://www.googleapis.com/drive/v3/files/${file.id}/export?mimeType=text/plain`, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    });
    if (!res.ok) throw new Error(`Drive export APIエラー (${res.status}): ${await res.text()}`);
    return await res.text();
  }
  if (file.mimeType === "text/plain" || file.mimeType === "text/markdown") {
    const res = await fetch(`https://www.googleapis.com/drive/v3/files/${file.id}?alt=media`, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    });
    if (!res.ok) throw new Error(`Drive download APIエラー (${res.status}): ${await res.text()}`);
    return await res.text();
  }

  const isPdf = file.mimeType === "application/pdf";
  const isDocx = file.mimeType === DOCX_MIME;
  const isPptx = file.mimeType === PPTX_MIME;
  const isAudioVideo = file.mimeType.startsWith("audio/") || file.mimeType.startsWith("video/");

  // DOCX/PPTXはファイル全体をダウンロードせず、HTTP RangeでZIPの必要な部分
  // （central directory・対象XMLエントリ）だけを取得する。容量の大半を占める埋め込み
  // 動画/画像に触れないため、ファイルサイズの実質的な上限が無くなる（2026-08-27）。
  if (isDocx || isPptx) {
    const totalSize = await getDriveFileSize(token, file.id, signal);
    const source = driveRangeSource(token, file.id, totalSize, signal);
    return isDocx ? extractTextFromDocxSource(source) : extractTextFromPptxSource(source);
  }

  if (isPdf || isAudioVideo) {
    const res = await fetch(`https://www.googleapis.com/drive/v3/files/${file.id}?alt=media`, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    });
    if (!res.ok) throw new Error(`Drive download APIエラー (${res.status}): ${await res.text()}`);
    const bytes = await readBodyWithLimit(res, MAX_DOWNLOAD_BYTES);
    if (isPdf) return extractTextFromPdf(env, bytes, file.name);
    return transcribeAudioVideo(env, bytes, file.mimeType, file.name);
  }

  return null; // 未対応mimeType（画像等）
}

// ファイルサイズはDrive files.getのメタデータ（fields=size）で取得する。
// alt=mediaのレスポンスヘッダーから読み取る方式だと、Content-Length省略時に
// 破綻するリスクがある（readBodyWithLimit参照）ため、メタデータAPIを使う。
async function getDriveFileSize(token: string, fileId: string, signal: AbortSignal): Promise<number> {
  const res = await fetch(`https://www.googleapis.com/drive/v3/files/${fileId}?fields=size`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  if (!res.ok) throw new Error(`Driveファイルサイズ取得エラー (${res.status}): ${await res.text()}`);
  const data = (await res.json()) as { size?: string };
  const size = Number(data.size || 0);
  if (!size) throw new Error("Driveファイルのサイズを取得できませんでした");
  return size;
}

async function fetchDriveRange(token: string, fileId: string, start: number, length: number, signal: AbortSignal): Promise<Uint8Array> {
  const end = start + length - 1;
  const res = await fetch(`https://www.googleapis.com/drive/v3/files/${fileId}?alt=media`, {
    headers: { Authorization: `Bearer ${token}`, Range: `bytes=${start}-${end}` },
    signal,
  });
  if (res.status !== 206 && res.status !== 200) {
    throw new Error(`Drive range取得エラー (${res.status}): ${await res.text()}`);
  }
  return new Uint8Array(await res.arrayBuffer());
}

function driveRangeSource(token: string, fileId: string, totalSize: number, signal: AbortSignal): ByteRangeSource {
  return {
    totalSize,
    read: (start, length) => fetchDriveRange(token, fileId, start, Math.min(length, totalSize - start), signal),
  };
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
      const text = await withAbortTimeout(
        (signal) => extractDriveFileText(env, token, file, signal),
        PER_FILE_TIMEOUT_MS,
        `${file.name}の変換`,
      );
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
