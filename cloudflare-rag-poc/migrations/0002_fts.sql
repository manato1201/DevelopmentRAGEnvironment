-- キーワード検索（BM25）用のFTS5仮想テーブル。Vectorizeのベクトル検索結果とRRFで統合する
-- （既存GAS実装の bm25Search_ + rrfMerge_ に相当）。
--
-- 日本語は単語間にスペースが無いため、標準のunicode61トークナイザでは実質検索できない
-- （GAS側はSudachiPyで形態素解析しているが、Workersランタイムでは利用不可）。
-- 代わりにtrigramトークナイザ（3文字の部分文字列でインデックス）を使い、
-- 形態素解析なしでも日本語の部分一致検索ができるようにする。
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id UNINDEXED,
    file UNINDEXED,
    namespace UNINDEXED,
    scope UNINDEXED,
    owner_user_id UNINDEXED,
    difficulty UNINDEXED,
    body,
    tokenize = 'trigram'
);
