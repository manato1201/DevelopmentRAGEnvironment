import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId } from "./chunking";

// 簡易CSVパーサ（RFC4180準拠：ダブルクォート囲み・""によるエスケープ・引用内の改行に対応）。
// 外部ライブラリを追加せずに済む程度の単純なQA一覧を想定している。
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.some((f) => f !== "")) rows.push(row);
      row = [];
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    if (row.some((f) => f !== "")) rows.push(row);
  }
  return rows;
}

const DEFAULT_BATCH_SIZE = 5;

// POST /admin/kb/import-qa-csv — QAペアのCSVを一括登録する（既存GAS adminKbImportQaCsv /
// kbBulkImportQaPairs_相当）。ヘッダー行に question, answer 列が必要。
// Notion/Drive同期と同じ理由（Cloudflareのサブリクエスト数上限対策）でバッチ処理にしている。
// body: { namespace, csvText, startIndex?（省略時0）, batchSize?（省略時5）, opId?（継続呼び出し時に指定） }
export async function handleImportQaCsv(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as {
    namespace?: string;
    csvText?: string;
    startIndex?: number;
    batchSize?: number;
    opId?: string;
  };
  const namespace = (body.namespace || "").trim();
  const csvText = body.csvText || "";
  if (!namespace || !csvText.trim()) {
    return jsonResponse(400, { error: "namespace と csvText は必須です" });
  }

  const rows = parseCsv(csvText);
  if (rows.length < 2) return jsonResponse(400, { error: "CSVにヘッダー行とデータ行が必要です" });

  const header = rows[0].map((h) => h.trim().toLowerCase());
  const qIdx = header.indexOf("question");
  const aIdx = header.indexOf("answer");
  if (qIdx === -1 || aIdx === -1) {
    return jsonResponse(400, { error: "ヘッダー行に question, answer 列が必要です" });
  }
  const dataRows = rows.slice(1);

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();
  const batch = dataRows.slice(startIndex, startIndex + batchSize);

  let documents = 0;
  let chunks = 0;
  const skipped: Array<{ file: string; reason: string }> = [];

  for (let i = 0; i < batch.length; i++) {
    const rowNum = startIndex + i + 2; // 1-indexed + ヘッダー行ぶん
    const q = (batch[i][qIdx] || "").trim();
    const a = (batch[i][aIdx] || "").trim();
    const label = `QA行${rowNum}: ${q.slice(0, 40)}`;
    if (!q || !a) {
      skipped.push({ file: label, reason: "questionまたはanswerが空です" });
      await logKb(env, opId, namespace, "manual", label, "skipped", "questionまたはanswerが空");
      continue;
    }
    try {
      const result = await ingestDocument(env, namespace, label, `Q: ${q}\nA: ${a}`, "manual");
      documents += 1;
      chunks += result.chunks;
      await logKb(env, opId, namespace, "manual", label, "ok", `QA一括登録: ${result.chunks}チャンク`);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: label, reason: detail });
      await logKb(env, opId, namespace, "manual", label, "error", detail);
    }
  }

  const nextIndex = startIndex + batchSize < dataRows.length ? startIndex + batchSize : null;

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    totalRows: dataRows.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
