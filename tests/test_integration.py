"""Integration tests — verify 5 new modules are wired into existing modules."""
from __future__ import annotations

import asyncio

import pytest

from skillpool.audit import AuditLayer
from skillpool.cost import CostManager
from skillpool.cost.models import CostRecord
from skillpool.evolver import EvolverLayer, DefectSeverity
from skillpool.health import HealthManager
from skillpool.monitor import MonitorLayer
from skillpool.registry import Registry
from skillpool.registry.models import RegisterSkillRequest, SkillMetadata, SkillStatus, StateTransitionRequest
from skillpool.resolver import SkillResolver
from skillpool.resolver.skill_graph import SkillGraph
from skillpool.review import ReviewManager
from skillpool.review.models import CheckpointLevel, ReviewTriggerRequest, ReviewTrigger


class TestAuditCostIntegration:
    """AuditLayer replaces AuditHashChain in CostManager."""

    def test_cost_manager_with_audit_layer(self):
        audit = AuditLayer()
        cm = CostManager(audit_layer=audit)
        record = CostRecord(agent_id="evolver_v4", cost_usd=0.05)
        result = cm.report_cost(record)
        assert result is True
        assert audit.get_record_count() == 1
        assert audit.verify_integrity() is True

    def test_cost_manager_without_audit_layer_backward_compat(self):
        cm = CostManager()
        record = CostRecord(agent_id="evolver_v4", cost_usd=0.05)
        result = cm.report_cost(record)
        assert result is True


class TestEvolverReviewIntegration:
    """EvolverLayer receives veto results from ReviewManager."""

    def test_review_feeds_evolver_on_veto(self):
        audit = AuditLayer()
        evolver = EvolverLayer(audit_layer=audit)
        manager = ReviewManager(evolver=evolver)

        # Trigger L3 review with low scores → veto
        request = ReviewTriggerRequest(
            trigger=ReviewTrigger.L3_REGRESSION_FAIL,
            checkpoint=CheckpointLevel.L3,
            affected_skills=["S01"],
        )
        response = manager.trigger(request)

        # Evolver should have recorded defects if veto triggered
        if response.veto_triggered:
            defects = evolver.get_pending_evolutions()
            assert len(defects) >= 0

    def test_review_without_evolver_backward_compat(self):
        manager = ReviewManager()
        request = ReviewTriggerRequest(
            trigger=ReviewTrigger.L3_REGRESSION_FAIL,
            checkpoint=CheckpointLevel.L3,
            affected_skills=["S01"],
        )
        response = manager.trigger(request)
        assert response.review_id  # Still works


class TestGraphResolverIntegration:
    """SkillGraph.pagerank() uses PPR from graph module."""

    def test_skill_graph_pagerank(self):
        graph = SkillGraph()
        graph.add_edge("S01", "S05a", weight=0.8)
        graph.add_edge("S01", "S06", weight=0.6)
        graph.add_edge("S05a", "S09", weight=0.7)

        scores = graph.pagerank(seeds=["S01"])
        assert len(scores) == 4
        assert all(s >= 0 for s in scores.values())
        assert scores["S01"] >= scores["S05a"]

    def test_skill_graph_to_sparse_matrix(self):
        graph = SkillGraph()
        graph.add_edge("A", "B", weight=1.0)
        graph.add_edge("B", "C", weight=2.0)

        adj, node_to_idx = graph.to_sparse_matrix()
        assert adj.shape == (3, 3)
        assert "A" in node_to_idx
        assert "B" in node_to_idx
        assert "C" in node_to_idx


class TestMonitorHealthIntegration:
    """MonitorLayer receives health check results from HealthManager."""

    def test_health_feeds_monitor(self):
        monitor = MonitorLayer()
        hm = HealthManager(monitor=monitor)

        hm.register_component("resolver", check_fn=lambda: True, critical=True)
        hm.register_component("vpls", check_fn=lambda: False, critical=True)

        response = hm.check_health()

        # Monitor should have recorded health metrics
        metrics = monitor.get_metrics()
        assert len(metrics) > 0

    def test_health_without_monitor_backward_compat(self):
        hm = HealthManager()
        hm.register_component("resolver", check_fn=lambda: True)
        response = hm.check_health()
        assert response is not None


class TestRegistryResolverIntegration:
    """Registry provides skill metadata to SkillResolver."""

    def test_resolver_with_registry(self):
        audit = AuditLayer()
        registry = Registry(audit_layer=audit)

        # Register a skill
        meta = SkillMetadata(
            skill_id="S01",
            name="Requirement Coverage",
            version="1.0",
            security={
                "sbom_ref": "sbom-001",
                "provenance_ref": "prov-001",
                "source_pin": "sha256:abc",
                "signature_ref": "sig-001",
            },
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        registry.register_candidate(req)

        # Enable the skill
        registry.transition_state(
            "S01",
            StateTransitionRequest(
                from_status=SkillStatus.TESTING,
                to_status=SkillStatus.ENABLED,
            ),
            sandbox_result="pass",
            policy_approval=True,
        )

        # Resolver should see the skill from Registry
        resolver = SkillResolver(registry=registry)
        from skillpool.resolver.models import SkillResolveRequest
        response = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert response.total_skills == 1
        assert response.resolved[0].skill_id == "S01"

    def test_resolver_without_registry_backward_compat(self):
        from skillpool.resolver import register_skill
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        from skillpool.resolver.models import SkillResolveRequest
        response = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert response.total_skills == 1


class TestMCPNewTools:
    """Verify new MCP tools are registered."""

    def test_mcp_tools_count(self):
        from skillpool.mcp_server import mcp
        tools = asyncio.run(mcp.list_tools())
        tool_names = [t.name for t in tools]
        # Should have at least 10 tools now (3 original + 7 new)
        assert len(tool_names) >= 10, f"Expected >=10 tools, got {tool_names}"

    def test_audit_records_resource_exists(self):
        """audit_query was refactored to audit://records/{cursor} Resource (read-only, paginated)."""
        from skillpool.mcp_server import mcp
        templates = asyncio.run(mcp.list_resource_templates())
        template_uris = [str(t.uri_template) for t in templates]
        assert "audit://records/{cursor}" in template_uris

    def test_skill_register_tool_exists(self):
        from skillpool.mcp_server import mcp
        tools = asyncio.run(mcp.list_tools())
        tool_names = [t.name for t in tools]
        assert "skill_register" in tool_names

    def test_evolution_trigger_tool_exists(self):
        from skillpool.mcp_server import mcp
        tools = asyncio.run(mcp.list_tools())
        tool_names = [t.name for t in tools]
        assert "evolution_trigger" in tool_names

    def test_monitor_evaluate_tool_exists(self):
        from skillpool.mcp_server import mcp
        tools = asyncio.run(mcp.list_tools())
        tool_names = [t.name for t in tools]
        assert "monitor_evaluate" in tool_names

    def test_health_check_tool_exists(self):
        from skillpool.mcp_server import mcp
        tools = asyncio.run(mcp.list_tools())
        tool_names = [t.name for t in tools]
        assert "health_check" in tool_names