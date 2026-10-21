"""
gallery_upload.py — 生成した動画を、ダッシュボードの「動画」ページ（RAGReel ギャラリー）へアップロードする

背景:
  動画エンジン（video_factory_cloudrag_poc.exe）は、動画を作るたびに、exe の隣の output/ フォルダに
  書き出す（output/manifest.json と output/videos/<id>/{video.webm, thumb.png, metadata.json}）。
  ダッシュボード（ギャラリー Worker）に載るのは、アップロードされた動画だけで、これまでは、
  エンジンへ接続先が渡されていなかったため、Houdini から作った動画はほとんど載っていなかった。

このモジュールがやること（Qt に依存しない。標準ライブラリだけ。単体テストできる）:
  - find_local_entry():   動画ファイルから、output/manifest.json の該当の項目を見つける
  - upload_entry():       1本を、ギャラリーの POST /api/videos へ送る（multipart、Authorization: Bearer）
  - upload_missing():     output/ の中の、まだギャラリーに無い動画を、まとめて送る
  - fetch_gallery_ids():  ギャラリーに、すでにある動画の id（GET /manifest.json）

ギャラリー側は、同じ id の再アップロードを「上書き」として扱う（重複しない）ので、やり直しても安全。
大きな動画でもメモリを使い切らないよう、ファイルは少しずつ読みながら送る（ストリーミング）。
"""

from __future__ import annotations

import http.client
import json
import ssl
import uuid
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit

USER_AGENT = "HoudiniGalleryUploader/1.0"
# Cloudflare は、1回のリクエスト本文を、無料・Pro プランで 100MB までに制限している。
# 余裕を見て、これを超える動画は送らず、理由を返す。
MAX_UPLOAD_BYTES = 95 * 1024 * 1024
_CHUNK = 256 * 1024


class GalleryUploadError(Exception):
    """アップロードに失敗した（設定の不足・認証エラー・通信エラーなど）。メッセージは、そのまま画面に出せる。"""


# ─── ローカルの output/ の読み取り ────────────────────────────────────────────

def output_dir_for(exe_path: str) -> Path:
    """動画エンジンの出力フォルダ（exe の隣の output/）。"""
    return Path(exe_path).parent / "output"


def read_local_manifest(output_dir: Path) -> list[dict]:
    """output/manifest.json を読む。無い・壊れているときは、空のリスト。"""
    try:
        data = json.loads((Path(output_dir) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict) and e.get("id")] if isinstance(data, list) else []


def entry_files(output_dir: Path, entry: dict) -> tuple[Path, Path, Path]:
    """項目に対応する (動画, サムネイル, metadata.json) のパス（存在するとは限らない）。"""
    folder = Path(output_dir) / "videos" / str(entry["id"])
    return folder / "video.webm", folder / "thumb.png", folder / "metadata.json"


def find_local_entry(output_dir: Path, video_path: Path) -> dict | None:
    """
    動画ファイル（Houdini の「動画」タブの一覧にあるもの。phase2_cloudrag_<id>.webm）に対応する、
    output/manifest.json の項目を返す。見つからなければ None。
    ① ファイル名から id を決める（phase2_ を除いた名前が、そのまま id）。
    ② 無ければ、output/videos/<id>/video.webm とサイズが同じものを探す。
    """
    entries = read_local_manifest(output_dir)
    stem = Path(video_path).stem
    candidates = {stem, stem.removeprefix("phase2_")}
    for entry in entries:
        if str(entry["id"]) in candidates:
            return entry
    try:
        size = Path(video_path).stat().st_size
    except OSError:
        return None
    for entry in entries:
        video, _, _ = entry_files(output_dir, entry)
        try:
            if video.stat().st_size == size:
                return entry
        except OSError:
            continue
    return None


# ─── 送信 ───────────────────────────────────────────────────────────────────

def _connection(base_url: str, timeout: float) -> tuple[http.client.HTTPConnection, str]:
    """ギャラリーの URL から、接続と、パスの前置き（サブパスがあるとき）を作る。"""
    parts = urlsplit(base_url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise GalleryUploadError("ギャラリーの URL が正しくありません（https://… の形で入力してください）")
    prefix = parts.path.rstrip("/")
    if parts.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            parts.netloc, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        conn = http.client.HTTPConnection(parts.netloc, timeout=timeout)
    return conn, prefix


class _MultipartStream:
    """multipart/form-data の本文を、ファイルを少しずつ読みながら作る。read() を持つので http.client がそのまま送れる。"""

    def __init__(self, fields: list[tuple[str, str]], files: list[tuple[str, Path, str, str]]) -> None:
        self.boundary = uuid.uuid4().hex
        self._parts: list[bytes | Path] = []
        self._length = 0
        b = self.boundary
        for name, value in fields:
            head = (
                f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            ).encode()
            body = value.encode("utf-8") + b"\r\n"
            self._add_bytes(head + body)
        for name, path, filename, content_type in files:
            head = (
                f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            self._add_bytes(head)
            self._parts.append(path)
            self._length += path.stat().st_size
            self._add_bytes(b"\r\n")
        self._add_bytes(f"--{b}--\r\n".encode())
        self._iter = self._generate()

    def _add_bytes(self, data: bytes) -> None:
        self._parts.append(data)
        self._length += len(data)

    @property
    def length(self) -> int:
        return self._length

    def _generate(self) -> Iterable[bytes]:
        for part in self._parts:
            if isinstance(part, bytes):
                yield part
            else:
                with open(part, "rb") as f:
                    while chunk := f.read(_CHUNK):
                        yield chunk

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return b"".join(self._iter)
        out = b""
        while len(out) < size:
            try:
                out += next(self._iter)
            except StopIteration:
                break
        if len(out) > size:  # 余りは、次の read() の先頭へ戻す
            rest = out[size:]
            out = out[:size]
            self._iter = _chain(rest, self._iter)
        return out


def _chain(first: bytes, rest: Iterable[bytes]) -> Iterable[bytes]:
    yield first
    yield from rest


def _explain_http_error(status: int, body: bytes) -> str:
    try:
        message = json.loads(body.decode("utf-8", errors="replace")).get("error", "")
    except (ValueError, AttributeError):
        message = ""
    detail = f"（{message}）" if message else ""
    if status in (401, 403):
        return f"認証エラー{detail}: アップロードトークンが正しくありません"
    if status == 413:
        return f"動画が大きすぎて、受け付けられませんでした{detail}"
    return f"ギャラリーがエラーを返しました（HTTP {status}）{detail}"


def upload_entry(
    base_url: str,
    token: str,
    output_dir: Path,
    entry: dict,
    timeout: float = 600,
) -> None:
    """
    output/ の1本（entry）を、ギャラリーへ送る。失敗は GalleryUploadError（メッセージはそのまま画面に出せる）。
    動画が無い・大きすぎる・認証できない・通信できない、のいずれでも、他の動画には影響しない。
    """
    if not base_url.strip() or not token.strip():
        raise GalleryUploadError("ギャラリーの URL とアップロードトークンを、Settings タブで設定してください")
    video, thumb, meta = entry_files(output_dir, entry)
    if not video.is_file():
        raise GalleryUploadError(f"動画ファイルが見つかりません: {video}")
    if video.stat().st_size > MAX_UPLOAD_BYTES:
        mb = video.stat().st_size / 1024 / 1024
        raise GalleryUploadError(
            f"動画が大きすぎます（{mb:.0f}MB。上限は約{MAX_UPLOAD_BYTES // 1024 // 1024}MB）"
        )
    try:
        metadata_text = meta.read_text(encoding="utf-8")
        json.loads(metadata_text)
    except OSError:
        # metadata.json が無いときは、項目そのものを詳細の代わりにする（ギャラリーは JSON であることしか見ない）
        metadata_text = json.dumps(entry, ensure_ascii=False)
    except ValueError as exc:
        raise GalleryUploadError(f"metadata.json が壊れています: {meta} ({exc})") from exc

    files: list[tuple[str, Path, str, str]] = [("video", video, "video.webm", "video/webm")]
    if thumb.is_file():
        files.append(("thumbnail", thumb, "thumb.png", "image/png"))
    stream = _MultipartStream(
        [
            ("id", str(entry["id"])),
            ("entry", json.dumps(entry, ensure_ascii=False)),
            ("metadata", metadata_text),
        ],
        files,
    )

    conn, prefix = _connection(base_url, timeout)
    try:
        conn.request(
            "POST",
            f"{prefix}/api/videos",
            body=stream,
            headers={
                "Authorization": f"Bearer {token.strip()}",
                "Content-Type": f"multipart/form-data; boundary={stream.boundary}",
                "Content-Length": str(stream.length),
                "User-Agent": USER_AGENT,
            },
        )
        resp = conn.getresponse()
        body = resp.read()
    except (OSError, http.client.HTTPException) as exc:
        raise GalleryUploadError(f"ギャラリーに接続できませんでした: {exc}") from exc
    finally:
        conn.close()
    if resp.status >= 400:
        raise GalleryUploadError(_explain_http_error(resp.status, body))


def fetch_gallery_ids(base_url: str, timeout: float = 30) -> set[str]:
    """ギャラリーに、すでにある動画の id（GET /manifest.json）。取れなければ GalleryUploadError。"""
    conn, prefix = _connection(base_url, timeout)
    try:
        conn.request("GET", f"{prefix}/manifest.json", headers={"User-Agent": USER_AGENT})
        resp = conn.getresponse()
        body = resp.read()
    except (OSError, http.client.HTTPException) as exc:
        raise GalleryUploadError(f"ギャラリーに接続できませんでした: {exc}") from exc
    finally:
        conn.close()
    if resp.status >= 400:
        raise GalleryUploadError(_explain_http_error(resp.status, body))
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise GalleryUploadError("ギャラリーの一覧を読み取れませんでした") from exc
    return {str(e.get("id")) for e in data if isinstance(e, dict) and e.get("id")} if isinstance(data, list) else set()


def upload_missing(
    base_url: str,
    token: str,
    output_dir: Path,
    only_ids: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, list]:
    """
    output/ の中で、まだギャラリーに無い動画（only_ids があれば、その id のうち、無いもの）を、古い順に送る。
    戻り値: {"uploaded": [id…], "skipped": [id…]（すでにある）, "failed": [(id, 理由)…]}。
    1本の失敗で止めず、残りを続ける（認証エラーだけは、全部が同じ結果になるので、そこで止める）。
    """
    say = progress or (lambda _msg: None)
    existing = fetch_gallery_ids(base_url)
    result: dict[str, list] = {"uploaded": [], "skipped": [], "failed": []}
    entries = read_local_manifest(output_dir)
    entries.sort(key=lambda e: str(e.get("created_at", "")))  # 古い順（ギャラリーは新しいものを先頭に置く）
    targets = [e for e in entries if only_ids is None or str(e["id"]) in only_ids]
    for n, entry in enumerate(targets, 1):
        vid = str(entry["id"])
        if vid in existing:
            result["skipped"].append(vid)
            continue
        say(f"アップロード中 {n}/{len(targets)}: {entry.get('title') or vid}")
        try:
            upload_entry(base_url, token, output_dir, entry)
            result["uploaded"].append(vid)
        except GalleryUploadError as exc:
            result["failed"].append((vid, str(exc)))
            if "認証エラー" in str(exc):
                break
    return result


def gallery_env(cfg: dict) -> dict[str, str]:
    """動画エンジンに渡す環境変数（エンジンは、動画ができたあと、自分でギャラリーへ送る）。設定が足りなければ空。"""
    url = str(cfg.get("gallery_url", "")).strip()
    token = str(cfg.get("gallery_token", "")).strip()
    if not (cfg.get("gallery_auto_upload", True) and url and token):
        return {}
    return {"GALLERY_UPLOAD_URL": url, "GALLERY_UPLOAD_TOKEN": token}


def describe_result(result: dict[str, list]) -> str:
    """upload_missing() の結果を、画面に出す1行にする。"""
    parts = [f"{len(result['uploaded'])} 本をアップロードしました"]
    if result["skipped"]:
        parts.append(f"{len(result['skipped'])} 本は、すでにあるため省略")
    if result["failed"]:
        first = result["failed"][0]
        parts.append(f"{len(result['failed'])} 本が失敗（例: {first[1]}）")
    return " / ".join(parts)


__all__ = [
    "GalleryUploadError", "MAX_UPLOAD_BYTES", "describe_result", "entry_files", "fetch_gallery_ids",
    "find_local_entry", "gallery_env", "output_dir_for", "read_local_manifest", "upload_entry", "upload_missing",
]
