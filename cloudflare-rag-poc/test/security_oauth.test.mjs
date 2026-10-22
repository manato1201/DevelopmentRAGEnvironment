// 2026-10-22 のセキュリティ点検で直した箇所のテスト: Backlogのホスト制限、OAuth開始の使い捨てトークン、stateの1回きりの消費、セキュリティヘッダー。
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) { try { db.exec(readFileSync(MIG + f, "utf8")); } catch { /* fts5 など */ } }
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
const env = { DB: D1, BACKLOG_OAUTH_CLIENT_ID: "cid", BACKLOG_OAUTH_CLIENT_SECRET: "TOP-SECRET" };
const { sha256Hex } = await import("../src/embeddings");
const oc = await import("../src/oauthConnections");
const bl = await import("../src/backlogOAuth");
const http = await import("../src/http");

// ---- F1: Backlog のスペースは Nulab のドメインだけ
const n = bl.normalizeSpaceUrl;
assert.equal(n("yourspace.backlog.com"), "https://yourspace.backlog.com");
assert.equal(n("https://Team-1.backlog.jp/"), "https://team-1.backlog.jp");
assert.equal(n("x.backlogtool.com"), "https://x.backlogtool.com");
for (const bad of ["evil.example.com", "https://evil.com", "backlog.com.evil.com", "x.backlog.com.evil.com", "evilbacklog.com", "https://x.backlog.com:8443", "https://user:pw@x.backlog.com", "https://evil.com/.backlog.com", "", "  ", "backlog.com", "..backlog.com", "http://127.0.0.1"]) {
  assert.equal(n(bad), null, bad);
}

// 開始: 任意のホストは、リダイレクトされない
for (const k of ["a-key"]) {
  const uid = await sha256Hex(k);
  db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES (?, ?, 'member', 1)").run(uid, "m");
}
const startUrl = (space, q = "") => `https://rag.example/admin/oauth/backlog/start?key=a-key&owner=me&space=${encodeURIComponent(space)}${q}`;
let res = await bl.handleBacklogOAuthStart(new Request(startUrl("evil.example.com")), env);
assert.equal(res.status, 400, "a foreign host is refused (no redirect, no secret sent)");
res = await bl.handleBacklogOAuthStart(new Request(startUrl("team.backlog.com")), env);
assert.equal(res.status, 302); assert.ok(res.headers.get("location").startsWith("https://team.backlog.com/OAuth2AccessRequest.action?"));

// コールバック: 古い・細工したstateに、悪いホストが入っていても、secret は送らない
let fetched = [];
const realFetch = globalThis.fetch; globalThis.fetch = async (u, i) => { fetched.push(String(u)); return new Response("{}", { status: 400 }); };
try {
  const evilState = await oc.createPendingState(env, "backlog", { spaceUrl: "https://evil.example.com", owner_id: "x" });
  res = await bl.handleBacklogOAuthCallback(new Request(`https://rag.example/admin/oauth/backlog/callback?code=c&state=${evilState}`), env);
  assert.equal(res.status, 400); assert.deepEqual(fetched, [], "nothing was sent to the foreign host");
  assert.ok(!JSON.stringify(fetched).includes("TOP-SECRET"));
  // 保存済みの接続に、悪いホストが入っていても、更新で、secret を送らない
  await oc.saveConnection(env, "backlog", { accessToken: "old", refreshToken: "r", expiresAt: 1, extra: { spaceUrl: "https://evil.example.com" }, ownerId: "x" });
  assert.equal(await bl.resolveBacklogOAuthContext(env, "x"), null); assert.deepEqual(fetched, []);
} finally { globalThis.fetch = realFetch; }

// ---- F4: stateは1回だけ。期限切れも消える
const st = await oc.createPendingState(env, "jira", { a: 1 });
assert.deepEqual(await oc.consumePendingState(env, "jira", st), { a: 1 });
assert.equal(await oc.consumePendingState(env, "jira", st), null, "second use is refused");
const st2 = await oc.createPendingState(env, "jira", {});
assert.equal(await oc.consumePendingState(env, "slack", st2), null, "another service's state is refused");
db.prepare("UPDATE oauth_pending_state SET created_at = created_at - 1000").run();
assert.equal(await oc.consumePendingState(env, "jira", st2), null, "expired");

// ---- F2: 開始の使い捨てトークン
const uid = await sha256Hex("a-key");
const member = { userId: uid, role: "member", allowedNamespaces: [] };
res = await oc.handleOAuthStartToken(new Request("https://rag.example/me/oauth-start-token", { method: "POST" }), env, member);
assert.equal(res.status, 200); const { token } = await res.json();
assert.ok(token && !token.includes("a-key"), "the token is not the key");
const viaToken = new Request(`https://rag.example/admin/oauth/backlog/start?t=${token}`);
let who = await oc.authenticateFromQueryKey(viaToken, env);
assert.equal(who.userId, uid);
assert.equal(await oc.authenticateFromQueryKey(viaToken, env), null, "single use");
const old = await (await oc.handleOAuthStartToken(new Request("https://rag.example/x", { method: "POST" }), env, member)).json();
db.prepare("UPDATE oauth_pending_state SET created_at = created_at - 120 WHERE service = 'start'").run();
assert.equal(await oc.authenticateFromQueryKey(new Request(`https://rag.example/s?t=${old.token}`), env), null, "expires after 60 seconds");
assert.equal(await oc.authenticateFromQueryKey(new Request("https://rag.example/s?t=nope"), env), null);
assert.equal((await oc.authenticateFromQueryKey(new Request("https://rag.example/s?key=a-key"), env)).userId, uid, "the old ?key= form still works (deprecated)");
assert.equal((await oc.handleOAuthStartToken(new Request("https://rag.example/x", { method: "POST" }), env, { ...member, role: "guest" })).status, 403);
// 別のサービス用のstateは、開始トークンとして使えない
const other = await oc.createPendingState(env, "jira", { user_id: uid });
assert.equal(await oc.authenticateFromQueryKey(new Request(`https://rag.example/s?t=${other}`), env), null);

// ---- F5: ヘッダー
const page = http.oauthResultPage(true, "<b>x</b>");
assert.equal(page.headers.get("x-frame-options"), "DENY"); assert.match(page.headers.get("content-security-policy"), /frame-ancestors 'none'/);
assert.ok(!(await page.text()).includes("<b>x</b>"), "the message is escaped");
console.log("security tests OK");
