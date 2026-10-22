import type { Env } from "./types";

// OAuthクリック接続化の共通ストレージ層（2026-09-22追加、migrations/0016参照）。
// 「wrangler secret put」というCLI手順を「管理画面で『接続する』ボタンを押す→
// ブラウザで認可する」という非技術者でも完結できる操作に置き換えるための土台。
// 各サービス固有のOAuthフロー（jiraOAuth.ts/backlogOAuth.ts/calendarOAuth.ts/
// slackOAuth.ts）はこのモジュールの関数だけを使ってトークンを読み書きする。

export type OAuthService = "jira" | "backlog" | "google_calendar" | "google_drive" | "gmail" | "slack" | "mcp" | "start";

export interface OAuthConnection {
  service: OAuthService;
  ownerId: string; // ''=デプロイ全体で共有する接続、ユーザーID=そのユーザー専用の接続（migrations/0021）
  accessToken: string | null;
  refreshToken: string | null;
  expiresAt: number | null; // unix秒。nullなら失効しない
  extra: Record<string, unknown>;
  connectedAt: number;
}

interface OAuthConnectionRow {
  service: OAuthService;
  owner_id: string;
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
    ownerId: row.owner_id ?? "",
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
  ownerId = "",
): Promise<OAuthConnection | null> {
  const row = await env.DB.prepare(
    "SELECT * FROM oauth_connections WHERE service = ? AND owner_id = ?",
  )
    .bind(service, ownerId)
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
    ownerId?: string; // 省略時は共有の接続
  },
): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  // refreshTokenを渡さない呼び出し（アクセストークンだけの更新、例: リフレッシュ後）では
  // 既存のrefresh_tokenを消さないようCOALESCEする。extraも同様（cloudId等は初回接続時
  // にしか分からない情報のため、後続のトークン更新で上書き消去しないようにする）。
  await env.DB.prepare(
    `INSERT INTO oauth_connections (service, owner_id, access_token, refresh_token, expires_at, extra_json, connected_at, connected_by)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(service, owner_id) DO UPDATE SET
       access_token = excluded.access_token,
       refresh_token = COALESCE(excluded.refresh_token, oauth_connections.refresh_token),
       expires_at = excluded.expires_at,
       extra_json = COALESCE(excluded.extra_json, oauth_connections.extra_json)`,
  )
    .bind(
      service,
      data.ownerId ?? "",
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
  ownerId = "",
): Promise<void> {
  await env.DB.prepare("DELETE FROM oauth_connections WHERE service = ? AND owner_id = ?")
    .bind(service, ownerId)
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
// 取り出しと削除は、1回のSQL（DELETE ... RETURNING）で行う（2026-10-22。以前は、読んでから消していたため、
// 同時に2回届くと、両方が通る余地があった）。ttlSec は、stateの有効期間（既定10分）。
export async function consumePendingState(
  env: Env,
  service: OAuthService,
  state: string,
  ttlSec = PENDING_STATE_TTL_SEC,
): Promise<Record<string, unknown> | null> {
  const now = Math.floor(Date.now() / 1000);
  const row = await env.DB.prepare(
    "DELETE FROM oauth_pending_state WHERE state = ? AND service = ? RETURNING extra_json, created_at",
  )
    .bind(state, service)
    .first<{ extra_json: string | null; created_at: number }>();
  if (!row) return null;
  if (row.created_at < now - ttlSec) return null; // 期限切れ
  try {
    return row.extra_json ? JSON.parse(row.extra_json) : {};
  } catch {
    return {};
  }
}

// 【2026-10-22】OAuth開始のURLに、APIキーそのものを載せないための、使い捨てトークン（60秒・1回だけ）。
// 開始URLは、ブラウザの履歴・アクセスログ・Refererに残るため、キーを載せると、そこから漏れる。
// 画面は、先に POST /me/oauth-start-token でこのトークンを受け取り、開始URLには ?t=<トークン> だけを付ける。
export const START_TOKEN_TTL_SEC = 60;
export async function createStartToken(env: Env, userId: string): Promise<string> {
  return createPendingState(env, "start", { user_id: userId });
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
  // 使い捨てトークン（?t=）。画面は、こちらを使う。
  const token = url.searchParams.get("t");
  if (token) {
    const pending = await consumePendingState(env, "start", token, START_TOKEN_TTL_SEC);
    if (!pending || typeof pending.user_id !== "string") return null;
    const { loadAuthedUser } = await import("./auth");
    return loadAuthedUser(env, pending.user_id);
  }
  // 以前の方式（?key=<APIキー>）。古い画面・手作りのURLのために残してある（キーが履歴に残るので、非推奨）。
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

// POST /me/oauth-start-token — 開始用の使い捨てトークンを発行する（認証済みの全ユーザー。ゲストを除く）。
export async function handleOAuthStartToken(_req: Request, env: Env, user: import("./types").AuthedUser): Promise<Response> {
  if (user.role === "guest") return new Response(JSON.stringify({ error: "ゲストは連携を使えません" }), { status: 403, headers: { "content-type": "application/json; charset=utf-8" } });
  const token = await createStartToken(env, user.userId);
  return new Response(JSON.stringify({ token, expiresInSeconds: START_TOKEN_TTL_SEC, status: "ok" }), {
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}
