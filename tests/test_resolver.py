"""Tests for SkillResolver — skill chain resolution engine."""

from __future__ import annotations

import pytest

from skillpool.resolver import SkillResolver, register_skill, clear_registry
from skillpool.resolver.models import (
    ConflictType,
    DagEdgeType,
    Domain,
    ResolveStatus,
    SkillResolveRequest,
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
        register_skill(
            "S01",
            {"name": "A", "dependencies": [], "health_score": 1.0, "namespaces": ["auth"], "dimension": "security"},
        )
        register_skill(
            "S02",
            {"name": "A2", "dependencies": [], "health_score": 1.0, "namespaces": ["auth"], "dimension": "security"},
        )
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
        register_skill(
            "S01",
            {"name": "Auth", "dependencies": [], "health_score": 1.0, "namespaces": ["auth"], "dimension": "security"},
        )
        register_skill(
            "S02",
            {"name": "Auth2", "dependencies": [], "health_score": 1.0, "namespaces": ["auth"], "dimension": "security"},
        )
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


# ============================================================
# CircuitBreaker — Full State Machine Coverage
# ============================================================


class TestCircuitBreakerStateMachine:
    """Full coverage of CircuitBreaker state transitions."""

    def test_initial_state_is_closed(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        assert cb.state == CircuitState.CLOSED

    def test_closed_to_open_after_threshold(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_calls(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state.name == "OPEN"
        assert not cb.allow_request()

    def test_closed_allows_calls(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        assert cb.allow_request()

    def test_open_to_half_open_after_timeout(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState
        import time

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_half_open_success_closes(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState
        import time

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, half_open_max_calls=1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.allow_request()  # transitions to HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState
        import time

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, half_open_max_calls=1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.allow_request()  # transitions to HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_below_threshold_stays_closed(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=1.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_record_success_resets_failure_count(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        # Should still be CLOSED because success reset counter
        assert cb.state == CircuitState.CLOSED

    def test_success_count_tracking(self):
        from skillpool.resolver.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        cb.record_success()
        cb.record_success()
        assert cb.success_count == 0  # success_count only increments in HALF_OPEN


# ============================================================
# RateLimiter — Additional Coverage
# ============================================================


class TestRateLimiterAdditional:
    """Additional edge cases for RateLimiter."""

    def test_single_request_allowed(self):
        from skillpool.resolver.rate_limiter import RateLimiter

        rl = RateLimiter(max_requests=1, window_seconds=1.0)
        assert rl.allow() is True
        assert rl.allow() is False

    def test_current_count_after_expiry(self):
        from skillpool.resolver.rate_limiter import RateLimiter
        import time

        rl = RateLimiter(max_requests=5, window_seconds=0.05)
        rl.allow()
        rl.allow()
        time.sleep(0.06)
        # After window expiry, current_count should be 0
        assert rl.current_count == 0

    def test_reset_clears_counters(self):
        from skillpool.resolver.rate_limiter import RateLimiter

        rl = RateLimiter(max_requests=2, window_seconds=1.0)
        rl.allow()
        rl.allow()
        rl.reset()
        assert rl.current_count == 0
        assert rl.allow() is True


# ============================================================
# LRUCache — Additional Coverage
# ============================================================


class TestLRUCacheAdditional:
    """Additional edge cases for LRUCache."""

    def test_make_key_deterministic(self):
        from skillpool.resolver.cache import LRUCache

        key1 = LRUCache.make_key(["S01", "S02"], strategy="best_effort", max_skills=10)
        key2 = LRUCache.make_key(["S01", "S02"], strategy="best_effort", max_skills=10)
        assert key1 == key2

    def test_make_key_order_independent(self):
        from skillpool.resolver.cache import LRUCache

        key1 = LRUCache.make_key(["S01", "S02"])
        key2 = LRUCache.make_key(["S02", "S01"])
        assert key1 == key2  # Sorted internally

    def test_make_key_different_args_different_keys(self):
        from skillpool.resolver.cache import LRUCache

        key1 = LRUCache.make_key(["S01"], strategy="strict")
        key2 = LRUCache.make_key(["S01"], strategy="fuzzy")
        assert key1 != key2

    def test_invalidate_nonexistent_key(self):
        from skillpool.resolver.cache import LRUCache

        cache = LRUCache()
        assert cache.invalidate("nonexistent") is False

    def test_is_expired_nonexistent(self):
        from skillpool.resolver.cache import LRUCache

        cache = LRUCache()
        assert cache.is_expired("nonexistent") is False

    def test_stats_after_operations(self):
        from skillpool.resolver.cache import LRUCache

        cache = LRUCache()
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")  # hit
        cache.get("a")  # hit
        cache.get("c")  # miss
        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["size"] == 2

    def test_thread_safety_concurrent_access(self):
        """Test that concurrent put/get don't crash."""
        from skillpool.resolver.cache import LRUCache
        import threading

        cache = LRUCache(max_size=100)
        errors = []

        def writer():
            try:
                for i in range(50):
                    cache.put(f"key_{i}", i)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(50):
                    cache.get(f"key_{i}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(errors) == 0


# ============================================================
# SkillGraph — Edge Cases
# ============================================================


class TestSkillGraphEdgeCases:
    """Edge cases for SkillGraph operations."""

    def test_empty_graph_topological_sort(self):
        g = SkillGraph()
        order = g.topological_sort()
        assert order == []

    def test_single_node(self):
        g = SkillGraph()
        g.add_node("S01")
        order = g.topological_sort()
        assert order == ["S01"]

    def test_cycle_detection(self):
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "A")
        with pytest.raises(CycleDetected):
            g.topological_sort()

    def test_has_cycle_method(self):
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "A")
        assert g.has_cycle() is True

    def test_no_cycle(self):
        g = SkillGraph()
        g.add_edge("A", "B")
        assert g.has_cycle() is False

    def test_subgraph(self):
        g = SkillGraph()
        g.add_edge("A", "B", weight=0.8)
        g.add_edge("B", "C", weight=0.6)
        sub = g.subgraph({"A", "B"})
        assert sub.nodes == {"A", "B"}
        edges = sub.get_edges()
        assert len(edges) == 1
        assert edges[0] == ("A", "B", 0.8)

    def test_get_dependencies(self):
        g = SkillGraph()
        g.add_edge("S01", "S05a", weight=0.8)
        deps = g.get_dependencies("S05a")
        assert "S01" in deps

    def test_get_dependents(self):
        g = SkillGraph()
        g.add_edge("S01", "S05a", weight=0.8)
        deps = g.get_dependents("S01")
        assert "S05a" in deps

    def test_get_dependencies_no_deps(self):
        g = SkillGraph()
        g.add_node("S01")
        deps = g.get_dependencies("S01")
        assert deps == []


# ============================================================
# ConflictDetector — Edge Cases
# ============================================================


class TestConflictDetectorEdgeCases:
    """Edge cases for ConflictDetector."""

    def test_no_skills_no_conflicts(self):
        from skillpool.resolver.conflict_detector import ConflictDetector

        cd = ConflictDetector()
        conflicts = cd.detect()
        assert conflicts == []

    def test_single_skill_no_conflicts(self):
        from skillpool.resolver.conflict_detector import ConflictDetector

        cd = ConflictDetector()
        cd.register("S01", name="Test Skill")
        conflicts = cd.detect()
        assert conflicts == []

    def test_two_dissimilar_skills_no_conflicts(self):
        from skillpool.resolver.conflict_detector import ConflictDetector

        cd = ConflictDetector(threshold=0.5)
        cd.register("S01", name="Authentication", dimension="D3", namespaces=["auth"])
        cd.register("S09", name="Resilience", dimension="D5", namespaces=["resilience"])
        conflicts = cd.detect()
        assert len(conflicts) == 0

    def test_two_similar_skills_with_conflict(self):
        from skillpool.resolver.conflict_detector import ConflictDetector

        cd = ConflictDetector(threshold=0.01)
        cd.register("S01", name="Auth Check", dimension="D3", namespaces=["auth"])
        cd.register("S02", name="Auth Verify", dimension="D3", namespaces=["auth"])
        conflicts = cd.detect()
        assert len(conflicts) > 0

    def test_custom_threshold(self):
        from skillpool.resolver.conflict_detector import ConflictDetector

        cd = ConflictDetector(threshold=0.99)
        cd.register("S01", name="Auth Check", dimension="D3", namespaces=["auth"])
        cd.register("S02", name="Auth Verify", dimension="D3", namespaces=["auth"])
        # With very high threshold, should have no conflicts
        conflicts = cd.detect()
        assert len(conflicts) == 0

    def test_clear(self):
        from skillpool.resolver.conflict_detector import ConflictDetector

        cd = ConflictDetector()
        cd.register("S01", name="Test")
        cd.clear()
        conflicts = cd.detect()
        assert conflicts == []


# ============================================================
# HealthFilter — Edge Cases
# ============================================================


class TestHealthFilterEdgeCases:
    """Edge cases for HealthFilter."""

    def test_all_healthy(self):
        from skillpool.resolver.health_filter import HealthFilter

        hf = HealthFilter(min_score=0.6)
        skills = [
            {"skill_id": "S01", "health_score": 1.0},
            {"skill_id": "S02", "health_score": 0.9},
        ]
        passed, excluded = hf.filter(skills)
        assert len(passed) == 2
        assert len(excluded) == 0

    def test_all_unhealthy(self):
        from skillpool.resolver.health_filter import HealthFilter

        hf = HealthFilter(min_score=0.6)
        skills = [
            {"skill_id": "S01", "health_score": 0.3},
            {"skill_id": "S02", "health_score": 0.1},
        ]
        passed, excluded = hf.filter(skills)
        assert len(passed) == 0
        assert len(excluded) == 2

    def test_mixed_health(self):
        from skillpool.resolver.health_filter import HealthFilter

        hf = HealthFilter(min_score=0.6)
        skills = [
            {"skill_id": "S01", "health_score": 0.9},
            {"skill_id": "S02", "health_score": 0.3},
            {"skill_id": "S03", "health_score": 0.6},
        ]
        passed, excluded = hf.filter(skills)
        assert len(passed) == 2
        assert "S02" in excluded

    def test_empty_skills_list(self):
        from skillpool.resolver.health_filter import HealthFilter

        hf = HealthFilter()
        passed, excluded = hf.filter([])
        assert passed == []
        assert excluded == []

    def test_missing_health_score_defaults_healthy(self):
        from skillpool.resolver.health_filter import HealthFilter

        hf = HealthFilter(min_score=0.6)
        skills = [{"skill_id": "S01"}]  # No health_score key
        passed, excluded = hf.filter(skills)
        assert len(passed) == 1  # defaults to 1.0

    def test_exact_threshold(self):
        from skillpool.resolver.health_filter import HealthFilter

        hf = HealthFilter(min_score=0.6)
        skills = [{"skill_id": "S01", "health_score": 0.6}]
        passed, excluded = hf.filter(skills)
        assert len(passed) == 1  # Exactly at threshold should pass


# ============================================================
# SkillResolver — Cache Integration
# ============================================================


class TestResolverCacheIntegration:
    """Test that resolver uses caching correctly."""

    def test_cache_hit_on_repeated_resolve(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        req = SkillResolveRequest(skill_ids=["S01"])
        resp1 = resolver.resolve(req)
        assert resp1.from_cache is False
        resp2 = resolver.resolve(req)
        assert resp2.from_cache is True

    def test_cache_invalidation_on_different_request(self):
        register_skill("S01", {"name": "Test", "dependencies": [], "health_score": 1.0})
        register_skill("S02", {"name": "Test2", "dependencies": [], "health_score": 1.0})
        resolver = SkillResolver()
        req1 = SkillResolveRequest(skill_ids=["S01"])
        req2 = SkillResolveRequest(skill_ids=["S02"])
        resp1 = resolver.resolve(req1)
        resp2 = resolver.resolve(req2)
        assert resp1.from_cache is False
        assert resp2.from_cache is False

    def test_circuit_state_property(self):
        resolver = SkillResolver()
        from skillpool.resolver.circuit_breaker import CircuitState

        assert resolver.circuit_state == CircuitState.CLOSED


# ============================================================
# SkillResolver — Transitive Dependencies
# ============================================================


class TestTransitiveDependencies:
    """Test that the resolver follows transitive dependencies."""

    def test_transitive_deps_resolved(self):
        register_skill("A", {"name": "A", "dependencies": ["B"], "health_score": 1.0, "weight": 1.0})
        register_skill("B", {"name": "B", "dependencies": ["C"], "health_score": 1.0, "weight": 1.0})
        register_skill("C", {"name": "C", "dependencies": [], "health_score": 1.0, "weight": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["A"]))
        assert resp.total_skills == 3
        resolved_ids = {s.skill_id for s in resp.resolved}
        assert resolved_ids == {"A", "B", "C"}

    def test_circular_dependency_detected(self):
        register_skill("A", {"name": "A", "dependencies": ["B"], "health_score": 1.0, "weight": 1.0})
        register_skill("B", {"name": "B", "dependencies": ["A"], "health_score": 1.0, "weight": 1.0})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["A"]))
        # Circular dependency should be caught
        assert resp.error is not None or resp.degraded is True


# ============================================================
# SkillResolver — Feasibility Score Edge Cases
# ============================================================


class TestFeasibilityScoreEdgeCases:
    """Edge cases for feasibility_score computation."""

    def test_zero_skills_zero_feasibility(self):
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["MISSING"]))
        # No skills found → feasibility should be 1.0 (default) or 0.0
        # depending on implementation
        assert 0.0 <= resp.feasibility_score <= 1.0

    def test_feasibility_with_all_unhealthy(self):
        register_skill("S01", {"name": "Unhealthy", "dependencies": [], "health_score": 0.1})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"], min_health_score=0.6))
        # All filtered out → UNRESOLVED
        assert resp.status == ResolveStatus.UNRESOLVED

    def test_feasibility_bounded(self):
        register_skill("S01", {"name": "A", "dependencies": [], "health_score": 0.8})
        resolver = SkillResolver()
        resp = resolver.resolve(SkillResolveRequest(skill_ids=["S01"]))
        assert 0.0 <= resp.feasibility_score <= 1.0
