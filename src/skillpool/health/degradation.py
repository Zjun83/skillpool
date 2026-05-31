"""Degradation management — 4-level fallback mode handling.

Levels (aligned with cross-system-interfaces.yaml §5.2):
  L0_full:      All components healthy
  L1_partial:   Non-critical component(s) down, core still functional
  L2_bm25_only: Vector search (VPLS) unavailable, BM25-only fallback
  L3_disabled:  Multiple critical failures, minimal/disabled operation
"""
from __future__ import annotations

from skillpool.health.models import DegradationLevel, ServingStatus


class DegradationManager:
    """Manage service degradation levels.

    When components fail, the system degrades gracefully:
    - L0_full: All components healthy
    - L1_partial: Non-critical component(s) down
    - L2_bm25_only: Vector search unavailable, fall back to BM25
    - L3_disabled: Multiple critical failures, minimal operation

    Usage:
        dm = DegradationManager()
        dm.report_failure("vpls")
        level = dm.get_degradation_level()
    """

    def __init__(self, critical_threshold: int = 2) -> None:
        self.critical_threshold = critical_threshold
        self._failures: dict[str, int] = {}  # component → consecutive failures
        self._critical_failures: set[str] = set()
        self._degradation_level = DegradationLevel.L0_FULL

    def report_failure(self, component: str, critical: bool = True) -> DegradationLevel:
        """Report a component failure. Returns new degradation level."""
        self._failures[component] = self._failures.get(component, 0) + 1
        if critical:
            self._critical_failures.add(component)
        self._update_level()
        return self._degradation_level

    def report_recovery(self, component: str) -> DegradationLevel:
        """Report a component recovery. Returns new degradation level."""
        self._failures.pop(component, None)
        self._critical_failures.discard(component)
        self._update_level()
        return self._degradation_level

    def get_degradation_level(self) -> DegradationLevel:
        """Get current degradation level."""
        return self._degradation_level

    def get_fallback_mode(self) -> str:
        """Get current fallback mode string."""
        level = self._degradation_level
        if level == DegradationLevel.L0_FULL:
            return "vpls_vector"
        if level == DegradationLevel.L1_PARTIAL:
            return "vpls_vector"
        if level == DegradationLevel.L2_BM25_ONLY:
            return "bm25_keyword"
        return "sqlite_fts5"

    def _update_level(self) -> None:
        """Recalculate degradation level based on failures."""
        failed_count = len(self._failures)
        critical_count = len(self._critical_failures)

        if failed_count == 0:
            self._degradation_level = DegradationLevel.L0_FULL
        elif "vpls" in self._failures and critical_count < self.critical_threshold:
            # VPLS down but not too many critical failures → BM25 fallback
            self._degradation_level = DegradationLevel.L2_BM25_ONLY
        elif critical_count >= self.critical_threshold:
            # Too many critical failures → disabled
            self._degradation_level = DegradationLevel.L3_DISABLED
        elif failed_count > 0 and critical_count == 0:
            # Only non-critical failures → partial degradation
            self._degradation_level = DegradationLevel.L1_PARTIAL
        else:
            # Some critical but below threshold → BM25 fallback
            self._degradation_level = DegradationLevel.L2_BM25_ONLY

    def reset(self) -> None:
        """Reset all failures and return to L0_full."""
        self._failures.clear()
        self._critical_failures.clear()
        self._degradation_level = DegradationLevel.L0_FULL
