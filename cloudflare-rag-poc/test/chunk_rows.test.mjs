// chunk_rows (chunk_id -> FTS rowid map): ingest, re-ingest, shrink, delete by document / namespace, staging move, backfill.
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

let batches = 0;
const D1 = {
  async batch(stmts) { batches++; for (const s of stmts) await s.run(); return []; },
  prepare(sql) {
    return {
      a: [], bind(...x) { this.a = x; return this; },
      async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes } }; },
      async first() { return db.prepare(sql).get(...this.a) ?? null; },
      async all() { return { results: db.prepare(sql).all(...this.a) }; },
    };
  },
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
const CR = await import("../src/chunkRows");

const count = (t, w = "1=1") => db.prepare(`SELECT COUNT(*) c FROM ${t} WHERE ${w}`).get().c;
// every mapping must point at the FTS row that has the same chunk_id / namespace / file, and vice versa
function consistent(label) {
  const bad = db.prepare("SELECT COUNT(*) c FROM chunk_rows r LEFT JOIN chunks_fts f ON f.rowid = r.fts_rowid WHERE f.rowid IS NULL OR f.chunk_id != r.chunk_id OR f.namespace != r.namespace OR f.file != r.file").get().c;
  assert.equal(bad, 0, label + ": mappings point at the wrong/missing fts row");
  assert.equal(count("chunks_fts"), count("chunk_rows"), label + ": fts rows != map rows");
}
const para = (n, tag) => Array.from({ length: n }, (_, i) => `${tag}-${i} ` + "あ".repeat(900)).join("\n\n");

// 1) ingest a multi-chunk document
const r1 = await KI.ingestDocument(env, "shared:docs", "A.md", para(6, "a"), "manual");
assert.ok(r1.chunks >= 3, "need several chunks, got " + r1.chunks);
assert.equal(count("chunk_rows", "namespace='shared:docs' AND file='A.md'"), r1.chunks);
consistent("after ingest");

// 2) re-ingest the same document: no duplicates
await KI.ingestDocument(env, "shared:docs", "A.md", para(6, "a"), "manual");
assert.equal(count("chunk_rows"), r1.chunks);
consistent("after re-ingest");

// 3) a long document that spans more than one 50-statement batch keeps every chunk's pair intact
await KI.ingestDocument(env, "shared:docs", "Big.md", para(40, "b"), "manual");
consistent("after big ingest");

// 4) shrink: previousChunkCount removes the stale tail from fts and the map
const big = count("chunk_rows", "file='Big.md'");
const r4 = await KI.ingestDocument(env, "shared:docs", "Big.md", para(3, "b"), "manual", undefined, big);
assert.equal(count("chunk_rows", "file='Big.md'"), r4.chunks);
assert.equal(count("chunks_fts", "file='Big.md'"), r4.chunks);
consistent("after shrink");

// 5) other namespaces / personal
await KI.ingestDocument(env, "shared:other", "O.md", para(2, "o"), "manual");
await KI.ingestDocument(env, "personal:u9", "P.md", para(2, "p"), "manual");
consistent("after other ns");

// 6) delete one document: only that document goes (fts + map + kb_documents + vectors)
const aIds = await CR.listChunkIds(env, "shared:docs", "A.md");
assert.equal(aIds.length, r1.chunks);
const deleted = await KD.deleteDocumentChunks(env, "shared:docs", "A.md");
assert.equal(deleted, r1.chunks);
assert.equal(count("chunks_fts", "file='A.md'"), 0);
assert.equal(count("chunk_rows", "file='A.md'"), 0);
assert.equal(count("kb_documents", "file='A.md'"), 0);
assert.ok(count("chunks_fts", "file='Big.md'") > 0 && count("chunks_fts", "file='O.md'") > 0, "other documents must survive");
for (const id of aIds) assert.ok(!store.has("s:" + id), "vector deleted");
assert.equal(await KD.deleteDocumentChunks(env, "shared:docs", "A.md"), 0);
consistent("after document delete");

// 7) readDocumentChunks returns chunk_id + body from the fts row (rowid join)
const rows = await CR.readDocumentChunks(env, "shared:docs", "Big.md");
assert.equal(rows.length, r4.chunks);
assert.ok(rows.every((r) => typeof r.chunk_id === "string" && r.body.length > 0));
assert.deepEqual(rows.map((r) => r.chunk_id).sort(), (await CR.listChunkIds(env, "shared:docs", "Big.md")).sort());
assert.ok(rows.some((r) => r.body.includes("b-0")), "first chunk body is the document's own text");

// 8) delete a whole namespace (user deletion path)
await env.DB.batch(CR.deleteNamespaceChunkStatements(env, "personal:u9"));
assert.equal(count("chunks_fts", "namespace='personal:u9'"), 0);
assert.equal(count("chunk_rows", "namespace='personal:u9'"), 0);
consistent("after namespace delete");

// 9) backfill form of the migration reproduces the same map from the fts table
const before = db.prepare("SELECT chunk_id, fts_rowid, namespace, file FROM chunk_rows ORDER BY chunk_id").all();
db.exec("DELETE FROM chunk_rows");
db.exec("INSERT OR REPLACE INTO chunk_rows (chunk_id, fts_rowid, namespace, file) SELECT chunk_id, rowid, namespace, file FROM chunks_fts");
const after = db.prepare("SELECT chunk_id, fts_rowid, namespace, file FROM chunk_rows ORDER BY chunk_id").all();
assert.deepEqual(after, before);

// 10) group packing never splits a put group across batches
const groups = Array.from({ length: 30 }, (_, i) => CR.putChunkStatements(env, { chunkId: "g" + i, file: "G.md", namespace: "shared:g", scope: "shared", ownerUserId: null, difficulty: null, body: "x" }));
batches = 0;
await CR.runStatementGroups(env, groups);
assert.ok(batches >= 2, "30 groups x 4 statements must need more than one batch");
consistent("after grouped put");

console.log("chunk_rows tests ok");
