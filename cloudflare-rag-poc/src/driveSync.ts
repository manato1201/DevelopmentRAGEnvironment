import type { AuthedUser, Env, KbSyncResult } from "./types";
import { jsonResponse } from "./http";
import { requireKnowledgeEditor } from "./auth";
import { getGoogleAccessToken } from "./googleAuth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId, withAbortTimeout } from "./chunking";
import { notifySyncComplete } from "./syncNotify";

// PDFのFile APIアップロード＋動画のACTIVE待ちポーリングを含むと1件で数十秒かかることがあり、
// これがCloudflareエッジのリクエスト打ち切り（非JSON応答・HTTP 503）を引き起こしていた
// （2026-08-27、batchSize=1でも発生を確認）。1件あたりの処理に上限を設け、超過分は
// そのファイルだけスキップしてバッチ全体は正常応答できるようにする。
//
// 2026-08-29修正: この上限は当初「ダウンロード＋テキスト変換」だけに掛かっており、
// その後のingestDocument（チャンクごとのGemini埋め込み＋D1書き込み）は無制限のまま
// だった。サイズの小さい順に処理する設計（listDriveFiles参照）のため、バッチが進むほど
// 後段のファイルは大きく・チャンク数も多くなり、実機のhoudini21同期で85/335件目付近から
// 埋め込みだけで45秒を超えて連続タイムアウトするようになっていた。ingestDocument側も
// batchEmbedContentsでまとめて呼び出し往復回数自体を減らしたうえで、ダウンロード＋
// 変換＋埋め込みの全体を1つのタイムアウトで包み、上限自体も引き上げる。
const PER_FILE_TIMEOUT_MS = 100_000;
import { extractTextFromPdf, extractTextFromDocxSource, extractTextFromPptxSource } from "./docExtract";
import type { ByteRangeSource } from "./docExtract";
import { transcribeAudioVideo } from "./mediaTranscribe";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
// Workers isolateのメモリ上限（128MB）に対する安全マージンとして、ダウンロード時点で弾く上限
const MAX_DOWNLOAD_BYTES = 90 * 1024 * 1024;

// 2026-09-04追加: このアカウントがCloudflare Workers Freeプラン（CPU時間10ms固定、
// Paidプランと違い引き上げ不可）だったと判明し、大きいPDF/DOCX/PPTX/音声動画の変換処理が
// Error 1102（Worker exceeded resource limits）で強制終了されることがあった（kb_logに
// 記録が一切残らず、クライアント側には「非JSON・HTTP 503」としてしか見えない）。
// ファイルサイズと実際のCPU消費量は完全には比例しない（例: DOCX/PPTXは埋め込み動画が
// 容量の大半を占めていてもテキスト抽出自体は軽いことがある）が、他に安全な判定基準が
// ないため、サイズを目安にした保守的な閾値で自動処理そのものをスキップし、
// Cloudflare側に強制終了される前に明確な理由を返せるようにする。
const MAX_AUTO_PROCESS_BYTES = 40 * 1024 * 1024;

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
    if (isPdf) return extractTextFromPdf(env, bytes, file.name, signal);
    return transcribeAudioVideo(env, bytes, file.mimeType, file.name, signal);
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

// batch内の各ファイルをダウンロード＋変換＋埋め込み＋D1書き込みする共通処理。
// 通常のページング同期（handleSyncDrive）と、失敗ファイルだけを狙い撃ちする
// 再同期（handleRetryFailedDrive）の両方から呼ばれる（2026-09-04リトライ機能追加時に抽出）。
async function processDriveBatch(
  env: Env,
  token: string,
  namespace: string,
  opId: string,
  batch: DriveFile[],
): Promise<{
  documents: number;
  chunks: number;
  skipped: Array<{ file: string; reason: string }>;
  results: Array<{ file: string; status: "ok" | "skipped" | "error"; detail: string }>;
}> {
  let documents = 0;
  let chunks = 0;
  const skipped: Array<{ file: string; reason: string }> = [];
  const results: Array<{ file: string; status: "ok" | "skipped" | "error"; detail: string }> = [];

  for (const file of batch) {
    try {
      // ダウンロード＋変換＋埋め込み＋D1書き込みまでを1つのタイムアウトで包む
      // （2026-08-29: 以前はingestDocumentがこの枠の外にあり無制限だったため、
      // サイズの大きいファイルで埋め込みだけがタイムアウトせず延々と実行され続けていた）。
      const outcome = await withAbortTimeout(
        async (signal): Promise<
          | { kind: "skip"; reason: string }
          | { kind: "ok"; chunks: number; skippedVectors: number }
        > => {
          const isCpuHeavyType =
            file.mimeType === "application/pdf" ||
            file.mimeType === DOCX_MIME ||
            file.mimeType === PPTX_MIME ||
            file.mimeType.startsWith("audio/") ||
            file.mimeType.startsWith("video/");
          const declaredSize = Number(file.size || 0);
          if (isCpuHeavyType && declaredSize > MAX_AUTO_PROCESS_BYTES) {
            return {
              kind: "skip",
              reason: `ファイルが大きすぎるため自動処理をスキップしました（${Math.round(declaredSize / 1024 / 1024)}MB、上限${MAX_AUTO_PROCESS_BYTES / 1024 / 1024}MB。Cloudflare Workers FreeプランのCPU時間制限のため）`,
            };
          }
          const text = await extractDriveFileText(env, token, file, signal);
          if (text === null) return { kind: "skip", reason: `未対応のmimeType: ${file.mimeType}` };
          if (!text.trim()) return { kind: "skip", reason: "本文が空です" };
          const result = await ingestDocument(env, namespace, file.name, text, "drive", signal);
          return { kind: "ok", chunks: result.chunks, skippedVectors: result.skippedVectors.length };
        },
        PER_FILE_TIMEOUT_MS,
        `${file.name}の処理`,
      );
      if (outcome.kind === "skip") {
        skipped.push({ file: file.name, reason: outcome.reason });
        results.push({ file: file.name, status: "skipped", detail: outcome.reason });
        await logKb(env, opId, namespace, "drive", file.name, "skipped", outcome.reason);
        continue;
      }
      chunks += outcome.chunks;
      documents += 1;
      const skipNote = outcome.skippedVectors > 0 ? `（${outcome.skippedVectors}チャンクは登録失敗のためスキップ）` : "";
      const detail = `${outcome.chunks}チャンク登録${skipNote}`;
      results.push({ file: file.name, status: "ok", detail });
      await logKb(env, opId, namespace, "drive", file.name, "ok", detail);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: file.name, reason: detail });
      results.push({ file: file.name, status: "error", detail });
      await logKb(env, opId, namespace, "drive", file.name, "error", detail);
    }
  }

  return { documents, chunks, skipped, results };
}

async function resolveDriveFolder(env: Env, namespace: string): Promise<string> {
  const source = await env.DB.prepare("SELECT drive_folder_id FROM kb_sources WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ drive_folder_id: string | null }>();
  if (!source?.drive_folder_id) {
    throw new Error(`namespace(${namespace})にDriveフォルダIDが設定されていません。先に /admin/kb/set-source で設定してください`);
  }
  return source.drive_folder_id;
}

// POST /admin/sync/drive — 既存GAS syncDriveToSheets相当（PDF/DOCX等の変換・音声動画の文字起こしは未対応）。
// Notion同期と同じバッチ処理方式。
// body: { namespace, startIndex?（省略時0）, batchSize?（省略時5）, opId?（継続呼び出し時に指定） }
export async function handleSyncDrive(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const body = (await req.json()) as { namespace?: string; startIndex?: number; batchSize?: number; opId?: string; notifyOnErrorOnly?: boolean };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });

  let folderId: string;
  try {
    folderId = await resolveDriveFolder(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();

  const token = await getGoogleAccessToken(env, DRIVE_SCOPE);
  const files = await listDriveFiles(token, folderId);
  const batch = files.slice(startIndex, startIndex + batchSize);

  const { documents, chunks, skipped, results } = await processDriveBatch(env, token, namespace, opId, batch);

  const nextIndex = startIndex + batchSize < files.length ? startIndex + batchSize : null;
  if (nextIndex === null) {
    await notifySyncComplete(env, opId, namespace, "drive", body.notifyOnErrorOnly);
  }

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    results,
    totalFiles: files.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  } satisfies KbSyncResult & { totalFiles: number; processedRange: [number, number]; nextIndex: number | null });
}

// POST /admin/sync/drive/retry-failed — 直近の同期（opId）で失敗(error)したファイルだけを
// 対象に再実行する。全件をstartIndex=0からやり直す必要をなくし、無駄な再埋め込みを避ける
// （2026-09-04追加）。skipped（未対応mimeType・本文空）は「再試行しても結果が変わらない」
// ため対象外にし、errorのみを対象にする。
// body: { namespace, opId }
export async function handleRetryFailedDrive(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);

  const body = (await req.json()) as { namespace?: string; opId?: string };
  const namespace = (body.namespace || "").trim();
  const sourceOpId = (body.opId || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  if (!sourceOpId) return jsonResponse(400, { error: "opId は必須です" });

  let folderId: string;
  try {
    folderId = await resolveDriveFolder(env, namespace);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const failedRows = await env.DB.prepare(
    "SELECT DISTINCT file FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'drive' AND status = 'error'",
  )
    .bind(sourceOpId, namespace)
    .all<{ file: string }>();
  const failedNames = new Set(failedRows.results.map((r) => r.file));
  if (failedNames.size === 0) {
    return jsonResponse(200, {
      status: "ok",
      opId: sourceOpId,
      documents: 0,
      chunks: 0,
      skipped: [],
      results: [],
      totalFiles: 0,
      processedRange: [0, 0],
      nextIndex: null,
    } satisfies KbSyncResult & { totalFiles: number; processedRange: [number, number]; nextIndex: number | null });
  }

  const token = await getGoogleAccessToken(env, DRIVE_SCOPE);
  const allFiles = await listDriveFiles(token, folderId);
  // 既知の制約: kb_logはファイル名のみ記録しGoogle DriveのファイルID自体は持たないため、
  // 同一フォルダに同名ファイルが複数存在する場合（Driveでは許容される）、片方だけが
  // 失敗していても名前が一致する全ファイルを対象にしてしまう。フォルダ内の重複ファイル名を
  // 避ける運用でカバーする（真に直すにはkb_logにDriveファイルIDを持たせる必要がある）。
  const targets = allFiles.filter((f) => failedNames.has(f.name));

  // logKbは追記のみでerror行を消さないため、先に今回対象の古いerror行を消しておく。
  // これをしないと、成功して直ったファイルの古いerror行がいつまでも残り、次回の
  // 「失敗ファイルだけ再同期」で既に直った同名ファイルを無駄に再処理し続けてしまう
  // （2026-09-04、実装直後の自己レビューで発見）。
  const placeholders = targets.map(() => "?").join(",");
  if (targets.length > 0) {
    await env.DB.prepare(
      `DELETE FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'drive' AND status = 'error' AND file IN (${placeholders})`,
    )
      .bind(sourceOpId, namespace, ...targets.map((f) => f.name))
      .run();
  }

  // 元のopIdに追記する（新しいopIdを発番すると「直前の同期」と「そのリトライ」が別の
  // 同期履歴として分断され、kb_historyで追いづらくなるため）。
  const { documents, chunks, skipped, results } = await processDriveBatch(env, token, namespace, sourceOpId, targets);

  return jsonResponse(200, {
    status: "ok",
    opId: sourceOpId,
    documents,
    chunks,
    skipped,
    results,
    totalFiles: targets.length,
    processedRange: [0, targets.length],
    nextIndex: null,
  } satisfies KbSyncResult & { totalFiles: number; processedRange: [number, number]; nextIndex: number | null });
}
