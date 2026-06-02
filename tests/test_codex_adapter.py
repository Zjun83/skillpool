"""Tests for CodexAdapter including on_startup hook."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skillpool.adapters.codex_adapter import CodexAdapter
from skillpool.csdf import CSDFDocument


class TestCodexAdapterRender:
    """Tests for CodexAdapter.render_skill."""

    def test_render_skill_with_triggers(self):
        doc = CSDFDocument(name="test-skill", triggers=["on code review", "on commit"])
        adapter = CodexAdapter()
        rendered = adapter.render_skill(doc)
        assert "# test-skill" in rendered
        assert "## Triggers" in rendered
        assert "- on code review" in rendered
        assert "## Instructions" in rendered

    def test_render_skill_no_triggers(self):
        doc = CSDFDocument(name="test-skill", triggers=[])
        adapter = CodexAdapter()
        rendered = adapter.render_skill(doc)
        assert "- (none)" in rendered


class TestCodexAdapterVerify:
    """Tests for CodexAdapter.verify_skill."""

    def test_verify_existing_skill(self, tmp_path: Path):
        skill_file = tmp_path / "test-skill.md"
        skill_file.write_text("# test-skill")
        adapter = CodexAdapter()
        assert adapter.verify_skill("test-skill", tmp_path) is True

    def test_verify_missing_skill(self, tmp_path: Path):
        adapter = CodexAdapter()
        assert adapter.verify_skill("nonexistent", tmp_path) is False

    def test_verify_empty_skill(self, tmp_path: Path):
        skill_file = tmp_path / "empty.md"
        skill_file.write_text("")
        adapter = CodexAdapter()
        assert adapter.verify_skill("empty", tmp_path) is False


class TestCodexAdapterOnStartup:
    """Tests for CodexAdapter.on_startup hook."""

    def test_startup_no_skills_dir(self, tmp_path: Path):
        """Returns empty when skills dir doesn't exist."""
        adapter = CodexAdapter()
        adapter._skills_dir = tmp_path / "nonexistent"
        results = adapter.on_startup(target_dir=tmp_path / "output")
        assert results == {}

    def test_startup_empty_skills_dir(self, tmp_path: Path):
        """Returns empty when skills dir is empty."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        adapter = CodexAdapter()
        adapter._skills_dir = skills_dir
        results = adapter.on_startup(target_dir=tmp_path / "output")
        assert results == {}

    def test_startup_skips_skill_graph(self, tmp_path: Path):
        """Skips skill_graph.yaml when scanning."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "skill_graph.yaml").write_text("nodes: []")
        adapter = CodexAdapter()
        adapter._skills_dir = skills_dir
        results = adapter.on_startup(target_dir=tmp_path / "output")
        assert results == {}

    def test_startup_installs_skill(self, tmp_path: Path):
        """Installs a skill from CSDF YAML."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        output_dir = tmp_path / "output"

        # Create a minimal CSDF YAML
        (skills_dir / "S09-resilience.yaml").write_text(
            "name: resilience-skill\nversion: '1.0'\ndescription: test\ntriggers: []\n"
        )

        adapter = CodexAdapter()
        adapter._skills_dir = skills_dir

        with patch("skillpool.materializer.csdf_loader.load_csdf") as mock_load:
            mock_load.return_value = {
                "name": "resilience-skill",
                "version": "1.0",
                "description": "test",
                "triggers": [],
            }
            results = adapter.on_startup(target_dir=output_dir)

        assert results == {"S09": True}
        # Verify file was written
        assert (output_dir / "resilience-skill.md").exists()

    def test_startup_handles_install_failure(self, tmp_path: Path):
        """Handles write failure gracefully."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        output_dir = tmp_path / "output"

        (skills_dir / "S05a-security.yaml").write_text("name: security\nversion: '1.0'\n")

        adapter = CodexAdapter()
        adapter._skills_dir = skills_dir

        with patch("skillpool.materializer.csdf_loader.load_csdf") as mock_load:
            mock_load.return_value = {
                "name": "security",
                "version": "1.0",
                "description": "",
                "triggers": [],
            }
            # Make write_text fail
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                results = adapter.on_startup(target_dir=output_dir)

        assert results == {"S05a": False}

    def test_startup_handles_load_exception(self, tmp_path: Path):
        """Handles load_csdf exception gracefully."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        output_dir = tmp_path / "output"

        (skills_dir / "S10-recovery.yaml").write_text("name: recovery\nversion: '1.0'\n")

        adapter = CodexAdapter()
        adapter._skills_dir = skills_dir

        with patch("skillpool.materializer.csdf_loader.load_csdf") as mock_load:
            mock_load.side_effect = OSError("read error")
            results = adapter.on_startup(target_dir=output_dir)

        assert results == {"S10": False}

    def test_startup_skips_none_csdf(self, tmp_path: Path):
        """Skips skills where load_csdf returns None."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        output_dir = tmp_path / "output"

        (skills_dir / "S00-core.yaml").write_text("name: core\nversion: '1.0'\n")

        adapter = CodexAdapter()
        adapter._skills_dir = skills_dir

        with patch("skillpool.materializer.csdf_loader.load_csdf") as mock_load:
            mock_load.return_value = None
            results = adapter.on_startup(target_dir=output_dir)

        assert results == {}

    def test_startup_default_target_dir(self, tmp_path: Path):
        """Uses ~/.codex/skills as default target."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        adapter = CodexAdapter()
        adapter._skills_dir = skills_dir

        with patch.object(Path, "home", return_value=tmp_path):
            results = adapter.on_startup()

        # Should have created ~/.codex/skills/
        assert (tmp_path / ".codex" / "skills").exists()
