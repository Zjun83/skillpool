"""Combiner — Skill combination lifecycle management and recommendation.

Manages the full lifecycle of skill combinations:
  DISCOVERED → VALIDATING → PROMOTED → DEPRECATED → RETIRED
                    ↘→ REJECTED

Two discovery channels:
  1. Auto-discovered: Thompson Sampling explores new combinations from execution data
  2. Human-specified: Expert annotations in CSDF synergies field

Both channels require validation through execution feedback — human specification
only skips DISCOVERED, entering VALIDATING directly.

Part of SkillPool — independent infrastructure, shared by all agents.
"""
from skillpool.combiner.models import (
    CombinationLifecycleState,
    SkillCombination,
    CombinationTransitionResult,
    MIN_VALIDATION_EXECUTIONS,
)
from skillpool.combiner.lifecycle import CombinationLifecycleManager

__all__ = [
    "CombinationLifecycleState",
    "SkillCombination",
    "CombinationTransitionResult",
    "CombinationLifecycleManager",
    "MIN_VALIDATION_EXECUTIONS",
]
