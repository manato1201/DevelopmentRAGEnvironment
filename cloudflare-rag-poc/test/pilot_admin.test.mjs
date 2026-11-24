// 実証実験の管理画面（2026-11-17、src/pilotTasks.ts・src/chatUi.ts）のテスト。
//   ・回答の一覧: 自由記述と、計測した値（開始・終了の時刻、所要、中断、質問数、cookエラー、自己申告、到達、アンケートの各項目）が、参加者ごと・課題ごとに出る
//   ・事前アンケート（自由記述を含む）も、管理者だけが見られる
//   ・条件の割り当ての切り替え（自動 / 全員ツール使用 / 全員ドキュメントのみ）。開始した課題は、そのまま続ける
//   ・比較は、条件が混ざらないとき「比較できない」
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const pt = await import("../src/pilotTasks");

// ---- 割り当て（純関数） ----
assert.deepEqual(pt.assignmentForSlot(4), { taskId: "pyro", condition: "docs_only" }, "auto: slot 4 is the control");
assert.deepEqual(pt.assignmentForSlot(4, "auto"), pt.assignmentForSlot(4));
assert.deepEqual(pt.assignmentForSlot(4, "system"), { taskId: "pyro", condition: "system" }, "all-system keeps the subject, changes only the condition");
assert.deepEqual(pt.assignmentForSlot(2, "docs_only"), { taskId: "rbd", condition: "docs_only" });
assert.deepEqual([1, 2, 3, 4, 5, 6].map((s) => pt.assignmentForSlot(s, "system").taskId), ["pyro", "rbd", "rbd", "pyro", "rbd", "rbd"], "no cloud any more");
assert.deepEqual(pt.assignmentForSlot(4, "bogus"), pt.assignmentForSlot(4), "an unknown mode falls back to auto");
assert.deepEqual(pt.CONDITION_MODES, ["auto", "system", "docs_only"]);

// buildPlan: 切り替えは、まだ始めていない固定課題にだけ効く。始めた課題は、そのまま
let plan = pt.buildPlan(4, [], 1, "system");
assert.equal(plan.fixed.condition, "system");
assert.equal(plan.free.condition, "system");
assert.equal(pt.buildPlan(1, [], 1, "docs_only").fixed.condition, "docs_only");
assert.equal(pt.buildPlan(4, [], 1).fixed.condition, "docs_only", "the default mode is auto");
const started = { round: 1, kind: "fixed", ended_at: null, id: "s1", task_id: "pyro", condition: "docs_only" };
assert.equal(pt.buildPlan(4, [started], 1, "system").fixed.condition, "docs_only", "a started task keeps its condition");
assert.equal(pt.buildPlan(1, [{ ...started, task_id: "pyro", condition: "system" }], 1, "docs_only").fixed.condition, "system");
assert.equal(pt.buildPlan(1, [{ ...started, ended_at: 5, task_id: "rbd", condition: "docs_only" }], 1, "system").fixed.taskId, "rbd", "a finished task keeps its subject too");
assert.equal(pt.buildPlan(1, [{ round: 1, kind: "free", ended_at: null, id: "f1", task_id: "free", condition: "system" }], 1, "docs_only").fixed.condition, "docs_only", "only the fixed task is tied to the mode");

// ---- 比較: 条件が混ざらないとき、「比較できない」 ----
const row = (pid, condition, extra = {}) => ({
  pid, round: 1, kind: "fixed", taskId: "pyro", condition, durationSec: 1800, queryCount: 0, cookErrorNodes: 2, reached: 1, selfMistakes: 2,
  difficulty: 3, clarity: 3, focus: 2, accuracyWorry: 2, sourceUseful: 4, reuse: 4, comment: "", ...extra,
});
let sum = pt.summarizeTasks([row(1, "system"), row(2, "system", { difficulty: 5 })]);
assert.equal(sum.comparison.comparable, false);
assert.equal(sum.comparison.nSystem, 2);
assert.equal(sum.comparison.nDocs, 0);
assert.match(sum.comparison.reason, /比較できません/);
assert.ok(sum.compared.every((m) => m.comparable === false && m.medianDiff === null && m.cliffsDelta === null), "no difference against an empty group");
sum = pt.summarizeTasks([row(1, "docs_only")]);
assert.equal(sum.comparison.comparable, false);
assert.equal(sum.comparison.nSystem, 0);
sum = pt.summarizeTasks([]);
assert.equal(sum.comparison.comparable, false);
sum = pt.summarizeTasks([row(1, "system"), row(2, "docs_only", { difficulty: 5 })]);
assert.equal(sum.comparison.comparable, true);
assert.equal(sum.comparison.reason, "");
assert.ok(sum.compared.find((m) => m.key === "difficulty").comparable);
assert.equal(sum.compared.find((m) => m.key === "difficulty").medianDiff, -2);
// 自由課題だけが混ざっても、比較には入らない
sum = pt.summarizeTasks([row(1, "system"), { ...row(2, "docs_only"), kind: "free" }]);
assert.equal(sum.comparison.comparable, false, "the free task is not part of the comparison");
// 指標ごと: 片方に値が無ければ、その指標は比較できない
sum = pt.summarizeTasks([row(1, "system"), row(2, "docs_only", { difficulty: null })]);
assert.equal(sum.compared.find((m) => m.key === "difficulty").comparable, false);
assert.equal(sum.compared.find((m) => m.key === "difficulty").medianDiff, null);
assert.equal(sum.compared.find((m) => m.key === "clarity").comparable, true);

// ---- ハンドラ ----
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
const mkUser = (id, role = "member") => { db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES (?,?,?,1)").run(id, "名前-" + id, role); return { userId: id, role }; };
const post = (body) => new Request("https://x/", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const call = async (handler, user, body = {}) => { const res = await handler(post(body), env, user); return { status: res.status, body: await res.json() }; };

const users = Array.from({ length: 8 }, (_, i) => mkUser("u" + (i + 1)));
const admin = mkUser("boss", "admin");
for (const u of users) await call(pt.handlePilotProfile, u, { experienceYears: 1, selfLevel: "初級", background: "背景-" + u.userId, practice: "練習-" + u.userId, toolHistory: "道具-" + u.userId });
await call(pt.handlePilotConfig, admin, { openRound: 1 });

// 既定は、自動（変えない）
let cfg = await call(pt.handlePilotConfig, admin);
assert.equal(cfg.body.conditionMode, "auto");
assert.equal((await call(pt.handlePilotPlan, users[3])).body.fixed.condition, "docs_only", "auto: slot 4 is the control");
// 会員は、切り替えられない
await assert.rejects(() => pt.handlePilotConfig(post({ conditionMode: "system" }), env, users[0]), "members cannot switch the mode");
assert.equal((await call(pt.handlePilotConfig, admin)).body.conditionMode, "auto");
// 不正な値は、拒否して、何も変えない
assert.equal((await call(pt.handlePilotConfig, admin, { conditionMode: "both" })).status, 400);
assert.equal((await call(pt.handlePilotConfig, admin, { conditionMode: 1 })).status, 400);
assert.equal((await call(pt.handlePilotConfig, admin)).body.conditionMode, "auto");
// 検査は、保存より先: 片方が不正なら、もう片方も保存しない（openRound だけ変わる、という中途半端な状態を作らない）
assert.equal((await call(pt.handlePilotConfig, admin, { openRound: 2, conditionMode: "both" })).status, 400);
assert.equal((await call(pt.handlePilotConfig, admin)).body.openRound, 1, "a rejected request changes nothing");
assert.equal((await call(pt.handlePilotConfig, admin, { openRound: 9, conditionMode: "system" })).status, 400);
assert.equal((await call(pt.handlePilotConfig, admin)).body.conditionMode, "auto");

// u4（slot 4、自動ならドキュメントのみ）が、自動のうちに始める → あとで切り替えても、その課題は変わらない
let r = await call(pt.handlePilotSessionStart, users[3], { kind: "fixed" });
assert.equal(r.body.condition, "docs_only");
const sid4 = r.body.sessionId;
// 全員ツール使用に切り替える
cfg = await call(pt.handlePilotConfig, admin, { conditionMode: "system" });
assert.equal(cfg.body.conditionMode, "system");
assert.equal(cfg.body.openRound, 1, "switching the mode keeps the open round");
assert.equal(db.prepare("SELECT value FROM pilot_config WHERE key='condition_mode'").get().value, "system");
assert.equal((await call(pt.handlePilotPlan, users[4])).body.fixed.condition, "system", "u5 (slot 5) is no longer the control");
assert.equal((await call(pt.handlePilotPlan, users[4])).body.fixed.taskId, "rbd", "the subject still follows the number");
assert.equal((await call(pt.handlePilotPlan, users[3])).body.fixed.condition, "docs_only", "u4 already started: unchanged");
r = await call(pt.handlePilotSessionStart, users[3], { kind: "fixed" });
assert.equal(r.body.resumed, true);
assert.equal(r.body.sessionId, sid4);
assert.equal(r.body.condition, "docs_only", "the resumed task keeps its condition");
r = await call(pt.handlePilotSessionStart, users[4], { kind: "fixed" });
assert.equal(r.body.condition, "system", "u5 starts under the new mode");
assert.equal(db.prepare("SELECT condition FROM pilot_sessions WHERE user_id='u5'").get().condition, "system", "the stored condition is the one actually used");
const sid5 = r.body.sessionId;
// 全員ドキュメントのみ。自由課題は、いつも本システム
await call(pt.handlePilotConfig, admin, { conditionMode: "docs_only" });
r = await call(pt.handlePilotSessionStart, users[0], { kind: "fixed" }); // slot 1（自動なら本システム）
assert.equal(r.body.condition, "docs_only");
const sid1 = r.body.sessionId;
assert.equal((await call(pt.handlePilotPlan, users[0])).body.free.condition, "system", "the free task always uses the system");
r = await call(pt.handlePilotSessionStart, users[0], { kind: "free" });
assert.equal(r.status, 409, "the free task cannot be started before the required fixed task is done (2026-11-24)");
assert.equal(r.body.code, "fixed_first");
// 終えた課題も、そのまま（中断が所要時間を超えないよう、開始を 1 時間前にしておく）
db.prepare("UPDATE pilot_sessions SET started_at = ? WHERE id = ?").run(Math.floor(Date.now() / 1000) - 3600, sid5);
await call(pt.handlePilotSessionEnd, users[4], {
  sessionId: sid5, reached: true, cookErrorNodes: 3, selfMistakes: 2, pausedSec: 120, surveySec: 60,
  survey: { difficulty: 2, clarity: 4, focus: 1, accuracyWorry: 2, sourceUseful: 5, reuse: 5 }, comment: "良かった。<img src=x onerror=alert(1)>",
});
assert.equal((await call(pt.handlePilotPlan, users[4])).body.fixed.condition, "system", "a finished task keeps its condition");
// 自動に戻す
cfg = await call(pt.handlePilotConfig, admin, { conditionMode: "auto" });
assert.equal(cfg.body.conditionMode, "auto");
assert.equal((await call(pt.handlePilotPlan, users[5])).body.fixed.condition, "docs_only", "back to the number-based rule");
assert.equal((await call(pt.handlePilotPlan, users[0])).body.fixed.condition, "docs_only", "u1 started under docs_only: stays");
// 管理画面の状態: 条件ごとの開始済みの人数
assert.deepEqual(cfg.body.conditionCounts, { system: 1, docs_only: 2 }, "fixed tasks started so far (u4, u1 = docs_only, u5 = system)");

// やり直し（破棄）したあとは、その時点のモードで割り当て直す（破棄した記録は、集計に入らない）
await call(pt.handlePilotConfig, admin, { conditionMode: "system" });
await call(pt.handlePilotSessionReset, users[3], { sessionId: sid4 });
assert.equal((await call(pt.handlePilotPlan, users[3])).body.fixed.condition, "system", "a discarded record no longer ties the condition");

// ---- 管理画面の「回答の一覧」の元データ ----
// u1 は、まだ終えていない。u5 は、終えた。u2 に、自由記述なし・値の一部が空の記録を足す
r = await call(pt.handlePilotSessionStart, users[1], { kind: "fixed" });
const t2 = Math.floor(Date.now() / 1000) - 1800;
db.prepare("UPDATE pilot_sessions SET started_at = ? WHERE id = ?").run(t2, r.body.sessionId);
await call(pt.handlePilotSessionEnd, users[1], { sessionId: r.body.sessionId, reached: false, survey: { difficulty: 5 }, pausedSec: 300 });
const tasks = await call(pt.handlePilotTasks, admin);
assert.equal(tasks.status, 200);
assert.equal(tasks.body.conditionMode, "system");
const p5 = tasks.body.rows.find((x) => x.participant === "P05");
assert.equal(p5.comment, "良かった。<img src=x onerror=alert(1)>", "the free comment is returned as-is (escaped when rendered)");
assert.equal(p5.pausedSec, 120);
assert.equal(p5.condition, "system");
assert.equal(p5.cookErrorNodes, 3);
assert.equal(p5.selfMistakes, 2);
assert.equal(p5.reached, 1);
assert.equal(p5.difficulty, 2);
assert.equal(p5.reuse, 5);
assert.ok(Number.isInteger(p5.startedAt) && Number.isInteger(p5.endedAt) && p5.endedAt >= p5.startedAt, "start and end times are returned");
assert.equal(p5.pausedMin, 2);
const p2 = tasks.body.rows.find((x) => x.participant === "P02");
assert.equal(p2.pausedSec, 300);
assert.equal(p2.startedAt, t2);
assert.equal(p2.comment, "");
assert.equal(p2.reached, 0);
assert.equal(p2.focus, null);
assert.ok(!tasks.body.rows.some((x) => x.participant === "P01"), "unfinished tasks are not listed");
// 事前アンケート: 番号で出す。氏名・ユーザーIDは出さない
assert.equal(tasks.body.profiles.length, 8);
const pf = tasks.body.profiles.find((x) => x.participant === "P05");
assert.equal(pf.background, "背景-u5");
assert.equal(pf.practice, "練習-u5");
assert.equal(pf.toolHistory, "道具-u5");
assert.equal(pf.selfLevel, "初級");
assert.equal(pf.experienceYears, 1);
assert.ok(!JSON.stringify(tasks.body).includes("名前-"), "no display name");
assert.ok(!/"u\d"/.test(JSON.stringify(tasks.body)), "no user id");
assert.ok(!JSON.stringify(tasks.body).includes("boss"), "the admin's own profile is not listed");
await assert.rejects(() => pt.handlePilotTasks(post({}), env, users[4]), "members cannot read the answers");
// 条件が混ざらない（ここでは、開始済みの終えた記録: P05 = 本システム、P02 = 本システム）→ 比較できない
assert.equal(tasks.body.comparison.comparable, false);
assert.equal(tasks.body.comparison.nDocs, 0);
assert.ok(tasks.body.compared.every((m) => m.medianDiff === null));

// ---- 管理画面（HTML とスクリプト） ----
const vm = await import("node:vm");
const { chatUiHtml } = await import("../src/chatUi");
const html = chatUiHtml();
for (const id of ["pilotAnswers", "pilotAnswersCsv", "pilotProfiles", "pilotProfilesCsv", "pilotConditionMode", "pilotConditionSave", "pilotConditionNote", "pilotCompareNote"]) {
  assert.ok(html.includes('id="' + id + '"'), id);
}
for (const label of ["全員ツール使用", "全員ドキュメントのみ", "自動"]) assert.ok(html.includes(label), label);
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).filter((c) => c.trim().length > 0);
for (const code of scripts) new vm.Script(code);
const js = scripts.join("\n");
assert.ok(js.includes("conditionMode"), "the page sends and reads the mode");
assert.ok(js.includes("比較できない"), "the page says when a comparison is impossible");
// 自由記述は、textContent で入れる（HTML として解釈しない）。回答の一覧を作る関数に、innerHTML への連結が無いこと
const start = js.indexOf("async function loadPilotTasks");
const end = js.indexOf('$("pilotRefresh")');
assert.ok(start > 0 && end > start);
const section = js.slice(start, end);
assert.ok(!/innerHTML\s*\+?=\s*[^"'<\s]/.test(section.replace(/tbody\.innerHTML = "";/g, "").replace(/tbody\.innerHTML = "<tr><td colspan=" \+ columns \+ ">[^"]*<\/td><\/tr>";/g, "")), "no dynamic innerHTML in the pilot task section");

// ---- CSV の式注入の対策（全列）: 画面のスクリプトから、関数を取り出して試す ----
const csvStart = js.indexOf("function pilotCsvText");
const csvSrc = js.slice(csvStart, js.indexOf("async function loadPilotTasks"));
const csv = vm.runInNewContext(csvSrc + "; ({ pilotCsvText, pilotCsvRow })");
for (const bad of ["=1+1", "+1", "-1+2", "@SUM(A1)", "\t=1", "\r=1", " =1+1", "\n=cmd", "\u3000=1", " \t@x"]) {
  assert.equal(csv.pilotCsvText(bad), "'" + bad, JSON.stringify(bad) + " is neutralized");
}
for (const ok of ["", "普通の文", "a=b", "1+1", "x-y", "  文", "3.5"]) assert.equal(csv.pilotCsvText(ok), ok, JSON.stringify(ok) + " stays");
assert.equal(csv.pilotCsvText(-1), -1, "numbers are left alone");
assert.equal(csv.pilotCsvText(null), null);
assert.deepEqual(csv.pilotCsvRow(["P01", 1, "=HYPERLINK(1)", 2.5, ""]), ["P01", 1, "'=HYPERLINK(1)", 2.5, ""], "every column goes through it");
// 両方の CSV が、行の全体に対策をかけている
assert.equal((js.match(/pilotCsvRow\(\[/g) || []).length, 3, "all three pilot CSVs (tasks, learning, profiles) wrap their rows");

// 受け付ける回の選択は、自動更新で、サーバーの値（受付停止）に戻されない（2026-11-24。選んで「保存」を押す前に更新が入ると、受付停止のまま保存されていた）
{
  const fn = js.slice(js.indexOf("async function loadPilotRounds(update)"), js.indexOf('$("pilotRoundSave").addEventListener'));
  assert.match(js, /const pilotDirty = \{ rounds: false, mode: false \}/, "dirty flags exist before loadPilotRounds");
  assert.match(fn, /const keepRounds = pilotDirty\.rounds && !update;/, "a refresh without an update keeps what the admin picked");
  assert.match(fn, /select\.value = keepRounds \? chosen : String\(data\.openRound\)/, "the picked round is restored after the options are rebuilt");
  assert.match(fn, /if \(update\) pilotDirty\.rounds = false/, "a save clears the dirty flag");
  assert.match(js, /\$\("pilotRoundOpen"\)\.addEventListener\("change", \(\) => \{ pilotDirty\.rounds = true; \}\)/, "choosing a round marks it dirty");
  assert.match(js, /\$\("pilotRoundNow"\)/, "the server's current round is always shown");
  assert.match(js, /保存できませんでした（サーバーの値は/, "a save that did not take is reported, not called a success");
}

console.log("pilot_admin tests passed");
