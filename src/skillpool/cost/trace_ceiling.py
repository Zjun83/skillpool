"""TraceCeiling — per-trace cost ceiling with circuit breaker."""
from __future__ import annotations


class TraceCeiling:
    """Enforce a cost ceiling per trace_id.

    When a trace's cumulative cost exceeds the ceiling, all further
    operations under that trace are blocked (circuit broken).
    """

    def __init__(self, ceiling_usd: float = 5.0) -> None:
        self.ceiling_usd = ceiling_usd
        self._trace_costs: dict[str, float] = {}

    def record_trace_cost(self, trace_id: str, cost_usd: float) -> None:
        """Record a cost against a trace."""
        if trace_id not in self._trace_costs:
            self._trace_costs[trace_id] = 0.0
        self._trace_costs[trace_id] += cost_usd

    def check(self, trace_id: str, additional_cost: float) -> tuple[bool, str]:
        """Check if an additional cost is allowed for a trace.

        Returns (allowed, reason).
        """
        current = self._trace_costs.get(trace_id, 0.0)
        if current + additional_cost > self.ceiling_usd:
            return False, f"trace {trace_id} ceiling exceeded: ${current:.4f} + ${additional_cost:.4f} > ${self.ceiling_usd:.2f}"
        return True, "ok"

    def is_circuit_broken(self, trace_id: str) -> bool:
        """Check if a trace has hit its cost ceiling."""
        return self._trace_costs.get(trace_id, 0.0) >= self.ceiling_usd
