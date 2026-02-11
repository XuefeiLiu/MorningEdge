"""
Anchored assignment (t_assign) + graph connected components (t_graph) for story clusters.
Input: anchor embeddings + article embeddings; output: list of clusters (seeded + discovered).
"""
import logging
from typing import List, Tuple

import numpy as np

from backend.services.embedding_service import get_embedding_service
from backend.pipeline.overnight_pipeline.config import T_ASSIGN, T_GRAPH

logger = logging.getLogger(__name__)


def _connected_components(n: int, edges: List[Tuple[int, int]]) -> List[List[int]]:
    """Union-find: return list of components, each component = list of node indices (0..n-1)."""
    parent = list(range(n))

    def find(x: int) -> int:
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i, j in edges:
        if 0 <= i < n and 0 <= j < n:
            union(i, j)

    comp_id: dict = {}
    for i in range(n):
        root = find(i)
        if root not in comp_id:
            comp_id[root] = []
        comp_id[root].append(i)
    return list(comp_id.values())


def run_clustering(
    anchor_article_ids: List[int],
    anchor_embeddings: np.ndarray,
    article_ids: List[int],
    article_embeddings: np.ndarray,
    t_assign: float = T_ASSIGN,
    t_graph: float = T_GRAPH,
) -> List[dict]:
    """
    Anchored assignment then graph clustering for unmatched articles.

    Args:
        anchor_article_ids: list of article ids that are anchors (same order as anchor_embeddings)
        anchor_embeddings: (n_anchors, dim) array
        article_ids: list of all article ids (non-anchor articles only, or all; anchors will be excluded from assignment)
        article_embeddings: (n_articles, dim) array
        t_assign: assign article to best anchor if similarity >= this
        t_graph: edge between two unmatched articles if similarity >= this

    Returns:
        List of clusters. Each cluster:
          - "cluster_type": "seeded" | "discovered"
          - "anchor_article_id": int or None (for seeded, the anchor's article_id)
          - "article_ids": list of article ids in this cluster (for seeded, includes anchor if it was in article_ids)
    """
    if len(article_ids) == 0 and len(anchor_article_ids) == 0:
        return []
    anchor_set = set(anchor_article_ids)
    svc = get_embedding_service()

    # Normalize
    if len(anchor_embeddings) == 0:
        anchor_embeddings = np.zeros((0, article_embeddings.shape[1] if len(article_embeddings) > 0 else 1536), dtype=np.float32)
    if len(article_embeddings) == 0:
        article_embeddings = np.zeros((0, anchor_embeddings.shape[1]), dtype=np.float32)

    clusters_out: List[dict] = []

    # 1) Seeded clusters: each anchor gets a cluster; assign articles to best anchor if score >= t_assign
    if len(anchor_embeddings) > 0 and len(article_embeddings) > 0:
        # (n_articles, n_anchors)
        sim = svc.compute_similarity_matrix(article_embeddings, anchor_embeddings)
        best_anchor_idx = np.argmax(sim, axis=1)
        best_scores = np.max(sim, axis=1)
        assigned_mask = best_scores >= t_assign
        # Per-anchor: list of article indices (into article_ids) that assigned to this anchor
        anchor_to_articles: dict = {i: [] for i in range(len(anchor_article_ids))}
        for art_idx in range(len(article_ids)):
            if assigned_mask[art_idx]:
                anc_idx = int(best_anchor_idx[art_idx])
                anchor_to_articles[anc_idx].append(art_idx)
        for anc_idx, art_indices in anchor_to_articles.items():
            anchor_aid = anchor_article_ids[anc_idx]
            cluster_article_ids = [article_ids[i] for i in art_indices]
            # Include anchor in the cluster's article list for LLM and linking
            all_ids = [anchor_aid]
            for aid in cluster_article_ids:
                if aid != anchor_aid and aid not in all_ids:
                    all_ids.append(aid)
            clusters_out.append({
                "cluster_type": "seeded",
                "anchor_article_id": anchor_aid,
                "article_ids": all_ids,
            })
        unmatched_article_indices = [i for i in range(len(article_ids)) if not assigned_mask[i]]
    else:
        unmatched_article_indices = list(range(len(article_ids)))

    # 2) Discovered clusters: among unmatched articles, graph with edge if sim >= t_graph, then connected components
    if len(unmatched_article_indices) == 0:
        return clusters_out
    unm_embeddings = article_embeddings[unmatched_article_indices]
    n_unm = len(unmatched_article_indices)
    if n_unm == 1:
        clusters_out.append({
            "cluster_type": "discovered",
            "anchor_article_id": None,
            "article_ids": [article_ids[unmatched_article_indices[0]]],
        })
        return clusters_out
    sim_uu = svc.compute_similarity_matrix(unm_embeddings, unm_embeddings)
    edges = []
    for i in range(n_unm):
        for j in range(i + 1, n_unm):
            if sim_uu[i, j] >= t_graph:
                edges.append((i, j))
    components = _connected_components(n_unm, edges)
    for comp in components:
        cluster_article_ids = [article_ids[unmatched_article_indices[i]] for i in comp]
        clusters_out.append({
            "cluster_type": "discovered",
            "anchor_article_id": None,
            "article_ids": cluster_article_ids,
        })
    return clusters_out
