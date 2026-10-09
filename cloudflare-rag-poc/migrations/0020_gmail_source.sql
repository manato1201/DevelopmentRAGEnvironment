-- Gmailのメールをナレッジ登録元にする（2026-10-09追加）。
-- namespaceごとに「どのメールを取り込むか」をGmailの検索式（例: label:project-x newer_than:30d）で指定する。
-- 検索式が空のnamespaceは同期の対象にならない（全メールを取り込む事故を避けるため、既定値は設けない）。
ALTER TABLE kb_sources ADD COLUMN gmail_query TEXT;
