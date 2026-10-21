// Houdini docs crawl: context header + context-tagged file names, no overwrite between same-titled pages,
// one-time removal of legacy (header-less) registrations, idempotent re-crawl.
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
installHtmlRewriterShim();

const upserts = [], deleted = [];
const env = { DB: D1, GEMINI_API_KEY: "g",
  VEC_SHARED: { async upsert(v) { upserts.push(...v); }, async deleteByIds(ids) { deleted.push(...ids); } },
  VEC_PERSONAL: {},
};
let embedCalls = 0;
const pages = {
  "https://www.sidefx.com/docs/houdini/nodes/index.html": '<html><title>Nodes</title><body><main>ノード一覧のページです ' + "あ".repeat(60) +
    '<a href="/docs/houdini/nodes/sop/merge.html">SOP</a><a href="/docs/houdini/nodes/vop/merge.html">VOP</a>' +
    '<a href="/docs/houdini/nodes/dop/merge.html">DOP</a><a href="/docs/houdini/model/rivet.html">guide</a></main></body></html>',
  "https://www.sidefx.com/docs/houdini/nodes/sop/merge.html": "<html><title>Merge</title><body><main>SOPのMerge: 複数のジオメトリを1つにまとめます。 " + "い".repeat(80) + "</main></body></html>",
  "https://www.sidefx.com/docs/houdini/nodes/vop/merge.html": "<html><title>Merge</title><body><main>VOPのMerge: 値を結合します。 " + "う".repeat(80) + "</main></body></html>",
  "https://www.sidefx.com/docs/houdini/nodes/dop/merge.html": "<html><title>Merge</title><body><main>DOPのMerge: ダイナミクスを結合します。 " + "え".repeat(80) + "</main></body></html>",
  "https://www.sidefx.com/docs/houdini/model/rivet.html": "<html><title>Rivet</title><body><main>ガイドのページです。章の見出しは付きません。 " + "お".repeat(80) + "</main></body></html>",
};
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.includes(":batchEmbedContents")) {
    embedCalls++;
    const reqs = JSON.parse(init.body).requests;
    return new Response(JSON.stringify({ embeddings: reqs.map(() => ({ values: new Array(768).fill(0.01) })) }), { status: 200 });
  }
  if (pages[url] !== undefined) { const r = new Response(pages[url], { status: 200 }); Object.defineProperty(r, "url", { value: url }); return r; }
  return new Response("nf", { status: 404 });
};

const U = await import("../src/urlImport");
const K = await import("../src/kbIngest");
const editor = { userId: "ed", role: "editor", allowedNamespaces: ["shared:houdini22"] };
const post = (b) => new Request("https://x.test/p", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('ed','e','editor',1)").run();
db.prepare("INSERT INTO namespaces (namespace_id, scope) VALUES ('shared:houdini22','shared')").run();
const NS = "shared:houdini22";

async function crawlAll(body) {
  let r = await (await U.handleCrawlUrl(post(body), env, editor)).json();
  const results = [...(r.results || [])];
  for (let i = 0; i < 50 && !r.done; i++) { r = await (await U.handleCrawlUrl(post({ opId: r.opId, batchSize: 1 }), env, editor)).json(); results.push(...r.results); }
  return results;
}
const files = () => db.prepare("SELECT file FROM kb_documents WHERE namespace = ? ORDER BY file").all(NS).map((r) => r.file);
const bodyOf = (file) => db.prepare("SELECT body FROM chunks_fts WHERE namespace = ? AND file = ? ORDER BY rowid LIMIT 1").get(NS, file)?.body ?? "";

// ---- legacy state: an old registration under the plain title, with the page's analytics boilerplate ----
await K.ingestDocument(env, NS, "Merge", "window.dataLayer = window.dataLayer || []; function gtag(){dataLayer.push(arguments);} 旧形式の本文", "manual");
assert.deepEqual(files(), ["Merge"]);

// ---- first crawl ----
const out = await crawlAll({ namespace: NS, url: "https://www.sidefx.com/docs/houdini/nodes/index.html", depth: 1, maxPages: 20, batchSize: 1 });
assert.equal(out.every((r) => r.status === "ok"), true, JSON.stringify(out.map((r) => [r.title, r.status, r.error])));
// the three same-titled pages did NOT overwrite each other, and the legacy plain-title document is gone
assert.deepEqual(files(), ["Merge [DOP]", "Merge [SOP]", "Merge [VOP]", "Nodes", "Rivet"]);
// headers carry the context, the node type and the version taken from the namespace
assert.ok(bodyOf("Merge [SOP]").startsWith("【Houdini 22 / SOP / merge】\n"), bodyOf("Merge [SOP]").slice(0, 60));
assert.ok(bodyOf("Merge [VOP]").startsWith("【Houdini 22 / VOP / merge】\n"));
assert.ok(bodyOf("Merge [DOP]").startsWith("【Houdini 22 / DOP / merge】\n"));
// each page keeps its own content
assert.ok(bodyOf("Merge [SOP]").includes("SOPのMerge"));
assert.ok(bodyOf("Merge [VOP]").includes("VOPのMerge"));
// non-node pages (the index, a guide) are untouched: no header, plain title
assert.ok(!bodyOf("Rivet").startsWith("【"), "guide pages get no header");
assert.ok(!bodyOf("Nodes").startsWith("【"));
// vectors carry the header too (it is part of the chunk text that is embedded and returned)
assert.ok(upserts.some((v) => v.metadata.file === "Merge [SOP]" && v.metadata.text.startsWith("【Houdini 22 / SOP / merge】")));
assert.equal(db.prepare("SELECT COUNT(*) c FROM kb_documents WHERE namespace = ? AND file = 'Merge'").get(NS).c, 0, "legacy document removed from the index table");
assert.equal(db.prepare("SELECT COUNT(*) c FROM chunks_fts WHERE namespace = ? AND file = 'Merge'").get(NS).c, 0, "legacy chunks removed from the full-text index");
assert.ok(deleted.length >= 1, "legacy vector deleted");

// ---- second crawl: nothing changed -> no embedding, nothing stacked ----
const before = embedCalls;
const again = await crawlAll({ namespace: NS, url: "https://www.sidefx.com/docs/houdini/nodes/index.html", depth: 1, maxPages: 20, batchSize: 1 });
assert.equal(again.every((r) => r.status === "unchanged"), true, JSON.stringify(again.map((r) => [r.title, r.status])));
assert.equal(embedCalls, before);
assert.ok(bodyOf("Merge [SOP]").startsWith("【Houdini 22 / SOP / merge】\n") && !bodyOf("Merge [SOP]").startsWith("【Houdini 22 / SOP / merge】\n【"), "header is not stacked");

// ---- a page whose content changes is re-registered in place (same file name, still one header) ----
pages["https://www.sidefx.com/docs/houdini/nodes/sop/merge.html"] = "<html><title>Merge</title><body><main>SOPのMerge（更新）。 " + "い".repeat(80) + "</main></body></html>";
const changed = await crawlAll({ namespace: NS, url: "https://www.sidefx.com/docs/houdini/nodes/index.html", depth: 1, maxPages: 20, batchSize: 1 });
assert.equal(changed.find((r) => r.title === "Merge [SOP]").status, "ok");
assert.deepEqual(files(), ["Merge [DOP]", "Merge [SOP]", "Merge [VOP]", "Nodes", "Rivet"], "no duplicates after re-registering");
assert.ok(bodyOf("Merge [SOP]").includes("（更新）"));

// ---- single-URL import (import-url) applies the same rules ----
await K.ingestDocument(env, NS, "Null", "window.dataLayer = []; 旧", "manual");
pages["https://www.sidefx.com/docs/houdini/nodes/obj/null.html"] = "<html><title>Null</title><body><main>OBJのNull: 空のオブジェクトです。 " + "か".repeat(80) + "</main></body></html>";
const imp = await (await U.handleImportUrl(post({ namespace: NS, url: "https://www.sidefx.com/docs/houdini/nodes/obj/null.html", title: "Null" }), env, editor)).json();
assert.equal(imp.title, "Null [OBJ]");
assert.ok(files().includes("Null [OBJ]") && !files().includes("Null"));
assert.ok(bodyOf("Null [OBJ]").startsWith("【Houdini 22 / OBJ / null】"));

console.log("crawl_houdini tests passed");
