// 一覧の並べ替え（2026-10-23）: 画面に埋め込む純粋な関数（src/listSort.ts）を、同じ文字列から評価して検証する。
// あわせて、画面（chatUi.ts）に並べ替えの部品が入っていて、スクリプトとして正しいことを確かめる。
import assert from "node:assert/strict";
import vm from "node:vm";

const { LIST_SORT_JS } = await import("../src/listSort");
const { chatUiHtml } = await import("../src/chatUi");

// 純粋な関数だけを評価して取り出す
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(LIST_SORT_JS + "\nthis.api = { sortItems, parseCellValue, sortedRowOrder, compareText, isEmptySortValue };", sandbox);
const { sortItems, parseCellValue, sortedRowOrder, compareText, isEmptySortValue } = sandbox.api;

// 埋め込み用の文字列に、テンプレート文字列を壊すものがない
assert.ok(!LIST_SORT_JS.includes("\\"), "no backslash in the embedded script");
assert.ok(!LIST_SORT_JS.includes("`"), "no backtick");
assert.ok(!LIST_SORT_JS.includes("${"), "no template placeholder");

// ---- 名前順: 日本語・英数字・数字の並び
const names = (list, spec, dir) => sortItems(list, spec, dir).map((x) => x.n);
const byName = [{ get: (x) => x.n, type: "text" }];
assert.deepEqual(names([{ n: "file10" }, { n: "file2" }, { n: "File1" }], byName, 1), ["File1", "file2", "file10"], "natural number order, case-insensitive");
assert.deepEqual(names([{ n: "うさぎ" }, { n: "あひる" }, { n: "いぬ" }], byName, 1), ["あひる", "いぬ", "うさぎ"], "Japanese order");
assert.deepEqual(names([{ n: "b" }, { n: "a" }, { n: "c" }], byName, -1), ["c", "b", "a"], "descending");

// ---- 空の値は、昇順でも降順でも、いちばん後ろ
const byTime = [{ get: (x) => x.t, type: "number" }, { get: (x) => x.n, type: "text" }];
const withEmpty = [{ n: "none", t: null }, { n: "old", t: 100 }, { n: "new", t: 300 }, { n: "dash", t: "-" }, { n: "nan", t: NaN }];
assert.deepEqual(names(withEmpty, byTime, 1).slice(0, 2), ["old", "new"]);
assert.deepEqual(names(withEmpty, byTime, -1).slice(0, 2), ["new", "old"]);
for (const dir of [1, -1]) {
  const tail = names(withEmpty, byTime, dir).slice(2).sort();
  assert.deepEqual(tail, ["dash", "nan", "none"], "empty values always last (dir " + dir + ")");
}
// 空どうしは、2番目の決め手（名前の昇順）で並ぶ
assert.deepEqual(names(withEmpty, byTime, 1).slice(2), ["dash", "nan", "none"]);

// ---- 同点は2番目の決め手（常に昇順）。主キーを降順にしても、決め手は昇順のまま
const byKind = [{ get: (x) => x.k, type: "text" }, { get: (x) => x.n, type: "text" }];
const items = [{ k: "web", n: "b" }, { k: "pdf", n: "z" }, { k: "web", n: "a" }, { k: "pdf", n: "y" }];
assert.deepEqual(items.map(() => 0).length, 4);
assert.deepEqual(sortItems(items, byKind, 1).map((x) => x.k + x.n), ["pdfy", "pdfz", "weba", "webb"]);
assert.deepEqual(sortItems(items, byKind, -1).map((x) => x.k + x.n), ["weba", "webb", "pdfy", "pdfz"]);

// ---- 安定（元の並びを保つ）・元の配列は変えない
const same = [{ n: "x", i: 1 }, { n: "x", i: 2 }, { n: "x", i: 3 }];
assert.deepEqual(sortItems(same, byName, 1).map((x) => x.i), [1, 2, 3]);
assert.deepEqual(sortItems(same, byName, -1).map((x) => x.i), [1, 2, 3], "ties stay in original order even when descending");
const original = [{ n: "b" }, { n: "a" }];
sortItems(original, byName, 1);
assert.deepEqual(original.map((x) => x.n), ["b", "a"], "input array is not mutated");
assert.deepEqual(sortItems([], byName, 1), []);

// ---- compareText / isEmptySortValue
assert.ok(compareText(null, "a") < 0);
assert.equal(compareText("a", "A"), 0);
assert.ok(isEmptySortValue(""));
assert.ok(isEmptySortValue(undefined));
assert.ok(!isEmptySortValue(0), "0 is a real value");

// ---- 表のセル: 数・単位・日時・文字・空
assert.deepEqual({ ...parseCellValue("12") }, { type: "number", value: 12 });
assert.deepEqual({ ...parseCellValue("1,234") }, { type: "number", value: 1234 });
assert.deepEqual({ ...parseCellValue("3.5 MB") }, { type: "number", value: 3.5 });
assert.deepEqual({ ...parseCellValue("45%") }, { type: "number", value: 45 });
assert.equal(parseCellValue("2026/10/22 10:11:12").type, "time");
assert.equal(parseCellValue("2026-10-22T10:11:12Z").type, "time");
assert.equal(parseCellValue("hello").type, "text");
assert.equal(parseCellValue("").type, "empty");
assert.equal(parseCellValue("-").type, "empty");
assert.equal(parseCellValue(null).type, "empty");
assert.equal(parseCellValue("2026/13/45 99:99").type === "time", false, "an impossible date is not a time");

// ---- 表の並べ替え: 数は大きさで（文字なら "10" < "9" になってしまう）、日時は新旧で、空は後ろ
const rows = [["a", "9"], ["b", "10"], ["c", ""], ["d", "100"]];
assert.deepEqual(sortedRowOrder(rows, 1, 1), [0, 1, 3, 2]);
assert.deepEqual(sortedRowOrder(rows, 1, -1), [3, 1, 0, 2], "empty stays last when descending");
const dates = [["x", "2026/10/02 00:00:00"], ["y", "2026/09/30 23:59:59"], ["z", "2026/10/10 12:00:00"]];
assert.deepEqual(sortedRowOrder(dates, 1, 1), [1, 0, 2]);
assert.deepEqual(sortedRowOrder(dates, 1, -1), [2, 0, 1]);
assert.deepEqual(sortedRowOrder([["b"], ["a"], ["c"]], 0, 1), [1, 0, 2]);
assert.deepEqual(sortedRowOrder([["x", "1"], ["y", "1"], ["z", "1"]], 1, -1), [0, 1, 2], "stable for equal values");

// ---- 画面: 部品が入っていて、スクリプトとして正しい
const html = chatUiHtml();
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).filter((c) => c.trim().length > 0);
for (const code of scripts) new vm.Script(code);
const code = scripts.join("\n");
assert.match(code, /function sortItems\(/);
assert.match(code, /function sortedRowOrder\(/);
assert.match(html, /id="kbListSort"/);
assert.match(html, /<th data-sort-key="name">/);
assert.match(html, /<th data-sort-key="updated">/);
assert.match(html, /<th data-sort-key="kind">/);
assert.match(html, /data-sort-managed="1"/);
assert.match(html, /th\.sortable\[aria-sort="ascending"\]/);
assert.match(code, /ragPocKbSort/);
assert.match(code, /function enableTableSort\(/);
assert.match(code, /new MutationObserver\(enableAllTableSorts\)/);
assert.match(code, /ragPocThreadSort/);
assert.match(code, /ragPocPinnedSort/);
// 一覧の並べ替えは、ページ分けより前（全件を並べてから、1ページ分を切り出す）
assert.match(code, /const filtered = sortKbItems\(/);
console.log("list_sort tests passed");
