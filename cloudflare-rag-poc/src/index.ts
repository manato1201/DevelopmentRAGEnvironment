import type { Env } from "./types";
import { authenticate, ForbiddenError } from "./auth";
import { handleSearch } from "./search";
import { handleQuery } from "./query";
import { handleIngest } from "./ingest";
import { handleMemoryList, handleMemoryRate } from "./memory";
import { handleSyncNotion } from "./notionSync";
import { handleSyncDrive } from "./driveSync";
import { handleSetKbSource, handleKbHistory } from "./kbAdmin";
import {
  handleCreateKey,
  handleListKeys,
  handleDeleteKey,
  handleUpdateKeyNamespaces,
  handleSetKeyCapacity,
  handleChargeKey,
  handleBootstrapAdmin,
} from "./keyAdmin";
import { handleAddFaq } from "./faqAdd";
import { handleCreateNamespace, handleListNamespaces, handleDeleteNamespace, handleSetNamespaceLimit } from "./namespaceAdmin";
import { handleGraph } from "./graph";
import { handleUsageStats, handleRatingStats } from "./usageStats";
import { handleImportUrl } from "./urlImport";
import { handleImportQaCsv } from "./qaImport";
import { handleKbRollback } from "./kbRollback";
import { handleImportYoutube, handleUploadDoc } from "./mediaImport";
import { handleHealthCheck, handleTestAlert, checkHealthAndAlert } from "./healthCheck";
import { handleBackupExport } from "./backup";
import { handleClaudeMessages } from "./claude";
import { handleMyNamespaces } from "./retrieve";
import { RateLimitedError } from "./rateLimit";
import { chatUiHtml } from "./chatUi";
import { BudgetExceededError } from "./budget";

const MEMORY_RETENTION_DAYS = 90;
// 既存GASのpurgeExpiredTokenUsage_/purgeExpiredClaudeUsage_相当。GAS版はGoogle Sheetsの
// 行数上限を避けるための対策だったが、D1にはその制約は無いため、監査目的も踏まえて
// memoryより長めの180日にしている（2026-08-27追加。以前はaudit_logが無期限に蓄積していた）。
const AUDIT_LOG_RETENTION_DAYS = 180;

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
        case "/graph":
          return await handleGraph(req, env, user);
        case "/admin/sync/notion":
          return await handleSyncNotion(req, env, user);
        case "/admin/sync/drive":
          return await handleSyncDrive(req, env, user);
        case "/admin/kb/set-source":
          return await handleSetKbSource(req, env, user);
        case "/admin/kb/history":
          return await handleKbHistory(req, env, user);
        case "/admin/keys/create":
          return await handleCreateKey(req, env, user);
        case "/admin/keys/list":
          return await handleListKeys(req, env, user);
        case "/admin/keys/delete":
          return await handleDeleteKey(req, env, user);
        case "/admin/keys/update-namespaces":
          return await handleUpdateKeyNamespaces(req, env, user);
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
        case "/admin/usage/stats":
          return await handleUsageStats(req, env, user);
        case "/admin/rating-stats":
          return await handleRatingStats(req, env, user);
        case "/admin/kb/import-url":
          return await handleImportUrl(req, env, user);
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

  // Cron Trigger本体。wrangler.jsonc の triggers.crons に登録した2つのスケジュールを
  // event.cron の値で判別する：
  //   "0 3 * * *"  … 期限切れチャット履歴の自動削除（既存GAS purgeExpiredMemory_相当）
  //   "*/30 * * * *" … ヘルスチェック（既存GAS checkHealthAndAlert_相当）
  async scheduled(event: ScheduledController, env: Env): Promise<void> {
    if (event.cron === "0 3 * * *") {
      const memoryCutoff = Math.floor(Date.now() / 1000) - MEMORY_RETENTION_DAYS * 86400;
      await env.DB.prepare("DELETE FROM memory WHERE created_at < ?").bind(memoryCutoff).run();
      const auditCutoff = Math.floor(Date.now() / 1000) - AUDIT_LOG_RETENTION_DAYS * 86400;
      await env.DB.prepare("DELETE FROM audit_log WHERE created_at < ?").bind(auditCutoff).run();
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
