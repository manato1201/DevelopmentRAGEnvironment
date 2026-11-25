// 実証実験の第3回（固定課題は全員 RBD）と、基本操作の練習の記録（2026-11-26。src/pilotTasks.ts・migrations/0040）のテスト。
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const pt = await import("../src/pilotTasks");

// ---- 第3回: 題材は全員 RBD。条件の割り当て（半々）は、これまでと同じ ----
const r3 = [1, 2, 3, 4, 5, 6].map((s) => pt.assignmentForSlot(s, "auto", 3));
assert.deepEqual(r3.map((c) => c.taskId), ["rbd", "rbd", "rbd", "rbd", "rbd", "rbd"]);
assert.deepEqual(r3.map((c) => c.condition), ["system", "system", "system", "docs_only", "docs_only", "docs_only"]);
assert.deepEqual([1, 4].map((s) => pt.assignmentForSlot(s, "auto", 2).taskId), ["pyro", "pyro"], "round 2 keeps the old subjects");
assert.deepEqual(pt.assignmentForSlot(4, "system", 3), { taskId: "rbd", condition: "system" }, "the operator's mode still applies");
assert.equal(pt.buildPlan(1, [], 3).fixed.taskId, "rbd");
assert.equal(pt.buildPlan(1, [], 2).fixed.taskId, "pyro");
// 始めた課題は、始めたときの題材のまま（第2回に Pyro で始めた人は、第3回を開いても Pyro）
assert.equal(pt.buildPlan(1, [{ round: 2, kind: "fixed", ended_at: null, task_id: "pyro", condition: "system" }], 3).fixed.taskId, "pyro");

// ---- 初心者と、練習の勧め ----
assert.equal(pt.isBeginner(0, "初級"), true, "less than a year");
assert.equal(pt.isBeginner(0.5, ""), true);
assert.equal(pt.isBeginner(2, "初心者"), true, "self level");
assert.equal(pt.isBeginner(1, "初級"), false);
assert.equal(pt.isBeginner(null, ""), false, "unknown is not a beginner");
const fresh = { step: 0, total: 0, startedAt: null, doneAt: null };
const notStarted = { fixed: { done: false, active: false } };
assert.equal(pt.basicsAdvice(true, fresh, notStarted).recommend, true);
assert.equal(pt.basicsAdvice(false, fresh, notStarted).recommend, false, "only beginners");
assert.equal(pt.basicsAdvice(true, { ...fresh, doneAt: 5 }, notStarted).recommend, false, "not after the practice");
assert.equal(pt.basicsAdvice(true, fresh, { fixed: { done: false, active: true } }).recommend, false, "not after the task started");

// 記録の更新: 戻っても減らさない・最後の手順で終える・終えた時刻は最初のまま
let st = pt.nextBasicsState(fresh, 3, 12, 100);
assert.deepEqual(st, { step: 3, total: 12, startedAt: 100, doneAt: null });
st = pt.nextBasicsState(st, 1, 12, 110);
assert.equal(st.step, 3, "going back keeps the best step");
st = pt.nextBasicsState(st, 12, 12, 120);
assert.deepEqual([st.step, st.startedAt, st.doneAt], [12, 100, 120]);
st = pt.nextBasicsState(st, 12, 12, 200);
assert.equal(st.doneAt, 120, "the first finish is kept");
assert.equal(pt.nextBasicsState(fresh, 99, 12, 1).step, 12, "the step is clamped to the total");

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
const env = { DB: D1 };
const mkUser = (id, role = "member") => { db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES (?,?,?,1)").run(id, id, role); return { userId: id, role }; };
const post = (body) => new Request("https://x/", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const call = async (handler, user, body = {}) => { const res = await handler(post(body), env, user); return { status: res.status, body: await res.json() }; };

const admin = mkUser("boss", "admin");
const users = ["a", "b", "c", "d"].map((id) => mkUser(id));
const [newbie, expert, skipper, control] = users;

// 参加者でない人の練習は、記録しない
let r = await call(pt.handlePilotBasics, newbie, { step: 2, total: 12 });
assert.deepEqual([r.status, r.body.recorded], [200, false]);
assert.equal((await call(pt.handlePilotBasics, newbie, { step: 2, total: 0 })).status, 400);
assert.equal((await call(pt.handlePilotBasics, newbie, { step: "x", total: 12 })).status, 400);

await call(pt.handlePilotConfig, admin, { openRound: 3, labels: { 3: "11/30〜12/5" } });
r = await call(pt.handlePilotProfile, newbie, { experienceMonths: 0, selfLevel: "初級" }); // slot 1
assert.equal(r.body.round, 3);
assert.equal(r.body.roundLabel, "11/30〜12/5");
assert.equal(r.body.fixed.taskId, "rbd");
assert.deepEqual(r.body.basics, { beginner: true, recommend: true, step: 0, total: 0, done: false });
r = await call(pt.handlePilotProfile, expert, { experienceMonths: 36, selfLevel: "中級" }); // slot 2
assert.equal(r.body.basics.recommend, false, "experienced people are not pushed");
await call(pt.handlePilotProfile, skipper, { experienceMonths: 2, selfLevel: "初心者" }); // slot 3
r = await call(pt.handlePilotProfile, control, { experienceMonths: 0 }); // slot 4（対照）
assert.deepEqual([r.body.fixed.taskId, r.body.fixed.condition], ["rbd", "docs_only"]);

// 初心者が練習を進める → 終える → 勧めが消える
r = await call(pt.handlePilotBasics, newbie, { step: 5, total: 12 });
assert.deepEqual([r.body.recorded, r.body.step, r.body.done], [true, 5, false]);
r = await call(pt.handlePilotBasics, newbie, { step: 12, total: 12 });
assert.equal(r.body.done, true);
let plan = await call(pt.handlePilotPlan, newbie);
assert.deepEqual(plan.body.basics, { beginner: true, recommend: false, step: 12, total: 12, done: true });
// 対照の人も、練習はできる（練習は、条件に関係なく、だれにでも勧める）
await call(pt.handlePilotBasics, control, { step: 12, total: 12 });

// 固定課題: 練習を終えてから始めた人（newbie・control）と、練習しなかった初心者（skipper）
const finish = async (u) => {
  const s = await call(pt.handlePilotSessionStart, u, { kind: "fixed" });
  assert.equal(s.body.taskId, "rbd");
  return call(pt.handlePilotSessionEnd, u, { sessionId: s.body.sessionId, reached: true, survey: { difficulty: 3 } });
};
for (const u of [newbie, skipper, control, expert]) await finish(u);
plan = await call(pt.handlePilotPlan, skipper);
assert.deepEqual([plan.body.basics.beginner, plan.body.basics.recommend], [true, false], "no nagging once the task has started");
// 課題を終えたあとに練習しても、「課題の前に終えた」には入らない
await call(pt.handlePilotBasics, skipper, { step: 12, total: 12 });
db.prepare("UPDATE pilot_profile SET basics_done_at = basics_done_at + 10 WHERE user_id = 'c'").run();

const tasks = await call(pt.handlePilotTasks, admin);
const byPid = Object.fromEntries(tasks.body.rows.map((x) => [x.participant, x]));
assert.deepEqual([byPid.P01.beginner, byPid.P01.basicsBefore], [1, 1]);
assert.deepEqual([byPid.P02.beginner, byPid.P02.basicsBefore], [0, 0]);
assert.deepEqual([byPid.P03.beginner, byPid.P03.basicsBefore], [1, 0], "practice after the task does not count");
assert.deepEqual([byPid.P04.beginner, byPid.P04.basicsBefore], [1, 1]);
const groups = tasks.body.byBasics.map((g) => [g.round, g.condition, g.basicsDone, g.n, g.beginners]);
assert.deepEqual(groups, [[3, "docs_only", true, 1, 1], [3, "system", false, 2, 1], [3, "system", true, 1, 1]]);
const prof = Object.fromEntries(tasks.body.profiles.map((p) => [p.participant, p]));
assert.deepEqual([prof.P01.beginner, prof.P01.basicsStep, prof.P01.basicsTotal, prof.P01.basicsDoneAt != null], [true, 12, 12, true]);
assert.deepEqual([prof.P02.beginner, prof.P02.basicsStep], [false, null]);

// 管理画面: 第3回の選択肢・期間の欄・練習の表
const { chatUiHtml } = await import("../src/chatUi");
const html = chatUiHtml();
for (const id of ["pilotRoundLabel3", "pilotBasicsGroups"]) assert.ok(html.includes('id="' + id + '"'), id);
assert.ok(html.includes('<option value="3">第3回</option>'));
assert.ok(html.includes("labels: { 1: label(1), 2: label(2), 3: label(3) }"));
const vm = await import("node:vm");
for (const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) if (m[1].trim()) new vm.Script(m[1]);

console.log("pilot_round3_basics tests passed");
