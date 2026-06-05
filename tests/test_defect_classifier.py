"""Tests for DefectClassifier — ProcCtrlBench 11-type defect ontology."""

from __future__ import annotations

import asyncio


from skillpool.monitor.defect_classifier import (
    DefectClassifier,
    DefectType,
)
from skillpool.monitor.bug_collector import BugSeverity


class TestDefectType:
    """Tests for DefectType enum."""

    def test_all_11_types_defined(self):
        """Verify all 11 ProcCtrlBench defect types exist."""
        expected = {
            "param_error",
            "permission_breach",
            "timeout",
            "dependency_missing",
            "execution_failure",
            "output_invalid",
            "state_corruption",
            "resource_exhaustion",
            "gate_denied",
            "protocol_error",
            "unknown",
        }
        actual = {dt.value for dt in DefectType}
        assert actual == expected

    def test_str_enum_behavior(self):
        """DefectType should be a StrEnum."""
        assert DefectType.PARAM_ERROR == "param_error"
        assert DefectType.PARAM_ERROR.value == "param_error"


class TestBugSeverity:
    """Tests for BugSeverity enum (shared from bug_collector)."""

    def test_severity_ordering(self):
        """P0 < P1 < P2 in string comparison."""
        assert BugSeverity.P0.value < BugSeverity.P1.value
        assert BugSeverity.P1.value < BugSeverity.P2.value

    def test_three_levels(self):
        """BugSeverity should have exactly 3 levels (P0, P1, P2)."""
        assert len(BugSeverity) == 3


class TestDefectClassifier:
    """Tests for DefectClassifier class."""

    def test_classify_type_error(self):
        """TypeError should classify as PARAM_ERROR."""
        classifier = DefectClassifier()
        result = classifier.classify(TypeError("bad type"))
        assert result == DefectType.PARAM_ERROR

    def test_classify_value_error(self):
        """ValueError should classify as PARAM_ERROR."""
        classifier = DefectClassifier()
        result = classifier.classify(ValueError("bad value"))
        assert result == DefectType.PARAM_ERROR

    def test_classify_key_error(self):
        """KeyError should classify as PARAM_ERROR."""
        classifier = DefectClassifier()
        result = classifier.classify(KeyError("missing key"))
        assert result == DefectType.PARAM_ERROR

    def test_classify_permission_error(self):
        """PermissionError should classify as PERMISSION_BREACH."""
        classifier = DefectClassifier()
        result = classifier.classify(PermissionError("access denied"))
        assert result == DefectType.PERMISSION_BREACH

    def test_classify_timeout_error(self):
        """TimeoutError should classify as TIMEOUT."""
        classifier = DefectClassifier()
        result = classifier.classify(TimeoutError("timed out"))
        assert result == DefectType.TIMEOUT

    def test_classify_async_timeout_error(self):
        """asyncio.TimeoutError should classify as TIMEOUT."""
        classifier = DefectClassifier()
        result = classifier.classify(asyncio.TimeoutError())
        assert result == DefectType.TIMEOUT

    def test_classify_import_error(self):
        """ImportError should classify as DEPENDENCY_MISSING."""
        classifier = DefectClassifier()
        result = classifier.classify(ImportError("no module"))
        assert result == DefectType.DEPENDENCY_MISSING

    def test_classify_module_not_found_error(self):
        """ModuleNotFoundError should classify as DEPENDENCY_MISSING."""
        classifier = DefectClassifier()
        result = classifier.classify(ModuleNotFoundError("no module"))
        assert result == DefectType.DEPENDENCY_MISSING

    def test_classify_file_not_found_error(self):
        """FileNotFoundError should classify as DEPENDENCY_MISSING."""
        classifier = DefectClassifier()
        result = classifier.classify(FileNotFoundError("no file"))
        assert result == DefectType.DEPENDENCY_MISSING

    def test_classify_runtime_error(self):
        """RuntimeError should classify as EXECUTION_FAILURE."""
        classifier = DefectClassifier()
        result = classifier.classify(RuntimeError("crashed"))
        assert result == DefectType.EXECUTION_FAILURE

    def test_classify_assertion_error(self):
        """AssertionError should classify as OUTPUT_INVALID."""
        classifier = DefectClassifier()
        result = classifier.classify(AssertionError("assertion failed"))
        assert result == DefectType.OUTPUT_INVALID

    def test_classify_memory_error(self):
        """MemoryError should classify as RESOURCE_EXHAUSTION."""
        classifier = DefectClassifier()
        result = classifier.classify(MemoryError("out of memory"))
        assert result == DefectType.RESOURCE_EXHAUSTION

    def test_classify_connection_error(self):
        """ConnectionError should classify as PROTOCOL_ERROR."""
        classifier = DefectClassifier()
        result = classifier.classify(ConnectionError("connection refused"))
        assert result == DefectType.PROTOCOL_ERROR

    def test_classify_unknown_exception(self):
        """Unknown exception types should classify as UNKNOWN."""
        classifier = DefectClassifier()
        result = classifier.classify(Exception("mystery error"))
        assert result == DefectType.UNKNOWN

    def test_classify_custom_exception_subclass(self):
        """Subclass of a known exception should match parent."""

        class CustomValueError(ValueError):
            pass

        classifier = DefectClassifier()
        result = classifier.classify(CustomValueError("custom"))
        assert result == DefectType.PARAM_ERROR


class TestClassifyWithContext:
    """Tests for classify_with_context method."""

    def test_basic_context_returns_default_severity(self):
        """Empty context should return default severity for defect type."""
        classifier = DefectClassifier()
        defect, severity = classifier.classify_with_context(
            MemoryError("oom"),
            {},
        )
        assert defect == DefectType.RESOURCE_EXHAUSTION
        assert severity == BugSeverity.P0  # Default for RESOURCE_EXHAUSTION

    def test_production_context_escalates_to_p0(self):
        """production=True should escalate to P0."""
        classifier = DefectClassifier()
        defect, severity = classifier.classify_with_context(
            ValueError("bad param"),
            {"production": True},
        )
        assert defect == DefectType.PARAM_ERROR
        assert severity == BugSeverity.P0

    def test_user_facing_context_escalates_to_p1(self):
        """user_facing=True should escalate to P1."""
        classifier = DefectClassifier()
        defect, severity = classifier.classify_with_context(
            RuntimeError("crashed"),
            {"user_facing": True},
        )
        assert defect == DefectType.EXECUTION_FAILURE
        assert severity == BugSeverity.P1

    def test_no_escalation_when_already_higher(self):
        """Context should not de-escalate severity."""
        classifier = DefectClassifier()
        # RESOURCE_EXHAUSTION defaults to P0
        defect, severity = classifier.classify_with_context(
            MemoryError("oom"),
            {"user_facing": True},  # Would be P1, but P0 is higher
        )
        assert severity == BugSeverity.P0

    def test_critical_path_escalates_to_p0(self):
        """critical_path=True should escalate to P0."""
        classifier = DefectClassifier()
        defect, severity = classifier.classify_with_context(
            TimeoutError("slow"),
            {"critical_path": True},
        )
        assert severity == BugSeverity.P0

    def test_security_breach_escalates_to_p0(self):
        """security_breach=True should escalate to P0."""
        classifier = DefectClassifier()
        defect, severity = classifier.classify_with_context(
            PermissionError("denied"),
            {"security_breach": True},
        )
        assert severity == BugSeverity.P0

    def test_data_loss_escalates_to_p0(self):
        """data_loss=True should escalate to P0."""
        classifier = DefectClassifier()
        defect, severity = classifier.classify_with_context(
            RuntimeError("corrupt"),
            {"data_loss": True},
        )
        assert severity == BugSeverity.P0

    def test_retry_exhausted_escalates_to_p1(self):
        """retry_exhausted=True should escalate to P1."""
        classifier = DefectClassifier()
        defect, severity = classifier.classify_with_context(
            ConnectionError("failed"),
            {"retry_exhausted": True},
        )
        assert severity == BugSeverity.P1

    def test_cascade_escalates_to_p1(self):
        """cascade=True should escalate to P1."""
        classifier = DefectClassifier()
        defect, severity = classifier.classify_with_context(
            ImportError("missing"),
            {"cascade": True},
        )
        assert severity == BugSeverity.P1


class TestSuggestFix:
    """Tests for suggest_fix method."""

    def test_suggest_fix_returns_string(self):
        """suggest_fix should return a non-empty string."""
        classifier = DefectClassifier()
        for defect_type in DefectType:
            suggestion = classifier.suggest_fix(defect_type)
            assert isinstance(suggestion, str)
            assert len(suggestion) > 0

    def test_suggest_fix_param_error(self):
        """PARAM_ERROR should suggest parameter validation."""
        classifier = DefectClassifier()
        suggestion = classifier.suggest_fix(DefectType.PARAM_ERROR)
        assert "Validate" in suggestion or "parameter" in suggestion.lower()

    def test_suggest_fix_timeout(self):
        """TIMEOUT should suggest timeout adjustment."""
        classifier = DefectClassifier()
        suggestion = classifier.suggest_fix(DefectType.TIMEOUT)
        assert "timeout" in suggestion.lower()

    def test_suggest_fix_unknown(self):
        """UNKNOWN should suggest adding context."""
        classifier = DefectClassifier()
        suggestion = classifier.suggest_fix(DefectType.UNKNOWN)
        assert "context" in suggestion.lower() or "classification" in suggestion.lower()


class TestDomainExceptions:
    """Tests for domain-specific exception mapping."""

    def test_skill_not_found_error(self):
        """SkillNotFoundError should classify as DEPENDENCY_MISSING."""
        from skillpool.registry import SkillNotFoundError

        classifier = DefectClassifier()
        result = classifier.classify(SkillNotFoundError("skill-123"))
        assert result == DefectType.DEPENDENCY_MISSING

    def test_supply_chain_evidence_missing_error(self):
        """SupplyChainEvidenceMissingError should classify as PERMISSION_BREACH."""
        from skillpool.registry import SupplyChainEvidenceMissingError

        classifier = DefectClassifier()
        result = classifier.classify(SupplyChainEvidenceMissingError("no sbom"))
        assert result == DefectType.PERMISSION_BREACH

    def test_illegal_state_transition_error(self):
        """IllegalStateTransitionError should classify as STATE_CORRUPTION."""
        from skillpool.registry import IllegalStateTransitionError

        classifier = DefectClassifier()
        result = classifier.classify(IllegalStateTransitionError("bad transition"))
        assert result == DefectType.STATE_CORRUPTION

    def test_audit_unavailable_error(self):
        """AuditUnavailableError should classify as GATE_DENIED."""
        from skillpool.audit import AuditUnavailableError

        classifier = DefectClassifier()
        result = classifier.classify(AuditUnavailableError("audit down"))
        assert result == DefectType.GATE_DENIED
