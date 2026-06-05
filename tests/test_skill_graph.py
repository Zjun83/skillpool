"""Tests for SkillGraph — DAG construction, topological sort, cycle detection."""

import pytest

from skillpool.resolver.skill_graph import CycleDetected, SkillGraph


class TestAddNodesAndEdges:
    def test_add_node(self) -> None:
        g = SkillGraph()
        g.add_node("A")
        assert "A" in g.nodes

    def test_add_edge(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B")
        assert "A" in g.nodes
        assert "B" in g.nodes
        assert g.get_dependents("A") == ["B"]
        assert g.get_dependencies("B") == ["A"]

    def test_get_edges(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B", weight=0.8)
        g.add_edge("B", "C", weight=0.5)
        edges = g.get_edges()
        assert len(edges) == 2
        assert ("A", "B", 0.8) in edges
        assert ("B", "C", 0.5) in edges


class TestTopologicalSort:
    def test_linear_chain(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        order = g.topological_sort()
        assert order.index("A") < order.index("B") < order.index("C")

    def test_diamond(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("A", "C")
        g.add_edge("B", "D")
        g.add_edge("C", "D")
        order = g.topological_sort()
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_disconnected_nodes(self) -> None:
        g = SkillGraph()
        g.add_node("X")
        g.add_node("Y")
        g.add_edge("A", "B")
        order = g.topological_sort()
        assert set(order) == {"X", "Y", "A", "B"}

    def test_single_node(self) -> None:
        g = SkillGraph()
        g.add_node("A")
        assert g.topological_sort() == ["A"]


class TestCycleDetection:
    def test_no_cycle(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        assert g.has_cycle() is False

    def test_simple_cycle(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "A")
        assert g.has_cycle() is True

    def test_three_node_cycle(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "A")
        assert g.has_cycle() is True

    def test_cycle_raises_exception(self) -> None:
        g = SkillGraph()
        g.add_edge("X", "Y")
        g.add_edge("Y", "X")
        with pytest.raises(CycleDetected) as exc_info:
            g.topological_sort()
        assert "X" in exc_info.value.cycle_nodes or "Y" in exc_info.value.cycle_nodes


class TestSubgraph:
    def test_subgraph_filters_nodes(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "D")
        sub = g.subgraph({"A", "B", "C"})
        assert sub.nodes == {"A", "B", "C"}
        assert len(sub.get_edges()) == 2

    def test_subgraph_preserves_edges(self) -> None:
        g = SkillGraph()
        g.add_edge("A", "B", weight=0.7)
        sub = g.subgraph({"A", "B"})
        edges = sub.get_edges()
        assert len(edges) == 1
        assert edges[0] == ("A", "B", 0.7)
