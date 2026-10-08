"""
deploy_panels.py — houdini/python_panels/ を Houdini のユーザー設定フォルダへ配置する

Houdini は Documents/houdini<バージョン>/python_panels/ のコピーを読み込む。リポジトリを
直しても手動コピーしない限り実機に反映されないため（2026-09-26、約12日間の修正が届いて
いなかったことが判明）、配置を1コマンドにする。

  python houdini/deploy_panels.py 22.0            # モジュールだけ配置（上書き前に自動バックアップ）
  python houdini/deploy_panels.py 22.0 --pypanel  # default.pypanel（パネル定義）も作り直す
  python houdini/deploy_panels.py 21.0 --check    # 何も書かず、リポジトリと配置済みの差分だけ表示

配置後は Houdini を再起動すること（起動中はモジュールがキャッシュされたまま）。
--pypanel は rag_chatbot.py（パネル本体）をパネル定義へ埋め込み直す。既存の default.pypanel は
バックアップしてから置き換える。
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent / "python_panels"
MODULES = [
    "graph_view", "houdini_tools", "screen_capture", "token_usage", "tutorial_agent",
    "tutorial_feedback", "tutorial_graph_simplify", "tutorial_view", "video_factory_bridge",
]
_CDATA_OPEN = "<script><![CDATA["
_CDATA_CLOSE = "]]></script>"
_PYPANEL_SKELETON = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<pythonPanelDocument>\n'
    '  <interface name="RAGChatBot" label="RAGChatBot" icon="MISC_python" '
    'showNetworkNavigationBar="false" help_url="">\n    ' + _CDATA_OPEN + "\n{script}\n" + _CDATA_CLOSE + "\n"
    '    <includeInToolbarMenu menu_position="209" create_separator="false"/>\n'
    '    <help><![CDATA[]]></help>\n  </interface>\n</pythonPanelDocument>\n'
)


def _same(a: Path, b: Path) -> bool:
    return b.exists() and a.read_bytes().replace(b"\r\n", b"\n") == b.read_bytes().replace(b"\r\n", b"\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", help="Houdiniのバージョン（例: 21.0 / 22.0）")
    parser.add_argument("--pypanel", action="store_true", help="default.pypanel も作り直す")
    parser.add_argument("--check", action="store_true", help="差分の表示だけ（何も書き込まない）")
    args = parser.parse_args()

    house = Path.home() / "Documents" / f"houdini{args.version}"
    if not house.exists():
        print(f"{house} がありません。そのバージョンのHoudiniを一度起動してから実行してください。", file=sys.stderr)
        return 1
    dst = house / "python_panels"
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = house / f"python_panels_backup_{stamp}"

    changed = [m for m in MODULES if not _same(REPO / f"{m}.py", dst / f"{m}.py")]
    for m in MODULES:
        print(f"{'DIFF' if m in changed else 'same'}  {m}.py")
    if args.check:
        return 0

    dst.mkdir(parents=True, exist_ok=True)
    for m in changed:
        target = dst / f"{m}.py"
        if target.exists():
            backup.mkdir(exist_ok=True)
            shutil.copy2(target, backup / target.name)
        shutil.copyfile(REPO / f"{m}.py", target)
    print(f"{len(changed)} 件を配置しました" + (f"（元のファイルは {backup} に退避）" if backup.exists() else ""))

    if args.pypanel:
        script = (REPO / "rag_chatbot.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        if "]]>" in script:
            print("rag_chatbot.py に ']]>' が含まれておりCDATAに埋め込めません", file=sys.stderr)
            return 1
        target = dst / "default.pypanel"
        if target.exists():
            backup.mkdir(exist_ok=True)
            shutil.copy2(target, backup / target.name)
        # .pypanel のCDATAは「スクリプトのUTF-8バイト列を1バイト=1文字（Latin-1）として読み替えた文字列」
        # をUTF-8のXMLとして保存する形式（Houdini自身が保存したファイルがこの形）。日本語や「§」を
        # そのまま書くと、Houdini 22で "SyntaxError: (unicode error) 'utf-8' codec can't decode byte
        # 0xa7" になる（2026-09-27に実機で発生・hythonで再現）。
        embedded = script.encode("utf-8").decode("latin-1")
        target.write_text(_PYPANEL_SKELETON.format(script=embedded), encoding="utf-8", newline="\n")
        print("default.pypanel を作り直しました")
    print("Houdini を再起動してください（起動中はモジュールがキャッシュされています）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
