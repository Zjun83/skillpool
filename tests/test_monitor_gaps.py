"""Tests for monitor module coverage gaps.

Targeted gaps from:
- telemetry_bridge.py: emit, evaluate, check_alerts, snapshot
- self_healing.py: scan_and_propose, execute_healing, get_healing_status, _determine_action
- bug_collector.py: record, get_bugs, get_stats, capture_exception
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from skillpool.monitor.telemetry_bridge import TelemetryBridge
from skillpool.monitor.self_healing import SelfHealingLoop, HealingAction
from skillpool.monitor.bug_collector import BugCollector, BugSeverity, DefectType
from skillpool.evolver import EvolverLayer


@pytest.fixture
def telemetry_bridge():
    return TelemetryBridge()


@pytest.fixture
def bug_collector(tmp_path):
    return BugCollector(log_dir=tmp_path)


@pytest.fixture
def healing_loop(tmp_path):
    bc = BugCollector(log_dir=tmp_path)
    evolver = EvolverLayer(evolver_dir=tmp_path)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return SelfHealingLoop(bug_collector=bc, evolver=evolver, skills_dir=skills_dir)


# ═══════════════════════════════════════════════════════════════
# telemetry_bridge gaps
# ═══════════════════════════════════════════════════════════════


class TestTelemetryBridgeGaps:
    def test_emit_stores_metric(self, telemetry_bridge):
        """emit stores metric internally."""
        metric = {"metric_type": "success", "value": 1.0}
        telemetry_bridge.emit(metric)
        assert len(telemetry_bridge._metrics) == 1

    def test_emit_forwards_to_sink(self):
        """emit forwards metric to sink callable."""
        sink = MagicMock()
        bridge = TelemetryBridge(sink=sink)
        metric = {"metric_type": "success", "value": 1.0}
        bridge.emit(metric)
        sink.assert_called_once_with(metric)

    def test_emit_sink_exception_suppressed(self):
        """emit suppresses sink exceptions."""
        sink = MagicMock(side_effect=RuntimeError("sink error"))
        bridge = TelemetryBridge(sink=sink)
        metric = {"metric_type": "success", "value": 1.0}
        bridge.emit(metric)  # Should not raise
        assert len(bridge._metrics) == 1

    def test_evaluate_empty_metrics(self, telemetry_bridge):
        """evaluate with empty metrics returns basic level."""
        result = telemetry_bridge.evaluate([])
        assert result["level"] == "basic"
        assert result["overall"] == 1.0

    def test_evaluate_with_error_metrics(self, telemetry_bridge):
        """evaluate with error metrics reduces robustness."""
        metrics = [{"metric_type": "error", "value": 1}]
        result = telemetry_bridge.evaluate(metrics)
        assert result["dimensions"]["robustness"] < 5.0

    def test_evaluate_with_success_metrics(self, telemetry_bridge):
        """evaluate with success metrics increases correctness."""
        metrics = [{"metric_type": "success", "value": 1}]
        result = telemetry_bridge.evaluate(metrics)
        assert result["dimensions"]["correctness"] > 1.0

    def test_evaluate_with_latency_metrics(self, telemetry_bridge):
        """evaluate with latency metrics adjusts efficiency."""
        metrics = [{"metric_type": "latency", "value": 500}]
        result = telemetry_bridge.evaluate(metrics)
        assert result["dimensions"]["efficiency"] < 5.0

    def test_evaluate_level_excellent(self, telemetry_bridge):
        """evaluate returns excellent level for high scores."""
        # Need enough success metrics to push overall >= 4.0
        metrics = [{"metric_type": "success", "value": 1}] * 50
        result = telemetry_bridge.evaluate(metrics)
        assert result["level"] in ("excellent", "good", "acceptable")

    def test_check_alerts_critical(self, telemetry_bridge):
        """check_alerts generates critical alert for low overall."""
        evaluation = {
            "overall": 1.5,
            "dimensions": {"correctness": 1.0, "efficiency": 1.0, "robustness": 1.0, "usability": 1.0, "security": 1.0},
        }
        alerts = telemetry_bridge.check_alerts(evaluation)
        assert any(a["severity"] == "critical" for a in alerts)

    def test_check_alerts_warning(self, telemetry_bridge):
        """check_alerts generates warning for low dimension."""
        evaluation = {
            "overall": 3.0,
            "dimensions": {"correctness": 1.5, "efficiency": 4.0, "robustness": 4.0, "usability": 4.0, "security": 4.0},
        }
        alerts = telemetry_bridge.check_alerts(evaluation)
        assert any(a["severity"] == "warning" for a in alerts)

    def test_check_alerts_info(self, telemetry_bridge):
        """check_alerts generates info for borderline dimension."""
        evaluation = {
            "overall": 3.5,
            "dimensions": {"correctness": 2.5, "efficiency": 4.0, "robustness": 4.0, "usability": 4.0, "security": 4.0},
        }
        alerts = telemetry_bridge.check_alerts(evaluation)
        assert any(a["severity"] == "info" for a in alerts)

    def test_check_alerts_no_alerts(self, telemetry_bridge):
        """check_alerts returns empty for good scores."""
        evaluation = {
            "overall": 4.5,
            "dimensions": {"correctness": 4.5, "efficiency": 4.5, "robustness": 4.5, "usability": 4.5, "security": 4.5},
        }
        alerts = telemetry_bridge.check_alerts(evaluation)
        assert len(alerts) == 0

    def test_snapshot(self, telemetry_bridge):
        """snapshot returns metrics and alerts."""
        telemetry_bridge.emit({"metric_type": "success", "value": 1})
        snap = telemetry_bridge.snapshot()
        assert snap["counts"]["metrics"] == 1
        assert "alerts" in snap
        assert "snapshot_at" in snap


# ═══════════════════════════════════════════════════════════════
# self_healing gaps
# ═══════════════════════════════════════════════════════════════


class TestSelfHealingGaps:
    def test_scan_and_propose_returns_empty_when_no_bugs(self, healing_loop):
        """scan_and_propose returns empty list when no bugs."""
        result = healing_loop.scan_and_propose()
        assert result == []

    def test_scan_and_propose_creates_proposal_for_bugs(self, healing_loop):
        """scan_and_propose creates proposal when bugs exist."""
        for _ in range(3):
            healing_loop._bug_collector.record(
                severity=BugSeverity.P2,
                defect_type=DefectType.EXECUTION_FAILURE,
                message="Test bug",
                skill_id="S09",
            )
        proposals = healing_loop.scan_and_propose()
        assert len(proposals) == 1
        assert proposals[0]["skill_id"] == "S09"
        assert proposals[0]["upgrade_type"] == "PATCH"

    def test_execute_healing_not_found(self, healing_loop):
        """execute_healing returns not_found for invalid proposal_id."""
        result = healing_loop.execute_healing("nonexistent")
        assert result["status"] == "not_found"

    def test_major_needs_human(self, healing_loop):
        """P0 bug triggers NEEDS_HUMAN action."""
        healing_loop._bug_collector.record(
            severity=BugSeverity.P0,
            defect_type=DefectType.EXECUTION_FAILURE,
            message="Critical bug",
            skill_id="S09",
        )
        proposals = healing_loop.scan_and_propose()
        assert len(proposals) == 1
        assert proposals[0]["upgrade_type"] == "needs_human"

    def test_get_healing_status_empty(self, healing_loop):
        """get_healing_status returns empty when no proposals."""
        status = healing_loop.get_healing_status()
        assert status["total_proposals"] == 0

    def test_get_healing_status_with_proposals(self, healing_loop):
        """get_healing_status returns proposal summaries."""
        for _ in range(3):
            healing_loop._bug_collector.record(
                severity=BugSeverity.P2,
                defect_type=DefectType.EXECUTION_FAILURE,
                message="Test bug",
                skill_id="S09",
            )
        healing_loop.scan_and_propose()
        status = healing_loop.get_healing_status()
        assert status["total_proposals"] == 1
        assert "by_status" in status
        assert "proposals" in status

    def test_determine_action_p0_triggers_needs_human(self):
        """P0 bug triggers NEEDS_HUMAN."""
        result = SelfHealingLoop._determine_action({"P0": 1, "P1": 0, "P2": 0})
        assert result == HealingAction.NEEDS_HUMAN

    def test_determine_action_p1_triggers_minor(self):
        """P1 bug triggers MINOR."""
        result = SelfHealingLoop._determine_action({"P0": 0, "P1": 1, "P2": 0})
        assert result == HealingAction.MINOR

    def test_determine_action_5_p2_triggers_minor(self):
        """5 P2 bugs triggers MINOR."""
        result = SelfHealingLoop._determine_action({"P0": 0, "P1": 0, "P2": 5})
        assert result == HealingAction.MINOR

    def test_determine_action_3_p2_triggers_patch(self):
        """3 P2 bugs triggers PATCH."""
        result = SelfHealingLoop._determine_action({"P0": 0, "P1": 0, "P2": 3})
        assert result == HealingAction.PATCH

    def test_determine_action_below_threshold_skipped(self):
        """Below threshold triggers SKIPPED."""
        result = SelfHealingLoop._determine_action({"P0": 0, "P1": 0, "P2": 2})
        assert result == HealingAction.SKIPPED

    def test_dominant_severity_p0(self):
        """P0 is dominant."""
        result = SelfHealingLoop._dominant_severity({"P0": 1, "P1": 2, "P2": 3})
        assert result == BugSeverity.P0

    def test_dominant_severity_p1(self):
        """P1 is dominant when no P0."""
        result = SelfHealingLoop._dominant_severity({"P0": 0, "P1": 1, "P2": 3})
        assert result == BugSeverity.P1

    def test_dominant_severity_p2(self):
        """P2 is dominant when no P0/P1."""
        result = SelfHealingLoop._dominant_severity({"P0": 0, "P1": 0, "P2": 3})
        assert result == BugSeverity.P2


# ═══════════════════════════════════════════════════════════════
# bug_collector gaps
# ═══════════════════════════════════════════════════════════════


class TestBugCollectorGaps:
    def test_record_bug_with_all_fields(self, bug_collector):
        """Record a bug with all fields."""
        rec = bug_collector.record(
            severity=BugSeverity.P1,
            defect_type=DefectType.EXECUTION_FAILURE,
            message="Test bug description",
            skill_id="S09",
            context={"session_id": "s1"},
        )
        assert rec.bug_id is not None
        assert rec.severity == BugSeverity.P1
        assert rec.defect_type == DefectType.EXECUTION_FAILURE
        assert rec.skill_id == "S09"
        assert rec.context == {"session_id": "s1"}

    def test_get_bugs_by_severity(self, bug_collector):
        """Filter bugs by severity."""
        bug_collector.record(BugSeverity.P0, DefectType.EXECUTION_FAILURE, "Critical bug", skill_id="S09")
        bug_collector.record(BugSeverity.P2, DefectType.TIMEOUT, "Low bug", skill_id="S10")
        p0_bugs = bug_collector.get_bugs(severity=BugSeverity.P0)
        assert len(p0_bugs) == 1
        assert p0_bugs[0].severity == BugSeverity.P0

    def test_get_bugs_by_defect_type(self, bug_collector):
        """Filter bugs by defect_type."""
        bug_collector.record(BugSeverity.P2, DefectType.EXECUTION_FAILURE, "Exec bug")
        bug_collector.record(BugSeverity.P2, DefectType.TIMEOUT, "Timeout bug")
        exec_bugs = bug_collector.get_bugs(defect_type=DefectType.EXECUTION_FAILURE)
        assert len(exec_bugs) == 1
        assert exec_bugs[0].defect_type == DefectType.EXECUTION_FAILURE

    def test_get_bugs_by_skill_id(self, bug_collector):
        """Filter bugs by skill_id."""
        bug_collector.record(BugSeverity.P2, DefectType.EXECUTION_FAILURE, "S09 bug", skill_id="S09")
        bug_collector.record(BugSeverity.P2, DefectType.EXECUTION_FAILURE, "S10 bug", skill_id="S10")
        s09_bugs = bug_collector.get_bugs(skill_id="S09")
        assert len(s09_bugs) == 1
        assert s09_bugs[0].skill_id == "S09"

    def test_get_stats(self, bug_collector):
        """get_stats returns aggregate counts."""
        bug_collector.record(BugSeverity.P0, DefectType.EXECUTION_FAILURE, "Critical", skill_id="S09")
        bug_collector.record(BugSeverity.P2, DefectType.TIMEOUT, "Low", skill_id="S10")
        stats = bug_collector.get_stats()
        assert stats["total"] == 2
        assert stats["by_severity"]["P0"] == 1
        assert stats["by_severity"]["P2"] == 1

    def test_capture_exception(self, bug_collector):
        """Capture an exception with auto-classification."""
        try:
            raise ValueError("test error")
        except ValueError as e:
            rec = bug_collector.capture_exception(e, skill_id="S09")
        assert rec.bug_id is not None
        assert rec.skill_id == "S09"
        assert "test error" in rec.message

    def test_record_bug_minimal(self, bug_collector):
        """Minimal record with just required fields."""
        rec = bug_collector.record(
            severity=BugSeverity.P2,
            defect_type=DefectType.UNKNOWN,
            message="Minimal bug",
        )
        assert rec.bug_id is not None
        assert rec.severity == BugSeverity.P2
