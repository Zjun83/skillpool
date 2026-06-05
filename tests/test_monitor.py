"""Tests for Monitor Layer — Runtime observability, SLO, and evaluation."""

from __future__ import annotations

import pytest

from skillpool.monitor import (
    Alert,
    AlertSeverity,
    EvaluationLevel,
    FiveDimensionEvaluation,
    Metric,
    MetricType,
    MonitorLayer,
    TelemetryBridge,
)


class TestMetricType:
    def test_values(self):
        assert MetricType.COUNTER == "counter"
        assert MetricType.GAUGE == "gauge"
        assert MetricType.HISTOGRAM == "histogram"


class TestAlertSeverity:
    def test_values(self):
        assert AlertSeverity.INFO == "info"
        assert AlertSeverity.WARNING == "warning"
        assert AlertSeverity.ERROR == "error"
        assert AlertSeverity.CRITICAL == "critical"


class TestEvaluationLevel:
    def test_values(self):
        assert EvaluationLevel.GOOD == "Good"
        assert EvaluationLevel.AVERAGE == "Average"
        assert EvaluationLevel.POOR == "Poor"


class TestFiveDimensionEvaluation:
    def test_overall_score_calculation(self):
        eval_ = FiveDimensionEvaluation(
            skill_id="s1",
            safety=EvaluationLevel.GOOD,
            safety_score=0.9,
            safety_reason="ok",
            completeness=EvaluationLevel.GOOD,
            completeness_score=0.8,
            completeness_reason="ok",
            executability=EvaluationLevel.GOOD,
            executability_score=0.7,
            executability_reason="ok",
            maintainability=EvaluationLevel.AVERAGE,
            maintainability_score=0.5,
            maintainability_reason="avg",
            cost_awareness=EvaluationLevel.GOOD,
            cost_awareness_score=0.8,
            cost_awareness_reason="ok",
        )
        expected = 0.9 * 0.25 + 0.8 * 0.20 + 0.7 * 0.25 + 0.5 * 0.15 + 0.8 * 0.15
        assert abs(eval_.overall_score - expected) < 0.01


class TestMetric:
    def test_creation(self):
        m = Metric(name="latency", value=100.0, metric_type=MetricType.HISTOGRAM)
        assert m.name == "latency"
        assert m.value == 100.0


class TestAlert:
    def test_creation(self):
        a = Alert(alert_id="a1", severity=AlertSeverity.ERROR, message="fail")
        assert a.alert_id == "a1"
        assert a.severity == AlertSeverity.ERROR


class TestMonitorLayer:
    def test_record_metric(self):
        mon = MonitorLayer()
        mon.record_metric("cpu", 0.5)
        metrics = mon.get_metrics("cpu")
        assert "cpu" in metrics
        assert len(metrics["cpu"]) == 1

    def test_record_latency(self):
        mon = MonitorLayer()
        mon.record_latency("s1", 100.0, True)
        metrics = mon.get_metrics("skill_execution_latency_ms")
        assert len(metrics["skill_execution_latency_ms"]) == 1

    def test_latency_slo_breach_alert(self):
        mon = MonitorLayer()
        mon.set_slo_target("s1.latency_p99", 50.0)
        mon.record_latency("s1", 100.0, True)
        alerts = mon.get_alerts()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_record_error(self):
        mon = MonitorLayer()
        mon.record_error("s1", "timeout", "connection timed out")
        alerts = mon.get_alerts()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ERROR

    def test_check_slo_compliance_no_data(self):
        mon = MonitorLayer()
        mon.set_slo_target("s1.latency_p99", 100.0)
        compliance = mon.check_slo_compliance("s1")
        assert compliance["latency_p99"] is True

    def test_check_slo_compliance_pass(self):
        mon = MonitorLayer()
        mon.set_slo_target("s1.latency_p99", 1000.0)
        mon.record_latency("s1", 50.0, True)
        compliance = mon.check_slo_compliance("s1")
        assert compliance["latency_p99"] is True

    def test_get_alerts_filtered_by_skill(self):
        mon = MonitorLayer()
        mon.record_error("s1", "err", "msg1")
        mon.record_error("s2", "err", "msg2")
        alerts = mon.get_alerts(skill_id="s1")
        assert len(alerts) == 1

    def test_get_alerts_filtered_by_severity(self):
        mon = MonitorLayer()
        mon.record_error("s1", "err", "msg")
        mon.set_slo_target("s1.latency_p99", 1.0)
        mon.record_latency("s1", 100.0, True)
        alerts = mon.get_alerts(severity=AlertSeverity.WARNING)
        assert all(a.severity == AlertSeverity.WARNING for a in alerts)

    def test_evaluate_skill(self):
        mon = MonitorLayer()
        eval_ = mon.evaluate_skill(
            "s1",
            {
                "error_rate": 0.05,
                "security_issues": 0,
                "coverage": 0.9,
                "doc_completeness": 0.8,
                "p99_latency_ms": 200,
                "update_frequency_days": 10,
                "resource_efficiency": 0.7,
            },
        )
        assert eval_.skill_id == "s1"
        assert eval_.overall_score > 0
        assert eval_.safety == EvaluationLevel.GOOD

    def test_evaluate_skill_with_security_issues(self):
        mon = MonitorLayer()
        eval_ = mon.evaluate_skill(
            "s1",
            {
                "error_rate": 0.1,
                "security_issues": 2,
                "coverage": 0.5,
                "doc_completeness": 0.5,
                "p99_latency_ms": 500,
                "update_frequency_days": 30,
                "resource_efficiency": 0.5,
            },
        )
        assert eval_.safety_score < 0.5  # Penalty for security issues

    def test_get_evaluation(self):
        mon = MonitorLayer()
        eval_ = mon.evaluate_skill(
            "s1",
            {
                "error_rate": 0.0,
                "security_issues": 0,
                "coverage": 1.0,
                "doc_completeness": 1.0,
                "p99_latency_ms": 10,
                "update_frequency_days": 1,
                "resource_efficiency": 1.0,
            },
        )
        found = mon.get_evaluation("s1")
        assert found is eval_

    def test_get_evaluation_not_found(self):
        mon = MonitorLayer()
        assert mon.get_evaluation("nonexistent") is None

    def test_record_trajectory(self):
        mon = MonitorLayer()
        mon.record_trajectory("s1", {"steps": 5}, prm_score=0.8)
        agg = mon.aggregate_trajectories("s1")
        assert agg["trajectory_count"] == 1
        assert agg["avg_prm_score"] == 0.8

    def test_aggregate_trajectories_empty(self):
        mon = MonitorLayer()
        agg = mon.aggregate_trajectories("s1")
        assert agg["trajectory_count"] == 0

    def test_aggregate_trajectories_with_errors(self):
        mon = MonitorLayer()
        mon.record_trajectory("s1", {"error": True, "error_type": "timeout"})
        mon.record_trajectory("s1", {"steps": 5})
        agg = mon.aggregate_trajectories("s1")
        assert agg["trajectory_count"] == 2
        assert agg["error_count"] == 1
        assert "timeout" in agg["error_patterns"]

    def test_skill_performance_summary(self):
        mon = MonitorLayer()
        mon.record_latency("s1", 50.0, True)
        mon.evaluate_skill(
            "s1",
            {
                "error_rate": 0.0,
                "security_issues": 0,
                "coverage": 1.0,
                "doc_completeness": 1.0,
                "p99_latency_ms": 10,
                "update_frequency_days": 1,
                "resource_efficiency": 1.0,
            },
        )
        summary = mon.get_skill_performance_summary("s1")
        assert summary["skill_id"] == "s1"
        assert summary["five_dimension"] is not None
        assert "trajectory_aggregation" in summary

    def test_p99_calculation(self):
        mon = MonitorLayer()
        values = [float(i) for i in range(1, 101)]
        p99 = mon._calculate_p99(values)
        assert p99 >= 99.0

    def test_p99_empty(self):
        mon = MonitorLayer()
        assert mon._calculate_p99([]) == 0.0


class TestTelemetryBridge:
    def test_emit_stores_metric(self):
        bridge = TelemetryBridge()
        bridge.emit({"name": "latency", "value": 100})
        snap = bridge.snapshot()
        assert snap["counts"]["metrics"] == 1

    def test_emit_forwards_to_sink(self):
        received = []
        bridge = TelemetryBridge(sink=lambda m: received.append(m))
        bridge.emit({"name": "test"})
        assert len(received) == 1

    def test_sink_exception_swallowed(self):
        def bad_sink(m):
            raise RuntimeError("fail")

        bridge = TelemetryBridge(sink=bad_sink)
        bridge.emit({"name": "test"})  # Should not raise

    def test_evaluate_empty(self):
        bridge = TelemetryBridge()
        result = bridge.evaluate([])
        assert result["overall"] == 1.0
        assert result["level"] == "basic"

    def test_evaluate_with_metrics(self):
        bridge = TelemetryBridge()
        metrics = [
            {"metric_type": "success", "value": 1},
            {"metric_type": "latency", "value": 100},
        ]
        result = bridge.evaluate(metrics)
        assert "dimensions" in result
        assert result["overall"] > 0

    def test_check_alerts_critical(self):
        bridge = TelemetryBridge()
        eval_result = {
            "dimensions": {"correctness": 1.0, "efficiency": 1.0, "robustness": 1.0, "usability": 1.0, "security": 1.0},
            "overall": 1.5,
        }
        alerts = bridge.check_alerts(eval_result)
        assert any(a["severity"] == "critical" for a in alerts)

    def test_check_alerts_warning(self):
        bridge = TelemetryBridge()
        eval_result = {
            "dimensions": {"correctness": 1.5, "efficiency": 3.0, "robustness": 3.0, "usability": 3.0, "security": 3.0},
            "overall": 2.7,
        }
        alerts = bridge.check_alerts(eval_result)
        assert any(a["severity"] == "warning" for a in alerts)

    def test_snapshot(self):
        bridge = TelemetryBridge()
        bridge.emit({"name": "test"})
        snap = bridge.snapshot()
        assert "metrics" in snap
        assert "alerts" in snap
        assert "counts" in snap


class TestErrorBudget:
    """Tests for error budget policy and burn rate."""

    def test_set_error_budget(self):
        mon = MonitorLayer()
        mon.set_error_budget("S09", slo_target=0.999)
        status = mon.get_error_budget_status("S09")
        assert status is not None
        assert status["slo_target"] == 0.999
        assert status["error_budget"] == pytest.approx(0.001, abs=0.0001)

    def test_error_budget_consumed(self):
        mon = MonitorLayer()
        mon.set_error_budget("S09", slo_target=0.99)
        # 100 requests, 1 failure → 1% error rate = consumed 100% of budget
        for _ in range(99):
            mon.record_budget_request("S09", success=True)
        mon.record_budget_request("S09", success=False)
        status = mon.get_error_budget_status("S09")
        assert status["consumed_pct"] == pytest.approx(1.0, abs=0.01)

    def test_error_budget_remaining(self):
        mon = MonitorLayer()
        mon.set_error_budget("S09", slo_target=0.999)
        for _ in range(1000):
            mon.record_budget_request("S09", success=True)
        status = mon.get_error_budget_status("S09")
        assert status["remaining_pct"] == 1.0  # No errors consumed

    def test_burn_rate_calculation(self):
        mon = MonitorLayer()
        mon.set_error_budget("S09", slo_target=0.99)
        # 50 failures out of 1000 = 5% error rate
        for _ in range(950):
            mon.record_budget_request("S09", success=True)
        for _ in range(50):
            mon.record_budget_request("S09", success=False)
        status = mon.get_error_budget_status("S09")
        # burn_rate = actual_error_rate / error_budget = 0.05 / 0.01 = 5.0
        assert status["burn_rate"] == pytest.approx(5.0, abs=0.1)

    def test_no_budget_returns_none(self):
        mon = MonitorLayer()
        assert mon.get_error_budget_status("nonexistent") is None

    def test_record_request_without_budget(self):
        mon = MonitorLayer()
        # Should not raise
        mon.record_budget_request("S09", success=False)


class TestRecordBug:
    """Tests for record_bug method (BugCollector integration)."""

    def test_record_bug_creates_bug_record(self):
        mon = MonitorLayer()
        from skillpool.monitor.bug_collector import BugSeverity, DefectType

        record = mon.record_bug(
            severity=BugSeverity.P2,
            defect_type=DefectType.PARAM_ERROR,
            message="test bug",
            skill_id="S09",
        )
        assert record.bug_id.startswith("bug-")
        assert record.severity == BugSeverity.P2
        assert record.defect_type == DefectType.PARAM_ERROR
        assert record.skill_id == "S09"

    def test_record_bug_with_context(self):
        mon = MonitorLayer()
        from skillpool.monitor.bug_collector import BugSeverity, DefectType

        record = mon.record_bug(
            severity=BugSeverity.P1,
            defect_type=DefectType.EXECUTION_FAILURE,
            message="execution failure",
            skill_id="S13a",
            context={"checkpoint": "L3"},
        )
        assert record.context.get("checkpoint") == "L3"


class TestScoreToLevel:
    """Tests for _score_to_level conversion."""

    def test_good_threshold(self):
        mon = MonitorLayer()
        assert mon._score_to_level(0.7) == EvaluationLevel.GOOD
        assert mon._score_to_level(0.9) == EvaluationLevel.GOOD
        assert mon._score_to_level(1.0) == EvaluationLevel.GOOD

    def test_average_threshold(self):
        mon = MonitorLayer()
        assert mon._score_to_level(0.4) == EvaluationLevel.AVERAGE
        assert mon._score_to_level(0.5) == EvaluationLevel.AVERAGE
        assert mon._score_to_level(0.69) == EvaluationLevel.AVERAGE

    def test_poor_threshold(self):
        mon = MonitorLayer()
        assert mon._score_to_level(0.0) == EvaluationLevel.POOR
        assert mon._score_to_level(0.39) == EvaluationLevel.POOR

    def test_boundary_at_0_4(self):
        mon = MonitorLayer()
        assert mon._score_to_level(0.399) == EvaluationLevel.POOR
        assert mon._score_to_level(0.4) == EvaluationLevel.AVERAGE

    def test_boundary_at_0_7(self):
        mon = MonitorLayer()
        assert mon._score_to_level(0.699) == EvaluationLevel.AVERAGE
        assert mon._score_to_level(0.7) == EvaluationLevel.GOOD
