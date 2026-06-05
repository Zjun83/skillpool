"""Evolver Layer — Evolution recommendations with defect accumulation.

Architecture constraint:
- Evolver MUST only recommend, NOT auto-publish
- EvolutionProposal.recommendation_only = true
- Evolver MUST NOT mutate Registry enabled state

Open source enhancements:
- Defect accumulation threshold trigger (AutoSkill)
- Add/Merge/Discard tri-state update (AutoSkill)
- Dual-loop architecture support (AutoSkill + SkillClaw)

V4.1 additions:
- VERIFY phase (BDD regression + 12-dim scoring + VETO V1-V6)
- 6 safety constraints (rate limit, MAJOR approval, rollback, cooldown, global CB lock, regression monitor)
- approval_token for MAJOR upgrades
"""

from __future__ import annotations

__all__ = [
    "DefectAccumulator",
    "DefectRecord",
    "DefectSeverity",
    "EvolutionAction",
    "EvolverLayer",
    "EvolutionProposal",
    "VerificationReport",
    "VerificationStatus",
]

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
import hashlib
import logging
import secrets

import yaml

from skillpool.config import get_data_dir

logger = logging.getLogger(__name__)


class DefectSeverity(StrEnum):
    """Defect severity levels."""

    CRITICAL = "critical"  # 1 trigger
    MAJOR = "major"  # 5 trigger
    MINOR = "minor"  # 20 trigger


class EvolutionAction(StrEnum):
    """Evolution action types (from AutoSkill)."""

    ADD = "add"  # Create new skill
    MERGE = "merge"  # Merge with existing
    DISCARD = "discard"  # Discard candidate


class VerificationStatus(StrEnum):
    """VERIFY phase result status."""

    PASSED = "passed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class DefectRecord:
    """Single defect record."""

    defect_id: str
    skill_id: str
    version: str
    severity: DefectSeverity
    description: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved: bool = False


@dataclass
class EvolutionProposal:
    """Recommendation-only evolution proposal."""

    context: dict[str, Any]
    proposal_id: str = ""
    recommendation_only: bool = True  # ALWAYS true
    risk: str = "medium"
    audit_ref: str = ""
    action: EvolutionAction = EvolutionAction.ADD
    created_at: str = ""
    approval_token: str = ""  # MAJOR upgrades require token verification
    upgrade_type: str = "PATCH"  # PATCH / MINOR / MAJOR / NONE


@dataclass
class VerificationReport:
    """VERIFY phase output — validates evolution results."""

    proposal_id: str
    status: VerificationStatus = VerificationStatus.PASSED
    bdd_regression_passed: bool = True
    dimension_scores_before: dict[str, float] = field(default_factory=dict)
    dimension_scores_after: dict[str, float] = field(default_factory=dict)
    new_blind_spots: list[str] = field(default_factory=list)
    veto_triggered: bool = False
    veto_details: list[str] = field(default_factory=list)
    rollback_performed: bool = False
    verified_at: str = ""

    def score_improved(self, dimension: str) -> bool:
        """Check if a dimension score improved after evolution."""
        before = self.dimension_scores_before.get(dimension, 0.0)
        after = self.dimension_scores_after.get(dimension, 0.0)
        return after > before

    def any_regression(self) -> bool:
        """Check if any dimension regressed."""
        for dim in self.dimension_scores_before:
            if self.dimension_scores_after.get(dim, 0.0) < self.dimension_scores_before.get(dim, 0.0):
                return True
        return False


@dataclass
class DefectAccumulator:
    """Defect accumulation tracker (from open source design)."""

    THRESHOLDS: dict[DefectSeverity, int] = field(
        default_factory=lambda: {
            DefectSeverity.CRITICAL: 1,
            DefectSeverity.MAJOR: 5,
            DefectSeverity.MINOR: 20,
        }
    )

    counts: dict[str, dict[DefectSeverity, int]] = field(default_factory=dict)
    defects: list[DefectRecord] = field(default_factory=list)

    def accumulate(self, defect: DefectRecord) -> None:
        """Accumulate a defect, grouped by skill@version."""
        key = f"{defect.skill_id}@{defect.version}"
        if key not in self.counts:
            self.counts[key] = dict.fromkeys(DefectSeverity, 0)
        self.counts[key][defect.severity] += 1
        self.defects.append(defect)

    def should_trigger_evolution(self, skill_id: str, version: str) -> bool:
        """Check if accumulated defects trigger evolution."""
        key = f"{skill_id}@{version}"
        if key not in self.counts:
            return False
        counts = self.counts[key]
        return any(counts[sev] >= self.THRESHOLDS[sev] for sev in DefectSeverity)

    def get_pending_defects(self, skill_id: str, version: str) -> list[DefectRecord]:
        """Get unresolved defects for a skill version."""
        return [d for d in self.defects if d.skill_id == skill_id and d.version == version and not d.resolved]


class EvolverLayer:
    """
    Evolver layer — evolution recommendations.

    Hard rules:
    - recommendation_only = true
    - MUST NOT auto-publish
    - MUST NOT mutate Registry enabled state
    - Sandbox pass alone does not enable production release

    V4.1 additions:
    - VERIFY phase (Detect → Adapt → Verify)
    - 6 safety constraints from evolution-loop-spec.yaml §4
    - approval_token for MAJOR upgrades
    """

    # Safety constraint #1: max auto-evolution frequency
    MAX_PATCH_PER_DAY = 10
    MAX_MINOR_PER_DAY = 3

    # Safety constraint #4: isolation cooldown (24h)
    EVOLUTION_COOLDOWN_HOURS = 24

    # Safety constraint #6: regression monitor window (7 days)
    REGRESSION_MONITOR_DAYS = 7

    def __init__(self, audit_layer=None, skills_dir: Path | None = None, evolver_dir: Path | None = None) -> None:
        self._audit = audit_layer
        self._skills_dir = skills_dir or get_data_dir() / "skills"
        self._evolver_dir = evolver_dir or get_data_dir() / "evolver"
        self._proposals: dict[str, EvolutionProposal] = {}
        self._defect_accumulator = DefectAccumulator()
        self._evolution_queue: list[dict] = []
        # Safety constraint #1: daily counters
        self._daily_patch_count: int = 0
        self._daily_minor_count: int = 0
        self._daily_reset_date: str = datetime.now(UTC).strftime("%Y-%m-%d")
        # Safety constraint #4: per-skill cooldown tracking
        self._last_evolution_time: dict[str, datetime] = {}
        # Safety constraint #5: global CB lock
        self._global_cb_locked: bool = False
        # Safety constraint #6: regression monitor
        self._regression_monitors: dict[str, dict] = {}
        # VERIFY phase: verification reports
        self._verification_reports: dict[str, VerificationReport] = {}
        # Rollback snapshots
        self._snapshots: dict[str, dict] = {}
        # Auto-load from disk on init
        self._load_from_disk()

    # === Defect Management ===

    def record_defect(
        self,
        skill_id: str,
        version: str,
        severity: DefectSeverity,
        description: str,
    ) -> DefectRecord:
        """
        Record a defect for accumulation.

        Defects accumulate until threshold triggers evolution.
        """
        defect = DefectRecord(
            defect_id=f"defect-{len(self._defect_accumulator.defects) + 1}",
            skill_id=skill_id,
            version=version,
            severity=severity,
            description=description,
        )

        self._defect_accumulator.accumulate(defect)

        # Check if evolution should trigger
        if self._defect_accumulator.should_trigger_evolution(skill_id, version):
            self._queue_evolution(skill_id, version, defect.severity)

        if self._audit:
            self._audit.append(
                action="record_defect",
                object_id=skill_id,
                result=f"{severity.value}_accumulated",
            )

        return defect

    def _queue_evolution(
        self,
        skill_id: str,
        version: str,
        trigger_severity: DefectSeverity,
    ) -> None:
        """Queue an evolution task."""
        evolution = {
            "skill_id": skill_id,
            "version": version,
            "trigger": trigger_severity.value,
            "defects": self._defect_accumulator.get_pending_defects(skill_id, version),
            "queued_at": datetime.now(UTC).isoformat(),
        }
        self._evolution_queue.append(evolution)

    def get_pending_evolutions(self) -> list[dict]:
        """Get pending evolution tasks."""
        return list(self._evolution_queue)

    # === Tri-State Update (from AutoSkill) ===

    def judge_skill_candidate(
        self,
        candidate_id: str,
        existing_skills: list[str],
        similarity_threshold: float = 0.8,
    ) -> EvolutionAction:
        """
        Judge what action to take for a skill candidate.

        AutoSkill Add/Merge/Discard tri-state logic:
        - ADD: No similar existing skills
        - MERGE: Similar to existing, combine versions
        - DISCARD: Nearly identical to existing, skip
        """
        if not existing_skills:
            return EvolutionAction.ADD

        # Exact match → discard
        if candidate_id in existing_skills:
            return EvolutionAction.DISCARD

        # Similar skills → merge
        similar_exists = any(
            self._calculate_similarity(candidate_id, existing) > similarity_threshold for existing in existing_skills
        )

        if similar_exists:
            return EvolutionAction.MERGE

        return EvolutionAction.ADD

    def _calculate_similarity(self, skill_a: str, skill_b: str) -> float:
        """Calculate similarity between two skills based on ID structure.

        Skill IDs follow patterns like S05a, S09, S13a. Similarity is based on:
        1. Exact match → 1.0
        2. Same base number (e.g. S05a vs S05b) → 0.85
        3. Same dimension (derived from DIMENSION_SKILLS mapping) → 0.6
        4. Otherwise → 0.0
        """
        if skill_a == skill_b:
            return 1.0

        # Extract base number: S05a → S05, S13b → S13
        import re

        match_a = re.match(r"S(\d+)", skill_a)
        match_b = re.match(r"S(\d+)", skill_b)
        if not match_a or not match_b:
            # Fallback to Jaccard on characters for non-standard IDs
            set_a = set(skill_a)
            set_b = set(skill_b)
            intersection = len(set_a & set_b)
            union = len(set_a | set_b)
            return intersection / union if union else 0.0

        num_a = match_a.group(1)
        num_b = match_b.group(1)
        if num_a == num_b:
            return 0.85  # Same skill family (e.g. S05a, S05b)

        # Check if skills share a dimension
        from skillpool.review.checkpoint_runner import DIMENSION_SKILLS

        dims_a = {d for d, skills in DIMENSION_SKILLS.items() if skill_a in skills}
        dims_b = {d for d, skills in DIMENSION_SKILLS.items() if skill_b in skills}
        if dims_a & dims_b:
            return 0.6  # Same dimension

        return 0.0

    # === Proposal Creation ===

    def create_proposal(
        self,
        context: dict[str, Any],
        evidence_refs: list[str] | None = None,
        candidate_summary: str = "",
        risk: str = "medium",
        upgrade_type: str = "PATCH",
    ) -> EvolutionProposal:
        """
        Create a recommendation-only evolution proposal.

        IMPORTANT: This does NOT mutate any Registry state.
        It only creates a proposal for human review.

        Safety constraints applied:
        - #1: Rate limit (PATCH ≤10/day, MINOR ≤3/day)
        - #2: MAJOR requires approval_token
        - #4: 24h cooldown per skill
        - #5: Global CB lock blocks auto-evolution
        """
        # Reset daily counters if date changed
        self._check_daily_reset()

        # Safety constraint #5: global CB lock
        if self._global_cb_locked and upgrade_type in ("PATCH", "MINOR"):
            return self._create_blocked_proposal(context, "global_cb_locked", upgrade_type)

        # Safety constraint #1: rate limit
        if upgrade_type == "PATCH" and self._daily_patch_count >= self.MAX_PATCH_PER_DAY:
            return self._create_blocked_proposal(context, "patch_rate_exceeded", upgrade_type)
        if upgrade_type == "MINOR" and self._daily_minor_count >= self.MAX_MINOR_PER_DAY:
            return self._create_blocked_proposal(context, "minor_rate_exceeded", upgrade_type)

        # Safety constraint #4: 24h cooldown per skill
        skill_id = context.get("skill_id", "")
        if skill_id and self._is_in_cooldown(skill_id):
            return self._create_blocked_proposal(context, "cooldown_active", upgrade_type)

        proposal_id = f"proposal-{len(self._proposals) + 1}"

        # Safety constraint #2: MAJOR requires approval_token
        approval_token = ""
        if upgrade_type == "MAJOR":
            approval_token = secrets.token_urlsafe(32)

        audit_ref = ""
        if self._audit:
            audit_ref = self._audit.append(
                action="create_evolution_proposal",
                result="success",
            )

        proposal = EvolutionProposal(
            context=context,
            proposal_id=proposal_id,
            recommendation_only=True,  # ALWAYS true
            risk=risk,
            audit_ref=audit_ref,
            created_at=datetime.now(UTC).isoformat(),
            approval_token=approval_token,
            upgrade_type=upgrade_type,
        )

        self._proposals[proposal_id] = proposal

        # Track cooldown
        if skill_id:
            self._last_evolution_time[skill_id] = datetime.now(UTC)

        # Increment daily counters
        if upgrade_type == "PATCH":
            self._daily_patch_count += 1
        elif upgrade_type == "MINOR":
            self._daily_minor_count += 1

        self._save_to_disk()
        return proposal

    def _create_blocked_proposal(self, context: dict, reason: str, upgrade_type: str) -> EvolutionProposal:
        """Create a proposal blocked by safety constraints."""
        proposal_id = f"proposal-{len(self._proposals) + 1}"
        proposal = EvolutionProposal(
            context={**context, "blocked_reason": reason},
            proposal_id=proposal_id,
            recommendation_only=True,
            risk="blocked",
            created_at=datetime.now(UTC).isoformat(),
            upgrade_type=upgrade_type,
        )
        self._proposals[proposal_id] = proposal
        return proposal

    def verify_approval_token(self, proposal_id: str, token: str) -> bool:
        """Verify approval token for MAJOR upgrades (safety constraint #2)."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return False
        if proposal.upgrade_type != "MAJOR":
            return True  # Non-MAJOR doesn't need token
        return proposal.approval_token == token and token != ""

    def can_auto_enable(self, proposal_id: str) -> bool:
        """Check if a proposal can auto-enable a skill. Returns: ALWAYS False."""
        return False  # Hard rule: Evolver cannot auto-enable

    def get_proposal(self, proposal_id: str) -> EvolutionProposal | None:
        """Get proposal by ID."""
        return self._proposals.get(proposal_id)

    # === Safety Constraint Helpers ===

    def _check_daily_reset(self) -> None:
        """Reset daily counters if date changed."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_patch_count = 0
            self._daily_minor_count = 0
            self._daily_reset_date = today

    def _is_in_cooldown(self, skill_id: str) -> bool:
        """Check if a skill is in 24h evolution cooldown (safety constraint #4)."""
        last_time = self._last_evolution_time.get(skill_id)
        if last_time is None:
            return False
        return datetime.now(UTC) < last_time + timedelta(hours=self.EVOLUTION_COOLDOWN_HOURS)

    def set_global_cb_lock(self, locked: bool) -> None:
        """Set global CB lock (safety constraint #5).

        When locked, PATCH/MINOR auto-evolutions are blocked.
        """
        self._global_cb_locked = locked

    def is_global_cb_locked(self) -> bool:
        """Check if global CB lock is active."""
        return self._global_cb_locked

    def get_daily_counts(self) -> dict[str, int]:
        """Get current daily evolution counts."""
        self._check_daily_reset()
        return {"patch": self._daily_patch_count, "minor": self._daily_minor_count}

    # === Evolution Execution (V4.3) ===

    def execute_evolution(
        self,
        proposal_id: str,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an evolution proposal: write changes to CSDF YAML + re-materialize.

        Steps:
        1. Validate proposal exists
        2. Find the skill's CSDF YAML file
        3. Save pre-evolution snapshot for rollback
        4. Apply updates to the YAML data
        5. Write updated YAML back to disk
        6. Trigger re-materialization

        Args:
            proposal_id: The evolution proposal ID to execute.
            updates: Optional dict of field updates to apply to the CSDF.

        Returns:
            Dict with execution result (status, yaml_updated, materialized).
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "not_found", "error": f"No proposal with id {proposal_id}"}

        skill_id = proposal.context.get("skill_id", "")
        if not skill_id:
            return {"status": "error", "error": "Proposal has no skill_id in context"}

        # Find CSDF YAML
        yaml_path = self._find_skill_yaml(skill_id)
        if yaml_path is None:
            return {"status": "no_yaml", "error": f"No CSDF YAML found for {skill_id}"}

        # Read current data
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as e:
            return {"status": "yaml_error", "error": str(e)}

        if not isinstance(data, dict):
            return {"status": "yaml_error", "error": "CSDF is not a dict"}

        # Save snapshot for rollback (deep copy before mutation)
        import copy

        self.save_snapshot(proposal_id, copy.deepcopy(data))

        # Apply updates
        if updates:
            data.update(updates)

        # Bump version based on upgrade_type
        version = str(data.get("version", "0.0.0"))
        data["version"] = self._bump_version(version, proposal.upgrade_type)
        data["last_evolved"] = datetime.now(UTC).isoformat()
        data["evolution_proposal"] = proposal_id

        # Write back to disk
        try:
            yaml_path.write_text(
                yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except OSError as e:
            return {"status": "write_error", "error": str(e)}

        # Trigger re-materialization
        materialized = self._rematerialize(skill_id, yaml_path)

        if self._audit:
            self._audit.append(
                action="execute_evolution",
                object_id=proposal_id,
                result="success",
            )

        return {
            "status": "success",
            "skill_id": skill_id,
            "version": data["version"],
            "yaml_updated": True,
            "materialized": materialized,
        }

    def _find_skill_yaml(self, skill_id: str) -> Path | None:
        """Find the CSDF YAML file for a skill ID."""
        if not self._skills_dir.exists():
            return None
        exact = self._skills_dir / f"{skill_id}.yaml"
        if exact.exists():
            return exact
        for p in self._skills_dir.iterdir():
            if p.name.startswith(f"{skill_id}-") and p.suffix == ".yaml":
                return p
        return None

    @staticmethod
    def _bump_version(version: str, upgrade_type: str) -> str:
        """Bump a semver version based on upgrade type."""
        import re

        match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
        if not match:
            return version
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if upgrade_type == "MAJOR":
            return f"{major + 1}.0.0"
        elif upgrade_type == "MINOR":
            return f"{major}.{minor + 1}.0"
        else:  # PATCH
            return f"{major}.{minor}.{patch + 1}"

    def _rematerialize(self, skill_id: str, yaml_path: Path) -> bool:
        """Trigger re-materialization of a skill after evolution.

        Re-materializes to the default Claude Code skills directory.
        """
        try:
            from skillpool.materializer import Materializer
            from skillpool.profile import CLAUDE_CODE_PROFILE

            mat = Materializer(profile=CLAUDE_CODE_PROFILE)
            result = mat.materialize(csdf_path=yaml_path)
            if result.status == "success" and result.skill:
                out_dir = Path.home() / ".claude" / "skills"
                out_dir.mkdir(parents=True, exist_ok=True)
                skill_file = out_dir / f"{result.skill.id}.md"
                skill_file.write_text(result.skill.markdown, encoding="utf-8")
                return True
        except Exception as e:
            logger.warning("Rematerialization failed for %s: %s", yaml_path, e)
        return False

    # === VERIFY Phase (V4.1) ===

    def verify_evolution(
        self,
        proposal_id: str,
        bdd_results: dict[str, bool] | None = None,
        scores_before: dict[str, float] | None = None,
        scores_after: dict[str, float] | None = None,
        new_blind_spots: list[str] | None = None,
        veto_details: list[str] | None = None,
    ) -> VerificationReport:
        """
        VERIFY phase — validate evolution results.

        Per evolution-loop-spec.yaml §1 VERIFY:
        1. Run BDD regression test suite
        2. Compare 12-dim scores before/after
        3. Check for new blind spots introduced
        4. VETO rules V1-V6 must all pass

        If VERIFY fails → automatic rollback (safety constraint #3).
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return VerificationReport(
                proposal_id=proposal_id,
                status=VerificationStatus.FAILED,
                bdd_regression_passed=False,
                verified_at=datetime.now(UTC).isoformat(),
            )

        bdd_results = bdd_results or {}
        scores_before = scores_before or {}
        scores_after = scores_after or {}
        new_blind_spots = new_blind_spots or []
        veto_details = veto_details or []

        # Step 1: BDD regression
        bdd_passed = all(bdd_results.values()) if bdd_results else True

        # Step 2: Score comparison — no regression allowed
        score_regression = False
        for dim, before_score in scores_before.items():
            after_score = scores_after.get(dim, before_score)
            if after_score < before_score:
                score_regression = True
                break

        # Step 3: New blind spots check
        has_new_blind_spots = len(new_blind_spots) > 0

        # Step 4: VETO check
        veto_triggered = len(veto_details) > 0

        # Determine overall status
        all_passed = bdd_passed and not score_regression and not has_new_blind_spots and not veto_triggered

        if all_passed:
            status = VerificationStatus.PASSED
            rollback = False
        else:
            # Safety constraint #3: VERIFY failed → rollback
            status = VerificationStatus.ROLLED_BACK
            rollback = True
            self._perform_rollback(proposal_id)

        report = VerificationReport(
            proposal_id=proposal_id,
            status=status,
            bdd_regression_passed=bdd_passed,
            dimension_scores_before=scores_before,
            dimension_scores_after=scores_after,
            new_blind_spots=new_blind_spots,
            veto_triggered=veto_triggered,
            veto_details=veto_details,
            rollback_performed=rollback,
            verified_at=datetime.now(UTC).isoformat(),
        )

        self._verification_reports[proposal_id] = report

        # Safety constraint #6: start regression monitor for passed evolutions
        if status == VerificationStatus.PASSED:
            skill_id = proposal.context.get("skill_id", "")
            if skill_id:
                self._regression_monitors[skill_id] = {
                    "proposal_id": proposal_id,
                    "started_at": datetime.now(UTC).isoformat(),
                    "monitor_until": (datetime.now(UTC) + timedelta(days=self.REGRESSION_MONITOR_DAYS)).isoformat(),
                    "dimensions": list(scores_after.keys()),
                }

        if self._audit:
            self._audit.append(
                action="verify_evolution",
                object_id=proposal_id,
                result=status.value,
            )

        self._save_to_disk()
        return report

    def get_verification_report(self, proposal_id: str) -> VerificationReport | None:
        """Get verification report for a proposal."""
        return self._verification_reports.get(proposal_id)

    def _perform_rollback(self, proposal_id: str) -> None:
        """Perform rollback for failed verification (safety constraint #3).

        Restores skill CSDF YAML from the pre-evolution snapshot,
        then re-materializes the original skill definition.
        """
        snapshot = self._snapshots.get(proposal_id)
        if snapshot and "data" in snapshot:
            restored_data = snapshot["data"]
            skill_id = restored_data.get("id", "")
            if skill_id:
                # Find and restore the YAML file
                yaml_path = self._find_skill_yaml(skill_id)
                if yaml_path is not None:
                    try:
                        yaml_path.write_text(
                            yaml.dump(restored_data, default_flow_style=False, allow_unicode=True, sort_keys=False),
                            encoding="utf-8",
                        )
                        # Re-materialize the restored skill
                        self._rematerialize(skill_id, yaml_path)
                    except OSError:
                        pass  # Best-effort rollback
        if self._audit:
            self._audit.append(
                action="evolution_rollback",
                object_id=proposal_id,
                result="rolled_back",
            )

    def save_snapshot(self, proposal_id: str, skill_data: dict) -> None:
        """Save a pre-evolution snapshot for potential rollback."""
        self._snapshots[proposal_id] = {
            "data": skill_data,
            "saved_at": datetime.now(UTC).isoformat(),
            "hash": hashlib.sha256(str(skill_data).encode()).hexdigest()[:16],
        }
        self._save_to_disk()

    def get_snapshot(self, proposal_id: str) -> dict | None:
        """Get a saved snapshot."""
        snap = self._snapshots.get(proposal_id)
        return snap["data"] if snap else None

    # === Regression Monitor (Safety Constraint #6) ===

    def check_regression_monitor(self, skill_id: str) -> dict | None:
        """Check if a skill is under regression monitoring.

        Returns monitor info if active, None if expired or not monitored.
        """
        monitor = self._regression_monitors.get(skill_id)
        if monitor is None:
            return None
        until = datetime.fromisoformat(monitor["monitor_until"])
        if datetime.now(UTC) > until:
            del self._regression_monitors[skill_id]
            return None
        return monitor

    def report_regression_recurrence(self, skill_id: str, dimension: str) -> str:
        """Report a regression recurrence during monitoring period.

        Per safety constraint #6: if blind spot recurs within 7 days,
        upgrade evolution: PATCH → MINOR → MAJOR.
        """
        monitor = self._regression_monitors.get(skill_id)
        if monitor is None:
            return "no_monitor"

        # Escalate: current level → next level
        current_proposal = self._proposals.get(monitor["proposal_id"])
        if current_proposal is None:
            return "no_proposal"

        if current_proposal.upgrade_type == "PATCH":
            return "escalate_to_minor"
        elif current_proposal.upgrade_type == "MINOR":
            return "escalate_to_major"
        else:
            return "already_major"

    # === Dual-Loop Architecture Support ===

    # === Disk Persistence (V4.3) ===

    def _save_to_disk(self) -> None:
        """Persist proposals, snapshots, and verification reports to disk."""
        try:
            self._evolver_dir.mkdir(parents=True, exist_ok=True)

            # Save proposals
            proposals_path = self._evolver_dir / "proposals.yaml"
            proposals_data = {}
            for pid, p in self._proposals.items():
                proposals_data[pid] = {
                    "context": p.context,
                    "proposal_id": p.proposal_id,
                    "risk": p.risk,
                    "audit_ref": p.audit_ref,
                    "action": p.action.value,
                    "created_at": p.created_at,
                    "upgrade_type": p.upgrade_type,
                }
            proposals_path.write_text(
                yaml.dump(proposals_data, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )

            # Save snapshots
            snapshots_path = self._evolver_dir / "snapshots.yaml"
            snapshots_path.write_text(
                yaml.dump(self._snapshots, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )

            # Save verification reports
            reports_path = self._evolver_dir / "verification_reports.yaml"
            reports_data = {}
            for pid, r in self._verification_reports.items():
                reports_data[pid] = {
                    "proposal_id": r.proposal_id,
                    "status": r.status.value,
                    "bdd_regression_passed": r.bdd_regression_passed,
                    "dimension_scores_before": r.dimension_scores_before,
                    "dimension_scores_after": r.dimension_scores_after,
                    "new_blind_spots": r.new_blind_spots,
                    "veto_triggered": r.veto_triggered,
                    "veto_details": r.veto_details,
                    "rollback_performed": r.rollback_performed,
                    "verified_at": r.verified_at,
                }
            reports_path.write_text(
                yaml.dump(reports_data, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
        except OSError:
            pass  # Disk persistence is best-effort

    def _load_from_disk(self) -> None:
        """Load proposals, snapshots, and verification reports from disk."""
        try:
            if not self._evolver_dir.exists():
                return

            # Load proposals
            proposals_path = self._evolver_dir / "proposals.yaml"
            if proposals_path.exists():
                data = yaml.safe_load(proposals_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for pid, p_data in data.items():
                        self._proposals[pid] = EvolutionProposal(
                            context=p_data.get("context", {}),
                            proposal_id=p_data.get("proposal_id", pid),
                            risk=p_data.get("risk", "medium"),
                            audit_ref=p_data.get("audit_ref", ""),
                            action=EvolutionAction(p_data.get("action", "add")),
                            created_at=p_data.get("created_at", ""),
                            upgrade_type=p_data.get("upgrade_type", "PATCH"),
                        )

            # Load snapshots
            snapshots_path = self._evolver_dir / "snapshots.yaml"
            if snapshots_path.exists():
                data = yaml.safe_load(snapshots_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._snapshots = data

            # Load verification reports
            reports_path = self._evolver_dir / "verification_reports.yaml"
            if reports_path.exists():
                data = yaml.safe_load(reports_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for pid, r_data in data.items():
                        self._verification_reports[pid] = VerificationReport(
                            proposal_id=r_data.get("proposal_id", pid),
                            status=VerificationStatus(r_data.get("status", "passed")),
                            bdd_regression_passed=r_data.get("bdd_regression_passed", True),
                            dimension_scores_before=r_data.get("dimension_scores_before", {}),
                            dimension_scores_after=r_data.get("dimension_scores_after", {}),
                            new_blind_spots=r_data.get("new_blind_spots", []),
                            veto_triggered=r_data.get("veto_triggered", False),
                            veto_details=r_data.get("veto_details", []),
                            rollback_performed=r_data.get("rollback_performed", False),
                            verified_at=r_data.get("verified_at", ""),
                        )
        except (yaml.YAMLError, OSError):
            pass  # Disk load is best-effort

    def process_internal_feedback(
        self,
        skill_id: str,
        feedback_data: dict,
    ) -> dict | None:
        """
        Process internal feedback loop (left loop of dual-loop).

        Synchronous, real-time processing path.
        Returns evolution suggestions based on immediate feedback.
        """
        success_rate = feedback_data.get("success_rate", 1.0)
        error_patterns = feedback_data.get("error_patterns", [])

        suggestions = []

        if success_rate < 0.9:
            suggestions.append(
                {
                    "type": "performance_degradation",
                    "skill_id": skill_id,
                    "severity": DefectSeverity.MAJOR if success_rate < 0.7 else DefectSeverity.MINOR,
                    "action": "review_and_optimize",
                }
            )

        for pattern in error_patterns:
            suggestions.append(
                {
                    "type": "error_pattern",
                    "skill_id": skill_id,
                    "pattern": pattern,
                    "action": "investigate",
                }
            )

        return {"suggestions": suggestions} if suggestions else None

    def process_external_evolution(
        self,
        skill_id: str,
        external_update: dict,
    ) -> dict | None:
        """
        Process external evolution signals (right loop of dual-loop).

        Asynchronous, batch processing path.
        """
        update_version = external_update.get("version")
        update_type = external_update.get("type")

        return {
            "skill_id": skill_id,
            "external_version": update_version,
            "update_type": update_type,
            "recommendation": "review_for_adoption",
            "source": "external_evolution",
        }
