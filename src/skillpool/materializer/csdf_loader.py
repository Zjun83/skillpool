"""Shared CSDF loading utility for SkillPool MCP and LazySkillLoader.

Extracted from mcp_server.py and lazy_loader.py to eliminate code
duplication. Both modules use this single implementation.

Part of SkillPool — independent infrastructure, shared by all agents.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_csdf(
    skill_id: str,
    skills_dir: Path,
) -> dict[str, Any] | None:
    """Load CSDF data for a skill by ID.

    Tries three lookup strategies in order:
    1. Exact YAML match: {skills_dir}/{skill_id}.yaml
    2. Prefix YAML match: {skills_dir}/{skill_id}_*.yaml
    3. Directory-based: {skills_dir}/{skill_id}/SKILL.md

    Args:
        skill_id: Skill identifier (e.g., "S09", "scaffold-docs").
        skills_dir: Path to the skills directory.

    Returns:
        Dict with CSDF data, or None if not found.
    """
    # 1. Exact match
    exact = skills_dir / f"{skill_id}.yaml"
    if exact.exists():
        return _parse_yaml(exact)

    # 2. Prefix match (e.g., S09-resilience-degradation.yaml)
    for p in skills_dir.glob(f"{skill_id}-*.yaml"):
        return _parse_yaml(p)

    # 3. Directory-based skill
    skill_dir = skills_dir / skill_id
    if skill_dir.is_dir():
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            return _parse_directory_skill(skill_id, skill_md, skill_dir)

    return None


def _parse_yaml(path: Path) -> dict[str, Any] | None:
    """Parse a CSDF YAML file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict):
            return data
    except (yaml.YAMLError, OSError):
        pass
    return None


def _parse_directory_skill(
    skill_id: str,
    skill_md: Path,
    skill_dir: Path,
) -> dict[str, Any]:
    """Parse a directory-based skill from SKILL.md frontmatter."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return {"id": skill_id, "name": skill_id, "type": "directory"}

    # Parse YAML frontmatter
    frontmatter: dict[str, Any] = {"id": skill_id, "name": skill_id, "type": "directory"}
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            try:
                fm = yaml.safe_load(text[3:end])
                if isinstance(fm, dict):
                    frontmatter.update(fm)
            except yaml.YAMLError:
                pass

    frontmatter["id"] = frontmatter.get("id", skill_id)
    frontmatter["name"] = frontmatter.get("name", skill_id)
    frontmatter["type"] = "directory"
    frontmatter["_skill_dir"] = str(skill_dir)

    # Store the markdown body (content after frontmatter) for directory-based skills
    # This allows skill_definition() to return the full SKILL.md content
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            # Extract body after the closing ---
            body = text[end + 3 :].lstrip("\n")
            if body:
                frontmatter["_markdown_body"] = body

    # Merge manifest.yaml if present (contains synergies, dependencies, etc.)
    manifest_path = skill_dir / "manifest.yaml"
    if manifest_path.exists():
        manifest_data = _parse_yaml(manifest_path)
        if manifest_data and isinstance(manifest_data, dict):
            # manifest fields override frontmatter defaults, but don't clobber id/type
            for k, v in manifest_data.items():
                if k not in ("id", "type"):
                    frontmatter.setdefault(k, v)

    return frontmatter
