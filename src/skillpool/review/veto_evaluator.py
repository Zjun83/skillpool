"""VetoEvaluator — VETO V1-V6 rule evaluation.

Rules:
  V1: D3 < 7.0 → block
  V2: D5 < 7.0 → block
  V3: D7 < 7.5 → block
  V4: D11 < 6.0 → block
  V5: D10 < 5.5 → risk_notice (not block)
  V6: baseline_avg < 7.5 → veto_explanation
"""

from __future__ import annotations

from skillpool.review.models import VetoDetail, VetoRule

# Baseline dimensions for V6 calculation
_BASELINE_DIMS = {"D3", "D5", "D7", "D10", "D11"}

# Veto rule definitions: (rule, dimension, threshold, blocks)
_VETO_RULES = [
    (VetoRule.V1, "D3", 7.0, True),
    (VetoRule.V2, "D5", 7.0, True),
    (VetoRule.V3, "D7", 7.5, True),
    (VetoRule.V4, "D11", 6.0, True),
    (VetoRule.V5, "D10", 5.5, False),  # risk notice, not block
]


class VetoEvaluator:
    """Evaluate VETO rules V1-V6 against dimension scores."""

    def evaluate(self, scores: dict[str, float]) -> tuple[list[VetoDetail], bool]:
        """
        Evaluate all veto rules.

        Returns:
            (veto_details, veto_triggered) where veto_triggered is True
            if any blocking veto is active.
        """
        details: list[VetoDetail] = []
        any_blocking = False

        # V1-V5: individual dimension checks
        for rule, dimension, threshold, blocks in _VETO_RULES:
            score = scores.get(dimension, 0.0)  # Default to failing if not present
            triggered = score < threshold

            if triggered:
                details.append(
                    VetoDetail(
                        rule=rule,
                        dimension=dimension,
                        score=score,
                        threshold=threshold,
                        blocks=blocks,
                        recommendation=self._recommendation(rule, score, threshold),
                    )
                )
                if blocks:
                    any_blocking = True

        # V6: baseline average check
        baseline_scores = [scores.get(d, 0.0) for d in _BASELINE_DIMS if d in scores]
        if baseline_scores:
            avg = sum(baseline_scores) / len(baseline_scores)
            if avg < 7.5:
                details.append(
                    VetoDetail(
                        rule=VetoRule.V6,
                        dimension="baseline_avg",
                        score=avg,
                        threshold=7.5,
                        blocks=True,  # V6 blocks — veto explanation required
                        recommendation="Improve baseline dimension scores above 7.5 average",
                    )
                )
                any_blocking = True

        return details, any_blocking

    def _recommendation(self, rule: VetoRule, score: float, threshold: float) -> str:
        """Generate recommendation for a triggered veto."""
        gap = threshold - score
        if rule == VetoRule.V1:
            return f"Improve security compliance (D3) by {gap:.1f} points"
        if rule == VetoRule.V2:
            return f"Improve fault tolerance (D5) by {gap:.1f} points"
        if rule == VetoRule.V3:
            return f"Improve testability (D7) by {gap:.1f} points"
        if rule == VetoRule.V4:
            return f"Improve engineering feasibility (D11) by {gap:.1f} points"
        if rule == VetoRule.V5:
            return "Review protocol timeliness (D10) — risk notice, not blocking"
        return "Address identified dimension gap"
