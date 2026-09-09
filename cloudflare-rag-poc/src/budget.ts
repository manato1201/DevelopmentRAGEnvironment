import type { Env } from "./types";

// トークン予算のチェック・消費（既存GAS _hasQuotaRemaining_ / _consumeKeyBudget_相当）。
// GASと同じく「サーバー側が唯一の判定者」であり、クライアントから改ざんできない設計にする
// （token_budgetsテーブルはWorkers側でのみ更新し、外部に書き込みAPIを公開しない）。

export class BudgetExceededError extends Error {
  constructor(budgetType: string) {
    super(`トークン予算(${budgetType})の上限に達しています`);
    this.name = "BudgetExceededError";
  }
}

interface BudgetRow {
  limit_tokens: number;
  used_tokens: number;
  reset_at: number | null;
  reset_interval_hours: number | null;
}

// 予定リセット時刻を過ぎていれば使用量を0に戻す（既存GAS _applyScheduledResets_相当）。
// アクセスのたびに遅延評価する方式（Cron Triggerを使わず、呼び出し時点でチェックするだけで済む）。
async function applyScheduledResetIfDue(env: Env, userId: string, budgetType: "rag" | "claude", row: BudgetRow): Promise<BudgetRow> {
  if (!row.reset_interval_hours || !row.reset_at) return row;
  const now = Math.floor(Date.now() / 1000);
  if (now < row.reset_at) return row;

  const nextResetAt = row.reset_at + row.reset_interval_hours * 3600;
  await env.DB.prepare("UPDATE token_budgets SET used_tokens = 0, reset_at = ? WHERE user_id = ? AND budget_type = ?")
    .bind(nextResetAt, userId, budgetType)
    .run();
  return { ...row, used_tokens: 0, reset_at: nextResetAt };
}

// 現在の残量を確認する（予算未設定＝無制限として扱う。既存GASのフォールバック方針を踏襲）。
// /me/budget（ユーザー自身への残量表示）からも使うためexportする。
export async function getRemaining(env: Env, userId: string, budgetType: "rag" | "claude"): Promise<{ limit: number; used: number; remaining: number } | null> {
  const row = await env.DB.prepare(
    "SELECT limit_tokens, used_tokens, reset_at, reset_interval_hours FROM token_budgets WHERE user_id = ? AND budget_type = ?"
  )
    .bind(userId, budgetType)
    .first<BudgetRow>();
  if (!row) return null; // 予算レコードが無いユーザーは無制限（開発・検証用の既定）
  const fresh = await applyScheduledResetIfDue(env, userId, budgetType, row);
  return { limit: fresh.limit_tokens, used: fresh.used_tokens, remaining: fresh.limit_tokens - fresh.used_tokens };
}

// 呼び出し前に「見積もりトークン数」だけ先んじてused_tokensへ加算し、その結果が上限を
// 超えないかを1回のUPDATE文で原子的に判定する（2026-09-04、check-then-writeが2回の別々の
// D1往復に分かれておりレース条件があった不備を修正）。
//
// 背景: 実際に使うトークン数は呼び出し（Gemini埋め込み・生成）が終わるまで分からないため、
// 「見積もり」を先に確保（reserve）し、実測値が分かった時点でreconcileBudget()で差分だけ
// 調整する、という2段階方式にする。UPDATE ... WHERE used_tokens + ? <= limit_tokens は
// SQLite/D1が単一の書き込みとして直列化するため、同時に複数リクエストが来ても
// 「現在の最新のused_tokensに対して」判定される＝先に確保した分は後続の判定に必ず
// 反映され、TOCTOUによる予算超過（例: 残り1トークンの状態でN件同時リクエストが来て
// 全件が同じ「残り1」を見て通過してしまう）を防げる。
// 予算レコードが無いユーザーは常に成功（無制限、既存の方針を踏襲）。
export async function reserveBudget(env: Env, userId: string, budgetType: "rag" | "claude", estimate: number): Promise<boolean> {
  const row = await env.DB.prepare(
    "SELECT limit_tokens, used_tokens, reset_at, reset_interval_hours FROM token_budgets WHERE user_id = ? AND budget_type = ?"
  )
    .bind(userId, budgetType)
    .first<BudgetRow>();
  if (!row) return true; // 予算レコードが無いユーザーは無制限
  await applyScheduledResetIfDue(env, userId, budgetType, row);

  const res = await env.DB.prepare(
    "UPDATE token_budgets SET used_tokens = used_tokens + ? WHERE user_id = ? AND budget_type = ? AND used_tokens + ? <= limit_tokens"
  )
    .bind(estimate, userId, budgetType, estimate)
    .run();
  return (res.meta.changes ?? 0) > 0;
}

// reserveBudget()で確保した見積もり分と、実測値の差分だけused_tokensを調整する。
// 実測が見積もりより少なければ払い戻し（減算）、多ければ追加加算する。
// 予算レコードが無いユーザーは何もしない（無制限のまま、reserveBudget側で既にreserveしていない）。
export async function reconcileBudget(env: Env, userId: string, budgetType: "rag" | "claude", estimate: number, actual: number): Promise<void> {
  const delta = actual - estimate;
  if (delta === 0) return;
  await env.DB.prepare(
    "UPDATE token_budgets SET used_tokens = MAX(0, used_tokens + ?) WHERE user_id = ? AND budget_type = ?"
  )
    .bind(delta, userId, budgetType)
    .run();
}
