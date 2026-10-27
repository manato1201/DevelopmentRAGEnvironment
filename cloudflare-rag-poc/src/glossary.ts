// Houdini の用語辞書（成長機能用。2026-10-27追加）。質問文に出てきた用語を数えて、利用者の習熟度の目安にする。
//
// level: その用語を使いこなすのに必要な段階の目安（basic < applied < advanced）。チュートリアルの3段階と同じ名前。
// aliases: 同じ意味の別の書き方（英語・カタカナ・略称）。英数字の語は、前後が英数字でないときだけ一致とする
// （"top" のような一般の語に反応しないよう、TOP は「TOPs」「TOPネットワーク」などの形だけを入れている）。
// 辞書は、判断の目安のためのもの（網羅ではない）。足すときは、ここに1行足すだけ。
export type TermLevel = "basic" | "applied" | "advanced";

export interface GlossaryTerm {
  term: string; // 表示名（正）
  level: TermLevel;
  aliases: string[];
}

const t = (term: string, level: TermLevel, ...aliases: string[]): GlossaryTerm => ({ term, level, aliases: [term, ...aliases] });

export const HOUDINI_TERMS: GlossaryTerm[] = [
  // basic: 画面・基本の操作と、よく使うノード
  t("ノード", "basic", "node", "nodes"),
  t("ネットワーク", "basic", "network"),
  t("パラメータ", "basic", "parameter", "parm", "パラメーター"),
  t("ジオメトリ", "basic", "geometry", "geo"),
  t("SOP", "basic", "sops", "surface operator", "サーフェスオペレータ"),
  t("オブジェクト", "basic", "obj", "object"),
  t("ポリゴン", "basic", "polygon"),
  t("プリミティブ", "basic", "primitive", "prim"),
  t("グループ", "basic", "group"),
  t("トランスフォーム", "basic", "transform"),
  t("ビューポート", "basic", "viewport"),
  t("シェルフ", "basic", "shelf"),
  t("マテリアル", "basic", "material", "shader", "シェーダ"),
  t("カメラ", "basic", "camera"),
  t("ライト", "basic", "light"),
  t("UV", "basic", "uvs"),
  t("法線", "basic", "normal", "ノーマル"),
  t("Merge", "basic", "マージ"),
  t("Scatter", "basic", "スキャッター"),
  t("Copy to Points", "basic", "copytopoints", "コピートゥポイント"),
  t("Mountain", "basic", "マウンテン"),
  t("Null", "basic", "ヌル"),
  t("Subnet", "basic", "サブネット", "subnetwork"),
  t("ジオメトリスプレッドシート", "basic", "geometry spreadsheet", "スプレッドシート"),
  // applied: データと手続きの理解（属性・VEX・ソルバー・アセット）
  t("アトリビュート", "applied", "attribute", "attributes", "attrib", "属性"),
  t("ポイント", "applied", "point"),
  t("Attribute Wrangle", "applied", "wrangle", "ランゴル", "ラングル", "attribwrangle", "アトリビュートランゴル"),
  t("VEX", "applied", "vex"),
  t("VOP", "applied", "vops", "vop network"),
  t("HDA", "applied", "digital asset", "デジタルアセット", "hdas", "otl"),
  t("エクスプレッション", "applied", "expression", "hscript"),
  t("チャンネル", "applied", "channel"),
  t("ランプ", "applied", "ramp"),
  t("ForEach", "applied", "for-each", "for each", "フォーイーチ", "foreach", "ループ", "loop"),
  t("パックドプリミティブ", "applied", "packed primitive", "packed", "パック"),
  t("インスタンス", "applied", "instance", "instancing", "インスタンシング"),
  t("DOP", "applied", "dops", "dynamics", "ダイナミクス"),
  t("ソルバー", "applied", "solver", "sop solver"),
  t("POP", "applied", "pops", "particle", "パーティクル"),
  t("Pyro", "applied", "パイロ"),
  t("FLIP", "applied", "フリップ"),
  t("Vellum", "applied", "ベラム"),
  t("RBD", "applied", "rigid body", "リジッドボディ", "剛体"),
  t("ボリューム", "applied", "volume"),
  t("VDB", "applied", "vdbs"),
  t("SDF", "applied", "signed distance"),
  t("キャッシュ", "applied", "cache", "bgeo", "file cache"),
  t("ROP", "applied", "rops", "render output"),
  t("Karma", "applied", "カルマ"),
  t("COP", "applied", "cops"),
  t("Python SOP", "applied", "python sop", "pythonsop"),
  // advanced: パイプライン・USD・高度な最適化と拡張
  t("PDG", "advanced", "procedural dependency graph", "tops", "top network", "topネットワーク", "top ノード", "topノード"),
  t("ワークアイテム", "advanced", "work item", "workitem"),
  t("LOP", "advanced", "lops", "solaris", "ソラリス"),
  t("USD", "advanced", "usds", "usda", "usdc"),
  t("マルチパーム", "advanced", "multiparm", "multi parm", "multiparameter"),
  t("Compile Block", "advanced", "compile block", "コンパイルブロック"),
  t("KineFX", "advanced", "キネFX", "キネエフエックス"),
  t("APEX", "advanced", "エイペックス"),
  t("Copernicus", "advanced", "コペルニクス"),
  t("CHOP", "advanced", "chops"),
  t("Houdini Engine", "advanced", "houdini engine", "ヒューディーニエンジン"),
  t("OpenCL", "advanced", "opencl"),
  t("HDK", "advanced", "hdk"),
  t("HQueue", "advanced", "hqueue", "tractor", "トラクター"),
  t("Sparse Pyro", "advanced", "sparse pyro", "スパースパイロ"),
  t("MPM", "advanced", "mpm"),
  t("Constraint Network", "advanced", "constraint network", "コンストレイントネットワーク"),
  t("Attribute Transfer", "advanced", "attribute transfer", "アトリビュートトランスファー", "attribtransfer"),
  t("Volume Wrangle", "advanced", "volume wrangle", "ボリュームランゴル"),
  t("Detail Attribute", "advanced", "detail attribute", "ディテールアトリビュート"),
];

const LEVEL_POINTS: Record<TermLevel, number> = { basic: 1, applied: 2, advanced: 3 };
export function levelPoints(level: TermLevel): number {
  return LEVEL_POINTS[level];
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// 英数字だけの別名は、前後が英数字・アンダースコアでないときだけ一致にする。日本語・記号を含む別名は、そのまま含まれていれば一致。
const MATCHERS: Array<{ term: GlossaryTerm; patterns: RegExp[] }> = HOUDINI_TERMS.map((term) => ({
  term,
  patterns: term.aliases.map((alias) => {
    const body = escapeRegExp(alias.toLowerCase());
    return /^[a-z0-9_ ]+$/i.test(alias) ? new RegExp(`(?<![a-z0-9_])${body}(?![a-z0-9_])`, "gi") : new RegExp(body, "gi");
  }),
}));

// 文章に出てくる辞書の用語を、重複なしで返す（辞書の順）。
// 長い用語の一部になっている短い用語は、数えない（「Attribute Wrangle」の attribute を、アトリビュートとして二重に数えない）。
export function findTerms(text: string): GlossaryTerm[] {
  const lower = String(text || "").toLowerCase();
  if (!lower) return [];
  const spans: Array<{ term: GlossaryTerm; start: number; end: number }> = [];
  for (const { term, patterns } of MATCHERS) {
    for (const pattern of patterns) {
      for (const m of lower.matchAll(pattern)) {
        if (m[0].length > 0) spans.push({ term, start: m.index ?? 0, end: (m.index ?? 0) + m[0].length });
      }
    }
  }
  const kept = spans.filter((a) => !spans.some((b) => b.term !== a.term && b.start <= a.start && b.end >= a.end && b.end - b.start > a.end - a.start));
  const found = new Set(kept.map((x) => x.term));
  return HOUDINI_TERMS.filter((term) => found.has(term));
}

export function termByName(name: string): GlossaryTerm | undefined {
  return HOUDINI_TERMS.find((x) => x.term === name);
}
