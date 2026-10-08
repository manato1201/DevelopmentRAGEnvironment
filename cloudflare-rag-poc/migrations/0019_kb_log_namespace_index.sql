-- 登録済みナレッジ一覧（POST /admin/kb/list-documents）が、ドキュメントごとの種類（手動／Notion／
-- Drive／Jira…）と最終更新日時を kb_log から引くための索引（2026-10-08追加）。kb_log には
-- namespace の索引が無く、一覧を開くたびに全行を読んでいた（D1のRows read課金に効く）。
CREATE INDEX IF NOT EXISTS idx_kb_log_namespace_file ON kb_log(namespace_id, file);
