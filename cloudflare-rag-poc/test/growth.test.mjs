// 説明のレベルと成長機能（2026-10-27、src/growth.ts・src/glossary.ts）のテスト。
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
db.prepare("INSERT INTO users (user_id, display_name, role, created_at) VALUES ('u1','a','member',1),('u2','b','member',1)").run();

const gl = await import("../src/glossary");
const gr = await import("../src/growth");
const { buildAnswerPrompt } = await import("../src/embeddings");

// ---- 辞書: 用語を見つける。一般の語には反応しない
const names = (text) => gl.findTerms(text).map((t) => t.term);
assert.deepEqual(names("SOPでアトリビュートをVEXで書き換えたい").sort(), ["SOP", "VEX", "アトリビュート"].sort());
assert.deepEqual(names("Attribute Wrangle の使い方"), ["Attribute Wrangle"]);
assert.ok(names("パーティクルをDOPで動かす").includes("POP"), "alias (パーティクル) maps to POP");
assert.ok(names("PDG と TOPネットワーク").includes("PDG"));
assert.deepEqual(names("Go to the top of the page and each item"), [], "top / each are not Houdini terms");
assert.deepEqual(names("vexation, sopranos"), [], "ASCII aliases need word boundaries");
assert.deepEqual(names(""), []);
assert.equal(new Set(names("SOP SOP sop")).size, 1, "no duplicates");

// ---- 点数としきい値: 同じ用語は3回まで数える
const row = (term, count) => ({ term, count });
assert.equal(gr.scoreOf([row("SOP", 1)]), 0.3);   // basic 1点 × 1/3
assert.equal(gr.scoreOf([row("SOP", 9)]), 1);     // 3回で頭打ち
assert.equal(gr.scoreOf([row("VEX", 3)]), 2);     // applied 2点
assert.equal(gr.scoreOf([row("PDG", 3)]), 3);     // advanced 3点
assert.equal(gr.scoreOf([row("存在しない用語", 5)]), 0, "unknown terms are ignored");
assert.equal(gr.levelForScore(0), "basic");
assert.equal(gr.levelForScore(gr.THRESHOLD_APPLIED - 0.1), "basic");
assert.equal(gr.levelForScore(gr.THRESHOLD_APPLIED), "applied");
assert.equal(gr.levelForScore(gr.THRESHOLD_ADVANCED), "advanced");

// ---- 記録: 回数を数える。質問の全文は保存しない
const secretQuery = "社外秘の案件名ABC123についてSOPとVEXの違いを教えて";
const found = await gr.recordQueryTerms(env, "u1", secretQuery);
assert.deepEqual(found.sort(), ["SOP", "VEX"]);
await gr.recordQueryTerms(env, "u1", "SOPのノードを増やしたい");
const rows = db.prepare("SELECT term, count FROM user_terms WHERE user_id = 'u1' ORDER BY term").all();
assert.deepEqual(rows.map((r) => [r.term, r.count]), [["SOP", 2], ["VEX", 1], ["ノード", 1]]);
const dump = JSON.stringify(db.prepare("SELECT * FROM user_terms").all());
assert.ok(!dump.includes("ABC123") && !dump.includes("社外秘"), "the query text is never stored");
assert.deepEqual(db.prepare("PRAGMA table_info(user_terms)").all().map((c) => c.name), ["user_id", "term", "count", "first_seen", "last_seen"]);
assert.equal((await gr.recordQueryTerms(env, "u1", "雑談だけです")).length, 0);

// ---- 成長: 用語が増えると、おまかせのレベルが上がる
let profile = await gr.loadGrowth(env, "u1");
assert.equal(profile.level, "basic");
assert.deepEqual(profile.knownTerms.map((k) => k.term), ["SOP"], "terms used twice or more are 'known'");
assert.equal(profile.nextAt, gr.THRESHOLD_APPLIED);
for (const term of ["VEX", "アトリビュート", "ソルバー", "DOP", "VOP", "HDA", "ForEach", "Pyro"]) {
  for (let i = 0; i < 3; i++) await gr.recordQueryTerms(env, "u1", term + "について");
}
profile = await gr.loadGrowth(env, "u1");
assert.ok(profile.score >= gr.THRESHOLD_APPLIED, "score " + profile.score);
assert.equal(profile.level, "applied");
assert.equal(profile.nextAt, gr.THRESHOLD_ADVANCED);
// 別の利用者の記録とは、混ざらない
assert.equal((await gr.loadGrowth(env, "u2")).termCount, 0);

// ---- 「役に立たなかった」が3件続くと、一段やさしくする
const insertMemory = (user, rating, at) => db.prepare("INSERT INTO memory (user_id, query, answer, sources_json, rating, created_at) VALUES (?, 'q', 'a', '[]', ?, ?)").run(user, rating, at);
insertMemory("u1", -1, 10); insertMemory("u1", -1, 11); insertMemory("u1", 1, 12);
assert.equal((await gr.loadGrowth(env, "u1")).lowered, false, "a recent good rating breaks the streak");
insertMemory("u1", -1, 13); insertMemory("u1", -1, 14); insertMemory("u1", -1, 15);
profile = await gr.loadGrowth(env, "u1");
assert.equal(profile.lowered, true);
assert.equal(profile.scoreLevel, "applied");
assert.equal(profile.level, "basic", "one level easier");
insertMemory("u2", -1, 1); insertMemory("u2", -1, 2); insertMemory("u2", -1, 3);
assert.equal((await gr.loadGrowth(env, "u2")).level, "basic", "basic cannot go lower");

// ---- 説明の指示（プロンプトに足す文）
let plan = gr.buildExplainPlan("basic", null, ["SOPの説明"]);
assert.equal(plan.mode, "fixed");
assert.equal(plan.level, "basic");
assert.ok(plan.note.includes(gr.EXPLAIN_STYLE.basic));
assert.deepEqual(plan.candidates, [], "fixed levels do not introduce new terms");
assert.ok(!plan.note.includes("使いこなしている"));
plan = gr.buildExplainPlan("advanced", null, []);
assert.ok(plan.note.includes("基本の説明は省いて"));
assert.notEqual(gr.EXPLAIN_STYLE.basic, gr.EXPLAIN_STYLE.applied);
assert.notEqual(gr.EXPLAIN_STYLE.applied, gr.EXPLAIN_STYLE.advanced);

// おまかせ: 使いこなしている用語は省く。次の段階の用語は、検索結果に出てくるものから、1〜2個
const rising = { level: "applied", scoreLevel: "applied", score: 8, nextAt: 18, termCount: 5, lowered: false,
  knownTerms: [{ term: "VEX", level: "applied", count: 3 }, { term: "SOP", level: "basic", count: 4 }] };
const context = ["[1] VEX と SOP の説明。PDG はワークアイテムを扱う。Pyro と FLIP と USD も出てくる。"];
plan = gr.buildExplainPlan("auto", rising, context);
assert.equal(plan.mode, "auto");
assert.equal(plan.level, "applied");
assert.ok(plan.note.includes("使いこなしている用語（説明は省いてよい）: VEX、SOP"));
assert.ok(plan.candidates.length >= 1 && plan.candidates.length <= 2);
assert.ok(!plan.candidates.includes("VEX") && !plan.candidates.includes("SOP"), "known terms are not introduced");
assert.ok(plan.candidates.every((c) => ["PDG", "ワークアイテム", "USD", "Pyro", "FLIP"].includes(c)), "only terms present in the retrieved context: " + plan.candidates);
assert.ok(plan.note.includes("検索結果に書かれている範囲で"));
// 上限: applied の人に、advanced の用語を2つ以上先取りさせない（1つ上まで）。basic の人に advanced は出さない
const novice = { ...rising, level: "basic", scoreLevel: "basic", score: 1, knownTerms: [] };
plan = gr.buildExplainPlan("auto", novice, context);
assert.ok(plan.candidates.every((c) => gl.termByName(c).level !== "advanced"), "a beginner is not shown advanced terms: " + plan.candidates);
// 検索結果に用語が無ければ、紹介しない（辞書から勝手に持ち出さない）
assert.deepEqual(gr.buildExplainPlan("auto", rising, ["用語を含まない文章"]).candidates, []);
// 習熟度が読めないとき（null）は、basic として扱う
assert.equal(gr.buildExplainPlan("auto", null, []).level, "basic");

// 回答に実際に出た用語だけを「紹介した」とする
assert.deepEqual(gr.introducedIn("PDG（依存関係のグラフ）は…", ["PDG", "USD"]), ["PDG"]);
assert.deepEqual(gr.introducedIn("何も出ない", ["PDG"]), []);
assert.deepEqual(gr.introducedIn("PDG", []), []);

// ---- 入力の確認
assert.equal(gr.parseExplain("auto"), "auto");
assert.equal(gr.parseExplain("advanced"), "advanced");
assert.equal(gr.parseExplain(""), null);
assert.equal(gr.parseExplain("expert"), null);
assert.equal(gr.parseExplain(undefined), null);

// ---- プロンプト: 指示が入る。explain なしは、これまでと同じ
const history = [];
const without = buildAnswerPrompt("質問です", ["[1] 本文"], history);
assert.ok(without.endsWith("[1] 本文\n\n質問: 質問です"), "unchanged layout without explain");
assert.ok(!without.includes("説明のレベル"));
const withNote = buildAnswerPrompt("質問です", ["[1] 本文"], history, false, plan.note);
assert.ok(withNote.includes("【説明のレベル:"));
assert.ok(withNote.indexOf("【説明のレベル:") < withNote.indexOf("[1] 本文"), "the instruction comes before the sources");
const withTools = buildAnswerPrompt("質問です", ["[1] 本文"], history, true, plan.note);
assert.ok(withTools.includes("【説明のレベル:"));

// ---- 本人の習熟度・記録の削除（本人だけ）
const user = { userId: "u1", role: "member", allowedNamespaces: [] };
const body = await (await gr.handleMyGrowth(new Request("https://x/me/growth", { method: "POST" }), env, user)).json();
assert.equal(body.status, "ok");
assert.ok(body.thresholds.applied === gr.THRESHOLD_APPLIED && Array.isArray(body.knownTerms));
const reset = await (await gr.handleMyGrowthReset(new Request("https://x/me/growth/reset", { method: "POST" }), env, user)).json();
assert.ok(reset.deleted >= 1);
assert.equal(db.prepare("SELECT COUNT(*) AS c FROM user_terms WHERE user_id = 'u1'").get().c, 0);
assert.ok(db.prepare("SELECT COUNT(*) AS c FROM user_terms").get().c >= 0);
console.log("growth tests passed");
