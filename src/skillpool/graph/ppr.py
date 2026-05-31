"""Personalized PageRank (PPR) — Three-layer implementation.

V1.1 Section 8.5 compliance:
  Layer 1: Pure Python — correctness verification only, not for production
  Layer 2: SciPy CSR sparse matrix — CPU production path for medium graphs
  Layer 3: scikit-network PageRank — fallback for large graphs when available

Unified interface:
    personalized_pagerank(adj, seeds, alpha=0.85, epsilon=1e-6, top_k=None)

Performance acceptance criteria (must record hardware + params):
  - 10K nodes × 50K edges: CSR path < 10ms
  - 100K nodes: CSR path < 50ms (P95), requires documented benchmarks
"""
from __future__ import annotations

__all__ = ["personalized_pagerank", "reverse_ppr"]

import numpy as np
from scipy import sparse as sp


def _validate_inputs(
    adj: sp.spmatrix,
    seeds: list[int] | dict[int, float],
) -> tuple[int, np.ndarray]:
    """
    Validate adjacency matrix and normalize seeds into a probability vector.

    Args:
        adj: Sparse adjacency matrix (n x n)
        seeds: Either list of node indices (uniform weight) or {node: weight} dict

    Returns:
        Tuple of (n_nodes, seed_vector)

    Raises:
        ValueError: If adj is not square or seeds contain invalid nodes
    """
    n = adj.shape[0]
    if adj.shape[1] != n:
        raise ValueError(f"Adjacency must be square, got {adj.shape}")

    seed_vec = np.zeros(n, dtype=np.float64)
    if isinstance(seeds, dict):
        total_w = sum(seeds.values())
        for node, weight in seeds.items():
            if node < 0 or node >= n:
                raise ValueError(f"Seed node {node} out of range [0, {n})")
            seed_vec[node] = weight / total_w
    else:
        for node in seeds:
            if node < 0 or node >= n:
                raise ValueError(f"Seed node {node} out of range [0, {n})")
        seed_vec[list(seeds)] = 1.0 / len(seeds)

    return n, seed_vec


# ── Layer 1: Pure Python (correctness baseline) ──

def _ppr_push_python(
    adj: sp.spmatrix,
    seeds_vec: np.ndarray,
    alpha: float,
    epsilon: float,
    max_iter: int = 200,
) -> np.ndarray:
    """
    Pure Python Push algorithm for PPR — small graph verification only.

    NOT for production use. Use CSR or sknetwork path.
    """
    n = len(seeds_vec)
    r = seeds_vec.copy()
    x = np.zeros(n, dtype=np.float64)

    if not sp.isspmatrix_csr(adj):
        adj = adj.tocsr()

    out_degree = np.array(adj.sum(axis=1)).flatten()
    dangling_mask = out_degree == 0

    for _ in range(max_iter):
        max_r = r.max()
        if max_r < epsilon:
            break
        for u in range(n):
            threshold = max(out_degree[u], 1) * epsilon
            if r[u] > threshold:
                push_amount = alpha * r[u]
                x[u] += push_amount
                remain = r[u] - push_amount
                r[u] = 0

                if not dangling_mask[u]:
                    degree_u = out_degree[u]
                    share = remain / degree_u
                    row_start = adj.indptr[u]
                    row_end = adj.indptr[u + 1]
                    for idx in range(row_start, row_end):
                        v = adj.indices[idx]
                        r[v] += share
                else:
                    share = remain / n
                    r += share

    x += r
    return x


# ── Layer 2: SciPy CSR Sparse Matrix (production CPU path) ──

def _ppr_csr_power_iteration(
    adj: sp.spmatrix,
    seeds_vec: np.ndarray,
    alpha: float,
    epsilon: float,
    max_iter: int = 100,
) -> np.ndarray:
    """
    Power iteration using SciPy CSR sparse matrix for medium graphs.

    This is the recommended production path for graphs up to ~500K nodes.
    """
    n = len(seeds_vec)
    if not sp.isspmatrix_csr(adj):
        adj = adj.tocsr()

    # Build column-stochastic transition matrix M = D^-1 * A^T
    out_degree_raw = np.array(adj.sum(axis=1)).flatten().astype(np.float64)
    dangling_mask = out_degree_raw == 0
    out_degree = out_degree_raw.copy()
    out_degree[out_degree == 0] = 1.0
    d_inv = sp.diags(1.0 / out_degree, format="csr")
    mt = adj.T.dot(d_inv)  # M^T for left-multiplication

    p_prev = seeds_vec.copy()

    for _iteration in range(max_iter):
        mt_p = mt.dot(p_prev)
        p = alpha * seeds_vec + (1.0 - alpha) * mt_p

        # Dangling-node correction
        if dangling_mask.any():
            dangling_mass = p_prev[dangling_mask].sum()
            if dangling_mass > 0:
                p += (1.0 - alpha) * dangling_mass / n

        delta = np.abs(p - p_prev).sum()
        if delta < epsilon * n:
            break
        p_prev = p

    return p


# ── Layer 3: scikit-network (optional, large graphs) ──

def _ppr_sknetwork(
    adj: sp.spmatrix,
    seeds_vec: np.ndarray,
    alpha: float,
) -> np.ndarray:
    """
    Use scikit-network's PageRank for large graphs.

    Falls back to CSR power iteration if sknetwork is not installed.
    """
    try:
        from sknetwork.ranking import PageRank
        pr = PageRank(damping_factor=alpha, solver="piteration")
        scores = pr.fit_transform(adj)
        if seeds_vec.sum() > 0:
            scores = alpha * seeds_vec + (1 - alpha) * scores
        return scores
    except ImportError:
        return _ppr_csr_power_iteration(adj, seeds_vec, alpha, 1e-6)


# ── Unified Public API ──

def personalized_pagerank(
    adj: sp.spmatrix,
    seeds: list[int] | dict[int, float],
    alpha: float = 0.85,
    epsilon: float = 1e-6,
    top_k: int | None = None,
    method: str = "auto",
) -> np.ndarray:
    """
    Compute Personalized PageRank scores for seed nodes.

    Args:
        adj: Sparse adjacency matrix (n x n), scipy.sparse format
        seeds: Seed nodes — list (uniform weight) or {node: weight} dict
        alpha: Teleport probability (damping factor), default 0.85
        epsilon: Convergence tolerance, default 1e-6
        top_k: If set, return only top-k scores (approximate for large graphs)
        method: "python" | "csr" | "sknetwork" | "auto" (default: auto-select)

    Returns:
        PPR score vector (n,)

    Raises:
        ValueError: For invalid inputs
    """
    n, seeds_vec = _validate_inputs(adj, seeds)

    # Auto-select method based on graph size
    if method == "auto":
        if n < 1000:
            method = "python"
        elif n < 500000:
            method = "csr"
        else:
            method = "sknetwork"

    if method == "python":
        scores = _ppr_push_python(adj, seeds_vec, alpha, epsilon)
    elif method == "csr":
        scores = _ppr_csr_power_iteration(adj, seeds_vec, alpha, epsilon)
    elif method == "sknetwork":
        scores = _ppr_sknetwork(adj, seeds_vec, alpha)
    else:
        raise ValueError(f"Unknown method: {method}")

    # Normalize
    s = scores.sum()
    if s > 0:
        scores /= s

    if top_k is not None:
        indices = np.argpartition(scores, -top_k)[-top_k:]
        mask = np.zeros(n, dtype=np.float64)
        mask[indices] = scores[indices]
        mask /= mask.sum()
        return mask

    return scores


# ── Reverse PPR (V1.1 Section 8.5 target-centric query path) ──

def reverse_ppr(
    adj: sp.spmatrix,
    target: int,
    alpha: float = 0.85,
    epsilon: float = 1e-6,
) -> np.ndarray:
    """
    Compute Reverse PPR for a target node.

    Equivalent to running PPR on the transpose graph with the target as seed.
    Used for "which skills contribute most to this skill?" queries.

    Args:
        adj: Sparse adjacency matrix (n x n)
        target: Target node index
        alpha: Teleport probability
        epsilon: Convergence tolerance

    Returns:
        Reverse PPR score vector (n,)
    """
    return personalized_pagerank(
        adj.T.tocsr() if hasattr(adj, 'T') else adj.transpose().tocsr(),
        [target],
        alpha=alpha,
        epsilon=epsilon,
        method="csr",
    )
