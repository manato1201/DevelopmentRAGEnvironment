// POST /admin/bootstrap(認証なしで通る初回セットアップ専用の入口)が、管理者が1人でもいれば閉じること。
// 2026-11-10: 確認と INSERT の間の競合(同時に2回呼ばれて管理者が2人できる)も、INSERT 自体を条件付きにして塞いだ。
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));

// seed=true: 移行直後の状態(0001_init.sql が管理者 dev-test-user-hash を1件入れている)。
// seed=false: その初期管理者を消した「管理者が1人もいない」状態。
function makeEnv({ seed = false } = {}) {
  const db = new DatabaseSync(":memory:");
  for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) { try { db.exec(readFileSync(MIG + f, "utf8")); } catch { /* fts5 など */ } }
  const D1 = {
    prepare(sql) {
      return {
        a: [], bind(...x) { this.a = x; return this; },
        async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: Number(r.changes) } }; },
        async first() { return db.prepare(sql).get(...this.a) ?? null; },
        async all() { return { results: db.prepare(sql).all(...this.a) }; },
      };
    },
  };
  if (!seed) {
    // 初期管理者に紐づく行(予算・namespace・許可)ごと、外部キーを一時的に切って消す
    db.exec("PRAGMA foreign_keys = OFF");
    db.exec("DELETE FROM token_budgets WHERE user_id = 'dev-test-user-hash'");
    db.exec("DELETE FROM key_namespace_grants WHERE user_id = 'dev-test-user-hash'");
    db.exec("DELETE FROM namespaces WHERE owner_user_id = 'dev-test-user-hash'");
    db.exec("DELETE FROM users WHERE user_id = 'dev-test-user-hash'");
    db.exec("PRAGMA foreign_keys = ON");
  }
  return { db, env: { DB: D1 } };
}

const { handleBootstrapAdmin } = await import("../src/keyAdmin");
const call = (env, body = {}) =>
  handleBootstrapAdmin(new Request("https://x/admin/bootstrap", { method: "POST", body: JSON.stringify(body) }), env);
const adminCount = (db) => db.prepare("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'").get().c;

// 1) 管理者がいなければ最初の1つが作れ、そのキーは1回だけ返る
{
  const { db, env } = makeEnv();
  const res = await call(env, { displayName: "初代" });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.role, "admin");
  assert.ok(body.apiKey && body.apiKey.length >= 40);
  assert.equal(adminCount(db), 1);
}

// 2) 作成後は閉じる: 2回目は 403 で、管理者は増えない
{
  const { db, env } = makeEnv();
  assert.equal((await call(env)).status, 200);
  const again = await call(env, { displayName: "乗っ取り" });
  assert.equal(again.status, 403);
  assert.equal(adminCount(db), 1);
}

// 3) 管理者が(別経路で)既にいれば最初から 403。有効期限が切れた管理者でも閉じたまま
{
  const { db, env } = makeEnv();
  db.prepare("INSERT INTO users (user_id, display_name, role, created_at, expires_at) VALUES ('old', 'x', 'admin', 1, 2)").run();
  assert.equal((await call(env)).status, 403);
  assert.equal(adminCount(db), 1);
}

// 4) 管理者でないユーザーしかいない場合は、設計どおり最初の管理者を作れる
{
  const { db, env } = makeEnv();
  db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('m', 'member', 'member', 1)").run();
  assert.equal((await call(env)).status, 200);
  assert.equal(adminCount(db), 1);
}

// 5) 同時に2回呼んでも、管理者は1人だけ(200 が1つ、403 が1つ)
{
  const { db, env } = makeEnv();
  const [a, b] = await Promise.all([call(env, { displayName: "A" }), call(env, { displayName: "B" })]);
  assert.deepEqual([a.status, b.status].sort(), [200, 403]);
  assert.equal(adminCount(db), 1);
  // 負けた側の個人namespaceや予算の行が残っていない
  assert.equal(db.prepare("SELECT COUNT(*) AS c FROM token_budgets").get().c, 1);
}

// 6) 移行直後の DB(初期管理者が入っている)では、最初から 403。このドアは実運用では開かない
{
  const { db, env } = makeEnv({ seed: true });
  assert.equal(adminCount(db), 1);
  assert.equal((await call(env, { displayName: "乗っ取り" })).status, 403);
  assert.equal(adminCount(db), 1);
}

console.log("bootstrap tests passed");
