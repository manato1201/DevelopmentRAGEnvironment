// New providers: static OAuth clients (GitHub/Slack/Google), public no-auth servers, DCR servers listed.
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
for (const f of readdirSync(MIG)
  .filter((n) => n.endsWith(".sql"))
  .sort()) {
  try {
    db.exec(readFileSync(MIG + f, "utf8"));
  } catch {}
}
const D1 = {
  prepare(sql) {
    return {
      a: [],
      bind(...x) {
        this.a = x;
        return this;
      },
      async run() {
        const r = db.prepare(sql).run(...this.a);
        return { meta: { changes: r.changes } };
      },
      async first() {
        return db.prepare(sql).get(...this.a) ?? null;
      },
      async all() {
        return { results: db.prepare(sql).all(...this.a) };
      },
    };
  },
};

const prov = await import("../src/mcp/providers");
const auth = await import("../src/mcp/auth");
const svc = await import("../src/mcp/service");
const proto = await import("../src/mcp/protocol");

// ---- registry
const ids = prov.providerIds();
for (const id of [
  "notion",
  "vercel",
  "canva",
  "github",
  "slack",
  "gmail",
  "gdrive",
  "gcalendar",
  "figma",
  "cfdocs",
])
  assert.ok(ids.includes(id), id);
for (const p of Object.values(prov.MCP_PROVIDERS))
  assert.ok(p.url.startsWith("https://"), p.id);

// ---- setup detection
const bare = { DB: D1 };
assert.equal(prov.setupFor(bare, prov.MCP_PROVIDERS.github).needed, true);
assert.equal(prov.setupFor(bare, prov.MCP_PROVIDERS.gdrive).needed, true);
assert.equal(prov.setupFor(bare, prov.MCP_PROVIDERS.vercel).needed, false);
assert.equal(prov.setupFor(bare, prov.MCP_PROVIDERS.cfdocs).needed, false);
const env = {
  DB: D1,
  GMAIL_OAUTH_CLIENT_ID: "gid",
  GMAIL_OAUTH_CLIENT_SECRET: "gsec",
  SLACK_OAUTH_CLIENT_ID: "sid",
  SLACK_OAUTH_CLIENT_SECRET: "ssec",
};
assert.equal(prov.setupFor(env, prov.MCP_PROVIDERS.gdrive).needed, false);
assert.equal(prov.setupFor(env, prov.MCP_PROVIDERS.github).needed, true);
assert.deepEqual(prov.staticClientFor(env, prov.MCP_PROVIDERS.slack), {
  client_id: "sid",
  client_secret: "ssec",
}); // 通知用アプリのsecretを流用
// Google専用のクライアントがあれば、Gmail通知用より優先。IDとSecretは同じ組で使う
assert.deepEqual(prov.staticClientFor({ ...env, MCP_GOOGLE_CLIENT_ID: "mid", MCP_GOOGLE_CLIENT_SECRET: "msec" }, prov.MCP_PROVIDERS.gdrive), {
  client_id: "mid",
  client_secret: "msec",
});
assert.deepEqual(prov.staticClientFor({ ...env, MCP_GOOGLE_CLIENT_ID: "mid" }, prov.MCP_PROVIDERS.gdrive), { client_id: "mid" }, "never pairs the MCP id with the Gmail secret");

// ---- fake world
const calls = [];
const json = (o, s = 200) =>
  new Response(JSON.stringify(o), {
    status: s,
    headers: { "content-type": "application/json" },
  });
const fakeFetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  calls.push({ url, init });
  if (url.includes("/.well-known/oauth-protected-resource"))
    return json({
      authorization_servers: ["https://accounts.google.com/"],
      scopes_supported: ["x"],
    });
  if (
    url === "https://accounts.google.com/.well-known/oauth-authorization-server"
  )
    return json({
      issuer: "https://accounts.google.com",
      authorization_endpoint: "https://accounts.google.com/o/oauth2/v2/auth",
      token_endpoint: "https://oauth2.googleapis.com/token",
    });
  if (url === "https://oauth2.googleapis.com/token")
    return json({ access_token: "A", refresh_token: "R", expires_in: 3600 });
  if (url === "https://docs.mcp.cloudflare.com/mcp") {
    const body = JSON.parse(init.body);
    return json({
      jsonrpc: "2.0",
      id: body.id,
      result: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        serverInfo: { name: "x", version: "1" },
      },
    });
  }
  return new Response("not found", { status: 404 });
};

// ---- Google: authorize URL (no resource, offline, readonly scope, static client, no DCR call)
const gdrive = prov.MCP_PROVIDERS.gdrive;
const authUrl = new URL(
  await auth.buildAuthorizeUrl(env, gdrive, "https://w.test", "u1", fakeFetch),
);
assert.equal(authUrl.searchParams.get("client_id"), "gid");
assert.equal(authUrl.searchParams.get("resource"), null);
assert.equal(authUrl.searchParams.get("access_type"), "offline");
assert.equal(authUrl.searchParams.get("prompt"), "consent");
assert.equal(
  authUrl.searchParams.get("scope"),
  "https://www.googleapis.com/auth/drive.readonly",
);
assert.equal(
  authUrl.searchParams.get("redirect_uri"),
  "https://w.test/admin/oauth/mcp/callback",
);
assert.equal(authUrl.searchParams.get("code_challenge_method"), "S256");
assert.equal(
  calls.some((c) => String(c.url).includes("register")),
  false,
);

// ---- Google: token exchange sends client_secret, no resource
const state = authUrl.searchParams.get("state");
const payload = await auth.consumeState(env, state);
const cred = await auth.exchangeCode("CODE", payload, gdrive, fakeFetch);
const tokenCall = calls.find(
  (c) => c.url === "https://oauth2.googleapis.com/token",
);
const form = new URLSearchParams(tokenCall.init.body);
assert.equal(form.get("client_secret"), "gsec");
assert.equal(form.get("client_id"), "gid");
assert.equal(form.get("resource"), null);
assert.equal(form.get("code_verifier").length > 20, true);
assert.equal(cred.accessToken, "A");

// ---- missing secret → clear error, no authorize URL
await assert.rejects(
  () =>
    auth.buildAuthorizeUrl(
      { DB: D1 },
      prov.MCP_PROVIDERS.github,
      "https://w.test",
      "u1",
      fakeFetch,
    ),
  /準備が必要/,
);

// ---- public server: connect without any OAuth, session sends no Authorization header
const p = await svc.connectPublic(env, "cfdocs", "u1");
assert.equal(p.id, "cfdocs");
const row = db
  .prepare("SELECT * FROM mcp_connections WHERE provider_id = 'cfdocs'")
  .get();
assert.equal(row.status, "connected");
await assert.rejects(
  () => svc.connectPublic(env, "vercel", "u1"),
  /認証が必要/,
);
await proto.openSession("https://docs.mcp.cloudflare.com/mcp", "", fakeFetch);
const initCall = calls.filter(
  (c) => c.url === "https://docs.mcp.cloudflare.com/mcp",
)[0];
assert.equal(initCall.init.headers.Authorization, undefined);

// ---- statuses
const st = await svc.statuses(env);
const by = Object.fromEntries(st.map((s) => [s.id, s]));
assert.equal(by.cfdocs.connected, true);
assert.equal(by.cfdocs.noAuth, true);
assert.equal(by.github.setupRequired, true);
assert.equal(by.github.setupHint.includes("callback"), true);
assert.equal(by.gdrive.setupRequired, false);
assert.equal(by.vercel.setupRequired, false);
// 2026-10-22に外した（使わない）サービスは、一覧に出ない
for (const gone of ["linear", "sentry", "atlassian"]) assert.equal(prov.providerIds().includes(gone), false, gone);

console.log("mcp extension tests passed");
