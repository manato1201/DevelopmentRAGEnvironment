// Reference タブの説明の保管と取得（2026-11-19、src/reference.ts・migrations/0038）のテスト。
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ref = await import("../src/reference");

// ---- 検査の部品 ----
assert.ok(ref.validMediaId("node/sop/mountain/after.png"));
for (const bad of ["", "../x.png", "/abs.png", "a//b.png", "a/", "a b.png", "a\b.png", "x".repeat(201), 3, null]) assert.ok(!ref.validMediaId(bad), `rejects ${String(bad)}`);
assert.equal(ref.mediaContentType("a/b.WEBM"), "video/webm");
assert.equal(ref.mediaContentType("a/b.png"), "image/png");
assert.equal(ref.mediaContentType("a/b.exe"), null);
assert.deepEqual(ref.cleanMedia([{ id: "a/b.png", role: "before", label: "前" }, { id: "../x.png" }, { id: "a/c.exe" }, null, { id: "a/d.mp4" }]).map((m) => [m.id, m.type, m.role]), [["a/b.png", "image", "before"], ["a/d.mp4", "video", "clip"]]);
assert.equal(ref.cleanEntryBody({ what: "  ", use: "" }), null, "all-empty is rejected");
assert.equal(ref.cleanEntryBody("x"), null);
const body = ref.cleanEntryBody({ what: "点を散らす", when: "x".repeat(5000), references: [{ title: "t", url: "https://e.com/a" }, { title: "bad", url: "javascript:alert(1)" }] });
assert.equal(body.what, "点を散らす");
assert.equal(body.when.length, ref.SECTION_MAX, "long text is clipped");
// 同じ結果にする条件（2026-11-28）: 形を保って通し、変なキー・深すぎる入れ子・大きすぎるものは落とす
const cond = { frame: 40, sim: true, display: "final", nodes: [{ name: "cloth", type: "grid", parms: [{ name: "size", label: "Size", value: "2, 2" }], inputs: [], "Bad-Key": "x", a: { b: { c: { d: { e: { f: 1 } } } } } }] };
const withCond = ref.cleanEntryBody({ what: "布を動かす", conditions: cond });
assert.equal(withCond.conditions.frame, 40);
assert.equal(withCond.conditions.nodes[0].parms[0].label, "Size");
assert.ok(!("Bad-Key" in withCond.conditions.nodes[0]), "odd keys are dropped");
assert.equal(ref.cleanConditions({ frame: 1, nodes: [] }), null, "no nodes, no conditions");
assert.equal(ref.cleanConditions({ nodes: Array.from({ length: 40 }, () => ({ note: "x".repeat(600), more: "y".repeat(600) })) }), null, "too large is rejected");
assert.equal(ref.cleanEntryBody({ what: "x", conditions: "text" }).conditions, undefined);
assert.equal(body.references.length, 1, "non-http references are dropped");

// ---- ハンドラ（実際のスキーマで） ----
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
const store = new Map();
const R2 = { async put(k, v) { store.set(k, v); }, async get(k) { return store.has(k) ? { body: store.get(k), size: store.get(k).byteLength } : null; } };
const env = { DB: D1, REFERENCE_MEDIA: R2 };
const member = { userId: "u", role: "member" }, admin = { userId: "boss", role: "admin" };
const post = (body) => new Request("https://x/", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const call = async (handler, user, body = {}) => { const res = await handler(post(body), env, user); return { status: res.status, body: await res.json() }; };

// 空のとき
assert.deepEqual((await call(ref.handleReferenceIndex, member)).body.items, []);
assert.equal((await call(ref.handleReferenceEntry, member, { kind: "node", key: "sop/scatter" })).status, 404);
assert.equal((await call(ref.handleReferenceEntry, member, { kind: "nope", key: "x" })).status, 400);

// 会員は書けない。管理者は書ける
await assert.rejects(() => ref.handleReferencePut(post({ kind: "node", key: "sop/scatter", entry: { what: "x" } }), env, member), "members cannot publish");
await assert.rejects(() => ref.handleReferenceDelete(post({ kind: "node", key: "sop/scatter" }), env, member));
await assert.rejects(() => ref.handleReferenceMediaPut(new Request("https://x/?id=a.png", { method: "POST", body: "x" }), env, member));
assert.equal((await call(ref.handleReferencePut, admin, { kind: "node", key: "sop/scatter", entry: {} })).status, 400);
assert.equal((await call(ref.handleReferencePut, admin, { kind: "bad", key: "x", entry: { what: "a" } })).status, 400);

let r = await call(ref.handleReferencePut, admin, { kind: "node", key: "sop/scatter", title: "Scatter", entry: { what: "点を散らす", use: "植生" }, media: [{ id: "node/sop/scatter/after.png", role: "after", label: "後" }] });
assert.equal(r.status, 200);
assert.equal(r.body.version, 1);
assert.equal(r.body.media, 1);
r = await call(ref.handleReferencePut, admin, { kind: "node", key: "sop/scatter", title: "Scatter", entry: { what: "点を散らす（改）" } });
assert.equal(r.body.version, 2, "each rewrite bumps the version");
await call(ref.handleReferencePut, admin, { kind: "vex", key: "vex/chf", title: "chf", entry: { what: "チャンネルを読む" } });

// 取得（会員でも読める）
const idx = (await call(ref.handleReferenceIndex, member)).body;
assert.equal(idx.count, 2);
assert.deepEqual(idx.items.map((i) => [i.kind, i.key, i.version, i.mediaCount]), [["node", "sop/scatter", 2, 0], ["vex", "vex/chf", 1, 0]]);
assert.ok(!JSON.stringify(idx).includes("点を散らす"), "the index carries no body");
const got = (await call(ref.handleReferenceEntry, member, { kind: "node", key: "sop/scatter" })).body;
assert.equal(got.entry.what, "点を散らす（改）");
assert.equal(got.version, 2);

// 画像・動画
assert.equal((await call(ref.handleReferenceMedia, member, { id: "../x.png" })).status, 400);
assert.equal((await call(ref.handleReferenceMedia, member, { id: "node/sop/scatter/after.png" })).status, 404, "not uploaded yet");
const put = await ref.handleReferenceMediaPut(new Request("https://x/?id=node/sop/scatter/after.png", { method: "POST", body: new Uint8Array([1, 2, 3]) }), env, admin);
assert.equal(put.status, 200);
const media = await ref.handleReferenceMedia(post({ id: "node/sop/scatter/after.png" }), env, member);
assert.equal(media.status, 200);
assert.equal(media.headers.get("content-type"), "image/png");
assert.deepEqual([...new Uint8Array(await media.arrayBuffer())], [1, 2, 3]);
assert.equal((await ref.handleReferenceMediaPut(new Request("https://x/?id=a.exe", { method: "POST", body: "x" }), env, admin)).status, 400);
assert.equal((await ref.handleReferenceMediaPut(new Request("https://x/?id=a.png", { method: "POST", body: new Uint8Array(0) }), env, admin)).status, 400, "empty");
assert.equal((await ref.handleReferenceMediaPut(new Request("https://x/?id=a.png", { method: "POST", body: new Uint8Array(ref.MEDIA_MAX_BYTES + 1) }), env, admin)).status, 413);
// R2 が未設定のとき
const noR2 = { DB: D1 };
assert.equal((await ref.handleReferenceMedia(post({ id: "a.png" }), noR2, member)).status, 503);

// 削除
assert.equal((await call(ref.handleReferenceDelete, admin, { kind: "vex", key: "vex/chf" })).body.deleted, 1);
assert.equal((await call(ref.handleReferenceIndex, member)).body.count, 1);

console.log("reference ok");
