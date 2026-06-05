"""Tests for Health Check + Degradation Manager (4-level schema-aligned)."""

from skillpool.health import HealthManager
from skillpool.health.check import HealthChecker
from skillpool.health.degradation import DegradationManager
from skillpool.health.models import (
    ComponentHealth,
    DegradationLevel,
    HealthCheckResponse,
    ServingStatus,
)


class TestServingStatus:
    def test_enum_values(self) -> None:
        assert ServingStatus.SERVING == "SERVING"
        assert ServingStatus.NOT_SERVING == "NOT_SERVING"
        assert ServingStatus.DEGRADED == "DEGRADED"


class TestDegradationLevel:
    def test_enum_values(self) -> None:
        assert DegradationLevel.L0_FULL == "L0_full"
        assert DegradationLevel.L1_PARTIAL == "L1_partial"
        assert DegradationLevel.L2_BM25_ONLY == "L2_bm25_only"
        assert DegradationLevel.L3_DISABLED == "L3_disabled"


class TestHealthChecker:
    def test_all_healthy(self) -> None:
        checker = HealthChecker()
        checker.register("resolver", check_fn=lambda: True)
        checker.register("review", check_fn=lambda: True)
        resp = checker.check()
        assert resp.status == ServingStatus.SERVING
        assert len(resp.components) == 2

    def test_critical_failure(self) -> None:
        checker = HealthChecker()
        checker.register("resolver", check_fn=lambda: False, critical=True)
        resp = checker.check()
        assert resp.status == ServingStatus.NOT_SERVING

    def test_non_critical_failure(self) -> None:
        checker = HealthChecker()
        checker.register("resolver", check_fn=lambda: True, critical=True)
        checker.register("cache", check_fn=lambda: False, critical=False)
        resp = checker.check()
        assert resp.status == ServingStatus.DEGRADED

    def test_exception_in_check(self) -> None:
        def failing_check():
            raise ConnectionError("unreachable")

        checker = HealthChecker()
        checker.register("db", check_fn=failing_check, critical=True)
        resp = checker.check()
        assert resp.status == ServingStatus.NOT_SERVING

    def test_no_check_fn_means_serving(self) -> None:
        checker = HealthChecker()
        checker.register("static_component")
        resp = checker.check()
        assert resp.status == ServingStatus.SERVING


class TestDegradationManager:
    def test_starts_l0_full(self) -> None:
        dm = DegradationManager()
        assert dm.get_degradation_level() == DegradationLevel.L0_FULL

    def test_vpls_failure_degrades_to_l2_bm25(self) -> None:
        dm = DegradationManager()
        level = dm.report_failure("vpls", critical=True)
        assert level == DegradationLevel.L2_BM25_ONLY

    def test_non_critical_failure_l1_partial(self) -> None:
        dm = DegradationManager()
        level = dm.report_failure("cache", critical=False)
        assert level == DegradationLevel.L1_PARTIAL

    def test_multiple_critical_failures_l3_disabled(self) -> None:
        dm = DegradationManager(critical_threshold=2)
        dm.report_failure("vpls", critical=True)
        level = dm.report_failure("clawmem", critical=True)
        assert level == DegradationLevel.L3_DISABLED

    def test_recovery(self) -> None:
        dm = DegradationManager()
        dm.report_failure("vpls", critical=True)
        level = dm.report_recovery("vpls")
        assert level == DegradationLevel.L0_FULL

    def test_reset(self) -> None:
        dm = DegradationManager()
        dm.report_failure("vpls", critical=True)
        dm.report_failure("clawmem", critical=True)
        dm.reset()
        assert dm.get_degradation_level() == DegradationLevel.L0_FULL

    def test_fallback_mode_l0(self) -> None:
        dm = DegradationManager()
        assert dm.get_fallback_mode() == "vpls_vector"

    def test_fallback_mode_l1_partial(self) -> None:
        dm = DegradationManager()
        dm.report_failure("cache", critical=False)
        assert dm.get_fallback_mode() == "vpls_vector"

    def test_fallback_mode_l2_bm25(self) -> None:
        dm = DegradationManager()
        dm.report_failure("vpls", critical=True)
        assert dm.get_fallback_mode() == "bm25_keyword"

    def test_fallback_mode_l3_disabled(self) -> None:
        dm = DegradationManager(critical_threshold=2)
        dm.report_failure("vpls", critical=True)
        dm.report_failure("clawmem", critical=True)
        assert dm.get_fallback_mode() == "sqlite_fts5"

    def test_l1_partial_with_mixed_failures(self) -> None:
        dm = DegradationManager(critical_threshold=3)
        dm.report_failure("cache", critical=False)
        dm.report_failure("monitor", critical=False)
        assert dm.get_degradation_level() == DegradationLevel.L1_PARTIAL

    def test_l2_bm25_one_critical_below_threshold(self) -> None:
        dm = DegradationManager(critical_threshold=3)
        dm.report_failure("vpls", critical=True)
        dm.report_failure("cache", critical=False)
        assert dm.get_degradation_level() == DegradationLevel.L2_BM25_ONLY


class TestHealthManager:
    def test_check_and_degrade(self) -> None:
        hm = HealthManager()
        hm.register_component("vpls", check_fn=lambda: False, critical=False)
        resp = hm.check_health()
        assert resp.status == ServingStatus.DEGRADED
        assert hm.get_degradation_level() == DegradationLevel.L2_BM25_ONLY

    def test_all_healthy(self) -> None:
        hm = HealthManager()
        hm.register_component("resolver", check_fn=lambda: True)
        resp = hm.check_health()
        assert resp.status == ServingStatus.SERVING
        assert hm.get_degradation_level() == DegradationLevel.L0_FULL

    def test_response_degradation_level_field(self) -> None:
        hm = HealthManager()
        hm.register_component("cache", check_fn=lambda: False, critical=False)
        resp = hm.check_health()
        assert resp.degradation_level == DegradationLevel.L1_PARTIAL

    def test_response_l0_full_when_healthy(self) -> None:
        hm = HealthManager()
        hm.register_component("resolver", check_fn=lambda: True)
        resp = hm.check_health()
        assert resp.degradation_level == DegradationLevel.L0_FULL

    def test_component_health_fallback_mode_field(self) -> None:
        comp = ComponentHealth(component="vpls", fallback_mode="bm25_keyword")
        assert comp.fallback_mode == "bm25_keyword"

    def test_component_health_default_fallback_mode(self) -> None:
        comp = ComponentHealth(component="resolver")
        assert comp.fallback_mode == ""

    def test_response_vpls_latency_field(self) -> None:
        resp = HealthCheckResponse(vpls_latency_p99_ms=42.5)
        assert resp.vpls_latency_p99_ms == 42.5
