// Slackのチャット（メンション・DM）で答える（2026-10-25、src/slackEvents.ts）のテスト。
// 署名・再送・ボット自身の発言の無視・許可ワークスペース・連携・DMだけMCPを使う・履歴・D1の一時エラーのやり直し。
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
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('u1','taro','member',1),('g1','guest','guest',1)").run();
db.prepare("INSERT INTO slack_bindings (team_id, slack_user_id, user_id, created_at) VALUES ('T1','UALICE','u1',1),('T1','UGUEST','g1',1)").run();

const SECRET = "signing-secret";
const env = { DB: D1, SLACK_SIGNING_SECRET: SECRET, SLACK_TEAM_IDS: "T1", SLACK_BOT_TOKEN: "xoxb-SECRET-TOKEN" };
const ev = await import("../src/slackEvents");

async function sign(body, ts = Math.floor(Date.now() / 1000)) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`v0:${ts}:${body}`));
  return { "x-slack-request-timestamp": String(ts), "x-slack-signature": "v0=" + [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("") };
}
async function post(payload, headers = {}, e = env, deps = {}) {
  const raw = JSON.stringify(payload);
  const req = new Request("https://x/slack/events", { method: "POST", headers: { ...(await sign(raw)), ...headers }, body: raw });
  return ev.handleSlackEvents(req, e, undefined, deps);
}

// ---- stripMentions / classifyEvent / buildSlackHistory
assert.equal(ev.stripMentions("<@U0BOT> こんにちは  <@U1|taro> 世界"), "こんにちは 世界");
const base = { type: "event_callback", team_id: "T1", authorizations: [{ user_id: "UBOT" }] };
const dm = { ...base, event: { type: "message", channel_type: "im", channel: "D1", user: "UALICE", text: "質問", ts: "1.1" } };
assert.deepEqual({ ...ev.classifyEvent(dm) }, { channel: "D1", ts: "1.1", threadTs: undefined, replyThreadTs: undefined, slackUser: "UALICE", teamId: "T1", text: "質問", isDm: true });
const mention = { ...base, event: { type: "app_mention", channel: "C1", user: "UALICE", text: "<@UBOT> 質問", ts: "2.2" } };
const m = ev.classifyEvent(mention);
assert.equal(m.isDm, false);
assert.equal(m.replyThreadTs, "2.2", "a channel mention is answered in a thread started at the question");
assert.equal(m.text, "質問");
assert.equal(ev.classifyEvent({ ...mention, event: { ...mention.event, thread_ts: "1.0" } }).replyThreadTs, "1.0", "or in the thread it was asked in");
// 対象外
assert.equal(ev.classifyEvent({ ...dm, event: { ...dm.event, bot_id: "B1" } }), null, "other bots");
assert.equal(ev.classifyEvent({ ...dm, event: { ...dm.event, user: "UBOT" } }), null, "the bot itself");
assert.equal(ev.classifyEvent({ ...dm, event: { ...dm.event, subtype: "message_changed" } }), null, "edits");
assert.equal(ev.classifyEvent({ ...dm, event: { ...dm.event, channel_type: "channel" } }), null, "channel messages that are not mentions");
assert.equal(ev.classifyEvent({ ...dm, type: "url_verification" }), null);

const hist = ev.buildSlackHistory([
  { type: "message", user: "UALICE", text: "<@UBOT> 最初の質問", ts: "1" },
  { type: "message", bot_id: "B1", text: "最初の回答", ts: "2" },
  { type: "message", bot_id: "B1", text: "調べています…", ts: "3" },
  { type: "message", user: "UALICE", text: "いまの質問", ts: "4" },
], "4", "UBOT");
assert.deepEqual(hist, [{ role: "user", content: "最初の質問" }, { role: "assistant", content: "最初の回答" }], "current question and placeholder are left out");
assert.equal(ev.buildSlackHistory(Array.from({ length: 20 }, (_, i) => ({ type: "message", user: "U", text: "m" + i, ts: String(i) })), "x").length, 6, "only the latest few");

// ---- 署名・再送・url_verification
const noSecret = await post(dm, {}, { ...env, SLACK_SIGNING_SECRET: undefined });
assert.equal(noSecret.status, 503);
const raw = JSON.stringify(dm);
assert.equal((await ev.handleSlackEvents(new Request("https://x/slack/events", { method: "POST", headers: { "x-slack-request-timestamp": "1", "x-slack-signature": "v0=bad" }, body: raw }), env)).status, 401);
const challenge = await post({ type: "url_verification", challenge: "abc123" });
assert.equal(challenge.status, 200);
assert.deepEqual(await challenge.json(), { challenge: "abc123" });

// ---- Slack API と、答える関数の偽物
const calls = [];
const slack = async (url, init) => {
  const method = String(url).split("/api/")[1];
  const body = JSON.parse(init.body);
  calls.push({ method, body, auth: init.headers.authorization });
  if (method === "chat.postMessage") return new Response(JSON.stringify({ ok: true, ts: "9.9" }));
  if (method === "chat.update") return new Response(JSON.stringify({ ok: true }));
  if (method === "conversations.history") return new Response(JSON.stringify({ ok: true, messages: [
    { type: "message", user: "UALICE", text: "いまの質問", ts: "1.1" }, // 新しい順
    { type: "message", bot_id: "B1", text: "前の回答", ts: "0.9" },
    { type: "message", user: "UALICE", text: "前の質問", ts: "0.8" },
  ] }));
  return new Response(JSON.stringify({ ok: false, error: "missing_scope" }));
};
const answers = [];
const answer = async (_env, user, body) => {
  answers.push({ user, body });
  return { ok: true, answer: "答えです", sources: [{ file: "a.md", namespace: "shared:x", cited: true }], toolCalls: body.useMcp ? [{ providerLabel: "GitHub", ok: true }] : [], pendingActions: [] };
};
const deps = { fetchImpl: slack, answer };
const reset = () => { calls.length = 0; answers.length = 0; };

// DM: 受け付け（200）→ 「調べています…」→ 答えで書き換え。MCPを使う。履歴を渡す
reset();
let res = await post(dm, {}, env, deps);
assert.equal(res.status, 200);
assert.equal(calls[0].method, "chat.postMessage");
assert.equal(calls[0].body.text, "調べています…");
assert.equal(calls[0].body.thread_ts, undefined, "a DM is answered flat");
assert.equal(calls[0].auth, "Bearer xoxb-SECRET-TOKEN");
assert.equal(answers[0].user.userId, "u1", "runs with the linked user's permissions");
assert.equal(answers[0].body.useMcp, true, "external services are used in a DM");
assert.deepEqual(answers[0].body.history, [{ role: "user", content: "前の質問" }, { role: "assistant", content: "前の回答" }]);
const upd = calls.find((c) => c.method === "chat.update");
assert.equal(upd.body.ts, "9.9");
assert.match(upd.body.text, /答えです/);
assert.match(upd.body.text, /使った外部サービス: GitHub/);

// チャンネルのメンション: スレッドに返信。MCPは使わない（その場の全員に見えるため）
reset();
await post(mention, {}, env, deps);
assert.equal(calls[0].body.thread_ts, "2.2");
assert.equal(answers[0].body.useMcp, false, "never in a channel");
assert.deepEqual(answers[0].body.history, [], "a new thread has no history");
assert.ok(!calls.some((c) => c.method === "conversations.history" || c.method === "conversations.replies"));

// 書き込みの確認が必要な操作は、Slackでは実行せず、案内を出す
reset();
await post(dm, {}, env, { fetchImpl: slack, answer: async () => ({ ok: true, answer: "x", sources: [], pendingActions: [{ approvalId: "a" }] }) });
assert.match(calls.find((c) => c.method === "chat.update").body.text, /ウェブ画面のチャットで確認/);

// 再送・ボット自身・トークン未設定は、何もしない
reset();
await post(dm, { "x-slack-retry-num": "1" }, env, deps);
await post({ ...dm, event: { ...dm.event, bot_id: "B1" } }, {}, env, deps);
await post(dm, {}, { ...env, SLACK_BOT_TOKEN: undefined }, deps);
assert.equal(calls.length, 0);
assert.equal(answers.length, 0);

// 許可されていないワークスペース・未連携・ゲスト
reset();
await post({ ...dm, team_id: "T9", event: { ...dm.event } }, {}, env, deps);
assert.match(calls[0].body.text, /許可されていません/);
assert.equal(answers.length, 0);
reset();
await post({ ...dm, event: { ...dm.event, user: "UNEW" } }, {}, env, deps);
assert.match(calls[0].body.text, /\/rag link/);
reset();
await post({ ...dm, event: { ...dm.event, user: "UGUEST" } }, {}, env, deps);
assert.match(calls[0].body.text, /質問できません/);
assert.equal(answers.length, 0);

// 空の質問（メンションだけ）
reset();
await post({ ...mention, event: { ...mention.event, text: "<@UBOT>" } }, {}, env, deps);
assert.match(calls[0].body.text, /質問を書いてください/);
assert.equal(answers.length, 0);

// 失敗は「質問できませんでした」で、書き換える。トークンは出さない
reset();
await post(dm, {}, env, { fetchImpl: slack, answer: async () => ({ ok: false, error: "予算を超えました" }) });
const failed = calls.find((c) => c.method === "chat.update");
assert.match(failed.body.text, /質問できませんでした: 予算を超えました/);
assert.ok(!JSON.stringify(calls.map((c) => c.body)).includes("xoxb"));

// 書き換えに失敗したら、新しい発言で送る
reset();
const noUpdate = async (url, init) => (String(url).endsWith("chat.update") ? (calls.push({ method: "chat.update", body: JSON.parse(init.body) }), new Response(JSON.stringify({ ok: false }))) : slack(url, init));
await post(dm, {}, env, { fetchImpl: noUpdate, answer });
assert.equal(calls.filter((c) => c.method === "chat.postMessage").length, 2, "placeholder + fallback post");

// D1の一時エラーは、1回だけやり直す
const sb = await import("../src/slackBot");
let n = 0;
const flaky = async () => (++n === 1 ? { ok: false, error: "D1_ERROR: Internal error in D1 DB storage caused object to be reset" } : { ok: true, answer: "ok", sources: [] });
const retried = await sb.answerWithRetry(env, { userId: "u1" }, { query: "q" }, flaky);
assert.equal(retried.ok, true);
assert.equal(n, 2);
n = 0;
const other = async () => (++n, { ok: false, error: "予算を超えました" });
assert.equal((await sb.answerWithRetry(env, { userId: "u1" }, { query: "q" }, other)).ok, false);
assert.equal(n, 1, "other errors are not retried");

console.log("slack_events tests passed");

// ---- Slackの表記への変換（太字・見出し・箇条書き・リンク・エスケープ。コードの中はそのまま）
const sbx = await import("../src/slackBot");
assert.equal(sbx.toSlackMrkdwn("**概要**: TOP は…"), "*概要*: TOP は…");
assert.equal(sbx.toSlackMrkdwn("* **主な機能**: x\n- 項目\n  - 入れ子"), "• *主な機能*: x\n• 項目\n  • 入れ子");
assert.equal(sbx.toSlackMrkdwn("## 見出し\n本文"), "*見出し*\n本文");
assert.equal(sbx.toSlackMrkdwn("[資料](https://example.com/a?x=1&y=2)"), "<https://example.com/a?x=1&amp;y=2|資料>");
assert.equal(sbx.toSlackMrkdwn("<!channel> と <@U123> と a & b"), "&lt;!channel&gt; と &lt;@U123&gt; と a &amp; b", "no accidental mentions");
assert.equal(sbx.toSlackMrkdwn("`**x** <a>` と ```\n- a\n**b**\n```"), "`**x** <a>` と ```\n- a\n**b**\n```", "code is untouched");
assert.equal(sbx.toSlackMrkdwn("*すでにSlack形式*"), "*すでにSlack形式*");
const formatted = sbx.formatSlackAnswer("**太字**です", [{ file: "<!here>.md", namespace: "shared:x", cited: true }]);
assert.match(formatted, /^\*太字\*です/);
assert.ok(formatted.includes("&lt;!here&gt;.md") && !formatted.includes("<!here>"));
console.log("slack mrkdwn tests passed");
