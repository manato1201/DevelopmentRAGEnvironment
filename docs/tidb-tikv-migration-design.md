# TiDB Cloud / TiKV 移行設計書（IMPROVEMENT_PLAN.md Phase3）

**位置づけ:** 本書は設計のみを扱う。実装（実際にTiDB/TiKVへ接続するコードを本番経路に組み込むこと）は、下記「実装着手条件」を満たすまで行わない（IMPROVEMENT_PLAN.md Phase3のアンチパターン注記に従う）。参考実装として移行スクリプトのスケルエトンを1本だけ用意しているが、これは実際のTiDBインスタンスに対して未検証であり、`scripts/rag_local_bridge.py` 等の本番経路からは呼ばれない独立スクリプトである。

---

## 1. 適用範囲の分離

このリポジトリには性質の異なる2つのデータストアがある。一括で「DBを置き換える」計画にはせず、別軸で扱う。

| ストア | 現状 | 本書での扱い |
|---|---|---|
| 認証・メタデータ（`data/auth.db`、SQLite） | `users`/`access_logs`（`scripts/auth_manager.py`）・`understanding_scores`（`scripts/score_engine.py`）の3テーブル | **§2 TiDB**: スキーマ移行計画を用意する |
| ベクトル本体（`data/chroma/`、ChromaDB PersistentClient） | ローカルディスクI/O、規模的な問題は未観測 | **§3 TiKV**: 適用候補として条件のみ明記。今は移行しない |

`docs/distribution-strategy.md` が非推奨としたのは「個人配布用途でのDocker回帰」（同書§2.3、方式D）であり、TiDB Cloudのようなマネージドサービスへの接続はローカル実行バイナリの配布方式そのものを変えない。両者は矛盾しない（§4参照）。

---

## 2. TiDB: 認証・メタデータの移行計画

### 2.1 現在のスキーマ（`data/auth.db`、`scripts/auth_manager.py` / `scripts/score_engine.py` から採取）

```sql
-- scripts/auth_manager.py の実際のCREATE TABLE文（2026-08-12時点）
CREATE TABLE IF NOT EXISTS users (
    id                  TEXT PRIMARY KEY,
    api_key_hash        TEXT NOT NULL UNIQUE,
    display_name        TEXT NOT NULL,
    allowed_namespaces  TEXT NOT NULL DEFAULT '[]',   -- JSON文字列として保存
    is_admin            INTEGER NOT NULL DEFAULT 0,   -- SQLiteにBOOLEAN型が無いため0/1
    created_at          TEXT NOT NULL,                -- ISO8601文字列
    last_used           TEXT
);

CREATE TABLE IF NOT EXISTS access_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT,
    timestamp    TEXT NOT NULL,
    endpoint     TEXT NOT NULL,
    query_text   TEXT,
    namespaces   TEXT,
    status_code  INTEGER,
    ip_addr      TEXT
);

-- scripts/score_engine.py
CREATE TABLE IF NOT EXISTS understanding_scores (
    user_id    TEXT NOT NULL,
    topic      TEXT NOT NULL,
    score      REAL NOT NULL DEFAULT 0.5,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, topic)
);
```

### 2.2 移行後（TiDB、MySQL互換）のスキーマ

TiDBはMySQLワイヤプロトコル互換のため、型のみMySQL側の慣用に合わせて調整する。列名・主キー構成はそのまま維持し、`pep.py`/`auth_manager.py`/`score_engine.py`のインターフェースを変更しないことを最優先にする。

```sql
CREATE TABLE users (
    id                 VARCHAR(64)  PRIMARY KEY,
    api_key_hash       VARCHAR(128) NOT NULL UNIQUE,
    display_name       VARCHAR(255) NOT NULL,
    allowed_namespaces JSON         NOT NULL,          -- SQLite版はTEXT('[]') → JSON型に強化
    is_admin           TINYINT(1)   NOT NULL DEFAULT 0,
    created_at         DATETIME     NOT NULL,
    last_used          DATETIME
);

CREATE TABLE access_logs (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id      VARCHAR(64),
    timestamp    DATETIME     NOT NULL,
    endpoint     VARCHAR(64)  NOT NULL,
    query_text   TEXT,
    namespaces   VARCHAR(255),
    status_code  SMALLINT,
    ip_addr      VARCHAR(64),
    INDEX idx_access_logs_user_id (user_id),
    INDEX idx_access_logs_timestamp (timestamp)
);

CREATE TABLE understanding_scores (
    user_id    VARCHAR(64) NOT NULL,
    topic      VARCHAR(255) NOT NULL,
    score      FLOAT NOT NULL DEFAULT 0.5,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, topic)
);
```

`access_logs`/`understanding_scores` にインデックスを追加しているのは、SQLite版には存在しない最適化（TiDBは分散ストレージのため、フルスキャンのコストがSQLiteより顕著に出やすい）。挙動には影響しない。

### 2.3 移行手順（案）

1. `data/auth.db` を読み取り専用で開く（サービス停止不要 — SQLiteはWALモードでも読み取りはブロックしない）。
2. `users` → `access_logs` → `understanding_scores` の順でバルクINSERT（外部キー制約は現状無いため順序に厳密な制約はないが、可読性のため親から子の順で統一）。
3. 件数突合（Phase3検証チェックリスト該当項目）: 移行前後で `SELECT COUNT(*)` を3テーブルそれぞれ比較する。
4. `auth_manager.py`/`score_engine.py` の接続先を環境変数で切り替えられるようにする（例: `AUTH_DB_BACKEND=sqlite|tidb`、未設定時は現行のsqlite3のまま — 後方互換）。実際の接続先切り替えロジックの実装は、下記「実装着手条件」を満たしてから行う。

### 2.4 参考実装（未接続・未検証）

`scripts/migrate_auth_to_tidb.py`（本書と同時に追加）に、上記手順1〜3のスケルトンを実装した。`pymysql`（現時点でこのリポジトリの依存関係には含めていない — 実際に移行を実行する時点で `uv add pymysql` すること）を使い、`data/auth.db` から読み取ったレコードをTiDBへ書き込む。接続先はコマンドライン引数 or 環境変数（`TIDB_HOST`/`TIDB_PORT`/`TIDB_USER`/`TIDB_PASSWORD`/`TIDB_DATABASE`）で指定する想定。**実際のTiDBインスタンスに対しては未実行・未検証**であり、実行前に必ずステージング環境で件数突合を行うこと。

---

## 3. TiKV: 高頻度KVアクセスの適用候補（設計のみ、実装しない）

ChromaDBのベクトル本体（`data/chroma/`）は本フェーズの移行対象に**含めない**。`PersistentClient`（ローカルディスク）で規模的な問題が出ていないため。

TiKVが適用候補になり得るのは、`understanding_scores` のような「ユーザーID + トピック単位の高頻度・低レイテンシKVアクセス」が将来ボトルネック化した場合。現時点ではSQLite（またはTiDB移行後はTiDB自体）で十分間に合っている。

### 実装着手条件（このいずれかを満たすまで着手しない）

- 同時接続ユーザー数が「個人〜数名運用」の範囲を明確に超えた（目安: 同時アクティブユーザー数が2桁に達する）
- `access_logs` への書き込みレイテンシが、SQLiteのfsync待ちに起因して体感できる劣化（クエリ応答全体の遅延として数百ms以上）を引き起こしていることが実測で確認された
- 上記いずれかが観測された時点で、まず「TiDBへの移行だけで足りるか」を先に検証し、それでも不足する場合にのみTiKV導入を検討する（TiDB自体もある程度の高頻度アクセスには耐えるため、TiKVを直接使う必要があるとは限らない）

---

## 4. `docs/distribution-strategy.md` との非矛盾

`distribution-strategy.md` が非推奨としたのは「個人配布用途でのDocker回帰」（同書§2.3、方式D — エンドユーザーの手元にDockerランタイムを要求する配布方式）であり、これは「配布されたバイナリ/スクリプトがどう動くか」の話。

TiDB Cloudのようなマネージドサービスへの**接続**（本書の対象）は、ローカル実行バイナリの配布方式そのものを変えない — 配布物は変わらずローカルで動くスクリプト/実行ファイルのままで、その内部が接続する先がSQLiteファイルからTiDB CloudのTCP接続に変わるだけである。両者は独立した軸であり、矛盾しない。

配布方式（`distribution-strategy.md` 方式A〜E）のいずれとも、TiDB接続設定（接続文字列の環境変数化等）は独立して両立する。

---

## 5. 検証チェックリスト（実装着手後、TiDB移行時点で満たすべき項目）

- [ ] `auth.db`の3テーブル全レコードがTiDBへ欠損なく移行できること（件数突合）
- [ ] `pep.py`の`authorize()`/`filter_namespaces()`がTiDB移行後もインターフェース変更なしに動作すること
- [ ] `score_engine.py`の`update_score()`/`get_score()`がTiDB接続でも既存のSQLite版と同じ戻り値形式を返すこと
- [ ] ChromaDB（ベクトル本体）が本フェーズの移行対象に含まれていないこと（スコープ確認）
- [ ] 配布方式（`distribution-strategy.md`方式A〜E）のいずれとも、TiDB接続設定が独立して両立すること

## 6. アンチパターン

「TiDB/TiKVを入れる」こと自体を目的化しない。SQLiteのファイルロックやChromaDBのローカルディスクI/Oが実際にボトルネックとして観測されるまでは設計止まりとし、実装（本番経路への接続コード組み込み）には着手しない。
