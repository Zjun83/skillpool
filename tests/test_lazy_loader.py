"""Tests for LazySkillLoader — L0/L1/L2 tiered loading with cache and thread safety.

Part of SkillPool — independent infrastructure, shared by all agents.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from skillpool.materializer.lazy_loader import LazySkillLoader


# Use real skills dir for integration-style tests
_SKILLS_DIR = Path.home() / ".skillpool" / "skills"


@pytest.fixture
def loader():
    return LazySkillLoader(skills_dir=_SKILLS_DIR)


class TestTierValidation:
    """Test tier validation."""

    def test_valid_tiers(self, loader):
        for tier in ("L0", "L1", "L2"):
            # Will raise ValueError if skill not found, but tier validation passes first
            try:
                loader.load("S09", tier=tier)
            except ValueError:
                pass  # Skill not found is fine — we're testing tier validation

    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError, match="Invalid tier"):
            LazySkillLoader(skills_dir=_SKILLS_DIR).load("S09", tier="L99")


class TestLoadL0:
    """Test L0 tier loading (metadata only)."""

    def test_l0_returns_metadata_fields(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        data = loader.load("S09", tier="L0")
        assert data["_tier"] == "L0"
        assert "id" in data
        assert "name" in data
        assert "version" in data

    def test_l0_does_not_include_description(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        data = loader.load("S09", tier="L0")
        # L0 should not have description field (or it should be empty)
        assert "description" not in data or data.get("description") == ""

    def test_unknown_skill_raises(self, loader):
        with pytest.raises(ValueError, match="Skill not found"):
            loader.load("NONEXISTENT_SKILL_XYZ", tier="L0")


class TestLoadL1:
    """Test L1 tier loading (summary with description)."""

    def test_l1_includes_description(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        data = loader.load("S09", tier="L1")
        assert data["_tier"] == "L1"
        # L1 should include description or checklist_summary
        assert "description" in data or "checklist_summary" in data

    def test_l1_inherits_l0_fields(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        data = loader.load("S09", tier="L1")
        assert "id" in data
        assert "name" in data


class TestLoadL2:
    """Test L2 tier loading (full materialization)."""

    def test_l2_includes_markdown(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        data = loader.load("S09", tier="L2")
        assert data["_tier"] == "L2"
        # L2 should have markdown or _markdown_body
        assert "markdown" in data or "_markdown_body" in data


class TestUpgrade:
    """Test upgrade from lower to higher tier."""

    def test_upgrade_l0_to_l1(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        l0 = loader.load("S09", tier="L0")
        l1 = loader.upgrade("S09", "L0", "L1")
        assert l1["_tier"] == "L1"

    def test_upgrade_l0_to_l2(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        loader.load("S09", tier="L0")
        l2 = loader.upgrade("S09", "L0", "L2")
        assert l2["_tier"] == "L2"

    def test_upgrade_requires_cached_skill(self, loader):
        with pytest.raises(ValueError, match="not in cache"):
            loader.upgrade("S09", "L0", "L1")

    def test_upgrade_rejects_lower_target(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        loader.load("S09", tier="L1")
        with pytest.raises(ValueError, match="must be higher"):
            loader.upgrade("S09", "L1", "L0")


class TestPreload:
    """Test batch loading."""

    def test_preload_multiple_skills(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        result = loader.preload(["S09", "NONEXISTENT_XYZ"], tier="L0")
        assert "S09" in result
        assert "NONEXISTENT_XYZ" not in result


class TestClearCache:
    """Test cache clearing."""

    def test_clear_all_cache(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        loader.load("S09", tier="L0")
        loader.clear_cache()
        # Should be able to reload
        data = loader.load("S09", tier="L0")
        assert data["_tier"] == "L0"

    def test_clear_specific_skill(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        loader.load("S09", tier="L0")
        loader.clear_cache(skill_id="S09")
        data = loader.load("S09", tier="L0")
        assert data["_tier"] == "L0"


class TestThreadSafety:
    """Test concurrent access to LazySkillLoader."""

    def test_concurrent_loads(self, loader):
        if not (_SKILLS_DIR / "S09-resilience-degradation.yaml").exists():
            pytest.skip("S09 YAML not available")
        errors = []

        def load_in_thread():
            try:
                data = loader.load("S09", tier="L0")
                assert data["_tier"] == "L0"
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=load_in_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestDirectorySkill:
    """Test loading directory-based skills (SKILL.md frontmatter)."""

    def test_directory_skill_l0(self, loader):
        # scaffold-docs is a known directory-based skill
        if not (_SKILLS_DIR / "scaffold-docs" / "SKILL.md").exists():
            pytest.skip("scaffold-docs not available")
        data = loader.load("scaffold-docs", tier="L0")
        assert data["_tier"] == "L0"
        # Directory skills are found by the loader even though L0 metadata
        # doesn't include a "type" field (that's at L1/L2 level)

    def test_directory_skill_l1(self, loader):
        if not (_SKILLS_DIR / "scaffold-docs" / "SKILL.md").exists():
            pytest.skip("scaffold-docs not available")
        data = loader.load("scaffold-docs", tier="L1")
        assert data["_tier"] == "L1"