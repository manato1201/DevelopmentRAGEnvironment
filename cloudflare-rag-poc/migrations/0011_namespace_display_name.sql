-- 個人namespace（personal:<APIキーのSHA-256ハッシュ>）はIDだけでは「誰の」namespaceか
-- 管理画面から判別できなかった（2026-09-10フィードバック）。発行時に付けた表示名を
-- 持たせられるようにし、namespace管理テーブルではIDの代わりにこちらを主表示にする。
-- shared namespaceは今のところ対象外（NULLのまま=従来通りnamespace_idを表示）。
ALTER TABLE namespaces ADD COLUMN display_name TEXT;
