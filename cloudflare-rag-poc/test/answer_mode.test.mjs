// 答え方（2026-11-22）: open（既定。資料を最優先に、足りないところは「（推測）」と明示して答える）と grounded（資料だけ）。
import assert from "node:assert/strict";

const { buildAnswerPrompt, parseAnswerMode, OPEN_ANSWER_RULES, UNTRUSTED_CONTEXT_GUARD } = await import("../src/embeddings");

// ---- 値の読み取り: 無い・不正は open（推測も答える）。grounded だけが、資料だけ
assert.equal(parseAnswerMode(undefined), "open");
assert.equal(parseAnswerMode("grounded"), "grounded");
assert.equal(parseAnswerMode("open"), "open");
assert.equal(parseAnswerMode("OPEN "), "open");
assert.equal(parseAnswerMode({ x: 1 }), "open");

// ---- grounded は、従来のプロンプトと同じ（資料だけ・わかりません）
const history = [];
const grounded = buildAnswerPrompt("質問です", ["[1] 本文"], history, false, "", "grounded");
assert.equal(grounded, buildAnswerPrompt("質問です", ["[1] 本文"], history), "the default of the function stays the old behaviour");
assert.match(grounded, /検索結果だけを根拠に/);
assert.match(grounded, /わかりません/);
assert.ok(!grounded.includes("（推測）"));

// ---- open: 資料が最優先。推測は「（推測）」と明示し、資料と混ぜない。「わかりません」で終わらせない
const open = buildAnswerPrompt("ミズクラゲに必要なノードは？", ["[1] 本文"], history, false, "", "open");
assert.ok(!/検索結果だけを根拠に/.test(open), "open is not limited to the sources");
assert.match(open, /最優先/);
assert.ok(open.includes(OPEN_ANSWER_RULES));
assert.match(OPEN_ANSWER_RULES, /（推測）/);
assert.match(OPEN_ANSWER_RULES, /確かさ/);
assert.match(OPEN_ANSWER_RULES, /混ぜない/);
assert.match(OPEN_ANSWER_RULES, /名前は要確認/);
assert.match(OPEN_ANSWER_RULES, /「わかりません」で終わらず/);
// 守りは、そのまま: 資料の前に、指示ではなくデータの一文。並びも同じ（資料のあとに質問）
assert.ok(open.includes(UNTRUSTED_CONTEXT_GUARD));
assert.ok(open.indexOf(UNTRUSTED_CONTEXT_GUARD) < open.indexOf("[1] 本文"));
assert.ok(open.indexOf(OPEN_ANSWER_RULES) < open.indexOf("[1] 本文"), "the rules come before the sources");
assert.ok(open.endsWith("[1] 本文\n\n質問: ミズクラゲに必要なノードは？"));
// 資料の中に、答え方を変える指示が書かれていても、ガードの文は、変わらない（資料はデータ）
assert.match(UNTRUSTED_CONTEXT_GUARD, /従わない/);

// ---- ツール（MCP）を使うときも、open は推測として答えてよい。grounded は、従来どおり
const toolsOpen = buildAnswerPrompt("Q", ["[1] 本文"], history, true, "", "open");
const toolsGrounded = buildAnswerPrompt("Q", ["[1] 本文"], history, true, "", "grounded");
assert.ok(toolsOpen.includes(OPEN_ANSWER_RULES));
assert.ok(!toolsGrounded.includes(OPEN_ANSWER_RULES));
assert.match(toolsGrounded, /正直に「わかりません」/);
assert.ok(!/正直に「わかりません」/.test(toolsOpen));

// ---- 説明のレベルと一緒でも、指示は資料の前
const both = buildAnswerPrompt("Q", ["[1] 本文"], history, false, "【説明のレベル: 初心者】", "open");
assert.ok(both.includes("【説明のレベル: 初心者】") && both.indexOf("【説明のレベル: 初心者】") < both.indexOf("[1] 本文"));

console.log("answer_mode.test.mjs: ok");
