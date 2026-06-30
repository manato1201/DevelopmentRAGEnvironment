"""
rag_service.py — RAG サービスモジュール

ドキュメント処理・エンベディング生成・ベクトルデータベースを統合して、
インデックス化と検索の機能を提供する。mcp-rag-server から独立させた版
（document_processor.py / embedding_generator.py / vector_database.py を
 このリポジトリ内で直接 import する）。
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from document_processor import DocumentProcessor
from embedding_generator import EmbeddingGenerator
from vector_database import VectorDatabase


class RAGService:
    """
    RAG サービスクラス

    Attributes:
        document_processor: ドキュメント処理クラスのインスタンス
        embedding_generator: エンベディング生成クラスのインスタンス
        vector_database: ベクトルデータベースクラスのインスタンス
        logger: ロガー
    """

    def __init__(
        self, document_processor: DocumentProcessor, embedding_generator: EmbeddingGenerator, vector_database: VectorDatabase
    ):
        self.logger = logging.getLogger("rag_service")
        self.logger.setLevel(logging.INFO)

        self.document_processor = document_processor
        self.embedding_generator = embedding_generator
        self.vector_database = vector_database

        try:
            self.vector_database.initialize_database()
        except Exception as e:
            self.logger.error(f"データベースの初期化に失敗しました: {str(e)}")
            raise

    def index_documents(
        self,
        source_dir: str,
        processed_dir: str = None,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
        incremental: bool = False,
    ) -> Dict[str, Any]:
        start_time = time.time()
        document_count = 0

        if processed_dir is None:
            processed_dir = "data/processed"

        try:
            if incremental:
                self.logger.info(f"ディレクトリ '{source_dir}' 内の差分ファイルをインデックス化しています...")
            else:
                self.logger.info(f"ディレクトリ '{source_dir}' 内のファイルをインデックス化しています...")

            chunks = self.document_processor.process_directory(
                source_dir, processed_dir, chunk_size, chunk_overlap, incremental
            )

            if not chunks:
                self.logger.warning(f"ディレクトリ '{source_dir}' 内に処理可能なファイルが見つかりませんでした")
                return {
                    "document_count": 0,
                    "processing_time": time.time() - start_time,
                    "success": True,
                    "message": f"ディレクトリ '{source_dir}' 内に処理可能なファイルが見つかりませんでした",
                }

            self.logger.info(f"{len(chunks)} チャンクのエンベディングを生成しています...")
            texts = [chunk["content"] for chunk in chunks]
            embeddings = self.embedding_generator.generate_embeddings(texts)

            self.logger.info(f"{len(chunks)} チャンクをデータベースに挿入しています...")
            documents = []
            for i, chunk in enumerate(chunks):
                documents.append(
                    {
                        "document_id": chunk["document_id"],
                        "content": chunk["content"],
                        "file_path": chunk["file_path"],
                        "chunk_index": chunk["chunk_index"],
                        "embedding": embeddings[i],
                        "metadata": {
                            "file_name": os.path.basename(chunk["file_path"]),
                            "directory": os.path.dirname(chunk["file_path"]),
                            "original_file_path": chunk.get("original_file_path", ""),
                            "directory_suffix": chunk.get("metadata", {}).get("directory_suffix", ""),
                        },
                    }
                )

            self.vector_database.batch_insert_documents(documents)
            document_count = len(documents)

            processing_time = time.time() - start_time
            self.logger.info(f"インデックス化が完了しました（{document_count} ドキュメント、{processing_time:.2f} 秒）")

            return {
                "document_count": document_count,
                "processing_time": processing_time,
                "success": True,
                "message": f"{document_count} ドキュメントをインデックス化しました",
            }

        except Exception as e:
            processing_time = time.time() - start_time
            self.logger.error(f"インデックス化中にエラーが発生しました: {str(e)}")
            return {"document_count": document_count, "processing_time": processing_time, "success": False, "error": str(e)}

    def search(
        self, query: str, limit: int = 5, with_context: bool = False, context_size: int = 1, full_document: bool = False
    ) -> List[Dict[str, Any]]:
        try:
            self.logger.info(f"クエリ '{query}' のエンベディングを生成しています...")
            query_embedding = self.embedding_generator.generate_search_embedding(query)

            self.logger.info(f"クエリ '{query}' でベクトル検索を実行しています...")
            results = self.vector_database.search(query_embedding, limit, query_text=query)

            if with_context and context_size > 0:
                context_results = []
                processed_files = set()

                for result in results:
                    file_path = result["file_path"]
                    chunk_index = result["chunk_index"]
                    file_chunk_key = f"{file_path}_{chunk_index}"

                    if file_chunk_key in processed_files:
                        continue
                    processed_files.add(file_chunk_key)

                    adjacent_chunks = self.vector_database.get_adjacent_chunks(file_path, chunk_index, context_size)
                    context_results.extend(adjacent_chunks)

                all_results = results.copy()
                existing_doc_ids = {result["document_id"] for result in all_results}

                for context in context_results:
                    if context["document_id"] not in existing_doc_ids:
                        all_results.append(context)
                        existing_doc_ids.add(context["document_id"])

                all_results.sort(key=lambda x: (x["file_path"], x["chunk_index"]))
                self.logger.info(f"検索結果（コンテキスト含む）: {len(all_results)} 件")

                if full_document:
                    return self._merge_full_documents(all_results)
                return all_results
            else:
                if full_document:
                    return self._merge_full_documents(results)
                self.logger.info(f"検索結果: {len(results)} 件")
                return results

        except Exception as e:
            self.logger.error(f"検索中にエラーが発生しました: {str(e)}")
            raise

    def _merge_full_documents(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        full_doc_results = []
        processed_files = set()

        for result in results:
            file_path = result["file_path"]
            if file_path in processed_files:
                continue
            processed_files.add(file_path)
            full_doc_results.extend(self.vector_database.get_document_by_file_path(file_path))

        merged_results = results.copy()
        existing_doc_ids = {result["document_id"] for result in merged_results}

        for doc_chunk in full_doc_results:
            if doc_chunk["document_id"] not in existing_doc_ids:
                merged_results.append(doc_chunk)
                existing_doc_ids.add(doc_chunk["document_id"])

        merged_results.sort(key=lambda x: (x["file_path"], x["chunk_index"]))
        self.logger.info(f"検索結果（全文含む）: {len(merged_results)} 件")
        return merged_results

    def clear_index(self) -> Dict[str, Any]:
        try:
            self.logger.info("インデックスをクリアしています...")
            deleted_count = self.vector_database.clear_database()
            self.logger.info(f"インデックスをクリアしました（{deleted_count} ドキュメントを削除）")
            return {"deleted_count": deleted_count, "success": True, "message": f"{deleted_count} ドキュメントを削除しました"}
        except Exception as e:
            self.logger.error(f"インデックスのクリア中にエラーが発生しました: {str(e)}")
            return {"deleted_count": 0, "success": False, "error": str(e)}

    def get_document_count(self) -> int:
        try:
            count = self.vector_database.get_document_count()
            self.logger.info(f"インデックス内のドキュメント数: {count}")
            return count
        except Exception as e:
            self.logger.error(f"ドキュメント数の取得中にエラーが発生しました: {str(e)}")
            raise


def create_rag_service_from_env() -> RAGService:
    """環境変数から RAGService を作成する（os.environ.get のみ使用、.env は読み込まない）。"""
    embedding_model = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")

    document_processor = DocumentProcessor()
    embedding_generator = EmbeddingGenerator(model_name=embedding_model)
    vector_database = VectorDatabase(
        {
            "chroma_path": os.environ.get("CHROMA_PATH", str(Path(__file__).parent.parent / "data" / "chroma")),
            "embedding_dim": os.environ.get("EMBEDDING_DIM", "1024"),
        }
    )

    return RAGService(document_processor, embedding_generator, vector_database)
