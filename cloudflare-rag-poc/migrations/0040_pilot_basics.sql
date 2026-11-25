-- 実証実験: 基本操作の練習の記録（2026-11-26）。設計: docs/pilot/pilot-analysis-design.md §14
--   Guide タブの組み込みの「基本操作の練習」（AI を使わない 12 手順。houdini/python_panels/basics_guide.py）を、どこまで進めたか。
--   第3回（固定課題は全員 RBD）で、練習をしてから固定課題に入った人と、そうでない人（第2回の RBD を含む）を比べるため。
--     basics_step       … 進んだ手順の最大（戻っても減らさない）
--     basics_total      … 練習の手順の数（パネルが送る。練習の中身を変えたときに、分母が分かるように）
--     basics_started_at … 練習を最初に開いた時刻
--     basics_done_at    … 最後の手順まで進んだ最初の時刻。固定課題の開始（pilot_sessions.started_at）より前なら「練習してから課題に入った」
--   事前アンケートの前（参加者でない人）の練習は、記録しない。
ALTER TABLE pilot_profile ADD COLUMN basics_step INTEGER;
ALTER TABLE pilot_profile ADD COLUMN basics_total INTEGER;
ALTER TABLE pilot_profile ADD COLUMN basics_started_at INTEGER;
ALTER TABLE pilot_profile ADD COLUMN basics_done_at INTEGER;
