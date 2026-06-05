"""Tests for Registry — covering uncovered lines in registry/__init__.py.

Uncovered lines:
- 83-84: from_dict with invalid status value → fallback to DRAFT
- 100: from_dict with metadata already being a SkillMetadata object
- 206: _load with empty file content
- 217-232: _load JSONL format parsing (one record per line)
- 244-245: _save OSError handling
- 408: get_skill by name index
- 445: verify_evidence_integrity with missing evidence
- 450-451: verify_evidence_integrity SBOM claimed but no field
- 453-454: verify_evidence_integrity signature claimed but no field
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch


from skillpool.audit import AuditLayer
from skillpool.registry import (
    Registry,
    SkillRecord,
    SUPPLY_CHAIN_PROFILES,
)
from skillpool.registry.models import (
    RegisterSkillRequest,
    SkillMetadata,
    SkillStatus,
)


def _make_metadata(skill_id="s1", **security_overrides) -> SkillMetadata:
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


# ---------------------------------------------------------------------------
# SkillRecord.from_dict — invalid status (lines 83-84)
# ---------------------------------------------------------------------------

class TestSkillRecordFromDictInvalidStatus:
    """When status string is not a valid SkillStatus, fallback to DRAFT."""

    def test_invalid_status_falls_back_to_draft(self):
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        record = SkillRecord(metadata=meta, created_at=now, updated_at=now)
        d = record.to_dict()
        # Corrupt the status
        d["metadata"]["status"] = "nonexistent_status"
        restored = SkillRecord.from_dict(d)
        assert restored.metadata.status == SkillStatus.DRAFT

    def test_valid_status_preserved(self):
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        record = SkillRecord(metadata=meta, created_at=now, updated_at=now)
        d = record.to_dict()
        d["metadata"]["status"] = "testing"
        restored = SkillRecord.from_dict(d)
        assert restored.metadata.status == SkillStatus.TESTING


# ---------------------------------------------------------------------------
# SkillRecord.from_dict — metadata already a SkillMetadata object (line 100)
# ---------------------------------------------------------------------------

class TestSkillRecordFromDictMetadataObject:
    """When metadata field is already a SkillMetadata, use it directly."""

    def test_metadata_is_skillmetadata_object(self):
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        data = {
            "metadata": meta,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "evidence": ["SPDX SBOM"],
            "audit_refs": ["audit-1"],
        }
        restored = SkillRecord.from_dict(data)
        assert restored.metadata is meta
        assert restored.metadata.skill_id == "s1"


# ---------------------------------------------------------------------------
# _load — empty file content (line 206)
# ---------------------------------------------------------------------------

class TestRegistryLoadEmptyFile:
    """Loading from an empty file should produce empty registry."""

    def test_empty_file_content(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("")
        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))
        assert len(reg._skills) == 0

    def test_whitespace_only_file(self, tmp_path):
        path = tmp_path / "whitespace.json"
        path.write_text("   \n\n  ")
        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))
        assert len(reg._skills) == 0


# ---------------------------------------------------------------------------
# _load — JSONL format (lines 217-232)
# ---------------------------------------------------------------------------

class TestRegistryLoadJSONL:
    """Registry supports JSONL format (one record per line).

    JSONL path is reached when json.loads(content) fails (e.g., multiple JSON
    objects on separate lines), triggering the JSONL line-by-line parser.
    """

    def _write_jsonl(self, path, records):
        """Write SkillRecords as JSONL (one JSON object per line).

        Using 2+ lines ensures json.loads(content) raises JSONDecodeError,
        forcing the JSONL line-by-line parser to run.
        """
        lines = [json.dumps(rec.to_dict()) for rec in records]
        # Write with a second line (even empty) to ensure multi-line content
        # that triggers JSONDecodeError in json.loads()
        content = "\n".join(lines) + "\n"
        path.write_text(content)

    def test_load_jsonl_format(self, tmp_path):
        """Load from JSONL file with one record per line."""
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        record = SkillRecord(metadata=meta, created_at=now, updated_at=now, evidence={"SPDX SBOM"})
        # Need at least 2 lines for json.loads to fail → JSONL parser
        meta2 = _make_metadata("s2")
        meta2.name = "Second Skill"
        record2 = SkillRecord(metadata=meta2, created_at=now, updated_at=now)

        path = tmp_path / "registry.jsonl"
        self._write_jsonl(path, [record, record2])

        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))
        assert "s1" in reg._skills
        assert "s2" in reg._skills

    def test_load_jsonl_multiple_records(self, tmp_path):
        """Load from JSONL with multiple records."""
        now = datetime.now(UTC)
        records = []
        for sid in ["s1", "s2", "s3"]:
            meta = _make_metadata(sid)
            rec = SkillRecord(metadata=meta, created_at=now, updated_at=now)
            records.append(rec)

        path = tmp_path / "registry.jsonl"
        self._write_jsonl(path, records)

        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))
        assert len(reg._skills) == 3

    def test_load_jsonl_skips_bad_lines(self, tmp_path):
        """Bad lines in JSONL are skipped gracefully."""
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        rec = SkillRecord(metadata=meta, created_at=now, updated_at=now)
        good_line = json.dumps(rec.to_dict())

        # Write: bad line, good line, another bad line
        # Multi-line ensures json.loads fails → JSONL path
        path = tmp_path / "registry.jsonl"
        path.write_text("bad line\n" + good_line + "\nanother bad line\n")

        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))
        assert len(reg._skills) == 1
        assert "s1" in reg._skills

    def test_load_jsonl_skips_blank_lines(self, tmp_path):
        """Blank lines in JSONL are skipped."""
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        rec = SkillRecord(metadata=meta, created_at=now, updated_at=now)
        meta2 = _make_metadata("s2")
        meta2.name = "Skill Two"
        rec2 = SkillRecord(metadata=meta2, created_at=now, updated_at=now)

        path = tmp_path / "registry.jsonl"
        # Blank lines between valid records
        lines = ["", json.dumps(rec.to_dict()), "", json.dumps(rec2.to_dict()), ""]
        path.write_text("\n".join(lines) + "\n")

        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))
        assert len(reg._skills) == 2

    def test_load_jsonl_name_index_populated(self, tmp_path):
        """JSONL load populates the name index for dual lookup."""
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        meta.name = "my-special-skill"
        rec = SkillRecord(metadata=meta, created_at=now, updated_at=now)
        meta2 = _make_metadata("s2")
        meta2.name = "other-skill"
        rec2 = SkillRecord(metadata=meta2, created_at=now, updated_at=now)

        path = tmp_path / "registry.jsonl"
        self._write_jsonl(path, [rec, rec2])

        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))
        # Lookup by name should work
        record = reg.get_skill("my-special-skill")
        assert record is not None
        assert record.metadata.skill_id == "s1"

    def test_load_json_format_with_name_index(self, tmp_path):
        """JSON object format also populates name index."""
        now = datetime.now(UTC)
        meta = _make_metadata("s1")
        meta.name = "json-skill"
        rec = SkillRecord(metadata=meta, created_at=now, updated_at=now)
        data = {"s1": rec.to_dict()}

        path = tmp_path / "registry.json"
        path.write_text(json.dumps(data))

        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))
        record = reg.get_skill("json-skill")
        assert record is not None


# ---------------------------------------------------------------------------
# _load — general exception (line 232)
# ---------------------------------------------------------------------------

class TestRegistryLoadException:
    """Registry load handles general exceptions gracefully."""

    def test_load_unreadable_file(self, tmp_path):
        """When file read raises an unexpected exception, load fails gracefully."""
        path = tmp_path / "unreadable.json"
        path.write_text("{}")
        audit = _make_audit()
        with patch.object(Path, "read_text", side_effect=PermissionError("no access")):
            reg = Registry(audit_layer=audit, registry_path=str(path))
            assert len(reg._skills) == 0


# ---------------------------------------------------------------------------
# _save — OSError handling (lines 244-245)
# ---------------------------------------------------------------------------

class TestRegistrySaveOSError:
    """Registry save handles OSError gracefully."""

    def test_save_os_error_logged(self, tmp_path):
        """When write fails, it's logged but doesn't raise."""
        path = tmp_path / "readonly" / "registry.json"
        audit = _make_audit()
        reg = Registry(audit_layer=audit, registry_path=str(path))

        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        # Should not raise even if save fails
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            resp = reg.register_candidate(req)
        assert resp.skill_id == "s1"


# ---------------------------------------------------------------------------
# get_skill by name index (line 408)
# ---------------------------------------------------------------------------

class TestGetSkillByName:
    """get_skill supports lookup by name via _by_name index."""

    def test_lookup_by_name(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        meta.name = "resilience-degradation"
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        # Lookup by skill_id works
        assert reg.get_skill("s1") is not None
        # Lookup by name works
        record = reg.get_skill("resilience-degradation")
        assert record is not None
        assert record.metadata.skill_id == "s1"

    def test_lookup_by_unknown_name_returns_none(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        assert reg.get_skill("nonexistent-name") is None


# ---------------------------------------------------------------------------
# verify_evidence_integrity — missing evidence (line 445)
# ---------------------------------------------------------------------------

class TestVerifyEvidenceIntegrityMissing:
    """When required evidence is missing, issues are reported."""

    def test_missing_evidence_reported(self, tmp_path):
        """Skill with incomplete evidence reports missing items."""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        # Use dev profile so registration doesn't require evidence
        reg._evidence_profile = "dev"
        reg._required_evidence = SUPPLY_CHAIN_PROFILES["dev"]

        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={},
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        # Now change evidence requirement to prod for verification
        reg._required_evidence = SUPPLY_CHAIN_PROFILES["prod"]

        issues = reg.verify_evidence_integrity("s1")
        assert len(issues) > 0
        assert any("Missing evidence" in i for i in issues)


# ---------------------------------------------------------------------------
# verify_evidence_integrity — SBOM claimed but no field (lines 450-451)
# ---------------------------------------------------------------------------

class TestVerifyEvidenceSBOMClaimedButNoField:
    """When SBOM evidence is claimed but no sbom_ref/sbom field exists."""

    def test_sbom_evidence_claimed_without_field(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        # Manually add SBOM evidence but remove the security fields
        record = reg.get_skill("s1")
        record.evidence.add("SPDX SBOM")
        record.metadata.security = {}  # Remove sbom_ref/sbom

        issues = reg.verify_evidence_integrity("s1")
        assert any("SBOM evidence claimed but no sbom_ref/sbom field" in i for i in issues)


# ---------------------------------------------------------------------------
# verify_evidence_integrity — signature claimed but no field (lines 453-454)
# ---------------------------------------------------------------------------

class TestVerifyEvidenceSignatureClaimedButNoField:
    """When signature evidence is claimed but no signature field exists."""

    def test_signature_evidence_claimed_without_field(self):
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        # Manually add signature evidence but remove the security fields
        record = reg.get_skill("s1")
        record.evidence.add("signature")
        record.metadata.security = {}  # Remove signature_ref/signature/digest

        issues = reg.verify_evidence_integrity("s1")
        assert any("Signature evidence claimed but no signature field" in i for i in issues)

    def test_both_sbom_and_signature_claims_without_fields(self):
        """Both SBOM and signature claims without backing fields."""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = _make_metadata("s1")
        req = RegisterSkillRequest(skill_metadata=meta)
        reg.register_candidate(req)

        record = reg.get_skill("s1")
        record.evidence.add("SPDX SBOM")
        record.evidence.add("signature")
        record.metadata.security = {}

        issues = reg.verify_evidence_integrity("s1")
        assert any("SBOM evidence claimed" in i for i in issues)
        assert any("Signature evidence claimed" in i for i in issues)


# ---------------------------------------------------------------------------
# Evidence mapping alternate field names (lines 275-282)
# ---------------------------------------------------------------------------

class TestEvidenceAlternateFieldNames:
    """Test all alternate security field names that map to evidence types."""

    def test_sbom_field_instead_of_sbom_ref(self):
        """'sbom' field maps to SPDX SBOM evidence."""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={"sbom": "data", "provenance_ref": "p", "source_pin": "s", "signature_ref": "sig"},
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        resp = reg.register_candidate(req)
        assert resp.status == "testing"
        record = reg.get_skill("s1")
        assert "SPDX SBOM" in record.evidence

    def test_provenance_field_instead_of_provenance_ref(self):
        """'provenance' field maps to SLSA provenance evidence."""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={"sbom_ref": "sbom", "provenance": "data", "source_pin": "s", "signature_ref": "sig"},
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        resp = reg.register_candidate(req)
        assert resp.status == "testing"
        record = reg.get_skill("s1")
        assert "SLSA provenance" in record.evidence

    def test_source_ref_field(self):
        """'source_ref' field maps to source pin evidence."""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={"sbom_ref": "sbom", "provenance_ref": "p", "source_ref": "src", "signature_ref": "sig"},
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        _resp = reg.register_candidate(req)
        record = reg.get_skill("s1")
        assert "source pin" in record.evidence

    def test_source_field(self):
        """'source' field maps to source pin evidence."""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={"sbom_ref": "sbom", "provenance_ref": "p", "source": "src", "signature_ref": "sig"},
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        _resp = reg.register_candidate(req)
        record = reg.get_skill("s1")
        assert "source pin" in record.evidence

    def test_digest_field(self):
        """'digest' field maps to signature evidence."""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={"sbom_ref": "sbom", "provenance_ref": "p", "source_pin": "s", "digest": "sha256:abc"},
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        _resp = reg.register_candidate(req)
        record = reg.get_skill("s1")
        assert "signature" in record.evidence

    def test_signature_field(self):
        """'signature' field maps to signature evidence."""
        audit = _make_audit()
        reg = Registry(audit_layer=audit)
        meta = SkillMetadata(
            skill_id="s1", name="Test", version="1.0",
            security={"sbom_ref": "sbom", "provenance_ref": "p", "source_pin": "s", "signature": "sig-data"},
        )
        req = RegisterSkillRequest(skill_metadata=meta)
        _resp = reg.register_candidate(req)
        record = reg.get_skill("s1")
        assert "signature" in record.evidence
