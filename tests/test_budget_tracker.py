"""Tests for BudgetTracker — monthly budget enforcement with threshold alerts."""
import pytest

from skillpool.cost.budget_tracker import BudgetTracker


@pytest.fixture
def tracker() -> BudgetTracker:
    return BudgetTracker(monthly_budget_usd=1000.0)


class TestRecordCost:
    def test_initial_consumed_is_zero(self, tracker: BudgetTracker) -> None:
        assert tracker.get_consumed_pct() == 0.0

    def test_record_single_cost(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(100.0)
        assert tracker.get_consumed_pct() == pytest.approx(0.1)

    def test_record_multiple_costs(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(200.0)
        tracker.record_cost(300.0)
        assert tracker.get_consumed_pct() == pytest.approx(0.5)

    def test_record_exceeds_budget(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(1200.0)
        assert tracker.get_consumed_pct() == pytest.approx(1.2)


class TestGetStatus:
    def test_status_fields(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(250.0)
        status = tracker.get_status()
        assert status.monthly_budget_usd == 1000.0
        assert status.consumed_usd == 250.0
        assert status.remaining_usd == 750.0
        assert status.consumed_pct == pytest.approx(0.25)

    def test_remaining_clamps_to_zero(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(1500.0)
        status = tracker.get_status()
        assert status.remaining_usd == 0.0

    def test_zero_budget(self) -> None:
        bt = BudgetTracker(monthly_budget_usd=0.0)
        bt.record_cost(1.0)
        assert bt.get_consumed_pct() == 1.0


class TestThresholds:
    def test_normal_when_over_50pct_remaining(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(400.0)  # 40% consumed, 60% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "normal"
        assert action == "continue"

    def test_caution_at_50pct_remaining(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(550.0)  # 55% consumed, 45% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "caution"
        assert action == "monitor"

    def test_warning_at_25pct_remaining(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(800.0)  # 80% consumed, 20% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "warning"
        assert action == "throttle"

    def test_critical_at_10pct_remaining(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(950.0)  # 95% consumed, 5% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "critical"
        assert action == "block"

    def test_exactly_50pct_is_normal(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(500.0)  # exactly 50% consumed, 50% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "normal"  # <50% remaining triggers caution; exactly 50% is normal
        assert action == "continue"

    def test_just_below_50pct_is_caution(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(501.0)  # 50.1% consumed, 49.9% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "caution"

    def test_exactly_75pct_is_caution(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(750.0)  # 75% consumed, 25% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "caution"

    def test_exactly_90pct_is_critical(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(900.0)  # 90% consumed, 10% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "critical"  # <10% remaining triggers critical; exactly 10% is critical

    def test_just_above_90pct_is_warning(self, tracker: BudgetTracker) -> None:
        tracker.record_cost(860.0)  # 86% consumed, 14% remaining
        name, action = tracker.check_budget_threshold()
        assert name == "warning"
