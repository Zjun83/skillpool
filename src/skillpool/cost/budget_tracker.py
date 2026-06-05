"""BudgetTracker — monthly budget enforcement with threshold alerts."""

from __future__ import annotations

from skillpool.cost.models import AgentConfig, BudgetStatus


class BudgetTracker:
    """Track monthly cost against a budget with threshold actions.

    Thresholds:
      - >=50% remaining: normal
      - >=25% remaining: caution
      - >=10% remaining: warning
      - 0% remaining: critical (all spending blocked)
    """

    def __init__(self, monthly_budget_usd: float = 5000.0) -> None:
        self.monthly_budget_usd = monthly_budget_usd
        self._consumed_usd: float = 0.0

    def record_cost(self, cost_usd: float) -> None:
        """Record a cost event against the monthly budget."""
        self._consumed_usd += cost_usd

    def get_status(self, agent_configs: list[AgentConfig] | None = None) -> BudgetStatus:
        """Return current monthly budget status."""
        remaining = self.monthly_budget_usd - self._consumed_usd
        consumed_pct = self.get_consumed_pct()
        # Project: if we've used X% so far, assume linear burn to month end
        projected = self._consumed_usd  # simplified; real impl would use day-of-month
        if consumed_pct > 0:
            # Approximate projection assuming mid-month
            projected = self._consumed_usd * 2.0
        return BudgetStatus(
            monthly_budget_usd=self.monthly_budget_usd,
            consumed_usd=round(self._consumed_usd, 4),
            remaining_usd=round(max(0.0, remaining), 4),
            consumed_pct=round(consumed_pct, 4),
            projected_month_end_usd=round(projected, 4),
            per_agent_limits=agent_configs or [],
        )

    def get_consumed_pct(self) -> float:
        """Return percentage of monthly budget consumed (0.0 - 1.0+)."""
        if self.monthly_budget_usd <= 0:
            return 1.0
        return self._consumed_usd / self.monthly_budget_usd

    def check_budget_threshold(self) -> tuple[str, str]:
        """Check budget threshold and return (threshold_name, action).

        Returns:
            - ("normal", "continue") when >50% budget remaining
            - ("caution", "monitor") when 25-50% remaining
            - ("warning", "throttle") when 10-25% remaining
            - ("critical", "block") when <10% remaining
        """
        remaining_pct = 1.0 - self.get_consumed_pct()
        if remaining_pct < 0.10:
            return "critical", "block"
        if remaining_pct < 0.25:
            return "warning", "throttle"
        if remaining_pct < 0.50:
            return "caution", "monitor"
        return "normal", "continue"
