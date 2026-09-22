-- ナレッジ登録の同期元にJira/Backlog/Googleカレンダーを追加する（2026-09-17、
-- 管理タブの「連携」サブタブ追加に伴う。Notion/Driveと同じくnamespaceごとに1つの
-- プロジェクト/カレンダーを紐付ける想定で、既存のnotion_database_id/drive_folder_idと
-- 同じ形（namespace単位の識別子カラムを1つ追加するだけ）に揃える）。
-- API認証情報（Jiraのメール+APIトークン、Backlogのスペース+APIキー）自体はnamespace単位
-- ではなくデプロイ単位の秘密情報のためsecrets（wrangler secret）で管理し、ここには含めない。
ALTER TABLE kb_sources ADD COLUMN jira_project_key TEXT;
ALTER TABLE kb_sources ADD COLUMN backlog_project_id TEXT;
ALTER TABLE kb_sources ADD COLUMN calendar_id TEXT;
