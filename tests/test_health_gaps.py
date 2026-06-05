"""Tests for Health module coverage gaps — uncovered lines from health/check.py.

Targeted gaps:
- L51: check_fn is None -> SERVING
- L56-58: check_fn raises exception -> NOT_SERVING
- L60-64: non-critical component NOT_SERVING -> DEGRADED
- L78-83: get_component_status missing component
"""
from __future__ import annotations


import pytest

from skillpool.health.check import HealthChecker
from skillpool.health.models import ServingStatus


@pytest.fixture
def checker():
    return HealthChecker()


class TestHealthCheckerNoCheckFn:
    def test_component_with_no_check_fn_serving(self, checker):
        """Line 51: check_fn is None -> SERVING."""
        checker.register("null_component", check_fn=None, critical=True)
        result = checker.check()
        comp = [c for c in result.components if c.component == "null_component"][0]
        assert comp.status == ServingStatus.SERVING


class TestHealthCheckerException:
    def test_check_fn_raises_not_serving(self, checker):
        """Lines 56-58: check_fn raises -> NOT_SERVING."""
        checker.register("failing_component", check_fn=lambda: (_ for _ in ()).throw(RuntimeError("fail")), critical=True)
        result = checker.check()
        comp = [c for c in result.components if c.component == "failing_component"][0]
        assert comp.status == ServingStatus.NOT_SERVING


class TestHealthCheckerDegraded:
    def test_non_critical_not_serving_degrades(self, checker):
        """Lines 60-64: non-critical NOT_SERVING -> DEGRADED."""
        checker.register("healthy", check_fn=lambda: True, critical=True)
        checker.register("optional_bad", check_fn=lambda: False, critical=False)
        result = checker.check()
        assert result.status == ServingStatus.DEGRADED

    def test_non_critical_bad_with_critical_bad(self, checker):
        """Critical component failing overrides degraded."""
        checker.register("critical_bad", check_fn=lambda: False, critical=True)
        checker.register("optional_bad", check_fn=lambda: False, critical=False)
        result = checker.check()
        assert result.status == ServingStatus.NOT_SERVING


class TestHealthCheckerGetComponentStatus:
    def test_missing_component_status(self, checker):
        """Lines 78-83: unknown component -> NOT_SERVING."""
        status = checker.get_component_status("nonexistent")
        assert status == ServingStatus.NOT_SERVING

    def test_known_component_status(self, checker):
        """Returns last known status after check."""
        checker.register("mycomp", check_fn=lambda: True, critical=True)
        checker.check()
        status = checker.get_component_status("mycomp")
        assert status == ServingStatus.SERVING

    def test_overall_serving_when_all_healthy(self, checker):
        """All components healthy -> SERVING."""
        checker.register("a", check_fn=lambda: True, critical=True)
        checker.register("b", check_fn=lambda: True, critical=True)
        result = checker.check()
        assert result.status == ServingStatus.SERVING
