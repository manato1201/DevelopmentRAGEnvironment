-- namespace（DB）ごとに検索結果の採用件数上限を設定できるようにする。
-- NULLの場合は上限なし（従来通りの挙動、後方互換）。
-- 複数DBを横断検索した際、無関係なDBのチャンクが紛れ込んで結果を圧迫する問題への対処
-- （2026-08-25、ユーザーからの実際のクエリ例で確認）。
ALTER TABLE namespaces ADD COLUMN result_limit INTEGER;
