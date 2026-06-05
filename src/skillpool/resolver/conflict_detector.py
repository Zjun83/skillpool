"""ConflictDetector — Jaccard similarity conflict detection between skills."""

from __future__ import annotations

import re
from typing import Optional


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase word set."""
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


class ConflictDetector:
    """Detect naming conflicts between skills using Jaccard similarity.

    Usage:
        cd = ConflictDetector()
        cd.register("S01", "Requirement Coverage", "D1", namespaces=["req", "coverage"])
        conflicts = cd.detect(threshold=0.5)
    """

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self._skills: dict[str, dict] = {}  # skill_id → {name, tokens, namespaces}

    def register(
        self,
        skill_id: str,
        name: str = "",
        dimension: str = "",
        namespaces: Optional[list[str]] = None,
    ) -> None:
        """Register a skill for conflict detection."""
        tokens = _tokenize(f"{name} {dimension} {' '.join(namespaces or [])}")
        self._skills[skill_id] = {
            "name": name,
            "tokens": tokens,
            "namespaces": set(namespaces or []),
        }

    def detect(self, threshold: Optional[float] = None) -> list[dict]:
        """Detect all pairwise conflicts above threshold.

        Returns list of dicts: {skill_a, skill_b, jaccard_score, severity, overlapping_namespaces}
        """
        thresh = threshold if threshold is not None else self.threshold
        conflicts = []
        skill_ids = list(self._skills.keys())

        for i in range(len(skill_ids)):
            for j in range(i + 1, len(skill_ids)):
                a_id, b_id = skill_ids[i], skill_ids[j]
                a_info, b_info = self._skills[a_id], self._skills[b_id]

                score = jaccard_similarity(a_info["tokens"], b_info["tokens"])
                if score >= thresh:
                    overlapping = a_info["namespaces"] & b_info["namespaces"]
                    severity = self._classify_severity(score, overlapping)
                    conflicts.append(
                        {
                            "skill_a": a_id,
                            "skill_b": b_id,
                            "jaccard_score": round(score, 4),
                            "severity": severity,
                            "conflict_type": self._classify_conflict_type(overlapping, score),
                            "overlapping_namespaces": sorted(overlapping),
                            "recommendation": self._generate_recommendation(severity, overlapping),
                        }
                    )

        return conflicts

    def _classify_severity(self, score: float, overlapping: set[str]) -> str:
        """Classify conflict severity based on Jaccard score and namespace overlap."""
        if overlapping and score >= 0.7:
            return "high"
        if overlapping or score >= 0.7:
            return "medium"
        return "low"

    def _classify_conflict_type(self, overlapping: set[str], score: float) -> str:
        """Classify conflict type per schema enum."""
        if overlapping:
            return "namespace_overlap"
        if score >= 0.8:
            return "semantic_conflict"
        return "namespace_overlap"  # Default for Jaccard-based detection

    def _generate_recommendation(self, severity: str, overlapping: set[str]) -> str:
        """Generate a recommendation for resolving the conflict."""
        if severity == "high":
            return "Consider merging or removing one of the conflicting skills"
        if severity == "medium":
            return "Review skill boundaries and adjust namespaces"
        return "Monitor for potential future conflicts"

    def clear(self) -> None:
        """Remove all registered skills."""
        self._skills.clear()
