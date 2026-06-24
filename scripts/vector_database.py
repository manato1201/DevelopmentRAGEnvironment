"""
vector_database.py — ChromaDB + BM25 ハイブリッド検索版

変更点（オリジナルからの差分）:
  - BM25 インデックスを namespace ごとに {chroma_path}/bm25/{ns}.pkl に保存
  - 日本語形態素解析: SudachiPy（未インストール時は regex fallback）
  - search() に query_text 引数を追加 → ベクトル + BM25 を RRF でマージ
  - clear_database / batch_insert_documents でも BM25 を同期更新

セットアップ:
  uv add rank-bm25 sudachipy sudachidict-core

Namespace mapping:
  File path top-level directory → ChromaDB collection name
  e.g. tutorials/foo.md  → collection "tutorials"
       root_file.md       → collection "default"
  Directories starting with _ or . are excluded.
"""
from __future__ import annotations

import os
import pickle
import re
from pathlib import Path
from typing import Optional


class VectorDatabase:
    def __init__(self, config: dict) -> None:
        self.chroma_path: str = config.get("chroma_path", "./data/chroma")
        self.embedding_dim: int = int(config.get("embedding_dim", 1024))
        self.client = None
        self._collections: dict = {}

        # BM25 関連
        self._bm25_dir: Optional[Path] = None
        self._bm25_cache: dict = {}   # namespace → {doc_ids, contents, file_paths, chunk_indices, metadatas, tokenized, bm25}
        self._sudachi = None          # SudachiPy tokenizer（lazy init）
        self._use_sudachi: Optional[bool] = None  # None = 未確認

    # ------------------------------------------------------------------ #
    # Connection lifecycle                                                  #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        import chromadb
        Path(self.chroma_path).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.chroma_path)
        self._bm25_dir = Path(self.chroma_path) / "bm25"
        self._bm25_dir.mkdir(exist_ok=True)

    def disconnect(self) -> None:
        self.client = None
        self._collections.clear()
        self._bm25_cache.clear()

    def initialize_database(self) -> None:
        self.connect()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _namespace_from_path(self, file_path: str) -> Optional[str]:
        source_dir = os.environ.get("SOURCE_DIR", "")
        try:
            rel = Path(file_path).relative_to(source_dir)
            parts = rel.parts
        except ValueError:
            parts = Path(file_path).parts

        if len(parts) > 1:
            first = parts[0]
            if first.startswith(("_", ".")):
                return None
            return first
        return "default"

    def _get_collection(self, namespace: str):
        if namespace not in self._collections:
            self._collections[namespace] = self.client.get_or_create_collection(
                name=namespace,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[namespace]

    @staticmethod
    def _safe_meta(metadata: dict) -> dict:
        return {
            k: v
            for k, v in metadata.items()
            if isinstance(v, (str, int, float, bool))
        }

    @staticmethod
    def _to_list(embedding) -> list:
        try:
            return embedding.tolist()
        except AttributeError:
            return list(embedding)

    @staticmethod
    def _source_file_path(doc: dict) -> str:
        original = doc.get("metadata", {}).get("original_file_path") or doc.get("original_file_path")
        return original or doc.get("file_path", "")

    # ------------------------------------------------------------------ #
    # 形態素解析 / トークナイザー                                            #
    # ------------------------------------------------------------------ #

    def _tokenize(self, text: str) -> list[str]:
        """
        日本語テキストをトークン列に変換。
        SudachiPy が使えればそれを使い、なければ regex fallback。
        """
        # SudachiPy 使用可否を初回だけ確認
        if self._use_sudachi is None:
            try:
                from sudachipy import dictionary as _sd
                dic = _sd.Dictionary()
                self._sudachi = dic.create()
                self._use_sudachi = True
            except Exception:
                self._use_sudachi = False

        tokens: list[str] = []

        if self._use_sudachi and self._sudachi is not None:
            stop_pos = {"助詞", "助動詞", "記号", "補助記号", "空白"}
            try:
                morphs = self._sudachi.tokenize(text)
                for m in morphs:
                    pos = m.part_of_speech()[0]
                    if pos in stop_pos:
                        continue
                    form = m.dictionary_form()
                    if len(form) > 1:
                        tokens.append(form)
            except Exception:
                pass

        # 英数字 / ゲームID / モデル名（BTQ-116, FR-3, TC-8 など）は常に追加
        alpha = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*", text)
        tokens.extend(t.lower() for t in alpha if len(t) > 1)

        # SudachiPy が使えない場合は CJK 2文字以上 + 英数字で代替
        if not self._use_sudachi:
            cjk = re.findall(r"[぀-ヿ一-鿿]{2,}", text)
            tokens.extend(cjk)

        return list(dict.fromkeys(tokens)) if tokens else text.split()

    # ------------------------------------------------------------------ #
    # BM25 インデックス管理                                                  #
    # ------------------------------------------------------------------ #

    def _bm25_path(self, namespace: str) -> Path:
        return self._bm25_dir / f"{namespace}.pkl"  # type: ignore[operator]

    def _load_bm25(self, namespace: str) -> Optional[dict]:
        """ディスクから BM25 インデックスをロード（キャッシュあり）"""
        if namespace in self._bm25_cache:
            return self._bm25_cache[namespace]
        p = self._bm25_path(namespace)
        if p.exists():
            try:
                data = pickle.loads(p.read_bytes())
                self._bm25_cache[namespace] = data
                return data
            except Exception:
                pass
        return None

    def _save_bm25(self, namespace: str, data: dict) -> None:
        self._bm25_cache[namespace] = data
        if self._bm25_dir:
            self._bm25_path(namespace).write_bytes(pickle.dumps(data))

    def _rebuild_bm25_from_chroma(self, namespace: str) -> None:
        """
        ChromaDB の内容を正として BM25 インデックスを再構築する。
        batch_insert_documents / delete 系の後に呼ぶ。
        """
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            return  # rank_bm25 未インストール → BM25 スキップ

        col = self._get_collection(namespace)
        count = col.count()
        if count == 0:
            # コレクションが空になった → インデックス削除
            self._bm25_cache.pop(namespace, None)
            p = self._bm25_path(namespace)
            if p.exists():
                p.unlink()
            return

        res = col.get(include=["documents", "metadatas"])
        doc_ids      = res["ids"]
        contents     = res["documents"]
        metadatas    = res["metadatas"]
        file_paths   = [m.get("file_path", "") for m in metadatas]
        chunk_indices = [m.get("chunk_index", 0) for m in metadatas]

        tokenized = [self._tokenize(c) for c in contents]
        bm25_obj  = BM25Okapi(tokenized)

        data = {
            "doc_ids":       doc_ids,
            "contents":      contents,
            "file_paths":    file_paths,
            "chunk_indices": chunk_indices,
            "metadatas":     metadatas,
            "tokenized":     tokenized,
            "bm25":          bm25_obj,
        }
        self._save_bm25(namespace, data)

    # ------------------------------------------------------------------ #
    # Write operations                                                      #
    # ------------------------------------------------------------------ #

    def insert_document(self, document: dict) -> None:
        self.batch_insert_documents([document])

    def batch_insert_documents(self, documents: list) -> None:
        """ChromaDB への upsert + 影響 namespace の BM25 再構築"""
        by_ns: dict[str, list] = {}
        for doc in documents:
            fp = self._source_file_path(doc)
            ns = self._namespace_from_path(fp)
            if ns is None:
                continue
            by_ns.setdefault(ns, []).append(doc)

        for ns, docs in by_ns.items():
            col = self._get_collection(ns)
            col.upsert(
                ids=[d["document_id"] for d in docs],
                embeddings=[self._to_list(d["embedding"]) for d in docs],
                documents=[d["content"] for d in docs],
                metadatas=[
                    {
                        "file_path": self._source_file_path(d),
                        "chunk_index": d.get("chunk_index", 0),
                        **self._safe_meta(d.get("metadata", {})),
                    }
                    for d in docs
                ],
            )
            # BM25 再構築（ChromaDB を正として同期）
            self._rebuild_bm25_from_chroma(ns)

    def delete_document(self, document_id: str) -> None:
        if self.client is None:
            return
        for col in self.client.list_collections():
            try:
                self._get_collection(col.name).delete(ids=[document_id])
                self._rebuild_bm25_from_chroma(col.name)
            except Exception:
                pass

    def delete_by_file_path(self, file_path: str) -> None:
        ns = self._namespace_from_path(file_path)
        try:
            self._get_collection(ns).delete(
                where={"file_path": {"$eq": file_path}}
            )
            self._rebuild_bm25_from_chroma(ns)
        except Exception:
            pass

    def clear_database(self) -> int:
        if self.client is None:
            return 0
        total = 0
        for col in self.client.list_collections():
            total += col.count()
            self.client.delete_collection(col.name)
        self._collections.clear()
        # BM25 インデックスも全削除
        self._bm25_cache.clear()
        if self._bm25_dir and self._bm25_dir.exists():
            for p in self._bm25_dir.glob("*.pkl"):
                p.unlink()
        return total

    # ------------------------------------------------------------------ #
    # BM25 検索                                                             #
    # ------------------------------------------------------------------ #

    def _bm25_search(
        self,
        query_text: str,
        namespace: Optional[str],
        limit: int,
    ) -> list[dict]:
        """BM25 でスコアリングし、上位 limit 件を返す。"""
        try:
            from rank_bm25 import BM25Okapi  # noqa: F401 — import check
        except ImportError:
            return []

        targets = (
            [namespace]
            if namespace
            else [c.name for c in self.client.list_collections()]
        )

        query_tokens = self._tokenize(query_text)
        if not query_tokens:
            return []

        all_hits: list[dict] = []

        for ns in targets:
            data = self._load_bm25(ns)
            if data is None:
                # インデックスがなければ再構築を試みる
                self._rebuild_bm25_from_chroma(ns)
                data = self._load_bm25(ns)
            if data is None:
                continue

            bm25_obj = data["bm25"]
            scores   = bm25_obj.get_scores(query_tokens)

            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:limit]

            for idx in top_indices:
                if scores[idx] <= 0:
                    continue
                all_hits.append({
                    "document_id": data["doc_ids"][idx],
                    "content":     data["contents"][idx],
                    "file_path":   data["file_paths"][idx],
                    "chunk_index": data["chunk_indices"][idx],
                    "similarity":  float(scores[idx]),   # BM25 スコアを similarity として格納
                    "metadata":    data["metadatas"][idx],
                    "namespace":   ns,
                })

        all_hits.sort(key=lambda x: x["similarity"], reverse=True)
        return all_hits[:limit]

    # ------------------------------------------------------------------ #
    # RRF マージ                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rrf_merge(
        vector_results: list[dict],
        bm25_results: list[dict],
        limit: int,
        k: int = 60,
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion でベクトル検索と BM25 の結果をマージ。

        RRF score = 1/(k + vector_rank) + 1/(k + bm25_rank)
        k=60 が標準値（Cormack et al. 2009）。
        """
        rrf_scores: dict[str, float] = {}
        doc_map: dict[str, dict]     = {}

        for rank, r in enumerate(vector_results):
            did = r["document_id"]
            rrf_scores[did] = rrf_scores.get(did, 0.0) + 1.0 / (k + rank + 1)
            doc_map[did] = r

        for rank, r in enumerate(bm25_results):
            did = r["document_id"]
            rrf_scores[did] = rrf_scores.get(did, 0.0) + 1.0 / (k + rank + 1)
            if did not in doc_map:
                doc_map[did] = r

        sorted_ids = sorted(rrf_scores, key=lambda d: rrf_scores[d], reverse=True)
        merged = []
        for did in sorted_ids[:limit]:
            r = dict(doc_map[did])
            r["similarity"] = rrf_scores[did]  # RRF スコアで上書き
            merged.append(r)
        return merged

    # ------------------------------------------------------------------ #
    # Read operations                                                       #
    # ------------------------------------------------------------------ #

    def search(
        self,
        embedding,
        limit: int = 5,
        namespace: Optional[str] = None,
        query_text: str = "",
    ) -> list[dict]:
        """
        ハイブリッド検索（ベクトル + BM25）。

        Args:
            embedding:   クエリの埋め込みベクトル
            limit:       返す件数
            namespace:   指定すると該当コレクションのみ検索
            query_text:  BM25 用の生テキスト（省略するとベクトルのみ）

        Returns:
            RRF スコアでソートされた検索結果リスト
        """
        if self.client is None:
            return []

        targets = (
            [namespace]
            if namespace
            else [c.name for c in self.client.list_collections()]
        )

        # ── ベクトル検索 ──────────────────────────────────────────
        vector_results: list[dict] = []
        fetch_n = limit * 2  # RRF のために多めに取得

        for ns in targets:
            col   = self._get_collection(ns)
            count = col.count()
            if count == 0:
                continue
            res = col.query(
                query_embeddings=[self._to_list(embedding)],
                n_results=min(fetch_n, count),
                include=["documents", "metadatas", "distances"],
            )
            for doc_id, doc, meta, dist in zip(
                res["ids"][0],
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
            ):
                vector_results.append({
                    "document_id": doc_id,
                    "content":     doc,
                    "file_path":   meta.get("file_path", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                    "similarity":  float(1.0 - dist),
                    "metadata":    meta,
                    "namespace":   ns,
                })

        vector_results.sort(key=lambda x: x["similarity"], reverse=True)
        vector_results = vector_results[:fetch_n]

        # ── BM25 検索（query_text がある場合のみ）────────────────
        if query_text:
            bm25_results = self._bm25_search(query_text, namespace, fetch_n)
            if bm25_results:
                return self._rrf_merge(vector_results, bm25_results, limit)

        # BM25 なし / ヒットなし → ベクトルのみ
        return vector_results[:limit]

    # ------------------------------------------------------------------ #
    # Utility                                                               #
    # ------------------------------------------------------------------ #

    def get_document_count(self) -> int:
        if self.client is None:
            return 0
        return sum(c.count() for c in self.client.list_collections())

    def get_adjacent_chunks(
        self, file_path: str, chunk_index: int, context_size: int = 1
    ) -> list:
        ns  = self._namespace_from_path(file_path)
        col = self._get_collection(ns)
        results: list = []
        for idx in range(
            max(0, chunk_index - context_size), chunk_index + context_size + 1
        ):
            if idx == chunk_index:
                continue
            res = col.get(
                where={
                    "$and": [
                        {"file_path": {"$eq": file_path}},
                        {"chunk_index": {"$eq": idx}},
                    ]
                },
                include=["documents", "metadatas"],
            )
            for doc_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
                results.append({
                    "document_id": doc_id,
                    "content":     doc,
                    "file_path":   file_path,
                    "chunk_index": idx,
                    "metadata":    meta,
                })
        results.sort(key=lambda x: x["chunk_index"])
        return results

    def get_document_by_file_path(self, file_path: str) -> list:
        ns  = self._namespace_from_path(file_path)
        col = self._get_collection(ns)
        res = col.get(
            where={"file_path": {"$eq": file_path}},
            include=["documents", "metadatas"],
        )
        results = [
            {
                "document_id": doc_id,
                "content":     doc,
                "file_path":   file_path,
                "chunk_index": meta.get("chunk_index", 0),
                "metadata":    meta,
            }
            for doc_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"])
        ]
        results.sort(key=lambda x: x["chunk_index"])
        return results
