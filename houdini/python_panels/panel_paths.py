"""
panel_paths.py — 生成物の保存先（設定の local_bridge_dir）の決め方（Qt・Houdini に依存しない純粋な関数。単体テストできる）

背景（2026-11-17の実証実験）:
  参加者の PC で、チュートリアルを「保存」すると「Bridge Directory（DevelopmentRAGEnvironment のパス）を設定してください」
  と出て、保存できなかった。設定する場所（設定タブ）は、一般の利用者には出ない画面で、しかも文面は開発者向けだった。
  そこで、保存先が未設定のときは、パネルが自分で既定の場所（ドキュメント\\RAGReelTutorial）を使う。

  ・default_data_dir()   … 既定の保存先（install.ps1 の -DataDir の既定と同じ場所）
  ・is_blank(value)      … 空・空白だけ・null は「未設定」
  ・resolve_data_dir(cfg) … 設定を見て、使う保存先を決める（未設定なら既定の場所を作る）。結果は dict
  ・choose_to_save(...)  … 設定ファイルへ書くとき、ほかのパネル・インストーラーが入れた値を、古い空の値で消さない
  ・STORAGE_HELP / SAVE_DIR_MISSING … 利用者向けの案内の文（開発者向けの言葉は使わない）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER = "RAGReelTutorial"

STORAGE_HELP = (
    "チュートリアルの保存先フォルダを用意できませんでした。"
    "右上のメニュー（≡）の「接続・アカウント」の「保存先フォルダ」に、書き込める場所（例: ドキュメント内のフォルダ）を入力して保存してください。"
)

# 保存先が使えないとき、画面の状態欄・案内に出す短い文（チュートリアルの保存・一覧・案内の画面で共通）
SAVE_DIR_MISSING = "保存先のフォルダを用意できません。右上のメニュー（≡）の「接続・アカウント」で、「保存先フォルダ」を入力してください"


def documents_dir() -> Path:
    """「ドキュメント」フォルダ。OneDrive で移されていても、Windows が指す場所を使う（install.ps1 の GetFolderPath と同じ）。"""
    if sys.platform == "win32":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(260)
            # CSIDL_PERSONAL = 5（ドキュメント）, SHGFP_TYPE_CURRENT = 0
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0 and buffer.value:
                return Path(buffer.value)
        except Exception:  # noqa: BLE001 -- 取れなければ、下の代わりの場所
            pass
    return Path(os.path.expanduser("~")) / "Documents"


def default_data_dir() -> Path:
    return documents_dir() / APP_FOLDER


def is_blank(value) -> bool:
    """未設定か。None・空文字・空白だけ・文字以外（数値など）は、未設定とみなす。"""
    return not isinstance(value, str) or not value.strip()


def resolve_data_dir(cfg: dict, default: Path | None = None) -> dict:
    """使う保存先を決める。

    戻り値: {"path": 使う場所（文字列。使えないときは ""）, "source": "config" | "default" | "none",
             "created": 新しく作ったか, "error": 失敗の理由（無ければ ""）}
      ・設定に値がある: そのまま使う（source=config）。フォルダは作らない（別の PC のパスでも、勝手に作らない）。
      ・未設定: 既定の場所を作って使う（source=default）。作れなければ source=none（呼び出し側が、案内を出す）。
      ・Local モード（開発者）: 未設定でも、既定の場所は使わない。ここはブリッジのあるプロジェクトの場所を指すため。
    """
    value = cfg.get("local_bridge_dir")
    if not is_blank(value):
        return {"path": value.strip(), "source": "config", "created": False, "error": ""}
    if cfg.get("mode") == "local":
        return {"path": "", "source": "none", "created": False, "error": "Local モードでは、保存先（ブリッジのあるフォルダ）を入力してください。"}
    target = default if default is not None else default_data_dir()
    try:
        existed = target.is_dir()
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return {"path": "", "source": "none", "created": False, "error": f"{target} を使えません（{exc.__class__.__name__}）"}
    return {"path": str(target), "source": "default", "created": not existed, "error": ""}


def apply_default_data_dir(cfg: dict, default: Path | None = None) -> dict:
    """cfg の local_bridge_dir が未設定なら、既定の保存先を入れる（cfg を直接書き換える）。resolve_data_dir の結果を返す。"""
    result = resolve_data_dir(cfg, default)
    if result["source"] == "default":
        cfg["local_bridge_dir"] = result["path"]
    elif is_blank(cfg.get("local_bridge_dir")):
        cfg["local_bridge_dir"] = ""  # 空白だけの値は、空にそろえる
    return result


def choose_to_save(in_memory, on_disk, default: Path | None = None):
    """設定ファイルに書くときの local_bridge_dir を決める。

    パネルを開いたまま install.cmd を実行（更新）すると、パネルの手元の設定は古いままで、保存すると、
    インストーラーが入れた保存先を、空・既定のままの値で消してしまう。そこで、手元の値が「空」か「自動で入れた既定の値」で、
    ファイルに別の値があれば、ファイルの値を残す。利用者が画面で入力して変えた値は、そのまま書く。
    """
    auto = str(default if default is not None else default_data_dir())
    mine = in_memory.strip() if isinstance(in_memory, str) else ""
    theirs = on_disk.strip() if isinstance(on_disk, str) else ""
    if (not mine or _same_path(mine, auto)) and theirs:
        return theirs
    return mine


def _same_path(a: str, b: str) -> bool:
    norm = lambda s: os.path.normcase(os.path.normpath(s))  # noqa: E731
    return norm(a) == norm(b)
