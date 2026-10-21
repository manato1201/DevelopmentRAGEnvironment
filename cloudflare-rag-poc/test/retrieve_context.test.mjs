// retrieve(): HyDE at temperature 0 + the raw question as a second query vector, context boost from the
// question or a caller hint, the ambiguity note, and determinism across repeated calls.
import assert from "node:assert/strict";

const H = await import("../src/houdiniContext");

const head = (ctx, name) => `${H.docHeader({ context: ctx, name }, "22")}\n`;
const meta = (ctx, name, i) => ({ file: `${name} [${ctx}]`, namespace: "shared:houdini22", scope: "shared", chunk_index: i, text: head(ctx, name) + `${ctx}の${name}の説明` });
const vop = { id: "v", metadata: meta("VOP", "transform", 0) };
const sop = { id: "s", metadata: meta("SOP", "transform", 0) };
const apex = { id: "a", metadata: meta("APEX", "transform", 0) };
const merge = { id: "m", metadata: meta("SOP", "merge", 0) };

// the HyDE text pulls toward VOP, the raw question pulls toward SOP (what an ambiguous question does)
const vectorCalls = [];
const env = {
  GEMINI_API_KEY: "g", EMBEDDING_MODEL: "gemini-embedding-001", GENERATION_MODEL: "gemini-flash-latest",
  DB: { prepare() { return { bind() { return this; }, async all() { return { results: [] }; }, async first() { return null; }, async run() { return { meta: { changes: 0 } }; } }; } },
  VEC_SHARED: {
    async query(vector, opts) {
      vectorCalls.push({ vector, opts });
      const hydeCall = vector[0] === 0.5;
      return { matches: (hydeCall ? [vop, sop, apex, merge] : [sop, vop, merge]).map((m) => ({ ...m })) };
    },
  },
  VEC_PERSONAL: { async query() { return { matches: [] }; } },
};
const generateBodies = [];
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.includes(":generateContent")) {
    generateBodies.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: "HYDE" }] } }], usageMetadata: { promptTokenCount: 10, candidatesTokenCount: 5 } }));
  }
  if (url.includes(":embedContent")) {
    const text = JSON.parse(init.body).content.parts[0].text;
    return new Response(JSON.stringify({ embedding: { values: new Array(768).fill(text === "HYDE" ? 0.5 : 0.25) } }));
  }
  throw new Error("unexpected fetch " + url);
};

const R = await import("../src/retrieve");
const user = { userId: "u", role: "viewer", allowedNamespaces: ["shared:houdini22"] };
const ids = (r) => r.ranked.map((c) => c.id);
const run = (q, hint = []) => R.retrieve(env, user, q, ["shared:houdini22"], "", 6, hint);

// 1) HyDE is deterministic (temperature 0) and told not to pick a context on its own
await run("Transformの使い方");
assert.equal(generateBodies[0].generationConfig.temperature, 0);
assert.match(generateBodies[0].contents[0].parts[0].text, /決めつけず/);

// 2) both the HyDE vector and the raw question vector are searched
assert.equal(vectorCalls.length, 2);
assert.deepEqual(new Set(vectorCalls.map((c) => c.vector[0])), new Set([0.5, 0.25]));

// 3) ambiguous question, no cue: every context stays, a note names the contexts and the default
let r = await run("Transformの使い方");
assert.deepEqual(new Set(ids(r)), new Set(["v", "s", "a", "m"]));
assert.match(r.contextNote, /transform/);
assert.match(r.contextNote, /SOP \/ VOP \/ APEX/);
assert.match(r.contextNote, /既定: SOP/);
const texts = R.buildContextTexts(r.ranked, r.contextNote).texts;
assert.ok(texts.some((t) => t.includes("注意（章の曖昧さ）")), "the note reaches the prompt text");

// 4) determinism: the same question gives the same ranking and the same note, every time
const first = await run("Transformの使い方");
for (let i = 0; i < 10; i++) {
  const again = await run("Transformの使い方");
  assert.deepEqual(ids(again), ids(first));
  assert.equal(again.contextNote, first.contextNote);
}

// 5) cue in the question: that context first, nothing dropped, no note
r = await run("APEXのTransformの使い方");
assert.equal(ids(r)[0], "a");
assert.equal(r.ranked.length, 4);
assert.equal(r.contextNote, "");
r = await run("VOPでTransformしたい");
assert.equal(ids(r)[0], "v");

// 6) hint from the caller (e.g. the Houdini panel knows the user is inside an APEX graph)
r = await run("Transformの使い方", ["APEX"]);
assert.equal(ids(r)[0], "a");
assert.equal(r.contextNote, "");

// 7) a wrong cue is not fatal: the other contexts are still there
r = await run("DOPでTransformしたい");  // no DOP page exists
assert.ok(ids(r).includes("s") && ids(r).includes("v"));

// 8) different nodes in one context are not "ambiguous"
vectorCalls.length = 0;
const solo = { ...env, VEC_SHARED: { async query() { return { matches: [{ ...sop }, { ...merge }] }; } } };
r = await R.retrieve(solo, user, "ノードの使い方", ["shared:houdini22"], "", 6, []);
assert.equal(r.contextNote, "");

console.log("retrieve_context tests passed");
