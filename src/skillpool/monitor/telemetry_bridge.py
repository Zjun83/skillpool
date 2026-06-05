"""Telemetry Bridge — Metric emission, evaluation, and alerting.

V4.1 module. Bridges runtime metrics to observability backends.
Architecture constraint:
- TelemetryBridge is observation only, no control
- MUST NOT publish versions or replace Audit
"""

from __future__ import annotations

__all__ = ["TelemetryBridge"]

from collections.abc import Callable
from datetime import UTC, datetime


class TelemetryBridge:
    """Runtime telemetry emission, five-dimension evaluation, and alerting.

    Responsibilities:
    1. Collect and emit Metric objects
    2. Evaluate metric sets against five-dimension model
    3. Generate alerts from evaluation results
    4. Provide metric snapshots for external consumers
    """

    def __init__(self, sink: Callable | None = None) -> None:
        """Initialize TelemetryBridge.

        Args:
            sink: Optional callable that receives each emitted Metric.
                  Signature: sink(metric) -> None
        """
        self._sink = sink
        self._metrics: list[dict] = []
        self._alerts: list[dict] = []

    def emit(self, metric) -> None:
        """Emit a metric to the bridge.

        Stores the metric internally and forwards to the sink if configured.

        Args:
            metric: A Metric object (from skillpool.monitor).
        """
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "metric": metric,
        }
        self._metrics.append(entry)

        if self._sink is not None:
            from contextlib import suppress

            with suppress(Exception):
                self._sink(metric)

    def evaluate(self, metrics: list) -> dict:
        """Evaluate a set of metrics against the five-dimension model.

        Dimensions:
        1. Correctness — accuracy of outputs
        2. Efficiency — resource utilization
        3. Robustness — error handling and resilience
        4. Usability — developer experience
        5. Security — vulnerability resistance

        Args:
            metrics: List of Metric objects to evaluate.

        Returns:
            FiveDimensionEvaluation-compatible dict with scores per dimension.
        """
        scores = {
            "correctness": 1.0,
            "efficiency": 1.0,
            "robustness": 1.0,
            "usability": 1.0,
            "security": 1.0,
        }

        if not metrics:
            return {
                "dimensions": scores,
                "overall": 1.0,
                "level": "basic",
                "evaluated_at": datetime.now(UTC).isoformat(),
            }

        error_count = 0
        latency_sum = 0.0
        latency_count = 0
        success_count = 0
        total_count = len(metrics)

        for m in metrics:
            if isinstance(m, dict):
                mtype = m.get("metric_type", "")
                value = m.get("value", 0)
            else:
                mtype = getattr(m, "metric_type", "")
                value = getattr(m, "value", 0)

            mtype_str = str(mtype).lower()

            if "error" in mtype_str or "fail" in mtype_str:
                error_count += 1
            elif "latency" in mtype_str or "duration" in mtype_str:
                latency_sum += float(value)
                latency_count += 1
            elif "success" in mtype_str:
                success_count += 1

        if total_count > 0:
            scores["correctness"] = round(min(5.0, 1.0 + 4.0 * (success_count / total_count)), 2)
            scores["robustness"] = round(min(5.0, max(1.0, 5.0 - error_count * 0.5)), 2)

        if latency_count > 0:
            avg_latency = latency_sum / latency_count
            scores["efficiency"] = round(min(5.0, max(1.0, 5.0 - avg_latency / 1000)), 2)

        overall = round(sum(scores.values()) / len(scores), 2)

        if overall >= 4.0:
            level = "excellent"
        elif overall >= 3.0:
            level = "good"
        elif overall >= 2.0:
            level = "acceptable"
        else:
            level = "basic"

        return {
            "dimensions": scores,
            "overall": overall,
            "level": level,
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    def check_alerts(self, evaluation: dict) -> list:
        """Generate alerts from evaluation results.

        Args:
            evaluation: FiveDimensionEvaluation dict from evaluate().

        Returns:
            List of Alert dicts with severity and message.
        """
        alerts = []
        dimensions = evaluation.get("dimensions", {})
        overall = evaluation.get("overall", 1.0)

        if overall < 2.0:
            alerts.append(
                {
                    "severity": "critical",
                    "message": f"Overall evaluation critically low: {overall}",
                    "dimension": "overall",
                }
            )

        for dim_name, score in dimensions.items():
            if score < 2.0:
                alerts.append(
                    {
                        "severity": "warning",
                        "message": f"Dimension '{dim_name}' below threshold: {score}",
                        "dimension": dim_name,
                    }
                )
            elif score < 3.0:
                alerts.append(
                    {
                        "severity": "info",
                        "message": f"Dimension '{dim_name}' needs attention: {score}",
                        "dimension": dim_name,
                    }
                )

        self._alerts.extend(alerts)
        return alerts

    def snapshot(self) -> dict:
        """Return a snapshot of all collected metrics and alerts.

        Returns:
            Dict with 'metrics', 'alerts', and 'counts' keys.
        """
        return {
            "metrics": list(self._metrics),
            "alerts": list(self._alerts),
            "counts": {
                "metrics": len(self._metrics),
                "alerts": len(self._alerts),
            },
            "snapshot_at": datetime.now(UTC).isoformat(),
        }
