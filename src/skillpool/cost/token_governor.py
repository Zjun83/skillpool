"""TokenGovernor — per-agent daily token budget enforcement."""
from __future__ import annotations

from dataclasses import dataclass, field

from skillpool.cost.models import AgentConfig, ThrottleAction


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
