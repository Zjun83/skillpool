"""Tests for Evolver Layer — Evolution recommendations with defect accumulation."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from skillpool.evolver import (
    DefectAccumulator,
    DefectRecord,
    DefectSeverity,
    EvolutionAction,
    EvolverLayer,
    VerificationStatus,
)


@pytest.fixture(autouse=True)
def _isolated_evolver(tmp_path, monkeypatch):
    """Ensure all tests use isolated evolver directory (no cross-contamination)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


class TestDefectSeverity:
    def test_values(self):
        assert DefectSeverity.CRITICAL == "critical"
        assert DefectSeverity.MAJOR == "major"
        assert DefectSeverity.MINOR == "minor"


class TestEvolutionAction:
    def test_values(self):
        assert EvolutionAction.ADD == "add"
        assert EvolutionAction.MERGE == "merge"
        assert EvolutionAction.DISCARD == "discard"


class TestVerificationStatus:
    def test_values(self):
        assert VerificationStatus.PASSED == "passed"
        assert VerificationStatus.FAILED == "failed"
        assert VerificationStatus.ROLLED_BACK == "rolled_back"


class TestDefectRecord:
    def test_creation(self):
        d = DefectRecord(
            defect_id="d1", skill_id="s1", version="1.0",
            severity=DefectSeverity.MAJOR, description="bug"
        )
        assert d.defect_id == "d1"
        assert d.severity == DefectSeverity.MAJOR
        assert not d.resolved


class TestDefectAccumulator:
    def test_accumulate(self):
        acc = DefectAccumulator()
        d = DefectRecord(
            defect_id="d1", skill_id="s1", version="1.0",
            severity=DefectSeverity.MINOR, description="bug"
        )
        acc.accumulate(d)
        assert len(acc.defects) == 1
        key = "s1@1.0"
        assert acc.counts[key][DefectSeverity.MINOR] == 1

    def test_trigger_critical(self):
        acc = DefectAccumulator()
        d = DefectRecord(
            defect_id="d1", skill_id="s1", version="1.0",
            severity=DefectSeverity.CRITICAL, description="crash"
        )
        acc.accumulate(d)
        assert acc.should_trigger_evolution("s1", "1.0") is True

    def test_trigger_major_after_5(self):
        acc = DefectAccumulator()
        for i in range(5):
            acc.accumulate(DefectRecord(
                defect_id=f"d{i}", skill_id="s1", version="1.0",
                severity=DefectSeverity.MAJOR, description=f"bug-{i}"
            ))
        assert acc.should_trigger_evolution("s1", "1.0") is True

    def test_no_trigger_minor_below_20(self):
        acc = DefectAccumulator()
        for i in range(19):
            acc.accumulate(DefectRecord(
                defect_id=f"d{i}", skill_id="s1", version="1.0",
                severity=DefectSeverity.MINOR, description=f"bug-{i}"
            ))
        assert acc.should_trigger_evolution("s1", "1.0") is False

    def test_trigger_minor_at_20(self):
        acc = DefectAccumulator()
        for i in range(20):
            acc.accumulate(DefectRecord(
                defect_id=f"d{i}", skill_id="s1", version="1.0",
                severity=DefectSeverity.MINOR, description=f"bug-{i}"
            ))
        assert acc.should_trigger_evolution("s1", "1.0") is True

    def test_pending_defects(self):
        acc = DefectAccumulator()
        acc.accumulate(DefectRecord(
            defect_id="d1", skill_id="s1", version="1.0",
            severity=DefectSeverity.MINOR, description="bug"
        ))
        acc.accumulate(DefectRecord(
            defect_id="d2", skill_id="s1", version="1.0",
            severity=DefectSeverity.MINOR, description="bug2", resolved=True
        ))
        pending = acc.get_pending_defects("s1", "1.0")
        assert len(pending) == 1
        assert pending[0].defect_id == "d1"


class TestEvolverLayer:
    def test_record_defect(self):
        evolver = EvolverLayer()
        defect = evolver.record_defect(
            skill_id="s1", version="1.0",
            severity=DefectSeverity.MAJOR, description="bug"
        )
        assert defect.defect_id == "defect-1"
        assert defect.skill_id == "s1"

    def test_defect_triggers_evolution_queue(self):
        evolver = EvolverLayer()
        evolver.record_defect(
            skill_id="s1", version="1.0",
            severity=DefectSeverity.CRITICAL, description="crash"
        )
        pending = evolver.get_pending_evolutions()
        assert len(pending) == 1
        assert pending[0]["skill_id"] == "s1"
        assert pending[0]["trigger"] == "critical"

    def test_judge_add_no_existing(self):
        evolver = EvolverLayer()
        action = evolver.judge_skill_candidate("new-skill", [])
        assert action == EvolutionAction.ADD

    def test_judge_discard_exact_match(self):
        evolver = EvolverLayer()
        action = evolver.judge_skill_candidate("s1", ["s1"])
        assert action == EvolutionAction.DISCARD

    def test_judge_merge_similar(self):
        evolver = EvolverLayer()
        action = evolver.judge_skill_candidate(
            "my-great-skill-v2", ["my-great-skill-v1"],
            similarity_threshold=0.5
        )
        assert action == EvolutionAction.MERGE

    def test_judge_add_novel(self):
        evolver = EvolverLayer()
        action = evolver.judge_skill_candidate(
            "completely-different", ["existing-skill"],
            similarity_threshold=0.8
        )
        assert action == EvolutionAction.ADD

    def test_create_proposal(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"reason": "security fix"},
            risk="high"
        )
        assert proposal.proposal_id == "proposal-1"
        assert proposal.recommendation_only is True
        assert proposal.risk == "high"

    def test_cannot_auto_enable(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(context={"reason": "test"})
        assert evolver.can_auto_enable(proposal.proposal_id) is False

    def test_get_proposal(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(context={"reason": "test"})
        found = evolver.get_proposal(proposal.proposal_id)
        assert found is proposal

    def test_get_proposal_not_found(self):
        evolver = EvolverLayer()
        assert evolver.get_proposal("nonexistent") is None

    def test_internal_feedback_low_success_rate(self):
        evolver = EvolverLayer()
        result = evolver.process_internal_feedback(
            "s1", {"success_rate": 0.5, "error_patterns": []}
        )
        assert result is not None
        assert len(result["suggestions"]) >= 1
        assert result["suggestions"][0]["type"] == "performance_degradation"

    def test_internal_feedback_error_patterns(self):
        evolver = EvolverLayer()
        result = evolver.process_internal_feedback(
            "s1", {"success_rate": 1.0, "error_patterns": ["timeout"]}
        )
        assert result is not None
        assert any(s["type"] == "error_pattern" for s in result["suggestions"])

    def test_internal_feedback_no_issues(self):
        evolver = EvolverLayer()
        result = evolver.process_internal_feedback(
            "s1", {"success_rate": 1.0, "error_patterns": []}
        )
        assert result is None

    def test_external_evolution(self):
        evolver = EvolverLayer()
        result = evolver.process_external_evolution(
            "s1", {"version": "2.0", "type": "security_patch"}
        )
        assert result["skill_id"] == "s1"
        assert result["external_version"] == "2.0"
        assert result["recommendation"] == "review_for_adoption"

    def test_with_audit_layer(self):
        from skillpool.audit import AuditLayer
        audit = AuditLayer()
        evolver = EvolverLayer(audit_layer=audit)
        _defect = evolver.record_defect(
            skill_id="s1", version="1.0",
            severity=DefectSeverity.MINOR, description="bug"
        )
        assert audit.get_record_count() == 1

    def test_proposal_with_audit_layer(self):
        from skillpool.audit import AuditLayer
        audit = AuditLayer()
        evolver = EvolverLayer(audit_layer=audit)
        proposal = evolver.create_proposal(context={"reason": "test"})
        assert proposal.audit_ref != ""
        assert audit.get_record_count() == 1


# === V4.1: VERIFY Phase Tests ===

class TestVerifyPhase:
    """Tests for the VERIFY phase (Detect → Adapt → Verify)."""

    def test_verify_all_passed(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1", "reason": "fix"},
            upgrade_type="PATCH",
        )
        report = evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            bdd_results={"scenario_1": True, "scenario_2": True},
            scores_before={"D3": 6.5, "D5": 7.0},
            scores_after={"D3": 7.5, "D5": 7.5},
        )
        assert report.status == VerificationStatus.PASSED
        assert report.bdd_regression_passed is True
        assert report.rollback_performed is False
        assert not report.new_blind_spots
        assert not report.veto_triggered

    def test_verify_bdd_failure_triggers_rollback(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        report = evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            bdd_results={"scenario_1": True, "scenario_2": False},
        )
        assert report.status == VerificationStatus.ROLLED_BACK
        assert report.bdd_regression_passed is False
        assert report.rollback_performed is True

    def test_verify_score_regression_triggers_rollback(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        report = evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            scores_before={"D3": 8.0, "D5": 7.5},
            scores_after={"D3": 7.0, "D5": 7.5},  # D3 regressed
        )
        assert report.status == VerificationStatus.ROLLED_BACK
        assert report.rollback_performed is True

    def test_verify_new_blind_spots_triggers_rollback(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        report = evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            new_blind_spots=["D7-testability-gap"],
        )
        assert report.status == VerificationStatus.ROLLED_BACK
        assert report.new_blind_spots == ["D7-testability-gap"]

    def test_verify_veto_triggers_rollback(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        report = evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            veto_details=["V1: D3 < 7.0"],
        )
        assert report.status == VerificationStatus.ROLLED_BACK
        assert report.veto_triggered is True

    def test_verify_nonexistent_proposal(self):
        evolver = EvolverLayer()
        report = evolver.verify_evolution(proposal_id="nonexistent")
        assert report.status == VerificationStatus.FAILED

    def test_verify_score_improved(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(context={"skill_id": "s1"})
        report = evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            scores_before={"D3": 6.5},
            scores_after={"D3": 7.5},
        )
        assert report.score_improved("D3") is True

    def test_verify_any_regression(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(context={"skill_id": "s1"})
        report = evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            scores_before={"D3": 8.0, "D5": 7.0},
            scores_after={"D3": 7.0, "D5": 8.0},  # D3 regressed even though D5 improved
        )
        assert report.any_regression() is True

    def test_get_verification_report(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(context={"skill_id": "s1"})
        evolver.verify_evolution(proposal_id=proposal.proposal_id)
        report = evolver.get_verification_report(proposal.proposal_id)
        assert report is not None
        assert report.status == VerificationStatus.PASSED

    def test_verify_with_audit(self):
        from skillpool.audit import AuditLayer
        audit = AuditLayer()
        evolver = EvolverLayer(audit_layer=audit)
        proposal = evolver.create_proposal(context={"skill_id": "s1"})
        evolver.verify_evolution(proposal_id=proposal.proposal_id)
        # Audit should have records for proposal creation + verify
        assert audit.get_record_count() >= 2


# === V4.1: Safety Constraint Tests ===

class TestSafetyConstraint1RateLimit:
    """Safety constraint #1: max auto-evolution frequency."""

    def test_patch_rate_limit(self):
        evolver = EvolverLayer()
        # Create MAX_PATCH_PER_DAY proposals
        for i in range(evolver.MAX_PATCH_PER_DAY):
            p = evolver.create_proposal(
                context={"skill_id": f"s{i}"},
                upgrade_type="PATCH",
            )
            assert p.risk != "blocked"

        # Next one should be blocked
        p = evolver.create_proposal(
            context={"skill_id": "s_blocked"},
            upgrade_type="PATCH",
        )
        assert p.risk == "blocked"
        assert p.context.get("blocked_reason") == "patch_rate_exceeded"

    def test_minor_rate_limit(self):
        evolver = EvolverLayer()
        for i in range(evolver.MAX_MINOR_PER_DAY):
            p = evolver.create_proposal(
                context={"skill_id": f"s{i}"},
                upgrade_type="MINOR",
            )
            assert p.risk != "blocked"

        p = evolver.create_proposal(
            context={"skill_id": "s_blocked"},
            upgrade_type="MINOR",
        )
        assert p.risk == "blocked"
        assert p.context.get("blocked_reason") == "minor_rate_exceeded"

    def test_daily_counts(self):
        evolver = EvolverLayer()
        evolver.create_proposal(context={"skill_id": "s1"}, upgrade_type="PATCH")
        evolver.create_proposal(context={"skill_id": "s2"}, upgrade_type="PATCH")
        evolver.create_proposal(context={"skill_id": "s3"}, upgrade_type="MINOR")
        counts = evolver.get_daily_counts()
        assert counts["patch"] == 2
        assert counts["minor"] == 1


class TestSafetyConstraint2MajorApproval:
    """Safety constraint #2: MAJOR requires approval_token."""

    def test_major_gets_approval_token(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="MAJOR",
        )
        assert proposal.approval_token != ""
        assert len(proposal.approval_token) > 20  # Secure random token

    def test_patch_no_approval_token(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        assert proposal.approval_token == ""

    def test_verify_approval_token_correct(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="MAJOR",
        )
        assert evolver.verify_approval_token(proposal.proposal_id, proposal.approval_token) is True

    def test_verify_approval_token_wrong(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="MAJOR",
        )
        assert evolver.verify_approval_token(proposal.proposal_id, "wrong-token") is False

    def test_verify_approval_token_non_major(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        # Non-MAJOR always passes
        assert evolver.verify_approval_token(proposal.proposal_id, "") is True


class TestSafetyConstraint3Rollback:
    """Safety constraint #3: VERIFY failed → automatic rollback."""

    def test_rollback_on_verify_failure(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(context={"skill_id": "s1"})
        report = evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            bdd_results={"test": False},
        )
        assert report.rollback_performed is True
        assert report.status == VerificationStatus.ROLLED_BACK

    def test_snapshot_save_and_restore(self):
        evolver = EvolverLayer()
        skill_data = {"name": "s1", "version": "1.0", "config": {"timeout": 15}}
        evolver.save_snapshot("proposal-1", skill_data)
        restored = evolver.get_snapshot("proposal-1")
        assert restored == skill_data

    def test_snapshot_not_found(self):
        evolver = EvolverLayer()
        assert evolver.get_snapshot("nonexistent") is None


class TestSafetyConstraint4Cooldown:
    """Safety constraint #4: 24h cooldown per skill."""

    def test_cooldown_blocks_second_evolution(self):
        evolver = EvolverLayer()
        # First evolution succeeds
        p1 = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        assert p1.risk != "blocked"

        # Second evolution for same skill is blocked by cooldown
        p2 = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        assert p2.risk == "blocked"
        assert p2.context.get("blocked_reason") == "cooldown_active"

    def test_different_skill_not_blocked(self):
        evolver = EvolverLayer()
        p1 = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        assert p1.risk != "blocked"

        # Different skill is not blocked
        p2 = evolver.create_proposal(
            context={"skill_id": "s2"},
            upgrade_type="PATCH",
        )
        assert p2.risk != "blocked"


class TestSafetyConstraint5GlobalCBLock:
    """Safety constraint #5: global CB lock blocks auto-evolution."""

    def test_global_lock_blocks_patch(self):
        evolver = EvolverLayer()
        evolver.set_global_cb_lock(True)
        p = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        assert p.risk == "blocked"
        assert p.context.get("blocked_reason") == "global_cb_locked"

    def test_global_lock_blocks_minor(self):
        evolver = EvolverLayer()
        evolver.set_global_cb_lock(True)
        p = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="MINOR",
        )
        assert p.risk == "blocked"

    def test_global_lock_allows_major(self):
        evolver = EvolverLayer()
        evolver.set_global_cb_lock(True)
        p = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="MAJOR",
        )
        # MAJOR still allowed (requires human approval anyway)
        assert p.risk != "blocked"

    def test_unlock_restores_evolution(self):
        evolver = EvolverLayer()
        evolver.set_global_cb_lock(True)
        p1 = evolver.create_proposal(context={"skill_id": "s1"}, upgrade_type="PATCH")
        assert p1.risk == "blocked"

        evolver.set_global_cb_lock(False)
        p2 = evolver.create_proposal(context={"skill_id": "s2"}, upgrade_type="PATCH")
        assert p2.risk != "blocked"

    def test_is_global_cb_locked(self):
        evolver = EvolverLayer()
        assert evolver.is_global_cb_locked() is False
        evolver.set_global_cb_lock(True)
        assert evolver.is_global_cb_locked() is True


class TestSafetyConstraint6RegressionMonitor:
    """Safety constraint #6: 7-day regression monitor after evolution."""

    def test_monitor_started_on_verify_pass(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            scores_before={"D3": 7.0},
            scores_after={"D3": 8.0},
        )
        monitor = evolver.check_regression_monitor("s1")
        assert monitor is not None
        assert "monitor_until" in monitor

    def test_no_monitor_on_verify_fail(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        evolver.verify_evolution(
            proposal_id=proposal.proposal_id,
            bdd_results={"test": False},
        )
        monitor = evolver.check_regression_monitor("s1")
        assert monitor is None

    def test_regression_recurrence_escalation(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="PATCH",
        )
        evolver.verify_evolution(proposal_id=proposal.proposal_id)
        # Report recurrence — PATCH should escalate to MINOR
        result = evolver.report_regression_recurrence("s1", "D3")
        assert result == "escalate_to_minor"

    def test_regression_recurrence_minor_escalates_to_major(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"skill_id": "s1"},
            upgrade_type="MINOR",
        )
        evolver.verify_evolution(proposal_id=proposal.proposal_id)
        result = evolver.report_regression_recurrence("s1", "D5")
        assert result == "escalate_to_major"

    def test_regression_recurrence_no_monitor(self):
        evolver = EvolverLayer()
        result = evolver.report_regression_recurrence("s1", "D3")
        assert result == "no_monitor"


class TestEvolutionProposalUpgradeType:
    """Test upgrade_type field on proposals."""

    def test_default_upgrade_type(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(context={"reason": "test"})
        assert proposal.upgrade_type == "PATCH"

    def test_explicit_upgrade_type(self):
        evolver = EvolverLayer()
        proposal = evolver.create_proposal(
            context={"reason": "test"},
            upgrade_type="MAJOR",
        )
        assert proposal.upgrade_type == "MAJOR"


class TestExecuteEvolution:
    """Test execute_evolution: YAML write + re-materialize."""

    def test_execute_writes_yaml(self, tmp_path: Path):
        """execute_evolution should update the CSDF YAML on disk."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_yaml = skills_dir / "S09-test.yaml"
        skill_yaml.write_text(
            yaml.dump({"id": "S09", "name": "Test", "version": "1.0.0"}),
            encoding="utf-8",
        )

        evolver = EvolverLayer(skills_dir=skills_dir)
        proposal = evolver.create_proposal(
            context={"skill_id": "S09"},
            upgrade_type="PATCH",
        )
        result = evolver.execute_evolution(proposal.proposal_id)

        assert result["status"] == "success"
        assert result["yaml_updated"] is True

        # Verify YAML was updated
        data = yaml.safe_load(skill_yaml.read_text(encoding="utf-8"))
        assert data["version"] == "1.0.1"
        assert "last_evolved" in data
        assert data["evolution_proposal"] == proposal.proposal_id

    def test_execute_with_updates(self, tmp_path: Path):
        """execute_evolution should apply custom updates to the YAML."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_yaml = skills_dir / "S09-test.yaml"
        skill_yaml.write_text(
            yaml.dump({"id": "S09", "name": "Test", "version": "1.2.0"}),
            encoding="utf-8",
        )

        evolver = EvolverLayer(skills_dir=skills_dir)
        proposal = evolver.create_proposal(
            context={"skill_id": "S09"},
            upgrade_type="MINOR",
        )
        result = evolver.execute_evolution(
            proposal.proposal_id,
            updates={"description": "Updated via evolution"},
        )

        assert result["status"] == "success"
        data = yaml.safe_load(skill_yaml.read_text(encoding="utf-8"))
        assert data["version"] == "1.3.0"
        assert data["description"] == "Updated via evolution"

    def test_execute_major_version_bump(self, tmp_path: Path):
        """MAJOR upgrade should bump major version."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_yaml = skills_dir / "S09-test.yaml"
        skill_yaml.write_text(
            yaml.dump({"id": "S09", "name": "Test", "version": "2.3.1"}),
            encoding="utf-8",
        )

        evolver = EvolverLayer(skills_dir=skills_dir)
        proposal = evolver.create_proposal(
            context={"skill_id": "S09"},
            upgrade_type="MAJOR",
        )
        result = evolver.execute_evolution(proposal.proposal_id)

        assert result["status"] == "success"
        data = yaml.safe_load(skill_yaml.read_text(encoding="utf-8"))
        assert data["version"] == "3.0.0"

    def test_execute_not_found_proposal(self):
        """execute_evolution should return error for nonexistent proposal."""
        evolver = EvolverLayer()
        result = evolver.execute_evolution("nonexistent")
        assert result["status"] == "not_found"

    def test_execute_no_yaml_file(self):
        """execute_evolution should return error when no YAML exists."""
        evolver = EvolverLayer(skills_dir=Path("/nonexistent"))
        proposal = evolver.create_proposal(
            context={"skill_id": "S99"},
            upgrade_type="PATCH",
        )
        result = evolver.execute_evolution(proposal.proposal_id)
        assert result["status"] == "no_yaml"

    def test_execute_saves_snapshot(self, tmp_path: Path):
        """execute_evolution should save pre-evolution snapshot for rollback."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_yaml = skills_dir / "S09-test.yaml"
        original_data = {"id": "S09", "name": "Test", "version": "1.0.0"}
        skill_yaml.write_text(
            yaml.dump(original_data),
            encoding="utf-8",
        )

        evolver = EvolverLayer(skills_dir=skills_dir)
        proposal = evolver.create_proposal(
            context={"skill_id": "S09"},
            upgrade_type="PATCH",
        )
        evolver.execute_evolution(proposal.proposal_id)

        # Verify snapshot was saved
        snapshot = evolver.get_snapshot(proposal.proposal_id)
        assert snapshot is not None
        assert snapshot["id"] == "S09"
        assert snapshot["version"] == "1.0.0"


class TestBumpVersion:
    """Test _bump_version static method."""

    def test_patch_bump(self):
        assert EvolverLayer._bump_version("1.2.3", "PATCH") == "1.2.4"

    def test_minor_bump(self):
        assert EvolverLayer._bump_version("1.2.3", "MINOR") == "1.3.0"

    def test_major_bump(self):
        assert EvolverLayer._bump_version("1.2.3", "MAJOR") == "2.0.0"

    def test_non_semver_unchanged(self):
        assert EvolverLayer._bump_version("v1", "PATCH") == "v1"


class TestDiskPersistence:
    """Test Evolver disk persistence (proposals, snapshots, reports)."""

    def test_save_and_load_proposals(self, tmp_path: Path):
        """Proposals should persist to disk and reload on init."""
        evolver_dir = tmp_path / "evolver"

        evolver = EvolverLayer(evolver_dir=evolver_dir)
        proposal = evolver.create_proposal(
            context={"skill_id": "S09"},
            upgrade_type="PATCH",
        )
        assert evolver_dir.exists()
        assert (evolver_dir / "proposals.yaml").exists()

        # Create new evolver instance and verify it loads
        evolver2 = EvolverLayer(evolver_dir=evolver_dir)
        assert proposal.proposal_id in evolver2._proposals

    def test_save_and_load_snapshots(self, tmp_path: Path):
        """Snapshots should persist to disk and reload on init."""
        evolver_dir = tmp_path / "evolver"

        evolver = EvolverLayer(evolver_dir=evolver_dir)
        evolver.save_snapshot("snap-1", {"id": "S09", "version": "1.0.0"})
        assert (evolver_dir / "snapshots.yaml").exists()

        evolver2 = EvolverLayer(evolver_dir=evolver_dir)
        assert "snap-1" in evolver2._snapshots

    def test_graceful_no_dir(self, tmp_path: Path):
        """Loading should be a no-op when no evolver dir exists."""
        evolver_dir = tmp_path / "nonexistent"
        evolver = EvolverLayer(evolver_dir=evolver_dir)
        assert len(evolver._proposals) == 0
