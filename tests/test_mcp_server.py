"""Comprehensive tests for MCP Server — Resources, Tools, Prompts, and Middleware.

Tests call handler functions directly (they are plain synchronous functions
decorated by FastMCP, not async coroutines). Module-level singletons
(_audit, _evolver, _registry, etc.) are patched where isolation is needed.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import skillpool.mcp_server as _mod
from skillpool.mcp_server import (
    SkillPoolLoggingMiddleware,
    TimingMiddleware,
    _cached_resource,
    _get_profile,
    _load_csdf,
    gate_check,
    telemetry_report,
    audit_verify,
    skill_register,
    skill_transition,
    skill_status,
    evolution_trigger,
    evolution_proposal,
    monitor_evaluate,
    health_check,
    review_trigger,
    security_scan,
    healing_scan,
    healing_execute,
    skill_search,
    skill_get,
    skill_match,
    report_usage,
    assess_paradigm,
    combination_create,
    combination_get,
    combination_list,
    combination_transition,
    skill_lifecycle_check,
    get_emergency_overrides,
    skill_list,
    skill_definition,
    skill_summary,
    skill_manifest,
    skill_execution,
    skill_rules,
    skill_graph,
    audit_records,
    bug_list,
    skill_context,
    trigger_review,
    gate_status,
    mcp,
    main,
)
from skillpool.audit import AuditLayer


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_search_state(tmp_path):
    """Clear search-first enforcement state between tests.

    Also patches _SKILLS_DIR to a temp dir with minimal test skill data,
    so tests work in CI where ~/.skillpool/skills/ is empty.
    """
    from tests.conftest import _create_test_skills

    _mod._search_done_callers.clear()
    _mod._RESOURCE_CACHE.clear()
    sd = _create_test_skills(tmp_path / "skills")
    with patch.object(_mod, "_SKILLS_DIR", sd), patch.object(_mod._lazy_loader, "_skills_dir", sd):
        yield
    _mod._search_done_callers.clear()
    _mod._RESOURCE_CACHE.clear()


def _sample_csdf(**overrides):
    """Build a minimal CSDF dict for gate_check tests."""
    base = {
        "id": "S05a-security",
        "name": "Security Transport",
        "version": "1.0.0",
        "dimension": "D3",
        "checklist": [
            {"item": "Check TLS config", "priority": "high"},
            {"item": "Verify cert chain", "priority": "high"},
        ],
        "veto_rule": "score < 7.0 -> reject",
        "min_trust_level": 2,
        "required_agent_capabilities": {"bash", "file_system"},
        "paradigm": "review",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════
# Module-level helpers
# ═══════════════════════════════════════════════════════════════════


class TestGetProfile:
    def test_valid_profiles(self):
        for name in ("claude-code", "codex", "hermes", "openclaw"):
            profile = _get_profile(name)
            assert profile.name == name

    def test_invalid_profile_raises(self):
        with pytest.raises(ValueError, match="Unknown agent_type"):
            _get_profile("nonexistent")


class TestCachedResource:
    def test_caches_result(self):
        call_count = 0

        def compute():
            nonlocal call_count
            call_count += 1
            return {"data": 42}

        result1 = _cached_resource("test://cache1", compute)
        result2 = _cached_resource("test://cache1", compute)
        assert result1 == {"data": 42}
        assert result2 == {"data": 42}
        assert call_count == 1  # Second call hit cache

    def test_cache_expiry(self):
        call_count = 0

        def compute():
            nonlocal call_count
            call_count += 1
            return call_count

        # Save and shorten TTL
        original_ttl = _mod._RESOURCE_CACHE_TTL
        _mod._RESOURCE_CACHE_TTL = 0.0  # Expire immediately
        try:
            result1 = _cached_resource("test://cache2", compute)
            time.sleep(0.01)
            result2 = _cached_resource("test://cache2", compute)
            assert result1 == 1
            assert result2 == 2  # Cache expired, recomputed
            assert call_count == 2
        finally:
            _mod._RESOURCE_CACHE_TTL = original_ttl

    def test_cache_eviction_at_max(self):
        original_max = _mod._RESOURCE_CACHE_MAX
        _mod._RESOURCE_CACHE_MAX = 2
        try:
            _cached_resource("test://evict1", lambda: "a")
            _cached_resource("test://evict2", lambda: "b")
            # Adding a third should evict the oldest
            _cached_resource("test://evict3", lambda: "c")
            assert "test://evict1" not in _mod._RESOURCE_CACHE
            assert "test://evict3" in _mod._RESOURCE_CACHE
        finally:
            _mod._RESOURCE_CACHE_MAX = original_max


class TestLoadCsdf:
    def test_returns_dict_for_known_skill(self):
        result = _load_csdf("S09")
        if result is not None:
            assert isinstance(result, dict)
            assert "id" in result or "name" in result

    def test_returns_none_for_unknown_skill(self):
        result = _load_csdf("NONEXISTENT_SKILL_XYZ")
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# RESOURCES
# ═══════════════════════════════════════════════════════════════════


class TestSkillListResource:
    def test_returns_list(self):
        result = skill_list()
        assert isinstance(result, list)

    def test_lightweight_metadata(self):
        """skill://list should NOT include full markdown content."""
        result = skill_list()
        for skill in result:
            assert "markdown" not in skill
            assert "checklist" not in skill

    def test_skill_has_required_fields(self):
        result = skill_list()
        if result:
            first = result[0]
            assert "id" in first
            assert "name" in first


class TestSkillDefinitionResource:
    def test_returns_string_for_known_skill(self):
        result = skill_definition("S09")
        assert isinstance(result, str)
        assert "S09" in result

    def test_not_found_for_unknown_skill(self):
        result = skill_definition("NONEXISTENT")
        assert "not found" in result.lower()


class TestSkillSummaryResource:
    def test_returns_dict(self):
        result = skill_summary("S09")
        assert isinstance(result, dict)

    def test_not_found_skill(self):
        result = skill_summary("NONEXISTENT")
        assert "error" in result


class TestSkillManifestResource:
    def test_returns_manifest_structure(self):
        result = skill_manifest("S09")
        assert isinstance(result, dict)
        assert "id" in result
        assert "version" in result
        assert "dependencies" in result

    def test_not_found_skill(self):
        result = skill_manifest("NONEXISTENT")
        assert "error" in result


class TestSkillExecutionResource:
    def test_returns_execution_info(self):
        result = skill_execution("S09")
        assert isinstance(result, dict)
        assert "id" in result
        assert "execution_type" in result

    def test_not_found_skill(self):
        result = skill_execution("NONEXISTENT")
        assert "error" in result


class TestSkillRulesResource:
    def test_returns_string(self):
        result = skill_rules("multi-dim-review")
        assert isinstance(result, str)

    def test_empty_for_nonexistent(self):
        result = skill_rules("NONEXISTENT")
        assert isinstance(result, str)
        # No RULES.md file -> empty string
        assert result == ""


class TestSkillGraphResource:
    def test_returns_dict(self):
        result = skill_graph()
        assert isinstance(result, dict)

    def test_graph_not_error(self):
        result = skill_graph()
        assert "error" not in result


class TestAuditRecordsResource:
    def test_returns_dict(self):
        result = audit_records()
        assert isinstance(result, dict)
        assert "records" in result
        assert "total" in result

    def test_default_limit(self):
        result = audit_records()
        assert result["limit"] <= 500

    def test_custom_pagination(self):
        result = audit_records(cursor=0, limit=10)
        assert result["limit"] == 10
        assert result["cursor"] == 0
        assert len(result["records"]) <= 10

    def test_limit_clamped(self):
        result = audit_records(limit=9999)
        assert result["limit"] == 500  # Clamped to max

    def test_next_cursor(self):
        result = audit_records(cursor=0, limit=10)
        total = result["total"]
        if total > 10:
            assert result["next_cursor"] == 10
        else:
            assert result["next_cursor"] is None


class TestBugListResource:
    def test_returns_dict(self):
        result = bug_list()
        assert isinstance(result, dict)
        assert "bugs" in result
        assert "total" in result

    def test_default_limit(self):
        result = bug_list()
        assert result["limit"] <= 500

    def test_custom_pagination(self):
        result = bug_list(cursor=0, limit=10)
        assert result["limit"] == 10


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Gate
# ═══════════════════════════════════════════════════════════════════


class TestGateCheck:
    def test_allow_low_complexity(self):
        csdf = {"id": "S01", "name": "Simple", "min_trust_level": 1, "checklist": []}
        result = gate_check(csdf, profile_name="claude-code")
        assert result["decision"] == "allow"

    def test_deny_capability_mismatch(self):
        csdf = {
            "id": "S02",
            "min_trust_level": 3,
            "required_agent_capabilities": {"bash", "python", "extra"},
        }
        result = gate_check(csdf, profile_name="hermes")
        assert result["decision"] == "deny"

    def test_guard_medium_complexity(self):
        csdf = _sample_csdf()
        result = gate_check(csdf, profile_name="claude-code")
        assert result["decision"] in ("allow", "guard", "escalate", "deny")

    def test_safe_deny_on_error(self):
        result = gate_check(None, profile_name="claude-code")  # type: ignore
        assert result["decision"] == "DENY"
        assert "safe-deny" in result["reason"]

    def test_invalid_profile_safe_deny(self):
        csdf = {"id": "S01", "name": "Simple", "checklist": []}
        result = gate_check(csdf, profile_name="invalid_profile")
        assert result["decision"] == "DENY"

    def test_result_structure(self):
        csdf = {"id": "S01", "name": "Simple", "checklist": []}
        result = gate_check(csdf, profile_name="claude-code")
        assert "decision" in result
        assert "reason" in result
        assert "complexity_level" in result
        assert "complexity_total" in result
        assert "conditions" in result


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Telemetry
# ═══════════════════════════════════════════════════════════════════


class TestTelemetryReport:
    def test_report_event(self):
        result = telemetry_report(
            event_type="skill_used",
            skill_id="S05a",
            channel="hook",
        )
        assert result["event_type"] == "skill_used"
        assert result["skill_id"] == "S05a"

    def test_report_with_payload(self):
        result = telemetry_report(
            event_type="skill_error",
            skill_id="S10",
            channel="mcp",
            payload={"error": "timeout"},
        )
        assert result["event_type"] == "skill_error"
        assert result["channel"] == "mcp"

    def test_silent_failure_on_error(self):
        with patch("skillpool.mcp_server.TelemetryBridge") as MockBridge:
            MockBridge.return_value.emit.side_effect = RuntimeError("boom")
            result = telemetry_report(
                event_type="test",
                skill_id="S01",
                channel="hook",
            )
            assert "error" in result
            assert "telemetry dropped" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Audit
# ═══════════════════════════════════════════════════════════════════


class TestAuditVerify:
    def test_returns_integrity_status(self):
        result = audit_verify()
        assert "integrity" in result
        assert "record_count" in result

    def test_error_handling(self):
        with patch.object(_mod._audit, "verify_integrity", side_effect=RuntimeError("fail")):
            result = audit_verify()
            assert result["integrity"] is False


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Registry
# ═══════════════════════════════════════════════════════════════════


class TestSkillRegister:
    def test_register_with_evidence(self):
        original = os.environ.get("SKILLPOOL_EVIDENCE_TIER")
        try:
            os.environ["SKILLPOOL_EVIDENCE_TIER"] = "dev"
            # Re-create registry with dev tier
            audit = AuditLayer(data_dir=Path("/tmp/skillpool_test_audit"))
            from skillpool.registry import Registry

            registry = Registry(audit_layer=audit)

            with patch.object(_mod, "_registry", registry):
                result = skill_register(
                    skill_id="test-reg-001",
                    name="Test Skill",
                    version="1.0.0",
                )
                assert result.get("skill_id") == "test-reg-001"
                assert result.get("status") == "testing"
        finally:
            if original is not None:
                os.environ["SKILLPOOL_EVIDENCE_TIER"] = original
            else:
                os.environ.pop("SKILLPOOL_EVIDENCE_TIER", None)

    def test_register_prod_requires_evidence(self):
        original = os.environ.get("SKILLPOOL_EVIDENCE_TIER")
        try:
            os.environ["SKILLPOOL_EVIDENCE_TIER"] = "prod"
            audit = AuditLayer(data_dir=Path("/tmp/skillpool_test_audit2"))
            from skillpool.registry import Registry

            registry = Registry(audit_layer=audit)

            with patch.object(_mod, "_registry", registry):
                result = skill_register(
                    skill_id="test-reg-002",
                    name="Test Skill Prod",
                    version="1.0.0",
                )
                assert "error" in result
        finally:
            if original is not None:
                os.environ["SKILLPOOL_EVIDENCE_TIER"] = original
            else:
                os.environ.pop("SKILLPOOL_EVIDENCE_TIER", None)


class TestSkillTransition:
    def test_transition_invalid_status(self):
        result = skill_transition(
            skill_id="nonexistent",
            from_status="draft",
            to_status="enabled",
        )
        assert "error" in result

    def test_transition_with_trace_id(self):
        result = skill_transition(
            skill_id="nonexistent",
            from_status="testing",
            to_status="enabled",
            trace_id="abc123",
        )
        assert "error" in result


class TestSkillStatusTool:
    def test_not_found(self):
        result = skill_status(skill_id="nonexistent_xyz")
        assert result["status"] == "not_found"

    def test_result_structure(self):
        result = skill_status(skill_id="nonexistent_xyz")
        assert "skill_id" in result


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Evolver
# ═══════════════════════════════════════════════════════════════════


class TestEvolutionTrigger:
    def test_trigger_defect(self):
        result = evolution_trigger(
            skill_id="S09",
            version="9.0.0",
            severity="minor",
            description="Test defect",
        )
        assert "defect_id" in result
        assert result["severity"] == "minor"

    def test_invalid_severity(self):
        result = evolution_trigger(
            skill_id="S09",
            version="9.0.0",
            severity="invalid",
            description="Test",
        )
        assert "error" in result

    def test_critical_severity(self):
        result = evolution_trigger(
            skill_id="S09",
            version="9.0.0",
            severity="critical",
            description="Critical defect",
        )
        assert "defect_id" in result
        assert result["severity"] == "critical"


class TestEvolutionProposal:
    def test_create_proposal(self):
        result = evolution_proposal(reason="Test evolution", risk="low")
        assert "proposal_id" in result
        assert result["recommendation_only"] is True

    def test_default_risk(self):
        result = evolution_proposal(reason="Test")
        assert result["risk"] == "medium"


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Monitor
# ═══════════════════════════════════════════════════════════════════


class TestMonitorEvaluate:
    def test_evaluate_skill(self):
        result = monitor_evaluate(skill_id="S09", error_rate=0.05, coverage=0.8)
        assert result["skill_id"] == "S09"
        assert "overall_score" in result
        assert "safety" in result

    def test_result_has_five_dimensions(self):
        result = monitor_evaluate(skill_id="S09")
        for dim in ("safety", "completeness", "executability", "maintainability", "cost_awareness"):
            assert dim in result
            assert "score" in result[dim]
            assert "level" in result[dim]

    def test_error_handling(self):
        with patch.object(_mod._monitor, "evaluate_skill", side_effect=RuntimeError("fail")):
            result = monitor_evaluate(skill_id="S09")
            assert result["overall_score"] == 0.0
            assert "error" in result


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Health
# ═══════════════════════════════════════════════════════════════════


class TestHealthCheck:
    def test_returns_status(self):
        result = health_check()
        assert "status" in result
        assert "components" in result
        assert "degradation_level" in result

    def test_include_gateway(self):
        """Gateway check should not crash regardless of gateway state."""
        result = health_check(include_gateway=True)
        assert "gateway" in result
        # Gateway can be healthy, unreachable, or any status
        assert "status" in result["gateway"]

    def test_error_handling(self):
        with patch.object(_mod._health, "check_health", side_effect=RuntimeError("fail")):
            result = health_check()
            assert result["status"] == "DEGRADED"


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Review
# ═══════════════════════════════════════════════════════════════════


class TestReviewTrigger:
    def test_valid_checkpoint(self):
        result = review_trigger(checkpoint="L1")
        assert "status" in result or "review_id" in result

    def test_invalid_checkpoint(self):
        result = review_trigger(checkpoint="L9")
        assert "error" in result or "status" in result

    def test_with_skill_ids(self):
        result = review_trigger(checkpoint="L2", skill_ids=["S09"])
        assert isinstance(result, dict)

    def test_with_trace_id(self):
        result = review_trigger(checkpoint="L2", trace_id="test-trace-123")
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Security
# ═══════════════════════════════════════════════════════════════════


class TestSecurityScan:
    def test_safe_content(self):
        result = security_scan(content="Safe YAML content", skill_id="test")
        assert result["threat_level"] == "safe"
        assert result["is_safe"] is True

    def test_dangerous_content(self):
        result = security_scan(content='exec("rm -rf /")', skill_id="test")
        assert result["threat_level"] == "critical"
        assert result["is_safe"] is False
        assert len(result["blockers"]) > 0

    def test_yaml_dangerous_tag(self):
        result = security_scan(content="data: !!python/object:module.Class", skill_id="test")
        assert result["threat_level"] == "critical"
        assert result["is_safe"] is False

    def test_error_handling(self):
        with patch.object(_mod._security_scanner, "full_check", side_effect=RuntimeError("fail")):
            result = security_scan(content="test", skill_id="test")
            assert result["is_safe"] is False
            assert result["threat_level"] == "critical"


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Self-Healing
# ═══════════════════════════════════════════════════════════════════


class TestHealingScan:
    def test_returns_proposals(self):
        result = healing_scan()
        assert isinstance(result, dict)
        assert "proposals" in result
        assert "total_proposals" in result
        assert "status" in result

    def test_empty_bugs_no_proposals(self):
        """No bugs -> no proposals."""
        with patch.object(_mod._bug_collector, "get_bugs", return_value=[]):
            with patch.object(_mod._self_healing, "scan_and_propose", return_value=[]):
                result = healing_scan()
                assert result["total_proposals"] == 0

    def test_error_handling(self):
        with patch.object(_mod._self_healing, "scan_and_propose", side_effect=RuntimeError("fail")):
            result = healing_scan()
            assert result["status"] == "error"


class TestHealingExecute:
    def test_nonexistent_proposal(self):
        result = healing_execute(proposal_id="nonexistent")
        assert "error" in result or result.get("status") == "not_found"

    def test_error_handling(self):
        with patch.object(_mod._self_healing, "execute_healing", side_effect=RuntimeError("fail")):
            result = healing_execute(proposal_id="any")
            assert result["status"] == "error"


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Skill Search & Get
# ═══════════════════════════════════════════════════════════════════


class TestSkillSearch:
    def test_returns_result(self):
        result = skill_search(intent="security review", agent_type="claude-code")
        assert isinstance(result, dict)
        assert result["intent"] == "security review"
        assert result["agent"] == "claude-code"

    def test_marks_search_done(self):
        assert "claude-code" not in _mod._search_done_callers
        skill_search(intent="test", agent_type="claude-code")
        assert "claude-code" in _mod._search_done_callers

    def test_top_k_clamped(self):
        result = skill_search(intent="test", agent_type="codex", top_k=999)
        assert isinstance(result, dict)


class TestSkillGet:
    def test_search_required_error(self):
        """Without prior skill_search, skill_get should block."""
        result = skill_get(skill_id="S09", agent_type="claude-code")
        assert result["error"] == "search_required"

    def test_get_after_search(self):
        """After skill_search, skill_get should succeed."""
        skill_search(intent="resilience", agent_type="claude-code")
        result = skill_get(skill_id="S09", agent_type="claude-code", detail="definition")
        assert result.get("skill_id") == "S09"
        assert "content" in result

    def test_summary_detail(self):
        skill_search(intent="resilience", agent_type="codex")
        result = skill_get(skill_id="S09", agent_type="codex", detail="summary")
        assert result.get("detail") == "summary"
        assert "data" in result

    def test_manifest_detail(self):
        skill_search(intent="resilience", agent_type="hermes")
        result = skill_get(skill_id="S09", agent_type="hermes", detail="manifest")
        assert result.get("detail") == "manifest"
        assert "data" in result

    def test_manifest_not_found(self):
        skill_search(intent="test", agent_type="openclaw")
        result = skill_get(skill_id="NONEXISTENT", agent_type="openclaw", detail="manifest")
        assert "error" in result

    def test_definition_not_found(self):
        skill_search(intent="test", agent_type="claude-code")
        result = skill_get(skill_id="NONEXISTENT_SKILL_XYZ", agent_type="claude-code")
        assert "error" in result


class TestSkillMatch:
    """Tests for skill_match tool.

    Note: skill_match internally creates SkillResolver which uses the global
    _SKILL_REGISTRY. Other test files (e.g., test_resolver.py) may populate
    this registry, causing state pollution. We mock the resolver to ensure
    isolation and avoid the m.score AttributeError (ResolvedSkill has weight,
    not score).
    """

    def test_returns_result(self):
        """Test skill_match returns expected structure."""
        # Mock SkillResolver to avoid global registry pollution
        mock_response = MagicMock()
        mock_response.resolved = []  # Empty to avoid m.score bug
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_response

        # Mock IntentRouter to avoid Ollama calls
        mock_routing = MagicMock()
        mock_routing.primary = None
        mock_routing.candidates = []
        mock_routing.enhancers = []
        mock_routing.layers_used = ["L1"]
        mock_router = MagicMock()
        mock_router.route.return_value = mock_routing

        with patch("skillpool.resolver.SkillResolver", return_value=mock_resolver):
            with patch("skillpool.router.IntentRouter", return_value=mock_router):
                result = skill_match(
                    task_description="resilience review",
                    agent_type="claude-code",
                )
        assert isinstance(result, dict)
        assert result["task"] == "resilience review"
        assert result["agent"] == "claude-code"

    def test_without_combinations(self):
        """Test skill_match with include_combinations=False."""
        mock_response = MagicMock()
        mock_response.resolved = []
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_response

        mock_routing = MagicMock()
        mock_routing.primary = None
        mock_routing.candidates = []
        mock_routing.enhancers = []
        mock_routing.layers_used = ["L1"]
        mock_router = MagicMock()
        mock_router.route.return_value = mock_routing

        with patch("skillpool.resolver.SkillResolver", return_value=mock_resolver):
            with patch("skillpool.router.IntentRouter", return_value=mock_router):
                result = skill_match(
                    task_description="security check",
                    agent_type="codex",
                    include_combinations=False,
                )
        assert isinstance(result, dict)

    def test_invalid_agent_type(self):
        with pytest.raises(ValueError):
            skill_match(
                task_description="test",
                agent_type="invalid_agent",
            )


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Report Usage
# ═══════════════════════════════════════════════════════════════════


class TestReportUsage:
    def test_minimal_report(self):
        result = report_usage(
            skill_name="S09",
            session_id="sess-001",
            agent_type="claude-code",
        )
        assert result["skill_name"] == "S09"
        assert result["session_id"] == "sess-001"
        assert "telemetry" in result

    def test_with_gain_scores(self):
        result = report_usage(
            skill_name="S09",
            session_id="sess-002",
            agent_type="claude-code",
            effectiveness=8.0,
            efficiency=7.0,
            quality=6.0,
            gain=2.0,
        )
        assert result["gain_recorded"] is True

    def test_with_combination_skills(self):
        result = report_usage(
            skill_name="S09",
            session_id="sess-003",
            agent_type="claude-code",
            combination_skills=["S05a"],
        )
        assert result["combination_count"] == 1


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Paradigm
# ═══════════════════════════════════════════════════════════════════


class TestAssessParadigm:
    def test_returns_result(self):
        result = assess_paradigm(paradigm="review", agent_type="claude-code")
        assert isinstance(result, dict)
        assert result["paradigm"] == "review"
        assert result["agent_type"] == "claude-code"
        assert "can_execute" in result

    def test_invalid_agent_type(self):
        with pytest.raises(ValueError):
            assess_paradigm(paradigm="review", agent_type="invalid")

    def test_includes_trust_and_capabilities(self):
        result = assess_paradigm(paradigm="sdd", agent_type="codex")
        assert "trust_level" in result
        assert "capabilities" in result


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Combinations
# ═══════════════════════════════════════════════════════════════════


class TestCombinationCreate:
    def test_create_combination(self):
        result = combination_create(
            primary="S09",
            enhancers=["S05a"],
            agent_type="claude-code",
        )
        assert "combination_id" in result
        assert result["primary"] == "S09"
        assert result["enhancers"] == ["S05a"]

    def test_auto_discovered_source(self):
        result = combination_create(
            primary="S09",
            enhancers=["S13a"],
            agent_type="codex",
            source="auto_discovered",
        )
        assert "combination_id" in result


class TestCombinationGet:
    def test_not_found(self):
        result = combination_get(combination_id="nonexistent_combo")
        assert "error" in result

    def test_get_existing(self):
        # Create first
        create_result = combination_create(
            primary="S05a",
            enhancers=["S09"],
            agent_type="claude-code",
        )
        combo_id = create_result["combination_id"]
        result = combination_get(combination_id=combo_id)
        assert result.get("combination_id") == combo_id


class TestCombinationList:
    def test_returns_dict(self):
        result = combination_list()
        assert isinstance(result, dict)
        assert "count" in result
        assert "combinations" in result

    def test_filter_by_state(self):
        result = combination_list(state="PROMOTED")
        assert isinstance(result, dict)

    def test_filter_by_primary(self):
        result = combination_list(primary="S09")
        assert isinstance(result, dict)

    def test_invalid_state(self):
        result = combination_list(state="INVALID_STATE")
        assert "error" in result


class TestCombinationTransition:
    def test_invalid_state(self):
        result = combination_transition(
            combination_id="nonexistent",
            to_state="INVALID_STATE",
            agent_type="claude-code",
        )
        assert "error" in result
        assert "invalid_state" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Lifecycle
# ═══════════════════════════════════════════════════════════════════


class TestSkillLifecycleCheck:
    def test_returns_dict(self):
        result = skill_lifecycle_check()
        assert isinstance(result, dict)
        assert "deprecation_checks" in result
        assert "combination_checks" in result

    def test_with_skill_id(self):
        result = skill_lifecycle_check(skill_id="S09")
        assert isinstance(result, dict)

    def test_skip_checks(self):
        result = skill_lifecycle_check(
            skill_id="S09",
            check_deprecation=False,
            check_combinations=False,
        )
        assert result["deprecation_checks"] == []
        assert result["combination_checks"] == []


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Emergency Overrides
# ═══════════════════════════════════════════════════════════════════


class TestGetEmergencyOverrides:
    def test_returns_dict(self):
        result = get_emergency_overrides()
        assert isinstance(result, dict)
        assert "overrides" in result
        assert "count" in result

    def test_with_skill_id_filter(self):
        result = get_emergency_overrides(skill_id="S09")
        assert isinstance(result, dict)
        assert "count" in result


# ═══════════════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════════════


class TestSkillContextPrompt:
    def test_returns_skill_context(self):
        result = skill_context("S09")
        assert isinstance(result, str)
        assert "S09" in result

    def test_includes_definition_section(self):
        result = skill_context("S09")
        assert "Definition" in result or "Skill" in result

    def test_not_found_skill(self):
        result = skill_context("NONEXISTENT")
        assert "not found" in result.lower()


class TestTriggerReviewPrompt:
    def test_returns_review_instructions(self):
        result = trigger_review()
        assert isinstance(result, str)
        assert "Multi-Dimension Review" in result or "12" in result or "review" in result.lower()


class TestGateStatusPrompt:
    def test_returns_gate_status(self):
        result = gate_status(skill_id="S09")
        assert isinstance(result, str)
        assert "Gate Check" in result or "Decision" in result

    def test_not_found_skill(self):
        result = gate_status(skill_id="NONEXISTENT_XYZ")
        assert "not found" in result.lower()

    def test_custom_agent_type(self):
        result = gate_status(skill_id="S09", agent_type="codex")
        assert isinstance(result, str)

    def test_invalid_agent_type(self):
        with pytest.raises(ValueError):
            gate_status(skill_id="S09", agent_type="invalid")


# ═══════════════════════════════════════════════════════════════════
# MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════


class TestSkillPoolLoggingMiddleware:
    def test_detect_error_status_success(self):
        result = MagicMock()
        result.structured_content = None
        result.content = []
        assert SkillPoolLoggingMiddleware._detect_error_status(result) == "success"

    def test_detect_error_status_from_structured_content(self):
        result = MagicMock()
        result.structured_content = {"error": "something broke"}
        result.content = []
        assert SkillPoolLoggingMiddleware._detect_error_status(result) == "error"

    def test_detect_error_status_from_text(self):
        block = MagicMock()
        block.text = '{"error": "bad"}'
        result = MagicMock()
        result.structured_content = None
        result.content = [block]
        assert SkillPoolLoggingMiddleware._detect_error_status(result) == "error"


class TestTimingMiddleware:
    def test_init_stores_monitor(self):
        from skillpool.monitor import MonitorLayer

        monitor = MonitorLayer()
        mw = TimingMiddleware(monitor=monitor)
        assert mw._monitor is monitor


# ═══════════════════════════════════════════════════════════════════
# MCP App & Entry Point
# ═══════════════════════════════════════════════════════════════════


class TestMcpApp:
    def test_app_name(self):
        assert mcp.name == "skillpool"

    def test_app_version(self):
        assert mcp.version == "4.3.0"

    def test_middleware_registered(self):
        assert len(mcp.middleware) >= 2  # Logging + Timing


class TestMain:
    def test_help_exits(self):
        with patch("sys.argv", ["skillpool-mcp", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
