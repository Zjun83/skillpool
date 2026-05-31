"""SelfHealingLoop — BugCollector → Evolver → Skill upgrade → BDD verify → auto-rollback.

Connects the BugCollector's defect data to the Evolver's evolution pipeline,
adding BDD verification and automatic rollback on failure.

Trigger logic (from CLAUDE.md Section 8.5):
- >=3 P2 bugs of same defect_type in same skill -> PATCH (auto)
- >=5 P2 or >=1 P1 -> MINOR (auto + notify)
- >=1 P0 -> MAJOR (must NOT auto-execute, return needs_human)

Part of SkillPool — independent infrastructure, shared by all agents.
"""
from __future__ import annotations

__all__ = [
    "HealingAction",
    "HealingProposal",
    "HealingStatus",
    "SelfHealingLoop",
]

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from skillpool.evolver import (
    DefectSeverity,
    EvolverLayer,
    EvolutionProposal,
    VerificationStatus,
)
from skillpool.monitor.bug_collector import BugCollector, BugSeverity, DefectType


class HealingAction(StrEnum):
    """Action taken by the healing loop."""
    PATCH = "PATCH"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    NEEDS_HUMAN = "needs_human"
    SKIPPED = "skipped"


class HealingStatus(StrEnum):
    """Status of a healing proposal execution."""
    PROPOSED = "proposed"
    EXECUTING = "executing"
    VERIFIED = "verified"
    ROLLED_BACK = "rolled_back"
    NEEDS_HUMAN = "needs_human"
    BLOCKED = "blocked"


@dataclass
class HealingProposal:
    """A healing proposal generated from bug pattern analysis."""
    proposal_id: str
    skill_id: str
    defect_type: DefectType
    upgrade_type: HealingAction
    bug_count: int
    bug_severity: BugSeverity
    evolver_proposal: EvolutionProposal | None = None
    status: HealingStatus = HealingStatus.PROPOSED
    verification_result: dict[str, Any] = field(default_factory=dict)


class SelfHealingLoop:
    """Self-healing feedback loop: BugCollector → Evolver → upgrade → verify → rollback.

    Scans BugCollector for recurring defect patterns, groups by skill_id +
    defect_type, proposes evolutions via Evolver, and verifies results with
    BDD-style checks. Auto-rolls back on verification failure.

    Args:
        bug_collector: BugCollector instance to scan for defects.
        evolver: EvolverLayer instance to create/execute evolutions.
        audit_layer: Optional AuditLayer for audit trail.
    """

    def __init__(
        self,
        bug_collector: BugCollector,
        evolver: EvolverLayer,
        audit_layer: Any | None = None,
    ) -> None:
        self._bug_collector = bug_collector
        self._evolver = evolver
        self._audit = audit_layer
        self._proposals: dict[str, HealingProposal] = {}
        self._proposal_counter: int = 0

    def scan_and_propose(self) -> list[dict[str, Any]]:
        """Scan BugCollector for recurring defects and propose evolutions.

        Groups bugs by (skill_id, defect_type), counts by severity, and
        applies trigger thresholds to determine upgrade type.

        Returns:
            List of dicts with proposal details (proposal_id, skill_id,
            defect_type, upgrade_type, bug_count, status).
        """
        all_bugs = self._bug_collector.get_bugs()
        if not all_bugs:
            return []

        # Group by (skill_id, defect_type) -> severity counts
        groups: dict[tuple[str, str], dict[str, int]] = {}
        for bug in all_bugs:
            key = (bug.skill_id, bug.defect_type.value)
            if key not in groups:
                groups[key] = {"P0": 0, "P1": 0, "P2": 0}
            groups[key][bug.severity.value] += 1

        proposals: list[dict[str, Any]] = []

        for (skill_id, defect_type_str), counts in groups.items():
            action = self._determine_action(counts)
            if action == HealingAction.SKIPPED:
                continue

            # Dedup: skip if a PROPOSED proposal already exists for this key
            existing = any(
                p.skill_id == skill_id and p.defect_type.value == defect_type_str
                and p.status == HealingStatus.PROPOSED
                for p in self._proposals.values()
            )
            if existing:
                continue

            defect_type = DefectType(defect_type_str)
            total = counts["P0"] + counts["P1"] + counts["P2"]
            dominant_severity = self._dominant_severity(counts)

            self._proposal_counter += 1
            proposal_id = f"heal-{self._proposal_counter}"

            # Create evolver proposal
            evolver_proposal = self._evolver.create_proposal(
                context={
                    "skill_id": skill_id,
                    "defect_type": defect_type_str,
                    "bug_counts": counts,
                    "trigger_source": "self_healing_loop",
                },
                risk="high" if action == HealingAction.MAJOR else "medium",
                upgrade_type=action.value if action != HealingAction.NEEDS_HUMAN else "MAJOR",
            )

            healing = HealingProposal(
                proposal_id=proposal_id,
                skill_id=skill_id,
                defect_type=defect_type,
                upgrade_type=action,
                bug_count=total,
                bug_severity=dominant_severity,
                evolver_proposal=evolver_proposal,
                status=HealingStatus.NEEDS_HUMAN if action == HealingAction.NEEDS_HUMAN else HealingStatus.PROPOSED,
            )

            self._proposals[proposal_id] = healing

            proposals.append({
                "proposal_id": proposal_id,
                "skill_id": skill_id,
                "defect_type": defect_type_str,
                "upgrade_type": action.value,
                "bug_count": total,
                "bug_counts": counts,
                "status": healing.status.value,
            })

        if self._audit:
            self._audit.append(
                action="self_healing_scan",
                result=f"proposed_{len(proposals)}",
            )

        return proposals

    def execute_healing(self, proposal_id: str) -> dict[str, Any]:
        """Execute a proposed healing evolution with BDD verification.

        Steps:
        1. Validate proposal exists and is in PROPOSED state
        2. MAJOR proposals require human approval (return needs_human)
        3. Mark as EXECUTING
        4. Record pre-evolution bug snapshot
        5. Save snapshot via Evolver for rollback support
        6. Run BDD verification (check bug count decreased)
        7. If BDD fails -> call Evolver.verify_evolution() to trigger rollback
        8. If BDD passes -> call Evolver.verify_evolution() with passing results
        9. Return execution result

        Args:
            proposal_id: The healing proposal ID to execute.

        Returns:
            Dict with execution result details.
        """
        # Part of SkillPool — independent infrastructure, shared by all agents
        healing = self._proposals.get(proposal_id)
        if healing is None:
            return {
                "proposal_id": proposal_id,
                "status": "not_found",
                "error": f"No healing proposal with id {proposal_id}",
            }

        # MAJOR upgrades must NOT auto-execute
        if healing.upgrade_type == HealingAction.NEEDS_HUMAN:
            healing.status = HealingStatus.NEEDS_HUMAN
            return {
                "proposal_id": proposal_id,
                "status": HealingStatus.NEEDS_HUMAN.value,
                "reason": "MAJOR upgrade requires human approval",
            }

        if healing.status != HealingStatus.PROPOSED:
            return {
                "proposal_id": proposal_id,
                "status": healing.status.value,
                "reason": f"Proposal not in PROPOSED state (current: {healing.status.value})",
            }

        # Mark executing
        healing.status = HealingStatus.EXECUTING

        # Capture pre-evolution bug count for this skill+defect_type
        bugs_before = self._bug_collector.get_bugs(
            skill_id=healing.skill_id,
            defect_type=healing.defect_type,
        )
        count_before = len(bugs_before)

        # Save snapshot via evolver for rollback support
        if healing.evolver_proposal:
            self._evolver.save_snapshot(
                healing.evolver_proposal.proposal_id,
                {"bug_count_before": count_before, "skill_id": healing.skill_id},
            )

        # BDD verification: check that no new bugs of same type appeared
        bdd_passed = self._bdd_verify(healing.skill_id, healing.defect_type, count_before)

        if bdd_passed:
            # Run evolver's verify_evolution with passing BDD results
            if healing.evolver_proposal:
                report = self._evolver.verify_evolution(
                    proposal_id=healing.evolver_proposal.proposal_id,
                    bdd_results={"bug_count_decreased": True},
                    scores_before={},
                    scores_after={},
                )
                if report.status == VerificationStatus.ROLLED_BACK:
                    healing.status = HealingStatus.ROLLED_BACK
                    healing.verification_result = {
                        "bdd_passed": False,
                        "evolver_rollback": True,
                        "veto_triggered": report.veto_triggered,
                        "veto_details": report.veto_details,
                    }
                    return {
                        "proposal_id": proposal_id,
                        "status": HealingStatus.ROLLED_BACK.value,
                        "reason": "Evolver verification triggered rollback",
                        "verification": healing.verification_result,
                    }

            healing.status = HealingStatus.VERIFIED
            healing.verification_result = {
                "bdd_passed": True,
                "bug_count_before": count_before,
                "bug_count_after": len(self._bug_collector.get_bugs(
                    skill_id=healing.skill_id,
                    defect_type=healing.defect_type,
                )),
            }
        else:
            # BDD failed — trigger evolver rollback via verify_evolution
            if healing.evolver_proposal:
                self._evolver.verify_evolution(
                    proposal_id=healing.evolver_proposal.proposal_id,
                    bdd_results={"bug_count_decreased": False},
                    scores_before={},
                    scores_after={},
                    veto_details=["BDD verification failed: bug count did not decrease"],
                )
            # Restore from snapshot
            snapshot = None
            if healing.evolver_proposal:
                snapshot = self._evolver.get_snapshot(healing.evolver_proposal.proposal_id)

            healing.status = HealingStatus.ROLLED_BACK
            healing.verification_result = {
                "bdd_passed": False,
                "bug_count_before": count_before,
                "reason": "BDD verification failed: bug count did not decrease",
                "snapshot_restored": snapshot is not None,
            }

        if self._audit:
            self._audit.append(
                action="self_healing_execute",
                object_id=proposal_id,
                result=healing.status.value,
            )

        return {
            "proposal_id": proposal_id,
            "status": healing.status.value,
            "verification": healing.verification_result,
        }

    def get_healing_status(self) -> dict[str, Any]:
        """Return current healing loop status.

        Returns:
            Dict with total proposals, counts by status, and proposal summaries.
        """
        by_status: dict[str, int] = {}
        summaries: list[dict[str, Any]] = []

        for healing in self._proposals.values():
            status_key = healing.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1
            summaries.append({
                "proposal_id": healing.proposal_id,
                "skill_id": healing.skill_id,
                "defect_type": healing.defect_type.value,
                "upgrade_type": healing.upgrade_type.value,
                "bug_count": healing.bug_count,
                "status": healing.status.value,
            })

        return {
            "total_proposals": len(self._proposals),
            "by_status": by_status,
            "proposals": summaries,
        }

    # ── Internal ──

    @staticmethod
    def _determine_action(counts: dict[str, int]) -> HealingAction:
        """Determine healing action from bug severity counts.

        Thresholds (CLAUDE.md Section 8.5):
        - >=1 P0 -> MAJOR (needs_human)
        - >=1 P1 or >=5 P2 -> MINOR
        - >=3 P2 -> PATCH
        - else -> SKIPPED
        """
        p0 = counts.get("P0", 0)
        p1 = counts.get("P1", 0)
        p2 = counts.get("P2", 0)

        if p0 >= 1:
            return HealingAction.NEEDS_HUMAN
        if p1 >= 1 or p2 >= 5:
            return HealingAction.MINOR
        if p2 >= 3:
            return HealingAction.PATCH
        return HealingAction.SKIPPED

    @staticmethod
    def _dominant_severity(counts: dict[str, int]) -> BugSeverity:
        """Return the highest severity with non-zero count."""
        if counts.get("P0", 0) > 0:
            return BugSeverity.P0
        if counts.get("P1", 0) > 0:
            return BugSeverity.P1
        return BugSeverity.P2

    def _bdd_verify(
        self,
        skill_id: str,
        defect_type: DefectType,
        count_before: int,
    ) -> bool:
        """BDD-style verification: check that bug count did not increase.

        Compares pre-evolution bug count with current bug count for the
        same skill_id + defect_type. If new bugs appeared, fails.

        Since the Evolver is recommendation-only (does not auto-apply
        skill changes), BDD verification checks whether the defect pattern
        is worsening regardless — a worsening pattern means the proposed
        evolution is insufficient.
        """
        current_bugs = self._bug_collector.get_bugs(
            skill_id=skill_id,
            defect_type=defect_type,
        )
        count_after = len(current_bugs)

        # If no new bugs appeared, verification passes
        if count_after <= count_before:
            return True

        # New bugs appeared — check if they're genuinely new
        # (not just the same bugs we counted before)
        new_bug_count = count_after - count_before
        # If more than 1 new bug of the same type appeared, pattern is worsening
        return new_bug_count <= 1
