"""
reference_remote.py — Reference タブの説明を、Cloudflare（rag-poc の Worker）から取る・置く（2026-11-19）

  ・方針（決定: 2026-11-19）: 説明は、開発側が 1 回だけ作って、Cloudflare（D1 に本文、R2 に画像・動画）に置く。参加者の端末は、通信で取って読むだけ
    （人ごとに内容が違う・AI の費用が際限なくかかる、を避ける。手元のファイルでの配布もしない）。
  ・端末のキャッシュ: <保存先>/localRAG/reference/remote/…。一覧（index）は 1 時間。説明は、版（version）が同じなら、通信しない。
    通信できないときは、キャッシュを使う（無ければ、空）。例外は投げない（取得系）。
  ・置く側（publish_*）は、管理者のキー用。scripts/publish_reference.py が使う。

Qt にも Houdini にも依存しない（単体テストできる。通信は opener で差し替える）。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

_USER_AGENT = "HoudiniRAGPanel/1.0"  # Cloudflare は urllib 既定の User-Agent を bot として拒否する（error 1010）
INDEX_MAX_AGE_SECONDS = 3600
_SAFE = re.compile(r"[^0-9a-zA-Z_.-]+")


def _base(cfg: dict) -> str:
    return str((cfg or {}).get("cf_url", "")).strip().rstrip("/")


def _cache_root(cfg: dict) -> Path | None:
    base_dir = str((cfg or {}).get("local_bridge_dir") or "")
    return Path(base_dir) / "localRAG" / "reference" / "remote" if base_dir else None


def _safe(text: str) -> str:
    return _SAFE.sub("_", str(text or "")).strip("_") or "x"


def _request(cfg: dict, path: str, payload: dict | bytes, timeout: int, opener: Callable | None, content_type: str = "application/json") -> bytes:
    base = _base(cfg)
    if not base:
        raise RuntimeError("Cloudflare の URL が設定されていません")
    data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": content_type, "User-Agent": _USER_AGENT}
    key = str((cfg or {}).get("cf_api_key", ""))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method="POST")
    with (opener or (lambda r, t: urllib.request.urlopen(r, timeout=t)))(req, timeout) as response:
        return response.read()


def _json(cfg: dict, path: str, payload: dict, timeout: int, opener: Callable | None) -> dict:
    data = json.loads(_request(cfg, path, payload, timeout, opener))
    if not isinstance(data, dict):
        raise ValueError("想定していない応答です")
    return data


# ── 取得（参加者の端末）────────────────────────────────────────────────────

def load_cached_index(cfg: dict) -> dict[str, dict]:
    """保存してある一覧（通信しない）。無ければ空。"""
    root = _cache_root(cfg)
    try:
        data = json.loads((root / "_index.json").read_text(encoding="utf-8")) if root else {}
        items = data.get("items") or {}
        return items if isinstance(items, dict) else {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def fetch_index(cfg: dict, now: float | None = None, opener: Callable | None = None, force: bool = False) -> dict[str, dict]:
    """説明のある項目の一覧。{"node/sop/scatter": {"kind", "key", "title", "version", "mediaCount"}, ...}（キーは kind/key ではなく "kind|key"）。
    1 時間は、保存したものを使う。取れなければ、古い保存か、空。"""
    now = time.time() if now is None else now
    root = _cache_root(cfg)
    path = root / "_index.json" if root else None
    cached: dict = {}
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached = data.get("items") or {}
            if not force and cached and now - float(data.get("fetched_at", 0)) < INDEX_MAX_AGE_SECONDS:
                return cached
        except (OSError, ValueError, AttributeError, TypeError):
            cached = {}
    try:
        result = _json(cfg, "/reference/index", {}, 20, opener)
        items = {f"{i['kind']}|{i['key']}": i for i in (result.get("items") or []) if isinstance(i, dict) and i.get("kind") and i.get("key")}
    except Exception:  # noqa: BLE001 -- 通信できなくても、保存したもので動く
        return cached
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"fetched_at": now, "items": items}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return items


def index_key(kind: str, key: str) -> str:
    return f"{kind}|{key}"


def _entry_path(cfg: dict, kind: str, key: str) -> Path | None:
    root = _cache_root(cfg)
    return root / "entries" / _safe(kind) / f"{_safe(key)}.json" if root else None


def load_cached_entry(cfg: dict, kind: str, key: str) -> dict | None:
    path = _entry_path(cfg, kind, key)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("entry"), dict) else None


def fetch_entry(cfg: dict, kind: str, key: str, version: int | None = None, opener: Callable | None = None) -> dict | None:
    """1 項目の説明（{"entry", "media", "title", "version"}）。保存してある版が version と同じなら、通信しない。
    通信できなくても、保存したものがあれば、それを返す。無ければ None。"""
    cached = load_cached_entry(cfg, kind, key)
    if cached is not None and version is not None and int(cached.get("version", -1)) == int(version):
        return cached
    try:
        data = _json(cfg, "/reference/entry", {"kind": kind, "key": key}, 20, opener)
        if data.get("status") != "ok" or not isinstance(data.get("entry"), dict):
            return cached
    except Exception:  # noqa: BLE001
        return cached
    record = {"entry": data["entry"], "media": [m for m in (data.get("media") or []) if isinstance(m, dict)],
              "title": str(data.get("title") or ""), "version": int(data.get("version") or 0)}
    path = _entry_path(cfg, kind, key)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return record


def media_path(cfg: dict, media_id: str) -> Path | None:
    root = _cache_root(cfg)
    return root / "media" / _safe(media_id) if root else None


def fetch_media(cfg: dict, media_id: str, opener: Callable | None = None) -> Path | None:
    """画像・動画を、端末に保存して、そのパスを返す（保存済みなら、通信しない）。取れなければ None。
    id は、説明を書き換えても同じ名前を使い回さない前提（置く側が、版つきの名前にする: publish_reference.py）。"""
    path = media_path(cfg, media_id)
    if path is None:
        return None
    if path.is_file() and path.stat().st_size > 0:
        return path
    try:
        data = _request(cfg, "/reference/media", {"id": media_id}, 60, opener)
        if not data:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
    except Exception:  # noqa: BLE001
        return None


CACHE_MAX_BYTES = 50 * 1024 * 1024  # 画像・動画の保存の上限（端末の容量を圧迫しないため）


def prune_cache(cfg: dict, max_bytes: int = CACHE_MAX_BYTES) -> int:
    """端末に保存した画像・動画の掃除。消した件数を返す。
    ・どの説明からも使われない画像（説明が更新されて、古くなったもの）を消す
    ・それでも合計が max_bytes を超えるときは、古い（最後に使った日時の順）ものから消す
    説明の本文（小さい）は、消さない。例外は投げない。"""
    root = _cache_root(cfg)
    if root is None or not (root / "media").is_dir():
        return 0
    wanted: set[str] = set()
    entries_dir = root / "entries"
    if entries_dir.is_dir():
        for path in entries_dir.rglob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for media in (record.get("media") or []) if isinstance(record, dict) else []:
                if isinstance(media, dict) and media.get("id"):
                    wanted.add(_safe(str(media["id"])))
    removed = 0
    files = []
    for path in (root / "media").iterdir():
        try:
            if not path.is_file():
                continue
            if path.name not in wanted:
                path.unlink()
                removed += 1
            else:
                stat = path.stat()
                files.append((max(stat.st_atime, stat.st_mtime), stat.st_size, path))
        except OSError:
            continue
    total = sum(size for _, size, _ in files)
    for _, size, path in sorted(files):
        if total <= max_bytes:
            break
        try:
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            continue
    return removed


# ── 置く（開発側。管理者のキー）──────────────────────────────────────────────

def publish_entry(cfg: dict, kind: str, key: str, title: str, entry: dict, media: list[dict] | None = None, opener: Callable | None = None) -> dict:
    """説明を置く（同じ項目は、版が 1 つ上がって、上書きされる）。失敗は例外のまま（呼び出し側が、画面に出す）。"""
    return _json(cfg, "/admin/reference/put", {"kind": kind, "key": key, "title": title, "entry": entry, "media": media or []}, 30, opener)


def delete_entry(cfg: dict, kind: str, key: str, opener: Callable | None = None) -> dict:
    """公開した説明を取り下げる（画像は、Worker の R2 に残る。説明が無ければ、誰も参照しない）。"""
    return _json(cfg, "/admin/reference/delete", {"kind": kind, "key": key}, 30, opener)


def publish_media(cfg: dict, media_id: str, data: bytes, opener: Callable | None = None) -> dict:
    """画像・動画を置く（Worker 側の上限 12MB）。"""
    from urllib.parse import quote

    base = _base(cfg)
    if not base:
        raise RuntimeError("Cloudflare の URL が設定されていません")
    headers = {"Content-Type": "application/octet-stream", "User-Agent": _USER_AGENT}
    key = str((cfg or {}).get("cf_api_key", ""))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(f"{base}/admin/reference/media_put?id={quote(media_id, safe='/')}", data=data, headers=headers, method="POST")
    with (opener or (lambda r, t: urllib.request.urlopen(r, timeout=t)))(req, 120) as response:
        return json.loads(response.read())


def error_text(exc: BaseException) -> str:
    """通信の例外を、画面に出せる短い文に（Worker の {"error": …} があれば、それ）。"""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            if isinstance(body, dict) and body.get("error"):
                return str(body["error"])[:300]
        except Exception:  # noqa: BLE001
            pass
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"接続できません: {exc.reason}"
    return str(exc)[:300] or exc.__class__.__name__
