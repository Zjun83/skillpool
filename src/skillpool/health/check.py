"""Health check — component health assessment."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from skillpool.health.models import (
    ComponentHealth,
    DegradationLevel,
    HealthCheckResponse,
    ServingStatus,
)


class HealthChecker:
    """Assess health of skillpool components.

    Usage:
        checker = HealthChecker()
        checker.register("resolver", check_fn=lambda: True)
        response = checker.check()
    """

    def __init__(self) -> None:
        self._components: dict[str, dict] = {}

    def register(
        self,
        name: str,
        check_fn: Optional[callable] = None,
        critical: bool = True,
    ) -> None:
        """Register a component for health checking."""
        self._components[name] = {
            "check_fn": check_fn,
            "critical": critical,
            "last_status": ServingStatus.SERVING,
        }

    def check(self) -> HealthCheckResponse:
        """Run health checks on all registered components."""
        results = []
        overall = ServingStatus.SERVING

        for name, config in self._components.items():
            check_fn = config.get("check_fn")
            if check_fn is None:
                comp_status = ServingStatus.SERVING
            else:
                try:
                    healthy = check_fn()
                    comp_status = ServingStatus.SERVING if healthy else ServingStatus.NOT_SERVING
                except Exception:
                    comp_status = ServingStatus.NOT_SERVING

            if comp_status == ServingStatus.NOT_SERVING and config.get("critical", True):
                overall = ServingStatus.NOT_SERVING
            elif comp_status == ServingStatus.NOT_SERVING and not config.get("critical", True):
                if overall == ServingStatus.SERVING:
                    overall = ServingStatus.DEGRADED

            config["last_status"] = comp_status
            results.append(ComponentHealth(
                component=name,
                status=comp_status,
            ))

        return HealthCheckResponse(
            status=overall,
            components=results,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def get_component_status(self, name: str) -> ServingStatus:
        """Get the last known status of a component."""
        config = self._components.get(name)
        if config:
            return config["last_status"]
        return ServingStatus.NOT_SERVING
