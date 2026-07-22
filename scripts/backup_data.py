#!/usr/bin/env python3
"""
backup_data.py — Local RAG の再生成不可能なデータのバックアップ・復元

ChromaDB インデックス（data/chroma）はソース（localRAG/）から
`rag_cli.py index` で再生成できるため対象外。バックアップ対象は
「消えたら二度と作れない」データに限定する:

  data/auth.db           … ユーザー・APIキー・アクセスログ（SQLite）
  data/knowledge/        … ナレッジ登録の履歴・定期クロール設定・アップロード控え
  logs/                  … 監査ログ（JSONL）
  localRAG/**/_imported/ … ナレッジ登録機能が生成した取り込み済みMarkdown

Usage:
    uv run python scripts/backup_data.py backup
    uv run python scripts/backup_data.py list
    uv run python scripts/backup_data.py restore --file backups/backup_20260705_120000.zip
"""

from __future__ import annotations

import argparse
import datetime
import sys
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_BACKUP_DIR = _REPO_ROOT / "backups"

# バックアップ対象（存在しなければスキップする）
_TARGET_DIRS = ["data/auth.db", "data/knowledge", "logs"]


def _collect_imported_dirs() -> list[Path]:
    """localRAG/<namespace>/_imported/ をすべて収集する（存在するnamespaceのみ）。"""
    vault = _REPO_ROOT / "localRAG"
    if not vault.exists():
        return []
    return [d for d in vault.glob("*/_imported") if d.is_dir()]


def backup() -> Path:
    _BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = _BACKUP_DIR / f"backup_{timestamp}.zip"

    targets: list[Path] = []
    for rel in _TARGET_DIRS:
        p = _REPO_ROOT / rel
        if p.exists():
            targets.append(p)
        else:
            print(f"  [スキップ] 存在しません: {rel}")
    targets.extend(_collect_imported_dirs())

    if not targets:
        print("バックアップ対象が1つも見つかりませんでした。")
        sys.exit(1)

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for target in targets:
            if target.is_file():
                zf.write(target, target.relative_to(_REPO_ROOT))
            else:
                for f in target.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(_REPO_ROOT))

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f"バックアップ完了: {archive_path}  ({size_mb:.2f} MB)")
    return archive_path


def list_backups() -> None:
    if not _BACKUP_DIR.exists():
        print("バックアップはまだありません。")
        return
    archives = sorted(_BACKUP_DIR.glob("backup_*.zip"), reverse=True)
    if not archives:
        print("バックアップはまだありません。")
        return
    for a in archives:
        size_mb = a.stat().st_size / (1024 * 1024)
        mtime = datetime.datetime.fromtimestamp(a.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {a.name}  ({size_mb:.2f} MB, 作成: {mtime})")


def restore(archive_file: str, force: bool = False) -> None:
    archive_path = Path(archive_file)
    if not archive_path.is_absolute():
        archive_path = _REPO_ROOT / archive_path
    if not archive_path.exists():
        print(f"エラー: バックアップファイルが見つかりません: {archive_path}")
        sys.exit(1)

    if not force:
        answer = input(
            f"'{archive_path.name}' を復元します。現在の data/knowledge・logs・"
            f"localRAG/**/_imported の内容は上書きされます。続行しますか？ (y/N): "
        )
        if answer.lower() != "y":
            print("キャンセルしました。")
            return

    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(_REPO_ROOT)
    print(f"復元完了: {archive_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local RAG の再生成不可能なデータのバックアップ・復元")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("backup", help="現在のデータをバックアップする")
    sub.add_parser("list", help="バックアップ一覧を表示する")

    r = sub.add_parser("restore", help="バックアップから復元する")
    r.add_argument("--file", required=True, help="復元するzipファイルのパス（backups/配下、または絶対パス）")
    r.add_argument("--force", action="store_true", help="確認プロンプトをスキップする")

    args = parser.parse_args()

    if args.cmd == "backup":
        backup()
    elif args.cmd == "list":
        list_backups()
    elif args.cmd == "restore":
        restore(args.file, force=args.force)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
