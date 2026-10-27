// 実証実験の集計（2026-10-27、src/pilotStats.ts）: 管理者だけ。管理者自身の利用は数えない。習熟度は匿名の集計だけ。
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
const env = { DB: D1 };
const { handlePilotSummary, MIN_GROUP } = await import("../src/pilotStats");
const { ForbiddenError } = await import("../src/auth");

const NOW = Math.floor(Date.now() / 1000);
const DAY = 86400;
const users = [["ad", "運営", "admin"], ["ed", "編集者", "editor"], ["m1", "参加者A", "member"], ["m2", "参加者B", "member"], ["m3", "参加者C", "member"], ["m4", "休眠", "member"], ["g1", "ゲスト", "guest"]];
for (const [id, name, role] of users) db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES (?, ?, ?, 1)").run(id, name, role);

let seq = 0;
const memory = (user, rating, explain, ageDays = 1) => db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, rating, created_at, explain_level) VALUES (?, 'q', 'a', '[]', ?, ?, ?)").run(user, rating, NOW - ageDays * DAY, explain);
const tutorial = (user, rating, level, houdini, ageDays = 1) => db.prepare("INSERT INTO tutorial_feedback (user_id, tutorial_key, rating, level, houdini_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)").run(user, "k" + ++seq, rating, level, houdini, NOW - ageDays * DAY, NOW - ageDays * DAY);

// 参加者A: 説明おまかせで3問（良2・悪1）、チュートリアルは良1（basic・Houdini 22）
memory("m1", 1, "auto:applied"); memory("m1", 1, "auto:applied"); memory("m1", -1, "auto:basic");
tutorial("m1", 1, "basic", "22.0");
// 参加者B: 指定なしで2問（良1・未評価1）、チュートリアル悪1（advanced・Houdini 21）
memory("m2", 1, null); memory("m2", null, null);
tutorial("m2", -1, "advanced", "21.0");
// 参加者C: basic 固定で1問（悪）
memory("m3", -1, "fixed:basic");
// 古い（期間外）の利用: 参加者Bの60日前 / 休眠の人は、期間内に何も無い
memory("m2", 1, null, 60); tutorial("m2", 1, "basic", "22.0", 60); memory("m4", 1, null, 90);
// 運営（管理者）のテストと、編集者の利用: 管理者は数えない
memory("ad", 1, "auto:advanced"); tutorial("ad", 1, "advanced", "22.0");

const asUser = (id, role) => ({ userId: id, role, allowedNamespaces: [] });
const call = async (user, body = {}) => handlePilotSummary(new Request("https://x/admin/pilot/summary", { method: "POST", body: JSON.stringify(body) }), env, user);

// ---- 管理者だけ
for (const [id, role] of [["ed", "editor"], ["m1", "member"], ["g1", "guest"]]) {
  await assert.rejects(() => call(asUser(id, role)), ForbiddenError, role + " is rejected");
}

// ---- 管理者の集計
let res = await (await call(asUser("ad", "admin"), { days: 30 })).json();
assert.equal(res.status, "ok");
assert.equal(res.days, 30);
const byName = Object.fromEntries(res.participants.map((p) => [p.displayName, p]));
assert.deepEqual(Object.keys(byName).sort(), ["参加者A", "参加者B", "参加者C"].sort(), "admin, dormant users and guests are not listed");
assert.equal(byName["参加者A"].questions, 3);
assert.equal(byName["参加者A"].chatGood, 2);
assert.equal(byName["参加者A"].chatBad, 1);
assert.equal(byName["参加者A"].tutorialGood, 1);
assert.equal(byName["参加者B"].questions, 2, "the 60-day-old question is outside the 30-day window");
assert.equal(byName["参加者B"].tutorialBad, 1);
assert.equal(byName["参加者B"].tutorialGood, 0, "the old tutorial rating is outside the window");
assert.ok(byName["参加者B"].lastQuestionAt >= NOW - 2 * DAY);
assert.deepEqual(res.participants.map((p) => p.displayName)[0], "参加者A", "sorted by questions, most first");

assert.equal(res.kpis.participants, 3);
assert.equal(res.kpis.questions, 6);
assert.equal(res.kpis.chatRated, 5);
assert.ok(Math.abs(res.kpis.chatGoodRate - 3 / 5) < 1e-9);
assert.equal(res.kpis.tutorialRated, 2);
assert.ok(Math.abs(res.kpis.tutorialGoodRate - 0.5) < 1e-9);

// 説明レベル別（管理者の auto:advanced は入らない）
const ex = Object.fromEntries(res.byExplain.map((b) => [b.key, b]));
assert.deepEqual(Object.keys(ex).sort(), ["auto:applied", "auto:basic", "fixed:basic", "指定なし"].sort());
assert.equal(ex["auto:applied"].total, 2);
assert.equal(ex["auto:applied"].goodRate, 1);
assert.equal(ex["auto:basic"].goodRate, 0);
assert.equal(ex["指定なし"].total, 2);
assert.equal(ex["指定なし"].goodRate, 1, "unrated answers are not counted in the rate");
assert.equal(ex["fixed:basic"].bad, 1);

// チュートリアル: 段階別・Houdiniの版別
const tl = Object.fromEntries(res.tutorialByLevel.map((b) => [b.key, b]));
assert.equal(tl.basic.total, 1);
assert.equal(tl.advanced.bad, 1);
assert.ok(!("" in tl));
const th = Object.fromEntries(res.tutorialByHoudini.map((b) => [b.key, b]));
assert.equal(th["22.0"].good, 1);
assert.equal(th["21.0"].bad, 1);

// 期間を変えると、古い分も入る
res = await (await call(asUser("ad", "admin"), { days: 365 })).json();
assert.equal(res.participants.find((p) => p.displayName === "参加者B").questions, 3);
assert.ok(res.participants.some((p) => p.displayName === "休眠"), "dormant user appears when the window covers the old activity");
// 期間の入力は丸める
assert.equal((await (await call(asUser("ad", "admin"), { days: 99999 })).json()).days, 365);
assert.equal((await (await call(asUser("ad", "admin"), { days: "abc" })).json()).days, 30);
assert.equal((await (await call(asUser("ad", "admin"))).json()).days, 30);

// ---- 習熟度: 少人数のときは出さない
const term = (user, name, count) => db.prepare("INSERT INTO user_terms (user_id, term, count, first_seen, last_seen) VALUES (?, ?, ?, 1, 1)").run(user, name, count);
term("m1", "SOP", 5); term("m1", "VEX", 3);
term("m2", "SOP", 2);
term("ad", "PDG", 9); // 管理者の記録は、数えない
res = await (await call(asUser("ad", "admin"))).json();
assert.equal(res.growth.hidden, true);
assert.equal(res.minGroup, MIN_GROUP);
assert.ok(res.growth.reason.includes("3人未満"));
assert.equal(res.growth.topTerms, undefined, "nothing is shown for a small group");
for (const identity of ["m1", "m2", "参加者A", "参加者B"]) assert.ok(!JSON.stringify(res.growth).includes(identity), "no identity: " + identity);

// 3人そろうと、匿名の分布と用語が出る。1人しか使っていない用語は出ない
term("m3", "SOP", 1); term("m3", "アトリビュート", 6);
for (let i = 0; i < 3; i++) term("m3", ["VOP", "HDA", "ソルバー"][i], 3);
res = await (await call(asUser("ad", "admin"))).json();
assert.equal(res.growth.hidden, false);
assert.equal(res.growth.users, 3, "the admin is not counted");
assert.equal(res.growth.levels.basic + res.growth.levels.applied + res.growth.levels.advanced, 3);
assert.equal(res.growth.levels.applied, 1, "m3 reached applied");
const top = Object.fromEntries(res.growth.topTerms.map((t) => [t.term, t]));
assert.equal(top["SOP"].users, 3);
assert.equal(top["SOP"].total, 8);
assert.equal(top["VEX"], undefined, "terms used by a single person are not listed");
assert.equal(top["PDG"], undefined, "the admin's terms are not counted");
assert.equal(res.growth.topTerms[0].term, "SOP");
const growthJson = JSON.stringify(res.growth);
for (const id of ["m1", "m2", "m3", "参加者A", "参加者B", "参加者C"]) assert.ok(!growthJson.includes(id), "no user identity in the growth aggregate: " + id);

// 参加者の表には、習熟度・用語を出さない
for (const p of res.participants) {
  assert.deepEqual(Object.keys(p).sort(), ["chatBad", "chatGood", "displayName", "lastQuestionAt", "questions", "role", "tutorialBad", "tutorialGood", "userId"]);
}
console.log("pilot_stats tests passed");
