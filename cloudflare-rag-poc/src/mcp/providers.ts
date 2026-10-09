// 公式MCPサーバーの登録簿（固有層。2026-10-08追加）。別プロジェクトの
// server/app/mcp/providers/ にならい、サービスごとの違いは「宣言（データ）」だけで表す。
// 通信・認可・保存・確認の判定は共通層（protocol.ts / auth.ts / permissions.ts / service.ts）に
// 1つだけ置き、ここには書かない。
//
// セキュリティ: 接続先はこの登録簿にあるURLだけ（任意のURLは受け付けない＝SSRF防止）。
// 新しいサービスを足すときは、公式のリモートMCPサーバーのURLを1件足すだけでよい。
// 認可に必要な情報（OAuthの探索・クライアントの自動登録・PKCE）は共通層が行うので、
// 自動登録に対応したサーバーはOAuthアプリ登録もsecret設定も要らない。対応しないサーバー
// （GitHub・Slack・Google）だけ staticClient でsecretを使う。認証が要らない公開サーバーは auth: "none"。

import type { Env } from "../types";

export interface McpProvider {
  id: string; // URLの一部・保存キー・監査ログのタグ。英小文字のみ
  label: string; // 画面に出す名前
  description: string; // 画面の説明（一言）
  url: string; // 公式MCPエンドポイント（これ以外のホストへは接続しない）
  scopes: string[]; // 追加のOAuthスコープ。通常はサーバーのメタデータから取る
  // ツールの扱い。名前はサーバー自身のツール名。
  readOnlyTools: string[]; // サーバーのヒントが無くても、確認なしの読み取りとして扱う
  writeTools: string[]; // サーバーが読み取り専用と言っても、常に書き込みとして扱う
  blockedTools: string[]; // モデルに一切見せない
  toolHints: Record<string, string>; // ツールの説明の末尾に足す補足
  // 認証方式。既定は "oauth"（探索→自動登録→PKCE）。"none" は認証が要らない公開サーバー
  // （接続＝有効化するだけ。トークンは持たない）。
  auth?: "oauth" | "none";
  // 自動登録（RFC 7591）に対応しないサーバー向け。事前に作ったOAuthアプリのClient ID/Secretを
  // secretから読む（候補は先頭から順に探す）。無い間は「準備が必要」と表示して接続させない。
  staticClient?: { idEnv: string[]; secretEnv: string[]; setupHint: string };
  // 認可URLに足す固定のパラメータ（例: Googleのリフレッシュトークン用 access_type=offline）
  authParams?: Record<string, string>;
  // RFC 8707 の resource を送るか。対応しないサーバー（Google・GitHub・Slack）では false にする。
  sendResource?: boolean;
}

const GOOGLE_STATIC = {
  idEnv: ["GMAIL_OAUTH_CLIENT_ID"],
  secretEnv: ["GMAIL_OAUTH_CLIENT_SECRET"],
  setupHint:
    "Google Cloudで当該MCP APIを有効にし（Google Workspace Developer Previewへの参加が必要）、" +
    "OAuthクライアントの承認済みリダイレクトURIに https://<このWorkerのドメイン>/admin/oauth/mcp/callback を追加してください。",
};
const GOOGLE_PARAMS = { access_type: "offline", prompt: "consent" };
const NO_TOOLS = { readOnlyTools: [], writeTools: [], blockedTools: [], toolHints: {} };

export const MCP_PROVIDERS: Record<string, McpProvider> = {
  notion: {
    id: "notion",
    label: "Notion",
    description: "ページ・データベースの検索と閲覧（公式MCP）",
    url: "https://mcp.notion.com/mcp",
    scopes: [],
    readOnlyTools: [],
    writeTools: [],
    blockedTools: [],
    toolHints: {},
  },
  atlassian: {
    id: "atlassian",
    label: "Atlassian（Jira / Confluence）",
    description: "Jiraの課題・Confluenceのページの検索と閲覧（公式MCP）",
    url: "https://mcp.atlassian.com/v1/mcp",
    scopes: [],
    readOnlyTools: [],
    writeTools: [],
    blockedTools: [],
    toolHints: {},
  },
  // ---- 自動登録に対応するサーバー（secret不要）----
  linear: {
    id: "linear",
    label: "Linear",
    description: "課題・プロジェクト・ドキュメントの検索と閲覧（公式MCP）",
    url: "https://mcp.linear.app/mcp",
    scopes: ["read"],
    ...NO_TOOLS,
  },
  sentry: {
    id: "sentry",
    label: "Sentry",
    description: "エラー・課題・リリースの検索と閲覧（公式MCP）",
    url: "https://mcp.sentry.dev/mcp",
    scopes: [],
    ...NO_TOOLS,
  },
  figma: {
    id: "figma",
    label: "Figma",
    description: "デザインファイルの内容の閲覧（公式MCP）",
    url: "https://mcp.figma.com/mcp",
    scopes: [],
    ...NO_TOOLS,
  },
  // ---- 認証が要らない公開サーバー ----
  mslearn: {
    id: "mslearn",
    label: "Microsoft Learn",
    description: "Microsoftの公式ドキュメント（.NET・C#・Azureなど）の検索（公式MCP、認証なし）",
    url: "https://learn.microsoft.com/api/mcp",
    scopes: [],
    auth: "none",
    ...NO_TOOLS,
  },
  cfdocs: {
    id: "cfdocs",
    label: "Cloudflare Docs",
    description: "Cloudflare（Workers・D1・Vectorizeなど）の公式ドキュメントの検索（公式MCP、認証なし）",
    url: "https://docs.mcp.cloudflare.com/mcp",
    scopes: [],
    auth: "none",
    ...NO_TOOLS,
  },
  // ---- 自動登録に対応しないサーバー（事前にOAuthアプリを作り、secretを設定する）----
  github: {
    id: "github",
    label: "GitHub",
    description: "リポジトリ・課題・プルリクエストの検索と閲覧（公式MCP）",
    url: "https://api.githubcopilot.com/mcp/",
    scopes: ["repo", "read:org", "read:user"],
    ...NO_TOOLS,
    staticClient: {
      idEnv: ["MCP_GITHUB_CLIENT_ID"],
      secretEnv: ["MCP_GITHUB_CLIENT_SECRET"],
      setupHint:
        "GitHubの Settings → Developer settings → OAuth Apps でアプリを作り、Authorization callback URL に " +
        "https://<このWorkerのドメイン>/admin/oauth/mcp/callback を設定して、Client IDとSecretを " +
        "MCP_GITHUB_CLIENT_ID / MCP_GITHUB_CLIENT_SECRET としてWorkerのsecretに登録してください。",
    },
    sendResource: false,
  },
  slack: {
    id: "slack",
    label: "Slack",
    description: "メッセージ・チャンネル・キャンバスの検索と閲覧（公式MCP）",
    url: "https://mcp.slack.com/mcp",
    scopes: [
      "search:read.public", "search:read.private", "channels:history", "channels:read",
      "groups:history", "groups:read", "users:read", "canvases:read",
    ],
    ...NO_TOOLS,
    staticClient: {
      idEnv: ["MCP_SLACK_CLIENT_ID", "SLACK_OAUTH_CLIENT_ID"],
      secretEnv: ["MCP_SLACK_CLIENT_SECRET", "SLACK_OAUTH_CLIENT_SECRET"],
      setupHint:
        "SlackのAPI管理画面（api.slack.com/apps）で、自分のワークスペースのアプリを作り（または通知用の既存アプリを使い）、" +
        "「Agents & AI Apps」でMCPを有効にし、Redirect URLs に https://<このWorkerのドメイン>/admin/oauth/mcp/callback を追加して、" +
        "Client IDとSecretを MCP_SLACK_CLIENT_ID / MCP_SLACK_CLIENT_SECRET としてWorkerのsecretに登録してください（通知用アプリと同じ値なら設定済みです）。",
    },
    sendResource: false,
  },
  gmail: {
    id: "gmail",
    label: "Gmail（公式MCP）",
    description: "メールの検索と閲覧（Google公式MCP・Developer Preview）",
    url: "https://gmailmcp.googleapis.com/mcp/v1",
    scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    ...NO_TOOLS,
    staticClient: GOOGLE_STATIC,
    authParams: GOOGLE_PARAMS,
    sendResource: false,
  },
  gdrive: {
    id: "gdrive",
    label: "Google Drive（公式MCP）",
    description: "ファイルの検索と閲覧（Google公式MCP・Developer Preview）",
    url: "https://drivemcp.googleapis.com/mcp/v1",
    scopes: ["https://www.googleapis.com/auth/drive.readonly"],
    ...NO_TOOLS,
    staticClient: GOOGLE_STATIC,
    authParams: GOOGLE_PARAMS,
    sendResource: false,
  },
  gcalendar: {
    id: "gcalendar",
    label: "Google カレンダー（公式MCP）",
    description: "予定の検索と空き時間の確認（Google公式MCP・Developer Preview）",
    url: "https://calendarmcp.googleapis.com/mcp/v1",
    scopes: [
      "https://www.googleapis.com/auth/calendar.events.readonly",
      "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    ],
    ...NO_TOOLS,
    staticClient: GOOGLE_STATIC,
    authParams: GOOGLE_PARAMS,
    sendResource: false,
  },
};

// 自動登録に対応しない公式サーバー（GitHub・Slack・Google）用の、事前登録済みOAuthアプリのsecretを返す。
export function staticClientFor(env: Env, provider: McpProvider): { client_id: string; client_secret?: string } | null {
  const spec = provider.staticClient;
  if (!spec) return null;
  const vars = env as unknown as Record<string, string | undefined>;
  const id = spec.idEnv.map((k) => vars[k]).find(Boolean);
  if (!id) return null;
  const secret = spec.secretEnv.map((k) => vars[k]).find(Boolean);
  return secret ? { client_id: id, client_secret: secret } : { client_id: id };
}

// 接続の前に管理者が準備する必要があるか（secret未設定）と、その手順。
export function setupFor(env: Env, provider: McpProvider): { needed: boolean; hint: string } {
  if (provider.staticClient && !staticClientFor(env, provider)) return { needed: true, hint: provider.staticClient.setupHint };
  return { needed: false, hint: "" };
}

export function providerIds(): string[] {
  return Object.keys(MCP_PROVIDERS);
}

export function getProvider(id: string): McpProvider {
  const provider = MCP_PROVIDERS[id];
  if (!provider) throw new McpConfigError(`未対応のMCPサーバーです: ${id}`);
  return provider;
}

// ── エラー（共通層で使う） ─────────────────────────────────────────────────────

export class McpError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "McpError";
  }
}

// サーバーが認証を拒否した（トークン失効・取り消し）。接続を「要再認証」にする合図。
export class McpAuthError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = "McpAuthError";
  }
}

export class McpConfigError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = "McpConfigError";
  }
}

export class McpNotConnectedError extends McpError {
  constructor(message = "このMCPサーバーは未接続です。管理画面の「連携」から接続してください") {
    super(message);
    this.name = "McpNotConnectedError";
  }
}

export class McpToolNotAllowed extends McpError {
  constructor(message: string) {
    super(message);
    this.name = "McpToolNotAllowed";
  }
}
