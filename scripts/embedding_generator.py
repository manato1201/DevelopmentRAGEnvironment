"""
embedding_generator.py — エンベディング生成モジュール

テキストからエンベディングを生成する。mcp-rag-server から独立させた版。
"""

import logging
import os
from typing import List

from sentence_transformers import SentenceTransformer


class EmbeddingGenerator:
    """
    エンベディング生成クラス

    Attributes:
        model: SentenceTransformer モデル
        logger: ロガー
    """

    def __init__(self, model_name: str = None):
        self.model_name = model_name or os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
        self.prefix_query = os.environ.get("EMBEDDING_PREFIX_QUERY", "")
        self.prefix_embedding = os.environ.get("EMBEDDING_PREFIX_EMBEDDING", "")

        self.logger = logging.getLogger("embedding_generator")
        self.logger.setLevel(logging.INFO)

        self.logger.info(f"モデル '{self.model_name}' を読み込んでいます...")
        try:
            self.model = SentenceTransformer(self.model_name)
            self.logger.info(f"モデル '{self.model_name}' を読み込みました")
        except Exception as e:
            self.logger.error(f"モデル '{self.model_name}' の読み込みに失敗しました: {str(e)}")
            raise

    def _add_prefix(self, text: str, prefix: str) -> str:
        if not prefix:
            return text
        if text.startswith(prefix):
            return text
        return f"{prefix}{text}"

    def generate_embedding(self, text: str) -> List[float]:
        if not text:
            self.logger.warning("空のテキストからエンベディングを生成しようとしています")
            return []
        processed_text = self._add_prefix(text, self.prefix_embedding)
        embedding = self.model.encode(processed_text)
        return embedding.tolist()

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            self.logger.warning("空のテキストリストからエンベディングを生成しようとしています")
            return []
        processed_texts = [self._add_prefix(text, self.prefix_embedding) for text in texts]
        embeddings = self.model.encode(processed_texts)
        self.logger.info(f"{len(texts)} 個のテキストのエンベディングを生成しました")
        return embeddings.tolist()

    def generate_search_embedding(self, query: str) -> List[float]:
        if not query:
            self.logger.warning("空のクエリからエンベディングを生成しようとしています")
            return []
        processed_query = self._add_prefix(query, self.prefix_query)
        embedding = self.model.encode(processed_query)
        return embedding.tolist()
