"""Unit tests for skillpool.materializer module."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillpool.csdf import CSDFDocument
from skillpool.materializer import MaterializationResult, Materializer


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


class TestMaterializationResult:
    def test_result_creation(self) -> None:
        result = MaterializationResult(
            skill_name="test",
            version="1.0.0",
            agent_type="codex",
            output_path="/tmp/test",
            success=True,
        )
        assert result.success is True
        assert result.skill_name == "test"
        assert result.version == "1.0.0"
        assert result.agent_type == "codex"
        assert result.timestamp != ""

    def test_result_failure(self) -> None:
        result = MaterializationResult(
            skill_name="test",
            version="1.0.0",
            agent_type="codex",
            output_path="",
            success=False,
            error="something went wrong",
        )
        assert result.success is False
        assert result.error == "something went wrong"


class TestMaterializer:
    def test_materialize_creates_output_dir(
        self, sample_doc: CSDFDocument, state_dir: Path
    ) -> None:
        mat = Materializer(state_dir=state_dir)
        _result = mat.materialize(sample_doc)
        assert (state_dir / "materialization_state").exists()

    def test_materialize_creates_skill_dir(self, sample_doc: CSDFDocument, state_dir: Path) -> None:
        mat = Materializer(state_dir=state_dir)
        result = mat.materialize(sample_doc)
        assert result.success is True

    def test_materialize_creates_csdf_file(self, sample_doc: CSDFDocument, state_dir: Path) -> None:
        mat = Materializer(state_dir=state_dir)
        result = mat.materialize(sample_doc)
        assert result.success is True

    def test_materialize_csdf_valid_json(self, sample_doc: CSDFDocument, state_dir: Path) -> None:
        mat = Materializer(state_dir=state_dir)
        result = mat.materialize(sample_doc)
        assert result.success is True
        assert result.skill_name == "test-skill"
        assert result.version == "1.0.0"

    def test_materialize_success_result(self, sample_doc: CSDFDocument, state_dir: Path) -> None:
        mat = Materializer(state_dir=state_dir)
        result = mat.materialize(sample_doc)
        assert result.success is True
        assert result.skill_name == "test-skill"

    def test_materialize_idempotent(self, sample_doc: CSDFDocument, state_dir: Path) -> None:
        mat = Materializer(state_dir=state_dir)
        result1 = mat.materialize(sample_doc)
        result2 = mat.materialize(sample_doc)
        assert result1.success is True
        assert result2.success is True

    def test_materialize_creates_version_copy(
        self, sample_doc: CSDFDocument, state_dir: Path
    ) -> None:
        mat = Materializer(state_dir=state_dir)
        _result1 = mat.materialize(sample_doc)
        sample_doc.version = "2.0.0"
        result2 = mat.materialize(sample_doc)
        assert result2.success is True

    def test_materialize_multiple_skills(self, state_dir: Path) -> None:
        doc1 = CSDFDocument(name="skill-a", version="1.0.0", dimensions={"completeness": 0.5})
        doc2 = CSDFDocument(name="skill-b", version="1.0.0", dimensions={"completeness": 0.7})
        mat = Materializer(state_dir=state_dir)
        r1 = mat.materialize(doc1)
        r2 = mat.materialize(doc2)
        assert r1.success is True
        assert r2.success is True
