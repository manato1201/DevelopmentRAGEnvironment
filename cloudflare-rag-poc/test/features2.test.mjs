// Operation log (who), staging promote, knowledge gaps, crawl schedules.
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";
import { installHtmlRewriterShim } from "./helpers/htmlRewriterShim.mjs";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
try { db.exec("CREATE TABLE chunks_fts (chunk_id TEXT, file TEXT, namespace TEXT, scope TEXT, owner_user_id TEXT, difficulty TEXT, body TEXT)"); } catch {}
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) { try { db.exec(readFileSync(MIG + f, "utf8")); } catch (e) { console.log("migration skipped:", f, String(e.message).slice(0, 60)); } }
const D1 = {
  async batch(stmts) { for (const s of stmts) await s.run(); return []; },
  prepare(sql) {
    return {
      a: [], bind(...x) { this.a = x; return this; },
      async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes, last_row_id: r.lastInsertRowid } }; },
      async first() { return db.prepare(sql).get(...this.a) ?? null; },
      async all() { return { results: db.prepare(sql).all(...this.a) }; },
    };
  },
};

// ---- fake vector index that really stores vectors ----
const store = new Map();
const mkIndex = () => ({
  async upsert(v) { v.forEach((x) => store.set(x.id, x)); },
  async deleteByIds(ids) { ids.forEach((id) => store.delete(id)); },
  async getByIds(ids) { return ids.filter((id) => store.has(id)).map((id) => store.get(id)); },
});
const env = { DB: D1, GEMINI_API_KEY: "g", VEC_SHARED: mkIndex(), VEC_PERSONAL: mkIndex() };

// ---- HTMLRewriter shim + fake web + fake embeddings ----
installHtmlRewriterShim();
const pages = {
  "https://docs.test/": '<html><title>Top</title><body>トップ ' + "あ".repeat(60) + '<a href="/a">A</a><a href="/b">B</a></body></html>',
  "https://docs.test/a": "<html><title>A</title><body>" + "A本文 ".repeat(40) + "</body></html>",
  "https://docs.test/b": "<html><title>B</title><body>" + "B本文 ".repeat(40) + "</body></html>",
};
let embedCalls = 0;
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
const K = await import("../src/kbAdmin");
const IN = await import("../src/kbIngest");
const ST = await import("../src/staging");
const IG = await import("../src/insights");
const CS = await import("../src/crawlSchedules");
const T = await import("../src/syncTargets");

const post = (b) => new Request("https://x.test/p", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
const rejects = async (p, re) => assert.rejects(Promise.resolve().then(p), re);
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('ad','Admin太郎','admin',1),('ed','Editor花子','editor',1),('ed2','Editor次郎','editor',1)").run();
for (const ns of ["shared:docs", "shared:stage", "shared:prod", "shared:other"]) db.prepare("INSERT INTO namespaces (namespace_id, scope) VALUES (?, 'shared')").run(ns);
const admin = { userId: "ad", role: "admin", allowedNamespaces: [] };
const editor = { userId: "ed", role: "editor", allowedNamespaces: ["shared:docs", "shared:stage", "shared:prod"] };
const editor2 = { userId: "ed2", role: "editor", allowedNamespaces: ["shared:stage"] }; // no grant on shared:prod

// ============ 1) who ran each import ============
db.prepare("INSERT INTO sync_allowed_namespaces (namespace_id, created_at) VALUES ('shared:docs', 1)").run();
let r = await (await U.handleCrawlUrl(post({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 5, batchSize: 5 }), env, editor)).json();
assert.equal(r.done, true);
const op = db.prepare("SELECT user_id, kind, namespace_id FROM kb_ops WHERE op_id = ?").get(r.opId);
assert.deepEqual({ ...op }, { user_id: "ed", kind: "crawl", namespace_id: "shared:docs" });
await IN.recordOp(env, "cronop1", null, "jira", "shared:docs");
IN.logKb(env, "cronop1", "shared:docs", "jira", "J-1: x", "ok", "d");
await new Promise((r2) => setTimeout(r2, 20));
db.prepare("INSERT INTO kb_log (op_id, namespace_id, source, file, status, detail, created_at) VALUES ('legacy','shared:docs','manual','old.md','ok','', 1)").run();
db.prepare("INSERT INTO kb_log (op_id, namespace_id, source, file, status, detail, created_at) VALUES ('p1','personal:ed','gmail','mail','ok','', 99999999999)").run();
let hist = await (await K.handleKbHistory(post({ limit: 100 }), env, editor)).json();
const actors = new Set(hist.entries.map((e) => e.actor));
assert.ok(actors.has("Editor花子"), [...actors].join());
assert.ok(actors.has("自動（Cron）"));
assert.ok(actors.has("不明"));
assert.equal(hist.entries.some((e) => e.namespace_id.startsWith("personal:")), false, "personal-namespace history is not listed");

// ============ 2) staging ============
await rejects(() => ST.handleSetStaging(post({ staging: "shared:stage", target: "shared:prod" }), env, editor), /管理者/);
let res = await ST.handleSetStaging(post({ staging: "shared:stage", target: "shared:stage" }), env, admin);
assert.equal(res.status, 400);
res = await ST.handleSetStaging(post({ staging: "shared:stage", target: "shared:prod" }), env, admin);
assert.equal(res.status, 200);
assert.equal(db.prepare("SELECT COUNT(*) c FROM sync_allowed_namespaces WHERE namespace_id='shared:stage'").get().c, 1); // 受け皿は許可リストへ
assert.equal(db.prepare("SELECT COUNT(*) c FROM sync_allowed_namespaces WHERE namespace_id='shared:prod'").get().c, 0); // 本番は入れない
// integration-style write goes to staging only
await IN.ingestDocument(env, "shared:stage", "手順書.md", "ステージの本文です。" + "あ".repeat(900), "jira");
await IN.ingestDocument(env, "shared:stage", "メモ.md", "もう1件の本文", "gmail");
const pending = (await (await ST.handleListStaging(post({}), env, editor)).json()).pairs[0];
assert.equal(pending.pending, 2);
const docs = await (await ST.handleStagingDocs(post({ staging: "shared:stage" }), env, editor)).json();
assert.deepEqual(docs.documents.map((d) => d.file).sort(), ["メモ.md", "手順書.md"]);
assert.ok(docs.documents.find((d) => d.file === "手順書.md").excerpt.startsWith("ステージの本文"));
// editor without a grant on the target cannot promote
await rejects(() => ST.handlePromoteStaging(post({ staging: "shared:stage", files: ["手順書.md"] }), env, editor2), /書き込み権限/);
const chunksBefore = db.prepare("SELECT COUNT(*) c FROM chunks_fts WHERE namespace='shared:stage' AND file='手順書.md'").get().c;
assert.ok(chunksBefore >= 1);
res = await (await ST.handlePromoteStaging(post({ staging: "shared:stage", files: ["手順書.md", "存在しない.md"] }), env, editor)).json();
assert.equal(res.results.find((x) => x.file === "手順書.md").status, "ok");
assert.equal(res.results.find((x) => x.file === "存在しない.md").status, "error");
assert.equal(db.prepare("SELECT COUNT(*) c FROM chunks_fts WHERE namespace='shared:stage' AND file='手順書.md'").get().c, 0);
assert.equal(db.prepare("SELECT COUNT(*) c FROM chunks_fts WHERE namespace='shared:prod' AND file='手順書.md'").get().c, chunksBefore);
assert.equal(db.prepare("SELECT COUNT(*) c FROM kb_documents WHERE namespace='shared:prod' AND file='手順書.md'").get().c, 1);
assert.equal(db.prepare("SELECT COUNT(*) c FROM kb_documents WHERE namespace='shared:stage' AND file='手順書.md'").get().c, 0);
const movedVec = [...store.values()].filter((v) => v.metadata.file === "手順書.md");
assert.ok(movedVec.length === chunksBefore && movedVec.every((v) => v.metadata.namespace === "shared:prod"), "vectors re-keyed to the target, old ones removed");
assert.equal(db.prepare("SELECT status FROM kb_log WHERE namespace_id='shared:prod' AND file='手順書.md'").get().status, "ok");
assert.equal(db.prepare("SELECT user_id FROM kb_ops WHERE op_id = ?").get(res.opId).user_id, "ed");
assert.equal((await (await ST.handleListStaging(post({}), env, editor)).json()).pairs[0].pending, 1);

// ============ 3) knowledge gaps ============
const ins = db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, namespaces, rating, created_at) VALUES ('ad', ?, 'a', ?, '', ?, ?)");
const nowS = Math.floor(Date.now() / 1000);
ins.run("Houdini 22 の新機能は？", "[]", null, nowS - 100);
ins.run("houdini 22 の新機能は？ ", "[]", null, nowS - 50);
ins.run("VEXでループ", JSON.stringify([{ cited: false }, { cited: false }]), null, nowS - 10);
ins.run("よく答えられた質問", JSON.stringify([{ cited: true }]), 1, nowS - 10);
ins.run("低評価の質問", JSON.stringify([{ cited: true }]), -1, nowS - 10);
ins.run("古すぎる質問", "[]", null, nowS - 100 * 86400);
const gaps = await (await IG.handleKnowledgeGaps(post({ days: 30 }), env, admin)).json();
const byQ = Object.fromEntries(gaps.gaps.map((g) => [g.query.toLowerCase().trim(), g]));
assert.equal(gaps.gaps[0].count, 2, "same question grouped regardless of case/spaces");
assert.equal(byQ["houdini 22 の新機能は？"].noSources, 2);
assert.equal(byQ["vexでループ"].uncited, 1);
assert.equal(byQ["低評価の質問"].disliked, 1);
assert.equal(byQ["よく答えられた質問"], undefined);
assert.equal(byQ["古すぎる質問"], undefined);
await rejects(() => IG.handleKnowledgeGaps(post({}), env, editor), /管理者/);

// ============ 4) crawl schedules ============
// not allowed: shared:other is not on the allow-list
await rejects(() => CS.handleSaveCrawlSchedule(post({ namespace: "shared:other", url: "https://docs.test/" }), env, editor), /権限がありません|許可されていません/);
res = await (await CS.handleSaveCrawlSchedule(post({ namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 5, frequency: "daily" }), env, editor)).json();
const sid = res.id;
let list = (await (await CS.handleListCrawlSchedules(post({}), env, editor)).json()).schedules;
assert.equal(list.length, 1);
assert.equal(list[0].enabled, false, "schedules start disabled");
// disabled -> nothing runs
embedCalls = 0;
let tick = await CS.runScheduledCrawls(env, 5000);
assert.equal(tick.ran, 0);
assert.equal(embedCalls, 0);
// enable -> runs (pages already registered by the crawl above and unchanged -> no embedding at all)
await CS.handleSaveCrawlSchedule(post({ id: sid, namespace: "shared:docs", url: "https://docs.test/", depth: 1, maxPages: 5, frequency: "daily", enabled: true }), env, editor);
tick = await CS.runScheduledCrawls(env, 5000);
assert.equal(tick.ran, 1);
assert.equal(tick.finished, 1);
assert.equal(embedCalls, 0, "unchanged pages are not embedded again");
let row = db.prepare("SELECT last_run_at, active_op_id FROM crawl_schedules WHERE id = ?").get(sid);
assert.ok(row.last_run_at > 0);
assert.equal(row.active_op_id, null);
// not due again right away
tick = await CS.runScheduledCrawls(env, 5000);
assert.equal(tick.ran, 0);
// due again after a day, one page changed -> only that page is embedded
db.prepare("UPDATE crawl_schedules SET last_run_at = ? WHERE id = ?").run(nowS - 25 * 3600, sid);
pages["https://docs.test/b"] = "<html><title>B</title><body>更新されたB本文です " + "い".repeat(100) + "</body></html>";
embedCalls = 0;
tick = await CS.runScheduledCrawls(env, 5000);
assert.equal(tick.finished, 1);
assert.equal(embedCalls, 1, "only the changed page is re-embedded");
const cronOp = db.prepare("SELECT user_id FROM kb_ops WHERE kind = 'crawl' ORDER BY created_at DESC, rowid DESC LIMIT 1").get();
assert.equal(cronOp.user_id, null, "scheduled crawls are recorded as automatic runs");
// resume across ticks: a zero budget makes progress page by page and keeps the job
db.prepare("UPDATE crawl_schedules SET last_run_at = ? WHERE id = ?").run(nowS - 25 * 3600, sid);
db.prepare("DELETE FROM crawl_page_hashes").run();
tick = await CS.runScheduledCrawls(env, 0);
assert.equal(tick.finished, 0);
tick = await CS.runScheduledCrawls(env, 60000);
assert.equal(tick.finished, 1);
// removed from the allow-list -> the cron skips it
db.prepare("DELETE FROM sync_allowed_namespaces WHERE namespace_id = 'shared:docs'").run();
db.prepare("UPDATE crawl_schedules SET last_run_at = ? WHERE id = ?").run(nowS - 25 * 3600, sid);
tick = await CS.runScheduledCrawls(env, 5000);
assert.equal(tick.ran, 0);
// delete
await CS.handleDeleteCrawlSchedule(post({ id: sid }), env, admin);
assert.equal(db.prepare("SELECT COUNT(*) c FROM crawl_schedules").get().c, 0);

console.log("features2 tests passed");
