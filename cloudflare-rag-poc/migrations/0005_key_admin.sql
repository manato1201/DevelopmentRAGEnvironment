-- APIキーごとの共有namespaceアクセス許可（既存GASのallowed_namespaces相当）。
-- これまでの実装では「全ユーザーが全shared namespaceを閲覧できる」という単純化した挙動
-- だったが、GAS本来の「キーごとに見られるnamespaceを制御する」設計に合わせて厳格化する。
-- adminロールはこのテーブルに関わらず全shared namespaceを閲覧できる（src/auth.ts参照）。
CREATE TABLE key_namespace_grants (
    user_id TEXT NOT NULL,
    namespace_id TEXT NOT NULL,
    PRIMARY KEY (user_id, namespace_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (namespace_id) REFERENCES namespaces(namespace_id)
);

-- 既存ユーザーは「移行前は全shared namespaceが見えていた」という挙動を壊さないよう、
-- 現時点で存在する全shared namespaceへの明示的な許可を後付けで作成しておく。
-- （今後adminが新規発行するキーは、ここに頼らず明示的にnamespacesを指定する）
INSERT INTO key_namespace_grants (user_id, namespace_id)
SELECT u.user_id, n.namespace_id
FROM users u
CROSS JOIN namespaces n
WHERE n.scope = 'shared';

-- トークン予算の自動リセット用（既存GAS _applyScheduledResets_相当）。
ALTER TABLE token_budgets ADD COLUMN reset_interval_hours INTEGER;
