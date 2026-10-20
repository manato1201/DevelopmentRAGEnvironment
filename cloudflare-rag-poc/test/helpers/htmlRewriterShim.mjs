// Cloudflare WorkersのHTMLRewriterの、テスト用の代用品。
// 本物と同じく、タグの入れ子・終了タグ（element.onEndTag）・セレクタ（タグ名、*、[属性]、[属性=値]、カンマ区切り）・
// 「一致した要素の中の文字」（text）を扱う。完全なHTMLパーサではない（壊れたHTMLや、複雑なセレクタは対象外）。
// 使い方: import { installHtmlRewriterShim } from "./helpers/htmlRewriterShim.mjs"; installHtmlRewriterShim();

const VOID = new Set([
  "meta",
  "link",
  "br",
  "img",
  "hr",
  "input",
  "source",
  "area",
  "base",
  "col",
  "embed",
  "param",
  "track",
  "wbr",
]);

function parseAttrs(raw) {
  const attrs = {};
  for (const m of raw.matchAll(
    /([^\s=/>"']+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g,
  )) {
    attrs[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? "";
  }
  return attrs;
}

function parseSelector(sel) {
  return sel
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((part) => {
      const m = part.match(/^([a-zA-Z*][\w-]*|\*)?((?:\[[^\]]+\])*)$/);
      if (!m) throw new Error(`shim: 未対応のセレクタ ${part}`);
      const attrs = [
        ...(m[2] || "").matchAll(/\[([^\]=]+)(?:=([^\]]*))?\]/g),
      ].map((a) => [a[1].toLowerCase(), a[2]?.replace(/^["']|["']$/g, "")]);
      return { tag: m[1] && m[1] !== "*" ? m[1].toLowerCase() : null, attrs };
    });
}

function matches(parsed, el) {
  return parsed.some(
    (p) =>
      (!p.tag || p.tag === el.tag) &&
      p.attrs.every(
        ([k, v]) => k in el.attrs && (v === undefined || el.attrs[k] === v),
      ),
  );
}

export function installHtmlRewriterShim() {
  globalThis.HTMLRewriter = class {
    constructor() {
      this.handlers = [];
    }
    on(selector, handlers) {
      this.handlers.push({ sel: parseSelector(selector), h: handlers });
      return this;
    }
    transform(res) {
      const self = this;
      return {
        async text() {
          const html = await res.text();
          const stack = [];
          const re =
            /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>|[^<]+|</g;
          let rawUntil = null; // <script>/<style>の中身は、文字として扱わない
          for (const m of html.matchAll(re)) {
            const tok = m[0];
            if (rawUntil) {
              if (m[1] && m[1].toLowerCase() === rawUntil) rawUntil = null; // 終了タグ。以下で通常どおり処理する
              else continue; // スクリプトの中身は読み飛ばす
            }
            if (tok.startsWith("<!--")) continue;
            if (m[1]) {
              // 終了タグ
              const tag = m[1].toLowerCase();
              for (let i = stack.length - 1; i >= 0; i--) {
                if (stack[i].tag === tag) {
                  const closing = stack.splice(i);
                  for (const el of closing.reverse())
                    for (const cb of el.endCbs) cb();
                  break;
                }
              }
              continue;
            }
            if (m[2]) {
              // 開始タグ
              const tag = m[2].toLowerCase();
              const selfClosing = /\/\s*$/.test(m[3] || "");
              const el = { tag, attrs: parseAttrs(m[3] || ""), endCbs: [] };
              for (const { sel, h } of self.handlers) {
                if (h.element && matches(sel, el)) {
                  h.element({
                    tagName: tag,
                    getAttribute: (n) => el.attrs[n.toLowerCase()] ?? null,
                    remove() {},
                    onEndTag: (cb) => el.endCbs.push(cb),
                  });
                }
              }
              if (tag === "script" || tag === "style") rawUntil = tag;
              if (!VOID.has(tag) && !selfClosing) stack.push(el);
              continue;
            }
            // 文字: 一致する要素の中にあるときだけ、そのhandlerに渡す
            for (const { sel, h } of self.handlers) {
              if (h.text && stack.some((el) => matches(sel, el)))
                h.text({ text: tok });
            }
          }
          for (const el of stack.reverse()) for (const cb of el.endCbs) cb();
          return html;
        },
      };
    }
  };
}
