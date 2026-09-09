-- 過去のQ&Aをお気に入り登録できるようにする（2026-09-04追加）。
-- 既存のrating（役立った/役立たなかった）と独立した軸：ratingは回答品質の評価、
-- pinnedは「あとで参照したい」という利用者側のマーキング。
-- 0=未登録（デフォルト）、1=お気に入り。
ALTER TABLE memory ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
CREATE INDEX idx_memory_user_pinned ON memory(user_id, pinned);
