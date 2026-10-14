-- 再クロールを速くする（2026-10-14追加）。ページごとに「前回登録したときの本文のハッシュ」を覚えておき、
-- 再クロールで本文が変わっていないページは、埋め込み・登録をせずに「変更なし」として飛ばす。
-- （従来は同じページを毎回すべて埋め込み直していたため、200ページ規模の再クロールが長くなり、
--  途中で通信が切れると最初からやり直しになっていた）
CREATE TABLE crawl_page_hashes (
    namespace_id TEXT NOT NULL,
    url TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,  -- 前回登録したチャンク数（短くなったページの古い末尾を消すため）
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (namespace_id, url)
);
