"""Houdini の画面（GUI）を起動して、Reference のノード図を、実際のネットワークエディタで撮る（2026-11-28）。

  uv run python scripts/reference_capture/run_gui_network_shots.py [--only sop/vellumsolver,sop/boolean] [--keep-open]

一時のフォルダに起動時のスクリプト（scripts/123.py）を置き、HOUDINI_PATH の先頭に足して、Houdini を起動する
（この起動のときだけ。ふだんの設定は変えない）。123.py は、画面ができてから gui_network_shots.run() を呼び、終わると Houdini を閉じる。
撮影のあいだ、Houdini の画面が前面に出る（ネットワークエディタを、画面から切り出すため。ほかのウィンドウを上に重ねない）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HOUDINI = Path(r"C:\Program Files\Side Effects Software\Houdini 22.0.506\bin\houdini.exe")

STARTUP = '''import sys
sys.path.insert(0, r"{here}")
from PySide6.QtCore import QTimer


def _start():
    import gui_network_shots
    gui_network_shots.run()


QTimer.singleShot(6000, _start)  # 画面（ペインの配置）ができるのを待ってから撮る
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="", help="撮るキー（カンマ区切り）。省略すると、条件のある全部")
    parser.add_argument("--keep-open", action="store_true", help="撮り終えても Houdini を閉じない（確かめる用）")
    parser.add_argument("--out", default="", help="保存先（省略すると build/reference_media。<種類>/<キー>/node.png）")
    parser.add_argument("--timeout", type=int, default=3600, help="待つ秒数の上限")
    args = parser.parse_args(argv)
    if not HOUDINI.exists():
        print(f"Houdini が見つかりません: {HOUDINI}")
        return 1
    log = ROOT / "build" / "gui_network_shots.log"
    with tempfile.TemporaryDirectory() as tmp:
        scripts = Path(tmp) / "scripts"
        scripts.mkdir()
        (scripts / "123.py").write_text(STARTUP.format(here=str(HERE)), encoding="utf-8")
        env = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            env.pop(key, None)
        env["HOUDINI_PATH"] = Path(tmp).as_posix() + ";&"
        env["HOME"] = str(Path.home() / "Documents")  # Git Bash などの HOME では、別の設定フォルダを見てしまう
        env["REF_GUI_ONLY"] = args.only
        if args.out:
            env["REF_GUI_OUT"] = str(Path(args.out).resolve())
        if args.keep_open:
            env["REF_GUI_KEEP_OPEN"] = "1"
        started = time.time()
        proc = subprocess.Popen([str(HOUDINI)], env=env)
        try:
            proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            print("時間内に終わりませんでした（Houdini は開いたままです）")
            return 1
        print(f"Houdini が閉じました（{time.time() - started:.0f} 秒）")
    if log.exists():
        lines = log.read_text(encoding="utf-8").splitlines()
        bad = [ln for ln in lines if ln.split(" ", 2)[1:2] in (["NG"], ["FATAL"])]
        print("\n".join(bad[:30]))
        print(lines[-1] if lines else "（記録が空です）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
