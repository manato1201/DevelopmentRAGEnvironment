#!/usr/bin/env python
"""
rag_mcp_server.py — Local RAG MCP Server（Claude Desktop 直接登録用）

Model Context Protocol (MCP) に準拠した RAG サーバー。
Claude Desktop の claude_desktop_config.json に直接登録して使う。
mcp-rag-server から独立した、このリポジトリ単体で完結する版。

Usage:
    uv run python scripts/rag_mcp_server.py

Env（.env は読み込まない。claude_desktop_config.json の "env" で渡すか
     OS の環境変数として設定すること）:
    SOURCE_DIR      インデックス化対象ディレクトリ（デフォルト: localRAG）
    PROCESSED_DIR   処理済みファイル保存先
    CHROMA_PATH     ChromaDB データ保存先
    EMBEDDING_MODEL 埋め込みモデル名
"""

import argparse
import io
import logging
import os
import sys
from pathlib import Path

# Windows のデフォルトエンコーディング(CP932)で日本語が文字化けするのを防ぐ
if hasattr(sys.stdin, "buffer"):
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
from mcp_server import MCPServer  # noqa: E402
from rag_mcp_tools import register_rag_tools  # noqa: E402
from rag_service import create_rag_service_from_env  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Local RAG MCP Server")
    parser.add_argument("--name", default="local-rag-server", help="サーバー名")
    parser.add_argument("--version", default="1.0.0", help="サーバーバージョン")
    parser.add_argument("--description", default="Local RAG MCP Server", help="サーバーの説明")
    args = parser.parse_args()

    os.makedirs("logs", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(os.path.join("logs", "rag_mcp_server.log"), encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("rag_mcp_server")

    try:
        server = MCPServer()

        logger.info("RAGサービスを初期化しています...")
        rag_service = create_rag_service_from_env()
        register_rag_tools(server, rag_service)
        logger.info("RAGツールを登録しました")

        server.start(args.name, args.version, args.description)

    except KeyboardInterrupt:
        print("サーバーを終了します。", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"エラーが発生しました: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
