"""Tests for CostDashboard — aggregated cost query and reporting."""

import pytest

from skillpool.cost.models import CostQuery
from skillpool.cost.token_governor import TokenGovernor, PRESET_AGENT_CONFIGS
from skillpool.cost.budget_tracker import BudgetTracker
from skillpool.cost.dashboard import CostDashboard


@pytest.fixture
def dashboard() -> CostDashboard:
    governor = TokenGovernor(PRESET_AGENT_CONFIGS)
    budget = BudgetTracker(monthly_budget_usd=5000.0)
    return CostDashboard(governor=governor, budget_tracker=budget)


class TestCostDashboardQuery:
    def test_empty_query_returns_zeros(self, dashboard: CostDashboard) -> None:
        resp = dashboard.query(CostQuery(window="24h"))
        assert resp.total_cost_usd == 0.0
        assert resp.total_tokens == 0
        assert resp.by_agent == []

    def test_single_record_aggregation(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.15)
        resp = dashboard.query(CostQuery(window="24h"))
        assert resp.total_cost_usd == 0.15
        assert resp.total_tokens == 1500
        assert len(resp.by_agent) == 1
        assert resp.by_agent[0].agent_id == "evolver_v4"
        assert resp.by_agent[0].tokens == 1500
        assert resp.by_agent[0].cost_usd == 0.15
        assert resp.by_agent[0].pct_of_total == 100.0

    def test_multi_agent_aggregation(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.15)
        dashboard.record("knowledge_refiner", 2000, 1000, 0.30)
        resp = dashboard.query(CostQuery(window="24h"))
        assert resp.total_cost_usd == 0.45
        assert resp.total_tokens == 4500
        assert len(resp.by_agent) == 2

    def test_filter_by_agent_id(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.15)
        dashboard.record("knowledge_refiner", 2000, 1000, 0.30)
        resp = dashboard.query(CostQuery(window="24h", agent_id="evolver_v4"))
        assert len(resp.by_agent) == 1
        assert resp.by_agent[0].agent_id == "evolver_v4"
        assert resp.total_cost_usd == 0.15

    def test_pct_of_total_with_multiple_agents(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10)
        dashboard.record("knowledge_refiner", 2000, 1000, 0.30)
        resp = dashboard.query(CostQuery(window="24h"))
        # evolver_v4: 0.10 / 0.40 = 25%
        # knowledge_refiner: 0.30 / 0.40 = 75%
        by_id = {a.agent_id: a for a in resp.by_agent}
        assert by_id["evolver_v4"].pct_of_total == 25.0
        assert by_id["knowledge_refiner"].pct_of_total == 75.0

    def test_budget_consumed_pct_in_response(self, dashboard: CostDashboard) -> None:
        dashboard._budget.record_cost(500.0)
        resp = dashboard.query(CostQuery(window="24h"))
        assert resp.monthly_budget_usd == 5000.0
        assert resp.monthly_budget_consumed_pct == 10.0

    def test_throttled_flag_in_agent_cost(self, dashboard: CostDashboard) -> None:
        # Record enough usage to push evolver_v4 past 80% throttle threshold
        dashboard._governor.record_usage("evolver_v4", 80_001)
        dashboard.record("evolver_v4", 1000, 500, 0.15)
        resp = dashboard.query(CostQuery(window="24h"))
        assert resp.by_agent[0].throttled is True

    def test_window_echoed_in_response(self, dashboard: CostDashboard) -> None:
        resp = dashboard.query(CostQuery(window="7d"))
        assert resp.window == "7d"

    def test_get_budget_status(self, dashboard: CostDashboard) -> None:
        dashboard._budget.record_cost(1000.0)
        status = dashboard.get_budget_status()
        assert status.monthly_budget_usd == 5000.0
        assert status.consumed_usd == 1000.0
        assert status.remaining_usd == 4000.0


class TestCostDashboardMultiDimension:
    """Tests for multi-dimension grouping (by_model, by_skill, by_operation)."""

    def test_by_model_aggregation(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10, model="gpt-4o")
        dashboard.record("evolver_v4", 500, 250, 0.05, model="gpt-4o")
        dashboard.record("evolver_v4", 1000, 500, 0.15, model="claude-sonnet")
        resp = dashboard.query(CostQuery(window="24h"))
        assert "gpt-4o" in resp.by_model
        assert resp.by_model["gpt-4o"]["cost_usd"] == pytest.approx(0.15, abs=0.001)
        assert resp.by_model["gpt-4o"]["tokens"] == 2250
        assert "claude-sonnet" in resp.by_model
        assert resp.by_model["claude-sonnet"]["cost_usd"] == pytest.approx(0.15, abs=0.001)

    def test_by_skill_aggregation(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10, skill_id="S09-recovery")
        dashboard.record("evolver_v4", 1000, 500, 0.10, skill_id="S09-recovery")
        dashboard.record("evolver_v4", 1000, 500, 0.20, skill_id="S13a-test")
        resp = dashboard.query(CostQuery(window="24h"))
        assert "S09-recovery" in resp.by_skill
        assert resp.by_skill["S09-recovery"]["cost_usd"] == pytest.approx(0.20, abs=0.001)
        assert resp.by_skill["S09-recovery"]["tokens"] == 3000
        assert "S13a-test" in resp.by_skill
        assert resp.by_skill["S13a-test"]["cost_usd"] == pytest.approx(0.20, abs=0.001)

    def test_by_operation_aggregation(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10, operation="generate")
        dashboard.record("evolver_v4", 1000, 500, 0.15, operation="review")
        dashboard.record("evolver_v4", 1000, 500, 0.05, operation="generate")
        resp = dashboard.query(CostQuery(window="24h"))
        assert "generate" in resp.by_operation
        assert resp.by_operation["generate"]["cost_usd"] == pytest.approx(0.15, abs=0.001)
        assert "review" in resp.by_operation
        assert resp.by_operation["review"]["cost_usd"] == pytest.approx(0.15, abs=0.001)

    def test_empty_model_skill_operation(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10)
        resp = dashboard.query(CostQuery(window="24h"))
        # Empty strings should not create entries
        assert resp.by_model == {}
        assert resp.by_skill == {}
        assert resp.by_operation == {}

    def test_projected_overspend_pct_below_50(self, dashboard: CostDashboard) -> None:
        # consumed < 50% → projected_overspend = 0
        dashboard._budget.record_cost(2000.0)  # 40% of 5000
        dashboard.record("evolver_v4", 1000, 500, 0.10)
        resp = dashboard.query(CostQuery(window="24h"))
        assert resp.projected_overspend_pct == 0.0

    def test_projected_overspend_pct_above_50(self, dashboard: CostDashboard) -> None:
        # consumed > 50% → projected_overspend = (consumed_pct * 2 - 1) * 100
        dashboard._budget.record_cost(3500.0)  # 70% of 5000
        dashboard.record("evolver_v4", 1000, 500, 0.10)
        resp = dashboard.query(CostQuery(window="24h"))
        # (0.7 * 2 - 1) * 100 = 40.0
        assert resp.projected_overspend_pct == pytest.approx(40.0, abs=0.1)

    def test_cost_query_granularity_field(self) -> None:
        q = CostQuery(window="24h", granularity="5m")
        assert q.granularity == "5m"
        q2 = CostQuery(window="24h")
        assert q2.granularity == "1d"

    def test_cost_record_skill_id_field(self) -> None:
        from skillpool.cost.models import CostRecord

        r = CostRecord(agent_id="evolver_v4", skill_id="S09-recovery", cost_usd=0.10)
        assert r.skill_id == "S09-recovery"
        r2 = CostRecord(agent_id="evolver_v4", cost_usd=0.10)
        assert r2.skill_id == ""


class TestCostTimeSeries:
    """Tests for time series generation in CostDashboard."""

    def test_empty_records_empty_series(self, dashboard: CostDashboard) -> None:
        resp = dashboard.query(CostQuery(window="24h", granularity="1h"))
        assert resp.series == []

    def test_single_record_hourly_series(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10)
        resp = dashboard.query(CostQuery(window="24h", granularity="1h"))
        assert len(resp.series) == 1
        assert resp.series[0]["tokens"] == 1500
        assert resp.series[0]["cost_usd"] == pytest.approx(0.10, abs=0.001)

    def test_multiple_records_same_bucket(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10)
        dashboard.record("evolver_v4", 500, 250, 0.05)
        resp = dashboard.query(CostQuery(window="24h", granularity="1h"))
        # Both records in same hour → single bucket
        assert len(resp.series) == 1
        assert resp.series[0]["tokens"] == 2250
        assert resp.series[0]["cost_usd"] == pytest.approx(0.15, abs=0.001)

    def test_daily_granularity(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10)
        resp = dashboard.query(CostQuery(window="24h", granularity="1d"))
        assert len(resp.series) == 1
        assert resp.series[0]["tokens"] == 1500

    def test_5m_granularity(self, dashboard: CostDashboard) -> None:
        dashboard.record("evolver_v4", 1000, 500, 0.10)
        resp = dashboard.query(CostQuery(window="24h", granularity="5m"))
        assert len(resp.series) == 1
        assert resp.series[0]["tokens"] == 1500

    def test_series_sorted_by_timestamp(self, dashboard: CostDashboard) -> None:
        import time

        dashboard.record("evolver_v4", 1000, 500, 0.10)
        time.sleep(0.01)
        dashboard.record("evolver_v4", 500, 250, 0.05)
        resp = dashboard.query(CostQuery(window="24h", granularity="1h"))
        # Should be sorted ascending
        if len(resp.series) > 1:
            assert resp.series[0]["timestamp"] <= resp.series[1]["timestamp"]
