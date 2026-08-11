#!/usr/bin/env python3
"""
migrate_auth_to_tidb.py — data/auth.db（SQLite）→ TiDB 移行スクリプト（参考実装）

IMPROVEMENT_PLAN.md Phase3 / docs/tidb-tikv-migration-design.md §2.4 の
参考実装。**実際のTiDBインスタンスに対しては未実行・未検証。** このリポジトリの
本番経路（rag_local_bridge.py 等）からは呼ばれない独立スクリプトであり、
実装着手条件（docs/tidb-tikv-migration-design.md §3）を満たすまでは実行しない。

事前準備:
    uv add pymysql   # 現時点ではこのリポジトリの依存関係に含めていない

Usage:
    uv run python scripts/migrate_auth_to_tidb.py --dry-run
    uv run python scripts/migrate_auth_to_tidb.py --apply

Env（--apply 時に必須。接続情報を平文でコマンドライン引数に渡さないため環境変数のみ対応）:
    TIDB_HOST, TIDB_PORT（既定4000）, TIDB_USER, TIDB_PASSWORD, TIDB_DATABASE
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_AUTH_DB = _REPO_ROOT / "data" / "auth.db"

# docs/tidb-tikv-migration-design.md §2.2 のDDLと対応させること。
_SCHEMA_TIDB = """
CREATE TABLE IF NOT EXISTS users (
    id                 VARCHAR(64)  PRIMARY KEY,
    api_key_hash       VARCHAR(128) NOT NULL UNIQUE,
    display_name       VARCHAR(255) NOT NULL,
    allowed_namespaces JSON         NOT NULL,
    is_admin           TINYINT(1)   NOT NULL DEFAULT 0,
    created_at         DATETIME     NOT NULL,
    last_used          DATETIME
);

CREATE TABLE IF NOT EXISTS access_logs (
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

CREATE TABLE IF NOT EXISTS understanding_scores (
    user_id    VARCHAR(64) NOT NULL,
    topic      VARCHAR(255) NOT NULL,
    score      FLOAT NOT NULL DEFAULT 0.5,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, topic)
);
"""


def _read_sqlite_rows(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    """data/auth.db の3テーブル全件を読み取る（読み取り専用）。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {}
        for name in ("users", "access_logs", "understanding_scores"):
            cur = conn.execute(f"SELECT * FROM {name}")
            tables[name] = [dict(row) for row in cur.fetchall()]
        return tables
    finally:
        conn.close()


def _connect_tidb():
    """
    TiDBへ接続する。pymysql は事前インストールが必要
    （`uv add pymysql`、このリポジトリの既定依存関係には含めていない）。
    """
    import pymysql  # noqa: PLC0415 -- 実行時にのみ必要な参考実装用の遅延import

    return pymysql.connect(
        host=os.environ["TIDB_HOST"],
        port=int(os.environ.get("TIDB_PORT", "4000")),
        user=os.environ["TIDB_USER"],
        password=os.environ["TIDB_PASSWORD"],
        database=os.environ["TIDB_DATABASE"],
        charset="utf8mb4",
        autocommit=False,
    )


def _migrate(tables: dict[str, list[dict[str, Any]]], dry_run: bool) -> None:
    counts = {name: len(rows) for name, rows in tables.items()}
    print(f"移行対象件数: {counts}")

    if dry_run:
        print("--dry-run のため書き込みは行いません。")
        return

    conn = _connect_tidb()
    try:
        with conn.cursor() as cur:
            for statement in _SCHEMA_TIDB.strip().split(";\n\n"):
                statement = statement.strip().rstrip(";")
                if statement:
                    cur.execute(statement)

            for user in tables["users"]:
                cur.execute(
                    "INSERT INTO users (id, api_key_hash, display_name, allowed_namespaces, "
                    "is_admin, created_at, last_used) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)",
                    (
                        user["id"], user["api_key_hash"], user["display_name"],
                        user["allowed_namespaces"], user["is_admin"],
                        user["created_at"], user["last_used"],
                    ),
                )

            for log in tables["access_logs"]:
                cur.execute(
                    "INSERT INTO access_logs (user_id, timestamp, endpoint, query_text, "
                    "namespaces, status_code, ip_addr) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        log["user_id"], log["timestamp"], log["endpoint"], log["query_text"],
                        log["namespaces"], log["status_code"], log["ip_addr"],
                    ),
                )

            for score in tables["understanding_scores"]:
                cur.execute(
                    "INSERT INTO understanding_scores (user_id, topic, score, updated_at) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE score=VALUES(score), updated_at=VALUES(updated_at)",
                    (score["user_id"], score["topic"], score["score"], score["updated_at"]),
                )

        conn.commit()
        print("移行が完了しました。件数突合を必ず行ってください（docs/tidb-tikv-migration-design.md §2.3）。")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-db", default=str(_DEFAULT_AUTH_DB), help="data/auth.db のパス")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="件数を表示するだけで書き込まない")
    group.add_argument("--apply", action="store_true", help="実際にTiDBへ書き込む")
    args = parser.parse_args()

    db_path = Path(args.auth_db)
    if not db_path.exists():
        raise SystemExit(f"auth.db が見つかりません: {db_path}")

    tables = _read_sqlite_rows(db_path)
    _migrate(tables, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
