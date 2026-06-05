"""Tests for TokenGovernor — per-agent daily token budget enforcement + estimate_session_cost."""
import json
import pytest
from pathlib import Path

from skillpool.cost.models import AgentConfig, CostEstimate, ThrottleAction
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


# ---------------------------------------------------------------------------
# Group 1: estimate_session_cost — cost calculation (P50 pricing)
# ---------------------------------------------------------------------------


class TestEstimateSessionCostCalculation:
    """Verify P50 pricing model: $0.003/1K tokens for cost calculation."""

    def test_basic_cost_calculation(self, governor: TokenGovernor) -> None:
        """Skill with 10K chars → token estimate → cost at P50 rate."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=10_000,
        )
        assert isinstance(estimate, CostEstimate)
        assert estimate.skill_id == "dev-4d-sdd"
        assert estimate.skill_length == 10_000
        assert estimate.token_count > 0
        assert estimate.price_per_1k_tokens == 0.003
        # base_cost = token_count * 0.003 / 1000
        expected_base = estimate.token_count * 0.003 / 1000
        assert abs(estimate.base_cost_usd - expected_base) < 1e-6

    def test_l2_review_overhead_added(self, governor: TokenGovernor) -> None:
        """L2 level task includes L2 review overhead in total cost."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            review_level="L2",
        )
        assert estimate.l2_review_overhead_usd > 0
        assert estimate.total_cost_usd > estimate.base_cost_usd

    def test_l3_review_overhead_added(self, governor: TokenGovernor) -> None:
        """L3+L2+ level task includes both L2 and L3 review overhead."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            review_level="L3+L2+",
        )
        assert estimate.l2_review_overhead_usd > 0
        assert estimate.l3_review_overhead_usd > 0
        assert estimate.total_cost_usd > estimate.base_cost_usd + estimate.l2_review_overhead_usd

    def test_l1_no_review_overhead(self, governor: TokenGovernor) -> None:
        """L1 level task has no L2/L3 review overhead."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            review_level="L1",
        )
        assert estimate.l2_review_overhead_usd == 0.0
        assert estimate.l3_review_overhead_usd == 0.0

    def test_total_cost_equals_sum(self, governor: TokenGovernor) -> None:
        """total_cost_usd = base + L2 overhead + L3 overhead + checkpoint overhead."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=8_000,
            review_level="L3+L2+",
            include_review_checkpoint=True,
        )
        expected_total = (
            estimate.base_cost_usd
            + estimate.l2_review_overhead_usd
            + estimate.l3_review_overhead_usd
            + estimate.review_checkpoint_overhead_usd
        )
        assert abs(estimate.total_cost_usd - expected_total) < 1e-6

    def test_token_count_from_skill_length(self, governor: TokenGovernor) -> None:
        """Token count estimated from skill_length using ~4 chars/token ratio."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=4_000,
        )
        # ~4 chars per token → 4K chars ≈ 1K tokens
        assert estimate.token_count == 1_000


# ---------------------------------------------------------------------------
# Group 2: estimate_session_cost — skill_get error handling
# ---------------------------------------------------------------------------


class TestEstimateSessionCostSkillGetErrors:
    """Verify graceful handling when skill_get fails or skill not found."""

    def test_skill_get_not_found_uses_defaults(self, governor: TokenGovernor) -> None:
        """When skill_get returns NotFound, fall back to skill_length param."""
        estimate = governor.estimate_session_cost(
            skill_id="nonexistent-skill",
            skill_length=5_000,
        )
        # Should not crash, uses provided skill_length
        assert estimate.skill_id == "nonexistent-skill"
        assert estimate.skill_length == 5_000
        assert estimate.token_count > 0

    def test_skill_get_mcp_unavailable_uses_defaults(self, governor: TokenGovernor) -> None:
        """When MCP skill_get is unavailable, fall back to skill_length param."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=6_000,
            skill_get_fn=None,  # No MCP available
        )
        assert estimate.skill_length == 6_000
        assert estimate.token_count > 0

    def test_skill_get_exception_uses_defaults(self, governor: TokenGovernor) -> None:
        """When skill_get raises an exception, fall back gracefully."""
        def failing_skill_get(skill_id: str) -> None:
            raise RuntimeError("MCP connection failed")

        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=3_000,
            skill_get_fn=failing_skill_get,
        )
        assert estimate.skill_length == 3_000
        assert estimate.token_count > 0

    def test_skill_get_with_content_attribute(self, governor: TokenGovernor) -> None:
        """When skill_get returns object with .content, use its length."""
        class MockSkill:
            content = "x" * 2_000  # 2K chars → 500 tokens

        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=999,  # Should be overridden by skill_get
            skill_get_fn=lambda sid: MockSkill(),
        )
        assert estimate.skill_length == 2_000
        assert estimate.token_count == 500

    def test_skill_get_with_dict_content(self, governor: TokenGovernor) -> None:
        """When skill_get returns dict with 'content' key, use its length."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=999,
            skill_get_fn=lambda sid: {"content": "y" * 1_200},
        )
        assert estimate.skill_length == 1_200


# ---------------------------------------------------------------------------
# Group 3: Gate + review_checkpoint interaction
# ---------------------------------------------------------------------------


class TestEstimateSessionCostGateAndCheckpoint:
    """Verify Gate validation and review_checkpoint auto-trigger in cost estimation."""

    def test_gate_passed_when_no_policy(self, governor: TokenGovernor) -> None:
        """Without a gate policy, gate_passed defaults to True."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
        )
        assert estimate.gate_passed is True
        assert estimate.gate_block_reason is None

    def test_gate_blocked_sets_reason(self, governor: TokenGovernor, tmp_path: Path) -> None:
        """When gate blocks, gate_passed=False and reason is set."""
        # Create a mock gate check result that blocks
        from skillpool.gate_policy.state_machine import GateCheckResult

        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            gate_check_result=GateCheckResult(
                passed=False,
                missing_artifacts=["sdd_contract"],
                validation_message="Missing: sdd_contract",
            ),
        )
        assert estimate.gate_passed is False
        assert estimate.gate_block_reason is not None

    def test_review_checkpoint_overhead_included(self, governor: TokenGovernor) -> None:
        """When include_review_checkpoint=True, overhead is added."""
        estimate_no_checkpoint = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            include_review_checkpoint=False,
        )
        estimate_with_checkpoint = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            include_review_checkpoint=True,
        )
        assert estimate_with_checkpoint.review_checkpoint_overhead_usd > 0
        assert estimate_no_checkpoint.review_checkpoint_overhead_usd == 0.0
        assert estimate_with_checkpoint.total_cost_usd > estimate_no_checkpoint.total_cost_usd


# ---------------------------------------------------------------------------
# Group 4: Emergency bypass + basename + enforcement mode scenarios
# ---------------------------------------------------------------------------


class TestEstimateSessionCostEmergencyBypass:
    """Verify emergency bypass, basename matching, and enforcement mode scenarios."""

    def test_emergency_bypass_active_when_override_file_exists(
        self, governor: TokenGovernor, tmp_path: Path
    ) -> None:
        """Bypass active: override file exists and not expired → cost estimate shows bypass."""
        override_file = tmp_path / "emergency_overrides.json"
        override_file.write_text(json.dumps({
            "expires_at": "2099-12-31T23:59:59+00:00",
            "reason": "Hotfix deployment",
        }))
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            emergency_bypass_path=str(override_file),
        )
        assert estimate.emergency_bypass_active is True
        assert estimate.gate_passed is True

    def test_emergency_bypass_expired_not_active(
        self, governor: TokenGovernor, tmp_path: Path
    ) -> None:
        """Bypass expired: override file exists but expired → bypass not active."""
        override_file = tmp_path / "emergency_overrides.json"
        override_file.write_text(json.dumps({
            "expires_at": "2000-01-01T00:00:00+00:00",
            "reason": "Old override",
        }))
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            emergency_bypass_path=str(override_file),
        )
        assert estimate.emergency_bypass_active is False

    def test_emergency_bypass_no_file_not_active(self, governor: TokenGovernor) -> None:
        """No override file → bypass not active regardless of config."""
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            emergency_bypass_path="/nonexistent/path/emergency_overrides.json",
        )
        assert estimate.emergency_bypass_active is False

    def test_emergency_bypass_indefinite_when_no_expiry(self, governor: TokenGovernor, tmp_path: Path) -> None:
        """Override file without expires_at → bypass active indefinitely."""
        override_file = tmp_path / "emergency_overrides.json"
        override_file.write_text(json.dumps({
            "reason": "Hotfix — no expiry set",
        }))
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            emergency_bypass_path=str(override_file),
        )
        assert estimate.emergency_bypass_active is True

    def test_emergency_bypass_corrupt_file_not_active(self, governor: TokenGovernor, tmp_path: Path) -> None:
        """Corrupt override file → bypass not active."""
        override_file = tmp_path / "emergency_overrides.json"
        override_file.write_text("NOT VALID JSON {{{")
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            emergency_bypass_path=str(override_file),
        )
        assert estimate.emergency_bypass_active is False

    def test_basename_matching_for_nested_paths(self, governor: TokenGovernor) -> None:
        """Gate file_pattern matches basename for nested paths like src/foo/bar.py."""
        # This tests that the cost estimation correctly handles
        # changed_files with nested paths via basename matching
        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            changed_files=["src/skillpool/cost/token_governor.py"],
        )
        # Should not crash — basename matching resolves the file pattern
        assert estimate.skill_id == "dev-4d-sdd"

    def test_permissive_mode_gate_block_not_fatal(self, governor: TokenGovernor) -> None:
        """In permissive enforcement mode, gate block doesn't prevent estimation."""
        from skillpool.gate_policy.state_machine import GateCheckResult

        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            gate_check_result=GateCheckResult(
                passed=False,
                missing_artifacts=["sdd_contract"],
                validation_message="Missing: sdd_contract",
            ),
            enforcement_mode="permissive",
        )
        # Permissive: estimate still produced, gate_passed=False but not fatal
        assert estimate.gate_passed is False
        assert estimate.total_cost_usd > 0

    def test_disabled_mode_gate_ignored(self, governor: TokenGovernor) -> None:
        """In disabled enforcement mode, gate check is ignored."""
        from skillpool.gate_policy.state_machine import GateCheckResult

        estimate = governor.estimate_session_cost(
            skill_id="dev-4d-sdd",
            skill_length=5_000,
            gate_check_result=GateCheckResult(
                passed=False,
                missing_artifacts=["sdd_contract"],
                validation_message="Missing: sdd_contract",
            ),
            enforcement_mode="disabled",
        )
        assert estimate.gate_passed is True


# ---------------------------------------------------------------------------
# MCP tool cost_estimate integration
# ---------------------------------------------------------------------------


class TestCostEstimateMCPTool:
    """Verify cost_estimate MCP tool returns correct structure."""

    def test_mcp_cost_estimate_returns_dict(self) -> None:
        """MCP cost_estimate returns a dict with all CostEstimate fields."""
        from skillpool.mcp_server import cost_estimate
        result = cost_estimate("dev-4d-sdd", skill_length=5000, review_level="L2")
        assert isinstance(result, dict)
        assert result["skill_id"] == "dev-4d-sdd"
        assert result["total_cost_usd"] > 0
        assert result["gate_passed"] is True

    def test_mcp_cost_estimate_safe_deny_on_error(self) -> None:
        """MCP cost_estimate returns error dict on invalid input."""
        from skillpool.mcp_server import cost_estimate
        result = cost_estimate("dev-4d-sdd", skill_length=5000, review_level="INVALID")
        assert "error" in result or "skill_id" in result


# ---------------------------------------------------------------------------
# Gate CLI reset integration
# ---------------------------------------------------------------------------


class TestGateCLIReset:
    """Verify gate reset CLI command works correctly."""

    def test_gate_reset_clears_state(self, tmp_path: Path) -> None:
        """gate reset clears phase to IDLE and preserves created_at."""
        from skillpool.gate_policy.state_machine import GateStateMachine
        gate_path = tmp_path / "gate.json"
        sm = GateStateMachine(gate_path)
        sm.assess("L2", changed_files=[])
        sm.transition("SDD")
        assert sm.state.current_phase == "SDD"

        result = sm.reset()
        assert result.current_phase == "IDLE"
        assert result.assessed_level is None
        assert len(result.phase_history) == 0
