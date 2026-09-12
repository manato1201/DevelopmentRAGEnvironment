import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { jsonResponse } from "./http";

// プロバイダ横断のモデル別単価（USD / 1M tokens）。
// - Claude: houdini/python_panels/tutorial_agent.py の _MODEL_PRICES と同一の値を保つこと
//   （あちらがコスト上限判定の実測計算に使う価格テーブルの正）。cache_write/cache_readは
//   このプロキシ経由では未使用のため参考値として残すのみで、コスト計算には使わない。
//   claude-sonnet-5: 標準価格 $3/$15 / claude-haiku-4-5: $1/$5
// - Gemini: https://ai.google.dev/gemini-api/docs/pricing で2026-09-10に確認した値。
//   gemini-flash-latestは2026-12-31までの期間限定価格（$0.75/$3.75、2027-01-01以降は
//   $1.50/$7.50に上がる予定）。embeddingは入力のみの課金でoutputは無い（gemini-embedding-001:
//   $0.15/1M、出力側は常に0として扱う）。
// このテーブルはRAG（Gemini）・Claude両方のコスト集計（下のhandleClaudeCostStats/
// handleGeminiCostStats）から共通で参照する（2026-09-10リファクタリング：元は
// Claude専用のCLAUDE_MODEL_PRICESだったものをプロバイダ横断に一般化した）。
const MODEL_PRICES: Record<string, { input: number; output: number }> = {
  "claude-sonnet-5": { input: 3.0, output: 15.0 },
  "claude-haiku-4-5": { input: 1.0, output: 5.0 },
  "gemini-flash-latest": { input: 0.75, output: 3.75 },
};
const FALLBACK_CLAUDE_PRICE = MODEL_PRICES["claude-sonnet-5"]; // 未知のClaudeモデルは安全側にsonnet-5単価で見積もる
const FALLBACK_GEMINI_PRICE = MODEL_PRICES["gemini-flash-latest"]; // 未知のGeminiモデルはflash単価で見積もる

function estimateCostUsd(
  model: string | null,
  inputTokens: number,
  outputTokens: number,
  fallback: { input: number; output: number },
): number {
  const price = (model && MODEL_PRICES[model]) || fallback;
  return (inputTokens * price.input + outputTokens * price.output) / 1_000_000;
}

interface CostRow {
  day: string;
  model: string | null;
  inputTokens: number;
  outputTokens: number;
  calls: number;
}

// Claude/Gemini双方のコスト集計で共通の畳み込みロジック（2026-09-10リファクタリングで
// handleClaudeCostStatsから切り出し、handleGeminiCostStatsと共有できるようにした）。
// SQL側でSUM(cost)しない理由：モデルをまたいで単価が異なるため、行ごとに
// estimateCostUsd()を適用してからJS側で合算する必要がある。
function aggregateCostRows(rows: CostRow[], fallback: { input: number; output: number }) {
  const dailyMap = new Map<string, { tokens: number; costUsd: number; calls: number }>();
  const byModelMap = new Map<string, { inputTokens: number; outputTokens: number; costUsd: number; calls: number }>();
  let totalCostUsd = 0;
  let totalTokens = 0;
  let totalCalls = 0;

  for (const r of rows) {
    const cost = estimateCostUsd(r.model, r.inputTokens, r.outputTokens, fallback);
    const tokens = r.inputTokens + r.outputTokens;

    const day = dailyMap.get(r.day) ?? { tokens: 0, costUsd: 0, calls: 0 };
    day.tokens += tokens;
    day.costUsd += cost;
    day.calls += r.calls;
    dailyMap.set(r.day, day);

    const modelKey = r.model ?? "unknown";
    const m = byModelMap.get(modelKey) ?? { inputTokens: 0, outputTokens: 0, costUsd: 0, calls: 0 };
    m.inputTokens += r.inputTokens;
    m.outputTokens += r.outputTokens;
    m.costUsd += cost;
    m.calls += r.calls;
    byModelMap.set(modelKey, m);

    totalCostUsd += cost;
    totalTokens += tokens;
    totalCalls += r.calls;
  }

  return {
    totalCostUsd,
    totalTokens,
    totalCalls,
    daily: Array.from(dailyMap.entries()).map(([day, v]) => ({ day, ...v })).sort((a, b) => a.day.localeCompare(b.day)),
    byModel: Array.from(byModelMap.entries()).map(([model, v]) => ({ model, ...v })),
  };
}

// POST /admin/usage/stats — 日次のトークン使用量集計（既存GAS adminTokenUsageStats相当）。
// 管理画面の折れ線/棒グラフ表示用。日付はUTC基準（SQLiteのunixepoch由来のためタイムゾーン変換はしない）。
export async function handleUsageStats(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { days?: number };
  const days = Math.min(Math.max(body.days ?? 14, 1), 90);
  const sinceTs = Math.floor(Date.now() / 1000) - days * 86400;

  const dailyRes = await env.DB.prepare(
    `SELECT date(created_at, 'unixepoch') AS day, SUM(tokens_used) AS tokens, COUNT(*) AS queries
     FROM audit_log
     WHERE created_at >= ?
     GROUP BY day
     ORDER BY day ASC`,
  )
    .bind(sinceTs)
    .all<{ day: string; tokens: number; queries: number }>();

  const byUserRes = await env.DB.prepare(
    `SELECT u.display_name AS displayName, u.user_id AS userId, SUM(a.tokens_used) AS tokens, COUNT(*) AS queries
     FROM audit_log a
     JOIN users u ON u.user_id = a.user_id
     WHERE a.created_at >= ?
     GROUP BY a.user_id
     ORDER BY tokens DESC`,
  )
    .bind(sinceTs)
    .all<{
      displayName: string;
      userId: string;
      tokens: number;
      queries: number;
    }>();

  return jsonResponse(200, {
    daily: dailyRes.results ?? [],
    byUser: byUserRes.results ?? [],
    days,
    status: "ok",
  });
}

// POST /admin/rating-stats — チャット履歴への評価（役に立った/立たなかった）の集計
// （既存GAS adminRatingStats相当）。memoryテーブルは既に評価を保持しているため追加スキーマ不要。
export async function handleRatingStats(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);

  const totalsRes = await env.DB.prepare(
    `SELECT
       COUNT(*) AS total,
       SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS good,
       SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) AS bad,
       SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) AS unrated
     FROM memory`,
  ).first<{ total: number; good: number; bad: number; unrated: number }>();

  const byUserRes = await env.DB.prepare(
    `SELECT u.display_name AS displayName, m.user_id AS userId,
            COUNT(*) AS total,
            SUM(CASE WHEN m.rating = 1 THEN 1 ELSE 0 END) AS good,
            SUM(CASE WHEN m.rating = -1 THEN 1 ELSE 0 END) AS bad
     FROM memory m
     JOIN users u ON u.user_id = m.user_id
     GROUP BY m.user_id
     ORDER BY total DESC`,
  ).all<{
    displayName: string;
    userId: string;
    total: number;
    good: number;
    bad: number;
  }>();

  return jsonResponse(200, {
    total: totalsRes?.total ?? 0,
    good: totalsRes?.good ?? 0,
    bad: totalsRes?.bad ?? 0,
    unrated: totalsRes?.unrated ?? 0,
    byUser: byUserRes.results ?? [],
    status: "ok",
  });
}

// POST /admin/usage/claude-cost — Houdiniチュートリアル生成等が使うClaudeプロキシ
// （/claude/messages、claude.ts）だけの使用量・推定コストを可視化する（2026-09-10追加）。
// audit_logのnamespace_id='claude:proxy'の行はinput_tokens/output_tokens/modelを
// 持つため（migrations/0010）、RAG系（Gemini呼び出し）のトークンとは完全に分離して
// 集計できる。金額はAnthropicの公表単価に基づく推定であり、実際の請求額と若干の
// 差異が生じ得る（cache_write/cache_read分は現状このプロキシ経路では使っていない
// ため考慮していない）。
export async function handleClaudeCostStats(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { days?: number };
  const days = Math.min(Math.max(body.days ?? 30, 1), 90);
  const sinceTs = Math.floor(Date.now() / 1000) - days * 86400;

  const rowsRes = await env.DB.prepare(
    `SELECT date(created_at, 'unixepoch') AS day, model,
            SUM(COALESCE(input_tokens, 0)) AS inputTokens,
            SUM(COALESCE(output_tokens, 0)) AS outputTokens,
            COUNT(*) AS calls
     FROM audit_log
     WHERE namespace_id = 'claude:proxy' AND created_at >= ?
     GROUP BY day, model
     ORDER BY day ASC`,
  )
    .bind(sinceTs)
    .all<{ day: string; model: string | null; inputTokens: number; outputTokens: number; calls: number }>();

  const agg = aggregateCostRows(rowsRes.results ?? [], FALLBACK_CLAUDE_PRICE);

  return jsonResponse(200, { days, ...agg, status: "ok" });
}

// POST /admin/usage/gemini-cost — RAGチャット自体の生成（Gemini、query.ts/search.ts）の
// 使用量・推定コストを可視化する（2026-09-10追加、handleClaudeCostStatsと対になる存在）。
// query.ts/search.tsがinput_tokens/output_tokens/modelを埋めるようになったのは今回からで、
// namespace_id は実際のnamespace一覧（"shared:xxx,personal:yyy"等）が入るため
// 'claude:proxy' 以外の全行が対象になる。input_tokens IS NOT NULL で絞ることで、
// この変更より前に作られた列未設定の古い行（コスト計算不可）を除外している。
// 埋め込み（ナレッジ登録時のベクトル化）のコストは含まない点に注意（Gemini
// embedContent APIのレスポンスにトークン数が含まれないため未計測）。
export async function handleGeminiCostStats(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { days?: number };
  const days = Math.min(Math.max(body.days ?? 30, 1), 90);
  const sinceTs = Math.floor(Date.now() / 1000) - days * 86400;

  const rowsRes = await env.DB.prepare(
    `SELECT date(created_at, 'unixepoch') AS day, model,
            SUM(COALESCE(input_tokens, 0)) AS inputTokens,
            SUM(COALESCE(output_tokens, 0)) AS outputTokens,
            COUNT(*) AS calls
     FROM audit_log
     WHERE namespace_id != 'claude:proxy' AND input_tokens IS NOT NULL AND created_at >= ?
     GROUP BY day, model
     ORDER BY day ASC`,
  )
    .bind(sinceTs)
    .all<{ day: string; model: string | null; inputTokens: number; outputTokens: number; calls: number }>();

  const agg = aggregateCostRows(rowsRes.results ?? [], FALLBACK_GEMINI_PRICE);

  return jsonResponse(200, { days, ...agg, status: "ok" });
}

// POST /admin/audit-log — 監査ログの一覧を確認する（2026-09-12追加）。従来audit_logは
// D1に記録されるだけで、管理画面から中身を見る手段が無かった（コスト暴走や不審な
// アクセスパターンに気づく手段が実質的に無かった、というフィードバックへの対応）。
// query_hashはクエリ本文そのものではなくSHA-256ハッシュのため、この画面から質問内容が
// 漏れることはない（既存の設計方針＝本文を残さない、を踏襲）。
export async function handleAuditLogList(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { limit?: number; user?: string; namespace?: string };
  const limit = Math.min(Math.max(body.limit ?? 50, 1), 500);

  const conditions: string[] = [];
  const params: (string | number)[] = [];
  if (body.user) {
    // 2026-09-12レビューで発見・修正：当初はuser_id（SHA-256ハッシュ）の完全一致で
    // 絞り込む設計だったが、管理画面のどこにも生のuser_idを表示・コピーできる場所が
    // 無く、実質的に使えないフィルタになっていた。display_nameの部分一致に変更し、
    // 「発行済みキー一覧」に出ている名前をそのまま入力すれば絞り込めるようにした。
    conditions.push("u.display_name LIKE ?");
    params.push(`%${body.user}%`);
  }
  if (body.namespace) {
    // namespace_idはカンマ区切りで複数入りうるため部分一致で検索する
    conditions.push("a.namespace_id LIKE ?");
    params.push(`%${body.namespace}%`);
  }
  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
  params.push(limit);

  const res = await env.DB.prepare(
    `SELECT a.id, a.user_id, u.display_name AS displayName, a.namespace_id, a.difficulty,
            a.result_count, a.latency_ms, a.tokens_used, a.model, a.created_at
     FROM audit_log a
     LEFT JOIN users u ON u.user_id = a.user_id
     ${where}
     ORDER BY a.created_at DESC
     LIMIT ?`,
  )
    .bind(...params)
    .all();

  return jsonResponse(200, { entries: res.results ?? [], status: "ok" });
}
