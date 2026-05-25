"""Unit tests for CSDF parser."""

from pathlib import Path

import pytest

from skillpool.csdf import CSDFDocument, CSDFParser

VALID_SKILL_MD = """---
name: test-skill
version: 1.0.0
description: A test skill
triggers:
  - test
  - unit test
dimensions:
  completeness: 0.8
  accuracy: 0.9
  usability: 0.7
  maintainability: 0.85
references:
  - docs/guide.md
---

# Test Skill

This is the body of the test skill.
It has multiple lines.
"""

MINIMAL_SKILL_MD = """---
name: minimal-skill
---

Minimal body.
"""


class TestCSDFParser:
    """Tests for CSDFParser."""

    def setup_method(self):
        self.parser = CSDFParser()

    def test_parse_valid_document(self):
        doc = self.parser.parse(VALID_SKILL_MD, source_path="/test/skill.md")
        assert doc.name == "test-skill"
        assert doc.version == "1.0.0"
        assert doc.description == "A test skill"
        assert "test" in doc.triggers
        assert "unit test" in doc.triggers
        assert doc.dimensions["completeness"] == 0.8
        assert doc.dimensions["accuracy"] == 0.9
        assert "docs/guide.md" in doc.references
        assert "Test Skill" in doc.body
        assert doc.source_path == "/test/skill.md"
        assert len(doc.content_hash) == 16

    def test_parse_minimal_document(self):
        doc = self.parser.parse(MINIMAL_SKILL_MD)
        assert doc.name == "minimal-skill"
        assert doc.version == "0.1.0"
        assert doc.description == ""
        assert doc.triggers == []
        assert doc.dimensions == {}
        assert doc.references == []
        assert "Minimal body" in doc.body

    def test_parse_no_frontmatter_raises(self):
        with pytest.raises(ValueError, match="No valid YAML frontmatter"):
            self.parser.parse("No frontmatter here")

    def test_parse_invalid_yaml_raises(self):
        bad_yaml = "---\n: invalid: yaml: [\n---\nbody"
        with pytest.raises(ValueError, match="Invalid YAML"):
            self.parser.parse(bad_yaml)

    def test_parse_missing_name_raises(self):
        no_name = "---\ndescription: no name\n---\nbody"
        with pytest.raises(ValueError, match="name"):
            self.parser.parse(no_name)

    def test_parse_file(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(VALID_SKILL_MD, encoding="utf-8")
        doc = self.parser.parse_file(skill_file)
        assert doc.name == "test-skill"
        assert doc.source_path == str(skill_file)

    def test_parse_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            self.parser.parse_file(Path("/nonexistent/SKILL.md"))

    def test_content_hash_deterministic(self):
        doc1 = self.parser.parse(VALID_SKILL_MD)
        doc2 = self.parser.parse(VALID_SKILL_MD)
        assert doc1.content_hash == doc2.content_hash

    def test_content_hash_differs_for_different_content(self):
        doc1 = self.parser.parse(VALID_SKILL_MD)
        doc2 = self.parser.parse(MINIMAL_SKILL_MD)
        assert doc1.content_hash != doc2.content_hash

    def test_references_string_converted_to_list(self):
        single_ref = "---\nname: test\nreferences: single.md\n---\nbody"
        doc = self.parser.parse(single_ref)
        assert doc.references == ["single.md"]


class TestCSDFDocument:
    """Tests for CSDFDocument validation."""

    def test_valid_dimensions(self):
        doc = CSDFDocument(
            name="test",
            dimensions={"completeness": 0.5, "accuracy": 1.0},
        )
        assert doc.dimensions["completeness"] == 0.5

    def test_invalid_dimension_value_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            CSDFDocument(
                name="test",
                dimensions={"completeness": 1.5},
            )

    def test_negative_dimension_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            CSDFDocument(
                name="test",
                dimensions={"accuracy": -0.1},
            )

    def test_invalid_version_raises(self):
        with pytest.raises(ValueError, match="major.minor"):
            CSDFDocument(name="test", version="1")

    def test_valid_version(self):
        doc = CSDFDocument(name="test", version="2.3.1")
        assert doc.version == "2.3.1"


class TestCSDFValidator:
    """Tests for CSDFParser.validate."""

    def setup_method(self):
        self.parser = CSDFParser()

    def test_validate_complete_document(self):
        doc = self.parser.parse(VALID_SKILL_MD)
        issues = self.parser.validate(doc)
        assert len(issues) == 0

    def test_validate_missing_description(self):
        doc = self.parser.parse(MINIMAL_SKILL_MD)
        issues = self.parser.validate(doc)
        assert any("description" in i for i in issues)

    def test_validate_missing_triggers(self):
        doc = self.parser.parse(MINIMAL_SKILL_MD)
        issues = self.parser.validate(doc)
        assert any("triggers" in i for i in issues)

    def test_validate_missing_dimensions(self):
        doc = self.parser.parse(MINIMAL_SKILL_MD)
        issues = self.parser.validate(doc)
        assert any("dimensions" in i for i in issues)
