// お気に入りの読み込み（/memory/import）と、回答1件の取得（/memory/get）。実SQLiteで検証する。
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) {
  try { db.exec(readFileSync(MIG + f, "utf8")); } catch { /* fts5 などは、この環境に無い */ }
}
const D1 = {
  prepare(sql) {
    return {
      a: [], bind(...x) { this.a = x; return this; },
      async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes, last_row_id: Number(r.lastInsertRowid) } }; },
      async first() { return db.prepare(sql).get(...this.a) ?? null; },
      async all() { return { results: db.prepare(sql).all(...this.a) }; },
    };
  },
};
const env = { DB: D1 };
for (const u of ["u1", "u2", "g"]) db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES (?, ?, ?, ?)").run(u, u, "member", 1);
const mem = await import("../src/memory");
const user = (id, role = "member") => ({ userId: id, role, allowedNamespaces: [] });
const post = (path, body) => new Request("https://rag.example" + path, { method: "POST", body: JSON.stringify(body) });

// ---- import: 形を絞り、本人の履歴として保存し、お気に入りにする
const longAnswer = "あ".repeat(30000);
let r = await mem.handleMemoryImport(post("/memory/import", {
  entries: [
    { query: "Q1", answer: "A1 [1]", sources: [{ file: "a.md", namespace: "shared:houdini22", score: 88, cited: true, evil: "<script>", excerpt: "x".repeat(900) }, { nofile: 1 }, "bad"] },
    { query: "Q2", answer: longAnswer },
    { query: "", answer: "空の質問" },
    { answer: "質問なし" },
    "文字列",
    null,
  ],
}), env, user("u1"));
assert.equal(r.status, 200); let out = await r.json();
assert.deepEqual([out.imported, out.skipped], [2, 4]);
const pinned = await mem.getPinnedMemory(env, "u1");
assert.equal(pinned.length, 2); assert.ok(pinned.every((e) => e.pinned));
const q1 = pinned.find((e) => e.query === "Q1");
assert.deepEqual(q1.sources.map((s) => [s.file, s.namespace, s.score, s.cited]), [["a.md", "shared:houdini22", 88, true]], "invalid sources dropped");
assert.equal(q1.sources[0].excerpt.length, 400); assert.equal(q1.sources[0].evil, undefined, "unknown fields are dropped");
assert.deepEqual(q1.namespaces, ["shared:houdini22"]);
assert.equal(pinned.find((e) => e.query === "Q2").answer.length, 20000, "answers are capped");
assert.equal((await mem.getPinnedMemory(env, "u2")).length, 0, "saved under the importing user only");

// ---- 入力の検証
assert.equal((await mem.handleMemoryImport(post("/memory/import", {}), env, user("u1"))).status, 400);
assert.equal((await mem.handleMemoryImport(post("/memory/import", { entries: [] }), env, user("u1"))).status, 400);
assert.equal((await mem.handleMemoryImport(post("/memory/import", { entries: Array.from({ length: mem.MAX_IMPORT_ENTRIES + 1 }, () => ({ query: "q", answer: "a" })) }), env, user("u1"))).status, 400);
assert.equal((await mem.handleMemoryImport(post("/memory/import", { entries: [{ query: "q", answer: "a" }] }), env, user("g", "guest"))).status, 403);

// ---- 回答1件の取得: 本人のものだけ
const id = q1.id;
r = await mem.handleMemoryGet(post("/memory/get", { id }), env, user("u1"));
assert.equal(r.status, 200); assert.equal((await r.json()).entry.query, "Q1");
r = await mem.handleMemoryGet(post("/memory/get", { id }), env, user("u2"));
assert.equal(r.status, 404, "another user's answer cannot be opened by link");
assert.equal((await mem.handleMemoryGet(post("/memory/get", { id: "1" }), env, user("u1"))).status, 400);
assert.equal((await mem.handleMemoryGet(post("/memory/get", { id: 1.5 }), env, user("u1"))).status, 400);
assert.equal((await mem.handleMemoryGet(post("/memory/get", { id: 99999 }), env, user("u1"))).status, 404);
console.log("memory export/import tests OK");
