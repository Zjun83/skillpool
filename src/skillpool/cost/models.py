"""Cost models — Pydantic schemas for cost tracking and budgeting."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field

from skillpool.utils.time_utils import utc_now


class ThrottleAction(StrEnum):
    ALLOW = "allow"
    THROTTLE = "throttle"
    REJECT = "reject"


class AgentConfig(BaseModel):
    """Per-agent token budget configuration."""
    agent_id: str
    agent_type: str = "worker"
    daily_limit_tokens: int = Field(default=0, description="0 means unlimited")
    throttle_at_pct: float = Field(default=0.8, ge=0.0, le=1.0)
    throttle_to_pct: float = Field(default=0.25, ge=0.0, le=1.0)
    is_critical: bool = False


class CostRecord(BaseModel):
    """A single cost event record."""
    agent_id: str
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = Field(default=0.0, ge=0.0)
    model: str = ""
    operation: str = ""
    trace_id: str = ""
    skill_id: str = ""  # V4.1: per-skill cost attribution
    timestamp: datetime = Field(default_factory=utc_now)


class CostQuery(BaseModel):
    """Query parameters for cost dashboard.

    V4.1: Supports multi-dimension grouping and granularity.
    """
    window: str = Field(default="24h", pattern=r"^(1h|6h|24h|7d|30d)$")
    group_by: list[str] = Field(default_factory=lambda: ["agent_id"])
    agent_id: Optional[str] = None
    granularity: str = Field(default="1d", pattern=r"^(5m|1h|1d)$", description="Time series granularity")


class AgentCost(BaseModel):
    """Cost summary for a single agent."""
    agent_id: str
    agent_type: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    pct_of_total: float = 0.0
    budget_limit: int = 0
    budget_consumed_pct: float = 0.0
    throttled: bool = False


class CostDashboardResponse(BaseModel):
    """Response from cost dashboard query.

    V4.1: Multi-dimension grouping (by_agent, by_model, by_skill, by_operation)
    and time series data.
    """
    window: str
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    monthly_budget_usd: float = 0.0
    monthly_budget_consumed_pct: float = 0.0
    by_agent: list[AgentCost] = Field(default_factory=list)
    by_model: dict[str, dict] = Field(default_factory=dict, description="Cost grouped by model: {model: {tokens, cost_usd}}")
    by_skill: dict[str, dict] = Field(default_factory=dict, description="Cost grouped by skill_id: {skill_id: {tokens, cost_usd}}")
    by_operation: dict[str, dict] = Field(default_factory=dict, description="Cost grouped by operation: {op: {tokens, cost_usd}}")
    series: list[dict] = Field(default_factory=list, description="Time series data [{timestamp, agent_id, tokens, cost_usd}]")
    projected_overspend_pct: float = Field(default=0.0, description="Projected overspend percentage if current burn rate continues")


class BudgetStatus(BaseModel):
    """Monthly budget status."""
    monthly_budget_usd: float
    consumed_usd: float = 0.0
    remaining_usd: float = 0.0
    consumed_pct: float = 0.0
    projected_month_end_usd: float = 0.0
    per_agent_limits: list[AgentConfig] = Field(default_factory=list)
