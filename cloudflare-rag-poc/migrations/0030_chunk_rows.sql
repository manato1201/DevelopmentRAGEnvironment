-- chunks_fts（FTS5）の行を、chunk_id・namespace・fileから速く引くための対応表（2026-10-16追加）。
-- chunks_ftsはchunk_id/namespace/fileがUNINDEXED列のため、これらでの検索・削除（WHERE chunk_id = ? など）は
-- 毎回全チャンクの走査になり、D1の無料枠（1日500万行の読み取り）を使い切って全APIが止まった。
-- FTS5はrowidでの参照だけは速いので、「chunk_id → rowid」を持ち、削除・参照はrowid経由にする。
-- 書き込み側はsrc/chunkRows.tsに集約している（chunks_ftsへ挿入した直後のrowidをここへ記録する）。
CREATE TABLE IF NOT EXISTS chunk_rows (
    chunk_id TEXT PRIMARY KEY,
    fts_rowid INTEGER NOT NULL,
    namespace TEXT NOT NULL,
    file TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunk_rows_ns_file ON chunk_rows(namespace, file);

-- 既存データのバックフィル（このマイグレーションの1回だけ、chunks_ftsを全件読む）。
INSERT OR REPLACE INTO chunk_rows (chunk_id, fts_rowid, namespace, file)
SELECT chunk_id, rowid, namespace, file FROM chunks_fts;
