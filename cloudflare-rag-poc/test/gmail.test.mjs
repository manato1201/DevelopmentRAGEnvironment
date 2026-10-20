// Gmail / Drive(OAuth) sync end-to-end against a fake Google + Gemini and a real SQLite (node:sqlite).
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) {
  try { db.exec(readFileSync(MIG + f, "utf8")); } catch (e) { console.log("migration skipped:", f, String(e.message).slice(0, 80)); }
}
try { db.exec('CREATE TABLE IF NOT EXISTS chunks_fts (chunk_id TEXT, file TEXT, namespace TEXT, scope TEXT, owner_user_id TEXT, difficulty TEXT, body TEXT)'); } catch {}
const D1 = {
  prepare(sql) {
    return {
      a: [], bind(...x) { this.a = x; return this; },
      async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes } }; },
      async first() { return db.prepare(sql).get(...this.a) ?? null; },
      async all() { return { results: db.prepare(sql).all(...this.a) }; },
    };
  },
};
const upserts = [];
const env = {
  DB: D1, GEMINI_API_KEY: "g", GMAIL_OAUTH_CLIENT_ID: "cid", GMAIL_OAUTH_CLIENT_SECRET: "csec",
  VEC_SHARED: { async upsert(v) { upserts.push(...v); } },
};

const b64 = (s) => Buffer.from(s, "utf8").toString("base64url");
const mails = {
  m1: { id: "m1", internalDate: String(Date.UTC(2026, 9, 8, 3, 0, 0)), payload: { mimeType: "multipart/alternative", headers: [{ name: "Subject", value: "=?UTF-8?B?" + Buffer.from("打ち合わせの件").toString("base64") + "?=" }, { name: "From", value: "Alice <a@example.com>" }], parts: [{ mimeType: "text/plain", body: { data: b64("明日の会議は10時です。") } }, { mimeType: "text/html", body: { data: b64("<p>html版</p>") } }] } },
  m2: { id: "m2", internalDate: String(Date.UTC(2026, 9, 7, 3, 0, 0)), payload: { mimeType: "text/html", headers: [{ name: "Subject", value: "HTMLだけ" }], body: { data: b64("<style>x{}</style><div>本文<br>2行目 &amp; 3</div>") } } },
  m3: { id: "m3", internalDate: String(Date.UTC(2026, 9, 6, 3, 0, 0)), payload: { mimeType: "multipart/mixed", headers: [{ name: "Subject", value: "添付のみ" }], parts: [{ mimeType: "application/pdf", filename: "a.pdf", body: { data: b64("PDF") } }] } },
};
const calls = [];
let failM2 = false;
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  calls.push(url.replace(/key=[^&]+/, "key=***"));
  const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "content-type": "application/json" } });
  if (url.startsWith("https://oauth2.googleapis.com/token")) {
    const p = new URLSearchParams(init.body);
    if (p.get("grant_type") === "refresh_token") return json({ access_token: "refreshed", expires_in: 3600 });
    return json({ access_token: "acc", refresh_token: "ref", expires_in: 3600 });
  }
  if (url.includes("gmail.googleapis.com/gmail/v1/users/me/profile")) return json({ emailAddress: "me@example.com" });
  if (url.includes("www.googleapis.com/drive/v3/about")) return json({ user: { emailAddress: "drive@example.com" } });
  if (url.includes("/gmail/v1/users/me/labels")) return json({ labels: [{ id: "L1", name: "project x", type: "user" }, { id: "INBOX", name: "INBOX", type: "system" }] });
  if (url.includes("/gmail/v1/users/me/messages?")) {
    const q = new URL(url).searchParams.get("q");
    assert.equal(q, "label:project-x");
    return json({ messages: [{ id: "m1" }, { id: "m2" }, { id: "m3" }], resultSizeEstimate: 3 });
  }
  const m = /\/gmail\/v1\/users\/me\/messages\/(\w+)\?format=full/.exec(url);
  if (m) {
    assert.match(init.headers.Authorization, /^Bearer /);
    if (m[1] === "m2" && failM2) return json({ error: "boom" }, 500);
    return json(mails[m[1]]);
  }
  if (url.includes(":batchEmbedContents")) {
    const n = JSON.parse(init.body).requests.length;
    return json({ embeddings: Array.from({ length: n }, () => ({ values: new Array(768).fill(0.01) })) });
  }
  throw new Error("unexpected fetch: " + url);
};

const oauth = await import("../src/googleOAuth");
const gm = await import("../src/gmailSync");
const kb = await import("../src/kbAdmin");

db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('u','t','admin',1)").run();
db.prepare("INSERT INTO namespaces (namespace_id, scope) VALUES ('shared:mail','shared')").run();
db.prepare("INSERT INTO sync_allowed_namespaces (namespace_id, added_by, created_at) VALUES ('shared:mail','u',1)").run();
const user = { userId: "u", role: "admin", allowedNamespaces: [] };
const post = (path, body) => new Request("https://x.test" + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

// --- decodeMimeHeader
assert.equal(gm.decodeMimeHeader("=?UTF-8?B?" + Buffer.from("日本語").toString("base64") + "?="), "日本語");
assert.equal(gm.decodeMimeHeader("=?UTF-8?Q?a=20b?="), "a b");

// --- OAuth callback (drive + gmail) stores token + account
for (const [svc, acct] of [["google_drive", "drive@example.com"], ["gmail", "me@example.com"]]) {
  db.prepare("INSERT INTO oauth_pending_state (state, service, created_at, extra_json) VALUES (?, ?, ?, '{}')").run("st-" + svc, svc, Math.floor(Date.now() / 1000));
  const res = await oauth.handleGoogleOAuthCallback(new Request(`https://x.test/admin/oauth/${svc}/callback?code=c&state=st-${svc}`), env, svc);
  assert.equal(res.status, 200);
  const st = await oauth.googleOAuthStatus(env, svc);
  assert.deepEqual(st, { connected: true, label: acct });
}
// bad state is rejected
const bad = await oauth.handleGoogleOAuthCallback(new Request("https://x.test/admin/oauth/gmail/callback?code=c&state=nope"), env, "gmail");
assert.match(await bad.text(), /有効期限|不正/);

// --- refresh path
db.prepare("UPDATE oauth_connections SET expires_at = 1 WHERE service = 'gmail'").run();
assert.equal(await oauth.resolveGoogleOAuthAccessToken(env, "gmail"), "refreshed");

// --- sync requires a query
let res = await gm.handleSyncGmail(post("/admin/sync/gmail", { namespace: "shared:mail" }), env, user);
assert.equal(res.status, 400);
assert.match((await res.json()).error, /検索式/);

// --- set source via kbAdmin
res = await kb.handleSetKbSource(post("/admin/kb/set-source", { namespace: "shared:mail", gmailQuery: "label:project-x" }), env, user);
assert.equal(res.status, 200);
assert.equal(db.prepare("SELECT gmail_query FROM kb_sources WHERE namespace_id='shared:mail'").get().gmail_query, "label:project-x");

// --- label list
res = await gm.handleListGmailLabels(post("/admin/gmail/list-labels", {}), env, user);
assert.deepEqual((await res.json()).labels, [{ id: "project x", summary: "project x", query: "label:project-x" }]);

// --- test connection
res = await gm.handleTestGmailConnection(post("/admin/kb/test-connection/gmail", { namespace: "shared:mail" }), env, user);
assert.match((await res.json()).message, /約3件/);

// --- full sync (m2 fails)
failM2 = true;
res = await gm.handleSyncGmail(post("/admin/sync/gmail", { namespace: "shared:mail", batchSize: 2 }), env, user);
let data = await res.json();
assert.equal(data.totalMessages, 3);
assert.equal(data.nextIndex, 2);
assert.equal(data.documents, 1);
assert.equal(data.results[0].file.startsWith("打ち合わせの件 (2026-10-08) #m1"), true, data.results[0].file);
assert.equal(data.results[1].status, "error");
const opId = data.opId;
res = await gm.handleSyncGmail(post("/admin/sync/gmail", { namespace: "shared:mail", batchSize: 2, startIndex: 2, opId }), env, user);
data = await res.json();
assert.equal(data.nextIndex, null);
// m3 is attachment-only: subject line still makes the text non-empty, so it ingests
assert.equal(data.documents, 1);
const text1 = upserts.find((v) => v.metadata.file.includes("#m1")).metadata.text;
assert.match(text1, /差出人: Alice/);
assert.match(text1, /明日の会議は10時です/);
assert.doesNotMatch(text1, /html版/);

// --- retry the failed one
failM2 = false;
res = await gm.handleRetryFailedGmail(post("/admin/sync/gmail/retry-failed", { namespace: "shared:mail", opId }), env, user);
data = await res.json();
assert.equal(data.documents, 1);
assert.equal(data.results[0].status, "ok");
const text2 = upserts.find((v) => v.metadata.file.includes("#m2")).metadata.text;
assert.match(text2, /本文\n2行目 & 3/);
assert.doesNotMatch(text2, /x\{\}/);
const logRows = db.prepare("SELECT status, source FROM kb_log WHERE op_id = ?").all(opId);
assert.equal(logRows.every((r) => r.source === "gmail"), true);
assert.equal(logRows.filter((r) => r.status === "error").length, 0);

// --- overview flags
res = await kb.handleKbOverview(post("/admin/kb/overview", {}), env, user);
assert.equal((await res.json()).namespaces[0].hasGmailSource, true);

// --- disconnect
await oauth.handleGoogleOAuthDisconnect(post("/admin/oauth/gmail/disconnect", {}), env, user, "gmail");
assert.deepEqual(await oauth.googleOAuthStatus(env, "gmail"), { connected: false });
res = await gm.handleSyncGmail(post("/admin/sync/gmail", { namespace: "shared:mail" }), env, user);
assert.match((await res.json()).error, /未接続/);

console.log("gmail/drive oauth tests passed");
