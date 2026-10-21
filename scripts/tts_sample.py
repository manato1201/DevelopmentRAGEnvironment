"""音声の聞き比べ用サンプルを作る（Worker の POST /tts を呼ぶ）。

使い方（PowerShell。鍵は環境変数で渡し、コマンドやログに残さない）:
    $env:CF_URL = "https://rag-poc.xxxx.workers.dev"
    $env:CF_API_KEY = "（管理タブで発行したAPIキー）"
    uv run python scripts/tts_sample.py

`tts_samples/` に、声ごとの WAV を書く。同じ文章を、複数の声で読ませて聞き比べる。
消費する文字数は、1声あたり約 120 文字（鍵ごとの1日の上限から引かれる）。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

VOICES = [
    "ja-JP-Neural2-B",  # 女性
    "ja-JP-Neural2-C",  # 男性
    "ja-JP-Neural2-D",  # 男性
    "ja-JP-Chirp3-HD-Aoede",
    "ja-JP-Chirp3-HD-Kore",
    "ja-JP-Chirp3-HD-Charon",
]

TEXT = (
    "この動画では、スキャッターで点を散らして、その点に岩を置く方法を説明します。"
    "スキャッターは、面の上にランダムに点を置くノードです。種をまく作業に似ています。"
    "ここで、点が百個ほど見えれば正しいです。"
)


def main() -> int:
    url = os.environ.get("CF_URL", "").rstrip("/")
    key = os.environ.get("CF_API_KEY", "")
    if not url or not key:
        print("CF_URL と CF_API_KEY を環境変数に設定してください", file=sys.stderr)
        return 2
    out_dir = Path("tts_samples")
    out_dir.mkdir(exist_ok=True)
    failed = 0
    for voice in VOICES:
        body = json.dumps({"text": TEXT, "voice": voice}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/tts", data=body, method="POST",
            # urllib 標準の User-Agent は、Cloudflare に弾かれる（error code: 1010）。
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "User-Agent": "RAGReel-tts-sample/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                audio = res.read()
                used = res.headers.get("x-tts-chars-used-today", "?")
                limit = res.headers.get("x-tts-chars-limit", "?")
                cache = res.headers.get("x-tts-cache", "?")
        except urllib.error.HTTPError as exc:
            print(f"NG  {voice}: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:160]}")
            failed += 1
            continue
        except OSError as exc:
            print(f"NG  {voice}: {exc}")
            failed += 1
            continue
        path = out_dir / f"{voice}.wav"
        path.write_bytes(audio)
        print(f"OK  {voice}: {len(audio) / 1024:.0f} KB  cache={cache}  今日の使用 {used}/{limit} 文字  -> {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
