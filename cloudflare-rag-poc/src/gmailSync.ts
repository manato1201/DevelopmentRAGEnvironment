import type { AuthedUser, Env, KbSyncResult } from "./types";
import { jsonResponse } from "./http";
import { resolveGoogleOAuthAccessToken } from "./googleOAuth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId, withAbortTimeout } from "./chunking";
import { notifySyncComplete } from "./syncNotify";
import { authorizeSync, previewBody, PREVIEW_LIMIT, scopeFor, type SyncScope } from "./syncTargets";

// Gmailのメールをナレッジ登録元にする（2026-10-09追加）。読み取り専用スコープ
// （gmail.readonly）のOAuth接続（googleOAuth.ts）で、namespaceごとに指定した検索式に
// 合うメールだけを取り込む。検索式が空のnamespaceは対象外（全メールの取り込みを避ける）。
//
// 取り込むのは「件名・差出人・日時・本文のテキスト」だけ。添付ファイルは取り込まない。
// メールの内容は、そのnamespaceにアクセスできる全員が検索で見られるようになる点に注意
// （個人用namespaceに入れるか、共有してよいラベルだけに絞る運用を想定する）。
// 継続同期（cron）は設けず、管理画面からの手動実行のみ。
const DEFAULT_BATCH_SIZE = 10;
const PER_MESSAGE_TIMEOUT_MS = 60_000;
const MAX_MESSAGES = 500; // 1回の同期で扱う上限（検索式が広すぎる事故の歯止め）
const GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me";

interface MailDoc {
  id: string;
  title: string; // ナレッジ上のファイル名。末尾に " #<メッセージID>" を付けて一意にし、再試行でIDを復元できるようにする
  text: string;
}

async function resolveGmailToken(env: Env, ownerId = ""): Promise<string> {
  const token = await resolveGoogleOAuthAccessToken(env, "gmail", ownerId);
  if (!token) {
    throw new Error(
      ownerId
        ? "あなたのGmailが未接続です。「自分用」の連携からGmailを接続してください"
        : "Gmailが未接続です。管理画面のナレッジ登録タブ「連携するシステムを追加」からGmailを接続してください",
    );
  }
  return token;
}

async function resolveGmailQuery(env: Env, namespace: string): Promise<string> {
  const source = await env.DB.prepare("SELECT gmail_query FROM kb_sources WHERE namespace_id = ?")
    .bind(namespace)
    .first<{ gmail_query: string | null }>();
  const query = source?.gmail_query?.trim();
  if (!query) {
    throw new Error(`namespace(${namespace})にGmailの検索式が設定されていません。先に /admin/kb/set-source で設定してください`);
  }
  return query;
}

// ---- メール本文の取り出し ----
function decodeBase64Url(data: string): string {
  const b64 = data.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder("utf-8").decode(bytes);
}

function htmlToText(html: string): string {
  return html
    .replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|tr|h[1-6])>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/[ \t]+/g, " ")
    .replace(/\n\s*\n\s*\n+/g, "\n\n")
    .trim();
}

interface GmailPart {
  mimeType?: string;
  filename?: string;
  body?: { data?: string };
  parts?: GmailPart[];
}

function collectBodies(part: GmailPart | undefined, out: { plain: string[]; html: string[] }): void {
  if (!part) return;
  if (part.filename) return; // 添付ファイルは取り込まない
  if (part.body?.data) {
    if (part.mimeType === "text/plain") out.plain.push(decodeBase64Url(part.body.data));
    else if (part.mimeType === "text/html") out.html.push(decodeBase64Url(part.body.data));
  }
  for (const child of part.parts ?? []) collectBodies(child, out);
}

// RFC 2047（=?UTF-8?B?...?= / =?UTF-8?Q?...?=）の件名を読める文字へ戻す。
export function decodeMimeHeader(value: string): string {
  return value.replace(/=\?([^?]+)\?([bBqQ])\?([^?]*)\?=/g, (_m, charset: string, enc: string, text: string) => {
    try {
      let bytes: Uint8Array;
      if (enc.toLowerCase() === "b") {
        const bin = atob(text);
        bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
      } else {
        const raw = text.replace(/_/g, " ").replace(/=([0-9A-Fa-f]{2})/g, (_x, h: string) => String.fromCharCode(parseInt(h, 16)));
        bytes = Uint8Array.from(raw, (c) => c.charCodeAt(0));
      }
      return new TextDecoder(charset).decode(bytes);
    } catch {
      return text;
    }
  });
}

function headerValue(headers: Array<{ name: string; value: string }> | undefined, name: string): string {
  const h = headers?.find((x) => x.name.toLowerCase() === name.toLowerCase());
  return h ? decodeMimeHeader(h.value) : "";
}

function formatDate(ms: number | null, fallback: string): string {
  if (ms === null || Number.isNaN(ms)) return fallback;
  const d = new Date(ms + 9 * 3600_000); // JST
  return d.toISOString().slice(0, 10);
}

async function listMessageIds(token: string, query: string): Promise<string[]> {
  const ids: string[] = [];
  let pageToken: string | undefined;
  do {
    const url = new URL(`${GMAIL_API}/messages`);
    url.searchParams.set("q", query);
    url.searchParams.set("maxResults", "100");
    if (pageToken) url.searchParams.set("pageToken", pageToken);
    const res = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`Gmail messages APIエラー (${res.status}): ${await res.text()}`);
    const data = (await res.json()) as { messages?: Array<{ id: string }>; nextPageToken?: string };
    for (const m of data.messages ?? []) ids.push(m.id);
    pageToken = data.nextPageToken;
  } while (pageToken && ids.length < MAX_MESSAGES);
  return ids.slice(0, MAX_MESSAGES);
}

async function fetchMail(token: string, id: string): Promise<MailDoc> {
  const res = await fetch(`${GMAIL_API}/messages/${encodeURIComponent(id)}?format=full`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Gmail message取得エラー (${res.status}): ${await res.text()}`);
  const msg = (await res.json()) as {
    id: string;
    internalDate?: string;
    payload?: GmailPart & { headers?: Array<{ name: string; value: string }> };
  };
  const subject = headerValue(msg.payload?.headers, "Subject") || "(件名なし)";
  const from = headerValue(msg.payload?.headers, "From");
  const dateHeader = headerValue(msg.payload?.headers, "Date");
  const date = formatDate(msg.internalDate ? Number(msg.internalDate) : null, dateHeader);

  const bodies = { plain: [] as string[], html: [] as string[] };
  collectBodies(msg.payload, bodies);
  const body = bodies.plain.length > 0 ? bodies.plain.join("\n\n") : htmlToText(bodies.html.join("\n\n"));

  const text = [subject, from ? `差出人: ${from}` : "", date ? `日時: ${date}` : "", body.trim()].filter(Boolean).join("\n\n");
  return { id, title: `${subject} (${date}) #${id}`, text };
}

async function processMailBatch(
  env: Env,
  token: string,
  namespace: string,
  opId: string,
  ids: string[],
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

  for (const id of ids) {
    let label = `#${id}`;
    try {
      const outcome = await withAbortTimeout(
        async (signal): Promise<{ kind: "skip"; reason: string; title: string } | { kind: "ok"; chunks: number; skippedVectors: number; title: string }> => {
          const mail = await fetchMail(token, id);
          label = mail.title;
          if (!mail.text.trim()) return { kind: "skip", reason: "本文が空です", title: mail.title };
          const result = await ingestDocument(env, namespace, mail.title, mail.text, "gmail", signal);
          return { kind: "ok", chunks: result.chunks, skippedVectors: result.skippedVectors.length, title: mail.title };
        },
        PER_MESSAGE_TIMEOUT_MS,
        `メール${id}の処理`,
      );
      label = outcome.title;
      if (outcome.kind === "skip") {
        skipped.push({ file: label, reason: outcome.reason });
        results.push({ file: label, status: "skipped", detail: outcome.reason });
        await logKb(env, opId, namespace, "gmail", label, "skipped", outcome.reason);
        continue;
      }
      chunks += outcome.chunks;
      documents += 1;
      const skipNote = outcome.skippedVectors > 0 ? `（${outcome.skippedVectors}チャンクは登録失敗のためスキップ）` : "";
      const detail = `${outcome.chunks}チャンク登録${skipNote}`;
      results.push({ file: label, status: "ok", detail });
      await logKb(env, opId, namespace, "gmail", label, "ok", detail);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: label, reason: detail });
      results.push({ file: label, status: "error", detail });
      await logKb(env, opId, namespace, "gmail", label, "error", detail);
    }
  }

  return { documents, chunks, skipped, results };
}

// POST /admin/sync/gmail — namespaceに設定した検索式に合うメールを一括登録する。
// body: { namespace, startIndex?（省略時0）, batchSize?（省略時10）, opId?（継続呼び出し時に指定）, notifyOnErrorOnly? }
export async function handleSyncGmail(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string; startIndex?: number; batchSize?: number; opId?: string; notifyOnErrorOnly?: boolean };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  const scope = await authorizeSync(env, user, namespace);

  let ids: string[];
  let token: string;
  try {
    const query = await resolveGmailQuery(env, namespace);
    token = await resolveGmailToken(env, scope.ownerId);
    ids = await listMessageIds(token, query);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();
  const batch = ids.slice(startIndex, startIndex + batchSize);

  const { documents, chunks, skipped, results } = await processMailBatch(env, token, namespace, opId, batch);

  const nextIndex = startIndex + batchSize < ids.length ? startIndex + batchSize : null;
  if (nextIndex === null) {
    await notifySyncComplete(env, opId, namespace, "gmail", body.notifyOnErrorOnly);
  }

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    results,
    totalMessages: ids.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  } satisfies KbSyncResult & { totalMessages: number; processedRange: [number, number]; nextIndex: number | null });
}

// POST /admin/sync/gmail/retry-failed — 直近の同期（opId）で失敗したメールだけを再実行する。
// ファイル名の末尾の「#<メッセージID>」から対象を復元するので、検索式を引き直す必要はない。
export async function handleRetryFailedGmail(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string; opId?: string };
  const namespace = (body.namespace || "").trim();
  const sourceOpId = (body.opId || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  if (!sourceOpId) return jsonResponse(400, { error: "opId は必須です" });
  const scope = await authorizeSync(env, user, namespace);

  const failedRows = await env.DB.prepare(
    "SELECT DISTINCT file FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'gmail' AND status = 'error'",
  )
    .bind(sourceOpId, namespace)
    .all<{ file: string }>();
  const failed = (failedRows.results ?? []).map((r) => ({ file: r.file, id: /#([0-9a-zA-Z]+)$/.exec(r.file)?.[1] ?? "" })).filter((f) => f.id);

  if (failed.length === 0) {
    return jsonResponse(200, {
      status: "ok", opId: sourceOpId, documents: 0, chunks: 0, skipped: [], results: [],
      totalMessages: 0, processedRange: [0, 0], nextIndex: null,
    } satisfies KbSyncResult & { totalMessages: number; processedRange: [number, number]; nextIndex: number | null });
  }

  let token: string;
  try {
    token = await resolveGmailToken(env, scope.ownerId);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const placeholders = failed.map(() => "?").join(",");
  await env.DB.prepare(
    `DELETE FROM kb_log WHERE op_id = ? AND namespace_id = ? AND source = 'gmail' AND status = 'error' AND file IN (${placeholders})`,
  )
    .bind(sourceOpId, namespace, ...failed.map((f) => f.file))
    .run();

  const { documents, chunks, skipped, results } = await processMailBatch(env, token, namespace, sourceOpId, failed.map((f) => f.id));

  return jsonResponse(200, {
    status: "ok",
    opId: sourceOpId,
    documents,
    chunks,
    skipped,
    results,
    totalMessages: failed.length,
    processedRange: [0, failed.length],
    nextIndex: null,
  } satisfies KbSyncResult & { totalMessages: number; processedRange: [number, number]; nextIndex: number | null });
}

// POST /admin/gmail/list-labels — 接続したアカウントのラベル一覧（検索式を作る手がかり）。
export async function handleListGmailLabels(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as { mine?: boolean };
  const scope = scopeFor(user, body.mine);
  try {
    const token = await resolveGmailToken(env, scope.ownerId);
    const res = await fetch(`${GMAIL_API}/labels`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return jsonResponse(400, { error: `ラベル一覧取得エラー (${res.status}): ${await res.text()}` });
    const data = (await res.json()) as { labels?: Array<{ id: string; name: string; type?: string }> };
    const labels = (data.labels ?? [])
      .filter((l) => l.type === "user")
      .map((l) => ({ id: l.name, summary: l.name, query: `label:${l.name.replace(/\s+/g, "-")}` }))
      .sort((a, b) => a.summary.localeCompare(b.summary));
    return jsonResponse(200, { status: "ok", labels });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}

// POST /admin/kb/test-connection/gmail — 接続と検索式の確認（取り込みは行わない）。
export async function handleTestGmailConnection(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  const scope = await authorizeSync(env, user, namespace);
  try {
    const query = await resolveGmailQuery(env, namespace);
    const token = await resolveGmailToken(env, scope.ownerId);
    const url = new URL(`${GMAIL_API}/messages`);
    url.searchParams.set("q", query);
    url.searchParams.set("maxResults", "1");
    const res = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return jsonResponse(400, { error: `Gmail接続エラー (${res.status}): ${await res.text()}` });
    const data = (await res.json()) as { resultSizeEstimate?: number };
    return jsonResponse(200, { status: "ok", message: `接続成功（検索式「${query}」に合うメールは約${data.resultSizeEstimate ?? 0}件）` });
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}

// メール1通の概要（件名・差出人・日時だけ。本文は取らない）。プレビュー用。
async function fetchMailSummary(token: string, id: string): Promise<{ title: string; detail: string }> {
  const url = new URL(`${GMAIL_API}/messages/${encodeURIComponent(id)}`);
  url.searchParams.set("format", "metadata");
  for (const h of ["Subject", "From", "Date"]) url.searchParams.append("metadataHeaders", h);
  const res = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`Gmail message取得エラー (${res.status})`);
  const msg = (await res.json()) as { internalDate?: string; payload?: { headers?: Array<{ name: string; value: string }> } };
  const subject = headerValue(msg.payload?.headers, "Subject") || "(件名なし)";
  const from = headerValue(msg.payload?.headers, "From");
  const date = formatDate(msg.internalDate ? Number(msg.internalDate) : null, headerValue(msg.payload?.headers, "Date"));
  return { title: subject, detail: [date, from].filter(Boolean).join(" ・ ") };
}

// POST /admin/sync/gmail/preview — 同期するとどのメールが登録されるかの一覧（書き込みはしない）。
// body: { namespace }
export async function handlePreviewGmail(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json()) as { namespace?: string };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  const scope: SyncScope = await authorizeSync(env, user, namespace);
  try {
    const query = await resolveGmailQuery(env, namespace);
    const token = await resolveGmailToken(env, scope.ownerId);
    const ids = await listMessageIds(token, query);
    const items = [];
    for (const id of ids.slice(0, PREVIEW_LIMIT)) {
      try {
        items.push(await fetchMailSummary(token, id));
      } catch {
        items.push({ title: `(取得できませんでした) #${id}`, detail: "" });
      }
    }
    return jsonResponse(
      200,
      previewBody(namespace, scope, ids.length, items, `検索式「${query}」に合うメール。本文・添付ファイルはこの画面には出しません`),
    );
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }
}
