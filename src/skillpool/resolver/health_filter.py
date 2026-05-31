"""HealthFilter — filter skills by health score threshold."""
from __future__ import annotations

from typing import Optional


class HealthFilter:
    """Filter skills based on health_score.

    Skills with health_score < min_score are excluded.

    Usage:
        hf = HealthFilter(min_score=0.6)
        passed, excluded = hf.filter(skills)
    """

    def __init__(self, min_score: float = 0.6) -> None:
        self.min_score = min_score

    def filter(self, skills: list[dict]) -> tuple[list[dict], list[str]]:
        """Filter skills by health_score.

        Args:
            skills: List of dicts with at least 'skill_id' and 'health_score' keys.

        Returns:
            Tuple of (passed_skills, excluded_skill_ids)
        """
        passed = []
        excluded = []

        for skill in skills:
            health = skill.get("health_score", 1.0)
            if health >= self.min_score:
                passed.append(skill)
            else:
                excluded.append(skill.get("skill_id", "unknown"))

        return passed, excluded
