"""SkillPool CSDF Parser — Parse SKILL.md frontmatter into structured data."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class CSDFDocument(BaseModel):
    """Parsed CSDF (Codex Skill Definition Format) document."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    dimensions: dict[str, float] = Field(default_factory=dict)
    body: str = ""
    content_hash: str = ""
    source_path: str = ""

    @field_validator("version")
    @classmethod
    def version_format(cls, v: str) -> str:
        """Accept semver (1.2.3) or short (1.0) version strings."""
        if not re.match(r"^\d+(\.\d+)*$", v):
            raise ValueError(f"Invalid version format: {v!r}")
        return v


class CSDFParser:
    """Stateless parser for CSDF frontmatter documents."""

    def __init__(self) -> None:
        self._frontmatter_re = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)

    def parse(self, content: str, source_path: str = "") -> CSDFDocument:
        """Parse a SKILL.md string into a CSDFDocument.

        Raises ValueError if no valid YAML frontmatter is found.
        """
        if isinstance(content, Path):
            content = content.read_text(encoding="utf-8")

        content = str(content)
        match = self._frontmatter_re.match(content)
        if not match:
            raise ValueError("No valid YAML frontmatter found")

        fm_text, body = match.group(1), match.group(2)
        try:
            fm: dict[str, Any] = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in frontmatter: {exc}") from exc

        quality = fm.pop("quality", {}) or {}
        dimensions = fm.pop("dimensions", {}) or {}

        doc = CSDFDocument(
            name=fm.get("name", ""),
            version=fm.get("version", "0.1.0"),
            description=fm.get("description", ""),
            triggers=fm.get("triggers", []),
            references=fm.get("references", []),
            dependencies=fm.get("dependencies", []),
            quality=quality,
            dimensions=dimensions,
            body=body.strip(),
            content_hash=self._hash(content),
            source_path=source_path,
        )
        return doc

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def parse_csdf(source: str | Path) -> CSDFDocument:
    """Parse a CSDF document from a file path or string content.

    Unlike CSDFParser.parse(), this function gracefully handles content
    without frontmatter by returning a default CSDFDocument.
    """
    parser = CSDFParser()
    if isinstance(source, Path):
        content = source.read_text(encoding="utf-8")
        try:
            return parser.parse(content, source_path=str(source))
        except ValueError:
            return CSDFDocument(
                name="",
                body=content.strip(),
                content_hash=parser._hash(content),
                source_path=str(source),
            )
    content = str(source)
    try:
        return parser.parse(content)
    except ValueError:
        return CSDFDocument(
            name="",
            body=content.strip(),
            content_hash=parser._hash(content),
        )


def validate_csdf(doc: CSDFDocument) -> list[str]:
    """Validate a CSDFDocument and return a list of issues."""
    issues: list[str] = []
    if not doc.name:
        issues.append("Missing name")
    if not doc.description:
        issues.append("Missing description")
    if not doc.triggers:
        issues.append("Missing triggers")
    if not doc.body:
        issues.append("Missing body content after frontmatter")
    return issues
