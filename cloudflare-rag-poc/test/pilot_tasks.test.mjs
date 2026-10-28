// 実証実験の課題の記録とアンケート（2026-10-28、src/pilotTasks.ts・migrations/0035）のテスト。
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const pt = await import("../src/pilotTasks");

// ---- 割り当て（ラテン方格・対照） ----
assert.deepEqual([1, 2, 3, 4, 5, 6, 7].map(pt.slotForPid), [1, 2, 3, 1, 2, 3, 1]);
for (const slot of [1, 2, 3]) assert.equal(new Set(pt.LATIN[slot]).size, 3, "each participant does every task once");
for (let round = 0; round < 3; round++) assert.equal(new Set([1, 2, 3].map((s) => pt.LATIN[s][round])).size, 3, "each round covers every task");
// 対照（回 = slot）の題材は、3人で1つずつ違う
assert.deepEqual([1, 2, 3].map((s) => pt.LATIN[s][s - 1]).sort(), ["cloud", "pyro", "rbd"]);

// ---- 操作ミス: cookエラー7割 + 自己申告3割 ----
assert.equal(pt.mistakeScore(0, 1), 0);
assert.equal(pt.mistakeScore(10, 5), 1);
assert.equal(pt.mistakeScore(99, 5), 1, "cook errors are capped");
assert.equal(pt.mistakeScore(5, 1), 0.35); // 0.7 * 0.5
assert.equal(pt.mistakeScore(0, 5), 0.3); // 0.3 * 1
assert.equal(pt.mistakeScore(5, 3), 0.5); // 0.7*0.5 + 0.3*0.5
assert.equal(pt.mistakeScore(null, 3), null, "no substitute when one side is missing");
assert.equal(pt.mistakeScore(3, undefined), null);

// ---- 次の課題 ----
const s = (round, kind, ended = true) => ({ round, kind, ended_at: ended ? 1 : null });
let plan = pt.buildPlan(1, []);
assert.equal(plan.round, 1);
assert.equal(plan.fixed.taskId, "pyro");
assert.equal(plan.fixed.condition, "docs_only", "slot 1: round 1 is the control");
assert.equal(plan.free.condition, "system", "free tasks always use the system");
assert.equal(pt.buildPlan(2, []).fixed.condition, "system");
plan = pt.buildPlan(1, [s(1, "fixed")]);
assert.equal(plan.round, 1, "a round is complete only with both tasks");
assert.ok(plan.fixed.done && !plan.free.done);
plan = pt.buildPlan(1, [s(1, "fixed"), s(1, "free")]);
assert.equal(plan.round, 2);
assert.equal(plan.fixed.taskId, "rbd");
assert.equal(plan.fixed.condition, "system");
assert.equal(plan.completedRounds, 1);
assert.ok(pt.buildPlan(2, [s(1, "fixed"), s(1, "free"), s(2, "fixed", false)]).fixed.active);
plan = pt.buildPlan(3, [1, 2, 3].flatMap((r) => [s(r, "fixed"), s(r, "free")]));
assert.ok(plan.finished);
assert.equal(plan.round, 3);

// ---- 集計の部品 ----
assert.equal(pt.median([]), null);
assert.equal(pt.median([3, 1, 2]), 2);
assert.equal(pt.median([1, 2, 3, 4]), 2.5);
assert.equal(pt.median([null, 5, undefined]), 5);
assert.equal(pt.pairedRankBiserial([1, 2, 3]), 1);
assert.equal(pt.pairedRankBiserial([-1, -2, -3]), -1);
assert.equal(pt.pairedRankBiserial([1, -1]), 0);
assert.equal(pt.pairedRankBiserial([0, 0]), null, "zero differences carry no direction");
assert.equal(pt.pairedRankBiserial([]), null);
// 順位: |d| = 1,2,2,4 → 順位 1,2.5,2.5,4（同順位は平均）。正: 1+2.5+4=7.5、負: 2.5 → (7.5−2.5)/10 = 0.5
assert.equal(pt.pairedRankBiserial([1, 2, -2, 4]), 0.5);

const row = (pid, round, kind, condition, extra = {}) => ({
  pid, round, kind, taskId: kind === "free" ? "free" : "pyro", condition,
  durationSec: 1800, queryCount: 0, cookErrorNodes: 2, reached: 1, selfMistakes: 2,
  difficulty: 3, clarity: 3, focus: 2, accuracyWorry: 2, sourceUseful: 4, reuse: 4, comment: "", ...extra,
});
const rows = [
  // 参加者1: 対照（1回目）より、システムの回（2・3回目）のほうが、やさしく・速い
  row(1, 1, "fixed", "docs_only", { difficulty: 4, clarity: 2, durationSec: 3600, cookErrorNodes: 6, selfMistakes: 4, reached: 0 }),
  row(1, 2, "fixed", "system", { difficulty: 2, clarity: 4, durationSec: 1800, cookErrorNodes: 2, selfMistakes: 2 }),
  row(1, 3, "fixed", "system", { difficulty: 2, clarity: 5, durationSec: 1200, cookErrorNodes: 0, selfMistakes: 1 }),
  row(1, 1, "free", "system"),
  // 参加者2: 対照は2回目。ここでも、システムの回のほうが良い
  row(2, 1, "fixed", "system", { difficulty: 3, clarity: 4, durationSec: 2400 }),
  row(2, 2, "fixed", "docs_only", { difficulty: 5, clarity: 2, durationSec: 4200, queryCount: 3, comment: "検索で迷った" }),
  row(2, 3, "fixed", "system", { difficulty: 3, clarity: 4, durationSec: 2400 }),
  // 参加者3: 差なし
  row(3, 1, "fixed", "system"), row(3, 2, "fixed", "system"), row(3, 3, "fixed", "docs_only"),
];
const sum = pt.summarizeTasks(rows);
assert.equal(sum.participants, 3);
assert.equal(sum.sessions, rows.length);
const byKey = Object.fromEntries(sum.paired.map((p) => [p.key, p]));
assert.equal(byKey.difficulty.pairs, 3);
assert.equal(byKey.difficulty.improved, 2);
assert.equal(byKey.difficulty.medianDiff, -2, "system − docs: p1 −2, p2 −2, p3 0 → median −2");
assert.ok(byKey.difficulty.rankBiserial < 0, "lower difficulty with the system");
assert.equal(byKey.clarity.improved, 2);
assert.ok(byKey.clarity.rankBiserial > 0);
assert.equal(byKey.reached.pairs, 3);
assert.deepEqual(sum.contaminated, [2], "a control round with questions is flagged");
assert.deepEqual(sum.comments.map((c) => c.pid), [2]);
const g = sum.byGroup.find((x) => x.round === 1 && x.kind === "fixed" && x.condition === "system");
assert.equal(g.n, 2);
const noControl = pt.summarizeTasks([row(1, 1, "fixed", "system")]);
assert.ok(noControl.paired.every((p) => p.pairs === 0 && p.medianDiff === null), "no pairs without a control round");

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

const u1 = mkUser("u1"), u2 = mkUser("u2"), u3 = mkUser("u3"), admin = mkUser("boss", "admin");

// 登録前
assert.equal((await call(pt.handlePilotPlan, u1)).body.profile, false);
assert.equal((await call(pt.handlePilotSessionStart, u1, { kind: "fixed" })).status, 409, "must register first");

// 事前アンケート: 番号は登録順。再送しても変わらない。管理者は番号を取らない
let r = await call(pt.handlePilotProfile, u1, { experienceYears: 1.5, selfLevel: "初級", background: "CG専攻" });
assert.equal(r.body.pid, 1);
assert.equal(r.body.slot, 1);
assert.equal((await call(pt.handlePilotProfile, u2, {})).body.slot, 2);
assert.equal((await call(pt.handlePilotProfile, u3, {})).body.slot, 3);
assert.equal((await call(pt.handlePilotProfile, u1, { experienceYears: 2 })).body.pid, 1, "re-sending keeps the number");
assert.equal(db.prepare("SELECT experience_years AS y FROM pilot_profile WHERE user_id='u1'").get().y, 2, "answers are updated");
const adminPlan = await call(pt.handlePilotProfile, admin, {});
assert.equal(adminPlan.body.pid, null);
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM pilot_profile").get().n, 4);

// 開始（slot 1: 第1回の固定課題は Pyro・対照）
r = await call(pt.handlePilotSessionStart, u1, { kind: "fixed" });
assert.equal(r.status, 200);
assert.equal(r.body.taskId, "pyro");
assert.equal(r.body.condition, "docs_only");
const sid = r.body.sessionId;
assert.equal((await call(pt.handlePilotSessionStart, u1, { kind: "fixed" })).body.sessionId, sid, "a started task is resumed, not duplicated");
assert.equal((await call(pt.handlePilotSessionStart, u1, { kind: "bogus" })).status, 400);

// 対照の回に、質問が混ざった（本システムを使った）
const t0 = db.prepare("SELECT started_at AS t FROM pilot_sessions WHERE id=?").get(sid).t;
db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, created_at) VALUES ('u1','q','a','[]',?)").run(t0);
db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, created_at) VALUES ('u1','old','a','[]',?)").run(t0 - 100);
db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, created_at) VALUES ('u2','other','a','[]',?)").run(t0);

// 他人の課題は終えられない
assert.equal((await call(pt.handlePilotSessionEnd, u2, { sessionId: sid })).status, 404);
assert.equal((await call(pt.handlePilotSessionEnd, u1, { sessionId: "nope" })).status, 404);

// 終了: 範囲外の値は無効（null）。対照の回の「出典の有用性」は保存しない
r = await call(pt.handlePilotSessionEnd, u1, {
  sessionId: sid, reached: true, cookErrorNodes: 4, selfMistakes: 3,
  survey: { difficulty: 4, clarity: 2, focus: 9, accuracyWorry: "x", sourceUseful: 5, reuse: 3 }, comment: "  検索が大変  ",
});
assert.equal(r.status, 200);
let saved = db.prepare("SELECT * FROM pilot_sessions WHERE id=?").get(sid);
assert.equal(saved.query_count, 1, "only this user's questions inside the window");
assert.equal(saved.reached, 1);
assert.equal(saved.cook_error_nodes, 4);
assert.equal(saved.self_mistakes, 3);
assert.equal(saved.difficulty, 4);
assert.equal(saved.focus, null, "out of range → null");
assert.equal(saved.accuracy_worry, null, "not a number → null");
assert.equal(saved.source_useful, null, "no usefulness for the control round");
assert.equal(saved.reuse, 3);
assert.equal(saved.comment, "検索が大変");
assert.ok(saved.duration_sec >= 0 && saved.ended_at >= saved.started_at);
assert.equal((await call(pt.handlePilotSessionEnd, u1, { sessionId: sid })).status, 409, "cannot end twice");
assert.equal((await call(pt.handlePilotSessionStart, u1, { kind: "fixed" })).status, 409, "this round's fixed task is done");

// 自由課題 → 第2回へ
r = await call(pt.handlePilotSessionStart, u1, { kind: "free" });
assert.equal(r.body.taskId, "free");
assert.equal(r.body.condition, "system");
r = await call(pt.handlePilotSessionEnd, u1, { sessionId: r.body.sessionId, reached: false, survey: { sourceUseful: 4 } });
assert.equal(r.body.round, 2);
assert.equal(r.body.fixed.taskId, "rbd");
assert.equal(r.body.fixed.condition, "system");
assert.equal(db.prepare("SELECT source_useful AS s FROM pilot_sessions WHERE kind='free'").get().s, 4, "kept in system rounds");

// 管理者の集計: 氏名なし・管理者の記録は入らない・番号で出る
const as = await call(pt.handlePilotSessionStart, admin, { kind: "fixed" });
await call(pt.handlePilotSessionEnd, admin, { sessionId: as.body.sessionId, survey: { difficulty: 1 } });
const tasks = await call(pt.handlePilotTasks, admin);
assert.equal(tasks.body.registered, 3);
assert.equal(tasks.body.sessions, 2);
assert.deepEqual(tasks.body.rows.map((x) => x.participant), ["P01", "P01"]);
assert.ok(!JSON.stringify(tasks.body).includes("u1"), "no user id or name in the aggregate");
assert.deepEqual(tasks.body.contaminated, [1], "the control round had a question");
assert.equal(tasks.body.rows[0].mistake, 0.43, "cook 4/10 × 0.7 = 0.28, self (3−1)/4 × 0.3 = 0.15");
await assert.rejects(() => pt.handlePilotTasks(post({}), env, u1), "members cannot read the aggregate");

// ---- 所要時間: 振り返りの回答の時間と、中断（Houdini が閉じていた時間）を引く ----
r = await call(pt.handlePilotSessionStart, u2, { kind: "fixed" });
const sid2 = r.body.sessionId;
const ago = Math.floor(Date.now() / 1000) - 3600;
db.prepare("UPDATE pilot_sessions SET started_at = ? WHERE id = ?").run(ago, sid2);
await call(pt.handlePilotSessionEnd, u2, { sessionId: sid2, surveySec: 300, pausedSec: 600 });
saved = db.prepare("SELECT * FROM pilot_sessions WHERE id=?").get(sid2);
assert.ok(Math.abs(saved.duration_sec - 2700) <= 3, `3600 − 300(survey) − 600(paused) = 2700, got ${saved.duration_sec}`);
assert.equal(saved.paused_sec, 600);
assert.ok(Math.abs(saved.ended_at - (ago + 3300)) <= 3, "ended when 終了 was pressed, not when the survey was sent");
// 異常な値でも、所要時間は負にならない
r = await call(pt.handlePilotSessionStart, u2, { kind: "free" });
await call(pt.handlePilotSessionEnd, u2, { sessionId: r.body.sessionId, surveySec: 99999, pausedSec: 99999 });
saved = db.prepare("SELECT * FROM pilot_sessions WHERE id=?").get(r.body.sessionId);
assert.equal(saved.duration_sec, 0);
assert.ok(saved.ended_at >= saved.started_at);

// ---- やり直し ----
// 計測中の記録を破棄 → 同じ課題を、新しい記録で始め直せる
r = await call(pt.handlePilotSessionStart, u3, { kind: "fixed" }); // slot 3: 第1回の固定課題は、雲（システムあり）
assert.equal(r.body.taskId, "cloud");
const run1 = r.body.sessionId;
let plan3 = await call(pt.handlePilotSessionReset, u3, { sessionId: run1 });
assert.equal(plan3.status, 200);
assert.equal(plan3.body.fixed.active, false, "the discarded run is not 'in progress'");
assert.equal(plan3.body.history.length, 0);
r = await call(pt.handlePilotSessionStart, u3, { kind: "fixed" });
assert.notEqual(r.body.sessionId, run1, "a fresh record, not the discarded one");
assert.equal(r.body.resumed, false);
assert.equal((await call(pt.handlePilotSessionEnd, u3, { sessionId: run1 })).status, 404, "a discarded record cannot be ended");
assert.equal((await call(pt.handlePilotSessionReset, u3, { sessionId: run1 })).status, 404, "discard once only");
assert.equal((await call(pt.handlePilotSessionReset, u1, { sessionId: r.body.sessionId })).status, 404, "not someone else's");
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM pilot_sessions WHERE user_id='u3'").get().n, 2, "the discarded record is kept");
const run2 = r.body.sessionId;
await call(pt.handlePilotSessionEnd, u3, { sessionId: run2, reached: true, survey: { difficulty: 2 } });

// 終えた記録の取り消し: 次の回を始める前なら、できる
r = await call(pt.handlePilotSessionStart, u3, { kind: "free" });
plan3 = await call(pt.handlePilotSessionEnd, u3, { sessionId: r.body.sessionId, reached: true });
assert.equal(plan3.body.round, 2, "both done → the next round");
assert.deepEqual(plan3.body.history.map((h) => [h.round, h.kind, h.redoable]), [[1, "fixed", true], [1, "free", true]]);
const freeId = plan3.body.history[1].sessionId;
plan3 = await call(pt.handlePilotSessionReset, u3, { sessionId: freeId }); // 間違えて終えた自由課題を、取り消す
assert.equal(plan3.body.round, 1, "back to round 1");
assert.equal(plan3.body.free.done, false);
assert.equal(plan3.body.fixed.done, true, "the other task keeps its record");
r = await call(pt.handlePilotSessionStart, u3, { kind: "free" });
await call(pt.handlePilotSessionEnd, u3, { sessionId: r.body.sessionId, reached: true });
// 第2回を始めたら、第1回は固定される
r = await call(pt.handlePilotSessionStart, u3, { kind: "fixed" });
assert.equal(r.body.round, 2);
const round2 = r.body.sessionId;
plan3 = await call(pt.handlePilotPlan, u3);
assert.deepEqual(plan3.body.history.map((h) => [h.round, h.kind, h.redoable]), [[1, "fixed", false], [1, "free", false], [2, "fixed", true]]);
assert.equal(plan3.body.history[2].running, true);
const locked = await call(pt.handlePilotSessionReset, u3, { sessionId: plan3.body.history[0].sessionId });
assert.equal(locked.status, 409, "cannot change round 1 once round 2 has started");
assert.equal((await call(pt.handlePilotSessionReset, u3, { sessionId: round2 })).status, 200, "the running record of the current round can be discarded");

// 集計: 破棄した記録は入らず、やり直した回数だけ分かる
const after = await call(pt.handlePilotTasks, admin);
const p3 = after.body.rows.filter((x) => x.participant === "P03");
assert.equal(p3.length, 2, "only the kept records of P03");
assert.deepEqual(p3.map((x) => [x.kind, x.redoCount]), [["fixed", 1], ["free", 1]], "each of the redone tasks was redone once");
assert.equal(after.body.rows.filter((x) => x.participant === "P01").every((x) => x.redoCount === 0), true);

// ---- 管理画面: 課題の集計の部品が入っていて、スクリプトが構文として読める ----
const vm = await import("node:vm");
const { chatUiHtml } = await import("../src/chatUi");
const html = chatUiHtml();
for (const id of ["pilotTaskNote", "pilotTasksCsv", "pilotTaskGroups", "pilotPaired"]) assert.ok(html.includes('id="' + id + '"'), id);
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).filter((c) => c.trim().length > 0);
for (const code of scripts) new vm.Script(code);
assert.ok(scripts.join("\n").includes('api("/admin/pilot/tasks"'));

console.log("pilot_tasks tests passed");
