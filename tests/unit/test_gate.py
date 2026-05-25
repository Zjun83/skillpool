"""Unit tests for skillpool.gate module."""

import pytest

from skillpool.csdf import CSDFDocument
from skillpool.gate import Gate, GateConfig, GateStatus
from skillpool.quality import QualityProfile

# --- Fixtures ---


@pytest.fixture
def passing_profile() -> QualityProfile:
    return QualityProfile(
        name="good-skill",
        completeness=0.9,
        accuracy=0.85,
        usability=0.8,
        maintainability=0.75,
    )


@pytest.fixture
def failing_profile() -> QualityProfile:
    return QualityProfile(
        name="bad-skill",
        completeness=0.3,
        accuracy=0.2,
        usability=0.4,
        maintainability=0.5,
    )


@pytest.fixture
def gate() -> Gate:
    return Gate()


@pytest.fixture
def gate_with_overrides() -> Gate:
    config = GateConfig(
        min_quality_score=0.6,
        required_dimensions=["completeness", "accuracy"],
        min_dimension_score=0.5,
        emergency_overrides={"emergency-key": "Production hotfix"},
    )
    return Gate(config=config)


# --- GateStatus tests ---


class TestGateStatus:
    def test_status_values(self):
        assert GateStatus.PASS == "pass"
        assert GateStatus.FAIL == "fail"
        assert GateStatus.OVERRIDE == "override"
        assert GateStatus.SKIPPED == "skipped"


# --- GateConfig tests ---


class TestGateConfig:
    def test_defaults(self):
        config = GateConfig()
        assert config.min_quality_score == 0.6
        assert config.required_dimensions == ["completeness", "accuracy"]
        assert config.min_dimension_score == 0.5

    def test_custom(self):
        config = GateConfig(
            min_quality_score=0.8,
            required_dimensions=["completeness"],
            min_dimension_score=0.7,
        )
        assert config.min_quality_score == 0.8
        assert len(config.required_dimensions) == 1


# --- Gate.check tests ---


class TestGateCheck:
    def test_passing_profile(self, gate, passing_profile):
        result = gate.check(passing_profile)
        assert result.status == GateStatus.PASS
        assert result.overall_score >= 0.6

    def test_failing_profile(self, gate, failing_profile):
        result = gate.check(failing_profile)
        assert result.status == GateStatus.FAIL

    def test_override_on_fail(self, gate_with_overrides, failing_profile):
        result = gate_with_overrides.check(failing_profile, override_key="emergency-key")
        assert result.status == GateStatus.OVERRIDE
        assert result.override_reason == "Production hotfix"

    def test_override_invalid_key(self, gate_with_overrides, failing_profile):
        result = gate_with_overrides.check(failing_profile, override_key="bad-key")
        assert result.status == GateStatus.FAIL

    def test_no_override_on_pass(self, gate_with_overrides, passing_profile):
        result = gate_with_overrides.check(passing_profile)
        assert result.status == GateStatus.PASS


# --- Gate.check_document tests ---


class TestGateCheckDocument:
    def test_check_document_pass(self, gate):
        doc = CSDFDocument(
            name="doc-skill",
            dimensions={
                "completeness": 0.9,
                "accuracy": 0.8,
                "usability": 0.7,
                "maintainability": 0.8,
            },
        )
        result = gate.check_document(doc)
        assert result.status == GateStatus.PASS

    def test_check_document_fail(self, gate):
        doc = CSDFDocument(
            name="doc-skill",
            dimensions={
                "completeness": 0.3,
                "accuracy": 0.2,
                "usability": 0.4,
                "maintainability": 0.5,
            },
        )
        result = gate.check_document(doc)
        assert result.status == GateStatus.FAIL


# --- GateResult tests ---


class TestGateResult:
    def test_timestamp_auto_set(self, passing_profile, gate):
        result = gate.check(passing_profile)
        assert result.timestamp != ""

    def test_dimension_results_populated(self, gate, passing_profile):
        result = gate.check(passing_profile)
        assert "completeness" in result.dimension_results
        assert "accuracy" in result.dimension_results
