"""CostDashboard — aggregated cost query and reporting."""
from __future__ import annotations

from datetime import datetime, timedelta

from skillpool.cost.models import (
    AgentConfig,
    AgentCost,
    CostDashboardResponse,
    CostQuery,
    BudgetStatus,
)
from skillpool.cost.token_governor import TokenGovernor
from skillpool.cost.budget_tracker import BudgetTracker
from skillpool.utils.time_utils import utc_now


class CostDashboard:
    """Aggregate cost data across agents for dashboard queries.

    Uses TokenGovernor for per-agent budget/throttle state and
    BudgetTracker for monthly budget status.
    """

    def __init__(
        self,
        governor: TokenGovernor,
        budget_tracker: BudgetTracker,
    ) -> None:
        self._governor = governor
        self._budget = budget_tracker
        # In-memory cost records for aggregation
        self._records: list[dict] = []

    def record(self, agent_id: str, tokens_input: int, tokens_output: int, cost_usd: float,
               model: str = "", operation: str = "", skill_id: str = "") -> None:
        """Store a cost record for later querying."""
        self._records.append({
            "agent_id": agent_id,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost_usd": cost_usd,
            "model": model,
            "operation": operation,
            "skill_id": skill_id,
            "timestamp": utc_now().isoformat(),
        })

    def query(self, request: CostQuery) -> CostDashboardResponse:
        """Query aggregated cost data.

        Supports multi-dimension grouping: agent_id, model, skill_id, operation.
        """
        # Filter by agent_id if specified
        records = self._records
        if request.agent_id:
            records = [r for r in records if r["agent_id"] == request.agent_id]

        # Aggregate by agent
        agent_data: dict[str, dict] = {}
        model_data: dict[str, dict] = {}
        skill_data: dict[str, dict] = {}
        op_data: dict[str, dict] = {}
        total_cost = 0.0
        total_tokens = 0

        for r in records:
            aid = r["agent_id"]
            if aid not in agent_data:
                agent_data[aid] = {"tokens": 0, "cost_usd": 0.0}
            agent_data[aid]["tokens"] += r["tokens_input"] + r["tokens_output"]
            agent_data[aid]["cost_usd"] += r["cost_usd"]

            # Group by model
            model = r.get("model", "")
            if model:
                if model not in model_data:
                    model_data[model] = {"tokens": 0, "cost_usd": 0.0}
                model_data[model]["tokens"] += r["tokens_input"] + r["tokens_output"]
                model_data[model]["cost_usd"] += r["cost_usd"]

            # Group by skill_id
            skill = r.get("skill_id", "")
            if skill:
                if skill not in skill_data:
                    skill_data[skill] = {"tokens": 0, "cost_usd": 0.0}
                skill_data[skill]["tokens"] += r["tokens_input"] + r["tokens_output"]
                skill_data[skill]["cost_usd"] += r["cost_usd"]

            # Group by operation
            op = r.get("operation", "")
            if op:
                if op not in op_data:
                    op_data[op] = {"tokens": 0, "cost_usd": 0.0}
                op_data[op]["tokens"] += r["tokens_input"] + r["tokens_output"]
                op_data[op]["cost_usd"] += r["cost_usd"]

            total_cost += r["cost_usd"]
            total_tokens += r["tokens_input"] + r["tokens_output"]

        # Build per-agent summaries
        by_agent: list[AgentCost] = []
        for aid, data in agent_data.items():
            cfg = self._governor.get_config(aid)
            pct_of_total = (data["cost_usd"] / total_cost * 100) if total_cost > 0 else 0.0
            budget_limit = cfg.daily_limit_tokens if cfg else 0
            daily_usage = self._governor.get_daily_usage(aid)
            budget_consumed_pct = (daily_usage / budget_limit) if budget_limit > 0 else 0.0

            by_agent.append(AgentCost(
                agent_id=aid,
                agent_type=cfg.agent_type if cfg else "",
                tokens=data["tokens"],
                cost_usd=round(data["cost_usd"], 4),
                pct_of_total=round(pct_of_total, 2),
                budget_limit=budget_limit,
                budget_consumed_pct=round(budget_consumed_pct, 4),
                throttled=self._governor.is_throttled(aid),
            ))

        budget_pct = self._budget.get_consumed_pct() * 100

        # Projected overspend
        consumed_pct = self._budget.get_consumed_pct()
        projected_overspend = max(0.0, (consumed_pct * 2.0 - 1.0) * 100) if consumed_pct > 0.5 else 0.0

        # Time series generation
        series = self._build_time_series(records, request.granularity)

        return CostDashboardResponse(
            window=request.window,
            total_cost_usd=round(total_cost, 4),
            total_tokens=total_tokens,
            monthly_budget_usd=self._budget.monthly_budget_usd,
            monthly_budget_consumed_pct=round(budget_pct, 2),
            by_agent=by_agent,
            by_model=model_data,
            by_skill=skill_data,
            by_operation=op_data,
            series=series,
            projected_overspend_pct=round(projected_overspend, 2),
        )

    @staticmethod
    def _build_time_series(records: list[dict], granularity: str) -> list[dict]:
        """Build time series buckets from cost records.

        granularity: "5m" → 5-minute buckets, "1h" → hourly, "1d" → daily.
        """
        if not records:
            return []

        delta_map = {"5m": timedelta(minutes=5), "1h": timedelta(hours=1), "1d": timedelta(days=1)}
        delta = delta_map.get(granularity, timedelta(hours=1))

        buckets: dict[str, dict] = {}
        for r in records:
            ts = datetime.fromisoformat(r["timestamp"])
            # Floor to bucket boundary
            if granularity == "5m":
                bucket_key = ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0).isoformat()
            elif granularity == "1d":
                bucket_key = ts.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            else:  # 1h
                bucket_key = ts.replace(minute=0, second=0, microsecond=0).isoformat()

            if bucket_key not in buckets:
                buckets[bucket_key] = {"timestamp": bucket_key, "tokens": 0, "cost_usd": 0.0}
            buckets[bucket_key]["tokens"] += r["tokens_input"] + r["tokens_output"]
            buckets[bucket_key]["cost_usd"] += r["cost_usd"]

        return sorted(buckets.values(), key=lambda b: b["timestamp"])

    def get_budget_status(self) -> BudgetStatus:
        """Return current monthly budget status."""
        configs = list(self._governor._configs.values())
        return self._budget.get_status(agent_configs=configs)
