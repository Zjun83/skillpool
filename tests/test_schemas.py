"""Tests for CSDF schema validators."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from skillpool.schemas import (
    CSDFSkill,
    ChecklistItem,
    SkillDimension,
    validate_csdf,
    validate_csdf_file,
)


# --- Fixtures ---


@pytest.fixture
def valid_csdf_dict() -> dict:
    """A minimal valid CSDF skill dictionary."""
    return {
        "id": "S05a",
        "name": "Security Transport Layer",
        "version": "9.0.0",
        "dimension": "D3",
        "weight": 0.148,
        "veto_rule": "V1: D3 < 7.0 -> block",
        "description": "Check transport layer security compliance.",
        "checklist": [
            {"id": "S05a-C01", "description": "TLS 1.3+ required", "severity": "critical"},
            {"id": "S05a-C02", "description": "mTLS enabled", "severity": "high"},
        ],
    }


@pytest.fixture
def valid_csdf_yaml(tmp_path: Path) -> Path:
    """Write a valid CSDF YAML file and return its path."""
    yaml_path = tmp_path / "S05a-test.yaml"
    yaml_path.write_text(
        """
id: S05a
name: "Security Transport Layer"
version: "9.0.0"
dimension: "D3"
weight: 0.148
veto_rule: "V1: D3 < 7.0 -> block"
description: |
  Check transport layer security compliance.
checklist:
  - id: S05a-C01
    description: "TLS 1.3+ required"
    severity: critical
  - id: S05a-C02
    description: "mTLS enabled"
    severity: high
""",
        encoding="utf-8",
    )
    return yaml_path


# --- Tests for ChecklistItem ---


class TestChecklistItem:
    def test_valid_checklist_item(self) -> None:
        item = ChecklistItem(id="C01", description="Test item", severity="critical")
        assert item.id == "C01"
        assert item.severity == "critical"

    def test_all_severities_allowed(self) -> None:
        for sev in ("critical", "high", "medium", "low"):
            item = ChecklistItem(id="C01", description="Test", severity=sev)
            assert item.severity == sev

    def test_invalid_severity_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ChecklistItem(id="C01", description="Test", severity="urgent")
        assert "severity must be one of" in str(exc_info.value)


# --- Tests for CSDFSkill ---


class TestCSDFSkill:
    def test_valid_csdf_passes(self, valid_csdf_dict: dict) -> None:
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        assert skill.id == "S05a"
        assert skill.version == "9.0.0"
        assert skill.dimension == SkillDimension.D3
        assert skill.weight == 0.148
        assert len(skill.checklist) == 2

    def test_missing_required_field_raises(self, valid_csdf_dict: dict) -> None:
        del valid_csdf_dict["id"]
        with pytest.raises(ValidationError) as exc_info:
            CSDFSkill.model_validate(valid_csdf_dict)
        assert "id" in str(exc_info.value).lower()

    def test_missing_name_raises(self, valid_csdf_dict: dict) -> None:
        del valid_csdf_dict["name"]
        with pytest.raises(ValidationError) as exc_info:
            CSDFSkill.model_validate(valid_csdf_dict)
        assert "name" in str(exc_info.value).lower()

    def test_invalid_dimension_raises(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["dimension"] = "D99"
        with pytest.raises(ValidationError) as exc_info:
            CSDFSkill.model_validate(valid_csdf_dict)
        assert "dimension" in str(exc_info.value).lower()

    def test_dimension_all_allowed(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["dimension"] = "ALL"
        valid_csdf_dict["weight"] = None
        valid_csdf_dict["veto_rule"] = None
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        assert skill.dimension == SkillDimension.ALL

    def test_invalid_version_format_raises(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["version"] = "9.0"  # Missing patch
        with pytest.raises(ValidationError) as exc_info:
            CSDFSkill.model_validate(valid_csdf_dict)
        assert "semver" in str(exc_info.value).lower()

    def test_version_with_prerelease_rejected(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["version"] = "9.0.0-alpha"
        with pytest.raises(ValidationError):
            CSDFSkill.model_validate(valid_csdf_dict)

    def test_weight_out_of_range_high_raises(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["weight"] = 1.5
        with pytest.raises(ValidationError) as exc_info:
            CSDFSkill.model_validate(valid_csdf_dict)
        assert "weight" in str(exc_info.value).lower()

    def test_weight_out_of_range_low_raises(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["weight"] = -0.1
        with pytest.raises(ValidationError):
            CSDFSkill.model_validate(valid_csdf_dict)

    def test_weight_null_allowed(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["weight"] = None
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        assert skill.weight is None

    def test_veto_rule_null_allowed(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["veto_rule"] = None
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        assert skill.veto_rule is None

    def test_optional_dependencies_and_conflicts(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["dependencies"] = ["S01", "S02"]
        valid_csdf_dict["conflicts"] = ["S99"]
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        assert skill.dependencies == ["S01", "S02"]
        assert skill.conflicts == ["S99"]

    def test_empty_checklist_allowed(self, valid_csdf_dict: dict) -> None:
        valid_csdf_dict["checklist"] = []
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        assert skill.checklist == []


# --- Tests for validate_csdf function ---


class TestValidateCsdf:
    def test_validate_csdf_returns_skill(self, valid_csdf_dict: dict) -> None:
        skill = validate_csdf(valid_csdf_dict)
        assert isinstance(skill, CSDFSkill)
        assert skill.id == "S05a"

    def test_validate_csdf_raises_on_invalid(self) -> None:
        with pytest.raises(ValidationError):
            validate_csdf({})


# --- Tests for validate_csdf_file function ---


class TestValidateCsdfFile:
    def test_validate_csdf_file_valid_yaml(self, valid_csdf_yaml: Path) -> None:
        skill = validate_csdf_file(valid_csdf_yaml)
        assert skill.id == "S05a"
        assert skill.version == "9.0.0"
        assert len(skill.checklist) == 2

    def test_validate_csdf_file_missing_raises(self, tmp_path: Path) -> None:
        missing_path = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            validate_csdf_file(missing_path)

    def test_validate_csdf_file_invalid_yaml_content(self, tmp_path: Path) -> None:
        bad_yaml = tmp_path / "invalid.yaml"
        bad_yaml.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Expected a YAML mapping"):
            validate_csdf_file(bad_yaml)

    def test_validate_csdf_file_schema_error(self, tmp_path: Path) -> None:
        bad_schema = tmp_path / "bad_schema.yaml"
        bad_schema.write_text(
            """
id: S99
name: "Missing required fields"
""",
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            validate_csdf_file(bad_schema)


# --- Tests for validate_contract method (lines 67-85) ---


class TestValidateContract:
    """Tests for CSDFSkill.validate_contract() — GovernSpec contract validation.

    Note: Pydantic validates types at model construction time, so the isinstance
    checks in validate_contract() (lines 69-70, 72-73, 80-81) are defensive.
    To reach those lines, we use model_construct() which bypasses Pydantic
    validation and sets fields directly.
    """

    def _make_skill_via_construct(self, **overrides) -> CSDFSkill:
        """Build a CSDFSkill via model_construct to bypass Pydantic validation.

        This allows setting fields to types that Pydantic would reject,
        which is needed to test the isinstance guards in validate_contract().
        """
        defaults = {
            "id": "S99",
            "name": "Test Skill",
            "version": "1.0.0",
            "dimension": SkillDimension.D3,
            "description": "A test skill.",
            "checklist": [],
            "permissions": [],
            "boundaries": [],
            "verification_steps": [],
        }
        defaults.update(overrides)
        return CSDFSkill.model_construct(**defaults)

    # --- Permissions type check (lines 68-70) ---

    def test_validate_contract_valid_permissions(self, valid_csdf_dict: dict) -> None:
        """Valid string permissions should return no errors."""
        valid_csdf_dict["permissions"] = ["read:files", "write:files"]
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert all("permissions" not in e for e in errors)

    def test_validate_contract_empty_permissions(self, valid_csdf_dict: dict) -> None:
        """Empty permissions list should return no errors."""
        valid_csdf_dict["permissions"] = []
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert all("permissions" not in e for e in errors)

    def test_validate_contract_invalid_permission_type(self) -> None:
        """Non-string permission should produce error (lines 69-70)."""
        # Use model_construct to bypass Pydantic type enforcement
        skill = self._make_skill_via_construct(permissions=["valid", 123, None])
        errors = skill.validate_contract()
        perm_errors = [e for e in errors if "permissions" in e]
        assert len(perm_errors) == 2
        assert any("permissions[1]" in e and "expected str" in e and "int" in e for e in perm_errors)
        assert any("permissions[2]" in e and "expected str" in e and "NoneType" in e for e in perm_errors)

    # --- Boundaries type check (lines 71-74) ---

    def test_validate_contract_empty_boundaries(self, valid_csdf_dict: dict) -> None:
        """Empty boundaries list should return no errors."""
        valid_csdf_dict["boundaries"] = []
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert all("boundaries" not in e for e in errors)

    def test_validate_contract_valid_boundaries(self, valid_csdf_dict: dict) -> None:
        """Valid boundaries with type and value keys should return no errors."""
        valid_csdf_dict["boundaries"] = [
            {"type": "path", "value": "/tmp"},
            {"type": "network", "value": "localhost:8080"},
        ]
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert all("boundaries" not in e for e in errors)

    def test_validate_contract_boundary_not_dict(self) -> None:
        """Non-dict boundary should produce error and skip key checks (lines 72-74)."""
        skill = self._make_skill_via_construct(boundaries=["not a dict", 123])
        errors = skill.validate_contract()
        boundary_errors = [e for e in errors if "boundaries" in e]
        assert len(boundary_errors) == 2
        assert any("boundaries[0]" in e and "expected dict" in e and "str" in e for e in boundary_errors)
        assert any("boundaries[1]" in e and "expected dict" in e and "int" in e for e in boundary_errors)

    # --- Boundaries missing keys (lines 75-78) ---

    def test_validate_contract_boundary_missing_type(self, valid_csdf_dict: dict) -> None:
        """Boundary missing 'type' key should produce error (lines 75-76)."""
        valid_csdf_dict["boundaries"] = [{"value": "/tmp"}]  # Missing 'type'
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert any("boundaries[0]" in e and "missing 'type'" in e for e in errors)

    def test_validate_contract_boundary_missing_value(self, valid_csdf_dict: dict) -> None:
        """Boundary missing 'value' key should produce error (lines 77-78)."""
        valid_csdf_dict["boundaries"] = [{"type": "path"}]  # Missing 'value'
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert any("boundaries[0]" in e and "missing 'value'" in e for e in errors)

    def test_validate_contract_boundary_missing_both_keys(self, valid_csdf_dict: dict) -> None:
        """Boundary missing both keys should produce two errors."""
        valid_csdf_dict["boundaries"] = [{}]  # Empty dict — valid to Pydantic but fails contract
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        boundary_errors = [e for e in errors if "boundaries[0]" in e]
        assert len(boundary_errors) == 2
        assert any("missing 'type'" in e for e in boundary_errors)
        assert any("missing 'value'" in e for e in boundary_errors)

    # --- Verification steps type check (lines 79-82) ---

    def test_validate_contract_empty_verification_steps(self, valid_csdf_dict: dict) -> None:
        """Empty verification_steps list should return no errors."""
        valid_csdf_dict["verification_steps"] = []
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert all("verification_steps" not in e for e in errors)

    def test_validate_contract_valid_verification_steps(self, valid_csdf_dict: dict) -> None:
        """Valid verification_steps with 'check' key should return no errors."""
        valid_csdf_dict["verification_steps"] = [
            {"check": "verify_tls_version"},
            {"check": "check_certificate_expiry", "args": {"days": 30}},
        ]
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert all("verification_steps" not in e for e in errors)

    def test_validate_contract_verification_step_not_dict(self) -> None:
        """Non-dict verification_step should produce error and skip key check (lines 80-82)."""
        skill = self._make_skill_via_construct(verification_steps=["not a dict", None])
        errors = skill.validate_contract()
        step_errors = [e for e in errors if "verification_steps" in e]
        assert len(step_errors) == 2
        assert any("verification_steps[0]" in e and "expected dict" in e and "str" in e for e in step_errors)
        assert any("verification_steps[1]" in e and "expected dict" in e and "NoneType" in e for e in step_errors)

    # --- Verification steps missing check key (lines 83-85) ---

    def test_validate_contract_verification_step_missing_check(self, valid_csdf_dict: dict) -> None:
        """Verification step missing 'check' key should produce error (lines 83-85)."""
        valid_csdf_dict["verification_steps"] = [{"action": "do_something"}]  # Missing 'check'
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert any("verification_steps[0]" in e and "missing 'check'" in e for e in errors)

    # --- Combined / integration tests ---

    def test_validate_contract_multiple_errors(self) -> None:
        """Multiple contract violations should all be reported."""
        # Use model_construct for type violations; use Pydantic for key violations
        skill = self._make_skill_via_construct(
            permissions=[123],
            boundaries=[{}],  # Missing both keys
            verification_steps=["invalid"],
        )
        errors = skill.validate_contract()
        assert len(errors) == 4  # 1 perm + 2 boundary + 1 verification
        assert any("permissions[0]" in e for e in errors)
        assert any("boundaries[0]" in e and "missing 'type'" in e for e in errors)
        assert any("boundaries[0]" in e and "missing 'value'" in e for e in errors)
        assert any("verification_steps[0]" in e for e in errors)

    def test_validate_contract_returns_empty_list_for_valid_contract(self, valid_csdf_dict: dict) -> None:
        """A fully valid contract should return an empty error list."""
        valid_csdf_dict["permissions"] = ["read:all", "write:temp"]
        valid_csdf_dict["boundaries"] = [
            {"type": "path", "value": "/tmp"},
            {"type": "memory", "value": "512MB"},
        ]
        valid_csdf_dict["verification_steps"] = [
            {"check": "verify_permissions"},
            {"check": "check_boundaries"},
        ]
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert errors == []

    def test_validate_contract_mixed_valid_and_invalid(self, valid_csdf_dict: dict) -> None:
        """Mix of valid and invalid entries should report only the invalid ones."""
        # Only test key-level issues through Pydantic validation
        valid_csdf_dict["permissions"] = ["valid", "also_valid"]
        valid_csdf_dict["boundaries"] = [
            {"type": "path", "value": "/tmp"},  # Valid
            {"type": "network"},  # Missing value
        ]
        valid_csdf_dict["verification_steps"] = [
            {"check": "step1"},  # Valid
            {"action": "step2"},  # Missing check
        ]
        skill = CSDFSkill.model_validate(valid_csdf_dict)
        errors = skill.validate_contract()
        assert len(errors) == 2
        assert any("boundaries[1]" in e and "missing 'value'" in e for e in errors)
        assert any("verification_steps[1]" in e and "missing 'check'" in e for e in errors)


# --- Integration test with real skill file ---


def _skills_dir_accessible() -> bool:
    """Check if /root/.skillpool/skills is accessible (not in CI)."""
    try:
        return Path("/root/.skillpool/skills").is_dir()
    except PermissionError:
        return False


class TestRealSkillFiles:
    @pytest.mark.skipif(
        not _skills_dir_accessible(),
        reason="Real skill files not available (CI environment)",
    )
    def test_validate_real_s05a_yaml(self) -> None:
        """Validate an actual skill file from the skills directory."""
        skill_path = Path("/root/.skillpool/skills/S05a-security-transport.yaml")
        if skill_path.exists():
            skill = validate_csdf_file(skill_path)
            assert skill.id == "S05a"
            assert skill.dimension == SkillDimension.D3
            assert skill.weight is not None
            assert 0 < skill.weight <= 1

    @pytest.mark.skipif(
        not _skills_dir_accessible(),
        reason="Real skill files not available (CI environment)",
    )
    def test_validate_real_s10_yaml(self) -> None:
        """Validate S10 which has version 9.1.0."""
        skill_path = Path("/root/.skillpool/skills/S10-recovery-mttr.yaml")
        if skill_path.exists():
            skill = validate_csdf_file(skill_path)
            assert skill.id == "S10"
            assert skill.version == "9.1.0"
            assert skill.dimension == SkillDimension.D5

    @pytest.mark.skipif(
        not _skills_dir_accessible(),
        reason="Real skill files not available (CI environment)",
    )
    def test_validate_real_s00_yaml(self) -> None:
        """Validate S00 orchestrator with dimension=ALL and weight=null."""
        skill_path = Path("/root/.skillpool/skills/S00-orchestrator.yaml")
        if skill_path.exists():
            skill = validate_csdf_file(skill_path)
            assert skill.id == "S00"
            assert skill.dimension == SkillDimension.ALL
            assert skill.weight is None
            assert skill.veto_rule is None
