// 管理画面の「使用量を0に戻す」と、一覧が返す「次に戻る日時」の検査(2026-11-17)。
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
      async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes } }; },
      async first() { return db.prepare(sql).get(...this.a) ?? null; },
      async all() { return { results: db.prepare(sql).all(...this.a) }; },
    };
  },
};
const env = { DB: D1 };
const admin = { userId: "adm", role: "admin", displayName: "admin" };
const member = { userId: "m1", role: "member", displayName: "m" };
const { handleChargeKey, handleSetKeyCapacity, handleListKeys } = await import("../src/keyAdmin");
const post = (body) => new Request("https://x/admin", { method: "POST", body: JSON.stringify(body) });

db.prepare("INSERT OR IGNORE INTO users (user_id, display_name, role, created_at) VALUES ('u1','Alice','member',1)").run();
db.prepare("DELETE FROM token_budgets WHERE user_id = 'u1'").run();
db.prepare("INSERT INTO token_budgets (user_id, budget_type, limit_tokens, used_tokens) VALUES ('u1','claude',1000,700),('u1','rag',500,100)").run();

// reset: true で、使った分が 0 に戻る(上限は変わらない。もう一方の予算も触らない)
let res = await handleChargeKey(post({ userId: "u1", budgetType: "claude", reset: true }), env, admin);
assert.equal(res.status, 200);
const claude = db.prepare("SELECT limit_tokens, used_tokens FROM token_budgets WHERE user_id='u1' AND budget_type='claude'").get();
assert.deepEqual({ ...claude }, { limit_tokens: 1000, used_tokens: 0 });
assert.equal(db.prepare("SELECT used_tokens FROM token_budgets WHERE user_id='u1' AND budget_type='rag'").get().used_tokens, 100);

// 従来の amount(補充)は、そのまま動く
res = await handleChargeKey(post({ userId: "u1", budgetType: "rag", amount: 30 }), env, admin);
assert.equal(res.status, 200);
assert.equal(db.prepare("SELECT used_tokens FROM token_budgets WHERE user_id='u1' AND budget_type='rag'").get().used_tokens, 70);

// amount も reset も無ければ 400
res = await handleChargeKey(post({ userId: "u1", budgetType: "rag" }), env, admin);
assert.equal(res.status, 400);

// 管理者以外は拒否される
await assert.rejects(() => handleChargeKey(post({ userId: "u1", budgetType: "claude", reset: true }), env, member));

// 自動リセットの周期を設定すると、一覧に「次に戻る日時」と周期が出る。0 にすると自動では戻らない
res = await handleSetKeyCapacity(post({ userId: "u1", budgetType: "claude", limitTokens: 1000, resetIntervalHours: 24 }), env, admin);
assert.equal(res.status, 200);
let list = await (await handleListKeys(post({}), env, admin)).json();
let row = (list.keys || list).find((k) => k.user_id === "u1");
assert.equal(row.claude_reset_hours, 24);
assert.ok(row.claude_reset_at > Date.now() / 1000, "次に戻る日時は未来");
assert.equal(row.rag_reset_hours, null);

res = await handleSetKeyCapacity(post({ userId: "u1", budgetType: "claude", limitTokens: 1000, resetIntervalHours: 0 }), env, admin);
list = await (await handleListKeys(post({}), env, admin)).json();
row = (list.keys || list).find((k) => k.user_id === "u1");
assert.equal(row.claude_reset_hours, 0);
console.log("budget reset ok");
