"""Gate State Machine — 7-state FSM for 4D paradigm phase transitions.

Error Codes:
  GP003: Illegal phase transition
  GP004: Missing required artifact for gate
  GP006: gate.json read/write failure

States: IDLE, ASSESSING, DOCSDD, SDD, BDD, TDD, REVIEW, COMPLETE

Contracts:
  - gate.json persists across process restarts (B04)
  - All transitions logged to phase_history (B13)
  - Atomic writes via temp file + os.replace()
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from skillpool.gate_policy.parser import (
    GatePolicyConfig,
    GatePolicyError,
    resolve_level_for_path,
)
from skillpool.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class PhaseTransition(BaseModel):
    """Single phase transition record."""

    from_phase: str
    to_phase: str
    timestamp: str
    reason: str = ""


class ReviewCheckpoint(BaseModel):
    """Review checkpoint state."""

    triggered: bool = False
    checkpoint_level: str | None = None
    review_result: str | None = None
    veto_status: str | None = None


class GateMetadata(BaseModel):
    """Gate state metadata."""

    created_at: str | None = None
    updated_at: str | None = None
    session_id: str | None = None
    task_description: str | None = None


class GateStateFile(BaseModel):
    """gate.json runtime state."""

    incremental_mode: bool = True
    current_phase: str = "IDLE"
    assessed_level: str | None = None
    assessed_at: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    phase_history: list[PhaseTransition] = Field(default_factory=list)
    gate_checks: dict[str, str | None] = Field(default_factory=dict)
    artifacts: dict[str, str | None] = Field(default_factory=dict)
    review_checkpoint: ReviewCheckpoint = Field(default_factory=ReviewCheckpoint)
    metadata: GateMetadata = Field(default_factory=GateMetadata)


class GateCheckResult(BaseModel):
    """Result of a gate check between phases."""

    passed: bool
    missing_artifacts: list[str] = Field(default_factory=list)
    validation_message: str = ""


# ---------------------------------------------------------------------------
# Legal Transitions Table
# ---------------------------------------------------------------------------

_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "IDLE": {"ASSESSING"},
    "ASSESSING": {"COMPLETE", "DOCSDD", "SDD"},
    "DOCSDD": {"SDD"},
    "SDD": {"BDD", "TDD"},
    "BDD": {"TDD"},
    "TDD": {"REVIEW", "COMPLETE"},
    "REVIEW": {"COMPLETE"},
    "COMPLETE": set(),
}

# Conditional transition rules: (from, to) → required assessed_level
_TRANSITION_LEVEL_CONDITIONS: dict[tuple[str, str], set[str]] = {
    ("ASSESSING", "COMPLETE"): {"L0"},
    ("ASSESSING", "DOCSDD"): {"L2", "L3+L2+"},
    ("ASSESSING", "SDD"): {"L1", "L2", "L3+L2+"},
    ("SDD", "BDD"): {"L2", "L3+L2+"},
    ("SDD", "TDD"): {"L1"},
    ("TDD", "REVIEW"): {"L3+L2+"},
    ("TDD", "COMPLETE"): {"L0", "L1", "L2"},
}


# ---------------------------------------------------------------------------
# GateStateMachine
# ---------------------------------------------------------------------------


class GateStateMachine:
    """7-state FSM for 4D paradigm phase transitions.

    Args:
        state_path: Path to gate.json file for persistence.

    Contract:
        - Loads state from gate.json on init (B04).
        - If gate.json missing/corrupt, starts at IDLE.
        - All transitions logged to phase_history (B13).
    """

    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._state = self._load_state()
        self._policy: GatePolicyConfig | None = None

    @property
    def state(self) -> GateStateFile:
        """Current gate state."""
        return self._state

    def set_policy(self, policy: GatePolicyConfig) -> None:
        """Set policy for gate check validation."""
        self._policy = policy

    def assess(
        self,
        task_description: str,
        changed_files: list[str],
        policy: GatePolicyConfig | None = None,
    ) -> str:
        """Assess complexity and set assessed_level.

        Args:
            task_description: Natural language task description.
            changed_files: List of changed file paths.
            policy: Optional policy for path-based level resolution.

        Returns:
            Assessed complexity level string (L0/L1/L2/L3+L2+).

        Side effects:
            - Transitions IDLE → ASSESSING.
            - Sets assessed_level in gate.json.
            - If L0, immediately transitions to COMPLETE.

        Raises:
            GatePolicyError: GP003 if not in IDLE state.
        """
        if self._state.current_phase != "IDLE":
            raise GatePolicyError(
                "GP003",
                f"assess() can only be called from IDLE, current: {self._state.current_phase}",
            )

        # Transition IDLE → ASSESSING
        self._do_transition("ASSESSING", reason="assess called")

        # Determine level from changed files if policy provided
        if policy and changed_files:
            # Use highest level across all files
            levels = set()
            for f in changed_files:
                resolution = resolve_level_for_path(f, policy)
                levels.add(resolution.level)
            # Pick highest
            level_order = {"L0": 0, "L1": 1, "L2": 2, "L3+L2+": 3}
            assessed = max(levels, key=lambda lvl: level_order.get(lvl, 0))
        else:
            # Simple keyword-based assessment as fallback
            assessed = _keyword_assess(task_description)

        self._state.assessed_level = assessed
        self._state.assessed_at = utc_now().isoformat()
        self._state.changed_files = list(changed_files)
        self._state.metadata.task_description = task_description
        self._persist()

        # Auto-transition if L0
        if assessed == "L0":
            self._do_transition("COMPLETE", reason="L0 auto-complete")

        return assessed

    def transition(self, target_phase: str) -> GateStateFile:
        """Transition to target phase.

        Args:
            target_phase: One of the 7 valid phase names.

        Returns:
            Updated GateStateFile after transition.

        Raises:
            GatePolicyError: GP003 if transition is illegal (strict mode).
        """
        current = self._state.current_phase

        # Determine enforcement mode
        mode = "strict"
        if self._policy:
            mode = self._policy.enforcement.mode

        # Check if transition is in legal table
        illegal = target_phase not in _LEGAL_TRANSITIONS.get(current, set())

        # Check level conditions
        level_violation = False
        key = (current, target_phase)
        if key in _TRANSITION_LEVEL_CONDITIONS:
            required_levels = _TRANSITION_LEVEL_CONDITIONS[key]
            assessed = self._state.assessed_level
            if assessed not in required_levels:
                level_violation = True

        if illegal or level_violation:
            if mode == "strict":
                reason = f"Illegal transition: {current} → {target_phase}"
                if level_violation:
                    reason = (
                        f"Transition {current} → {target_phase} requires assessed_level "
                        f"in {_TRANSITION_LEVEL_CONDITIONS[key]}, got {self._state.assessed_level}"
                    )
                raise GatePolicyError("GP003", reason)
            elif mode == "permissive":
                logger.warning(
                    "GP003 (permissive): Illegal transition %s → %s blocked but not raised",
                    current,
                    target_phase,
                )
                return self._state  # No transition, no exception
            # disabled mode: proceed regardless
            logger.warning(
                "GP003 (disabled): Illegal transition %s → %s allowed by disabled enforcement",
                current,
                target_phase,
            )

        self._do_transition(target_phase, reason=f"transition to {target_phase}")
        return self._state

    def check_gate(
        self,
        from_phase: str,
        to_phase: str,
        artifacts: dict[str, str | None],
        policy: GatePolicyConfig | None = None,
    ) -> GateCheckResult:
        """Check if gate transition is allowed given current artifacts.

        Does NOT modify state. Pure check function.
        """
        gate_key = f"{from_phase.lower()}_to_{to_phase.lower()}"
        missing: list[str] = []

        # Check policy phase_gates
        effective_policy = policy or self._policy
        if effective_policy and gate_key in effective_policy.phase_gates:
            gate = effective_policy.phase_gates[gate_key]
            for artifact_name in gate.required_artifacts:
                if artifacts.get(artifact_name) is None:
                    missing.append(artifact_name)

        # Check emergency bypass — only active if override file exists
        if effective_policy and effective_policy.emergency_bypass.enabled:
            bypass_path = self._state_path.parent / effective_policy.emergency_bypass.config_file
            bypass_file_exists = bypass_path.exists()
            bypass_expired = self._check_bypass_expiry(effective_policy) if bypass_file_exists else False
            if bypass_file_exists and not bypass_expired:
                # Bypass is active
                if to_phase in effective_policy.emergency_bypass.allowed_phases:
                    return GateCheckResult(passed=True, validation_message="Emergency bypass active")
                else:
                    missing.append(f"emergency_bypass:phase_{to_phase}_not_allowed")

        return GateCheckResult(
            passed=len(missing) == 0,
            missing_artifacts=missing,
            validation_message="All artifacts present" if not missing else f"Missing: {missing}",
        )

    def update_artifact(self, name: str, value: str) -> None:
        """Update artifact status in gate.json."""
        self._state.artifacts[name] = value
        self._persist()

    def reset(self) -> GateStateFile:
        """Reset state machine to IDLE.

        Returns:
            GateStateFile with current_phase="IDLE", cleared history.

        Contract:
            - Clears assessed_level, changed_files, phase_history, gate_checks, artifacts, review_checkpoint.
            - Persists reset state to gate.json.
            - Does NOT clear metadata.created_at.
            - Gate key format: ``{from_phase.lower()}_to_{to_phase.lower()}``
              (e.g. "sdd_to_bdd", "tdd_to_review"). After reset, all gate_checks are cleared.
        """
        created_at = self._state.metadata.created_at
        self._state = GateStateFile()
        self._state.metadata.created_at = created_at
        self._state.metadata.updated_at = utc_now().isoformat()
        self._persist()
        return self._state

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    def _check_bypass_expiry(self, policy: GatePolicyConfig) -> bool:
        """Check if emergency bypass has expired.

        Returns True if bypass has expired (should enforce normal rules).
        Returns False if bypass is still active or no override file exists.
        """
        bypass_path = self._state_path.parent / policy.emergency_bypass.config_file
        if not bypass_path.exists():
            return False  # No override file → bypass not activated
        try:
            data = json.loads(bypass_path.read_text())
            expires_at = data.get("expires_at")
            if not expires_at:
                return False  # No expiry set → bypass active indefinitely
            from datetime import datetime

            expiry = datetime.fromisoformat(expires_at)
            now = utc_now()
            if now >= expiry:
                return True  # Bypass expired
            return False
        except Exception:
            return False  # Corrupt file → treat as bypass active (safer default)

    def _do_transition(self, target: str, reason: str = "") -> None:
        """Execute a transition and log it."""
        transition = PhaseTransition(
            from_phase=self._state.current_phase,
            to_phase=target,
            timestamp=utc_now().isoformat(),
            reason=reason,
        )
        self._state.phase_history.append(transition)
        self._state.current_phase = target
        self._state.metadata.updated_at = utc_now().isoformat()
        # Auto-set review_checkpoint when entering REVIEW
        if target == "REVIEW":
            self._state.review_checkpoint.triggered = True
            self._state.review_checkpoint.checkpoint_level = self._state.assessed_level
        self._persist()

    def _load_state(self) -> GateStateFile:
        """Load state from gate.json. Returns IDLE on any failure (GP006)."""
        if not self._state_path.exists():
            state = GateStateFile()
            state.metadata.created_at = utc_now().isoformat()
            return state
        try:
            data = json.loads(self._state_path.read_text())
            return GateStateFile.model_validate(data)
        except Exception:
            # GP006: corrupt file, reset to IDLE
            state = GateStateFile()
            state.metadata.created_at = utc_now().isoformat()
            return state

    def _persist(self) -> None:
        """Atomic write of gate.json via temp file + os.replace()."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._state.model_dump(mode="json")

        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._state_path.parent),
                suffix=".tmp",
            )
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self._state_path)
        except Exception:
            # GP006: write failure, try to clean up temp file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise


# ---------------------------------------------------------------------------
# Helper: Keyword-based complexity assessment (fallback)
# ---------------------------------------------------------------------------

_KEYWORD_LEVELS: dict[str, list[str]] = {
    "L0": ["typo", "comment", "log", "style", "rename", "whitespace", "formatting"],
    "L1": ["config", "flag", "param", "validation", "default", "simple fix", "parameter"],
    "L2": ["feature", "module", "refactor", "api", "integration", "new feature"],
    "L3+L2+": ["subsystem", "migration", "breaking", "security", "architecture", "performance"],
}


def _keyword_assess(task_description: str) -> str:
    """Assess complexity from task description keywords."""
    desc_lower = task_description.lower()
    # Check from highest to lowest
    for level in ["L3+L2+", "L2", "L1", "L0"]:
        for keyword in _KEYWORD_LEVELS[level]:
            if keyword in desc_lower:
                return level
    return "L2"  # Default
