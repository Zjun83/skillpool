"""
Skill Lifecycle State Machine — 9-state enumeration with transition validation.

States: DRAFT → PROPOSED → UNDER_REVIEW → APPROVED → ACTIVE → DEPRECATED → ARCHIVED → REMOVED
                                                                          ↗              ↘
        REJECTED ←───────────────────────────────────────────────────────────────────────
            ↓
        DRAFT (rework cycle)

Terminal state: REMOVED (no outgoing transitions)
"""

from enum import IntEnum
from typing import Optional


class SkillLifecycleState(IntEnum):
    """9-state lifecycle for skills in the pool."""
    DRAFT = 0
    PROPOSED = 1
    UNDER_REVIEW = 2
    APPROVED = 3
    REJECTED = 4
    ACTIVE = 5
    DEPRECATED = 6
    ARCHIVED = 7
    REMOVED = 8


# Transition table: from_state → set of valid to_states
_TRANSITIONS: dict[SkillLifecycleState, list[SkillLifecycleState]] = {
    SkillLifecycleState.DRAFT: [
        SkillLifecycleState.PROPOSED,
        SkillLifecycleState.REMOVED,
    ],
    SkillLifecycleState.PROPOSED: [
        SkillLifecycleState.UNDER_REVIEW,
        SkillLifecycleState.DRAFT,
        SkillLifecycleState.REMOVED,
    ],
    SkillLifecycleState.UNDER_REVIEW: [
        SkillLifecycleState.APPROVED,
        SkillLifecycleState.REJECTED,
        SkillLifecycleState.PROPOSED,
    ],
    SkillLifecycleState.APPROVED: [
        SkillLifecycleState.ACTIVE,
        SkillLifecycleState.REJECTED,
    ],
    SkillLifecycleState.REJECTED: [
        SkillLifecycleState.DRAFT,
        SkillLifecycleState.REMOVED,
    ],
    SkillLifecycleState.ACTIVE: [
        SkillLifecycleState.DEPRECATED,
        SkillLifecycleState.ARCHIVED,
    ],
    SkillLifecycleState.DEPRECATED: [
        SkillLifecycleState.ARCHIVED,
        SkillLifecycleState.ACTIVE,
        SkillLifecycleState.REMOVED,
    ],
    SkillLifecycleState.ARCHIVED: [
        SkillLifecycleState.ACTIVE,
        SkillLifecycleState.REMOVED,
    ],
    SkillLifecycleState.REMOVED: [],
}


def validate_transition(
    from_state: SkillLifecycleState,
    to_state: SkillLifecycleState,
) -> bool:
    """Check if a transition from from_state to to_state is valid."""
    if from_state == to_state:
        return False
    return to_state in _TRANSITIONS.get(from_state, [])


def get_valid_transitions(
    from_state: SkillLifecycleState,
) -> list[SkillLifecycleState]:
    """Return sorted list of valid target states from from_state."""
    return sorted(_TRANSITIONS.get(from_state, []), key=lambda s: s.value)


def is_terminal(state: SkillLifecycleState) -> bool:
    """Check if a state is terminal (no outgoing transitions)."""
    return len(_TRANSITIONS.get(state, [])) == 0


def get_state_name(state: SkillLifecycleState) -> str:
    """Return lowercase snake_case name of a state."""
    return state.name.lower()


def parse_state(name: str) -> Optional[SkillLifecycleState]:
    """Parse a state name (case-insensitive) into SkillLifecycleState.
    Returns None if the name is not a valid state.
    """
    if not name:
        return None
    upper = name.strip().upper()
    try:
        return SkillLifecycleState[upper]
    except KeyError:
        return None
