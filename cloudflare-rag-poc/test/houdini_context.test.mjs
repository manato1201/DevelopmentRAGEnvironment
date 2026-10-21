// houdiniContext: URL -> context, headers, file names, cues, boost, ambiguity note.
import assert from "node:assert/strict";

const H = await import("../src/houdiniContext");

// 1) URL -> context / node name
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/nodes/sop/transform.html"), { context: "SOP", name: "transform" });
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/nodes/vop/transform.html"), { context: "VOP", name: "transform" });
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/nodes/apex/transform.html"), { context: "APEX", name: "transform" });
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/nodes/cop2/blur.html"), { context: "COP2", name: "blur" });
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/nodes/cop/blur.html"), { context: "COP", name: "blur" });
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/nodes/out/fetch.html"), { context: "ROP", name: "fetch" });
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/nodes/sop/kinefx--rigpose.html"), { context: "SOP", name: "kinefx::rigpose" }, "namespaced type names");
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/vex/functions/noise.html"), { context: "VEX", name: "noise" });
assert.deepEqual(H.contextFromUrl("https://www.sidefx.com/docs/houdini/hom/hou/Node.html"), { context: "HOM", name: "Node" });
for (const u of [
  "https://www.sidefx.com/docs/houdini/nodes/sop/", // index page, no node
  "https://www.sidefx.com/docs/houdini/model/rivet.html", // guide
  "https://example.com/docs/houdini/nodes/sop/transform.html".replace("example.com", "example.com") + "x/y/z",
  "not a url",
  "https://www.sidefx.com/docs/houdini/nodes/unknowncat/foo.html",
]) {
  const r = H.contextFromUrl(u);
  if (u.endsWith("sop/")) assert.equal(r, null, u);
  if (u.includes("model/")) assert.equal(r, null, u);
  if (u === "not a url") assert.equal(r, null);
  if (u.includes("unknowncat")) assert.equal(r, null);
}

// 2) header + file name + prepareDocument
const sop = { context: "SOP", name: "transform" };
assert.equal(H.docHeader(sop, "22"), "【Houdini 22 / SOP / transform】");
assert.equal(H.docHeader(sop), "【Houdini / SOP / transform】");
assert.equal(H.versionFromNamespace("shared:houdini22"), "22");
assert.equal(H.versionFromNamespace("shared:research"), undefined);
assert.equal(H.fileNameFor("Transform geometry node", sop), "Transform geometry node [SOP]");
assert.equal(H.fileNameFor("Transform geometry node [SOP]", sop), "Transform geometry node [SOP]", "idempotent");
const doc = H.prepareDocument("https://www.sidefx.com/docs/houdini/nodes/vop/merge.html", "Merge", "本文です", "shared:houdini22");
assert.equal(doc.file, "Merge [VOP]");
assert.equal(doc.text, "【Houdini 22 / VOP / merge】\n本文です");
assert.deepEqual(H.parseHeader(doc.text), { context: "VOP", name: "merge", version: "22" });
assert.ok(H.hasHeader(doc.text));
assert.ok(!H.hasHeader("window.dataLayer = window.dataLayer || [];"), "legacy chunk (analytics boilerplate) has no header");
const other = H.prepareDocument("https://example.com/page", "Title", "text", "shared:houdini22");
assert.deepEqual([other.file, other.text, other.info], ["Title", "text", null], "other sites are untouched");
// re-preparing the same page gives the same result (no stacking)
assert.equal(H.prepareDocument("https://www.sidefx.com/docs/houdini/nodes/vop/merge.html", doc.file, "本文です", "shared:houdini22").file, "Merge [VOP]");

// 3) cues in questions
assert.deepEqual(H.detectContextCues("SOPでTransformしたい"), ["SOP"]);
assert.deepEqual(H.detectContextCues("sop の transform の使い方"), ["SOP"]);
assert.ok(H.detectContextCues("APEXのTransformとVOPのTransformの違い").includes("APEX"));
assert.ok(H.detectContextCues("APEXのTransformとVOPのTransformの違い").includes("VOP"));
assert.deepEqual(H.detectContextCues("Transformの使い方"), [], "no cue");
assert.deepEqual(H.detectContextCues("move it to the top of the list"), [], "lowercase 'top' is an English word");
assert.deepEqual(H.detectContextCues("TOPネットワークでPDGを使う"), ["TOP"]);
assert.deepEqual(H.detectContextCues("Solarisでマテリアルを割り当てる"), ["LOP"]);
assert.deepEqual(H.detectContextCues("Copernicusでノイズを作る"), ["COP"]);
assert.deepEqual(H.detectContextCues("stopped working"), [], "SOP inside a word must not match");
assert.deepEqual(H.detectContextCues("ECOPLUS"), []);
assert.deepEqual(H.normalizeContextHint("sop"), ["SOP"]);
assert.deepEqual(H.normalizeContextHint(["APEX", "bogus", "cop"]), ["APEX", "COP"]);
assert.deepEqual(H.normalizeContextHint("copernicus"), ["COP"]);
assert.deepEqual(H.normalizeContextHint(undefined), []);
assert.deepEqual(H.normalizeContextHint(42), []);

// 4) boost: reorder only, never drop
const chunk = (ctx, name, score) => ({ id: `${ctx}-${name}`, score, metadata: { text: H.docHeader({ context: ctx, name }, "22") + "\n説明" } });
const legacy = { id: "legacy", score: 0.020, metadata: { text: "window.dataLayer = ..." } };
const ranked = [chunk("VOP", "transform", 0.030), chunk("SOP", "transform", 0.025), legacy, chunk("APEX", "transform", 0.018)];
assert.deepEqual(H.boostByContext(ranked, []).map((c) => c.id), ranked.map((c) => c.id), "no context: unchanged");
const boosted = H.boostByContext(ranked, ["SOP"]);
assert.equal(boosted[0].id, "SOP-transform", "SOP chunk moves to the top");
assert.equal(boosted.length, ranked.length, "nothing is dropped");
assert.ok(boosted.some((c) => c.id === "VOP-transform"), "other contexts stay (a wrong cue is not fatal)");
assert.equal(H.boostByContext(ranked, ["SOP", "APEX"])[0].id, "SOP-transform");
const tie = [{ id: "a", score: 0.01, metadata: { text: "x" } }, { id: "b", score: 0.01, metadata: { text: "y" } }];
assert.deepEqual(H.boostByContext(tie, ["SOP"]).map((c) => c.id), ["a", "b"], "stable on ties");

// 5) ambiguity note
const amb = H.ambiguityNote(ranked, []);
assert.match(amb, /transform/);
assert.match(amb, /SOP \/ VOP \/ APEX/, "contexts listed in the fixed priority order");
assert.match(amb, /既定: SOP/);
assert.equal(H.ambiguityNote(ranked, ["VOP"]), "", "a cue in the question removes the note");
assert.equal(H.ambiguityNote([chunk("SOP", "merge", 1), chunk("SOP", "null", 1)], []), "", "different nodes in one context are not ambiguous");
assert.equal(H.ambiguityNote([legacy], []), "");
assert.equal(H.defaultContext(["APEX", "VOP"], []), "VOP");
assert.equal(H.defaultContext(["APEX", "VOP"], ["APEX"]), "APEX", "a hint from the caller wins");
// deterministic: same input, same note
assert.equal(H.ambiguityNote(ranked, []), H.ambiguityNote([...ranked].reverse(), []), "order of results does not change the note");

console.log("houdini_context tests passed");
