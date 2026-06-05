"""Tests for GainTracker — four-dimension scoring and gain quantification."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from skillpool.gain import (
    GainTracker,
    GainScores,
    SkillExecution,
    GainReport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path):
    """Create a temporary data directory for GainTracker."""
    d = tmp_path / "gain"
    d.mkdir()
    return d


@pytest.fixture
def tracker(data_dir):
    """Return a GainTracker pointed at the temp data_dir."""
    return GainTracker(data_dir=data_dir)


# ---------------------------------------------------------------------------
# GainScores model
# ---------------------------------------------------------------------------


class TestGainScores:
    """Test the GainScores Pydantic model."""

    def test_defaults(self):
        scores = GainScores()
        assert scores.effectiveness == 0.0
        assert scores.efficiency == 0.0
        assert scores.quality == 0.0
        assert scores.gain == 0.0

    def test_valid_scores(self):
        scores = GainScores(effectiveness=8.5, efficiency=7.0, quality=9.0, gain=1.5)
        assert scores.effectiveness == 8.5
        assert scores.efficiency == 7.0
        assert scores.quality == 9.0
        assert scores.gain == 1.5

    def test_score_bounds(self):
        # effectiveness, efficiency, quality: 0-10
        with pytest.raises(Exception):
            GainScores(effectiveness=-1.0)
        with pytest.raises(Exception):
            GainScores(effectiveness=11.0)
        with pytest.raises(Exception):
            GainScores(efficiency=-0.1)
        with pytest.raises(Exception):
            GainScores(quality=15.0)
        # gain: -10 to +10
        with pytest.raises(Exception):
            GainScores(gain=-11.0)
        with pytest.raises(Exception):
            GainScores(gain=15.0)

    def test_score_at_boundaries(self):
        s = GainScores(effectiveness=0.0, efficiency=10.0, quality=0.0, gain=-10.0)
        assert s.effectiveness == 0.0
        assert s.efficiency == 10.0
        assert s.gain == -10.0
        s2 = GainScores(effectiveness=10.0, efficiency=0.0, quality=10.0, gain=10.0)
        assert s2.effectiveness == 10.0
        assert s2.gain == 10.0


# ---------------------------------------------------------------------------
# SkillExecution model
# ---------------------------------------------------------------------------


class TestSkillExecution:
    """Test the SkillExecution Pydantic model."""

    def test_defaults(self):
        ex = SkillExecution(skill_ids=["test"])
        assert ex.execution_id == ""
        assert ex.skill_ids == ["test"]
        assert ex.timestamp == ""
        assert ex.intent == ""
        assert isinstance(ex.scores, GainScores)
        assert ex.duration_ms == 0
        assert ex.token_count == 0
        assert ex.success is True
        assert ex.source == "implicit"

    def test_full_construction(self):
        scores = GainScores(effectiveness=8.0)
        ex = SkillExecution(
            execution_id="exec-001",
            skill_ids=["review", "security"],
            timestamp="2026-01-01T00:00:00Z",
            intent="code review",
            scores=scores,
            duration_ms=5000,
            token_count=1000,
            success=True,
            source="explicit",
        )
        assert ex.execution_id == "exec-001"
        assert ex.skill_ids == ["review", "security"]
        assert ex.timestamp == "2026-01-01T00:00:00Z"
        assert ex.intent == "code review"
        assert ex.scores.effectiveness == 8.0
        assert ex.duration_ms == 5000
        assert ex.token_count == 1000
        assert ex.success is True
        assert ex.source == "explicit"

    def test_skill_ids_required(self):
        """skill_ids is a required field."""
        with pytest.raises(Exception):
            SkillExecution()


# ---------------------------------------------------------------------------
# GainReport model
# ---------------------------------------------------------------------------


class TestGainReport:
    """Test the GainReport Pydantic model."""

    def test_defaults(self):
        report = GainReport(skill_id="test")
        assert report.skill_id == "test"
        assert report.execution_count == 0
        assert report.avg_effectiveness == 0.0
        assert report.avg_efficiency == 0.0
        assert report.avg_quality == 0.0
        assert report.avg_gain == 0.0
        assert report.combined_score == 0.0

    def test_with_values(self):
        report = GainReport(
            skill_id="review",
            execution_count=10,
            avg_effectiveness=8.5,
            avg_efficiency=7.0,
            avg_quality=9.0,
            avg_gain=1.5,
            combined_score=7.5,
        )
        assert report.skill_id == "review"
        assert report.execution_count == 10
        assert report.avg_effectiveness == 8.5
        assert report.combined_score == 7.5


# ---------------------------------------------------------------------------
# GainTracker — constructor
# ---------------------------------------------------------------------------


class TestGainTrackerInit:
    """Test GainTracker constructor."""

    def test_default_data_dir(self):
        """When no data_dir provided, uses get_data_dir() / 'gain'."""
        with patch("skillpool.gain.get_data_dir", return_value=Path("/fake")):
            t = GainTracker()
            assert t.data_dir == Path("/fake/gain")

    def test_custom_data_dir(self, tmp_path):
        t = GainTracker(data_dir=tmp_path)
        assert t.data_dir == tmp_path

    def test_creates_data_dir(self, tmp_path):
        """If data_dir doesn't exist, it's created."""
        new_dir = tmp_path / "new_gain"
        assert not new_dir.exists()
        _t = GainTracker(data_dir=new_dir)
        assert new_dir.exists()

    def test_initial_state(self, tracker):
        assert tracker._executions == []
        assert tracker._loaded is False


# ---------------------------------------------------------------------------
# GainTracker — record
# ---------------------------------------------------------------------------


class TestRecord:
    """Test recording skill executions."""

    def test_record_basic(self, tracker, data_dir):
        ex = SkillExecution(
            skill_ids=["review"],
            scores=GainScores(effectiveness=8.0),
        )
        tracker.record(ex)

        assert len(tracker._executions) == 1
        assert tracker._executions[0].skill_ids == ["review"]
        assert tracker._executions[0].scores.effectiveness == 8.0

        # Check persistence
        log_file = data_dir / "executions.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["skill_ids"] == ["review"]

    def test_record_auto_timestamp(self, tracker, data_dir):
        """If timestamp is empty, it's auto-generated."""
        with patch("skillpool.gain.utc_now") as mock_now:
            from datetime import datetime, timezone

            mock_now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

            ex = SkillExecution(skill_ids=["test"])
            tracker.record(ex)

            assert ex.timestamp == "2026-01-01T12:00:00+00:00"

    def test_record_auto_execution_id(self, tracker, data_dir):
        """If execution_id is empty, it's auto-generated."""
        ex1 = SkillExecution(skill_ids=["test"])
        ex2 = SkillExecution(skill_ids=["test"])
        tracker.record(ex1)
        tracker.record(ex2)

        assert ex1.execution_id == "exec-000001"
        assert ex2.execution_id == "exec-000002"

    def test_record_preserves_existing_timestamp(self, tracker, data_dir):
        """If timestamp is already set, it's not overwritten."""
        ex = SkillExecution(skill_ids=["test"], timestamp="2025-01-01T00:00:00Z")
        tracker.record(ex)
        assert ex.timestamp == "2025-01-01T00:00:00Z"

    def test_record_preserves_existing_execution_id(self, tracker, data_dir):
        """If execution_id is already set, it's not overwritten."""
        ex = SkillExecution(skill_ids=["test"], execution_id="custom-123")
        tracker.record(ex)
        assert ex.execution_id == "custom-123"

    def test_record_appends_to_existing_file(self, tracker, data_dir):
        """Multiple records append to the same file."""
        tracker.record(SkillExecution(skill_ids=["a"]))
        tracker.record(SkillExecution(skill_ids=["b"]))
        tracker.record(SkillExecution(skill_ids=["c"]))

        log_file = data_dir / "executions.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_record_triggers_lazy_load(self, tracker, data_dir):
        """Recording triggers _ensure_loaded if not already loaded."""
        # Pre-populate a log file
        log_file = data_dir / "executions.jsonl"
        log_file.write_text('{"skill_ids": ["pre"], "timestamp": "2025-01-01T00:00:00Z"}\n')

        # Record a new execution
        tracker.record(SkillExecution(skill_ids=["new"]))

        # Should have loaded the pre-existing record plus the new one
        assert len(tracker._executions) == 2
        assert tracker._loaded is True


# ---------------------------------------------------------------------------
# GainTracker — record_implicit
# ---------------------------------------------------------------------------


class TestRecordImplicit:
    """Test implicit (auto-collected) execution recording."""

    def test_record_implicit_success(self, tracker):
        tracker.record_implicit(
            skill_ids=["review"],
            intent="code review",
            duration_ms=10000,
            token_count=500,
            success=True,
        )

        assert len(tracker._executions) == 1
        ex = tracker._executions[0]
        assert ex.skill_ids == ["review"]
        assert ex.intent == "code review"
        assert ex.duration_ms == 10000
        assert ex.token_count == 500
        assert ex.success is True
        assert ex.source == "implicit"
        # Success → effectiveness 7.0
        assert ex.scores.effectiveness == 7.0
        # <30s → efficiency 10.0
        assert ex.scores.efficiency == 10.0
        # No quality data → 5.0
        assert ex.scores.quality == 5.0
        # Unknown gain → 0.0
        assert ex.scores.gain == 0.0

    def test_record_implicit_failure(self, tracker):
        tracker.record_implicit(
            skill_ids=["review"],
            success=False,
        )

        ex = tracker._executions[0]
        assert ex.success is False
        # Failure → effectiveness 3.0
        assert ex.scores.effectiveness == 3.0

    def test_efficiency_scoring_tiers(self, tracker):
        """Test efficiency score based on duration tiers."""
        # <30s → 10.0
        tracker.record_implicit(skill_ids=["a"], duration_ms=29_000)
        assert tracker._executions[-1].scores.efficiency == 10.0

        # <2min → 8.0
        tracker.record_implicit(skill_ids=["b"], duration_ms=119_000)
        assert tracker._executions[-1].scores.efficiency == 8.0

        # <5min → 5.0
        tracker.record_implicit(skill_ids=["c"], duration_ms=299_000)
        assert tracker._executions[-1].scores.efficiency == 5.0

        # >=5min → 3.0
        tracker.record_implicit(skill_ids=["d"], duration_ms=300_000)
        assert tracker._executions[-1].scores.efficiency == 3.0

        tracker.record_implicit(skill_ids=["e"], duration_ms=600_000)
        assert tracker._executions[-1].scores.efficiency == 3.0

    def test_record_implicit_persists(self, tracker, data_dir):
        tracker.record_implicit(skill_ids=["test"])

        log_file = data_dir / "executions.jsonl"
        assert log_file.exists()
        data = json.loads(log_file.read_text().strip())
        assert data["skill_ids"] == ["test"]
        assert data["source"] == "implicit"


# ---------------------------------------------------------------------------
# GainTracker — _ensure_loaded
# ---------------------------------------------------------------------------


class TestEnsureLoaded:
    """Test lazy loading of execution history."""

    def test_no_file_no_load(self, tracker, data_dir):
        """If log file doesn't exist, loads empty list."""
        tracker._ensure_loaded()
        assert tracker._executions == []
        assert tracker._loaded is True

    def test_loads_existing_file(self, tracker, data_dir):
        """Loads records from existing log file."""
        log_file = data_dir / "executions.jsonl"
        log_file.write_text(
            '{"skill_ids": ["a"], "timestamp": "2025-01-01T00:00:00Z"}\n'
            '{"skill_ids": ["b"], "timestamp": "2025-01-02T00:00:00Z"}\n'
        )

        tracker._ensure_loaded()
        assert len(tracker._executions) == 2
        assert tracker._executions[0].skill_ids == ["a"]
        assert tracker._executions[1].skill_ids == ["b"]

    def test_skips_empty_lines(self, tracker, data_dir):
        """Empty lines in log file are skipped."""
        log_file = data_dir / "executions.jsonl"
        log_file.write_text('{"skill_ids": ["a"]}\n\n{"skill_ids": ["b"]}\n\n')

        tracker._ensure_loaded()
        assert len(tracker._executions) == 2

    def test_skips_whitespace_lines(self, tracker, data_dir):
        """Whitespace-only lines are skipped."""
        log_file = data_dir / "executions.jsonl"
        log_file.write_text('{"skill_ids": ["a"]}\n   \n{"skill_ids": ["b"]}\n')

        tracker._ensure_loaded()
        assert len(tracker._executions) == 2

    def test_skips_invalid_json(self, tracker, data_dir):
        """Invalid JSON lines are skipped with a warning."""
        log_file = data_dir / "executions.jsonl"
        log_file.write_text('{"skill_ids": ["a"]}\n{invalid json}\n{"skill_ids": ["b"]}\n')

        tracker._ensure_loaded()
        # Should load valid lines, skip invalid
        assert len(tracker._executions) == 2

    def test_only_loads_once(self, tracker, data_dir):
        """Subsequent calls don't re-load from disk."""
        log_file = data_dir / "executions.jsonl"
        log_file.write_text('{"skill_ids": ["a"]}\n')

        tracker._ensure_loaded()
        assert len(tracker._executions) == 1

        # Add more to file
        with open(log_file, "a") as f:
            f.write('{"skill_ids": ["b"]}\n')

        # Call again - should not re-load
        tracker._ensure_loaded()
        assert len(tracker._executions) == 1  # Still 1, not 2


# ---------------------------------------------------------------------------
# GainTracker — report
# ---------------------------------------------------------------------------


class TestReport:
    """Test generating aggregated gain reports."""

    def test_report_no_executions(self, tracker):
        """When no executions exist, returns empty report."""
        report = tracker.report("nonexistent")
        assert isinstance(report, GainReport)
        assert report.skill_id == "nonexistent"
        assert report.execution_count == 0
        assert report.combined_score == 0.0

    def test_report_single_execution(self, tracker):
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                scores=GainScores(effectiveness=8.0, efficiency=7.0, quality=9.0, gain=1.0),
            )
        )

        report = tracker.report("review")
        assert report.execution_count == 1
        assert report.avg_effectiveness == 8.0
        assert report.avg_efficiency == 7.0
        assert report.avg_quality == 9.0
        assert report.avg_gain == 1.0

    def test_report_multiple_executions(self, tracker):
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                scores=GainScores(effectiveness=8.0, efficiency=7.0, quality=9.0, gain=1.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                scores=GainScores(effectiveness=6.0, efficiency=5.0, quality=7.0, gain=0.5),
            )
        )

        report = tracker.report("review")
        assert report.execution_count == 2
        assert report.avg_effectiveness == 7.0  # (8+6)/2
        assert report.avg_efficiency == 6.0  # (7+5)/2
        assert report.avg_quality == 8.0  # (9+7)/2
        assert report.avg_gain == 0.75  # (1+0.5)/2

    def test_report_last_n_filter(self, tracker):
        """Report only considers last N executions."""
        for i in range(10):
            tracker.record(
                SkillExecution(
                    skill_ids=["review"],
                    scores=GainScores(effectiveness=float(i)),
                )
            )

        report = tracker.report("review", last_n=3)
        assert report.execution_count == 3
        # Last 3: 7, 8, 9 → avg = 8.0
        assert report.avg_effectiveness == 8.0

    def test_report_filters_by_skill_id(self, tracker):
        """Report only includes executions with matching skill_id."""
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                scores=GainScores(effectiveness=8.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["security"],
                scores=GainScores(effectiveness=5.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["review", "security"],  # Both skills
                scores=GainScores(effectiveness=9.0),
            )
        )

        report_review = tracker.report("review")
        assert report_review.execution_count == 2  # First and third
        # (8 + 9) / 2 = 8.5
        assert report_review.avg_effectiveness == 8.5

        report_security = tracker.report("security")
        assert report_security.execution_count == 2  # Second and third
        # (5 + 9) / 2 = 7.0
        assert report_security.avg_effectiveness == 7.0

    def test_combined_score_formula(self, tracker):
        """Test the combined score weighted average."""
        tracker.record(
            SkillExecution(
                skill_ids=["test"],
                scores=GainScores(effectiveness=10.0, efficiency=10.0, quality=10.0, gain=10.0),
            )
        )

        report = tracker.report("test")
        # Combined = eff*0.35 + effi*0.20 + qual*0.25 + max(0,gain)*0.20
        # = 10*0.35 + 10*0.20 + 10*0.25 + 10*0.20 = 3.5 + 2 + 2.5 + 2 = 10.0
        assert report.combined_score == 10.0

    def test_combined_score_negative_gain_ignored(self, tracker):
        """Negative gain doesn't contribute to combined score."""
        tracker.record(
            SkillExecution(
                skill_ids=["test"],
                scores=GainScores(effectiveness=5.0, efficiency=5.0, quality=5.0, gain=-5.0),
            )
        )

        report = tracker.report("test")
        # Combined = 5*0.35 + 5*0.20 + 5*0.25 + max(0,-5)*0.20
        # = 1.75 + 1 + 1.25 + 0 = 4.0
        assert report.combined_score == 4.0

    def test_report_values_rounded(self, tracker):
        """Report values are rounded to 2 decimal places."""
        tracker.record(
            SkillExecution(
                skill_ids=["test"],
                scores=GainScores(effectiveness=8.333, efficiency=7.777, quality=9.111, gain=1.555),
            )
        )

        report = tracker.report("test")
        assert report.avg_effectiveness == 8.33
        assert report.avg_efficiency == 7.78
        assert report.avg_quality == 9.11
        # Python banker's rounding: round(1.555, 2) == 1.55
        assert report.avg_gain == round(1.555, 2)


# ---------------------------------------------------------------------------
# GainTracker — combination_gain
# ---------------------------------------------------------------------------


class TestCombinationGain:
    """Test marginal gain calculation for skill combinations."""

    def test_no_data_returns_zero(self, tracker):
        """When no relevant executions, returns 0.0."""
        assert tracker.combination_gain("a", "b") == 0.0

    def test_only_together_no_alone(self, tracker):
        """If only A+B executions exist (no A alone), returns 0.0."""
        tracker.record(
            SkillExecution(
                skill_ids=["a", "b"],
                scores=GainScores(effectiveness=9.0),
            )
        )
        assert tracker.combination_gain("a", "b") == 0.0

    def test_only_alone_no_together(self, tracker):
        """If only A alone executions exist (no A+B), returns 0.0."""
        tracker.record(
            SkillExecution(
                skill_ids=["a"],
                scores=GainScores(effectiveness=7.0),
            )
        )
        assert tracker.combination_gain("a", "b") == 0.0

    def test_positive_gain(self, tracker):
        """When A+B performs better than A alone, returns positive gain."""
        # A alone: effectiveness 6.0
        tracker.record(SkillExecution(skill_ids=["a"], scores=GainScores(effectiveness=6.0)))
        tracker.record(SkillExecution(skill_ids=["a"], scores=GainScores(effectiveness=8.0)))
        # A+B: effectiveness 9.0
        tracker.record(SkillExecution(skill_ids=["a", "b"], scores=GainScores(effectiveness=9.0)))
        tracker.record(SkillExecution(skill_ids=["a", "b"], scores=GainScores(effectiveness=9.0)))

        # A alone avg = 7.0, A+B avg = 9.0, gain = 2.0
        assert tracker.combination_gain("a", "b") == 2.0

    def test_negative_gain(self, tracker):
        """When A+B performs worse than A alone, returns negative gain."""
        # A alone: effectiveness 9.0
        tracker.record(SkillExecution(skill_ids=["a"], scores=GainScores(effectiveness=9.0)))
        # A+B: effectiveness 6.0
        tracker.record(SkillExecution(skill_ids=["a", "b"], scores=GainScores(effectiveness=6.0)))

        # A alone avg = 9.0, A+B avg = 6.0, gain = -3.0
        assert tracker.combination_gain("a", "b") == -3.0

    def test_result_rounded(self, tracker):
        tracker.record(SkillExecution(skill_ids=["a"], scores=GainScores(effectiveness=7.0)))
        tracker.record(SkillExecution(skill_ids=["a", "b"], scores=GainScores(effectiveness=8.333)))

        # 8.333 - 7.0 = 1.333 → rounded to 1.33
        assert tracker.combination_gain("a", "b") == 1.33


# ---------------------------------------------------------------------------
# GainTracker — get_top_combinations
# ---------------------------------------------------------------------------


class TestGetTopCombinations:
    """Test retrieving top-performing skill combinations."""

    def test_no_executions(self, tracker):
        assert tracker.get_top_combinations() == []

    def test_single_skill(self, tracker):
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                scores=GainScores(effectiveness=8.0),
            )
        )

        result = tracker.get_top_combinations()
        assert len(result) == 1
        assert result[0]["skill_id"] == "review"
        assert result[0]["avg_gain"] == 8.0
        assert result[0]["execution_count"] == 1

    def test_multiple_skills_sorted_by_gain(self, tracker):
        tracker.record(
            SkillExecution(
                skill_ids=["low"],
                scores=GainScores(effectiveness=3.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["high"],
                scores=GainScores(effectiveness=9.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["mid"],
                scores=GainScores(effectiveness=6.0),
            )
        )

        result = tracker.get_top_combinations()
        assert len(result) == 3
        # Sorted descending by avg_gain
        assert result[0]["skill_id"] == "high"
        assert result[1]["skill_id"] == "mid"
        assert result[2]["skill_id"] == "low"

    def test_top_k_limit(self, tracker):
        for i in range(10):
            tracker.record(
                SkillExecution(
                    skill_ids=[f"skill-{i}"],
                    scores=GainScores(effectiveness=float(i)),
                )
            )

        result = tracker.get_top_combinations(top_k=3)
        assert len(result) == 3
        # Top 3: skill-9, skill-8, skill-7
        assert result[0]["skill_id"] == "skill-9"
        assert result[1]["skill_id"] == "skill-8"
        assert result[2]["skill_id"] == "skill-7"

    def test_intent_filter_match(self, tracker):
        tracker.record(
            SkillExecution(
                skill_ids=["code-review"],
                scores=GainScores(effectiveness=8.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["security-scan"],
                scores=GainScores(effectiveness=7.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["testing"],
                scores=GainScores(effectiveness=6.0),
            )
        )

        result = tracker.get_top_combinations(intent="review")
        assert len(result) == 1
        assert result[0]["skill_id"] == "code-review"

    def test_intent_filter_partial_match(self, tracker):
        """Intent filter matches if skill_id contains any intent word."""
        tracker.record(
            SkillExecution(
                skill_ids=["code-review"],
                scores=GainScores(effectiveness=8.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["review-checklist"],
                scores=GainScores(effectiveness=7.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["unrelated"],
                scores=GainScores(effectiveness=9.0),
            )
        )

        result = tracker.get_top_combinations(intent="review")
        assert len(result) == 2
        skill_ids = {r["skill_id"] for r in result}
        assert skill_ids == {"code-review", "review-checklist"}

    def test_last_execution_timestamp(self, tracker):
        """Result includes the most recent timestamp for each skill."""
        tracker.record(
            SkillExecution(
                skill_ids=["test"],
                timestamp="2025-01-01T00:00:00Z",
                scores=GainScores(effectiveness=5.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["test"],
                timestamp="2025-01-02T00:00:00Z",
                scores=GainScores(effectiveness=6.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["test"],
                timestamp="2025-01-03T00:00:00Z",
                scores=GainScores(effectiveness=7.0),
            )
        )

        result = tracker.get_top_combinations()
        assert result[0]["last_execution"] == "2025-01-03T00:00:00Z"

    def test_multi_skill_execution_counts_each_skill(self, tracker):
        """An execution with multiple skills counts for each skill separately."""
        tracker.record(
            SkillExecution(
                skill_ids=["a", "b"],
                scores=GainScores(effectiveness=8.0),
            )
        )

        result = tracker.get_top_combinations()
        assert len(result) == 2
        for r in result:
            assert r["execution_count"] == 1
            assert r["avg_gain"] == 8.0


# ---------------------------------------------------------------------------
# GainTracker — get_gain_history
# ---------------------------------------------------------------------------


class TestGetGainHistory:
    """Test retrieving execution history for a specific skill."""

    def test_no_history(self, tracker):
        assert tracker.get_gain_history("nonexistent") == []

    def test_single_execution(self, tracker):
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                timestamp="2025-01-01T00:00:00Z",
                scores=GainScores(effectiveness=8.0),
            )
        )

        history = tracker.get_gain_history("review")
        assert len(history) == 1
        assert history[0]["timestamp"] == "2025-01-01T00:00:00Z"
        assert history[0]["gain"] == 8.0
        assert history[0]["skill_ids"] == ["review"]

    def test_multiple_executions(self, tracker):
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                timestamp="2025-01-01T00:00:00Z",
                scores=GainScores(effectiveness=7.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                timestamp="2025-01-02T00:00:00Z",
                scores=GainScores(effectiveness=8.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                timestamp="2025-01-03T00:00:00Z",
                scores=GainScores(effectiveness=9.0),
            )
        )

        history = tracker.get_gain_history("review")
        assert len(history) == 3

    def test_filters_by_skill_id(self, tracker):
        tracker.record(
            SkillExecution(
                skill_ids=["review"],
                timestamp="2025-01-01T00:00:00Z",
                scores=GainScores(effectiveness=8.0),
            )
        )
        tracker.record(
            SkillExecution(
                skill_ids=["security"],
                timestamp="2025-01-02T00:00:00Z",
                scores=GainScores(effectiveness=7.0),
            )
        )

        history = tracker.get_gain_history("review")
        assert len(history) == 1
        assert history[0]["skill_ids"] == ["review"]

    def test_includes_multi_skill_executions(self, tracker):
        """Executions with multiple skills are included if skill_id matches."""
        tracker.record(
            SkillExecution(
                skill_ids=["review", "security"],
                timestamp="2025-01-01T00:00:00Z",
                scores=GainScores(effectiveness=9.0),
            )
        )

        history = tracker.get_gain_history("review")
        assert len(history) == 1
        assert history[0]["skill_ids"] == ["review", "security"]

        history_sec = tracker.get_gain_history("security")
        assert len(history_sec) == 1


# ---------------------------------------------------------------------------
# GainTracker — persistence integration
# ---------------------------------------------------------------------------


class TestPersistenceIntegration:
    """Test that data persists across GainTracker instances."""

    def test_data_persists_across_instances(self, data_dir):
        """Data written by one tracker is readable by another."""
        t1 = GainTracker(data_dir=data_dir)
        t1.record(
            SkillExecution(
                skill_ids=["persistent"],
                scores=GainScores(effectiveness=8.5),
            )
        )

        # New instance should load the same data
        t2 = GainTracker(data_dir=data_dir)
        report = t2.report("persistent")
        assert report.execution_count == 1
        assert report.avg_effectiveness == 8.5

    def test_concurrent_appends(self, data_dir):
        """Multiple tracker instances can append to the same log file."""
        t1 = GainTracker(data_dir=data_dir)
        t2 = GainTracker(data_dir=data_dir)

        t1.record(SkillExecution(skill_ids=["t1"]))
        t2.record(SkillExecution(skill_ids=["t2"]))

        # Both should be in the file
        log_file = data_dir / "executions.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

        # A third tracker should see both (after triggering _ensure_loaded via report)
        t3 = GainTracker(data_dir=data_dir)
        report = t3.report("t1")
        assert report.execution_count >= 1
        # _executions is loaded lazily; force load and check
        t3._ensure_loaded()
        assert len(t3._executions) == 2
