-- Reference タブの説明（2026-11-19）。ノード・VEX・APEX・シェルフツールの「何をする・使いどころ・実例」を、開発側が作って、ここに置く。
-- 参加者の端末は、読むだけ（人ごとに内容が違う・AI の費用が際限なくかかる、を避ける）。画像・動画は R2（REFERENCE_MEDIA）に置き、media の id で参照する。
--   body    … 説明の JSON（what / use / example / example_point / when と、関連の参考資料 references）
--   media   … [{"id": "...", "type": "image|video", "role": "before|after|node|clip", "label": "..."}]（id は R2 のキー）
--   version … 内容を書き換えるたびに増える（端末のキャッシュを取り直す目印）
CREATE TABLE reference_entries (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    media TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE INDEX idx_reference_entries_updated ON reference_entries(updated_at);
