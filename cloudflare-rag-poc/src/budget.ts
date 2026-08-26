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

// 現在の残量を確認する（予算未設定＝無制限として扱う。既存GASのフォールバック方針を踏襲）
async function getRemaining(env: Env, userId: string, budgetType: "rag" | "claude"): Promise<number | null> {
  const row = await env.DB.prepare(
    "SELECT limit_tokens, used_tokens, reset_at, reset_interval_hours FROM token_budgets WHERE user_id = ? AND budget_type = ?"
  )
    .bind(userId, budgetType)
    .first<BudgetRow>();
  if (!row) return null; // 予算レコードが無いユーザーは無制限（開発・検証用の既定）
  const fresh = await applyScheduledResetIfDue(env, userId, budgetType, row);
  return fresh.limit_tokens - fresh.used_tokens;
}

// 呼び出し前に残量を確認する。0以下なら例外を投げて処理を止める。
export async function assertBudgetAvailable(env: Env, userId: string, budgetType: "rag" | "claude"): Promise<void> {
  const remaining = await getRemaining(env, userId, budgetType);
  if (remaining !== null && remaining <= 0) {
    throw new BudgetExceededError(budgetType);
  }
}

// 実際に使った分だけused_tokensに加算する（呼び出し後に実測トークン数で消費）。
// 予算レコードが無いユーザーは何もしない（無制限のまま）。
export async function consumeBudget(env: Env, userId: string, budgetType: "rag" | "claude", amount: number): Promise<void> {
  if (amount <= 0) return;
  await env.DB.prepare(
    "UPDATE token_budgets SET used_tokens = used_tokens + ? WHERE user_id = ? AND budget_type = ?"
  )
    .bind(amount, userId, budgetType)
    .run();
}
