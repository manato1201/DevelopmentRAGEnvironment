-- Slackから質問する（2026-10-16追加）。Slackのユーザーと、このシステムのユーザー（APIキー）の紐づけ。
-- 紐づけは、ウェブ画面で発行した短時間・1回限りの連携コードを、Slackの「/rag link <コード>」に入力して行う
-- （APIキーそのものをSlackに貼らない）。質問は、紐づいたユーザーの権限（アクセスできるnamespace・予算）で動く。
CREATE TABLE slack_bindings (
    team_id TEXT NOT NULL,
    slack_user_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (team_id, slack_user_id)
);
CREATE INDEX idx_slack_bindings_user ON slack_bindings(user_id);

CREATE TABLE slack_link_codes (
    code TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
