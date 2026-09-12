-- namespace単位のトークン予算（監視用途、2026-09-12追加）。監査ログのnamespace_idは
-- 1クエリが複数namespaceを横断検索した場合カンマ区切りで複数入るため、正確な予算
-- "強制" はできない（1クエリのトークンを関与した全namespaceに計上する近似値になる）。
-- そのためこれは強制ブロックではなく、超過検知・可視化・アラート用のしきい値として扱う。
ALTER TABLE namespaces ADD COLUMN token_budget INTEGER;

-- APIキーの有効期限（2026-09-12追加）。NULLは無期限。authenticate()が期限切れキーを
-- 「存在しないキー」と同じ扱いで拒否する。失効間近のキーは日次cronでSlack/Gmailに通知する。
ALTER TABLE users ADD COLUMN expires_at INTEGER;
