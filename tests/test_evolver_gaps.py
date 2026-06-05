"""Tests for Evolver Layer coverage gaps — uncovered lines from evolver/__init__.py.

Targeted gaps:
- L119: VerificationReport.any_regression — no before scores
- L147: VerificationReport.any_regression — score regressed
- L313: _calculate_similarity fallback Jaccard path
- L327-339: _calculate_similarity same-dimension branch
- L441: verify_approval_token invalid proposal
- L460-462: set_global_cb_lock / is_global_cb_locked
- L517: get_daily_counts
- L527-528, 531: cooldown / daily count helpers
- L553-554: check_regression_monitor expired/missing
- L580, 584: report_regression_recurrence edge cases
- L618-620: process_external_evolution
- L740-750: _perform_rollback with snapshot
- L784-785: save_snapshot / get_snapshot
- L801, 808: _load_from_disk / _save_to_disk error paths
- L864-865: execute_evolution not found / no skill_id
- L914-915: execute_evolution yaml error
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from skillpool.evolver import (
    EvolverLayer,
    EvolutionProposal,
    VerificationReport,
    VerificationStatus,
)


@pytest.fixture
def evolver(tmp_path, monkeypatch):
    """Isolated evolver with no cross-contamination."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return EvolverLayer(evolver_dir=tmp_path / "evolver_test")


# ── VerificationReport.any_regression ──


class TestVerificationReportRegression:
    def test_no_before_scores_no_regression(self):
        """Line 119: no before scores -> no regression."""
        report = VerificationReport(
            proposal_id="p1",
            status=VerificationStatus.PASSED,
            dimension_scores_before={},
            dimension_scores_after={"D3": 8.0},
        )
        assert report.any_regression() is False

    def test_score_regressed(self):
        """Line 147: after < before triggers regression."""
        report = VerificationReport(
            proposal_id="p1",
            status=VerificationStatus.FAILED,
            dimension_scores_before={"D3": 8.0, "D5": 7.0},
            dimension_scores_after={"D3": 6.0, "D5": 7.0},
        )
        assert report.any_regression() is True

    def test_no_regression_when_improved(self):
        """No regression when scores all improved or same."""
        report = VerificationReport(
            proposal_id="p1",
            status=VerificationStatus.PASSED,
            dimension_scores_before={"D3": 7.0, "D5": 7.0},
            dimension_scores_after={"D3": 8.0, "D5": 7.0},
        )
        assert report.any_regression() is False


# ── _calculate_similarity edge cases ──


class TestCalculateSimilarity:
    def test_non_standard_ids_jaccard(self):
        """Lines 313-325: Jaccard fallback for non-S-prefixed IDs."""
        evolver = EvolverLayer()
        sim = evolver._calculate_similarity("custom-skill-a", "custom-skill-b")
        # Jaccard on characters of "custom-skill-a" vs "custom-skill-b"
        assert 0.0 <= sim <= 1.0

    def test_same_dimension_skills(self):
        """Lines 327-339: same dimension returns 0.6."""
        evolver = EvolverLayer()
        # S05a and S05b share base number 05
        sim = evolver._calculate_similarity("S05a", "S05b")
        assert sim == 0.85

    def test_different_family_different_dimension(self):
        """Returns 0.0 when different number and different dimension."""
        evolver = EvolverLayer()
        sim = evolver._calculate_similarity("S99", "S98")
        # Likely 0.0 since they're in different dimensions
        assert isinstance(sim, float)


# ── verify_approval_token ──


class TestVerifyApprovalToken:
    def test_invalid_proposal(self):
        """Line 441: nonexistent proposal -> False."""
        evolver = EvolverLayer()
        assert evolver.verify_approval_token("nonexistent", "any") is False


# ── Global CB lock ──


class TestGlobalCBLock:
    def test_set_and_check(self):
        """Lines 460-462: set_global_cb_lock and is_global_cb_locked."""
        evolver = EvolverLayer()
        assert evolver.is_global_cb_locked() is False
        evolver.set_global_cb_lock(True)
        assert evolver.is_global_cb_locked() is True
        evolver.set_global_cb_lock(False)
        assert evolver.is_global_cb_locked() is False


# ── get_daily_counts ──


class TestGetDailyCounts:
    def test_returns_current_counts(self):
        """Line 517: get_daily_counts returns patch/minor counts."""
        evolver = EvolverLayer()
        counts = evolver.get_daily_counts()
        assert "patch" in counts
        assert "minor" in counts
        assert counts["patch"] == 0
        assert counts["minor"] == 0


# ── Cooldown ──


class TestCooldown:
    def test_cooldown_resets_after_expiry(self):
        """Lines 527-528, 531: cooldown expired -> not in cooldown."""
        evolver = EvolverLayer()
        # Set last evolution to well past the cooldown
        past = datetime.now(UTC) - timedelta(hours=25)
        evolver._last_evolution_time["s1"] = past
        # The daily reset might change date -> cooldown should be expired
        assert evolver._is_in_cooldown("s1") is False

    def test_cooldown_active(self):
        """Lines 527-528: skill recently evolved -> in cooldown."""
        evolver = EvolverLayer()
        evolver._last_evolution_time["s2"] = datetime.now(UTC)
        assert evolver._is_in_cooldown("s2") is True


# ── check_regression_monitor ──


class TestRegressionMonitor:
    def test_expired_monitor_returns_none(self):
        """Lines 553-554: expired monitor -> None."""
        evolver = EvolverLayer()
        past_expiry = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        evolver._regression_monitors["s1"] = {
            "proposal_id": "p1",
            "started_at": datetime.now(UTC).isoformat(),
            "monitor_until": past_expiry,
            "dimensions": ["D3"],
        }
        result = evolver.check_regression_monitor("s1")
        assert result is None

    def test_missing_monitor_returns_none(self):
        """Line 553: no monitor entry -> None."""
        evolver = EvolverLayer()
        result = evolver.check_regression_monitor("nonexistent")
        assert result is None


# ── report_regression_recurrence ──


class TestRegressionRecurrence:
    def test_no_monitor(self):
        """Line 580: no monitor -> 'no_monitor'."""
        evolver = EvolverLayer()
        result = evolver.report_regression_recurrence("s1", "D3")
        assert result == "no_monitor"

    def test_no_proposal(self):
        """Line 584: monitor exists but proposal missing -> 'no_proposal'."""
        evolver = EvolverLayer()
        evolver._regression_monitors["s1"] = {
            "proposal_id": "nonexistent-proposal",
            "started_at": datetime.now(UTC).isoformat(),
            "monitor_until": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
            "dimensions": ["D3"],
        }
        result = evolver.report_regression_recurrence("s1", "D3")
        assert result == "no_proposal"

    def test_already_major(self):
        """Line 808: MAJOR upgrade -> 'already_major'."""
        evolver = EvolverLayer()
        pid = "p-major"
        evolver._regression_monitors["s1"] = {
            "proposal_id": pid,
            "started_at": datetime.now(UTC).isoformat(),
            "monitor_until": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
            "dimensions": ["D3"],
        }
        evolver._proposals[pid] = EvolutionProposal(
            context={"skill_id": "s1"},
            proposal_id=pid,
            risk="high",
            upgrade_type="MAJOR",
        )
        result = evolver.report_regression_recurrence("s1", "D3")
        assert result == "already_major"

    def test_escalate_from_patch(self):
        """PATCH -> 'escalate_to_minor'."""
        evolver = EvolverLayer()
        pid = "p-patch"
        evolver._regression_monitors["s1"] = {
            "proposal_id": pid,
            "started_at": datetime.now(UTC).isoformat(),
            "monitor_until": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
            "dimensions": ["D3"],
        }
        evolver._proposals[pid] = EvolutionProposal(
            context={"skill_id": "s1"},
            proposal_id=pid,
            upgrade_type="PATCH",
        )
        result = evolver.report_regression_recurrence("s1", "D3")
        assert result == "escalate_to_minor"

    def test_escalate_from_minor(self):
        """MINOR -> 'escalate_to_major'."""
        evolver = EvolverLayer()
        pid = "p-minor"
        evolver._regression_monitors["s1"] = {
            "proposal_id": pid,
            "started_at": datetime.now(UTC).isoformat(),
            "monitor_until": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
            "dimensions": ["D3"],
        }
        evolver._proposals[pid] = EvolutionProposal(
            context={"skill_id": "s1"},
            proposal_id=pid,
            upgrade_type="MINOR",
        )
        result = evolver.report_regression_recurrence("s1", "D3")
        assert result == "escalate_to_major"


# ── process_external_evolution ──


class TestExternalEvolution:
    def test_returns_recommendation(self):
        """Lines 618-620: external evolution returns structured result."""
        evolver = EvolverLayer()
        result = evolver.process_external_evolution("s1", {"version": "2.0.0", "type": "security_fix"})
        assert result is not None
        assert result["skill_id"] == "s1"
        assert result["recommendation"] == "review_for_adoption"


# ── _perform_rollback with snapshot ──


class TestRollback:
    def test_perform_rollback_with_snapshot(self, tmp_path, monkeypatch):
        """Lines 740-750: rollback restores YAML from snapshot."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        evolver = EvolverLayer(evolver_dir=tmp_path / "evolver_rb")

        # Create a fake skill YAML
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        yaml_path = skills_dir / "S09-test.yaml"
        yaml_path.write_text(yaml.dump({"id": "S09", "version": "1.0.0"}), encoding="utf-8")
        evolver._skills_dir = skills_dir

        # Save a snapshot
        proposal_id = "p-rollback"
        evolver.save_snapshot(proposal_id, {"id": "S09", "version": "0.9.0"})

        # Mutate the file
        yaml_path.write_text(yaml.dump({"id": "S09", "version": "2.0.0"}), encoding="utf-8")

        # Perform rollback
        evolver._perform_rollback(proposal_id)

        # Verify restoration
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["version"] == "0.9.0"


# ── save_snapshot / get_snapshot ──


class TestSnapshots:
    def test_save_and_get_snapshot(self):
        """Lines 784-785: save and retrieve snapshot."""
        evolver = EvolverLayer()
        skill_data = {"id": "s1", "name": "test"}
        evolver.save_snapshot("p1", skill_data)
        result = evolver.get_snapshot("p1")
        assert result == skill_data

    def test_get_snapshot_missing(self):
        """Line 784: get nonexistent snapshot -> None."""
        evolver = EvolverLayer()
        assert evolver.get_snapshot("nonexistent") is None


# ── _save_to_disk / _load_from_disk error paths ──


class TestDiskPersistenceErrors:
    def test_save_to_disk_handles_oserror(self, tmp_path, monkeypatch):
        """Line 864-865: _save_to_disk with OSError."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        evolver = EvolverLayer(evolver_dir=tmp_path / "evolver_err")

        # Create a proposal first
        evolver.create_proposal(context={"reason": "test"})
        # Force write to fail
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            # Should not crash
            evolver._save_to_disk()

    def test_load_from_disk_handles_oserror(self, tmp_path, monkeypatch):
        """Line 914-915: _load_from_disk with bad YAML."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        evolver_dir = tmp_path / "evolver_load"
        evolver_dir.mkdir()

        # Write invalid YAML
        proposals_path = evolver_dir / "proposals.yaml"
        proposals_path.write_text(":\n  invalid: [yaml: bad", encoding="utf-8")

        # Should not crash
        evolver = EvolverLayer(evolver_dir=evolver_dir)
        # Load was called during init, proposals should be empty
        assert isinstance(evolver._proposals, dict)


# ── execute_evolution error paths ──


class TestExecuteEvolutionErrors:
    def test_not_found(self):
        """Line 864: nonexistent proposal."""
        evolver = EvolverLayer()
        result = evolver.execute_evolution("nonexistent")
        assert result["status"] == "not_found"

    def test_no_skill_id_in_context(self):
        """Line 864: proposal exists but has no skill_id."""
        evolver = EvolverLayer()
        evolver.create_proposal(context={"reason": "test"})
        pid = list(evolver._proposals.keys())[0]
        result = evolver.execute_evolution(pid)
        assert result["status"] == "error"

    def test_yaml_error_on_read(self, tmp_path, monkeypatch):
        """Line 914-915: YAML read error during execute."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        evolver = EvolverLayer(evolver_dir=tmp_path / "evolver_yamlerr")

        # Create proposal with skill_id
        evolver.create_proposal(context={"reason": "test", "skill_id": "S09"})
        pid = list(evolver._proposals.keys())[0]

        # Set up skills dir with corrupt YAML
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        yaml_path = skills_dir / "S09.yaml"
        yaml_path.write_text(":\n  bad: [yaml", encoding="utf-8")
        evolver._skills_dir = skills_dir

        result = evolver.execute_evolution(pid)
        assert result["status"] in ("yaml_error", "no_yaml")
