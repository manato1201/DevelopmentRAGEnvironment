// 空状態の生き物（2026-10-27、src/asciiArt.ts。設計書 追補第3弾 D1・D4・D5）: 時刻だけで絵が決まる純関数。
import assert from "node:assert/strict";
import vm from "node:vm";

const { ASCII_ART_JS } = await import("../src/asciiArt");
const { chatUiHtml } = await import("../src/chatUi");

assert.ok(!ASCII_ART_JS.includes("\\"), "no backslash in the embedded script");
assert.ok(!ASCII_ART_JS.includes("`"), "no backtick");
assert.ok(!ASCII_ART_JS.includes("${"), "no template placeholder");

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(ASCII_ART_JS + "\nthis.api = { ART_RAMPS, brightnessToChar, critterBrightness, cellDelay, critterFrame };", sandbox);
const { ART_RAMPS, brightnessToChar, critterBrightness, cellDelay, critterFrame } = sandbox.api;

const NL = String.fromCharCode(10);

// ---- D1: 明るさ → 文字。明るいほど、濃い文字
const ramp = ART_RAMPS.classic;
assert.equal(brightnessToChar(0, ramp), " ");
assert.equal(brightnessToChar(1, ramp), "@");
let last = -1;
for (let i = 0; i <= 100; i++) {
  const index = ramp.indexOf(brightnessToChar(i / 100, ramp));
  assert.ok(index >= last, "monotonic at " + i);
  last = index;
}
assert.equal(brightnessToChar(-5, ramp), " ", "clamped low");
assert.equal(brightnessToChar(9, ramp), "@", "clamped high");
assert.equal(brightnessToChar(NaN, ramp), " ", "NaN is treated as dark");
assert.equal(brightnessToChar(0.5), brightnessToChar(0.5, ART_RAMPS.classic), "default ramp");

// ---- D4: 階調表はパラメータ。同じ絵を、別の文字で描ける
const a = critterFrame(30, 9, 0, 1, ART_RAMPS.classic);
const b = critterFrame(30, 9, 0, 1, ART_RAMPS.critter);
assert.notEqual(a, b, "a different ramp gives a different picture");
assert.equal(a.split(NL).length, b.split(NL).length, "same number of rows");
for (const ch of new Set(b.replace(/\n/g, ""))) assert.ok(ART_RAMPS.critter.includes(ch), "only ramp characters: " + JSON.stringify(ch));

// ---- 純関数: 同じ入力なら、同じ絵。時刻で形が変わる
assert.equal(critterFrame(30, 9, 1.25, 1, ART_RAMPS.critter), critterFrame(30, 9, 1.25, 1, ART_RAMPS.critter));
assert.notEqual(critterFrame(30, 9, 0, 1, ART_RAMPS.critter), critterFrame(30, 9, 1.7, 1, ART_RAMPS.critter), "tentacles move with time");
for (let y = 0; y < 9; y++) for (let x = 0; x < 30; x++) {
  const v = critterBrightness(x, y, 30, 9, 2.3);
  assert.ok(v >= 0 && v <= 1, "brightness in range");
}

// ---- 形: 傘（上）が明るく、目が暗い。触手が下に伸びる。大きさ
const full = critterFrame(30, 9, 0, 1, ART_RAMPS.classic);
const rows = full.split("\n");
assert.equal(rows.length, 9);
assert.ok(rows.every((r) => r.length <= 30));
const density = (row) => [...row].filter((c) => c !== " ").length;
assert.ok(density(rows[2]) + density(rows[3]) > density(rows[8]), "the dome is denser than the tentacle tips");
assert.ok(rows.slice(5).some((r) => density(r) > 0), "tentacles reach the lower rows");
assert.ok(density(rows[0]) < density(rows[3]), "empty above the dome");

// ---- D5: マスごとの遅れ。粒状に現れる（進み具合が大きいほど、見えるマスが増える）
for (let y = 0; y < 9; y++) for (let x = 0; x < 30; x++) {
  const d = cellDelay(x, y);
  assert.ok(d >= 0 && d < 1, "delay in [0,1)");
  assert.equal(d, cellDelay(x, y), "deterministic");
}
assert.notEqual(cellDelay(0, 0), cellDelay(1, 0));
const visible = (progress) => [...critterFrame(30, 9, 0, progress, ART_RAMPS.classic)].filter((c) => c !== " " && c !== "\n").length;
let previous = -1;
for (let p = 0; p <= 1.0001; p += 0.1) {
  const count = visible(Math.min(1, p));
  assert.ok(count >= previous, "monotonic reveal at " + p.toFixed(1));
  previous = count;
}
assert.equal(visible(0), 0, "nothing at progress 0");
assert.ok(visible(0.5) > 0 && visible(0.5) < visible(1), "partly revealed at 0.5");
assert.equal(critterFrame(30, 9, 0, 5, ART_RAMPS.classic), full, "progress is clamped to 1");
// 現れかけのマスは、完成形のマスと同じ文字（別の文字に化けない）
const half = critterFrame(30, 9, 0, 0.5, ART_RAMPS.classic).split("\n");
half.forEach((row, y) => [...row].forEach((c, x) => { if (c !== " ") assert.equal(c, rows[y][x], "same character at " + x + "," + y); }));

// ---- 画面: 部品が入っていて、動きを減らす設定のときは静止する
const html = chatUiHtml();
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).filter((c) => c.trim().length > 0);
for (const code of scripts) new vm.Script(code);
const code = scripts.join("\n");
assert.match(code, /function critterFrame\(/);
assert.match(code, /function asciiCritter\(/);
assert.match(code, /if \(calm\) \{\s*paintCritter\(pre, critterFrame\(CRITTER_W, CRITTER_H, 0, 1, ART_RAMPS\.critter\)\);\s*return pre;/, "reduced motion: a still, finished frame; no timer");
assert.ok(!/critterText\(/.test(code), "the old rotating-glyph code is gone");

// 追補（ASCII モチーフ）: 回答待ちにも出す。画面の外・非表示のタブでは描かない。取り除かれたら止まる
assert.match(code, /skeleton\.appendChild\(asciiCritter\(\)\)/, "the waiting skeleton shows the creature");
assert.match(code, /if \(document\.hidden \|\| !onScreen\) return;/, "no drawing while hidden or off screen");
assert.match(code, /if \(!pre\.isConnected\) \{ clearInterval\(timer\);/, "the timer stops when the creature is removed");
assert.match(html, /\.msg\.skeleton i:nth-of-type\(1\)/,"skeleton bars are counted by type, so the creature does not shift them");
assert.ok(!/\.msg\.skeleton i:nth-child/.test(html), "no nth-child on the skeleton bars");
// 色は既存トークンだけ（紫 --accent と、濃いマスのアンバー --highlight）
assert.match(html, /\.ascii-critter \{[^}]*color: var\(--accent\)/);
assert.match(html, /\.ascii-critter \.ascii-glow \{ color: var\(--highlight\); \}/);

// Z20: 背景の生き物は、選んだ人だけ（既定はなし）。操作を邪魔せず、狭い画面では出さない。動きを減らす設定は asciiCritter が尊重する
assert.match(html, /<option value="off" selected>背景: なし<\/option>/, "off by default");
assert.match(html, /id="glassToggle"[^>]*>曇りガラス: なし</, "the frosted glass is off by default");
assert.match(code, /function initWallpaper\(/);
assert.match(code, /el = asciiCritter\(\);\s*el\.classList\.add\("ascii-wallpaper"\)/, "reuses the same creature (and its reduced-motion handling)");
assert.match(html, /\.ascii-wallpaper \{[^}]*z-index: -1;[^}]*pointer-events: none;/, "behind the content, never takes clicks");
assert.match(html, /@media \(max-width: 720px\) \{ \.ascii-wallpaper \{ display: none; \} \}/, "hidden on narrow screens");
assert.match(code, /if \(el\) \{ el\.remove\(\); el = null; \}/, "switching off removes it, which also stops its timer");
assert.match(code, /stop\(\);\s*stop = function \(\) \{\};/, "switching wallpapers stops the previous timer and the resize listener");

// paintCritter: 濃いマス（X と @）だけを span にする。文字は欠けない
const paintStart = code.indexOf("function paintCritter(");
const paintSrc = code.slice(paintStart, code.indexOf("// 空状態と、回答待ち", paintStart));
const fakeDoc = {
  createElement: (tag) => ({ tag, className: "", textContent: "" }),
  createTextNode: (text) => ({ text }),
};
const fakePre = { children: [], appendChild(n) { this.children.push(n); }, set textContent(v) { this.children = []; } };
vm.runInNewContext(paintSrc + "\npaintCritter(pre, text);", { document: fakeDoc, pre: fakePre, text: "ot X@8 o" });
assert.equal(fakePre.children.map((n) => n.text ?? n.textContent).join(""), "ot X@8 o", "no character is lost");
assert.deepEqual(fakePre.children.filter((n) => n.tag === "span").map((n) => n.textContent), ["X@"], "only the dense cells glow");
assert.ok(fakePre.children.filter((n) => n.tag === "span").every((n) => n.className === "ascii-glow"));
console.log("ascii_art tests passed");


// ---- Z20（2026-11-06）: 画面いっぱいの壁紙7種 + 右下のクラゲ = 8種。どれも時刻と座標だけで決まる純関数
{
  const sb = {};
  vm.createContext(sb);
  vm.runInContext(ASCII_ART_JS + "\nthis.api = { WALLPAPER_KINDS, WALLPAPER_LABELS, wallpaperBrightness, wallpaperFrame, ART_RAMPS };", sb);
  const { WALLPAPER_KINDS, WALLPAPER_LABELS, wallpaperBrightness, wallpaperFrame, ART_RAMPS: RAMPS } = sb.api;
  assert.equal(WALLPAPER_KINDS.length, 7);
  assert.equal(Object.keys(WALLPAPER_LABELS).length, 8, "7 full-screen wallpapers + the jellyfish in the corner");
  const W = 60, H = 20;
  const seen = new Set();
  for (const kind of WALLPAPER_KINDS) {
    const frame = wallpaperFrame(kind, W, H, 3.7, RAMPS.classic);
    assert.equal(frame, wallpaperFrame(kind, W, H, 3.7, RAMPS.classic), kind + ": same input, same picture");
    assert.equal(frame.split(NL).length, H, kind + ": rows");
    assert.ok(frame.replace(/\s/g, "").length > 0, kind + ": something is drawn");
    for (const row of frame.split(NL)) assert.ok(row.length <= W, kind + ": row width");
    for (const ch of new Set(frame.replace(/\n/g, ""))) assert.ok(RAMPS.classic.includes(ch), kind + ": only ramp characters " + JSON.stringify(ch));
    let max = 0;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const v = wallpaperBrightness(kind, x, y, W, H, 1.3);
      assert.ok(v >= 0 && v <= 1 && !Number.isNaN(v), kind + ": brightness in range");
      if (v > max) max = v;
    }
    assert.ok(max > 0.5, kind + ": has bright cells");
    seen.add(frame);
  }
  assert.equal(seen.size, WALLPAPER_KINDS.length, "every wallpaper looks different");
  // 動く壁紙は、時刻で絵が変わる（格子と砂丘も、ゆっくり変わる）
  for (const kind of WALLPAPER_KINDS) {
    assert.notEqual(wallpaperFrame(kind, W, H, 0, RAMPS.classic), wallpaperFrame(kind, W, H, 9, RAMPS.classic), kind + ": moves with time");
  }
  assert.equal(wallpaperFrame("nonsense", 10, 4, 1, RAMPS.classic).replace(/\s/g, ""), "", "an unknown kind draws nothing");
  // 大きな画面（170x60）でも、1コマは速い（7秒に1000コマ以下の負荷で動かすための目安）
  const begin = Date.now();
  for (const kind of WALLPAPER_KINDS) wallpaperFrame(kind, 170, 60, 2, RAMPS.classic);
  assert.ok(Date.now() - begin < 1000, "7 full-size frames in under a second");
}

// ---- Z20: 画面側。壁紙は薄く・操作を通さず・狭い画面では出さない。曇りガラスは背景色を8割まぜる（文字は壁紙の上に直接のらない）
{
  const options = [...html.matchAll(/<option value="([a-z]+)"[^>]*>背景: /g)].map((m) => m[1]);
  assert.deepEqual(options, ["off", "critter", "wave", "stars", "rain", "swirl", "school", "dunes", "grid"]);
  const full = html.match(/\.ascii-wallpaper\.ascii-wallpaper-full \{([^}]*)\}/);
  assert.ok(full, "full-screen wallpaper rule");
  const opacity = Number(full[1].match(/opacity: ([.\d]+)/)[1]);
  assert.ok(opacity <= 0.2, "faint enough for body text to stay readable (dark): " + opacity);
  assert.match(html, /:root\[data-theme="light"\] \.ascii-wallpaper\.ascii-wallpaper-full \{[^}]*opacity: \.16;/);
  const glass = html.match(/html\.glass header, html\.glass nav\.tabs, html\.glass \.tabpanel \{([^}]*)\}/);
  assert.ok(glass, "glass rule");
  const mix = Number(glass[1].match(/var\(--bg\) (\d+)%/)[1]);
  assert.ok(mix >= 60, "the surface keeps at least 60% of the background colour: " + mix);
  const glassWall = html.match(/html\.glass \.ascii-wallpaper\.ascii-wallpaper-full \{ opacity: ([.\d]+); \}/);
  assert.ok(glassWall && Number(glassWall[1]) <= 0.35, "with the glass on, the wallpaper stays under 35% opacity: " + (glassWall && glassWall[1]));
  assert.match(html, /@supports \(\(backdrop-filter: blur\(1px\)\)[^{]*color-mix/, "only where the browser supports it");
  assert.match(code, /localStorage\.setItem\("ragPocGlass"/);
  assert.match(code, /full\.indexOf\(raw\)|FULL_KINDS\.indexOf\(raw\) >= 0/, "an unknown saved value falls back to off");
  assert.match(code, /if \(!document\.hidden\) draw\(\)/, "no drawing in a hidden tab");
  assert.match(code, /const calm = window\.matchMedia[^;]*prefers-reduced-motion: reduce/, "reduced motion: one still frame");
  assert.match(code, /if \(!calm\) \{\s*timer = setInterval/, "no timer when motion is reduced");
}
