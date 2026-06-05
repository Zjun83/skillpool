"""CostManager — unified cost tracking, budgeting, and throttling."""

from __future__ import annotations

from skillpool.cost.models import (
    BudgetStatus,
    CostDashboardResponse,
    CostQuery,
    CostRecord,
    ThrottleAction,
)
from skillpool.cost.token_governor import TokenGovernor
from skillpool.cost.budget_tracker import BudgetTracker
from skillpool.cost.trace_ceiling import TraceCeiling
from skillpool.cost.audit_hash import AuditHashChain
from skillpool.cost.dashboard import CostDashboard


class CostManager:
    """Central cost management: recording, throttling, budgeting, auditing.

    Combines TokenGovernor, BudgetTracker, TraceCeiling, AuditHashChain/AuditLayer,
    and CostDashboard into a single facade.

    When an AuditLayer is provided via audit_layer parameter, it is used for
    full 34-field OTel audit records. Otherwise the lightweight AuditHashChain
    is used for basic hash chain integrity.
    """

    def __init__(
        self,
        monthly_budget_usd: float = 5000.0,
        trace_ceiling_usd: float = 5.0,
        audit_layer=None,
    ) -> None:
        self._governor = TokenGovernor()
        self._budget = BudgetTracker(monthly_budget_usd=monthly_budget_usd)
        self._trace_ceiling = TraceCeiling(ceiling_usd=trace_ceiling_usd)
        # Use full AuditLayer if provided, otherwise lightweight AuditHashChain
        if audit_layer is not None:
            self._audit = audit_layer
            self._audit_full = True
        else:
            self._audit = AuditHashChain()
            self._audit_full = False
        self._dashboard = CostDashboard(governor=self._governor, budget_tracker=self._budget)

    def report_cost(self, record: CostRecord) -> bool:
        """Process a cost record: validate, record, check throttles.

        Returns True if the cost was accepted, False if rejected by
        budget or trace ceiling.
        """
        total_tokens = record.tokens_input + record.tokens_output

        # Check trace ceiling
        allowed, reason = self._trace_ceiling.check(record.trace_id, record.cost_usd)
        if not allowed:
            return False

        # Check budget threshold
        threshold, action = self._budget.check_budget_threshold()
        if action == "block":
            return False

        # Record usage
        self._governor.record_usage(record.agent_id, total_tokens)
        self._budget.record_cost(record.cost_usd)
        self._trace_ceiling.record_trace_cost(record.trace_id, record.cost_usd)

        # Audit record: full AuditLayer or lightweight AuditHashChain
        if self._audit_full:
            self._audit.append(
                action="cost_record",
                object_id=record.agent_id,
                result="success",
                metadata={
                    "cost_usd": record.cost_usd,
                    "tokens_input": record.tokens_input,
                    "tokens_output": record.tokens_output,
                    "trace_id": record.trace_id,
                },
                trace_id=record.trace_id,
            )
        else:
            self._audit.append(record.model_dump(mode="json"))

        self._dashboard.record(
            agent_id=record.agent_id,
            tokens_input=record.tokens_input,
            tokens_output=record.tokens_output,
            cost_usd=record.cost_usd,
            model=record.model,
            operation=record.operation,
            skill_id=record.skill_id,
        )

        return True

    def get_dashboard(self, query: CostQuery) -> CostDashboardResponse:
        """Query the cost dashboard."""
        return self._dashboard.query(query)

    def get_budget(self) -> BudgetStatus:
        """Return current monthly budget status."""
        return self._dashboard.get_budget_status()

    def check_throttle(self, agent_id: str, tokens: int) -> ThrottleAction:
        """Check throttle status for an agent/token request."""
        action, _ = self._governor.check(agent_id, tokens)
        return action
