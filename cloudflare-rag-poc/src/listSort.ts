// 一覧の並べ替え（画面側のJavaScriptの部品。2026-10-23追加）。
//
// 画面（chatUi.ts）は、1つのテンプレート文字列で出す素のJavaScriptなので、import できない。
// そこで、並べ替えの「純粋な関数」だけを、ここに文字列として持ち、画面に埋め込む。
// テスト（test/list_sort.test.mjs）は、同じ文字列を評価して、同じ関数を検証する。
//
// 守ること: この文字列の中に、バックスラッシュ・バッククォート・「${」を書かない
// （テンプレート文字列として解釈されるため）。正規表現は、バックスラッシュの要らない形だけを使う。

export const LIST_SORT_JS = `
  // ---------- 一覧の並べ替え（純粋な関数） ----------
  const SORT_COLLATOR = new Intl.Collator("ja", { numeric: true, sensitivity: "base" });
  function compareText(a, b) {
    return SORT_COLLATOR.compare(String(a == null ? "" : a), String(b == null ? "" : b));
  }
  // 空の値（null・undefined・空文字・"-"）は、昇順でも降順でも、いちばん後ろに置く。
  function isEmptySortValue(v) {
    return v === null || v === undefined || v === "" || v === "-" || (typeof v === "number" && isNaN(v));
  }
  function compareValues(a, b, type) {
    if (type === "number") return a - b;
    return compareText(a, b);
  }
  // items を並べ替えた新しい配列を返す（元の配列は変えない。安定: 同じ値は、元の順を保つ）。
  // spec: [{ get: (item) => 値, type: "text" | "number" }, ...]。先頭が主キー（dir: 1=昇順, -1=降順）、
  // 2番目以降は、同点のときの決め手（常に昇順）。
  function sortItems(items, spec, dir) {
    const direction = dir === -1 ? -1 : 1;
    return items
      .map((item, index) => ({ item, index }))
      .sort((x, y) => {
        for (let k = 0; k < spec.length; k++) {
          const a = spec[k].get(x.item);
          const b = spec[k].get(y.item);
          const emptyA = isEmptySortValue(a);
          const emptyB = isEmptySortValue(b);
          if (emptyA || emptyB) {
            if (emptyA && emptyB) continue;
            return emptyA ? 1 : -1;
          }
          const c = compareValues(a, b, spec[k].type);
          if (c !== 0) return k === 0 ? c * direction : c;
        }
        return x.index - y.index;
      })
      .map((entry) => entry.item);
  }
  // 表のセルの文字を、数・日時・文字のどれかとして読む。数と単位（「12%」「3.5 MB」「1,234 件」）は数、
  // 日付らしいもの（「2026/10/22 10:11:12」）は日時（ミリ秒）、それ以外は文字。空は null。
  function parseCellValue(text) {
    const t = String(text == null ? "" : text).trim();
    if (t === "" || t === "-") return { type: "empty", value: null };
    const plain = t.split(",").join("");
    if (/^[-+]?[0-9]+[.]?[0-9]*[ ]?[^0-9 ]{0,4}$/.test(plain) && !isNaN(parseFloat(plain))) {
      return { type: "number", value: parseFloat(plain) };
    }
    if (t.length >= 8 && t.length <= 40 && t.charCodeAt(0) >= 48 && t.charCodeAt(0) <= 57 && (t.indexOf("/") > 0 || t.indexOf("-") > 0)) {
      const time = Date.parse(t.split("/").join("-").replace(" ", "T"));
      if (!isNaN(time)) return { type: "time", value: time };
      const raw = Date.parse(t);
      if (!isNaN(raw)) return { type: "time", value: raw };
    }
    return { type: "text", value: t };
  }
  // 表の1列分の並べ替え用の値を比べる。同じ種類どうしは、その種類で。違うときは、文字として。空は後ろ。
  function compareCellValues(a, b) {
    if (a.type === "empty" || b.type === "empty") {
      if (a.type === b.type) return 0;
      return a.type === "empty" ? 1 : -1;
    }
    if (a.type === b.type && (a.type === "number" || a.type === "time")) return a.value - b.value;
    return compareText(a.value, b.value);
  }
  // 行の配列（各行は、セルの文字の配列）を、列 col で並べ替えた「元の位置の並び」を返す。
  function sortedRowOrder(rowsText, col, dir) {
    const direction = dir === -1 ? -1 : 1;
    const parsed = rowsText.map((cells, index) => ({ index, v: parseCellValue(cells[col]) }));
    parsed.sort((x, y) => {
      if (x.v.type === "empty" || y.v.type === "empty") return compareCellValues(x.v, y.v) || x.index - y.index;
      const c = compareCellValues(x.v, y.v) * direction;
      return c !== 0 ? c : x.index - y.index;
    });
    return parsed.map((p) => p.index);
  }
`;
