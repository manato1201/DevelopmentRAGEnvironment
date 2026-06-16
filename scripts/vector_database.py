"""
vector_database.py — ChromaDB drop-in replacement for mcp-rag-server

Usage:
  cp scripts/vector_database.py ~/mcp-rag-server/src/vector_database.py
  cd ~/mcp-rag-server && uv add chromadb

Namespace mapping:
  File path top-level directory → ChromaDB collection name
  e.g. tutorials/foo.md  → collection "tutorials"
       root_file.md       → collection "default"
  Directories starting with _ or . are excluded (Obsidian system dirs).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


class VectorDatabase:
    def __init__(self, config: dict) -> None:
        self.chroma_path: str = config.get("chroma_path", "./data/chroma")
        self.embedding_dim: int = int(config.get("embedding_dim", 1024))
        self.client = None
        self._collections: dict = {}

    # ------------------------------------------------------------------ #
    # Connection lifecycle                                                  #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        import chromadb

        Path(self.chroma_path).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.chroma_path)

    def disconnect(self) -> None:
        self.client = None
        self._collections.clear()

    def initialize_database(self) -> None:
        # Establish the ChromaDB connection (called by RAGService.__init__).
        self.connect()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _namespace_from_path(self, file_path: str) -> Optional[str]:
        """
        Derive collection name from the first directory under SOURCE_DIR.

        Returns:
            str  — valid collection name (e.g. "tutorials")
            None — document should be skipped (_rag_dashboard, _templates, .processed …)
        """
        import os
        source_dir = os.environ.get("SOURCE_DIR", "")
        try:
            rel = Path(file_path).relative_to(source_dir)
            parts = rel.parts
        except ValueError:
            # file_path is not under SOURCE_DIR; fall back to raw parts
            parts = Path(file_path).parts

        if len(parts) > 1:
            first = parts[0]
            if first.startswith(("_", ".")):
                return None  # skip: system dir (_rag_dashboard, _templates, .processed)
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
        """ChromaDB metadata must be flat dict with str/int/float/bool values."""
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

    # ------------------------------------------------------------------ #
    # Write operations                                                      #
    # ------------------------------------------------------------------ #

    def insert_document(self, document: dict) -> None:
        self.batch_insert_documents([document])

    @staticmethod
    def _source_file_path(doc: dict) -> str:
        """
        document_processor.py writes a cache copy of every file under
        PROCESSED_DIR and sets chunk["file_path"] to that cache path,
        stashing the true source path separately as
        chunk["original_file_path"] / metadata["original_file_path"].
        Prefer the original source path so namespace derivation and
        stored metadata reflect the real vault location, not the cache.
        """
        original = doc.get("metadata", {}).get("original_file_path") or doc.get("original_file_path")
        return original or doc.get("file_path", "")

    def batch_insert_documents(self, documents: list) -> None:
        """Insert or update documents, grouped by namespace (collection).
        Documents under _rag_dashboard, _templates, .processed etc. are skipped.
        """
        by_ns: dict[str, list] = {}
        for doc in documents:
            fp = self._source_file_path(doc)
            ns = self._namespace_from_path(fp)
            if ns is None:
                continue  # skip system dirs
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

    def delete_document(self, document_id: str) -> None:
        if self.client is None:
            return
        for col in self.client.list_collections():
            try:
                self._get_collection(col.name).delete(ids=[document_id])
            except Exception:
                pass

    def delete_by_file_path(self, file_path: str) -> None:
        ns = self._namespace_from_path(file_path)
        try:
            self._get_collection(ns).delete(
                where={"file_path": {"$eq": file_path}}
            )
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
        return total

    # ------------------------------------------------------------------ #
    # Read operations                                                       #
    # ------------------------------------------------------------------ #

    def search(
        self,
        embedding,
        limit: int = 5,
        namespace: Optional[str] = None,
    ) -> list:
        """
        Vector similarity search.

        Args:
            embedding: Query embedding (numpy array or list).
            limit:     Max results to return (across all searched namespaces).
            namespace: If given, search only that collection.
                       If None, search all collections.

        Returns:
            List of dicts sorted by similarity descending.
            Each dict has: document_id, content, file_path,
                           similarity (0-1), metadata, namespace.
        """
        if self.client is None:
            return []

        targets = (
            [namespace]
            if namespace
            else [c.name for c in self.client.list_collections()]
        )

        results: list = []
        for ns in targets:
            col = self._get_collection(ns)
            count = col.count()
            if count == 0:
                continue
            res = col.query(
                query_embeddings=[self._to_list(embedding)],
                n_results=min(limit, count),
                include=["documents", "metadatas", "distances"],
            )
            for doc_id, doc, meta, dist in zip(
                res["ids"][0],
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
            ):
                results.append(
                    {
                        "document_id": doc_id,
                        "content": doc,
                        "file_path": meta.get("file_path", ""),
                        "chunk_index": meta.get("chunk_index", 0),
                        "similarity": float(1.0 - dist),  # cosine dist → similarity
                        "metadata": meta,
                        "namespace": ns,
                    }
                )

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    def get_document_count(self) -> int:
        if self.client is None:
            return 0
        return sum(c.count() for c in self.client.list_collections())

    def get_adjacent_chunks(
        self, file_path: str, chunk_index: int, context_size: int = 1
    ) -> list:
        ns = self._namespace_from_path(file_path)
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
                results.append(
                    {
                        "document_id": doc_id,
                        "content": doc,
                        "file_path": file_path,
                        "chunk_index": idx,
                        "metadata": meta,
                    }
                )
        results.sort(key=lambda x: x["chunk_index"])
        return results

    def get_document_by_file_path(self, file_path: str) -> list:
        ns = self._namespace_from_path(file_path)
        col = self._get_collection(ns)
        res = col.get(
            where={"file_path": {"$eq": file_path}},
            include=["documents", "metadatas"],
        )
        results = [
            {
                "document_id": doc_id,
                "content": doc,
                "file_path": file_path,
                "chunk_index": meta.get("chunk_index", 0),
                "metadata": meta,
            }
            for doc_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"])
        ]
        results.sort(key=lambda x: x["chunk_index"])
        return results
