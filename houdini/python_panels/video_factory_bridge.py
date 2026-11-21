"""
video_factory_bridge.py — LearningQt の動画生成エンジンをHoudini側から起動する

tutorial_view.py::_on_save がチュートリアルの .md/.json を保存した直後に呼ぶ:
  1. HoudiniToolExecutor が生成中に既に撮影済みの per-step スクリーンショット
     一覧（step_screenshots）を <slug>_screenshots.json マニフェストとして書く
  2. video_factory_cloudrag_poc.exe を --houdini-md/--houdini-json/
     --houdini-screenshots 付きで非同期起動する

起動は rag_chatbot.py の RAG local bridge 起動パターン（subprocess.Popen、
プロセスの完了は待たない）を踏襲している。Houdini のUIをブロックしないことを
優先し、動画生成の成否そのものはこのプロセスからは追跡しない（Webダッシュ
ボードに公開されるまで数分かかるため、ここで待つのはそもそも不適切）。

stdout/stderrはDEVNULLではなく <slug>_video_factory.log へ書く -- 初回の実機
テストで「音声が入っていない」不具合が報告されたが、そのときはstderrが
DEVNULLへ捨てられていて main_cloudrag.cpp 側のログ（narration synthesis
failed等）が一切見えなかった。ログをファイルに残すことで次回以降は原因が
追える。

ベストエフォート: どの段階が失敗してもチュートリアル保存自体は既に成功して
いるので、例外を外に投げず、状態表示用の短い文字列を返すだけに留める。

2026-11-17: 手順ごとの記録（<slug>_screenshots.json）に、"network_pages"（長いコードを複数枚に分けたときの 2 枚目以降の画像）と
"capture"（画像の補足情報）を足した（manifest_entries）。エンジンが読まなければ無視される。出典は、台本（--houdini-script）の
"sources" として渡る（video_script.build_script）。

2026-08-31: 戻り値に log_path を追加した。呼び出し元（tutorial_view.py）が
この後の生成進捗（video_encoder.cpp が書く "Rendered frame N / M" 行）を
ログファイルのポーリングで追跡できるようにするため。起動そのものに失敗した
場合（exe未設定・見つからない・起動エラー）は log_path=None を返す。
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from pathlib import Path


def _extra_pages(image_path: str | None) -> list[str]:
    """長いコードを複数枚に分けた画像の、2 枚目以降（<画像>_p2.png, _p3.png…）。無ければ空。
    screen_capture.extra_page_path と同じ名前（screen_capture は hou を読み込むので、ここでは再実装している）。"""
    if not image_path:
        return []
    base = Path(image_path)
    found = []
    for path in base.parent.glob(f"{glob.escape(base.stem)}_p*{glob.escape(base.suffix)}"):  # 名前に [ ] などがあっても探せる
        match = re.fullmatch(rf"{re.escape(base.stem)}_p(\d+)", path.stem)
        if match:
            found.append((int(match.group(1)), str(path)))
    return [p for _n, p in sorted(found)]


def _capture_meta(image_path: str | None) -> dict:
    """画像のとなりの <画像>.meta.json（撮影側が書いた、ノード数・文字の大きさ・コードの省略など）。無ければ空。"""
    if not image_path:
        return {}
    try:
        data = json.loads(Path(image_path + ".meta.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def manifest_entries(step_screenshots: list[dict]) -> list[dict]:
    """動画エンジンに渡す、手順ごとの記録（<slug>_screenshots.json の中身）。
    guide は案内モード用なので、渡さない。2026-11-17 に足した（エンジンが読まなければ、無視される）:
      "network_pages": 長いコードを複数枚に分けたときの、2 枚目以降の画像のパス（順番どおり）
      "capture": "network" 画像の補足情報（kind=node_diagram / code_card、nodes_shown / nodes_total、name_pt、pages など）
    2026-11-22: 手順に "network_video"（動画用に、読める大きさで描いたノード図）があれば、"network" をそれに差し替える（パラメータの画像は、そのまま）。"""
    out = []
    for s in step_screenshots:
        entry = {k: v for k, v in s.items() if k not in ("guide", "network_video")}
        # 動画には、読める大きさで描いた図（network_video）があれば、実画面（network）の代わりに渡す（2026-11-22）。
        # 実画面は、ノードが小さく、動画では名前が読めなかった。Guide・手順書は、実画面のまま。
        video_image = s.get("network_video")
        if video_image and entry.get("network_kind") != "parameter" and Path(str(video_image)).is_file():
            entry["network"] = str(video_image)
        pages = _extra_pages(entry.get("network"))
        if pages:
            entry["network_pages"] = pages
        meta = _capture_meta(entry.get("network"))
        if meta:
            entry["capture"] = meta
        out.append(entry)
    return out


def launch_video_generation(
    md_path: Path,
    json_path: Path,
    sandbox_path: str,
    step_screenshots: list[dict],
    exe_path: str,
    db_key: str = "",
    script_path: Path | None = None,
    tts_url: str = "",
    tts_key: str = "",
    extra_env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    tts_parallel: int = 4,
) -> tuple[str, Path | None]:
    """
    動画生成を非同期で起動する。戻り値は (状態メッセージ, ログファイルパス)。
    ログファイルパスは実際にプロセスを起動できた場合のみ返す（進捗ポーリング用）。
    呼び出し元の状態ラベルにそのまま表示できる短い日本語メッセージを返す。例外は投げない。

    script_path（2026-10-19追加）: video_script.py が作った初心者向けの台本（<slug>_video_script.json）。
    あれば --houdini-script で渡す。エンジンは、手順ごとの解説で音声を作り、画面と同期させる。
    無い・存在しないときは、従来どおり（チュートリアル本文の朗読）になる。

    tts_url / tts_key（2026-10-20追加）: 音声合成（Worker の /tts → Google Cloud TTS）の接続先とAPIキー。
    Settingsタブの Cloudflare URL / APIキーをそのまま渡す。あれば、VOICEVOXを入れていなくても自然な声になる
    （無い・失敗したときは、VOICEVOX、なければ従来の音声に切り替わる）。キーはコマンドラインではなく
    環境変数で渡す（プロセス一覧に出ないように）。

    extra_env（2026-10-22追加）: エンジンの環境変数に足すもの。ダッシュボード（ギャラリー）への自動アップロード用の
    GALLERY_UPLOAD_URL / GALLERY_UPLOAD_TOKEN（gallery_upload.gallery_env）を渡す。エンジンは、動画ができたあと、
    自分でギャラリーへ送る（失敗しても、ローカルの動画は無事）。

    extra_args（2026-11-19追加）: エンジンに足す引数。短縮版の動画は ["--short"]（video_short.engine_args）。
    tts_parallel（2026-11-19追加）: クラウド TTS を同時に呼ぶ数（RAGREEL_TTS_PARALLEL）。本物のクラウドで、直列 384 秒 → 4 で 96 秒（約 4 倍）、
    出力の音声は直列と同じ、429・エラーなし（RAGReel docs/technical-reference.md §28）。クラウド TTS を使うとき（tts_url と tts_key がある）だけ入れる。
    利用者が、環境変数 RAGREEL_TTS_PARALLEL を自分で決めていれば、それを優先する。
    """
    if not exe_path:
        return "動画生成: video_factory_exe_path が未設定のためスキップしました（Settingsタブで設定してください）", None
    if not Path(exe_path).exists():
        return f"動画生成: exeが見つかりません: {exe_path}", None

    screenshots_path = md_path.with_name(md_path.stem + "_screenshots.json")
    log_path = md_path.with_name(md_path.stem + "_video_factory.log")

    try:
        screenshots_path.write_text(
            json.dumps(manifest_entries(step_screenshots), ensure_ascii=False, indent=2),  # guide は案内モード用（動画エンジンには渡さない）
            encoding="utf-8",
        )
    except OSError as exc:
        return f"動画生成: スクリーンショット一覧の書き出しに失敗しました: {exc}", None

    args = [
        exe_path,
        "--houdini-md",
        str(md_path),
        "--houdini-json",
        str(json_path),
        "--houdini-screenshots",
        str(screenshots_path),
    ]
    has_script = script_path is not None and Path(script_path).exists()
    if has_script:
        args += ["--houdini-script", str(script_path)]
    if extra_args:
        args += [str(a) for a in extra_args]

    # 動画エンジンの位置引数（トピック・DBキー）。トピックはエンジン側がチュートリアルの
    # タイトルで上書きするので仮の値でよい。DBキーは動画のブランド表示（"HOUDINI22"）と
    # RAG問い合わせ先になる。未指定だとエンジンの既定値 houdini21 になり、Houdini 22の
    # チュートリアルなのに動画に「HOUDINI21」と出ていた（2026-10-04）。
    if db_key:
        args += [md_path.stem, db_key]

    # cwdを明示しない場合、Popenは呼び出し元（Houdini自身）のカレントディレクトリを
    # 継承するため、生成される.webmの出力先が実行のたびに変わりうる不定な状態だった。
    # パネル内プレビュー機能（tutorial_view.py._open_video_preview）がファイルを
    # 確実に見つけられるよう、常にexe自身のディレクトリを作業ディレクトリに固定する
    # （main_cloudrag.cppの出力パスはCWD相対のため、2026-08-31）。
    env = os.environ.copy()
    if tts_url and tts_key:
        env["RAGREEL_CLOUD_TTS_URL"] = tts_url.strip()
        env["RAGREEL_CLOUD_TTS_KEY"] = tts_key.strip()
        if tts_parallel > 1 and not env.get("RAGREEL_TTS_PARALLEL"):
            env["RAGREEL_TTS_PARALLEL"] = str(min(8, int(tts_parallel)))
    if extra_env:
        env.update(extra_env)
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            subprocess.Popen(
                args, stdout=log_file, stderr=subprocess.STDOUT, cwd=str(Path(exe_path).parent), env=env
            )
    except OSError as exc:
        return f"動画生成の起動に失敗しました: {exc}", None

    script_note = "台本つき / " if has_script else ""
    shot_count = sum(1 for s in step_screenshots if s.get("viewport") or s.get("network"))
    if shot_count:
        status = (
            f"動画生成をバックグラウンドで開始しました（{script_note}スクリーンショット{shot_count}件 / "
            f"ログ: {log_path.name}）"
        )
    else:
        status = (
            f"動画生成をバックグラウンドで開始しました（{script_note}スクリーンショットなし。"
            f"ログ: {log_path.name}）"
        )
    return status, log_path
