// /docs/list and /docs/get: reassembly of chunked documents, access rules, paging, "did you mean" suggestions.
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
// node:sqlite has no FTS5: a plain table has the same rowid semantics the code relies on.
db.exec("CREATE TABLE chunks_fts (chunk_id TEXT, file TEXT, namespace TEXT, scope TEXT, owner_user_id TEXT, difficulty TEXT, body TEXT)");
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) {
  try { db.exec(readFileSync(MIG + f, "utf8")); } catch (e) { if (!/fts5|chunks_fts/.test(String(e))) console.log("migration warn", f, String(e).slice(0, 80)); }
}

const D1 = {
  async batch(stmts) { for (const s of stmts) await s.run(); return []; },
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
const DR = await import("../src/docRead");
const { chunkText } = await import("../src/chunking");
const { ForbiddenError } = await import("../src/auth");

// A text whose every 150-char window is unique, so overlap detection cannot be fooled by repeated characters.
const unique = (n) => Array.from({ length: n }, (_, i) => `[${String(i).padStart(4, "0")}]` + "ノードを置く。".repeat(3)).join("");
const post = (handler, user, body) => handler(new Request("https://x/", { method: "POST", body: JSON.stringify(body) }), env, user);
const json = async (res) => ({ status: res.status, body: await res.json() });

const alice = { userId: "alice", role: "member", allowedNamespaces: ["shared:houdini22", "personal:alice"] };
const bob = { userId: "bob", role: "member", allowedNamespaces: ["shared:houdini22", "personal:bob", "personal:alice"] };
const outsider = { userId: "eve", role: "member", allowedNamespaces: ["shared:other"] };

// 1) joinChunks undoes chunkText exactly
for (const n of [3, 40, 120]) {
  const text = unique(n);
  assert.equal(DR.joinChunks(chunkText(text)), text.trim(), `joinChunks(chunkText(...)) for ${n} pieces`);
}
// chunks that were cut some other way (no overlap) are joined with a newline, nothing is lost
assert.equal(DR.joinChunks(["abc", "def"]), "abc\ndef");
assert.equal(DR.joinChunks(["only"]), "only");
assert.equal(DR.joinChunks([]), "");

// 2) ingest real documents through the normal path, then read them back
const long = unique(160); // several chunks
const r = await KI.ingestDocument(env, "shared:houdini22", "nodes/rbdmaterialfracture.md", long, "manual");
assert.ok(r.chunks >= 3, "need several chunks, got " + r.chunks);
await KI.ingestDocument(env, "shared:houdini22", "nodes/scatter.md", "Scatter creates points on a surface.", "manual");
await KI.ingestDocument(env, "shared:houdini22", "nodes/copy_to_points.md", "Copy to Points stamps geometry.", "manual");
await KI.ingestDocument(env, "shared:houdini22", "100%_done.md", "percent sign in a file name", "manual");
await KI.ingestDocument(env, "personal:alice", "memo.md", "alice private memo", "manual");

let res = await json(await post(DR.handleDocsGet, alice, { namespace: "shared:houdini22", file: "nodes/rbdmaterialfracture.md", maxChars: DR.DOC_MAX_CHARS }));
assert.equal(res.status, 200);
assert.equal(res.body.text, long.trim(), "the whole document comes back in order, without duplicated overlap");
assert.equal(res.body.totalChars, long.trim().length);
assert.equal(res.body.nextOffset, null);
assert.equal(res.body.chunkCount, r.chunks);

// 3) paging: pieces concatenate to the whole
let offset = 0;
let assembled = "";
let pages = 0;
for (;;) {
  const page = await json(await post(DR.handleDocsGet, alice, { namespace: "shared:houdini22", file: "nodes/rbdmaterialfracture.md", offset, maxChars: 500 }));
  assert.equal(page.status, 200);
  assert.ok(page.body.text.length <= 500);
  assembled += page.body.text;
  pages++;
  if (page.body.nextOffset === null) break;
  assert.equal(page.body.nextOffset, offset + page.body.text.length);
  offset = page.body.nextOffset;
  assert.ok(pages < 100, "paging must terminate");
}
assert.equal(assembled, long.trim());
assert.ok(pages > 1);
// the default page size is bounded
res = await json(await post(DR.handleDocsGet, alice, { namespace: "shared:houdini22", file: "nodes/rbdmaterialfracture.md" }));
assert.ok(res.body.text.length <= DR.DOC_DEFAULT_MAX_CHARS);
// absurd values are clamped, not trusted
res = await json(await post(DR.handleDocsGet, alice, { namespace: "shared:houdini22", file: "nodes/scatter.md", offset: 99999, maxChars: -5 }));
assert.equal(res.status, 200);
assert.equal(res.body.text, "");
assert.equal(res.body.nextOffset, null);

// 4) not found -> 404 with near names
res = await json(await post(DR.handleDocsGet, alice, { namespace: "shared:houdini22", file: "scatter" }));
assert.equal(res.status, 404);
assert.deepEqual(res.body.suggestions, ["nodes/scatter.md"]);
res = await json(await post(DR.handleDocsGet, alice, { namespace: "shared:houdini22" }));
assert.equal(res.status, 400);

// 5) list: all, substring filter, LIKE wildcards are literal, paging, total
res = await json(await post(DR.handleDocsList, alice, { namespace: "shared:houdini22" }));
assert.equal(res.status, 200);
assert.equal(res.body.total, 4);
assert.deepEqual(res.body.files, ["100%_done.md", "nodes/copy_to_points.md", "nodes/rbdmaterialfracture.md", "nodes/scatter.md"]);
res = await json(await post(DR.handleDocsList, alice, { namespace: "shared:houdini22", query: "SCATTER" }));
assert.deepEqual(res.body.files, ["nodes/scatter.md"], "case-insensitive substring");
res = await json(await post(DR.handleDocsList, alice, { namespace: "shared:houdini22", query: "%" }));
assert.deepEqual(res.body.files, ["100%_done.md"], "% is a literal character, not a wildcard");
res = await json(await post(DR.handleDocsList, alice, { namespace: "shared:houdini22", query: "_" }));
assert.equal(res.body.total, 2, "_ matches only names containing an underscore (not any single character)");
res = await json(await post(DR.handleDocsList, alice, { namespace: "shared:houdini22", limit: 2, offset: 1 }));
assert.deepEqual(res.body.files, ["nodes/copy_to_points.md", "nodes/rbdmaterialfracture.md"]);
assert.equal(res.body.total, 4);
res = await json(await post(DR.handleDocsList, alice, {}));
assert.equal(res.status, 400);
// an absurdly long filter is cut, not rejected or run as-is
res = await json(await post(DR.handleDocsList, alice, { namespace: "shared:houdini22", query: "scatter" + "x".repeat(5000) }));
assert.equal(res.status, 200);
assert.equal(res.body.total, 0);

// 6) access rules
await assert.rejects(post(DR.handleDocsList, outsider, { namespace: "shared:houdini22" }), ForbiddenError);
await assert.rejects(post(DR.handleDocsGet, outsider, { namespace: "shared:houdini22", file: "nodes/scatter.md" }), ForbiddenError);
// personal namespaces: only the owner, even if the allow-list (wrongly) contains someone else's
res = await json(await post(DR.handleDocsGet, alice, { namespace: "personal:alice", file: "memo.md" }));
assert.equal(res.status, 200);
assert.equal(res.body.text, "alice private memo");
await assert.rejects(post(DR.handleDocsGet, bob, { namespace: "personal:alice", file: "memo.md" }), ForbiddenError);
await assert.rejects(post(DR.handleDocsList, bob, { namespace: "personal:alice" }), ForbiddenError);
res = await json(await post(DR.handleDocsList, alice, { namespace: "personal:alice" }));
assert.deepEqual(res.body.files, ["memo.md"]);

console.log("docs_read tests ok");
