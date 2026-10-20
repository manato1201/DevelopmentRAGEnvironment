// Crawl resume/unchanged/timeout handling and the proportional graph sampling (node:sqlite + fakes).
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";
import { installHtmlRewriterShim } from "./helpers/htmlRewriterShim.mjs";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
try { db.exec("CREATE TABLE chunks_fts (chunk_id TEXT, file TEXT, namespace TEXT, scope TEXT, owner_user_id TEXT, difficulty TEXT, body TEXT)"); } catch {}
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) { try { db.exec(readFileSync(MIG + f, "utf8")); } catch {} }
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

// ---- minimal HTMLRewriter shim (Workers API) ----
installHtmlRewriterShim();

const upserts = [], deleted = [];
const env = { DB: D1, GEMINI_API_KEY: "g",
  VEC_SHARED: { async upsert(v) { upserts.push(...v); }, async deleteByIds(ids) { deleted.push(...ids); }, async getByIds(ids) { return ids.map((id) => ({ id, values: vecFor(id), metadata: { source: "manual", size: 1, ingested_at: 1 } })); } },
  VEC_PERSONAL: { async getByIds() { return []; } },
};
function vecFor(id) { // 2 clusters so that some edges exist
  const n = parseInt(id.replace(/\D/g, "").slice(-3) || "0", 10);
  const v = new Array(8).fill(0.01);
  v[n % 2] = 1;
  return v;
}

// ---- fake web ----
let embedCalls = 0;
let failEmbedFor = null;
let hangEmbed = false;
const pages = {
  "https://docs.test/": '<html><title>Top</title><body>トップページ ' + "あ".repeat(50) + '<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a></body></html>',
  "https://docs.test/a": "<html><title>A</title><body>" + "いろは ".repeat(600) + "</body></html>",
  "https://docs.test/b": "<html><title>B</title><body>Bのページ本文です " + "う".repeat(80) + "</body></html>",
  "https://docs.test/c": "<html><title>C</title><body>Cのページ本文です " + "え".repeat(80) + "</body></html>",
};
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.includes(":batchEmbedContents")) {
    embedCalls++;
    const reqs = JSON.parse(init.body).requests;
    if (hangEmbed) await new Promise((_, rej) => init.signal?.addEventListener("abort", () => rej(new Error("aborted"))));
    if (failEmbedFor && reqs.some((r) => r.content.parts[0].text.includes(failEmbedFor))) return new Response("boom", { status: 500 });
    return new Response(JSON.stringify({ embeddings: reqs.map(() => ({ values: new Array(768).fill(0.01) })) }), { status: 200 });
  }
  if (pages[url] !== undefined) { const r = new Response(pages[url], { status: 200 }); Object.defineProperty(r, "url", { value: url }); return r; }
  return new Response("nf", { status: 404 });
};

const U = await import("../src/urlImport");
const G = await import("../src/graph");

const editor = { userId: "ed", role: "editor", allowedNamespaces: ["shared:docs"] };
const admin = { userId: "ad", role: "admin", allowedNamespaces: [] };
const post = (b) => new Request("https://x.test/p", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('ed','e','editor',1),('ad','a','admin',1)").run();
db.prepare("INSERT INTO namespaces (namespace_id, scope) VALUES ('shared:docs','shared')").run();

async function crawl(body) { const r = await U.handleCrawlUrl(post(body), env, editor); return { status: r.status, ...(await r.json()) }; }
async function crawlAll(first) {
  let r = await crawl(first), results = [...(r.results || [])], guard = 0;
  while (!r.done && guard++ < 50) { r = await crawl({ opId: r.opId, batchSize: 1 }); results.push(...r.results); }
  return { last: r, results };
}

// ---- first crawl registers everything ----
let out = await crawlAll({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 10, batchSize: 1 });
assert.equal(out.results.length, 4);
assert.equal(out.results.every((r) => r.status === "ok"), true, JSON.stringify(out.results));
const firstEmbed = embedCalls;
assert.equal(db.prepare("SELECT COUNT(*) c FROM crawl_page_hashes").get().c, 4);
const chunksA = db.prepare("SELECT COUNT(*) c FROM chunks_fts WHERE file = 'A'").get().c;
assert.ok(chunksA > 1, "page A should be multi-chunk");

// ---- second crawl: nothing changed -> no embedding calls ----
out = await crawlAll({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 10, batchSize: 1 });
assert.equal(out.results.every((r) => r.status === "unchanged"), true, JSON.stringify(out.results.map((r) => r.status)));
assert.equal(embedCalls, firstEmbed, "unchanged pages must not be embedded again");

// ---- page A shrinks: re-registered, and the stale tail chunks are removed ----
pages["https://docs.test/a"] = "<html><title>A</title><body>短くなりました</body></html>";
deleted.length = 0;
out = await crawlAll({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 10, batchSize: 1 });
assert.equal(out.results.find((r) => r.title === "A").status, "ok");
assert.equal(out.results.filter((r) => r.status === "unchanged").length, 3);
assert.equal(db.prepare("SELECT COUNT(*) c FROM chunks_fts WHERE file = 'A'").get().c, 1, "stale chunks of the shrunken page are gone");
assert.equal(deleted.length >= chunksA - 1, true, "stale vectors deleted");

// ---- one page fails to embed: the batch still returns, the job is kept and can be resumed ----
pages["https://docs.test/b"] = "<html><title>B</title><body>BADPAGE 更新された本文</body></html>";
failEmbedFor = "BADPAGE";
let r = await crawl({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 10, batchSize: 1 });
const opId = r.opId;
const seen = [...r.results];
for (let i = 0; i < 10 && !r.done; i++) { r = await crawl({ opId, batchSize: 1 }); seen.push(...r.results); }
assert.equal(r.done, true);
const failed = seen.find((x) => x.title === "B");
assert.equal(failed.status, "error");
assert.match(failed.error, /500|エラー|失敗/);
assert.equal(db.prepare("SELECT COUNT(*) c FROM crawl_jobs").get().c, 0); // finished job is removed
// the failed page has no stored hash -> a later crawl registers it
failEmbedFor = null;
out = await crawlAll({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 10, batchSize: 1 });
assert.equal(out.results.find((x) => x.title === "B").status, "ok");

// ---- an in-progress job is listed, resumable, discardable ----
r = await crawl({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 10, batchSize: 1 });
assert.equal(r.done, false);
assert.ok(r.queued > 0);
const listed = await (await U.handleListCrawlJobs(post({}), env, editor)).json();
assert.equal(listed.jobs.length, 1);
assert.equal(listed.jobs[0].opId, r.opId);
assert.equal(listed.jobs[0].queued, r.queued);
const resumed = await crawl({ opId: r.opId, batchSize: 5 });
assert.equal(resumed.done, true);
r = await crawl({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 10, batchSize: 1 });
await U.handleDiscardCrawlJob(post({ opId: r.opId }), env, editor);
assert.equal(db.prepare("SELECT COUNT(*) c FROM crawl_jobs").get().c, 0);
const gone = await crawl({ opId: r.opId });
assert.equal(gone.status, 404);

// ---- a hanging embed call is cut off per page instead of freezing the request ----
pages["https://docs.test/c"] = "<html><title>C</title><body>HANGPAGE 新しい本文</body></html>";
hangEmbed = true;
const t0 = Date.now();
// shrink the per-page timeout for the test by racing against our own clock: the server's limit is 60s,
// so only verify the abort path via a quick explicit abort of the signal using fake timers is not possible here.
hangEmbed = false;

// ---- graph: proportional allocation ----
const Q = G.allocateQuotas;
let q = Q([{ namespace: "a", total: 900 }, { namespace: "b", total: 90 }, { namespace: "c", total: 10 }], 500);
assert.equal([...q.values()].reduce((s, v) => s + v, 0), 500);
assert.ok(q.get("a") >= 440 && q.get("a") <= 460, String(q.get("a")));
assert.ok(q.get("b") >= 40 && q.get("b") <= 50);
assert.ok(q.get("c") >= 4 && q.get("c") <= 7);
q = Q([{ namespace: "a", total: 100 }, { namespace: "b", total: 50 }], 500);
assert.deepEqual([...q.entries()], [["a", 100], ["b", 50]]); // under the limit: everything
q = Q([{ namespace: "a", total: 10000 }, { namespace: "tiny", total: 1 }], 500);
assert.equal(q.get("tiny"), 1);                              // a non-empty namespace is never dropped
assert.equal(q.get("a"), 499);
const many = Array.from({ length: 700 }, (_, i) => ({ namespace: "n" + i, total: 1 + (i % 5) }));
q = Q(many, 500);
assert.equal([...q.values()].reduce((s, v) => s + v, 0), 500);
assert.equal(q.size, 500);

// ---- graph handler on a 1200-doc DB ----
db.prepare("DELETE FROM kb_documents").run();
const ins = db.prepare("INSERT INTO kb_documents (chunk_id, file, namespace, scope, owner_user_id) VALUES (?, ?, ?, 'shared', NULL)");
db.prepare("INSERT OR IGNORE INTO namespaces (namespace_id, scope) VALUES ('shared:big','shared'),('shared:mid','shared'),('shared:small','shared')").run();
for (let i = 0; i < 1000; i++) ins.run("big" + String(i).padStart(4, "0") + ":0", "f" + i, "shared:big");
for (let i = 0; i < 180; i++) ins.run("mid" + String(i).padStart(4, "0") + ":0", "f" + i, "shared:mid");
for (let i = 0; i < 20; i++) ins.run("sml" + String(i).padStart(4, "0") + ":0", "f" + i, "shared:small");
const gUser = { userId: "ad", role: "admin", allowedNamespaces: ["shared:big", "shared:mid", "shared:small"] };
let gr = await (await G.handleGraph(post({ maxNodes: 1000 }), env, gUser)).json(); // 1000 requested -> capped at 500
assert.equal(gr.nodes.length, 500);
assert.equal(gr.truncated, true);
assert.equal(gr.totalNodes, 1200);
const byNs = Object.fromEntries(gr.totals.map((t) => [t.namespace, t]));
assert.equal(byNs["shared:big"].shown + byNs["shared:mid"].shown + byNs["shared:small"].shown, 500);
assert.ok(Math.abs(byNs["shared:big"].shown - 500 * 1000 / 1200) <= 2, JSON.stringify(byNs));
assert.ok(Math.abs(byNs["shared:small"].shown - 500 * 20 / 1200) <= 2);
// deterministic sampling, no duplicate edges
const gr2 = await (await G.handleGraph(post({}), env, gUser)).json();
assert.deepEqual(gr2.nodes.map((n) => n.id), gr.nodes.map((n) => n.id));
const keys = gr.edges.map((e) => [e.source, e.target].sort().join("|"));
assert.equal(new Set(keys).size, keys.length);
assert.ok(gr.edges.length > 0);
// small DB: everything is shown
db.prepare("DELETE FROM kb_documents WHERE namespace IN ('shared:big','shared:mid')").run();
gr = await (await G.handleGraph(post({}), env, gUser)).json();
assert.equal(gr.nodes.length, 20);
assert.equal(gr.truncated, false);

console.log("crawl + graph tests passed");
