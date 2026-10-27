import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { findTerms, levelPoints, termByName, type TermLevel } from "./glossary";

// 説明のレベルと、成長機能（2026-10-27追加）。
//   ・質問に explain を付けると、回答の説明の深さと専門用語の量を、そのレベルに合わせる。
//       "basic" | "applied" | "advanced" … 固定  /  "auto"（おまかせ）… 質問の蓄積から決める（成長）
//     explain を付けない質問は、これまでどおり（説明のレベルの指示も、用語の記録もしない）。
//   ・成長: 質問に使った専門用語（辞書 src/glossary.ts）と回数を、利用者ごとに蓄積する（質問の全文は保存しない）。
//       使った用語の「段階の点」の合計（同じ用語は3回までを数える）が、しきい値を超えると、おまかせのレベルが上がる。
//       「役に立たなかった」の評価が直近3件とも続くときは、一段やさしくする。
//       2回以上使った用語は「使いこなしている」として、説明を省く。次の段階の用語を、検索結果に出てくる範囲で、1〜2個だけ紹介する。
//   ・本人だけが、自分の習熟度を見られる・消せる（/me/growth、/me/growth/reset）。
export type ExplainRequest = "auto" | TermLevel;

const LEVELS: TermLevel[] = ["basic", "applied", "advanced"];
export const THRESHOLD_APPLIED = 6;
export const THRESHOLD_ADVANCED = 18;
export const KNOWN_COUNT = 2; // この回数以上使った用語は、使いこなしているとみなす
const MAX_TERMS_PER_QUERY = 12;

export const EXPLAIN_STYLE: Record<TermLevel, string> = {
  basic:
    "専門用語は最小限にし、使うときは、初めて出たところで短い説明（かっこ書き）を添えてください。操作は順番に、ひとつずつ。身近なたとえを使ってよいです。前提知識は仮定しないでください。",
  applied:
    "よく使うHoudiniの用語（SOP・アトリビュート・VEXなど）は、説明なしで使ってよいです。操作の手順だけでなく、なぜそうするのか（仕組みと理由）と、つまずきやすい点も書いてください。",
  advanced:
    "専門用語はそのまま使い、基本の説明は省いてください。内部の仕組み、パフォーマンス、設計上のトレードオフ、代わりの方法と使い分けも書いてください。簡潔に、密度高く。",
};

export function parseExplain(value: unknown): ExplainRequest | null {
  if (value === "auto" || value === "basic" || value === "applied" || value === "advanced") return value;
  return null;
}

export interface TermRow {
  term: string;
  count: number;
}

export interface GrowthProfile {
  level: TermLevel; // おまかせで使うレベル（評価での調整後）
  scoreLevel: TermLevel; // 用語の点だけで決まるレベル
  score: number;
  nextAt: number | null; // 次のレベルになる点（最上位は null）
  termCount: number; // これまでに使った用語の数
  knownTerms: Array<{ term: string; level: TermLevel; count: number }>; // 使いこなしている用語（段階の高い順）
  lowered: boolean; // 「役に立たなかった」が続いて、一段やさしくした
}

export function scoreOf(rows: TermRow[]): number {
  let total = 0;
  for (const row of rows) {
    const term = termByName(row.term);
    if (!term) continue; // 辞書から消えた用語は数えない
    total += (levelPoints(term.level) * Math.min(row.count, 3)) / 3;
  }
  return Math.round(total * 10) / 10;
}

export function levelForScore(score: number): TermLevel {
  return score >= THRESHOLD_ADVANCED ? "advanced" : score >= THRESHOLD_APPLIED ? "applied" : "basic";
}

export function buildProfile(rows: TermRow[], recentRatings: number[]): GrowthProfile {
  const score = scoreOf(rows);
  const scoreLevel = levelForScore(score);
  const lowered = recentRatings.length >= 3 && recentRatings.slice(0, 3).every((r) => r === -1) && scoreLevel !== "basic";
  const level = lowered ? LEVELS[LEVELS.indexOf(scoreLevel) - 1] : scoreLevel;
  const known = rows
    .filter((r) => r.count >= KNOWN_COUNT && termByName(r.term))
    .map((r) => ({ term: r.term, level: termByName(r.term)!.level, count: r.count }))
    .sort((a, b) => LEVELS.indexOf(b.level) - LEVELS.indexOf(a.level) || b.count - a.count);
  return {
    level,
    scoreLevel,
    score,
    nextAt: scoreLevel === "basic" ? THRESHOLD_APPLIED : scoreLevel === "applied" ? THRESHOLD_ADVANCED : null,
    termCount: rows.filter((r) => termByName(r.term)).length,
    knownTerms: known,
    lowered,
  };
}

export async function loadGrowth(env: Env, userId: string): Promise<GrowthProfile> {
  const [terms, ratings] = await Promise.all([
    env.DB.prepare("SELECT term, count FROM user_terms WHERE user_id = ?").bind(userId).all<TermRow>(),
    env.DB.prepare("SELECT rating FROM memory WHERE user_id = ? AND rating IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 3")
      .bind(userId)
      .all<{ rating: number }>(),
  ]);
  return buildProfile(terms.results ?? [], (ratings.results ?? []).map((r) => r.rating));
}

// 質問に使った辞書の用語を、数える（質問の全文は保存しない）。
export async function recordQueryTerms(env: Env, userId: string, query: string): Promise<string[]> {
  const found = findTerms(query).slice(0, MAX_TERMS_PER_QUERY);
  const now = Math.floor(Date.now() / 1000);
  if (found.length > 0) {
    // 1回の往復でまとめて書く（用語ごとに待たない）
    await env.DB.batch(
      found.map((term) =>
        env.DB.prepare(
          `INSERT INTO user_terms (user_id, term, count, first_seen, last_seen) VALUES (?, ?, 1, ?, ?)
           ON CONFLICT(user_id, term) DO UPDATE SET count = count + 1, last_seen = excluded.last_seen`,
        ).bind(userId, term.term, now, now),
      ),
    );
  }
  return found.map((t) => t.term);
}

export interface ExplainPlan {
  level: TermLevel;
  mode: "auto" | "fixed";
  note: string; // 回答のプロンプトに足す指示
  candidates: string[]; // 今回、紹介してよいと伝えた用語（実際に回答に出たかは、あとで確かめる）
  score: number;
}

// 回答のプロンプトに足す、説明のレベルの指示。おまかせのときだけ、使いこなしている用語と、紹介する用語を添える。
export function buildExplainPlan(requested: ExplainRequest, profile: GrowthProfile | null, contextTexts: string[]): ExplainPlan {
  const mode = requested === "auto" ? "auto" : "fixed";
  const level: TermLevel = requested === "auto" ? (profile?.level ?? "basic") : requested;
  const lines = [`【説明のレベル: ${level}${mode === "auto" ? "（おまかせ。これまでの質問から決めました）" : ""}】`, EXPLAIN_STYLE[level]];
  let candidates: string[] = [];
  if (mode === "auto" && profile) {
    const known = profile.knownTerms.slice(0, 12).map((k) => k.term);
    if (known.length > 0) lines.push(`利用者がすでに使いこなしている用語（説明は省いてよい）: ${known.join("、")}`);
    // 次の段階へ: 検索結果に出てくる、まだ使いこなしていない用語を、1〜2個。今のレベルの1つ上までに限る。
    const knownSet = new Set(profile.knownTerms.map((k) => k.term));
    const ceiling = Math.min(LEVELS.indexOf(level) + 1, LEVELS.length - 1);
    const pool = findTerms(contextTexts.join("\n"))
      .filter((t) => !knownSet.has(t.term) && LEVELS.indexOf(t.level) <= ceiling)
      .sort((a, b) => LEVELS.indexOf(b.level) - LEVELS.indexOf(a.level));
    candidates = pool.slice(0, 2).map((t) => t.term);
    if (candidates.length > 0) {
      lines.push(
        `今回の回答で、次の用語を、自然に紹介してよいです（検索結果に書かれている範囲で。利用者が初めて見る用語なので、かっこ書きで短い説明を添えてください）: ${candidates.join("、")}`,
      );
    }
  }
  return { level, mode, note: "\n" + lines.join("\n") + "\n", candidates, score: profile?.score ?? 0 };
}

// 回答に実際に出た用語だけを、「今回紹介した用語」として返す。
export function introducedIn(answer: string, candidates: string[]): string[] {
  if (candidates.length === 0) return [];
  const present = new Set(findTerms(answer).map((t) => t.term));
  return candidates.filter((c) => present.has(c));
}

// POST /me/growth — 自分の習熟度（本人だけ）
export async function handleMyGrowth(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const profile = await loadGrowth(env, user.userId);
  return jsonResponse(200, { status: "ok", ...profile, thresholds: { applied: THRESHOLD_APPLIED, advanced: THRESHOLD_ADVANCED } });
}

// POST /me/growth/reset — 自分の用語の記録を消す（本人だけ）
export async function handleMyGrowthReset(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const result = await env.DB.prepare("DELETE FROM user_terms WHERE user_id = ?").bind(user.userId).run();
  return jsonResponse(200, { status: "ok", deleted: result.meta?.changes ?? 0 });
}
