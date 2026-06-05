"""Review models — Pydantic schemas for multi-dimension review pipeline.

Aligned with contracts/sdd/review-trigger-spec.yaml
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ReviewTrigger(StrEnum):
    """What triggered this review."""

    L3_REGRESSION_FAIL = "l3_regression_fail"
    L4_E2E_FAIL = "l4_e2e_fail"
    L5_ERROR_BUDGET_BURN = "l5_error_budget_burn"
    MANUAL = "manual"
    SCHEDULED_DIMENSION_SCAN = "scheduled_dimension_scan"


class CheckpointLevel(StrEnum):
    """Review checkpoint level — determines which dimensions are evaluated."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


# Checkpoint SLA timeouts (per spec)
CHECKPOINT_SLA_TIMEOUTS: dict[CheckpointLevel, float] = {
    CheckpointLevel.L1: 10.0,  # seconds
    CheckpointLevel.L2: 60.0,
    CheckpointLevel.L3: 120.0,
    CheckpointLevel.L4: 300.0,
}


class VetoRule(StrEnum):
    """Veto rules V1-V6 with human-readable conditions."""

    V1 = "V1"  # D3 < 7.0 → block
    V2 = "V2"  # D5 < 7.0 → block
    V3 = "V3"  # D7 < 7.5 → block
    V4 = "V4"  # D11 < 6.0 → block
    V5 = "V5"  # D10 < 5.5 → risk_notice (not block)
    V6 = "V6"  # baseline_avg < 7.5 → veto_explanation


class ReviewStatus(StrEnum):
    """Status of a review execution."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    QUEUED = "queued"
    PROCESSING = "processing"


class UpgradeRecommendation(StrEnum):
    """Recommended upgrade action based on review results."""

    PATCH = "PATCH"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    NONE = "NONE"


class FailedTestDetail(BaseModel):
    """Structured failed test information (per schema)."""

    test_name: str
    expected: str = ""
    actual: str = ""
    skill_id: str = ""
    duration_ms: float = 0.0


class VetoDetail(BaseModel):
    """Detail of a single veto rule evaluation."""

    rule: VetoRule
    dimension: str
    score: float
    threshold: float
    blocks: bool = Field(description="Whether this veto blocks admission")
    recommendation: str = Field(default="", description="Action recommendation")


class SuspectSkill(BaseModel):
    """A skill marked as suspect during review."""

    skill_id: str
    reason: str
    suspected_dimension: str = ""


class BlindSpotFound(BaseModel):
    """New blind spot discovered during review."""

    id: str
    description: str
    dimension: str
    severity: str = "P2"


class ReviewTriggerRequest(BaseModel):
    """Request to trigger a multi-dimension review.

    Aligned with contracts/sdd/review-trigger-spec.yaml:
    - trace_id: W3C TraceContext
    - failed_tests: structured objects (not flat strings)
    - baseline_metrics: before/after metrics for comparison
    - pipeline_url: CI pipeline reference
    """

    trigger: ReviewTrigger
    checkpoint: CheckpointLevel
    affected_skills: list[str] = Field(min_length=1, description="Skill IDs under review")
    failed_tests: Optional[list[str]] = Field(default=None, description="Test IDs that failed (backward compat)")
    failed_test_details: list[FailedTestDetail] = Field(default_factory=list, description="Structured failed test info")
    trace_id: str = Field(default="", description="W3C TraceContext trace_id")
    baseline_metrics: dict[str, float] = Field(
        default_factory=dict, description="Baseline metrics (previous_recall, current_recall, etc.)"
    )
    pipeline_url: str = Field(default="", description="CI pipeline URL for audit")

    def get_all_failed_tests(self) -> list[str]:
        """Get all failed test names (from both flat and structured sources)."""
        flat = self.failed_tests or []
        structured = [d.test_name for d in self.failed_test_details]
        # Merge, dedup
        return list(dict.fromkeys(flat + structured))


class ReviewTriggerResponse(BaseModel):
    """Response from a review trigger execution.

    Aligned with contracts/sdd/review-trigger-spec.yaml:
    - new_blind_spots: blind spots discovered
    - estimated_cost: token/cost estimate
    - merkle_commit: ClawMem savepoint hash
    - retry_after_seconds: for async polling
    """

    review_id: str
    status: ReviewStatus
    checkpoint: CheckpointLevel
    scores: dict[str, float] = Field(default_factory=dict, description="Dimension → score (D1-D12)")
    veto_triggered: bool = False
    veto_details: list[VetoDetail] = Field(default_factory=list)
    suspect_skills: list[SuspectSkill] = Field(default_factory=list)
    recommendation: UpgradeRecommendation = UpgradeRecommendation.NONE
    duration_ms: float = 0.0
    # Schema-aligned fields
    new_blind_spots: list[BlindSpotFound] = Field(default_factory=list, description="New blind spots discovered")
    estimated_cost: dict[str, Any] = Field(
        default_factory=dict, description="Cost estimate {review_tokens, review_cost_usd}"
    )
    merkle_commit: str = Field(default="", description="ClawMem SAVEPOINT hash")
    retry_after_seconds: float = Field(default=0.0, description="Seconds until async result available (0 = sync)")
