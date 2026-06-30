#!/usr/bin/env python3
"""
rag_graph_export.py — ChromaDB グラフデータエクスポーター

このリポジトリの uv 環境で実行される（chromadb / numpy が必要）。
stdout に JSON を出力して終了する。rag_local_bridge.py から呼ばれる。

Usage:
    uv run python <this_file> [chroma_path]

Env:
    CHROMA_PATH  ChromaDB データ保存先（省略時はリポジトリ直下の data/chroma）

Output JSON:
    {
      "nodes": [{"id": "...", "label": "...", "db": "local",
                 "chunk_count": 3, "x": 0.42, "y": 0.71}],
      "edges": [{"source": "a.md", "target": "b.md", "score": 0.87}]
    }
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from pathlib import Path


# ─── Spring レイアウト ──────────────────────────────────────────────────────────
def _spring_layout(
    node_ids: list[str],
    edge_set: dict[tuple[str, str], float],
    iterations: int = 80,
) -> dict[str, list[float]]:
    random.seed(42)
    pos: dict[str, list[float]] = {
        nid: [random.uniform(0.1, 0.9), random.uniform(0.1, 0.9)]
        for nid in node_ids
    }

    for _ in range(iterations):
        forces: dict[str, list[float]] = {nid: [0.0, 0.0] for nid in node_ids}
        for ai, a in enumerate(node_ids):
            for bi, b in enumerate(node_ids):
                if ai >= bi:
                    continue
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d = math.hypot(dx, dy) or 0.001
                # 反発力
                f_rep = 0.004 / (d * d)
                forces[a][0] += dx / d * f_rep
                forces[a][1] += dy / d * f_rep
                forces[b][0] -= dx / d * f_rep
                forces[b][1] -= dy / d * f_rep
                # エッジ引力
                score = edge_set.get((a, b), edge_set.get((b, a), 0.0))
                if score > 0:
                    f_att = score * 0.025
                    forces[a][0] -= dx * f_att
                    forces[a][1] -= dy * f_att
                    forces[b][0] += dx * f_att
                    forces[b][1] += dy * f_att
        for nid in node_ids:
            pos[nid][0] = max(0.04, min(0.96, pos[nid][0] + forces[nid][0]))
            pos[nid][1] = max(0.04, min(0.96, pos[nid][1] + forces[nid][1]))

    return pos


# ─── メイン ────────────────────────────────────────────────────────────────────
def main() -> None:
    repo_root = Path(__file__).parent.parent
    chroma_path_raw = (
        sys.argv[1] if len(sys.argv) > 1
        else os.environ.get("CHROMA_PATH", str(repo_root / "data" / "chroma"))
    )
    chroma_path = (
        Path(chroma_path_raw)
        if Path(chroma_path_raw).is_absolute()
        else (repo_root / chroma_path_raw).resolve()
    )

    try:
        import chromadb
        import numpy as np
    except ImportError as exc:
        print(json.dumps({"error": str(exc), "nodes": [], "edges": []}))
        return

    client = chromadb.PersistentClient(path=str(chroma_path))
    collections = client.list_collections()
    if not collections:
        print(json.dumps({"nodes": [], "edges": []}))
        return

    # namespace ごとに分かれた全コレクションを横断して集計する
    ids: list[str] = []
    metas: list[dict] = []
    embeddings: list = []
    col_names: list[str] = []
    for c in collections:
        col = client.get_collection(c.name)
        result = col.get(include=["metadatas", "embeddings"])
        n = len(result["ids"])
        ids.extend(result["ids"])
        metas.extend(result.get("metadatas") or [{} for _ in range(n)])
        col_embeddings = result.get("embeddings")
        if col_embeddings is not None and len(col_embeddings) > 0:
            embeddings.extend(col_embeddings)
        else:
            embeddings.extend([None] * n)
        col_names.extend([c.name] * n)

    has_embeddings = any(e is not None for e in embeddings)

    # ── ノード: file_path でグルーピング ──────────────────────────────────────
    # 各ファイルの「代表チャンク」（最初のチャンクのインデックス）を使う
    nodes_dict: dict[str, dict] = {}
    for i, meta in enumerate(metas):
        fp: str = meta.get("file_path", ids[i])
        if fp not in nodes_dict:
            nodes_dict[fp] = {
                "id": fp,
                "label": Path(fp).name,
                "db": col_names[i],
                "chunk_count": 1,
                "_emb_idx": i,
            }
        else:
            nodes_dict[fp]["chunk_count"] += 1

    node_list = list(nodes_dict.values())
    node_ids = [n["id"] for n in node_list]

    # ── エッジ: 代表埋め込みのコサイン類似度 top-3 ──────────────────────────
    edges: list[dict] = []
    edge_set: dict[tuple[str, str], float] = {}

    if has_embeddings and len(node_list) > 1:
        rep_embs = np.array(
            [embeddings[n["_emb_idx"]] for n in node_list], dtype=float
        )
        norms = np.linalg.norm(rep_embs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        rep_embs /= norms
        sim: np.ndarray = rep_embs @ rep_embs.T
        np.fill_diagonal(sim, -1.0)

        seen: set[tuple[str, str]] = set()
        for i in range(len(node_list)):
            top3 = np.argsort(sim[i])[-3:][::-1]
            for j in top3:
                score = float(sim[i, j])
                if score < 0.70:
                    continue
                a_id, b_id = node_list[i]["id"], node_list[j]["id"]
                key = (min(a_id, b_id), max(a_id, b_id))
                if key not in seen:
                    seen.add(key)
                    edges.append({"source": a_id, "target": b_id, "score": round(score, 4)})
                    edge_set[key] = score

    # ── Spring レイアウト ──────────────────────────────────────────────────────
    pos = _spring_layout(node_ids, edge_set)

    output_nodes = []
    for n in node_list:
        output_nodes.append({
            "id": n["id"],
            "label": n["label"],
            "db": n["db"],
            "chunk_count": n["chunk_count"],
            "x": round(pos[n["id"]][0], 4),
            "y": round(pos[n["id"]][1], 4),
        })

    print(json.dumps({"nodes": output_nodes, "edges": edges}, ensure_ascii=False))


if __name__ == "__main__":
    main()
