"""Tests for Cost module coverage gaps — uncovered lines from cost/__init__.py.

Targeted gaps:
- L58: trace ceiling check fails -> return False
- L63: budget block action -> return False
- L105: budget threshold check in get_budget
- L109-110: check_throttle with audit
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from skillpool.cost import CostManager
from skillpool.cost.models import CostRecord, BudgetStatus


@pytest.fixture
def cost_manager():
    return CostManager(monthly_budget_usd=100.0, trace_ceiling_usd=5.0)


def _make_record(**overrides):
    base = CostRecord(
        agent_id="agent-1",
        model="gpt-4",
        operation="chat",
        tokens_input=1000,
        tokens_output=500,
        cost_usd=0.05,
        trace_id="trace-001",
        skill_id="S09",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


class TestCostManagerTraceCeiling:
    def test_trace_ceiling_blocks_cost(self, cost_manager):
        """Line 58: cost blocked by trace ceiling."""
        # Record a large cost to exceed trace ceiling
        big_record = _make_record(cost_usd=10.0, trace_id="big-trace")
        result = cost_manager.report_cost(big_record)
        assert result is False

    def test_trace_ceiling_allows_within_limit(self, cost_manager):
        """Within ceiling -> accepted."""
        record = _make_record(cost_usd=0.01, trace_id="small-trace")
        result = cost_manager.report_cost(record)
        assert result is True


class TestCostManagerBudgetBlock:
    def test_budget_block_rejects_cost(self, cost_manager):
        """Line 63: budget threshold block action."""
        # Exhaust the budget
        for i in range(50):
            record = _make_record(cost_usd=3.0, trace_id=f"trace-{i}")
            cost_manager.report_cost(record)
        # Next cost should be rejected
        record = _make_record(cost_usd=0.01, trace_id="final-trace")
        result = cost_manager.report_cost(record)
        assert result is False


class TestCostManagerGetBudget:
    def test_get_budget_returns_status(self, cost_manager):
        """Line 105: get_budget returns BudgetStatus."""
        budget = cost_manager.get_budget()
        assert isinstance(budget, BudgetStatus)
        assert hasattr(budget, "monthly_budget_usd")


class TestCostManagerCheckThrottle:
    def test_check_throttle_returns_action(self, cost_manager):
        """Lines 109-110: check_throttle returns ThrottleAction."""
        from skillpool.cost.models import ThrottleAction
        action = cost_manager.check_throttle("agent-1", 1000)
        assert isinstance(action, ThrottleAction)

    def test_check_throttle_with_excessive_tokens(self, cost_manager):
        """Excessive tokens -> throttle action."""
        from skillpool.cost.models import ThrottleAction
        # Record lots of usage then check
        for _ in range(100):
            record = _make_record(cost_usd=0.01)
            cost_manager.report_cost(record)
        action = cost_manager.check_throttle("agent-1", 1000000)
        # Should return some throttle action
        assert isinstance(action, ThrottleAction)


class TestCostManagerWithAudit:
    def test_report_with_audit_layer(self):
        """Lines 109-110: cost reporting with full audit layer."""
        audit = MagicMock()
        audit.append.return_value = "audit-ref-1"
        mgr = CostManager(monthly_budget_usd=500.0, audit_layer=audit)
        record = _make_record(cost_usd=0.01)
        result = mgr.report_cost(record)
        assert result is True
        audit.append.assert_called_once()

    def test_report_with_audit_hash_chain(self):
        """Lines 85-86: cost reporting with lightweight AuditHashChain."""
        mgr = CostManager(monthly_budget_usd=500.0)
        assert mgr._audit_full is False
        record = _make_record(cost_usd=0.01)
        result = mgr.report_cost(record)
        assert result is True
