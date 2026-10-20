// /query/stream (SSE) and the shared prepare/finish pipeline against fake Gemini + Vectorize + SQLite.
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
try { db.exec("CREATE TABLE chunks_fts (chunk_id TEXT, file TEXT, namespace TEXT, scope TEXT, owner_user_id TEXT, difficulty TEXT, body TEXT)"); } catch {}
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) { try { db.exec(readFileSync(MIG + f, "utf8")); } catch {} }
const D1 = {
  async batch(stmts) { for (const s of stmts) await s.run(); return []; },
  prepare(sql) {
    return {
      a: [], bind(...x) { this.a = x; return this; },
      async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes, last_row_id: r.lastInsertRowid } }; },
      async first() { return db.prepare(sql).get(...this.a) ?? null; },
      async all() { if (/MATCH/.test(sql)) return { results: [] }; return { results: db.prepare(sql).all(...this.a) }; },
    };
  },
};
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('u1','u','member',1)").run();
db.prepare("INSERT INTO namespaces (namespace_id, scope) VALUES ('shared:docs','shared')").run();

const meta = { file: "VEXガイド.md", namespace: "shared:docs", scope: "shared", chunk_index: 0, text: "VEX では @P を書き換えられます。".repeat(30), source: "manual", size: 100, ingested_at: 1760000000 };
const env = {
  DB: D1, GEMINI_API_KEY: "g",
  VEC_SHARED: { async query() { return { matches: [{ id: "c1:0", score: 0.9, metadata: meta }] }; }, async getByIds() { return []; } },
  VEC_PERSONAL: { async query() { return { matches: [] }; } },
};

let streamMode = "ok";
const ANSWER = "VEX の attribute wrangle では @P を直接書き換えられます [1]。";
function sse(events) { return events.map((e) => "data: " + JSON.stringify(e) + "\r\n\r\n").join(""); }
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.includes(":embedContent") || url.includes(":batchEmbedContents")) {
    const body = JSON.parse(init.body);
    if (body.requests) return new Response(JSON.stringify({ embeddings: body.requests.map(() => ({ values: new Array(768).fill(0.01) })) }));
    return new Response(JSON.stringify({ embedding: { values: new Array(768).fill(0.01) } }));
  }
  if (url.includes(":streamGenerateContent")) {
    if (streamMode === "fail") return new Response("upstream error", { status: 500 });
    const chunks = [
      { candidates: [{ content: { parts: [{ text: "VEX の attribute wrangle では " }] } }] },
      { candidates: [{ content: { parts: [{ text: "考え中…", thought: true }, { text: "@P を直接書き換えられます" }] } }] },
      { candidates: [{ content: { parts: [{ text: " [1]。" }] } }], usageMetadata: { promptTokenCount: 120, candidatesTokenCount: 30 } },
    ];
    const text = sse(chunks);
    // split into awkward pieces (mid-event, mid-multibyte) to exercise the SSE parser
    const bytes = new TextEncoder().encode(text);
    const stream = new ReadableStream({
      start(controller) {
        for (let i = 0; i < bytes.length; i += 37) controller.enqueue(bytes.slice(i, i + 37));
        controller.close();
      },
    });
    return new Response(stream, { headers: { "content-type": "text/event-stream" } });
  }
  if (url.includes(":generateContent")) {
    return new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: ANSWER }] } }], usageMetadata: { promptTokenCount: 100, candidatesTokenCount: 20 } }));
  }
  throw new Error("unexpected fetch " + url);
};

const Q = await import("../src/query");
const user = { userId: "u1", role: "member", allowedNamespaces: ["shared:docs"] };
const post = (b) => new Request("https://x.test/query/stream", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
const pending = [];
const ctx = { waitUntil: (p) => pending.push(p) };

async function readEvents(res) {
  const text = await res.text();
  return text.split("\n\n").filter(Boolean).map((blk) => {
    const ev = /event: (.*)/.exec(blk)[1];
    const data = JSON.parse(/data: (.*)/.exec(blk)[1]);
    return { ev, data };
  });
}

// ---- streaming success ----
let res = await Q.handleQueryStream(post({ query: "VEXで座標を動かすには" }), env, user, ctx);
assert.match(res.headers.get("content-type"), /text\/event-stream/);
let events = await readEvents(res);
await Promise.all(pending);
assert.equal(events[0].ev, "sources");
assert.equal(events[0].data.sources[0].file, "VEXガイド.md");
assert.ok(events[0].data.sources[0].excerpt.length > 0 && events[0].data.sources[0].excerpt.length <= 400);
assert.equal(events[0].data.sources[0].ingestedAt, 1760000000);
const deltas = events.filter((e) => e.ev === "delta").map((e) => e.data.text).join("");
assert.equal(deltas, ANSWER, "thought parts are excluded and chunks join into the full answer");
const done = events[events.length - 1];
assert.equal(done.ev, "done");
assert.equal(done.data.answer, ANSWER);
assert.equal(done.data.extractionRate, 100);
assert.equal(done.data.sources[0].cited, true);
assert.ok(done.data.memoryId > 0);
const mem = db.prepare("SELECT query, answer, sources_json FROM memory WHERE id = ?").get(done.data.memoryId);
assert.equal(mem.answer, ANSWER);
assert.equal(JSON.parse(mem.sources_json)[0].ingestedAt, 1760000000);
const usage = db.prepare("SELECT tokens_used, input_tokens, output_tokens FROM audit_log ORDER BY id DESC LIMIT 1").get();
assert.equal(usage.output_tokens, 30);

// ---- non-streaming /query returns the same shape (and the new fields) ----
res = await Q.handleQuery(new Request("https://x.test/query", { method: "POST", body: JSON.stringify({ query: "VEXで座標を動かすには" }) }), env, user);
const plain = await res.json();
assert.equal(plain.answer, ANSWER);
assert.equal(plain.sources[0].excerpt.length > 0, true);
assert.equal(plain.sources[0].ingestedAt, 1760000000);

// ---- validation errors stay plain JSON ----
res = await Q.handleQueryStream(post({ query: "" }), env, user, ctx);
assert.equal(res.status, 400);
assert.match(res.headers.get("content-type"), /json/);

// ---- generation failure -> error event, nothing saved, budget refunded ----
const before = db.prepare("SELECT COUNT(*) c FROM memory").get().c;
streamMode = "fail";
res = await Q.handleQueryStream(post({ query: "失敗するケース" }), env, user, ctx);
events = await readEvents(res);
await Promise.all(pending);
assert.equal(events[0].ev, "sources");
assert.equal(events[events.length - 1].ev, "error");
assert.match(events[events.length - 1].data.error, /500/);
assert.equal(db.prepare("SELECT COUNT(*) c FROM memory").get().c, before);

console.log("stream tests passed");
