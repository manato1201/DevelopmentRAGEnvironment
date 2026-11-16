// 実証実験の課題の記録とアンケート（2026-10-28、src/pilotTasks.ts・migrations/0035・0037）のテスト。
// 2026-11-11: 1人1回（3時間）・回 = 募集期間・管理画面で受け付ける回を切り替える・対照は参加者の間で比べる。
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const pt = await import("../src/pilotTasks");

// ---- 割り当て（3題材 × 2条件 = 6通りを、登録順に回す） ----
assert.deepEqual([1, 2, 3, 4, 5, 6, 7, 8].map(pt.slotForPid), [1, 2, 3, 4, 5, 6, 1, 2]);
const cells = [1, 2, 3, 4, 5, 6].map(pt.assignmentForSlot);
assert.deepEqual(cells.map((c) => `${c.taskId}/${c.condition}`), ["pyro/system", "rbd/system", "cloud/system", "pyro/docs_only", "rbd/docs_only", "cloud/docs_only"]);
assert.equal(new Set(cells.map((c) => `${c.taskId}/${c.condition}`)).size, 6, "each task × condition cell once per 6 participants");
assert.deepEqual(pt.assignmentForSlot(7), pt.assignmentForSlot(1), "the cells repeat");
assert.deepEqual(pt.assignmentForSlot(0), pt.assignmentForSlot(6), "odd slots stay inside the table");
assert.equal(pt.ROUNDS, 2);

// ---- 操作ミス: cookエラー7割 + 自己申告3割 ----
assert.equal(pt.mistakeScore(0, 1), 0);
assert.equal(pt.mistakeScore(10, 5), 1);
assert.equal(pt.mistakeScore(99, 5), 1, "cook errors are capped");
assert.equal(pt.mistakeScore(5, 1), 0.35); // 0.7 * 0.5
assert.equal(pt.mistakeScore(0, 5), 0.3); // 0.3 * 1
assert.equal(pt.mistakeScore(5, 3), 0.5); // 0.7*0.5 + 0.3*0.5
assert.equal(pt.mistakeScore(null, 3), null, "no substitute when one side is missing");
assert.equal(pt.mistakeScore(3, undefined), null);

// ---- 次の課題（受け付けている回で決まる） ----
const s = (round, kind, ended = true) => ({ round, kind, ended_at: ended ? 1 : null });
let plan = pt.buildPlan(1, [], 0);
assert.equal(plan.round, null, "not accepting: no round yet");
assert.equal(plan.canStart, false);
assert.equal(plan.openRound, 0);
assert.equal(pt.buildPlan(1, [], 3).canStart, false, "an out-of-range open round counts as closed");
plan = pt.buildPlan(1, [], 1);
assert.equal(plan.round, 1);
assert.equal(plan.canStart, true);
assert.equal(plan.fixed.taskId, "pyro");
assert.equal(plan.fixed.condition, "system");
assert.equal(plan.free.condition, "system", "free tasks always use the system");
assert.equal(pt.buildPlan(4, [], 2).fixed.condition, "docs_only", "slot 4 is the control");
assert.equal(pt.buildPlan(4, [], 2).round, 2, "joins the round that is open");
plan = pt.buildPlan(2, [s(1, "fixed")], 2);
assert.equal(plan.round, 1, "someone who already joined stays in their own round");
assert.equal(plan.canStart, true);
assert.ok(plan.fixed.done && !plan.free.done && !plan.finished);
assert.equal(plan.completed, true, "the fixed task alone completes the participation (the free task is optional)");
assert.equal(plan.free.optional, true);
assert.equal(plan.fixed.optional, false);
assert.equal(pt.buildPlan(2, [s(1, "free")], 1).completed, false, "the free task alone does not complete it");
assert.equal(pt.buildPlan(2, [s(1, "fixed")], 0).canStart, true, "closing does not lock out people who are partway");
assert.ok(pt.buildPlan(2, [s(1, "fixed", false)], 1).fixed.active);
plan = pt.buildPlan(2, [s(1, "fixed"), s(1, "free")], 2);
assert.ok(plan.finished, "one round is the whole participation");
assert.equal(plan.round, 1);

// ---- 集計の部品 ----
assert.equal(pt.median([]), null);
assert.equal(pt.median([3, 1, 2]), 2);
assert.equal(pt.median([1, 2, 3, 4]), 2.5);
assert.equal(pt.median([null, 5, undefined]), 5);
assert.equal(pt.cliffsDelta([1, 2, 3], [1, 2, 3]), 0);
assert.equal(pt.cliffsDelta([4, 5], [1, 2]), 1);
assert.equal(pt.cliffsDelta([1], [2]), -1);
assert.equal(pt.cliffsDelta([1, 3], [2]), 0, "one above, one below");
assert.equal(pt.cliffsDelta([], [1]), null);
assert.equal(pt.cliffsDelta([1], []), null);

const row = (pid, round, kind, condition, extra = {}) => ({
  pid, round, kind, taskId: kind === "free" ? "free" : "pyro", condition,
  durationSec: 1800, queryCount: 0, cookErrorNodes: 2, reached: 1, selfMistakes: 2,
  difficulty: 3, clarity: 3, focus: 2, accuracyWorry: 2, sourceUseful: 4, reuse: 4, comment: "", ...extra,
});
const rows = [
  // 本システムの群（P01〜P03）: やさしく・わかりやすく・速い
  row(1, 1, "fixed", "system", { difficulty: 2, clarity: 4, durationSec: 1800, cookErrorNodes: 2, selfMistakes: 2 }),
  row(2, 1, "fixed", "system", { difficulty: 2, clarity: 5, durationSec: 1500 }),
  row(3, 2, "fixed", "system", { difficulty: 3, clarity: 4, durationSec: 2400 }),
  row(1, 1, "free", "system"),
  // 対照の群（P04〜P05）
  row(4, 1, "fixed", "docs_only", { difficulty: 4, clarity: 2, durationSec: 3600, cookErrorNodes: 6, selfMistakes: 4, reached: 0 }),
  row(5, 2, "fixed", "docs_only", { difficulty: 5, clarity: 2, durationSec: 4200, queryCount: 3, comment: "検索で迷った" }),
];
const sum = pt.summarizeTasks(rows);
assert.equal(sum.participants, 5);
assert.equal(sum.sessions, rows.length);
assert.equal(sum.paired, undefined, "no within-person pairs any more");
const byKey = Object.fromEntries(sum.compared.map((p) => [p.key, p]));
assert.equal(byKey.difficulty.nSystem, 3, "the free task is not part of the comparison");
assert.equal(byKey.difficulty.nDocs, 2);
assert.equal(byKey.difficulty.medianSystem, 2);
assert.equal(byKey.difficulty.medianDocs, 4.5);
assert.equal(byKey.difficulty.medianDiff, -2.5, "system − docs");
assert.equal(byKey.difficulty.cliffsDelta, -1, "every system value is below every control value");
assert.equal(byKey.clarity.cliffsDelta, 1);
assert.equal(byKey.reached.nDocs, 2);
assert.deepEqual(sum.contaminated, [5], "a control session with questions is flagged");
assert.deepEqual(sum.comments.map((c) => c.pid), [5]);
const g = sum.byGroup.find((x) => x.round === 1 && x.kind === "fixed" && x.condition === "system");
assert.equal(g.n, 2);
const noControl = pt.summarizeTasks([row(1, 1, "fixed", "system")]);
assert.ok(noControl.compared.every((p) => p.nDocs === 0 && p.medianDiff === null && p.cliffsDelta === null), "no comparison without a control group");

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

const u1 = mkUser("u1"), u2 = mkUser("u2"), u3 = mkUser("u3"), u4 = mkUser("u4"), u5 = mkUser("u5"), u6 = mkUser("u6"), admin = mkUser("boss", "admin");

// 登録前
assert.equal((await call(pt.handlePilotPlan, u1)).body.profile, false);
assert.equal((await call(pt.handlePilotSessionStart, u1, { kind: "fixed" })).status, 409, "must register first");

// 事前アンケート: 番号は登録順。再送しても変わらない。管理者は番号を取らない
let r = await call(pt.handlePilotProfile, u1, { experienceYears: 1.5, selfLevel: "初級", background: "CG専攻" });
assert.equal(r.body.pid, 1);
assert.equal(r.body.slot, 1);
assert.equal((await call(pt.handlePilotProfile, u2, {})).body.slot, 2);
assert.equal((await call(pt.handlePilotProfile, u3, {})).body.slot, 3);
assert.equal((await call(pt.handlePilotProfile, u4, {})).body.slot, 4);
assert.equal((await call(pt.handlePilotProfile, u1, { experienceYears: 2 })).body.pid, 1, "re-sending keeps the number");
assert.equal(db.prepare("SELECT experience_years AS y FROM pilot_profile WHERE user_id='u1'").get().y, 2, "answers are updated");
const adminPlan = await call(pt.handlePilotProfile, admin, {});
assert.equal(adminPlan.body.pid, null);
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM pilot_profile").get().n, 5);

// ---- 受け付ける回の切り替え（管理画面） ----
// 初期は、受付停止。始められない
let plan1 = await call(pt.handlePilotPlan, u1);
assert.equal(plan1.body.canStart, false);
assert.equal(plan1.body.round, null);
r = await call(pt.handlePilotSessionStart, u1, { kind: "fixed" });
assert.equal(r.status, 409);
assert.equal(r.body.code, "closed");
// 会員は、切り替えられない・状態も見られない
await assert.rejects(() => pt.handlePilotConfig(post({ openRound: 1 }), env, u1), "members cannot switch rounds");
// 状態を読む（何も変えない）
let cfg = await call(pt.handlePilotConfig, admin);
assert.equal(cfg.body.openRound, 0);
assert.equal(cfg.body.maxRound, 2);
assert.equal(cfg.body.rounds.length, 2);
assert.equal(cfg.body.registered, 4);
// 範囲外は拒否
assert.equal((await call(pt.handlePilotConfig, admin, { openRound: 3 })).status, 400);
assert.equal((await call(pt.handlePilotConfig, admin, { openRound: -1 })).status, 400);
assert.equal((await call(pt.handlePilotConfig, admin, { openRound: "x" })).status, 400);
assert.equal((await call(pt.handlePilotConfig, admin)).body.openRound, 0, "a rejected value changes nothing");
// 第1回を受け付ける + 回の表示
cfg = await call(pt.handlePilotConfig, admin, { openRound: 1, labels: { 1: "  11/16〜11/21 ", 2: "11/23〜11/28" } });
assert.equal(cfg.body.openRound, 1);
assert.deepEqual(cfg.body.rounds.map((x) => [x.round, x.label, x.open]), [[1, "11/16〜11/21", true], [2, "11/23〜11/28", false]]);
plan1 = await call(pt.handlePilotPlan, u1);
assert.equal(plan1.body.canStart, true);
assert.equal(plan1.body.round, 1);
assert.equal(plan1.body.roundLabel, "11/16〜11/21");
assert.equal(plan1.body.rounds, 2);

// ---- 課題（u4 = slot 4: Pyro・対照）。初めて始めた回に参加する ----
r = await call(pt.handlePilotSessionStart, u4, { kind: "fixed" });
assert.equal(r.status, 200);
assert.equal(r.body.taskId, "pyro");
assert.equal(r.body.condition, "docs_only");
assert.equal(r.body.round, 1);
const sid = r.body.sessionId;
assert.equal((await call(pt.handlePilotSessionStart, u4, { kind: "fixed" })).body.sessionId, sid, "a started task is resumed, not duplicated");
assert.equal((await call(pt.handlePilotSessionStart, u4, { kind: "bogus" })).status, 400);

// 対照の回に、質問が混ざった（本システムを使った）
const t0 = db.prepare("SELECT started_at AS t FROM pilot_sessions WHERE id=?").get(sid).t;
db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, created_at) VALUES ('u4','q','a','[]',?)").run(t0);
db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, created_at) VALUES ('u4','old','a','[]',?)").run(t0 - 100);
db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, created_at) VALUES ('u2','other','a','[]',?)").run(t0);

// 他人の課題は終えられない
assert.equal((await call(pt.handlePilotSessionEnd, u2, { sessionId: sid })).status, 404);
assert.equal((await call(pt.handlePilotSessionEnd, u4, { sessionId: "nope" })).status, 404);

// 終了: 範囲外の値は無効（null）。対照の回の「出典の有用性」は保存しない
r = await call(pt.handlePilotSessionEnd, u4, {
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
assert.equal(saved.source_useful, null, "no usefulness for the control group");
assert.equal(saved.reuse, 3);
assert.equal(saved.comment, "検索が大変");
assert.ok(saved.duration_sec >= 0 && saved.ended_at >= saved.started_at);
assert.equal((await call(pt.handlePilotSessionEnd, u4, { sessionId: sid })).status, 409, "cannot end twice");
assert.equal((await call(pt.handlePilotSessionStart, u4, { kind: "fixed" })).status, 409, "the fixed task is done");

// 自由課題 → 全部完了（1回で終わり）
r = await call(pt.handlePilotSessionStart, u4, { kind: "free" });
assert.equal(r.body.taskId, "free");
assert.equal(r.body.condition, "system");
r = await call(pt.handlePilotSessionEnd, u4, { sessionId: r.body.sessionId, reached: false, survey: { sourceUseful: 4 } });
assert.equal(r.body.finished, true, "one round is the whole participation");
assert.equal(r.body.round, 1);
assert.equal(db.prepare("SELECT source_useful AS s FROM pilot_sessions WHERE kind='free'").get().s, 4, "kept for the free task");
assert.equal((await call(pt.handlePilotSessionStart, u4, { kind: "free" })).status, 409, "nothing more to start");

// 管理者の集計: 氏名なし・管理者の記録は入らない・番号で出る
const as = await call(pt.handlePilotSessionStart, admin, { kind: "fixed" });
assert.equal(as.status, 200, "an admin can try the flow while a round is open");
await call(pt.handlePilotSessionEnd, admin, { sessionId: as.body.sessionId, survey: { difficulty: 1 } });
const tasks = await call(pt.handlePilotTasks, admin);
assert.equal(tasks.body.registered, 4);
assert.equal(tasks.body.sessions, 2);
assert.deepEqual(tasks.body.rows.map((x) => x.participant), ["P04", "P04"]);
assert.ok(!JSON.stringify(tasks.body).includes("u4"), "no user id or name in the aggregate");
assert.deepEqual(tasks.body.contaminated, [4], "the control session had a question");
assert.equal(tasks.body.rows[0].mistake, 0.43, "cook 4/10 × 0.7 = 0.28, self (3−1)/4 × 0.3 = 0.15");
await assert.rejects(() => pt.handlePilotTasks(post({}), env, u1), "members cannot read the aggregate");
cfg = await call(pt.handlePilotConfig, admin);
assert.deepEqual(cfg.body.rounds.map((x) => [x.round, x.joined, x.finished]), [[1, 1, 1], [2, 0, 0]], "the admin's own record is not counted");

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
r = await call(pt.handlePilotSessionStart, u3, { kind: "fixed" }); // slot 3: 固定課題は、雲（本システム）
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

// 終えた記録の取り消し: 参加は1回だけなので、いつでもできる
r = await call(pt.handlePilotSessionStart, u3, { kind: "free" });
plan3 = await call(pt.handlePilotSessionEnd, u3, { sessionId: r.body.sessionId, reached: true });
assert.equal(plan3.body.finished, true, "both done → finished");
assert.deepEqual(plan3.body.history.map((h) => [h.round, h.kind, h.redoable]), [[1, "fixed", true], [1, "free", true]]);
const freeId = plan3.body.history[1].sessionId;
plan3 = await call(pt.handlePilotSessionReset, u3, { sessionId: freeId }); // 間違えて終えた自由課題を、取り消す
assert.equal(plan3.body.finished, false);
assert.equal(plan3.body.free.done, false);
assert.equal(plan3.body.fixed.done, true, "the other task keeps its record");
r = await call(pt.handlePilotSessionStart, u3, { kind: "free" });
await call(pt.handlePilotSessionEnd, u3, { sessionId: r.body.sessionId, reached: true });

// 集計: 破棄した記録は入らず、やり直した回数だけ分かる
const after = await call(pt.handlePilotTasks, admin);
const p3 = after.body.rows.filter((x) => x.participant === "P03");
assert.equal(p3.length, 2, "only the kept records of P03");
assert.deepEqual(p3.map((x) => [x.kind, x.redoCount]), [["fixed", 1], ["free", 1]], "each of the redone tasks was redone once");
assert.equal(after.body.rows.filter((x) => x.participant === "P04").every((x) => x.redoCount === 0), true);

// ---- 回の切り替え: 第2回へ ----
// 第2回に切り替えると、新しい人は第2回に参加する。第1回に参加済みの人は、そのまま第1回
await call(pt.handlePilotProfile, u5, {});
await call(pt.handlePilotConfig, admin, { openRound: 2 });
r = await call(pt.handlePilotSessionStart, u5, { kind: "fixed" }); // slot 5: RBD・対照
assert.equal(r.status, 200);
assert.equal(r.body.round, 2, "a newcomer joins the round that is open");
assert.equal(r.body.taskId, "rbd");
assert.equal(r.body.condition, "docs_only");
const u5run = r.body.sessionId;
const plan2 = await call(pt.handlePilotPlan, u2);
assert.equal(plan2.body.round, 1, "u2 joined round 1 and stays there");
assert.equal(plan2.body.finished, true);

// 受付を止める: 新しい人は始められない。参加済みで途中の人は、続けて終えられる
await call(pt.handlePilotProfile, u6, {});
await call(pt.handlePilotConfig, admin, { openRound: 0 });
r = await call(pt.handlePilotSessionStart, u6, { kind: "fixed" });
assert.equal(r.status, 409);
assert.equal(r.body.code, "closed");
assert.equal((await call(pt.handlePilotPlan, u6)).body.canStart, false);
const u5plan = await call(pt.handlePilotPlan, u5);
assert.equal(u5plan.body.canStart, true, "u5 already joined: still allowed to finish");
r = await call(pt.handlePilotSessionStart, u5, { kind: "free" });
assert.equal(r.status, 200, "the second task of the joined round can be started after closing");
assert.equal(r.body.round, 2);
await call(pt.handlePilotSessionEnd, u5, { sessionId: u5run, reached: true });
await call(pt.handlePilotSessionEnd, u5, { sessionId: r.body.sessionId, reached: true });
cfg = await call(pt.handlePilotConfig, admin);
assert.deepEqual(cfg.body.rounds.map((x) => [x.round, x.joined, x.finished, x.open]), [[1, 3, 3, false], [2, 1, 1, false]]);
assert.equal(cfg.body.openRound, 0);
// 回の表示だけを変えても、受け付ける回は変わらない
cfg = await call(pt.handlePilotConfig, admin, { labels: { 2: "11/23〜11/28（変更）" } });
assert.equal(cfg.body.openRound, 0);
assert.equal(cfg.body.rounds[1].label, "11/23〜11/28（変更）");
assert.equal(cfg.body.rounds[0].label, "11/16〜11/21", "the other label is kept");

// 参加者の間の比較（実データ）: 本システムの群（P01なし・P02・P03）と、対照の群（P04・P05）
const final = await call(pt.handlePilotTasks, admin);
const diff = final.body.compared.find((x) => x.key === "durationMin");
assert.equal(diff.nDocs, 2);
assert.equal(diff.nSystem, 2);

// ---- 自由課題は任意: 固定課題だけで参加は完了。自由課題は、そのあとに（受付を止めたあとでも）始められる ----
const u7 = mkUser("u7");
await call(pt.handlePilotProfile, u7, {});
await call(pt.handlePilotConfig, admin, { openRound: 1 });
r = await call(pt.handlePilotSessionStart, u7, { kind: "fixed" });
assert.equal(r.status, 200);
let plan7 = await call(pt.handlePilotSessionEnd, u7, { sessionId: r.body.sessionId, reached: true, survey: { difficulty: 3 } });
assert.equal(plan7.body.completed, true, "participation is complete with the fixed task only");
assert.equal(plan7.body.finished, false, "but not everything is done");
assert.equal(plan7.body.free.optional, true);
cfg = await call(pt.handlePilotConfig, admin);
assert.deepEqual(cfg.body.rounds.map((x) => [x.round, x.joined, x.finished]), [[1, 4, 4], [2, 1, 1]], "complete = the fixed task is done, even without the free task");
await call(pt.handlePilotConfig, admin, { openRound: 0 });
r = await call(pt.handlePilotSessionStart, u7, { kind: "free" });
assert.equal(r.status, 200, "an optional free task can still be done after the round closes");
plan7 = await call(pt.handlePilotSessionEnd, u7, { sessionId: r.body.sessionId, reached: false });
assert.equal(plan7.body.finished, true);

// ---- 管理画面: 課題の集計の部品と、回の切り替えが入っていて、スクリプトが構文として読める ----
const vm = await import("node:vm");
const { chatUiHtml } = await import("../src/chatUi");
const html = chatUiHtml();
for (const id of ["pilotTaskNote", "pilotTasksCsv", "pilotTaskGroups", "pilotCompared", "pilotRoundOpen", "pilotRoundLabel1", "pilotRoundLabel2", "pilotRoundSave", "pilotRoundTable"]) {
  assert.ok(html.includes('id="' + id + '"'), id);
}
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).filter((c) => c.trim().length > 0);
for (const code of scripts) new vm.Script(code);
assert.ok(scripts.join("\n").includes('api("/admin/pilot/tasks"'));
assert.ok(scripts.join("\n").includes('api("/admin/pilot/config"'));

console.log("pilot_tasks tests passed");
