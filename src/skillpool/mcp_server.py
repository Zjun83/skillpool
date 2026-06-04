"""MCP Server — expose skillpool via FastMCP with Resources/Tools/Prompts separation.

Architecture (V4.1 dual-channel):
  - CLI (Start Hook): Materialization channel — one-time file writes at session start
  - MCP Resources: Read-only context delivery — skill definitions, audit records
  - MCP Tools: Governance actions — register, transition, gate_check, review, telemetry
  - MCP Prompts: User-controlled templates — skill invocation, review trigger

Why Resources vs Tools (per MCP 2025-03-26 spec):
  - Resources = application-controlled, read-only contextual data
  - Tools = model-controlled, executable functions that change state
  - Skill content delivery is read-only context → Resources
  - Governance mutations are state-changing actions → Tools
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import yaml
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware

from skillpool.materializer import Materializer
from skillpool.materializer.models import MaterializationResult
from skillpool.materializer.lazy_loader import LazySkillLoader  # Part of SkillPool — independent infrastructure
from skillpool.materializer.csdf_loader import load_csdf as _load_csdf_shared  # Part of SkillPool
from skillpool.hooks.security_scanner import SecurityScanner  # Part of SkillPool — independent infrastructure
from skillpool.telemetry import TelemetryBridge, TelemetryChannel, TelemetryEvent
from skillpool.gate import GateManager, GateResult, GateDecision
from skillpool.profile import (
    CLAUDE_CODE_PROFILE,
    CODEX_PROFILE,
    HERMES_PROFILE,
    OPENCLAW_PROFILE,
    AgentCapabilityProfile,
)
from skillpool.audit import AuditLayer, AuditRecord
from skillpool.evolver import EvolverLayer, DefectSeverity
from skillpool.registry import Registry, SkillStatus
from skillpool.monitor import MonitorLayer, FiveDimensionEvaluation, MetricType
from skillpool.monitor.bug_collector import BugCollector, BugSeverity, DefectType  # Part of SkillPool — independent infrastructure
from skillpool.monitor.self_healing import SelfHealingLoop  # Part of SkillPool — independent infrastructure
from skillpool.health import HealthManager

logger = logging.getLogger("skillpool.mcp")

mcp = FastMCP("skillpool", version="4.3.0")

# Search-first enforcement: tracks which callers have performed a search.
# Keyed by agent_type (all agents sharing the same MCP process).
# This is Agent-neutral — no dependency on Claude Code session IDs.
_search_done_callers: set[str] = set()


# ═══════════════════════════════════════════════════════════════════
# MIDDLEWARE — Logging + Timing
# ═══════════════════════════════════════════════════════════════════


class SkillPoolLoggingMiddleware(Middleware):
    """Log every MCP tool call and resource read."""

    async def on_call_tool(self, context, call_next):
        tool_name = context.message.name
        args = context.message.arguments or {}
        args_summary = {k: type(v).__name__ for k, v in args.items()} if args else {}
        logger.info("mcp_tool_call_start", extra={"tool": tool_name, "args_summary": args_summary})
        result = await call_next(context)
        status = self._detect_error_status(result)
        logger.info("mcp_tool_call_end", extra={"tool": tool_name, "status": status})
        return result

    async def on_read_resource(self, context, call_next):
        uri = str(context.message.uri) if hasattr(context.message, "uri") else "unknown"
        logger.info("mcp_resource_read_start", extra={"uri": uri})

        # Search-first enforcement: soft guidance for Resource reads
        # Hard enforcement is in skill_get Tool (for model-controlled access)
        # Resource reads can't be blocked (application-controlled), so we only log
        uri_str = uri.lower()
        if uri_str.startswith("skill://") and uri_str != "skill://list" and uri_str != "skill://graph":
            if not _search_done_callers:
                logger.info("search_enforcement_soft", extra={"uri": uri, "note": "skill_get Tool enforces hard block"})

        result = await call_next(context)
        logger.info("mcp_resource_read_end", extra={"uri": uri, "status": "success"})
        return result

    @staticmethod
    def _detect_error_status(result) -> str:
        """Detect error from ToolResult — no is_error field on FastMCP ToolResult."""
        # Check structured_content for error key
        sc = getattr(result, "structured_content", None)
        if isinstance(sc, dict) and "error" in sc:
            return "error"
        # Check content text for error indicators
        content = getattr(result, "content", [])
        for block in content:
            text = getattr(block, "text", "")
            if isinstance(text, str) and '"error"' in text:
                return "error"
        return "success"


class TimingMiddleware(Middleware):
    """Track execution time for tool calls and resource reads; store in MonitorLayer."""

    def __init__(self, monitor: MonitorLayer) -> None:
        self._monitor = monitor

    async def on_call_tool(self, context, call_next):
        tool_name = context.message.name
        start = time.monotonic()
        result = await call_next(context)
        elapsed_ms = (time.monotonic() - start) * 1000
        success = SkillPoolLoggingMiddleware._detect_error_status(result) == "success"
        self._monitor.record_latency(
            skill_id=f"mcp_tool:{tool_name}",
            latency_ms=elapsed_ms,
            success=success,
        )
        logger.debug("mcp_tool_timing", extra={"tool": tool_name, "elapsed_ms": round(elapsed_ms, 2)})
        return result

    async def on_read_resource(self, context, call_next):
        uri = str(context.message.uri) if hasattr(context.message, "uri") else "unknown"
        start = time.monotonic()
        result = await call_next(context)
        elapsed_ms = (time.monotonic() - start) * 1000
        self._monitor.record_metric(
            name="mcp_resource_read_latency_ms",
            value=elapsed_ms,
            metric_type=MetricType.HISTOGRAM,
            labels={"uri": uri},
        )
        logger.debug("mcp_resource_timing", extra={"uri": uri, "elapsed_ms": round(elapsed_ms, 2)})
        return result

_PROFILES: dict[str, AgentCapabilityProfile] = {
    "claude-code": CLAUDE_CODE_PROFILE,
    "codex": CODEX_PROFILE,
    "hermes": HERMES_PROFILE,
    "openclaw": OPENCLAW_PROFILE,
}

from skillpool.config import get_data_dir

_SKILLPOOL_DIR = get_data_dir()
_SKILLS_DIR = _SKILLPOOL_DIR / "skills"

# Resource cache — TTL-based LRU for skill definitions/rules/manifests
_RESOURCE_CACHE: dict[str, tuple[float, object]] = {}  # uri → (timestamp, result)
_RESOURCE_CACHE_TTL = 60.0  # seconds — stale entries expire after 1 minute
_RESOURCE_CACHE_MAX = 50  # max cached entries

# Shared instances (lazy-initialized)
# Part of SkillPool — independent infrastructure, shared by all agents
_audit = AuditLayer()
_evolver = EvolverLayer(audit_layer=_audit)
_registry = Registry(audit_layer=_audit)
_monitor = MonitorLayer(audit_layer=_audit)
_health = HealthManager(monitor=_monitor)
_lazy_loader = LazySkillLoader()
_bug_collector = BugCollector()  # Part of SkillPool — independent infrastructure
_self_healing = SelfHealingLoop(bug_collector=_bug_collector, evolver=_evolver)  # Part of SkillPool
_security_scanner = SecurityScanner()  # Part of SkillPool

# Register middleware on the MCP instance
mcp.add_middleware(SkillPoolLoggingMiddleware())
mcp.add_middleware(TimingMiddleware(monitor=_monitor))


def _get_profile(name: str) -> AgentCapabilityProfile:
    """Resolve profile by name. Raises ValueError for unknown agent types."""
    if name not in _PROFILES:
        raise ValueError(
            f"Unknown agent_type '{name}'. "
            f"Must be one of: {', '.join(_PROFILES.keys())}"
        )
    return _PROFILES[name]


def _cached_resource(uri: str, compute_fn):
    """TTL-based cache for MCP Resources. Returns cached value if fresh."""
    now = time.monotonic()
    if uri in _RESOURCE_CACHE:
        ts, val = _RESOURCE_CACHE[uri]
        if now - ts < _RESOURCE_CACHE_TTL:
            return val
    # Evict oldest if at capacity
    if len(_RESOURCE_CACHE) >= _RESOURCE_CACHE_MAX:
        oldest = min(_RESOURCE_CACHE, key=lambda k: _RESOURCE_CACHE[k][0])
        del _RESOURCE_CACHE[oldest]
    val = compute_fn()
    _RESOURCE_CACHE[uri] = (now, val)
    return val


def _load_csdf(skill_id: str) -> dict | None:
    """Load CSDF YAML for a skill_id from ~/.skillpool/skills/.

    Delegates to the shared csdf_loader module.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    return _load_csdf_shared(skill_id, _SKILLS_DIR)


# ═══════════════════════════════════════════════════════════════════
# RESOURCES — Application-controlled, read-only context delivery
# ═══════════════════════════════════════════════════════════════════


@mcp.resource("skill://list")
def skill_list() -> list[dict]:
    """Return lightweight metadata for all available skills (cached 60s).

    Returns only id, name, version, dimension, tags — no full content.
    Uses LazySkillLoader L0 tier for token-efficient delivery (~50 tokens/skill).

    Use skill://{skill_id}/summary for medium detail (~200 tokens).
    Use skill://{skill_id}/definition for full content.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    return _cached_resource("skill://list", lambda: _compute_skill_list())


def _compute_skill_list() -> list[dict]:
    """Compute skill list from filesystem (uncached)."""
    skills = []
    if not _SKILLS_DIR.exists():
        return skills

    # Collect all skill IDs from filesystem
    skill_ids = []
    # 1. CSDF YAML skills
    for yaml_file in sorted(_SKILLS_DIR.glob("*.yaml")):
        if yaml_file.name == "skill_graph.yaml":
            continue
        # Extract skill_id from filename: "S09-resilience-degradation" → "S09"
        stem = yaml_file.stem
        skill_id = stem.split("-")[0] if stem[0:2].isupper() else stem
        skill_ids.append(skill_id)
    # 2. Directory-based skills
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            skill_ids.append(skill_dir.name)

    # Use LazySkillLoader for L0 metadata
    loaded = _lazy_loader.preload(skill_ids, tier="L0")
    for skill_id, data in sorted(loaded.items()):
        skills.append(data)

    return skills


@mcp.resource("skill://{skill_id}/definition")
def skill_definition(skill_id: str) -> str:
    """Return the full SKILL.md content for a skill.

    Uses LazySkillLoader L2 tier (full materialization) with in-memory cache.
    First call materializes, subsequent calls return cached result.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        data = _lazy_loader.load(skill_id, tier="L2")
        # For directory-based skills, prefer the raw SKILL.md body over
        # the Materializer-generated summary (which only uses frontmatter fields)
        if "_markdown_body" in data and data["_markdown_body"]:
            return data["_markdown_body"]
        if "markdown" in data and data["markdown"]:
            return data["markdown"]
        # Materialization failed — return partial info
        name = data.get("name", skill_id)
        return f"# {name}\n\nContent unavailable (materialization errors: {data.get('_materialization_errors', [])})"
    except ValueError as e:
        return f"Skill not found: {skill_id}"


@mcp.resource("skill://{skill_id}/summary")
def skill_summary(skill_id: str) -> dict:
    """Return medium-detail metadata for a skill (~200 tokens).

    Uses LazySkillLoader L1 tier: includes description, triggers,
    veto rules, and dependencies — enough to decide whether to load
    the full definition.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        return _lazy_loader.load(skill_id, tier="L1")
    except ValueError as e:
        return {"error": f"Skill not found: {skill_id}"}


@mcp.resource("skill://{skill_id}/manifest.yaml")
def skill_manifest(skill_id: str) -> dict:
    """Return the dependency manifest for a skill.

    Includes: dependencies, conflicts, requires, veto_rule.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    csdf = _load_csdf(skill_id)
    if csdf is None:
        return {"error": f"Skill not found: {skill_id}"}

    return {
        "id": csdf.get("id", skill_id),
        "name": csdf.get("name", ""),
        "version": csdf.get("version", ""),
        "description": csdf.get("description", ""),
        "dimension": csdf.get("dimension", ""),
        "dependencies": csdf.get("dependencies", []),
        "conflicts": csdf.get("conflicts", []),
        "requires": csdf.get("requires", []),
        "synergies": csdf.get("synergies", []),
        "values": csdf.get("values", []),
        "veto_rule": csdf.get("veto_rule", ""),
        "weight": csdf.get("weight", 0),
    }


@mcp.resource("skill://{skill_id}/x-execution")
def skill_execution(skill_id: str) -> dict:
    """Return the execution method for a skill.

    Describes how the skill is invoked: prompt, script, or mcp_tool.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    csdf = _load_csdf(skill_id)
    if csdf is None:
        return {"error": f"Skill not found: {skill_id}"}

    input_schema = csdf.get("input_schema", {})
    output_schema = csdf.get("output_schema", {})

    return {
        "id": csdf.get("id", skill_id),
        "execution_type": "prompt",  # All current skills are prompt-based
        "input_schema": input_schema,
        "output_schema": output_schema,
        "checklist": csdf.get("checklist", []),
    }


@mcp.resource("skill://{skill_id}/rules")
def skill_rules(skill_id: str) -> str:
    """Return the full RULES.md content for a directory-based skill.

    For skills like multi-dim-review that have a separate RULES.md with
    detailed scoring rules, veto conditions, and blind spot management.
    Returns empty string if no RULES.md exists.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    skill_dir = _SKILLS_DIR / skill_id
    rules_path = skill_dir / "RULES.md"
    if rules_path.exists():
        return rules_path.read_text(encoding="utf-8")
    # Not a directory-based skill or no RULES.md
    return ""


@mcp.resource("skill://graph")
def skill_graph() -> dict:
    """Return the skill dependency graph (DAG structure, cached 60s)."""
    # Part of SkillPool — independent infrastructure, shared by all agents
    return _cached_resource("skill://graph", lambda: _compute_skill_graph())


def _compute_skill_graph() -> dict:
    """Compute skill graph from filesystem (uncached)."""
    graph_path = _SKILLS_DIR / "skill_graph.yaml"
    if not graph_path.exists():
        return {"error": "skill_graph.yaml not found"}

    try:
        return yaml.safe_load(graph_path.read_text()) or {}
    except Exception as e:
        return {"error": f"Failed to load graph: {e}"}


@mcp.resource("audit://records/{cursor}")
def audit_records(cursor: int = 0, limit: int = 100) -> dict:
    """Return audit records with pagination (read-only, immutable).

    Audit records cannot be modified via MCP — only read for traceability.

    Args:
        cursor: Offset index to start from (0-based).
        limit: Maximum number of records to return (1-500, default 100).
    """
    limit = max(1, min(limit, 500))
    records = _audit.get_records()
    total = len(records)
    page = records[cursor:cursor + limit]
    return {
        "total": total,
        "cursor": cursor,
        "limit": limit,
        "next_cursor": cursor + limit if cursor + limit < total else None,
        "records": [
            {
                "audit_id": r.audit_id,
                "action": r.action,
                "actor": r.actor,
                "resource_id": r.resource_id,
                "result": r.result,
                "severity": r.severity,
                "timestamp": r.created_at,
                "chain_index": r.chain_index,
            }
            for r in page
        ],
    }


@mcp.resource("bug://list/{cursor}")
def bug_list(cursor: int = 0, limit: int = 100) -> dict:
    """Return collected bug records with pagination from BugCollector.

    Query bug records captured by the 4-stage pipeline
    (Capture→Enrich→Filter→Persist). Read-only via MCP.

    Args:
        cursor: Offset index to start from (0-based).
        limit: Maximum number of records to return (1-500, default 100).
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    limit = max(1, min(limit, 500))
    bugs = _bug_collector.get_bugs()
    total = len(bugs)
    page = bugs[cursor:cursor + limit]
    return {
        "total": total,
        "cursor": cursor,
        "limit": limit,
        "next_cursor": cursor + limit if cursor + limit < total else None,
        "bugs": [b.to_dict() for b in page],
    }


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Model-controlled, state-changing governance actions
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def gate_check(csdf: dict, profile_name: str) -> dict:
    """Check gate decision for a CSDF skill.

    Returns ALLOW/GUARD/ESCALATE/DENY based on complexity and profile.
    On timeout or error, returns DENY (safe-deny default).

    Args:
        csdf: CSDF skill definition dict
        profile_name: Agent profile name — MUST be one of: claude-code, codex, hermes, openclaw
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        profile = _get_profile(profile_name)
        gate = GateManager(profile=profile)
        result = gate.check(csdf)
        return {
            "decision": str(result.decision),
            "reason": result.reason,
            "complexity_level": result.complexity.level if result.complexity else None,
            "complexity_total": result.complexity.total if result.complexity else None,
            "conditions": result.conditions,
        }
    except Exception as e:
        # Safe-deny: gate_check failure defaults to DENY
        return {
            "decision": "DENY",
            "reason": f"gate_check error (safe-deny): {type(e).__name__}: {e}",
            "complexity_level": None,
            "complexity_total": None,
            "conditions": [],
        }


@mcp.tool()
def gate_check_with_policy(
    csdf: dict,
    profile_name: str,
    policy_path: str = "",
    changed_files: Optional[list[str]] = None,
) -> dict:
    """Gate check with policy-based 4D phase enforcement.

    Extends gate_check with gate.policy integration for:
    - Path-based complexity level resolution
    - Incremental mode (git diff changed files)
    - Phase gate artifact validation
    - Emergency bypass awareness

    On timeout or error, returns DENY (safe-deny default).

    Args:
        csdf: CSDF skill definition dict
        profile_name: Agent profile name — MUST be one of: claude-code, codex, hermes, openclaw
        policy_path: Path to gate.policy YAML file
        changed_files: Optional list of changed files for incremental mode
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        profile = _get_profile(profile_name)
        gate = GateManager(profile=profile)

        from pathlib import Path as _Path
        pp = _Path(policy_path) if policy_path else None

        result = gate.check_with_policy(
            csdf,
            policy_path=pp,
            changed_files=changed_files,
        )

        state_dict = None
        if result.state:
            state_dict = result.state.model_dump(mode="json")

        return {
            "decision": str(result.decision),
            "reason": result.reason,
            "complexity_level": result.complexity.level if result.complexity else None,
            "complexity_total": result.complexity.total if result.complexity else None,
            "conditions": result.conditions,
            "policy_level": result.policy_level,
            "skip_phases": result.skip_phases,
            "state": state_dict,
        }
    except Exception as e:
        return {
            "decision": "DENY",
            "reason": f"gate_check_with_policy error (safe-deny): {type(e).__name__}: {e}",
            "complexity_level": None,
            "complexity_total": None,
            "conditions": [],
            "policy_level": None,
            "skip_phases": [],
            "state": None,
        }


@mcp.tool()
def telemetry_report(
    event_type: str,
    skill_id: str,
    channel: str = "hook",
    payload: Optional[dict] = None,
    trace_id: str = "",
) -> dict:
    """Report a telemetry event.

    On failure, silently drops the event and returns error info
    (does not block the caller).

    Args:
        event_type: Event type string (e.g., skill_used, skill_error)
        skill_id: Skill ID this event relates to
        channel: Telemetry channel (hook, mcp, log_file)
        payload: Optional event payload dict
        trace_id: Optional W3C trace ID
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        bridge = TelemetryBridge()
        event = bridge.emit(
            event_type=event_type,
            skill_id=skill_id,
            channel=channel,
            payload=payload or {},
            trace_id=trace_id,
        )
        return {
            "event_type": event.event_type,
            "skill_id": event.skill_id,
            "channel": str(event.channel),
            "timestamp": event.timestamp,
        }
    except Exception as e:
        # Silent failure — telemetry should not block operations
        return {
            "event_type": event_type,
            "skill_id": skill_id,
            "error": f"telemetry dropped: {type(e).__name__}: {e}",
            "fallback": "event logged locally for retry",
        }


@mcp.tool()
def audit_verify() -> dict:
    """Verify the integrity of the audit hash chain.

    Returns True if all records form a valid chain, False if tampered.
    On error, returns integrity=False with error details.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        return {
            "integrity": _audit.verify_integrity(),
            "record_count": _audit.get_record_count(),
        }
    except Exception as e:
        return {
            "integrity": False,
            "record_count": 0,
            "error": f"audit_verify error: {type(e).__name__}",
        }


# ── Registry tools ──


@mcp.tool()
def skill_register(
    skill_id: str,
    name: str,
    version: str,
    sbom_ref: str = "",
    provenance_ref: str = "",
    source_pin: str = "",
    signature_ref: str = "",
    trace_id: str = "",
) -> dict:
    """Register a skill candidate into the Registry.

    Requires SPDX SBOM, SLSA provenance, source pin, and signature evidence.
    Skill enters 'testing' state (not production-routable).

    Args:
        skill_id: Unique skill identifier
        name: Human-readable skill name
        version: Semantic version string
        sbom_ref: SPDX SBOM reference
        provenance_ref: SLSA provenance reference
        source_pin: Source pin (sha256 or version)
        signature_ref: Signature reference
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    from skillpool.registry.models import RegisterSkillRequest, SkillMetadata

    meta = SkillMetadata(
        skill_id=skill_id,
        name=name,
        version=version,
        security={
            "sbom_ref": sbom_ref,
            "provenance_ref": provenance_ref,
            "source_pin": source_pin,
            "signature_ref": signature_ref,
        },
    )
    req = RegisterSkillRequest(skill_metadata=meta)
    try:
        resp = _registry.register_candidate(req)
        return {"skill_id": resp.skill_id, "status": resp.status, "audit_ref": resp.audit_ref}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


@mcp.tool()
def skill_transition(
    skill_id: str,
    from_status: str,
    to_status: str,
    sandbox_result: str = "",
    policy_approval: bool = False,
    trace_id: str = "",
) -> dict:
    """Transition a skill's lifecycle state in the Registry.

    Args:
        skill_id: Skill to transition
        from_status: Current state (draft/imported/testing/enabled/disabled/deprecated)
        to_status: Target state
        sandbox_result: "pass" required for enabled state
        policy_approval: True required for enabled state
        trace_id: Optional W3C TraceContext trace_id for cross-Agent correlation
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    from skillpool.registry.models import StateTransitionRequest, SkillStatus

    try:
        req = StateTransitionRequest(
            from_status=SkillStatus(from_status),
            to_status=SkillStatus(to_status),
        )
        resp = _registry.transition_state(
            skill_id, req,
            sandbox_result=sandbox_result or None,
            policy_approval=policy_approval,
        )
        if trace_id and _audit:
            _audit.append(action="skill_transition", object_id=skill_id, result=to_status, trace_id=trace_id)
        return {
            "skill_id": resp.skill_id,
            "from_status": resp.from_status,
            "to_status": resp.to_status,
            "audit_ref": resp.audit_ref,
            "trace_id": trace_id,
        }
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


@mcp.tool()
def skill_status(skill_id: str) -> dict:
    """Query a skill's current lifecycle state and metadata.

    All Agents share the same Registry via SkillPool MCP — any state
    change made by one Agent (via skill_transition) is immediately
    visible to other Agents via this tool.

    Args:
        skill_id: Skill ID to query.
    """
    try:
        record = _registry.get_skill(skill_id)
        if record is None:
            return {"skill_id": skill_id, "status": "not_found"}
        return {
            "skill_id": record.metadata.skill_id,
            "name": record.metadata.name,
            "version": record.metadata.version,
            "status": str(record.metadata.status),
            "enabled": _registry.is_enabled(skill_id),
        }
    except Exception as e:
        return {"skill_id": skill_id, "error": type(e).__name__, "detail": str(e)}


# ── Evolver tools ──


@mcp.tool()
def evolution_trigger(
    skill_id: str,
    version: str,
    severity: str,
    description: str,
    trace_id: str = "",
) -> dict:
    """Record a defect that may trigger skill evolution.

    Args:
        skill_id: Skill with the defect
        version: Version string
        severity: "critical", "major", or "minor"
        description: Defect description
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        defect = _evolver.record_defect(
            skill_id=skill_id,
            version=version,
            severity=DefectSeverity(severity),
            description=description,
        )
        pending = _evolver.get_pending_evolutions()
        return {
            "defect_id": defect.defect_id,
            "severity": defect.severity.value,
            "evolution_queued": len(pending) > 0,
            "pending_evolutions": len(pending),
        }
    except (ValueError, KeyError) as e:
        return {"error": type(e).__name__, "detail": str(e)}


@mcp.tool()
def evolution_proposal(
    reason: str,
    risk: str = "medium",
    trace_id: str = "",
) -> dict:
    """Create a recommendation-only evolution proposal.

    IMPORTANT: This does NOT mutate any Registry state.
    It only creates a proposal for human review.

    Args:
        reason: Context/reason for the evolution
        risk: Risk level ("low", "medium", "high")
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    proposal = _evolver.create_proposal(
        context={"reason": reason},
        risk=risk,
    )
    return {
        "proposal_id": proposal.proposal_id,
        "recommendation_only": proposal.recommendation_only,
        "risk": proposal.risk,
        "audit_ref": proposal.audit_ref,
    }


# ── Monitor tools ──


@mcp.tool()
def monitor_evaluate(
    skill_id: str,
    error_rate: float = 0.0,
    security_issues: int = 0,
    coverage: float = 0.5,
    doc_completeness: float = 0.5,
    p99_latency_ms: float = 1000.0,
    update_frequency_days: float = 30.0,
    resource_efficiency: float = 0.5,
) -> dict:
    """Perform five-dimension evaluation on a skill.

    Args:
        skill_id: Skill to evaluate
        error_rate: Error rate (0.0-1.0)
        security_issues: Number of security issues
        coverage: Test coverage (0.0-1.0)
        doc_completeness: Documentation completeness (0.0-1.0)
        p99_latency_ms: P99 latency in milliseconds
        update_frequency_days: Days since last update
        resource_efficiency: Resource efficiency (0.0-1.0)
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        eval_ = _monitor.evaluate_skill(skill_id, {
            "error_rate": error_rate,
            "security_issues": security_issues,
            "coverage": coverage,
            "doc_completeness": doc_completeness,
            "p99_latency_ms": p99_latency_ms,
            "update_frequency_days": update_frequency_days,
            "resource_efficiency": resource_efficiency,
        })
        return {
            "skill_id": eval_.skill_id,
            "overall_score": round(eval_.overall_score, 4),
            "safety": {"score": eval_.safety_score, "level": eval_.safety.value},
            "completeness": {"score": eval_.completeness_score, "level": eval_.completeness.value},
            "executability": {"score": eval_.executability_score, "level": eval_.executability.value},
            "maintainability": {"score": eval_.maintainability_score, "level": eval_.maintainability.value},
            "cost_awareness": {"score": eval_.cost_awareness_score, "level": eval_.cost_awareness.value},
        }
    except Exception as e:
        return {
            "skill_id": skill_id,
            "overall_score": 0.0,
            "error": f"monitor_evaluate error: {type(e).__name__}",
        }


# ── Health tools ──


@mcp.tool()
def health_check(include_gateway: bool = False) -> dict:
    """Run health checks on all registered components and return status.

    On error, returns DEGRADED status.

    Args:
        include_gateway: If True, also check vMCP Gateway /health endpoint.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        resp = _health.check_health()
        result = {
            "status": str(resp.status),
            "components": [
                {
                    "component": c.component,
                    "status": str(c.status),
                    "critical": c.critical,
                    "message": c.message,
                }
                for c in resp.components
            ],
            "degradation_level": str(_health.get_degradation_level()),
        }

        if include_gateway:
            try:
                import httpx
                with httpx.Client(timeout=3.0) as client:
                    gw_resp = client.get("http://127.0.0.1:9000/health")
                    result["gateway"] = gw_resp.json() if gw_resp.status_code == 200 else {
                        "status": "unreachable",
                        "http_status": gw_resp.status_code,
                    }
            except Exception as e:
                result["gateway"] = {"status": "unreachable", "error": str(e)}

        return result
    except Exception as e:
        return {
            "status": "DEGRADED",
            "error": f"health_check error: {type(e).__name__}: {e}",
            "components": [],
            "degradation_level": "unknown",
        }


# ── Review tool ──


@mcp.tool()
def review_trigger(
    checkpoint: str = "L2",
    skill_ids: Optional[list[str]] = None,
    trace_id: str = "",
) -> dict:
    """Trigger a review checkpoint (L1-L4).

    L1: DocsDD — 7-dim shadow review (non-blocking)
    L2: SDD — 12-dim full review + VETO V1-V6
    L3: BDD — baseline 5-dim + all VETO
    L4: TDD — baseline regression, new blind spots only

    Args:
        checkpoint: Review level (L1, L2, L3, L4)
        skill_ids: Optional list of skill IDs to review (empty = all)
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    from skillpool.review import ReviewManager
    from skillpool.review.models import CheckpointLevel, ReviewTrigger, ReviewTriggerRequest

    try:
        rm = ReviewManager()
        request = ReviewTriggerRequest(
            trigger=ReviewTrigger.MANUAL,
            checkpoint=CheckpointLevel(checkpoint),
            affected_skills=skill_ids or ["all"],
        )
        result = rm.trigger(request)
        return {
            "status": result.status.value,
            "review_id": result.review_id,
            "checkpoint": checkpoint,
            "scores": result.scores,
            "veto_triggered": result.veto_triggered,
            "veto_details": [
                {"rule": v.rule.value, "dimension": v.dimension, "score": v.score,
                 "threshold": v.threshold, "blocks": v.blocks, "decision": "block" if v.blocks else "risk_notice",
                 "reason": v.recommendation}
                for v in result.veto_details
            ],
            "suspect_skills": [
                {"skill_id": s.skill_id, "reason": s.reason, "dimension": s.suspected_dimension}
                for s in result.suspect_skills
            ],
            "recommendation": result.recommendation.value,
            "duration_ms": result.duration_ms,
        }
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


@mcp.tool()
def security_scan(content: str, skill_id: str = "") -> dict:
    """Scan skill content for security threats before materialization.

    Runs YAML safety checks, dangerous pattern scanning, and signature
    verification (placeholder). Returns threat level and details.

    Args:
        content: The skill content (YAML or SKILL.md) to scan.
        skill_id: Optional skill ID for context (used in warnings).
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        result = _security_scanner.full_check(content)
        return {
            "skill_id": skill_id,
            "threat_level": result.threat_level.value,
            "is_safe": result.is_safe,
            "checks_passed": result.checks_passed,
            "warnings": result.warnings,
            "blockers": result.blockers,
        }
    except Exception as e:
        return {
            "skill_id": skill_id,
            "threat_level": "critical",
            "is_safe": False,
            "error": f"security_scan error: {type(e).__name__}",
            "checks_passed": [],
            "warnings": [],
            "blockers": ["Scan failed: internal error"],
        }


@mcp.tool()
def healing_scan() -> dict:
    """Scan BugCollector for recurring defects and propose self-healing evolutions.

    Groups bugs by (skill_id, defect_type), applies trigger thresholds,
    and returns proposed healing actions. Does NOT execute any changes.

    Trigger thresholds:
    - >=3 P2 bugs -> PATCH (auto)
    - >=1 P1 or >=5 P2 -> MINOR (auto + notify)
    - >=1 P0 -> MAJOR (needs_human, must NOT auto-execute)
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        proposals = _self_healing.scan_and_propose()
        return {
            "proposals": proposals,
            "total_proposals": len(proposals),
            "status": "scanned",
        }
    except Exception as e:
        return {
            "proposals": [],
            "total_proposals": 0,
            "status": "error",
            "error": f"healing_scan error: {type(e).__name__}: {e}",
        }


@mcp.tool()
def healing_execute(proposal_id: str) -> dict:
    """Execute a proposed self-healing evolution with BDD verification.

    Steps:
    1. Validate proposal exists and is in PROPOSED state
    2. MAJOR proposals require human approval (return needs_human)
    3. Run BDD verification (check bug count decreased)
    4. If verification fails -> auto-rollback

    Args:
        proposal_id: The healing proposal ID to execute (from healing_scan).
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        result = _self_healing.execute_healing(proposal_id)
        return result
    except Exception as e:
        return {
            "proposal_id": proposal_id,
            "status": "error",
            "error": f"healing_execute error: {type(e).__name__}: {e}",
        }


# ═══════════════════════════════════════════════════════════════════
# PROMPTS — User-controlled, templated skill invocation
# ═══════════════════════════════════════════════════════════════════


@mcp.prompt()
def skill_context(skill_id: str) -> str:
    """Inject skill context into the conversation.

    Use this to load a specific skill's definition and checklist
    as context for the current task.

    Args:
        skill_id: Skill ID to load (e.g., S09, S13a)
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    definition = skill_definition(skill_id)
    manifest = skill_manifest(skill_id)

    deps = manifest.get("dependencies", [])
    deps_str = ", ".join(deps) if deps else "none"

    return f"""# Skill: {skill_id}

## Dependencies
{deps_str}

## Definition
{definition}
"""


@mcp.prompt()
def trigger_review() -> str:
    """Trigger a multi-dimension review of the current work.

    Evaluates across 12 dimensions (D1-D12) with VETO rules V1-V6.
    Uses SkillPool MCP Resources for dynamic content — no hardcoded paths.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    return """Execute a Multi-Dimension Review V9.0 on the current work.

Steps:
1. Read skill://multi-dim-review/definition for full rules and rubric
2. Read skill://multi-dim-review/manifest.yaml for dependencies and veto rules
3. Score all 12 dimensions per V9.0 rubric
4. Check VETO rules V1-V6
5. Collect blind spots with severity (P0/P1/P2)
6. Determine if any skill upgrades are triggered
7. Write blind spots to blindspots/ directory and ClawMem

Fallback: If MCP Resources are unavailable, read local files at
~/.skillpool/skills/multi-dim-review/RULES.md and state.yaml
"""


@mcp.prompt()
def gate_status(skill_id: str, agent_type: str = "claude-code") -> str:
    """Check gate status for a skill.

    Returns whether the skill is ALLOWED, GUARDED, ESCALATED, or DENIED.

    Args:
        skill_id: Skill ID to check
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    csdf = _load_csdf(skill_id)
    if csdf is None:
        return f"Skill not found: {skill_id}"

    profile = _get_profile(agent_type)
    gate = GateManager(profile=profile)
    result = gate.check(csdf)

    return f"""Gate Check Result for {skill_id}:
- Decision: {result.decision}
- Reason: {result.reason}
- Complexity Level: {result.complexity.level if result.complexity else 'N/A'}
- Complexity Total: {result.complexity.total if result.complexity else 'N/A'}
"""


# ═══════════════════════════════════════════════════════════════════
# MCP Tools — V4.1 补齐（match / report_usage / assess_paradigm / get_emergency_overrides）
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def skill_search(
    intent: str,
    agent_type: str,
    top_k: int = 5,
    include_lifecycle: bool = True,
) -> dict:
    """Search for optimal skill combinations for a given intent.

    This is the MANDATORY first step before accessing any skill definition.
    Uses four-layer routing (semantic + logical + causal + predictive) to
    find the best skill combination for the described intent.

    Layer 1 (Semantic): BGE-M3 embedding similarity via Ollama
    Layer 2 (Logical): DAG dependencies + synergy edges from CSDF
    Layer 3 (Causal): Historical combination gain data (Thompson Sampling)
    Layer 4 (Predictive): Collaborative filtering + gain decay

    Returns ranked skill candidates with combination recommendations
    and lifecycle state information.

    Args:
        intent: Natural language description of what you want to do.
        agent_type: Agent profile name for capability filtering.
        top_k: Maximum number of candidates to return (1-10).
        include_lifecycle: If True, include combination lifecycle state.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    from skillpool.router import IntentRouter
    from skillpool.synergy import SynergyDetector

    top_k = max(1, min(top_k, 10))

    # L1+L2: Intent routing (semantic + logical)
    intent_router = IntentRouter(skills_dir=_SKILLS_DIR)
    routing_result = intent_router.route(intent, top_k=top_k)

    primary = routing_result.primary
    result = {
        "intent": intent,
        "agent": agent_type,
        "layers_used": routing_result.layers_used,
        "primary_skill": {
            "id": primary.skill_id if primary else None,
            "score": primary.score if primary else 0,
            "layer": primary.layer if primary else "none",
            "reason": primary.reason if primary else "",
        } if primary else None,
        "candidates": [
            {"id": c.skill_id, "score": c.score, "layer": c.layer, "reason": c.reason[:100]}
            for c in routing_result.candidates[:top_k]
        ],
    }

    # Include combination recommendations
    if routing_result.enhancers:
        result["recommended_combinations"] = [
            {
                "primary": primary.skill_id if primary else "",
                "enhancer": e.skill_id,
                "gain": e.gain,
                "reason": e.reason[:100],
                "score": e.score,
            }
            for e in routing_result.enhancers[:5]
        ]

    # Add synergy data from CSDF
    if primary:
        detector = SynergyDetector(skills_dir=_SKILLS_DIR)
        detector.load_expert_synergies()
        synergies = detector.get_synergies_for(primary.skill_id)
        if synergies:
            result["expert_synergies"] = [
                {"skill_id": s.target, "gain": s.gain, "reason": s.reason, "weight": s.weight}
                for s in synergies
            ]

    # Include combination lifecycle data
    if include_lifecycle:
        from skillpool.combiner import CombinationLifecycleManager
        lifecycle_mgr = CombinationLifecycleManager()

        # Get promoted combinations for the primary skill
        if primary:
            promoted = lifecycle_mgr.get_promoted_combinations(primary.skill_id)
            if promoted:
                result["active_combinations"] = [
                    {
                        "combination_id": c.combination_id,
                        "enhancers": c.enhancers,
                        "state": c.state.name,
                        "gain_avg": round(c.gain_avg, 2),
                        "weight": round(c.current_weight(), 3),
                        "source": c.source,
                    }
                    for c in promoted
                ]

        # Get validating combinations (candidates being evaluated)
        validating = lifecycle_mgr.get_validating_combinations()
        if validating:
            result["validating_combinations"] = [
                {
                    "combination_id": c.combination_id,
                    "primary": c.primary,
                    "enhancers": c.enhancers,
                    "execution_count": c.execution_count,
                    "gain_avg": round(c.gain_avg, 2),
                    "confidence": round(c.gain_confidence, 2),
                }
                for c in validating[:5]
            ]

    # Mark search as done for this caller (enables direct skill access)
    # Agent-neutral: uses agent_type as caller identifier, not Claude Code session ID
    _search_done_callers.add(agent_type)

    return result


@mcp.tool()
def skill_get(
    skill_id: str,
    agent_type: str,
    detail: str = "definition",
) -> dict:
    """Get skill content with search-first enforcement.

    This is a model-controlled Tool wrapper around skill Resources.
    It enforces that skill_search must be called before accessing
    skill content — applies to ALL Agents equally via MCP server logic.

    If skill_search has not been called for this agent_type yet,
    returns a guidance message instead of skill content.

    Args:
        skill_id: Skill ID to retrieve.
        agent_type: Agent identifier for search-first tracking.
        detail: Level of detail: "summary" (~200 tokens), "definition" (full), "manifest" (deps only).
    """
    # Part of SkillPool — independent infrastructure, shared by all agents

    # Search-first enforcement: Agent-neutral, no Claude Code dependencies
    if agent_type not in _search_done_callers:
        return {
            "error": "search_required",
            "message": f"Please call skill_search(intent=...) first to find the optimal skill combination. "
                       f"Direct skill access is blocked until you search for the best match.",
            "skill_id": skill_id,
            "agent_type": agent_type,
        }

    # Delegate to the appropriate Resource function
    if detail == "summary":
        data = _lazy_loader.load(skill_id, tier="L1")
        return {"skill_id": skill_id, "detail": "summary", "data": data}
    elif detail == "manifest":
        csdf = _load_csdf(skill_id)
        if csdf is None:
            return {"error": f"Skill not found: {skill_id}"}
        return {
            "skill_id": skill_id,
            "detail": "manifest",
            "data": {
                "id": csdf.get("id", skill_id),
                "version": csdf.get("version", ""),
                "dependencies": csdf.get("dependencies", []),
                "synergies": csdf.get("synergies", []),
                "values": csdf.get("values", {}),
            },
        }
    else:  # definition
        try:
            data = _lazy_loader.load(skill_id, tier="L2")
            if "markdown" in data and data["markdown"]:
                content = data["markdown"]
            elif "_markdown_body" in data and data["_markdown_body"]:
                content = data["_markdown_body"]
            else:
                content = f"Content unavailable (errors: {data.get('_materialization_errors', [])})"
            return {"skill_id": skill_id, "detail": "definition", "content": content}
        except ValueError:
            return {"error": f"Skill not found: {skill_id}"}


@mcp.tool()
def skill_match(task_description: str, agent_type: str, include_combinations: bool = True) -> dict:
    """Match skills to a task description using IntentRouter + Resolver DAG traversal.

    V4.3 Phase 9 upgrade: Uses IntentRouter (L1 semantic + L2 logical routing)
    to find optimal skill combinations, including enhancers from synergy data.

    Args:
        task_description: Description of the task to match skills for.
        agent_type: Agent profile name for capability filtering.
        include_combinations: If True, also recommend skill combinations with gain data.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    from skillpool.resolver import SkillResolver, SkillResolveRequest
    from skillpool.router import IntentRouter

    profile = _get_profile(agent_type)

    # L1+L2: Intent routing (semantic + logical)
    intent_router = IntentRouter(skills_dir=_SKILLS_DIR)
    routing_result = intent_router.route(task_description, top_k=5)

    # Resolver DAG traversal for dependency resolution
    resolver = SkillResolver()
    skill_ids = []
    if _SKILLS_DIR.exists():
        for yaml_file in sorted(_SKILLS_DIR.glob("*.yaml")):
            if yaml_file.name == "skill_graph.yaml":
                continue
            skill_id = yaml_file.stem.split("-")[0]
            csdf = _load_csdf(skill_id)
            if csdf:
                skill_ids.append(skill_id)

    request = SkillResolveRequest(
        skill_ids=skill_ids or ["S00"],
        task_description=task_description,
    )
    response = resolver.resolve(request)
    matches = response.resolved if hasattr(response, 'resolved') else []

    # Combine results
    primary = routing_result.primary
    result = {
        "task": task_description,
        "agent": agent_type,
        "layers_used": routing_result.layers_used,
        "primary_skill": {
            "id": primary.skill_id if primary else None,
            "score": primary.score if primary else 0,
            "layer": primary.layer if primary else "none",
            "reason": primary.reason if primary else "",
        } if primary else None,
        "skill_candidates": [
            {"id": c.skill_id, "score": c.score, "layer": c.layer, "reason": c.reason[:100]}
            for c in routing_result.candidates[:10]
        ],
        "dag_matches": [{"id": m.skill_id, "name": m.name, "score": m.score} for m in matches[:10]],
        "total_candidates": len(skill_ids),
    }

    # Include combination recommendations if requested
    if include_combinations and routing_result.enhancers:
        # Load lifecycle data for combination state info
        combo_lifecycle_states: dict[str, str] = {}
        try:
            from skillpool.combiner import CombinationLifecycleManager
            from skillpool.combiner.models import CombinationLifecycleState
            lifecycle_mgr = CombinationLifecycleManager()
            for e in routing_result.enhancers[:5]:
                combos = lifecycle_mgr.get_combinations_for_skill(e.skill_id)
                if combos:
                    best = max(combos, key=lambda c: c.current_weight())
                    combo_lifecycle_states[e.skill_id] = CombinationLifecycleState(best.state).name
        except Exception as e:
            logger.warning("Failed to load combination lifecycle states: %s", e)

        result["combinations"] = [
            {
                "primary": primary.skill_id if primary else "",
                "enhancer": e.skill_id,
                "gain": e.gain,
                "reason": e.reason[:100],
                "score": e.score,
                "lifecycle_state": combo_lifecycle_states.get(e.skill_id, ""),
            }
            for e in routing_result.enhancers[:5]
        ]

    # Add synergy data from CSDF
    if primary and include_combinations:
        from skillpool.synergy import SynergyDetector
        detector = SynergyDetector(skills_dir=_SKILLS_DIR)
        detector.load_expert_synergies()
        synergies = detector.get_synergies_for(primary.skill_id)
        if synergies:
            result["expert_synergies"] = [
                {"skill_id": s.target, "gain": s.gain, "reason": s.reason, "weight": s.weight}
                for s in synergies
            ]

    return result


@mcp.tool()
def report_usage(
    skill_name: str,
    session_id: str,
    agent_type: str,
    duration_ms: int = 0,
    result: str = "success",
    combination_skills: Optional[list[str]] = None,
    effectiveness: float = 0.0,
    efficiency: float = 0.0,
    quality: float = 0.0,
    gain: float = 0.0,
    intent: str = "",
) -> dict:
    """Report skill usage with optional combination data and four-dimension scores.

    V4.3 Phase 9 upgrade: Supports reporting skill combinations and gain data.
    Implicit tracking is zero-burden — only skill_name + session_id required.
    Explicit scoring is optional — provide four-dimension scores for richer data.

    Args:
        skill_name: Name of the primary skill that was used.
        session_id: Session identifier for correlation.
        duration_ms: Duration of skill execution in milliseconds.
        result: Execution result status (success/partial/failed).
        agent_type: Agent profile name.
        combination_skills: Other skills used alongside the primary skill.
        effectiveness: Task goal achievement (0-10, optional).
        efficiency: Resource consumption reasonableness (0-10, optional).
        quality: Output sustainability (0-10, optional).
        gain: Combination marginal contribution (-10 to +10, optional).
        intent: Original agent intent description (optional).
    """
    # Part of SkillPool — independent infrastructure, shared by all agents

    # 1. Record telemetry event
    payload = {
        "session_id": session_id,
        "duration_ms": duration_ms,
        "result": result,
        "agent_type": agent_type,
    }
    if combination_skills:
        payload["combination_skills"] = combination_skills
        payload["combination"] = f"{skill_name}+{','.join(combination_skills)}"
    if intent:
        payload["intent"] = intent

    tel_result = telemetry_report(
        event_type="usage",
        skill_id=skill_name,
        channel="mcp",
        payload=payload,
    )

    # 2. Record gain data if scores provided
    gain_recorded = False
    if effectiveness > 0 or efficiency > 0 or quality > 0 or gain != 0:
        from skillpool.gain import GainTracker, SkillExecution, GainScores
        tracker = GainTracker()

        skill_ids = [skill_name]
        if combination_skills:
            skill_ids.extend(combination_skills)

        scores = GainScores(
            effectiveness=effectiveness,
            efficiency=efficiency,
            quality=quality,
            gain=gain,
        )

        source = "explicit" if effectiveness > 0 else "implicit"
        tracker.record(SkillExecution(
            skill_ids=skill_ids,
            intent=intent,
            scores=scores,
            duration_ms=duration_ms,
            source=source,
        ))
        gain_recorded = True

    # 3. Update combination lifecycle if combination_skills provided
    lifecycle_updated = False
    lifecycle_state = ""
    if combination_skills:
        from skillpool.combiner import CombinationLifecycleManager
        from skillpool.combiner.models import CombinationLifecycleState
        lifecycle_mgr = CombinationLifecycleManager()

        # Record execution for the combination
        combo_id = f"{skill_name}+{'+'.join(sorted(combination_skills))}"
        combo = lifecycle_mgr.record_execution(
            combo_id, gain=gain, success=(result == "success"),
        )

        if combo:
            lifecycle_state = CombinationLifecycleState(combo.state).name

            # DISCOVERED → VALIDATING: first execution triggers validation
            if combo.state == CombinationLifecycleState.DISCOVERED:
                transition_result = lifecycle_mgr.transition(
                    combo_id, CombinationLifecycleState.VALIDATING,
                )
                if transition_result.success:
                    lifecycle_updated = True
                    lifecycle_state = "VALIDATING"

            # VALIDATING → PROMOTED: try promotion after enough executions
            if combo.state == CombinationLifecycleState.VALIDATING:
                promote_result = lifecycle_mgr.try_promote(combo_id)
                if promote_result.success:
                    lifecycle_updated = True
                    lifecycle_state = "PROMOTED"

        # If combination doesn't exist yet, create it
        if combo is None:
            lifecycle_mgr.create_combination(
                primary=skill_name,
                enhancers=combination_skills,
                source="auto_discovered",
            )
            lifecycle_state = "DISCOVERED"

    return {
        "skill_name": skill_name,
        "session_id": session_id,
        "telemetry": tel_result,
        "gain_recorded": gain_recorded,
        "combination_count": len(combination_skills) if combination_skills else 0,
        "lifecycle_updated": lifecycle_updated,
    }


@mcp.tool()
def assess_paradigm(paradigm: str, agent_type: str, skill_id: str = "") -> dict:
    """Assess whether an agent can execute a given paradigm.

    Checks agent profile capabilities and trust level against paradigm requirements.

    Args:
        paradigm: Paradigm to assess (docsdd/sdd/bdd/tdd or review/code/test/planning).
        skill_id: Optional skill ID for context-specific assessment.
        agent_type: Agent profile name.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    from skillpool.paradigm import ParadigmRegistry
    profile = _get_profile(agent_type)
    registry = ParadigmRegistry()

    # Check if paradigm exists
    paradigms = registry.list_paradigms() if hasattr(registry, "list_paradigms") else []
    paradigm_exists = paradigm in {p.get("paradigm", "") for p in paradigms}

    # Check agent compatibility
    can_execute, reason = profile.can_execute({"paradigm": paradigm})

    return {
        "paradigm": paradigm,
        "agent_type": agent_type,
        "paradigm_registered": paradigm_exists,
        "can_execute": can_execute,
        "reason": reason,
        "trust_level": profile.trust_level,
        "capabilities": sorted(profile.required_capabilities),
    }


@mcp.tool()
def combination_create(
    primary: str,
    enhancers: list[str],
    agent_type: str,
    source: str = "human_specified",
) -> dict:
    """Create a new skill combination via MCP.

    Human-specified combinations skip DISCOVERED, enter VALIDATING directly.
    Auto-discovered combinations start at DISCOVERED.
    ALL Agents can create combinations — this is MCP-level, agent-neutral.

    Args:
        primary: Primary skill ID.
        enhancers: List of enhancing skill IDs.
        agent_type: Agent creating this combination (for audit trail).
        source: Discovery source: human_specified or auto_discovered.
    """
    # Part of SkillPool — independent infrastructure
    from skillpool.combiner import CombinationLifecycleManager

    mgr = CombinationLifecycleManager()
    combo = mgr.create_combination(
        primary=primary,
        enhancers=enhancers,
        source=source,
    )

    return {
        "combination_id": combo.combination_id,
        "primary": combo.primary,
        "enhancers": combo.enhancers,
        "state": combo.state.name,
        "source": combo.source,
        "message": f"Combination created in {combo.state.name} state",
    }


@mcp.tool()
def combination_get(combination_id: str) -> dict:
    """Get details of a specific skill combination.

    Returns combination state, gain data, and lifecycle information.

    Args:
        combination_id: The combination ID (e.g. "review+karnpathy-guidelines").
    """
    from skillpool.combiner import CombinationLifecycleManager

    mgr = CombinationLifecycleManager()
    combo = mgr.get_combination(combination_id)

    if combo is None:
        return {"error": "not_found", "message": f"Combination '{combination_id}' not found"}

    return {
        "combination_id": combo.combination_id,
        "primary": combo.primary,
        "enhancers": combo.enhancers,
        "state": combo.state.name,
        "source": combo.source,
        "gain_avg": combo.gain_avg,
        "gain_confidence": combo.gain_confidence,
        "all_time_gain_avg": combo.all_time_gain_avg,
        "recent_gain_avg": combo.recent_gain_avg,
        "execution_count": combo.execution_count,
        "current_weight": combo.current_weight(),
        "last_execution": combo.last_execution,
        "promoted_at": combo.promoted_at,
    }


@mcp.tool()
def combination_list(
    state: str = "",
    primary: str = "",
) -> dict:
    """List skill combinations, optionally filtered by state or primary skill.

    Args:
        state: Filter by lifecycle state (DISCOVERED/VALIDATING/PROMOTED/
               REJECTED/DEPRECATED/RETIRED). Empty = all states.
        primary: Filter by primary skill ID. Empty = all skills.
    """
    from skillpool.combiner import CombinationLifecycleManager, CombinationLifecycleState

    mgr = CombinationLifecycleManager()
    mgr._ensure_loaded()

    combos = list(mgr._combinations.values())

    if state:
        try:
            state_enum = CombinationLifecycleState[state]
        except KeyError:
            return {"error": "invalid_state", "message": f"Unknown state '{state}'"}
        combos = [c for c in combos if c.state == state_enum]

    if primary:
        combos = [c for c in combos if c.primary == primary]

    return {
        "count": len(combos),
        "combinations": [
            {
                "combination_id": c.combination_id,
                "primary": c.primary,
                "enhancers": c.enhancers,
                "state": c.state.name,
                "gain_avg": c.gain_avg,
                "execution_count": c.execution_count,
                "current_weight": c.current_weight(),
            }
            for c in combos
        ],
    }


@mcp.tool()
def combination_transition(
    combination_id: str,
    to_state: str,
    agent_type: str,
    reason: str = "",
) -> dict:
    """Manually transition a combination's lifecycle state.

    Use with caution — automated transitions happen via report_usage
    and skill_lifecycle_check. This tool exists for administrative overrides.

    Args:
        combination_id: The combination ID to transition.
        to_state: Target state name (DISCOVERED/VALIDATING/PROMOTED/
                  REJECTED/DEPRECATED/RETIRED).
        agent_type: Agent requesting the transition (for audit trail).
        reason: Reason for the manual transition.
    """
    from skillpool.combiner import CombinationLifecycleManager, CombinationLifecycleState

    try:
        target = CombinationLifecycleState[to_state]
    except KeyError:
        return {"error": "invalid_state", "message": f"Unknown state '{to_state}'"}

    mgr = CombinationLifecycleManager()
    result = mgr.transition(combination_id, target, reason=reason)

    return {
        "combination_id": result.combination_id,
        "from_state": result.from_state.name,
        "to_state": result.to_state.name,
        "success": result.success,
        "reason": result.reason,
    }


@mcp.tool()
def skill_lifecycle_check(
    skill_id: str = "",
    check_deprecation: bool = True,
    check_combinations: bool = True,
) -> dict:
    """Check skill lifecycle state and trigger auto-deprecation if needed.

    Available to ALL Agents — this is the MCP-level entry point for
    skill auto-deprecation, not an internal-only function.

    Args:
        skill_id: Specific skill to check. Empty = check all ACTIVE skills.
        check_deprecation: If True, trigger auto-deprecation checks.
        check_combinations: If True, also check combination lifecycle.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    from skillpool.lifecycle import SkillLifecycleState, check_auto_deprecation
    from skillpool.combiner import CombinationLifecycleManager

    results = {
        "deprecation_checks": [],
        "combination_checks": [],
    }

    if check_deprecation:
        if skill_id:
            deprecated = check_auto_deprecation(skill_id)
            results["deprecation_checks"].append({
                "skill_id": skill_id,
                "deprecated": deprecated,
            })

    if check_combinations:
        mgr = CombinationLifecycleManager()

        if skill_id:
            combos = mgr.get_combinations_for_skill(skill_id)
        else:
            mgr._ensure_loaded()
            combos = list(mgr._combinations.values())

        for combo in combos:
            if combo.state.value == 2:  # PROMOTED
                result = mgr.check_deprecation(combo.combination_id)
                if result:
                    results["combination_checks"].append({
                        "combination_id": combo.combination_id,
                        "action": result.to_state.name,
                        "reason": result.reason,
                    })

            elif combo.state.value == 4:  # DEPRECATED
                result = mgr.check_retirement(combo.combination_id)
                if result:
                    results["combination_checks"].append({
                        "combination_id": combo.combination_id,
                        "action": result.to_state.name,
                        "reason": result.reason,
                    })

    return results


@mcp.tool()
def get_emergency_overrides(skill_id: str = "") -> dict:
    """Query current emergency overrides for skills.

    Returns active WARN/DEGRADE/QUARANTINE/KILL overrides.
    If skill_id is provided, returns overrides for that skill only.
    If omitted, returns all active overrides.

    Args:
        skill_id: Optional skill ID to filter overrides.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    from skillpool.paradigm import OverrideLevel, EmergencyOverride
    import json

    overrides_path = _SKILLPOOL_DIR / "emergency_overrides.json"
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text())
        if skill_id:
            overrides = {k: v for k, v in overrides.items() if k == skill_id}
        return {"overrides": overrides, "count": len(overrides)}
    return {"overrides": {}, "count": 0}


@mcp.tool()
def cost_estimate(
    skill_id: str,
    skill_length: int = 0,
    review_level: str = "L1",
    include_review_checkpoint: bool = False,
    emergency_bypass_path: str = "",
) -> dict:
    """Estimate session cost for a skill execution using P50 conservative pricing.

    Uses $0.003/1K tokens pricing model. Combines skill execution cost
    + L2/L3 review overhead + review checkpoint overhead.

    Args:
        skill_id: Skill identifier (e.g. "dev-4d-sdd").
        skill_length: Character count of skill definition (fallback if skill_get unavailable).
        review_level: Complexity level (L0/L1/L2/L3+L2+).
        include_review_checkpoint: Whether to include review checkpoint overhead.
        emergency_bypass_path: Path to emergency_overrides.json file.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        from skillpool.cost.token_governor import TokenGovernor, PRESET_AGENT_CONFIGS
        from skillpool.cost.models import CostEstimate

        governor = TokenGovernor(PRESET_AGENT_CONFIGS)
        result = governor.estimate_session_cost(
            skill_id=skill_id,
            skill_length=skill_length,
            review_level=review_level,
            include_review_checkpoint=include_review_checkpoint,
            emergency_bypass_path=emergency_bypass_path or None,
        )
        return result.model_dump()
    except Exception as e:
        return {
            "error": f"cost_estimate error: {type(e).__name__}: {e}",
            "skill_id": skill_id,
            "total_cost_usd": 0.0,
        }


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════


def main():
    """Entry point for skillpool-mcp CLI command."""
    import argparse
    parser = argparse.ArgumentParser(description="SkillPool MCP Server")
    parser.add_argument("--agent-type", help="Agent type for logging/metadata (tools receive agent_type per-call)")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio",
                        help="MCP transport protocol (default: stdio)")
    parser.add_argument("--port", type=int, default=8101,
                        help="HTTP port for streamable-http transport (default: 8101)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="HTTP host for streamable-http transport (default: 127.0.0.1)")
    args = parser.parse_args()

    if args.transport in ("streamable-http", "sse"):
        import uvicorn
        logger.info("Starting SkillPool MCP on %s:%d (%s)", args.host, args.port, args.transport)
        app = mcp.http_app()
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
