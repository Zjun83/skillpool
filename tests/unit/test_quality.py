"""Unit tests for skillpool.quality module."""

from skillpool.csdf import CSDFDocument
from skillpool.quality import QualityProfile, QualityProfiler

# Dimension keys that belong inside CSDFDocument.dimensions, not top-level
_DIM_KEYS = {"completeness", "accuracy", "usability", "maintainability"}


class TestQualityProfile:
    """Tests for QualityProfile dataclass."""

    def test_default_weights(self):
        profile = QualityProfile(name="test")
        assert profile.weights == {
            "completeness": 0.30,
            "accuracy": 0.30,
            "usability": 0.20,
            "maintainability": 0.20,
        }

    def test_auto_overall(self):
        profile = QualityProfile(
            name="test",
            completeness=0.8,
            accuracy=0.7,
            usability=0.9,
            maintainability=0.6,
        )
        expected = 0.8 * 0.30 + 0.7 * 0.30 + 0.9 * 0.20 + 0.6 * 0.20
        assert abs(profile.overall - round(expected, 4)) < 0.001

    def test_explicit_overall(self):
        profile = QualityProfile(name="test", overall=0.5)
        assert profile.overall == 0.5

    def test_zero_scores(self):
        profile = QualityProfile(name="test")
        assert profile.overall == 0.0


class TestQualityProfiler:
    """Tests for QualityProfiler class."""

    def _make_doc(self, **overrides):
        # Separate dimension overrides from top-level CSDFDocument overrides
        dim_overrides = {k: v for k, v in overrides.items() if k in _DIM_KEYS}
        top_overrides = {k: v for k, v in overrides.items() if k not in _DIM_KEYS}

        dimensions = {
            "completeness": 0.8,
            "accuracy": 0.7,
            "usability": 0.9,
            "maintainability": 0.6,
        }
        dimensions.update(dim_overrides)

        defaults = dict(
            name="test-skill",
            version="0.1.0",
            description="A test skill",
            triggers=["test"],
            dimensions=dimensions,
            references=[],
            body="Test body",
        )
        defaults.update(top_overrides)
        return CSDFDocument(**defaults)

    def test_profile_basic(self):
        profiler = QualityProfiler()
        doc = self._make_doc()
        profile = profiler.profile(doc)
        assert profile.name == "test-skill"
        assert 0.0 <= profile.completeness <= 1.0
        assert 0.0 <= profile.accuracy <= 1.0

    def test_profile_calibration(self):
        profiler = QualityProfiler()
        doc = self._make_doc(accuracy=1.0)
        profile = profiler.profile(doc)
        # accuracy has -0.05 calibration offset: 1.0 + (-0.05) = 0.95
        assert profile.accuracy == 0.95

    def test_profile_calibration_floor(self):
        profiler = QualityProfiler()
        doc = self._make_doc(accuracy=0.0)
        profile = profiler.profile(doc)
        # calibration offset -0.05, but clamped to 0.0
        assert profile.accuracy == 0.0

    def test_custom_weights(self):
        weights = {"completeness": 1.0, "accuracy": 0.0, "usability": 0.0, "maintainability": 0.0}
        profiler = QualityProfiler(weights=weights)
        doc = self._make_doc(completeness=0.5)
        profile = profiler.profile(doc)
        assert profile.completeness == 0.5

    def test_score(self):
        profiler = QualityProfiler()
        doc = self._make_doc()
        profile = profiler.profile(doc)
        score = profiler.score(profile)
        assert score == profile.overall

    def test_compare(self):
        profiler = QualityProfiler()
        doc_a = self._make_doc(completeness=0.9)
        doc_b = self._make_doc(completeness=0.5)
        profile_a = profiler.profile(doc_a)
        profile_b = profiler.profile(doc_b)
        diffs = profiler.compare(profile_a, profile_b)
        assert diffs["completeness"] > 0
        assert "overall" in diffs

    def test_missing_dimensions_default_zero(self):
        profiler = QualityProfiler()
        doc = self._make_doc(dimensions={})
        profile = profiler.profile(doc)
        assert profile.completeness == 0.0
        assert profile.accuracy == 0.0
