"""
deploy_panels.py — 開発機の Houdini に、リポジトリを直接読む「開発用のパッケージ」を登録する（2026-11-26）

以前は houdini/python_panels/ を Documents/houdini<版>/python_panels/ へコピーしていた。コピーし忘れると
古いまま動く（2026-09-26、約12日分の修正が届いていなかった）。今は Documents/houdini<版>/packages/
ragreel_tutorial.json がリポジトリを指すので、リポジトリを直したら Houdini を再起動するだけで反映される。
配布版（houdini/package/install.ps1）と同じ仕組み（Houdini のパッケージ）で、同じ名前のファイルを使う
（配布版と開発用は、どちらか一方だけが登録される）。

  uv run python houdini/deploy_panels.py 22.0            # 登録。Documents/houdini22.0 が無ければ作る。古いコピーは退避する
  uv run python houdini/deploy_panels.py 21.0 22.0       # 複数の版
  uv run python houdini/deploy_panels.py 22.0 --check    # 何も書かず、状態だけ表示
  uv run python houdini/deploy_panels.py 22.0 --remove   # 開発用の登録を外す（配布版を試す前など。そのあと install.cmd）

登録・変更のあとは Houdini を再起動すること（起動中はモジュールがキャッシュされたまま）。
パネルは「RAGReel Tutorial」（配布版と同じ定義 houdini/package/houdini/python_panels/RAGReelTutorial.pypanel）。
以前のコピー方式の「RAGChatBot」パネルは、退避したので出なくなる。
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

HOUDINI_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOUDINI_DIR.parent
REPO = HOUDINI_DIR / "python_panels"
PACKAGE_HOUDINI = HOUDINI_DIR / "package" / "houdini"  # python_panels/RAGReelTutorial.pypanel と toolbar/ragreel_tutorial.shelf
PACKAGE_FILE = "ragreel_tutorial.json"
DEV_ENV = "RAGREEL_TUTORIAL_DEV"
# パネルのモジュール（配布 zip の中身とずれていないことを、test_package が確かめる）。新しい .py を足したら、ここにも足す。
MODULES = [
    "doc_tools", "display_isolation", "tutorial_followup", "panel_thinking", "video_short", "reference_data", "reference_author", "reference_remote", "reference_view", "guide_view", "guide_mode", "guide_shortcuts", "trial_pruning", "houdini_tools", "screen_capture", "token_usage", "tutorial_agent",
    "tutorial_feedback", "tutorial_graph_simplify", "tutorial_view", "video_factory_bridge",
    "video_script", "lesson_design", "tutorial_review", "graph_diagram", "video_progress", "rag_client", "gallery_upload", "panel_info", "panel_widgets", "panel_actions", "panel_debug", "panel_paths", "panel_nav", "panel_bus", "node_links", "node_link_data", "report_dialog", "pilot_task", "pilot_panel", "chat_figures", "question_hints", "tool_analogies", "basics_guide", "houdini_terms", "panel_motion",
]
# 退避の対象のうち、MODULES に無いもの（パネル本体と、以前のコピー方式で置いていて今はリポジトリに無いモジュール）
LEGACY_MODULES = ["rag_chatbot", "graph_view", "docs_view"]


def package_json(repo_root: Path = REPO_ROOT) -> dict:
    """開発用のパッケージ定義。モジュールはリポジトリの houdini/python_panels を、パネル定義とシェルフは houdini/package/houdini を読む。"""
    return {
        "enable": True,
        "env": [
            {DEV_ENV: repo_root.as_posix()},
            {"PYTHONPATH": {"method": "append", "value": f"${DEV_ENV}/houdini/python_panels"}},
        ],
        "path": f"${DEV_ENV}/houdini/package/houdini",
    }


def _read_package(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def describe_package(path: Path) -> str:
    if not path.exists():
        return "未登録"
    data = _read_package(path)
    if data is None:
        return "読めない（壊れている）"
    env = {k: v for item in data.get("env", []) if isinstance(item, dict) for k, v in item.items()}
    if DEV_ENV in env:
        return f"開発用（{env[DEV_ENV]}）"
    if "RAGREEL_TUTORIAL_HOME" in env:
        return f"配布版（{env['RAGREEL_TUTORIAL_HOME']}）"
    return "別の内容"


def _is_our_pypanel(path: Path) -> bool:
    """以前のコピー方式の default.pypanel（RAGChatBot だけを定義）か。ほかのパネルも入っていたら、触らない。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return text.count("<interface ") == 1 and 'name="RAGChatBot"' in text


def legacy_copies(house: Path) -> list[Path]:
    """以前のコピー方式で置いたファイル。残すと、古いモジュールが先に読み込まれることがある。"""
    found: list[Path] = []
    panels = house / "python_panels"
    if panels.is_dir():
        names = set(MODULES) | set(LEGACY_MODULES)
        found += [p for p in sorted(panels.glob("*.py")) if p.stem in names]
        if (panels / "__pycache__").is_dir():
            found.append(panels / "__pycache__")
        if (panels / "default.pypanel").exists() and _is_our_pypanel(panels / "default.pypanel"):
            found.append(panels / "default.pypanel")
    shelf = house / "toolbar" / "ragreel_tutorial.shelf"  # パッケージの path から読むので、コピーは二重になる
    if shelf.exists():
        found.append(shelf)
    return found


def register(house: Path, repo_root: Path = REPO_ROOT, stamp: str | None = None) -> list[str]:
    """1 つの版に登録する。行ったことを、行ごとに返す。"""
    done: list[str] = []
    if not house.exists():
        house.mkdir(parents=True)
        done.append(f"{house} が無かったので作りました（その版の Houdini を、まだ起動していない）")
    pkg = house / "packages" / PACKAGE_FILE
    before = describe_package(pkg)
    if before.startswith("配布版"):
        done.append(f"配布版の登録を、開発用に置き換えます（元: {before}。戻すときは --remove のあと install.cmd）")
    pkg.parent.mkdir(exist_ok=True)
    pkg.write_text(json.dumps(package_json(repo_root), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    done.append(f"登録しました: {pkg} → {repo_root.as_posix()}")
    old = legacy_copies(house)
    if old:
        backup = house / f"python_panels_backup_{stamp or datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup.mkdir(exist_ok=True)
        for path in old:
            target = backup / (path.name if path.parent.name != "toolbar" else f"toolbar_{path.name}")
            shutil.move(str(path), str(target))
        done.append(f"以前のコピー {len(old)} 件を退避しました: {backup}")
    return done


def remove(house: Path) -> list[str]:
    pkg = house / "packages" / PACKAGE_FILE
    state = describe_package(pkg)
    if not state.startswith("開発用"):
        return [f"{house.name}: 開発用の登録はありません（{state}）。何もしません"]
    pkg.unlink()
    return [f"{house.name}: 開発用の登録を外しました（{pkg}）"]


def check(house: Path) -> list[str]:
    lines = [f"{house.name}: " + ("フォルダなし" if not house.exists() else describe_package(house / "packages" / PACKAGE_FILE))]
    old = legacy_copies(house) if house.exists() else []
    if old:
        lines.append(f"  以前のコピーが {len(old)} 件残っています（登録すると退避します）: " + ", ".join(p.name for p in old[:8])
                     + (" ..." if len(old) > 8 else ""))
    missing = [p for p in (PACKAGE_HOUDINI / "python_panels" / "RAGReelTutorial.pypanel", REPO / "rag_chatbot.py") if not p.exists()]
    for p in missing:
        lines.append(f"  リポジトリに {p} がありません")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("versions", nargs="+", help="Houdini の版（例: 22.0。21.0 22.0 のように複数も可）")
    parser.add_argument("--check", action="store_true", help="状態の表示だけ（何も書き込まない）")
    parser.add_argument("--remove", action="store_true", help="開発用の登録を外す")
    parser.add_argument("--documents", default=str(Path.home() / "Documents"), help="Houdini の設定フォルダがある場所")
    parser.add_argument("--pypanel", action="store_true", help=argparse.SUPPRESS)  # 以前の方式の名残。今は不要（受け取って無視する）
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    docs = Path(args.documents)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for version in args.versions:
        house = docs / f"houdini{version.removeprefix('houdini')}"
        if args.check:
            lines = check(house)
        elif args.remove:
            lines = remove(house)
        else:
            lines = register(house, stamp=stamp)
        for line in lines:
            print(line)
    if not args.check:
        print("Houdini を再起動してください（起動中はモジュールがキャッシュされています）。")
        if args.pypanel:
            print("（--pypanel は不要になりました。パネル定義もリポジトリから読みます）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
