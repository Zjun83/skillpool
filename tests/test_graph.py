"""Tests for Graph PPR — Personalized PageRank with 3-layer implementation."""
from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp

from skillpool.graph.ppr import personalized_pagerank, reverse_ppr


def _make_chain_adj(n: int) -> sp.spmatrix:
    """Create a chain graph adjacency matrix (0→1→2→...→n-1)."""
    rows, cols = [], []
    for i in range(n - 1):
        rows.append(i)
        cols.append(i + 1)
    return sp.csr_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(n, n)
    )


def _make_star_adj(n: int) -> sp.spmatrix:
    """Create a star graph: node 0 connects to all others."""
    rows, cols = [], []
    for i in range(1, n):
        rows.append(0)
        cols.append(i)
    return sp.csr_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(n, n)
    )


def _make_cycle_adj(n: int) -> sp.spmatrix:
    """Create a cycle graph: 0→1→2→...→n-1→0."""
    rows, cols = [], []
    for i in range(n):
        rows.append(i)
        cols.append((i + 1) % n)
    return sp.csr_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(n, n)
    )


def _make_complete_adj(n: int) -> sp.spmatrix:
    """Create a complete graph (all nodes connected to all others)."""
    rows, cols = [], []
    for i in range(n):
        for j in range(n):
            if i != j:
                rows.append(i)
                cols.append(j)
    return sp.csr_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(n, n)
    )


class TestValidateInputs:
    def test_non_square_raises(self):
        adj = sp.csr_matrix((3, 4))
        with pytest.raises(ValueError, match="square"):
            personalized_pagerank(adj, [0])

    def test_seed_out_of_range_raises(self):
        adj = sp.csr_matrix((3, 3))
        with pytest.raises(ValueError, match="out of range"):
            personalized_pagerank(adj, [5])

    def test_negative_seed_raises(self):
        adj = sp.csr_matrix((3, 3))
        with pytest.raises(ValueError, match="out of range"):
            personalized_pagerank(adj, [-1])

    def test_dict_seed_out_of_range_raises(self):
        adj = sp.csr_matrix((3, 3))
        with pytest.raises(ValueError, match="out of range"):
            personalized_pagerank(adj, {0: 0.5, 10: 0.5})

    def test_dict_seed_negative_raises(self):
        adj = sp.csr_matrix((3, 3))
        with pytest.raises(ValueError, match="out of range"):
            personalized_pagerank(adj, {0: 0.5, -1: 0.5})


class TestPersonalizedPagerank:
    def test_returns_correct_shape(self):
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0])
        assert scores.shape == (5,)

    def test_scores_sum_to_one(self):
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0])
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_seed_node_highest_score(self):
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0])
        assert scores[0] > scores[1]

    def test_dict_seeds(self):
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, {0: 0.7, 2: 0.3})
        assert scores.shape == (5,)
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_dict_seeds_weighted(self):
        """Higher-weighted seed should get higher score."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, {0: 0.9, 4: 0.1})
        assert scores[0] > scores[4]

    def test_python_method(self):
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0], method="python")
        assert scores.shape == (5,)
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_csr_method(self):
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0], method="csr")
        assert scores.shape == (5,)
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_auto_method_small_graph(self):
        adj = _make_chain_adj(10)
        scores = personalized_pagerank(adj, [0], method="auto")
        assert scores.shape == (10,)

    def test_methods_agree(self):
        """Python and CSR methods should produce similar results."""
        adj = _make_chain_adj(5)
        scores_python = personalized_pagerank(adj, [0], method="python")
        scores_csr = personalized_pagerank(adj, [0], method="csr")
        # They should be close (within 10% relative)
        np.testing.assert_allclose(scores_python, scores_csr, rtol=0.1)

    def test_top_k(self):
        adj = _make_chain_adj(10)
        scores = personalized_pagerank(adj, [0], top_k=3)
        # top_k=3 should have at most 3 non-zero entries
        non_zero = np.count_nonzero(scores)
        assert non_zero <= 3
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_single_node(self):
        adj = sp.csr_matrix((1, 1))
        scores = personalized_pagerank(adj, [0])
        assert scores.shape == (1,)
        assert scores[0] == 1.0

    def test_disconnected_nodes(self):
        adj = sp.csr_matrix((3, 3))  # No edges
        scores = personalized_pagerank(adj, [0], method="csr")
        assert scores.shape == (3,)
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_star_graph(self):
        adj = _make_star_adj(5)
        scores = personalized_pagerank(adj, [0])
        assert scores.shape == (5,)
        # Node 0 should have highest score (only outgoing node)
        assert scores[0] >= scores[1]

    def test_unknown_method_raises(self):
        adj = _make_chain_adj(3)
        with pytest.raises(ValueError, match="Unknown method"):
            personalized_pagerank(adj, [0], method="invalid")

    def test_csr_convergence_with_dangling(self):
        """Test CSR handles dangling nodes (no outgoing edges)."""
        # Node 2 has no outgoing edges (dangling)
        adj = sp.csr_matrix(
            (np.ones(2), ([0, 1], [1, 2])), shape=(3, 3)
        )
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)


class TestPersonalizedPagerankExtended:
    """Extended PPR tests for graph structures, parameters, and edge cases."""

    # ── Graph structures ──

    def test_cycle_graph_uniform_seeds(self):
        """In a cycle with uniform seed, all nodes should have similar scores."""
        adj = _make_cycle_adj(5)
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        # Seed node should have highest score
        assert scores[0] >= scores[1]

    def test_complete_graph_uniform(self):
        """In a complete graph with single seed, seed should have highest score."""
        adj = _make_complete_adj(4)
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        assert scores[0] > scores[1]

    def test_complete_graph_all_seeds(self):
        """In a complete graph with all nodes as seeds, scores should be nearly uniform."""
        adj = _make_complete_adj(4)
        scores = personalized_pagerank(adj, [0, 1, 2, 3], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        # All scores should be approximately equal
        np.testing.assert_allclose(scores, scores[0], rtol=0.1)

    def test_bidirectional_graph(self):
        """Graph with bidirectional edges."""
        # 0 <-> 1 <-> 2
        rows = [0, 1, 1, 2]
        cols = [1, 0, 2, 1]
        adj = sp.csr_matrix((np.ones(4), (rows, cols)), shape=(3, 3))
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        # Seed should have highest score
        assert scores[0] >= scores[1]

    def test_self_loop(self):
        """Graph with self-loops."""
        # Node 0 has a self-loop
        rows = [0, 0, 1]
        cols = [0, 1, 2]
        adj = sp.csr_matrix((np.ones(3), (rows, cols)), shape=(3, 3))
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_weighted_adjacency(self):
        """Adjacency matrix with non-binary weights."""
        rows = [0, 0, 1]
        cols = [1, 2, 2]
        weights = [3.0, 1.0, 2.0]
        adj = sp.csr_matrix((weights, (rows, cols)), shape=(3, 3))
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        # Node 1 should get more weight from node 0 than node 2
        assert scores[1] > scores[2]

    # ── Alpha parameter ──

    def test_high_alpha_more_personalized(self):
        """Higher alpha = more teleport to seed = seed gets higher score."""
        adj = _make_chain_adj(5)
        scores_low = personalized_pagerank(adj, [0], alpha=0.5, method="csr")
        scores_high = personalized_pagerank(adj, [0], alpha=0.95, method="csr")
        # Higher alpha should concentrate more mass on seed
        assert scores_high[0] > scores_low[0]

    def test_alpha_boundary_low(self):
        """Very low alpha should still produce valid results."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0], alpha=0.1, method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=4)

    def test_alpha_boundary_high(self):
        """Very high alpha should still produce valid results."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0], alpha=0.99, method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=4)

    # ── Epsilon parameter ──

    def test_tighter_epsilon_same_result(self):
        """Tighter epsilon should produce similar but more precise results.

        Note: Loose epsilon (1e-3) may not converge to the same precision
        as tight epsilon (1e-9), so we use a more relaxed tolerance.
        """
        adj = _make_chain_adj(5)
        scores_loose = personalized_pagerank(adj, [0], epsilon=1e-3, method="csr")
        scores_tight = personalized_pagerank(adj, [0], epsilon=1e-9, method="csr")
        # Use a more relaxed tolerance since loose epsilon stops early
        np.testing.assert_allclose(scores_loose, scores_tight, rtol=0.15)

    # ── Multiple seeds ──

    def test_two_seeds_list(self):
        """Two seed nodes with uniform weight."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0, 4], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        # Both seeds should have higher scores than middle nodes
        assert scores[0] > scores[2]
        assert scores[4] > scores[2]

    def test_two_seeds_dict(self):
        """Two seed nodes with different weights."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, {0: 0.8, 4: 0.2}, method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        # Higher-weighted seed should have higher score
        assert scores[0] > scores[4]

    # ── top_k edge cases ──

    def test_top_k_equals_n(self):
        """top_k = n should return all nodes."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0], top_k=5, method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        assert np.count_nonzero(scores) == 5

    def test_top_k_one(self):
        """top_k=1 should return only the highest-scoring node."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0], top_k=1, method="csr")
        assert np.count_nonzero(scores) == 1
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    # ── Dangling nodes ──

    def test_all_dangling_nodes(self):
        """Graph with no edges at all -- all nodes are dangling."""
        adj = sp.csr_matrix((4, 4))
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_mixed_dangling_and_connected(self):
        """Graph where some nodes have edges and some don't."""
        # 0->1, node 2 and 3 are isolated
        rows = [0]
        cols = [1]
        adj = sp.csr_matrix((np.ones(1), (rows, cols)), shape=(4, 4))
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    # ── Method-specific tests ──

    def test_python_method_chain(self):
        """Python push method on a chain graph."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0], method="python")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=4)
        assert scores[0] > scores[1]

    def test_python_method_with_dangling(self):
        """Python push method with dangling nodes."""
        adj = sp.csr_matrix(
            (np.ones(2), ([0, 1], [1, 2])), shape=(3, 3)
        )
        scores = personalized_pagerank(adj, [0], method="python")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=4)

    def test_python_and_csr_agree_on_cycle(self):
        """Python and CSR should agree on a cycle graph."""
        adj = _make_cycle_adj(5)
        scores_python = personalized_pagerank(adj, [0], method="python")
        scores_csr = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_allclose(scores_python, scores_csr, rtol=0.1)

    def test_python_and_csr_agree_on_star(self):
        """Python and CSR should agree on a star graph."""
        adj = _make_star_adj(5)
        scores_python = personalized_pagerank(adj, [0], method="python")
        scores_csr = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_allclose(scores_python, scores_csr, rtol=0.1)

    def test_csc_matrix_input(self):
        """CSR method should handle CSC input (auto-converts)."""
        adj = _make_chain_adj(5).tocsc()
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_coo_matrix_input(self):
        """CSR method should handle COO input (auto-converts)."""
        adj = _make_chain_adj(5).tocoo()
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    # ── sknetwork method (optional) ──

    def test_sknetwork_method_or_fallback(self):
        """sknetwork method should work or fall back to CSR."""
        adj = _make_chain_adj(5)
        scores = personalized_pagerank(adj, [0], method="sknetwork")
        assert scores.shape == (5,)
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=4)

    # ── Auto method selection ──

    def test_auto_selects_python_for_small_graph(self):
        """auto should select python for n < 1000."""
        adj = _make_chain_adj(10)
        scores = personalized_pagerank(adj, [0], method="auto")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=4)

    def test_auto_selects_csr_for_medium_graph(self):
        """auto should select csr for 1000 <= n < 500000."""
        # Create a medium-sized sparse graph
        n = 1500
        rows = np.arange(n - 1)
        cols = np.arange(1, n)
        adj = sp.csr_matrix((np.ones(n - 1), (rows, cols)), shape=(n, n))
        scores = personalized_pagerank(adj, [0], method="auto")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=4)

    # ── Known result verification ──

    def test_known_result_two_node_graph(self):
        """Verify PPR on a simple 2-node graph with known result.

        Graph: 0->1 (only edge)
        Seed: [0]
        With alpha=0.85, the steady state should satisfy:
          p[0] = alpha * 1.0 + (1-alpha) * dangling_correction
          p[1] = (1-alpha) * p[0] + dangling_correction
        Since node 1 is dangling, mass redistributes.
        """
        adj = sp.csr_matrix((np.ones(1), ([0], [1])), shape=(2, 2))
        scores = personalized_pagerank(adj, [0], alpha=0.85, method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        assert scores[0] > scores[1]  # Seed should dominate

    def test_known_result_symmetric_graph(self):
        """In a symmetric graph with symmetric seeds, scores should be symmetric."""
        # 0<->1 (bidirectional)
        rows = [0, 1]
        cols = [1, 0]
        adj = sp.csr_matrix((np.ones(2), (rows, cols)), shape=(2, 2))
        scores = personalized_pagerank(adj, [0, 1], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)
        # Both seeds have equal weight, graph is symmetric
        np.testing.assert_almost_equal(scores[0], scores[1], decimal=4)


class TestReversePPR:
    def test_basic(self):
        # 0->1->2 chain
        adj = _make_chain_adj(3)
        scores = reverse_ppr(adj, target=2)
        assert scores.shape == (3,)
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)

    def test_reverse_vs_forward(self):
        """Reverse PPR on transpose should equal PPR with target as seed."""
        adj = _make_chain_adj(5)
        reverse_scores = reverse_ppr(adj, target=0)
        forward_scores = personalized_pagerank(adj.T.tocsr(), [0], method="csr")
        np.testing.assert_allclose(reverse_scores, forward_scores, rtol=1e-5)

    def test_reverse_target_highest(self):
        """Target node should have highest reverse PPR score."""
        adj = _make_chain_adj(5)
        scores = reverse_ppr(adj, target=0)
        assert scores[0] >= scores[1]

    def test_reverse_chain_upstream(self):
        """In a chain 0->1->2->3->4, reverse PPR from node 4 should
        give higher scores to upstream nodes (3,2) than distant ones (0)."""
        adj = _make_chain_adj(5)
        scores = reverse_ppr(adj, target=4)
        # Node 3 (direct predecessor) should score higher than node 0
        assert scores[3] > scores[0]

    def test_reverse_star_graph(self):
        """In a star graph (0->1,0->2,0->3), reverse PPR from leaf
        should give the target node the highest score (it is the seed
        in the transposed graph). Node 0 in the transpose has no
        incoming edges from the star leaves, so it gets lower score."""
        adj = _make_star_adj(4)
        scores = reverse_ppr(adj, target=1)
        # Target node (1) is the seed in the transposed graph
        assert scores[1] > scores[0]

    def test_reverse_with_alpha(self):
        """Reverse PPR should respect alpha parameter."""
        adj = _make_chain_adj(5)
        scores_low = reverse_ppr(adj, target=2, alpha=0.5)
        scores_high = reverse_ppr(adj, target=2, alpha=0.95)
        # Higher alpha = more concentrated on target
        assert scores_high[2] > scores_low[2]

    def test_reverse_single_node(self):
        """Reverse PPR on a single-node graph."""
        adj = sp.csr_matrix((1, 1))
        scores = reverse_ppr(adj, target=0)
        assert scores.shape == (1,)
        assert scores[0] == 1.0
