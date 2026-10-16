-- 取り込みの実行者の記録（2026-10-16追加）。kb_log（1ファイル=1行の結果）には誰が実行したかが残らなかったため、
-- 取り込み1回（op_id）ごとに「誰が・何を・どのnamespaceへ」を残す。user_idがNULLのものは自動実行（Cron）。
CREATE TABLE kb_ops (
    op_id TEXT PRIMARY KEY,
    user_id TEXT,
    kind TEXT NOT NULL,          -- 'manual' | 'notion' | 'drive' | 'jira' | 'backlog' | 'google_calendar' | 'gmail' | 'crawl' ...
    namespace_id TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX idx_kb_ops_created ON kb_ops(created_at);
