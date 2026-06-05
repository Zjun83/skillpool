"""BDD tests for Cost Attribution — mapping to cost-attribution.feature scenarios."""

import pytest

from skillpool.cost import CostManager
from skillpool.cost.models import CostQuery, CostRecord, ThrottleAction
from skillpool.cost.token_governor import TokenGovernor
from skillpool.cost.budget_tracker import BudgetTracker
from skillpool.cost.trace_ceiling import TraceCeiling
from skillpool.cost.audit_hash import AuditHashChain


class TestCostQuery:
    """Scenario: Query 24h cost aggregated by agent."""

    def test_query_24h_by_agent(self):
        """Scenario: Query cost for 24h window grouped by agent."""
        mgr = CostManager()
        mgr.report_cost(
            CostRecord(
                agent_id="evolver_v4",
                tokens_input=1000,
                tokens_output=500,
                cost_usd=0.05,
                model="gpt-4",
                operation="evolve",
                trace_id="trace-001",
            )
        )
        mgr.report_cost(
            CostRecord(
                agent_id="knowledge_refiner",
                tokens_input=2000,
                tokens_output=800,
                cost_usd=0.10,
                model="gpt-4",
                operation="refine",
                trace_id="trace-002",
            )
        )
        query = CostQuery(window="24h", group_by=["agent_id"])
        response = mgr.get_dashboard(query)
        assert response.total_cost_usd > 0
        assert response.total_tokens > 0
        assert len(response.by_agent) > 0

    def test_query_monthly_budget_status(self):
        """Scenario: Query monthly budget status."""
        tracker = BudgetTracker(monthly_budget_usd=5000.0)
        tracker.record_cost(250.0)
        status = tracker.get_status()
        assert status.monthly_budget_usd == 5000.0
        assert status.consumed_usd > 0
        assert status.consumed_pct > 0


class TestTokenGovernor:
    """Scenarios for token-based throttling."""

    def test_evolver_80_percent_throttle(self):
        """Scenario: evolver_v4 at 80% daily limit → throttle to 50%."""
        gov = TokenGovernor()
        config = gov.get_config("evolver_v4")
        assert config is not None
        assert config.throttle_at_pct == 0.80

    def test_evolver_100_percent_reject(self):
        """Scenario: evolver_v4 at 100% daily limit → reject."""
        gov = TokenGovernor()
        config = gov.get_config("evolver_v4")
        # Simulate consuming 100K tokens
        gov.record_usage("evolver_v4", config.daily_limit_tokens)
        action, _ = gov.check("evolver_v4", 1000)
        assert action == ThrottleAction.REJECT

    def test_unlimited_agents_always_allowed(self):
        """Scenario: Unlimited agents (root_planner) are never throttled."""
        gov = TokenGovernor()
        action, _ = gov.check("root_planner", 999999)
        assert action == ThrottleAction.ALLOW


class TestBudgetTracker:
    """Budget threshold scenarios."""

    def test_90_percent_threshold(self):
        """Scenario: Monthly budget at 90% → global throttle."""
        tracker = BudgetTracker(monthly_budget_usd=100.0)
        tracker.record_cost(90.0)
        threshold, _ = tracker.check_budget_threshold()
        assert threshold is not None

    def test_50_percent_remaining(self):
        tracker = BudgetTracker(monthly_budget_usd=100.0)
        tracker.record_cost(50.0)
        # get_consumed_pct returns 0.0-1.0, not 0-100
        assert tracker.get_consumed_pct() == pytest.approx(0.5)


class TestTraceCeiling:
    """Per-trace cost ceiling scenarios."""

    def test_trace_ceiling_blocks_excess(self):
        """Scenario: Per-trace cost exceeds ceiling → circuit break."""
        tc = TraceCeiling(ceiling_usd=5.0)
        tc.record_trace_cost("trace-1", 4.0)
        allowed, reason = tc.check("trace-1", 2.0)
        assert allowed is False

    def test_trace_ceiling_allows_under(self):
        tc = TraceCeiling(ceiling_usd=5.0)
        tc.record_trace_cost("trace-1", 2.0)
        allowed, reason = tc.check("trace-1", 2.0)
        assert allowed is True


class TestAuditHashChain:
    """Audit hash chain integrity scenarios."""

    def test_chain_verification(self):
        """Scenario: Verify audit hash chain integrity."""
        chain = AuditHashChain()
        chain.append({"agent": "evolver_v4", "cost": 0.05})
        chain.append({"agent": "knowledge_refiner", "cost": 0.10})
        assert chain.verify_chain() is True

    def test_tampered_chain_fails(self):
        """Scenario: Tampered audit chain fails verification."""
        chain = AuditHashChain()
        chain.append({"agent": "evolver_v4", "cost": 0.05})
        # Tamper with the chain
        chain._hashes[0] = "tampered_hash"
        assert chain.verify_chain() is False


class TestMultiDimensionGrouping:
    """Scenarios for multi-dimension cost grouping (by_model, by_skill, by_operation)."""

    def test_query_by_model(self):
        """Scenario: Cost grouped by model."""
        mgr = CostManager()
        mgr.report_cost(CostRecord(agent_id="evolver_v4", cost_usd=0.10, model="gpt-4o"))
        mgr.report_cost(CostRecord(agent_id="evolver_v4", cost_usd=0.15, model="claude-sonnet"))
        resp = mgr.get_dashboard(CostQuery(window="24h"))
        assert "gpt-4o" in resp.by_model
        assert "claude-sonnet" in resp.by_model

    def test_query_by_skill(self):
        """Scenario: Cost grouped by skill_id."""
        mgr = CostManager()
        mgr.report_cost(CostRecord(agent_id="evolver_v4", cost_usd=0.10, skill_id="S09-recovery"))
        resp = mgr.get_dashboard(CostQuery(window="24h"))
        assert "S09-recovery" in resp.by_skill

    def test_query_by_operation(self):
        """Scenario: Cost grouped by operation."""
        mgr = CostManager()
        mgr.report_cost(CostRecord(agent_id="evolver_v4", cost_usd=0.10, operation="generate"))
        resp = mgr.get_dashboard(CostQuery(window="24h"))
        assert "generate" in resp.by_operation

    def test_projected_overspend(self):
        """Scenario: Projected overspend percentage when budget > 50% consumed."""
        tracker = BudgetTracker(monthly_budget_usd=100.0)
        tracker.record_cost(70.0)  # 70%
        from skillpool.cost.dashboard import CostDashboard
        from skillpool.cost.token_governor import TokenGovernor, PRESET_AGENT_CONFIGS

        dash = CostDashboard(governor=TokenGovernor(PRESET_AGENT_CONFIGS), budget_tracker=tracker)
        dash.record("evolver_v4", 100, 50, 0.10)
        resp = dash.query(CostQuery(window="24h"))
        assert resp.projected_overspend_pct > 0

    def test_trace_id_propagation_in_cost(self):
        """Scenario: trace_id is propagated through cost recording."""
        mgr = CostManager()
        record = CostRecord(agent_id="evolver_v4", cost_usd=0.10, trace_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        result = mgr.report_cost(record)
        assert result is True
