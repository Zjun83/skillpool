"""SkillGraph — DAG construction, topological sort, cycle detection, PPR ranking."""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


class CycleDetected(Exception):
    """Raised when a cycle is detected in the skill dependency graph."""
    def __init__(self, cycle_nodes: list[str]):
        self.cycle_nodes = cycle_nodes
        super().__init__(f"Cycle detected: {' → '.join(cycle_nodes)}")


class SkillGraph:
    """Directed Acyclic Graph for skill dependencies.

    Supports topological sort, cycle detection, and PPR-based importance ranking.

    Usage:
        graph = SkillGraph()
        graph.add_edge("S01", "S05a", weight=0.8)
        order = graph.topological_sort()  # ["S01", "S05a"]
        scores = graph.pagerank(["S01"])  # PPR importance scores
    """

    def __init__(self) -> None:
        self._adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
        self._nodes: set[str] = set()
        self._in_degree: dict[str, int] = defaultdict(int)

    @property
    def nodes(self) -> set[str]:
        return set(self._nodes)

    def add_node(self, node: str) -> None:
        """Add a node without edges."""
        self._nodes.add(node)
        if node not in self._in_degree:
            self._in_degree[node] = 0

    def add_edge(self, source: str, target: str, weight: float = 1.0) -> None:
        """Add a directed edge source → target."""
        self.add_node(source)
        self.add_node(target)
        self._adj[source].append((target, weight))
        self._in_degree[target] += 1

    def get_edges(self) -> list[tuple[str, str, float]]:
        """Return all edges as (source, target, weight) tuples."""
        edges = []
        for src, targets in self._adj.items():
            for tgt, w in targets:
                edges.append((src, tgt, w))
        return edges

    def get_dependencies(self, node: str) -> list[str]:
        """Get nodes that `node` depends on (upstream)."""
        deps = []
        for src, targets in self._adj.items():
            for tgt, _ in targets:
                if tgt == node:
                    deps.append(src)
        return deps

    def get_dependents(self, node: str) -> list[str]:
        """Get nodes that depend on `node` (downstream)."""
        return [tgt for tgt, _ in self._adj.get(node, [])]

    def topological_sort(self) -> list[str]:
        """Kahn's algorithm for topological sort. Raises CycleDetected if cycle exists."""
        in_deg = dict(self._in_degree)
        queue = [n for n in self._nodes if in_deg.get(n, 0) == 0]
        result: list[str] = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for tgt, _ in self._adj.get(node, []):
                in_deg[tgt] -= 1
                if in_deg[tgt] == 0:
                    queue.append(tgt)

        if len(result) != len(self._nodes):
            # Find cycle nodes
            remaining = self._nodes - set(result)
            raise CycleDetected(list(remaining))

        return result

    def has_cycle(self) -> bool:
        """Check if the graph contains a cycle."""
        try:
            self.topological_sort()
            return False
        except CycleDetected:
            return True

    def subgraph(self, nodes: set[str]) -> SkillGraph:
        """Extract a subgraph containing only the specified nodes."""
        g = SkillGraph()
        for node in nodes:
            if node in self._nodes:
                g.add_node(node)
        for src, targets in self._adj.items():
            if src in nodes:
                for tgt, w in targets:
                    if tgt in nodes:
                        g.add_edge(src, tgt, w)
        return g

    def to_sparse_matrix(self) -> tuple["scipy.sparse.csr_matrix", dict[str, int]]:
        """Convert graph to scipy sparse adjacency matrix.

        Returns:
            Tuple of (adjacency_matrix, node_to_index_mapping)

        Raises:
            ImportError if scipy/numpy not available
        """
        import numpy as np
        from scipy import sparse as sp

        node_list = sorted(self._nodes)
        node_to_idx = {n: i for i, n in enumerate(node_list)}
        n = len(node_list)

        rows, cols, weights = [], [], []
        for src, targets in self._adj.items():
            for tgt, w in targets:
                rows.append(node_to_idx[src])
                cols.append(node_to_idx[tgt])
                weights.append(w)

        if rows:
            adj = sp.csr_matrix(
                (np.array(weights, dtype=np.float64), (rows, cols)),
                shape=(n, n),
            )
        else:
            adj = sp.csr_matrix((n, n))

        return adj, node_to_idx

    def pagerank(
        self,
        seeds: list[str],
        alpha: float = 0.85,
        method: str = "auto",
    ) -> dict[str, float]:
        """Compute Personalized PageRank scores for seed nodes.

        Uses the 3-layer PPR implementation from skillpool.graph.ppr.

        Args:
            seeds: Seed skill IDs for personalization
            alpha: Damping factor (default 0.85)
            method: "python", "csr", "sknetwork", or "auto"

        Returns:
            Dict mapping skill_id → PPR score
        """
        from skillpool.graph.ppr import personalized_pagerank

        adj, node_to_idx = self.to_sparse_matrix()

        # Convert seed IDs to indices
        seed_indices = [node_to_idx[s] for s in seeds if s in node_to_idx]
        if not seed_indices:
            # No valid seeds — return uniform scores
            n = len(self._nodes)
            return {node: 1.0 / n for node in self._nodes} if n > 0 else {}

        scores_vec = personalized_pagerank(adj, seed_indices, alpha=alpha, method=method)

        # Map back to skill IDs
        idx_to_node = {i: n for n, i in node_to_idx.items()}
        return {idx_to_node[i]: float(scores_vec[i]) for i in range(len(scores_vec))}
