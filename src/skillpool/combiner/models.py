"""Combination data models — SkillCombination + lifecycle state enum."""
from __future__ import annotations

from enum import IntEnum
from typing import Optional

from pydantic import BaseModel, Field

from skillpool.utils.time_utils import utc_now

# Minimum executions before a combination can be promoted
MIN_VALIDATION_EXECUTIONS = 5


class CombinationLifecycleState(IntEnum):
    """Lifecycle states for skill combinations."""
    DISCOVERED = 0   # New combination, awaiting validation
    VALIDATING = 1   # Collecting execution data
    PROMOTED = 2     # Validated, positive gain, officially recommended
    REJECTED = 3     # Validation failed, negative or insufficient gain
    DEPRECATED = 4   # Gain decayed, no longer recommended
    RETIRED = 5      # Permanently removed


class SkillCombination(BaseModel):
    """A skill combination with lifecycle state and gain data."""
    combination_id: str = Field(default="", description="Unique combination ID")
    primary: str = Field(description="Primary skill ID")
    enhancers: list[str] = Field(default_factory=list, description="Enhancing skill IDs")
    state: CombinationLifecycleState = Field(
        default=CombinationLifecycleState.DISCOVERED,
        description="Current lifecycle state",
    )
    source: str = Field(
        default="auto_discovered",
        description="Discovery source: auto_discovered | human_specified",
    )
    gain_avg: float = Field(default=0.0, description="Average gain across executions")
    gain_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence in gain estimate [0,1]",
    )
    execution_count: int = Field(default=0, description="Total executions")
    last_execution: str = Field(default="", description="ISO 8601 timestamp")
    discovered_at: str = Field(default="", description="When discovered")
    promoted_at: str = Field(default="", description="When promoted")
    deprecated_at: str = Field(default="", description="When deprecated")
    all_time_gain_avg: float = Field(default=0.0, description="All-time average gain (computed on promotion)")
    recent_gain_avg: float = Field(default=0.0, description="Recent average gain (computed on deprecation check)")
    base_weight: float = Field(default=0.5, ge=0.0, le=1.0, description="Base weight")
    decay_lambda: float = Field(default=0.01, description="Time decay coefficient")
    rejection_reason: str = Field(default="", description="Why rejected, if applicable")

    def model_post_init(self, __context: object) -> None:
        if not self.combination_id:
            enhancer_str = "+".join(sorted(self.enhancers))
            self.combination_id = f"{self.primary}+{enhancer_str}"
        if not self.discovered_at:
            self.discovered_at = utc_now().isoformat()

    def current_weight(self) -> float:
        """Compute dynamic weight: base × time_decay × confidence."""
        if self.state not in (
            CombinationLifecycleState.PROMOTED,
            CombinationLifecycleState.VALIDATING,
        ):
            return 0.0

        # Time decay
        if self.last_execution:
            from datetime import datetime
            try:
                last = datetime.fromisoformat(self.last_execution)
                days = (utc_now() - last).days
                time_decay = max(0.1, 1.0 - self.decay_lambda * days)
            except (ValueError, TypeError):
                time_decay = 1.0
        else:
            time_decay = 0.5

        # Confidence factor
        confidence_factor = min(1.0, self.execution_count / MIN_VALIDATION_EXECUTIONS)

        return self.base_weight * time_decay * confidence_factor


class CombinationTransitionResult(BaseModel):
    """Result of a lifecycle state transition."""
    combination_id: str
    from_state: CombinationLifecycleState
    to_state: CombinationLifecycleState
    success: bool = True
    reason: str = ""
