-- namespaceごとの同期元設定（既存GASのDB_KEY_MAP/DRIVE_KEY_MAP・スクリプトプロパティ相当）。
CREATE TABLE kb_sources (
    namespace_id TEXT PRIMARY KEY,
    notion_database_id TEXT,
    drive_folder_id TEXT,
    FOREIGN KEY (namespace_id) REFERENCES namespaces(namespace_id)
);

-- 知識ベース登録操作の履歴（既存GAS getKbLogSheet_/adminKbHistory相当）。
CREATE TABLE kb_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id TEXT NOT NULL,
    namespace_id TEXT NOT NULL,
    source TEXT NOT NULL,      -- 'notion' | 'drive' | 'manual'
    file TEXT,
    status TEXT NOT NULL,      -- 'ok' | 'error' | 'skipped'
    detail TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX idx_kb_log_op ON kb_log(op_id);
