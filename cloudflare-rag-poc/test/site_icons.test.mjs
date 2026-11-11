// サイトのアイコン(/icon.svg・/favicon.ico・/apple-touch-icon.png): 画像の中身が正しいこと、画面の <head> から読まれること、
// ルートが認証より前に置かれ、正しい content-type で返ること。index.ts は Workers 専用のモジュールを読むため Node から直接は呼べない。
// そこで、画像は siteIcons.ts を直接、ルートはソースの形で検査する。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const { APPLE_ICON_PNG_BASE64, FAVICON_ICO_BASE64, ICON_SVG, decodeBase64 } = await import("../src/siteIcons");
const { chatUiHtml } = await import("../src/chatUi");
const indexSource = readFileSync(fileURLToPath(new URL("../src/index.ts", import.meta.url)), "utf8");

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const startsWithPng = (bytes, at = 0) => PNG_SIGNATURE.every((b, i) => bytes[at + i] === b);

// --- favicon.ico: 16 / 32 / 48 の PNG が入った ICO
const ico = decodeBase64(FAVICON_ICO_BASE64);
const view = new DataView(ico.buffer, ico.byteOffset, ico.byteLength);
assert.equal(view.getUint16(0, true), 0, "ICO の予約領域は 0");
assert.equal(view.getUint16(2, true), 1, "ICO の種類は 1(アイコン)");
const count = view.getUint16(4, true);
assert.equal(count, 3);
const sizes = [];
for (let i = 0; i < count; i++) {
  const entry = 6 + 16 * i;
  const size = ico[entry] || 256;
  const length = view.getUint32(entry + 8, true);
  const offset = view.getUint32(entry + 12, true);
  assert.ok(offset + length <= ico.length, "項目が ICO の範囲に収まる");
  assert.ok(startsWithPng(ico, offset), `${size}px は PNG`);
  sizes.push(size);
}
assert.deepEqual(sizes, [16, 32, 48]);

// --- apple-touch-icon: 180x180 の PNG
const apple = decodeBase64(APPLE_ICON_PNG_BASE64);
assert.ok(startsWithPng(apple), "PNG");
const appleView = new DataView(apple.buffer, apple.byteOffset, apple.byteLength);
assert.equal(appleView.getUint32(16), 180, "幅 180");
assert.equal(appleView.getUint32(20), 180, "高さ 180");

// --- icon.svg: 自己完結(スクリプト・外部参照なし)。ブラウザが暗いときは反転する
assert.match(ICON_SVG, /^<svg [^>]*viewBox="0 0 32 32"/);
assert.match(ICON_SVG, /prefers-color-scheme:dark/);
assert.ok(!/<script|href=|xlink:|onload|<foreignObject/i.test(ICON_SVG), "SVG にスクリプトや外部参照を入れない");

// --- 画面の <head> から読まれる
const html = chatUiHtml();
assert.match(html, /<link rel="icon" href="\/icon\.svg" type="image\/svg\+xml">/);
assert.match(html, /<link rel="icon" href="\/favicon\.ico" sizes="48x48">/);
assert.match(html, /<link rel="apple-touch-icon" href="\/apple-touch-icon\.png">/);

// --- ルート: 3 つとも GET・認証なし(authenticate() より前)・正しい content-type
for (const [path, type] of [
  ["/favicon.ico", "image/x-icon"],
  ["/icon.svg", "image/svg+xml"],
  ["/apple-touch-icon.png", "image/png"],
]) {
  const at = indexSource.indexOf(`url.pathname === "${path}"`);
  assert.ok(at > 0, `${path} のルートがある`);
  const block = indexSource.slice(at, at + 400);
  assert.ok(block.includes(`"content-type": "${type}"`), `${path} は ${type}`);
  assert.ok(block.includes("nosniff"), `${path} に nosniff`);
}
// 最初の authenticate( の呼び出しより前に 3 つのルートがあること(認証なしで返す)
const firstCall = indexSource.indexOf("await authenticate(");
for (const path of ["/favicon.ico", "/icon.svg", "/apple-touch-icon.png"]) {
  assert.ok(indexSource.indexOf(`url.pathname === "${path}"`) < firstCall, `${path} は認証より前`);
}
console.log("site icons: ok");
