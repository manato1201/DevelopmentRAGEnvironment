// The admin UI is one big HTML string with an inline script: TypeScript cannot check that script, so a typo only
// shows up in the browser. Parse it (without running it) and check the knowledge-registration progress pieces.
import assert from "node:assert/strict";
import vm from "node:vm";

const { chatUiHtml } = await import("../src/chatUi");
const html = chatUiHtml();
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
  .map((m) => m[1])
  .filter((code) => code.trim().length > 0);
assert.ok(scripts.length >= 1, "an inline script exists");
for (const code of scripts) new vm.Script(code); // throws SyntaxError on a typo

const code = scripts.join("\n");
// the registration progress: per-item fraction, never going backwards, no fake 50%
assert.match(code, /S\.frac\[index\] = Math\.max\(S\.frac\[index\] \|\| 0/);
assert.match(
  code,
  /progress-bar" \+ \(indeterminate \? " indeterminate" : ""\)/,
);
assert.ok(
  !/finished \+ \(S\.status\.indexOf\("running"\) >= 0 \? 0\.5 : 0\)/.test(
    code,
  ),
  "the fake 50% for the running item is gone",
);
assert.match(code, /onFraction/);
assert.match(code, /runningFrac === undefined/);
assert.match(html, /\.progress-bar\.indeterminate/);
// 動きの追補（Y2）: Pulse（処理中）・Wiggle（エラー）・Push（タブ）。動きを減らす設定のときだけ動かす
const motion = html.match(
  /@media \(prefers-reduced-motion: no-preference\) \{[\s\S]*?[\n]  \}/,
);
assert.ok(
  motion,
  "the motion rules live inside prefers-reduced-motion: no-preference",
);
assert.match(motion[0], /\.msg\.skeleton i \{ animation: pulse-soft/);
assert.match(motion[0], /#status\.wiggle/);
assert.match(motion[0], /\.tabpanel\.push-next/);
assert.match(motion[0], /\.tabpanel\.push-prev/);
const outside = html.replace(motion[0], "");
for (const name of [
  "pulse-soft",
  "wiggle-soft",
  "push-in-next",
  "push-in-prev",
]) {
  assert.ok(
    !outside.includes("animation: " + name),
    name + " is only applied inside the reduced-motion guard",
  );
}
assert.match(code, /classList\.add\("wiggle"\)/);
assert.match(code, /nextIndex > previousIndex \? "push-next" : "push-prev"/);
console.log("ui_syntax tests passed");

// 段階①（2026-10-25）: どのユーザーで入っているかの表示と、折りたたみ
assert.match(html, /id="whoami"/);
assert.match(code, /function showWhoAmI\(/);
assert.match(code, /showWhoAmI\(data\);/);
assert.match(code, /if \(!unlocked\) showWhoAmI\(null\);/);
assert.match(code, /function enableFolding\(/);
assert.match(code, /ragPocFolded/);
assert.match(html, /\.section\.collapsed > \*:not\(\.card-head\):not\(h2\)/);

// 段階③（2026-10-27）: 説明のレベル（おまかせ＝成長）
assert.match(html, /id="explain"/);
assert.match(code, /explain: explainEl\.value \|\| undefined/);
assert.match(code, /ragPocExplain/);
assert.match(code, /data\.explain\.introduced/);
