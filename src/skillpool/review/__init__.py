"""ReviewManager — orchestrates the multi-dimension review pipeline."""
from __future__ import annotations

import time
import uuid

from skillpool.review.models import (
    CheckpointLevel,
    ReviewStatus,
    ReviewTriggerRequest,
    ReviewTriggerResponse,
    SuspectSkill,
    UpgradeRecommendation,
)
from skillpool.review.veto_evaluator import VetoEvaluator
from skillpool.review.checkpoint_runner import CheckpointRunner
from skillpool.review.suspect_marker import SuspectMarker
from skillpool.review.async_queue import AsyncReviewQueue
from skillpool.telemetry import TelemetryBridge


class ReviewManager:
    """Orchestrates the full review pipeline.

    Pipeline: validate request → check cooldown → run checkpoint →
              evaluate veto → mark suspects → feed evolver → emit telemetry

    When an EvolverLayer is provided, veto results feed into the defect
    accumulation system, and evolution proposals are generated automatically.
    """

    def __init__(
        self,
        telemetry: TelemetryBridge | None = None,
        checkpoint_runner: CheckpointRunner | None = None,
        veto_evaluator: VetoEvaluator | None = None,
        suspect_marker: SuspectMarker | None = None,
        queue: AsyncReviewQueue | None = None,
        evolver=None,
    ) -> None:
        self._telemetry = telemetry or TelemetryBridge()
        self._runner = checkpoint_runner or CheckpointRunner()
        self._evaluator = veto_evaluator or VetoEvaluator()
        self._marker = suspect_marker or SuspectMarker()
        self._queue = queue or AsyncReviewQueue()
        self._evolver = evolver

    def trigger(self, request: ReviewTriggerRequest) -> ReviewTriggerResponse:
        """Execute the full review pipeline for a trigger request."""
        start_ms = time.time() * 1000

        # Step 1: Check cooldown via queue (returns the review_id)
        try:
            review_id = self._queue.submit(request)
        except ValueError:
            # Cooldown violation — return queued status
            return ReviewTriggerResponse(
                review_id=uuid.uuid4().hex[:16],
                status=ReviewStatus.QUEUED,
                checkpoint=request.checkpoint,
                scores={},
                veto_triggered=False,
                veto_details=[],
                suspect_skills=[],
                recommendation=UpgradeRecommendation.NONE,
                duration_ms=round(time.time() * 1000 - start_ms, 2),
            )
        except RuntimeError:
            # Max concurrent reached — return queued
            return ReviewTriggerResponse(
                review_id=uuid.uuid4().hex[:16],
                status=ReviewStatus.QUEUED,
                checkpoint=request.checkpoint,
                scores={},
                veto_triggered=False,
                veto_details=[],
                suspect_skills=[],
                recommendation=UpgradeRecommendation.NONE,
                duration_ms=round(time.time() * 1000 - start_ms, 2),
            )

        # Mark as processing
        self._queue.set_status(review_id, ReviewStatus.PROCESSING)

        # Step 2: Run checkpoint
        try:
            scores = self._runner.run_checkpoint(
                level=request.checkpoint,
                skills=request.affected_skills,
            )
        except Exception:
            self._queue.set_status(review_id, ReviewStatus.FAILED)
            return ReviewTriggerResponse(
                review_id=review_id,
                status=ReviewStatus.FAILED,
                checkpoint=request.checkpoint,
                scores={},
                veto_triggered=False,
                veto_details=[],
                suspect_skills=[],
                recommendation=UpgradeRecommendation.NONE,
                duration_ms=round(time.time() * 1000 - start_ms, 2),
            )

        # Step 3: Evaluate veto (only for L2, L3, L4)
        veto_details = []
        veto_triggered = False
        if request.checkpoint in (CheckpointLevel.L2, CheckpointLevel.L3, CheckpointLevel.L4):
            veto_details, veto_triggered = self._evaluator.evaluate(scores)

        # Step 4: Mark suspect skills
        suspect_skills: list[SuspectSkill] = []
        for detail in veto_details:
            if detail.blocks:
                for skill_id in request.affected_skills:
                    self._marker.mark(
                        skill_id=skill_id,
                        reason=f"Veto {detail.rule.value}: {detail.recommendation}",
                        suspected_dimension=detail.dimension,
                    )
        suspect_skills = self._marker.list_suspects()

        # Step 5: Feed evolver (if available) and determine recommendation
        recommendation = self._determine_recommendation(veto_details)
        self._feed_evolver(veto_details, request, recommendation)

        # Step 6: Determine final status
        if veto_triggered:
            status = ReviewStatus.PARTIAL
        else:
            status = ReviewStatus.COMPLETED

        self._queue.set_status(review_id, status)

        # Step 7: Emit telemetry (propagate trace_id from request)
        for skill_id in request.affected_skills:
            self._telemetry.emit(
                event_type="review_completed",
                skill_id=skill_id,
                payload={
                    "review_id": review_id,
                    "checkpoint": request.checkpoint.value,
                    "trigger": request.trigger.value,
                    "veto_triggered": veto_triggered,
                    "recommendation": recommendation.value,
                    "scores": scores,
                },
                trace_id=request.trace_id,
            )

        duration_ms = round(time.time() * 1000 - start_ms, 2)
        return ReviewTriggerResponse(
            review_id=review_id,
            status=status,
            checkpoint=request.checkpoint,
            scores=scores,
            veto_triggered=veto_triggered,
            veto_details=veto_details,
            suspect_skills=suspect_skills,
            recommendation=recommendation,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _determine_recommendation(veto_details: list) -> UpgradeRecommendation:
        """Determine upgrade recommendation from veto results.

        - MAJOR: any P0-level veto (V1 security block)
        - MINOR: any P1-level veto (V2, V3, V4)
        - PATCH: only V5 risk notice or V6 explanation
        - NONE: no vetoes at all
        """
        if not veto_details:
            return UpgradeRecommendation.NONE

        blocking = [d for d in veto_details if d.blocks]
        if not blocking:
            # Only non-blocking (V5) → PATCH
            return UpgradeRecommendation.PATCH

        # Check for MAJOR triggers (security = V1)
        for d in blocking:
            if d.rule.value in ("V1",):
                return UpgradeRecommendation.MAJOR

        # Check for MINOR triggers (V2, V3, V4)
        for d in blocking:
            if d.rule.value in ("V2", "V3", "V4"):
                return UpgradeRecommendation.MINOR

        # V6 only → PATCH
        return UpgradeRecommendation.PATCH

    def _feed_evolver(self, veto_details, request, recommendation) -> None:
        """Feed veto results into EvolverLayer for defect accumulation.

        When evolver is available, each blocking veto is recorded as a defect.
        Non-blocking vetoes are recorded as MINOR defects for tracking.
        Evolution proposals are created when defect thresholds are reached.
        """
        if self._evolver is None:
            return

        from skillpool.evolver import DefectSeverity

        for detail in veto_details:
            # Map veto severity to defect severity
            if detail.blocks:
                if detail.rule.value == "V1":
                    severity = DefectSeverity.CRITICAL
                else:
                    severity = DefectSeverity.MAJOR
            else:
                severity = DefectSeverity.MINOR

            # Record one defect per affected skill per veto
            for skill_id in request.affected_skills:
                self._evolver.record_defect(
                    skill_id=skill_id,
                    version="current",
                    severity=severity,
                    description=f"Veto {detail.rule.value}: {detail.recommendation}",
                )

        # If recommendation is MAJOR/MINOR, create an evolution proposal
        if recommendation in (UpgradeRecommendation.MAJOR, UpgradeRecommendation.MINOR):
            context = {
                "trigger": "review_veto",
                "recommendation": recommendation.value,
                "checkpoint": request.checkpoint.value,
                "affected_skills": request.affected_skills,
                "veto_count": len(veto_details),
            }
            self._evolver.create_proposal(
                context=context,
                risk="high" if recommendation == UpgradeRecommendation.MAJOR else "medium",
            )
