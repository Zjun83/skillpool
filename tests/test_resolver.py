"""Tests for SkillResolver — skill chain resolution engine."""
from __future__ import annotations

import pytest

from skillpool.resolver import SkillResolver, register_skill, clear_registry
from skillpool.resolver.models import (
    ConflictSeverity,
    ConflictType,
    DagEdgeType,
    Domain,
    ResolveStatus,
    ResolveStrategy,
    SkillResolveRequest,
    SkillResolveResponse,
)
from skillpool.resolver.skill_graph import SkillGraph, CycleDetected


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the global skill registry before each test."""
    clear_registry()
    yield
    clear_registry()


# === Schema-Aligned Model Tests ===

class TestResolveRequestSchemaFields:
    """Test new schema-aligned fields on SkillResolveRequest."""

    def test_task_description(self):
        req = SkillResolveRequest(
            skill_ids=["S01"],
            task_description="Refactor authentication module",
        )
        assert req.task_description == "Refactor authentication module"

    def test_domain_enum(self):
        req = SkillResolveRequest(
            skill_ids=["S01"],
            domain=Domain.SECURITY_FIX,
        )
        assert req.domain == Domain.SECURITY_FIX

    def test_trace_id(self):
        req = SkillResolveRequest(
            skill_ids=["S01"],
            trace_id="0af7651916cd43dd8448eb211c80319c",
        )
        assert req.trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_plan_id(self):
        req = SkillResolveRequest(
            skill_ids=["S01"],
            plan_id="plan-001",
        )
        assert req.plan_id == "plan-001"

    def test_domain_none_by_default(self):
        req = SkillResolveRequest(skill_ids=["S01"])
        assert req.domain is None


class TestResolveResponseSchemaFields:
    """Test new schema-aligned fields on SkillResolveResponse."""

    def test_status_resolved(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert resp.status == ResolveStatus.RESOLVED

    def test_status_partial(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01", "S_MISSING"]))
        assert resp.status == ResolveStatus.PARTIAL

    def test_status_unresolved(self):
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S_MISSING_1", "S_MISSING_2"]))
        assert resp.status == ResolveStatus.UNRESOLVED

    def test_health_scores_mapping(self):
        register_skill("S01", {"name": "A", "dependencies": [], "health_score": 0.9})
        register_skill("S02", {"name": "B", "dependencies": [], "health_score": 0.7})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01", "S02"]))
        assert "S01" in resp.health_scores
        assert resp.health_scores["S01"] == 0.9
        assert resp.health_scores["S02"] == 0.7

    def test_feasibility_score(self):
        register_skill("S01", {"name": "A", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert 0.0 <= resp.feasibility_score <= 1.0
        assert resp.feasibility_score > 0.0

    def test_feasibility_penalized_by_conflicts(self):
        register_skill("S01", {"name": "A", "dependencies": [], "health_score": 1.0,
                                "namespaces": ["auth"], "dimension": "security"})
        register_skill("S02", {"name": "A2", "dependencies": [], "health_score": 1.0,
                                "namespaces": ["auth"], "dimension": "security"})
        resolver = SkillResolver(conflict_threshold=0.01)
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01", "S02"]))
        # With conflicts, feasibility should be lower than without
        assert resp.feasibility_score < 1.0


class TestResolvedSkillSchemaFields:
    """Test new schema-aligned fields on ResolvedSkill."""

    def test_version_field(self):
        register_skill("S01", {"name": "Test", "version": "2.1.0", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert resp.resolved[0].version == "2.1.0"

    def test_default_version(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert resp.resolved[0].version == "1.0.0"

    def test_estimated_tokens(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0, "estimated_tokens": 500})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert resp.resolved[0].estimated_tokens == 500

    def test_provides_tags(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0, "provides": ["auth", "jwt"]})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert "auth" in resp.resolved[0].provides


class TestDagEdgeType:
    """Test DagEdge type enum."""

    def test_edge_type_in_response(self):
        register_skill("S01", {"name": "A", "dependencies": [], "health_score": 1.0, "weight": 0.8})
        register_skill("S02", {"name": "B", "dependencies": ["S01"], "health_score": 1.0, "weight": 0.6})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01", "S02"]))
        assert len(resp.dag_edges) >= 1
        assert resp.dag_edges[0].type == DagEdgeType.DEPENDS_ON


class TestConflictTypeAndRecommendation:
    """Test Conflict conflict_type and recommendation fields."""

    def test_conflict_type_populated(self):
        register_skill("S01", {"name": "Auth", "dependencies": [], "health_score": 1.0,
                                "namespaces": ["auth"], "dimension": "security"})
        register_skill("S02", {"name": "Auth2", "dependencies": [], "health_score": 1.0,
                                "namespaces": ["auth"], "dimension": "security"})
        resolver = SkillResolver(conflict_threshold=0.01)
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01", "S02"]))
        if resp.conflicts:
            assert resp.conflicts[0].conflict_type == ConflictType.NAMESPACE_OVERLAP
            assert resp.conflicts[0].recommendation != ""


# === Core Resolution Tests ===

class TestSkillResolver:
    """Core resolution pipeline tests."""

    def test_resolve_single_skill(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert resp.total_skills == 1
        assert resp.resolved[0].skill_id == "S01"
        assert resp.error is None

    def test_resolve_with_dependencies(self):
        register_skill("S01", {"name": "Root", "dependencies": [], "health_score": 1.0, "weight": 1.0})
        register_skill("S05a", {"name": "Child", "dependencies": ["S01"], "health_score": 1.0, "weight": 0.8})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S05a"]))
        assert resp.total_skills == 2

    def test_resolve_missing_skill(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S_MISSING"]))
        assert resp.error == "no_skills_found"

    def test_exclude_skills(self):
        register_skill("S01", {"name": "A", "dependencies": [], "health_score": 1.0})
        register_skill("S02", {"name": "B", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01", "S02"], exclude_skills=["S02"]))
        assert resp.total_skills == 1
        assert "S02" in resp.excluded

    def test_max_skills_constraint(self):
        for i in range(5):
            register_skill(f"S{i}", {"name": f"Skill-{i}", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S0", "S1", "S2", "S3", "S4"], max_skills=2))
        assert resp.total_skills <= 2

    def test_health_score_filter(self):
        register_skill("S01", {"name": "Healthy", "dependencies": [], "health_score": 0.9})
        register_skill("S02", {"name": "Unhealthy", "dependencies": [], "health_score": 0.3})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01", "S02"], min_health_score=0.6))
        assert resp.total_skills == 1
        assert resp.resolved[0].skill_id == "S01"

    def test_degraded_response_on_circuit_open(self):
        resolver = SkillResolver()
        # Force circuit open by recording failures
        for _ in range(10):
            resolver._circuit.record_failure()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert resp.degraded is True
        assert resp.error == "circuit_open"

    def test_rate_limit(self):
        resolver = SkillResolver(rate_max_requests=2, rate_window_seconds=1.0)
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        # First two should succeed
        resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        # Third should be rate limited
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert resp.error == "rate_limit_exceeded"
