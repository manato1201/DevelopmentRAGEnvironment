import type { Env } from "./types";
import { authenticate, ForbiddenError, requireKnowledgeEditor } from "./auth";
import { handleSearch } from "./search";
import { handleQuery, handleQueryStream } from "./query";
import { handleIngest } from "./ingest";
import { handleMemoryList, handleMemoryRate, handleMemoryPin, handlePinnedList, handleMemoryGet, handleMemoryImport } from "./memory";
import { handleSyncNotion, handleRetryFailedNotion, handlePreviewNotion } from "./notionSync";
import { handleSyncDrive, handleRetryFailedDrive, handlePreviewDrive } from "./driveSync";
import { handleSyncJira, handleRetryFailedJira, handleTestJiraConnection, handleListJiraProjects, runScheduledJiraSync, handlePreviewJira } from "./jiraSync";
import { handleSyncBacklog, handleRetryFailedBacklog, handleTestBacklogConnection, handleListBacklogProjects, runScheduledBacklogSync, handlePreviewBacklog } from "./backlogSync";
import { handleSyncCalendar, handleRetryFailedCalendar, handleTestCalendarConnection, handleListCalendars, runScheduledCalendarSync, handlePreviewCalendar } from "./calendarSync";
import { handleImportPlace, handleImportPlacesCsv, handleTestMapsConnection } from "./mapsImport";
import { handleJiraOAuthStart, handleJiraOAuthCallback, handleJiraOAuthDisconnect } from "./jiraOAuth";
import { handleBacklogOAuthStart, handleBacklogOAuthCallback, handleBacklogOAuthDisconnect } from "./backlogOAuth";
import { handleCalendarOAuthStart, handleCalendarOAuthCallback, handleCalendarOAuthDisconnect } from "./calendarOAuth";
import { handleListCrawlSchedules, handleSaveCrawlSchedule, handleDeleteCrawlSchedule, runScheduledCrawls } from "./crawlSchedules";
import { handleSlackCommand, handleSlackLinkCode, handleSlackStatus, handleSlackUnlink } from "./slackBot";
import { handleSlackEvents } from "./slackEvents";
import { handleMyGrowth, handleMyGrowthReset } from "./growth";
import { handlePilotSummary } from "./pilotStats";
import { handlePresetList, handlePresetSave, handlePresetDelete } from "./presets";
import { handleThreadList, handleThreadGet, handleThreadRename, handleThreadDelete } from "./threads";
import { handleKnowledgeGaps } from "./insights";
import { handleListStaging, handleSetStaging, handleRemoveStaging, handleStagingDocs, handlePromoteStaging } from "./staging";
import { handleListSyncTargets, handleAddSyncTarget, handleRemoveSyncTarget } from "./syncTargets";
import { handleMyConnections } from "./myConnections";
import { handleGoogleOAuthStart, handleGoogleOAuthCallback, handleGoogleOAuthDisconnect, googleOAuthStatus } from "./googleOAuth";
import { handleSyncGmail, handleRetryFailedGmail, handleListGmailLabels, handleTestGmailConnection, handlePreviewGmail } from "./gmailSync";
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
import { handleImportUrl, handleCrawlUrl, handleListCrawlJobs, handleDiscardCrawlJob } from "./urlImport";
import { handleListDocuments, handleDeleteDocument, handleFindDuplicateDocuments } from "./kbDocuments";
import { handleImportQaCsv } from "./qaImport";
import { handleKbRollback } from "./kbRollback";
import { handleImportYoutube, handleUploadDoc } from "./mediaImport";
import { handleHealthCheck, handleTestAlert, checkHealthAndAlert } from "./healthCheck";
import { handleBackupExport } from "./backup";
import { handleClaudeMessages } from "./claude";
import { handleTts } from "./tts";
import { handleOAuthStartToken } from "./oauthConnections";
import { handleMcpOAuthStart, handleMcpOAuthCallback, handleMcpStatus, handleMcpDisconnect, handleMcpTools, handleMcpSetTools, handleMcpSetChat, handleMcpCall, handleMyMcp, handleMcpConfirm, handleMcpCancel } from "./mcp/routes";
import { purgeExpiredApprovals } from "./mcp/approval";
import { handleTutorialFeedbackSubmit, handleTutorialFeedbackList, handleTutorialFeedbackStats } from "./tutorialFeedback";
import { handleMyNamespaces, handleMyBudget } from "./retrieve";
import { RateLimitedError } from "./rateLimit";
import { chatUiHtml } from "./chatUi";
import { BudgetExceededError } from "./budget";

const MEMORY_RETENTION_DAYS = 90;
const SECURITY_HEADERS = {
  "x-frame-options": "DENY",
  "content-security-policy": "frame-ancestors 'none'",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};
// 既存GASのpurgeExpiredTokenUsage_/purgeExpiredClaudeUsage_相当。GAS版はGoogle Sheetsの
// 行数上限を避けるための対策だったが、D1にはその制約は無いため、監査目的も踏まえて
// memoryより長めの180日にしている（2026-08-27追加。以前はaudit_logが無期限に蓄積していた）。
const AUDIT_LOG_RETENTION_DAYS = 180;
// 再帰クロールのバッチ進行状態（crawl_jobs）は、ブラウザを閉じた等で完走せずに
// 放置されたジョブがテーブルに残り続けないよう、一定期間で掃除する（2026-09-13追加）。
const CRAWL_JOB_ABANDONED_DAYS = 1;

export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/health") {
      return json(200, { status: "ok" });
    }

    // Webチャット画面（既存GAS getChatHtml_相当）。認証はページ内のAPIキー入力で
    // クライアント側からfetchする各APIコール時に行う。
    if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/chat")) {
      // 開いたままの古い画面が、デプロイ後も古いスクリプトで動き続けないよう、毎回サーバーに確認させる（2026-10-21）。
      // 【2026-10-22】他のサイトの枠（iframe）に埋め込まれて、画面の上でボタンを押させる（クリックジャッキング）ことを防ぐ。
      // 画面は、ブラウザに保存したAPIキーで動くため、枠の中でも、持ち主の権限で操作できてしまう。
      return new Response(chatUiHtml(), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-cache", ...SECURITY_HEADERS } });
    }

    // ブラウザが自動で取りに来る /favicon.ico に、405（開発者ツールの赤いエラー）を返さない。アイコンは無いので、中身なしで返す。
    if (req.method === "GET" && url.pathname === "/favicon.ico") {
      return new Response(null, { status: 204, headers: { "cache-control": "public, max-age=86400" } });
    }

    // OAuthクリック接続化（2026-09-22追加、oauthConnections.ts参照）。start/callbackは
    // 外部サービスへのブラウザ直接ナビゲーション（リダイレクト）で叩かれるため、
    // 他の全エンドポイントと違いGETかつAuthorizationヘッダー無しで届く。そのためこの
    // ルーティングは下のauthenticate()より前・POST限定ゲートより前に置く必要がある
    // （startはクエリの?keyで、callbackはstate自体の検証で認可を確認する）。
    if (req.method === "GET" && url.pathname.startsWith("/admin/oauth/")) {
      const [, , , service, action, step] = url.pathname.split("/");
      try {
        // 公式MCPサーバー連携（src/mcp/）。/admin/oauth/mcp/callback と /admin/oauth/mcp/<provider>/start
        if (service === "mcp") {
          if (action === "callback") return await handleMcpOAuthCallback(req, env);
          if (step === "start") return await handleMcpOAuthStart(req, env, action);
          return json(404, { error: "未定義のOAuthエンドポイントです" });
        }
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
          case "google_drive/start":
            return await handleGoogleOAuthStart(req, env, "google_drive");
          case "google_drive/callback":
            return await handleGoogleOAuthCallback(req, env, "google_drive");
          case "gmail/start":
            return await handleGoogleOAuthStart(req, env, "gmail");
          case "gmail/callback":
            return await handleGoogleOAuthCallback(req, env, "gmail");
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
    // Slackのスラッシュコマンド。APIキーではなくSlackの署名で確認するため、authenticate()より前に置く。
    // Slackのチャット（メンション・DM）。同じく署名で確認するため、authenticate()より前に置く。
    if (url.pathname === "/slack/events") {
      try {
        return await handleSlackEvents(req, env, ctx);
      } catch (err) {
        return json(500, { error: err instanceof Error ? err.message : String(err) });
      }
    }
    if (url.pathname === "/slack/command") {
      try {
        return await handleSlackCommand(req, env, ctx);
      } catch (err) {
        return json(500, { error: err instanceof Error ? err.message : String(err) });
      }
    }

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
        case "/query/stream":
          return await handleQueryStream(req, env, user, ctx);
        case "/ingest":
          return await handleIngest(req, env, user);
        case "/threads/list":
          return await handleThreadList(req, env, user);
        case "/threads/get":
          return await handleThreadGet(req, env, user);
        case "/threads/rename":
          return await handleThreadRename(req, env, user);
        case "/threads/delete":
          return await handleThreadDelete(req, env, user);
        case "/memory/list":
          return await handleMemoryList(req, env, user);
        case "/memory/rate":
          return await handleMemoryRate(req, env, user);
        case "/memory/pin":
          return await handleMemoryPin(req, env, user);
        case "/memory/pinned":
          return await handlePinnedList(req, env, user);
        case "/memory/get":
          return await handleMemoryGet(req, env, user);
        case "/memory/import":
          return await handleMemoryImport(req, env, user);
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
        case "/admin/sync/gmail":
          return await handleSyncGmail(req, env, user);
        case "/admin/sync/gmail/preview":
          return await handlePreviewGmail(req, env, user);
        case "/admin/sync/calendar/preview":
          return await handlePreviewCalendar(req, env, user);
        case "/admin/sync/drive/preview":
          return await handlePreviewDrive(req, env, user);
        case "/admin/sync/notion/preview":
          return await handlePreviewNotion(req, env, user);
        case "/admin/sync/jira/preview":
          return await handlePreviewJira(req, env, user);
        case "/admin/sync/backlog/preview":
          return await handlePreviewBacklog(req, env, user);
        case "/admin/insights/gaps":
          return await handleKnowledgeGaps(req, env, user);
        case "/admin/crawl-schedules/list":
          return await handleListCrawlSchedules(req, env, user);
        case "/admin/crawl-schedules/save":
          return await handleSaveCrawlSchedule(req, env, user);
        case "/admin/crawl-schedules/delete":
          return await handleDeleteCrawlSchedule(req, env, user);
        case "/admin/staging/list":
          return await handleListStaging(req, env, user);
        case "/admin/staging/set":
          return await handleSetStaging(req, env, user);
        case "/admin/staging/remove":
          return await handleRemoveStaging(req, env, user);
        case "/admin/staging/docs":
          return await handleStagingDocs(req, env, user);
        case "/admin/staging/promote":
          return await handlePromoteStaging(req, env, user);
        case "/admin/sync-targets/list":
          return await handleListSyncTargets(req, env, user);
        case "/admin/sync-targets/add":
          return await handleAddSyncTarget(req, env, user);
        case "/admin/sync-targets/remove":
          return await handleRemoveSyncTarget(req, env, user);
        case "/admin/sync/gmail/retry-failed":
          return await handleRetryFailedGmail(req, env, user);
        case "/admin/gmail/list-labels":
          return await handleListGmailLabels(req, env, user);
        case "/admin/jira/list-projects":
          return await handleListJiraProjects(req, env, user);
        case "/admin/backlog/list-projects":
          return await handleListBacklogProjects(req, env, user);
        case "/admin/calendar/list-calendars":
          return await handleListCalendars(req, env, user);
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
        case "/admin/kb/test-connection/gmail":
          return await handleTestGmailConnection(req, env, user);
        case "/admin/kb/test-connection/maps":
          return await handleTestMapsConnection(req, env, user);
        case "/admin/oauth/jira/disconnect":
          return await handleJiraOAuthDisconnect(req, env, user);
        case "/admin/oauth/backlog/disconnect":
          return await handleBacklogOAuthDisconnect(req, env, user);
        case "/admin/oauth/google_calendar/disconnect":
          return await handleCalendarOAuthDisconnect(req, env, user);
        case "/admin/oauth/google_drive/disconnect":
          return await handleGoogleOAuthDisconnect(req, env, user, "google_drive");
        case "/admin/oauth/gmail/disconnect":
          return await handleGoogleOAuthDisconnect(req, env, user, "gmail");
        case "/admin/oauth/slack/disconnect":
          return await handleSlackOAuthDisconnect(req, env, user);
        case "/admin/oauth/status": {
          requireKnowledgeEditor(user);
          const [jira, backlog, googleCalendar, slack, googleDrive, gmail] = await Promise.all([
            getConnection(env, "jira"),
            getConnection(env, "backlog"),
            getConnection(env, "google_calendar"),
            getConnection(env, "slack"),
            googleOAuthStatus(env, "google_drive"),
            googleOAuthStatus(env, "gmail"),
          ]);
          return json(200, {
            status: "ok",
            jira: jira ? { connected: true, label: jira.extra.siteName ?? "Jira" } : { connected: false },
            backlog: backlog ? { connected: true, label: backlog.extra.spaceUrl ?? "Backlog" } : { connected: false },
            google_calendar: googleCalendar ? { connected: true, label: "Google" } : { connected: false },
            google_drive: googleDrive,
            gmail,
            // マップはOAuthではなくAPIキー（secret）方式。キーが設定済みかどうかだけを返す。
            google_maps: env.GOOGLE_MAPS_API_KEY ? { connected: true, label: "APIキー設定済み" } : { connected: false },
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
        case "/admin/kb/crawl-jobs":
          return await handleListCrawlJobs(req, env, user);
        case "/admin/kb/crawl-jobs/discard":
          return await handleDiscardCrawlJob(req, env, user);
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
        case "/tts":
          return await handleTts(req, env, user);
        // Houdiniチュートリアル生成への評価（migrations/0017）。送信は評価者本人、閲覧・集計はadminのみ。
        // 公式MCPサーバー連携（MCPクライアント、2026-10-08）。接続・ツール選択はadminのみ
        case "/admin/mcp/status":
          return await handleMcpStatus(req, env, user);
        case "/admin/mcp/disconnect":
          return await handleMcpDisconnect(req, env, user);
        case "/admin/mcp/tools":
          return await handleMcpTools(req, env, user);
        case "/admin/mcp/set-tools":
          return await handleMcpSetTools(req, env, user);
        case "/admin/mcp/set-chat":
          return await handleMcpSetChat(req, env, user);
        case "/admin/mcp/call":
          return await handleMcpCall(req, env, user);
        case "/me/mcp":
          return await handleMyMcp(req, env, user);
        case "/me/oauth-start-token":
          return await handleOAuthStartToken(req, env, user);
        case "/mcp/confirm":
          return await handleMcpConfirm(req, env, user);
        case "/mcp/cancel":
          return await handleMcpCancel(req, env, user);
        case "/tutorial-feedback/submit":
          return await handleTutorialFeedbackSubmit(req, env, user);
        case "/admin/tutorial-feedback/list":
          return await handleTutorialFeedbackList(req, env, user);
        case "/admin/tutorial-feedback/stats":
          return await handleTutorialFeedbackStats(req, env, user);
        case "/me/slack/link-code":
          return await handleSlackLinkCode(req, env, user);
        case "/me/slack/status":
          return await handleSlackStatus(req, env, user);
        case "/me/slack/unlink":
          return await handleSlackUnlink(req, env, user);
        case "/me/presets/list":
          return await handlePresetList(req, env, user);
        case "/me/presets/save":
          return await handlePresetSave(req, env, user);
        case "/me/presets/delete":
          return await handlePresetDelete(req, env, user);
        case "/me/connections":
          return await handleMyConnections(req, env, user);
        case "/me/namespaces":
          return await handleMyNamespaces(req, env, user);
        case "/admin/pilot/summary":
          return await handlePilotSummary(req, env, user);
        case "/me/growth":
          return await handleMyGrowth(req, env, user);
        case "/me/growth/reset":
          return await handleMyGrowthReset(req, env, user);
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
      // 中身の無くなったスレッド（質問がすべて保存期間を過ぎたもの）も消す
      await env.DB.prepare("DELETE FROM threads WHERE thread_id NOT IN (SELECT DISTINCT thread_id FROM memory WHERE thread_id IS NOT NULL)").run();
      const auditCutoff = Math.floor(Date.now() / 1000) - AUDIT_LOG_RETENTION_DAYS * 86400;
      await env.DB.prepare("DELETE FROM audit_log WHERE created_at < ?").bind(auditCutoff).run();
      await env.DB.prepare("DELETE FROM mcp_audit WHERE created_at < ?").bind(auditCutoff).run();
      await purgeExpiredApprovals(env); // 期限が切れた「書き込みの確認待ち」（5分で失効）
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
    // 30分ごとに、動かす時刻が来た定期の再クロール（と、途中のもの）を、時間の予算の範囲で進める
    if (event.cron === "*/30 * * * *") await runScheduledCrawls(env).catch(() => undefined);
  },
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
