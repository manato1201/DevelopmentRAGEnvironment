-- チャット履歴（既存GASのsaveMemory_/getUserMemory/rateMemoryEntry相当）。
-- Webチャット画面の「過去の会話」表示と、回答の役立ち度評価に使う。
CREATE TABLE memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    query TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    namespaces TEXT,
    rating INTEGER,              -- NULL=未評価 / 1=役に立った / -1=役に立たなかった
    created_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX idx_memory_user_created ON memory(user_id, created_at DESC);
