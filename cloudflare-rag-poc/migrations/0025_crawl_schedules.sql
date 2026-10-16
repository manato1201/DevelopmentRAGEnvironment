-- 定期の再クロール（2026-10-16追加）。サイトごとに「毎日/毎週」の再クロールを、明示的にオンにしたものだけ実行する。
-- 本文が変わっていないページは飛ばす（crawl_page_hashes）ので、再クロールは変わったページだけを処理する。
-- 大きなサイトは1回では終わらないため、続きは active_op_id（crawl_jobs）に残し、30分ごとのCronが少しずつ進める。
CREATE TABLE crawl_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id TEXT NOT NULL,
    url TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 1,
    max_pages INTEGER NOT NULL DEFAULT 30,
    path_prefix TEXT,
    exclude_patterns TEXT,
    frequency TEXT NOT NULL DEFAULT 'weekly',   -- 'daily' | 'weekly'
    enabled INTEGER NOT NULL DEFAULT 0,          -- 既定はオフ（明示的にオンにしたものだけ動く）
    created_by TEXT,
    created_at INTEGER NOT NULL,
    last_run_at INTEGER,                         -- 直近に完了した（または開始した）時刻
    active_op_id TEXT                            -- 途中のクロールジョブ（完了したらNULL）
);
CREATE INDEX idx_crawl_schedules_ns ON crawl_schedules(namespace_id);
