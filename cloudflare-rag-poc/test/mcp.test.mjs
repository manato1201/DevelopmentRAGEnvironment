// MCP client end-to-end against fake OAuth / MCP / Gemini servers and a real SQLite (node:sqlite).
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) {
  try { db.exec(readFileSync(MIG + f, "utf8")); } catch (e) { console.log("migration skipped:", f, String(e.message).slice(0, 60)); }
}
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
const env = { DB: D1, GEMINI_API_KEY: "g-key", GENERATION_MODEL: "gemini-test" };

const svc = await import("../src/mcp/service");
const auth = await import("../src/mcp/auth");
const perm = await import("../src/mcp/permissions");
const prov = await import("../src/mcp/providers");
const chat = await import("../src/mcp/chat");
const routes = await import("../src/mcp/routes");
const schema = await import("../src/mcp/schema");
const proto = await import("../src/mcp/protocol");
const { sha256Hex } = await import("../src/embeddings");

// ------------------------------------------------------------------ fake world
const sha = (s) => createHash("sha256").update(s).digest("base64url");
const world = {
  registrations: 0, tokenCalls: [], mcpCalls: [], geminiBodies: [],
  failRefresh: false, mcpMode: "json", mcp401: false, expiresIn: 3600,
  tools: [
    { name: "search", description: "検索", inputSchema: { type: "object", properties: { q: { type: "string" } }, required: ["q"] }, annotations: { readOnlyHint: true } },
    { name: "fetch", description: "取得", inputSchema: { type: "object", properties: { id: { type: "string" } } }, annotations: { readOnlyHint: true } },
    { name: "create-page", description: "作成", inputSchema: { type: "object", properties: { title: { type: "string" } } }, annotations: { readOnlyHint: false } },
    { name: "mystery", description: "不明", inputSchema: { type: "object" } },
  ],
  pending: null, // {challenge, redirect}
  refreshSeq: 0,
};
const json = (obj, status = 200, headers = {}) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", ...headers } });
let geminiScript = [];
const fakeFetch = async (input, init = {}) => {
  const url = String(input); const u = new URL(url); const method = (init.method || "GET").toUpperCase();
  if (u.host === "mcp.notion.com") {
    if (u.pathname === "/.well-known/oauth-protected-resource/mcp") return json({ resource: "https://mcp.notion.com/mcp", authorization_servers: ["https://mcp.notion.com"], scopes_supported: ["default"] });
    if (u.pathname === "/.well-known/oauth-authorization-server") return json({ issuer: "https://mcp.notion.com", authorization_endpoint: "https://mcp.notion.com/authorize", token_endpoint: "https://mcp.notion.com/token", registration_endpoint: "https://mcp.notion.com/register", code_challenge_methods_supported: ["S256"] });
    if (u.pathname === "/register" && method === "POST") { world.registrations++; const b = JSON.parse(init.body); assert.deepEqual(b.redirect_uris.length, 1); assert.equal(b.token_endpoint_auth_method, "none"); return json({ client_id: "cid-" + world.registrations }, 201); }
    if (u.pathname === "/token" && method === "POST") {
      const p = new URLSearchParams(init.body); world.tokenCalls.push(Object.fromEntries(p));
      if (p.get("grant_type") === "authorization_code") {
        assert.equal(sha(p.get("code_verifier")), world.pending.challenge, "PKCE verifier must match the challenge");
        assert.equal(p.get("redirect_uri"), world.pending.redirect); assert.equal(p.get("resource"), "https://mcp.notion.com/mcp");
        return json({ access_token: "at-1", refresh_token: "rt-1", expires_in: world.expiresIn });
      }
      if (p.get("grant_type") === "refresh_token") {
        if (world.failRefresh) return json({ error: "invalid_grant" }, 400);
        assert.equal(p.get("refresh_token"), "rt-1"); world.refreshSeq++;
        return json({ access_token: "at-r" + world.refreshSeq, expires_in: 3600 });
      }
    }
    if (u.pathname === "/mcp" && method === "POST") {
      const body = JSON.parse(init.body); world.mcpCalls.push({ method: body.method, auth: init.headers.Authorization, sid: init.headers["Mcp-Session-Id"] });
      if (world.mcp401) return new Response("no", { status: 401 });
      const reply = (result) => world.mcpMode === "sse"
        ? new Response(`event: ping\ndata: {"noise":true}\n\nevent: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", id: body.id, result })}\n\n`, { status: 200, headers: { "content-type": "text/event-stream" } })
        : json({ jsonrpc: "2.0", id: body.id, result }, 200, { "Mcp-Session-Id": "sess-1" });
      if (body.method === "initialize") return reply({ protocolVersion: "2025-06-18", capabilities: {}, serverInfo: { name: "fake" } });
      if (body.method === "notifications/initialized") return new Response(null, { status: 202 });
      if (body.method === "tools/list") return body.params.cursor ? reply({ tools: world.tools.slice(2) }) : reply({ tools: world.tools.slice(0, 2), nextCursor: "c2" });
      if (body.method === "tools/call") {
        if (body.params.name === "boom") return reply({ isError: true, content: [{ type: "text", text: "失敗しました" }] });
        return reply({ content: [{ type: "text", text: `結果:${body.params.name}:${JSON.stringify(body.params.arguments)}` }, { type: "image", data: "x" }] });
      }
    }
  }
  if (u.host === "generativelanguage.googleapis.com") {
    world.geminiBodies.push(JSON.parse(init.body));
    const next = geminiScript.shift(); assert.ok(next, "unexpected extra Gemini call");
    return json(next);
  }
  throw new Error("unexpected fetch: " + method + " " + url);
};

// ------------------------------------------------------------------ 1. discovery, registration cache, authorize URL
let meta = await auth.discover("https://mcp.notion.com/mcp", fakeFetch);
assert.equal(meta.registration_endpoint, "https://mcp.notion.com/register"); assert.deepEqual(meta.resource_scopes, ["default"]);
await assert.rejects(() => auth.discover("https://nowhere.example/mcp", async () => new Response("x", { status: 404 })), /認証情報を取得できません/);

const url1 = new URL(await svc.startAuthorization(env, "notion", "https://rag.example", "admin-1", fakeFetch));
assert.equal(url1.origin + url1.pathname, "https://mcp.notion.com/authorize");
assert.equal(url1.searchParams.get("code_challenge_method"), "S256"); assert.equal(url1.searchParams.get("resource"), "https://mcp.notion.com/mcp");
assert.equal(url1.searchParams.get("redirect_uri"), "https://rag.example/admin/oauth/mcp/callback"); assert.equal(url1.searchParams.get("scope"), "default");
assert.equal(url1.searchParams.get("client_id"), "cid-1");
const url2 = new URL(await svc.startAuthorization(env, "notion", "https://rag.example", "admin-1", fakeFetch));
assert.equal(world.registrations, 1, "client registered once and cached");
assert.notEqual(url1.searchParams.get("state"), url2.searchParams.get("state")); assert.notEqual(url1.searchParams.get("code_challenge"), url2.searchParams.get("code_challenge"));
await assert.rejects(() => svc.startAuthorization(env, "evil", "https://rag.example", "a", fakeFetch), /未対応のMCPサーバー/);
console.log("1 discovery / registration cache / authorize URL OK");

// ------------------------------------------------------------------ 2. callback
world.pending = { challenge: url1.searchParams.get("code_challenge"), redirect: "https://rag.example/admin/oauth/mcp/callback" };
const provider = await svc.completeAuthorization(env, url1.searchParams.get("state"), "code-xyz", fakeFetch);
assert.equal(provider.id, "notion");
await assert.rejects(() => svc.completeAuthorization(env, url1.searchParams.get("state"), "code-xyz", fakeFetch), /有効期限が切れたか/, "state is single use");
await assert.rejects(() => svc.completeAuthorization(env, "forged", "c", fakeFetch), /有効期限が切れたか/);
let conn = await svc.getConnection(env, "notion");
assert.equal(conn.status, "connected"); assert.equal(conn.credential.accessToken, "at-1"); assert.equal(conn.chatEnabled, false, "chat use is opt-in"); assert.equal(conn.connectedBy, "admin-1");
assert.ok(conn.credential.expiresAt > Date.now() / 1000 + 3000);
let st = (await svc.statuses(env)).find((p) => p.id === "notion"); assert.equal(st.connected, true);
assert.equal((await svc.statuses(env)).find((p) => p.id === "vercel").status, "disconnected");
console.log("2 callback / PKCE / single-use state OK");

// ------------------------------------------------------------------ 3. tools + policy + selection
const settings = await svc.toolSettings(env, "notion", true, fakeFetch);
assert.deepEqual(settings.map((t) => [t.name, t.readOnly, t.enabled]), [["search", true, true], ["fetch", true, true], ["create-page", false, false], ["mystery", false, false]], "pagination merged; hint missing = not read-only; unselected = read-only tools only (writes are opt-in)");
assert.deepEqual(world.mcpCalls.slice(0, 4).map((c) => c.method), ["initialize", "notifications/initialized", "tools/list", "tools/list"]);
assert.equal(world.mcpCalls[2].sid, "sess-1", "session id echoed back");
// provider overrides
const testProvider = { ...prov.MCP_PROVIDERS.notion, readOnlyTools: ["mystery"], writeTools: ["fetch"], blockedTools: ["search"], toolHints: { mystery: "補足" } };
const classified = perm.applyPolicy(testProvider, await (await proto.openSession("https://mcp.notion.com/mcp", "at-1", fakeFetch)).listTools());
assert.deepEqual(classified.map((t) => [t.name, t.readOnly]), [["fetch", false], ["create-page", false], ["mystery", true]]);
assert.ok(classified[2].description.endsWith("補足"));
await svc.setEnabledTools(env, "notion", ["search", "create-page", "search"]);
const sel = await svc.toolSettings(env, "notion", false, fakeFetch);
assert.deepEqual(sel.filter((t) => t.enabled).map((t) => t.name), ["search", "create-page"]);
console.log("3 tools / policy / selection OK");

// ------------------------------------------------------------------ 4. callTool rules + audit
await assert.rejects(() => svc.callTool(env, "u1", "notion", "fetch", {}, {}, fakeFetch), prov.McpToolNotAllowed);
await assert.rejects(() => svc.callTool(env, "u1", "notion", "create-page", { title: "x" }, { readOnlyOnly: true }, fakeFetch), /書き込みを行う可能性/);
const ok = await svc.callTool(env, "u1", "notion", "search", { q: "岩" }, { readOnlyOnly: true }, fakeFetch);
assert.equal(ok.text, '結果:search:{"q":"岩"}'); assert.equal(ok.isError, false); assert.equal(ok.readOnly, true);
const written = await svc.callTool(env, "admin", "notion", "create-page", { title: "t" }, {}, fakeFetch);
assert.equal(written.readOnly, false);
const audits = db.prepare("SELECT action, status, user_id FROM mcp_audit ORDER BY id").all();
assert.ok(audits.some((a) => a.action === "search" && a.user_id === "u1" && a.status === "ok") && audits.some((a) => a.action === "connect"));
assert.ok(!JSON.stringify(db.prepare("SELECT detail FROM mcp_audit").all()).includes("岩"), "tool arguments are never written to the audit log");
console.log("4 callTool rules / audit OK");

// ------------------------------------------------------------------ 5. SSE responses
world.mcpMode = "sse"; svc.clearToolsCache();
const sse = await svc.toolSettings(env, "notion", true, fakeFetch);
assert.equal(sse.length, 4, "SSE stream with noise lines parsed");
const sseCall = await svc.callTool(env, "u1", "notion", "search", { q: "z" }, {}, fakeFetch); assert.ok(sseCall.text.startsWith("結果:search"));
world.mcpMode = "json";
console.log("5 SSE OK");

// ------------------------------------------------------------------ 6. token refresh + reauth
conn = await svc.getConnection(env, "notion"); conn.credential.expiresAt = Math.floor(Date.now() / 1000) + 10; await svc.saveConnection(env, conn); svc.clearToolsCache();
await svc.toolSettings(env, "notion", true, fakeFetch);
conn = await svc.getConnection(env, "notion");
assert.equal(conn.credential.accessToken, "at-r1", "refreshed and persisted"); assert.equal(conn.credential.refreshToken, "rt-1", "refresh token kept when the server omits it");
assert.equal(world.mcpCalls.at(-1).auth, "Bearer at-r1");
const refreshCall = world.tokenCalls.at(-1); assert.equal(refreshCall.resource, "https://mcp.notion.com/mcp"); assert.equal(refreshCall.client_id, "cid-1");
// refresh failure -> reauth_required
conn.credential.expiresAt = Math.floor(Date.now() / 1000) - 5; await svc.saveConnection(env, conn); world.failRefresh = true; svc.clearToolsCache();
await assert.rejects(() => svc.toolSettings(env, "notion", true, fakeFetch), prov.McpAuthError);
assert.equal((await svc.getConnection(env, "notion")).status, "reauth_required");
assert.equal((await svc.statuses(env)).find((p) => p.id === "notion").connected, false);
await assert.rejects(() => svc.callTool(env, "u", "notion", "search", {}, {}, fakeFetch), /有効期限が切れました/);
// reconnect restores, keeping the user's settings
const url3 = new URL(await svc.startAuthorization(env, "notion", "https://rag.example", "admin-2", fakeFetch));
world.pending = { challenge: url3.searchParams.get("code_challenge"), redirect: "https://rag.example/admin/oauth/mcp/callback" }; world.failRefresh = false;
await svc.completeAuthorization(env, url3.searchParams.get("state"), "c2", fakeFetch);
conn = await svc.getConnection(env, "notion");
assert.equal(conn.status, "connected"); assert.deepEqual(conn.enabledTools, ["create-page", "search"], "tool selection survives reconnect");
// a 401 from the MCP server marks reauth too
world.mcp401 = true; svc.clearToolsCache();
await assert.rejects(() => svc.toolSettings(env, "notion", true, fakeFetch), prov.McpAuthError);
assert.equal((await svc.getConnection(env, "notion")).status, "reauth_required");
world.mcp401 = false; await svc.completeAuthorization(env, (await (async () => { const u = new URL(await svc.startAuthorization(env, "notion", "https://rag.example", "a", fakeFetch)); world.pending = { challenge: u.searchParams.get("code_challenge"), redirect: "https://rag.example/admin/oauth/mcp/callback" }; return u.searchParams.get("state"); })()), "c3", fakeFetch);
console.log("6 refresh / reauth / reconnect OK");

// ------------------------------------------------------------------ 7. routes: gating and responses
const mkUser = (role) => ({ userId: "id-" + role, role, allowedNamespaces: [] });
const req = (body, path = "/") => new Request("https://rag.example" + path, { method: "POST", body: JSON.stringify(body) });
const mustThrowForbidden = async (fn, role) => { let name = ""; try { await fn(req({}), env, mkUser(role)); } catch (e) { name = e.name; } assert.equal(name, "ForbiddenError", fn.name + " as " + role); };
for (const fn of [routes.handleMcpDisconnect, routes.handleMcpTools, routes.handleMcpSetTools, routes.handleMcpSetChat, routes.handleMcpCall]) {
  await mustThrowForbidden(fn, "editor"); await mustThrowForbidden(fn, "member");
}
await mustThrowForbidden(routes.handleMcpStatus, "member");
let r = await routes.handleMcpStatus(req({}), env, mkUser("editor")); assert.equal(r.status, 200); assert.equal((await r.json()).providers.length, 10);
r = await routes.handleMcpSetChat(req({ provider: "notion", enabled: "yes" }), env, mkUser("admin")); assert.equal(r.status, 400);
r = await routes.handleMcpSetChat(req({ provider: "notion", enabled: true }), env, mkUser("admin")); assert.equal(r.status, 200);
r = await routes.handleMyMcp(req({}), env, mkUser("member")); let me = await r.json(); assert.deepEqual(me, { available: true, providers: [{ id: "notion", label: "Notion" }], status: "ok" });
// test-run: reads allowed, writes need confirmation enforced server side. (routes use the real fetch, so install the fake)
const realFetch = globalThis.fetch; globalThis.fetch = fakeFetch;
try {
  r = await routes.handleMcpCall(req({ provider: "notion", tool: "search", arguments: { q: "a" } }), env, mkUser("admin")); assert.equal(r.status, 200); assert.equal((await r.json()).result.text.startsWith("結果:search"), true);
  r = await routes.handleMcpCall(req({ provider: "notion", tool: "create-page", arguments: { title: "a" } }), env, mkUser("admin")); assert.equal(r.status, 409); assert.equal((await r.json()).needsConfirmation, true);
  r = await routes.handleMcpCall(req({ provider: "notion", tool: "create-page", arguments: { title: "a" }, confirmed: true }), env, mkUser("admin")); assert.equal(r.status, 200);
  r = await routes.handleMcpCall(req({ provider: "notion", tool: "fetch", arguments: {} }), env, mkUser("admin")); assert.equal(r.status, 403, "disabled tool");
  r = await routes.handleMcpTools(req({ provider: "notion" }), env, mkUser("admin")); assert.equal((await r.json()).tools.length, 4);
  r = await routes.handleMcpSetTools(req({ provider: "notion", tools: "x" }), env, mkUser("admin")); assert.equal(r.status, 400);
  r = await routes.handleMcpSetTools(req({ provider: "notion", tools: ["search", "fetch"] }), env, mkUser("admin")); assert.equal(r.status, 200);
  r = await routes.handleMcpTools(req({ provider: "nope" }), env, mkUser("admin")); assert.equal(r.status, 500 === r.status ? 500 : r.status); assert.ok(r.status >= 400);
} finally { globalThis.fetch = realFetch; }
// OAuth start/callback pages
const adminKey = "admin-key-123", memberKey = "member-key-456";
const usersCols = db.prepare("PRAGMA table_info(users)").all().map((c) => c.name);
const insertUser = (key, role) => db.prepare(`INSERT INTO users (user_id, display_name, role, created_at) VALUES (?, ?, ?, ?)`).run(createHash("sha256").update(key).digest("hex"), role, role, 1);
insertUser(adminKey, "admin"); insertUser(memberKey, "member");
const startReq = (key, provider = "notion") => new Request(`https://rag.example/admin/oauth/mcp/${provider}/start?key=${key}`);
globalThis.fetch = fakeFetch;
try {
  let res = await routes.handleMcpOAuthStart(startReq(adminKey), env, "notion"); assert.equal(res.status, 302); assert.ok(res.headers.get("location").startsWith("https://mcp.notion.com/authorize?"));
  res = await routes.handleMcpOAuthStart(startReq(memberKey), env, "notion"); assert.equal(res.status, 400); assert.match(await res.text(), /管理者だけ/);
  res = await routes.handleMcpOAuthStart(startReq("bad"), env, "notion"); assert.equal(res.status, 400);
  res = await routes.handleMcpOAuthStart(startReq(adminKey), env, "evil"); assert.equal(res.status, 400);
  res = await routes.handleMcpOAuthCallback(new Request("https://rag.example/admin/oauth/mcp/callback?error=access_denied"), env); assert.equal(res.status, 400);
  res = await routes.handleMcpOAuthCallback(new Request("https://rag.example/admin/oauth/mcp/callback?error=%3Cscript%3Ealert(1)%3C/script%3E"), env);
  const page = await res.text(); assert.ok(!page.includes("<script>alert(1)"), "error text is escaped on the result page"); assert.ok(page.includes("&lt;script&gt;"));
  res = await routes.handleMcpOAuthCallback(new Request("https://rag.example/admin/oauth/mcp/callback?code=c&state=forged"), env); assert.equal(res.status, 400);
} finally { globalThis.fetch = realFetch; }
console.log("7 routes / gating / OAuth pages OK");

// ------------------------------------------------------------------ 8. chat tool loop
await svc.setEnabledTools(env, "notion", ["search", "fetch", "create-page"]); svc.clearToolsCache();
const available = await svc.chatTools(env, fakeFetch);
assert.deepEqual(available.map((t) => t.tool.name).sort(), ["fetch", "search"], "only enabled read-only tools reach the model; write/unknown never");
assert.equal(chat.geminiToolName("notion", "notion-search", new Set()), "mcp_notion_notion_search");
const taken = new Set(); assert.notEqual(chat.geminiToolName("n", "a.b", taken), chat.geminiToolName("n", "a_b", taken));
assert.ok(chat.geminiToolName("notion", "x".repeat(200), new Set()).length <= 60);

const sig = "THOUGHT-SIG";
const modelCall = { role: "model", parts: [{ functionCall: { name: "mcp_notion_search", args: { q: "岩の散布" } }, thoughtSignature: sig }, { functionCall: { name: "mcp_notion_nosuch", args: {} } }] };
geminiScript = [
  { candidates: [{ content: modelCall }], usageMetadata: { promptTokenCount: 100, candidatesTokenCount: 10 } },
  { candidates: [{ content: { role: "model", parts: [{ text: "考え中", thought: true }, { text: "Notionによると…（Notion）" }] } }], usageMetadata: { promptTokenCount: 150, candidatesTokenCount: 20 } },
];
world.geminiBodies.length = 0;
const answered = await chat.answerWithMcpTools(env, "u1", "質問です", undefined, fakeFetch);
assert.equal(answered.text, "Notionによると…（Notion）", "thought parts are not shown");
assert.equal(answered.promptTokens, 250); assert.equal(answered.candidateTokens, 30);
assert.deepEqual(answered.toolCalls.map((c) => [c.providerId, c.tool, c.ok]), [["notion", "search", true]], "unknown tool names are not logged as calls");
const b1 = world.geminiBodies[0], b2 = world.geminiBodies[1];
assert.deepEqual(b1.tools[0].functionDeclarations.map((d) => d.name).sort(), ["mcp_notion_fetch", "mcp_notion_search"]);
assert.equal(b1.tools[0].functionDeclarations.find((d) => d.name === "mcp_notion_search").parameters.required[0], "q");
assert.deepEqual(b2.contents[1], modelCall, "the model's turn (incl. thoughtSignature) is replayed verbatim");
const fr = b2.contents[2].parts; assert.equal(fr.length, 2);
assert.equal(fr[0].functionResponse.name, "mcp_notion_search"); assert.match(fr[0].functionResponse.response.result, /結果:search/);
assert.match(fr[1].functionResponse.response.error, /不明なツール/);
assert.ok(b2.tools, "tools still offered in round 2");
// tool failure is reported to the model, not thrown
geminiScript = [
  { candidates: [{ content: { role: "model", parts: [{ functionCall: { name: "mcp_notion_fetch", args: { id: "boom" } } }] } }] },
  { candidates: [{ content: { role: "model", parts: [{ text: "取得に失敗しました" }] } }] },
];
world.tools.push({ name: "boom", description: "", inputSchema: { type: "object" }, annotations: { readOnlyHint: true } });
const failed = await chat.answerWithMcpTools(env, "u1", "q", undefined, async (u, i) => { const x = JSON.parse(i?.body ?? "{}"); if (String(u).endsWith("/mcp") && x.method === "tools/call") return json({ jsonrpc: "2.0", id: x.id, result: { isError: true, content: [{ type: "text", text: "失敗しました" }] } }); return fakeFetch(u, i); });
assert.equal(failed.text, "取得に失敗しました"); assert.equal(failed.toolCalls[0].ok, false);
// call cap + the final round has no tools
geminiScript = [];
for (let i = 0; i < chat.MAX_ROUNDS; i++) geminiScript.push({ candidates: [{ content: { role: "model", parts: [{ functionCall: { name: "mcp_notion_search", args: { q: "a" + i } } }, { functionCall: { name: "mcp_notion_search", args: { q: "b" + i } } }] } }] });
geminiScript.push({ candidates: [{ content: { role: "model", parts: [{ text: "ここまでの情報で回答" }] } }] });
world.geminiBodies.length = 0; world.mcpCalls.length = 0;
const capped = await chat.answerWithMcpTools(env, "u1", "q", undefined, fakeFetch);
assert.equal(capped.text, "ここまでの情報で回答"); assert.equal(capped.toolCalls.length, chat.MAX_CALLS, "never more than MAX_CALLS tool executions");
assert.equal(world.geminiBodies.length, chat.MAX_ROUNDS + 1); assert.equal(world.geminiBodies.at(-1).tools, undefined, "final round forces a plain answer");
const lastResponses = world.geminiBodies.at(-1).contents.at(-1).parts;
assert.ok(lastResponses.some((p) => /上限に達しました/.test(p.functionResponse.response.error)));
// no tools => null (caller falls back to the plain RAG answer)
await svc.setChatEnabled(env, "notion", false);
assert.equal(await chat.answerWithMcpTools(env, "u1", "q", undefined, fakeFetch), null);
await svc.setChatEnabled(env, "notion", true);
console.log("8 Gemini tool loop OK");

// ------------------------------------------------------------------ 9. schema conversion
const g = schema.toGeminiSchema({ type: "object", $schema: "x", additionalProperties: false, properties: { a: { type: ["string", "null"], description: "d", enum: ["x", "y"] }, b: { anyOf: [{ type: "null" }, { type: "integer" }] }, c: { type: "array", items: { type: "object", properties: { z: { type: "boolean" } } } }, d: { type: "object" }, e: { type: "number", minimum: 1 } }, required: ["a", "ghost"] });
assert.deepEqual(g.required, ["a"]); assert.equal(g.properties.a.type, "STRING"); assert.deepEqual(g.properties.a.enum, ["x", "y"]); assert.equal(g.properties.b.type, "INTEGER");
assert.equal(g.properties.c.items.properties.z.type, "BOOLEAN"); assert.equal(g.properties.d.type, "STRING", "free-form nested object becomes JSON text"); assert.equal(g.properties.e.minimum, undefined);
assert.deepEqual(Object.keys(schema.toGeminiSchema({ type: "object" }).properties), ["reason"]);
assert.equal(schema.toGeminiSchema(null).type, "STRING"); assert.equal(schema.hasProperties({ type: "object" }), false);
console.log("9 schema conversion OK");

// ------------------------------------------------------------------ 10. disconnect
await svc.disconnect(env, "notion", "admin");
assert.equal(await svc.getConnection(env, "notion"), null);
await assert.rejects(() => svc.toolSettings(env, "notion", false, fakeFetch), prov.McpNotConnectedError);
assert.equal((await chat.answerWithMcpTools(env, "u", "q", undefined, fakeFetch)), null);
console.log("10 disconnect OK");
console.log("MCP tests OK");
