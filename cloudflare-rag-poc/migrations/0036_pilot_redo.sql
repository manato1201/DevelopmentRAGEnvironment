-- 実証実験の課題: やり直し（2026-10-28）。設計: docs/pilot-analysis-design.md
--   discarded_at … 参加者が「やり直す」で破棄した記録。消さずに残す（やり直しの回数を、分析で見られるように）。集計・次の課題の判定には入れない。
--   paused_sec   … Houdini が閉じていた（落ちた・再起動した）あいだの秒数。所要時間から引く。
-- 同じ（人・回・種類）の記録は、破棄していないものが1つだけ。
ALTER TABLE pilot_sessions ADD COLUMN discarded_at INTEGER;
ALTER TABLE pilot_sessions ADD COLUMN paused_sec INTEGER NOT NULL DEFAULT 0;
DROP INDEX idx_pilot_sessions_slot;
CREATE UNIQUE INDEX idx_pilot_sessions_slot ON pilot_sessions(user_id, round, kind) WHERE discarded_at IS NULL;
