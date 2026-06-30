"""
rag_mcp_tools.py — RAG ツールモジュール（MCP 用）

MCPサーバー（mcp_server.py）に登録する search / get_document_count ツール。
mcp-rag-server から独立させた版（rag_service.py を直接 import）。
"""

import os
from typing import Any, Dict

from rag_service import RAGService, create_rag_service_from_env


def register_rag_tools(server, rag_service: RAGService):
    server.register_tool(
        name="search",
        description="ベクトル検索を行います",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ"},
                "limit": {"type": "integer", "description": "返す結果の数（デフォルト: 5）", "default": 5},
                "with_context": {"type": "boolean", "description": "前後のチャンクも取得するかどうか（デフォルト: true）", "default": True},
                "context_size": {"type": "integer", "description": "前後に取得するチャンク数（デフォルト: 1）", "default": 1},
                "full_document": {"type": "boolean", "description": "ドキュメント全体を取得するかどうか（デフォルト: false）", "default": False},
            },
            "required": ["query"],
        },
        handler=lambda params: search_handler(params, rag_service),
    )

    server.register_tool(
        name="get_document_count",
        description="インデックス内のドキュメント数を取得します",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=lambda params: get_document_count_handler(params, rag_service),
    )


def search_handler(params: Dict[str, Any], rag_service: RAGService) -> Dict[str, Any]:
    query = params.get("query")
    limit = params.get("limit", 5)
    with_context = params.get("with_context", True)
    context_size = params.get("context_size", 1)
    full_document = params.get("full_document", False)

    if not query:
        return {"content": [{"type": "text", "text": "エラー: 検索クエリが指定されていません"}], "isError": True}

    try:
        doc_count = rag_service.get_document_count()
        if doc_count == 0:
            return {
                "content": [{
                    "type": "text",
                    "text": "インデックスにドキュメントが存在しません。CLIコマンド "
                            "`uv run python scripts/rag_cli.py index` を使用してドキュメントをインデックス化してください。",
                }],
                "isError": True,
            }

        results = rag_service.search(query, limit, with_context, context_size, full_document)

        if not results:
            return {"content": [{"type": "text", "text": f"クエリ '{query}' に一致する結果が見つかりませんでした"}]}

        file_groups: dict = {}
        for result in results:
            file_groups.setdefault(result["file_path"], []).append(result)
        for fp in file_groups:
            file_groups[fp].sort(key=lambda x: x["chunk_index"])

        content_items = [{"type": "text", "text": f"クエリ '{query}' の検索結果（{len(results)} 件）:"}]

        for i, (file_path, group) in enumerate(file_groups.items()):
            file_name = os.path.basename(file_path)
            content_items.append({"type": "text", "text": f"\n[{i + 1}] ファイル: {file_name}"})

            for result in group:
                similarity_percent = result.get("similarity", 0) * 100
                is_context = result.get("is_context", False)
                is_full_document = result.get("is_full_document", False)

                if is_full_document:
                    text = f"\n+++ ドキュメント全文（チャンク {result['chunk_index']}) +++\n{result['content']}"
                elif is_context:
                    text = f"\n--- 前後のコンテキスト（チャンク {result['chunk_index']}) ---\n{result['content']}"
                else:
                    text = f"\n=== 検索ヒット（チャンク {result['chunk_index']}, 類似度: {similarity_percent:.2f}%) ===\n{result['content']}"
                content_items.append({"type": "text", "text": text})

        return {"content": content_items}

    except Exception as e:
        return {"content": [{"type": "text", "text": f"検索中にエラーが発生しました: {str(e)}"}], "isError": True}


def get_document_count_handler(params: Dict[str, Any], rag_service: RAGService) -> Dict[str, Any]:
    try:
        count = rag_service.get_document_count()
        return {"content": [{"type": "text", "text": f"インデックス内のドキュメント数: {count}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"ドキュメント数の取得中にエラーが発生しました: {str(e)}"}], "isError": True}
