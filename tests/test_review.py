"""Comprehensive tests for skillpool.review — models, veto, checkpoint, suspect, queue, manager."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from skillpool.review.models import (
    CheckpointLevel,
    ReviewStatus,
    ReviewTrigger,
    ReviewTriggerRequest,
    ReviewTriggerResponse,
    SuspectSkill,
    UpgradeRecommendation,
    VetoDetail,
    VetoRule,
)
from skillpool.review.veto_evaluator import VetoEvaluator
from skillpool.review.checkpoint_runner import CheckpointRunner, SHADOW_DIMENSIONS, BASELINE_DIMENSIONS, ALL_DIMENSIONS
from skillpool.review.suspect_marker import SuspectMarker
from skillpool.review.async_queue import AsyncReviewQueue
from skillpool.review import ReviewManager
from skillpool.telemetry import TelemetryBridge


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def evaluator() -> VetoEvaluator:
    return VetoEvaluator()


@pytest.fixture
def runner() -> CheckpointRunner:
    return CheckpointRunner(seed=42)


@pytest.fixture
def marker() -> SuspectMarker:
    return SuspectMarker()


@pytest.fixture
def queue() -> AsyncReviewQueue:
    return AsyncReviewQueue(max_concurrent=10, cooldown_seconds=86400.0)


@pytest.fixture
def fast_queue() -> AsyncReviewQueue:
    """Queue with very short cooldown for testing."""
    return AsyncReviewQueue(max_concurrent=2, cooldown_seconds=0.1)


@pytest.fixture
def manager(tmp_path: Path) -> ReviewManager:
    telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
    return ReviewManager(telemetry=telemetry)


def _make_request(
    trigger: ReviewTrigger = ReviewTrigger.MANUAL,
    checkpoint: CheckpointLevel = CheckpointLevel.L2,
    skills: list[str] | None = None,
    failed_tests: list[str] | None = None,
) -> ReviewTriggerRequest:
    return ReviewTriggerRequest(
        trigger=trigger,
        checkpoint=checkpoint,
        affected_skills=skills or ["S05a", "S10"],
        failed_tests=failed_tests,
    )


# ── Models ────────────────────────────────────────────────────────────

class TestModels:
    """Pydantic model validation."""

    def test_review_trigger_enum(self):
        assert ReviewTrigger.L3_REGRESSION_FAIL.value == "l3_regression_fail"
        assert ReviewTrigger.L4_E2E_FAIL.value == "l4_e2e_fail"
        assert ReviewTrigger.L5_ERROR_BUDGET_BURN.value == "l5_error_budget_burn"
        assert ReviewTrigger.MANUAL.value == "manual"

    def test_checkpoint_level_enum(self):
        assert set(CheckpointLevel) == {CheckpointLevel.L1, CheckpointLevel.L2, CheckpointLevel.L3, CheckpointLevel.L4}

    def test_veto_rule_enum(self):
        assert set(VetoRule) == {VetoRule.V1, VetoRule.V2, VetoRule.V3, VetoRule.V4, VetoRule.V5, VetoRule.V6}

    def test_review_status_enum(self):
        assert set(ReviewStatus) == {
            ReviewStatus.COMPLETED, ReviewStatus.PARTIAL, ReviewStatus.FAILED,
            ReviewStatus.QUEUED, ReviewStatus.PROCESSING,
        }

    def test_upgrade_recommendation_enum(self):
        assert set(UpgradeRecommendation) == {
            UpgradeRecommendation.PATCH, UpgradeRecommendation.MINOR,
            UpgradeRecommendation.MAJOR, UpgradeRecommendation.NONE,
        }

    def test_veto_detail_model(self):
        vd = VetoDetail(
            rule=VetoRule.V1,
            dimension="D3",
            score=6.5,
            threshold=7.0,
            blocks=True,
            recommendation="D3 < 7.0 — block",
        )
        assert vd.rule is VetoRule.V1
        assert vd.score == 6.5
        assert vd.blocks is True

    def test_suspect_skill_model(self):
        ss = SuspectSkill(skill_id="S05a", reason="D3 low", suspected_dimension="D3")
        assert ss.skill_id == "S05a"
        assert ss.suspected_dimension == "D3"

    def test_review_trigger_request_minimal(self):
        req = ReviewTriggerRequest(
            trigger=ReviewTrigger.MANUAL,
            checkpoint=CheckpointLevel.L2,
            affected_skills=["S05a"],
        )
        assert req.failed_tests is None

    def test_review_trigger_request_with_failed_tests(self):
        req = ReviewTriggerRequest(
            trigger=ReviewTrigger.L3_REGRESSION_FAIL,
            checkpoint=CheckpointLevel.L3,
            affected_skills=["S05a", "S10"],
            failed_tests=["test_d3_compliance", "test_d5_resilience"],
        )
        assert len(req.failed_tests) == 2

    def test_review_trigger_request_empty_skills_rejected(self):
        with pytest.raises(Exception):
            ReviewTriggerRequest(
                trigger=ReviewTrigger.MANUAL,
                checkpoint=CheckpointLevel.L1,
                affected_skills=[],
            )

    def test_review_trigger_response_defaults(self):
        resp = ReviewTriggerResponse(
            review_id="abc123",
            status=ReviewStatus.COMPLETED,
            checkpoint=CheckpointLevel.L2,
        )
        assert resp.scores == {}
        assert resp.veto_triggered is False
        assert resp.veto_details == []
        assert resp.suspect_skills == []
        assert resp.recommendation is UpgradeRecommendation.NONE
        assert resp.duration_ms == 0.0


# ── VetoEvaluator ────────────────────────────────────────────────────

class TestVetoEvaluator:
    """VetoEvaluator — all 6 veto rules."""

    def test_no_veto_when_all_scores_high(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 9.0 for i in range(1, 13)}
        details, triggered = evaluator.evaluate(scores)
        assert triggered is False
        assert details == []

    def test_v1_d3_below_threshold(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 9.0 for i in range(1, 13)}
        scores["D3"] = 6.5  # below 7.0
        details, triggered = evaluator.evaluate(scores)
        assert triggered is True
        v1 = [d for d in details if d.rule is VetoRule.V1]
        assert len(v1) == 1
        assert v1[0].dimension == "D3"
        assert v1[0].score == 6.5
        assert v1[0].threshold == 7.0
        assert v1[0].blocks is True

    def test_v2_d5_below_threshold(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 9.0 for i in range(1, 13)}
        scores["D5"] = 6.0  # below 7.0
        details, triggered = evaluator.evaluate(scores)
        assert triggered is True
        v2 = [d for d in details if d.rule is VetoRule.V2]
        assert len(v2) == 1
        assert v2[0].dimension == "D5"
        assert v2[0].blocks is True

    def test_v3_d7_below_threshold(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 9.0 for i in range(1, 13)}
        scores["D7"] = 7.0  # below 7.5
        details, triggered = evaluator.evaluate(scores)
        assert triggered is True
        v3 = [d for d in details if d.rule is VetoRule.V3]
        assert len(v3) == 1
        assert v3[0].dimension == "D7"
        assert v3[0].threshold == 7.5
        assert v3[0].blocks is True

    def test_v4_d11_below_threshold(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 9.0 for i in range(1, 13)}
        scores["D11"] = 5.5  # below 6.0
        details, triggered = evaluator.evaluate(scores)
        assert triggered is True
        v4 = [d for d in details if d.rule is VetoRule.V4]
        assert len(v4) == 1
        assert v4[0].dimension == "D11"
        assert v4[0].blocks is True

    def test_v5_d10_below_threshold_not_blocking(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 9.0 for i in range(1, 13)}
        scores["D10"] = 5.0  # below 5.5
        details, triggered = evaluator.evaluate(scores)
        # V5 does NOT block
        assert triggered is False
        v5 = [d for d in details if d.rule is VetoRule.V5]
        assert len(v5) == 1
        assert v5[0].dimension == "D10"
        assert v5[0].blocks is False

    def test_v6_baseline_avg_below_threshold(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 9.0 for i in range(1, 13)}
        # Set baseline dimensions low so average < 7.5
        scores["D3"] = 6.0
        scores["D5"] = 6.0
        scores["D7"] = 6.0
        scores["D10"] = 6.0
        scores["D11"] = 6.0
        details, triggered = evaluator.evaluate(scores)
        assert triggered is True
        v6 = [d for d in details if d.rule is VetoRule.V6]
        assert len(v6) == 1
        assert v6[0].dimension == "baseline_avg"
        assert v6[0].score < 7.5
        assert v6[0].blocks is True

    def test_v6_not_triggered_when_baseline_ok(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 8.0 for i in range(1, 13)}
        details, triggered = evaluator.evaluate(scores)
        v6 = [d for d in details if d.rule is VetoRule.V6]
        assert len(v6) == 0

    def test_multiple_vetos_fire(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 4.0 for i in range(1, 13)}
        details, triggered = evaluator.evaluate(scores)
        assert triggered is True
        # Should have V1, V2, V3, V4, V5, V6 all firing
        rules = {d.rule for d in details}
        assert VetoRule.V1 in rules
        assert VetoRule.V2 in rules
        assert VetoRule.V3 in rules
        assert VetoRule.V4 in rules
        assert VetoRule.V5 in rules
        assert VetoRule.V6 in rules

    def test_missing_dimension_defaults_to_zero(self, evaluator: VetoEvaluator):
        # Only provide some dimensions — missing ones default to 0.0
        scores = {"D1": 9.0, "D2": 9.0}
        details, triggered = evaluator.evaluate(scores)
        assert triggered is True
        # D3=0.0 triggers V1, D5=0.0 triggers V2, etc.

    def test_v3_exactly_at_threshold_passes(self, evaluator: VetoEvaluator):
        scores = {f"D{i}": 9.0 for i in range(1, 13)}
        scores["D7"] = 7.5  # exactly at threshold — should NOT trigger
        details, triggered = evaluator.evaluate(scores)
        v3 = [d for d in details if d.rule is VetoRule.V3]
        assert len(v3) == 0


# ── CheckpointRunner ─────────────────────────────────────────────────

class TestCheckpointRunner:
    """CheckpointRunner — L1/L2/L3/L4 dimension selection and scoring."""

    def test_l1_shadow_dimensions_only(self, runner: CheckpointRunner):
        scores = runner.run_checkpoint(CheckpointLevel.L1, ["S05a"])
        assert set(scores.keys()) == set(SHADOW_DIMENSIONS)
        assert len(scores) == 7

    def test_l2_all_dimensions(self, runner: CheckpointRunner):
        scores = runner.run_checkpoint(CheckpointLevel.L2, ["S05a"])
        assert set(scores.keys()) == set(ALL_DIMENSIONS)
        assert len(scores) == 12

    def test_l3_baseline_dimensions(self, runner: CheckpointRunner):
        scores = runner.run_checkpoint(CheckpointLevel.L3, ["S05a"])
        assert set(scores.keys()) == set(BASELINE_DIMENSIONS)
        assert len(scores) == 5

    def test_l4_baseline_regression(self, runner: CheckpointRunner):
        scores = runner.run_checkpoint(CheckpointLevel.L4, ["S05a"])
        assert set(scores.keys()) == set(BASELINE_DIMENSIONS)

    def test_scores_in_valid_range(self, runner: CheckpointRunner):
        scores = runner.run_checkpoint(CheckpointLevel.L2, ["S05a", "S10"])
        for dim, score in scores.items():
            assert 5.0 <= score <= 10.0, f"{dim} score {score} out of range"

    def test_deterministic_with_same_seed(self):
        r1 = CheckpointRunner(seed=42)
        r2 = CheckpointRunner(seed=42)
        s1 = r1.run_checkpoint(CheckpointLevel.L2, ["S05a"])
        s2 = r2.run_checkpoint(CheckpointLevel.L2, ["S05a"])
        assert s1 == s2

    def test_different_seed_different_scores(self):
        r1 = CheckpointRunner(seed=42)
        r2 = CheckpointRunner(seed=99)
        s1 = r1.run_checkpoint(CheckpointLevel.L2, ["S05a"])
        s2 = r2.run_checkpoint(CheckpointLevel.L2, ["S05a"])
        # Extremely unlikely to be identical with different seeds
        assert s1 != s2

    def test_different_skills_different_scores(self):
        # Use default seed (derived from skills) so different skills produce different seeds
        runner = CheckpointRunner()
        s1 = runner.run_checkpoint(CheckpointLevel.L2, ["S05a"])
        s2 = runner.run_checkpoint(CheckpointLevel.L2, ["S10"])
        assert s1 != s2


# ── SuspectMarker ────────────────────────────────────────────────────

class TestSuspectMarker:
    """SuspectMarker — mark, check, list, clear."""

    def test_mark_and_is_suspect(self, marker: SuspectMarker):
        marker.mark("S05a", reason="D3 low", suspected_dimension="D3")
        assert marker.is_suspect("S05a") is True
        assert marker.is_suspect("S10") is False

    def test_list_suspects(self, marker: SuspectMarker):
        marker.mark("S05a", reason="D3 low", suspected_dimension="D3")
        marker.mark("S10", reason="D5 low", suspected_dimension="D5")
        suspects = marker.list_suspects()
        assert len(suspects) == 2
        ids = {s.skill_id for s in suspects}
        assert ids == {"S05a", "S10"}

    def test_list_suspects_returns_suspect_skill_objects(self, marker: SuspectMarker):
        marker.mark("S05a", reason="D3 low", suspected_dimension="D3")
        suspects = marker.list_suspects()
        assert isinstance(suspects[0], SuspectSkill)
        assert suspects[0].reason == "D3 low"
        assert suspects[0].suspected_dimension == "D3"

    def test_clear(self, marker: SuspectMarker):
        marker.mark("S05a", reason="test")
        marker.mark("S10", reason="test")
        marker.clear()
        assert marker.is_suspect("S05a") is False
        assert marker.is_suspect("S10") is False
        assert marker.list_suspects() == []

    def test_mark_overwrites_previous(self, marker: SuspectMarker):
        marker.mark("S05a", reason="first", suspected_dimension="D3")
        marker.mark("S05a", reason="second", suspected_dimension="D5")
        suspects = marker.list_suspects()
        assert len(suspects) == 1
        assert suspects[0].reason == "second"
        assert suspects[0].suspected_dimension == "D5"

    def test_empty_marker(self, marker: SuspectMarker):
        assert marker.list_suspects() == []
        assert marker.is_suspect("nonexistent") is False


# ── AsyncReviewQueue ─────────────────────────────────────────────────

class TestAsyncReviewQueue:
    """AsyncReviewQueue — submit, status, cooldown, max_concurrent."""

    def test_submit_returns_review_id(self, queue: AsyncReviewQueue):
        req = _make_request()
        review_id = queue.submit(req)
        assert isinstance(review_id, str)
        assert len(review_id) > 0

    def test_get_status_after_submit(self, queue: AsyncReviewQueue):
        req = _make_request()
        review_id = queue.submit(req)
        status = queue.get_status(review_id)
        assert status is ReviewStatus.QUEUED

    def test_set_status(self, queue: AsyncReviewQueue):
        req = _make_request()
        review_id = queue.submit(req)
        queue.set_status(review_id, ReviewStatus.PROCESSING)
        assert queue.get_status(review_id) is ReviewStatus.PROCESSING

    def test_get_status_unknown_raises(self, queue: AsyncReviewQueue):
        with pytest.raises(KeyError):
            queue.get_status("nonexistent")

    def test_cooldown_blocks_resubmit(self, queue: AsyncReviewQueue):
        req = _make_request(skills=["S05a"])
        queue.submit(req)
        # Second submit with same skill should fail
        req2 = _make_request(skills=["S05a"])
        with pytest.raises(ValueError, match="cooldown"):
            queue.submit(req2)

    def test_cooldown_different_skills_ok(self, queue: AsyncReviewQueue):
        req1 = _make_request(skills=["S05a"])
        queue.submit(req1)
        # Different skill should be fine
        req2 = _make_request(skills=["S10"])
        review_id = queue.submit(req2)
        assert isinstance(review_id, str)

    def test_cooldown_expires(self, fast_queue: AsyncReviewQueue):
        req1 = _make_request(skills=["S05a"])
        fast_queue.submit(req1)
        # Wait for cooldown to expire
        time.sleep(0.15)
        req2 = _make_request(skills=["S05a"])
        review_id = fast_queue.submit(req2)
        assert isinstance(review_id, str)

    def test_is_in_cooldown(self, fast_queue: AsyncReviewQueue):
        req = _make_request(skills=["S05a"])
        fast_queue.submit(req)
        assert fast_queue.is_in_cooldown("S05a") is True
        assert fast_queue.is_in_cooldown("S10") is False

    def test_max_concurrent(self, fast_queue: AsyncReviewQueue):
        # fast_queue has max_concurrent=2
        req1 = _make_request(skills=["S05a"])
        req2 = _make_request(skills=["S10"])
        fast_queue.submit(req1)
        fast_queue.submit(req2)
        # Set both to PROCESSING
        for rid in list(fast_queue._entries.keys()):
            fast_queue.set_status(rid, ReviewStatus.PROCESSING)
        # Third should fail
        req3 = _make_request(skills=["S13a"])
        with pytest.raises(RuntimeError, match="Max concurrent"):
            fast_queue.submit(req3)

    def test_clear(self, queue: AsyncReviewQueue):
        req = _make_request()
        queue.submit(req)
        queue.clear()
        with pytest.raises(KeyError):
            queue.get_status("any")


# ── ReviewManager ────────────────────────────────────────────────────

class TestReviewManager:
    """ReviewManager.trigger() — happy path, veto path, cooldown path."""

    def test_happy_path_l1(self, manager: ReviewManager):
        req = _make_request(checkpoint=CheckpointLevel.L1)
        resp = manager.trigger(req)
        assert resp.status is ReviewStatus.COMPLETED
        assert resp.checkpoint is CheckpointLevel.L1
        assert len(resp.scores) == 7  # shadow dimensions
        assert resp.veto_triggered is False
        assert resp.veto_details == []
        assert resp.recommendation is UpgradeRecommendation.NONE
        assert resp.duration_ms > 0

    def test_happy_path_l2(self, manager: ReviewManager):
        req = _make_request(checkpoint=CheckpointLevel.L2)
        resp = manager.trigger(req)
        assert resp.status in (ReviewStatus.COMPLETED, ReviewStatus.PARTIAL)
        assert len(resp.scores) == 12  # all dimensions
        assert resp.review_id  # non-empty

    def test_veto_path_l3(self, tmp_path: Path):
        """L3 with scores that trigger a veto."""
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        # Use a runner that produces low scores
        runner = _LowScoreRunner()
        manager = ReviewManager(
            telemetry=telemetry,
            checkpoint_runner=runner,
            queue=AsyncReviewQueue(cooldown_seconds=0.0),
        )
        req = _make_request(checkpoint=CheckpointLevel.L3)
        resp = manager.trigger(req)
        assert resp.veto_triggered is True
        assert len(resp.veto_details) > 0
        assert resp.status is ReviewStatus.PARTIAL
        assert resp.recommendation in (
            UpgradeRecommendation.PATCH,
            UpgradeRecommendation.MINOR,
            UpgradeRecommendation.MAJOR,
        )

    def test_cooldown_path(self, tmp_path: Path):
        """Second trigger for same skills should return QUEUED."""
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        queue = AsyncReviewQueue(cooldown_seconds=86400.0)
        manager = ReviewManager(telemetry=telemetry, queue=queue)
        req = _make_request(skills=["S05a"])
        resp1 = manager.trigger(req)
        assert resp1.status in (ReviewStatus.COMPLETED, ReviewStatus.PARTIAL)
        # Second trigger — cooldown should cause QUEUED
        resp2 = manager.trigger(req)
        assert resp2.status is ReviewStatus.QUEUED
        assert resp2.scores == {}

    def test_suspect_marking_on_veto(self, tmp_path: Path):
        """When veto fires, affected skills should be marked as suspects."""
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        marker = SuspectMarker()
        runner = _LowScoreRunner()
        manager = ReviewManager(
            telemetry=telemetry,
            checkpoint_runner=runner,
            suspect_marker=marker,
            queue=AsyncReviewQueue(cooldown_seconds=0.0),
        )
        req = _make_request(checkpoint=CheckpointLevel.L3, skills=["S05a"])
        resp = manager.trigger(req)
        if resp.veto_triggered:
            assert marker.is_suspect("S05a")
            assert len(resp.suspect_skills) > 0

    def test_telemetry_emitted(self, tmp_path: Path):
        """Review should emit telemetry events."""
        log_dir = tmp_path / "telem"
        telemetry = TelemetryBridge(log_dir=log_dir)
        queue = AsyncReviewQueue(cooldown_seconds=0.0)
        manager = ReviewManager(telemetry=telemetry, queue=queue)
        req = _make_request(skills=["S05a"])
        manager.trigger(req)
        events = telemetry.read_events(skill_id="S05a", event_type="review_completed")
        assert len(events) >= 1
        assert events[0].payload["checkpoint"] == req.checkpoint.value

    def test_l4_checkpoint(self, manager: ReviewManager):
        req = _make_request(checkpoint=CheckpointLevel.L4)
        resp = manager.trigger(req)
        assert resp.checkpoint is CheckpointLevel.L4
        assert len(resp.scores) == 5  # baseline dimensions

    def test_recommendation_major_on_v1(self, tmp_path: Path):
        """V1 (security) veto should produce MAJOR recommendation."""
        evaluator = VetoEvaluator()
        # We need a runner that produces D3 < 7.0 but others high
        runner = _SelectiveLowRunner(low_dimensions={"D3": 6.0})
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        manager = ReviewManager(
            telemetry=telemetry,
            checkpoint_runner=runner,
            queue=AsyncReviewQueue(cooldown_seconds=0.0),
        )
        req = _make_request(checkpoint=CheckpointLevel.L3)
        resp = manager.trigger(req)
        assert resp.veto_triggered is True
        assert resp.recommendation is UpgradeRecommendation.MAJOR


# ── Test Helpers ──────────────────────────────────────────────────────

class _LowScoreRunner(CheckpointRunner):
    """CheckpointRunner that always returns low scores (triggers vetoes)."""

    def run_checkpoint(self, level, skills):
        dimensions = self._dimensions_for_level(level)
        return {d: 4.0 for d in dimensions}


class _SelectiveLowRunner(CheckpointRunner):
    """CheckpointRunner that returns low scores for specific dimensions."""

    def __init__(self, low_dimensions: dict[str, float]):
        super().__init__(seed=42)
        self._low_dimensions = low_dimensions

    def run_checkpoint(self, level, skills):
        dimensions = self._dimensions_for_level(level)
        scores = {d: 9.0 for d in dimensions}
        for d, v in self._low_dimensions.items():
            if d in scores:
                scores[d] = v
        return scores


class TestReviewTraceIdPropagation:
    """Tests for trace_id propagation through ReviewManager."""

    def test_trigger_propagates_trace_id_to_telemetry(self):
        """ReviewManager.trigger should propagate trace_id to telemetry events."""
        from skillpool.review import ReviewManager
        from skillpool.telemetry import TelemetryBridge

        bridge = TelemetryBridge()
        captured_events = []
        bridge.register_hook(lambda e: captured_events.append(e))

        manager = ReviewManager(telemetry=bridge)

        request = ReviewTriggerRequest(
            trigger=ReviewTrigger.MANUAL,
            checkpoint=CheckpointLevel.L1,
            affected_skills=["S09"],
            trace_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        )
        manager.trigger(request)

        # Check that the emitted event carries the trace_id
        assert len(captured_events) > 0
        assert captured_events[-1].trace_id == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

    def test_trigger_without_trace_id(self):
        """ReviewManager.trigger should work with empty trace_id."""
        from skillpool.review import ReviewManager

        manager = ReviewManager()
        request = ReviewTriggerRequest(
            trigger=ReviewTrigger.MANUAL,
            checkpoint=CheckpointLevel.L1,
            affected_skills=["S09"],
        )
        resp = manager.trigger(request)
        assert resp.status == ReviewStatus.COMPLETED
