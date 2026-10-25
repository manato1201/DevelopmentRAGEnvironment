// 「どのユーザーで入っているか」（2026-10-25）: /me/namespaces が、キーの名前・役割・IDの先頭を返す。キー自体は返さない。
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

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
const HASH = "ab12cd34ef56" + "0".repeat(52);
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES (?, '田中の鍵', 'member', 1), ('nn', NULL, 'guest', 1)").run(HASH);
const { loadAuthedUser } = await import("../src/auth");
const { handleMyNamespaces } = await import("../src/retrieve");

const user = await loadAuthedUser({ DB: D1 }, HASH);
assert.equal(user.displayName, "田中の鍵");
const body = await (await handleMyNamespaces(new Request("https://x/me/namespaces", { method: "POST" }), { DB: D1 }, user)).json();
assert.equal(body.displayName, "田中の鍵");
assert.equal(body.role, "member");
assert.equal(body.userIdShort, "ab12cd");
assert.ok(!JSON.stringify(body).includes(HASH), "the full key hash is never returned");

// 名前の無いキーは、空文字（画面側で「（名前なし）」と出す）
const anon = await loadAuthedUser({ DB: D1 }, "nn");
const anonBody = await (await handleMyNamespaces(new Request("https://x/me/namespaces", { method: "POST" }), { DB: D1 }, anon)).json();
assert.equal(anonBody.displayName, "");
console.log("whoami tests passed");
