"""Tests for Registry Layer — Skill metadata and lifecycle governance."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from skillpool.audit import AuditLayer
from skillpool.registry import (
    AuditUnavailableError,
    IllegalStateTransitionError,
    PolicyDeniedError,
    Registry,
    SandboxRequiredError,
    SkillNotFoundError,
    SkillRecord,
    SUPPLY_CHAIN_PROFILES,
    SupplyChainEvidenceMissingError,
)
from skillpool.registry.models import (
    RegisterSkillRequest,
    SkillMetadata,
    SkillStatus,
    StateTransitionRequest,
)


def _make_metadata(skill_id="s1", **security_overrides) -> SkillMetadata:
    """Create a SkillMetadata with all required evidence fields."""
    security = {
        "sbom_ref": "sbom-001",
        "provenance_ref": "provenance-001",
        "source_pin": "sha256:abc123",
        "signature_ref": "sig-001",
    }
    security.update(security_overrides)
    return SkillMetadata(
        skill_id=skill_id,
        name="Test Skill",
        version="1.0.0",
        status=SkillStatus.DRAFT,
        security=security,
    )


def _make_audit() -> AuditLayer:
    return AuditLayer(available=True)


class TestSkillStatus:
    def test_all_9_states(self):
        states = [
            "draft", "imported", "testing", "enabled", "disabled",
            "deprecated", "archived", "rejected", "quarantined",
        ]
        for s in states:
            assert SkillStatus(s).value == s


class TestSkillMetadata:
    def test_creation(self):
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            status=SkillStatus.DRAFT
        )
        assert meta.skill_id == "s1"
        assert meta.status == SkillStatus.DRAFT


class TestSkillRecord:
    def test_to_dict_and_from_dict(self):
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        record = SkillRecord(
            metadata=meta, created_at=now, updated_at=now,
            evidence={"SPDX SBOM"}, audit_refs=["audit-1"]
        )
        d = record.to_dict()
        assert d["metadata"]["skill_id"] == "s1"
        assert "SPDX SBOM" in d["evidence"]

        restored = SkillRecord.from_dict(d)
        assert restored.metadata.skill_id == "s1"
        assert "SPDX SBOM" in restored.evidence


class TestRegistry:
    def test_register_candidate_success(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        resp = reg.register_candidate(req)
        assert resp.skill_id == "s1"
        assert resp.status == "testing"

    def test_register_candidate_audit_unavailable(self):
        audit = AuditLayer(available=False)
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        with pytest.raises(AuditUnavailableError):
            reg.register_candidate(req)

    def test_register_missing_evidence(self):
        audit = _make_audit()
        # Ensure prod evidence tier for this test (dev tier allows no evidence)
        reg = Registry(audit_layer=audit)
        reg._evidence_profile = "prod"
        reg._required_evidence = SUPPLY_CHAIN_PROFILES["prod"]
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={"sbom_ref": "only_sbom"}
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        with pytest.raises(SupplyChainEvidenceMissingError):
            reg.register_candidate(req)

    def test_register_sets_testing_status(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        meta.status = SkillStatus.DRAFT
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)
        record = reg.get_skill("s1")
        assert record.metadata.status == SkillStatus.TESTING

    def test_transition_legal(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        transition_req = StateTransitionRequest(
            from_status=SkillStatus.TESTING,
            to_status=SkillStatus.ENABLED,
        )
        resp = reg.transition_state(
            "s1", transition_req,
            sandbox_result="pass", policy_approval=True
        )
        assert resp.to_status == "enabled"

    def test_transition_illegal_draft_to_enabled(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        meta.status = SkillStatus.DRAFT
        # Manually insert record in draft state
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        reg._skills["s1"] = SkillRecord(metadata=meta, created_at=now, updated_at=now)

        transition_req = StateTransitionRequest(
            from_status=SkillStatus.DRAFT,
            to_status=SkillStatus.ENABLED,
        )
        with pytest.raises(IllegalStateTransitionError, match="Illegal"):
            reg.transition_state("s1", transition_req)

    def test_transition_unknown_path(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        meta.status = SkillStatus.ENABLED
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        reg._skills["s1"] = SkillRecord(metadata=meta, created_at=now, updated_at=now)

        transition_req = StateTransitionRequest(
            from_status=SkillStatus.ENABLED,
            to_status=SkillStatus.DRAFT,  # Not in LEGAL_TRANSITIONS
        )
        with pytest.raises(IllegalStateTransitionError, match="Unknown"):
            reg.transition_state("s1", transition_req)

    def test_transition_state_mismatch(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)  # status = testing

        transition_req = StateTransitionRequest(
            from_status=SkillStatus.DRAFT,  # Wrong current state
            to_status=SkillStatus.ENABLED,
        )
        with pytest.raises(IllegalStateTransitionError, match="Current state"):
            reg.transition_state("s1", transition_req)

    def test_transition_requires_sandbox(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        transition_req = StateTransitionRequest(
            from_status=SkillStatus.TESTING,
            to_status=SkillStatus.ENABLED,
        )
        # sandbox_result not provided → SandboxRequiredError
        with pytest.raises(SandboxRequiredError):
            reg.transition_state("s1", transition_req, policy_approval=True)

    def test_transition_requires_policy(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        transition_req = StateTransitionRequest(
            from_status=SkillStatus.TESTING,
            to_status=SkillStatus.ENABLED,
        )
        with pytest.raises(PolicyDeniedError):
            reg.transition_state("s1", transition_req, sandbox_result="pass")

    def test_transition_audit_unavailable(self):
        audit = AuditLayer(available=False)
        reg = Registry(audit_layer=audit)
        with pytest.raises(AuditUnavailableError):
            reg.transition_state("s1", StateTransitionRequest(
                from_status=SkillStatus.TESTING,
                to_status=SkillStatus.ENABLED,
            ))

    def test_skill_not_found(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        with pytest.raises(SkillNotFoundError):
            reg.transition_state("nonexistent", StateTransitionRequest(
                from_status=SkillStatus.TESTING,
                to_status=SkillStatus.ENABLED,
            ))

    def test_get_skill(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)
        record = reg.get_skill("s1")
        assert record is not None
        assert record.metadata.skill_id == "s1"

    def test_get_skill_not_found(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        assert reg.get_skill("nonexistent") is None

    def test_is_enabled(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)
        assert not reg.is_enabled("s1")  # In testing state

    def test_is_enabled_after_transition(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)
        reg.transition_state("s1", StateTransitionRequest(
            from_status=SkillStatus.TESTING,
            to_status=SkillStatus.ENABLED,
        ), sandbox_result="pass", policy_approval=True)
        assert reg.is_enabled("s1")

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "registry.json")
            audit = _make_audit()
            reg = Registry(audit_layer=audit, registry_path=path)
            meta = _make_metadata("s1")
            req = RegisterSkillRequest(skill_metadata=meta)
            reg.register_candidate(req)

            # Load from disk
            reg2 = Registry(audit_layer=audit, registry_path=path)
            record = reg2.get_skill("s1")
            assert record is not None
            assert record.metadata.skill_id == "s1"

    def test_evidence_mapping_sbom(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={"sbom": "sbom-data", "provenance": "prov",
                      "source": "src", "signature": "sig"}
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        resp = reg.register_candidate(req)
        assert resp.status == "testing"

    def test_full_lifecycle(self):
        """Test: draft → testing → enabled → disabled → testing → enabled"""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        # testing → enabled
        reg.transition_state("s1", StateTransitionRequest(
            from_status=SkillStatus.TESTING,
            to_status=SkillStatus.ENABLED,
        ), sandbox_result="pass", policy_approval=True)
        assert reg.is_enabled("s1")

        # enabled → disabled
        reg.transition_state("s1", StateTransitionRequest(
            from_status=SkillStatus.ENABLED,
            to_status=SkillStatus.DISABLED,
        ))
        assert not reg.is_enabled("s1")

        # disabled → testing
        reg.transition_state("s1", StateTransitionRequest(
            from_status=SkillStatus.DISABLED,
            to_status=SkillStatus.TESTING,
        ))
        record = reg.get_skill("s1")
        assert record.metadata.status == SkillStatus.TESTING

    def test_multiple_skills(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        for i in range(3):
            meta = _make_metadata(f"s{i}")
            req = RegisterSkillRequest(skill_metadata=meta)
            reg.register_candidate(req)
        for i in range(3):
            assert reg.get_skill(f"s{i}") is not None


class TestSupplyChainEvidence:
    """Tests for supply chain evidence query and verification."""

    def test_get_supply_chain_evidence(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)
        evidence = reg.get_supply_chain_evidence("s1")
        assert evidence is not None
        assert evidence["skill_id"] == "s1"
        assert evidence["is_complete"] is True
        assert len(evidence["missing"]) == 0

    def test_get_evidence_not_found(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        assert reg.get_supply_chain_evidence("nonexistent") is None

    def test_verify_evidence_integrity_complete(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)
        issues = reg.verify_evidence_integrity("s1")
        assert issues == []

    def test_verify_evidence_not_found(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        issues = reg.verify_evidence_integrity("nonexistent")
        assert len(issues) == 1
        assert "not found" in issues[0]

    def test_evidence_contains_required_fields(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)
        evidence = reg.get_supply_chain_evidence("s1")
        # All 4 required evidence types should be present
        assert "SPDX SBOM" in evidence["evidence"]
        assert "SLSA provenance" in evidence["evidence"]
        assert "source pin" in evidence["evidence"]
        assert "signature" in evidence["evidence"]


class TestSaveLoadCycle:
    """Integration tests for Registry save→load cycle (data survives restart)."""

    def test_state_transitions_preserved(self, tmp_path):
        """State transitions should survive a save→load cycle."""
        path = str(tmp_path / "registry.json")
        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=path)

        # Register and transition to enabled
        meta = _make_metadata("s1")
        reg.register_candidate(RegisterSkillRequest(skill_metadata=meta))
        reg.transition_state("s1", StateTransitionRequest(
            from_status=SkillStatus.TESTING,
            to_status=SkillStatus.ENABLED,
        ), sandbox_result="pass", policy_approval=True)
        assert reg.is_enabled("s1")

        # Save and reload
        reg2 = Registry(audit_layer=audit, registry_path=path)
        record = reg2.get_skill("s1")
        assert record is not None
        assert record.metadata.status == SkillStatus.ENABLED
        assert reg2.is_enabled("s1")

    def test_multiple_skills_preserved(self, tmp_path):
        """Multiple skills with different states should survive save→load."""
        path = str(tmp_path / "registry.json")
        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=path)

        # Register 3 skills with different states
        for sid in ["s1", "s2", "s3"]:
            meta = _make_metadata(sid)
            reg.register_candidate(RegisterSkillRequest(skill_metadata=meta))

        # Transition s1 to enabled
        reg.transition_state("s1", StateTransitionRequest(
            from_status=SkillStatus.TESTING,
            to_status=SkillStatus.ENABLED,
        ), sandbox_result="pass", policy_approval=True)

        # Transition s2 to disabled
        reg.transition_state("s2", StateTransitionRequest(
            from_status=SkillStatus.TESTING,
            to_status=SkillStatus.DISABLED,
        ))

        # Reload and verify all 3 skills with correct states
        reg2 = Registry(audit_layer=audit, registry_path=path)
        assert reg2.get_skill("s1").metadata.status == SkillStatus.ENABLED
        assert reg2.get_skill("s2").metadata.status == SkillStatus.DISABLED
        assert reg2.get_skill("s3").metadata.status == SkillStatus.TESTING

    def test_evidence_preserved(self, tmp_path):
        """Supply chain evidence should survive save→load."""
        path = str(tmp_path / "registry.json")
        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=path)

        meta = _make_metadata("s1")
        reg.register_candidate(RegisterSkillRequest(skill_metadata=meta))

        # Reload and verify evidence
        reg2 = Registry(audit_layer=audit, registry_path=path)
        evidence = reg2.get_supply_chain_evidence("s1")
        assert "SPDX SBOM" in evidence["evidence"]

    def test_empty_registry_load(self, tmp_path):
        """Loading from nonexistent file should produce empty registry."""
        path = str(tmp_path / "nonexistent.json")
        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=path)
        assert len(reg._skills) == 0
