-- グラフビュー（graph.ts）専用の軽量ドキュメント一覧テーブル。
--
-- これまでgraph.tsは chunks_fts に対して
--   WHERE namespace IN (...) AND chunk_id LIKE '%:0'
-- という、先頭ワイルドカードLIKE（インデックス不使用）を UNINDEXED 列に対して行っており、
-- グラフタブを開くたびに全DB分の全チャンクをフルスキャンしていた。KB同期の書き込み量が
-- 増えたことと、グラフのノード上限を150→1000へ引き上げたこと（LIMITを満たすまでの
-- スキャン量が増える）が重なり、D1の日次Rows read上限（Freeプラン5,000,000行/日）の
-- 9割近くを消費する事態になった（2026-08-29、実機のCloudflareダッシュボードで確認）。
--
-- 1ドキュメントにつき1行（chunk_index=0のチャンクIDをそのまま主キーに使う）だけを持つ
-- 専用テーブルを用意し、namespaceにインデックスを張ることで、グラフを開くたびのコストを
-- 「全チャンク数」ではなく「ドキュメント数」に比例させる。以後はingestDocument()が
-- ドキュメントごとに1回だけ書き込む（chunks_fts本体への書き込み量は変わらない）。
CREATE TABLE kb_documents (
    chunk_id TEXT PRIMARY KEY,
    file TEXT NOT NULL,
    namespace TEXT NOT NULL,
    scope TEXT NOT NULL,
    owner_user_id TEXT
);
CREATE INDEX idx_kb_documents_namespace ON kb_documents (namespace);
CREATE INDEX idx_kb_documents_owner_user_id ON kb_documents (owner_user_id);

-- 既存データの一括バックフィル。このマイグレーション実行時に1回だけ chunks_fts の
-- フルスキャンが走るが、以後グラフを開くたびに走っていたスキャンはこれで最後になる。
INSERT INTO kb_documents (chunk_id, file, namespace, scope, owner_user_id)
SELECT chunk_id, file, namespace, scope, owner_user_id
FROM chunks_fts
WHERE chunk_id LIKE '%:0';
