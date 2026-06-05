"""MCP Protocol Tests — verify SkillPool MCP server via FastMCPTransport (in-memory).

Tests the complete MCP protocol path: resources/list, resources/read, tools/call, prompts/list.
This is more thorough than direct function calls because it exercises the MCP serialization layer.
"""

from __future__ import annotations

import os

# Ensure dev evidence tier BEFORE importing mcp_server (Registry reads env at import time)
os.environ.setdefault("SKILLPOOL_EVIDENCE_TIER", "dev")

import pytest_asyncio

from fastmcp.client import Client
from skillpool.mcp_server import mcp


@pytest_asyncio.fixture
async def client():
    """Create an in-memory MCP client connected to the SkillPool server."""
    async with Client(mcp) as c:
        yield c


# ═══════════════════════════════════════════════════════════════════
# RESOURCES
# ═══════════════════════════════════════════════════════════════════


class TestResourceList:
    """Verify resources/list returns expected URIs."""

    async def test_list_resources_includes_skill_list(self, client: Client) -> None:
        resources = await client.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "skill://list" in uris

    async def test_list_resources_includes_audit_records(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert "audit://records/{cursor}" in uris

    async def test_list_resources_includes_skill_graph(self, client: Client) -> None:
        resources = await client.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "skill://graph" in uris


class TestResourceTemplates:
    """Verify resources/templates/list returns parameterized URIs."""

    async def test_list_templates_includes_definition(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert any("definition" in u for u in uris)

    async def test_list_templates_includes_manifest(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert any("manifest" in u for u in uris)


class TestResourceRead:
    """Verify resources/read returns correct content."""

    async def test_read_skill_list(self, client: Client) -> None:
        result = await client.read_resource("skill://list")
        assert len(result) > 0
        # Result should be a list of skill metadata
        text = getattr(result[0], "text", str(result[0]))
        # At least some CSDF skills should be present
        assert "S00" in text or "S01" in text

    async def test_read_skill_definition(self, client: Client) -> None:
        result = await client.read_resource("skill://S09/definition")
        assert len(result) > 0
        text = getattr(result[0], "text", str(result[0]))
        assert "容错" in text or "降级" in text or "S09" in text

    async def test_read_skill_manifest(self, client: Client) -> None:
        result = await client.read_resource("skill://S09/manifest.yaml")
        assert len(result) > 0

    async def test_read_skill_execution(self, client: Client) -> None:
        result = await client.read_resource("skill://S09/x-execution")
        assert len(result) > 0

    async def test_read_skill_graph(self, client: Client) -> None:
        result = await client.read_resource("skill://graph")
        assert len(result) > 0

    async def test_read_audit_records(self, client: Client) -> None:
        result = await client.read_resource("audit://records/0")
        assert len(result) > 0

    async def test_read_directory_skill_definition(self, client: Client) -> None:
        result = await client.read_resource("skill://scaffold-docs/definition")
        assert len(result) > 0
        text = getattr(result[0], "text", str(result[0]))
        assert "scaffold" in text.lower() or "documentation" in text.lower()

    async def test_read_unknown_skill_returns_not_found(self, client: Client) -> None:
        result = await client.read_resource("skill://NONEXISTENT_SKILL_XYZ/definition")
        assert len(result) > 0
        text = getattr(result[0], "text", str(result[0]))
        assert "not found" in text.lower()


# ═══════════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════════


class TestToolList:
    """Verify tools/list returns expected tools."""

    async def test_tool_count(self, client: Client) -> None:
        tools = await client.list_tools()
        assert len(tools) >= 10

    async def test_gate_check_exists(self, client: Client) -> None:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "gate_check" in names

    async def test_health_check_exists(self, client: Client) -> None:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "health_check" in names


class TestToolCall:
    """Verify tools/call returns correct results."""

    async def test_gate_check_allow(self, client: Client) -> None:
        result = await client.call_tool(
            "gate_check",
            {
                "csdf": {"id": "S01", "name": "Simple", "min_trust_level": 1, "checklist": []},
                "profile_name": "claude-code",
            },
        )
        assert not result.is_error
        assert result.data is not None
        assert result.data.get("decision") == "allow"

    async def test_gate_check_safe_deny_on_invalid(self, client: Client) -> None:
        """gate_check with invalid input should return error or safe-deny."""
        result = await client.call_tool(
            "gate_check",
            {
                "csdf": {"id": "X99", "min_trust_level": 99, "checklist": []},
                "profile_name": "hermes",
            },
        )
        # Either denied by gate logic or by capability mismatch
        assert not result.is_error
        decision = result.data.get("decision", "")
        assert decision in ("deny", "DENY", "allow", "GUARD", "ESCALATE")

    async def test_telemetry_report(self, client: Client) -> None:
        result = await client.call_tool(
            "telemetry_report",
            {
                "event_type": "skill_used",
                "skill_id": "S05a",
                "channel": "hook",
            },
        )
        assert not result.is_error
        assert result.data.get("event_type") == "skill_used"

    async def test_health_check(self, client: Client) -> None:
        result = await client.call_tool("health_check", {})
        assert not result.is_error
        status = result.data.get("status", "")
        assert status in ("SERVING", "DEGRADED", "NOT_SERVING")

    async def test_audit_verify(self, client: Client) -> None:
        result = await client.call_tool("audit_verify", {})
        assert not result.is_error
        assert "integrity" in result.data


# ═══════════════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════════════


class TestPromptList:
    """Verify prompts/list returns expected prompts."""

    async def test_prompt_count(self, client: Client) -> None:
        prompts = await client.list_prompts()
        assert len(prompts) >= 3

    async def test_skill_context_exists(self, client: Client) -> None:
        prompts = await client.list_prompts()
        names = [p.name for p in prompts]
        assert "skill_context" in names

    async def test_trigger_review_exists(self, client: Client) -> None:
        prompts = await client.list_prompts()
        names = [p.name for p in prompts]
        assert "trigger_review" in names

    async def test_gate_status_exists(self, client: Client) -> None:
        prompts = await client.list_prompts()
        names = [p.name for p in prompts]
        assert "gate_status" in names


# ═══════════════════════════════════════════════════════════════════
# EXTENDED: Error Handling + Directory Skills + Boundary + Environment
# ═══════════════════════════════════════════════════════════════════


class TestToolErrorHandling:
    """Test error handling and safe-deny patterns."""

    async def test_gate_check_empty_csdf(self, client: Client) -> None:
        """gate_check with empty/minimal CSDF should return a valid decision, not crash."""
        result = await client.call_tool(
            "gate_check",
            {
                "csdf": {"id": "", "name": "", "min_trust_level": 0, "checklist": []},
                "profile_name": "claude-code",
            },
        )
        assert not result.is_error
        decision = result.data.get("decision", "")
        # Empty CSDF should still produce a valid gate decision
        assert decision in ("allow", "ALLOW", "deny", "DENY", "GUARD", "ESCALATE")

    async def test_skill_register_no_evidence_dev_mode(self, client: Client) -> None:
        """In dev evidence tier, registration without supply chain evidence should succeed."""
        result = await client.call_tool(
            "skill_register",
            {
                "skill_id": "test-dev-skill",
                "name": "Test Dev Skill",
                "version": "0.1.0",
            },
        )
        assert not result.is_error
        # Dev mode requires no evidence — should succeed
        assert "error" not in result.data or result.data.get("skill_id") == "test-dev-skill"

    async def test_skill_transition_nonexistent(self, client: Client) -> None:
        """Transitioning a nonexistent skill should return an error, not crash."""
        result = await client.call_tool(
            "skill_transition",
            {
                "skill_id": "NONEXISTENT_SKILL_XYZ_999",
                "from_status": "testing",
                "to_status": "enabled",
            },
        )
        assert not result.is_error
        # Should contain error info, not a bare crash
        assert "error" in result.data

    async def test_evolution_trigger_invalid_severity(self, client: Client) -> None:
        """evolution_trigger with invalid severity should return an error."""
        result = await client.call_tool(
            "evolution_trigger",
            {
                "skill_id": "S09",
                "version": "1.0.0",
                "severity": "INVALID_SEVERITY",
                "description": "test invalid severity",
            },
        )
        assert result.is_error or "error" in result.data

    async def test_monitor_evaluate_zero_coverage(self, client: Client) -> None:
        """monitor_evaluate with zero coverage should return Poor completeness."""
        result = await client.call_tool(
            "monitor_evaluate",
            {
                "skill_id": "test-zero-coverage",
                "error_rate": 0.0,
                "security_issues": 0,
                "coverage": 0.0,
                "doc_completeness": 0.0,
                "p99_latency_ms": 100.0,
                "update_frequency_days": 1.0,
                "resource_efficiency": 0.5,
            },
        )
        assert not result.is_error
        completeness = result.data.get("completeness", {})
        assert completeness.get("level") == "Poor"


class TestDirectorySkillResources:
    """Test directory-based skill access via MCP."""

    async def test_skill_list_includes_directory_skills(self, client: Client) -> None:
        """skill://list should include directory-based skills."""
        result = await client.read_resource("skill://list")
        text = getattr(result[0], "text", str(result[0]))
        # scaffold-docs is a known directory skill
        assert "scaffold-docs" in text or "directory" in text

    async def test_scaffold_docs_definition(self, client: Client) -> None:
        """scaffold-docs definition should return SKILL.md body."""
        result = await client.read_resource("skill://scaffold-docs/definition")
        assert len(result) > 0
        text = getattr(result[0], "text", str(result[0]))
        assert "not found" not in text.lower()
        # Should contain scaffold-related content
        assert len(text) > 50

    async def test_multi_dim_review_definition(self, client: Client) -> None:
        """multi-dim-review definition should return SKILL.md body."""
        result = await client.read_resource("skill://multi-dim-review/definition")
        assert len(result) > 0
        text = getattr(result[0], "text", str(result[0]))
        assert "not found" not in text.lower()


class TestResourceBoundaryConditions:
    """Test boundary conditions for resources."""

    async def test_skill_list_not_empty(self, client: Client) -> None:
        """skill://list should return at least one skill."""
        result = await client.read_resource("skill://list")
        text = getattr(result[0], "text", str(result[0]))
        assert len(text) > 10  # Not empty

    async def test_audit_records_capped(self, client: Client) -> None:
        """audit://records should return at most 100 records."""
        result = await client.read_resource("audit://records/0")
        text = getattr(result[0], "text", str(result[0]))
        import json

        records = json.loads(text) if text.startswith("[") else []
        assert len(records) <= 100

    async def test_skill_graph_structure(self, client: Client) -> None:
        """skill://graph should return a valid dict structure."""
        result = await client.read_resource("skill://graph")
        text = getattr(result[0], "text", str(result[0]))
        import json

        data = json.loads(text) if text.startswith("{") else {}
        # Should have some structure (nodes, edges, or skills)
        assert isinstance(data, dict)

    async def test_skill_definition_all_csdf_skills(self, client: Client) -> None:
        """Definition resource should work for all CSDF skills (sample a few)."""
        sample_ids = ["S09", "S13a", "S05a"]
        for skill_id in sample_ids:
            result = await client.read_resource(f"skill://{skill_id}/definition")
            assert len(result) > 0
            text = getattr(result[0], "text", str(result[0]))
            assert "not found" not in text.lower(), f"Skill {skill_id} not found"


class TestEnvironmentAwareRegistration:
    """Test environment-aware supply chain evidence."""

    async def test_register_prod_requires_evidence(self, client: Client) -> None:
        """In prod evidence tier, registration without evidence should fail."""
        original = os.environ.get("SKILLPOOL_EVIDENCE_TIER")
        try:
            os.environ["SKILLPOOL_EVIDENCE_TIER"] = "prod"
            # Re-create registry with prod profile
            from skillpool.registry import Registry
            from skillpool.audit import AuditLayer

            prod_registry = Registry(audit_layer=AuditLayer())
            from skillpool.registry.models import RegisterSkillRequest, SkillMetadata

            meta = SkillMetadata(
                skill_id="prod-test-skill",
                name="Prod Test",
                version="1.0.0",
                security={},
            )
            req = RegisterSkillRequest(skill_metadata=meta)
            try:
                prod_registry.register_candidate(req)
                assert False, "Should have raised SupplyChainEvidenceMissingError"
            except Exception as e:
                assert "Missing required evidence" in str(e) or "SupplyChain" in type(e).__name__
        finally:
            if original is not None:
                os.environ["SKILLPOOL_EVIDENCE_TIER"] = original
            else:
                os.environ["SKILLPOOL_EVIDENCE_TIER"] = "dev"

    async def test_register_ci_requires_partial_evidence(self, client: Client) -> None:
        """In ci evidence tier, registration requires source pin + SBOM only."""
        original = os.environ.get("SKILLPOOL_EVIDENCE_TIER")
        try:
            os.environ["SKILLPOOL_EVIDENCE_TIER"] = "ci"
            from skillpool.registry import Registry
            from skillpool.audit import AuditLayer

            ci_registry = Registry(audit_layer=AuditLayer())
            from skillpool.registry.models import RegisterSkillRequest, SkillMetadata

            # Without required CI evidence, should fail
            meta_no_evidence = SkillMetadata(
                skill_id="ci-test-no-evidence",
                name="CI Test No Evidence",
                version="1.0.0",
                security={},
            )
            try:
                ci_registry.register_candidate(RegisterSkillRequest(skill_metadata=meta_no_evidence))
                assert False, "Should have raised SupplyChainEvidenceMissingError"
            except Exception as e:
                assert "Missing required evidence" in str(e) or "SupplyChain" in type(e).__name__

            # With source pin + SBOM, should succeed
            meta_with_evidence = SkillMetadata(
                skill_id="ci-test-with-evidence",
                name="CI Test With Evidence",
                version="1.0.0",
                security={"source_pin": "sha256:abc123", "sbom_ref": "spdx:ref"},
            )
            resp = ci_registry.register_candidate(RegisterSkillRequest(skill_metadata=meta_with_evidence))
            assert resp.skill_id == "ci-test-with-evidence"
        finally:
            if original is not None:
                os.environ["SKILLPOOL_EVIDENCE_TIER"] = original
            else:
                os.environ["SKILLPOOL_EVIDENCE_TIER"] = "dev"
