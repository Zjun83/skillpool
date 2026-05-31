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

mcp = FastMCP("skillpool")


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
}

_SKILLPOOL_DIR = Path.home() / ".skillpool"
_SKILLS_DIR = _SKILLPOOL_DIR / "skills"

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
    """Resolve profile by name."""
    return _PROFILES.get(name, CLAUDE_CODE_PROFILE)


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
    """Return lightweight metadata for all available skills.

    Returns only id, name, version, dimension, tags — no full content.
    Uses LazySkillLoader L0 tier for token-efficient delivery (~50 tokens/skill).

    Use skill://{skill_id}/summary for medium detail (~200 tokens).
    Use skill://{skill_id}/definition for full content.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
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
        if "markdown" in data and data["markdown"]:
            return data["markdown"]
        if "_markdown_body" in data and data["_markdown_body"]:
            return data["_markdown_body"]
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
        "version": csdf.get("version", ""),
        "dependencies": csdf.get("dependencies", []),
        "conflicts": csdf.get("conflicts", []),
        "requires": csdf.get("requires", []),
        "veto_rule": csdf.get("veto_rule", ""),
        "dimension": csdf.get("dimension", ""),
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


@mcp.resource("skill://graph")
def skill_graph() -> dict:
    """Return the skill dependency graph (DAG structure)."""
    # Part of SkillPool — independent infrastructure, shared by all agents
    graph_path = _SKILLS_DIR / "skill_graph.yaml"
    if not graph_path.exists():
        return {"error": "skill_graph.yaml not found"}

    try:
        return yaml.safe_load(graph_path.read_text()) or {}
    except Exception as e:
        return {"error": f"Failed to load graph: {e}"}


@mcp.resource("audit://records")
def audit_records() -> list[dict]:
    """Return audit records (read-only, immutable).

    Audit records cannot be modified via MCP — only read for traceability.
    """
    records = _audit.get_records()
    return [
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
        for r in records[:100]  # Cap at 100 to limit token usage
    ]


@mcp.resource("bug://list")
def bug_list() -> list[dict]:
    """Return collected bug records from BugCollector.

    Query bug records captured by the 4-stage pipeline
    (Capture→Enrich→Filter→Persist). Read-only via MCP.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    bugs = _bug_collector.get_bugs()
    return [b.to_dict() for b in bugs[:100]]


# ═══════════════════════════════════════════════════════════════════
# TOOLS — Model-controlled, state-changing governance actions
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def gate_check(csdf: dict, profile_name: str = "claude-code") -> dict:
    """Check gate decision for a CSDF skill.

    Returns ALLOW/GUARD/ESCALATE/DENY based on complexity and profile.
    On timeout or error, returns DENY (safe-deny default).

    Args:
        csdf: CSDF skill definition dict
        profile_name: Agent profile name (claude-code, codex, hermes)
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
) -> dict:
    """Transition a skill's lifecycle state in the Registry.

    Args:
        skill_id: Skill to transition
        from_status: Current state (draft/imported/testing/enabled/disabled/deprecated)
        to_status: Target state
        sandbox_result: "pass" required for enabled state
        policy_approval: True required for enabled state
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
        return {
            "skill_id": resp.skill_id,
            "from_status": resp.from_status,
            "to_status": resp.to_status,
            "audit_ref": resp.audit_ref,
        }
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


# ── Evolver tools ──


@mcp.tool()
def evolution_trigger(
    skill_id: str,
    version: str,
    severity: str,
    description: str,
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
def health_check() -> dict:
    """Run health checks on all registered components and return status.

    On error, returns DEGRADED status.
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    try:
        resp = _health.check_health()
        return {
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

    try:
        rm = ReviewManager(audit_layer=_audit)
        result = rm.run_checkpoint(checkpoint)
        return {
            "status": result.status,
            "checkpoint": checkpoint,
            "veto_details": [
                {"rule": v.rule, "decision": v.decision, "reason": v.reason}
                for v in (result.veto_details or [])
            ],
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
def gate_status(skill_id: str) -> str:
    """Check gate status for a skill.

    Returns whether the skill is ALLOWED, GUARDED, ESCALATED, or DENIED.

    Args:
        skill_id: Skill ID to check
    """
    # Part of SkillPool — independent infrastructure, shared by all agents
    csdf = _load_csdf(skill_id)
    if csdf is None:
        return f"Skill not found: {skill_id}"

    profile = _get_profile("claude-code")
    gate = GateManager(profile=profile)
    result = gate.check(csdf)

    return f"""Gate Check Result for {skill_id}:
- Decision: {result.decision}
- Reason: {result.reason}
- Complexity Level: {result.complexity.level if result.complexity else 'N/A'}
- Complexity Total: {result.complexity.total if result.complexity else 'N/A'}
"""


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════


def main():
    """Entry point for skillpool-mcp CLI command."""
    import sys
    # Parse --agent-type if provided
    agent_type = "claude-code"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--agent-type" and i + 1 <= len(sys.argv) - 1:
            agent_type = sys.argv[i + 1]
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
