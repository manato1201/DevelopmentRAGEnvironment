-- Houdiniチュートリアル生成への評価（good/bad・理由タグ・メモ）と、生成時の自動品質指標
-- （2026-10-05追加）。クライアント（houdini/python_panels/tutorial_feedback.py）が評価を
-- 付けたときに送ってくる。閲覧・集計は管理者（admin）だけ。
--
-- 1ユーザー×1チュートリアルで1行（評価を付け直すと上書き）。tutorial_keyはクライアント側の
-- ファイル名（拡張子なし）で、ユーザーが同じチュートリアルを評価し直したときの重複を防ぐ。
-- チュートリアル本文は保存しない（題名・トピック・概要の抜粋・指標のみ）。
CREATE TABLE tutorial_feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    tutorial_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    level TEXT,
    model TEXT,
    rag_name TEXT,
    houdini_version TEXT,
    rating INTEGER NOT NULL,                 -- 1 = good, -1 = bad
    tags_json TEXT NOT NULL DEFAULT '[]',    -- 理由タグ（文字列の配列）
    note TEXT NOT NULL DEFAULT '',           -- 一言メモ
    overview TEXT NOT NULL DEFAULT '',       -- チュートリアル概要の抜粋
    metrics_json TEXT NOT NULL DEFAULT '{}', -- 反復回数・cookエラー数・コスト等の自動指標
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (user_id, tutorial_key)
);

CREATE INDEX idx_tutorial_feedback_updated ON tutorial_feedback(updated_at);
CREATE INDEX idx_tutorial_feedback_rating ON tutorial_feedback(rating);
