"""Tests for SkillPool MCP server request handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from skillpool.mcp_server import _handle_request, _read_registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skillpool_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary .skillpool directory with sample registry."""
    sp_dir = tmp_path / ".skillpool"
    sp_dir.mkdir()
    # Write a sample registry
    registry_path = sp_dir / "registry.jsonl"
    entries = [
        {"name": "web-search", "quality_score": 0.85, "domain": "retrieval"},
        {"name": "code-gen", "quality_score": 0.72, "domain": "generation"},
        {"name": "draft-skill", "quality_score": 0.35, "domain": "draft"},
    ]
    with open(registry_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    # Patch cwd so _find_skillpool_dir finds our temp dir
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
# initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_initialize_response(self, skillpool_dir: Path) -> None:
        req = _make_request("initialize")
        resp = _handle_request(req)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert result["serverInfo"]["name"] == "skillpool"

    def test_initialize_capabilities(self, skillpool_dir: Path) -> None:
        req = _make_request("initialize")
        resp = _handle_request(req)
        caps = resp["result"]["capabilities"]
        assert "tools" in caps


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


class TestToolsList:
    def test_tools_list_returns_three_tools(self, skillpool_dir: Path) -> None:
        req = _make_request("tools/list")
        resp = _handle_request(req)
        tools = resp["result"]["tools"]
        assert len(tools) == 7
        names = {t["name"] for t in tools}
        assert names == {
            "skill_list",
            "skill_get",
            "skill_gate",
            "check_updates",
            "report_usage",
            "get_emergency_overrides",
            "assess_paradigm",
        }

    def test_tools_have_input_schema(self, skillpool_dir: Path) -> None:
        req = _make_request("tools/list")
        resp = _handle_request(req)
        for tool in resp["result"]["tools"]:
            assert "inputSchema" in tool


# ---------------------------------------------------------------------------
# tools/call — skill_list
# ---------------------------------------------------------------------------


class TestSkillList:
    def test_list_all_skills(self, skillpool_dir: Path) -> None:
        req = _make_request("tools/call", {"name": "skill_list", "arguments": {}})
        resp = _handle_request(req)
        content = resp["result"]["content"]
        assert content[0]["type"] == "text"
        entries = json.loads(content[0]["text"])
        assert len(entries) == 3

    def test_list_with_min_score_filter(self, skillpool_dir: Path) -> None:
        req = _make_request("tools/call", {"name": "skill_list", "arguments": {"min_score": 0.7}})
        resp = _handle_request(req)
        entries = json.loads(resp["result"]["content"][0]["text"])
        assert len(entries) == 2
        assert all(e["quality_score"] >= 0.7 for e in entries)


# ---------------------------------------------------------------------------
# tools/call — skill_get
# ---------------------------------------------------------------------------


class TestSkillGet:
    def test_get_existing_skill(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call", {"name": "skill_get", "arguments": {"name": "web-search"}}
        )
        resp = _handle_request(req)
        entry = json.loads(resp["result"]["content"][0]["text"])
        assert entry["name"] == "web-search"
        assert entry["quality_score"] == 0.85

    def test_get_nonexistent_skill(self, skillpool_dir: Path) -> None:
        req = _make_request("tools/call", {"name": "skill_get", "arguments": {"name": "missing"}})
        resp = _handle_request(req)
        text = resp["result"]["content"][0]["text"]
        assert "not found" in text


# ---------------------------------------------------------------------------
# tools/call — skill_gate
# ---------------------------------------------------------------------------


class TestSkillGate:
    def test_gate_pass(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call", {"name": "skill_gate", "arguments": {"name": "web-search"}}
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "PASS"
        assert result["score"] == 0.85

    def test_gate_fail(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call", {"name": "skill_gate", "arguments": {"name": "draft-skill"}}
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "FAIL"

    def test_gate_override(self, skillpool_dir: Path) -> None:
        req = _make_request(
            "tools/call",
            {"name": "skill_gate", "arguments": {"name": "draft-skill", "override_key": "admin"}},
        )
        resp = _handle_request(req)
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "OVERRIDE"

    def test_gate_nonexistent_skill(self, skillpool_dir: Path) -> None:
        req = _make_request("tools/call", {"name": "skill_gate", "arguments": {"name": "missing"}})
        resp = _handle_request(req)
        text = resp["result"]["content"][0]["text"]
        assert "not found" in text


# ---------------------------------------------------------------------------
# Unknown method
# ---------------------------------------------------------------------------


class TestUnknownMethod:
    def test_unknown_method_returns_error(self, skillpool_dir: Path) -> None:
        req = _make_request("unknown/method")
        resp = _handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# _read_registry helper
# ---------------------------------------------------------------------------


class TestReadRegistry:
    def test_read_from_existing_registry(self, skillpool_dir: Path) -> None:
        entries = _read_registry(skillpool_dir)
        assert len(entries) == 3

    def test_read_from_missing_registry(self, tmp_path: Path) -> None:
        entries = _read_registry(tmp_path / "nonexistent")
        assert entries == []
