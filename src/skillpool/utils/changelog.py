"""Changelog utilities — auto-append entries to CHANGELOG.md.

Reads the project CHANGELOG.md, finds the current version section,
and appends structured entries under the appropriate category subsection.

Categories: Added, Fixed, Changed, Deprecated, Removed, Security
"""

from __future__ import annotations

__all__ = ["append_changelog_entry"]

import re
from datetime import date
from pathlib import Path

# Default changelog path
_CHANGELOG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "CHANGELOG.md"

# Valid categories (Keep a Changelog standard)
VALID_CATEGORIES = frozenset(
    {
        "Added",
        "Fixed",
        "Changed",
        "Deprecated",
        "Removed",
        "Security",
    }
)


def _detect_current_version(content: str) -> str | None:
    """Detect the current (most recent) version from CHANGELOG content.

    Looks for the first '## [X.Y.Z]' header.

    Args:
        content: Full CHANGELOG.md content.

    Returns:
        Version string (e.g., '4.2.0') or None if not found.
    """
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", content, re.MULTILINE)
    return match.group(1) if match else None


def _find_version_section_end(content: str, version: str) -> int | None:
    """Find the line index where the next version section starts.

    Args:
        content: Full CHANGELOG.md content split into lines.
        version: Version string to find.

    Returns:
        Line index of the next version header, or len(lines) if last section.
    """
    lines = content.split("\n")
    found_current = False
    for i, line in enumerate(lines):
        if re.match(rf"^## \[{re.escape(version)}\]", line):
            found_current = True
            continue
        if found_current and re.match(r"^## \[", line):
            return i
    return len(lines) if found_current else None


def _find_or_create_category(
    lines: list[str],
    section_start: int,
    section_end: int,
    category: str,
) -> int:
    """Find the line index where a category subsection starts, or determine
    where to insert it.

    Args:
        lines: CHANGELOG.md split into lines.
        section_start: Line index of the version header.
        section_end: Line index of the next version header (or len(lines)).
        category: Category name (e.g., 'Fixed').

    Returns:
        Line index where entries for this category should be appended.
        If the category subsection exists, returns the line after its last entry.
        If not, returns the line where the subsection header should be inserted.
    """
    category_header = f"### {category}"

    # Search for existing category subsection within the version section
    category_start = None
    next_category_start = None

    for i in range(section_start, section_end):
        if lines[i].strip() == category_header:
            category_start = i
            break

    if category_start is not None:
        # Found the category — find where it ends (next ### or ## or end of section)
        for i in range(category_start + 1, section_end):
            if re.match(r"^### ", lines[i]) or re.match(r"^## ", lines[i]):
                next_category_start = i
                break

        if next_category_start is not None:
            # Find the last non-empty line before the next subsection
            insert_at = next_category_start
            for i in range(next_category_start - 1, category_start, -1):
                if lines[i].strip():
                    insert_at = i + 1
                    break
            return insert_at
        else:
            # Category is the last subsection — append at end of section
            insert_at = section_end
            for i in range(section_end - 1, category_start, -1):
                if lines[i].strip():
                    insert_at = i + 1
                    break
            return insert_at
    else:
        # Category doesn't exist — insert after the version header
        # Find the first ### or non-empty line after the version header
        insert_at = section_start + 1
        for i in range(section_start + 1, section_end):
            stripped = lines[i].strip()
            if stripped.startswith("### ") or stripped.startswith("#### "):
                insert_at = i
                break
            if stripped and not stripped.startswith("---"):
                insert_at = i
                break

        return insert_at


def append_changelog_entry(
    category: str,
    description: str,
    details: dict | None = None,
    changelog_path: Path | str | None = None,
) -> None:
    """Append a structured entry to CHANGELOG.md under current version section.

    Categories: Added, Fixed, Changed, Deprecated, Removed, Security

    Writes a single line entry with timestamp and auto-detection of current version.

    Args:
        category: Changelog category (Added, Fixed, Changed, etc.).
        description: Short description of the change.
        details: Optional dict with additional context. If provided, rendered
                 as key=value pairs in the entry.
        changelog_path: Override for CHANGELOG.md path (default: project root).

    Raises:
        ValueError: If category is not a valid Keep a Changelog category.
        FileNotFoundError: If CHANGELOG.md does not exist.
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}")

    path = Path(changelog_path) if changelog_path else _CHANGELOG_PATH

    if not path.exists():
        raise FileNotFoundError(f"CHANGELOG.md not found at {path}")

    content = path.read_text(encoding="utf-8")
    version = _detect_current_version(content)

    if version is None:
        raise ValueError("No version section found in CHANGELOG.md")

    lines = content.split("\n")

    # Find the version section boundaries
    section_start = None
    for i, line in enumerate(lines):
        if re.match(rf"^## \[{re.escape(version)}\]", line):
            section_start = i
            break

    if section_start is None:
        raise ValueError(f"Version section [{version}] not found in CHANGELOG.md")

    section_end = _find_version_section_end(content, version)
    if section_end is None:
        section_end = len(lines)

    # Find where to insert the entry
    insert_at = _find_or_create_category(lines, section_start, section_end, category)

    # Build the entry line
    today = date.today().isoformat()
    details_str = ""
    if details:
        details_str = " ".join(f"{k}={v}" for k, v in details.items())
        details_str = f" ({details_str})"

    entry_line = f"- **{description}**:{details_str} ({today})"

    # Check if the category subsection header needs to be created
    category_header = f"### {category}"
    category_exists = any(lines[i].strip() == category_header for i in range(section_start, section_end))

    if category_exists:
        # Just insert the entry line
        lines.insert(insert_at, entry_line)
    else:
        # Insert category header + blank line + entry
        lines.insert(insert_at, entry_line)
        lines.insert(insert_at, "")
        lines.insert(insert_at, category_header)

    # Write back
    path.write_text("\n".join(lines), encoding="utf-8")
