-- 会話のスレッド（2026-10-16追加）。質問と回答（memory）を会話ごとにまとめ、名前を付けたり、検索したり、
-- 続きから再開したりできるようにする。thread_idがNULLのmemoryは、スレッド導入前の履歴。
ALTER TABLE memory ADD COLUMN thread_id TEXT;
CREATE INDEX idx_memory_thread ON memory(thread_id);

CREATE TABLE threads (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX idx_threads_user ON threads(user_id, updated_at DESC);
