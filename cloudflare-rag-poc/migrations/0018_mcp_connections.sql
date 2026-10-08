-- 公式MCPサーバー連携（MCPクライアント、2026-10-08追加）。AXChat:D（AxChatD）のMCP連携
-- （RAGEnvironment/server/app/mcp/）を参考に、このWorkerをMCPクライアントにして、
-- Notion・Atlassianなどの公式リモートMCPサーバーへつなぐ。
--
-- 接続はデプロイ単位で1サービス1接続（oauth_connectionsと同じスコープ。namespace単位ではない）。
-- 接続・解除・ツール選択・「チャットで使う」の切り替えは管理者のみ。トークンは既存の
-- oauth_connectionsと同じく平文でD1に保存する（PoC水準。本番化の前に暗号化が必要）。

CREATE TABLE mcp_connections (
    provider_id TEXT PRIMARY KEY,            -- src/mcp/providers.ts のid（'notion' / 'atlassian' ...）
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at INTEGER,                      -- アクセストークンの失効時刻（unix秒）。NULLなら失効しない
    resource_url TEXT NOT NULL,              -- 接続先MCPサーバーのURL（トークンの更新時にresourceとして送る）
    token_endpoint TEXT NOT NULL,
    client_json TEXT NOT NULL,               -- 自動登録したOAuthクライアント {client_id, client_secret?}
    status TEXT NOT NULL DEFAULT 'connected',-- 'connected' | 'reauth_required'（サーバーが認証を拒否した）
    last_error TEXT NOT NULL DEFAULT '',
    enabled_tools_json TEXT,                 -- 使うツール名の配列。NULL=ポリシーが許す全ツール
    chat_enabled INTEGER NOT NULL DEFAULT 0, -- 1=RAGチャットからこのサービスのツールを使ってよい（既定はオフ）
    connected_at INTEGER NOT NULL,
    connected_by TEXT,
    updated_at INTEGER NOT NULL
);

-- OAuthクライアントの動的登録（RFC 7591）の結果のキャッシュ。ボタンを押すたびに登録すると、
-- 認可サーバー側にクライアントが増え続けるため、認可サーバー×リダイレクトURIごとに1つだけ作る。
CREATE TABLE mcp_clients (
    cache_key TEXT PRIMARY KEY,              -- '<issuer>|<redirect_uri>'
    client_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

-- MCPツールの実行・接続操作の監査ログ。引数の中身は保存しない（個人情報・機密を含みうるため）。
CREATE TABLE mcp_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    user_id TEXT,
    action TEXT NOT NULL,                    -- 'connect' | 'disconnect' | 'reauth_required' | ツール名
    status TEXT NOT NULL DEFAULT 'ok',       -- 'ok' | 'error'
    detail TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);

CREATE INDEX idx_mcp_audit_created ON mcp_audit(created_at);
