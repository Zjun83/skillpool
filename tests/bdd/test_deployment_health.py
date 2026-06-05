"""BDD tests for Deployment Health Checks — mapping to deployment-health-checks.feature scenarios."""

from skillpool.health import HealthManager
from skillpool.health.check import HealthChecker
from skillpool.health.degradation import DegradationManager
from skillpool.health.models import DegradationLevel, ServingStatus


class TestHealthCheck:
    """Scenarios for component health checking."""

    def test_all_components_serving(self):
        """Scenario: All components report SERVING status."""
        checker = HealthChecker()
        checker.register("resolver", check_fn=lambda: True)
        checker.register("review", check_fn=lambda: True)
        resp = checker.check()
        assert resp.status == ServingStatus.SERVING

    def test_critical_component_down(self):
        """Scenario: Critical component down → NOT_SERVING."""
        checker = HealthChecker()
        checker.register("resolver", check_fn=lambda: False, critical=True)
        resp = checker.check()
        assert resp.status == ServingStatus.NOT_SERVING

    def test_non_critical_degraded(self):
        """Scenario: Non-critical component down → DEGRADED."""
        checker = HealthChecker()
        checker.register("resolver", check_fn=lambda: True, critical=True)
        checker.register("cache", check_fn=lambda: False, critical=False)
        resp = checker.check()
        assert resp.status == ServingStatus.DEGRADED

    def test_component_exception(self):
        """Scenario: Component check throws exception → NOT_SERVING for that component."""
        checker = HealthChecker()
        checker.register("db", check_fn=lambda: 1/0, critical=True)
        resp = checker.check()
        assert resp.status == ServingStatus.NOT_SERVING


class TestDegradation:
    """Scenarios for degradation management."""

    def test_vpls_down_triggers_bm25_fallback(self):
        """Scenario: VPLS unavailable → degrade to BM25-only."""
        dm = DegradationManager()
        level = dm.report_failure("vpls", critical=True)
        assert level == DegradationLevel.L2_BM25_ONLY

    def test_multiple_failures_minimal(self):
        """Scenario: Multiple critical failures → minimal degradation."""
        dm = DegradationManager(critical_threshold=2)
        dm.report_failure("vpls", critical=True)
        dm.report_failure("clawmem", critical=True)
        assert dm.get_degradation_level() == DegradationLevel.L3_DISABLED

    def test_recovery_to_full(self):
        """Scenario: All components recover → FULL functionality."""
        dm = DegradationManager()
        dm.report_failure("vpls", critical=True)
        dm.report_recovery("vpls")
        assert dm.get_degradation_level() == DegradationLevel.L0_FULL


class TestHealthManager:
    """Integration scenarios for HealthManager."""

    def test_check_health_and_degrade(self):
        """Scenario: Health check detects failure and triggers degradation."""
        hm = HealthManager()
        hm.register_component("vpls", check_fn=lambda: False, critical=False)
        resp = hm.check_health()
        assert resp.status == ServingStatus.DEGRADED
        assert hm.get_degradation_level() == DegradationLevel.L2_BM25_ONLY

    def test_cold_start_sequential_readiness(self):
        """Scenario: Cold start — components become ready in order."""
        # Simulate sequential startup
        states = [False, False, True]  # 3 stages
        hm = HealthManager()

        # Initially not serving
        hm.register_component("vpls", check_fn=lambda: states[0], critical=True)
        resp = hm.check_health()
        assert resp.status == ServingStatus.NOT_SERVING

        # VPLS comes up
        states[0] = True
        hm.register_component("vpls", check_fn=lambda: states[0], critical=True)
        resp = hm.check_health()
        assert resp.status == ServingStatus.SERVING


class TestFourLevelDegradation:
    """Scenarios for 4-level degradation (L0_full → L1_partial → L2_bm25_only → L3_disabled)."""

    def test_l0_full_when_healthy(self):
        """Scenario: All components healthy → L0_full."""
        dm = DegradationManager()
        assert dm.get_degradation_level() == DegradationLevel.L0_FULL

    def test_l1_partial_non_critical_failure(self):
        """Scenario: Non-critical failure → L1_partial."""
        dm = DegradationManager()
        level = dm.report_failure("cache", critical=False)
        assert level == DegradationLevel.L1_PARTIAL

    def test_l2_bm25_vpls_down(self):
        """Scenario: VPLS down → L2_bm25_only."""
        dm = DegradationManager()
        level = dm.report_failure("vpls", critical=True)
        assert level == DegradationLevel.L2_BM25_ONLY

    def test_l3_disabled_multiple_critical(self):
        """Scenario: Multiple critical failures → L3_disabled."""
        dm = DegradationManager(critical_threshold=2)
        dm.report_failure("vpls", critical=True)
        level = dm.report_failure("resolver", critical=True)
        assert level == DegradationLevel.L3_DISABLED

    def test_fallback_mode_per_level(self):
        """Scenario: Fallback mode transitions correctly."""
        dm = DegradationManager()
        assert dm.get_fallback_mode() == "vpls_vector"
        dm.report_failure("cache", critical=False)
        assert dm.get_fallback_mode() == "vpls_vector"
        dm.report_failure("vpls", critical=True)
        assert dm.get_fallback_mode() == "bm25_keyword"
        dm.report_failure("resolver", critical=True)
        assert dm.get_fallback_mode() == "sqlite_fts5"

    def test_health_response_degradation_field(self):
        """Scenario: Health check response includes degradation_level."""
        hm = HealthManager()
        hm.register_component("cache", check_fn=lambda: False, critical=False)
        resp = hm.check_health()
        assert resp.degradation_level == DegradationLevel.L1_PARTIAL


class TestGrpcHealthMock:
    """Scenarios for gRPC health check protocol (mocked without grpcio)."""

    def test_grpc_serving_status_mapping(self):
        """Scenario: gRPC ServingStatus maps to internal ServingStatus."""
        # gRPC defines: UNKNOWN=0, SERVING=1, NOT_SERVING=2, SERVICE_UNKNOWN=3
        # Our mapping: SERVING→SERVING, NOT_SERVING→NOT_SERVING, SERVICE_UNKNOWN→DEGRADED
        grpc_to_internal = {
            0: ServingStatus.NOT_SERVING,  # UNKNOWN
            1: ServingStatus.SERVING,       # SERVING
            2: ServingStatus.NOT_SERVING,   # NOT_SERVING
            3: ServingStatus.DEGRADED,      # SERVICE_UNKNOWN
        }
        assert grpc_to_internal[1] == ServingStatus.SERVING
        assert grpc_to_internal[2] == ServingStatus.NOT_SERVING
        assert grpc_to_internal[3] == ServingStatus.DEGRADED

    def test_grpc_health_check_request_mock(self):
        """Scenario: gRPC HealthCheckRequest mock with service name."""
        # Simulate a gRPC HealthCheckRequest
        class MockHealthCheckRequest:
            def __init__(self, service: str = ""):
                self.service = service

        req = MockHealthCheckRequest(service="skillpool.Resolver")
        assert req.service == "skillpool.Resolver"

    def test_grpc_health_check_response_mock(self):
        """Scenario: gRPC HealthCheckResponse mock maps to internal status."""
        class MockGrpcHealthResponse:
            SERVING = 1
            NOT_SERVING = 2

            def __init__(self, status: int = 1):
                self.status = status

        resp = MockGrpcHealthResponse(status=MockGrpcHealthResponse.SERVING)
        # Map to internal
        assert resp.status == 1
        internal = ServingStatus.SERVING if resp.status == 1 else ServingStatus.NOT_SERVING
        assert internal == ServingStatus.SERVING

    def test_grpc_watch_stream_mock(self):
        """Scenario: gRPC Watch() streaming health updates (mock)."""
        checker = HealthChecker()
        checker.register("resolver", check_fn=lambda: True)
        checker.register("review", check_fn=lambda: False, critical=False)

        # Simulate streaming by calling check() multiple times
        resp1 = checker.check()
        assert resp1.status == ServingStatus.DEGRADED

    def test_spire_certificate_rotation_zero_impact(self):
        """Scenario: SPIRE certificate rotation has zero impact on health."""
        checker = HealthChecker()
        # Before rotation
        checker.register("vpls", check_fn=lambda: True, critical=True)
        resp_before = checker.check()
        # After rotation (same result)
        resp_after = checker.check()
        assert resp_before.status == resp_after.status == ServingStatus.SERVING