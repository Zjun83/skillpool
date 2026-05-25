"""SkillPool MCP Server — JSON-RPC stdio server for agent runtime queries.

Implements the Model Context Protocol (MCP) over stdio transport,
exposing 7 core tools: skill_list, skill_get, skill_gate,
check_updates, report_usage, get_emergency_overrides, assess_paradigm.

Protocol version: 2024-11-05
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Configuration ───────────────────────────────────────────────────

GATE_THRESHOLD = 0.5  # Quality score below this → gate FAIL
OVERRIDE_KEY = "admin"  # Emergency override key

# Paradigm definitions for assess_paradigm
PARADIGMS = {
    "retrieval": {
        "domains": ["retrieval", "search", "web"],
        "description": "Information retrieval and search",
    },
    "generation": {
        "domains": ["generation", "coding", "writing"],
        "description": "Content and code generation",
    },
    "reasoning": {
        "domains": ["reasoning", "analysis", "planning"],
        "description": "Logical reasoning and analysis",
    },
    "interaction": {
        "domains": ["interaction", "communication", "ui"],
        "description": "User interaction and communication",
    },
    "automation": {
        "domains": ["automation", "ci", "deployment"],
        "description": "Process automation and CI/CD",
    },
}


# ── Registry helpers ────────────────────────────────────────────────


def _find_skillpool_dir() -> Path:
    """Locate the .skillpool directory (cwd or home)."""
    cwd_dir = Path.cwd() / ".skillpool"
    if cwd_dir.exists():
        return cwd_dir
    home_dir = Path.home() / ".skillpool"
    if home_dir.exists():
        return home_dir
    return cwd_dir  # fallback — will return empty registry


def _read_registry(skillpool_dir: Path) -> list[dict[str, Any]]:
    """Read and parse registry.jsonl from the given directory.

    Returns an empty list if the file does not exist or is empty.
    """
    registry_path = skillpool_dir / "registry.jsonl"
    if not registry_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with open(registry_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _read_audit_log(skillpool_dir: Path) -> list[dict[str, Any]]:
    """Read the MCP audit log for usage tracking."""
    audit_path = skillpool_dir / "mcp_audit.jsonl"
    if not audit_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with open(audit_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _append_audit_log(skillpool_dir: Path, entry: dict[str, Any]) -> None:
    """Append an entry to the MCP audit log."""
    audit_path = skillpool_dir / "mcp_audit.jsonl"
    with open(audit_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _read_emergency_overrides(skillpool_dir: Path) -> dict[str, Any]:
    """Read emergency overrides configuration."""
    overrides_path = skillpool_dir / "emergency_overrides.json"
    if not overrides_path.exists():
        return {"overrides": {}}
    try:
        with open(overrides_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"overrides": {}}


# ── JSON-RPC response builders ──────────────────────────────────────


def _success(result: Any, req_id: int | None) -> dict[str, Any]:
    """Build a JSON-RPC success response."""
    resp: dict[str, Any] = {"jsonrpc": "2.0", "result": result}
    if req_id is not None:
        resp["id"] = req_id
    return resp


def _error(code: int, message: str, req_id: int | None) -> dict[str, Any]:
    """Build a JSON-RPC error response."""
    resp: dict[str, Any] = {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
    }
    if req_id is not None:
        resp["id"] = req_id
    return resp


# ── Tool definitions ────────────────────────────────────────────────

TOOLS = [
    {
        "name": "skill_list",
        "description": "List all registered skills, optionally filtered by minimum quality score.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_score": {
                    "type": "number",
                    "description": "Minimum quality score filter (0.0-1.0)",
                },
            },
        },
    },
    {
        "name": "skill_get",
        "description": "Get details for a specific skill by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name to look up",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "skill_gate",
        "description": "Check gate status for a skill (PASS / FAIL / OVERRIDE).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name to check",
                },
                "override_key": {
                    "type": "string",
                    "description": "Emergency override key (bypasses gate if valid)",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "check_updates",
        "description": "Check for available updates by comparing skill versions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Optional: check updates for a specific skill only",
                },
            },
        },
    },
    {
        "name": "report_usage",
        "description": "Report skill usage event for telemetry and audit tracking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill that was used",
                },
                "agent_type": {
                    "type": "string",
                    "description": "Type of agent that used the skill (e.g. claude-code, codex)",
                },
                "outcome": {
                    "type": "string",
                    "description": "Outcome of the usage: success, failure, partial",
                },
            },
            "required": ["skill_name"],
        },
    },
    {
        "name": "get_emergency_overrides",
        "description": "Retrieve current emergency override settings for gate bypasses.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_expired": {
                    "type": "boolean",
                    "description": "Whether to include expired overrides (default: false)",
                },
            },
        },
    },
    {
        "name": "assess_paradigm",
        "description": "Assess which paradigm(s) a skill belongs to based on domain and metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Skill name to assess",
                },
            },
            "required": ["skill_name"],
        },
    },
]


# ── Tool handlers ───────────────────────────────────────────────────


def _tool_skill_list(arguments: dict[str, Any], skillpool_dir: Path) -> list[dict[str, Any]]:
    """Handle skill_list tool call."""
    min_score = arguments.get("min_score", 0.0)
    entries = _read_registry(skillpool_dir)
    filtered = [e for e in entries if e.get("quality_score", 0) >= min_score]
    return [{"type": "text", "text": json.dumps(filtered)}]


def _tool_skill_get(arguments: dict[str, Any], skillpool_dir: Path) -> list[dict[str, Any]]:
    """Handle skill_get tool call."""
    name = arguments.get("name", "")
    entries = _read_registry(skillpool_dir)
    for entry in entries:
        if entry.get("name") == name:
            return [{"type": "text", "text": json.dumps(entry)}]
    return [{"type": "text", "text": json.dumps({"error": f"Skill '{name}' not found"})}]


def _tool_skill_gate(arguments: dict[str, Any], skillpool_dir: Path) -> list[dict[str, Any]]:
    """Handle skill_gate tool call."""
    name = arguments.get("name", "")
    override_key = arguments.get("override_key")

    entries = _read_registry(skillpool_dir)
    skill = None
    for entry in entries:
        if entry.get("name") == name:
            skill = entry
            break

    if skill is None:
        return [{"type": "text", "text": json.dumps({"error": f"Skill '{name}' not found"})}]

    score = skill.get("quality_score", 0)

    # Check override first
    if override_key and override_key == OVERRIDE_KEY:
        result = {"status": "OVERRIDE", "score": score, "name": name}
    elif score >= GATE_THRESHOLD:
        result = {"status": "PASS", "score": score, "name": name}
    else:
        result = {"status": "FAIL", "score": score, "name": name, "reason": "below threshold"}

    return [{"type": "text", "text": json.dumps(result)}]


def _tool_check_updates(arguments: dict[str, Any], skillpool_dir: Path) -> list[dict[str, Any]]:
    """Handle check_updates tool call.

    Compares registered skill versions against a hypothetical latest version.
    In a production system, this would query a remote registry or git source.
    For now, it checks if the skill has a 'latest_version' field that differs
    from its 'version' field.
    """
    skill_name = arguments.get("skill_name")
    entries = _read_registry(skillpool_dir)

    if skill_name:
        entries = [e for e in entries if e.get("name") == skill_name]

    updates = []
    for entry in entries:
        current = entry.get("version", "0.0.0")
        latest = entry.get("latest_version")
        if latest and latest != current:
            updates.append(
                {
                    "name": entry.get("name", "unknown"),
                    "current_version": current,
                    "latest_version": latest,
                    "update_available": True,
                }
            )
        else:
            updates.append(
                {
                    "name": entry.get("name", "unknown"),
                    "current_version": current,
                    "latest_version": latest or current,
                    "update_available": False,
                }
            )

    return [{"type": "text", "text": json.dumps(updates)}]


def _tool_report_usage(arguments: dict[str, Any], skillpool_dir: Path) -> list[dict[str, Any]]:
    """Handle report_usage tool call.

    Records a usage event in the MCP audit log for telemetry and tracking.
    """
    skill_name = arguments.get("skill_name", "")
    agent_type = arguments.get("agent_type", "unknown")
    outcome = arguments.get("outcome", "success")

    # Verify skill exists
    entries = _read_registry(skillpool_dir)
    found = any(e.get("name") == skill_name for e in entries)

    audit_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "skill_usage",
        "skill_name": skill_name,
        "agent_type": agent_type,
        "outcome": outcome,
        "skill_registered": found,
    }

    _append_audit_log(skillpool_dir, audit_entry)

    result = {
        "recorded": True,
        "skill_name": skill_name,
        "agent_type": agent_type,
        "outcome": outcome,
        "skill_registered": found,
        "message": "Usage event recorded"
        if found
        else f"Usage recorded but skill '{skill_name}' not in registry",
    }

    return [{"type": "text", "text": json.dumps(result)}]


def _tool_get_emergency_overrides(
    arguments: dict[str, Any], skillpool_dir: Path
) -> list[dict[str, Any]]:
    """Handle get_emergency_overrides tool call.

    Returns current emergency override settings, optionally including expired ones.
    """
    include_expired = arguments.get("include_expired", False)
    overrides_data = _read_emergency_overrides(skillpool_dir)
    overrides = overrides_data.get("overrides", {})

    now = datetime.now(timezone.utc).isoformat()

    active_overrides = []
    for skill_name, override_info in overrides.items():
        entry = {"skill_name": skill_name}
        if isinstance(override_info, dict):
            entry["reason"] = override_info.get("reason", "")
            entry["expires_at"] = override_info.get("expires_at", "")
            is_expired = False
            if override_info.get("expires_at"):
                try:
                    expires = datetime.fromisoformat(override_info["expires_at"])
                    is_expired = datetime.now(timezone.utc) > expires
                except (ValueError, TypeError):
                    is_expired = False
            entry["expired"] = is_expired
            entry["active"] = not is_expired
        else:
            # Simple boolean or string override
            entry["active"] = bool(override_info)
            entry["expired"] = False

        if include_expired or entry.get("active", True):
            active_overrides.append(entry)

    result = {
        "overrides": active_overrides,
        "total_count": len(overrides),
        "active_count": len(active_overrides),
        "checked_at": now,
    }

    return [{"type": "text", "text": json.dumps(result)}]


def _tool_assess_paradigm(arguments: dict[str, Any], skillpool_dir: Path) -> list[dict[str, Any]]:
    """Handle assess_paradigm tool call.

    Determines which paradigm(s) a skill belongs to based on its domain
    and metadata fields.
    """
    skill_name = arguments.get("skill_name", "")
    entries = _read_registry(skillpool_dir)

    skill = None
    for entry in entries:
        if entry.get("name") == skill_name:
            skill = entry
            break

    if skill is None:
        return [{"type": "text", "text": json.dumps({"error": f"Skill '{skill_name}' not found"})}]

    domain = skill.get("domain", "").lower()
    tags = [t.lower() for t in skill.get("tags", [])]
    all_keywords = [domain] + tags

    # Score each paradigm by keyword overlap
    paradigm_scores: dict[str, float] = {}
    for paradigm_name, paradigm_info in PARADIGMS.items():
        score = 0.0
        for kw in all_keywords:
            if kw in paradigm_info["domains"]:
                score += 1.0
        # Normalize to 0-1 range
        max_possible = len(paradigm_info["domains"])
        paradigm_scores[paradigm_name] = (
            min(score / max(max_possible, 1), 1.0) if score > 0 else 0.0
        )

    # Select paradigms with non-zero score
    matched = [
        {
            "paradigm": name,
            "confidence": score,
            "description": PARADIGMS[name]["description"],
        }
        for name, score in sorted(paradigm_scores.items(), key=lambda x: -x[1])
        if score > 0
    ]

    # If no paradigm matched, assign to "unknown"
    if not matched:
        matched = [
            {"paradigm": "unknown", "confidence": 0.0, "description": "No matching paradigm found"}
        ]

    # Primary paradigm is the highest-scoring one
    primary = matched[0]["paradigm"]

    result = {
        "skill_name": skill_name,
        "domain": domain,
        "primary_paradigm": primary,
        "paradigms": matched,
    }

    return [{"type": "text", "text": json.dumps(result)}]


# ── Request dispatcher ──────────────────────────────────────────────

_TOOL_HANDLERS = {
    "skill_list": _tool_skill_list,
    "skill_get": _tool_skill_get,
    "skill_gate": _tool_skill_gate,
    "check_updates": _tool_check_updates,
    "report_usage": _tool_report_usage,
    "get_emergency_overrides": _tool_get_emergency_overrides,
    "assess_paradigm": _tool_assess_paradigm,
}


def _handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a JSON-RPC request and return a response dict.

    Supports:
      - initialize
      - tools/list
      - tools/call
    """
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return _success(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "skillpool", "version": "4.1.0"},
            },
            req_id,
        )

    if method == "tools/list":
        return _success({"tools": TOOLS}, req_id)

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = _TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return _error(-32601, f"Unknown tool: {tool_name}", req_id)
        skillpool_dir = _find_skillpool_dir()
        content = handler(arguments, skillpool_dir)
        return _success({"content": content}, req_id)

    return _error(-32601, f"Method not found: {method}", req_id)


# ── Stdio server loop ───────────────────────────────────────────────


def _serve_stdio() -> None:
    """Read JSON-RPC requests from stdin, write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            resp = _error(-32700, "Parse error", None)
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue

        response = _handle_request(request)
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


# ── Entry point ─────────────────────────────────────────────────────


def main() -> None:
    """Entry point for skillpool-mcp command."""
    _serve_stdio()


if __name__ == "__main__":
    main()
