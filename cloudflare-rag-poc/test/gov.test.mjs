// Governance: migration 0021 on existing data, allow-list, per-user connections/sync, preview, opt-in auto sync, per-user MCP.
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const files = readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort();
const db = new DatabaseSync(":memory:");
try { db.exec("CREATE TABLE chunks_fts (chunk_id TEXT, file TEXT, namespace TEXT, scope TEXT, owner_user_id TEXT, difficulty TEXT, body TEXT)"); } catch {}
// --- apply everything before 0021, seed legacy data, then apply 0021
for (const f of files.filter((n) => n < "0021")) { try { db.exec(readFileSync(MIG + f, "utf8")); } catch {} }
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('admin','a','admin',1),('ed','e','editor',1),('mem','m','member',1),('other','o','member',1),('guest','g','guest',1)").run();
for (const [id, scope, owner] of [["shared:old", "shared", null], ["shared:new", "shared", null], ["shared:mail", "shared", null], ["personal:mem", "personal", "mem"], ["personal:other", "personal", "other"]]) {
  db.prepare("INSERT INTO namespaces (namespace_id, scope, owner_user_id) VALUES (?, ?, ?)").run(id, scope, owner);
}
db.prepare("INSERT INTO kb_sources (namespace_id, notion_database_id, calendar_id) VALUES ('shared:old', 'nd', 'cal-old')").run();
db.prepare("INSERT INTO oauth_connections (service, access_token, refresh_token, expires_at, extra_json, connected_at) VALUES ('jira','legacy-jira','r',NULL,'{\"cloudId\":\"c1\",\"siteName\":\"Old\"}',1)").run();
db.prepare("INSERT INTO mcp_connections (provider_id, access_token, resource_url, token_endpoint, client_json, status, chat_enabled, connected_at, updated_at) VALUES ('notion','legacy-notion','https://mcp.notion.com/mcp','t','{\"client_id\":\"c\"}','connected',1,1,1)").run();
db.exec(readFileSync(MIG + "0021_sync_governance.sql", "utf8"));
for (const f of files.filter((n) => n.slice(0, 4) > "0021")) db.exec(readFileSync(MIG + f, "utf8"));

// migration results
assert.equal(db.prepare("SELECT owner_id, access_token FROM oauth_connections WHERE service='jira'").get().owner_id, "");
assert.equal(db.prepare("SELECT owner_id, chat_enabled FROM mcp_connections WHERE provider_id='notion'").get().chat_enabled, 1);
assert.deepEqual(db.prepare("SELECT namespace_id FROM sync_allowed_namespaces").all().map((r) => r.namespace_id), ["shared:old"]); // existing source seeded
assert.equal(db.prepare("SELECT auto_calendar FROM kb_sources WHERE namespace_id='shared:old'").get().auto_calendar, 0); // opt-in: off by default

const D1 = {
  async batch(stmts) { for (const st of stmts) await st.run(); return []; },
  prepare(sql) {
    return {
      a: [], bind(...x) { this.a = x; return this; },
      async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes } }; },
      async first() { return db.prepare(sql).get(...this.a) ?? null; },
      async all() { return { results: db.prepare(sql).all(...this.a) }; },
    };
  },
};
const sharedUp = [], personalUp = [];
const env = { DB: D1, GEMINI_API_KEY: "g", GMAIL_OAUTH_CLIENT_ID: "cid", GMAIL_OAUTH_CLIENT_SECRET: "csec",
  VEC_SHARED: { async upsert(v) { sharedUp.push(...v); } }, VEC_PERSONAL: { async upsert(v) { personalUp.push(...v); } } };

const mkUser = (userId, role, allowed = []) => ({ userId, role, allowedNamespaces: allowed });
const admin = mkUser("admin", "admin", ["shared:old", "shared:new", "shared:mail"]);
const editor = mkUser("ed", "editor", ["shared:old"]); // no grant on shared:new / shared:mail
const mem = mkUser("mem", "member", []);
const guest = mkUser("guest", "guest");
const post = (path, body) => new Request("https://x.test" + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

const b64 = (s) => Buffer.from(s, "utf8").toString("base64url");
const calls = [];
const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "content-type": "application/json" } });
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  calls.push({ url, auth: init.headers?.Authorization });
  if (url.startsWith("https://oauth2.googleapis.com/token")) return json({ access_token: "tok-" + new URLSearchParams(init.body).get("code"), refresh_token: "ref", expires_in: 3600 });
  if (url.includes("gmail/v1/users/me/profile")) return json({ emailAddress: "mem@example.com" });
  if (url.includes("/gmail/v1/users/me/messages?")) return json({ messages: [{ id: "m1" }, { id: "m2" }], resultSizeEstimate: 2 });
  let m = /\/gmail\/v1\/users\/me\/messages\/(\w+)\?(.*)/.exec(url);
  if (m) {
    const meta = m[2].includes("format=metadata");
    const hdr = [{ name: "Subject", value: "件名" + m[1] }, { name: "From", value: "a@example.com" }];
    return json({ id: m[1], internalDate: String(Date.UTC(2026, 9, 8)), payload: meta ? { headers: hdr } : { mimeType: "text/plain", headers: hdr, body: { data: b64("本文" + m[1]) } } });
  }
  if (url.includes("calendar/v3/calendars/") && url.includes("/events")) return json({ items: [{ id: "e1", summary: "予定A", start: { dateTime: "2026-10-10T10:00:00Z" } }] });
  if (url.includes(":batchEmbedContents")) return json({ embeddings: Array.from({ length: JSON.parse(init.body).requests.length }, () => ({ values: new Array(768).fill(0.01) })) });
  throw new Error("unexpected fetch " + url);
};

const T = await import("../src/syncTargets");
const G = await import("../src/gmailSync");
const GO = await import("../src/googleOAuth");
const CAL = await import("../src/calendarSync");
const KB = await import("../src/kbAdmin");
const KD = await import("../src/kbDocuments");
const S = await import("../src/mcp/service");
const AUTH = await import("../src/auth");

const rejects = async (p, re) => assert.rejects(Promise.resolve().then(p), re);

// ---------------- authorizeSync ----------------
assert.deepEqual(await T.authorizeSync(env, admin, "shared:old"), { ownerId: "" });
await rejects(() => T.authorizeSync(env, admin, "shared:new"), /許可されていません/);            // not on allow-list
await rejects(() => T.authorizeSync(env, editor, "shared:mail"), /権限がありません|許可されていません/); // editor without grant
await rejects(() => T.authorizeSync(env, mem, "shared:old"), /ナレッジ登録権限/);               // member can't touch shared
assert.deepEqual(await T.authorizeSync(env, mem, "personal:mem"), { ownerId: "mem" });         // own personal
await rejects(() => T.authorizeSync(env, mem, "personal:other"), /他のユーザー/);               // someone else's
await rejects(() => T.authorizeSync(env, guest, "personal:guest"), /ゲスト/);

// ---------------- allow-list admin API ----------------
let r = await T.handleAddSyncTarget(post("/x", { namespace: "shared:new" }), env, admin);
assert.equal(r.status, 200);
await rejects(() => T.handleAddSyncTarget(post("/x", { namespace: "shared:mail" }), env, editor), /管理者/);
r = await T.handleAddSyncTarget(post("/x", { namespace: "personal:mem" }), env, admin);
assert.equal(r.status, 400);
r = await T.handleListSyncTargets(post("/x", {}), env, editor);
const list = await r.json();
assert.deepEqual(list.allowed.map((a) => a.namespace_id).sort(), ["shared:new", "shared:old"]);
assert.ok(list.candidates.includes("shared:mail"));
assert.deepEqual(await T.authorizeSync(env, admin, "shared:new"), { ownerId: "" });

// ---------------- set-source + auto flags ----------------
await rejects(() => KB.handleSetKbSource(post("/x", { namespace: "shared:mail", gmailQuery: "label:x" }), env, admin), /許可されていません/);
r = await KB.handleSetKbSource(post("/x", { namespace: "shared:old", jiraProjectKey: "P", autoJira: true }), env, admin);
assert.equal(r.status, 200);
assert.equal(db.prepare("SELECT auto_jira, auto_calendar FROM kb_sources WHERE namespace_id='shared:old'").get().auto_jira, 1);
r = await KB.handleSetKbSource(post("/x", { namespace: "shared:old", jiraExtraJql: "x" }), env, admin); // 指定なし＝既存のまま
assert.equal(db.prepare("SELECT auto_jira FROM kb_sources WHERE namespace_id='shared:old'").get().auto_jira, 1);
r = await KB.handleSetKbSource(post("/x", { namespace: "shared:old", clearJira: true }), env, admin); // 解除したら自動もオフ
assert.equal(db.prepare("SELECT auto_jira FROM kb_sources WHERE namespace_id='shared:old'").get().auto_jira, 0);
// removing from allow-list switches auto-sync off
await KB.handleSetKbSource(post("/x", { namespace: "shared:new", calendarId: "cal-new", autoCalendar: true }), env, admin);
assert.equal(db.prepare("SELECT auto_calendar FROM kb_sources WHERE namespace_id='shared:new'").get().auto_calendar, 1);
await T.handleRemoveSyncTarget(post("/x", { namespace: "shared:new" }), env, admin);
assert.equal(db.prepare("SELECT auto_calendar FROM kb_sources WHERE namespace_id='shared:new'").get().auto_calendar, 0);
await T.handleAddSyncTarget(post("/x", { namespace: "shared:new" }), env, admin);

// ---------------- per-user Gmail connection (OAuth callback keyed by owner) ----------------
const now = Math.floor(Date.now() / 1000);
db.prepare("INSERT INTO oauth_pending_state (state, service, created_at, extra_json) VALUES ('st-mem','gmail',?,?)").run(now, JSON.stringify({ owner_id: "mem" }));
let res = await GO.handleGoogleOAuthCallback(new Request("https://x.test/admin/oauth/gmail/callback?code=MEM&state=st-mem"), env, "gmail");
assert.equal(res.status, 200);
db.prepare("INSERT INTO oauth_pending_state (state, service, created_at, extra_json) VALUES ('st-sh','gmail',?,?)").run(now, JSON.stringify({ owner_id: "" }));
await GO.handleGoogleOAuthCallback(new Request("https://x.test/admin/oauth/gmail/callback?code=SHARED&state=st-sh"), env, "gmail");
assert.deepEqual(await GO.googleOAuthStatus(env, "gmail", "mem"), { connected: true, label: "mem@example.com" });
assert.equal((await GO.googleOAuthStatus(env, "gmail", "other")).connected, false);
assert.equal(db.prepare("SELECT COUNT(*) c FROM oauth_connections WHERE service='gmail'").get().c, 2);

// member sets own source + syncs into personal index with HIS token
res = await KB.handleSetKbSource(post("/x", { namespace: "personal:mem", gmailQuery: "label:mine" }), env, mem);
assert.equal(res.status, 200);
// preview: lists, writes nothing
const upBefore = sharedUp.length + personalUp.length;
const logBefore = db.prepare("SELECT COUNT(*) c FROM kb_log").get().c;
calls.length = 0;
res = await G.handlePreviewGmail(post("/x", { namespace: "personal:mem" }), env, mem);
let pv = await res.json();
assert.equal(pv.total, 2);
assert.equal(pv.personal, true);
assert.equal(pv.items[0].title, "件名m1");
assert.equal(sharedUp.length + personalUp.length, upBefore);
assert.equal(db.prepare("SELECT COUNT(*) c FROM kb_log").get().c, logBefore);
assert.ok(calls.filter((c) => c.auth).every((c) => c.auth === "Bearer tok-MEM"), JSON.stringify(calls.map((c) => c.auth)));
// real sync
calls.length = 0;
res = await G.handleSyncGmail(post("/x", { namespace: "personal:mem" }), env, mem);
let sy = await res.json();
assert.equal(sy.documents, 2);
assert.equal(sharedUp.length, 0, "personal data must not go to the shared index");
assert.equal(personalUp.length > 0, true);
assert.equal(personalUp[0].metadata.scope, "personal");
assert.equal(personalUp[0].metadata.owner_user_id, "mem");
assert.equal(db.prepare("SELECT scope, owner_user_id FROM chunks_fts WHERE namespace='personal:mem' LIMIT 1").get().owner_user_id, "mem");
assert.equal(db.prepare("SELECT scope FROM kb_documents WHERE namespace='personal:mem' LIMIT 1").get().scope, "personal");
assert.ok(calls.filter((c) => c.auth).every((c) => c.auth === "Bearer tok-MEM"));
// other user cannot read or delete it
await rejects(() => KD.handleListDocuments(post("/x", { namespace: "personal:mem" }), env, mkUser("other", "member")), /他のユーザー/);
await rejects(() => G.handleSyncGmail(post("/x", { namespace: "personal:mem" }), env, mkUser("other", "member")), /他のユーザー/);
res = await KD.handleListDocuments(post("/x", { namespace: "personal:mem" }), env, mem);
const docFiles = (await res.json()).files;
assert.equal(docFiles.length, 2);
const vecDeleted = [];
env.VEC_PERSONAL.deleteByIds = async (ids) => { vecDeleted.push(...ids); };
env.VEC_SHARED.deleteByIds = async () => { throw new Error("shared index must not be touched"); };
res = await KD.handleDeleteDocument(post("/x", { namespace: "personal:mem", file: docFiles[0] }), env, mem);
assert.equal(res.status, 200);
assert.equal(vecDeleted.length > 0, true);

// shared sync uses the shared token and needs the allow-list
db.prepare("INSERT OR IGNORE INTO sync_allowed_namespaces (namespace_id, created_at) VALUES ('shared:mail', 1)").run();
await KB.handleSetKbSource(post("/x", { namespace: "shared:mail", gmailQuery: "label:team" }), env, admin);
calls.length = 0;
res = await G.handleSyncGmail(post("/x", { namespace: "shared:mail" }), env, admin);
assert.equal((await res.json()).documents, 2);
assert.ok(calls.filter((c) => c.auth).every((c) => c.auth === "Bearer tok-SHARED"));
assert.equal(sharedUp.length > 0, true);
assert.equal(sharedUp[0].metadata.scope, "shared");
await rejects(() => G.handleSyncGmail(post("/x", { namespace: "shared:mail" }), env, editor), /権限がありません/); // editor w/o grant
db.prepare("DELETE FROM sync_allowed_namespaces WHERE namespace_id='shared:mail'").run();
await rejects(() => G.handleSyncGmail(post("/x", { namespace: "shared:mail" }), env, admin), /許可されていません/); // allow-list revoked → blocked

// ---------------- scheduled calendar sync: opt-in + allow-list + owner token ----------------
db.prepare("INSERT INTO oauth_connections (service, owner_id, access_token, refresh_token, expires_at, extra_json, connected_at) VALUES ('google_calendar', '', 'cal-shared', 'r', NULL, '{}', 1)").run();
db.prepare("INSERT INTO oauth_connections (service, owner_id, access_token, refresh_token, expires_at, extra_json, connected_at) VALUES ('google_calendar', 'mem', 'cal-mem', 'r', NULL, '{}', 1)").run();
db.prepare("UPDATE kb_sources SET auto_calendar = 0").run();
db.prepare("UPDATE kb_sources SET calendar_id='mine@x', auto_calendar=1 WHERE namespace_id='personal:mem'").run();
db.prepare("INSERT OR REPLACE INTO kb_sources (namespace_id, calendar_id, auto_calendar) VALUES ('shared:mail','blocked@x',1)").run(); // not on the allow-list now
db.prepare("INSERT OR REPLACE INTO kb_sources (namespace_id, calendar_id, auto_calendar) VALUES ('shared:old','old@x',0)").run(); // opted out
calls.length = 0;
await CAL.runScheduledCalendarSync(env);
const calCalls = calls.filter((c) => c.url.includes("/events"));
assert.equal(calCalls.length, 1, JSON.stringify(calCalls.map((c) => c.url)));
assert.equal(calCalls[0].auth, "Bearer cal-mem");
assert.ok(calCalls[0].url.includes("mine%40x"));
db.prepare("UPDATE kb_sources SET auto_calendar = 1 WHERE namespace_id = 'shared:old'").run();
calls.length = 0;
await CAL.runScheduledCalendarSync(env);
const calCalls2 = calls.filter((c) => c.url.includes("/events"));
assert.deepEqual(calCalls2.map((c) => c.auth).sort(), ["Bearer cal-mem", "Bearer cal-shared"]);

// ---------------- per-user MCP ----------------
await S.connectPublic(env, "mslearn", "mem", "mem");
assert.equal((await S.statuses(env, "mem")).find((p) => p.id === "mslearn").connected, true);
assert.equal((await S.statuses(env, "other")).find((p) => p.id === "mslearn").connected, false);
assert.equal((await S.statuses(env)).find((p) => p.id === "mslearn").connected, false); // shared untouched
assert.equal((await S.statuses(env)).find((p) => p.id === "notion").connected, true); // legacy shared connection survived the migration
await S.setChatEnabled(env, "mslearn", true, "mem");
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url === "https://learn.microsoft.com/api/mcp") {
    const body = JSON.parse(init.body);
    if (body.method === "initialize") return json({ jsonrpc: "2.0", id: body.id, result: { protocolVersion: "2025-03-26", capabilities: {}, serverInfo: { name: "x", version: "1" } } });
    if (body.method === "notifications/initialized") return new Response(null, { status: 202 });
    if (body.method === "tools/list") return json({ jsonrpc: "2.0", id: body.id, result: { tools: [{ name: "search", description: "d", inputSchema: { type: "object" }, annotations: { readOnlyHint: true } }] } });
  }
  return realFetch(input, init);
};
const tools = await S.chatTools(env, fetch, "mem");
assert.deepEqual(tools.map((t) => [t.providerId, t.ownerId]), [["mslearn", "mem"]]);
assert.deepEqual(await S.chatTools(env, fetch, "other"), []); // another user doesn't get mem's connection
assert.deepEqual(await S.chatTools(env, fetch, ""), []);
globalThis.fetch = realFetch;
await S.disconnect(env, "mslearn", "mem", "mem");
assert.equal((await S.statuses(env, "mem")).find((p) => p.id === "mslearn").connected, false);

// ---------------- key deletion removes per-user connections ----------------
const KA = await import("../src/keyAdmin");
db.prepare("INSERT INTO oauth_connections (service, owner_id, access_token, connected_at) VALUES ('jira','other','x',1)").run();
db.prepare("INSERT INTO mcp_connections (provider_id, owner_id, access_token, resource_url, token_endpoint, client_json, connected_at, updated_at) VALUES ('linear','other','x','u','t','{}',1,1)").run();
env.VEC_PERSONAL.deleteByIds = async () => {};
res = await KA.handleDeleteKey(post("/x", { userId: "other" }), env, admin);
assert.equal(res.status, 200);
assert.equal(db.prepare("SELECT COUNT(*) c FROM oauth_connections WHERE owner_id='other'").get().c, 0);
assert.equal(db.prepare("SELECT COUNT(*) c FROM mcp_connections WHERE owner_id='other'").get().c, 0);

console.log("governance tests passed");
