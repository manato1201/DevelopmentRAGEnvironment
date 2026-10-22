// チャットからの「書き込み」ツール: 本人専用・明示的に許可・実行前の確認（1回だけ・5分・本人のみ）と、$ref展開のテスト。
// 実SQLite（node:sqlite）と、偽のMCPサーバー・偽のGeminiで検証する。
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
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
const chat = await import("../src/mcp/chat");
const routes = await import("../src/mcp/routes");
const approval = await import("../src/mcp/approval");
const schema = await import("../src/mcp/schema");

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });
const world = { toolCalls: [], geminiBodies: [] };
let geminiScript = [];
const TOOLS = [
  { name: "search", description: "検索", inputSchema: { type: "object", properties: { q: { type: "string" } } }, annotations: { readOnlyHint: true } },
  { name: "create-page", description: "作成", inputSchema: { type: "object", properties: { title: { type: "string" } } }, annotations: { readOnlyHint: false } },
];
const fakeFetch = async (input, init = {}) => {
  const u = new URL(String(input));
  if (u.host === "mcp.notion.com" && u.pathname === "/mcp") {
    const body = JSON.parse(init.body);
    const reply = (result) => json({ jsonrpc: "2.0", id: body.id, result });
    if (body.method === "initialize") return reply({ protocolVersion: "2025-06-18", capabilities: {}, serverInfo: { name: "fake" } });
    if (body.method === "notifications/initialized") return new Response(null, { status: 202 });
    if (body.method === "tools/list") return reply({ tools: TOOLS });
    if (body.method === "tools/call") {
      world.toolCalls.push({ name: body.params.name, args: body.params.arguments });
      return reply({ content: [{ type: "text", text: `done:${body.params.name}` }] });
    }
  }
  if (u.host === "generativelanguage.googleapis.com") {
    world.geminiBodies.push(JSON.parse(init.body));
    const next = geminiScript.shift();
    assert.ok(next, "unexpected extra Gemini call");
    return json(next);
  }
  throw new Error("unexpected fetch: " + u);
};

const connect = (ownerId, enabledTools) =>
  svc.saveConnection(env, {
    providerId: "notion", ownerId,
    credential: { accessToken: "at", refreshToken: "", expiresAt: null, resourceUrl: "https://mcp.notion.com/mcp", tokenEndpoint: "https://mcp.notion.com/token", client: { client_id: "c" } },
    status: "connected", lastError: "", enabledTools, chatEnabled: true, connectedAt: 1, connectedBy: ownerId || "admin",
  });
const names = (list) => list.map((t) => t.tool.name).sort();

// ------------------------------------------------------------------ 1. what the model may see
await connect("u1", null); svc.clearToolsCache();
assert.deepEqual(names(await svc.chatTools(env, fakeFetch, "u1")), ["search"], "unselected = read-only tools only");
const settings = await svc.toolSettings(env, "notion", true, fakeFetch, "u1");
assert.deepEqual(settings.map((t) => [t.name, t.enabled]), [["search", true], ["create-page", false]], "the picker shows writes unchecked until chosen");
await svc.setEnabledTools(env, "notion", ["search", "create-page"], "u1"); svc.clearToolsCache();
assert.deepEqual(names(await svc.chatTools(env, fakeFetch, "u1")), ["create-page", "search"], "an explicit choice offers the write tool to its owner");
assert.deepEqual(names(await svc.chatTools(env, fakeFetch, "u2")), [], "another user does not get u1's connection");
// 共有の接続では、明示的に選んでも書き込まない
await svc.disconnect(env, "notion", "u1", "u1");
await connect("", ["search", "create-page"]); svc.clearToolsCache();
assert.deepEqual(names(await svc.chatTools(env, fakeFetch, "u1")), ["search"], "a shared connection never offers writes");
await svc.disconnect(env, "notion", "admin", "");
console.log("1 visibility OK");

// ------------------------------------------------------------------ 2. the model asks for a write: nothing runs, a confirmation is stored
await connect("u1", ["search", "create-page"]); svc.clearToolsCache();
geminiScript = [
  { candidates: [{ content: { role: "model", parts: [{ functionCall: { name: "mcp_notion_create_page", args: { title: "企画書" } } }] } }] },
  { candidates: [{ content: { role: "model", parts: [{ text: "確認画面で「実行」を押してください" }] } }] },
];
world.toolCalls.length = 0; world.geminiBodies.length = 0;
const answered = await chat.answerWithMcpTools(env, "u1", "企画書ページを作って", undefined, fakeFetch);
assert.deepEqual(world.toolCalls, [], "the write tool was NOT executed");
assert.equal(answered.pendingActions.length, 1);
const pending = answered.pendingActions[0];
assert.deepEqual([pending.providerId, pending.tool, pending.arguments], ["notion", "create-page", { title: "企画書" }]);
assert.equal(answered.toolCalls.length, 0, "a pending write is not logged as a call");
const declared = world.geminiBodies[0].tools[0].functionDeclarations.find((d) => d.name === "mcp_notion_create_page");
assert.match(declared.description, /確認/, "the model is told that a confirmation comes first");
assert.match(JSON.stringify(world.geminiBodies[1].contents.at(-1)), /pending_user_confirmation/);
const row = db.prepare("SELECT * FROM mcp_approvals WHERE id = ?").get(pending.approvalId);
assert.equal(row.user_id, "u1"); assert.equal(row.owner_id, "u1"); assert.equal(JSON.parse(row.arguments_json).title, "企画書");
assert.ok(row.expires_at - Math.floor(Date.now() / 1000) <= approval.APPROVAL_TTL_SECONDS);
console.log("2 pending write OK");

// ------------------------------------------------------------------ 3. confirm: only the owner, only once, only what was stored
const mkUser = (userId, role = "member") => ({ userId, role, allowedNamespaces: [] });
const post = (body) => new Request("https://rag.example/mcp/confirm", { method: "POST", body: JSON.stringify(body) });
const realFetch = globalThis.fetch; globalThis.fetch = fakeFetch;
try {
  let r = await routes.handleMcpConfirm(post({ approvalId: pending.approvalId }), env, mkUser("u2"));
  assert.equal(r.status, 409, "someone else cannot confirm it"); assert.deepEqual(world.toolCalls, []);
  assert.ok(db.prepare("SELECT 1 FROM mcp_approvals WHERE id = ?").get(pending.approvalId), "a wrong user's attempt does not use it up");
  // 画面から別の引数を送っても、サーバーに保存した引数が実行される
  r = await routes.handleMcpConfirm(post({ approvalId: pending.approvalId, tool: "evil", arguments: { title: "改ざん" } }), env, mkUser("u1"));
  assert.equal(r.status, 200); const done = await r.json();
  assert.equal(done.result.text, "done:create-page"); assert.equal(done.result.isError, false);
  assert.deepEqual(world.toolCalls, [{ name: "create-page", args: { title: "企画書" } }], "runs the stored call, once");
  r = await routes.handleMcpConfirm(post({ approvalId: pending.approvalId }), env, mkUser("u1"));
  assert.equal(r.status, 409, "single use"); assert.equal(world.toolCalls.length, 1);
  const audits = db.prepare("SELECT action, user_id, status FROM mcp_audit WHERE action = 'create-page'").all();
  assert.deepEqual(audits.map((a) => [a.user_id, a.status]), [["u1", "ok"]]);
  assert.ok(!JSON.stringify(db.prepare("SELECT detail FROM mcp_audit").all()).includes("企画書"), "arguments are never written to the audit log");

  // 期限切れ
  const stale = await approval.createApproval(env, { userId: "u1", ownerId: "u1", providerId: "notion", tool: "create-page", arguments: { title: "古い" } });
  db.prepare("UPDATE mcp_approvals SET expires_at = ? WHERE id = ?").run(Math.floor(Date.now() / 1000) - 1, stale.id);
  r = await routes.handleMcpConfirm(post({ approvalId: stale.id }), env, mkUser("u1"));
  assert.equal(r.status, 409); assert.match((await r.json()).error, /期限/); assert.equal(world.toolCalls.length, 1);
  assert.equal(db.prepare("SELECT 1 FROM mcp_approvals WHERE id = ?").get(stale.id), undefined, "an expired one is removed");

  // 確認のあとで、管理者（本人）がツールを無効にした・接続を共有にした → 実行しない
  const later = await approval.createApproval(env, { userId: "u1", ownerId: "u1", providerId: "notion", tool: "create-page", arguments: { title: "後" } });
  await svc.setEnabledTools(env, "notion", ["search"], "u1"); svc.clearToolsCache();
  r = await routes.handleMcpConfirm(post({ approvalId: later.id }), env, mkUser("u1"));
  assert.equal(r.status, 403); assert.equal(world.toolCalls.length, 1, "disabled after the request: not executed");
  await svc.setEnabledTools(env, "notion", ["search", "create-page"], "u1"); svc.clearToolsCache();

  // guest / 空のID
  await assert.rejects(() => routes.handleMcpConfirm(post({ approvalId: "x" }), env, mkUser("g", "guest")), /ゲスト/);
  r = await routes.handleMcpConfirm(post({}), env, mkUser("u1")); assert.equal(r.status, 400);

  // やめる: 本人のものだけ消える
  const c1 = await approval.createApproval(env, { userId: "u1", ownerId: "u1", providerId: "notion", tool: "create-page", arguments: {} });
  await routes.handleMcpCancel(new Request("https://rag.example/mcp/cancel", { method: "POST", body: JSON.stringify({ approvalId: c1.id }) }), env, mkUser("u2"));
  assert.ok(db.prepare("SELECT 1 FROM mcp_approvals WHERE id = ?").get(c1.id), "another user cannot cancel it");
  await routes.handleMcpCancel(new Request("https://rag.example/mcp/cancel", { method: "POST", body: JSON.stringify({ approvalId: c1.id }) }), env, mkUser("u1"));
  assert.equal(db.prepare("SELECT 1 FROM mcp_approvals WHERE id = ?").get(c1.id), undefined);
} finally { globalThis.fetch = realFetch; }
console.log("3 confirm OK");

// ------------------------------------------------------------------ 4. at most MAX_PENDING per answer; purge
geminiScript = [
  { candidates: [{ content: { role: "model", parts: Array.from({ length: chat.MAX_PENDING + 2 }, (_, i) => ({ functionCall: { name: "mcp_notion_create_page", args: { title: "t" + i } } })) } }] },
  { candidates: [{ content: { role: "model", parts: [{ text: "ok" }] } }] },
];
const many = await chat.answerWithMcpTools(env, "u1", "たくさん作って", undefined, fakeFetch);
assert.equal(many.pendingActions.length, chat.MAX_PENDING);
db.prepare("UPDATE mcp_approvals SET expires_at = 1").run();
await approval.purgeExpiredApprovals(env);
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM mcp_approvals").get().n, 0);
console.log("4 cap / purge OK");

// ------------------------------------------------------------------ 5. $ref expansion
const withRefs = {
  type: "object",
  properties: { origin: { $ref: "#/$defs/Waypoint" }, stops: { type: "array", items: { $ref: "#/$defs/Waypoint" } }, loop: { $ref: "#/$defs/Loop" }, ext: { $ref: "https://example.com/x.json" } },
  required: ["origin"],
  $defs: {
    Waypoint: { type: "object", description: "地点", properties: { text: { type: "string" }, lat: { type: "number" } }, required: ["text"] },
    Loop: { type: "object", properties: { next: { $ref: "#/$defs/Loop" } } },
  },
};
const g = schema.toGeminiSchema(withRefs);
assert.equal(g.properties.origin.type, "OBJECT"); assert.equal(g.properties.origin.properties.text.type, "STRING"); assert.deepEqual(g.properties.origin.required, ["text"]);
assert.equal(g.properties.stops.items.properties.lat.type, "NUMBER");
assert.equal(g.properties.ext.type, "STRING", "an external reference becomes text");
assert.ok(JSON.stringify(g.properties.loop).length < 600, "a circular reference terminates");
assert.equal(g.$defs, undefined);
console.log("5 $ref OK");

console.log("MCP write tests OK");
