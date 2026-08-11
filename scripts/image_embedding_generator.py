"""
image_embedding_generator.py — 画像エンベディング生成モジュール（CLIP）

IMPROVEMENT_PLAN.md Phase2: Local RAGのテキスト埋め込み（intfloat/multilingual-e5-large、
embedding_generator.py）と並行して、CLIP系モデルによる画像埋め込みを追加する。
sentence-transformers が既にCLIPモデル（既定 'clip-ViT-B-32'）をラップしているため、
open_clip 等の新規の重い依存を追加せずに実現できる（sentence-transformers は
pyproject.toml に既存の直接依存）。

CLIPはテキストと画像を同一の埋め込み空間にマッピングするモデルのため、
generate_text_query_embedding() で「テキストで画像を検索する」クロスモーダル検索が
できる。ただしCLIPの埋め込み次元（ViT-B/32は512次元）はテキスト埋め込み
（multilingual-e5-largeは1024次元）と異なるため、ChromaDB上は必ず別コレクション
（{namespace}_images）に分離する。既存のテキスト検索（BM25+ベクトル、
vector_database.py の search()）とは完全に独立した経路として追加しており、
既存の検索ロジック・スコア・順位には一切影響しない
（IMPROVEMENT_PLAN.md Phase2 検証チェックリスト参照）。
"""

from __future__ import annotations

import logging
import os
from typing import List

from sentence_transformers import SentenceTransformer


class ImageEmbeddingGenerator:
    """
    画像エンベディング生成クラス（CLIP）。
    embedding_generator.EmbeddingGenerator と対称的なインターフェースにしている
    （vector_database.py / rag_service.py から同じ流儀で扱えるようにするため）。
    """

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get("IMAGE_EMBEDDING_MODEL", "clip-ViT-B-32")
        self.logger = logging.getLogger("image_embedding_generator")
        self.logger.setLevel(logging.INFO)

        self.logger.info(f"画像埋め込みモデル '{self.model_name}' を読み込んでいます...")
        try:
            self.model = SentenceTransformer(self.model_name)
            self.logger.info(f"画像埋め込みモデル '{self.model_name}' を読み込みました")
        except Exception as e:
            self.logger.error(f"画像埋め込みモデル '{self.model_name}' の読み込みに失敗しました: {str(e)}")
            raise

    def generate_image_embedding(self, image_path: str) -> List[float]:
        """画像ファイル1枚のエンベディングを生成する。"""
        from PIL import Image

        with Image.open(image_path) as img:
            embedding = self.model.encode(img.convert("RGB"))
        return embedding.tolist()

    def generate_image_embeddings(self, image_paths: List[str]) -> List[List[float]]:
        """複数画像をまとめてエンコードする（バッチの方がモデル呼び出し回数を減らせる）。"""
        from PIL import Image

        if not image_paths:
            self.logger.warning("空の画像パスリストからエンベディングを生成しようとしています")
            return []
        images = []
        for path in image_paths:
            with Image.open(path) as img:
                images.append(img.convert("RGB").copy())
        embeddings = self.model.encode(images)
        self.logger.info(f"{len(image_paths)} 枚の画像のエンベディングを生成しました")
        return embeddings.tolist()

    def generate_text_query_embedding(self, query: str) -> List[float]:
        """
        テキストクエリを画像検索用にエンコードする。CLIPのテキストエンコーダは
        画像エンコーダと同一空間にマッピングされるため、このベクトルを画像
        コレクションに対してそのままコサイン類似度検索に使える
        （例: 「炎のシミュレーション画面」というテキストで、実際に炎が映っている
        スクリーンショットを検索する）。
        """
        if not query:
            self.logger.warning("空のクエリから画像検索用エンベディングを生成しようとしています")
            return []
        embedding = self.model.encode(query)
        return embedding.tolist()
