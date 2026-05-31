"""Defect Classifier — ProcCtrlBench 11-type defect ontology.

Auto-classifies exceptions into structured defect types for monitoring
and self-healing feedback loops.

Uses MRO-based exception matching (more precise than string-based matching
in BugCollector) and context-aware severity escalation.
"""
from __future__ import annotations

__all__ = [
    "DefectClassifier",
    "DefectType",
]

import asyncio
from enum import StrEnum

from skillpool.monitor.bug_collector import BugSeverity


class DefectType(StrEnum):
    """11 defect types from ProcCtrlBench ontology.

    Uses lowercase snake_case values (distinct from BugCollector's
    UPPER_CASE DefectType for string-based matching). This enum is
    for class-based MRO classification via DefectClassifier.
    """
    PARAM_ERROR = "param_error"
    PERMISSION_BREACH = "permission_breach"
    TIMEOUT = "timeout"
    DEPENDENCY_MISSING = "dependency_missing"
    EXECUTION_FAILURE = "execution_failure"
    OUTPUT_INVALID = "output_invalid"
    STATE_CORRUPTION = "state_corruption"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    GATE_DENIED = "gate_denied"
    PROTOCOL_ERROR = "protocol_error"
    UNKNOWN = "unknown"


# Lazy import for domain-specific exceptions that live in other modules.
# Avoids circular imports at module load time.
def _get_domain_exceptions() -> dict[type[Exception], DefectType]:
    """Resolve domain-specific exception mappings lazily."""
    mapping: dict[type[Exception], DefectType] = {}
    try:
        from skillpool.registry import (
            SkillNotFoundError,
            SupplyChainEvidenceMissingError,
            IllegalStateTransitionError,
        )
        mapping[SkillNotFoundError] = DefectType.DEPENDENCY_MISSING
        mapping[SupplyChainEvidenceMissingError] = DefectType.PERMISSION_BREACH
        mapping[IllegalStateTransitionError] = DefectType.STATE_CORRUPTION
    except ImportError:
        pass

    try:
        from skillpool.audit import AuditUnavailableError
        mapping[AuditUnavailableError] = DefectType.GATE_DENIED
    except ImportError:
        pass

    return mapping


# Severity heuristics: defect type → default severity when no context
_DEFAULT_SEVERITY: dict[DefectType, BugSeverity] = {
    DefectType.RESOURCE_EXHAUSTION: BugSeverity.P0,
    DefectType.STATE_CORRUPTION: BugSeverity.P0,
    DefectType.PERMISSION_BREACH: BugSeverity.P1,
    DefectType.GATE_DENIED: BugSeverity.P1,
    DefectType.TIMEOUT: BugSeverity.P2,
    DefectType.EXECUTION_FAILURE: BugSeverity.P2,
    DefectType.DEPENDENCY_MISSING: BugSeverity.P2,
    DefectType.OUTPUT_INVALID: BugSeverity.P2,
    DefectType.PARAM_ERROR: BugSeverity.P2,
    DefectType.PROTOCOL_ERROR: BugSeverity.P2,
    DefectType.UNKNOWN: BugSeverity.P2,
}

# One-line fix suggestions per defect type
_FIX_SUGGESTIONS: dict[DefectType, str] = {
    DefectType.PARAM_ERROR: "Validate input parameters against the skill contract before execution.",
    DefectType.PERMISSION_BREACH: "Check agent trust level and supply chain evidence before access.",
    DefectType.TIMEOUT: "Increase timeout threshold or add async cancellation with fallback.",
    DefectType.DEPENDENCY_MISSING: "Verify all skill dependencies are registered and in ACTIVE state.",
    DefectType.EXECUTION_FAILURE: "Add defensive error handling and retry with exponential backoff.",
    DefectType.OUTPUT_INVALID: "Add output contract validation (schema check) after execution.",
    DefectType.STATE_CORRUPTION: "Reset skill lifecycle state and re-validate transition legality.",
    DefectType.RESOURCE_EXHAUSTION: "Enforce resource budgets via Token Governor and rate limiting.",
    DefectType.GATE_DENIED: "Review gate complexity score and escalate or adjust agent capabilities.",
    DefectType.PROTOCOL_ERROR: "Verify MCP protocol version and message schema compliance.",
    DefectType.UNKNOWN: "Add structured error context to enable classification on recurrence.",
}

# Context-based severity escalation rules
_SEVERITY_ESCALATION_KEYS: dict[str, BugSeverity] = {
    "production": BugSeverity.P0,
    "critical_path": BugSeverity.P0,
    "data_loss": BugSeverity.P0,
    "security_breach": BugSeverity.P0,
    "user_facing": BugSeverity.P1,
    "retry_exhausted": BugSeverity.P1,
    "cascade": BugSeverity.P1,
}


class DefectClassifier:
    """Auto-classify exceptions into defect types.

    Uses a two-tier mapping: built-in Python exceptions (static) and
    domain-specific SkillPool exceptions (lazy-loaded to avoid circular imports).

    Unlike BugCollector's string-based _classify_exception, this classifier
    walks the MRO for precise matching and supports context-aware severity
    escalation.

    Usage:
        classifier = DefectClassifier()
        defect = classifier.classify(ValueError("bad param"))
        defect_type, severity = classifier.classify_with_context(
            TimeoutError("slow"), {"production": True}
        )
        hint = classifier.suggest_fix(defect)
    """

    # Built-in exception → DefectType mapping (always available)
    EXCEPTION_MAP: dict[type[Exception], DefectType] = {
        TypeError: DefectType.PARAM_ERROR,
        ValueError: DefectType.PARAM_ERROR,
        KeyError: DefectType.PARAM_ERROR,
        PermissionError: DefectType.PERMISSION_BREACH,
        TimeoutError: DefectType.TIMEOUT,
        asyncio.TimeoutError: DefectType.TIMEOUT,
        ImportError: DefectType.DEPENDENCY_MISSING,
        ModuleNotFoundError: DefectType.DEPENDENCY_MISSING,
        FileNotFoundError: DefectType.DEPENDENCY_MISSING,
        RuntimeError: DefectType.EXECUTION_FAILURE,
        AssertionError: DefectType.OUTPUT_INVALID,
        MemoryError: DefectType.RESOURCE_EXHAUSTION,
        ConnectionError: DefectType.PROTOCOL_ERROR,
        OSError: DefectType.EXECUTION_FAILURE,
    }

    def __init__(self) -> None:
        self._domain_map: dict[type[Exception], DefectType] | None = None

    def _full_map(self) -> dict[type[Exception], DefectType]:
        """Return merged mapping (built-in + domain-specific)."""
        if self._domain_map is None:
            self._domain_map = {**self.EXCEPTION_MAP, **_get_domain_exceptions()}
        return self._domain_map

    def classify(self, exception: Exception) -> DefectType:
        """Classify an exception into a DefectType.

        Walks the MRO of the exception class to find the most specific
        matching defect type.

        Args:
            exception: The exception to classify.

        Returns:
            DefectType enum value.
        """
        mapping = self._full_map()
        for cls in type(exception).__mro__:
            if cls in mapping:
                return mapping[cls]
        return DefectType.UNKNOWN

    def classify_with_context(
        self,
        exception: Exception,
        context: dict,
    ) -> tuple[DefectType, BugSeverity]:
        """Classify an exception and determine severity with context.

        Context keys that escalate severity:
        - production / critical_path / data_loss / security_breach → P0
        - user_facing / retry_exhausted / cascade → P1

        Args:
            exception: The exception to classify.
            context: Additional context for severity determination.

        Returns:
            Tuple of (DefectType, BugSeverity).
        """
        defect_type = self.classify(exception)
        severity = _DEFAULT_SEVERITY[defect_type]

        # Escalate based on context
        for key, escalated in _SEVERITY_ESCALATION_KEYS.items():
            if context.get(key):
                # Only escalate, never de-escalate
                if escalated.value < severity.value:
                    severity = escalated
                break

        return defect_type, severity

    def suggest_fix(self, defect_type: DefectType) -> str:
        """Return a one-line fix suggestion for a defect type.

        Args:
            defect_type: The classified defect type.

        Returns:
            Human-readable fix suggestion string.
        """
        return _FIX_SUGGESTIONS.get(defect_type, _FIX_SUGGESTIONS[DefectType.UNKNOWN])
