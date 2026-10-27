import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { requireAdmin } from "./auth";
import { buildProfile, type TermRow } from "./growth";

// 実証実験の集計（2026-10-27）。Houdini のパネルから上がった評価や利用を、管理画面の「実証実験」で1か所に集める。
//   ・管理者だけ（requireAdmin）。管理者アカウント自身の利用（運営のテスト）は、数えない。
//   ・参加者ごとの表は、利用回数と評価だけ。習熟度（用語）は、人を特定できる形では出さない。
//   ・習熟度の分布と、よく使われた用語は、匿名の集計だけ。参加者が少ない（MIN_GROUP 人未満）ときは、出さない
//     （少人数だと、集計から個人が分かってしまうため）。用語も、2人以上が使ったものだけ。
export const MIN_GROUP = 3;
const MIN_USERS_PER_TERM = 2;

function clampDays(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? Math.min(365, Math.max(1, Math.floor(n))) : 30;
}

const rate = (good: number, bad: number): number | null =>
  good + bad === 0 ? null : good / (good + bad);

interface Bucket {
  key: string;
  total: number;
  good: number;
  bad: number;
  goodRate: number | null;
}

function bucket(key: string, total: number, good: number, bad: number): Bucket {
  return {
    key,
    total,
    good: good ?? 0,
    bad: bad ?? 0,
    goodRate: rate(good ?? 0, bad ?? 0),
  };
}

// POST /admin/pilot/summary { days } — 実証実験の集計（管理者だけ）
export async function handlePilotSummary(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { days?: number };
  const days = clampDays(body.days);
  const since = Math.floor(Date.now() / 1000) - days * 86400;

  // 参加者ごと（管理者以外）。期間内に、質問か評価があった人だけ。
  const participantsRes = await env.DB.prepare(
    `SELECT u.user_id AS userId, u.display_name AS displayName, u.role AS role,
       (SELECT COUNT(*) FROM memory m WHERE m.user_id = u.user_id AND m.created_at >= ?) AS questions,
       (SELECT MAX(m.created_at) FROM memory m WHERE m.user_id = u.user_id) AS lastQuestionAt,
       (SELECT COUNT(*) FROM memory m WHERE m.user_id = u.user_id AND m.created_at >= ? AND m.rating = 1) AS chatGood,
       (SELECT COUNT(*) FROM memory m WHERE m.user_id = u.user_id AND m.created_at >= ? AND m.rating = -1) AS chatBad,
       (SELECT COUNT(*) FROM tutorial_feedback f WHERE f.user_id = u.user_id AND f.updated_at >= ? AND f.rating = 1) AS tutorialGood,
       (SELECT COUNT(*) FROM tutorial_feedback f WHERE f.user_id = u.user_id AND f.updated_at >= ? AND f.rating = -1) AS tutorialBad
     FROM users u
     WHERE u.role != 'admin'
     ORDER BY questions DESC, u.display_name`,
  )
    .bind(since, since, since, since, since)
    .all<{
      userId: string;
      displayName: string | null;
      role: string;
      questions: number;
      lastQuestionAt: number | null;
      chatGood: number;
      chatBad: number;
      tutorialGood: number;
      tutorialBad: number;
    }>();
  const participants = (participantsRes.results ?? []).filter(
    (p) => p.questions + p.tutorialGood + p.tutorialBad > 0,
  );

  // 説明レベルごとのチャット評価（管理者以外）
  const explainRes = await env.DB.prepare(
    `SELECT COALESCE(m.explain_level, '指定なし') AS k, COUNT(*) AS total,
       SUM(CASE WHEN m.rating = 1 THEN 1 ELSE 0 END) AS good, SUM(CASE WHEN m.rating = -1 THEN 1 ELSE 0 END) AS bad
     FROM memory m JOIN users u ON u.user_id = m.user_id
     WHERE m.created_at >= ? AND u.role != 'admin'
     GROUP BY k ORDER BY total DESC`,
  )
    .bind(since)
    .all<{ k: string; total: number; good: number; bad: number }>();

  // チュートリアルの評価（段階別・Houdiniの版別。管理者以外）
  const tutorialBy = async (column: "level" | "houdini_version") =>
    (
      await env.DB.prepare(
        `SELECT COALESCE(NULLIF(f.${column}, ''), '（不明）') AS k, COUNT(*) AS total,
           SUM(CASE WHEN f.rating = 1 THEN 1 ELSE 0 END) AS good, SUM(CASE WHEN f.rating = -1 THEN 1 ELSE 0 END) AS bad
         FROM tutorial_feedback f JOIN users u ON u.user_id = f.user_id
         WHERE f.updated_at >= ? AND u.role != 'admin'
         GROUP BY k ORDER BY total DESC`,
      )
        .bind(since)
        .all<{ k: string; total: number; good: number; bad: number }>()
    ).results ?? [];
  const tutorialByLevel = await tutorialBy("level");
  const tutorialByHoudini = await tutorialBy("houdini_version");

  const sum = (rows: Array<{ total: number; good: number; bad: number }>) =>
    rows.reduce(
      (acc, r) => ({
        total: acc.total + r.total,
        good: acc.good + (r.good ?? 0),
        bad: acc.bad + (r.bad ?? 0),
      }),
      { total: 0, good: 0, bad: 0 },
    );
  const chatTotals = sum(explainRes.results ?? []);
  const tutorialTotals = sum(tutorialByLevel);

  // 習熟度の分布と、よく使われた用語（匿名の集計だけ）
  const termsRes = await env.DB.prepare(
    `SELECT t.user_id AS userId, t.term AS term, t.count AS count
     FROM user_terms t JOIN users u ON u.user_id = t.user_id WHERE u.role != 'admin'`,
  ).all<{ userId: string; term: string; count: number }>();
  const byUser = new Map<string, TermRow[]>();
  for (const row of termsRes.results ?? []) {
    if (!byUser.has(row.userId)) byUser.set(row.userId, []);
    byUser.get(row.userId)!.push({ term: row.term, count: row.count });
  }
  let growth: Record<string, unknown>;
  if (byUser.size < MIN_GROUP) {
    growth = {
      hidden: true,
      reason: `習熟度を記録している参加者が${MIN_GROUP}人未満のため、個人が特定されないよう、表示しません（現在 ${byUser.size}人）`,
    };
  } else {
    const levels = { basic: 0, applied: 0, advanced: 0 };
    let termTotal = 0;
    const termStats = new Map<string, { users: number; total: number }>();
    for (const rows of byUser.values()) {
      levels[buildProfile(rows, []).scoreLevel] += 1;
      termTotal += rows.length;
      for (const r of rows) {
        const s = termStats.get(r.term) ?? { users: 0, total: 0 };
        s.users += 1;
        s.total += r.count;
        termStats.set(r.term, s);
      }
    }
    growth = {
      hidden: false,
      users: byUser.size,
      levels,
      avgTerms: Math.round((termTotal / byUser.size) * 10) / 10,
      topTerms: [...termStats.entries()]
        .filter(([, s]) => s.users >= MIN_USERS_PER_TERM)
        .map(([term, s]) => ({ term, users: s.users, total: s.total }))
        .sort((a, b) => b.users - a.users || b.total - a.total)
        .slice(0, 20),
    };
  }

  return jsonResponse(200, {
    status: "ok",
    days,
    minGroup: MIN_GROUP,
    kpis: {
      participants: participants.length,
      questions: participants.reduce((a, p) => a + p.questions, 0),
      chatRated: chatTotals.good + chatTotals.bad,
      chatGoodRate: rate(chatTotals.good, chatTotals.bad),
      tutorialRated: tutorialTotals.good + tutorialTotals.bad,
      tutorialGoodRate: rate(tutorialTotals.good, tutorialTotals.bad),
    },
    participants,
    byExplain: (explainRes.results ?? []).map((r) =>
      bucket(r.k, r.total, r.good, r.bad),
    ),
    tutorialByLevel: tutorialByLevel.map((r) =>
      bucket(r.k, r.total, r.good, r.bad),
    ),
    tutorialByHoudini: tutorialByHoudini.map((r) =>
      bucket(r.k, r.total, r.good, r.bad),
    ),
    growth,
  });
}
