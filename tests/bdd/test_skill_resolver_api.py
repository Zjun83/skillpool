"""BDD tests for Skill Resolver — mapping to skill-resolver-api.feature scenarios."""
import pytest

from skillpool.resolver import SkillResolver, register_skill, clear_registry
from skillpool.resolver.models import SkillResolveRequest
from skillpool.resolver.skill_graph import SkillGraph, CycleDetected
from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState
from skillpool.resolver.rate_limiter import RateLimiter


# Sample skill registry for BDD tests
SKILLS = {
    "gitea_get_file": {
        "name": "Gitea Get File",
        "dimension": "D3",
        "weight": 0.15,
        "health_score": 0.92,
        "dependencies": [],
        "namespaces": ["file_ops", "gitea"],
    },
    "parse_config": {
        "name": "Parse Config",
        "dimension": "D1",
        "weight": 0.10,
        "health_score": 0.85,
        "dependencies": ["gitea_get_file"],
        "namespaces": ["config", "parsing"],
    },
    "validate_syntax": {
        "name": "Validate Syntax",
        "dimension": "D7",
        "weight": 0.12,
        "health_score": 0.78,
        "dependencies": ["parse_config"],
        "namespaces": ["validation", "syntax"],
    },
    "apply_patch": {
        "name": "Apply Patch",
        "dimension": "D5",
        "weight": 0.20,
        "health_score": 0.91,
        "dependencies": ["validate_syntax"],
        "namespaces": ["patch", "diff"],
    },
    "run_tests": {
        "name": "Run Tests",
        "dimension": "D7",
        "weight": 0.18,
        "health_score": 0.88,
        "dependencies": ["apply_patch"],
        "namespaces": ["testing", "execution"],
    },
}


class TestSkillResolver:
    """Scenario: Normal resolution — linear skill chain."""
    def test_linear_resolution(self):
        """Scenario: Normal resolve - linear skill chain."""
        clear_registry()
        for sid, data in SKILLS.items():
            register_skill(sid, data)

        resolver = SkillResolver()
        req = SkillResolveRequest(skill_ids=["run_tests"])
        response = resolver.resolve(req)

        assert response.total_skills == 5
        assert len(response.resolved) > 0

    def test_partial_resolution_health_filter(self):
        """Scenario: Skills with low health score are excluded."""
        clear_registry()
        register_skill("low_health", {
            "name": "LowHealth Skill",
            "dimension": "D3",
            "health_score": 0.3,
            "dependencies": [],
            "namespaces": ["testing"],
        })
        register_skill("good_skill", {
            "name": "Good Skill",
            "dimension": "D1",
            "health_score": 0.95,
            "dependencies": [],
            "namespaces": [],
        })

        resolver = SkillResolver()
        req = SkillResolveRequest(skill_ids=["low_health", "good_skill"])
        response = resolver.resolve(req)
        skill_ids = [s.skill_id for s in response.resolved]
        assert "good_skill" in skill_ids
        assert "low_health" not in skill_ids

    def test_cycle_detection(self):
        """Scenario: Detect circular dependencies."""
        g = SkillGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "A")
        assert g.has_cycle() is True

    def test_conflict_detection(self):
        """Scenario: Conflicts detected via namespace overlap."""
        clear_registry()
        register_skill("skill_a", {
            "name": "Skill A", "namespaces": ["file_ops"],
            "health_score": 0.9, "dependencies": [],
        })
        register_skill("skill_b", {
            "name": "Skill B", "namespaces": ["file_ops"],
            "health_score": 0.85, "dependencies": [],
        })
        resolver = SkillResolver()
        request = SkillResolveRequest(skill_ids=["skill_a", "skill_b"])
        response = resolver.resolve(request)
        assert len(response.conflicts) > 0

    def test_max_skills_constraint(self):
        """Scenario: max_skills limits the returned skills."""
        clear_registry()
        for sid, data in SKILLS.items():
            register_skill(sid, data)

        resolver = SkillResolver()
        req = SkillResolveRequest(skill_ids=["run_tests"], max_skills=3)
        response = resolver.resolve(req)
        assert len(response.resolved) <= 3


class TestCircuitBreaker:
    """Circuit breaker scenarios from skill-resolver-api.feature."""

    def test_circuit_breaker_open_blocks_requests(self):
        """Scenario: Circuit breaker opens and blocks requests."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_circuit_breaker_half_open(self):
        """Scenario: Circuit breaker enters half-open state."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        import time
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_circuit_breaker_closes_on_success(self):
        """Scenario: Success in half-open closes the circuit."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=1)
        cb.record_failure()  # Opens the breaker
        import time
        time.sleep(0.02)  # Wait for recovery timeout
        assert cb.state == CircuitState.HALF_OPEN
        cb.allow_request()  # Consume the half-open probe slot
        cb.record_success()  # Should close the circuit
        assert cb.state == CircuitState.CLOSED


class TestRateLimiting:
    """Scenarios for rate limiting."""
    def test_rate_limiter_blocks_excess_requests(self):
        limiter = RateLimiter(max_requests=5, window_seconds=1.0)
        for _ in range(5):
            assert limiter.allow()
        # 6th request should be blocked
        assert not limiter.allow()

    def test_rate_limiter_refill(self):
        limiter = RateLimiter(max_requests=3, window_seconds=0.01)
        assert limiter.allow()
        assert limiter.allow()
        assert limiter.allow()
        assert not limiter.allow()  # 4th blocked
        # Wait for window to expire
        import time
        time.sleep(0.02)
        assert limiter.allow()  # Should allow again


class TestResolverSchemaAlignment:
    """Scenarios for Resolver schema-aligned fields."""

    def test_resolve_status_enum(self):
        """Scenario: ResolveStatus has RESOLVED/PARTIAL/UNRESOLVED values."""
        from skillpool.resolver.models import ResolveStatus
        assert ResolveStatus.RESOLVED == "resolved"
        assert ResolveStatus.PARTIAL == "partial"
        assert ResolveStatus.UNRESOLVED == "unresolved"

    def test_resolve_response_status_field(self):
        """Scenario: SkillResolveResponse includes status field."""
        from skillpool.resolver.models import SkillResolveResponse, ResolveStatus
        resp = SkillResolveResponse(error="no_skills_found", status=ResolveStatus.UNRESOLVED)
        assert resp.status == ResolveStatus.UNRESOLVED

    def test_resolve_request_schema_fields(self):
        """Scenario: SkillResolveRequest includes schema-aligned fields."""
        from skillpool.resolver.models import SkillResolveRequest, Domain
        req = SkillResolveRequest(
            skill_ids=["S09"],
            task="review code",
            task_description="Review code for security issues",
            domain=Domain.SECURITY_FIX,
            trace_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        )
        assert req.domain == Domain.SECURITY_FIX
        assert req.trace_id != ""

    def test_health_scores_in_response(self):
        """Scenario: SkillResolveResponse includes health_scores dict."""
        from skillpool.resolver.models import SkillResolveResponse
        resp = SkillResolveResponse(health_scores={"s1": 0.9})
        assert resp.health_scores["s1"] == 0.9

    def test_feasibility_score_in_response(self):
        """Scenario: SkillResolveResponse includes feasibility_score."""
        from skillpool.resolver.models import SkillResolveResponse
        resp = SkillResolveResponse(feasibility_score=0.85)
        assert resp.feasibility_score == 0.85

    def test_dag_edge_type_enum(self):
        """Scenario: DagEdgeType has DEPENDS_ON/CONFLICTS/SAME_DOMAIN/OVERLAP values."""
        from skillpool.resolver.models import DagEdgeType
        assert DagEdgeType.DEPENDS_ON == "depends_on"
        assert DagEdgeType.CONFLICTS_WITH == "conflicts_with"
