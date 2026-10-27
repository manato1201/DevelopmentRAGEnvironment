-- 成長機能（2026-10-27）: 質問に使った専門用語の蓄積。質問の全文は保存せず、辞書（src/glossary.ts）の用語と回数だけ。
-- 利用者本人だけが、自分の分を見られる・消せる（/me/growth、/me/growth/reset）。管理者向けの集計は、人を特定しない形だけ。
CREATE TABLE user_terms (
    user_id TEXT NOT NULL,
    term TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    PRIMARY KEY (user_id, term)
);
CREATE INDEX idx_user_terms_user ON user_terms(user_id);
