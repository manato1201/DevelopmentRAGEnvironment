-- OAuthクリック接続化（2026-09-22追加）。「wrangler secret putでAPIトークンを発行・登録」
-- という手順をブラウザでの「接続する」ボタン一つに置き換えるための、取得済みトークンの
-- 保存先。デプロイ単位で1接続（Jira/Backlog/Googleカレンダー/Slackそれぞれ1つ）とし、
-- namespace単位ではない（既存のJIRA_API_TOKEN等のsecretと同じスコープ）。
--
-- 各OAuthアプリ自体のClient ID/Secret（サービス提供元への一度きりの登録で得るもの）は
-- 引き続きsecretとして管理する。ここに保存するのは、そのOAuthアプリを使って実際に
-- 「接続する」ボタンを押した結果得られるアクセストークン/リフレッシュトークン側。
CREATE TABLE oauth_connections (
    service TEXT PRIMARY KEY,   -- 'jira' | 'backlog' | 'google_calendar' | 'slack'
    access_token TEXT,
    refresh_token TEXT,
    expires_at INTEGER,         -- アクセストークンの失効時刻（unix秒）。NULLなら失効しない（例: Slack webhook URL）
    extra_json TEXT,            -- サービス固有の付随情報（JiraのcloudId、Backlogのスペースドメイン、Slackのチーム名等）
    connected_at INTEGER NOT NULL,
    connected_by TEXT           -- 接続したuser_id（監査用、任意）
);

-- OAuth認可フロー中のCSRF対策＋「誰がこの接続フローを開始したか」の一時的な紐付け。
-- コールバック（外部サービスからのリダイレクト、Authorizationヘッダーを持たない）が
-- 正当な開始リクエストに対応することを検証するために使う。有効期限が短い一時データ
-- のため、期限切れ分はコールバック処理のたびにまとめて掃除する（cronは設けない）。
CREATE TABLE oauth_pending_state (
    state TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    extra_json TEXT             -- 開始時点で入力済みの値（例: Backlogのスペースドメイン）
);
