// Threads, scope presets and the Slack slash command (signature, linking, async answer).
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { createHmac } from "node:crypto";
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
const meta = { file: "ガイド.md", namespace: "shared:docs", scope: "shared", chunk_index: 0, text: "本文", source: "manual", size: 10, ingested_at: 1 };
const env = {
  DB: D1, GEMINI_API_KEY: "g", SLACK_SIGNING_SECRET: "sek", SLACK_TEAM_IDS: "T1,T2",
  VEC_SHARED: { async query() { return { matches: [{ id: "c1:0", score: 0.9, metadata: meta }] }; }, async getByIds() { return []; } },
  VEC_PERSONAL: { async query() { return { matches: [] }; } },
};
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('u1','a','member',1),('u2','b','member',1),('g1','g','guest',1)").run();
db.prepare("INSERT INTO namespaces (namespace_id, scope) VALUES ('shared:docs','shared'),('shared:other','shared')").run();
db.prepare("INSERT INTO key_namespace_grants (user_id, namespace_id) VALUES ('u1','shared:docs')").run();

let lastPrompt = "";
const posted = [];
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.startsWith("https://hooks.slack.com/")) { posted.push({ url, body: JSON.parse(init.body) }); return new Response("ok"); }
  if (url.includes(":batchEmbedContents")) return new Response(JSON.stringify({ embeddings: JSON.parse(init.body).requests.map(() => ({ values: new Array(768).fill(0.01) })) }));
  if (url.includes(":embedContent")) return new Response(JSON.stringify({ embedding: { values: new Array(768).fill(0.01) } }));
  if (url.includes(":generateContent")) {
    lastPrompt = JSON.parse(init.body).contents[0].parts[0].text;
    return new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: "答えです [1]。" }] } }], usageMetadata: { promptTokenCount: 10, candidatesTokenCount: 5 } }));
  }
  throw new Error("unexpected fetch " + url);
};

const TH = await import("../src/threads");
const PR = await import("../src/presets");
const SB = await import("../src/slackBot");
const Q = await import("../src/query");
const MEM = await import("../src/memory");
const KA = await import("../src/keyAdmin");

const u1 = { userId: "u1", role: "member", allowedNamespaces: ["shared:docs", "personal:u1"] };
const u2 = { userId: "u2", role: "member", allowedNamespaces: ["shared:docs"] };
const guest = { userId: "g1", role: "guest", allowedNamespaces: [] };
const admin = { userId: "ad", role: "admin", allowedNamespaces: [] };
const post = (b) => new Request("https://x.test/p", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
const rejects = async (p, re) => assert.rejects(Promise.resolve().then(p), re);

// =============== threads ===============
const T1 = "thread-aaaa-1111";
async function ask(user, q, threadId, history) {
  const res = await Q.handleQuery(post({ query: q, threadId, history }), env, user);
  assert.equal(res.status, 200);
  return res.json();
}
await ask(u1, "最初の質問です", T1);
await ask(u1, "続きの質問です", T1, [{ role: "user", content: "最初の質問です" }, { role: "assistant", content: "答えです" }]);
let list = await (await TH.handleThreadList(post({}), env, u1)).json();
assert.equal(list.threads.length, 1);
assert.equal(list.threads[0].title, "最初の質問です");
assert.equal(list.threads[0].turns, 2);
await ask(u1, "スレッドなしの質問", undefined);
list = await (await TH.handleThreadList(post({}), env, u1)).json();
assert.equal(list.legacyCount, 1);
// search by title / question / answer, with wildcard characters taken literally
assert.equal((await (await TH.handleThreadList(post({ q: "続きの" }), env, u1)).json()).threads.length, 1);
assert.equal((await (await TH.handleThreadList(post({ q: "答えです" }), env, u1)).json()).threads.length, 1);
assert.equal((await (await TH.handleThreadList(post({ q: "%" }), env, u1)).json()).threads.length, 0);
assert.equal((await (await TH.handleThreadList(post({ q: "存在しない語" }), env, u1)).json()).threads.length, 0);
// get: ordered, own only
const got = await (await TH.handleThreadGet(post({ threadId: T1 }), env, u1)).json();
assert.deepEqual(got.entries.map((e) => e.query), ["最初の質問です", "続きの質問です"]);
assert.equal((await TH.handleThreadGet(post({ threadId: T1 }), env, u2)).status, 404);
assert.equal((await TH.handleThreadGet(post({ threadId: "bad id!" }), env, u1)).status, 400);
// another user can't push into / hijack my thread id
const before = db.prepare("SELECT COUNT(*) c FROM memory WHERE thread_id = ?").get(T1).c;
await ask(u2, "他人の質問", T1);
assert.equal(db.prepare("SELECT COUNT(*) c FROM memory WHERE thread_id = ?").get(T1).c, before);
assert.equal(db.prepare("SELECT thread_id FROM memory WHERE query = '他人の質問'").get().thread_id, null);
// rename / delete
assert.equal((await TH.handleThreadRename(post({ threadId: T1, title: "改名後" }), env, u2)).status, 404);
assert.equal((await TH.handleThreadRename(post({ threadId: T1, title: "改名後" }), env, u1)).status, 200);
assert.equal((await (await TH.handleThreadList(post({}), env, u1)).json()).threads[0].title, "改名後");
await rejects(() => TH.handleThreadList(post({}), env, guest), /ゲスト/);
// history context is capped server-side (6 turns, 800 chars)
const long = "あ".repeat(5000);
await ask(u1, "履歴の上限", T1, Array.from({ length: 10 }, (_, i) => ({ role: i % 2 ? "assistant" : "user", content: i === 9 ? long : "h" + i })));
assert.ok(!lastPrompt.includes("h0"), "old turns dropped");
assert.ok(lastPrompt.includes("h4") && lastPrompt.includes("h8"), "recent turns kept");
assert.ok(!lastPrompt.includes("あ".repeat(801)), "long turns truncated");
await TH.handleThreadDelete(post({ threadId: T1 }), env, u2); // not mine -> nothing happens
assert.ok(db.prepare("SELECT COUNT(*) c FROM memory WHERE thread_id = ?").get(T1).c > 0);
await TH.handleThreadDelete(post({ threadId: T1 }), env, u1);
assert.equal(db.prepare("SELECT COUNT(*) c FROM memory WHERE thread_id = ?").get(T1).c, 0);
assert.equal(db.prepare("SELECT COUNT(*) c FROM threads WHERE thread_id = ?").get(T1).c, 0);

// =============== presets ===============
let r = await PR.handlePresetSave(post({ name: "Houdini関連", namespaces: ["shared:docs"] }), env, u1);
assert.equal(r.status, 200);
r = await PR.handlePresetSave(post({ name: "禁止", namespaces: ["shared:other"] }), env, u1);
assert.equal(r.status, 403);
assert.equal((await PR.handlePresetSave(post({ name: "", namespaces: ["shared:docs"] }), env, u1)).status, 400);
assert.equal((await PR.handlePresetSave(post({ name: "空", namespaces: [] }), env, u1)).status, 400);
await PR.handlePresetSave(post({ name: "Houdini関連", namespaces: ["shared:docs", "personal:u1"] }), env, u1); // overwrite
let pl = (await (await PR.handlePresetList(post({}), env, u1)).json()).presets;
assert.deepEqual(pl, [{ name: "Houdini関連", namespaces: ["shared:docs", "personal:u1"] }]);
// access removed later -> filtered out when listed
const u1NoDocs = { ...u1, allowedNamespaces: ["personal:u1"] };
pl = (await (await PR.handlePresetList(post({}), env, u1NoDocs)).json()).presets;
assert.deepEqual(pl[0].namespaces, ["personal:u1"]);
assert.deepEqual((await (await PR.handlePresetList(post({}), env, u2)).json()).presets, []); // per user
await rejects(() => PR.handlePresetList(post({}), env, guest), /ゲスト/);
await PR.handlePresetDelete(post({ name: "Houdini関連" }), env, u1);
assert.equal((await (await PR.handlePresetList(post({}), env, u1)).json()).presets.length, 0);

// =============== Slack ===============
const sign = (body, ts, secret = "sek") => "v0=" + createHmac("sha256", secret).update(`v0:${ts}:${body}`).digest("hex");
const nowS = Math.floor(Date.now() / 1000);
assert.equal(await SB.verifySlackSignature("sek", String(nowS), sign("a=b", nowS), "a=b"), true);
assert.equal(await SB.verifySlackSignature("sek", String(nowS), sign("a=b", nowS), "a=c"), false);
assert.equal(await SB.verifySlackSignature("sek", String(nowS), sign("a=b", nowS, "other"), "a=b"), false);
assert.equal(await SB.verifySlackSignature("sek", String(nowS - 4000), sign("a=b", nowS - 4000), "a=b"), false); // replay window
assert.equal(await SB.verifySlackSignature("", String(nowS), sign("a=b", nowS), "a=b"), false);
assert.equal(await SB.verifySlackSignature("sek", null, null, "a=b"), false);

const pending = [];
const ctx = { waitUntil: (p) => pending.push(p) };
function slackReq(fields, { ts = nowS, secret = "sek", badSig = false } = {}) {
  const body = new URLSearchParams(fields).toString();
  const sig = badSig ? "v0=deadbeef" : sign(body, ts, secret);
  return new Request("https://x.test/slack/command", { method: "POST", headers: { "x-slack-request-timestamp": String(ts), "x-slack-signature": sig, "content-type": "application/x-www-form-urlencoded" }, body });
}
const base = { team_id: "T1", user_id: "USLACK1", response_url: "https://hooks.slack.com/commands/T1/1/abc" };
async function cmd(text, extra = {}, opts) { const res = await SB.handleSlackCommand(slackReq({ ...base, text, ...extra }, opts), env, ctx); return { status: res.status, json: await res.json() }; }

assert.equal((await cmd("hi", {}, { badSig: true })).status, 401);
assert.equal((await cmd("hi", {}, { ts: nowS - 4000 })).status, 401);
const noSecret = await SB.handleSlackCommand(slackReq({ ...base, text: "hi" }), { ...env, SLACK_SIGNING_SECRET: undefined }, ctx);
assert.equal(noSecret.status, 503);
assert.match((await cmd("hi", { team_id: "TX" })).json.text, /許可されていません/);
assert.match((await cmd("help")).json.text, /\/rag link/);
assert.match((await cmd("何か質問")).json.text, /連携されていません/);
assert.equal(posted.length, 0);

// link flow
const code = (await (await SB.handleSlackLinkCode(post({}), env, u1)).json()).code;
assert.match(code, /^[A-Z2-9]{8}$/);
await rejects(() => SB.handleSlackLinkCode(post({}), env, guest), /ゲスト/);
const bad = await cmd("link WRONGCODE");
assert.match(bad.json.text, /無効/);
const okLink = await cmd("link " + code.toLowerCase());
assert.match(okLink.json.text, /連携しました/);
assert.equal(db.prepare("SELECT user_id FROM slack_bindings WHERE team_id='T1' AND slack_user_id='USLACK1'").get().user_id, "u1");
assert.match((await cmd("link " + code)).json.text, /無効/, "codes are single-use");
// expired code
db.prepare("INSERT INTO slack_link_codes (code, user_id, expires_at) VALUES ('OLDCODE2', 'u2', ?)").run(nowS - 5);
assert.match((await cmd("link OLDCODE2", { user_id: "USLACK2" })).json.text, /無効/);
// a guest account can't be linked
db.prepare("INSERT INTO slack_link_codes (code, user_id, expires_at) VALUES ('GUESTCD2', 'g1', ?)").run(nowS + 600);
assert.match((await cmd("link GUESTCD2", { user_id: "USLACK3" })).json.text, /連携できません/);

// ask as the linked user: immediate ack, answer arrives via response_url, only that user's namespaces are searched
const ack = await cmd("VEXで座標を動かすには");
assert.equal(ack.json.response_type, "ephemeral");
assert.match(ack.json.text, /調べています/);
await Promise.all(pending);
assert.equal(posted.length, 1);
assert.equal(posted[0].url, "https://hooks.slack.com/commands/T1/1/abc");
assert.equal(posted[0].body.response_type, "ephemeral");
assert.match(posted[0].body.text, /答えです/);
assert.match(posted[0].body.text, /\[1\] ガイド\.md（docs）/); // 名前空間の接頭辞（shared:）は、Slackでは出さない
assert.match(posted[0].body.text, /回答で使った資料: 1件/);
assert.match(posted[0].body.text, /AIが生成した回答です/);
const mem = db.prepare("SELECT user_id FROM memory WHERE query = 'VEXで座標を動かすには'").get();
assert.equal(mem.user_id, "u1", "asked under the linked user's identity (history, budget, audit)");
// a response_url that is not Slack is never called
posted.length = 0;
await cmd("もう一つ質問", { response_url: "https://evil.example.com/steal" });
await Promise.all(pending);
assert.equal(posted.length, 0);
// unlink
assert.match((await cmd("unlink")).json.text, /解除/);
assert.match((await cmd("何か質問")).json.text, /連携されていません/);
// status / unlink from the web side, and key deletion cleans up
await SB.handleSlackLinkCode(post({}), env, u1);
db.prepare("INSERT INTO slack_bindings (team_id, slack_user_id, user_id, created_at) VALUES ('T1','USLACK9','u1',1)").run();
assert.equal((await (await SB.handleSlackStatus(post({}), env, u1)).json()).linked, 1);
await SB.handleSlackUnlink(post({}), env, u1);
assert.equal((await (await SB.handleSlackStatus(post({}), env, u1)).json()).linked, 0);
db.prepare("INSERT INTO slack_bindings (team_id, slack_user_id, user_id, created_at) VALUES ('T1','USLACK8','u2',1)").run();
db.prepare("INSERT INTO scope_presets (user_id, name, namespaces_json, created_at) VALUES ('u2','p','[]',1)").run();
env.VEC_PERSONAL.deleteByIds = async () => {};
const del = await KA.handleDeleteKey(post({ userId: "u2" }), env, admin);
assert.equal(del.status, 200);
assert.equal(db.prepare("SELECT COUNT(*) c FROM slack_bindings WHERE user_id='u2'").get().c, 0);
assert.equal(db.prepare("SELECT COUNT(*) c FROM scope_presets WHERE user_id='u2'").get().c, 0);
assert.equal(db.prepare("SELECT COUNT(*) c FROM threads WHERE user_id='u2'").get().c, 0);

console.log("features3 tests passed");
