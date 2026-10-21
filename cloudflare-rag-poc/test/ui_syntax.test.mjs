// The admin UI is one big HTML string with an inline script: TypeScript cannot check that script, so a typo only
// shows up in the browser. Parse it (without running it) and check the knowledge-registration progress pieces.
import assert from "node:assert/strict";
import vm from "node:vm";

const { chatUiHtml } = await import("../src/chatUi");
const html = chatUiHtml();
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).filter((code) => code.trim().length > 0);
assert.ok(scripts.length >= 1, "an inline script exists");
for (const code of scripts) new vm.Script(code); // throws SyntaxError on a typo

const code = scripts.join("\n");
// the registration progress: per-item fraction, never going backwards, no fake 50%
assert.match(code, /S\.frac\[index\] = Math\.max\(S\.frac\[index\] \|\| 0/);
assert.match(code, /progress-bar" \+ \(indeterminate \? " indeterminate" : ""\)/);
assert.ok(!/finished \+ \(S\.status\.indexOf\("running"\) >= 0 \? 0\.5 : 0\)/.test(code), "the fake 50% for the running item is gone");
assert.match(code, /onFraction/);
assert.match(code, /runningFrac === undefined/);
assert.match(html, /\.progress-bar\.indeterminate/);
console.log("ui_syntax tests passed");
