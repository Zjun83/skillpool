"""Monitor Layer — Runtime observability and SLO tracking.

Architecture constraint:
- Monitor collects OTel telemetry and SLO data
- MUST NOT publish versions or replace Audit
- Monitor is observation only, no control

Open source enhancements:
- Five-dimension evaluation (SkillNet)
- Trajectory aggregation G(s) (SkillClaw)
- PRM scoring support
"""

from __future__ import annotations

__all__ = [
    "Alert",
    "AlertSeverity",
    "BugCollector",
    "BugRecord",
    "BugSeverity",
    "DefectClassifier",
    "DefectType",
    "DefectTypeDetailed",
    "EvaluationLevel",
    "FiveDimensionEvaluation",
    "HealingAction",
    "HealingProposal",
    "HealingStatus",
    "Metric",
    "MetricType",
    "MonitorLayer",
    "SelfHealingLoop",
    "TelemetryBridge",
]

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from skillpool.monitor.telemetry_bridge import TelemetryBridge
from skillpool.monitor.bug_collector import BugCollector as BugCollector
from skillpool.monitor.bug_collector import BugRecord, BugSeverity, DefectType
from skillpool.monitor.defect_classifier import DefectClassifier, DefectType as DefectTypeDetailed
from skillpool.monitor.self_healing import (
    HealingAction,
    HealingProposal,
    HealingStatus,
    SelfHealingLoop,
)


class MetricType(StrEnum):
    """Metric types."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class AlertSeverity(StrEnum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EvaluationLevel(StrEnum):
    """Evaluation quality levels."""

    GOOD = "Good"
    AVERAGE = "Average"
    POOR = "Poor"


@dataclass
class FiveDimensionEvaluation:
    """
    Five-dimension skill evaluation (from SkillNet).

    Dimensions:
    - Safety: Security and isolation quality
    - Completeness: Feature coverage and documentation
    - Executability: Runtime reliability and performance
    - Maintainability: Code quality and update frequency
    - Cost_awareness: Resource efficiency
    """

    skill_id: str
    safety: EvaluationLevel
    safety_score: float
    safety_reason: str

    completeness: EvaluationLevel
    completeness_score: float
    completeness_reason: str

    executability: EvaluationLevel
    executability_score: float
    executability_reason: str

    maintainability: EvaluationLevel
    maintainability_score: float
    maintainability_reason: str

    cost_awareness: EvaluationLevel
    cost_awareness_score: float
    cost_awareness_reason: str

    overall_score: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Calculate overall score from five dimensions."""
        self.overall_score = (
            self.safety_score * 0.25
            + self.completeness_score * 0.20
            + self.executability_score * 0.25
            + self.maintainability_score * 0.15
            + self.cost_awareness_score * 0.15
        )


@dataclass
class Metric:
    """Single metric measurement."""

    name: str
    value: float
    metric_type: MetricType
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Alert:
    """Monitoring alert."""

    alert_id: str
    severity: AlertSeverity
    message: str
    skill_id: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class MonitorLayer:
    """
    Monitor layer — runtime observability and SLO tracking.

    Hard rules:
    - Collects OTel telemetry and SLO data
    - MUST NOT publish versions
    - MUST NOT replace Audit
    - Observation only, no control
    """

    def __init__(self, audit_layer=None) -> None:
        self._audit = audit_layer
        self._metrics: dict[str, list[Metric]] = {}
        self._alerts: list[Alert] = []
        self._slo_targets: dict[str, float] = {}
        self._evaluations: dict[str, FiveDimensionEvaluation] = {}
        self._trajectories: dict[str, list[dict]] = {}
        self._prm_scores: dict[str, list[float]] = {}
        self._error_budgets: dict[str, dict] = {}
        self._bug_collector = BugCollector(audit_layer=audit_layer)

    def record_metric(
        self,
        name: str,
        value: float,
        metric_type: MetricType = MetricType.GAUGE,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record a metric measurement."""
        metric = Metric(
            name=name,
            value=value,
            metric_type=metric_type,
            labels=labels or {},
        )

        if name not in self._metrics:
            self._metrics[name] = []
        self._metrics[name].append(metric)

    def record_latency(
        self,
        skill_id: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Record skill execution latency."""
        self.record_metric(
            name="skill_execution_latency_ms",
            value=latency_ms,
            metric_type=MetricType.HISTOGRAM,
            labels={
                "skill_id": skill_id,
                "success": str(success),
            },
        )

        slo = self._slo_targets.get(f"{skill_id}.latency_p99")
        if slo and latency_ms > slo:
            self._create_alert(
                severity=AlertSeverity.WARNING,
                message=f"Latency SLO breach: {skill_id} latency {latency_ms}ms > SLO {slo}ms",
                skill_id=skill_id,
            )

    def record_error(
        self,
        skill_id: str,
        error_type: str,
        error_message: str,
    ) -> None:
        """Record skill execution error."""
        self.record_metric(
            name="skill_errors_total",
            value=1,
            metric_type=MetricType.COUNTER,
            labels={
                "skill_id": skill_id,
                "error_type": error_type,
            },
        )

        self._create_alert(
            severity=AlertSeverity.ERROR,
            message=f"Skill error: {skill_id} - {error_type}: {error_message}",
            skill_id=skill_id,
            labels={"error_type": error_type},
        )

    def record_bug(
        self,
        severity: BugSeverity,
        defect_type: DefectType,
        message: str,
        skill_id: str | None = None,
        context: dict | None = None,
    ) -> BugRecord:
        """Record a bug via the BugCollector pipeline."""
        return self._bug_collector.record(
            severity=severity,
            defect_type=defect_type,
            message=message,
            skill_id=skill_id,
            context=context,
        )

    def set_slo_target(self, metric_name: str, target: float) -> None:
        """Set SLO target for a metric."""
        self._slo_targets[metric_name] = target

    def check_slo_compliance(self, skill_id: str) -> dict[str, bool]:
        """Check if skill meets SLO targets."""
        compliance = {}

        latency_slo = self._slo_targets.get(f"{skill_id}.latency_p99")
        if latency_slo:
            metrics = self._metrics.get("skill_execution_latency_ms", [])
            skill_metrics = [m for m in metrics if m.labels.get("skill_id") == skill_id]

            if skill_metrics:
                p99 = self._calculate_p99([m.value for m in skill_metrics])
                compliance["latency_p99"] = p99 <= latency_slo
            else:
                compliance["latency_p99"] = True

        error_slo = self._slo_targets.get(f"{skill_id}.error_rate")
        if error_slo:
            compliance["error_rate"] = True

        return compliance

    def _calculate_p99(self, values: list[float]) -> float:
        """Calculate P99 from list of values."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * 0.99)
        return sorted_values[min(index, len(sorted_values) - 1)]

    def _create_alert(
        self,
        severity: AlertSeverity,
        message: str,
        skill_id: str | None = None,
        labels: dict | None = None,
    ) -> Alert:
        """Create and store alert."""
        alert = Alert(
            alert_id=f"alert-{len(self._alerts) + 1}",
            severity=severity,
            message=message,
            skill_id=skill_id,
            labels=labels or {},
        )

        self._alerts.append(alert)

        if self._audit:
            self._audit.append(
                action="create_alert",
                result=severity.value,
            )

        return alert

    def get_alerts(
        self,
        skill_id: str | None = None,
        severity: AlertSeverity | None = None,
    ) -> list[Alert]:
        """Get alerts, optionally filtered."""
        alerts = self._alerts

        if skill_id:
            alerts = [a for a in alerts if a.skill_id == skill_id]

        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        return alerts

    def get_metrics(self, name: str | None = None) -> dict[str, list[Metric]]:
        """Get recorded metrics."""
        if name:
            return {name: self._metrics.get(name, [])}
        return self._metrics

    # === Five-Dimension Evaluation ===

    def evaluate_skill(
        self,
        skill_id: str,
        metrics: dict[str, float],
    ) -> FiveDimensionEvaluation:
        """
        Perform five-dimension evaluation on a skill.

        Args:
            skill_id: Skill to evaluate
            metrics: Dict containing error_rate, security_issues, coverage,
                     doc_completeness, avg_latency_ms, p99_latency_ms,
                     update_frequency_days, resource_efficiency
        """
        safety_score = 1.0 - min(metrics.get("error_rate", 0), 0.5)
        security_issues = metrics.get("security_issues", 0)
        if security_issues > 0:
            safety_score *= 0.5
        safety_level = self._score_to_level(safety_score)
        safety_reason = f"Error rate: {metrics.get('error_rate', 0):.2%}, Security issues: {security_issues}"

        completeness_score = metrics.get("coverage", 0.5) * 0.5 + metrics.get("doc_completeness", 0.5) * 0.5
        completeness_level = self._score_to_level(completeness_score)
        completeness_reason = (
            f"Coverage: {metrics.get('coverage', 0):.2%}, Docs: {metrics.get('doc_completeness', 0):.2%}"
        )

        p99_latency = metrics.get("p99_latency_ms", 1000)
        latency_score = max(0, 1.0 - (p99_latency / 10000))
        success_rate = 1.0 - metrics.get("error_rate", 0)
        executability_score = latency_score * 0.5 + success_rate * 0.5
        executability_level = self._score_to_level(executability_score)
        executability_reason = f"P99 latency: {p99_latency}ms, Success rate: {success_rate:.2%}"

        update_days = metrics.get("update_frequency_days", 30)
        maintain_score = max(0, 1.0 - (update_days / 90))
        maintainability_level = self._score_to_level(maintain_score)
        maintainability_reason = f"Last update: {update_days} days ago"

        resource_eff = metrics.get("resource_efficiency", 0.5)
        cost_awareness_score = resource_eff
        cost_awareness_level = self._score_to_level(cost_awareness_score)
        cost_awareness_reason = f"Resource efficiency: {resource_eff:.2%}"

        evaluation = FiveDimensionEvaluation(
            skill_id=skill_id,
            safety=safety_level,
            safety_score=safety_score,
            safety_reason=safety_reason,
            completeness=completeness_level,
            completeness_score=completeness_score,
            completeness_reason=completeness_reason,
            executability=executability_level,
            executability_score=executability_score,
            executability_reason=executability_reason,
            maintainability=maintainability_level,
            maintainability_score=maintain_score,
            maintainability_reason=maintainability_reason,
            cost_awareness=cost_awareness_level,
            cost_awareness_score=cost_awareness_score,
            cost_awareness_reason=cost_awareness_reason,
        )

        self._evaluations[skill_id] = evaluation
        return evaluation

    def _score_to_level(self, score: float) -> EvaluationLevel:
        """Convert numeric score to evaluation level."""
        if score >= 0.7:
            return EvaluationLevel.GOOD
        elif score >= 0.4:
            return EvaluationLevel.AVERAGE
        else:
            return EvaluationLevel.POOR

    def get_evaluation(self, skill_id: str) -> FiveDimensionEvaluation | None:
        """Get latest five-dimension evaluation for a skill."""
        return self._evaluations.get(skill_id)

    # === Trajectory Aggregation G(s) ===

    def record_trajectory(
        self,
        skill_id: str,
        trajectory: dict,
        prm_score: float | None = None,
    ) -> None:
        """Record an execution trajectory for aggregation."""
        if skill_id not in self._trajectories:
            self._trajectories[skill_id] = []
        self._trajectories[skill_id].append(
            {
                "trajectory": trajectory,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        if prm_score is not None:
            if skill_id not in self._prm_scores:
                self._prm_scores[skill_id] = []
            self._prm_scores[skill_id].append(prm_score)

    def aggregate_trajectories(self, skill_id: str) -> dict:
        """Aggregate trajectories G(s) for a skill (SkillClaw method)."""
        trajectories = self._trajectories.get(skill_id, [])
        prm_scores = self._prm_scores.get(skill_id, [])

        if not trajectories:
            return {"skill_id": skill_id, "trajectory_count": 0}

        avg_prm = sum(prm_scores) / len(prm_scores) if prm_scores else None

        error_patterns = []
        for t in trajectories:
            traj = t.get("trajectory", {})
            if traj.get("error"):
                error_patterns.append(traj.get("error_type", "unknown"))

        success_rate = 1.0 - (len(error_patterns) / len(trajectories)) if trajectories else 1.0

        return {
            "skill_id": skill_id,
            "trajectory_count": len(trajectories),
            "avg_prm_score": avg_prm,
            "success_rate": success_rate,
            "error_patterns": list(set(error_patterns)),
            "error_count": len(error_patterns),
        }

    def get_skill_performance_summary(self, skill_id: str) -> dict:
        """Get comprehensive performance summary for a skill."""
        evaluation = self.get_evaluation(skill_id)
        aggregation = self.aggregate_trajectories(skill_id)
        slo_compliance = self.check_slo_compliance(skill_id)

        return {
            "skill_id": skill_id,
            "five_dimension": evaluation.__dict__ if evaluation else None,
            "trajectory_aggregation": aggregation,
            "slo_compliance": slo_compliance,
        }

    # === Error Budget Policy ===

    def set_error_budget(self, skill_id: str, slo_target: float, window_days: int = 30) -> None:
        """Set error budget for a skill.

        Args:
            skill_id: Skill to set budget for.
            slo_target: SLO target as decimal (e.g., 0.999 for 99.9%).
            window_days: Budget window in days (default 30).
        """
        budget = 1.0 - slo_target  # error budget = 1 - SLO
        self._error_budgets[skill_id] = {
            "slo_target": slo_target,
            "error_budget": budget,
            "window_days": window_days,
            "errors_consumed": 0.0,
            "total_requests": 0,
            "failed_requests": 0,
        }

    def record_budget_request(self, skill_id: str, success: bool) -> None:
        """Record a request against the error budget."""
        budget = self._error_budgets.get(skill_id)
        if not budget:
            return
        budget["total_requests"] += 1
        if not success:
            budget["failed_requests"] += 1
            budget["errors_consumed"] = budget["failed_requests"] / max(budget["total_requests"], 1)

    def get_error_budget_status(self, skill_id: str) -> dict | None:
        """Get error budget status for a skill.

        Returns dict with: slo_target, error_budget, consumed_pct, remaining_pct,
        burn_rate, estimated_exhaustion_days.
        """
        budget = self._error_budgets.get(skill_id)
        if not budget:
            return None

        consumed_pct = budget["errors_consumed"] / budget["error_budget"] if budget["error_budget"] > 0 else 0.0
        remaining_pct = max(0.0, 1.0 - consumed_pct)

        # Burn rate: how fast the budget is being consumed
        # Simple model: consumed_pct / (window_days * progress_ratio)
        actual_error_rate = budget["failed_requests"] / max(budget["total_requests"], 1)
        burn_rate = actual_error_rate / budget["error_budget"] if budget["error_budget"] > 0 else 0.0

        # Estimated exhaustion
        if burn_rate > 0 and remaining_pct > 0:
            estimated_exhaustion_days = (remaining_pct * budget["window_days"]) / burn_rate
        else:
            estimated_exhaustion_days = float("inf") if remaining_pct > 0 else 0.0

        return {
            "skill_id": skill_id,
            "slo_target": budget["slo_target"],
            "error_budget": budget["error_budget"],
            "consumed_pct": round(consumed_pct, 4),
            "remaining_pct": round(remaining_pct, 4),
            "burn_rate": round(burn_rate, 4),
            "estimated_exhaustion_days": round(estimated_exhaustion_days, 1),
            "total_requests": budget["total_requests"],
            "failed_requests": budget["failed_requests"],
        }

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus exposition format.

        Returns:
            String in Prometheus text format suitable for /metrics endpoint.
        """
        lines = []
        for name, metrics in self._metrics.items():
            # Prometheus metric name: replace dots with underscores
            prom_name = f"skillpool_{name.replace('.', '_').replace('-', '_')}"
            # TYPE header
            metric_type_map = {
                MetricType.COUNTER: "counter",
                MetricType.GAUGE: "gauge",
                MetricType.HISTOGRAM: "histogram",
            }
            prom_type = metric_type_map.get(metrics[0].metric_type, "gauge") if metrics else "gauge"
            lines.append(f"# TYPE {prom_name} {prom_type}")
            # Data lines
            for m in metrics:
                if m.labels:
                    label_str = ",".join(f'{k}="{v}"' for k, v in sorted(m.labels.items()))
                    lines.append(f"{prom_name}{{{label_str}}} {m.value}")
                else:
                    lines.append(f"{prom_name} {m.value}")
        # Alerts as gauge
        if self._alerts:
            lines.append("# TYPE skillpool_alerts_total gauge")
            lines.append(f"skillpool_alerts_total {len(self._alerts)}")
        return "\n".join(lines) + "\n"
