"""BugCollector — Sentry-inspired 4-stage bug collection pipeline.

Stages: Capture -> Enrich -> Filter -> Persist

Capture: Intercept exceptions via sys.excepthook + manual record() calls
Enrich:  Auto-attach skill_id, trace_id, checkpoint, gate_result, defect_type
Filter:  Sample rate (test=1.0, prod=0.1), before_persist hook for noise filtering
Persist: Write to JSONL at ~/.skillpool/logs/bugs.jsonl (with fsync) + append to AuditLayer hash chain

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

__all__ = [
    "BugCollector",
    "BugRecord",
    "BugSeverity",
    "DefectType",
]

import json
import logging
import os
import random
import sys
import traceback
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from skillpool.config import get_data_dir
from skillpool.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


class BugSeverity(StrEnum):
    """Bug severity levels (Sentry-inspired)."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class DefectType(StrEnum):
    """Defect classification from ProcCtrlBench — 11 types."""

    PARAM_ERROR = "PARAM_ERROR"
    PERMISSION_BREACH = "PERMISSION_BREACH"
    TIMEOUT = "TIMEOUT"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    STATE_CORRUPTION = "STATE_CORRUPTION"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    GATE_DENIED = "GATE_DENIED"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class BugRecord:
    """Immutable bug record produced by the 4-stage pipeline."""

    bug_id: str
    timestamp: str
    severity: BugSeverity
    defect_type: DefectType
    message: str
    skill_id: str = ""
    trace_id: str = ""
    traceback: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (JSON-safe)."""
        d = asdict(self)
        d["severity"] = self.severity.value
        d["defect_type"] = self.defect_type.value
        return d

    def to_jsonl(self) -> str:
        """Serialize to single JSON line for JSONL persistence."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


class BugCollector:
    """4-stage bug collection pipeline: Capture -> Enrich -> Filter -> Persist.

    Args:
        audit_layer: Optional AuditLayer instance for hash chain persistence.
        sample_rate: Fraction of bugs to persist (1.0 = all, 0.1 = 10%).
        before_persist: Optional hook called before persist; return False to drop.
        log_dir: Override for persistence directory (default: ~/.skillpool/logs).
    """

    def __init__(
        self,
        audit_layer: Any | None = None,
        sample_rate: float = 1.0,
        before_persist: Callable[[BugRecord], bool] | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self._audit = audit_layer
        self._sample_rate = max(0.0, min(1.0, sample_rate))
        self._before_persist = before_persist
        self._log_dir = log_dir or get_data_dir() / "logs"
        self._bugs: list[BugRecord] = []
        self._original_excepthook: Any = None
        self._rng = random.Random(42)

    # ── Stage 1: Capture ──

    def record(
        self,
        severity: BugSeverity,
        defect_type: DefectType,
        message: str,
        skill_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> BugRecord:
        """Manually record a bug (Capture stage entry point).

        Runs the full 4-stage pipeline and returns the BugRecord
        (even if filtered out from persistence).
        """
        rec = self._create_record(
            severity=severity,
            defect_type=defect_type,
            message=message,
            skill_id=skill_id or "",
            tb="",
            context=context or {},
        )
        return self._pipeline(rec)

    def capture_exception(
        self,
        exc: BaseException,
        skill_id: str | None = None,
    ) -> BugRecord:
        """Capture an exception with auto-extracted traceback.

        Maps exception type to DefectType heuristically.
        """
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        defect_type = self._classify_exception(exc)
        severity = self._severity_from_exception(exc)

        rec = self._create_record(
            severity=severity,
            defect_type=defect_type,
            message=str(exc),
            skill_id=skill_id or "",
            tb=tb_str,
            context={"exc_type": type(exc).__name__},
        )
        return self._pipeline(rec)

    def install_excepthook(self) -> None:
        """Install sys.excepthook to auto-capture unhandled exceptions."""
        if self._original_excepthook is not None:
            return  # Already installed
        self._original_excepthook = sys.excepthook
        collector = self

        def _hook(exc_type, exc_value, exc_tb):  # type: ignore[no-untyped-def]
            # KeyboardInterrupt/SystemExit are control flow signals, not bugs
            if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
                if collector._original_excepthook is not None:
                    collector._original_excepthook(exc_type, exc_value, exc_tb)
                return
            try:
                tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                defect_type = collector._classify_exception(exc_value)
                severity = collector._severity_from_exception(exc_value)
                rec = collector._create_record(
                    severity=severity,
                    defect_type=defect_type,
                    message=str(exc_value),
                    skill_id="",
                    tb=tb_str,
                    context={"exc_type": exc_type.__name__, "source": "excepthook"},
                )
                collector._pipeline(rec)
            except Exception as e:
                logger.warning("BugCollector excepthook failed: %s", e)  # Never let the hook itself crash
            finally:
                if collector._original_excepthook is not None:
                    collector._original_excepthook(exc_type, exc_value, exc_tb)

        sys.excepthook = _hook

    def uninstall_excepthook(self) -> None:
        """Restore original sys.excepthook."""
        if self._original_excepthook is not None:
            sys.excepthook = self._original_excepthook
            self._original_excepthook = None

    # ── Query ──

    def get_bugs(
        self,
        severity: BugSeverity | None = None,
        defect_type: DefectType | None = None,
        skill_id: str | None = None,
    ) -> list[BugRecord]:
        """Query collected bugs with optional filters."""
        bugs = self._bugs
        if severity is not None:
            bugs = [b for b in bugs if b.severity == severity]
        if defect_type is not None:
            bugs = [b for b in bugs if b.defect_type == defect_type]
        if skill_id is not None:
            bugs = [b for b in bugs if b.skill_id == skill_id]
        return bugs

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate counts by severity and defect_type."""
        by_severity: dict[str, int] = {}
        by_defect: dict[str, int] = {}
        for bug in self._bugs:
            by_severity[bug.severity.value] = by_severity.get(bug.severity.value, 0) + 1
            by_defect[bug.defect_type.value] = by_defect.get(bug.defect_type.value, 0) + 1
        return {
            "total": len(self._bugs),
            "by_severity": by_severity,
            "by_defect_type": by_defect,
        }

    # ── Internal: Pipeline ──

    def _create_record(
        self,
        severity: BugSeverity,
        defect_type: DefectType,
        message: str,
        skill_id: str,
        tb: str,
        context: dict[str, Any],
    ) -> BugRecord:
        """Create a BugRecord with auto-generated id and timestamp."""
        return BugRecord(
            bug_id=f"bug-{uuid.uuid4().hex[:12]}",
            timestamp=utc_now().isoformat(),
            severity=severity,
            defect_type=defect_type,
            message=message,
            skill_id=skill_id,
            trace_id="",
            traceback=tb,
            context=context,
        )

    def _pipeline(self, record: BugRecord) -> BugRecord:
        """Run the 4-stage pipeline: Capture -> Enrich -> Filter -> Persist."""
        # Stage 2: Enrich
        record = self._enrich(record)
        # Always store in-memory (regardless of filter outcome)
        self._bugs.append(record)
        # Stage 3: Filter
        if not self._filter(record):
            return record
        # Stage 4: Persist
        self._persist(record)
        return record

    # ── Stage 2: Enrich ──

    def _enrich(self, record: BugRecord) -> BugRecord:
        """Auto-attach trace_id and context from environment."""
        if not record.trace_id:
            record.trace_id = os.urandom(16).hex()

        env_info: dict[str, str] = {}
        if "SKILLPOOL_ENV" in os.environ:
            env_info["env"] = os.environ["SKILLPOOL_ENV"]
        if env_info:
            record.context.update(env_info)

        return record

    # ── Stage 3: Filter ──

    def _filter(self, record: BugRecord) -> bool:
        """Determine if a record should be persisted.

        Returns True if the record passes both sampling and the before_persist hook.
        """
        if self._sample_rate < 1.0 and self._rng.random() >= self._sample_rate:
            return False

        if self._before_persist is not None:
            try:
                return self._before_persist(record)
            except Exception as e:
                logger.warning("before_persist hook failed, persisting by default: %s", e)
                return True  # Hook error -> persist by default

        return True

    # ── Stage 4: Persist ──

    def _persist(self, record: BugRecord) -> None:
        """Write to JSONL file and append to AuditLayer hash chain.

        Uses fsync for crash safety — partial lines from crashes are
        truncated on recovery by downstream consumers.
        """
        # JSONL persistence
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self._log_dir / "bugs.jsonl"
            line = record.to_jsonl() + "\n"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass  # Filesystem errors should not crash the pipeline

        # Audit chain persistence
        if self._audit is not None:
            try:
                self._audit.append(
                    action="bug_collected",
                    object_id=record.bug_id,
                    result=record.severity.value,
                    reason=record.message[:200],
                    severity=self._map_severity(record.severity),
                    metadata=record.to_dict(),
                    trace_id=record.trace_id,
                )
            except Exception as e:
                logger.warning(
                    "Audit record failed for bug %s: %s", record.bug_id, e
                )  # Audit errors should not crash the pipeline

    @staticmethod
    def _map_severity(severity: BugSeverity) -> str:
        """Map BugSeverity to AuditLayer severity string."""
        mapping = {
            BugSeverity.P0: "CRITICAL",
            BugSeverity.P1: "ERROR",
            BugSeverity.P2: "WARN",
        }
        return mapping.get(severity, "INFO")

    # ── Exception classification ──

    @staticmethod
    def _classify_exception(exc: BaseException) -> DefectType:
        """Heuristically map exception type to DefectType."""
        exc_name = type(exc).__name__
        mapping: dict[str, DefectType] = {
            "TimeoutError": DefectType.TIMEOUT,
            "ConnectionTimeoutError": DefectType.TIMEOUT,
            "PermissionError": DefectType.PERMISSION_BREACH,
            "PermissionDenied": DefectType.PERMISSION_BREACH,
            "ImportError": DefectType.DEPENDENCY_MISSING,
            "ModuleNotFoundError": DefectType.DEPENDENCY_MISSING,
            "FileNotFoundError": DefectType.DEPENDENCY_MISSING,
            "ValueError": DefectType.PARAM_ERROR,
            "TypeError": DefectType.PARAM_ERROR,
            "KeyError": DefectType.PARAM_ERROR,
            "AssertionError": DefectType.OUTPUT_INVALID,
            "RuntimeError": DefectType.EXECUTION_FAILURE,
            "OSError": DefectType.RESOURCE_EXHAUSTION,
            "MemoryError": DefectType.RESOURCE_EXHAUSTION,
            "ConnectionRefusedError": DefectType.RESOURCE_EXHAUSTION,
        }
        return mapping.get(exc_name, DefectType.UNKNOWN)

    @staticmethod
    def _severity_from_exception(exc: BaseException) -> BugSeverity:
        """Heuristically determine severity from exception type.

        KeyboardInterrupt and SystemExit are excluded from bug collection
        entirely (handled in the excepthook), so this method only maps
        actual defect exceptions.
        """
        critical_types = (MemoryError,)
        if isinstance(exc, critical_types):
            return BugSeverity.P0
        error_types = (PermissionError, ImportError, ModuleNotFoundError)
        if isinstance(exc, error_types):
            return BugSeverity.P1
        return BugSeverity.P2
