-- 実証実験の「いま受け付けている回」（2026-11-11）。設計: docs/pilot/pilot-analysis-design.md §8
--   回 = 募集期間（第1回 = 11/16〜11/21、第2回 = 11/23〜11/28 など）。管理画面で、受け付ける回を切り替える。
--   key:
--     open_round … いま新しく参加できる回（0 = 受付を止めている。1〜2）。すでに参加している人は、自分の回を最後まで続けられる
--     label_1 / label_2 … 回の表示（「11/16〜11/21」など。参加者の画面と管理画面に出す）
CREATE TABLE pilot_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
INSERT INTO pilot_config (key, value, updated_at) VALUES ('open_round', '0', 0);
