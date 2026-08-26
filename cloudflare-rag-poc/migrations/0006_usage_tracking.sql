-- 日次のトークン使用量グラフ表示のため、監査ログにトークン消費量を追加する。
-- 既存行はNULLではなく0扱いにしておく（DEFAULT 0）。
ALTER TABLE audit_log ADD COLUMN tokens_used INTEGER NOT NULL DEFAULT 0;

CREATE INDEX idx_audit_log_created_at ON audit_log(created_at);
