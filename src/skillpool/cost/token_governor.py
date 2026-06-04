"""TokenGovernor — per-agent daily token budget enforcement."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from skillpool.cost.models import AgentConfig, CostEstimate, ThrottleAction
from skillpool.utils.time_utils import utc_now


@dataclass
class _Usage:
    """Internal daily usage tracker for a single agent."""
    tokens: int = 0


# Preset agent configurations from CLAUDE.md Section 9.2
PRESET_AGENT_CONFIGS: list[AgentConfig] = [
    AgentConfig(agent_id="root_planner", agent_type="planner", daily_limit_tokens=0, is_critical=True),
    AgentConfig(agent_id="sub_planner", agent_type="planner", daily_limit_tokens=0, is_critical=True),
    AgentConfig(agent_id="level1_worker", agent_type="worker", daily_limit_tokens=0, is_critical=True),
    AgentConfig(agent_id="level2_worker", agent_type="worker", daily_limit_tokens=0, is_critical=True),
    AgentConfig(agent_id="evolver_v4", agent_type="evolver", daily_limit_tokens=100_000, throttle_at_pct=0.8, throttle_to_pct=0.5),
    AgentConfig(agent_id="knowledge_refiner", agent_type="refiner", daily_limit_tokens=500_000, throttle_at_pct=0.9, throttle_to_pct=0.25),
    AgentConfig(agent_id="sandbox_validator", agent_type="validator", daily_limit_tokens=50_000, throttle_at_pct=0.9, throttle_to_pct=0.25),
    AgentConfig(agent_id="hermes_refiner", agent_type="refiner", daily_limit_tokens=300_000, throttle_at_pct=0.8, throttle_to_pct=0.5),
]


class TokenGovernor:
    """Enforce per-agent daily token budgets with throttle/reject logic.

    Agents with daily_limit_tokens=0 are unlimited.
    When usage crosses throttle_at_pct of the limit, requests are throttled
    (allowed but reduced). When usage reaches 100%, requests are rejected.
    """

    def __init__(self, configs: list[AgentConfig] | None = None) -> None:
        self._configs: dict[str, AgentConfig] = {}
        self._usage: dict[str, _Usage] = {}

        for cfg in configs or PRESET_AGENT_CONFIGS:
            self._configs[cfg.agent_id] = cfg
            self._usage[cfg.agent_id] = _Usage()

    def get_config(self, agent_id: str) -> AgentConfig | None:
        """Return the config for an agent, or None if unknown."""
        return self._configs.get(agent_id)

    def check(self, agent_id: str, requested_tokens: int) -> tuple[ThrottleAction, int]:
        """Check whether a token request is allowed.

        Returns (action, allowed_tokens). For unlimited agents, always allows
        the full request. For budgeted agents:
          - below throttle threshold: ALLOW with full tokens
          - between throttle and 100%: THROTTLE with reduced tokens
          - at or above 100%: REJECT with 0 tokens
        """
        cfg = self._configs.get(agent_id)
        if cfg is None:
            # Unknown agent: allow by default
            return ThrottleAction.ALLOW, requested_tokens

        if cfg.daily_limit_tokens == 0:
            return ThrottleAction.ALLOW, requested_tokens

        usage = self._usage.get(agent_id, _Usage())
        pct_consumed = usage.tokens / cfg.daily_limit_tokens

        if pct_consumed >= 1.0:
            return ThrottleAction.REJECT, 0

        if pct_consumed >= cfg.throttle_at_pct:
            # Throttle: reduce to throttle_to_pct of the remaining budget
            remaining = cfg.daily_limit_tokens - usage.tokens
            allowed = int(remaining * cfg.throttle_to_pct)
            allowed = max(0, min(allowed, requested_tokens))
            return ThrottleAction.THROTTLE, allowed

        return ThrottleAction.ALLOW, requested_tokens

    def record_usage(self, agent_id: str, tokens_used: int) -> None:
        """Record actual token usage for an agent."""
        if agent_id not in self._usage:
            self._usage[agent_id] = _Usage()
        self._usage[agent_id].tokens += tokens_used

    def get_daily_usage(self, agent_id: str) -> int:
        """Return tokens consumed today by an agent."""
        usage = self._usage.get(agent_id)
        return usage.tokens if usage else 0

    def is_throttled(self, agent_id: str) -> bool:
        """Check if an agent is currently in throttled state."""
        cfg = self._configs.get(agent_id)
        if cfg is None or cfg.daily_limit_tokens == 0:
            return False
        usage = self._usage.get(agent_id, _Usage())
        return usage.tokens >= cfg.daily_limit_tokens * cfg.throttle_at_pct

    def reset_daily(self) -> None:
        """Reset all daily usage counters (for testing or day rollover)."""
        for usage in self._usage.values():
            usage.tokens = 0

    # -------------------------------------------------------------------
    # Session Cost Estimation (V4.2)
    # -------------------------------------------------------------------

    # P50 conservative pricing: $0.003/1K tokens (Claude Sonnet)
    _P50_PRICE_PER_1K: float = 0.003
    # Approximate chars per token for English/code content
    _CHARS_PER_TOKEN: int = 4
    # Review overhead: estimated token counts for review checkpoints
    _L2_REVIEW_TOKENS: int = 8_000
    _L3_REVIEW_TOKENS: int = 15_000
    _REVIEW_CHECKPOINT_TOKENS: int = 3_000

    def estimate_session_cost(
        self,
        skill_id: str,
        skill_length: int = 0,
        review_level: str = "L1",
        include_review_checkpoint: bool = False,
        skill_get_fn: Callable[[str], Any] | None = None,
        gate_check_result: Any | None = None,
        enforcement_mode: str = "strict",
        emergency_bypass_path: str | None = None,
        changed_files: list[str] | None = None,
    ) -> CostEstimate:
        """Estimate session cost for a skill execution.

        Uses P50 conservative pricing ($0.003/1K tokens).
        Combines: skill execution cost + L2/L3 review overhead + checkpoint overhead.

        Args:
            skill_id: Skill identifier (e.g. "dev-4d-sdd").
            skill_length: Character count of skill definition (fallback if skill_get unavailable).
            review_level: Complexity level (L0/L1/L2/L3+L2+).
            include_review_checkpoint: Whether to include review checkpoint overhead.
            skill_get_fn: Optional callable to fetch skill definition via MCP.
            gate_check_result: Optional GateCheckResult from gate validation.
            enforcement_mode: Gate enforcement mode (strict/permissive/disabled).
            emergency_bypass_path: Path to emergency_overrides.json file.
            changed_files: List of changed file paths for gate pattern matching.

        Returns:
            CostEstimate with full cost breakdown.
        """
        # Step 1: Resolve skill_length from skill_get or fallback
        resolved_length = skill_length
        if skill_get_fn is not None:
            try:
                skill_data = skill_get_fn(skill_id)
                if skill_data is not None and hasattr(skill_data, "content"):
                    resolved_length = len(skill_data.content)
                elif isinstance(skill_data, dict):
                    content = skill_data.get("content", "")
                    resolved_length = len(content) if content else skill_length
            except Exception:
                pass  # Fallback to provided skill_length

        # Step 2: Estimate token count
        token_count = max(1, resolved_length // self._CHARS_PER_TOKEN)

        # Step 3: Calculate base cost (P50 pricing)
        base_cost_usd = token_count * self._P50_PRICE_PER_1K / 1000

        # Step 4: Calculate review overhead based on level
        l2_overhead = 0.0
        l3_overhead = 0.0
        if review_level in ("L2", "L3+L2+"):
            l2_overhead = self._L2_REVIEW_TOKENS * self._P50_PRICE_PER_1K / 1000
        if review_level == "L3+L2+":
            l3_overhead = self._L3_REVIEW_TOKENS * self._P50_PRICE_PER_1K / 1000

        # Step 5: Calculate review checkpoint overhead
        checkpoint_overhead = 0.0
        if include_review_checkpoint:
            checkpoint_overhead = self._REVIEW_CHECKPOINT_TOKENS * self._P50_PRICE_PER_1K / 1000

        # Step 6: Gate validation
        gate_passed = True
        gate_block_reason = None
        if gate_check_result is not None:
            if enforcement_mode == "disabled":
                gate_passed = True
            elif enforcement_mode == "permissive":
                gate_passed = gate_check_result.passed
            else:  # strict
                gate_passed = gate_check_result.passed
                if not gate_passed:
                    gate_block_reason = gate_check_result.validation_message

        # Step 7: Emergency bypass check
        emergency_bypass_active = False
        if emergency_bypass_path is not None:
            bypass_path = Path(emergency_bypass_path)
            if bypass_path.exists():
                try:
                    data = json.loads(bypass_path.read_text())
                    expires_at = data.get("expires_at")
                    if expires_at:
                        from datetime import datetime, timezone
                        expiry = datetime.fromisoformat(expires_at)
                        if utc_now() < expiry:
                            emergency_bypass_active = True
                    else:
                        # No expiry → bypass active indefinitely
                        emergency_bypass_active = True
                except Exception:
                    pass  # Corrupt file → bypass not active

        # If bypass active, override gate result
        if emergency_bypass_active:
            gate_passed = True
            gate_block_reason = None

        # Step 8: Total cost
        total_cost = base_cost_usd + l2_overhead + l3_overhead + checkpoint_overhead

        return CostEstimate(
            skill_id=skill_id,
            skill_length=resolved_length,
            token_count=token_count,
            base_cost_usd=round(base_cost_usd, 6),
            l2_review_overhead_usd=round(l2_overhead, 6),
            l3_review_overhead_usd=round(l3_overhead, 6),
            review_checkpoint_overhead_usd=round(checkpoint_overhead, 6),
            total_cost_usd=round(total_cost, 6),
            price_per_1k_tokens=self._P50_PRICE_PER_1K,
            gate_passed=gate_passed,
            gate_block_reason=gate_block_reason,
            emergency_bypass_active=emergency_bypass_active,
        )
