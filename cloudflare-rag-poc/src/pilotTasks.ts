import type { AuthedUser, Env } from "./types";
import { clampInt, jsonResponse } from "./http";
import { requireAdmin } from "./auth";

// 実証実験の課題の記録とアンケート（2026-10-28）。設計: docs/pilot-analysis-design.md
//
//   ・参加者は、事前アンケートで登録する。登録順の匿名番号（pid）から、割り当て番号 slot（1〜3）が決まる。
//   ・固定課題の題材は、回ごとに違う（Pyro・RBD・雲）。slot ごとに順序をずらす（ラテン方格）。
//   ・3回のうち1回（回 = slot）だけ、固定課題を「公式ドキュメント・Web検索のみ」で行う（参加者の中の対照）。
//   ・各回に、固定課題と自由課題を1つずつ。終了時に、課題後アンケートと、到達・自己申告のミスを送る。
//   ・所要時間は、サーバーの時刻（開始・終了）から出す。質問回数は、その時間内の質問（memory）の数で、サーバーが数える
//     （画面からの申告に頼らない。「公式ドキュメントのみ」の回に質問が混ざったかも、これで分かる）。
//   ・集計は管理者だけ。氏名は出さず、P01 のような番号で出す。管理者の記録は、集計に入れない。

export type TaskId = "pyro" | "rbd" | "cloud";
export type Kind = "fixed" | "free";
export type Condition = "system" | "docs_only";

export const ROUNDS = 3;
export const TASKS: Record<TaskId, string> = {
  pyro: "Pyro（煙・炎のシミュレーション）",
  rbd: "RBD（剛体・破壊のシミュレーション）",
  cloud: "雲（パーティクルでの雲の制作）",
};
// slot → 回ごとの固定課題。どの課題も、どの回も、対照（公式ドキュメントのみ）に1度ずつ当たる。
export const LATIN: Record<number, TaskId[]> = {
  1: ["pyro", "rbd", "cloud"],
  2: ["rbd", "cloud", "pyro"],
  3: ["cloud", "pyro", "rbd"],
};
export const CRITERION = "課題の題材として、作品物ができていること";

// 操作ミス = メカニクス面（cookエラー）7割 + ビジュアル操作面（自己申告）3割。どちらも 0〜1 にそろえてから合わせる。
export const MISTAKE_WEIGHT_COOK = 0.7;
export const MISTAKE_WEIGHT_SELF = 0.3;
export const COOK_ERROR_CAP = 10; // cookエラーが出たノードがこの数以上なら、1（最大）として扱う

const SURVEY_FIELDS = ["difficulty", "clarity", "focus", "accuracyWorry", "sourceUseful", "reuse"] as const;
type SurveyField = (typeof SURVEY_FIELDS)[number];
const SURVEY_COLUMN: Record<SurveyField, string> = {
  difficulty: "difficulty",
  clarity: "clarity",
  focus: "focus",
  accuracyWorry: "accuracy_worry",
  sourceUseful: "source_useful",
  reuse: "reuse",
};

export function slotForPid(pid: number): number {
  return ((pid - 1) % 3) + 1;
}

// 操作ミスのスコア（0〜1。大きいほどミスが多い）。どちらかが無いときは null（片方だけで代用しない）。
export function mistakeScore(cookErrorNodes: number | null | undefined, selfMistakes: number | null | undefined): number | null {
  if (typeof cookErrorNodes !== "number" || typeof selfMistakes !== "number") return null;
  const cook = Math.min(Math.max(cookErrorNodes, 0), COOK_ERROR_CAP) / COOK_ERROR_CAP;
  const self = (Math.min(Math.max(selfMistakes, 1), 5) - 1) / 4;
  return Math.round((MISTAKE_WEIGHT_COOK * cook + MISTAKE_WEIGHT_SELF * self) * 1000) / 1000;
}

export interface PlanSession {
  round: number;
  kind: Kind;
  ended_at: number | null;
}

export interface TaskPlanItem {
  kind: Kind;
  taskId: TaskId | "free";
  label: string;
  condition: Condition;
  done: boolean;
  active: boolean; // 開始したが、まだ終えていない
}

export interface TaskPlan {
  slot: number;
  round: number;
  completedRounds: number;
  finished: boolean;
  fixed: TaskPlanItem;
  free: TaskPlanItem;
  criterion: string;
}

export function buildPlan(slot: number, sessions: PlanSession[]): TaskPlan {
  const done = (round: number, kind: Kind) => sessions.some((s) => s.round === round && s.kind === kind && s.ended_at != null);
  const active = (round: number, kind: Kind) => sessions.some((s) => s.round === round && s.kind === kind && s.ended_at == null);
  let completed = 0;
  while (completed < ROUNDS && done(completed + 1, "fixed") && done(completed + 1, "free")) completed++;
  const round = Math.min(completed + 1, ROUNDS);
  const order = LATIN[slot] ?? LATIN[1];
  const taskId = order[round - 1];
  return {
    slot,
    round,
    completedRounds: completed,
    finished: completed >= ROUNDS,
    fixed: { kind: "fixed", taskId, label: TASKS[taskId], condition: round === slot ? "docs_only" : "system", done: done(round, "fixed"), active: active(round, "fixed") },
    free: { kind: "free", taskId: "free", label: "自分の作りたいもの", condition: "system", done: done(round, "free"), active: active(round, "free") },
    criterion: CRITERION,
  };
}

// ---- 集計（純関数） ----

export interface TaskRow {
  pid: number;
  round: number;
  kind: Kind;
  taskId: string;
  condition: Condition;
  durationSec: number | null;
  queryCount: number | null;
  cookErrorNodes: number | null;
  reached: number | null;
  selfMistakes: number | null;
  difficulty: number | null;
  clarity: number | null;
  focus: number | null;
  accuracyWorry: number | null;
  sourceUseful: number | null;
  reuse: number | null;
  comment: string;
}

export function median(values: Array<number | null | undefined>): number | null {
  const xs = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v)).sort((a, b) => a - b);
  if (xs.length === 0) return null;
  const mid = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
}

// 対応のある rank-biserial 相関（Wilcoxon の符号付き順位から。-1〜1。0の差は除く。同順位は平均順位）。
export function pairedRankBiserial(diffs: number[]): number | null {
  const nonzero = diffs.filter((d) => d !== 0 && Number.isFinite(d));
  if (nonzero.length === 0) return null;
  const sorted = nonzero.map((d) => ({ d, a: Math.abs(d) })).sort((x, y) => x.a - y.a);
  const ranks = new Array<number>(sorted.length);
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1].a === sorted[i].a) j++;
    const avg = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) ranks[k] = avg;
    i = j + 1;
  }
  let plus = 0;
  let minus = 0;
  sorted.forEach((s, i) => (s.d > 0 ? (plus += ranks[i]) : (minus += ranks[i])));
  return Math.round(((plus - minus) / (plus + minus)) * 1000) / 1000;
}

const withMistake = (r: TaskRow) => mistakeScore(r.cookErrorNodes, r.selfMistakes);
const minutes = (r: TaskRow) => (r.durationSec == null ? null : Math.round((r.durationSec / 60) * 10) / 10);

const PAIRED_METRICS: Array<{ key: string; label: string; better: "lower" | "higher"; value: (r: TaskRow) => number | null }> = [
  { key: "difficulty", label: "難しさ（1〜5）", better: "lower", value: (r) => r.difficulty },
  { key: "clarity", label: "わかりやすさ（1〜5）", better: "higher", value: (r) => r.clarity },
  { key: "durationMin", label: "所要時間（分）", better: "lower", value: minutes },
  { key: "mistake", label: "操作ミス（0〜1）", better: "lower", value: withMistake },
  { key: "reached", label: "到達（0/1）", better: "higher", value: (r) => r.reached },
];

export function summarizeTasks(rows: TaskRow[]) {
  // 回 × 種類 × 条件ごとの中央値
  const groups = new Map<string, TaskRow[]>();
  for (const r of rows) {
    const key = `${r.round}|${r.kind}|${r.condition}`;
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  const byGroup = [...groups.entries()]
    .map(([key, items]) => {
      const [round, kind, condition] = key.split("|");
      const reachedKnown = items.filter((i) => i.reached != null);
      return {
        round: Number(round),
        kind,
        condition,
        n: items.length,
        tasks: [...new Set(items.map((i) => i.taskId))],
        reachedRate: reachedKnown.length ? reachedKnown.filter((i) => i.reached === 1).length / reachedKnown.length : null,
        median: {
          difficulty: median(items.map((i) => i.difficulty)),
          clarity: median(items.map((i) => i.clarity)),
          focus: median(items.map((i) => i.focus)),
          accuracyWorry: median(items.map((i) => i.accuracyWorry)),
          sourceUseful: median(items.map((i) => i.sourceUseful)),
          reuse: median(items.map((i) => i.reuse)),
          durationMin: median(items.map(minutes)),
          queries: median(items.map((i) => i.queryCount)),
          mistake: median(items.map(withMistake)),
        },
      };
    })
    .sort((a, b) => a.round - b.round || a.kind.localeCompare(b.kind) || a.condition.localeCompare(b.condition));

  // 対照（公式ドキュメントのみ）と、本システムの比較。固定課題だけ。同じ参加者の中で、システムの回の平均 − 対照の回。
  const fixed = rows.filter((r) => r.kind === "fixed");
  const pids = [...new Set(fixed.map((r) => r.pid))];
  const paired = PAIRED_METRICS.map((metric) => {
    const diffs: number[] = [];
    for (const pid of pids) {
      const docs = fixed.find((r) => r.pid === pid && r.condition === "docs_only");
      const sys = fixed.filter((r) => r.pid === pid && r.condition === "system").map(metric.value).filter((v): v is number => v != null);
      const base = docs ? metric.value(docs) : null;
      if (base == null || sys.length === 0) continue;
      diffs.push(sys.reduce((a, b) => a + b, 0) / sys.length - base);
    }
    const improved = diffs.filter((d) => (metric.better === "lower" ? d < 0 : d > 0)).length;
    return {
      key: metric.key,
      label: metric.label,
      better: metric.better,
      pairs: diffs.length,
      medianDiff: median(diffs),
      improved,
      rankBiserial: pairedRankBiserial(diffs),
    };
  });

  // 「公式ドキュメントのみ」の回に、質問が混ざった（本システムを使った可能性）記録
  const contaminated = rows.filter((r) => r.kind === "fixed" && r.condition === "docs_only" && (r.queryCount ?? 0) > 0).map((r) => r.pid);

  return {
    sessions: rows.length,
    participants: new Set(rows.map((r) => r.pid)).size,
    byGroup,
    paired,
    contaminated: [...new Set(contaminated)].sort((a, b) => a - b),
    comments: rows.filter((r) => r.comment).map((r) => ({ pid: r.pid, round: r.round, kind: r.kind, condition: r.condition, comment: r.comment })),
  };
}

// ---- 入力の検査 ----

function likert(value: unknown): number | null {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1 && n <= 5 ? n : null;
}

function text(value: unknown, max: number): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

function readBody(req: Request): Promise<Record<string, unknown>> {
  return req.json().then((b) => (b && typeof b === "object" ? (b as Record<string, unknown>) : {})).catch(() => ({}));
}

// ---- ハンドラ ----

interface ProfileRow {
  user_id: string;
  pid: number | null;
  slot: number;
}

async function loadProfile(env: Env, userId: string): Promise<ProfileRow | null> {
  return (await env.DB.prepare("SELECT user_id, pid, slot FROM pilot_profile WHERE user_id = ?").bind(userId).first<ProfileRow>()) ?? null;
}

async function loadSessions(env: Env, userId: string): Promise<Array<PlanSession & { id: string; started_at: number; task_id: string; condition: string }>> {
  const res = await env.DB.prepare("SELECT id, round, kind, task_id, condition, started_at, ended_at FROM pilot_sessions WHERE user_id = ? ORDER BY round, kind")
    .bind(userId)
    .all<PlanSession & { id: string; started_at: number; task_id: string; condition: string }>();
  return res.results ?? [];
}

async function planResponse(env: Env, userId: string): Promise<Response> {
  const profile = await loadProfile(env, userId);
  if (!profile) return jsonResponse(200, { status: "ok", profile: false });
  const plan = buildPlan(profile.slot, await loadSessions(env, userId));
  return jsonResponse(200, { status: "ok", profile: true, pid: profile.pid, ...plan });
}

// POST /pilot/plan — 自分の次の課題（本人だけ）
export async function handlePilotPlan(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  return planResponse(env, user.userId);
}

// POST /pilot/profile — 事前アンケート（1人1回。再送しても、番号は変わらず、回答だけ更新する）
export async function handlePilotProfile(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = await readBody(req);
  const years = Number(body.experienceYears);
  const fields = {
    experience_years: Number.isFinite(years) && years >= 0 && years <= 60 ? years : null,
    self_level: text(body.selfLevel, 40),
    background: text(body.background, 400),
    practice: text(body.practice, 400),
    tool_history: text(body.toolHistory, 400),
  };
  const existing = await loadProfile(env, user.userId);
  if (existing) {
    await env.DB.prepare("UPDATE pilot_profile SET experience_years = ?, self_level = ?, background = ?, practice = ?, tool_history = ? WHERE user_id = ?")
      .bind(fields.experience_years, fields.self_level, fields.background, fields.practice, fields.tool_history, user.userId)
      .run();
  } else {
    const isAdmin = user.role === "admin"; // 運営のテストは、番号を取らず、集計に入れない
    for (let attempt = 0; attempt < 3; attempt++) {
      const next = isAdmin ? null : ((await env.DB.prepare("SELECT COALESCE(MAX(pid), 0) + 1 AS n FROM pilot_profile").first<{ n: number }>())?.n ?? 1);
      try {
        await env.DB.prepare(
          "INSERT INTO pilot_profile (user_id, pid, slot, experience_years, self_level, background, practice, tool_history, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
          .bind(user.userId, next, next == null ? 1 : slotForPid(next), fields.experience_years, fields.self_level, fields.background, fields.practice, fields.tool_history, Math.floor(Date.now() / 1000))
          .run();
        break;
      } catch (err) {
        if (attempt === 2) throw err; // 同時に登録した人と番号がぶつかったときだけ、取り直す
      }
    }
  }
  return planResponse(env, user.userId);
}

// POST /pilot/session/start { kind } — いまの回の課題を始める。始めたまま終えていなければ、その続きを返す
export async function handlePilotSessionStart(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = await readBody(req);
  const kind = body.kind === "fixed" || body.kind === "free" ? body.kind : null;
  if (!kind) return jsonResponse(400, { error: "kind は fixed か free を指定してください" });
  const profile = await loadProfile(env, user.userId);
  if (!profile) return jsonResponse(409, { error: "先に事前アンケートに答えてください" });
  const sessions = await loadSessions(env, user.userId);
  const plan = buildPlan(profile.slot, sessions);
  if (plan.finished) return jsonResponse(409, { error: "3回すべて完了しています" });
  const item = kind === "fixed" ? plan.fixed : plan.free;
  if (item.done) return jsonResponse(409, { error: `第${plan.round}回の${kind === "fixed" ? "固定" : "自由"}課題は、完了しています` });
  const open = sessions.find((s) => s.round === plan.round && s.kind === kind && s.ended_at == null);
  if (open) {
    return jsonResponse(200, { status: "ok", sessionId: open.id, startedAt: open.started_at, resumed: true, round: plan.round, kind, taskId: item.taskId, label: item.label, condition: item.condition });
  }
  const id = crypto.randomUUID();
  const startedAt = Math.floor(Date.now() / 1000);
  await env.DB.prepare("INSERT INTO pilot_sessions (id, user_id, round, kind, task_id, condition, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
    .bind(id, user.userId, plan.round, kind, item.taskId, item.condition, startedAt)
    .run();
  return jsonResponse(200, { status: "ok", sessionId: id, startedAt, resumed: false, round: plan.round, kind, taskId: item.taskId, label: item.label, condition: item.condition });
}

// POST /pilot/session/end { sessionId, reached, cookErrorNodes, selfMistakes, survey{...}, comment }
export async function handlePilotSessionEnd(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = await readBody(req);
  const id = typeof body.sessionId === "string" ? body.sessionId : "";
  const row = id
    ? await env.DB.prepare("SELECT id, user_id, kind, condition, started_at, ended_at FROM pilot_sessions WHERE id = ?").bind(id).first<{
        id: string;
        user_id: string;
        kind: Kind;
        condition: Condition;
        started_at: number;
        ended_at: number | null;
      }>()
    : null;
  if (!row || row.user_id !== user.userId) return jsonResponse(404, { error: "課題の記録が見つかりません" });
  if (row.ended_at != null) return jsonResponse(409, { error: "この課題は、すでに終えています" });

  const now = Math.floor(Date.now() / 1000);
  const queries = await env.DB.prepare("SELECT COUNT(*) AS n FROM memory WHERE user_id = ? AND created_at >= ? AND created_at <= ?")
    .bind(user.userId, row.started_at, now)
    .first<{ n: number }>();
  const survey = (body.survey && typeof body.survey === "object" ? body.survey : {}) as Record<string, unknown>;
  const values = Object.fromEntries(SURVEY_FIELDS.map((f) => [f, likert(survey[f])])) as Record<SurveyField, number | null>;
  if (row.condition === "docs_only") values.sourceUseful = null; // 本システムを使わない回に、出典の有用性は無い
  const cook = body.cookErrorNodes == null ? null : clampInt(body.cookErrorNodes, 0, 0, 9999);
  await env.DB.prepare(
    `UPDATE pilot_sessions SET ended_at = ?, duration_sec = ?, query_count = ?, cook_error_nodes = ?, reached = ?, self_mistakes = ?,
       difficulty = ?, clarity = ?, focus = ?, accuracy_worry = ?, source_useful = ?, reuse = ?, comment = ? WHERE id = ?`,
  )
    .bind(
      now,
      now - row.started_at,
      queries?.n ?? 0,
      cook,
      body.reached === true || body.reached === 1 ? 1 : body.reached === false || body.reached === 0 ? 0 : null,
      likert(body.selfMistakes),
      values.difficulty,
      values.clarity,
      values.focus,
      values.accuracyWorry,
      values.sourceUseful,
      values.reuse,
      text(body.comment, 1000),
      id,
    )
    .run();
  return planResponse(env, user.userId);
}

// POST /admin/pilot/tasks — 課題の集計と、1課題1行のデータ（管理者だけ。氏名は出さず、P01 のような番号）
export async function handlePilotTasks(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const res = await env.DB.prepare(
    `SELECT p.pid AS pid, s.round AS round, s.kind AS kind, s.task_id AS taskId, s.condition AS condition,
       s.duration_sec AS durationSec, s.query_count AS queryCount, s.cook_error_nodes AS cookErrorNodes, s.reached AS reached,
       s.self_mistakes AS selfMistakes, s.difficulty AS difficulty, s.clarity AS clarity, s.focus AS focus,
       s.accuracy_worry AS accuracyWorry, s.source_useful AS sourceUseful, s.reuse AS reuse, COALESCE(s.comment, '') AS comment
     FROM pilot_sessions s JOIN pilot_profile p ON p.user_id = s.user_id JOIN users u ON u.user_id = s.user_id
     WHERE s.ended_at IS NOT NULL AND p.pid IS NOT NULL AND u.role != 'admin'
     ORDER BY p.pid, s.round, s.kind`,
  ).all<TaskRow>();
  const rows = res.results ?? [];
  const registered = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM pilot_profile p JOIN users u ON u.user_id = p.user_id WHERE p.pid IS NOT NULL AND u.role != 'admin'",
  ).first<{ n: number }>();
  return jsonResponse(200, {
    status: "ok",
    registered: registered?.n ?? 0,
    mistakeFormula: { cook: MISTAKE_WEIGHT_COOK, self: MISTAKE_WEIGHT_SELF, cookCap: COOK_ERROR_CAP },
    ...summarizeTasks(rows),
    rows: rows.map((r) => ({ ...r, participant: "P" + String(r.pid).padStart(2, "0"), mistake: withMistake(r), durationMin: minutes(r) })),
  });
}
