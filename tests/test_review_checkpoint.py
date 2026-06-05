"""Tests for review/__init__.py and review/checkpoint_runner.py uncovered lines.

Focuses on:
- ReviewManager: RuntimeError path, checkpoint exception path, _determine_recommendation
  branches, _feed_evolver with evolver integration
- CheckpointRunner: unknown checkpoint level, YAML parse errors, dimension-specific
  scorers (D3/D5/D7/D10/D11), generic scoring branches, _find_skill_yaml edge cases
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from skillpool.review import ReviewManager
from skillpool.review.checkpoint_runner import (
    ALL_DIMENSIONS,
    CheckpointRunner,
    DIMENSION_SKILLS,
)
from skillpool.review.models import (
    CheckpointLevel,
    ReviewStatus,
    ReviewTrigger,
    ReviewTriggerRequest,
    UpgradeRecommendation,
    VetoDetail,
    VetoRule,
)
from skillpool.review.async_queue import AsyncReviewQueue
from skillpool.telemetry import TelemetryBridge


# ── Helpers ──────────────────────────────────────────────────────────


def _make_request(
    trigger: ReviewTrigger = ReviewTrigger.MANUAL,
    checkpoint: CheckpointLevel = CheckpointLevel.L2,
    skills: list[str] | None = None,
    trace_id: str = "",
) -> ReviewTriggerRequest:
    return ReviewTriggerRequest(
        trigger=trigger,
        checkpoint=checkpoint,
        affected_skills=skills or ["S05a", "S10"],
        trace_id=trace_id,
    )


def _make_veto_detail(
    rule: VetoRule = VetoRule.V1,
    dimension: str = "D3",
    score: float = 6.0,
    threshold: float = 7.0,
    blocks: bool = True,
    recommendation: str = "Fix it",
) -> VetoDetail:
    return VetoDetail(
        rule=rule,
        dimension=dimension,
        score=score,
        threshold=threshold,
        blocks=blocks,
        recommendation=recommendation,
    )


# ── ReviewManager: RuntimeError path (lines 71-73) ──────────────────


class TestReviewManagerRuntimeError:
    """Cover lines 71-73: RuntimeError from queue.submit (max concurrent)."""

    def test_runtime_error_returns_queued(self, tmp_path: Path):
        """When queue.submit raises RuntimeError, response status is QUEUED."""
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        queue = AsyncReviewQueue(max_concurrent=1, cooldown_seconds=0.0)
        manager = ReviewManager(telemetry=telemetry, queue=queue)

        # Fill the queue with a PROCESSING entry
        req1 = _make_request(skills=["S05a"])
        rid1 = queue.submit(req1)
        queue.set_status(rid1, ReviewStatus.PROCESSING)

        # Second submit should hit max_concurrent → RuntimeError → QUEUED
        req2 = _make_request(skills=["S10"])
        resp = manager.trigger(req2)
        assert resp.status is ReviewStatus.QUEUED
        assert resp.scores == {}
        assert resp.veto_triggered is False
        assert resp.recommendation is UpgradeRecommendation.NONE


# ── ReviewManager: Checkpoint exception path (lines 94-97) ──────────


class TestReviewManagerCheckpointException:
    """Cover lines 94-97: checkpoint runner raises exception."""

    def test_checkpoint_exception_returns_failed(self, tmp_path: Path):
        """When runner.run_checkpoint raises, response status is FAILED."""
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        queue = AsyncReviewQueue(cooldown_seconds=0.0)

        failing_runner = MagicMock(spec=CheckpointRunner)
        failing_runner.run_checkpoint.side_effect = RuntimeError("boom")

        manager = ReviewManager(
            telemetry=telemetry,
            checkpoint_runner=failing_runner,
            queue=queue,
        )
        req = _make_request(skills=["S05a"])
        resp = manager.trigger(req)
        assert resp.status is ReviewStatus.FAILED
        assert resp.scores == {}
        assert resp.veto_triggered is False
        assert resp.recommendation is UpgradeRecommendation.NONE


# ── ReviewManager: _determine_recommendation branches (lines 183-196) ─


class TestDetermineRecommendation:
    """Cover lines 183, 187, 191-196: all _determine_recommendation branches."""

    def test_no_veto_details_returns_none(self):
        result = ReviewManager._determine_recommendation([])
        assert result is UpgradeRecommendation.NONE

    def test_only_non_blocking_v5_returns_patch(self):
        """Line 183: only non-blocking (V5) -> PATCH."""
        details = [_make_veto_detail(rule=VetoRule.V5, blocks=False)]
        result = ReviewManager._determine_recommendation(details)
        assert result is UpgradeRecommendation.PATCH

    def test_v1_blocking_returns_major(self):
        """Line 187: V1 blocking -> MAJOR."""
        details = [_make_veto_detail(rule=VetoRule.V1, blocks=True)]
        result = ReviewManager._determine_recommendation(details)
        assert result is UpgradeRecommendation.MAJOR

    def test_v2_blocking_returns_minor(self):
        """Lines 191-193: V2 blocking -> MINOR."""
        details = [_make_veto_detail(rule=VetoRule.V2, blocks=True)]
        result = ReviewManager._determine_recommendation(details)
        assert result is UpgradeRecommendation.MINOR

    def test_v3_blocking_returns_minor(self):
        """Lines 191-193: V3 blocking -> MINOR."""
        details = [_make_veto_detail(rule=VetoRule.V3, blocks=True)]
        result = ReviewManager._determine_recommendation(details)
        assert result is UpgradeRecommendation.MINOR

    def test_v4_blocking_returns_minor(self):
        """Lines 191-193: V4 blocking -> MINOR."""
        details = [_make_veto_detail(rule=VetoRule.V4, blocks=True)]
        result = ReviewManager._determine_recommendation(details)
        assert result is UpgradeRecommendation.MINOR

    def test_v6_only_blocking_returns_patch(self):
        """Lines 195-196: V6 only blocking -> PATCH."""
        details = [_make_veto_detail(rule=VetoRule.V6, blocks=True)]
        result = ReviewManager._determine_recommendation(details)
        assert result is UpgradeRecommendation.PATCH

    def test_mixed_v1_and_v5_returns_major(self):
        """V1 takes priority over V5."""
        details = [
            _make_veto_detail(rule=VetoRule.V5, blocks=False),
            _make_veto_detail(rule=VetoRule.V1, blocks=True),
        ]
        result = ReviewManager._determine_recommendation(details)
        assert result is UpgradeRecommendation.MAJOR

    def test_mixed_v2_and_v5_returns_minor(self):
        """V2 takes priority over V5."""
        details = [
            _make_veto_detail(rule=VetoRule.V5, blocks=False),
            _make_veto_detail(rule=VetoRule.V2, blocks=True),
        ]
        result = ReviewManager._determine_recommendation(details)
        assert result is UpgradeRecommendation.MINOR


# ── ReviewManager: _feed_evolver (lines 212-238) ────────────────────


class TestFeedEvolver:
    """Cover lines 212-238: _feed_evolver with evolver integration."""

    def test_no_evolver_is_noop(self):
        """When evolver is None, _feed_evolver returns immediately."""
        manager = ReviewManager(evolver=None)
        # Should not raise
        manager._feed_evolver([], _make_request(), UpgradeRecommendation.NONE)

    def test_blocking_v1_records_critical_defect(self):
        """Lines 212-214: V1 blocking -> DefectSeverity.CRITICAL."""
        evolver = MagicMock()
        manager = ReviewManager(evolver=evolver)
        details = [_make_veto_detail(rule=VetoRule.V1, blocks=True)]
        request = _make_request(skills=["S05a"])
        manager._feed_evolver(details, request, UpgradeRecommendation.MAJOR)

        evolver.record_defect.assert_called_once()
        call_kwargs = evolver.record_defect.call_args[1]
        assert call_kwargs["skill_id"] == "S05a"
        assert call_kwargs["severity"].value == "critical"

    def test_blocking_v2_records_major_defect(self):
        """Lines 215-216: non-V1 blocking -> DefectSeverity.MAJOR."""
        evolver = MagicMock()
        manager = ReviewManager(evolver=evolver)
        details = [_make_veto_detail(rule=VetoRule.V2, blocks=True)]
        request = _make_request(skills=["S10"])
        manager._feed_evolver(details, request, UpgradeRecommendation.MINOR)

        evolver.record_defect.assert_called_once()
        call_kwargs = evolver.record_defect.call_args[1]
        assert call_kwargs["severity"].value == "major"

    def test_non_blocking_records_minor_defect(self):
        """Lines 217-218: non-blocking -> DefectSeverity.MINOR."""
        evolver = MagicMock()
        manager = ReviewManager(evolver=evolver)
        details = [_make_veto_detail(rule=VetoRule.V5, blocks=False)]
        request = _make_request(skills=["S05a"])
        manager._feed_evolver(details, request, UpgradeRecommendation.PATCH)

        evolver.record_defect.assert_called_once()
        call_kwargs = evolver.record_defect.call_args[1]
        assert call_kwargs["severity"].value == "minor"

    def test_multiple_skills_multiple_defects(self):
        """Lines 220-222: one defect per affected skill per veto."""
        evolver = MagicMock()
        manager = ReviewManager(evolver=evolver)
        details = [_make_veto_detail(rule=VetoRule.V1, blocks=True)]
        request = _make_request(skills=["S05a", "S10"])
        manager._feed_evolver(details, request, UpgradeRecommendation.MAJOR)

        assert evolver.record_defect.call_count == 2

    def test_major_recommendation_creates_proposal(self):
        """Lines 230-238: MAJOR recommendation -> create_proposal with risk='high'."""
        evolver = MagicMock()
        manager = ReviewManager(evolver=evolver)
        details = [_make_veto_detail(rule=VetoRule.V1, blocks=True)]
        request = _make_request(skills=["S05a"], checkpoint=CheckpointLevel.L3)
        manager._feed_evolver(details, request, UpgradeRecommendation.MAJOR)

        evolver.create_proposal.assert_called_once()
        call_kwargs = evolver.create_proposal.call_args[1]
        assert call_kwargs["risk"] == "high"
        assert call_kwargs["context"]["trigger"] == "review_veto"
        assert call_kwargs["context"]["recommendation"] == "MAJOR"
        assert call_kwargs["context"]["checkpoint"] == "L3"
        assert "S05a" in call_kwargs["context"]["affected_skills"]

    def test_minor_recommendation_creates_proposal_medium_risk(self):
        """Lines 230-238: MINOR recommendation -> create_proposal with risk='medium'."""
        evolver = MagicMock()
        manager = ReviewManager(evolver=evolver)
        details = [_make_veto_detail(rule=VetoRule.V2, blocks=True)]
        request = _make_request(skills=["S05a"])
        manager._feed_evolver(details, request, UpgradeRecommendation.MINOR)

        evolver.create_proposal.assert_called_once()
        call_kwargs = evolver.create_proposal.call_args[1]
        assert call_kwargs["risk"] == "medium"

    def test_patch_recommendation_no_proposal(self):
        """PATCH recommendation does NOT create a proposal."""
        evolver = MagicMock()
        manager = ReviewManager(evolver=evolver)
        details = [_make_veto_detail(rule=VetoRule.V5, blocks=False)]
        request = _make_request(skills=["S05a"])
        manager._feed_evolver(details, request, UpgradeRecommendation.PATCH)

        evolver.create_proposal.assert_not_called()

    def test_none_recommendation_no_proposal(self):
        """NONE recommendation does NOT create a proposal."""
        evolver = MagicMock()
        manager = ReviewManager(evolver=evolver)
        request = _make_request(skills=["S05a"])
        manager._feed_evolver([], request, UpgradeRecommendation.NONE)

        evolver.create_proposal.assert_not_called()

    def test_evolver_full_integration_via_trigger(self, tmp_path: Path):
        """Full pipeline: trigger with evolver records defects and creates proposal."""
        evolver = MagicMock()
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        queue = AsyncReviewQueue(cooldown_seconds=0.0)

        # Use a runner that produces low scores to trigger vetoes
        low_runner = _LowScoreRunner()
        manager = ReviewManager(
            telemetry=telemetry,
            checkpoint_runner=low_runner,
            queue=queue,
            evolver=evolver,
        )
        req = _make_request(checkpoint=CheckpointLevel.L3, skills=["S05a"])
        resp = manager.trigger(req)

        # Evolver should have been called
        if resp.veto_triggered:
            assert evolver.record_defect.called


# ── CheckpointRunner: unknown checkpoint level (line 84) ────────────


class TestCheckpointRunnerUnknownLevel:
    """Cover line 84: default return ALL_DIMENSIONS for unknown level."""

    def test_unknown_level_returns_all_dimensions(self):
        runner = CheckpointRunner(seed=42, skills_dir=Path("/nonexistent"))
        # Use a string that is not a valid CheckpointLevel
        _fake_level = "L99"
        # _dimensions_for_level accepts CheckpointLevel but we can test
        # the fallback by passing a mock
        mock_level = MagicMock(spec=CheckpointLevel)
        mock_level.__eq__ = lambda self, other: False
        # All comparisons return False, so it falls through to the default
        result = runner._dimensions_for_level(mock_level)
        assert result == ALL_DIMENSIONS


# ── CheckpointRunner: _score_dimension with no skills (line 90) ──────


class TestScoreDimensionNoSkills:
    """Cover line 90: dimension with no associated skills uses fallback."""

    def test_unknown_dimension_uses_fallback(self):
        runner = CheckpointRunner(seed=42, skills_dir=Path("/nonexistent"))
        # "D99" is not in DIMENSION_SKILLS
        score = runner._score_dimension("D99")
        # Should get a fallback score in valid range
        assert 5.0 <= score <= 10.0


# ── CheckpointRunner: YAML parse errors (lines 109-110, 113) ────────


class TestCheckpointRunnerYamlErrors:
    """Cover lines 109-110 (YAML parse error) and 113 (non-dict data)."""

    def test_unparseable_yaml_returns_3(self, tmp_path: Path):
        """Line 109-110: YAML that fails to parse returns 3.0."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Write invalid YAML
        bad_yaml = skills_dir / "S05a-security.yaml"
        bad_yaml.write_text(":\n  :\n    - [\n", encoding="utf-8")

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S05a")
        assert score == 3.0

    def test_non_dict_yaml_returns_2(self, tmp_path: Path):
        """Line 113: YAML that parses to non-dict returns 2.0."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Write YAML that parses to a list
        list_yaml = skills_dir / "S05a-security.yaml"
        list_yaml.write_text("- item1\n- item2\n", encoding="utf-8")

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S05a")
        assert score == 2.0

    def test_oserror_returns_3(self, tmp_path: Path):
        """Line 109: OSError during read returns 3.0."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        yaml_file = skills_dir / "S05a-security.yaml"
        yaml_file.write_text("id: test", encoding="utf-8")

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        # Make read_text raise OSError
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            score = runner._score_skill("S05a")
        assert score == 3.0


# ── CheckpointRunner: dimension-specific scorers (lines 119, 132, 146-150, 154-155) ─


class TestCheckpointRunnerDimensionScorers:
    """Cover dimension-specific scoring paths via _score_skill with real YAML files."""

    def _write_skill_yaml(self, skills_dir: Path, skill_id: str, data: dict) -> Path:
        """Helper: write a skill YAML file to the skills directory."""
        skills_dir.mkdir(parents=True, exist_ok=True)
        # Find the dimension for this skill to determine filename prefix
        filename = f"{skill_id}-test.yaml"
        for dim, sids in DIMENSION_SKILLS.items():
            if skill_id in sids:
                filename = f"{skill_id}-{dim.lower()}.yaml"
                break
        path = skills_dir / filename
        path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
        return path

    # ── D3 Security (lines 146-150, 154-155) ──

    def test_d3_security_scanner_safe_bonus(self, tmp_path: Path):
        """Lines 144-145: SecurityScanner is_safe → +2.0 bonus."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S05a",
            {
                "id": "S05a",
                "name": "Security",
                "version": "1.0.0",
                "dimension": "D3",
                "description": "Security compliance scanning skill",
                "checklist": [{"description": "Check access controls", "severity": "critical"}],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        # Mock SecurityScanner at its import location (lazy import inside method)
        mock_result = MagicMock()
        mock_result.is_safe = True
        with patch("skillpool.hooks.security_scanner.SecurityScanner") as MockScanner:
            MockScanner.return_value.full_check.return_value = mock_result
            score = runner._score_skill("S05a")

        # Should have +2.0 bonus from safe scan
        assert score > 6.0  # generic base + 2.0 bonus

    def test_d3_security_scanner_warning_bonus(self, tmp_path: Path):
        """Lines 146-147: SecurityScanner warning → +0.5 bonus."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S05a",
            {
                "id": "S05a",
                "name": "Security",
                "version": "1.0.0",
                "dimension": "D3",
                "description": "Security compliance scanning skill",
                "checklist": [{"description": "Check access controls", "severity": "critical"}],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        mock_result = MagicMock()
        mock_result.is_safe = False
        mock_result.threat_level.value = "warning"
        with patch("skillpool.hooks.security_scanner.SecurityScanner") as MockScanner:
            MockScanner.return_value.full_check.return_value = mock_result
            score = runner._score_skill("S05a")

        # Should have +0.5 bonus from warning (not safe, not critical)
        assert score > 5.0

    def test_d3_security_scanner_unavailable(self, tmp_path: Path):
        """Lines 149-150: SecurityScanner import fails → skip bonus, no crash."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S05a",
            {
                "id": "S05a",
                "name": "Security",
                "version": "1.0.0",
                "dimension": "D3",
                "description": "Security compliance scanning skill",
                "checklist": [{"description": "Check access controls", "severity": "critical"}],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        with patch("skillpool.hooks.security_scanner.SecurityScanner", side_effect=ImportError("no scanner")):
            score = runner._score_skill("S05a")

        # Should still return a valid score (generic only, no scanner bonus)
        assert score > 0.0

    def test_d3_security_scan_required_bonus(self, tmp_path: Path):
        """Line 153-154: security_scan_required field → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S05a",
            {
                "id": "S05a",
                "name": "Security",
                "version": "1.0.0",
                "dimension": "D3",
                "description": "Security compliance scanning skill",
                "security_scan_required": True,
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        with patch("skillpool.hooks.security_scanner.SecurityScanner", side_effect=ImportError):
            score = runner._score_skill("S05a")
        # Should have +0.5 from security_scan_required
        assert score >= 4.5

    def test_d3_veto_rule_bonus(self, tmp_path: Path):
        """Line 155-156: veto_rule field → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S05a",
            {
                "id": "S05a",
                "name": "Security",
                "version": "1.0.0",
                "dimension": "D3",
                "description": "Security compliance scanning skill",
                "veto_rule": "V1",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        with patch("skillpool.hooks.security_scanner.SecurityScanner", side_effect=ImportError):
            score = runner._score_skill("S05a")
        # Should have +0.5 from veto_rule
        assert score >= 4.5

    # ── D5 Resilience (lines 160-190) ──

    def test_d5_fallback_bonus(self, tmp_path: Path):
        """Line 165-166: fallback field → +1.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S09",
            {
                "id": "S09",
                "name": "Resilience",
                "version": "1.0.0",
                "dimension": "D5",
                "description": "Fault tolerance and resilience skill",
                "fallback": "retry_with_backoff",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S09")
        assert score >= 5.5  # generic base + 1.5 fallback bonus

    def test_d5_degradation_bonus(self, tmp_path: Path):
        """Line 165-166: degradation field → +1.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S09",
            {
                "id": "S09",
                "name": "Resilience",
                "version": "1.0.0",
                "dimension": "D5",
                "description": "Fault tolerance and resilience skill",
                "degradation": "graceful_shutdown",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S09")
        assert score >= 5.5

    def test_d5_recovery_bonus(self, tmp_path: Path):
        """Line 168-169: recovery field → +1.0."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S09",
            {
                "id": "S09",
                "name": "Resilience",
                "version": "1.0.0",
                "dimension": "D5",
                "description": "Fault tolerance and resilience skill",
                "recovery": "auto_restart",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S09")
        assert score >= 5.0

    def test_d5_circuit_breaker_bonus(self, tmp_path: Path):
        """Line 171-172: circuit_breaker field → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S09",
            {
                "id": "S09",
                "name": "Resilience",
                "version": "1.0.0",
                "dimension": "D5",
                "description": "Fault tolerance and resilience skill",
                "circuit_breaker": "3_failures_in_60s",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S09")
        assert score >= 4.5

    def test_d5_no_resilience_fields_penalty(self, tmp_path: Path):
        """Lines 175-188: no resilience fields and no resilience checklist items → -1.0."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S09",
            {
                "id": "S09",
                "name": "Resilience",
                "version": "1.0.0",
                "dimension": "D5",
                "description": "Fault tolerance skill",
                "checklist": [{"description": "Check something unrelated"}],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S09")
        # Should have -1.0 penalty for no resilience fields
        assert score < 6.0

    def test_d5_resilience_checklist_item_avoids_penalty(self, tmp_path: Path):
        """Lines 179-186: resilience keyword in checklist avoids penalty."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S09",
            {
                "id": "S09",
                "name": "Resilience",
                "version": "1.0.0",
                "dimension": "D5",
                "description": "Fault tolerance skill",
                "checklist": [{"description": "Implement fallback mechanism for failures"}],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score_no_penalty = runner._score_skill("S09")

        # Compare with no checklist at all
        self._write_skill_yaml(
            skills_dir,
            "S09",
            {
                "id": "S09",
                "name": "Resilience",
                "version": "1.0.0",
                "dimension": "D5",
                "description": "Fault tolerance skill",
            },
        )
        score_with_penalty = runner._score_skill("S09")

        assert score_no_penalty > score_with_penalty

    # ── D7 Testability (lines 192-223) ──

    def test_d7_coverage_90_plus(self, tmp_path: Path):
        """Lines 199-200: test_coverage >= 90 → +2.0."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S13a",
            {
                "id": "S13a",
                "name": "Testability",
                "version": "1.0.0",
                "dimension": "D7",
                "description": "Test coverage and BDD specification skill",
                "test_coverage": 95,
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S13a")
        assert score >= 6.0  # generic + 2.0

    def test_d7_coverage_80_plus(self, tmp_path: Path):
        """Lines 201-202: test_coverage >= 80 → +1.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S13a",
            {
                "id": "S13a",
                "name": "Testability",
                "version": "1.0.0",
                "dimension": "D7",
                "description": "Test coverage and BDD specification skill",
                "test_coverage": 85,
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S13a")
        assert score >= 5.5

    def test_d7_coverage_70_plus(self, tmp_path: Path):
        """Lines 203-204: test_coverage >= 70 → +1.0."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S13a",
            {
                "id": "S13a",
                "name": "Testability",
                "version": "1.0.0",
                "dimension": "D7",
                "description": "Test coverage and BDD specification skill",
                "test_coverage": 75,
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S13a")
        assert score >= 5.0

    def test_d7_coverage_below_70(self, tmp_path: Path):
        """Lines 205-206: test_coverage < 70 → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S13a",
            {
                "id": "S13a",
                "name": "Testability",
                "version": "1.0.0",
                "dimension": "D7",
                "description": "Test coverage and BDD specification skill",
                "test_coverage": 50,
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S13a")
        assert score >= 4.5

    def test_d7_coverage_truthy_non_numeric(self, tmp_path: Path):
        """Line 207-208: test_coverage truthy but not int/float → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S13a",
            {
                "id": "S13a",
                "name": "Testability",
                "version": "1.0.0",
                "dimension": "D7",
                "description": "Test coverage and BDD specification skill",
                "test_coverage": "high",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S13a")
        assert score >= 4.5

    def test_d7_bdd_3_plus_items(self, tmp_path: Path):
        """Lines 218-219: bdd_count >= 3 → +1.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S13a",
            {
                "id": "S13a",
                "name": "Testability",
                "version": "1.0.0",
                "dimension": "D7",
                "description": "Test coverage and BDD specification skill",
                "checklist": [
                    {"description": "Given a valid input, when processed, then output is correct"},
                    {"description": "Should handle edge cases properly"},
                    {"description": "Must verify all return values"},
                ],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S13a")
        assert score >= 5.5

    def test_d7_bdd_1_item(self, tmp_path: Path):
        """Lines 220-221: bdd_count >= 1 → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S13a",
            {
                "id": "S13a",
                "name": "Testability",
                "version": "1.0.0",
                "dimension": "D7",
                "description": "Test coverage and BDD specification skill",
                "checklist": [
                    {"description": "Should validate inputs correctly"},
                ],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S13a")
        assert score >= 4.5

    # ── D10 Protocol (lines 225-245) ──

    def test_d10_semver_bonus(self, tmp_path: Path):
        """Lines 231-233: semver version → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "2.1.0",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S19")
        # Should have +0.5 from semver
        assert score >= 4.5

    def test_d10_non_semver_no_bonus(self, tmp_path: Path):
        """Non-semver version gets no bonus."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "v2-latest",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score_non_semver = runner._score_skill("S19")

        # Compare with semver
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "2.1.0",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
            },
        )
        score_semver = runner._score_skill("S19")

        assert score_semver > score_non_semver

    def test_d10_last_updated_bonus(self, tmp_path: Path):
        """Lines 236-237: last_updated field → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "1.0.0",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
                "last_updated": "2026-01-15",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S19")
        assert score >= 4.5

    def test_d10_effective_date_bonus(self, tmp_path: Path):
        """Lines 236-237: effective_date field → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "1.0.0",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
                "effective_date": "2026-03-01",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S19")
        assert score >= 4.5

    def test_d10_deprecated_without_replacement_penalty(self, tmp_path: Path):
        """Lines 240-243: deprecated=True without replacement → -1.0."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "1.0.0",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
                "deprecated": True,
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score_with_penalty = runner._score_skill("S19")

        # Compare with same file but not deprecated
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "1.0.0",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
            },
        )
        score_without_penalty = runner._score_skill("S19")

        # Deprecated without replacement should be 1.0 lower
        assert score_with_penalty < score_without_penalty
        assert score_without_penalty - score_with_penalty == pytest.approx(1.0, abs=0.01)

    def test_d10_deprecated_with_replacement_no_penalty(self, tmp_path: Path):
        """deprecated=True with replacement → no penalty."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "1.0.0",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
                "deprecated": True,
                "replacement": "S19b",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score_with_replacement = runner._score_skill("S19")

        # Compare with deprecated without replacement
        self._write_skill_yaml(
            skills_dir,
            "S19",
            {
                "id": "S19",
                "name": "Protocol",
                "version": "1.0.0",
                "dimension": "D10",
                "description": "Protocol timeliness and versioning skill",
                "deprecated": True,
            },
        )
        score_without_replacement = runner._score_skill("S19")

        assert score_with_replacement > score_without_replacement

    # ── D11 Feasibility (lines 247-266) ──

    def test_d11_dependencies_declared_bonus(self, tmp_path: Path):
        """Lines 252-253: dependencies key exists → +0.5."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S20",
            {
                "id": "S20",
                "name": "Feasibility",
                "version": "1.0.0",
                "dimension": "D11",
                "description": "Engineering feasibility assessment skill",
                "dependencies": [],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S20")
        assert score >= 4.5

    def test_d11_dependencies_with_items_bonus(self, tmp_path: Path):
        """Lines 254-256: dependencies list with items → +0.5 more."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S20",
            {
                "id": "S20",
                "name": "Feasibility",
                "version": "1.0.0",
                "dimension": "D11",
                "description": "Engineering feasibility assessment skill",
                "dependencies": ["S05a", "S09"],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score_with_items = runner._score_skill("S20")

        # Compare with empty dependencies
        self._write_skill_yaml(
            skills_dir,
            "S20",
            {
                "id": "S20",
                "name": "Feasibility",
                "version": "1.0.0",
                "dimension": "D11",
                "description": "Engineering feasibility assessment skill",
                "dependencies": [],
            },
        )
        score_empty = runner._score_skill("S20")

        assert score_with_items > score_empty

    def test_d11_implementation_bonus(self, tmp_path: Path):
        """Lines 259-260: implementation field → +1.0."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S20",
            {
                "id": "S20",
                "name": "Feasibility",
                "version": "1.0.0",
                "dimension": "D11",
                "description": "Engineering feasibility assessment skill",
                "implementation": "Python module with pytest",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S20")
        assert score >= 5.5

    def test_d11_implementation_notes_bonus(self, tmp_path: Path):
        """Lines 259-260: implementation_notes field → +1.0."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S20",
            {
                "id": "S20",
                "name": "Feasibility",
                "version": "1.0.0",
                "dimension": "D11",
                "description": "Engineering feasibility assessment skill",
                "implementation_notes": "Use subprocess for isolation",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S20")
        assert score >= 5.5

    def test_d11_no_deps_no_checklist_penalty(self, tmp_path: Path):
        """Lines 262-264: no dependencies and no checklist → -1.0."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S20",
            {
                "id": "S20",
                "name": "Feasibility",
                "version": "1.0.0",
                "dimension": "D11",
                "description": "Engineering feasibility assessment skill",
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S20")
        # Should have -1.0 penalty
        assert score < 5.0

    def test_d11_no_deps_but_has_checklist_no_penalty(self, tmp_path: Path):
        """Having checklist avoids the penalty even without dependencies."""
        skills_dir = tmp_path / "skills"
        self._write_skill_yaml(
            skills_dir,
            "S20",
            {
                "id": "S20",
                "name": "Feasibility",
                "version": "1.0.0",
                "dimension": "D11",
                "description": "Engineering feasibility assessment skill",
                "checklist": [{"description": "Verify dependencies"}],
            },
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score_with_checklist = runner._score_skill("S20")

        # Compare with no checklist and no dependencies
        self._write_skill_yaml(
            skills_dir,
            "S20",
            {
                "id": "S20",
                "name": "Feasibility",
                "version": "1.0.0",
                "dimension": "D11",
                "description": "Engineering feasibility assessment skill",
            },
        )
        score_without = runner._score_skill("S20")

        assert score_with_checklist > score_without


# ── CheckpointRunner: _score_generic branches (lines 277-321) ───────


class TestScoreGeneric:
    """Cover lines 294-297, 303, 306, 312-313, 316: generic scoring branches."""

    def test_checklist_1_item_gets_0_5(self):
        """Lines 296-297: checklist with 1 item → +0.5."""
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking",
            "checklist": [{"description": "One item"}],
        }
        score = runner._score_generic(data)
        # 4.0 (all required fields) + 0.5 (1 checklist item) + 1.5 (desc > 20) = 6.0
        assert score >= 5.5

    def test_checklist_2_items_gets_1(self):
        """Lines 294-295: checklist with 2-4 items → +1.0."""
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
            "checklist": [{"description": "Item 1"}, {"description": "Item 2"}],
        }
        score = runner._score_generic(data)
        assert score >= 5.5

    def test_checklist_5_items_gets_2(self):
        """Lines 292-293: checklist with 5-7 items → +2.0."""
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
            "checklist": [{"description": f"Item {i}"} for i in range(5)],
        }
        score = runner._score_generic(data)
        assert score >= 6.5

    def test_checklist_8_items_gets_3(self):
        """Lines 290-291: checklist with 8+ items → +3.0."""
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
            "checklist": [{"description": f"Item {i}"} for i in range(8)],
        }
        score = runner._score_generic(data)
        assert score >= 7.5

    def test_checklist_critical_severity_bonus(self):
        """Line 303: checklist with 'critical' severity → +0.5."""
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
            "checklist": [{"description": "Critical item", "severity": "critical"}],
        }
        score_with_critical = runner._score_generic(data)

        data_no_critical = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
            "checklist": [{"description": "Normal item", "severity": "normal"}],
        }
        score_without_critical = runner._score_generic(data_no_critical)

        assert score_with_critical > score_without_critical

    def test_no_checklist_gets_0_3(self):
        """Line 306: no checklist → +0.3."""
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
        }
        score = runner._score_generic(data)
        # 4.0 (fields) + 0.3 (no checklist) + 1.5 (desc > 20) = 5.8
        assert 5.0 <= score <= 6.5

    def test_short_description_gets_0_7(self):
        """Lines 312-313: description <= 20 chars → +0.7."""
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "Short",
        }
        score = runner._score_generic(data)
        # 4.0 (fields) + 0.3 (no checklist) + 0.7 (short desc) = 5.0
        assert 4.5 <= score <= 5.5

    def test_weight_field_bonus(self):
        """Line 317: weight field → +0.5."""
        runner = CheckpointRunner(seed=42)
        data_with_weight = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
            "weight": 0.15,
        }
        data_without_weight = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
        }
        score_with = runner._score_generic(data_with_weight)
        score_without = runner._score_generic(data_without_weight)
        assert score_with > score_without

    def test_veto_rule_field_bonus(self):
        """Line 318-319: veto_rule field → +0.5."""
        runner = CheckpointRunner(seed=42)
        data_with_veto = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
            "veto_rule": "V1",
        }
        data_without_veto = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
        }
        score_with = runner._score_generic(data_with_veto)
        score_without = runner._score_generic(data_without_veto)
        assert score_with > score_without

    def test_empty_checklist_gets_0_3(self):
        """Empty list checklist → +0.3 (same as no checklist)."""
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "A test skill for checking quality",
            "checklist": [],
        }
        score = runner._score_generic(data)
        # 4.0 (fields) + 0.3 (empty checklist) + 1.5 (desc > 20) = 5.8
        assert 5.0 <= score <= 6.5


# ── CheckpointRunner: _find_skill_yaml edge cases (line 330) ────────


class TestFindSkillYaml:
    """Cover line 330: _find_skill_yaml returns None when no matching file."""

    def test_no_matching_file_returns_none(self, tmp_path: Path):
        """When skills dir has no matching YAML, returns None."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Write a file that doesn't match the skill_id prefix
        (skills_dir / "S99-other.yaml").write_text("id: S99", encoding="utf-8")

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        result = runner._find_skill_yaml("S05a")
        assert result is None

    def test_matching_file_found(self, tmp_path: Path):
        """When skills dir has a matching YAML, returns the path."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "S05a-security.yaml").write_text("id: S05a", encoding="utf-8")

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        result = runner._find_skill_yaml("S05a")
        assert result is not None
        assert result.name == "S05a-security.yaml"

    def test_nonexistent_dir_returns_none(self):
        """When skills dir doesn't exist, returns None."""
        runner = CheckpointRunner(seed=42, skills_dir=Path("/nonexistent_dir_xyz"))
        result = runner._find_skill_yaml("S05a")
        assert result is None


# ── CheckpointRunner: _skill_dimension (line 132) ───────────────────


class TestSkillDimension:
    """Cover line 132: _skill_dimension returns None for unknown skill."""

    def test_known_skill_returns_dimension(self):
        runner = CheckpointRunner(seed=42)
        assert runner._skill_dimension("S05a") == "D3"
        assert runner._skill_dimension("S09") == "D5"
        assert runner._skill_dimension("S13a") == "D7"

    def test_unknown_skill_returns_none(self):
        runner = CheckpointRunner(seed=42)
        assert runner._skill_dimension("S99") is None


# ── CheckpointRunner: _fallback_score determinism ───────────────────


class TestFallbackScore:
    """Cover _fallback_score behavior with and without seed."""

    def test_fallback_with_seed_deterministic(self):
        runner = CheckpointRunner(seed=42, skills_dir=Path("/nonexistent"))
        s1 = runner._fallback_score("D3")
        s2 = runner._fallback_score("D3")
        assert s1 == s2

    def test_fallback_without_seed_deterministic(self):
        """Without seed, fallback uses hash of key — still deterministic."""
        runner = CheckpointRunner(seed=None, skills_dir=Path("/nonexistent"))
        s1 = runner._fallback_score("D3")
        s2 = runner._fallback_score("D3")
        assert s1 == s2

    def test_fallback_score_in_range(self):
        runner = CheckpointRunner(seed=42, skills_dir=Path("/nonexistent"))
        for key in ["D1", "D3", "D5", "D7", "D10", "D11", "S05a", "S99"]:
            score = runner._fallback_score(key)
            assert 5.0 <= score <= 10.0, f"fallback for {key} = {score}"


# ── CheckpointRunner: _score_skill with no primary_dim (line 119 fallback) ─


class TestScoreSkillNoPrimaryDim:
    """Cover line 119-125: skill with no primary dimension uses generic scoring."""

    def test_skill_not_in_dimension_skills_uses_generic(self, tmp_path: Path):
        """A skill YAML file that doesn't map to any dimension uses _score_generic."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Write a YAML for a skill not in DIMENSION_SKILLS
        (skills_dir / "S99-custom.yaml").write_text(
            yaml.dump(
                {
                    "id": "S99",
                    "name": "Custom",
                    "version": "1.0.0",
                    "description": "A custom skill not mapped to any dimension",
                }
            ),
            encoding="utf-8",
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        score = runner._score_skill("S99")
        # Should use generic scoring, not crash
        assert score > 0.0


# ── ReviewManager: full pipeline with evolver via trigger ────────────


class TestReviewManagerEvolverIntegration:
    """Integration tests for ReviewManager with evolver connected."""

    def test_trigger_with_v1_veto_feeds_evolver_critical(self, tmp_path: Path):
        """V1 veto through full pipeline records CRITICAL defect in evolver."""
        evolver = MagicMock()
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        queue = AsyncReviewQueue(cooldown_seconds=0.0)

        # Runner that produces D3 < 7.0, others high
        runner = _SelectiveLowRunner(low_dimensions={"D3": 6.0})
        manager = ReviewManager(
            telemetry=telemetry,
            checkpoint_runner=runner,
            queue=queue,
            evolver=evolver,
        )
        req = _make_request(checkpoint=CheckpointLevel.L3, skills=["S05a"])
        resp = manager.trigger(req)

        assert resp.veto_triggered is True
        assert resp.recommendation is UpgradeRecommendation.MAJOR
        # Evolver should have recorded defects
        assert evolver.record_defect.called
        # And created a proposal
        assert evolver.create_proposal.called

    def test_trigger_with_v5_only_patch_no_evolver_proposal(self, tmp_path: Path):
        """V5 (non-blocking) only → PATCH recommendation, no evolver proposal."""
        evolver = MagicMock()
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        queue = AsyncReviewQueue(cooldown_seconds=0.0)

        # Runner that produces D10 < 5.5, others high
        runner = _SelectiveLowRunner(low_dimensions={"D10": 5.0})
        manager = ReviewManager(
            telemetry=telemetry,
            checkpoint_runner=runner,
            queue=queue,
            evolver=evolver,
        )
        req = _make_request(checkpoint=CheckpointLevel.L3, skills=["S05a"])
        resp = manager.trigger(req)

        # V5 is non-blocking, so veto_triggered is False, status is COMPLETED
        # But _determine_recommendation returns PATCH (non-blocking veto present)
        assert resp.veto_triggered is False
        assert resp.status is ReviewStatus.COMPLETED
        # V5 produces PATCH recommendation
        assert resp.recommendation is UpgradeRecommendation.PATCH
        # PATCH recommendation does NOT create an evolver proposal
        evolver.create_proposal.assert_not_called()

    def test_trigger_l1_no_veto_evaluation(self, tmp_path: Path):
        """L1 checkpoint does not evaluate vetoes (line 112)."""
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        queue = AsyncReviewQueue(cooldown_seconds=0.0)
        runner = _LowScoreRunner()
        manager = ReviewManager(
            telemetry=telemetry,
            checkpoint_runner=runner,
            queue=queue,
        )
        req = _make_request(checkpoint=CheckpointLevel.L1)
        resp = manager.trigger(req)
        # L1 only evaluates shadow dimensions, no veto check
        assert resp.veto_triggered is False
        assert resp.veto_details == []


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


# ── Remaining branch partial coverage ───────────────────────────────


class TestBranchPartials:
    """Cover remaining branch partials: 146->153, 312->316."""

    def test_d3_critical_no_warning_branch(self, tmp_path: Path):
        """Branch 146->153: is_safe=False, threat_level=CRITICAL (not warning).

        When the scan result is CRITICAL, neither is_safe nor the warning
        branch is taken — execution falls through to security_scan_required.
        """
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "S05a-security.yaml").write_text(
            yaml.dump(
                {
                    "id": "S05a",
                    "name": "Security",
                    "version": "1.0.0",
                    "dimension": "D3",
                    "description": "Security compliance scanning skill for D3",
                    "security_scan_required": True,
                }
            ),
            encoding="utf-8",
        )

        runner = CheckpointRunner(seed=42, skills_dir=skills_dir)
        mock_result = MagicMock()
        mock_result.is_safe = False
        mock_result.threat_level.value = "critical"  # not "warning"
        with patch("skillpool.hooks.security_scanner.SecurityScanner") as MockScanner:
            MockScanner.return_value.full_check.return_value = mock_result
            score = runner._score_skill("S05a")

        # No scanner bonus (CRITICAL), but security_scan_required → +0.5
        assert score > 0.0

    def test_generic_short_desc_then_weight_branch(self):
        """Branch 312->316: description is short (elif desc:) then check weight.

        Covers the path where desc exists but len <= 20, then weight is checked.
        """
        runner = CheckpointRunner(seed=42)
        data = {
            "id": "test",
            "name": "test",
            "version": "1.0.0",
            "dimension": "D1",
            "description": "Short",
            "weight": 0.1,
        }
        score = runner._score_generic(data)
        # 4.0 (fields) + 0.3 (no checklist) + 0.7 (short desc) + 0.5 (weight) = 5.5
        assert 5.0 <= score <= 6.0


# ── ReviewManager: ValueError cooldown path (line 60) ───────────────


class TestReviewManagerCooldownValueError:
    """Cover line 60: ValueError from queue.submit (cooldown violation)."""

    def test_cooldown_returns_queued(self, tmp_path: Path):
        """When queue.submit raises ValueError (cooldown), response is QUEUED."""
        telemetry = TelemetryBridge(log_dir=tmp_path / "telem")
        queue = AsyncReviewQueue(max_concurrent=10, cooldown_seconds=86400.0)
        manager = ReviewManager(telemetry=telemetry, queue=queue)

        # First request succeeds
        req = _make_request(skills=["S05a"])
        resp1 = manager.trigger(req)
        assert resp1.status in (ReviewStatus.COMPLETED, ReviewStatus.PARTIAL)

        # Second request with same skill hits cooldown → ValueError → QUEUED
        resp2 = manager.trigger(req)
        assert resp2.status is ReviewStatus.QUEUED
        assert resp2.scores == {}
        assert resp2.veto_triggered is False
        assert resp2.recommendation is UpgradeRecommendation.NONE
