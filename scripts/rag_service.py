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
from typing import Any, Callable, Dict, List

from document_processor import DocumentProcessor
from embedding_generator import EmbeddingGenerator
from vector_database import VectorDatabase

# ─── 軽量サービスレジストリ（IMPROVEMENT_PLAN.md Phase4） ─────────────────────────
#
# ECS・重量DIコンテナは導入しない: このリポジトリはバッチ/CLI主体のETLパイプライン
# （rag_cli.py index）であり、毎フレーム大量エンティティを反復処理するランタイムでは
# ないため、アーキタイプ/システムの概念は不要。処理段も3〜4個程度でDIコンテナは
# オーバースペック。代わりに「関数登録＋名前引きルックアップ」だけの薄いレジストリを
# 用意し、将来の差し替えポイント（Phase1のレベリング用プロンプト構成、Phase2の
# CLIP画像埋め込み＝"clip"登録、Phase3のバックエンド差し替え＝SQLite↔TiDB・
# ChromaDB↔TiKV）がこの境界に乗るようにする。document_processor.py /
# embedding_generator.py 本体の実装には一切手を入れていない（登録簿を挟んだだけ）。

_EMBEDDERS: Dict[str, Callable[[], Any]] = {}
_VECTOR_BACKENDS: Dict[str, Callable[[dict], VectorDatabase]] = {}


def register_embedder(name: str, factory: Callable[[], Any]) -> None:
    """埋め込み生成器のファクトリを名前で登録する。"""
    _EMBEDDERS[name] = factory


def get_embedder(name: str = "default") -> Any:
    """
    登録済みの埋め込み生成器を名前で取得する。
    未登録キーは KeyError で即座に失敗させる（暗黙フォールバック禁止 —
    タイプミスしたモデル名で静かに間違った埋め込みを作り続ける事故を防ぐ）。
    """
    return _EMBEDDERS[name]()


def register_vector_backend(name: str, factory: Callable[[dict], VectorDatabase]) -> None:
    """ベクトルストアのファクトリを名前で登録する（configを受け取る点がembedderと異なる）。"""
    _VECTOR_BACKENDS[name] = factory


def get_vector_backend(config: dict, name: str = "default") -> VectorDatabase:
    """登録済みのベクトルストアを名前で取得する（未登録キーはKeyError）。"""
    return _VECTOR_BACKENDS[name](config)


def _default_text_embedder_factory() -> EmbeddingGenerator:
    model = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    return EmbeddingGenerator(model_name=model)


def _clip_image_embedder_factory() -> Any:
    # 遅延import: image_embedding_generator.py はCLIPモデルをロードするため重い。
    # レジストリへの「登録」自体はモジュールimport時に行うが、実際のモデルロードは
    # get_embedder("clip") が呼ばれた時点まで遅延させる（RAGService側の遅延初期化と
    # 二重の安全策）。
    from image_embedding_generator import ImageEmbeddingGenerator

    return ImageEmbeddingGenerator()


def _default_vector_backend_factory(config: dict) -> VectorDatabase:
    return VectorDatabase(config)


register_embedder("default", _default_text_embedder_factory)
register_embedder("clip", _clip_image_embedder_factory)
register_vector_backend("default", _default_vector_backend_factory)


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
        # 画像埋め込み（CLIP、IMPROVEMENT_PLAN.md Phase2）は遅延初期化する。
        # RAGServiceはブリッジ起動のたびに毎回構築されるため、ここでCLIPモデルを
        # 即ロードすると画像検索を一度も使わないユーザーの起動時間・メモリまで
        # 悪化させてしまう。実際に index_images()/search_images() が呼ばれた
        # 初回にだけロードする。
        self._image_embedding_generator = None

        try:
            self.vector_database.initialize_database()
        except Exception as e:
            self.logger.error(f"データベースの初期化に失敗しました: {str(e)}")
            raise

    def _get_image_embedding_generator(self):
        if self._image_embedding_generator is None:
            self._image_embedding_generator = get_embedder("clip")
        return self._image_embedding_generator

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
                            # Phase1レベリング: document_processor.process_file() が frontmatter の
                            # difficulty を読み取って chunk["metadata"] に入れている。ここで拾わないと
                            # そのまま握りつぶされ、search()でlevelフィルタが効かなくなる。
                            "difficulty": chunk.get("metadata", {}).get("difficulty", ""),
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

    # ------------------------------------------------------------------ #
    # 画像埋め込み（CLIP、IMPROVEMENT_PLAN.md Phase2）                        #
    # 既存のテキスト検索（index_documents/search）とは完全に独立した経路。     #
    # ------------------------------------------------------------------ #

    def index_images(
        self, namespace: str, image_paths: List[str], metadata_by_path: Dict[str, Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        画像ファイル群をCLIP埋め込みしてvector_database.insert_images()へ登録する。
        namespaceは呼び出し側が明示する（画像はlocalRAG/配下のフォルダ構造に
        従っているとは限らないため、テキストのように file_path から自動推定しない）。
        """
        if not image_paths:
            return {"success": True, "image_count": 0, "message": "画像パスが空です"}
        metadata_by_path = metadata_by_path or {}
        try:
            generator = self._get_image_embedding_generator()
            embeddings = generator.generate_image_embeddings(image_paths)
            documents = [
                {
                    "document_id": f"img::{namespace}::{path}",
                    "file_path": path,
                    "embedding": emb,
                    "metadata": metadata_by_path.get(path, {}),
                }
                for path, emb in zip(image_paths, embeddings)
            ]
            self.vector_database.insert_images(namespace, documents)
            self.logger.info(f"画像 {len(documents)} 枚を namespace '{namespace}' にインデックス化しました")
            return {"success": True, "image_count": len(documents)}
        except Exception as e:
            self.logger.error(f"画像インデックス化中にエラーが発生しました: {str(e)}")
            return {"success": False, "image_count": 0, "error": str(e)}

    def search_images(self, query: str, limit: int = 5, namespace: str = None) -> List[Dict[str, Any]]:
        """
        テキストクエリで画像を検索する（クロスモーダル検索）。CLIPのテキスト
        エンコーダでクエリをエンコードし、画像コレクション（{namespace}_images）
        に対してベクトル検索する。既存のテキスト検索には一切影響しない。
        """
        if not query:
            return []
        try:
            generator = self._get_image_embedding_generator()
            embedding = generator.generate_text_query_embedding(query)
            if not embedding:
                return []
            return self.vector_database.search_images(embedding, limit, namespace)
        except Exception as e:
            self.logger.error(f"画像検索中にエラーが発生しました: {str(e)}")
            return []

    def get_image_count(self) -> int:
        try:
            return self.vector_database.get_image_count()
        except Exception as e:
            self.logger.error(f"画像件数の取得中にエラーが発生しました: {str(e)}")
            return 0


def create_rag_service_from_env() -> RAGService:
    """
    環境変数から RAGService を作成する（os.environ.get のみ使用、.env は読み込まない）。
    埋め込み生成器・ベクトルストアはレジストリ（get_embedder/get_vector_backend）経由で
    取得する。既定登録（_default_text_embedder_factory/_default_vector_backend_factory）は
    従来と全く同じ構築ロジックのため、挙動は変わらない。Phase3でバックエンドを
    差し替える際は、ここを `get_vector_backend(config, name="tidb")` のように
    変えるだけで済むようにするのが狙い。
    """
    document_processor = DocumentProcessor()
    embedding_generator = get_embedder("default")
    vector_database = get_vector_backend(
        {
            "chroma_path": os.environ.get("CHROMA_PATH", str(Path(__file__).parent.parent / "data" / "chroma")),
            "embedding_dim": os.environ.get("EMBEDDING_DIM", "1024"),
        }
    )

    return RAGService(document_processor, embedding_generator, vector_database)
