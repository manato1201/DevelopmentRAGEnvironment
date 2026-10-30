// トークン予算（src/budget.ts）のテスト。予約・清算・定期リセットの追いつき（node:sqlite の偽 D1）。
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { reserveBudget, reconcileBudget, getRemaining } from "../src/budget";

const db = new DatabaseSync(":memory:");
db.exec(
  "CREATE TABLE token_budgets (user_id TEXT, budget_type TEXT, limit_tokens INTEGER, used_tokens INTEGER, reset_at INTEGER, reset_interval_hours INTEGER)",
);
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
    };
  },
};
const env = { DB: D1 };
const row = () =>
  db.prepare("SELECT used_tokens, reset_at FROM token_budgets").get();
const seed = (used, resetAt = null, hours = null) => {
  db.exec("DELETE FROM token_budgets");
  db.prepare("INSERT INTO token_budgets VALUES ('u','rag',10000,?,?,?)").run(
    used,
    resetAt,
    hours,
  );
};
const now = () => Math.floor(Date.now() / 1000);

// 予約 → 清算
seed(5000);
assert.equal(await reserveBudget(env, "u", "rag", 4000), true);
assert.equal(row().used_tokens, 9000);
await reconcileBudget(env, "u", "rag", 4000, 1800);
assert.equal(row().used_tokens, 6800);
assert.equal(
  await reserveBudget(env, "u", "rag", 4000),
  false,
  "6800+4000 > 10000",
);
assert.equal(row().used_tokens, 6800);

// 競合: 残り1000に800を2件
seed(9000);
assert.equal(await reserveBudget(env, "u", "rag", 800), true);
assert.equal(await reserveBudget(env, "u", "rag", 800), false);
assert.equal(row().used_tokens, 9800);

// 予算の行が無ければ無制限
db.exec("DELETE FROM token_budgets");
assert.equal(await reserveBudget(env, "u", "rag", 999999), true);
assert.equal(await getRemaining(env, "u", "rag"), null);

// 定期リセット: 期限を1周期だけ過ぎている → 0に戻り、次のリセットは未来
seed(9500, now() - 3600, 24);
assert.equal(await reserveBudget(env, "u", "rag", 3000), true);
assert.equal(row().used_tokens, 3000);
assert.ok(row().reset_at > now(), "next reset is in the future");

// 定期リセット: 何周期も遅れていても、リセットは1回だけ（使用量が積み上がる）
seed(9500, now() - 72 * 3600, 24);
assert.equal(await reserveBudget(env, "u", "rag", 3000), true);
assert.equal(row().used_tokens, 3000);
assert.ok(row().reset_at > now(), "reset_at catches up in one step");
assert.equal(await reserveBudget(env, "u", "rag", 3000), true);
assert.equal(
  row().used_tokens,
  6000,
  "second call accumulates, no repeated reset",
);
assert.equal(await reserveBudget(env, "u", "rag", 3000), true);
assert.equal(
  await reserveBudget(env, "u", "rag", 3000),
  false,
  "9000+3000 > 10000: limit enforced after a long idle",
);
assert.equal(row().used_tokens, 9000);
// 周期の境界は元のリズムを保つ（72時間遅れ → 次は +96h の位置）
const before = now() - 72 * 3600;
seed(0, before, 24);
await getRemaining(env, "u", "rag");
assert.equal(row().reset_at, before + 4 * 24 * 3600);

console.log("budget ok");
