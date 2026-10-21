// Houdini公式ドキュメントの「章」（SOP / VOP / APEX …）の扱い（2026-10-21）。
//
// 同名のノード（Transform / Merge / Null …）は、SOP・VOP・DOP・LOP・APEX などの章に別々にある。
// 登録はタイトルで管理するため、章の情報が無いと、後から登録した章が先のものを上書きし、
// 検索でも別の章の説明が混ざる。そこで次のようにする（namespaceは分けない。切り替えが要らない）:
//   1. 登録時: URLから章とノード名を決め、各ドキュメントの先頭に見出し「【Houdini 22 / SOP / transform】」を入れ、
//      ファイル名にも章を付ける（「Transform geometry node [SOP]」）。見出しは本文の一部なので、
//      BM25（全文検索）にも、埋め込みにも効く。DBの作り直しも、Vectorizeの設定追加も要らない。
//   2. 検索時: 質問に章の指定（「SOPで」「APEXの」）がある、または呼び出し側が作業場所（context）を渡したときだけ、
//      その章の結果の順位を上げる。除外はしない。判定が外れても、他の章の結果は残る。
//   3. 同名ノードが複数の章に出て、手がかりが無いときは、既定の章で答え、他の章があることを1行添える。
// このファイルは、DBにもネットワークにも触れない純粋な関数だけを置く（単体テストできる）。

export type DocContext =
  | "SOP" | "OBJ" | "VOP" | "DOP" | "LOP" | "TOP" | "CHOP" | "COP2" | "COP" | "ROP" | "APEX" | "SHOP" | "VEX" | "HOM";

// URLのパス（/docs/houdini/nodes/<カテゴリ>/<ノード>）のカテゴリ → 章
const NODE_CATEGORIES: Record<string, DocContext> = {
  sop: "SOP", obj: "OBJ", vop: "VOP", dop: "DOP", lop: "LOP", top: "TOP", chop: "CHOP",
  cop2: "COP2", cop: "COP", out: "ROP", rop: "ROP", apex: "APEX", shop: "SHOP",
};

// 見出しの版。見出しの形や付け方を変えたら上げる（再クロールで、見出しの無い／古い登録を作り直すため）。
export const HEADER_VERSION = 1;

export interface DocInfo {
  context: DocContext;
  /** ノードのタイプ名（URLの最後の部分。例: transform、kinefx::rigpose は kinefx--rigpose） */
  name: string;
}

/** Houdini公式ドキュメントのURLから、章とノード名を決める。対象外のURLは null。 */
export function contextFromUrl(url: string): DocInfo | null {
  let path: string;
  try {
    path = new URL(url).pathname;
  } catch {
    return null;
  }
  const m = path.match(/\/docs\/houdini\/(nodes|vex\/functions|hom\/hou)\/(?:([a-z0-9]+)\/)?([^/]+?)(?:\.html?)?\/?$/i);
  if (!m) return null;
  const [, section, category, rawName] = m;
  const name = decodeURIComponent(rawName).replace(/--/g, "::");
  if (section === "nodes") {
    const context = category ? NODE_CATEGORIES[category.toLowerCase()] : undefined;
    return context ? { context, name } : null;
  }
  if (section.startsWith("vex")) return { context: "VEX", name };
  return { context: "HOM", name };
}

/** 章の版つきの見出し。version は namespace（houdini22）から取った数字。 */
export function docHeader(info: DocInfo, version?: string): string {
  const v = version ? ` ${version}` : "";
  return `【Houdini${v} / ${info.context} / ${info.name}】`;
}

const HEADER_RE = /^【Houdini(?: (\d+))? \/ ([A-Z0-9]+) \/ ([^】\n]+)】/;

/** チャンクの本文の先頭にある見出しから、章とノード名を取り出す。無ければ null。 */
export function parseHeader(text: string): (DocInfo & { version?: string }) | null {
  const m = text.match(HEADER_RE);
  if (!m) return null;
  return { context: m[2] as DocContext, name: m[3].trim(), version: m[1] };
}

/** 見出しがあるか（旧形式の登録を見分ける） */
export function hasHeader(text: string): boolean {
  return HEADER_RE.test(text);
}

/** namespace（shared:houdini22）から版の数字（22）を取る。無ければ undefined。 */
export function versionFromNamespace(namespace: string): string | undefined {
  return namespace.match(/houdini(\d+)/i)?.[1];
}

/** ファイル名（タイトル）に章を付ける。既に付いていれば、そのまま。 */
export function fileNameFor(title: string, info: DocInfo): string {
  const tag = ` [${info.context}]`;
  return title.endsWith(tag) ? title : `${title}${tag}`;
}

/** 登録する本文と、ファイル名。対象外のURLは、タイトルも本文も変えない。 */
export function prepareDocument(
  url: string, title: string, text: string, namespace: string,
): { file: string; text: string; info: DocInfo | null } {
  const info = contextFromUrl(url);
  if (!info) return { file: title, text, info: null };
  return {
    file: fileNameFor(title, info),
    text: `${docHeader(info, versionFromNamespace(namespace))}\n${text}`,
    info,
  };
}

// ── 検索側 ──────────────────────────────────────────────────────────────

// 質問に書かれた章の指定。ASCIIは単語として、日本語は決まった言い方だけ（広く取ると誤判定が増える）。
const CUES: Array<[RegExp, DocContext]> = [
  [/(?<![A-Za-z])SOPs?(?![A-Za-z])|ジオメトリ(?:ノード|レベル)/i, "SOP"],
  [/(?<![A-Za-z])VOPs?(?![A-Za-z])|VOPネット/i, "VOP"],
  [/(?<![A-Za-z])APEX(?![A-Za-z])/i, "APEX"],
  [/(?<![A-Za-z])DOPs?(?![A-Za-z])|ダイナミクスネット/i, "DOP"],
  [/(?<![A-Za-z])LOPs?(?![A-Za-z])|Solaris|ソラリス/i, "LOP"],
  // "top"（「一番上」）は普通の英単語なので、TOPは大文字だけ。
  [/(?<![A-Za-z])TOPs?(?![A-Za-z])|(?<![A-Za-z])[Pp][Dd][Gg](?![A-Za-z])/, "TOP"],
  [/(?<![A-Za-z])CHOPs?(?![A-Za-z])/i, "CHOP"],
  [/(?<![A-Za-z])COP2(?![A-Za-z0-9])/i, "COP2"],
  [/(?<![A-Za-z])COPs?(?![A-Za-z0-9])|Copernicus|コペルニクス/i, "COP"],
  [/(?<![A-Za-z])OBJ(?![A-Za-z])|オブジェクトレベル/i, "OBJ"],
  [/(?<![A-Za-z])ROPs?(?![A-Za-z])/i, "ROP"],
  [/(?<![A-Za-z])VEX(?![A-Za-z])/i, "VEX"],
  [/(?<![A-Za-z])hou\./i, "HOM"],
];

/** 質問文にある、明示的な章の指定（複数あれば、全部）。 */
export function detectContextCues(query: string): DocContext[] {
  const found: DocContext[] = [];
  for (const [re, ctx] of CUES) if (re.test(query) && !found.includes(ctx)) found.push(ctx);
  return found;
}

/** 呼び出し側が渡した context（"sop" / ["SOP","APEX"]）を、正規の章の一覧にする。知らない値は捨てる。 */
export function normalizeContextHint(raw: unknown): DocContext[] {
  const list = Array.isArray(raw) ? raw : typeof raw === "string" ? raw.split(/[,\s]+/) : [];
  const valid = new Set<string>([...Object.values(NODE_CATEGORIES), "VEX", "HOM"]);
  const out: DocContext[] = [];
  for (const item of list) {
    const up = String(item).trim().toUpperCase();
    const ctx = (up === "COPERNICUS" ? "COP" : up) as DocContext;
    if (valid.has(ctx) && !out.includes(ctx)) out.push(ctx);
  }
  return out;
}

/** 手がかりが無いときの既定の章の優先順。モデリング系の質問が多いので SOP を先頭にする。 */
export const DEFAULT_CONTEXT_ORDER: DocContext[] = ["SOP", "OBJ", "VOP", "DOP", "LOP", "COP", "TOP", "CHOP", "APEX", "ROP", "SHOP", "COP2", "VEX", "HOM"];

interface ScoredChunk { metadata: { text: string }; score?: number }

/**
 * 章の指定（質問の中、または呼び出し側）があるとき、その章のチャンクを先に並べ、残りをその後ろに並べる。
 * 除外はしない（章の指定が外れていても、他の章の結果は残る）。それぞれの中の順は、元の順位のまま。
 * 点数を掛ける方式だと、順位が離れた正解（例: ベクトル検索の3位だけに出た章）を、既に上位にいる別の章の
 * 結果の上へ動かせないので、並べ方で決める。見出しの無いチャンク（他の種類の文書・旧形式の登録）は、
 * 「指定した章ではないもの」として後ろに回る。
 */
export function boostByContext<T extends ScoredChunk>(ranked: T[], contexts: DocContext[]): T[] {
  if (contexts.length === 0) return ranked;
  const hits: T[] = [];
  const rest: T[] = [];
  for (const chunk of ranked) {
    const header = parseHeader(chunk.metadata.text);
    (header !== null && contexts.includes(header.context) ? hits : rest).push(chunk);
  }
  return [...hits, ...rest];
}

export interface Ambiguity {
  name: string;
  contexts: DocContext[];
}

/** 同じノード名が、複数の章で見つかっているもの（章の指定が無いとき、答えがぶれる原因）。 */
export function findAmbiguities(ranked: Array<{ metadata: { text: string } }>): Ambiguity[] {
  const byName = new Map<string, Set<DocContext>>();
  for (const chunk of ranked) {
    const header = parseHeader(chunk.metadata.text);
    if (!header) continue;
    const key = header.name.toLowerCase();
    if (!byName.has(key)) byName.set(key, new Set());
    byName.get(key)!.add(header.context);
  }
  const out: Ambiguity[] = [];
  for (const [name, set] of byName) {
    if (set.size >= 2) {
      out.push({ name, contexts: DEFAULT_CONTEXT_ORDER.filter((c) => set.has(c)) });
    }
  }
  return out;
}

/** 既定の章（手がかり → なければ優先順の先頭）。 */
export function defaultContext(candidates: DocContext[], hint: DocContext[]): DocContext | undefined {
  for (const h of hint) if (candidates.includes(h)) return h;
  return DEFAULT_CONTEXT_ORDER.find((c) => candidates.includes(c));
}

/**
 * 検索結果の前に付ける注意書き。章の指定が無く、同名ノードが複数の章にあるときだけ出す。
 * 回答側は、既定の章で答え、前提と、他の章があることを1行で伝える（buildAnswerPrompt。毎回同じ形になり、ぶれない）。
 */
export function ambiguityNote(ranked: Array<{ metadata: { text: string } }>, specified: DocContext[]): string {
  if (specified.length > 0) return "";
  const items = findAmbiguities(ranked);
  if (items.length === 0) return "";
  const lines = items.slice(0, 3).map((a) => {
    const chosen = defaultContext(a.contexts, []);
    return `「${a.name}」は ${a.contexts.join(" / ")} にあります（既定: ${chosen}）`;
  });
  return (
    "注意（章の曖昧さ）: " + lines.join("。") +
    "。質問に章の指定が無いので、既定の章の内容を使い、他の章の内容を混ぜないこと。"
  );
}
