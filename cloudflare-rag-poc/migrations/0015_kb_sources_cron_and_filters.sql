-- 「連携」タブへのフィードバック対応（2026-09-19）:
-- 1. Jira/Backlogの自動差分同期（Cron Trigger）用に、namespaceごとの最終同期時刻を持たせる。
--    未設定（NULL）の場合は「過去24時間分」を初回の差分範囲として扱う（jiraSync.ts/
--    backlogSync.ts参照）。全件の初回取り込みは引き続き管理タブの手動同期ボタンで行う想定
--    （Cronは差分キャッチアップ専用）。
-- 2. Jira/Backlogをプロジェクト全件ではなく絞り込んで登録したいという声（「ステータス=完了
--    のみ」等）に対応する、namespaceごとの追加フィルタ条件。
ALTER TABLE kb_sources ADD COLUMN jira_last_synced_at INTEGER;
ALTER TABLE kb_sources ADD COLUMN backlog_last_synced_at INTEGER;
ALTER TABLE kb_sources ADD COLUMN jira_extra_jql TEXT; -- 例: "status = Done"（project = "KEY" に AND で連結）
ALTER TABLE kb_sources ADD COLUMN backlog_keyword_filter TEXT; -- Backlog issues API の keyword パラメータにそのまま渡す
