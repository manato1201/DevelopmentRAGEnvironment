// 画面(chatUi)の色トークンのコントラスト(WCAG 2.x AA)。画面の文字は認証後に JS が描くため、実ページではなくトークンの全組み合わせで保証する。
//  - 文字に使う色は、地・パネル・吹き出しのどの上でも 4.5:1 以上(ライト・ダークの両方)
//  - 塗りの上の文字(白 / --on-bad)も 4.5:1 以上
// 色を変えるときは、ここが落ちる。DESIGN.md「色」も直す。
import assert from "node:assert/strict";

const { chatUiHtml } = await import("../src/chatUi");
const css = chatUiHtml().match(/<style>([\s\S]*?)<\/style>/)[1];

function tokens(block) {
  const out = {};
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b/g)) out[m[1]] = m[2];
  return out;
}
function between(startMarker, fromIndex = 0) {
  const start = css.indexOf(startMarker, fromIndex);
  assert.ok(start >= 0, `${startMarker} がある`);
  return css.slice(start, css.indexOf("}", start));
}
const dark = tokens(between(":root {\n    color-scheme: dark;"));
const lightManual = tokens(between(':root[data-theme="light"] {'));
const lightAuto = tokens(between(":root:not([data-theme]) {"));

const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const f = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};

const TEXT = ["text", "muted", "muted2", "accent-text", "highlight", "teal-text", "bad"];
const GROUNDS = ["bg", "panel", "user-bubble"];
const FILLS = [["accent", "#ffffff"], ["teal", "#ffffff"]]; // 白文字を載せる塗り
const sets = { dark, "light(手動)": lightManual, "light(自動)": lightAuto };

// ライトの 2 か所(手動・自動)は同じ値であること(片方だけ直し忘れない)
for (const key of Object.keys(lightManual)) assert.equal(lightAuto[key], lightManual[key], `light の ${key} が手動と自動で一致する`);

for (const [name, t] of Object.entries(sets)) {
  for (const fg of TEXT) {
    assert.ok(t[fg], `${name} に --${fg} がある`);
    for (const bg of GROUNDS) {
      const v = ratio(t[fg], t[bg]);
      assert.ok(v >= 4.5, `${name}: --${fg} ${t[fg]} on --${bg} ${t[bg]} = ${v.toFixed(2)}:1(4.5 以上)`);
    }
  }
  for (const [fill, ink] of FILLS) {
    const v = ratio(t[fill], ink);
    assert.ok(v >= 4.5, `${name}: 白 on --${fill} ${t[fill]} = ${v.toFixed(2)}:1(4.5 以上)`);
  }
  const onBad = ratio(t["bad"], t["on-bad"]);
  assert.ok(onBad >= 4.5, `${name}: --on-bad ${t["on-bad"]} on --bad ${t["bad"]} = ${onBad.toFixed(2)}:1(4.5 以上)`);
}
console.log("ui contrast: ok");

// --- 動き: 終わりが読めない処理の帯(無限ループ)は、transform で動かし、動きを減らす設定では止める
const html = chatUiHtml();
assert.match(html, /@keyframes progress-slide \{ from \{ transform: translateX\(0\); \} to \{ transform: translateX\(185\.7%\); \} \}/);
assert.ok(!/@keyframes progress-slide[^}]*margin-left/.test(html), "レイアウト(margin-left)を動かさない");
assert.match(html, /@media \(prefers-reduced-motion: reduce\) \{ \.progress-bar\.indeterminate \{ animation: none; \} \}/);
console.log("ui motion: ok");

// --- ヒーローのパーティクル(canvas の requestAnimationFrame の無限ループ): 動きを減らす設定では 1 フレームだけ描いて止める
assert.match(html, /const heroCalm = !!\(window\.matchMedia && window\.matchMedia\("\(prefers-reduced-motion: reduce\)"\)\.matches\);/);
assert.match(html, /if \(!heroCalm\) heroAnimId = requestAnimationFrame\(frame\);/);
assert.match(html, /if \(heroCalm\) \{ frame\(0\); heroAnimId = 0; \} else heroAnimId = requestAnimationFrame\(frame\);/);
console.log("ui hero motion: ok");
