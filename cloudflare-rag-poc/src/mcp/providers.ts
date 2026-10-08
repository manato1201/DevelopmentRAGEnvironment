// 公式MCPサーバーの登録簿（固有層。2026-10-08追加）。別プロジェクトの
// server/app/mcp/providers/ にならい、サービスごとの違いは「宣言（データ）」だけで表す。
// 通信・認可・保存・確認の判定は共通層（protocol.ts / auth.ts / permissions.ts / service.ts）に
// 1つだけ置き、ここには書かない。
//
// セキュリティ: 接続先はこの登録簿にあるURLだけ（任意のURLは受け付けない＝SSRF防止）。
// 新しいサービスを足すときは、公式のリモートMCPサーバーのURLを1件足すだけでよい。
// 認可に必要な情報（OAuthの探索・クライアントの自動登録・PKCE）は共通層が行うので、
// 各サービス側のOAuthアプリ登録やsecret設定は要らない（自動登録に対応したサーバーの場合）。

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
}

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
};

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
