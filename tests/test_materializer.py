"""Unit tests for Materializer components: CSDFMapper, LifecycleFilter, BudgetCropper, and integration."""
from __future__ import annotations

import pytest

from skillpool.materializer.models import CSDFDocument, MaterializedSkill, MaterializationResult
from skillpool.materializer.mapper import CSDFMapper
from skillpool.materializer.lifecycle_filter import LifecycleFilter
from skillpool.materializer.budget_cropper import BudgetCropper
from skillpool.materializer import Materializer


# ============================================================
# Fixtures
# ============================================================

def _sample_csdf(**overrides) -> dict:
    """Build a minimal CSDF dict with sensible defaults."""
    base = {
        "id": "test-skill-001",
        "name": "Test Skill",
        "version": "1.0.0",
        "dimension": "D3",
        "weight": 0.8,
        "veto_rule": "score < 7.0 → reject",
        "description": "A test skill for unit testing.",
        "checklist": [
            {"item": "Check input types", "priority": "high"},
            {"item": "Verify output schema", "priority": "medium"},
            {"item": "Log execution time", "priority": "low"},
        ],
        "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
        "output_schema": {"type": "object", "properties": {"y": {"type": "string"}}},
        "version_history": [
            {"version": "0.1.0", "date": "2025-01-01", "changes": "Initial draft"},
            {"version": "1.0.0", "date": "2025-06-01", "changes": "Stable release"},
        ],
        "required_agent_capabilities": {"file_system"},
        "min_trust_level": 2,
        "paradigm": "testing",
        "lifecycle_state": "ACTIVE",
    }
    base.update(overrides)
    return base


# ============================================================
# CSDFMapper — 14 rules
# ============================================================

class TestCSDFMapper:
    """Test all 14 CSDF→SKILL.md mapping rules."""

    def setup_method(self):
        self.mapper = CSDFMapper()

    def test_r01_id_mapping(self):
        csdf = _sample_csdf(id="my-skill-42")
        md = self.mapper.map(csdf)
        assert "my-skill-42" in md

    def test_r02_name_mapping(self):
        csdf = _sample_csdf(name="My Cool Skill")
        md = self.mapper.map(csdf)
        assert "My Cool Skill" in md

    def test_r03_version_mapping(self):
        csdf = _sample_csdf(version="2.3.1")
        md = self.mapper.map(csdf)
        assert "2.3.1" in md

    def test_r04_dimension_mapping(self):
        csdf = _sample_csdf(dimension="D5")
        md = self.mapper.map(csdf)
        assert "D5" in md

    def test_r05_weight_mapping(self):
        csdf = _sample_csdf(weight=0.95)
        md = self.mapper.map(csdf)
        assert "0.95" in md

    def test_r06_veto_rule_mapping(self):
        csdf = _sample_csdf(veto_rule="score < 6.0 → reject")
        md = self.mapper.map(csdf)
        assert "score < 6.0" in md

    def test_r07_description_mapping(self):
        csdf = _sample_csdf(description="This is a detailed description.")
        md = self.mapper.map(csdf)
        assert "This is a detailed description." in md

    def test_r08_checklist_mapping(self):
        csdf = _sample_csdf()
        md = self.mapper.map(csdf)
        assert "Check input types" in md

    def test_r09_input_schema_mapping(self):
        csdf = _sample_csdf()
        md = self.mapper.map(csdf)
        assert "x" in md

    def test_r10_output_schema_mapping(self):
        csdf = _sample_csdf()
        md = self.mapper.map(csdf)
        assert "y" in md

    def test_r11_version_history_mapping(self):
        csdf = _sample_csdf()
        md = self.mapper.map(csdf)
        assert "0.1.0" in md or "1.0.0" in md

    def test_r12_required_capabilities_mapping(self):
        csdf = _sample_csdf(required_agent_capabilities={"file_system", "web_search"})
        md = self.mapper.map(csdf)
        assert "file_system" in md
        assert "web_search" in md

    def test_r13_min_trust_level_mapping(self):
        csdf = _sample_csdf(min_trust_level=3)
        md = self.mapper.map(csdf)
        assert "3" in md

    def test_r14_paradigm_mapping(self):
        csdf = _sample_csdf(paradigm="research")
        md = self.mapper.map(csdf)
        assert "research" in md

    def test_empty_csdf(self):
        """Mapping an empty dict should not crash."""
        md = self.mapper.map({})
        assert isinstance(md, str)

    def test_missing_optional_fields(self):
        """Fields like veto_rule, version_history can be empty."""
        csdf = {"id": "x", "name": "X", "version": "0.0.1", "dimension": "D1"}
        md = self.mapper.map(csdf)
        assert "X" in md


# ============================================================
# LifecycleFilter
# ============================================================

class TestLifecycleFilter:
    """Test lifecycle state filtering for all 9 states."""

    SAMPLE_MD = "# Test Skill\n\nThis is the content of the skill."

    def test_draft_adds_warning(self):
        f = LifecycleFilter(strict=True)
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "DRAFT"})
        assert "[DRAFT]" in result
        assert "开发中" in result
        assert "# Test Skill" in result

    def test_proposed_adds_draft_warning(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "PROPOSED"})
        assert "[DRAFT]" in result

    def test_under_review_adds_review_tag(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "UNDER_REVIEW"})
        assert "[REVIEW]" in result
        assert "审核中" in result

    def test_approved_no_change(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "APPROVED"})
        assert result == self.SAMPLE_MD

    def test_active_no_change(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "ACTIVE"})
        assert result == self.SAMPLE_MD

    def test_rejected_strict_clears_content(self):
        f = LifecycleFilter(strict=True)
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "REJECTED"})
        assert "[REJECTED]" in result
        assert "# Test Skill" not in result

    def test_rejected_non_strict_keeps_content(self):
        f = LifecycleFilter(strict=False)
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "REJECTED"})
        assert "[REJECTED]" in result
        assert "# Test Skill" in result

    def test_deprecated_adds_warning_and_replacement(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "DEPRECATED"})
        assert "[DEPRECATED]" in result
        assert "已弃用" in result
        assert "替代" in result
        assert "# Test Skill" in result

    def test_archived_strict_truncates(self):
        f = LifecycleFilter(strict=True)
        long_md = "# Title\n\n" + "x" * 500
        result = f.filter(long_md, {"lifecycle_state": "ARCHIVED"})
        assert "[ARCHIVED]" in result
        assert "已归档" in result
        assert len(result) < len(long_md)

    def test_archived_non_strict_keeps_content(self):
        f = LifecycleFilter(strict=False)
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "ARCHIVED"})
        assert "[ARCHIVED]" in result
        assert "# Test Skill" in result

    def test_removed_returns_empty(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "REMOVED"})
        assert result == ""

    def test_missing_lifecycle_defaults_to_active(self):
        """CSDF without lifecycle_state should default to ACTIVE."""
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {})
        assert result == self.SAMPLE_MD

    def test_invalid_state_defaults_to_active(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "UNKNOWN_STATE"})
        assert result == self.SAMPLE_MD

    def test_case_insensitive_state(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "draft"})
        assert "[DRAFT]" in result

    def test_mixed_case_state(self):
        f = LifecycleFilter()
        result = f.filter(self.SAMPLE_MD, {"lifecycle_state": "Draft"})
        assert "[DRAFT]" in result


# ============================================================
# BudgetCropper
# ============================================================

class TestBudgetCropper:
    """Test token budget cropping strategies."""

    def test_estimate_tokens(self):
        bc = BudgetCropper(max_tokens=4096)
        assert bc.estimate_tokens("a" * 100) == 25
        assert bc.estimate_tokens("") == 0

    def test_no_crop_when_under_budget(self):
        bc = BudgetCropper(max_tokens=4096)
        md = "# Hello\n\nShort content."
        result = bc.crop(md)
        assert result == md

    def test_remove_version_history(self):
        bc = BudgetCropper(max_tokens=10)
        md = "# Title\n\n## Description\n" + "x" * 100 + "\n\n## Version History\n- v0.1: init\n- v0.2: fix\n\n## Dimension\nD3"
        result = bc.crop(md)
        assert "Version History" not in result

    def test_remove_checklist_medium(self):
        bc = BudgetCropper(max_tokens=10)
        md = "# Title\n\n## Checklist\n- Item A [high]\n- Item B [medium]\n- Item C [low]\n"
        result = bc.crop(md)
        assert "[medium]" not in result

    def test_remove_checklist_low(self):
        bc = BudgetCropper(max_tokens=5)
        md = "# Title\n\n## Checklist\n- Item A [high]\n- Item B [low]\n"
        result = bc.crop(md)
        assert "[low]" not in result

    def test_truncate_description(self):
        bc = BudgetCropper(max_tokens=20)
        long_desc = "x" * 2000
        md = f"# Title\n\n## Description\n{long_desc}\n\n## Dimension\nD3"
        result = bc.crop(md)
        assert len(result) < len(md)

    def test_hard_truncate(self):
        bc = BudgetCropper(max_tokens=5)
        md = "# Title\n\n" + "y" * 5000
        result = bc.crop(md)
        assert len(result) < len(md)

    def test_crop_preserves_high_priority_sections(self):
        bc = BudgetCropper(max_tokens=100)
        md = (
            "# Skill Name\n\n"
            "## Dimension\nD3 Security\n\n"
            "## Weight\n0.9\n\n"
            "## Veto\nScore < 7.0 → reject\n\n"
            "## Version History\n- v1: init\n- v2: update\n- v3: patch\n\n"
            "## Description\n"
            + "Detailed description. " * 100
        )
        result = bc.crop(md)
        # High-priority sections should survive
        assert "Dimension" in result
        assert "Weight" in result or "0.9" in result

    def test_empty_input(self):
        bc = BudgetCropper()
        result = bc.crop("")
        assert result == ""


# ============================================================
# Materializer Integration
# ============================================================

class TestMaterializerIntegration:
    """End-to-end test: CSDF → SKILL.md via Materializer."""

    def _make_materializer(self, **kwargs):
        from skillpool.profile import CLAUDE_CODE_PROFILE
        return Materializer(profile=CLAUDE_CODE_PROFILE, **kwargs)

    def test_materialize_active_skill(self):
        mat = self._make_materializer()
        csdf = _sample_csdf(paradigm="code")  # CLAUDE_CODE_PROFILE supports "code"
        result = mat.materialize(csdf_dict=csdf)
        assert result.status == "success"
        assert result.skill is not None
        assert result.skill.name == "Test Skill"
        assert result.skill.markdown != ""

    def test_materialize_removed_skill(self):
        mat = self._make_materializer()
        csdf = _sample_csdf(lifecycle_state="REMOVED")
        result = mat.materialize(csdf_dict=csdf)
        # REMOVED should result in rejected or empty content
        assert result.status in ("rejected", "success")
        if result.skill:
            assert result.skill.markdown == "" or "REMOVED" in result.skill.markdown

    def test_materialize_with_budget(self):
        mat = self._make_materializer(context_budget=200)
        csdf = _sample_csdf(paradigm="code")
        result = mat.materialize(csdf_dict=csdf)
        assert result.status == "success"
        if result.skill:
            assert result.skill.token_count <= 200 or result.skill.markdown != ""

    def test_materialize_empty_csdf(self):
        mat = self._make_materializer()
        result = mat.materialize(csdf_dict={})
        # Should handle gracefully
        assert result.status in ("success", "error")

    def test_materialize_deprecated_skill(self):
        mat = self._make_materializer()
        csdf = _sample_csdf(lifecycle_state="DEPRECATED", paradigm="code")
        result = mat.materialize(csdf_dict=csdf)
        assert result.status == "success"
        if result.skill:
            assert "[DEPRECATED]" in result.skill.markdown or "DEPRECATED" in result.skill.markdown


# ============================================================
# CSDFMapper — Edge Cases & Additional Rules
# ============================================================

class TestCSDFMapperEdgeCases:
    """Additional edge-case coverage for CSDFMapper."""

    def setup_method(self):
        self.mapper = CSDFMapper()

    def test_r05_weight_zero(self):
        """Weight of 0.0 should still be rendered."""
        csdf = {"weight": 0.0}
        md = self.mapper.map(csdf)
        assert "0.0" in md

    def test_r06_veto_rule_none(self):
        """No veto_rule should produce no veto section."""
        csdf = {"id": "x"}
        md = self.mapper.map(csdf)
        assert "VETO" not in md

    def test_r08_checklist_with_id_and_severity(self):
        """Checklist items with 'id' and 'severity' format."""
        csdf = {
            "checklist": [
                {"id": "C1", "description": "Check auth", "severity": "high"},
            ]
        }
        md = self.mapper.map(csdf)
        assert "C1" in md
        assert "Check auth" in md
        assert "high" in md

    def test_r08_checklist_with_item_and_priority(self):
        """Checklist items with 'item' and 'priority' format."""
        csdf = {
            "checklist": [
                {"item": "Verify input", "priority": "low"},
            ]
        }
        md = self.mapper.map(csdf)
        assert "Verify input" in md
        assert "low" in md

    def test_r09_input_schema_required_optional_dict(self):
        """Input schema with required/optional dict format."""
        csdf = {
            "input_schema": {
                "required": {"x": "integer input"},
                "optional": {"y": "optional flag"},
            }
        }
        md = self.mapper.map(csdf)
        assert "Required" in md
        assert "Optional" in md
        assert "x" in md

    def test_r09_input_schema_required_optional_list(self):
        """Input schema with required/optional list format."""
        csdf = {
            "input_schema": {
                "required": ["field_a", "field_b"],
            }
        }
        md = self.mapper.map(csdf)
        assert "field_a" in md

    def test_r10_output_schema_empty(self):
        """Empty output_schema should produce no section."""
        csdf = {"output_schema": {}}
        md = self.mapper.map(csdf)
        # The mapper only adds section if schema is truthy
        # Empty dict is falsy-ish but the code checks `if not schema`
        assert "Output Schema" not in md

    def test_r11_version_history_with_non_string_changes(self):
        """Version history entries with non-string changes."""
        csdf = {
            "version_history": [
                {"version": "1.0.0", "date": "2025-01-01", "changes": ["Added feature", "Fixed bug"]},
            ]
        }
        md = self.mapper.map(csdf)
        assert "1.0.0" in md
        assert "Added feature" in md

    def test_r12_capabilities_as_list(self):
        """required_agent_capabilities as list should be handled."""
        csdf = {"required_agent_capabilities": ["bash", "python"]}
        md = self.mapper.map(csdf)
        assert "bash" in md
        assert "python" in md

    def test_r12_capabilities_empty_set(self):
        """Empty required_agent_capabilities should produce no section."""
        csdf = {"required_agent_capabilities": set()}
        md = self.mapper.map(csdf)
        assert "Required Capabilities" not in md

    def test_r13_trust_level_zero(self):
        """min_trust_level of 0 should not produce a section."""
        csdf = {"min_trust_level": 0}
        md = self.mapper.map(csdf)
        assert "Min Trust Level" not in md

    def test_r14_paradigm_none(self):
        """None paradigm should produce no section."""
        csdf = {"paradigm": None}
        md = self.mapper.map(csdf)
        assert "Paradigm" not in md

    def test_map_returns_trailing_newline(self):
        """map() should always return a string ending with newline."""
        csdf = {"id": "test"}
        md = self.mapper.map(csdf)
        assert md.endswith("\n")


# ============================================================
# LifecycleFilter — Additional Edge Cases
# ============================================================

class TestLifecycleFilterEdgeCases:
    """Additional edge-case coverage for LifecycleFilter."""

    def test_empty_markdown_with_active(self):
        f = LifecycleFilter()
        result = f.filter("", {"lifecycle_state": "ACTIVE"})
        assert result == ""

    def test_rejected_non_strict_preserves_warning_prefix(self):
        f = LifecycleFilter(strict=False)
        result = f.filter("content", {"lifecycle_state": "REJECTED"})
        assert result.startswith(">")

    def test_archived_strict_short_content_no_truncation_marker(self):
        """Content under 200 chars should not get truncation marker."""
        f = LifecycleFilter(strict=True)
        result = f.filter("short", {"lifecycle_state": "ARCHIVED"})
        assert "[ARCHIVED]" in result
        assert "内容已截断" not in result

    def test_archived_strict_long_content_has_truncation_marker(self):
        """Content over 200 chars should get truncation marker."""
        f = LifecycleFilter(strict=True)
        long_content = "x" * 300
        result = f.filter(long_content, {"lifecycle_state": "ARCHIVED"})
        assert "[ARCHIVED]" in result
        assert "内容已截断" in result

    def test_all_lifecycle_states_produce_string(self):
        """Every valid lifecycle state should return a string, never raise."""
        f = LifecycleFilter()
        for state in ["DRAFT", "PROPOSED", "UNDER_REVIEW", "APPROVED",
                       "ACTIVE", "REJECTED", "DEPRECATED", "ARCHIVED", "REMOVED"]:
            result = f.filter("test content", {"lifecycle_state": state})
            assert isinstance(result, str)

    def test_deprecated_includes_replacement_text(self):
        f = LifecycleFilter()
        result = f.filter("content", {"lifecycle_state": "DEPRECATED"})
        assert "替代方案" in result or "替代" in result

    def test_removed_always_empty(self):
        """REMOVED state returns empty regardless of input."""
        f = LifecycleFilter()
        result = f.filter("some content that should be erased", {"lifecycle_state": "REMOVED"})
        assert result == ""


# ============================================================
# BudgetCropper — Additional Edge Cases
# ============================================================

class TestBudgetCropperEdgeCases:
    """Additional edge-case coverage for BudgetCropper."""

    def test_estimate_tokens_single_char(self):
        bc = BudgetCropper()
        assert bc.estimate_tokens("a") == 0

    def test_estimate_tokens_four_chars(self):
        bc = BudgetCropper()
        assert bc.estimate_tokens("abcd") == 1

    def test_remove_checklist_with_paren_format(self):
        """Checklist items using (medium) instead of [medium]."""
        bc = BudgetCropper(max_tokens=5)
        md = "# Title\n\n### Checklist\n- Item A (high)\n- Item B (medium)\n- Item C (low)\n"
        result = bc.crop(md)
        assert "(medium)" not in result

    def test_remove_checklist_priority_colon_format(self):
        """Checklist items using 'priority: medium' format."""
        bc = BudgetCropper(max_tokens=5)
        md = "# Title\n\n### Checklist\n- Item A priority: high\n- Item B priority: medium\n"
        result = bc.crop(md)
        assert "priority: medium" not in result

    def test_hard_truncate_finds_newline_cut_point(self):
        """Hard truncate should prefer cutting at a newline if near the end."""
        bc = BudgetCropper(max_tokens=5)
        # Build content where last newline is in the last 20% of max_chars
        md = "x" * 50 + "\n" + "y" * 10
        result = bc.crop(md)
        assert len(result) < len(md)

    def test_crop_with_only_version_history(self):
        """Content that is just version history should be removable."""
        bc = BudgetCropper(max_tokens=5)
        md = "### Version History\n\n**0.1.0** (2025-01-01)\n  - init\n  - draft\n"
        result = bc.crop(md)
        # Version history should be removed
        assert len(result) < len(md)

    def test_max_tokens_one(self):
        """Very small budget should still produce output without crash."""
        bc = BudgetCropper(max_tokens=1)
        md = "# Title\n\nSome content here."
        result = bc.crop(md)
        assert isinstance(result, str)


# ============================================================
# Materializer — Additional Integration & Error Paths
# ============================================================

class TestMaterializerErrorPaths:
    """Error paths and rejection scenarios in Materializer."""

    def _make_materializer(self, **kwargs):
        from skillpool.profile import CLAUDE_CODE_PROFILE
        return Materializer(profile=CLAUDE_CODE_PROFILE, **kwargs)

    def test_materialize_no_input_raises(self):
        """Calling materialize with no csdf_path and no csdf_dict should raise."""
        mat = self._make_materializer()
        with pytest.raises(ValueError, match="必须提供"):
            mat.materialize()

    def test_materialize_capability_mismatch_rejected(self):
        """Skill requiring capability not in profile should be rejected."""
        from skillpool.profile import AgentCapabilityProfile
        # Minimal profile with no capabilities
        profile = AgentCapabilityProfile(
            name="minimal",
            required_capabilities=set(),
            trust_level=0,
            supported_paradigms=set(),
        )
        mat = Materializer(profile=profile)
        csdf = _sample_csdf(
            required_agent_capabilities={"super_advanced_capability"},
            paradigm="research",
        )
        result = mat.materialize(csdf_dict=csdf)
        assert result.status == "rejected"
        assert "capability mismatch" in result.errors[0]

    def test_materialize_trust_level_mismatch_rejected(self):
        """Skill requiring higher trust level than profile should be rejected."""
        from skillpool.profile import AgentCapabilityProfile
        profile = AgentCapabilityProfile(
            name="low-trust",
            trust_level=1,
            supported_paradigms={"code"},
        )
        mat = Materializer(profile=profile)
        csdf = _sample_csdf(min_trust_level=3, paradigm="code")
        result = mat.materialize(csdf_dict=csdf)
        assert result.status == "rejected"

    def test_materialize_paradigm_mismatch_rejected(self):
        """Skill requiring unsupported paradigm should be rejected."""
        from skillpool.profile import AgentCapabilityProfile
        profile = AgentCapabilityProfile(
            name="code-only",
            supported_paradigms={"code"},
        )
        mat = Materializer(profile=profile)
        csdf = _sample_csdf(paradigm="research")
        result = mat.materialize(csdf_dict=csdf)
        assert result.status == "rejected"

    def test_materialize_batch(self):
        """Batch materialization should return one result per path."""
        mat = self._make_materializer()
        csdf = _sample_csdf(paradigm="code")
        # Use csdf_dict for batch via individual materialize calls
        results = [mat.materialize(csdf_dict=csdf) for _ in range(3)]
        assert len(results) == 3
        assert all(r.status == "success" for r in results)

    def test_materialize_result_has_token_count(self):
        """Successful materialize should include token_count on the skill."""
        mat = self._make_materializer()
        csdf = _sample_csdf(paradigm="code")
        result = mat.materialize(csdf_dict=csdf)
        assert result.status == "success"
        assert result.skill is not None
        assert isinstance(result.skill.token_count, int)

    def test_materialize_csdf_with_minimal_fields(self):
        """CSDF with only id and name should still materialize."""
        mat = self._make_materializer()
        csdf = {"id": "minimal", "name": "Min", "paradigm": "code"}
        result = mat.materialize(csdf_dict=csdf)
        assert result.status == "success"
        assert result.skill.id == "minimal"

    def test_materialize_strict_lifecycle_false(self):
        """Non-strict lifecycle should keep content for REJECTED skills."""
        mat = self._make_materializer(strict_lifecycle=False)
        csdf = _sample_csdf(lifecycle_state="REJECTED", paradigm="code")
        result = mat.materialize(csdf_dict=csdf)
        # Non-strict should keep the content (with warning)
        if result.skill:
            assert "[REJECTED]" in result.skill.markdown


# ============================================================
# CSDFDocument Model Tests
# ============================================================

class TestCSDFDocumentModel:
    """Test CSDFDocument Pydantic model."""

    def test_defaults(self):
        doc = CSDFDocument()
        assert doc.id == ""
        assert doc.version == "0.0.0"
        assert doc.min_trust_level == 0
        assert doc.checklist == []
        assert doc.required_agent_capabilities == set()

    def test_with_fields(self):
        doc = CSDFDocument(
            id="S09",
            name="Resilience",
            version="1.2.0",
            dimension="D5",
            weight=0.8,
            veto_rule="score < 7.0",
        )
        assert doc.id == "S09"
        assert doc.weight == 0.8

    def test_materialized_skill_model(self):
        skill = MaterializedSkill(
            id="S01",
            name="Test",
            version="1.0.0",
            markdown="# Test\n",
            token_count=10,
        )
        assert skill.id == "S01"
        assert skill.token_count == 10

    def test_materialization_result_success(self):
        result = MaterializationResult(
            status="success",
            skill=MaterializedSkill(id="S01", name="T"),
            errors=[],
        )
        assert result.status == "success"
        assert result.skill is not None

    def test_materialization_result_rejected(self):
        result = MaterializationResult(
            status="rejected",
            skill=None,
            errors=["capability mismatch"],
        )
        assert result.status == "rejected"
        assert result.skill is None
        assert len(result.errors) == 1
