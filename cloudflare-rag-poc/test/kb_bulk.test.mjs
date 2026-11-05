// ナレッジの一括削除（POST /admin/kb/delete-documents）と、一覧の言語の推定（T13）。2026-11-06。
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
// node:sqlite has no FTS5: a plain table has the same rowid semantics we rely on.
db.exec("CREATE TABLE chunks_fts (chunk_id TEXT, file TEXT, namespace TEXT, scope TEXT, owner_user_id TEXT, difficulty TEXT, body TEXT)");
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) {
  try { db.exec(readFileSync(MIG + f, "utf8")); } catch (e) { if (!/fts5|chunks_fts/.test(String(e))) console.log("migration warn", f, String(e).slice(0, 80)); }
}

const isSelect = (sql) => /^\s*select/i.test(sql);
const stmt = (sql) => ({
  a: [],
  bind(...x) { this.a = x; return this; },
  async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes } }; },
  async first() { return db.prepare(sql).get(...this.a) ?? null; },
  async all() { return { results: db.prepare(sql).all(...this.a) }; },
  rows() { return isSelect(sql) ? db.prepare(sql).all(...this.a) : (db.prepare(sql).run(...this.a), []); },
});
const D1 = {
  async batch(stmts) { return stmts.map((s) => ({ results: s.rows() })); },
  prepare: stmt,
};
const store = new Map();
const vec = (name) => ({
  async upsert(items) { for (const v of items) store.set(name + v.id, v); },
  async deleteByIds(ids) { for (const i of ids) store.delete(name + i); },
  async getByIds(ids) { return ids.map((i) => store.get(name + i)).filter(Boolean); },
});
const env = { DB: D1, GEMINI_API_KEY: "g", VEC_SHARED: vec("s:"), VEC_PERSONAL: vec("p:") };
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.includes(":batchEmbedContents")) return new Response(JSON.stringify({ embeddings: JSON.parse(init.body).requests.map(() => ({ values: new Array(768).fill(0.01) })) }));
  if (url.includes(":embedContent")) return new Response(JSON.stringify({ embedding: { values: new Array(768).fill(0.01) } }));
  throw new Error("unexpected fetch " + url);
};

const KI = await import("../src/kbIngest");
const KD = await import("../src/kbDocuments");
const KL = await import("../src/kbLanguage");

const admin = { userId: "u1", role: "admin", allowedNamespaces: [] };
const guest = { userId: "g1", role: "guest", allowedNamespaces: [] };
const post = (body) => new Request("http://x/", { method: "POST", body: JSON.stringify(body) });
const count = (t, w = "1=1") => db.prepare(`SELECT COUNT(*) c FROM ${t} WHERE ${w}`).get().c;

// ---- 言語の推定（純関数）
assert.equal(KL.guessLanguage("これは日本語の文章です"), "日本語");
assert.equal(KL.guessLanguage("Scatter creates points on a surface."), "英語など");
assert.equal(KL.guessLanguage("カタカナだけ"), "日本語");
assert.equal(KL.guessLanguage("   "), "不明");
assert.equal(KL.guessLanguage(""), "不明");

// ---- 準備: 日本語2件・英語1件
await KI.ingestDocument(env, "shared:docs", "ja1.md", "日本語のドキュメントです。ノードの使い方を説明します。", "manual");
await KI.ingestDocument(env, "shared:docs", "ja2.md", "二つ目の日本語の資料。", "notion");
await KI.ingestDocument(env, "shared:docs", "en1.md", "An English document about the scatter node.", "manual");
await KI.ingestDocument(env, "shared:other", "keep.md", "別のnamespaceの資料は、消えてはいけません。", "manual");

// ---- 一覧: 言語が付く。ほかの項目（source・updatedAt）も従来どおり
{
  const res = await KD.handleListDocuments(post({ namespace: "shared:docs" }), env, admin);
  assert.equal(res.status, 200);
  const data = await res.json();
  assert.deepEqual(data.files, ["en1.md", "ja1.md", "ja2.md"], "files stays for older callers");
  const by = Object.fromEntries(data.documents.map((d) => [d.file, d]));
  assert.equal(by["ja1.md"].language, "日本語");
  assert.equal(by["ja2.md"].language, "日本語");
  assert.equal(by["en1.md"].language, "英語など");
  assert.ok("source" in by["ja2.md"] && "updatedAt" in by["ja2.md"], "the other columns are still returned");
}

// ---- 一括削除: 件ごとの結果。無いファイルは not_found。重複は1件にまとめる。ほかのnamespaceは触らない
{
  const res = await KD.handleDeleteDocuments(post({ namespace: "shared:docs", files: ["ja1.md", "ja1.md", "en1.md", "missing.md", "  "] }), env, admin);
  assert.equal(res.status, 200);
  const data = await res.json();
  assert.deepEqual(data.results.map((r) => [r.file, r.status]), [["ja1.md", "deleted"], ["en1.md", "deleted"], ["missing.md", "not_found"]]);
  assert.equal(data.deleted, 2);
  assert.ok(data.deletedChunks >= 2);
  assert.equal(count("kb_documents", "namespace='shared:docs' AND file IN ('ja1.md','en1.md')"), 0, "document rows are gone");
  assert.equal(count("chunk_rows", "namespace='shared:docs' AND file IN ('ja1.md','en1.md')"), 0, "chunk map rows are gone");
  assert.equal(count("chunks_fts", "file IN ('ja1.md','en1.md')"), 0, "fts rows are gone");
  assert.equal(count("kb_documents", "namespace='shared:docs' AND file='ja2.md'"), 1, "not requested: kept");
  assert.equal(count("kb_documents", "namespace='shared:other'"), 1, "another namespace: kept");
  assert.equal(count("chunk_rows"), count("chunks_fts"), "map and fts stay in step");
}

// ---- 入力の検査
{
  const bad = async (body, user = admin) => (await KD.handleDeleteDocuments(post(body), env, user)).status;
  assert.equal(await bad({ files: ["a"] }), 400, "namespace is required");
  assert.equal(await bad({ namespace: "shared:docs" }), 400, "files is required");
  assert.equal(await bad({ namespace: "shared:docs", files: "a.md" }), 400, "files must be an array");
  assert.equal(await bad({ namespace: "shared:docs", files: [] }), 400);
  assert.equal(await bad({ namespace: "shared:docs", files: [1, null, {}] }), 400, "non-strings are ignored, leaving nothing");
  const many = Array.from({ length: KD.MAX_BULK_DELETE + 1 }, (_, i) => `f${i}.md`);
  assert.equal(await bad({ namespace: "shared:docs", files: many }), 400, "over the per-call limit");
  assert.equal(count("kb_documents", "namespace='shared:docs'"), 1, "rejected requests delete nothing");
}

// ---- 権限: 編集権限のない人は消せない。他人の個人用namespaceも消せない
await assert.rejects(() => KD.handleDeleteDocuments(post({ namespace: "shared:docs", files: ["ja2.md"] }), env, guest), /権限/);
await assert.rejects(() => KD.handleDeleteDocuments(post({ namespace: "personal:someone-else", files: ["x.md"] }), env, admin), /個人用/);
assert.equal(count("kb_documents", "namespace='shared:docs'"), 1);

// ---- 上限ちょうど（MAX_BULK_DELETE 件）は通る
{
  for (let i = 0; i < KD.MAX_BULK_DELETE; i++) await KI.ingestDocument(env, "shared:bulk", `d${i}.md`, `資料 ${i} の本文です。`, "manual");
  const files = Array.from({ length: KD.MAX_BULK_DELETE }, (_, i) => `d${i}.md`);
  const data = await (await KD.handleDeleteDocuments(post({ namespace: "shared:bulk", files }), env, admin)).json();
  assert.equal(data.deleted, KD.MAX_BULK_DELETE);
  assert.equal(count("kb_documents", "namespace='shared:bulk'"), 0);
}

// ---- 一覧の言語の推定が失敗しても、一覧は返る
{
  const broken = { ...env, DB: { ...D1, batch: async () => { throw new Error("d1 down"); } } };
  const res = await KD.handleListDocuments(post({ namespace: "shared:docs" }), broken, admin);
  const data = await res.json();
  assert.equal(data.documents.length, 1);
  assert.equal(data.documents[0].language, null, "unknown when the estimate fails");
}

console.log("kb_bulk ok");
