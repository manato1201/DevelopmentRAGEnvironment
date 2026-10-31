import type { AuthedUser, Env } from "./types";
import { ForbiddenError } from "./auth";
import { jsonResponse } from "./http";
import { readDocumentChunks } from "./chunkRows";

// 登録済みドキュメントの「読み出し」（2026-10-31追加）。
// - /docs/list: namespace内のドキュメント名の一覧（名前の部分一致で絞れる）
// - /docs/get : 1ドキュメントの全文（チャンクを順に並べ、重なりを除いてつなぐ。長い場合は offset で続きを読む）
// 使い手は2つ: Houdiniパネルの「Docs」タブ（人が読む）と、チュートリアル生成エージェントの get_doc ツール。
// /admin/kb/list-documents（ナレッジ登録権限者だけ）と違い、検索で使える namespace なら誰でも読める
// （検索結果に本文の断片を返しているので、新しい情報は出さない）。
// LLM もベクトル検索も使わないので、トークン予算は消費しない（D1 の読み取りだけ）。

export const DOC_DEFAULT_MAX_CHARS = 8000;
export const DOC_MAX_CHARS = 60000;
const LIST_DEFAULT_LIMIT = 50;
const LIST_MAX_LIMIT = 200;
const SUGGESTION_LIMIT = 5;
// chunkText（chunking.ts）の既定の重なり。つなぐときの先頭一致の探索に使う。
const CHUNK_OVERLAP = 150;
const MIN_OVERLAP_MATCH = 20;
// 名前の絞り込み語の長さの上限（LIKE の評価を重くしない）
const MAX_QUERY_CHARS = 200;

// 読めるのは、自分のキーで検索できる namespace だけ。個人用 namespace は本人のものだけ。
export function authorizeDocumentRead(user: AuthedUser, namespace: string): void {
  if (!user.allowedNamespaces.includes(namespace)) {
    throw new ForbiddenError(`namespace(${namespace})へのアクセス権がありません`);
  }
  if (namespace.startsWith("personal:") && namespace !== `personal:${user.userId}`) {
    throw new ForbiddenError("他のユーザーの個人用namespaceは読めません");
  }
}

// チャンクは chunkText（1000文字・150文字の重なり）で切られているので、前のチャンクの末尾と
// 次のチャンクの先頭が重なっている。重なりを除いて、元の文章に近い形につなぐ。
// まず想定どおりの重なり（150文字）を試し、合わなければ（別の切り方で登録された文書）、
// 近い長さで最長の一致を探す。一致しなければ改行を挟んでそのままつなぐ。
export function joinChunks(chunks: string[], overlap = CHUNK_OVERLAP): string {
  let out = "";
  for (const chunk of chunks) {
    if (out === "") {
      out = chunk;
      continue;
    }
    let skip = 0;
    if (chunk.length >= overlap && out.endsWith(chunk.slice(0, overlap))) {
      skip = overlap;
    } else {
      const max = Math.min(overlap + 50, out.length, chunk.length);
      for (let n = max; n >= MIN_OVERLAP_MATCH; n--) {
        if (out.endsWith(chunk.slice(0, n))) {
          skip = n;
          break;
        }
      }
    }
    out += skip > 0 ? chunk.slice(skip) : "\n" + chunk;
  }
  return out;
}

function escapeLike(s: string): string {
  return s.replace(/[\\%_]/g, (c) => "\\" + c);
}

function clampInt(value: unknown, fallback: number, min: number, max: number): number {
  const n = typeof value === "number" ? Math.floor(value) : Number.NaN;
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}

// ファイル名の部分一致（大文字小文字は区別しない）。個人用 namespace は、自分の登録分だけ。
async function listFiles(
  env: Env,
  user: AuthedUser,
  namespace: string,
  query: string,
  limit: number,
  offset: number,
): Promise<{ files: string[]; total: number }> {
  const where: string[] = ["namespace = ?"];
  const binds: unknown[] = [namespace];
  if (namespace.startsWith("personal:")) {
    where.push("owner_user_id = ?");
    binds.push(user.userId);
  }
  if (query) {
    where.push("file LIKE ? ESCAPE '\\'");
    binds.push(`%${escapeLike(query.slice(0, MAX_QUERY_CHARS))}%`);
  }
  const clause = where.join(" AND ");
  const totalRow = await env.DB.prepare(`SELECT COUNT(*) AS n FROM kb_documents WHERE ${clause}`)
    .bind(...binds)
    .first<{ n: number }>();
  const res = await env.DB.prepare(`SELECT file FROM kb_documents WHERE ${clause} ORDER BY file LIMIT ? OFFSET ?`)
    .bind(...binds, limit, offset)
    .all<{ file: string }>();
  return { files: (res.results ?? []).map((r) => r.file), total: totalRow?.n ?? 0 };
}

// POST /docs/list — body: { namespace, query?, limit?, offset? }
export async function handleDocsList(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as {
    namespace?: string;
    query?: string;
    limit?: number;
    offset?: number;
  };
  const namespace = (body.namespace || "").trim();
  if (!namespace) return jsonResponse(400, { error: "namespace は必須です" });
  authorizeDocumentRead(user, namespace);

  const limit = clampInt(body.limit, LIST_DEFAULT_LIMIT, 1, LIST_MAX_LIMIT);
  const offset = clampInt(body.offset, 0, 0, 1_000_000);
  const { files, total } = await listFiles(env, user, namespace, (body.query || "").trim(), limit, offset);
  return jsonResponse(200, { status: "ok", namespace, files, total, offset, limit });
}

// POST /docs/get — body: { namespace, file, offset?, maxChars? }
// 見つからないときは、名前が近いものを suggestions に添えて 404 を返す（モデル・人が綴りを直せるように）。
export async function handleDocsGet(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as {
    namespace?: string;
    file?: string;
    offset?: number;
    maxChars?: number;
  };
  const namespace = (body.namespace || "").trim();
  const file = (body.file || "").trim();
  if (!namespace || !file) return jsonResponse(400, { error: "namespace と file は必須です" });
  authorizeDocumentRead(user, namespace);

  const chunks = await readDocumentChunks(env, namespace, file);
  if (chunks.length === 0) {
    const { files } = await listFiles(env, user, namespace, file, SUGGESTION_LIMIT, 0);
    return jsonResponse(404, {
      error: `namespace(${namespace})にfile(${file})という登録済みドキュメントが見つかりません`,
      suggestions: files,
    });
  }

  const full = joinChunks(chunks.map((c) => c.body));
  const maxChars = clampInt(body.maxChars, DOC_DEFAULT_MAX_CHARS, 200, DOC_MAX_CHARS);
  const offset = clampInt(body.offset, 0, 0, full.length);
  const end = Math.min(full.length, offset + maxChars);
  return jsonResponse(200, {
    status: "ok",
    namespace,
    file,
    text: full.slice(offset, end),
    totalChars: full.length,
    offset,
    nextOffset: end < full.length ? end : null,
    chunkCount: chunks.length,
  });
}
