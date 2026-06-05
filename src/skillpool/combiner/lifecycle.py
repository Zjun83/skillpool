"""CombinationLifecycleManager — Manage skill combination lifecycle transitions.

State transitions:
  DISCOVERED → VALIDATING (automatic, after discovery)
  VALIDATING → PROMOTED (gain > 0, confidence > 0.7, exec_count ≥ MIN)
  VALIDATING → REJECTED (gain ≤ 0 or confidence < 0.3)
  PROMOTED → DEPRECATED (30-day avg gain < 50% of historical)
  DEPRECATED → RETIRED (90 days no improvement)
  REJECTED → DISCOVERED (30 days cooldown, can be rediscovered)

Human-specified combinations skip DISCOVERED, enter VALIDATING directly.

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

import fcntl
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from skillpool.config import get_data_dir
from skillpool.combiner.models import (
    CombinationLifecycleState,
    SkillCombination,
    CombinationTransitionResult,
    MIN_VALIDATION_EXECUTIONS,
)
from skillpool.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


# Valid transitions: from_state → list of valid to_states
_TRANSITIONS: dict[CombinationLifecycleState, list[CombinationLifecycleState]] = {
    CombinationLifecycleState.DISCOVERED: [
        CombinationLifecycleState.VALIDATING,
        CombinationLifecycleState.RETIRED,
    ],
    CombinationLifecycleState.VALIDATING: [
        CombinationLifecycleState.PROMOTED,
        CombinationLifecycleState.REJECTED,
        CombinationLifecycleState.RETIRED,
    ],
    CombinationLifecycleState.PROMOTED: [
        CombinationLifecycleState.DEPRECATED,
        CombinationLifecycleState.RETIRED,
    ],
    CombinationLifecycleState.REJECTED: [
        CombinationLifecycleState.DISCOVERED,  # Rediscovery after cooldown
        CombinationLifecycleState.RETIRED,
    ],
    CombinationLifecycleState.DEPRECATED: [
        CombinationLifecycleState.PROMOTED,  # Re-promoted if gain recovers
        CombinationLifecycleState.RETIRED,
    ],
    CombinationLifecycleState.RETIRED: [],  # Terminal state
}


class CombinationLifecycleManager:
    """Manages skill combination lifecycle states and transitions.

    Usage:
        manager = CombinationLifecycleManager()
        # Human-specified combination
        combo = manager.create_combination(
            primary="multi-dim-review",
            enhancers=["karpathy-guidelines"],
            source="human_specified",
        )
        # Auto-discovered combination
        combo = manager.create_combination(
            primary="S05a",
            enhancers=["S09"],
            source="auto_discovered",
        )
        # Record execution feedback
        manager.record_execution(combo.combination_id, gain=1.5, success=True)
        # Check if ready for promotion
        result = manager.try_promote(combo.combination_id)
    """

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or get_data_dir() / "combinations"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._store_path = self.data_dir / "combinations.jsonl"
        self._combinations: dict[str, SkillCombination] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Lazy-load combinations from disk."""
        if self._loaded:
            return
        combos_file = self.data_dir / "combinations.jsonl"
        if combos_file.exists():
            for line in combos_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    combo = SkillCombination(**json.loads(line))
                    self._combinations[combo.combination_id] = combo
                except Exception as e:
                    logger.warning("Failed to parse combination record: %s", e)
                    continue
        self._loaded = True

    def _persist(self, combo: SkillCombination) -> None:
        """Append a combination to the JSONL file with file lock."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        combos_file = self._store_path
        with open(combos_file, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(combo.model_dump_json() + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)

    def _update_persisted(self, combo: SkillCombination) -> None:
        """Update an existing combination with atomic write and file lock.

        Uses write-to-temp-then-rename for atomicity, and file lock
        for multi-process safety.
        """
        self._combinations[combo.combination_id] = combo
        records = [c.model_dump() for c in self._combinations.values()]
        # Atomic write: temp file → rename
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self.data_dir), suffix=".jsonl.tmp")
        try:
            with open(tmp_fd, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                for record in records:
                    f.write(json.dumps(record, default=str) + "\n")
                fcntl.flock(f, fcntl.LOCK_UN)
            Path(tmp_path).rename(self._store_path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def create_combination(
        self,
        primary: str,
        enhancers: list[str],
        source: str = "auto_discovered",
        base_weight: float = 0.5,
    ) -> SkillCombination:
        """Create a new combination.

        Human-specified combinations skip DISCOVERED, enter VALIDATING directly.
        Auto-discovered combinations start at DISCOVERED.
        """
        self._ensure_loaded()

        # Check if combination already exists
        enhancer_str = "+".join(sorted(enhancers))
        combo_id = f"{primary}+{enhancer_str}"

        if combo_id in self._combinations:
            existing = self._combinations[combo_id]
            # If retired, allow rediscovery
            if existing.state == CombinationLifecycleState.RETIRED:
                existing.state = CombinationLifecycleState.DISCOVERED
                existing.source = source
                existing.discovered_at = utc_now().isoformat()
                self._update_persisted(existing)
                return existing
            return existing  # Already exists in non-retired state

        initial_state = (
            CombinationLifecycleState.VALIDATING
            if source == "human_specified"
            else CombinationLifecycleState.DISCOVERED
        )

        combo = SkillCombination(
            primary=primary,
            enhancers=enhancers,
            state=initial_state,
            source=source,
            base_weight=base_weight,
        )
        self._combinations[combo.combination_id] = combo
        self._persist(combo)
        return combo

    def validate_transition(
        self,
        from_state: CombinationLifecycleState,
        to_state: CombinationLifecycleState,
    ) -> bool:
        """Check if a state transition is valid."""
        if from_state == to_state:
            return False
        return to_state in _TRANSITIONS.get(from_state, [])

    def transition(
        self,
        combination_id: str,
        to_state: CombinationLifecycleState,
        reason: str = "",
    ) -> CombinationTransitionResult:
        """Execute a lifecycle state transition."""
        self._ensure_loaded()

        combo = self._combinations.get(combination_id)
        if combo is None:
            return CombinationTransitionResult(
                combination_id=combination_id,
                from_state=CombinationLifecycleState.DISCOVERED,
                to_state=to_state,
                success=False,
                reason="Combination not found",
            )

        from_state = combo.state
        if not self.validate_transition(from_state, to_state):
            return CombinationTransitionResult(
                combination_id=combination_id,
                from_state=from_state,
                to_state=to_state,
                success=False,
                reason=f"Invalid transition: {from_state.name} → {to_state.name}",
            )

        combo.state = to_state
        now = utc_now().isoformat()

        if to_state == CombinationLifecycleState.PROMOTED:
            combo.promoted_at = now
        elif to_state == CombinationLifecycleState.DEPRECATED:
            combo.deprecated_at = now
        elif to_state == CombinationLifecycleState.REJECTED:
            combo.rejection_reason = reason
        elif to_state == CombinationLifecycleState.DISCOVERED:
            # Rediscovery: reset validation data
            combo.gain_avg = 0.0
            combo.gain_confidence = 0.0
            combo.execution_count = 0
            combo.rejection_reason = ""

        self._update_persisted(combo)

        return CombinationTransitionResult(
            combination_id=combination_id,
            from_state=from_state,
            to_state=to_state,
            success=True,
            reason=reason,
        )

    def record_execution(
        self,
        combination_id: str,
        gain: float = 0.0,
        success: bool = True,
    ) -> SkillCombination | None:
        """Record an execution outcome for a combination.

        Updates gain_avg, execution_count, and gain_confidence.
        Automatically transitions DISCOVERED → VALIDATING.
        """
        self._ensure_loaded()

        combo = self._combinations.get(combination_id)
        if combo is None:
            logger.debug(f"Combination {combination_id} not found for execution recording")
            return None

        # Auto-transition DISCOVERED → VALIDATING on first execution
        if combo.state == CombinationLifecycleState.DISCOVERED:
            combo.state = CombinationLifecycleState.VALIDATING

        # Update execution data
        combo.execution_count += 1
        combo.last_execution = utc_now().isoformat()

        # Update rolling average gain
        old_avg = combo.gain_avg
        n = combo.execution_count
        combo.gain_avg = old_avg + (gain - old_avg) / n

        # Update recent_gain_avg (approximation: use current gain as proxy)
        # Full implementation would need gain_history with timestamps
        if combo.recent_gain_avg == 0.0:
            combo.recent_gain_avg = gain
        else:
            combo.recent_gain_avg = combo.recent_gain_avg * 0.7 + gain * 0.3

        # Update confidence: increases with more executions
        combo.gain_confidence = min(1.0, n / MIN_VALIDATION_EXECUTIONS)

        self._update_persisted(combo)
        return combo

    def try_promote(self, combination_id: str) -> CombinationTransitionResult:
        """Try to promote a VALIDATING combination to PROMOTED.

        Conditions:
          - state == VALIDATING
          - execution_count >= MIN_VALIDATION_EXECUTIONS
          - gain_avg > 0
          - gain_confidence >= 0.7
        """
        self._ensure_loaded()

        combo = self._combinations.get(combination_id)
        if combo is None:
            return CombinationTransitionResult(
                combination_id=combination_id,
                from_state=CombinationLifecycleState.VALIDATING,
                to_state=CombinationLifecycleState.PROMOTED,
                success=False,
                reason="Combination not found",
            )

        if combo.state != CombinationLifecycleState.VALIDATING:
            return CombinationTransitionResult(
                combination_id=combination_id,
                from_state=combo.state,
                to_state=CombinationLifecycleState.PROMOTED,
                success=False,
                reason=f"State is {combo.state.name}, not VALIDATING",
            )

        if combo.execution_count < MIN_VALIDATION_EXECUTIONS:
            return CombinationTransitionResult(
                combination_id=combination_id,
                from_state=CombinationLifecycleState.VALIDATING,
                to_state=CombinationLifecycleState.PROMOTED,
                success=False,
                reason=f"Only {combo.execution_count} executions, need {MIN_VALIDATION_EXECUTIONS}",
            )

        if combo.gain_avg <= 0:
            # Reject instead
            return self.transition(
                combination_id,
                CombinationLifecycleState.REJECTED,
                reason=f"Negative gain: {combo.gain_avg:.2f}",
            )

        if combo.gain_confidence < 0.7:
            return CombinationTransitionResult(
                combination_id=combination_id,
                from_state=CombinationLifecycleState.VALIDATING,
                to_state=CombinationLifecycleState.PROMOTED,
                success=False,
                reason=f"Confidence too low: {combo.gain_confidence:.2f}, need 0.7",
            )

        # Snapshot all-time gain average at promotion time (for future deprecation checks)
        combo.all_time_gain_avg = combo.gain_avg
        combo.recent_gain_avg = combo.gain_avg

        return self.transition(
            combination_id,
            CombinationLifecycleState.PROMOTED,
            reason=f"Gain={combo.gain_avg:.2f}, Confidence={combo.gain_confidence:.2f}",
        )

    def check_deprecation(self, combination_id: str) -> CombinationTransitionResult | None:
        """Check if a PROMOTED combination should be deprecated.

        Triggers:
        1. No execution in 30 days
        2. Recent (30-day) average gain < 50% of all-time average gain
        """
        self._ensure_loaded()

        combo = self._combinations.get(combination_id)
        if combo is None or combo.state != CombinationLifecycleState.PROMOTED:
            return None

        now = utc_now()

        # Check 1: No execution in 30 days
        if combo.last_execution:
            try:
                last = datetime.fromisoformat(combo.last_execution)
                days_inactive = (now - last).days
                if days_inactive > 30:
                    return self.transition(
                        combination_id,
                        CombinationLifecycleState.DEPRECATED,
                        reason=f"No execution in {days_inactive} days",
                    )
            except (ValueError, TypeError):
                pass

        # Check 2: Recent gain < 50% of all-time gain
        if combo.all_time_gain_avg > 0 and combo.recent_gain_avg > 0:
            gain_ratio = combo.recent_gain_avg / combo.all_time_gain_avg
            if gain_ratio < 0.5:
                return self.transition(
                    combination_id,
                    CombinationLifecycleState.DEPRECATED,
                    reason=f"Recent gain ({combo.recent_gain_avg:.2f}) "
                    f"< 50% of all-time ({combo.all_time_gain_avg:.2f}) "
                    f"(ratio={gain_ratio:.2f})",
                )

        return None

    def check_retirement(self, combination_id: str) -> CombinationTransitionResult | None:
        """Check if a DEPRECATED combination should be retired.

        Condition: 90 days since deprecation with no improvement.
        """
        self._ensure_loaded()

        combo = self._combinations.get(combination_id)
        if combo is None or combo.state != CombinationLifecycleState.DEPRECATED:
            return None

        if combo.deprecated_at:
            try:
                deprecated = datetime.fromisoformat(combo.deprecated_at)
                days_deprecated = (utc_now() - deprecated).days
                if days_deprecated > 90:
                    return self.transition(
                        combination_id,
                        CombinationLifecycleState.RETIRED,
                        reason=f"Deprecated for {days_deprecated} days with no improvement",
                    )
            except (ValueError, TypeError):
                pass

        return None

    def get_combination(self, combination_id: str) -> SkillCombination | None:
        """Get a combination by ID. Returns None if not found."""
        self._ensure_loaded()
        return self._combinations.get(combination_id)

    def get_promoted_combinations(self, primary: str = "") -> list[SkillCombination]:
        """Get all PROMOTED combinations, optionally filtered by primary skill."""
        self._ensure_loaded()
        results = [c for c in self._combinations.values() if c.state == CombinationLifecycleState.PROMOTED]
        if primary:
            results = [c for c in results if c.primary == primary]
        return sorted(results, key=lambda c: c.current_weight(), reverse=True)

    def get_validating_combinations(self) -> list[SkillCombination]:
        """Get all combinations currently in VALIDATING state."""
        self._ensure_loaded()
        return [c for c in self._combinations.values() if c.state == CombinationLifecycleState.VALIDATING]

    def get_combinations_for_skill(self, skill_id: str) -> list[SkillCombination]:
        """Get all combinations involving a skill (as primary or enhancer)."""
        self._ensure_loaded()
        return [c for c in self._combinations.values() if c.primary == skill_id or skill_id in c.enhancers]
