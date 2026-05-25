"""Unit tests for skillpool.materializer module — extended coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillpool.csdf import CSDFDocument
from skillpool.materializer import Materializer


@pytest.fixture
def sample_doc() -> CSDFDocument:
    return CSDFDocument(
        name="test-skill",
        version="1.0.0",
        dimensions={"completeness": 0.8, "accuracy": 0.7, "usability": 0.6, "maintainability": 0.9},
        dependencies=["base-skill"],
        metadata={"author": "test"},
    )


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


class TestMaterializerRollback:
    """Cover lines 138-153: rollback method."""

    def test_rollback_to_existing_version(self, sample_doc: CSDFDocument, state_dir: Path) -> None:
        mat = Materializer(state_dir=state_dir)
        mat.materialize(sample_doc)
        versions = mat.list_versions("test-skill", "codex")
        assert len(versions) > 0
        result = mat.rollback("test-skill", "codex", versions[0])
        assert result.success is True
        assert result.output_path != ""

    def test_rollback_nonexistent_version(self, state_dir: Path) -> None:
        mat = Materializer(state_dir=state_dir)
        result = mat.rollback("missing", "codex", "nonexistent_v1_20250101.md")
        assert result.success is False
        assert "not found" in result.error


class TestMaterializerListVersions:
    """Cover lines 97-98: list_versions with versions."""

    def test_list_versions_empty(self, state_dir: Path) -> None:
        mat = Materializer(state_dir=state_dir)
        versions = mat.list_versions("no-skill", "codex")
        assert versions == []

    def test_list_versions_after_materialize(
        self, sample_doc: CSDFDocument, state_dir: Path
    ) -> None:
        mat = Materializer(state_dir=state_dir)
        mat.materialize(sample_doc)
        versions = mat.list_versions("test-skill", "codex")
        assert len(versions) >= 1


class TestMaterializerTemplateError:
    """Cover lines 81-82: KeyError in template formatting."""

    def test_materialize_with_bad_template_key(
        self, sample_doc: CSDFDocument, state_dir: Path
    ) -> None:
        mat = Materializer(state_dir=state_dir)
        # Inject a template with a missing key to trigger KeyError path
        import skillpool.materializer as m

        original = m.AGENT_TEMPLATES.copy()
        m.AGENT_TEMPLATES["bad"] = "# {nonexistent_key}"
        try:
            result = mat.materialize(sample_doc, agent_type="bad")
            assert result.success is False
            assert "Template formatting error" in result.error
        finally:
            m.AGENT_TEMPLATES = original


class TestMaterializerWriteError:
    """Cover write error path."""

    def test_materialize_write_to_invalid_path(
        self, sample_doc: CSDFDocument, state_dir: Path
    ) -> None:
        mat = Materializer(state_dir=state_dir)
        # Use a path that cannot be written to (under /proc which is read-only)
        result = mat.materialize(sample_doc, output_path=Path("/proc/nonexistent/skill.md"))
        assert result.success is False
        assert "Write error" in result.error
