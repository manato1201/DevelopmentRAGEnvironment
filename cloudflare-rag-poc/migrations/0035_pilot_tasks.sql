-- 実証実験の課題の記録とアンケート（2026-10-28）。設計: docs/pilot-analysis-design.md
--   pilot_profile  … 参加者の事前アンケート。pid は匿名の参加者番号（登録順。集計では氏名を使わず P01 のように表す）。
--                    slot（1〜3）が、固定課題の順序（ラテン方格）と、「公式ドキュメントのみ」で行う回（対照）を決める。
--                    管理者（運営のテスト）は pid を持たず、集計に入らない。
--   pilot_sessions … 課題1回ぶんの記録（開始・終了・所要時間・質問回数・cookエラー・到達・自己申告・課題後アンケート）。
--                    1人につき、回（1〜3）× 種類（fixed=固定課題 / free=自由課題）で1行。
CREATE TABLE pilot_profile (
    user_id TEXT PRIMARY KEY,
    pid INTEGER,
    slot INTEGER NOT NULL,
    experience_years REAL,
    self_level TEXT,
    background TEXT,
    practice TEXT,
    tool_history TEXT,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX idx_pilot_profile_pid ON pilot_profile(pid);

CREATE TABLE pilot_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    kind TEXT NOT NULL,
    task_id TEXT NOT NULL,
    condition TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    duration_sec INTEGER,
    query_count INTEGER,
    cook_error_nodes INTEGER,
    reached INTEGER,
    self_mistakes INTEGER,
    difficulty INTEGER,
    clarity INTEGER,
    focus INTEGER,
    accuracy_worry INTEGER,
    source_useful INTEGER,
    reuse INTEGER,
    comment TEXT
);
CREATE UNIQUE INDEX idx_pilot_sessions_slot ON pilot_sessions(user_id, round, kind);
CREATE INDEX idx_pilot_sessions_user ON pilot_sessions(user_id);
