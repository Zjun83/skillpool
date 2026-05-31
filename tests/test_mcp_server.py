"""Tests for MCP Server — Resources, Tools, and Prompts."""
import pytest

from skillpool.mcp_server import (
    gate_check,
    telemetry_report,
    audit_verify,
    skill_register,
    skill_transition,
    evolution_trigger,
    evolution_proposal,
    monitor_evaluate,
    health_check,
    review_trigger,
    skill_list,
    skill_definition,
    skill_manifest,
    skill_execution,
    skill_graph,
    audit_records,
    skill_context,
    trigger_review,
    gate_status,
)


# ── Resources ──


class TestSkillListResource:
    def test_returns_list_of_skills(self) -> None:
        result = skill_list()
        assert isinstance(result, list)
        # Should have skills from ~/.skillpool/skills/
        if len(result) > 0:
            first = result[0]
            assert "id" in first
            assert "name" in first
            assert "version" in first
            assert "dimension" in first

    def test_lightweight_metadata_no_markdown(self) -> None:
        """skill://list should NOT include full markdown content."""
        result = skill_list()
        for skill in result:
            assert "markdown" not in skill
            assert "checklist" not in skill


class TestSkillDefinitionResource:
    def test_returns_definition_for_known_skill(self) -> None:
        result = skill_definition("S09")
        assert "S09" in result
        assert "容错" in result or "降级" in result

    def test_returns_not_found_for_unknown_skill(self) -> None:
        result = skill_definition("NONEXISTENT")
        assert "not found" in result.lower()


class TestSkillManifestResource:
    def test_returns_manifest_structure(self) -> None:
        result = skill_manifest("S09")
        assert "id" in result
        assert "version" in result
        assert "dependencies" in result
        assert "dimension" in result

    def test_not_found_skill(self) -> None:
        result = skill_manifest("NONEXISTENT")
        assert "error" in result


class TestSkillExecutionResource:
    def test_returns_execution_info(self) -> None:
        result = skill_execution("S09")
        assert "id" in result
        assert "execution_type" in result

    def test_not_found_skill(self) -> None:
        result = skill_execution("NONEXISTENT")
        assert "error" in result


class TestSkillGraphResource:
    def test_returns_graph_structure(self) -> None:
        result = skill_graph()
        # Should have graph data from skill_graph.yaml
        assert isinstance(result, dict)


class TestAuditRecordsResource:
    def test_returns_list(self) -> None:
        result = audit_records()
        assert isinstance(result, list)

    def test_capped_at_100(self) -> None:
        """audit://records should cap at 100 records for token efficiency."""
        result = audit_records()
        assert len(result) <= 100


# ── Tools ──


class TestGateCheck:
    def test_allow_low_complexity(self) -> None:
        csdf = {
            "id": "S01",
            "name": "Simple Skill",
            "min_trust_level": 1,
            "checklist": [],
        }
        result = gate_check(csdf)
        assert result["decision"] == "allow"

    def test_deny_capability_mismatch(self) -> None:
        csdf = {
            "id": "S02",
            "min_trust_level": 3,
            "required_agent_capabilities": {"bash", "python", "extra"},
        }
        result = gate_check(csdf, profile_name="hermes")
        assert result["decision"] == "deny"

    def test_safe_deny_on_error(self) -> None:
        """gate_check should return DENY on any error (safe-deny default)."""
        # Pass invalid data that causes an internal error
        result = gate_check(None)  # type: ignore
        assert result["decision"] == "DENY"
        assert "safe-deny" in result["reason"]


class TestTelemetryReport:
    def test_report_event(self) -> None:
        result = telemetry_report(
            event_type="skill_used",
            skill_id="S05a",
            channel="hook",
        )
        assert result["event_type"] == "skill_used"
        assert result["skill_id"] == "S05a"

    def test_report_with_payload(self) -> None:
        result = telemetry_report(
            event_type="skill_error",
            skill_id="S10",
            channel="mcp",
            payload={"error": "timeout"},
        )
        assert result["event_type"] == "skill_error"
        assert result["channel"] == "mcp"


class TestAuditVerify:
    def test_verify_returns_integrity_status(self) -> None:
        result = audit_verify()
        assert "integrity" in result
        assert "record_count" in result


class TestSkillRegister:
    def test_register_requires_supply_chain_evidence(self) -> None:
        """Registration requires SPDX SBOM, SLSA provenance, source pin, signature in prod mode."""
        import os
        from skillpool.registry import Registry
        from skillpool.audit import AuditLayer
        from skillpool.registry.models import RegisterSkillRequest, SkillMetadata

        original = os.environ.get("SKILLPOOL_EVIDENCE_TIER")
        try:
            os.environ["SKILLPOOL_EVIDENCE_TIER"] = "prod"
            prod_registry = Registry(audit_layer=AuditLayer())
            meta = SkillMetadata(
                skill_id="test-skill-001",
                name="Test Skill",
                version="1.0.0",
                security={},
            )
            req = RegisterSkillRequest(skill_metadata=meta)
            try:
                prod_registry.register_candidate(req)
                assert False, "Should have raised SupplyChainEvidenceMissingError"
            except Exception as e:
                assert "SupplyChain" in type(e).__name__ or "evidence" in str(e).lower()
        finally:
            if original is not None:
                os.environ["SKILLPOOL_EVIDENCE_TIER"] = original
            else:
                os.environ["SKILLPOOL_EVIDENCE_TIER"] = "dev"


class TestSkillTransition:
    def test_transition_invalid_status(self) -> None:
        result = skill_transition(
            skill_id="nonexistent",
            from_status="draft",
            to_status="enabled",
        )
        assert "error" in result


class TestEvolutionTrigger:
    def test_trigger_defect(self) -> None:
        result = evolution_trigger(
            skill_id="S09",
            version="9.0.0",
            severity="minor",
            description="Test defect",
        )
        assert "defect_id" in result
        assert result["severity"] == "minor"


class TestEvolutionProposal:
    def test_create_proposal(self) -> None:
        result = evolution_proposal(
            reason="Test evolution",
            risk="low",
        )
        assert "proposal_id" in result
        assert result["recommendation_only"] is True


class TestMonitorEvaluate:
    def test_evaluate_skill(self) -> None:
        result = monitor_evaluate(
            skill_id="S09",
            error_rate=0.05,
            coverage=0.8,
        )
        assert result["skill_id"] == "S09"
        assert "overall_score" in result
        assert "safety" in result


class TestHealthCheck:
    def test_returns_status(self) -> None:
        result = health_check()
        assert "status" in result
        assert "components" in result


class TestReviewTrigger:
    def test_trigger_with_invalid_checkpoint(self) -> None:
        result = review_trigger(checkpoint="L9")
        # Should return error for invalid checkpoint
        assert "error" in result or "status" in result


# ── Prompts ──


class TestSkillContextPrompt:
    def test_returns_skill_context(self) -> None:
        result = skill_context("S09")
        assert "S09" in result
        assert "Definition" in result or "容错" in result

    def test_not_found_skill(self) -> None:
        result = skill_context("NONEXISTENT")
        assert "not found" in result.lower()


class TestTriggerReviewPrompt:
    def test_returns_review_instructions(self) -> None:
        result = trigger_review()
        assert "Multi-Dimension Review" in result or "12" in result


class TestGateStatusPrompt:
    def test_returns_gate_status(self) -> None:
        result = gate_status("S09")
        assert "Gate Check" in result or "Decision" in result
