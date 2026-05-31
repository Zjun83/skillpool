"""Health module — component health checking and degradation management."""
from __future__ import annotations

from skillpool.health.check import HealthChecker
from skillpool.health.degradation import DegradationManager
from skillpool.health.models import (
    ComponentHealth,
    DegradationLevel,
    HealthCheckResponse,
    ServingStatus,
)


class HealthManager:
    """Unified health management: checking + degradation + monitoring.

    When a MonitorLayer is provided, health check results feed into the
    monitoring system's metrics and five-dimension evaluation.

    Usage:
        hm = HealthManager()
        hm.register_component("resolver")
        response = hm.check_health()
        level = hm.get_degradation_level()
    """

    def __init__(self, critical_threshold: int = 2, monitor=None) -> None:
        self.checker = HealthChecker()
        self.degradation = DegradationManager(critical_threshold=critical_threshold)
        self._monitor = monitor

    def register_component(
        self,
        name: str,
        check_fn: callable = None,
        critical: bool = True,
    ) -> None:
        """Register a component for health monitoring."""
        self.checker.register(name, check_fn=check_fn, critical=critical)

    def check_health(self) -> HealthCheckResponse:
        """Run health checks and update degradation state + monitor."""
        response = self.checker.check()
        # Update degradation based on results
        for comp in response.components:
            if comp.status == ServingStatus.NOT_SERVING:
                # Check if component is critical
                comp_config = self.checker._components.get(comp.component, {})
                is_critical = comp_config.get("critical", True)
                self.degradation.report_failure(comp.component, critical=is_critical)
            else:
                self.degradation.report_recovery(comp.component)

        # Update response with degradation level
        response.degradation_level = self.degradation.get_degradation_level()

        # Feed results to monitor layer if available
        if self._monitor is not None:
            from skillpool.monitor import MetricType
            for comp in response.components:
                status_val = 1.0 if comp.status == ServingStatus.SERVING else 0.0
                self._monitor.record_metric(
                    name=f"health.{comp.component}",
                    value=status_val,
                    metric_type=MetricType.GAUGE,
                    labels={"component": comp.component},
                )
        return response

    def get_degradation_level(self) -> DegradationLevel:
        return self.degradation.get_degradation_level()
