-- 連携の同期まわりの統制（2026-10-09追加）。
--  1) sync_allowed_namespaces: 連携（Jira / Backlog / カレンダー / Drive / Gmail / Notion）が書き込んでよい
--     共有namespaceの許可リスト。管理者だけが編集する。個人用namespace（personal:<user_id>）は対象外
--     （本人の接続で本人の索引にだけ書くため）。既に同期元を設定済みのnamespaceは、止まらないよう初期値として許可する。
--  2) kb_sources.auto_*: 毎日の自動同期を、namespaceごと・連携ごとに明示的にオンにしたものだけに限る（既定はオフ）。
--  3) oauth_connections / mcp_connections: 接続の持ち主（owner_id）を足す。'' = デプロイ全体で共有する接続（従来どおり）、
--     ユーザーID = そのユーザー専用の接続。主キーを (service, owner_id) / (provider_id, owner_id) にする。

CREATE TABLE sync_allowed_namespaces (
    namespace_id TEXT PRIMARY KEY,
    added_by TEXT,
    created_at INTEGER NOT NULL
);
INSERT OR IGNORE INTO sync_allowed_namespaces (namespace_id, added_by, created_at)
    SELECT namespace_id, NULL, CAST(strftime('%s', 'now') AS INTEGER) FROM kb_sources WHERE namespace_id NOT LIKE 'personal:%';

ALTER TABLE kb_sources ADD COLUMN auto_jira INTEGER NOT NULL DEFAULT 0;
ALTER TABLE kb_sources ADD COLUMN auto_backlog INTEGER NOT NULL DEFAULT 0;
ALTER TABLE kb_sources ADD COLUMN auto_calendar INTEGER NOT NULL DEFAULT 0;

CREATE TABLE oauth_connections_v2 (
    service TEXT NOT NULL,
    owner_id TEXT NOT NULL DEFAULT '',
    access_token TEXT,
    refresh_token TEXT,
    expires_at INTEGER,
    extra_json TEXT,
    connected_at INTEGER NOT NULL,
    connected_by TEXT,
    PRIMARY KEY (service, owner_id)
);
INSERT INTO oauth_connections_v2 (service, owner_id, access_token, refresh_token, expires_at, extra_json, connected_at, connected_by)
    SELECT service, '', access_token, refresh_token, expires_at, extra_json, connected_at, connected_by FROM oauth_connections;
DROP TABLE oauth_connections;
ALTER TABLE oauth_connections_v2 RENAME TO oauth_connections;

CREATE TABLE mcp_connections_v2 (
    provider_id TEXT NOT NULL,
    owner_id TEXT NOT NULL DEFAULT '',
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at INTEGER,
    resource_url TEXT NOT NULL,
    token_endpoint TEXT NOT NULL,
    client_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'connected',
    last_error TEXT NOT NULL DEFAULT '',
    enabled_tools_json TEXT,
    chat_enabled INTEGER NOT NULL DEFAULT 0,
    connected_at INTEGER NOT NULL,
    connected_by TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (provider_id, owner_id)
);
INSERT INTO mcp_connections_v2 (provider_id, owner_id, access_token, refresh_token, expires_at, resource_url, token_endpoint, client_json, status, last_error, enabled_tools_json, chat_enabled, connected_at, connected_by, updated_at)
    SELECT provider_id, '', access_token, refresh_token, expires_at, resource_url, token_endpoint, client_json, status, last_error, enabled_tools_json, chat_enabled, connected_at, connected_by, updated_at FROM mcp_connections;
DROP TABLE mcp_connections;
ALTER TABLE mcp_connections_v2 RENAME TO mcp_connections;
