"""Tests for TokenGovernor — per-agent daily token budget enforcement."""
import pytest

from skillpool.cost.models import AgentConfig, ThrottleAction
from skillpool.cost.token_governor import TokenGovernor, PRESET_AGENT_CONFIGS


@pytest.fixture
def governor() -> TokenGovernor:
    return TokenGovernor(PRESET_AGENT_CONFIGS)


class TestUnlimitedAgents:
    def test_root_planner_unlimited(self, governor: TokenGovernor) -> None:
        action, allowed = governor.check("root_planner", 1_000_000)
        assert action == ThrottleAction.ALLOW
        assert allowed == 1_000_000

    def test_sub_planner_unlimited(self, governor: TokenGovernor) -> None:
        action, allowed = governor.check("sub_planner", 500_000)
        assert action == ThrottleAction.ALLOW
        assert allowed == 500_000

    def test_level1_worker_unlimited(self, governor: TokenGovernor) -> None:
        action, allowed = governor.check("level1_worker", 999_999)
        assert action == ThrottleAction.ALLOW

    def test_level2_worker_unlimited(self, governor: TokenGovernor) -> None:
        action, allowed = governor.check("level2_worker", 999_999)
        assert action == ThrottleAction.ALLOW

    def test_unlimited_agents_never_throttled(self, governor: TokenGovernor) -> None:
        governor.record_usage("root_planner", 10_000_000)
        assert governor.is_throttled("root_planner") is False


class TestThrottleBehavior:
    def test_below_threshold_allows(self, governor: TokenGovernor) -> None:
        # evolver_v4: 100K limit, 80% throttle threshold
        governor.record_usage("evolver_v4", 70_000)
        action, allowed = governor.check("evolver_v4", 10_000)
        assert action == ThrottleAction.ALLOW
        assert allowed == 10_000

    def test_at_80pct_throttles(self, governor: TokenGovernor) -> None:
        # evolver_v4: 100K limit, 80% = 80K threshold, throttle_to 50%
        governor.record_usage("evolver_v4", 80_000)
        action, allowed = governor.check("evolver_v4", 10_000)
        assert action == ThrottleAction.THROTTLE
        # remaining = 100K - 80K = 20K, throttle_to 50% = 10K
        assert allowed == 10_000

    def test_throttle_reduces_tokens(self, governor: TokenGovernor) -> None:
        # evolver_v4: 100K limit, 80% threshold, throttle_to 50%
        governor.record_usage("evolver_v4", 90_000)
        action, allowed = governor.check("evolver_v4", 10_000)
        assert action == ThrottleAction.THROTTLE
        # remaining = 10K, throttle_to 50% = 5K, min(5K, 10K) = 5K
        assert allowed == 5_000

    def test_is_throttled_below_threshold(self, governor: TokenGovernor) -> None:
        governor.record_usage("evolver_v4", 70_000)
        assert governor.is_throttled("evolver_v4") is False

    def test_is_throttled_at_threshold(self, governor: TokenGovernor) -> None:
        governor.record_usage("evolver_v4", 80_000)
        assert governor.is_throttled("evolver_v4") is True


class TestRejectBehavior:
    def test_at_100pct_rejects(self, governor: TokenGovernor) -> None:
        # evolver_v4: 100K limit
        governor.record_usage("evolver_v4", 100_000)
        action, allowed = governor.check("evolver_v4", 1_000)
        assert action == ThrottleAction.REJECT
        assert allowed == 0

    def test_over_100pct_rejects(self, governor: TokenGovernor) -> None:
        governor.record_usage("evolver_v4", 150_000)
        action, allowed = governor.check("evolver_v4", 1_000)
        assert action == ThrottleAction.REJECT
        assert allowed == 0


class TestDailyUsage:
    def test_get_daily_usage(self, governor: TokenGovernor) -> None:
        governor.record_usage("evolver_v4", 5_000)
        governor.record_usage("evolver_v4", 3_000)
        assert governor.get_daily_usage("evolver_v4") == 8_000

    def test_get_daily_usage_unknown_agent(self, governor: TokenGovernor) -> None:
        assert governor.get_daily_usage("nonexistent") == 0


class TestResetDaily:
    def test_reset_clears_usage(self, governor: TokenGovernor) -> None:
        governor.record_usage("evolver_v4", 90_000)
        assert governor.is_throttled("evolver_v4") is True
        governor.reset_daily()
        assert governor.get_daily_usage("evolver_v4") == 0
        assert governor.is_throttled("evolver_v4") is False

    def test_reset_allows_after_rejection(self, governor: TokenGovernor) -> None:
        governor.record_usage("evolver_v4", 100_000)
        action, _ = governor.check("evolver_v4", 1_000)
        assert action == ThrottleAction.REJECT
        governor.reset_daily()
        action, allowed = governor.check("evolver_v4", 1_000)
        assert action == ThrottleAction.ALLOW
        assert allowed == 1_000


class TestUnknownAgent:
    def test_unknown_agent_allowed(self, governor: TokenGovernor) -> None:
        action, allowed = governor.check("unknown_agent", 5_000)
        assert action == ThrottleAction.ALLOW
        assert allowed == 5_000

    def test_unknown_agent_not_throttled(self, governor: TokenGovernor) -> None:
        assert governor.is_throttled("unknown_agent") is False


class TestCustomConfigs:
    def test_custom_config(self) -> None:
        configs = [
            AgentConfig(agent_id="test_agent", daily_limit_tokens=10_000, throttle_at_pct=0.5, throttle_to_pct=0.1),
        ]
        gov = TokenGovernor(configs)
        gov.record_usage("test_agent", 5_000)
        action, allowed = gov.check("test_agent", 5_000)
        assert action == ThrottleAction.THROTTLE
        # remaining = 5K, throttle_to 10% = 500
        assert allowed == 500
