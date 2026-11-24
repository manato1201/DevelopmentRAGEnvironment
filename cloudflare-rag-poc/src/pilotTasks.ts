import type { AuthedUser, Env } from "./types";
import { clampInt, jsonResponse } from "./http";
import { requireAdmin } from "./auth";

// 実証実験の課題の記録とアンケート（2026-10-28）。設計: docs/pilot/pilot-analysis-design.md
//
//   ・参加者は、事前アンケートで登録する。登録順の匿名番号（pid）から、割り当て番号 slot（1〜6）が決まる。
//   ・回 = 募集期間（第1回・第2回）。参加者は、管理画面で受け付けている回に、1回だけ参加する（1回 3 時間ほど。2026-11-11）。
//   ・1回には、固定課題（必須）と自由課題（任意。時間が余った人だけ。1コマに収めるため。2026-11-13）を1つずつ。固定課題の題材（Pyro・RBD・雲）と、条件（本システム／公式ドキュメント・Web検索のみ）は、
//     slot で決まる（3題材 × 2条件 = 6通りを、登録順に回す）。対照は、参加者の間で比べる。
//   ・終了時に、課題後アンケートと、到達・自己申告のミスを送る。
//   ・所要時間は、サーバーの時刻（開始・終了）から出す。質問回数は、その時間内の質問（memory）の数で、サーバーが数える
//     （画面からの申告に頼らない。「公式ドキュメントのみ」の回に質問が混ざったかも、これで分かる）。
//   ・集計は管理者だけ。氏名は出さず、P01 のような番号で出す。管理者の記録は、集計に入れない。
//   ・条件の割り当ては、運営が管理画面で切り替えられる（2026-11-17。pilot_config の condition_mode）:
//       auto = 参加者番号から決める（既定。半々）／ system = 全員ツール使用 ／ docs_only = 全員ドキュメントのみ。
//     切り替えが効くのは、まだ始めていない固定課題だけ。始めた課題（終えたものを含む）は、始めたときの題材と条件のまま続ける。
//   ・やり直し: 計測中の記録も、終えた記録も、本人が破棄できる（discarded_at。消さずに残し、集計と「次の課題」の判定からは外す）。
//     ただし、次の回の課題を始めたあとは、前の回はやり直せない（回の順序と、対照の割り当てを崩さないため）。
//   ・所要時間 = 終了の時刻 − 開始の時刻 − 中断（Houdini が閉じていた秒数）。終了の時刻は、振り返りの回答に使った時間（surveySec）を引く。
//     どちらも画面側が同じ時計で測った秒数で送る（サーバーとPCの時計のずれに左右されない）。

export type TaskId = "pyro" | "rbd" | "cloud";
export type Kind = "fixed" | "free";
export type Condition = "system" | "docs_only";
// 条件の割り当て方（運営が管理画面で切り替える）。auto = 参加者番号から決める（既定）。
export type ConditionMode = "auto" | Condition;
export const CONDITION_MODES: ConditionMode[] = ["auto", "system", "docs_only"];
export function parseConditionMode(value: unknown): ConditionMode {
  return CONDITION_MODES.includes(value as ConditionMode) ? (value as ConditionMode) : "auto";
}

export const ROUNDS = 2; // 回 = 募集期間の数。管理画面で、いま受け付ける回を切り替える（pilot_config の open_round）
export const TASKS: Record<TaskId, string> = {
  pyro: "Pyro（煙・炎のシミュレーション）",
  rbd: "RBD（剛体・破壊のシミュレーション）",
  cloud: "雲（パーティクルでの雲の制作）",
};
// 固定課題の題材の並び。slot 1〜3 が本システム、4〜6 が対照（公式ドキュメント・Web検索のみ）で、題材は同じ順に当たる。
// 2026-11-24: 雲を外し、割り当て 3・6 の番も RBD にする（運営の指示）。TaskId の "cloud" は、すでに記録した課題を表示するために残す。
export const TASK_ORDER: TaskId[] = ["pyro", "rbd", "rbd"];
export const SLOTS = 6;

// slot から、固定課題の題材と条件を決める（登録順の6人ごとに、3題材 × 2条件が1度ずつ当たる）。
// mode が system / docs_only のときは、題材は slot のまま、条件だけを全員そろえる。
export function assignmentForSlot(slot: number, mode: ConditionMode = "auto"): { taskId: TaskId; condition: Condition } {
  const i = (((Math.trunc(slot) - 1) % SLOTS) + SLOTS) % SLOTS;
  const forced = parseConditionMode(mode);
  const condition: Condition = forced !== "auto" ? forced : i >= TASK_ORDER.length ? "docs_only" : "system";
  return { taskId: TASK_ORDER[i % TASK_ORDER.length], condition };
}
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

// 学びの確認（2026-11-22。migrations/0039）。同じ3つの自己評価を、事前と事後に聞き、差（伸び）を見る。
//   goal  … 得たいもの（事前）/ いま学びたいもの（事後）。1 = 完成物を手早く作れるように … 5 = Houdini の仕組みを理解
//   goalUsed … 本システムの使い方。1 = 答え・完成物を出してもらうため … 5 = 作られた中身を追って、仕組みを理解するため（本システムを使わない回は聞かない）
//   selfHow / selfExplore / selfWhat … ノードのつながりを説明できる / 初めてのノードを調べて判断できる / Houdini が何かを説明できる
//   learned … この時間で、新しく理解できたことがあった
export const LEARNING_FIELDS = ["goalPost", "goalUsed", "selfHow", "selfExplore", "selfWhat", "learned"] as const;
type LearningField = (typeof LEARNING_FIELDS)[number];
// 自由記述の最大文字数（理解の証拠になる explainOwn は長め）
export const ESSAY_MAX = { explainOwn: 600, houdiniDef: 300, fun: 400 } as const;

export function slotForPid(pid: number): number {
  return ((pid - 1) % SLOTS) + 1;
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
  id?: string;
  task_id?: string;
  condition?: string;
  duration_sec?: number | null;
}

export interface TaskPlanItem {
  kind: Kind;
  taskId: TaskId | "free";
  label: string;
  condition: Condition;
  done: boolean;
  active: boolean; // 開始したが、まだ終えていない
  optional: boolean; // 任意（自由課題。1コマに収めるため、固定課題だけで参加は完了。2026-11-13）
  locked: boolean; // まだ始められない（自由課題は、必須の固定課題を終えたあと、時間が余ったときだけ。2026-11-24）
}

export interface TaskPlan {
  slot: number;
  rounds: number; // 回の数
  round: number | null; // 参加している回（まだ参加していなければ、いま受け付けている回。受付中でなければ null）
  openRound: number; // いま新しく参加できる回（0 = 受付を止めている）
  canStart: boolean; // 課題を始められるか（参加済みの人は、受付が止まっても自分の回を続けられる）
  completed: boolean; // 必須の課題（固定課題）を終えた = 参加は完了
  finished: boolean; // 固定課題も、自由課題も、終えた
  fixed: TaskPlanItem;
  free: TaskPlanItem;
  criterion: string;
}

export function buildPlan(slot: number, sessions: PlanSession[], openRound = 0, mode: ConditionMode = "auto"): TaskPlan {
  const joined = sessions.length ? Math.min(...sessions.map((s) => s.round)) : null; // 参加は1回だけ。最初に始めた回
  const accepting = openRound >= 1 && openRound <= ROUNDS;
  const round = joined ?? (accepting ? openRound : null);
  const done = (kind: Kind) => round != null && sessions.some((s) => s.round === round && s.kind === kind && s.ended_at != null);
  const active = (kind: Kind) => round != null && sessions.some((s) => s.round === round && s.kind === kind && s.ended_at == null);
  // 固定課題を始めている（終えたものを含む）なら、始めたときの題材と条件のまま。切り替えが効くのは、まだ始めていない人だけ。
  const assigned = assignmentForSlot(slot, mode);
  const startedFixed = round == null ? undefined : sessions.find((s) => s.round === round && s.kind === "fixed");
  const taskId: TaskId = startedFixed?.task_id && startedFixed.task_id in TASKS ? (startedFixed.task_id as TaskId) : assigned.taskId;
  const condition: Condition = startedFixed?.condition === "system" || startedFixed?.condition === "docs_only" ? startedFixed.condition : assigned.condition;
  return {
    slot,
    rounds: ROUNDS,
    round,
    openRound: accepting ? openRound : 0,
    canStart: joined != null || accepting,
    completed: done("fixed"),
    finished: done("fixed") && done("free"),
    fixed: { kind: "fixed", taskId, label: TASKS[taskId], condition, done: done("fixed"), active: active("fixed"), optional: false, locked: false },
    free: { kind: "free", taskId: "free", label: "自分の作りたいもの", condition: "system", done: done("free"), active: active("free"), optional: true, locked: !done("fixed") },
    criterion: CRITERION,
  };
}

export interface HistoryItem {
  sessionId: string;
  round: number;
  kind: Kind;
  label: string;
  running: boolean;
  durationSec: number | null;
  redoable: boolean; // 参加は1回だけなので、通常は、いつでもやり直せる
}

// これまでの記録（破棄していないもの）。画面の「完了した記録」と「やり直す」の元。
export function buildHistory(sessions: PlanSession[]): HistoryItem[] {
  const lastRound = Math.max(0, ...sessions.map((s) => s.round));
  return sessions
    .filter((s) => s.id)
    .map((s) => ({
      sessionId: s.id as string,
      round: s.round,
      kind: s.kind,
      label: s.kind === "free" ? "自分の作りたいもの" : (TASKS[s.task_id as TaskId] ?? String(s.task_id ?? "")),
      running: s.ended_at == null,
      durationSec: s.duration_sec ?? null,
      redoable: s.round >= lastRound,
    }))
    .sort((a, b) => a.round - b.round || a.kind.localeCompare(b.kind));
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
  // 学びの確認（固定課題の終了時）と、その事前の値（事前アンケート）。無い（答えなかった・旧版）は null / ""
  goalPost?: number | null;
  goalUsed?: number | null;
  selfHow?: number | null;
  selfExplore?: number | null;
  selfWhat?: number | null;
  learned?: number | null;
  explainOwn?: string;
  houdiniDef?: string;
  fun?: string;
  goalPre?: number | null;
  selfHowPre?: number | null;
  selfExplorePre?: number | null;
  selfWhatPre?: number | null;
  houdiniDefPre?: string;
  redoCount?: number; // やり直した回数（この課題を、破棄して取り直した数）
  startedAt?: number; // 開始・終了の時刻（秒）。管理画面の「回答の一覧」用
  endedAt?: number;
  pausedSec?: number; // 中断（Houdini が閉じていた秒数。所要時間から引いた分）
}

export function median(values: Array<number | null | undefined>): number | null {
  const xs = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v)).sort((a, b) => a - b);
  if (xs.length === 0) return null;
  const mid = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
}

// Cliff の delta（2つの群の効果量。-1〜1。x の群が大きいほど正。同じ値は0として数える）。どちらかが空なら null。
export function cliffsDelta(xs: number[], ys: number[]): number | null {
  if (xs.length === 0 || ys.length === 0) return null;
  let greater = 0;
  let less = 0;
  for (const x of xs) for (const y of ys) x > y ? greater++ : x < y ? less++ : 0;
  return Math.round(((greater - less) / (xs.length * ys.length)) * 1000) / 1000;
}

const participantLabel = (pid: number) => "P" + String(pid).padStart(2, "0");
const withMistake = (r: TaskRow) => mistakeScore(r.cookErrorNodes, r.selfMistakes);
const minutes = (r: TaskRow) => (r.durationSec == null ? null : Math.round((r.durationSec / 60) * 10) / 10);

// 伸び = 事後 − 事前。どちらかが無ければ null（片方だけで代用しない）
export function gain(post: number | null | undefined, pre: number | null | undefined): number | null {
  return typeof post === "number" && typeof pre === "number" ? post - pre : null;
}
const goalShift = (r: TaskRow) => gain(r.goalPost, r.goalPre);
const howGain = (r: TaskRow) => gain(r.selfHow, r.selfHowPre);
const exploreGain = (r: TaskRow) => gain(r.selfExplore, r.selfExplorePre);
const whatGain = (r: TaskRow) => gain(r.selfWhat, r.selfWhatPre);

const COMPARE_METRICS: Array<{ key: string; label: string; better: "lower" | "higher"; value: (r: TaskRow) => number | null }> = [
  { key: "difficulty", label: "難しさ（1〜5）", better: "lower", value: (r) => r.difficulty },
  { key: "clarity", label: "わかりやすさ（1〜5）", better: "higher", value: (r) => r.clarity },
  { key: "durationMin", label: "所要時間（分）", better: "lower", value: minutes },
  { key: "mistake", label: "操作ミス（0〜1）", better: "lower", value: withMistake },
  { key: "reached", label: "到達（0/1）", better: "higher", value: (r) => r.reached },
  // 学びの確認。本システムの目的は、生成物を作れるようになることではなく、中身を理解すること（2026-11-22）
  { key: "learned", label: "新しく理解できたこと（1〜5）", better: "higher", value: (r) => r.learned ?? null },
  { key: "selfHowGain", label: "ノードのつながりを説明できる（事後−事前）", better: "higher", value: howGain },
  { key: "selfExploreGain", label: "初めてのノードを調べて判断できる（事後−事前）", better: "higher", value: exploreGain },
  { key: "selfWhatGain", label: "Houdini が何かを説明できる（事後−事前）", better: "higher", value: whatGain },
  { key: "goalShift", label: "学びたいものの変化（事後−事前。+は、仕組みの理解へ）", better: "higher", value: goalShift },
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
          learned: median(items.map((i) => i.learned)),
          goalPost: median(items.map((i) => i.goalPost)),
          goalUsed: median(items.map((i) => i.goalUsed)),
          selfHowGain: median(items.map(howGain)),
          selfExploreGain: median(items.map(exploreGain)),
          selfWhatGain: median(items.map(whatGain)),
          goalShift: median(items.map(goalShift)),
          durationMin: median(items.map(minutes)),
          queries: median(items.map((i) => i.queryCount)),
          mistake: median(items.map(withMistake)),
        },
      };
    })
    .sort((a, b) => a.round - b.round || a.kind.localeCompare(b.kind) || a.condition.localeCompare(b.condition));

  // 対照（公式ドキュメントのみ）と、本システムの比較。固定課題だけ。参加者の間で比べる（参加は1回だけ。2026-11-11）。
  // 差 = 本システムの中央値 − 対照の中央値。効果量は Cliff の delta（本システムの群が大きいほど正）。
  const fixed = rows.filter((r) => r.kind === "fixed");
  const compared = COMPARE_METRICS.map((metric) => {
    const valuesOf = (condition: Condition) => fixed.filter((r) => r.condition === condition).map(metric.value).filter((v): v is number => v != null);
    const sys = valuesOf("system");
    const docs = valuesOf("docs_only");
    const medianSystem = median(sys);
    const medianDocs = median(docs);
    const comparable = sys.length > 0 && docs.length > 0; // 片方の群が空なら、比べない（0 件との差を出さない）
    return {
      key: metric.key,
      label: metric.label,
      better: metric.better,
      comparable,
      nSystem: sys.length,
      nDocs: docs.length,
      medianSystem,
      medianDocs,
      medianDiff: comparable && medianSystem != null && medianDocs != null ? medianSystem - medianDocs : null,
      cliffsDelta: comparable ? cliffsDelta(sys, docs) : null,
    };
  });
  const nSystemFixed = fixed.filter((r) => r.condition === "system").length;
  const nDocsFixed = fixed.filter((r) => r.condition === "docs_only").length;
  const comparison = {
    comparable: nSystemFixed > 0 && nDocsFixed > 0,
    nSystem: nSystemFixed,
    nDocs: nDocsFixed,
    reason:
      nSystemFixed > 0 && nDocsFixed > 0
        ? ""
        : `比較できません: ${nSystemFixed === 0 && nDocsFixed === 0 ? "終えた固定課題がまだありません" : nDocsFixed === 0 ? "固定課題がすべて「ツール使用」です（ドキュメントのみの記録が 0 件）" : "固定課題がすべて「ドキュメントのみ」です（ツール使用の記録が 0 件）"}。条件が混ざっていないため、群の間の差は出しません。`,
  };

  // 「公式ドキュメントのみ」の回に、質問が混ざった（本システムを使った可能性）記録
  const contaminated = rows.filter((r) => r.kind === "fixed" && r.condition === "docs_only" && (r.queryCount ?? 0) > 0).map((r) => r.pid);

  return {
    sessions: rows.length,
    participants: new Set(rows.map((r) => r.pid)).size,
    byGroup,
    compared,
    comparison,
    contaminated: [...new Set(contaminated)].sort((a, b) => a - b),
    comments: rows.filter((r) => r.comment).map((r) => ({ pid: r.pid, round: r.round, kind: r.kind, condition: r.condition, comment: r.comment })),
    // 楽しかったこと・自分の言葉での説明（自由記述。分析では、コーディングして集計する）
    fun: rows.filter((r) => r.fun).map((r) => ({ pid: r.pid, round: r.round, kind: r.kind, condition: r.condition, fun: r.fun })),
    // 「本システムを、どう使ったか」の分布（1 = 答え・完成物を出してもらうため … 5 = 中身を追って理解するため）。本システムを使った固定課題だけ
    goalUsedDistribution: [1, 2, 3, 4, 5].map((v) => ({ value: v, n: fixed.filter((r) => r.condition === "system" && r.goalUsed === v).length })),
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

type SessionRow = PlanSession & { id: string; started_at: number; task_id: string; condition: string };

// 破棄したもの（やり直し）は、入れない
async function loadSessions(env: Env, userId: string): Promise<SessionRow[]> {
  const res = await env.DB.prepare(
    "SELECT id, round, kind, task_id, condition, started_at, ended_at, duration_sec FROM pilot_sessions WHERE user_id = ? AND discarded_at IS NULL ORDER BY round, kind",
  )
    .bind(userId)
    .all<SessionRow>();
  return res.results ?? [];
}

// ---- いま受け付けている回（pilot_config。管理画面で切り替える） ----

export interface PilotConfig {
  openRound: number; // 0 = 受付を止めている
  labels: Record<number, string>; // 回の表示（「11/16〜11/21」など）
  conditionMode: ConditionMode; // 条件の割り当て（auto = 参加者番号から。既定）
}

const LABEL_MAX = 40;

export async function loadPilotConfig(env: Env): Promise<PilotConfig> {
  const res = await env.DB.prepare("SELECT key, value FROM pilot_config").all<{ key: string; value: string }>();
  const map = new Map((res.results ?? []).map((r) => [r.key, r.value]));
  const open = Number(map.get("open_round") ?? 0);
  const labels: Record<number, string> = {};
  for (let r = 1; r <= ROUNDS; r++) labels[r] = map.get(`label_${r}`) ?? "";
  return { openRound: Number.isInteger(open) && open >= 1 && open <= ROUNDS ? open : 0, labels, conditionMode: parseConditionMode(map.get("condition_mode")) };
}

async function saveConfigValue(env: Env, key: string, value: string): Promise<void> {
  await env.DB.prepare("INSERT INTO pilot_config (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
    .bind(key, value, Math.floor(Date.now() / 1000))
    .run();
}

async function planResponse(env: Env, userId: string): Promise<Response> {
  const profile = await loadProfile(env, userId);
  if (!profile) return jsonResponse(200, { status: "ok", profile: false });
  const sessions = await loadSessions(env, userId);
  const config = await loadPilotConfig(env);
  const plan = buildPlan(profile.slot, sessions, config.openRound, config.conditionMode);
  const roundLabel = plan.round != null ? config.labels[plan.round] ?? "" : "";
  return jsonResponse(200, { status: "ok", profile: true, pid: profile.pid, ...plan, roundLabel, history: buildHistory(sessions) });
}

// POST /pilot/plan — 自分の次の課題（本人だけ）
export async function handlePilotPlan(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  return planResponse(env, user.userId);
}

// POST /pilot/profile — 事前アンケート（1人1回。再送しても、番号は変わらず、回答だけ更新する）
export async function handlePilotProfile(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = await readBody(req);
  // 経験は、月数（experienceMonths。年と月で聞いた合計）を優先する。DB の列は、従来どおり「年」（月数 ÷ 12）に入れる（列を増やさない）。
  const months = Number(body.experienceMonths);
  const years = body.experienceMonths != null && Number.isFinite(months) && months >= 0 && months <= 720 ? Math.round(months) / 12 : Number(body.experienceYears);
  const fields = {
    experience_years: Number.isFinite(years) && years >= 0 && years <= 60 ? Math.round(years * 12) / 12 : null,
    self_level: text(body.selfLevel, 40),
    background: text(body.background, 400),
    practice: text(body.practice, 400),
    tool_history: text(body.toolHistory, 400),
  };
  // 学びの確認の事前の値（2026-11-22）。答えなかった項目は NULL。旧版のパネルは送らないので、更新のときは、すでにある値を消さない（COALESCE）。
  const pre = {
    goal_pre: likert(body.goalPre),
    self_how_pre: likert(body.selfHowPre),
    self_explore_pre: likert(body.selfExplorePre),
    self_what_pre: likert(body.selfWhatPre),
    houdini_def_pre: text(body.houdiniDefPre, ESSAY_MAX.houdiniDef) || null,
  };
  const existing = await loadProfile(env, user.userId);
  if (existing) {
    await env.DB.prepare(
      `UPDATE pilot_profile SET experience_years = ?, self_level = ?, background = ?, practice = ?, tool_history = ?,
         goal_pre = COALESCE(?, goal_pre), self_how_pre = COALESCE(?, self_how_pre), self_explore_pre = COALESCE(?, self_explore_pre),
         self_what_pre = COALESCE(?, self_what_pre), houdini_def_pre = COALESCE(?, houdini_def_pre) WHERE user_id = ?`,
    )
      .bind(fields.experience_years, fields.self_level, fields.background, fields.practice, fields.tool_history, pre.goal_pre, pre.self_how_pre, pre.self_explore_pre, pre.self_what_pre, pre.houdini_def_pre, user.userId)
      .run();
  } else {
    const isAdmin = user.role === "admin"; // 運営のテストは、番号を取らず、集計に入れない
    for (let attempt = 0; attempt < 3; attempt++) {
      const next = isAdmin ? null : ((await env.DB.prepare("SELECT COALESCE(MAX(pid), 0) + 1 AS n FROM pilot_profile").first<{ n: number }>())?.n ?? 1);
      try {
        await env.DB.prepare(
          `INSERT INTO pilot_profile (user_id, pid, slot, experience_years, self_level, background, practice, tool_history, created_at,
             goal_pre, self_how_pre, self_explore_pre, self_what_pre, houdini_def_pre) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
          .bind(user.userId, next, next == null ? 1 : slotForPid(next), fields.experience_years, fields.self_level, fields.background, fields.practice, fields.tool_history, Math.floor(Date.now() / 1000), pre.goal_pre, pre.self_how_pre, pre.self_explore_pre, pre.self_what_pre, pre.houdini_def_pre)
          .run();
        break;
      } catch (err) {
        if (attempt === 2) throw err; // 同時に登録した人と番号がぶつかったときだけ、取り直す
      }
    }
  }
  return planResponse(env, user.userId);
}

// POST /pilot/session/start { kind } — 自分の回の課題を始める（初めてのときは、いま受け付けている回に参加する）。始めたまま終えていなければ、その続きを返す
export async function handlePilotSessionStart(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = await readBody(req);
  const kind = body.kind === "fixed" || body.kind === "free" ? body.kind : null;
  if (!kind) return jsonResponse(400, { error: "kind は fixed か free を指定してください" });
  const profile = await loadProfile(env, user.userId);
  if (!profile) return jsonResponse(409, { error: "先に事前アンケートに答えてください" });
  const sessions = await loadSessions(env, user.userId);
  const config = await loadPilotConfig(env);
  const plan = buildPlan(profile.slot, sessions, config.openRound, config.conditionMode);
  if (plan.finished) return jsonResponse(409, { error: "課題は、すべて完了しています" });  // 自由課題は任意。固定課題だけを終えた人は、自由課題を始められる
  if (!plan.canStart || plan.round == null) return jsonResponse(409, { error: "いま、課題は受け付けていません。運営からの案内をお待ちください", code: "closed" });
  const item = kind === "fixed" ? plan.fixed : plan.free;
  // 固定課題は必須、自由課題は、固定課題を終えたあと、1 コマ（約 90 分）の時間が余ったときだけの任意（先に自由課題を始めて、必須の課題の時間を使わない）
  if (item.locked) return jsonResponse(409, { error: "自由課題は、固定課題（必須）を終えたあとに、時間が余ったときだけ行えます。先に固定課題を行ってください", code: "fixed_first" });
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
    ? await env.DB.prepare("SELECT id, user_id, kind, condition, started_at, ended_at, discarded_at FROM pilot_sessions WHERE id = ?").bind(id).first<{
        id: string;
        user_id: string;
        kind: Kind;
        condition: Condition;
        started_at: number;
        ended_at: number | null;
        discarded_at: number | null;
      }>()
    : null;
  if (!row || row.user_id !== user.userId || row.discarded_at != null) return jsonResponse(404, { error: "課題の記録が見つかりません" });
  if (row.ended_at != null) return jsonResponse(409, { error: "この課題は、すでに終えています" });

  const now = Math.floor(Date.now() / 1000);
  // 終了の時刻は、「終了」を押した時刻（送信の時刻から、振り返りの回答に使った時間を引く）。中断（Houdini が閉じていた時間）は所要時間から引く。
  const endedAt = Math.max(row.started_at, now - clampInt(body.surveySec, 0, 0, 86400));
  const pausedSec = Math.min(clampInt(body.pausedSec, 0, 0, 604800), endedAt - row.started_at);
  const queries = await env.DB.prepare("SELECT COUNT(*) AS n FROM memory WHERE user_id = ? AND created_at >= ? AND created_at <= ?")
    .bind(user.userId, row.started_at, endedAt)
    .first<{ n: number }>();
  const survey = (body.survey && typeof body.survey === "object" ? body.survey : {}) as Record<string, unknown>;
  const values = Object.fromEntries(SURVEY_FIELDS.map((f) => [f, likert(survey[f])])) as Record<SurveyField, number | null>;
  if (row.condition === "docs_only") values.sourceUseful = null; // 本システムを使わない回に、出典の有用性は無い
  // 学びの確認（2026-11-22）。答えなかった項目は NULL。本システムを使わない回に、「本システムの使い方」は無い。
  const learning = (body.learning && typeof body.learning === "object" ? body.learning : {}) as Record<string, unknown>;
  const learn = Object.fromEntries(LEARNING_FIELDS.map((f) => [f, likert(learning[f])])) as Record<LearningField, number | null>;
  if (row.condition === "docs_only") learn.goalUsed = null;
  const essays = (body.essays && typeof body.essays === "object" ? body.essays : {}) as Record<string, unknown>;
  const essay = {
    explainOwn: text(essays.explainOwn, ESSAY_MAX.explainOwn) || null,
    houdiniDef: text(essays.houdiniDef, ESSAY_MAX.houdiniDef) || null,
    fun: text(essays.fun, ESSAY_MAX.fun) || null,
  };
  const cook = body.cookErrorNodes == null ? null : clampInt(body.cookErrorNodes, 0, 0, 9999);
  await env.DB.prepare(
    `UPDATE pilot_sessions SET ended_at = ?, duration_sec = ?, paused_sec = ?, query_count = ?, cook_error_nodes = ?, reached = ?, self_mistakes = ?,
       difficulty = ?, clarity = ?, focus = ?, accuracy_worry = ?, source_useful = ?, reuse = ?, comment = ?,
       goal_post = ?, goal_used = ?, self_how = ?, self_explore = ?, self_what = ?, learned = ?, explain_own = ?, houdini_def = ?, fun = ? WHERE id = ?`,
  )
    .bind(
      endedAt,
      endedAt - row.started_at - pausedSec,
      pausedSec,
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
      learn.goalPost,
      learn.goalUsed,
      learn.selfHow,
      learn.selfExplore,
      learn.selfWhat,
      learn.learned,
      essay.explainOwn,
      essay.houdiniDef,
      essay.fun,
      id,
    )
    .run();
  return planResponse(env, user.userId);
}

// POST /pilot/session/reset { sessionId } — 計測中・終えた記録を、破棄してやり直す（本人だけ）。
// 破棄した記録は消さずに残す（集計には入れない）。
export async function handlePilotSessionReset(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = await readBody(req);
  const id = typeof body.sessionId === "string" ? body.sessionId : "";
  const row = id
    ? await env.DB.prepare("SELECT user_id, round, discarded_at FROM pilot_sessions WHERE id = ?").bind(id).first<{ user_id: string; round: number; discarded_at: number | null }>()
    : null;
  if (!row || row.user_id !== user.userId || row.discarded_at != null) return jsonResponse(404, { error: "課題の記録が見つかりません" });
  const later = await env.DB.prepare("SELECT COUNT(*) AS n FROM pilot_sessions WHERE user_id = ? AND discarded_at IS NULL AND round > ?")
    .bind(user.userId, row.round)
    .first<{ n: number }>();
  if ((later?.n ?? 0) > 0) return jsonResponse(409, { error: "次の回を始めたあとは、前の回はやり直せません。必要なら、運営に連絡してください" });
  await env.DB.prepare("UPDATE pilot_sessions SET discarded_at = ? WHERE id = ?").bind(Math.floor(Date.now() / 1000), id).run();
  return planResponse(env, user.userId);
}

// POST /admin/pilot/tasks — 課題の集計と、1課題1行のデータ（管理者だけ。氏名は出さず、P01 のような番号）
export async function handlePilotTasks(_req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const res = await env.DB.prepare(
    `SELECT p.pid AS pid, s.round AS round, s.kind AS kind, s.task_id AS taskId, s.condition AS condition,
       s.duration_sec AS durationSec, s.query_count AS queryCount, s.cook_error_nodes AS cookErrorNodes, s.reached AS reached,
       s.self_mistakes AS selfMistakes, s.difficulty AS difficulty, s.clarity AS clarity, s.focus AS focus,
       s.accuracy_worry AS accuracyWorry, s.source_useful AS sourceUseful, s.reuse AS reuse, COALESCE(s.comment, '') AS comment,
       s.started_at AS startedAt, s.ended_at AS endedAt, COALESCE(s.paused_sec, 0) AS pausedSec,
       s.goal_post AS goalPost, s.goal_used AS goalUsed, s.self_how AS selfHow, s.self_explore AS selfExplore, s.self_what AS selfWhat, s.learned AS learned,
       COALESCE(s.explain_own, '') AS explainOwn, COALESCE(s.houdini_def, '') AS houdiniDef, COALESCE(s.fun, '') AS fun,
       p.goal_pre AS goalPre, p.self_how_pre AS selfHowPre, p.self_explore_pre AS selfExplorePre, p.self_what_pre AS selfWhatPre, COALESCE(p.houdini_def_pre, '') AS houdiniDefPre,
       (SELECT COUNT(*) FROM pilot_sessions d WHERE d.user_id = s.user_id AND d.round = s.round AND d.kind = s.kind AND d.discarded_at IS NOT NULL) AS redoCount
     FROM pilot_sessions s JOIN pilot_profile p ON p.user_id = s.user_id JOIN users u ON u.user_id = s.user_id
     WHERE s.ended_at IS NOT NULL AND s.discarded_at IS NULL AND p.pid IS NOT NULL AND u.role != 'admin'
     ORDER BY p.pid, s.round, s.kind`,
  ).all<TaskRow>();
  const rows = res.results ?? [];
  const registered = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM pilot_profile p JOIN users u ON u.user_id = p.user_id WHERE p.pid IS NOT NULL AND u.role != 'admin'",
  ).first<{ n: number }>();
  // 事前アンケート（自由記述を含む）。個人情報が書かれているかもしれないので、管理者だけ。氏名・ユーザー ID は出さず、番号で出す。
  const profileRes = await env.DB.prepare(
    `SELECT p.pid AS pid, p.slot AS slot, p.experience_years AS experienceYears, COALESCE(p.self_level, '') AS selfLevel,
       COALESCE(p.background, '') AS background, COALESCE(p.practice, '') AS practice, COALESCE(p.tool_history, '') AS toolHistory, p.created_at AS createdAt,
       p.goal_pre AS goalPre, p.self_how_pre AS selfHowPre, p.self_explore_pre AS selfExplorePre, p.self_what_pre AS selfWhatPre, COALESCE(p.houdini_def_pre, '') AS houdiniDefPre
     FROM pilot_profile p JOIN users u ON u.user_id = p.user_id
     WHERE p.pid IS NOT NULL AND u.role != 'admin'
     ORDER BY p.pid`,
  ).all<{ pid: number; slot: number; experienceYears: number | null; selfLevel: string; background: string; practice: string; toolHistory: string; createdAt: number; goalPre: number | null; selfHowPre: number | null; selfExplorePre: number | null; selfWhatPre: number | null; houdiniDefPre: string }>();
  const config = await loadPilotConfig(env);
  return jsonResponse(200, {
    status: "ok",
    registered: registered?.n ?? 0,
    conditionMode: config.conditionMode,
    profiles: (profileRes.results ?? []).map((p) => ({ ...p, participant: participantLabel(p.pid) })),
    mistakeFormula: { cook: MISTAKE_WEIGHT_COOK, self: MISTAKE_WEIGHT_SELF, cookCap: COOK_ERROR_CAP },
    ...summarizeTasks(rows),
    rows: rows.map((r) => ({ ...r, participant: participantLabel(r.pid), mistake: withMistake(r), selfHowGain: howGain(r), selfExploreGain: exploreGain(r), selfWhatGain: whatGain(r), goalShift: goalShift(r), durationMin: minutes(r), pausedMin: r.pausedSec == null ? null : Math.round((r.pausedSec / 60) * 10) / 10 })),
  });
}

// POST /admin/pilot/config { openRound?, labels?, conditionMode? } — いま受け付ける回、回の表示、条件の割り当てを切り替える（管理者だけ）。何も指定しなければ、いまの状態を返す。
// conditionMode: "auto"（参加者番号から。既定）／ "system"（全員ツール使用）／ "docs_only"（全員ドキュメントのみ）。まだ始めていない固定課題にだけ効く。
export async function handlePilotConfig(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = await readBody(req);
  // 先に、すべての値を検査する（片方だけ保存されて、400 が返る、という中途半端な状態を作らない）
  const open = body.openRound !== undefined ? Number(body.openRound) : null;
  if (open !== null && (!Number.isInteger(open) || open < 0 || open > ROUNDS)) return jsonResponse(400, { error: `openRound は 0（受付停止）〜${ROUNDS} で指定してください` });
  if (body.conditionMode !== undefined && !CONDITION_MODES.includes(body.conditionMode as ConditionMode)) {
    return jsonResponse(400, { error: `conditionMode は ${CONDITION_MODES.join("・")} のどれかで指定してください` });
  }
  if (open !== null) await saveConfigValue(env, "open_round", String(open));
  if (body.conditionMode !== undefined) await saveConfigValue(env, "condition_mode", String(body.conditionMode));
  if (body.labels && typeof body.labels === "object") {
    const labels = body.labels as Record<string, unknown>;
    for (let r = 1; r <= ROUNDS; r++) {
      if (labels[String(r)] !== undefined) await saveConfigValue(env, `label_${r}`, text(labels[String(r)], LABEL_MAX));
    }
  }
  const config = await loadPilotConfig(env);
  // 回ごとの参加人数と完了人数（管理者の記録と、やり直しで破棄した記録は数えない）
  const res = await env.DB.prepare(
    `SELECT s.user_id AS userId, s.round AS round, s.kind AS kind, s.ended_at AS endedAt
     FROM pilot_sessions s JOIN users u ON u.user_id = s.user_id
     WHERE s.discarded_at IS NULL AND u.role != 'admin'`,
  ).all<{ userId: string; round: number; kind: Kind; endedAt: number | null }>();
  const sessions = res.results ?? [];
  const rounds = Array.from({ length: ROUNDS }, (_, i) => {
    const round = i + 1;
    const mine = sessions.filter((s) => s.round === round);
    const users = [...new Set(mine.map((s) => s.userId))];
    const finished = users.filter((id) => mine.some((s) => s.userId === id && s.kind === "fixed" && s.endedAt != null)); // 完了 = 固定課題を終えた（自由課題は任意）
    return { round, label: config.labels[round] ?? "", open: config.openRound === round, joined: users.length, finished: finished.length };
  });
  const registered = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM pilot_profile p JOIN users u ON u.user_id = p.user_id WHERE p.pid IS NOT NULL AND u.role != 'admin'",
  ).first<{ n: number }>();
  // 始めた固定課題の、条件ごとの数（切り替えたあと、混ざっているかの目安。破棄した記録・管理者の記録は数えない）
  const conditionCounts = { system: 0, docs_only: 0 };
  const condRes = await env.DB.prepare(
    `SELECT s.condition AS condition, COUNT(*) AS n
     FROM pilot_sessions s JOIN users u ON u.user_id = s.user_id
     WHERE s.kind = 'fixed' AND s.discarded_at IS NULL AND u.role != 'admin' GROUP BY s.condition`,
  ).all<{ condition: string; n: number }>();
  for (const c of condRes.results ?? []) if (c.condition === "system" || c.condition === "docs_only") conditionCounts[c.condition] = c.n;
  return jsonResponse(200, { status: "ok", openRound: config.openRound, maxRound: ROUNDS, rounds, registered: registered?.n ?? 0, conditionMode: config.conditionMode, conditionCounts });
}
