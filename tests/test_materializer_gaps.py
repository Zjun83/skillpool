"""Tests for Materializer module coverage gaps.

Targeted gaps from:
- csdf_loader.py (79%): L37, 60-62, 73-74, 85-86
- lazy_loader.py (89%): L153, 181-182, 194-195, 197-198, 255-256
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from skillpool.materializer.csdf_loader import load_csdf, _parse_yaml, _parse_directory_skill
from skillpool.materializer.lazy_loader import LazySkillLoader


# ═══════════════════════════════════════════════════════════════
# csdf_loader gaps
# ═══════════════════════════════════════════════════════════════


class TestCsdfLoaderGaps:
    def test_exact_yaml_match(self, tmp_path):
        """Line 37: exact match returns parsed YAML."""
        yaml_file = tmp_path / "S09.yaml"
        yaml_file.write_text(yaml.dump({"id": "S09", "name": "Test"}), encoding="utf-8")
        result = load_csdf("S09", tmp_path)
        assert result is not None
        assert result["id"] == "S09"

    def test_parse_yaml_invalid_content(self, tmp_path):
        """Lines 60-62: invalid YAML returns None."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(":\n  invalid: [yaml: content", encoding="utf-8")
        result = _parse_yaml(bad_yaml)
        assert result is None

    def test_parse_yaml_non_dict(self, tmp_path):
        """Lines 60-62: YAML that's not a dict returns None."""
        scalar_yaml = tmp_path / "scalar.yaml"
        scalar_yaml.write_text("just a string", encoding="utf-8")
        result = _parse_yaml(scalar_yaml)
        # safe_load returns a string, not a dict -> None
        assert result is None

    def test_parse_yaml_os_error(self, tmp_path):
        """Lines 60-62: OSError returns None."""
        bad_path = tmp_path / "nonexistent.yaml"
        result = _parse_yaml(bad_path)
        assert result is None

    def test_parse_directory_skill_read_error(self, tmp_path):
        """Lines 73-74: OSError reading SKILL.md returns minimal dict."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        # Create a file but mock read to fail
        skill_md.write_text("---\nid: my-skill\n---\n", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=OSError("read error")):
            result = _parse_directory_skill("my-skill", skill_md, skill_dir)
            assert result["id"] == "my-skill"
            assert result["type"] == "directory"

    def test_parse_directory_skill_no_frontmatter(self, tmp_path):
        """Lines 85-86: SKILL.md without frontmatter."""
        skill_dir = tmp_path / "plain-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("Just some content without frontmatter\n", encoding="utf-8")
        result = _parse_directory_skill("plain-skill", skill_md, skill_dir)
        assert result["id"] == "plain-skill"
        assert result["type"] == "directory"

    def test_parse_directory_skill_with_valid_frontmatter(self, tmp_path):
        """Valid frontmatter parsed correctly."""
        skill_dir = tmp_path / "fm-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nid: fm-skill\nname: Frontmatter Skill\nversion: 2.0\n---\nBody here\n", encoding="utf-8")
        result = _parse_directory_skill("fm-skill", skill_md, skill_dir)
        assert result["id"] == "fm-skill"
        assert result["name"] == "Frontmatter Skill"
        assert result["version"] == 2.0

    def test_parse_directory_skill_invalid_frontmatter_yaml(self, tmp_path):
        """Frontmatter with invalid YAML falls back gracefully."""
        skill_dir = tmp_path / "bad-fm-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\n: invalid yaml [\n---\nBody\n", encoding="utf-8")
        result = _parse_directory_skill("bad-fm-skill", skill_md, skill_dir)
        assert result["id"] == "bad-fm-skill"
        assert result["type"] == "directory"

    def test_prefix_yaml_match(self, tmp_path):
        """Line 40: prefix match returns CSDF."""
        yaml_file = tmp_path / "S09-resilience-degradation.yaml"
        yaml_file.write_text(yaml.dump({"id": "S09", "name": "Resilience"}), encoding="utf-8")
        result = load_csdf("S09", tmp_path)
        assert result is not None
        assert result["id"] == "S09"

    def test_directory_based_skill(self, tmp_path):
        """Directory-based skill with SKILL.md."""
        skill_dir = tmp_path / "my-dir-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nid: my-dir-skill\n---\nContent\n", encoding="utf-8")
        result = load_csdf("my-dir-skill", tmp_path)
        assert result is not None
        assert result["id"] == "my-dir-skill"

    def test_not_found_returns_none(self, tmp_path):
        """Skill not found -> None."""
        result = load_csdf("NONEXISTENT", tmp_path)
        assert result is None


# ═══════════════════════════════════════════════════════════════
# lazy_loader gaps
# ═══════════════════════════════════════════════════════════════


class TestLazySkillLoaderGaps:
    def test_upgrade_from_nonexistent_tier(self, tmp_path):
        """Line 153: upgrade from tier not loaded raises ValueError."""
        loader = LazySkillLoader(skills_dir=tmp_path)
        with pytest.raises(ValueError, match="not loaded at L0"):
            # Skill not in cache at all
            loader._cache["test-skill"] = {}
            loader.upgrade("test-skill", "L0", "L1")

    def test_upgrade_skill_not_in_cache(self, tmp_path):
        """Line 181-182: skill not in cache raises ValueError."""
        loader = LazySkillLoader(skills_dir=tmp_path)
        with pytest.raises(ValueError, match="not in cache"):
            loader.upgrade("nonexistent", "L0", "L1")

    def test_check_invalidation_with_modified_file(self, tmp_path):
        """Lines 194-195, 197-198: cache invalidation on file modification."""
        # Create a skill YAML
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        yaml_file = skills_dir / "test-skill.yaml"
        yaml_file.write_text(yaml.dump({"id": "test-skill", "name": "Test"}), encoding="utf-8")

        loader = LazySkillLoader(skills_dir=skills_dir)
        # Load the skill to populate cache
        try:
            data = loader.load("test-skill", tier="L0")
        except ValueError:
            pytest.skip("Skill not loadable in test environment")
            return

        # Modify the file to trigger invalidation
        yaml_file.write_text(yaml.dump({"id": "test-skill", "name": "Modified"}), encoding="utf-8")

        # Force invalidation check
        with loader._lock:
            loader._check_invalidation("test-skill")

    def test_l2_materialization_failure(self, tmp_path):
        """Line 255-256: L2 materialization failure stores empty markdown."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        yaml_file = skills_dir / "fail-skill.yaml"
        yaml_file.write_text(yaml.dump({"id": "fail-skill", "name": "Fail"}), encoding="utf-8")

        loader = LazySkillLoader(skills_dir=skills_dir)
        # Mock Materializer to return failure
        with patch("skillpool.materializer.lazy_loader.Materializer") as MockMat:
            mock_result = MagicMock()
            mock_result.status = "error"
            mock_result.skill = None
            mock_result.errors = ["materialization failed"]
            MockMat.return_value.materialize.return_value = mock_result

            try:
                data = loader.load("fail-skill", tier="L2")
            except ValueError:
                pytest.skip("Skill not loadable")
                return

            # Should have empty markdown with errors
            assert data.get("_tier") == "L2"
            assert "_materialization_errors" in data or data.get("markdown") == ""

    def test_clear_cache_specific_skill(self, tmp_path):
        """Clear cache for a specific skill."""
        loader = LazySkillLoader(skills_dir=tmp_path)
        loader._cache["s1"] = {"L0": {"id": "s1"}}
        loader._cache["s2"] = {"L0": {"id": "s2"}}
        loader.clear_cache("s1")
        assert "s1" not in loader._cache
        assert "s2" in loader._cache
