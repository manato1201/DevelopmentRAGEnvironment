"""bridge_guard.py — rag_local_bridge 用の Host / Origin 検査(認証ではない)。

目的: ローカルで動く API を、閲覧中の別サイトのページから叩かれないようにする。
  - Host 検査: DNS rebinding(攻撃者のドメインが 127.0.0.1 を指す)への対策。
  - Origin 検査: ブラウザ経由の CSRF 対策。Origin を付けないクライアント
    (Unity / Houdini / curl / CI)はそのまま通す。`Origin: null` は拒否。

これは認証の代わりにならない。複数人で使うときは X-API-Key による認証が前提。

環境変数:
    RAG_BRIDGE_ALLOWED_HOSTS  追加で許可する Host(カンマ区切り。ポートなしのホスト名)
    RAG_BRIDGE_CORS_ORIGINS   別オリジンのブラウザアプリを許可するとき(カンマ区切りの Origin)
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

ALLOWED_HOSTS_ENV = "RAG_BRIDGE_ALLOWED_HOSTS"
CORS_ORIGINS_ENV = "RAG_BRIDGE_CORS_ORIGINS"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def host_only(host_header: str) -> str:
    """Host ヘッダからポートを除いたホスト名(小文字)を返す。IPv6 の [::1]:8766 にも対応。"""
    value = (host_header or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def allowed_hosts() -> frozenset[str]:
    return LOOPBACK_HOSTS | {h.lower() for h in _csv_env(ALLOWED_HOSTS_ENV)}


def cors_origins() -> list[str]:
    return [o.rstrip("/") for o in _csv_env(CORS_ORIGINS_ENV)]


def host_allowed(host_header: str) -> bool:
    return host_only(host_header) in allowed_hosts()


def origin_allowed(origin: str | None, host_header: str) -> bool:
    """Origin が無い(非ブラウザ)・同一オリジン・許可リスト内のどれかなら True。"""
    if origin is None:
        return True
    origin = origin.strip()
    if origin == "" or origin.lower() == "null":
        return False
    if origin.rstrip("/") in cors_origins():
        return True
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return parts.netloc.lower() == (host_header or "").strip().lower()


def check_request(method: str, host_header: str, origin: str | None) -> str | None:
    """拒否理由(日本語)を返す。通してよければ None。"""
    if not host_allowed(host_header):
        return "このホスト名では使えません(RAG_BRIDGE_ALLOWED_HOSTS で許可できます)。"
    if method.upper() in UNSAFE_METHODS and not origin_allowed(origin, host_header):
        return "このオリジンからの変更操作は許可されていません。"
    return None


def cors_headers_for(origin: str | None) -> dict[str, str]:
    """許可リストに載った Origin にだけ CORS ヘッダを返す(`*` は使わない)。"""
    if origin and origin.rstrip("/") in cors_origins():
        return {
            "Access-Control-Allow-Origin": origin.rstrip("/"),
            "Vary": "Origin",
        }
    return {}
