-- 検索範囲のプリセット（2026-10-16追加）。チャットで検索対象のnamespaceを選ぶ組み合わせに名前を付けて保存し、
-- ワンタッチで切り替えられるようにする（ユーザーごと。端末をまたいで使える）。
CREATE TABLE scope_presets (
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    namespaces_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, name)
);
