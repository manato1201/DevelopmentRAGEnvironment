import type { Env } from "./types";

// OAuthクリック接続化の共通ストレージ層（2026-09-22追加、migrations/0016参照）。
// 「wrangler secret put」というCLI手順を「管理画面で『接続する』ボタンを押す→
// ブラウザで認可する」という非技術者でも完結できる操作に置き換えるための土台。
// 各サービス固有のOAuthフロー（jiraOAuth.ts/backlogOAuth.ts/calendarOAuth.ts/
// slackOAuth.ts）はこのモジュールの関数だけを使ってトークンを読み書きする。

export type OAuthService = "jira" | "backlog" | "google_calendar" | "slack" | "mcp";

export interface OAuthConnection {
  service: OAuthService;
  accessToken: string | null;
  refreshToken: string | null;
  expiresAt: number | null; // unix秒。nullなら失効しない
  extra: Record<string, unknown>;
  connectedAt: number;
}

interface OAuthConnectionRow {
  service: OAuthService;
  access_token: string | null;
  refresh_token: string | null;
  expires_at: number | null;
  extra_json: string | null;
  connected_at: number;
}

function rowToConnection(row: OAuthConnectionRow): OAuthConnection {
  let extra: Record<string, unknown> = {};
  if (row.extra_json) {
    try {
      extra = JSON.parse(row.extra_json);
    } catch {
      extra = {};
    }
  }
  return {
    service: row.service,
    accessToken: row.access_token,
    refreshToken: row.refresh_token,
    expiresAt: row.expires_at,
    extra,
    connectedAt: row.connected_at,
  };
}

export async function getConnection(
  env: Env,
  service: OAuthService,
): Promise<OAuthConnection | null> {
  const row = await env.DB.prepare(
    "SELECT * FROM oauth_connections WHERE service = ?",
  )
    .bind(service)
    .first<OAuthConnectionRow>();
  return row ? rowToConnection(row) : null;
}

export async function saveConnection(
  env: Env,
  service: OAuthService,
  data: {
    accessToken: string | null;
    refreshToken?: string | null;
    expiresAt?: number | null;
    extra?: Record<string, unknown>;
    connectedBy?: string;
  },
): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  // refreshTokenを渡さない呼び出し（アクセストークンだけの更新、例: リフレッシュ後）では
  // 既存のrefresh_tokenを消さないようCOALESCEする。extraも同様（cloudId等は初回接続時
  // にしか分からない情報のため、後続のトークン更新で上書き消去しないようにする）。
  await env.DB.prepare(
    `INSERT INTO oauth_connections (service, access_token, refresh_token, expires_at, extra_json, connected_at, connected_by)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(service) DO UPDATE SET
       access_token = excluded.access_token,
       refresh_token = COALESCE(excluded.refresh_token, oauth_connections.refresh_token),
       expires_at = excluded.expires_at,
       extra_json = COALESCE(excluded.extra_json, oauth_connections.extra_json)`,
  )
    .bind(
      service,
      data.accessToken,
      data.refreshToken ?? null,
      data.expiresAt ?? null,
      data.extra ? JSON.stringify(data.extra) : null,
      now,
      data.connectedBy ?? null,
    )
    .run();
}

export async function clearConnection(
  env: Env,
  service: OAuthService,
): Promise<void> {
  await env.DB.prepare("DELETE FROM oauth_connections WHERE service = ?")
    .bind(service)
    .run();
}

// state（CSRFトークン兼「正当な開始リクエストか」の検証）はランダムなUUIDを使う。
// 有効期限は短く（10分）、コールバック処理のたびに期限切れ分をまとめて掃除する
// （専用のcronは設けない。頻度が低い操作のため十分）。
const PENDING_STATE_TTL_SEC = 600;

export async function createPendingState(
  env: Env,
  service: OAuthService,
  extra: Record<string, unknown> = {},
): Promise<string> {
  const state = crypto.randomUUID();
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare("DELETE FROM oauth_pending_state WHERE created_at < ?")
    .bind(now - PENDING_STATE_TTL_SEC)
    .run();
  await env.DB.prepare(
    "INSERT INTO oauth_pending_state (state, service, created_at, extra_json) VALUES (?, ?, ?, ?)",
  )
    .bind(state, service, now, JSON.stringify(extra))
    .run();
  return state;
}

// 呼び出しと同時にstateを消費（削除）する。同じstateでの再利用（リプレイ）を防ぐため。
export async function consumePendingState(
  env: Env,
  service: OAuthService,
  state: string,
): Promise<Record<string, unknown> | null> {
  const now = Math.floor(Date.now() / 1000);
  const row = await env.DB.prepare(
    "SELECT extra_json, created_at FROM oauth_pending_state WHERE state = ? AND service = ?",
  )
    .bind(state, service)
    .first<{ extra_json: string | null; created_at: number }>();
  if (!row) return null;
  await env.DB.prepare("DELETE FROM oauth_pending_state WHERE state = ?")
    .bind(state)
    .run();
  if (row.created_at < now - PENDING_STATE_TTL_SEC) return null; // 期限切れ
  try {
    return row.extra_json ? JSON.parse(row.extra_json) : {};
  } catch {
    return {};
  }
}

// OAuth開始エンドポイント（ブラウザの直接ナビゲーションで叩かれるためAuthorizationヘッダーを
// 付けられない）専用の認証。管理画面のJS（chatUi.ts）が、既にlocalStorageに持っている
// APIキーをクエリパラメータとして一度だけ渡す。通常のAPI呼び出し（fetch経由）は今まで通り
// Authorizationヘッダーを使うため、この関数はOAuth開始の入口だけに限定して使う
// （2026-09-22追加。ブラウザ履歴・サーバーログにAPIキーが短時間残るトレードオフは、
// 管理者専用の内部ツールという性質上許容している。詳細はjiraOAuth.ts等のコメント参照）。
// 各サービスのOAuthアプリ登録時に「リダイレクトURL」として登録してもらう値。
// デプロイ先のドメイン（workers.dev既定 or カスタムドメイン）をハードコードせず、
// 実際に受けたリクエストのoriginから組み立てる（2026-09-22追加）。
export function oauthRedirectUri(req: Request, service: OAuthService): string {
  return `${new URL(req.url).origin}/admin/oauth/${service}/callback`;
}

export async function authenticateFromQueryKey(req: Request, env: Env) {
  const url = new URL(req.url);
  const key = url.searchParams.get("key");
  if (!key) return null;
  // authenticate()と同じ検証ロジックを再利用するため、一時的にAuthorizationヘッダーを
  // 持つRequestを作り直す（Requestのheadersは読み取り専用のため）。
  const cloned = new Request(req.url, {
    headers: { authorization: `Bearer ${key}` },
  });
  const { authenticate } = await import("./auth");
  return authenticate(cloned, env);
}
