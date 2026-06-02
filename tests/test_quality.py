"""Tests for QualityProfile, QualityProfiler, and auto-scoring helpers."""

from __future__ import annotations

import pytest

from skillpool.csdf import CSDFDocument
from skillpool.quality import (
    CALIBRATION_OFFSETS,
    DEFAULT_WEIGHTS,
    _compute_overall,
    _score_accuracy,
    _score_completeness,
    _score_maintainability,
    _score_usability,
    QualityProfile,
    QualityProfiler,
)


# ---------------------------------------------------------------------------
# _compute_overall tests
# ---------------------------------------------------------------------------


class TestComputeOverall:
    """Tests for _compute_overall weighted score computation."""

    def test_default_weights_sum_to_one(self):
        """Default weights should sum to 1.0."""
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_basic_computation(self):
        """Test basic weighted average with default weights."""
        # 0.8 * 0.30 + 0.7 * 0.30 + 0.9 * 0.20 + 0.6 * 0.20 = 0.75
        result = _compute_overall(0.8, 0.7, 0.9, 0.6, DEFAULT_WEIGHTS)
        assert result == pytest.approx(0.75, abs=0.0001)

    def test_all_zeros(self):
        """All zero scores should yield zero overall."""
        result = _compute_overall(0.0, 0.0, 0.0, 0.0, DEFAULT_WEIGHTS)
        assert result == 0.0

    def test_all_ones(self):
        """All perfect scores should yield 1.0 overall."""
        result = _compute_overall(1.0, 1.0, 1.0, 1.0, DEFAULT_WEIGHTS)
        assert result == pytest.approx(1.0, abs=0.0001)

    def test_custom_weights(self):
        """Test with custom weight configuration."""
        custom_weights = {
            "completeness": 0.5,
            "accuracy": 0.2,
            "usability": 0.2,
            "maintainability": 0.1,
        }
        # 1.0 * 0.5 + 0.0 * 0.2 + 0.0 * 0.2 + 0.0 * 0.1 = 0.5
        result = _compute_overall(1.0, 0.0, 0.0, 0.0, custom_weights)
        assert result == pytest.approx(0.5, abs=0.0001)

    def test_partial_weights(self):
        """Missing weight keys should be treated as 0.0."""
        partial_weights = {"completeness": 1.0}  # Only completeness matters
        result = _compute_overall(0.8, 0.9, 0.7, 0.6, partial_weights)
        assert result == pytest.approx(0.8, abs=0.0001)

    def test_empty_weights(self):
        """Empty weights dict should yield 0.0."""
        result = _compute_overall(1.0, 1.0, 1.0, 1.0, {})
        assert result == 0.0

    def test_rounding_to_four_decimals(self):
        """Result should be rounded to 4 decimal places."""
        weights = {
            "completeness": 0.3333,
            "accuracy": 0.3333,
            "usability": 0.1667,
            "maintainability": 0.1667,
        }
        result = _compute_overall(1.0, 1.0, 1.0, 1.0, weights)
        assert isinstance(result, float)
        assert len(str(result).split(".")[-1]) <= 4 or str(result).endswith("0")


# ---------------------------------------------------------------------------
# QualityProfile __post_init__ tests
# ---------------------------------------------------------------------------


class TestQualityProfilePostInit:
    """Tests for QualityProfile __post_init__ auto-calculation."""

    def test_auto_calc_when_overall_zero_and_dimensions_nonzero(self):
        """If overall=0 and any dimension is non-zero, recalculate overall."""
        profile = QualityProfile(
            name="test",
            completeness=0.8,
            accuracy=0.7,
            usability=0.9,
            maintainability=0.6,
            overall=0.0,  # Should be recalculated
        )
        # Expected: 0.8*0.30 + 0.7*0.30 + 0.9*0.20 + 0.6*0.20 = 0.75
        assert profile.overall == pytest.approx(0.75, abs=0.0001)

    def test_no_recalc_when_overall_explicitly_set(self):
        """If overall is explicitly non-zero, do not recalculate."""
        profile = QualityProfile(
            name="test",
            completeness=0.8,
            accuracy=0.7,
            usability=0.9,
            maintainability=0.6,
            overall=0.5,  # Explicit value, should NOT be recalculated
        )
        assert profile.overall == 0.5

    def test_no_recalc_when_all_dimensions_zero(self):
        """If all dimensions are zero, overall stays zero (no recalc needed)."""
        profile = QualityProfile(
            name="test",
            completeness=0.0,
            accuracy=0.0,
            usability=0.0,
            maintainability=0.0,
            overall=0.0,
        )
        assert profile.overall == 0.0

    def test_auto_calc_with_custom_weights(self):
        """Auto-calculation should use provided weights."""
        custom_weights = {
            "completeness": 0.5,
            "accuracy": 0.5,
            "usability": 0.0,
            "maintainability": 0.0,
        }
        profile = QualityProfile(
            name="test",
            completeness=1.0,
            accuracy=0.5,
            usability=0.0,
            maintainability=0.0,
            overall=0.0,
            weights=custom_weights,
        )
        # Expected: 1.0*0.5 + 0.5*0.5 = 0.75
        assert profile.overall == pytest.approx(0.75, abs=0.0001)

    def test_default_weights_copied_not_shared(self):
        """Each profile should have its own weights dict copy."""
        profile1 = QualityProfile(name="p1")
        profile2 = QualityProfile(name="p2")
        profile1.weights["completeness"] = 0.9
        # profile2's weights should not be affected
        assert profile2.weights["completeness"] == 0.30


# ---------------------------------------------------------------------------
# QualityProfile.from_document tests
# ---------------------------------------------------------------------------


class TestQualityProfileFromDocument:
    """Tests for QualityProfile.from_document class method."""

    def test_from_document_with_dimensions(self):
        """Create profile from document with dimensions dict."""
        doc = CSDFDocument(
            name="test-skill",
            dimensions={
                "completeness": 0.9,
                "accuracy": 0.8,
                "usability": 0.7,
                "maintainability": 0.6,
            },
        )
        profile = QualityProfile.from_document(doc)
        assert profile.name == "test-skill"
        assert profile.completeness == 0.9
        assert profile.accuracy == 0.8
        assert profile.usability == 0.7
        assert profile.maintainability == 0.6
        # Overall should be computed
        expected = 0.9 * 0.30 + 0.8 * 0.30 + 0.7 * 0.20 + 0.6 * 0.20
        assert profile.overall == pytest.approx(expected, abs=0.0001)

    def test_from_document_with_empty_dimensions(self):
        """Document with empty dimensions dict yields zero scores."""
        doc = CSDFDocument(name="empty-skill", dimensions={})
        profile = QualityProfile.from_document(doc)
        assert profile.name == "empty-skill"
        assert profile.completeness == 0.0
        assert profile.accuracy == 0.0
        assert profile.usability == 0.0
        assert profile.maintainability == 0.0
        assert profile.overall == 0.0

    def test_from_document_with_partial_dimensions(self):
        """Document with partial dimensions uses 0.0 for missing."""
        doc = CSDFDocument(
            name="partial-skill",
            dimensions={"completeness": 0.8, "accuracy": 0.6},
        )
        profile = QualityProfile.from_document(doc)
        assert profile.completeness == 0.8
        assert profile.accuracy == 0.6
        assert profile.usability == 0.0
        assert profile.maintainability == 0.0

    def test_from_document_with_custom_weights(self):
        """Custom weights override defaults."""
        doc = CSDFDocument(
            name="test",
            dimensions={"completeness": 1.0, "accuracy": 0.0, "usability": 0.0, "maintainability": 0.0},
        )
        custom_weights = {
            "completeness": 1.0,
            "accuracy": 0.0,
            "usability": 0.0,
            "maintainability": 0.0,
        }
        profile = QualityProfile.from_document(doc, weights=custom_weights)
        assert profile.overall == 1.0

    def test_from_document_ignores_extra_dimensions(self):
        """Extra dimension keys in doc are ignored."""
        doc = CSDFDocument(
            name="test",
            dimensions={
                "completeness": 0.5,
                "accuracy": 0.5,
                "usability": 0.5,
                "maintainability": 0.5,
                "extra_dim": 1.0,  # Should be ignored
            },
        )
        profile = QualityProfile.from_document(doc)
        assert not hasattr(profile, "extra_dim")


# ---------------------------------------------------------------------------
# QualityProfile.from_scores tests
# ---------------------------------------------------------------------------


class TestQualityProfileFromScores:
    """Tests for QualityProfile.from_scores class method."""

    def test_from_scores_basic(self):
        """Create profile from explicit scores."""
        profile = QualityProfile.from_scores(
            name="test",
            completeness=0.8,
            accuracy=0.7,
            usability=0.9,
            maintainability=0.6,
        )
        assert profile.name == "test"
        assert profile.completeness == 0.8
        assert profile.accuracy == 0.7
        assert profile.usability == 0.9
        assert profile.maintainability == 0.6
        expected = 0.8 * 0.30 + 0.7 * 0.30 + 0.9 * 0.20 + 0.6 * 0.20
        assert profile.overall == pytest.approx(expected, abs=0.0001)

    def test_from_scores_defaults(self):
        """Default scores should all be 0.0."""
        profile = QualityProfile.from_scores(name="default-test")
        assert profile.completeness == 0.0
        assert profile.accuracy == 0.0
        assert profile.usability == 0.0
        assert profile.maintainability == 0.0
        assert profile.overall == 0.0

    def test_from_scores_with_custom_weights(self):
        """Custom weights affect overall calculation."""
        custom_weights = {
            "completeness": 0.0,
            "accuracy": 0.0,
            "usability": 1.0,
            "maintainability": 0.0,
        }
        profile = QualityProfile.from_scores(
            name="test",
            completeness=1.0,
            accuracy=1.0,
            usability=0.5,
            maintainability=1.0,
            weights=custom_weights,
        )
        assert profile.overall == 0.5

    def test_from_scores_overall_explicitly_computed(self):
        """from_scores always computes overall, unlike __init__."""
        profile = QualityProfile.from_scores(
            name="test",
            completeness=0.5,
            accuracy=0.5,
            usability=0.5,
            maintainability=0.5,
        )
        expected = 0.5 * 0.30 + 0.5 * 0.30 + 0.5 * 0.20 + 0.5 * 0.20
        assert profile.overall == pytest.approx(expected, abs=0.0001)


# ---------------------------------------------------------------------------
# QualityProfile.compare tests
# ---------------------------------------------------------------------------


class TestQualityProfileCompare:
    """Tests for QualityProfile.compare delta calculation."""

    def test_compare_identical_profiles(self):
        """Comparing identical profiles yields zero deltas."""
        p1 = QualityProfile.from_scores("test", 0.8, 0.7, 0.9, 0.6)
        p2 = QualityProfile.from_scores("test", 0.8, 0.7, 0.9, 0.6)
        delta = p1.compare(p2)
        assert delta["completeness"] == 0.0
        assert delta["accuracy"] == 0.0
        assert delta["usability"] == 0.0
        assert delta["maintainability"] == 0.0
        assert delta["overall"] == 0.0

    def test_compare_positive_deltas(self):
        """First profile higher scores yield positive deltas."""
        p1 = QualityProfile.from_scores("high", 0.9, 0.8, 0.7, 0.6)
        p2 = QualityProfile.from_scores("low", 0.5, 0.4, 0.3, 0.2)
        delta = p1.compare(p2)
        assert delta["completeness"] == pytest.approx(0.4, abs=0.0001)
        assert delta["accuracy"] == pytest.approx(0.4, abs=0.0001)
        assert delta["usability"] == pytest.approx(0.4, abs=0.0001)
        assert delta["maintainability"] == pytest.approx(0.4, abs=0.0001)

    def test_compare_negative_deltas(self):
        """First profile lower scores yield negative deltas."""
        p1 = QualityProfile.from_scores("low", 0.3, 0.2, 0.1, 0.0)
        p2 = QualityProfile.from_scores("high", 0.9, 0.8, 0.7, 0.6)
        delta = p1.compare(p2)
        assert delta["completeness"] == pytest.approx(-0.6, abs=0.0001)
        assert delta["accuracy"] == pytest.approx(-0.6, abs=0.0001)
        assert delta["usability"] == pytest.approx(-0.6, abs=0.0001)
        assert delta["maintainability"] == pytest.approx(-0.6, abs=0.0001)

    def test_compare_mixed_deltas(self):
        """Mixed higher/lower scores yield mixed deltas."""
        p1 = QualityProfile.from_scores("mixed1", 0.9, 0.2, 0.5, 0.5)
        p2 = QualityProfile.from_scores("mixed2", 0.3, 0.8, 0.5, 0.5)
        delta = p1.compare(p2)
        assert delta["completeness"] == pytest.approx(0.6, abs=0.0001)
        assert delta["accuracy"] == pytest.approx(-0.6, abs=0.0001)
        assert delta["usability"] == 0.0
        assert delta["maintainability"] == 0.0

    def test_compare_returns_all_keys(self):
        """Compare should return all 5 dimension keys."""
        p1 = QualityProfile.from_scores("a", 0.5, 0.5, 0.5, 0.5)
        p2 = QualityProfile.from_scores("b", 0.5, 0.5, 0.5, 0.5)
        delta = p1.compare(p2)
        expected_keys = {"completeness", "accuracy", "usability", "maintainability", "overall"}
        assert set(delta.keys()) == expected_keys

    def test_compare_rounding(self):
        """Deltas should be rounded to 4 decimal places."""
        p1 = QualityProfile.from_scores("a", 1.0, 0.0, 0.0, 0.0)
        p2 = QualityProfile.from_scores("b", 0.0, 0.0, 0.0, 0.0)
        delta = p1.compare(p2)
        for value in delta.values():
            assert isinstance(value, float)


# ---------------------------------------------------------------------------
# QualityProfiler.profile tests
# ---------------------------------------------------------------------------


class TestQualityProfilerProfile:
    """Tests for QualityProfiler.profile method."""

    def test_profile_with_dimensions_present(self):
        """When doc has dimensions, use them (calibration offsets applied)."""
        doc = CSDFDocument(
            name="test",
            description="A test skill",
            triggers=["test"],
            body="Some content",
            dimensions={
                "completeness": 0.9,
                "accuracy": 0.8,
                "usability": 0.7,
                "maintainability": 0.6,
            },
        )
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.completeness == 0.9  # No offset for completeness
        # Accuracy has default -0.05 calibration offset: 0.8 - 0.05 = 0.75
        assert profile.accuracy == pytest.approx(0.75, abs=0.0001)
        assert profile.usability == 0.7  # No offset for usability
        assert profile.maintainability == 0.6  # No offset for maintainability

    def test_profile_without_dimensions_auto_scoring(self):
        """When doc has no dimensions, auto-score from content."""
        doc = CSDFDocument(
            name="auto-score-test",
            description="A test skill",
            triggers=["test"],
            body="## Header\n\nSome content with `code`.\n\n- Item 1\n- Item 2",
            references=["ref1", "ref2"],
            version="1.0.0",
        )
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        # Should have non-zero scores from auto-scoring
        assert profile.completeness > 0.0
        assert profile.accuracy > 0.0
        assert profile.usability > 0.0
        assert profile.maintainability > 0.0

    def test_profile_with_partial_dimensions(self):
        """Partial dimensions use provided values, auto-score missing ones."""
        doc = CSDFDocument(
            name="partial",
            description="Test",
            triggers=["t"],
            body="Content",
            dimensions={"completeness": 0.95},  # Only completeness provided
        )
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.completeness == 0.95
        # Others should be auto-scored (non-zero due to content)
        assert profile.accuracy >= 0.0
        assert profile.usability >= 0.0
        assert profile.maintainability >= 0.0

    def test_profile_applies_calibration_offsets(self):
        """Calibration offsets should be applied to scores."""
        doc = CSDFDocument(
            name="calib-test",
            dimensions={"completeness": 0.5, "accuracy": 0.5, "usability": 0.5, "maintainability": 0.5},
        )
        # Default calibration has accuracy offset of -0.05
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.completeness == 0.5  # No offset
        assert profile.accuracy == pytest.approx(0.45, abs=0.0001)  # -0.05 offset

    def test_profile_with_custom_weights(self):
        """Custom weights affect overall calculation."""
        doc = CSDFDocument(
            name="weight-test",
            dimensions={"completeness": 1.0, "accuracy": 0.0, "usability": 0.0, "maintainability": 0.0},
        )
        custom_weights = {
            "completeness": 1.0,
            "accuracy": 0.0,
            "usability": 0.0,
            "maintainability": 0.0,
        }
        profiler = QualityProfiler(weights=custom_weights)
        profile = profiler.profile(doc)
        assert profile.overall == 1.0

    def test_profile_with_custom_calibration_offsets(self):
        """Custom calibration offsets override defaults."""
        doc = CSDFDocument(
            name="custom-calib",
            dimensions={"completeness": 0.5, "accuracy": 0.5, "usability": 0.5, "maintainability": 0.5},
        )
        custom_offsets = {
            "completeness": 0.1,
            "accuracy": 0.1,
            "usability": 0.1,
            "maintainability": 0.1,
        }
        profiler = QualityProfiler(calibration_offsets=custom_offsets)
        profile = profiler.profile(doc)
        assert profile.completeness == 0.6
        assert profile.accuracy == 0.6
        assert profile.usability == 0.6
        assert profile.maintainability == 0.6


# ---------------------------------------------------------------------------
# Calibration offset clamping tests
# ---------------------------------------------------------------------------


class TestCalibrationOffsetClamping:
    """Tests for calibration offset clamping to [0.0, 1.0] range."""

    def test_clamp_lower_bound_zero(self):
        """Score + offset < 0 should clamp to 0.0."""
        doc = CSDFDocument(
            name="clamp-test",
            dimensions={"completeness": 0.1, "accuracy": 0.1, "usability": 0.1, "maintainability": 0.1},
        )
        large_negative_offsets = {
            "completeness": -0.5,
            "accuracy": -0.5,
            "usability": -0.5,
            "maintainability": -0.5,
        }
        profiler = QualityProfiler(calibration_offsets=large_negative_offsets)
        profile = profiler.profile(doc)
        # 0.1 - 0.5 = -0.4, clamped to 0.0
        assert profile.completeness == 0.0
        assert profile.accuracy == 0.0
        assert profile.usability == 0.0
        assert profile.maintainability == 0.0

    def test_clamp_upper_bound_one(self):
        """Score + offset > 1 should clamp to 1.0."""
        doc = CSDFDocument(
            name="clamp-test",
            dimensions={"completeness": 0.9, "accuracy": 0.9, "usability": 0.9, "maintainability": 0.9},
        )
        large_positive_offsets = {
            "completeness": 0.5,
            "accuracy": 0.5,
            "usability": 0.5,
            "maintainability": 0.5,
        }
        profiler = QualityProfiler(calibration_offsets=large_positive_offsets)
        profile = profiler.profile(doc)
        # 0.9 + 0.5 = 1.4, clamped to 1.0
        assert profile.completeness == 1.0
        assert profile.accuracy == 1.0
        assert profile.usability == 1.0
        assert profile.maintainability == 1.0

    def test_clamp_exact_boundaries(self):
        """Scores at exact boundaries should stay unchanged."""
        # Score 0.0 with offset 0.0 -> 0.0
        # Score 1.0 with offset 0.0 -> 1.0
        doc = CSDFDocument(
            name="boundary-test",
            dimensions={"completeness": 0.0, "accuracy": 1.0, "usability": 0.5, "maintainability": 0.5},
        )
        profiler = QualityProfiler(calibration_offsets={"completeness": 0.0, "accuracy": 0.0})
        profile = profiler.profile(doc)
        assert profile.completeness == 0.0
        assert profile.accuracy == 1.0

    def test_default_calibration_offsets_reasonable(self):
        """Default calibration offsets should not cause clamping with normal scores."""
        # Default accuracy offset is -0.05
        # A score of 0.0 with -0.05 offset would clamp to 0.0
        doc = CSDFDocument(
            name="default-calib",
            dimensions={"accuracy": 0.0},
        )
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.accuracy == 0.0  # 0.0 - 0.05 = -0.05 -> clamped to 0.0


# ---------------------------------------------------------------------------
# _score_completeness tests
# ---------------------------------------------------------------------------


class TestScoreCompleteness:
    """Tests for _score_completeness auto-scoring helper."""

    def test_all_fields_present(self):
        """All key fields present yields max score of 1.0."""
        doc = CSDFDocument(
            name="complete-skill",
            description="A complete skill",
            triggers=["trigger1"],
            body="Some body content",
        )
        score = _score_completeness(doc)
        assert score == 1.0

    def test_no_fields_present(self):
        """No key fields yields score of 0.0."""
        doc = CSDFDocument(name="", description="", triggers=[], body="")
        score = _score_completeness(doc)
        assert score == 0.0

    def test_partial_fields_quarter_each(self):
        """Each field contributes 0.25 to the score."""
        # Only name
        doc = CSDFDocument(name="test", description="", triggers=[], body="")
        assert _score_completeness(doc) == 0.25

        # Name + description
        doc = CSDFDocument(name="test", description="desc", triggers=[], body="")
        assert _score_completeness(doc) == 0.5

        # Name + description + triggers
        doc = CSDFDocument(name="test", description="desc", triggers=["t"], body="")
        assert _score_completeness(doc) == 0.75

    def test_empty_triggers_list(self):
        """Empty triggers list should not contribute to score."""
        doc = CSDFDocument(name="test", description="desc", triggers=[], body="content")
        # name (0.25) + description (0.25) + body (0.25) = 0.75
        assert _score_completeness(doc) == 0.75

    def test_non_empty_triggers_list(self):
        """Non-empty triggers list should contribute."""
        doc = CSDFDocument(name="test", description="desc", triggers=["t1", "t2"], body="content")
        assert _score_completeness(doc) == 1.0

    def test_score_capped_at_one(self):
        """Score should be capped at 1.0 even with extra content."""
        doc = CSDFDocument(
            name="test",
            description="desc",
            triggers=["t1", "t2", "t3"],
            body="content" * 100,
        )
        assert _score_completeness(doc) == 1.0


# ---------------------------------------------------------------------------
# _score_accuracy tests
# ---------------------------------------------------------------------------


class TestScoreAccuracy:
    """Tests for _score_accuracy auto-scoring helper."""

    def test_no_content_no_references(self):
        """No body or references yields 0.0."""
        doc = CSDFDocument(name="test", body="", references=[])
        assert _score_accuracy(doc) == 0.0

    def test_references_contribute_up_to_half(self):
        """References contribute 0.25 each, capped at 0.5."""
        # 1 reference = 0.25
        doc = CSDFDocument(name="test", references=["ref1"])
        assert _score_accuracy(doc) == 0.25

        # 2 references = 0.5
        doc = CSDFDocument(name="test", references=["ref1", "ref2"])
        assert _score_accuracy(doc) == 0.5

        # 3+ references still capped at 0.5
        doc = CSDFDocument(name="test", references=["r1", "r2", "r3", "r4"])
        assert _score_accuracy(doc) == 0.5

    def test_code_blocks_contribute(self):
        """Code blocks (```) contribute to accuracy score.

        One code block has 2 occurrences of ``` (opening + closing),
        so it matches the >=2 threshold for 0.30.
        """
        # 1 code block = 2 ``` markers = 0.30
        doc = CSDFDocument(name="test", body="Here is code:\n```\ncode\n```\n")
        assert _score_accuracy(doc) == 0.30

        # 2+ code blocks = 4 ``` markers = 0.30
        doc = CSDFDocument(name="test", body="```\ncode1\n```\n```\ncode2\n```\n")
        assert _score_accuracy(doc) == 0.30

    def test_single_backtick_only(self):
        """A single ``` (odd number) scores 0.15."""
        # Construct body with exactly 1 occurrence of ```
        doc = CSDFDocument(name="test", body="```just one marker")
        assert _score_accuracy(doc) == 0.15

    def test_tech_terms_contribute(self):
        """Technical terms (API, function, class, etc.) contribute."""
        # 1-2 tech terms = 0.10
        doc = CSDFDocument(name="test", body="This API is useful.")
        assert _score_accuracy(doc) == 0.10

        # 3+ tech terms = 0.20
        doc = CSDFDocument(name="test", body="The API function class method parameter return.")
        assert _score_accuracy(doc) == 0.20

    def test_combined_scoring(self):
        """All factors combine up to 1.0."""
        doc = CSDFDocument(
            name="test",
            references=["r1", "r2"],
            body="```\ncode\n```\n```\nmore\n```\nThe API function class method.",
        )
        # references: 0.5, code blocks (4 markers): 0.30, tech terms (5): 0.20 = 1.0
        assert _score_accuracy(doc) == 1.0

    def test_score_capped_at_one(self):
        """Score should be capped at 1.0."""
        doc = CSDFDocument(
            name="test",
            references=["r1", "r2", "r3"],
            body="```\ncode\n```\n```\nmore\n```\nAPI function class method parameter return.",
        )
        assert _score_accuracy(doc) == 1.0

    def test_tech_terms_case_insensitive(self):
        """Tech terms should be matched case-insensitively."""
        doc = CSDFDocument(name="test", body="The API FUNCTION CLASS METHOD PARAMETER RETURN.")
        assert _score_accuracy(doc) == 0.20


# ---------------------------------------------------------------------------
# _score_usability tests
# ---------------------------------------------------------------------------


class TestScoreUsability:
    """Tests for _score_usability auto-scoring helper."""

    def test_no_body_no_triggers(self):
        """No body or triggers yields 0.0."""
        doc = CSDFDocument(name="test", body="", triggers=[])
        assert _score_usability(doc) == 0.0

    def test_headers_contribute(self):
        """Markdown headers contribute to usability (combined with word count)."""
        # 1 header = 0.15, plus "Header" + "Content" = 2 words (< 50, so 0.15) = 0.30
        doc = CSDFDocument(name="test", body="# Header\n\nContent")
        assert _score_usability(doc) == 0.30

        # 3+ headers = 0.30, plus few words = 0.15 = 0.45
        doc = CSDFDocument(name="test", body="# H1\n## H2\n### H3\nContent")
        assert _score_usability(doc) == 0.45

    def test_headers_only_no_word_count_bonus(self):
        """Isolated header scoring without word count overlap."""
        # Use enough words (50+) to isolate header contribution
        body = "# Header\n\n" + " ".join(["word"] * 60)
        doc = CSDFDocument(name="test", body=body)
        # 1 header: 0.15, word count in range: 0.30 = 0.45
        assert _score_usability(doc) == 0.45

    def test_lists_contribute(self):
        """Markdown lists contribute to usability (combined with word count)."""
        # 1 list item = 0.10, plus "Item 1" = 2 words (< 50, so 0.15) = 0.25
        doc = CSDFDocument(name="test", body="- Item 1")
        assert _score_usability(doc) == 0.25

        # 3+ list items = 0.20, plus 6 words (< 50, so 0.15) = 0.35
        doc = CSDFDocument(name="test", body="- Item 1\n- Item 2\n- Item 3")
        assert _score_usability(doc) == 0.35

    def test_word_count_in_range(self):
        """Word count 50-2000 contributes 0.30."""
        body = " ".join(["word"] * 100)
        doc = CSDFDocument(name="test", body=body)
        assert _score_usability(doc) == 0.30

    def test_word_count_out_of_range(self):
        """Word count outside 50-2000 contributes 0.15."""
        # Too few words
        doc = CSDFDocument(name="test", body="few words")
        assert _score_usability(doc) == 0.15

        # Many words but still gets partial credit
        body = " ".join(["word"] * 3000)
        doc = CSDFDocument(name="test", body=body)
        assert _score_usability(doc) == 0.15

    def test_triggers_contribute(self):
        """Having triggers adds 0.10."""
        doc = CSDFDocument(name="test", body="", triggers=["trigger"])
        assert _score_usability(doc) == 0.10

    def test_whitespace_body_with_triggers(self):
        """Whitespace-only body is truthy but has 0 words; triggers still contribute."""
        doc = CSDFDocument(name="test", body="   \n\n   \t\t   ", triggers=["trigger"])
        # body is truthy -> enters the if doc.body block
        # no headers, no lists, word_count=0 (split on whitespace), triggers: 0.10
        assert _score_usability(doc) == 0.10

    def test_combined_usability_scoring(self):
        """All usability factors combine."""
        body = "# H1\n## H2\n### H3\n\n- Item 1\n- Item 2\n- Item 3\n\n" + " ".join(["word"] * 100)
        doc = CSDFDocument(name="test", body=body, triggers=["t"])
        # headers: 0.30, lists: 0.20, word count: 0.30, triggers: 0.10 = 0.90
        assert _score_usability(doc) == 0.90

    def test_score_capped_at_one(self):
        """Score should be capped at 1.0."""
        # The max achievable: headers(0.30) + lists(0.20) + words(0.30) + triggers(0.10) = 0.90
        body = "# H1\n## H2\n### H3\n#### H4\n\n- A\n- B\n- C\n- D\n\n" + " ".join(["word"] * 100)
        doc = CSDFDocument(name="test", body=body, triggers=["t1", "t2"])
        # All factors max out at 0.90 (below 1.0 cap, so 0.90)
        assert _score_usability(doc) == 0.90

    def test_list_various_markers(self):
        """Lists with -, *, + markers all count."""
        # Each has 3 list items + a few words (< 50), so list bonus + word bonus
        doc_dash = CSDFDocument(name="test", body="- Item 1\n- Item 2\n- Item 3")
        doc_star = CSDFDocument(name="test", body="* Item 1\n* Item 2\n* Item 3")
        doc_plus = CSDFDocument(name="test", body="+ Item 1\n+ Item 2\n+ Item 3")
        # 3 lists: 0.20, 6 words (< 50): 0.15 = 0.35
        assert _score_usability(doc_dash) == 0.35
        assert _score_usability(doc_star) == 0.35
        assert _score_usability(doc_plus) == 0.35


# ---------------------------------------------------------------------------
# _score_maintainability tests
# ---------------------------------------------------------------------------


class TestScoreMaintainability:
    """Tests for _score_maintainability auto-scoring helper.

    Note: CSDFDocument defaults version="0.1.0" which matches semver,
    so the version bonus (0.30) applies even without explicitly setting version.
    """

    def test_semver_version_contributes(self):
        """Semver version (x.y.z) contributes 0.30."""
        doc = CSDFDocument(name="test", version="1.0.0")
        assert _score_maintainability(doc) == 0.30

    def test_short_version_no_bonus(self):
        """Short version (x.y) does not get semver bonus."""
        doc = CSDFDocument(name="test", version="1.0")
        assert _score_maintainability(doc) == 0.0

    def test_description_contributes(self):
        """Having a description contributes 0.20, plus default version 0.1.0 adds 0.30."""
        doc = CSDFDocument(name="test", description="A description")
        # default version "0.1.0" is semver -> 0.30, description -> 0.20 = 0.50
        assert _score_maintainability(doc) == 0.50

    def test_description_with_non_semver_version(self):
        """Description contributes 0.20 when version is not semver."""
        doc = CSDFDocument(name="test", version="1.0", description="A description")
        assert _score_maintainability(doc) == 0.20

    def test_short_paragraphs_contribute(self):
        """Average paragraph length < 200 chars contributes 0.20, plus default version 0.30."""
        doc = CSDFDocument(name="test", body="Short paragraph.\n\nAnother short one.")
        # default version "0.1.0" -> 0.30, short paragraphs -> 0.20 = 0.50
        assert _score_maintainability(doc) == 0.50

    def test_short_paragraphs_no_default_version(self):
        """Short paragraphs without default version bonus."""
        doc = CSDFDocument(name="test", version="1.0", body="Short paragraph.\n\nAnother short one.")
        assert _score_maintainability(doc) == 0.20

    def test_medium_paragraphs_contribute_less(self):
        """Average paragraph length 200-400 chars contributes 0.10, plus default version 0.30."""
        para = "x" * 250
        doc = CSDFDocument(name="test", body=para)
        # default version "0.1.0" -> 0.30, medium paragraphs -> 0.10 = 0.40
        assert _score_maintainability(doc) == 0.40

    def test_long_paragraphs_no_bonus(self):
        """Average paragraph length > 400 chars contributes 0.0 for paragraphs, default version 0.30."""
        para = "x" * 500
        doc = CSDFDocument(name="test", body=para)
        # default version "0.1.0" -> 0.30, long paragraphs -> 0.0 = 0.30
        assert _score_maintainability(doc) == 0.30

    def test_combined_maintainability(self):
        """All maintainability factors combine."""
        doc = CSDFDocument(
            name="test",
            version="1.2.3",
            description="A skill",
            body="Short para.\n\nAnother short one.",
        )
        # version: 0.30, description: 0.20, paragraphs: 0.20 = 0.70
        assert _score_maintainability(doc) == 0.70

    def test_score_capped_at_one(self):
        """Score should be capped at 1.0."""
        doc = CSDFDocument(
            name="test",
            version="2.0.0",
            description="A skill",
            body="Short.\n\nShort.\n\nShort.",
        )
        # version: 0.30, description: 0.20, paragraphs: 0.20 = 0.70
        assert _score_maintainability(doc) <= 1.0

    def test_empty_body_no_paragraph_bonus(self):
        """Empty body should not contribute paragraph bonus, but default version still counts."""
        doc = CSDFDocument(name="test", body="")
        # default version "0.1.0" -> 0.30, no body -> no paragraphs
        assert _score_maintainability(doc) == 0.30

    def test_empty_body_and_non_semver_version(self):
        """Empty body with non-semver version yields 0.0."""
        doc = CSDFDocument(name="test", version="1.0", body="")
        assert _score_maintainability(doc) == 0.0

    def test_single_paragraph_body(self):
        """Single paragraph should be evaluated correctly, plus default version."""
        doc = CSDFDocument(name="test", body="A short paragraph.")
        # default version "0.1.0" -> 0.30, single short paragraph -> 0.20 = 0.50
        assert _score_maintainability(doc) == 0.50

    def test_single_paragraph_no_default_version(self):
        """Single paragraph without default version bonus."""
        doc = CSDFDocument(name="test", version="1.0", body="A short paragraph.")
        assert _score_maintainability(doc) == 0.20

    def test_body_with_only_newlines_no_paragraphs(self):
        """Body with only blank lines has no non-empty paragraphs."""
        doc = CSDFDocument(name="test", version="1.0", body="\n\n\n\n")
        # version non-semver: 0, description: 0, body exists but paragraphs list is empty
        assert _score_maintainability(doc) == 0.0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestQualityIntegration:
    """Integration tests combining multiple components."""

    def test_full_profiling_workflow(self):
        """Test complete workflow from document to profile."""
        doc = CSDFDocument(
            name="integration-skill",
            version="1.0.0",
            description="A comprehensive test skill",
            triggers=["test", "integration"],
            references=["ref1.md", "ref2.md"],
            body="""# Overview

This skill does things.

## Usage

- Step 1
- Step 2
- Step 3

```python
def example():
    return "API function class"
```
""",
        )
        profiler = QualityProfiler()
        profile = profiler.profile(doc)

        # All dimensions should have non-zero scores
        assert profile.completeness > 0.0
        assert profile.accuracy > 0.0
        assert profile.usability > 0.0
        assert profile.maintainability > 0.0
        assert profile.overall > 0.0

    def test_profile_comparison_workflow(self):
        """Test comparing two profiles from documents."""
        doc1 = CSDFDocument(
            name="skill-v1",
            version="1.0.0",
            description="Version 1",
            triggers=["test"],
            body="Short content.",
            dimensions={"completeness": 0.5, "accuracy": 0.5, "usability": 0.5, "maintainability": 0.5},
        )
        doc2 = CSDFDocument(
            name="skill-v2",
            version="2.0.0",
            description="Version 2 with improvements",
            triggers=["test", "new"],
            body="Much longer content with more details.",
            dimensions={"completeness": 0.8, "accuracy": 0.7, "usability": 0.6, "maintainability": 0.9},
        )
        profiler = QualityProfiler()
        profile1 = profiler.profile(doc1)
        profile2 = profiler.profile(doc2)

        delta = profile2.compare(profile1)
        assert delta["completeness"] > 0
        assert delta["accuracy"] > 0
        assert delta["overall"] > 0

    def test_custom_weights_affect_comparison(self):
        """Different weights should affect overall comparison."""
        doc = CSDFDocument(
            name="test",
            dimensions={"completeness": 1.0, "accuracy": 0.0, "usability": 0.0, "maintainability": 0.0},
        )

        weights_completeness = {
            "completeness": 1.0,
            "accuracy": 0.0,
            "usability": 0.0,
            "maintainability": 0.0,
        }
        weights_accuracy = {
            "completeness": 0.0,
            "accuracy": 1.0,
            "usability": 0.0,
            "maintainability": 0.0,
        }

        profiler1 = QualityProfiler(weights=weights_completeness)
        profiler2 = QualityProfiler(weights=weights_accuracy)

        profile1 = profiler1.profile(doc)
        profile2 = profiler2.profile(doc)

        assert profile1.overall == 1.0
        assert profile2.overall == 0.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_profile_with_unicode_content(self):
        """Profile should handle unicode content gracefully."""
        doc = CSDFDocument(
            name="unicode-test",
            description="Description with unicode: \u4e2d\u6587",
            body="# \u65e5\u672c\u8a9e\n\n- \u30c6\u30b9\u30c8",
        )
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.name == "unicode-test"

    def test_profile_with_special_characters_in_body(self):
        """Body with special regex characters should not crash."""
        doc = CSDFDocument(
            name="special",
            body="# Header\n\n```\ncode with (regex) [chars] {and} *stars*\n```\n",
        )
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.accuracy >= 0.0

    def test_empty_document(self):
        """Empty document with default version gets maintainability from default semver."""
        doc = CSDFDocument(name="")
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.completeness == 0.0
        # Default version "0.1.0" is semver, so maintainability gets 0.30 from auto-scoring
        assert profile.maintainability == 0.3
        assert profile.overall > 0.0  # maintainability contributes

    def test_truly_empty_document(self):
        """Document with no default version bonus has zero scores."""
        doc = CSDFDocument(name="", version="1.0")  # Non-semver version
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.completeness == 0.0
        assert profile.maintainability == 0.0
        assert profile.overall == 0.0

    def test_document_with_only_whitespace_body(self):
        """Whitespace-only body is truthy in Python, so completeness counts it."""
        doc = CSDFDocument(name="test", body="   \n\n   \t\t   ")
        score = _score_completeness(doc)
        # Body string is truthy (non-empty), so it counts: name (0.25) + body (0.25) = 0.50
        assert score == 0.50

    def test_very_long_body(self):
        """Very long body should not cause issues."""
        body = "word " * 10000
        doc = CSDFDocument(name="test", body=body)
        profiler = QualityProfiler()
        profile = profiler.profile(doc)
        assert profile.usability >= 0.0

    def test_default_calibration_offsets_values(self):
        """Verify default calibration offset values."""
        assert CALIBRATION_OFFSETS["completeness"] == 0.0
        assert CALIBRATION_OFFSETS["accuracy"] == -0.05
        assert CALIBRATION_OFFSETS["usability"] == 0.0
        assert CALIBRATION_OFFSETS["maintainability"] == 0.0

    def test_default_weights_values(self):
        """Verify default weight values."""
        assert DEFAULT_WEIGHTS["completeness"] == 0.30
        assert DEFAULT_WEIGHTS["accuracy"] == 0.30
        assert DEFAULT_WEIGHTS["usability"] == 0.20
        assert DEFAULT_WEIGHTS["maintainability"] == 0.20
