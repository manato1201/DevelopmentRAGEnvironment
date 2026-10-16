-- 取り込みのステージング（2026-10-16追加）。連携・クロールなどの取り込み先を「受け皿」namespaceにしておき、
-- 内容を確認してから本番のnamespaceへ移す（または破棄する）ための対応表。
-- 受け皿は連携の同期先の許可リストに入れ、本番側は許可リストに入れない（連携が本番へ直接書けないようにする）。
CREATE TABLE staging_targets (
    staging_namespace_id TEXT PRIMARY KEY,
    target_namespace_id TEXT NOT NULL,
    created_by TEXT,
    created_at INTEGER NOT NULL
);
