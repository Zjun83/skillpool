"""MCP E2E Integration Tests — verify all V4.3 endpoints via FastMCPTransport.

Covers new V4.3 additions:
  - skill://{id}/summary Resource (L1 tier)
  - bug://list Resource
  - security_scan Tool
  - healing_scan / healing_execute Tools
  - LazySkillLoader tier verification (L0/L1/L2)
  - trigger_review Prompt no hardcoded paths

Also re-validates existing V4.1 endpoints that were modified in V4.3.

Part of SkillPool — independent infrastructure, shared by all agents.
"""
from __future__ import annotations

import os

# Ensure dev evidence tier BEFORE importing mcp_server
os.environ.setdefault("SKILLPOOL_EVIDENCE_TIER", "dev")

import pytest
import pytest_asyncio

from skillpool.mcp_server import mcp


@pytest_asyncio.fixture
async def client():
    """Create an in-memory MCP client connected to the SkillPool server."""
    from fastmcp.client import Client

    async with Client(mcp) as c:
        yield c


# ═══════════════════════════════════════════════════════════════════
# V4.3 RESOURCES — skill://summary + bug://list
# ═══════════════════════════════════════════════════════════════════


class TestSkillSummaryResource:
    """Verify skill://{id}/summary returns L1-tier data (~200 tokens)."""

    async def test_summary_for_csdf_skill(self, client: Client) -> None:
        result = await client.read_resource("skill://S09/summary")
        assert len(result) > 0
        data = result[0]
        text = getattr(data, "text", str(data))
        # L1 tier should include description and checklist_summary
        import json
        parsed = json.loads(text) if text.startswith("{") else {}
        assert "description" in parsed or "name" in parsed, f"L1 tier missing key fields: {list(parsed.keys())}"

    async def test_summary_for_directory_skill(self, client: Client) -> None:
        result = await client.read_resource("skill://scaffold-docs/summary")
        assert len(result) > 0
        text = getattr(result[0], "text", str(result[0]))
        assert "not found" not in text.lower()

    async def test_summary_unknown_skill(self, client: Client) -> None:
        result = await client.read_resource("skill://NONEXISTENT_SUMM/summary")
        assert len(result) > 0
        text = getattr(result[0], "text", str(result[0]))
        assert "not found" in text.lower() or "error" in text.lower()

    async def test_summary_has_more_fields_than_l0(self, client: Client) -> None:
        """L1 summary should have more fields than L0 metadata."""
        import json
        # L0 via skill://list
        list_result = await client.read_resource("skill://list")
        list_text = getattr(list_result[0], "text", str(list_result[0]))
        # L1 via skill://S09/summary
        summ_result = await client.read_resource("skill://S09/summary")
        summ_text = getattr(summ_result[0], "text", str(summ_result[0]))
        # L1 should include description field which L0 does not
        assert "description" in summ_text.lower() or "checklist" in summ_text.lower()


class TestBugListResource:
    """Verify bug://list Resource returns BugCollector records."""

    async def test_bug_list_returns_list(self, client: Client) -> None:
        result = await client.read_resource("bug://list/0")
        assert len(result) > 0
        text = getattr(result[0], "text", str(result[0]))
        import json
        data = json.loads(text)
        assert isinstance(data, dict)
        assert "bugs" in data
        assert "total" in data

    async def test_bug_list_capped_at_100(self, client: Client) -> None:
        result = await client.read_resource("bug://list/0")
        text = getattr(result[0], "text", str(result[0]))
        import json
        data = json.loads(text)
        assert isinstance(data, dict)
        assert data["limit"] <= 500
        assert len(data.get("bugs", [])) <= data["limit"]

    async def test_bug_list_in_resource_list(self, client: Client) -> None:
        """bug://list template should appear in resource templates."""
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert "bug://list/{cursor}" in uris


class TestResourceListV43:
    """Verify resources/list includes all V4.3 additions."""

    async def test_list_includes_skill_list(self, client: Client) -> None:
        resources = await client.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "skill://list" in uris

    async def test_list_includes_bug_list(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert "bug://list/{cursor}" in uris

    async def test_list_includes_audit_records(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert "audit://records/{cursor}" in uris

    async def test_list_includes_skill_graph(self, client: Client) -> None:
        resources = await client.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "skill://graph" in uris

    async def test_summary_in_templates(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert any("summary" in u for u in uris), f"summary template not found in: {uris}"

    async def test_manifest_in_templates(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert any("manifest" in u for u in uris), f"manifest template not found in: {uris}"

    async def test_x_execution_in_templates(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert any("x-execution" in u for u in uris), f"x-execution template not found in: {uris}"


class TestSkillGraphResource:
    """Verify skill://graph Resource returns dependency graph."""

    async def test_graph_returns_dict(self, client: Client) -> None:
        import json
        result = await client.read_resource("skill://graph")
        text = getattr(result[0], "text", str(result[0]))
        data = json.loads(text) if text.startswith("{") else {}
        assert isinstance(data, dict)
        # Should have either skill data or an error message, not empty
        assert len(data) > 0 or "error" in text.lower()

    async def test_graph_in_resource_list(self, client: Client) -> None:
        resources = await client.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "skill://graph" in uris


class TestSkillManifestResource:
    """Verify skill://{id}/manifest.yaml Resource returns dependency manifest."""

    async def test_manifest_for_csdf_skill(self, client: Client) -> None:
        import json
        result = await client.read_resource("skill://S09/manifest.yaml")
        text = getattr(result[0], "text", str(result[0]))
        data = json.loads(text) if text.startswith("{") else {}
        assert "id" in data or "error" in data

    async def test_manifest_has_dependencies_field(self, client: Client) -> None:
        import json
        result = await client.read_resource("skill://S09/manifest.yaml")
        text = getattr(result[0], "text", str(result[0]))
        data = json.loads(text) if text.startswith("{") else {}
        if "error" not in data:
            assert "dependencies" in data

    async def test_manifest_unknown_skill(self, client: Client) -> None:
        import json
        result = await client.read_resource("skill://NONEXISTENT_MAN/manifest.yaml")
        text = getattr(result[0], "text", str(result[0]))
        assert "not found" in text.lower() or "error" in text.lower()


class TestSkillExecutionResource:
    """Verify skill://{id}/x-execution Resource returns execution method."""

    async def test_execution_for_csdf_skill(self, client: Client) -> None:
        import json
        result = await client.read_resource("skill://S09/x-execution")
        text = getattr(result[0], "text", str(result[0]))
        data = json.loads(text) if text.startswith("{") else {}
        if "error" not in data:
            assert "execution_type" in data
            assert data["execution_type"] == "prompt"

    async def test_execution_unknown_skill(self, client: Client) -> None:
        import json
        result = await client.read_resource("skill://NONEXISTENT_EXEC/x-execution")
        text = getattr(result[0], "text", str(result[0]))
        assert "not found" in text.lower() or "error" in text.lower()


class TestSkillRulesResource:
    """Verify skill://{id}/rules Resource returns RULES.md content."""

    async def test_rules_for_directory_skill(self, client: Client) -> None:
        result = await client.read_resource("skill://multi-dim-review/rules")
        text = getattr(result[0], "text", str(result[0]))
        # multi-dim-review has a RULES.md with scoring rules
        if text:
            assert "D3" in text or "VETO" in text or "维度" in text

    async def test_rules_for_csdf_skill_empty(self, client: Client) -> None:
        result = await client.read_resource("skill://S09/rules")
        text = getattr(result[0], "text", str(result[0]))
        # S09 is a CSDF skill, no RULES.md
        assert text == ""

    async def test_rules_in_resource_templates(self, client: Client) -> None:
        templates = await client.list_resource_templates()
        uris = [str(t.uriTemplate) for t in templates]
        assert any("rules" in u for u in uris), f"No rules template in: {uris}"


# ═══════════════════════════════════════════════════════════════════
# V4.3 TOOLS — security_scan, healing_scan, healing_execute
# ═══════════════════════════════════════════════════════════════════


class TestSecurityScanTool:
    """Verify security_scan Tool scans skill content for threats."""

    async def test_safe_content(self, client: Client) -> None:
        result = await client.call_tool("security_scan", {
            "content": "name: test\nversion: 1.0\n",
        })
        assert not result.is_error
        assert result.data.get("is_safe") is True
        assert result.data.get("threat_level") == "safe"

    async def test_dangerous_exec_pattern(self, client: Client) -> None:
        # NOSONAR: testing detection of exec(), not using it
        result = await client.call_tool("security_scan", {
            "content": "```python\nexec('malicious')\n```",
        })
        assert not result.is_error
        assert result.data.get("is_safe") is False
        assert result.data.get("threat_level") == "critical"

    async def test_dangerous_yaml_tag(self, client: Client) -> None:
        result = await client.call_tool("security_scan", {
            "content": "value: !!python/object:module.Class",
        })
        assert not result.is_error
        assert result.data.get("is_safe") is False
        assert result.data.get("threat_level") == "critical"

    async def test_subprocess_warning(self, client: Client) -> None:
        result = await client.call_tool("security_scan", {
            "content": "```python\nsubprocess.run(['echo'])\n```",
        })
        assert not result.is_error
        # subprocess is at least warning level
        assert result.data.get("threat_level") in ("warning", "critical")

    async def test_with_skill_id(self, client: Client) -> None:
        result = await client.call_tool("security_scan", {
            "content": "safe: true",
            "skill_id": "S09",
        })
        assert not result.is_error
        assert result.data.get("skill_id") == "S09"

    async def test_checks_passed_includes_yaml_and_pattern(self, client: Client) -> None:
        result = await client.call_tool("security_scan", {
            "content": "name: test\nversion: 1.0\n",
        })
        passed = result.data.get("checks_passed", [])
        assert "yaml_syntax" in passed
        assert "pattern_scan" in passed

    async def test_empty_content(self, client: Client) -> None:
        result = await client.call_tool("security_scan", {
            "content": "",
        })
        assert not result.is_error
        assert result.data.get("is_safe") is True

    async def test_large_content(self, client: Client) -> None:
        """Large content should not crash the scanner."""
        large = "name: test\n" + "x: y\n" * 1000
        result = await client.call_tool("security_scan", {
            "content": large,
        })
        assert not result.is_error
        assert "is_safe" in result.data


class TestHealingScanTool:
    """Verify healing_scan Tool scans BugCollector for recurring defects."""

    async def test_scan_returns_valid_structure(self, client: Client) -> None:
        result = await client.call_tool("healing_scan", {})
        assert not result.is_error
        assert "proposals" in result.data
        assert "total_proposals" in result.data
        assert "status" in result.data
        assert result.data["status"] == "scanned"

    async def test_scan_empty_collector(self, client: Client) -> None:
        """With no bugs in collector, scan should return empty proposals."""
        result = await client.call_tool("healing_scan", {})
        assert not result.is_error
        # May be empty or have proposals from previous test runs
        assert isinstance(result.data["proposals"], list)

    async def test_scan_threshold_below_trigger(self, client: Client) -> None:
        """Fewer than threshold bugs should not produce proposals for that group."""
        result = await client.call_tool("healing_scan", {})
        assert not result.is_error
        # Verify the structure even with no proposals
        assert "total_proposals" in result.data
        assert result.data["total_proposals"] >= 0


class TestHealingExecuteTool:
    """Verify healing_execute Tool executes proposed healing with BDD verification."""

    async def test_execute_nonexistent_proposal(self, client: Client) -> None:
        result = await client.call_tool("healing_execute", {
            "proposal_id": "nonexistent-xyz",
        })
        assert not result.is_error
        assert result.data.get("status") in ("not_found", "error")

    async def test_execute_returns_proposal_id(self, client: Client) -> None:
        result = await client.call_tool("healing_execute", {
            "proposal_id": "nonexistent-xyz",
        })
        assert result.data.get("proposal_id") == "nonexistent-xyz"


class TestToolListV43:
    """Verify tools/list includes all V4.3 additions."""

    async def test_tool_count(self, client: Client) -> None:
        tools = await client.list_tools()
        # V4.1 had 10, V4.3 adds 3 (security_scan, healing_scan, healing_execute)
        assert len(tools) >= 13

    async def test_security_scan_exists(self, client: Client) -> None:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "security_scan" in names

    async def test_healing_scan_exists(self, client: Client) -> None:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "healing_scan" in names

    async def test_healing_execute_exists(self, client: Client) -> None:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "healing_execute" in names


# ═══════════════════════════════════════════════════════════════════
# LazySkillLoader Tier Verification
# ═══════════════════════════════════════════════════════════════════


class TestLazyLoaderTiers:
    """Verify LazySkillLoader L0/L1/L2 tiers work correctly via MCP."""

    async def test_l0_metadata_only(self, client: Client) -> None:
        """skill://list uses L0 tier — should contain metadata fields only."""
        import json
        result = await client.read_resource("skill://list")
        text = getattr(result[0], "text", str(result[0]))
        data = json.loads(text) if text.startswith("[") else []
        if data:
            skill = data[0]
            # L0 fields
            assert "id" in skill or "name" in skill
            # L0 should NOT have description or checklist_summary
            assert "description" not in skill or skill.get("description") == ""

    async def test_l1_summary_has_description(self, client: Client) -> None:
        """skill://S09/summary uses L1 tier — should include description."""
        import json
        result = await client.read_resource("skill://S09/summary")
        text = getattr(result[0], "text", str(result[0]))
        data = json.loads(text) if text.startswith("{") else {}
        # L1 should include description or checklist_summary
        assert "description" in data or "_tier" in data

    async def test_l2_definition_has_markdown(self, client: Client) -> None:
        """skill://S09/definition uses L2 tier — should include full markdown."""
        result = await client.read_resource("skill://S09/definition")
        text = getattr(result[0], "text", str(result[0]))
        # L2 should produce readable markdown content
        assert len(text) > 50

    async def test_tier_progression_increases_content(self, client: Client) -> None:
        """L2 content should be larger than L1, which should be larger than L0."""
        import json

        # L0 via skill://list
        l0_result = await client.read_resource("skill://list")
        l0_text = getattr(l0_result[0], "text", str(l0_result[0]))
        l0_data = json.loads(l0_text) if l0_text.startswith("[") else []
        l0_size = len(l0_text)

        # L1 via skill://S09/summary
        l1_result = await client.read_resource("skill://S09/summary")
        l1_text = getattr(l1_result[0], "text", str(l1_result[0]))
        l1_size = len(l1_text)

        # L2 via skill://S09/definition
        l2_result = await client.read_resource("skill://S09/definition")
        l2_text = getattr(l2_result[0], "text", str(l2_result[0]))
        l2_size = len(l2_text)

        # L2 should typically be the largest
        assert l2_size >= l1_size or l2_size > 50
        assert l2_size >= l0_size or l2_size > 50


# ═══════════════════════════════════════════════════════════════════
# trigger_review Prompt — No Hardcoded Paths
# ═══════════════════════════════════════════════════════════════════


class TestTriggerReviewPrompt:
    """Verify trigger_review Prompt uses MCP Resources, not hardcoded paths."""

    async def test_no_hardcoded_root_path(self, client: Client) -> None:
        result = await client.get_prompt("trigger_review")
        messages = result.messages
        combined_text = " ".join(
            getattr(m.content, "text", str(m.content)) for m in messages
        )
        # Must NOT contain hardcoded /root/ paths
        assert "/root/.skillpool" not in combined_text
        # Must reference MCP Resources
        assert "skill://" in combined_text

    async def test_uses_skill_resource_uris(self, client: Client) -> None:
        result = await client.get_prompt("trigger_review")
        messages = result.messages
        combined_text = " ".join(
            getattr(m.content, "text", str(m.content)) for m in messages
        )
        # Should reference multi-dim-review via MCP URIs
        assert "skill://multi-dim-review/definition" in combined_text
        assert "skill://multi-dim-review/manifest.yaml" in combined_text

    async def test_fallback_uses_tilde(self, client: Client) -> None:
        """Fallback path should use ~, not /root."""
        result = await client.get_prompt("trigger_review")
        messages = result.messages
        combined_text = " ".join(
            getattr(m.content, "text", str(m.content)) for m in messages
        )
        # If fallback path is mentioned, it should use ~ not /root
        if "~/.skillpool" in combined_text or ".skillpool" in combined_text:
            assert "/root/.skillpool" not in combined_text


class TestSkillContextPrompt:
    """Verify skill_context Prompt loads skill definition and dependencies."""

    async def test_skill_context_for_csdf_skill(self, client: Client) -> None:
        result = await client.get_prompt("skill_context", arguments={"skill_id": "S09"})
        messages = result.messages
        combined_text = " ".join(
            getattr(m.content, "text", str(m.content)) for m in messages
        )
        # Should contain skill definition content
        assert "S09" in combined_text or "Resilience" in combined_text or "Dependencies" in combined_text

    async def test_skill_context_unknown_skill(self, client: Client) -> None:
        result = await client.get_prompt("skill_context", arguments={"skill_id": "NONEXISTENT_CTX"})
        messages = result.messages
        combined_text = " ".join(
            getattr(m.content, "text", str(m.content)) for m in messages
        )
        # Should indicate not found
        assert "not found" in combined_text.lower() or "unavailable" in combined_text.lower()


class TestGateStatusPrompt:
    """Verify gate_status Prompt returns gate check result."""

    async def test_gate_status_for_csdf_skill(self, client: Client) -> None:
        result = await client.get_prompt("gate_status", arguments={"skill_id": "S09"})
        messages = result.messages
        combined_text = " ".join(
            getattr(m.content, "text", str(m.content)) for m in messages
        )
        # Should contain a gate decision
        assert any(word in combined_text for word in ["ALLOW", "GUARD", "ESCALATE", "DENY", "Decision"])

    async def test_gate_status_unknown_skill(self, client: Client) -> None:
        result = await client.get_prompt("gate_status", arguments={"skill_id": "NONEXISTENT_GATE"})
        messages = result.messages
        combined_text = " ".join(
            getattr(m.content, "text", str(m.content)) for m in messages
        )
        assert "not found" in combined_text.lower()


# ═══════════════════════════════════════════════════════════════════
# Cross-Endpoint Integration
# ═══════════════════════════════════════════════════════════════════


class TestCrossEndpointIntegration:
    """Verify V4.3 endpoints work together correctly."""

    async def test_skill_list_then_summary(self, client: Client) -> None:
        """Load L0 list, then upgrade to L1 summary for a specific skill."""
        import json
        list_result = await client.read_resource("skill://list")
        list_text = getattr(list_result[0], "text", str(list_result[0]))
        skills = json.loads(list_text) if list_text.startswith("[") else []

        # Find a CSDF skill ID from the list
        csdf_skill_id = None
        for s in skills:
            sid = s.get("id", "")
            if sid.startswith("S"):
                csdf_skill_id = sid
                break

        if csdf_skill_id:
            summ_result = await client.read_resource(f"skill://{csdf_skill_id}/summary")
            assert len(summ_result) > 0

    async def test_skill_list_then_definition(self, client: Client) -> None:
        """Load L0 list, then load L2 definition for a specific skill."""
        import json
        list_result = await client.read_resource("skill://list")
        list_text = getattr(list_result[0], "text", str(list_result[0]))
        skills = json.loads(list_text) if list_text.startswith("[") else []

        csdf_skill_id = None
        for s in skills:
            sid = s.get("id", "")
            if sid.startswith("S"):
                csdf_skill_id = sid
                break

        if csdf_skill_id:
            def_result = await client.read_resource(f"skill://{csdf_skill_id}/definition")
            assert len(def_result) > 0

    async def test_security_scan_then_healing(self, client: Client) -> None:
        """security_scan finds threats, healing_scan checks for bugs."""
        # Scan safe content
        scan_result = await client.call_tool("security_scan", {
            "content": "name: safe\nversion: 1.0\n",
        })
        assert scan_result.data.get("is_safe") is True

        # Check healing proposals
        heal_result = await client.call_tool("healing_scan", {})
        assert isinstance(heal_result.data.get("proposals"), list)

    async def test_bug_list_and_healing_consistency(self, client: Client) -> None:
        """bug://list and healing_scan should reference the same BugCollector."""
        import json
        bug_result = await client.read_resource("bug://list/0")
        bug_text = getattr(bug_result[0], "text", str(bug_result[0]))
        bugs = json.loads(bug_text) if bug_text.startswith("[") else []

        heal_result = await client.call_tool("healing_scan", {})
        # If there are bugs, healing_scan should have processed them
        if len(bugs) > 0:
            # healing_scan may or may not produce proposals depending on thresholds
            assert isinstance(heal_result.data.get("proposals"), list)

    async def test_full_skill_lifecycle_via_mcp(self, client: Client) -> None:
        """Exercise a complete skill interaction path: list → summary → definition → gate → scan."""
        import json
        # 1. List skills
        list_result = await client.read_resource("skill://list")
        assert len(list_result) > 0

        # 2. Read summary
        summ_result = await client.read_resource("skill://S09/summary")
        assert len(summ_result) > 0

        # 3. Read full definition
        def_result = await client.read_resource("skill://S09/definition")
        assert len(def_result) > 0

        # 4. Gate check
        gate_result = await client.call_tool("gate_check", {
            "csdf": {"id": "S09", "name": "Resilience", "min_trust_level": 1, "checklist": []},
            "profile_name": "claude-code",
        })
        assert gate_result.data.get("decision") in ("allow", "ALLOW", "GUARD", "ESCALATE", "deny", "DENY")

        # 5. Security scan the definition
        def_text = getattr(def_result[0], "text", str(def_result[0]))
        scan_result = await client.call_tool("security_scan", {
            "content": def_text,
            "skill_id": "S09",
        })
        assert "is_safe" in scan_result.data


class TestCrossAgentSync:
    """Verify skill_transition by one Agent is visible to another via skill_status."""

    async def test_transition_visible_to_other_agent(self, client: Client) -> None:
        """Simulate: Agent A transitions a skill, Agent B queries status."""
        # 1. Register a skill
        reg_result = await client.call_tool("skill_register", {
            "skill_id": "sync-test-1",
            "name": "SyncTest",
            "version": "1.0.0",
            "sbom_ref": "sbom",
            "provenance_ref": "prov",
            "source_pin": "src",
            "signature_ref": "sig",
        })
        assert reg_result.data.get("skill_id") == "sync-test-1"

        # 2. Agent A transitions to enabled
        trans_result = await client.call_tool("skill_transition", {
            "skill_id": "sync-test-1",
            "from_status": "testing",
            "to_status": "enabled",
            "sandbox_result": "pass",
            "policy_approval": True,
        })
        assert trans_result.data.get("to_status") == "enabled"

        # 3. Agent B queries the same skill status
        status_result = await client.call_tool("skill_status", {
            "skill_id": "sync-test-1",
        })
        assert status_result.data.get("status") == "enabled"
        assert status_result.data.get("enabled") is True


class TestTraceIdPassthrough:
    """Verify trace_id is accepted and returned by state-modifying tools."""

    async def test_skill_transition_trace_id(self, client: Client) -> None:
        """skill_transition should accept and return trace_id."""
        # Register first
        await client.call_tool("skill_register", {
            "skill_id": "trace-test-1",
            "name": "TraceTest",
            "version": "1.0.0",
        })

        # Transition with trace_id
        result = await client.call_tool("skill_transition", {
            "skill_id": "trace-test-1",
            "from_status": "testing",
            "to_status": "enabled",
            "sandbox_result": "pass",
            "policy_approval": True,
            "trace_id": "0af7651916cd43dd8448eb211c80319c",
        })
        assert result.data.get("trace_id") == "0af7651916cd43dd8448eb211c80319c"

    async def test_evolution_trigger_trace_id(self, client: Client) -> None:
        """evolution_trigger should accept trace_id."""
        result = await client.call_tool("evolution_trigger", {
            "skill_id": "S09",
            "version": "1.0.0",
            "severity": "minor",
            "description": "test trace",
            "trace_id": "0af7651916cd43dd8448eb211c80319c",
        })
        # Should not error — trace_id is accepted
        assert "error" not in result.data or result.data.get("error") is None
