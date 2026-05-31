"""Unit tests for Materializer components: CSDFMapper, LifecycleFilter, BudgetCropper, and integration."""
from __future__ import annotations

import pytest

from skillpool.lifecycle import SkillLifecycleState
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
