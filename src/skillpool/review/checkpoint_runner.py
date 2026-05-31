"""CheckpointRunner — runs dimension scoring for each checkpoint level."""
from __future__ import annotations

import hashlib
from typing import Optional

from skillpool.review.models import CheckpointLevel

# Dimensions per checkpoint level
SHADOW_DIMENSIONS = ("D1", "D2", "D4", "D6", "D8", "D9", "D12")
BASELINE_DIMENSIONS = ("D3", "D5", "D7", "D10", "D11")
ALL_DIMENSIONS = BASELINE_DIMENSIONS + SHADOW_DIMENSIONS


class CheckpointRunner:
    """Runs dimension scoring for a given checkpoint level.

    Generates deterministic mock scores using a seed derived from
    skill IDs and checkpoint level. In production, these would come
    from actual evaluation logic.

    Usage:
        runner = CheckpointRunner(seed=42)
        scores = runner.run_checkpoint(CheckpointLevel.L2, ["S05a", "S10"])
    """

    def __init__(self, seed: Optional[int] = None):
        self._base_seed = seed

    def run_checkpoint(
        self,
        level: CheckpointLevel,
        skills: list[str],
    ) -> dict[str, float]:
        """Evaluate dimensions for the given checkpoint level.

        Returns a dict of dimension → score (0.0-10.0).
        """
        dimensions = self._dimensions_for_level(level)
        seed = self._make_seed(level, skills)
        return {d: self._generate_score(d, seed) for d in dimensions}

    def _dimensions_for_level(self, level: CheckpointLevel) -> tuple[str, ...]:
        """Return the dimensions to evaluate for each checkpoint level."""
        if level == CheckpointLevel.L1:
            return SHADOW_DIMENSIONS
        elif level == CheckpointLevel.L2:
            return ALL_DIMENSIONS
        elif level == CheckpointLevel.L3:
            return BASELINE_DIMENSIONS
        elif level == CheckpointLevel.L4:
            # L4: baseline regression — only check for new blindspots
            return BASELINE_DIMENSIONS
        return ALL_DIMENSIONS

    def _make_seed(self, level: CheckpointLevel, skills: list[str]) -> int:
        """Derive a deterministic seed from level + skills."""
        if self._base_seed is not None:
            return self._base_seed
        raw = f"{level.value}:{','.join(sorted(skills))}".encode()
        return int(hashlib.sha256(raw).hexdigest()[:8], 16)

    @staticmethod
    def _generate_score(dimension: str, seed: int) -> float:
        """Generate a deterministic score for a dimension.

        Uses a simple hash-based approach to produce scores in [5.0, 10.0].
        """
        combined = f"{dimension}:{seed}".encode()
        h = int(hashlib.sha256(combined).hexdigest()[:8], 16)
        # Map to [5.0, 10.0] range
        return round(5.0 + (h % 5000) / 1000.0, 2)
