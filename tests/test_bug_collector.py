"""Tests for BugCollector and pytest hook integration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from skillpool.monitor.bug_collector import BugCollector, BugRecord, BugSeverity, DefectType


@pytest.fixture(autouse=True)
def isolated_collector(tmp_path):
    """Reset BugCollector and use temp log path for each test."""
    # Reset the module-level collector in conftest
    import conftest
    conftest._collector = None

    # Create a fresh collector with temp log dir
    log_dir = tmp_path / "logs"
    yield log_dir
    # Cleanup is automatic with tmp_path


class TestDefectType:
    """Tests for DefectType classification."""

    def test_defect_types_exist(self):
        """Verify all 11 defect types are defined."""
        expected = {
            "PARAM_ERROR",
            "PERMISSION_BREACH",
            "TIMEOUT",
            "DEPENDENCY_MISSING",
            "EXECUTION_FAILURE",
            "OUTPUT_INVALID",
            "STATE_CORRUPTION",
            "RESOURCE_EXHAUSTION",
            "GATE_DENIED",
            "PROTOCOL_ERROR",
            "UNKNOWN",
        }
        actual = {dt.value for dt in DefectType}
        assert expected == actual


class TestBugSeverity:
    """Tests for BugSeverity levels."""

    def test_severity_levels(self):
        assert BugSeverity.P0.value == "P0"
        assert BugSeverity.P1.value == "P1"
        assert BugSeverity.P2.value == "P2"


class TestBugRecord:
    """Tests for BugRecord dataclass."""

    def test_to_dict(self):
        record = BugRecord(
            bug_id="bug-abc123",
            timestamp="2026-05-31T00:00:00Z",
            severity=BugSeverity.P2,
            defect_type=DefectType.OUTPUT_INVALID,
            message="test error",
        )
        d = record.to_dict()
        assert d["bug_id"] == "bug-abc123"
        assert d["severity"] == "P2"
        assert d["defect_type"] == "OUTPUT_INVALID"

    def test_to_jsonl(self):
        record = BugRecord(
            bug_id="bug-xyz",
            timestamp="2026-05-31T00:00:00Z",
            severity=BugSeverity.P1,
            defect_type=DefectType.TIMEOUT,
            message="timeout error",
        )
        j = record.to_jsonl()
        parsed = json.loads(j)
        assert parsed["bug_id"] == "bug-xyz"
        assert parsed["defect_type"] == "TIMEOUT"

    def test_default_fields(self):
        record = BugRecord(
            bug_id="bug-test",
            timestamp="2026-05-31T00:00:00Z",
            severity=BugSeverity.P2,
            defect_type=DefectType.UNKNOWN,
            message="msg",
        )
        assert record.skill_id == ""
        assert record.trace_id == ""
        assert record.traceback == ""
        assert record.context == {}


class TestBugCollector:
    """Tests for BugCollector 4-stage pipeline."""

    def test_record_creates_bug(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        record = collector.record(
            severity=BugSeverity.P2,
            defect_type=DefectType.PARAM_ERROR,
            message="test error",
        )
        assert record.bug_id.startswith("bug-")
        assert record.severity == BugSeverity.P2
        assert record.defect_type == DefectType.PARAM_ERROR
        assert record.trace_id != ""  # Auto-enriched

    def test_record_writes_to_jsonl(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        collector.record(
            severity=BugSeverity.P2,
            defect_type=DefectType.OUTPUT_INVALID,
            message="assertion failed",
        )
        log_path = isolated_collector / "bugs.jsonl"
        assert log_path.exists()
        content = log_path.read_text().strip()
        assert len(content) > 0
        parsed = json.loads(content)
        assert parsed["defect_type"] == "OUTPUT_INVALID"

    def test_capture_exception(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        try:
            raise ValueError("bad value")
        except ValueError as e:
            record = collector.capture_exception(e)

        assert record.defect_type == DefectType.PARAM_ERROR
        assert "bad value" in record.message
        assert "ValueError" in record.context.get("exc_type", "")

    def test_capture_timeout(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        try:
            raise TimeoutError("operation timed out")
        except TimeoutError as e:
            record = collector.capture_exception(e)

        assert record.defect_type == DefectType.TIMEOUT

    def test_capture_assertion(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        try:
            assert False, "assertion failed"
        except AssertionError as e:
            record = collector.capture_exception(e)

        assert record.defect_type == DefectType.OUTPUT_INVALID

    def test_get_bugs_filtering(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        collector.record(BugSeverity.P0, DefectType.RESOURCE_EXHAUSTION, "critical")
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "minor")
        collector.record(BugSeverity.P1, DefectType.TIMEOUT, "timeout")

        p0_bugs = collector.get_bugs(severity=BugSeverity.P0)
        assert len(p0_bugs) == 1
        assert p0_bugs[0].message == "critical"

        timeout_bugs = collector.get_bugs(defect_type=DefectType.TIMEOUT)
        assert len(timeout_bugs) == 1

    def test_get_stats(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        collector.record(BugSeverity.P0, DefectType.RESOURCE_EXHAUSTION, "c1")
        collector.record(BugSeverity.P0, DefectType.STATE_CORRUPTION, "c2")
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "m1")

        stats = collector.get_stats()
        assert stats["total"] == 3
        assert stats["by_severity"]["P0"] == 2
        assert stats["by_severity"]["P2"] == 1
        assert stats["by_defect_type"]["RESOURCE_EXHAUSTION"] == 1

    def test_sample_rate_filtering(self, isolated_collector):
        # sample_rate=0.0 means nothing gets persisted
        collector = BugCollector(log_dir=isolated_collector, sample_rate=0.0)
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "filtered")

        # Bug is in memory but not persisted
        assert len(collector.get_bugs()) == 1
        log_path = isolated_collector / "bugs.jsonl"
        assert not log_path.exists()

    def test_before_persist_hook(self, isolated_collector):
        def drop_all(rec: BugRecord) -> bool:
            return False  # Reject all

        collector = BugCollector(
            log_dir=isolated_collector,
            before_persist=drop_all,
        )
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "hooked")

        assert len(collector.get_bugs()) == 1
        log_path = isolated_collector / "bugs.jsonl"
        assert not log_path.exists()

    def test_creates_log_directory(self, tmp_path):
        deep_dir = tmp_path / "deep" / "nested"
        collector = BugCollector(log_dir=deep_dir)
        collector.record(BugSeverity.P2, DefectType.UNKNOWN, "test")

        assert deep_dir.exists()
        assert (deep_dir / "bugs.jsonl").exists()


class TestExceptionClassification:
    """Tests for exception type to DefectType mapping."""

    def test_typeerror_is_param_error(self):
        assert BugCollector._classify_exception(TypeError()) == DefectType.PARAM_ERROR

    def test_valueerror_is_param_error(self):
        assert BugCollector._classify_exception(ValueError()) == DefectType.PARAM_ERROR

    def test_timeout_is_timeout(self):
        assert BugCollector._classify_exception(TimeoutError()) == DefectType.TIMEOUT

    def test_importerror_is_dependency_missing(self):
        assert BugCollector._classify_exception(ImportError()) == DefectType.DEPENDENCY_MISSING

    def test_permissionerror_is_permission_breach(self):
        assert BugCollector._classify_exception(PermissionError()) == DefectType.PERMISSION_BREACH

    def test_runtimeerror_is_execution_failure(self):
        assert BugCollector._classify_exception(RuntimeError()) == DefectType.EXECUTION_FAILURE

    def test_memoryerror_is_resource_exhaustion(self):
        assert BugCollector._classify_exception(MemoryError()) == DefectType.RESOURCE_EXHAUSTION

    def test_unknown_exception(self):
        class CustomError(Exception):
            pass
        assert BugCollector._classify_exception(CustomError()) == DefectType.UNKNOWN


class TestSeverityFromException:
    """Tests for severity heuristics from exception type."""

    def test_memoryerror_is_p0(self):
        assert BugCollector._severity_from_exception(MemoryError()) == BugSeverity.P0

    def test_permissionerror_is_p1(self):
        assert BugCollector._severity_from_exception(PermissionError()) == BugSeverity.P1

    def test_importerror_is_p1(self):
        assert BugCollector._severity_from_exception(ImportError()) == BugSeverity.P1

    def test_valueerror_is_p2(self):
        assert BugCollector._severity_from_exception(ValueError()) == BugSeverity.P2


class TestExceptHook:
    """Tests for install_excepthook / uninstall_excepthook."""

    def test_install_and_uninstall(self, isolated_collector):
        """install_excepthook and uninstall_excepthook round-trip."""
        collector = BugCollector(log_dir=isolated_collector)
        original = sys.excepthook

        collector.install_excepthook()
        assert sys.excepthook is not original
        assert collector._original_excepthook is original

        collector.uninstall_excepthook()
        assert sys.excepthook is original
        assert collector._original_excepthook is None

    def test_install_twice_is_noop(self, isolated_collector):
        """Installing excepthook twice should not overwrite the original."""
        collector = BugCollector(log_dir=isolated_collector)
        original = sys.excepthook

        collector.install_excepthook()
        hook1 = sys.excepthook

        collector.install_excepthook()
        # Should still be the same hook (no double-wrap)
        assert sys.excepthook is hook1

        # Cleanup
        collector.uninstall_excepthook()
        assert sys.excepthook is original

    def test_uninstall_without_install_is_noop(self, isolated_collector):
        """Uninstalling without installing should be a no-op."""
        collector = BugCollector(log_dir=isolated_collector)
        original = sys.excepthook
        collector.uninstall_excepthook()
        assert sys.excepthook is original


class TestEnrichWithEnv:
    """Tests for _enrich attaching environment context."""

    def test_skillpool_env_attached(self, isolated_collector, monkeypatch):
        """SKILLPOOL_ENV should be attached to bug context."""
        monkeypatch.setenv("SKILLPOOL_ENV", "production")
        collector = BugCollector(log_dir=isolated_collector)
        record = collector.record(
            severity=BugSeverity.P2,
            defect_type=DefectType.PARAM_ERROR,
            message="test",
        )
        assert record.context.get("env") == "production"

    def test_no_skillpool_env_no_extra_context(self, isolated_collector, monkeypatch):
        """Without SKILLPOOL_ENV, no env info should be added."""
        monkeypatch.delenv("SKILLPOOL_ENV", raising=False)
        collector = BugCollector(log_dir=isolated_collector)
        record = collector.record(
            severity=BugSeverity.P2,
            defect_type=DefectType.PARAM_ERROR,
            message="test",
        )
        assert "env" not in record.context

    def test_trace_id_auto_generated(self, isolated_collector):
        """Bug without trace_id should get one auto-generated."""
        collector = BugCollector(log_dir=isolated_collector)
        record = collector.record(
            severity=BugSeverity.P2,
            defect_type=DefectType.PARAM_ERROR,
            message="test",
        )
        assert record.trace_id != ""
        assert len(record.trace_id) == 32  # 16 bytes hex


class TestBeforePersistHook:
    """Tests for before_persist hook edge cases."""

    def test_hook_exception_defaults_to_persist(self, isolated_collector):
        """If before_persist hook raises, record should be persisted by default."""
        def bad_hook(rec: BugRecord) -> bool:
            raise RuntimeError("hook crashed")

        collector = BugCollector(
            log_dir=isolated_collector,
            before_persist=bad_hook,
        )
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "hook crash test")

        # Despite hook error, bug should be persisted
        log_path = isolated_collector / "bugs.jsonl"
        assert log_path.exists()

    def test_hook_accept_persists(self, isolated_collector):
        """before_persist returning True should persist."""
        def accept(rec: BugRecord) -> bool:
            return True

        collector = BugCollector(
            log_dir=isolated_collector,
            before_persist=accept,
        )
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "accepted")

        log_path = isolated_collector / "bugs.jsonl"
        assert log_path.exists()


class TestMapSeverity:
    """Tests for _map_severity static method."""

    def test_p0_maps_to_critical(self):
        assert BugCollector._map_severity(BugSeverity.P0) == "CRITICAL"

    def test_p1_maps_to_error(self):
        assert BugCollector._map_severity(BugSeverity.P1) == "ERROR"

    def test_p2_maps_to_warn(self):
        assert BugCollector._map_severity(BugSeverity.P2) == "WARN"


class TestSampleRateClamping:
    """Tests for sample_rate clamping to [0.0, 1.0]."""

    def test_negative_clamped_to_zero(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector, sample_rate=-1.0)
        assert collector._sample_rate == 0.0

    def test_above_one_clamped_to_one(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector, sample_rate=2.0)
        assert collector._sample_rate == 1.0


class TestGetBugsSkillId:
    """Tests for get_bugs filtering by skill_id."""

    def test_filter_by_skill_id(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "a", skill_id="S09")
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "b", skill_id="S13a")
        collector.record(BugSeverity.P2, DefectType.PARAM_ERROR, "c", skill_id="S09")

        s09_bugs = collector.get_bugs(skill_id="S09")
        assert len(s09_bugs) == 2
        assert all(b.skill_id == "S09" for b in s09_bugs)

    def test_combined_filters(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        collector.record(BugSeverity.P0, DefectType.TIMEOUT, "a", skill_id="S09")
        collector.record(BugSeverity.P2, DefectType.TIMEOUT, "b", skill_id="S09")
        collector.record(BugSeverity.P0, DefectType.TIMEOUT, "c", skill_id="S13a")

        bugs = collector.get_bugs(severity=BugSeverity.P0, skill_id="S09")
        assert len(bugs) == 1
        assert bugs[0].message == "a"


class TestRecordWithContext:
    """Tests for record with skill_id and context."""

    def test_record_with_skill_id_and_context(self, isolated_collector):
        collector = BugCollector(log_dir=isolated_collector)
        record = collector.record(
            severity=BugSeverity.P1,
            defect_type=DefectType.EXECUTION_FAILURE,
            message="execution failure",
            skill_id="S09",
            context={"checkpoint": "L3", "agent": "claude-code"},
        )
        assert record.skill_id == "S09"
        assert record.context["checkpoint"] == "L3"
        assert record.context["agent"] == "claude-code"


class TestMoreExceptionClassification:
    """Tests for additional exception classifications."""

    def test_oserror_is_resource_exhaustion(self):
        assert BugCollector._classify_exception(OSError()) == DefectType.RESOURCE_EXHAUSTION

    def test_keyerror_is_param_error(self):
        assert BugCollector._classify_exception(KeyError()) == DefectType.PARAM_ERROR

    def test_connection_refused_is_resource_exhaustion(self):
        assert BugCollector._classify_exception(ConnectionRefusedError()) == DefectType.RESOURCE_EXHAUSTION

    def test_oserror_severity_is_p2(self):
        assert BugCollector._severity_from_exception(OSError()) == BugSeverity.P2


class TestConftestHook:
    """Tests for conftest.py helper functions."""

    def test_classify_error_type_typeerror(self):
        import conftest
        assert conftest._classify_error_type("TypeError") == DefectType.PARAM_ERROR

    def test_classify_error_type_timeout(self):
        import conftest
        assert conftest._classify_error_type("TimeoutError") == DefectType.TIMEOUT

    def test_classify_error_type_assertion(self):
        import conftest
        assert conftest._classify_error_type("AssertionError") == DefectType.OUTPUT_INVALID

    def test_classify_error_type_unknown(self):
        import conftest
        assert conftest._classify_error_type("SomeRandomError") == DefectType.UNKNOWN
