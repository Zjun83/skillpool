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
    return sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))


def _make_star_adj(n: int) -> sp.spmatrix:
    """Create a star graph: node 0 connects to all others."""
    rows, cols = [], []
    for i in range(1, n):
        rows.append(0)
        cols.append(i)
    return sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))


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
        adj = sp.csr_matrix((np.ones(2), ([0, 1], [1, 2])), shape=(3, 3))
        scores = personalized_pagerank(adj, [0], method="csr")
        np.testing.assert_almost_equal(scores.sum(), 1.0, decimal=5)


class TestReversePPR:
    def test_basic(self):
        # 0→1→2 chain
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
