#!/usr/bin/env python
"""
rag_cli.py — Local RAG CLI（mcp-rag-server から独立した版）

インデックスのクリア・インデックス化・件数確認を行うコマンドラインインターフェース。

Usage:
    uv run python scripts/rag_cli.py index [--directory PATH] [--incremental]
    uv run python scripts/rag_cli.py clear
    uv run python scripts/rag_cli.py count

Env:
    SOURCE_DIR     インデックス化対象ディレクトリ（デフォルト: localRAG）
    PROCESSED_DIR  処理済みファイル保存先
    CHROMA_PATH    ChromaDB データ保存先
    EMBEDDING_MODEL 埋め込みモデル名
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rag_service import create_rag_service_from_env  # noqa: E402

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_SOURCE_DIR = str(_REPO_ROOT / "localRAG")
_DEFAULT_PROCESSED_DIR = str(_REPO_ROOT / "localRAG" / "_rag_dashboard" / ".processed")


def setup_logging() -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join("logs", "rag_cli.log"), encoding="utf-8"),
        ],
    )
    return logging.getLogger("rag_cli")


def clear_index() -> None:
    logger = setup_logging()
    logger.info("インデックスをクリアしています...")

    rag_service = create_rag_service_from_env()
    processed_dir = os.environ.get("PROCESSED_DIR", _DEFAULT_PROCESSED_DIR)

    registry_path = Path(processed_dir) / "file_registry.json"
    if registry_path.exists():
        registry_path.unlink()
        print(f"ファイルレジストリを削除しました: {registry_path}")

    result = rag_service.clear_index()
    if result["success"]:
        print(f"インデックスをクリアしました（{result['deleted_count']} ドキュメントを削除）")
    else:
        print(f"インデックスのクリアに失敗しました: {result.get('error', '不明なエラー')}")
        sys.exit(1)


def index_documents(directory_path: str, chunk_size: int, chunk_overlap: int, incremental: bool) -> None:
    logger = setup_logging()
    action = "差分ファイルを" if incremental else "ファイルを"
    logger.info(f"ディレクトリ '{directory_path}' 内の{action}インデックス化しています...")

    if not os.path.isdir(directory_path):
        print(f"エラー: '{directory_path}' はディレクトリではありません、または見つかりません")
        sys.exit(1)

    rag_service = create_rag_service_from_env()
    processed_dir = os.environ.get("PROCESSED_DIR", _DEFAULT_PROCESSED_DIR)

    print(f"ディレクトリ '{directory_path}' 内の{action}インデックス化しています...")
    result = rag_service.index_documents(directory_path, processed_dir, chunk_size, chunk_overlap, incremental)

    if result["success"]:
        print(
            f"インデックス化が完了しました\n"
            f"- ドキュメント数: {result['document_count']}\n"
            f"- 処理時間: {result['processing_time']:.2f} 秒\n"
            f"- メッセージ: {result.get('message', '')}"
        )
    else:
        print(f"インデックス化に失敗しました\n- エラー: {result.get('error', '不明なエラー')}")
        sys.exit(1)


def get_document_count() -> None:
    setup_logging()
    rag_service = create_rag_service_from_env()
    try:
        count = rag_service.get_document_count()
        print(f"インデックス内のドキュメント数: {count}")
    except Exception as e:
        print(f"ドキュメント数の取得中にエラーが発生しました: {str(e)}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local RAG CLI - インデックスのクリア・インデックス化・件数確認")
    subparsers = parser.add_subparsers(dest="command", help="実行するコマンド")

    subparsers.add_parser("clear", help="インデックスをクリアする")

    index_parser = subparsers.add_parser("index", help="ドキュメントをインデックス化する")
    index_parser.add_argument(
        "--directory", "-d", default=os.environ.get("SOURCE_DIR", _DEFAULT_SOURCE_DIR),
        help="インデックス化するドキュメントが含まれるディレクトリのパス",
    )
    index_parser.add_argument("--chunk-size", "-s", type=int, default=500, help="チャンクサイズ（文字数）")
    index_parser.add_argument("--chunk-overlap", "-o", type=int, default=100, help="チャンク間のオーバーラップ（文字数）")
    index_parser.add_argument("--incremental", "-i", action="store_true", help="差分のみをインデックス化する")

    subparsers.add_parser("count", help="インデックス内のドキュメント数を取得する")

    args = parser.parse_args()

    if args.command == "clear":
        clear_index()
    elif args.command == "index":
        index_documents(args.directory, args.chunk_size, args.chunk_overlap, args.incremental)
    elif args.command == "count":
        get_document_count()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
