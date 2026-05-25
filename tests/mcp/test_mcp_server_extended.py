"""Tests for SkillPool MCP server — extended tools (check_updates, report_usage,
get_emergency_overrides, assess_paradigm)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from skillpool.mcp_server import _handle_request

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skillpool_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary .skillpool directory with sample registry and overrides."""
    sp_dir = tmp_path / ".skillpool"
    sp_dir.mkdir()

    # Write a sample registry with version info and domain/tags
    registry_path = sp_dir / "registry.jsonl"
    entries = [
        {
            "name": "web-search",
            "quality_score": 0.85,
            "domain": "retrieval",
            "version": "1.0.0",
            "latest_version": "1.2.0",
            "tags": ["search", "web"],
        },
        {
            "name": "code-gen",
            "quality_score": 0.72,
            "domain": "generation",
            "version": "2.0.0",
            "tags": ["coding"],
        },
        {
            "name": "draft-skill",
            "quality_score": 0.35,
            "domain": "draft",
            "version": "0.1.0",
        },
    ]
    with open(registry_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    # Write emergency overrides with one active and one expired
    overrides_path = sp_dir / "emergency_overrides.json"
    past_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    overrides_data = {
        "overrides": {
            "draft-skill": {
                "reason": "Emergency hotfix",
                "expires_at": future_ts,
            },
            "expired-override": {
                "reason": "Old override",
                "expires_at": past_ts,
            },
            "simple-override": True,
        }
    }
    with open(overrides_path, "w") as f:
        json.dump(overrides_data, f)

    # Create empty audit log
    (sp_dir / "mcp_audit.jsonl").touch()

    monkeypatch.chdir(tmp_path)
    return sp_dir


def _make_request(
    method: str, params: dict[str, Any] | None = None, req_id: int = 1
) -> dict[str, Any]:
    """Build a JSON-RPC request dict."""
    req: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        req["params"] = params
    return req


# ---------------------------------------------------------------------------
# tools/list — now returns 7 tools
# ---------------------------------------------------------------------------


class TestToolsListExtended:
    def test_tools_list_returns_seven_tools(self, skillpool_dir: Path) -> None:
        req = _make_request("tools/list")
        resp = _handle_request(req)
        tools = resp["result"]["tools"]
        assert len(tools) == 7
        names = {t["name"] for t in tools}
        expected = {
            "skill_list",
            "skill_get",
            "skill_gate",
            "check_updates",
            "report_usage",
            "get_emergency_overrides",
            "assess_paradigm",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# tools/call — check_updates
# ---------------------------------------------------------------------------


class TestCheckUpdates:
    def test_check_updates_all_skills(self, skillpool_dir: Path) -> None:
        req = _make_request("tools/call", {"name": "check_updates", "arguments": {}})
        resp = _handle_request(req)
        content = resp["result"]["content"]
        assert content[0]["type"] == "text"
        updates = json.loads(content[0]["text"])
        assert len(updates) == 3
        # web-search has update available
        ws = next(u for u in updates if u["name"] == "web-search")
        assert ws["update_available"] is True
        assert ws["current_version"] == "1.0.0"
        assert ws["latest_version"] == "1.2.0"

    def test_check_updates_specific_skill(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call", {"name": "check_updates", "arguments": {"skill_name": "code-gen"}}
        )
        resp = _handle_request(req)
        updates = json.loads(resp["result"]["content"][0]["text"])
        assert len(updates) == 1
        assert updates[0]["name"] == "code-gen"
        assert updates[0]["update_available"] is False

    def test_check_updates_nonexistent_skill(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call", {"name": "check_updates", "arguments": {"skill_name": "missing"}}
        )
        resp = _handle_request(req)
        updates = json.loads(resp["result"]["content"][0]["text"])
        assert len(updates) == 0

    def test_check_updates_skill_no_version_field(self, skillpool_dir: Path) -> None:
        """Skills without version field should default to 0.0.0."""
        req = _make_request(
            "tools/call", {"name": "check_updates", "arguments": {"skill_name": "draft-skill"}}
        )
        resp = _handle_request(req)
        updates = json.loads(resp["result"]["content"][0]["text"])
        assert len(updates) == 1
        assert updates[0]["current_version"] == "0.1.0"
        assert updates[0]["update_available"] is False


# ---------------------------------------------------------------------------
# tools/call — report_usage
# ---------------------------------------------------------------------------


class TestReportUsage:
    def test_report_usage_registered_skill(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "report_usage",
                "arguments": {
                    "skill_name": "web-search",
                    "agent_type": "codex",
                    "outcome": "success",
                },
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["recorded"] is True
        assert result["skill_registered"] is True
        assert result["agent_type"] == "codex"

    def test_report_usage_unregistered_skill(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "report_usage",
                "arguments": {"skill_name": "missing-skill", "agent_type": "claude"},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["recorded"] is True
        assert result["skill_registered"] is False

    def test_report_usage_writes_audit_log(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "report_usage",
                "arguments": {"skill_name": "web-search", "agent_type": "codex"},
            },
        )
        _handle_request(req)
        # Check audit log was written
        audit_path = skillpool_dir / "mcp_audit.jsonl"
        assert audit_path.exists()
        with open(audit_path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert entry["event"] == "skill_usage"
        assert entry["skill_name"] == "web-search"

    def test_report_usage_defaults(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "report_usage",
                "arguments": {"skill_name": "code-gen"},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["agent_type"] == "unknown"
        assert result["outcome"] == "success"


# ---------------------------------------------------------------------------
# tools/call — get_emergency_overrides
# ---------------------------------------------------------------------------


class TestGetEmergencyOverrides:
    def test_get_overrides_active_only(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "get_emergency_overrides",
                "arguments": {},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        # Active overrides: draft-skill (future expiry) + simple-override
        # Expired override should be excluded by default
        assert result["active_count"] >= 2
        names = {o["skill_name"] for o in result["overrides"]}
        assert "draft-skill" in names
        assert "simple-override" in names

    def test_get_overrides_include_expired(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "get_emergency_overrides",
                "arguments": {"include_expired": True},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        # Should include all 3 overrides
        assert result["total_count"] == 3
        names = {o["skill_name"] for o in result["overrides"]}
        assert "expired-override" in names

    def test_get_overrides_expired_marked_correctly(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "get_emergency_overrides",
                "arguments": {"include_expired": True},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        expired_entry = next(
            o for o in result["overrides"] if o["skill_name"] == "expired-override"
        )
        assert expired_entry["expired"] is True
        assert expired_entry["active"] is False

    def test_get_overrides_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No overrides file → empty result."""
        sp_dir = tmp_path / ".skillpool"
        sp_dir.mkdir()
        (sp_dir / "registry.jsonl").touch()
        (sp_dir / "mcp_audit.jsonl").touch()
        monkeypatch.chdir(tmp_path)
        req = _make_request(
            "tools/call",
            {
                "name": "get_emergency_overrides",
                "arguments": {},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["overrides"] == []
        assert result["total_count"] == 0


# ---------------------------------------------------------------------------
# tools/call — assess_paradigm
# ---------------------------------------------------------------------------


class TestAssessParadigm:
    def test_assess_paradigm_retrieval(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "assess_paradigm",
                "arguments": {"skill_name": "web-search"},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["skill_name"] == "web-search"
        assert result["primary_paradigm"] == "retrieval"
        assert len(result["paradigms"]) >= 1
        # First paradigm should be retrieval (highest score)
        assert result["paradigms"][0]["paradigm"] == "retrieval"

    def test_assess_paradigm_generation(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "assess_paradigm",
                "arguments": {"skill_name": "code-gen"},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["primary_paradigm"] == "generation"

    def test_assess_paradigm_unknown_domain(self, skillpool_dir: Path) -> None:
        """Skill with domain not matching any paradigm → 'unknown'."""
        req = _make_request(
            "tools/call",
            {
                "name": "assess_paradigm",
                "arguments": {"skill_name": "draft-skill"},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["primary_paradigm"] == "unknown"

    def test_assess_paradigm_nonexistent_skill(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "assess_paradigm",
                "arguments": {"skill_name": "missing"},
            },
        )
        resp = _handle_request(req)
        text = resp["result"]["content"][0]["text"]
        assert "not found" in text

    def test_assess_paradigm_returns_domain(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {
                "name": "assess_paradigm",
                "arguments": {"skill_name": "web-search"},
            },
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["domain"] == "retrieval"
