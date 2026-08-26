import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { sendSlackAlert, sendGmailAlert } from "./alerts";

export interface HealthIssue {
  severity: "warning" | "error";
  message: string;
}

const RECENT_ERROR_WINDOW_SEC = 3600;
const BUDGET_WARNING_RATIO = 0.9;

// 異常検知チェック本体（既存GAS checkHealthAndAlert_相当）。D1接続・直近のKB同期エラー・
// トークン予算の枯渇間近を確認する。ダウンタイム検知というより「気づかないと困る」種類の
// 異常にフォーカスした軽量なチェックにしている。
export async function runHealthCheck(env: Env): Promise<HealthIssue[]> {
  const issues: HealthIssue[] = [];

  try {
    await env.DB.prepare("SELECT 1").first();
  } catch (err) {
    issues.push({
      severity: "error",
      message: `D1データベースへの接続に失敗しました: ${err instanceof Error ? err.message : String(err)}`,
    });
    return issues; // D1が死んでいる場合は以降のチェックも実行できない
  }

  const since = Math.floor(Date.now() / 1000) - RECENT_ERROR_WINDOW_SEC;
  const errRes = await env.DB.prepare(
    "SELECT COUNT(*) AS cnt FROM kb_log WHERE status = 'error' AND created_at >= ?",
  )
    .bind(since)
    .first<{ cnt: number }>();
  if ((errRes?.cnt ?? 0) > 0) {
    issues.push({
      severity: "warning",
      message: `直近${RECENT_ERROR_WINDOW_SEC / 60}分間でKB同期エラーが${errRes!.cnt}件発生しています`,
    });
  }

  const budgetRes = await env.DB.prepare(
    `SELECT u.display_name AS displayName, tb.used_tokens AS used, tb.limit_tokens AS limitTokens
     FROM token_budgets tb
     JOIN users u ON u.user_id = tb.user_id
     WHERE tb.limit_tokens IS NOT NULL AND tb.limit_tokens > 0
       AND (tb.used_tokens * 1.0 / tb.limit_tokens) >= ?`,
  )
    .bind(BUDGET_WARNING_RATIO)
    .all<{ displayName: string; used: number; limitTokens: number }>();
  for (const r of budgetRes.results ?? []) {
    issues.push({
      severity: "warning",
      message: `${r.displayName}のRAGトークン予算が残りわずかです（${r.used}/${r.limitTokens}）`,
    });
  }

  return issues;
}

export async function checkHealthAndAlert(env: Env): Promise<HealthIssue[]> {
  const issues = await runHealthCheck(env);
  if (issues.length > 0) {
    const body = issues.map((i) => `[${i.severity}] ${i.message}`).join("\n");
    await Promise.allSettled([
      sendSlackAlert(env, `⚠️ RAG POC ヘルスチェックで問題を検出しました\n${body}`),
      sendGmailAlert(env, "【RAG POC】ヘルスチェックアラート", body),
    ]);
  }
  return issues;
}

// POST /admin/health/check — 手動でヘルスチェックを実行する（問題があればアラートも送る）
export async function handleHealthCheck(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const issues = await checkHealthAndAlert(env);
  return jsonResponse(200, { issues, status: "ok" });
}

// POST /admin/health/test-alert — Slack/Gmailの設定確認用に、実際の異常有無に関わらず
// テスト通知を送る。セットアップがうまくいっているかをすぐ確認できるようにするため。
export async function handleTestAlert(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const results: Record<string, string> = {};

  if (env.SLACK_WEBHOOK_URL) {
    try {
      await sendSlackAlert(env, "🔔 RAG POCからのテスト通知です。これが届いていればSlack連携は正常です。");
      results.slack = "ok";
    } catch (err) {
      results.slack = `error: ${err instanceof Error ? err.message : String(err)}`;
    }
  } else {
    results.slack = "未設定（SLACK_WEBHOOK_URLをシークレット登録してください）";
  }

  if (env.GMAIL_OAUTH_REFRESH_TOKEN && env.GMAIL_ALERT_TO) {
    try {
      await sendGmailAlert(env, "【RAG POC】テスト通知", "これはRAG POCからのテスト通知です。この通知が届いていればGmail連携は正常です。");
      results.gmail = "ok";
    } catch (err) {
      results.gmail = `error: ${err instanceof Error ? err.message : String(err)}`;
    }
  } else {
    results.gmail = "未設定（GMAIL_OAUTH_CLIENT_ID等・GMAIL_ALERT_TOをシークレット登録してください）";
  }

  return jsonResponse(200, { results, status: "ok" });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
