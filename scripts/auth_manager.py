#!/usr/bin/env python3
"""
auth_manager.py — ユーザー認証・アクセス制御マネージャー

SQLite ベース。API キー発行・namespace 単位の権限管理・アクセスログ。

CLI:
    python scripts/auth_manager.py create  --name "Alice" --namespaces tool_docs,research
    python scripts/auth_manager.py list
    python scripts/auth_manager.py delete  --id <user_id>
    python scripts/auth_manager.py update  --id <user_id> --namespaces tool_docs
    python scripts/auth_manager.py logs    [--user <user_id>] [--limit 50]
    python scripts/auth_manager.py create-admin --name "Admin"
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# ─── パス設定 ────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
_DB_PATH = _HERE.parent / "data" / "auth.db"

# ─── 有効な namespace ────────────────────────────────────────────────────────────
VALID_NAMESPACES = [
    "tool_docs",
    "game_info",
    "research",
    "team_notes",
    "personal_notes",
]


# ─── ユーティリティ ──────────────────────────────────────────────────────────────

def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _short_id() -> str:
    return secrets.token_hex(4)   # 8 文字の hex ID


# ─── DB 初期化 ───────────────────────────────────────────────────────────────────

def init_db(db_path: Path = _DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id                  TEXT PRIMARY KEY,
            api_key_hash        TEXT NOT NULL UNIQUE,
            display_name        TEXT NOT NULL,
            allowed_namespaces  TEXT NOT NULL DEFAULT '[]',
            is_admin            INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL,
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
    """)
    conn.commit()
    return conn


# ─── AuthManager ─────────────────────────────────────────────────────────────────

class AuthManager:
    """スレッドセーフなユーザー管理クラス。"""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        # 接続はリクエストごとに生成（スレッドセーフ）
        init_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── ユーザー作成 ──────────────────────────────────────────────────────────────

    def create_user(
        self,
        display_name: str,
        namespaces: list[str],
        is_admin: bool = False,
    ) -> tuple[str, str]:
        """
        ユーザーを作成する。
        Returns (user_id, api_key) — api_key は平文（一度だけ表示）
        """
        invalid = [ns for ns in namespaces if ns not in VALID_NAMESPACES]
        if invalid:
            raise ValueError(f"無効な namespace: {invalid}")

        user_id  = _short_id()
        api_key  = secrets.token_hex(24)   # 48 文字のランダムキー
        key_hash = _hash_key(api_key)

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO users
                    (id, api_key_hash, display_name, allowed_namespaces, is_admin, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, key_hash, display_name,
                 json.dumps(namespaces, ensure_ascii=False),
                 1 if is_admin else 0,
                 _now()),
            )
        return user_id, api_key

    # ── 認証 ─────────────────────────────────────────────────────────────────────

    def validate_key(self, api_key: str) -> Optional[dict]:
        """
        API キーを検証してユーザー情報を返す。
        無効なキーは None を返す。
        """
        if not api_key:
            return None
        key_hash = _hash_key(api_key)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE api_key_hash = ?", (key_hash,)
            ).fetchone()
        if not row:
            return None
        # last_used を更新
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET last_used = ? WHERE id = ?",
                (_now(), row["id"]),
            )
        return self._row_to_dict(row)

    # ── ユーザー参照 ─────────────────────────────────────────────────────────────

    def get_user(self, user_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── ユーザー更新 ─────────────────────────────────────────────────────────────

    def update_namespaces(self, user_id: str, namespaces: list[str]) -> bool:
        invalid = [ns for ns in namespaces if ns not in VALID_NAMESPACES]
        if invalid:
            raise ValueError(f"無効な namespace: {invalid}")
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE users SET allowed_namespaces = ? WHERE id = ?",
                (json.dumps(namespaces, ensure_ascii=False), user_id),
            )
        return cur.rowcount > 0

    def update_display_name(self, user_id: str, name: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE users SET display_name = ? WHERE id = ?",
                (name, user_id),
            )
        return cur.rowcount > 0

    def regenerate_key(self, user_id: str) -> Optional[str]:
        """API キーを再発行して新しい平文キーを返す。"""
        new_key  = secrets.token_hex(24)
        key_hash = _hash_key(new_key)
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE users SET api_key_hash = ? WHERE id = ?",
                (key_hash, user_id),
            )
        return new_key if cur.rowcount > 0 else None

    # ── ユーザー削除 ─────────────────────────────────────────────────────────────

    def delete_user(self, user_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0

    # ── アクセスログ ─────────────────────────────────────────────────────────────

    def log_access(
        self,
        user_id: Optional[str],
        endpoint: str,
        query_text: Optional[str] = None,
        namespaces: Optional[list[str]] = None,
        status_code: int = 200,
        ip_addr: Optional[str] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO access_logs
                    (user_id, timestamp, endpoint, query_text, namespaces, status_code, ip_addr)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, _now(), endpoint,
                    query_text,
                    json.dumps(namespaces, ensure_ascii=False) if namespaces else None,
                    status_code, ip_addr,
                ),
            )

    def get_logs(
        self,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM access_logs"
        params: list = []
        if user_id:
            sql += " WHERE user_id = ?"
            params.append(user_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── 内部ユーティリティ ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["allowed_namespaces"] = json.loads(d["allowed_namespaces"])
        d["is_admin"] = bool(d["is_admin"])
        return d


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def _print_users(users: list[dict]) -> None:
    if not users:
        print("ユーザーなし")
        return
    print(f"{'ID':<10} {'名前':<20} {'Admin':<6} {'Namespaces':<40} {'最終アクセス'}")
    print("-" * 90)
    for u in users:
        ns    = ", ".join(u["allowed_namespaces"]) or "(なし)"
        admin = "✓" if u["is_admin"] else ""
        last  = (u["last_used"] or "未使用")[:19]
        print(f"{u['id']:<10} {u['display_name']:<20} {admin:<6} {ns:<40} {last}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG ユーザー管理 CLI")
    sub = parser.add_subparsers(dest="cmd")

    # create
    c = sub.add_parser("create", help="ユーザーを作成")
    c.add_argument("--name", required=True)
    c.add_argument("--namespaces", default="",
                   help="カンマ区切り例: tool_docs,research")
    c.add_argument("--admin", action="store_true")

    # create-admin
    ca = sub.add_parser("create-admin", help="管理者ユーザーを作成")
    ca.add_argument("--name", required=True)
    ca.add_argument("--namespaces", default=",".join(VALID_NAMESPACES))

    # list
    sub.add_parser("list", help="ユーザー一覧")

    # delete
    d = sub.add_parser("delete", help="ユーザーを削除")
    d.add_argument("--id", required=True)

    # update
    u = sub.add_parser("update", help="namespace を更新")
    u.add_argument("--id", required=True)
    u.add_argument("--namespaces", required=True)
    u.add_argument("--name")

    # regenerate
    r = sub.add_parser("regenerate", help="API キーを再発行")
    r.add_argument("--id", required=True)

    # logs
    lg = sub.add_parser("logs", help="アクセスログを表示")
    lg.add_argument("--user")
    lg.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    mgr = AuthManager()

    if args.cmd in ("create", "create-admin"):
        is_admin = args.cmd == "create-admin" or getattr(args, "admin", False)
        ns_str = args.namespaces.strip()
        namespaces = [n.strip() for n in ns_str.split(",") if n.strip()] if ns_str else []
        try:
            uid, key = mgr.create_user(args.name, namespaces, is_admin=is_admin)
            print(f"\nユーザー作成完了")
            print(f"  ID      : {uid}")
            print(f"  名前    : {args.name}")
            print(f"  Admin   : {'Yes' if is_admin else 'No'}")
            print(f"  権限    : {', '.join(namespaces) or '(なし)'}")
            print(f"\n  ★ API キー（一度だけ表示）: {key}")
            print("  このキーを安全な場所に保存してください。再表示できません。\n")
        except ValueError as e:
            print(f"エラー: {e}")
            sys.exit(1)

    elif args.cmd == "list":
        _print_users(mgr.list_users())

    elif args.cmd == "delete":
        ok = mgr.delete_user(args.id)
        print("削除しました" if ok else "ユーザーが見つかりません")

    elif args.cmd == "update":
        ns = [n.strip() for n in args.namespaces.split(",") if n.strip()]
        try:
            ok = mgr.update_namespaces(args.id, ns)
            if ok and args.name:
                mgr.update_display_name(args.id, args.name)
            print("更新しました" if ok else "ユーザーが見つかりません")
        except ValueError as e:
            print(f"エラー: {e}")
            sys.exit(1)

    elif args.cmd == "regenerate":
        new_key = mgr.regenerate_key(args.id)
        if new_key:
            print(f"  ★ 新しい API キー: {new_key}")
        else:
            print("ユーザーが見つかりません")

    elif args.cmd == "logs":
        logs = mgr.get_logs(user_id=args.user, limit=args.limit)
        if not logs:
            print("ログなし")
            return
        print(f"{'時刻':<22} {'ユーザー':<10} {'エンドポイント':<12} {'クエリ':<40} {'NS'}")
        print("-" * 100)
        for lg in logs:
            ts    = (lg["timestamp"] or "")[:19]
            uid   = (lg["user_id"] or "anonymous")[:10]
            ep    = (lg["endpoint"] or "")[:12]
            q     = (lg["query_text"] or "")[:40]
            ns    = lg["namespaces"] or ""
            print(f"{ts:<22} {uid:<10} {ep:<12} {q:<40} {ns}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
