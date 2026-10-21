"""テスター配布用の zip（RAGReelTutorial-<版>.zip）を作る。

使い方:
    uv run python scripts/build_houdini_package.py                  # 版は、日付 + git の短い名前
    uv run python scripts/build_houdini_package.py --version 1.1.0 --out dist

zip の中身（展開して install.cmd をダブルクリックすれば導入できる）:
    install.cmd / install.ps1          導入（Houdini のパッケージ登録 + 設定 + 動画エンジンの検出）。-Uninstall で削除
    python/*.py                        パネルの Python ファイル（houdini/python_panels の全部）
    houdini/python_panels/RAGReelTutorial.pypanel   パネル定義（薄い読み込み用。中身は python/ にある）
    VERSION                            版

install.ps1 は、Windows PowerShell 5.1 が日本語を正しく読めるよう、UTF-8（BOM つき）で入れる。
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANELS = ROOT / "houdini" / "python_panels"
PACKAGE = ROOT / "houdini" / "package"
BOM = b"\xef\xbb\xbf"


def default_version() -> str:
    day = datetime.date.today().strftime("%Y%m%d")
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001 -- git が無くても作れる
        rev = ""
    return f"{day}-{rev}" if rev else day


def collect_files() -> list[tuple[Path, str]]:
    """(元のファイル, zip の中のパス) の一覧。"""
    files: list[tuple[Path, str]] = []
    for path in sorted(PANELS.glob("*.py")):
        files.append((path, f"python/{path.name}"))
    files.append((PACKAGE / "RAGReelTutorial.pypanel", "houdini/python_panels/RAGReelTutorial.pypanel"))
    files.append((PACKAGE / "install.ps1", "install.ps1"))
    files.append((PACKAGE / "install.cmd", "install.cmd"))
    readme = PACKAGE / "README.txt"
    if readme.exists():
        files.append((readme, "README.txt"))
    return files


def read_for_zip(path: Path, arcname: str) -> bytes:
    data = path.read_bytes()
    if arcname == "install.ps1" and not data.startswith(BOM):
        data = BOM + data
    # 改行は CRLF にそろえる（メモ帳・cmd でも崩れない）。Python は、どちらでも読める。
    if arcname.endswith((".ps1", ".cmd", ".txt")):
        text = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        data = text
    return data


def build(version: str, out_dir: Path) -> Path:
    missing = [str(p) for p, _ in collect_files() if not p.exists()]
    if missing:
        raise FileNotFoundError("必要なファイルがありません: " + ", ".join(missing))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"RAGReelTutorial-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path, arcname in collect_files():
            z.writestr(arcname, read_for_zip(path, arcname))
        z.writestr("VERSION", f"{version}\r\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", default="", help="版（省略すると、日付 + git の短い名前）")
    parser.add_argument("--out", default="dist", help="出力フォルダ")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    target = build(args.version or default_version(), Path(args.out))
    size_kb = target.stat().st_size / 1024
    print(f"作成しました: {target}（{size_kb:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
