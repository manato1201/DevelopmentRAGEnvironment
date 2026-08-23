-- docs/cloud-local-unification-plan.md §8.1 のD1スキーマ案をそのまま実装。
-- 本番のGoogle Sheets/ChromaDBには一切影響しない検証用スキーマ。

CREATE TABLE users (
    user_id TEXT PRIMARY KEY,       -- APIキーのSHA-256ハッシュ
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'member',  -- 'admin' | 'member' | 'guest'（既存pep.py準拠）
    created_at INTEGER NOT NULL
);

CREATE TABLE namespaces (
    namespace_id TEXT PRIMARY KEY,  -- 例: 'shared:tool_docs', 'personal:<user_id>'
    scope TEXT NOT NULL,            -- 'shared' | 'personal'
    owner_user_id TEXT,             -- scope='personal'の場合のみ設定
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
);

CREATE TABLE token_budgets (
    user_id TEXT NOT NULL,
    budget_type TEXT NOT NULL,      -- 'rag' | 'claude'
    limit_tokens INTEGER NOT NULL,
    used_tokens INTEGER NOT NULL DEFAULT 0,
    reset_at INTEGER,
    PRIMARY KEY (user_id, budget_type),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    namespace_id TEXT,
    query_hash TEXT NOT NULL,       -- SHA-256、既存RAGAuditLogger仕様を踏襲
    difficulty TEXT,                -- basic|applied|advanced（Phase1レベリング機能との連携）
    result_count INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    created_at INTEGER NOT NULL
);

-- 動作確認用の初期データ（本番投入前に削除すること）
INSERT INTO users (user_id, display_name, role, created_at) VALUES
    ('dev-test-user-hash', 'Dev Test User', 'admin', unixepoch());

INSERT INTO namespaces (namespace_id, scope, owner_user_id) VALUES
    ('shared:houdini21', 'shared', NULL),
    ('shared:tool_docs', 'shared', NULL),
    ('personal:dev-test-user-hash', 'personal', 'dev-test-user-hash');

INSERT INTO token_budgets (user_id, budget_type, limit_tokens, used_tokens) VALUES
    ('dev-test-user-hash', 'rag', 100000, 0);
