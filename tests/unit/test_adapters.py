"""Tests for SkillPool Agent Adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillpool.adapters.base import AgentAdapter
from skillpool.adapters.claude_adapter import ClaudeAdapter
from skillpool.adapters.codex_adapter import CodexAdapter
from skillpool.csdf import CSDFDocument


@pytest.fixture
def sample_doc() -> CSDFDocument:
    return CSDFDocument(
        name="test-skill",
        version="1.0.0",
        description="A test skill",
        triggers=["when testing", "on demand"],
        body="1. Do the thing\n2. Check the result",
        dimensions={
            "completeness": 0.9,
            "accuracy": 0.8,
            "usability": 0.7,
            "maintainability": 0.85,
        },
    )


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / ".skillpool"


@pytest.fixture
def codex_adapter(state_dir: Path) -> CodexAdapter:
    return CodexAdapter(state_dir=state_dir)


@pytest.fixture
def claude_adapter(state_dir: Path) -> ClaudeAdapter:
    return ClaudeAdapter(state_dir=state_dir)


class TestCodexAdapter:
    def test_render_skill(self, codex_adapter: CodexAdapter, sample_doc: CSDFDocument):
        rendered = codex_adapter.render_skill(sample_doc)
        assert "# test-skill" in rendered
        assert "## Triggers" in rendered
        assert "## Instructions" in rendered
        assert "- when testing" in rendered

    def test_install_skill(
        self, codex_adapter: CodexAdapter, sample_doc: CSDFDocument, tmp_path: Path
    ):
        target = tmp_path / "codex_skills"
        target.mkdir()
        result = codex_adapter.install_skill(sample_doc, target)
        assert result.success
        assert Path(result.output_path).exists()

    def test_verify_skill_exists(
        self, codex_adapter: CodexAdapter, sample_doc: CSDFDocument, tmp_path: Path
    ):
        target = tmp_path / "codex_skills"
        target.mkdir()
        codex_adapter.install_skill(sample_doc, target)
        assert codex_adapter.verify_skill("test-skill", target)

    def test_verify_skill_not_exists(self, codex_adapter: CodexAdapter, tmp_path: Path):
        target = tmp_path / "codex_skills"
        target.mkdir()
        assert not codex_adapter.verify_skill("nonexistent", target)


class TestClaudeAdapter:
    def test_render_skill(self, claude_adapter: ClaudeAdapter, sample_doc: CSDFDocument):
        rendered = claude_adapter.render_skill(sample_doc)
        assert "# test-skill" in rendered
        assert "### When to use" in rendered
        assert "### Instructions" in rendered

    def test_install_skill(
        self, claude_adapter: ClaudeAdapter, sample_doc: CSDFDocument, tmp_path: Path
    ):
        target = tmp_path / "claude_skills"
        target.mkdir()
        result = claude_adapter.install_skill(sample_doc, target)
        assert result.success
        assert Path(result.output_path).exists()

    def test_verify_skill(
        self, claude_adapter: ClaudeAdapter, sample_doc: CSDFDocument, tmp_path: Path
    ):
        target = tmp_path / "claude_skills"
        target.mkdir()
        claude_adapter.install_skill(sample_doc, target)
        assert claude_adapter.verify_skill("test-skill", target)


class TestAdapterBase:
    def test_cannot_instantiate_base(self):
        with pytest.raises(TypeError):
            AgentAdapter()
