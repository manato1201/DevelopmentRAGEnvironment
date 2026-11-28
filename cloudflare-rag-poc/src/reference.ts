import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { requireAdmin } from "./auth";

// Reference タブの説明（2026-11-19、migrations/0038）。
//
//   ・説明は、開発側が作って、ここに置く（POST /admin/reference/put）。参加者の端末は、読むだけ（人ごとの違い・AI の費用を避ける）。
//   ・画像・動画（適用前後・ノード画面）は R2（REFERENCE_MEDIA）。POST /admin/reference/media_put?id=... で置き、説明の media に id を書く。
//   ・端末は、index で版（version）を見て、変わったものだけ取り直す（取得は、認証済みの全員。管理者かどうかは問わない）。
//   ・このアプリの Worker は、認証後は POST だけを受け付けるので、取得も POST（本文は空でもよい）。

export const KINDS = ["node", "vex", "apex", "shelf"] as const;
export type RefKind = (typeof KINDS)[number];
export const SECTION_KEYS = ["what", "use", "example", "example_point", "when"] as const;
export const SECTION_MAX = 1500;
export const MEDIA_MAX_BYTES = 12 * 1024 * 1024;
export const MEDIA_ID_MAX = 200;
const MEDIA_TYPES: Record<string, string> = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif", webm: "video/webm", mp4: "video/mp4" };

export interface RefMedia {
  id: string;
  type: "image" | "video";
  role: string;
  label: string;
}

const clip = (value: unknown, max: number): string => (typeof value === "string" ? value.trim().slice(0, max) : "");

export function isKind(value: unknown): value is RefKind {
  return typeof value === "string" && (KINDS as readonly string[]).includes(value);
}

// R2 のキー（画像・動画の id）。英数字・._-/ だけ。".." や先頭の "/" は拒否（別の場所を指せないように）。
export function validMediaId(id: unknown): id is string {
  return typeof id === "string" && id.length > 0 && id.length <= MEDIA_ID_MAX && /^[A-Za-z0-9._\-/]+$/.test(id) && !id.includes("..") && !id.startsWith("/") && !id.endsWith("/") && !id.includes("//");
}

export function mediaContentType(id: string): string | null {
  const ext = id.split(".").pop()?.toLowerCase() ?? "";
  return MEDIA_TYPES[ext] ?? null;
}

export function cleanMedia(value: unknown): RefMedia[] {
  if (!Array.isArray(value)) return [];
  const out: RefMedia[] = [];
  for (const m of value.slice(0, 20)) {
    if (!m || typeof m !== "object") continue;
    const rec = m as Record<string, unknown>;
    if (!validMediaId(rec.id)) continue;
    const ct = mediaContentType(rec.id);
    if (!ct) continue;
    out.push({ id: rec.id, type: ct.startsWith("video/") ? "video" : "image", role: clip(rec.role, 20) || "clip", label: clip(rec.label, 60) });
  }
  return out;
}

export function cleanEntryBody(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object") return null;
  const rec = value as Record<string, unknown>;
  const body: Record<string, unknown> = {};
  for (const k of SECTION_KEYS) body[k] = clip(rec[k], SECTION_MAX);
  if (!SECTION_KEYS.some((k) => body[k])) return null;
  if (Array.isArray(rec.references)) {
    body.references = rec.references.slice(0, 8).flatMap((r) => {
      if (!r || typeof r !== "object") return [];
      const ref = r as Record<string, unknown>;
      const url = clip(ref.url, 500);
      return /^https?:\/\//.test(url) ? [{ title: clip(ref.title, 120), url, source: clip(ref.source, 60) }] : [];
    });
  }
  const conditions = cleanConditions(rec.conditions);
  if (conditions) body.conditions = conditions;
  return body;
}

// 同じ結果にする条件（2026-11-28）。撮影のネットワークを実機で書き出したもの（ノード・パラメータ・入出力の表示名・フレーム）。
// 形は決まっているが、ここでは中身を解釈せず、大きさだけを抑える: 入れ子 5 段・配列 40 件・文字 600 字・キーは英小文字と _ だけ、全体 32KB まで。
export const CONDITIONS_MAX_CHARS = 32000;
const CONDITION_KEY = /^[a-z_]{1,24}$/;
function cleanValue(value: unknown, depth: number): unknown {
  if (typeof value === "string") return value.slice(0, 600);
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value === "boolean") return value;
  if (depth >= 5 || value === null || typeof value !== "object") return null;
  if (Array.isArray(value)) return value.slice(0, 40).map((v) => cleanValue(v, depth + 1)).filter((v) => v !== null);
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>).slice(0, 40)) {
    if (!CONDITION_KEY.test(k)) continue;
    const cleaned = cleanValue(v, depth + 1);
    if (cleaned !== null) out[k] = cleaned;
  }
  return out;
}
export function cleanConditions(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const cleaned = cleanValue(value, 0) as Record<string, unknown>;
  if (!Array.isArray(cleaned.nodes) || cleaned.nodes.length === 0) return null;
  return JSON.stringify(cleaned).length <= CONDITIONS_MAX_CHARS ? cleaned : null;
}

async function readJson(req: Request): Promise<Record<string, unknown>> {
  try {
    const parsed = await req.json();
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

// 端末の取得: 項目の一覧（版つき）。本文は、含めない（軽く保つ）。
export async function handleReferenceIndex(_req: Request, env: Env, _user: AuthedUser): Promise<Response> {
  const res = await env.DB.prepare("SELECT kind, key, title, version, updated_at AS updatedAt, media FROM reference_entries ORDER BY kind, key").all<{
    kind: string; key: string; title: string; version: number; updatedAt: number; media: string;
  }>();
  const items = (res.results ?? []).map((r) => {
    let mediaCount = 0;
    try { mediaCount = (JSON.parse(r.media) as unknown[]).length; } catch { /* 壊れた JSON は 0 件 */ }
    return { kind: r.kind, key: r.key, title: r.title, version: r.version, updatedAt: r.updatedAt, mediaCount };
  });
  return jsonResponse(200, { status: "ok", count: items.length, items });
}

export async function handleReferenceEntry(req: Request, env: Env, _user: AuthedUser): Promise<Response> {
  const body = await readJson(req);
  if (!isKind(body.kind) || typeof body.key !== "string" || !body.key) return jsonResponse(400, { error: "kind と key を指定してください" });
  const row = await env.DB.prepare("SELECT kind, key, title, body, media, version, updated_at AS updatedAt FROM reference_entries WHERE kind = ? AND key = ?")
    .bind(body.kind, body.key).first<{ kind: string; key: string; title: string; body: string; media: string; version: number; updatedAt: number }>();
  if (!row) return jsonResponse(404, { error: "この項目の説明は、まだありません" });
  let entry: unknown = {};
  let media: unknown = [];
  try { entry = JSON.parse(row.body); } catch { /* 空のまま */ }
  try { media = JSON.parse(row.media); } catch { /* 空のまま */ }
  return jsonResponse(200, { status: "ok", kind: row.kind, key: row.key, title: row.title, version: row.version, updatedAt: row.updatedAt, entry, media });
}

// 画像・動画。端末が、説明の media の id を指定して取る。
export async function handleReferenceMedia(req: Request, env: Env, _user: AuthedUser): Promise<Response> {
  const body = await readJson(req);
  if (!validMediaId(body.id)) return jsonResponse(400, { error: "id が正しくありません" });
  if (!env.REFERENCE_MEDIA) return jsonResponse(503, { error: "画像・動画の保管場所（R2）が、まだ設定されていません" });
  const obj = await env.REFERENCE_MEDIA.get(body.id);
  if (!obj) return jsonResponse(404, { error: "画像・動画が見つかりません" });
  return new Response(obj.body, {
    status: 200,
    headers: { "content-type": mediaContentType(body.id) ?? "application/octet-stream", "cache-control": "private, max-age=86400", "content-length": String(obj.size) },
  });
}

// ---- 管理者（開発側の公開スクリプト）----

export async function handleReferencePut(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = await readJson(req);
  if (!isKind(body.kind) || typeof body.key !== "string" || !body.key.trim() || body.key.length > 200) return jsonResponse(400, { error: "kind と key（200 文字まで）を指定してください" });
  const entry = cleanEntryBody(body.entry);
  if (!entry) return jsonResponse(400, { error: "entry に、説明の欄（what / use / example / example_point / when）が、ひとつも入っていません" });
  const media = cleanMedia(body.media);
  const now = Date.now();
  const prev = await env.DB.prepare("SELECT version FROM reference_entries WHERE kind = ? AND key = ?").bind(body.kind, body.key).first<{ version: number }>();
  const version = (prev?.version ?? 0) + 1;
  await env.DB.prepare(
    `INSERT INTO reference_entries (kind, key, title, body, media, version, updated_at) VALUES (?,?,?,?,?,?,?)
     ON CONFLICT(kind, key) DO UPDATE SET title = excluded.title, body = excluded.body, media = excluded.media, version = excluded.version, updated_at = excluded.updated_at`,
  ).bind(body.kind, body.key, clip(body.title, 120), JSON.stringify(entry), JSON.stringify(media), version, now).run();
  return jsonResponse(200, { status: "ok", kind: body.kind, key: body.key, version, media: media.length });
}

export async function handleReferenceDelete(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = await readJson(req);
  if (!isKind(body.kind) || typeof body.key !== "string" || !body.key) return jsonResponse(400, { error: "kind と key を指定してください" });
  const res = await env.DB.prepare("DELETE FROM reference_entries WHERE kind = ? AND key = ?").bind(body.kind, body.key).run();
  return jsonResponse(200, { status: "ok", deleted: res.meta?.changes ?? 0 });
}

// 画像・動画を置く。本文は、ファイルそのもの。id は、URL の ?id=（例: node/sop/mountain/after.png）。
export async function handleReferenceMediaPut(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const id = new URL(req.url).searchParams.get("id");
  if (!validMediaId(id)) return jsonResponse(400, { error: "id が正しくありません（英数字と . _ - / のみ）" });
  if (!mediaContentType(id)) return jsonResponse(400, { error: "拡張子は png / jpg / webp / gif / webm / mp4 のどれかにしてください" });
  if (!env.REFERENCE_MEDIA) return jsonResponse(503, { error: "画像・動画の保管場所（R2）が、まだ設定されていません" });
  const declared = Number(req.headers.get("content-length") ?? 0);
  if (declared > MEDIA_MAX_BYTES) return jsonResponse(413, { error: `大きすぎます（${MEDIA_MAX_BYTES / 1024 / 1024}MB まで）` });
  const data = await req.arrayBuffer();
  if (data.byteLength === 0) return jsonResponse(400, { error: "空のファイルです" });
  if (data.byteLength > MEDIA_MAX_BYTES) return jsonResponse(413, { error: `大きすぎます（${MEDIA_MAX_BYTES / 1024 / 1024}MB まで）` });
  await env.REFERENCE_MEDIA.put(id, data);
  return jsonResponse(200, { status: "ok", id, bytes: data.byteLength });
}
