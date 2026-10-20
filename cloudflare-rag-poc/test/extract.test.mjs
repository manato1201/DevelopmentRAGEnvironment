// HTMLからの本文抽出（urlImport.ts の extractTextLinksAndTitle）。
// 背景: ドキュメントサイトは全ページに巨大な目次（サイドバー）を持つ。SideFXのページは、1ページ約10.5万文字のうち
// 本文は約1万文字。目次ごと登録すると、1ページ約200チャンクになり、再クロールが503で止まった（2026-10-17）。
import assert from "node:assert/strict";
import { installHtmlRewriterShim } from "./helpers/htmlRewriterShim.mjs";

installHtmlRewriterShim();
const { extractTextLinksAndTitle } = await import("../src/urlImport");
const { chunkText } = await import("../src/chunking");

const BASE = "https://www.sidefx.com/docs/houdini/nodes/sop/apex--addmldeformer.html";
const navItems = Array.from({ length: 3000 }, (_, i) => `<li><a href="/docs/houdini/nodes/sop/node${i}.html">Node number ${i} description</a></li>`).join("");
const body = "ML Deformerは、メッシュを機械学習のモデルで変形するノードです。".repeat(60); // 約2,000文字

// 1) SideFX型: <div id="toc"><nav>…巨大な目次…</nav></div> ＋ <main>本文</main> ＋ <footer>
{
  const html = `<!doctype html><html><head><title>Add ML Deformer</title><script>var tracking = "do not index";</script></head>
    <body><div id="toc"><nav><ul>${navItems}</ul></nav></div>
    <main><h1>Add ML Deformer</h1><p>${body}</p><a href="/docs/houdini/nodes/sop/ref.html#params">参照</a></main>
    <footer>Copyright SideFX</footer></body></html>`;
  const r = await extractTextLinksAndTitle(html, BASE);
  assert.equal(r.title, "Add ML Deformer");
  assert.ok(r.text.includes("ML Deformerは"), "本文が入っている");
  assert.ok(r.text.includes("Add ML Deformer"), "<main>内の見出しが入っている");
  assert.ok(!r.text.includes("Node number"), "目次（nav）の文字は入らない");
  assert.ok(!r.text.includes("Copyright"), "footerの文字は入らない");
  assert.ok(!r.text.includes("do not index"), "scriptの中身は入らない");
  // リンクは、目次からのものも、ページ全体から集める（クロールで辿るため）。#以降は落とす
  assert.ok(r.links.includes("https://www.sidefx.com/docs/houdini/nodes/sop/node2999.html"), "目次のリンクも集める");
  assert.ok(r.links.includes("https://www.sidefx.com/docs/houdini/nodes/sop/ref.html"), "本文内のリンクも集める（#は落とす）");
  assert.equal(r.links.length, 3001);
  // 目次ごと登録した場合との比較: チャンク数が、桁違いに減る
  const withNav = chunkText(html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ")).length;
  assert.ok(withNav > 50, "目次ごとだと、数十〜数百チャンクになる（" + withNav + "）");
  assert.ok(chunkText(r.text).length <= 4, "本文だけなら、数チャンク（" + chunkText(r.text).length + "）");
}

// 2) <main>が無いページ: 全体から取る。ただし、nav・footer・asideは除く
{
  const html = `<html><head><title>Plain</title></head><body>
    <nav><a href="/a">メニューA</a></nav><aside>広告</aside>
    <div><h1>見出し</h1><p>これは本文です。</p></div><footer>フッター</footer></body></html>`;
  const r = await extractTextLinksAndTitle(html, "https://example.com/x");
  assert.ok(r.text.includes("見出し") && r.text.includes("これは本文です。"));
  assert.ok(!r.text.includes("メニューA") && !r.text.includes("広告") && !r.text.includes("フッター"));
  assert.deepEqual(r.links, ["https://example.com/a"]);
}

// 3) <main>が空の入れ物（本文をJavaScriptで描くページなど）: 領域の絞り込みをやめて、全体から取り直す
{
  const html = `<html><head><title>Shell</title></head><body>
    <main id="app"></main><div><p>${"これはmainの外にある本文です。".repeat(10)}</p></div></body></html>`;
  const r = await extractTextLinksAndTitle(html, "https://example.com/y");
  assert.ok(r.text.includes("mainの外にある本文"), "取り直して、本文が取れる");
}

// 4) <article>・role="main"も、本文の領域として扱う
{
  const a = await extractTextLinksAndTitle(`<body><div>外の文字ABC</div><article><p>記事の本文XYZ</p></article></body>`, "https://example.com/");
  assert.ok(a.text.includes("記事の本文XYZ") && !a.text.includes("外の文字ABC"));
  const b = await extractTextLinksAndTitle(`<body><div>外の文字ABC</div><div role="main"><p>役割mainの本文</p></div></body>`, "https://example.com/");
  assert.ok(b.text.includes("役割mainの本文") && !b.text.includes("外の文字ABC"));
}

// 5) nav の中の<main>風の入れ子や、閉じ忘れが、後続の本文を巻き込まない（深さのカウントが戻る）
{
  const html = `<body><nav><ul><li>メニュー1</li><li>メニュー2</li></ul></nav><main><p>本文その1</p></main><nav>下のメニュー</nav><main><p>本文その2</p></main></body>`;
  const r = await extractTextLinksAndTitle(html, "https://example.com/");
  assert.ok(r.text.includes("本文その1") && r.text.includes("本文その2"));
  assert.ok(!r.text.includes("メニュー") && !r.text.includes("下のメニュー"));
}

console.log("extract tests ok");
