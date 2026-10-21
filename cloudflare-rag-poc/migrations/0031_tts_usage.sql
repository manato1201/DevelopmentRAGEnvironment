-- 音声合成プロキシ（POST /tts、src/tts.ts）の1日あたりの文字数。2026-10-20追加。
-- Google Cloud Text-to-Speech は文字数で課金されるため、鍵（user_id）ごとと全体（user_id = '*'）の
-- 両方に1日の上限をかけ、費用が膨らまないようにする。day は日本時間の日付（YYYY-MM-DD）。
CREATE TABLE IF NOT EXISTS tts_usage (
    user_id TEXT NOT NULL,
    day TEXT NOT NULL,
    chars INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
