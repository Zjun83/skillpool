"""Tests for changelog auto-append mechanism."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from skillpool.utils.changelog import (
    VALID_CATEGORIES,
    _detect_current_version,
    _find_or_create_category,
    _find_version_section_end,
    append_changelog_entry,
)


@pytest.fixture
def sample_changelog(tmp_path: Path) -> Path:
    """Create a sample CHANGELOG.md for testing."""
    content = """# Changelog

All notable changes to this project are documented in this file.

---

## [4.2.0] - 2026-05-31

### Added
- **New feature**: Something was added (2026-05-30)

### Fixed
- **Bug fix**: Something was fixed (2026-05-29)

---

## [4.1.0] - 2026-05-26

### Added
- **Old feature**: Something old (2026-05-25)

[4.2.0]: https://example.com/v4.2.0
[4.1.0]: https://example.com/v4.1.0
"""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(content, encoding="utf-8")
    return changelog_path


@pytest.fixture
def changelog_no_categories(tmp_path: Path) -> Path:
    """Create a CHANGELOG.md with version but no category subsections."""
    content = """# Changelog

## [1.0.0] - 2026-01-01

Some description without proper subsections.

[1.0.0]: https://example.com/v1.0.0
"""
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(content, encoding="utf-8")
    return changelog_path


class TestDetectCurrentVersion:
    """Tests for _detect_current_version."""

    def test_detects_first_version(self, sample_changelog: Path):
        content = sample_changelog.read_text(encoding="utf-8")
        version = _detect_current_version(content)
        assert version == "4.2.0"

    def test_returns_none_for_no_version(self, tmp_path: Path):
        content = "# Changelog\n\nNo versions here.\n"
        version = _detect_current_version(content)
        assert version is None

    def test_detects_version_with_prerelease(self, tmp_path: Path):
        content = "## [5.0.0-alpha.1] - 2026-06-01\n"
        version = _detect_current_version(content)
        # Only matches X.Y.Z format
        assert version == "5.0.0" or version is None


class TestFindVersionSectionEnd:
    """Tests for _find_version_section_end."""

    def test_finds_next_version(self, sample_changelog: Path):
        content = sample_changelog.read_text(encoding="utf-8")
        end = _find_version_section_end(content, "4.2.0")
        lines = content.split("\n")
        # Should point to the line with "## [4.1.0]"
        assert end is not None
        assert "## [4.1.0]" in lines[end]

    def test_returns_len_for_last_version(self, sample_changelog: Path):
        content = sample_changelog.read_text(encoding="utf-8")
        end = _find_version_section_end(content, "4.1.0")
        assert end == len(content.split("\n"))

    def test_returns_none_for_missing_version(self, sample_changelog: Path):
        content = sample_changelog.read_text(encoding="utf-8")
        end = _find_version_section_end(content, "9.9.9")
        assert end is None


class TestFindOrCreateCategory:
    """Tests for _find_or_create_category."""

    def test_finds_existing_category(self, sample_changelog: Path):
        content = sample_changelog.read_text(encoding="utf-8")
        lines = content.split("\n")

        # Find version section
        section_start = None
        for i, line in enumerate(lines):
            if "## [4.2.0]" in line:
                section_start = i
                break

        section_end = _find_version_section_end(content, "4.2.0")

        insert_at = _find_or_create_category(lines, section_start, section_end, "Fixed")

        # Should be after the existing Fixed entry
        assert insert_at > section_start
        assert insert_at < section_end

    def test_returns_insert_point_for_missing_category(self, sample_changelog: Path):
        content = sample_changelog.read_text(encoding="utf-8")
        lines = content.split("\n")

        section_start = None
        for i, line in enumerate(lines):
            if "## [4.2.0]" in line:
                section_start = i
                break

        section_end = _find_version_section_end(content, "4.2.0")

        insert_at = _find_or_create_category(lines, section_start, section_end, "Security")

        # Should return a valid position within the section
        assert insert_at > section_start
        assert insert_at <= section_end


class TestAppendChangelogEntry:
    """Tests for append_changelog_entry."""

    def test_appends_to_existing_category(self, sample_changelog: Path):
        append_changelog_entry(
            category="Fixed",
            description="Another bug fix",
            changelog_path=sample_changelog,
        )

        content = sample_changelog.read_text(encoding="utf-8")
        assert "Another bug fix" in content

        # Verify it's under the Fixed section
        lines = content.split("\n")
        fixed_section = False
        found_entry = False
        for line in lines:
            if "### Fixed" in line:
                fixed_section = True
            elif line.startswith("### ") and fixed_section:
                fixed_section = False
            elif fixed_section and "Another bug fix" in line:
                found_entry = True
                break

        assert found_entry

    def test_creates_new_category(self, sample_changelog: Path):
        append_changelog_entry(
            category="Security",
            description="Fixed vulnerability",
            changelog_path=sample_changelog,
        )

        content = sample_changelog.read_text(encoding="utf-8")
        assert "### Security" in content
        assert "Fixed vulnerability" in content

    def test_appends_with_details(self, sample_changelog: Path):
        append_changelog_entry(
            category="Added",
            description="New API endpoint",
            details={"endpoint": "/api/v2/test", "method": "POST"},
            changelog_path=sample_changelog,
        )

        content = sample_changelog.read_text(encoding="utf-8")
        assert "New API endpoint" in content
        assert "endpoint=/api/v2/test" in content
        assert "method=POST" in content

    def test_includes_date(self, sample_changelog: Path):
        from datetime import date

        today = date.today().isoformat()

        append_changelog_entry(
            category="Changed",
            description="Updated behavior",
            changelog_path=sample_changelog,
        )

        content = sample_changelog.read_text(encoding="utf-8")
        assert today in content

    def test_raises_for_invalid_category(self, sample_changelog: Path):
        with pytest.raises(ValueError, match="Invalid category"):
            append_changelog_entry(
                category="InvalidCategory",
                description="Test",
                changelog_path=sample_changelog,
            )

    def test_raises_for_missing_changelog(self, tmp_path: Path):
        missing_path = tmp_path / "MISSING.md"
        with pytest.raises(FileNotFoundError):
            append_changelog_entry(
                category="Fixed",
                description="Test",
                changelog_path=missing_path,
            )

    def test_raises_for_no_version_section(self, tmp_path: Path):
        no_version = tmp_path / "CHANGELOG.md"
        no_version.write_text("# Changelog\n\nNo versions.\n", encoding="utf-8")

        with pytest.raises(ValueError, match="No version section"):
            append_changelog_entry(
                category="Fixed",
                description="Test",
                changelog_path=no_version,
            )

    def test_works_with_no_existing_categories(self, changelog_no_categories: Path):
        append_changelog_entry(
            category="Added",
            description="First feature",
            changelog_path=changelog_no_categories,
        )

        content = changelog_no_categories.read_text(encoding="utf-8")
        assert "### Added" in content
        assert "First feature" in content

    def test_preserves_existing_content(self, sample_changelog: Path):
        _original_content = sample_changelog.read_text(encoding="utf-8")

        append_changelog_entry(
            category="Fixed",
            description="New fix",
            changelog_path=sample_changelog,
        )

        new_content = sample_changelog.read_text(encoding="utf-8")

        # All original content should still be present
        assert "## [4.1.0]" in new_content
        assert "Old feature" in new_content
        assert "[4.2.0]:" in new_content
        assert "[4.1.0]:" in new_content

        # New content should be added
        assert "New fix" in new_content


class TestValidCategories:
    """Tests for VALID_CATEGORIES constant."""

    def test_contains_all_keep_a_changelog_categories(self):
        expected = {"Added", "Fixed", "Changed", "Deprecated", "Removed", "Security"}
        assert expected == VALID_CATEGORIES


class TestEntryFormat:
    """Tests for the format of generated entries."""

    def test_entry_format_matches_pattern(self, sample_changelog: Path):
        append_changelog_entry(
            category="Fixed",
            description="Test entry format",
            changelog_path=sample_changelog,
        )

        content = sample_changelog.read_text(encoding="utf-8")

        # Entry should match: - **Description**: details (date)
        pattern = r"- \*\*Test entry format\*\*: \(\d{4}-\d{2}-\d{2}\)"
        assert re.search(pattern, content), f"Pattern not found in: {content}"

    def test_entry_format_with_details(self, sample_changelog: Path):
        append_changelog_entry(
            category="Added",
            description="Feature with details",
            details={"key1": "value1", "key2": "value2"},
            changelog_path=sample_changelog,
        )

        content = sample_changelog.read_text(encoding="utf-8")

        # Entry should include details
        pattern = r"- \*\*Feature with details\*\*: \(key1=value1 key2=value2\) \(\d{4}-\d{2}-\d{2}\)"
        assert re.search(pattern, content), f"Pattern not found in: {content}"
