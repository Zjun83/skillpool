"""SuspectMarker — tracks skills marked as suspect during review."""
from __future__ import annotations

from skillpool.review.models import SuspectSkill


class SuspectMarker:
    """Tracks skills marked as suspect during review.

    Usage:
        marker = SuspectMarker()
        marker.mark("S05a", reason="D3 below threshold", suspected_dimension="D3")
        assert marker.is_suspect("S05a")
        marker.clear()
    """

    def __init__(self) -> None:
        self._suspects: dict[str, SuspectSkill] = {}

    def mark(self, skill_id: str, reason: str, suspected_dimension: str = "") -> None:
        """Add a skill to the suspect set."""
        self._suspects[skill_id] = SuspectSkill(
            skill_id=skill_id,
            reason=reason,
            suspected_dimension=suspected_dimension,
        )

    def is_suspect(self, skill_id: str) -> bool:
        """Check whether a skill is currently marked as suspect."""
        return skill_id in self._suspects

    def clear(self) -> None:
        """Remove all skills from the suspect set."""
        self._suspects.clear()

    def list_suspects(self) -> list[SuspectSkill]:
        """Return all currently marked suspect skills."""
        return list(self._suspects.values())
