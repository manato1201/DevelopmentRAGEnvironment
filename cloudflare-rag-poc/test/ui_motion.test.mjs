// 状態変化の動き(ばね。2026-11-26): 回答のコピー・質問の文字数・予算のメーター。値は designbookmark の部品と同じ。
// インラインの script は TypeScript で検査できないので、文字列として決まりを確かめる(構文は ui_syntax.test.mjs)。
import assert from "node:assert/strict";
import { test } from "node:test";

const { chatUiHtml } = await import("../src/chatUi");
const html = chatUiHtml();
const code = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).join("\n");

test("ui_motion: ばねの値(強さ・減衰)は元の部品と同じ", () => {
  assert.match(code, /copyIcon: \[420, 18\], limitFill: \[280, 22\], limitPop: \[520, 16\], limitShake: \[700, 12\], meterWidth: \[260, 24\], meterSquash: \[520, 16\]/);
  assert.match(code, /Math\.min\(\(t - last\) \/ 1000, 1 \/ 30\) \/ 4/); // 1 フレーム最大 1/30 秒・4 分割
});

test("ui_motion: 動きを減らす設定では、ばねを使わず、すぐ目標の値にする", () => {
  assert.match(code, /window\.matchMedia\("\(prefers-reduced-motion: reduce\)"\)/);
  assert.match(code, /to: function \(t\) \{ s\.target = t; if \(reduced\(\)\) \{ s\.x = t;/);
  assert.match(code, /kick: function \(v\) \{ if \(reduced\(\)\) return;/);
});

test("ui_motion: 質問の文字数は 800 字の目安(入力は止めない)・400 字から出る・隠したら消える", () => {
  assert.match(code, /const Q_SOFT_LIMIT = 800;/);
  assert.match(code, /const show = n >= Q_SOFT_LIMIT \/ 2;/);
  assert.ok(!/inputEl\.value = inputEl\.value\.slice/.test(code), "入力を切り詰めない");
  assert.match(html, /\.q-limit\[hidden\] \{ display: none; \}/);
  assert.match(html, /<span id="qLimit" class="q-limit" hidden>/);
});

test("ui_motion: 回答のコピーはアイコンが ✓ に入れ替わり、1.8 秒で戻る。予算は回答のたびに読み直す", () => {
  assert.match(code, /const copiedFx = copyIconSwap\(copyBtn, COPY_LABEL\);/);
  assert.match(code, /sp\.to\(0\); btn\.title = idleLabel;[\s\S]{0,80}\}, 1800\);/);
  assert.match(code, /loadMyBudget\(\); \/\/ 使った分だけ/);
  assert.match(code, /el\.appendChild\(budgetMeter\(label, pct, isLow\)\);/);
  // 動かす性質は transform と opacity だけ(幅は scaleX)
  const block = code.slice(code.indexOf("const DRMotion"), code.indexOf("function budgetRadialSvg"));
  assert.ok(!/style\.width/.test(block));
});
