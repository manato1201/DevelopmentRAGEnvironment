-- D1の読み取り行数の削減（2026-10-16追加）。無料枠（1日500万行）を、chunks_ftsを全件走査する集計と、
-- 索引の無いkb_logの新しい順の取得が使い切り、全APIが500エラーになったため。
-- 1) kb_log の新しい順の取得（同期履歴）に索引を付ける。
CREATE INDEX IF NOT EXISTS idx_kb_log_created_at ON kb_log(created_at);
-- 2) 「namespaceごとの登録状況」の集計結果を一定時間キャッシュする（chunks_ftsは全件走査になるため）。
CREATE TABLE IF NOT EXISTS stats_cache (
    cache_key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    computed_at INTEGER NOT NULL
);
