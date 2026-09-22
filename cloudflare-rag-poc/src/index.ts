import type { Env } from "./types";
import { authenticate, ForbiddenError, requireKnowledgeEditor } from "./auth";
import { handleSearch } from "./search";
import { handleQuery } from "./query";
import { handleIngest } from "./ingest";
import { handleMemoryList, handleMemoryRate, handleMemoryPin, handlePinnedList } from "./memory";
import { handleSyncNotion, handleRetryFailedNotion } from "./notionSync";
import { handleSyncDrive, handleRetryFailedDrive } from "./driveSync";
import { handleSyncJira, handleRetryFailedJira, handleTestJiraConnection, runScheduledJiraSync } from "./jiraSync";
import { handleSyncBacklog, handleRetryFailedBacklog, handleTestBacklogConnection, runScheduledBacklogSync } from "./backlogSync";
import { handleSyncCalendar, handleRetryFailedCalendar, handleTestCalendarConnection, runScheduledCalendarSync } from "./calendarSync";
import { handleImportPlace, handleImportPlacesCsv, handleTestMapsConnection } from "./mapsImport";
import { handleJiraOAuthStart, handleJiraOAuthCallback, handleJiraOAuthDisconnect } from "./jiraOAuth";
import { handleBacklogOAuthStart, handleBacklogOAuthCallback, handleBacklogOAuthDisconnect } from "./backlogOAuth";
import { handleCalendarOAuthStart, handleCalendarOAuthCallback, handleCalendarOAuthDisconnect } from "./calendarOAuth";
import { handleSlackOAuthStart, handleSlackOAuthCallback, handleSlackOAuthDisconnect } from "./slackOAuth";
import { getConnection } from "./oauthConnections";
import { oauthResultPage } from "./http";
import { handleSetKbSource, handleKbHistory, handleKbOverview } from "./kbAdmin";
import {
  handleCreateKey,
  handleListKeys,
  handleDeleteKey,
  handleUpdateKeyNamespaces,
  handleUpdateKeyRole,
  handleUpdateKeyExpiry,
  handleSetKeyCapacity,
  handleChargeKey,
  handleBootstrapAdmin,
} from "./keyAdmin";
import { handleAddFaq } from "./faqAdd";
import { handleCreateNamespace, handleListNamespaces, handleDeleteNamespace, handleSetNamespaceLimit, handleSetNamespaceBudget, handleNamespaceUsage } from "./namespaceAdmin";
import { handleGraph } from "./graph";
import { handleUsageStats, handleRatingStats, handleClaudeCostStats, handleGeminiCostStats, handleAuditLogList } from "./usageStats";
import { handleImportUrl, handleCrawlUrl } from "./urlImport";
import { handleListDocuments, handleDeleteDocument, handleFindDuplicateDocuments } from "./kbDocuments";
import { handleImportQaCsv } from "./qaImport";
import { handleKbRollback } from "./kbRollback";
import { handleImportYoutube, handleUploadDoc } from "./mediaImport";
import { handleHealthCheck, handleTestAlert, checkHealthAndAlert } from "./healthCheck";
import { handleBackupExport } from "./backup";
import { handleClaudeMessages } from "./claude";
import { handleMyNamespaces, handleMyBudget } from "./retrieve";
import { RateLimitedError } from "./rateLimit";
import { chatUiHtml } from "./chatUi";
import { BudgetExceededError } from "./budget";

const MEMORY_RETENTION_DAYS = 90;
// 既存GASのpurgeExpiredTokenUsage_/purgeExpiredClaudeUsage_相当。GAS版はGoogle Sheetsの
// 行数上限を避けるための対策だったが、D1にはその制約は無いため、監査目的も踏まえて
// memoryより長めの180日にしている（2026-08-27追加。以前はaudit_logが無期限に蓄積していた）。
const AUDIT_LOG_RETENTION_DAYS = 180;
// 再帰クロールのバッチ進行状態（crawl_jobs）は、ブラウザを閉じた等で完走せずに
// 放置されたジョブがテーブルに残り続けないよう、一定期間で掃除する（2026-09-13追加）。
const CRAWL_JOB_ABANDONED_DAYS = 1;

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/health") {
      return json(200, { status: "ok" });
    }

    // Webチャット画面（既存GAS getChatHtml_相当）。認証はページ内のAPIキー入力で
    // クライアント側からfetchする各APIコール時に行う。
    if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/chat")) {
      return new Response(chatUiHtml(), { headers: { "content-type": "text/html; charset=utf-8" } });
    }

    // OAuthクリック接続化（2026-09-22追加、oauthConnections.ts参照）。start/callbackは
    // 外部サービスへのブラウザ直接ナビゲーション（リダイレクト）で叩かれるため、
    // 他の全エンドポイントと違いGETかつAuthorizationヘッダー無しで届く。そのためこの
    // ルーティングは下のauthenticate()より前・POST限定ゲートより前に置く必要がある
    // （startはクエリの?keyで、callbackはstate自体の検証で認可を確認する）。
    if (req.method === "GET" && url.pathname.startsWith("/admin/oauth/")) {
      const [, , , service, action] = url.pathname.split("/");
      try {
        switch (`${service}/${action}`) {
          case "jira/start":
            return await handleJiraOAuthStart(req, env);
          case "jira/callback":
            return await handleJiraOAuthCallback(req, env);
          case "backlog/start":
            return await handleBacklogOAuthStart(req, env);
          case "backlog/callback":
            return await handleBacklogOAuthCallback(req, env);
          case "google_calendar/start":
            return await handleCalendarOAuthStart(req, env);
          case "google_calendar/callback":
            return await handleCalendarOAuthCallback(req, env);
          case "slack/start":
            return await handleSlackOAuthStart(req, env);
          case "slack/callback":
            return await handleSlackOAuthCallback(req, env);
          default:
            return json(404, { error: "未定義のOAuthエンドポイントです" });
        }
      } catch (err) {
        return oauthResultPage(false, `予期しないエラーが発生しました: ${err instanceof Error ? err.message : String(err)}`);
      }
    }

    if (req.method !== "POST") {
      return json(405, { error: "POST のみ対応しています" });
    }

    // 管理者キーが1つも無い初回セットアップ専用の抜け道。authenticate()より前段で処理する
    // （そもそも認証できるキーが存在しない、という鶏卵問題への対応。src/keyAdmin.ts参照）。
    // handleBootstrapAdmin自身が「管理者が1人でも存在すれば403」を強制するため、
    // 認証をバイパスしても既存環境を乗っ取れるわけではない。
    if (url.pathname === "/admin/bootstrap") {
      try {
        return await handleBootstrapAdmin(req, env);
      } catch (err) {
        return json(500, { error: err instanceof Error ? err.message : String(err) });
      }
    }

    const user = await authenticate(req, env);
    if (!user) {
      return json(401, { error: "認証に失敗しました（Authorization: Bearer <APIキー> が必要です）" });
    }

    try {
      switch (url.pathname) {
        case "/search":
          return await handleSearch(req, env, user);
        case "/query":
          return await handleQuery(req, env, user);
        case "/ingest":
          return await handleIngest(req, env, user);
        case "/memory/list":
          return await handleMemoryList(req, env, user);
        case "/memory/rate":
          return await handleMemoryRate(req, env, user);
        case "/memory/pin":
          return await handleMemoryPin(req, env, user);
        case "/memory/pinned":
          return await handlePinnedList(req, env, user);
        case "/graph":
          return await handleGraph(req, env, user);
        case "/admin/sync/notion":
          return await handleSyncNotion(req, env, user);
        case "/admin/sync/drive":
          return await handleSyncDrive(req, env, user);
        case "/admin/sync/notion/retry-failed":
          return await handleRetryFailedNotion(req, env, user);
        case "/admin/sync/drive/retry-failed":
          return await handleRetryFailedDrive(req, env, user);
        case "/admin/sync/jira":
          return await handleSyncJira(req, env, user);
        case "/admin/sync/jira/retry-failed":
          return await handleRetryFailedJira(req, env, user);
        case "/admin/sync/backlog":
          return await handleSyncBacklog(req, env, user);
        case "/admin/sync/backlog/retry-failed":
          return await handleRetryFailedBacklog(req, env, user);
        case "/admin/sync/calendar":
          return await handleSyncCalendar(req, env, user);
        case "/admin/sync/calendar/retry-failed":
          return await handleRetryFailedCalendar(req, env, user);
        case "/admin/kb/import-place":
          return await handleImportPlace(req, env, user);
        case "/admin/kb/import-places-csv":
          return await handleImportPlacesCsv(req, env, user);
        case "/admin/kb/test-connection/jira":
          return await handleTestJiraConnection(req, env, user);
        case "/admin/kb/test-connection/backlog":
          return await handleTestBacklogConnection(req, env, user);
        case "/admin/kb/test-connection/calendar":
          return await handleTestCalendarConnection(req, env, user);
        case "/admin/kb/test-connection/maps":
          return await handleTestMapsConnection(req, env, user);
        case "/admin/oauth/jira/disconnect":
          return await handleJiraOAuthDisconnect(req, env, user);
        case "/admin/oauth/backlog/disconnect":
          return await handleBacklogOAuthDisconnect(req, env, user);
        case "/admin/oauth/google_calendar/disconnect":
          return await handleCalendarOAuthDisconnect(req, env, user);
        case "/admin/oauth/slack/disconnect":
          return await handleSlackOAuthDisconnect(req, env, user);
        case "/admin/oauth/status": {
          requireKnowledgeEditor(user);
          const [jira, backlog, googleCalendar, slack] = await Promise.all([
            getConnection(env, "jira"),
            getConnection(env, "backlog"),
            getConnection(env, "google_calendar"),
            getConnection(env, "slack"),
          ]);
          return json(200, {
            status: "ok",
            jira: jira ? { connected: true, label: jira.extra.siteName ?? "Jira" } : { connected: false },
            backlog: backlog ? { connected: true, label: backlog.extra.spaceUrl ?? "Backlog" } : { connected: false },
            google_calendar: googleCalendar ? { connected: true, label: "Google" } : { connected: false },
            slack: slack
              ? {
                  connected: true,
                  label: [slack.extra.teamName, slack.extra.channel ? `#${slack.extra.channel}` : ""]
                    .filter(Boolean)
                    .join(" / ") || "Slack",
                }
              : { connected: false },
          });
        }
        case "/admin/kb/set-source":
          return await handleSetKbSource(req, env, user);
        case "/admin/kb/history":
          return await handleKbHistory(req, env, user);
        case "/admin/kb/overview":
          return await handleKbOverview(req, env, user);
        case "/admin/keys/create":
          return await handleCreateKey(req, env, user);
        case "/admin/keys/list":
          return await handleListKeys(req, env, user);
        case "/admin/keys/delete":
          return await handleDeleteKey(req, env, user);
        case "/admin/keys/update-namespaces":
          return await handleUpdateKeyNamespaces(req, env, user);
        case "/admin/keys/update-role":
          return await handleUpdateKeyRole(req, env, user);
        case "/admin/keys/set-expiry":
          return await handleUpdateKeyExpiry(req, env, user);
        case "/admin/keys/set-capacity":
          return await handleSetKeyCapacity(req, env, user);
        case "/admin/keys/charge":
          return await handleChargeKey(req, env, user);
        case "/admin/namespaces/create":
          return await handleCreateNamespace(req, env, user);
        case "/admin/namespaces/list":
          return await handleListNamespaces(req, env, user);
        case "/admin/namespaces/delete":
          return await handleDeleteNamespace(req, env, user);
        case "/admin/namespaces/set-limit":
          return await handleSetNamespaceLimit(req, env, user);
        case "/admin/namespaces/set-budget":
          return await handleSetNamespaceBudget(req, env, user);
        case "/admin/namespaces/usage":
          return await handleNamespaceUsage(req, env, user);
        case "/admin/usage/stats":
          return await handleUsageStats(req, env, user);
        case "/admin/rating-stats":
          return await handleRatingStats(req, env, user);
        case "/admin/usage/claude-cost":
          return await handleClaudeCostStats(req, env, user);
        case "/admin/usage/gemini-cost":
          return await handleGeminiCostStats(req, env, user);
        case "/admin/audit-log":
          return await handleAuditLogList(req, env, user);
        case "/admin/kb/import-url":
          return await handleImportUrl(req, env, user);
        case "/admin/kb/crawl-url":
          return await handleCrawlUrl(req, env, user);
        case "/admin/kb/list-documents":
          return await handleListDocuments(req, env, user);
        case "/admin/kb/delete-document":
          return await handleDeleteDocument(req, env, user);
        case "/admin/kb/find-duplicates":
          return await handleFindDuplicateDocuments(req, env, user);
        case "/admin/kb/import-qa-csv":
          return await handleImportQaCsv(req, env, user);
        case "/admin/kb/add-faq":
          return await handleAddFaq(req, env, user);
        case "/admin/kb/rollback":
          return await handleKbRollback(req, env, user);
        case "/admin/kb/import-youtube":
          return await handleImportYoutube(req, env, user);
        case "/admin/kb/upload-doc":
          return await handleUploadDoc(req, env, user);
        case "/admin/health/check":
          return await handleHealthCheck(req, env, user);
        case "/admin/health/test-alert":
          return await handleTestAlert(req, env, user);
        case "/admin/backup/export":
          return await handleBackupExport(req, env, user);
        case "/claude/messages":
          return await handleClaudeMessages(req, env, user);
        case "/me/namespaces":
          return await handleMyNamespaces(req, env, user);
        case "/me/budget":
          return await handleMyBudget(req, env, user);
        default:
          return json(404, { error: `未定義のエンドポイントです: ${url.pathname}` });
      }
    } catch (err) {
      if (err instanceof BudgetExceededError) {
        return json(429, { error: err.message });
      }
      if (err instanceof RateLimitedError) {
        return json(429, { error: err.message });
      }
      if (err instanceof ForbiddenError) {
        return json(403, { error: err.message });
      }
      return json(500, { error: err instanceof Error ? err.message : String(err) });
    }
  },

  // Cron Trigger本体。wrangler.jsonc の triggers.crons に登録した3つのスケジュールを
  // event.cron の値で判別する：
  //   "0 3 * * *"  … 期限切れチャット履歴の自動削除（既存GAS purgeExpiredMemory_相当）
  //   "*/30 * * * *" … ヘルスチェック（既存GAS checkHealthAndAlert_相当）
  //   "0 4 * * *"  … Jira/Backlog/カレンダー連携の自動差分同期（2026-09-19追加、
  //                  jiraSync.ts/backlogSync.ts/calendarSync.tsのrunScheduledXxxSync参照）
  async scheduled(event: ScheduledController, env: Env): Promise<void> {
    if (event.cron === "0 3 * * *") {
      const memoryCutoff = Math.floor(Date.now() / 1000) - MEMORY_RETENTION_DAYS * 86400;
      await env.DB.prepare("DELETE FROM memory WHERE created_at < ?").bind(memoryCutoff).run();
      const auditCutoff = Math.floor(Date.now() / 1000) - AUDIT_LOG_RETENTION_DAYS * 86400;
      await env.DB.prepare("DELETE FROM audit_log WHERE created_at < ?").bind(auditCutoff).run();
      const crawlJobCutoff = Math.floor(Date.now() / 1000) - CRAWL_JOB_ABANDONED_DAYS * 86400;
      await env.DB.prepare("DELETE FROM crawl_jobs WHERE updated_at < ?").bind(crawlJobCutoff).run();
      return;
    }
    if (event.cron === "0 4 * * *") {
      // 1つのnamespace/連携の失敗が他を止めないよう、各関数内部でnamespaceごとにcatch
      // している（runScheduledJiraSync等の実装参照）ため、ここでは単純に3つとも実行する。
      await runScheduledJiraSync(env);
      await runScheduledBacklogSync(env);
      await runScheduledCalendarSync(env);
      return;
    }
    await checkHealthAndAlert(env);
  },
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
