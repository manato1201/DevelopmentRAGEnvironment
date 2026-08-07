"""
youtube_transcribe.py — 字幕の無いYouTube動画から文字起こしを作る

背景:
  ナレッジ登録（Cloud RAGの adminKbImportYoutube / Local RAGの
  KnowledgeManager.import_youtube）は、どちらも「公式・自動生成の字幕」を
  YouTube側から取得することしかできない。技術解説・製品説明系の動画は
  字幕が無い、または動画側で焼き込み字幕になっているだけ（テキストとして
  取得不可）というケースが多く、そのままでは取り込めない。

このスクリプトがやること:
  1. yt-dlp で動画の音声のみをダウンロードする（ffmpegで軽量な音声形式に変換）
  2. Gemini の Files API に音声をアップロードし、generateContent で文字起こしを
     依頼する（既存のGEMINI_API_KEYをそのまま使う。技術用語・製品名はできるだけ
     そのまま書き取るよう指示している）
  3. 文字起こし結果を標準出力・ファイルに出す。
     --local-namespace を指定すると、そのままrag_local_bridge.py（Local RAG）の
     /api/knowledge/import/youtube にPOSTして登録まで自動化する。
     --cloud-url/--cloud-api-key/--cloud-db を指定すると、Cloud RAG（GAS）の
     doPost action:'admin_kb_import_youtube'（管理者専用・要admin API key）に
     POSTして登録まで自動化する。どちらも省略した場合は、文字起こし結果を
     「ナレッジ登録」タブの「文字起こしを貼り付け」欄に手動で貼ってください。

前提:
  - yt-dlp（pyproject.tomlに追加済み。`uv sync`で導入される）
  - ffmpeg（PATHに入っていること。yt-dlpが音声抽出に使う）
  - 環境変数 GEMINI_API_KEY

注意:
  - 音声をGoogle（Gemini API）に送信する。社外に出せない機密動画では使わないこと。
  - 長尺動画は文字起こし精度・処理時間が落ちる。技術解説動画（数分〜30分程度）を
    想定している。

使い方:
  python scripts/youtube_transcribe.py "https://www.youtube.com/watch?v=..." \
      --out transcript.txt

  # Local RAGへ自動登録まで行う場合
  python scripts/youtube_transcribe.py "https://www.youtube.com/watch?v=..." \
      --local-namespace houdini21 --local-port 8766 --local-api-key <XAPIKEY>

  # Cloud RAGへ自動登録まで行う場合（--cloud-api-keyは管理者キー）
  python scripts/youtube_transcribe.py "https://www.youtube.com/watch?v=..." \
      --cloud-url https://script.google.com/macros/s/XXXX/exec \
      --cloud-api-key <ADMIN_API_KEY> --cloud-db houdini21
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import tempfile
import time
from pathlib import Path

import requests

GEMINI_BASE = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-3.6-flash"

TRANSCRIBE_PROMPT = (
    "この音声を日本語で文字起こししてください。要約や意訳はせず、話されている内容を"
    "できるだけ逐語的に書き取ってください。製品名・ツール名・技術用語・型番・英語の"
    "固有名詞は、聞き取れた通りの表記（英語ならアルファベット表記）でそのまま残して"
    "ください。話者交代や相槌の書き起こしは不要です。フィラー（あの、えー等）は"
    "適度に省略して読みやすくして構いません。"
)


class TranscribeError(RuntimeError):
    pass


def download_audio(url: str, workdir: Path) -> tuple[Path, str]:
    """yt-dlpで音声のみをダウンロードする。戻り値: (音声ファイルパス, 動画タイトル)"""
    try:
        import yt_dlp
    except ImportError as exc:
        raise TranscribeError(
            "yt-dlpがインストールされていません。`uv sync`を実行してください。"
        ) from exc

    out_template = str(workdir / "%(id)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "m4a",
            "preferredquality": "128",
        }],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info.get("id", "audio")
        title = info.get("title") or url

    audio_path = workdir / f"{video_id}.m4a"
    if not audio_path.exists():
        # preferredcodecの拡張子がm4aにならない場合があるため探索する
        candidates = list(workdir.glob(f"{video_id}.*"))
        if not candidates:
            raise TranscribeError("音声ファイルの生成に失敗しました（yt-dlp/ffmpegの出力を確認してください）")
        audio_path = candidates[0]
    return audio_path, title


def _gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise TranscribeError("環境変数 GEMINI_API_KEY が設定されていません。")
    return key


def upload_to_gemini(audio_path: Path, api_key: str) -> tuple[str, str]:
    """Gemini Files APIにアップロードし、file_uriを返す（resumable upload protocol）。"""
    mime_type = mimetypes.guess_type(str(audio_path))[0] or "audio/mp4"
    size = audio_path.stat().st_size

    start_resp = requests.post(
        f"{GEMINI_BASE}/upload/v1beta/files?key={api_key}",
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": audio_path.name}},
        timeout=60,
    )
    start_resp.raise_for_status()
    upload_url = start_resp.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise TranscribeError(f"Gemini Files APIのアップロードURLが取得できませんでした: {start_resp.text[:300]}")

    with audio_path.open("rb") as f:
        data = f.read()
    upload_resp = requests.post(
        upload_url,
        headers={
            "Content-Length": str(size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
        data=data,
        timeout=300,
    )
    upload_resp.raise_for_status()
    file_info = upload_resp.json().get("file", {})
    file_uri = file_info.get("uri")
    file_name = file_info.get("name")
    if not file_uri:
        raise TranscribeError(f"Gemini Files APIのアップロードに失敗しました: {upload_resp.text[:300]}")

    # 処理状態(ACTIVE)になるまで待つ（音声ファイルは変換に少し時間がかかることがある）
    if file_name:
        for _ in range(30):
            state_resp = requests.get(f"{GEMINI_BASE}/v1beta/{file_name}?key={api_key}", timeout=30)
            state_resp.raise_for_status()
            state = state_resp.json().get("state", "")
            if state == "ACTIVE":
                break
            if state == "FAILED":
                raise TranscribeError("Gemini側での音声ファイル処理が失敗しました（FAILED）。")
            time.sleep(2)

    return file_uri, mime_type


def transcribe(file_uri: str, mime_type: str, api_key: str, model: str) -> str:
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": TRANSCRIBE_PROMPT},
                {"file_data": {"mime_type": mime_type, "file_uri": file_uri}},
            ],
        }],
        "generationConfig": {"temperature": 0.1},
    }
    resp = requests.post(
        f"{GEMINI_BASE}/v1beta/models/{model}:generateContent?key={api_key}",
        json=payload,
        timeout=300,
    )
    resp.raise_for_status()
    body = resp.json()
    try:
        return body["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as exc:
        raise TranscribeError(f"Geminiの応答から文字起こしを取り出せませんでした: {json.dumps(body)[:400]}") from exc


def post_to_local_rag(url: str, namespace: str, transcript: str, port: int, api_key: str) -> dict:
    resp = requests.post(
        f"http://localhost:{port}/api/knowledge/import/youtube",
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        json={"url": url, "namespace": namespace, "transcript": transcript},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def post_to_cloud_rag(gas_url: str, gas_api_key: str, db_key: str, video_url: str, transcript: str) -> dict:
    """GAS（gas_cloud_rag.js）のdoPost action:'admin_kb_import_youtube'に登録する。
    管理者権限のAPIキーが必要（adminKbImportYoutube同様、ナレッジ登録は管理者専用）。"""
    resp = requests.post(
        gas_url,
        json={
            "action": "admin_kb_import_youtube",
            "apiKey": gas_api_key,
            "dbKey": db_key,
            "videoUrl": video_url,
            "transcript": transcript,
        },
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "ok":
        raise TranscribeError((body.get("error") or {}).get("message") or f"Cloud RAGへの登録に失敗しました: {body}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="YouTube動画のURL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"文字起こしに使うGeminiモデル（既定: {DEFAULT_MODEL}）")
    parser.add_argument("--out", type=Path, help="文字起こし結果の保存先ファイル（省略時は標準出力のみ）")
    parser.add_argument("--local-namespace", help="指定するとLocal RAG（rag_local_bridge.py）へ自動登録する")
    parser.add_argument("--local-port", type=int, default=8766, help="rag_local_bridge.pyのポート（既定8766）")
    parser.add_argument("--local-api-key", default="", help="rag_local_bridge.pyのAPIキー（--no-authモードなら不要）")
    parser.add_argument("--cloud-url", help="Cloud RAG（gas_cloud_rag.js）のGAS WebApp URL。指定すると--cloud-dbと合わせて自動登録する")
    parser.add_argument("--cloud-api-key", help="Cloud RAGの管理者APIキー（ナレッジ登録は管理者専用）")
    parser.add_argument("--cloud-db", help="Cloud RAGの登録先dbKey（例: houdini21）")
    args = parser.parse_args()

    if args.cloud_url and not (args.cloud_api_key and args.cloud_db):
        parser.error("--cloud-urlを使う場合は--cloud-api-keyと--cloud-dbも必要です")

    try:
        api_key = _gemini_key()
        with tempfile.TemporaryDirectory(prefix="yt_transcribe_") as tmp:
            workdir = Path(tmp)
            print(f"[1/3] 音声をダウンロード中: {args.url}", file=sys.stderr)
            audio_path, title = download_audio(args.url, workdir)
            print(f"      タイトル: {title}", file=sys.stderr)

            print("[2/3] Geminiにアップロード中...", file=sys.stderr)
            file_uri, mime_type = upload_to_gemini(audio_path, api_key)

            print(f"[3/3] 文字起こし中（model={args.model}）...", file=sys.stderr)
            transcript = transcribe(file_uri, mime_type, api_key, args.model)
    except TranscribeError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except requests.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        print(f"HTTPエラー: {detail}", file=sys.stderr)
        return 1

    print(transcript)
    if args.out:
        args.out.write_text(transcript, encoding="utf-8")
        print(f"\n保存しました: {args.out}", file=sys.stderr)

    if args.local_namespace:
        print(f"\nLocal RAG（namespace={args.local_namespace}）へ登録中...", file=sys.stderr)
        try:
            result = post_to_local_rag(args.url, args.local_namespace, transcript, args.local_port, args.local_api_key)
            print(f"登録完了: {json.dumps(result, ensure_ascii=False)}", file=sys.stderr)
        except requests.RequestException as exc:
            print(f"Local RAGへの登録に失敗しました: {exc}", file=sys.stderr)
            print("rag_local_bridge.pyが起動しているか、--local-portを確認してください。", file=sys.stderr)
            return 1

    if args.cloud_url:
        print(f"\nCloud RAG（dbKey={args.cloud_db}）へ登録中...", file=sys.stderr)
        try:
            result = post_to_cloud_rag(args.cloud_url, args.cloud_api_key, args.cloud_db, args.url, transcript)
            print(f"登録完了: {json.dumps(result, ensure_ascii=False)}", file=sys.stderr)
        except (requests.RequestException, TranscribeError) as exc:
            print(f"Cloud RAGへの登録に失敗しました: {exc}", file=sys.stderr)
            return 1

    if not args.local_namespace and not args.cloud_url:
        print(
            "\n※ --local-namespaceまたは--cloud-url/--cloud-api-key/--cloud-dbを指定すると"
            "自動登録されます。省略した場合は上記の文字起こしを手動で貼り付けてください。",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
