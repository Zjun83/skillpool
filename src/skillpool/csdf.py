"""SkillPool CSDF Parser — Parse SKILL.md frontmatter into structured data."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class CSDFDocument(BaseModel):
    """Parsed CSDF (Codex Skill Definition Format) document."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    dimensions: dict[str, float] = Field(default_factory=dict)
    references: list[str] = Field(default_factory=list)
    body: str = ""
    source_path: str = ""
    content_hash: str = ""

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, v: dict[str, float]) -> dict[str, float]:
        for key, value in v.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"Dimension '{key}' value {value} out of range [0.0, 1.0]")
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) < 2:
            raise ValueError(f"Version '{v}' must have at least major.minor format")
        return v


class CSDFParser:
    """Parser for SKILL.md files in CSDF format."""

    FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

    def parse(self, content: str, source_path: str = "") -> CSDFDocument:
        match = self.FRONTMATTER_PATTERN.match(content)
        if not match:
            raise ValueError("No valid YAML frontmatter found in SKILL.md")
        frontmatter_str = match.group(1)
        body = content[match.end() :]
        try:
            frontmatter = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in frontmatter: {e}") from e
        if not isinstance(frontmatter, dict):
            raise ValueError("Frontmatter must be a YAML mapping")
        name = frontmatter.get("name", "")
        if not name:
            raise ValueError("Frontmatter must contain a 'name' field")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        references = frontmatter.get("references", [])
        if isinstance(references, str):
            references = [references]
        return CSDFDocument(
            name=str(name),
            version=str(frontmatter.get("version", "0.1.0")),
            description=str(frontmatter.get("description", "")),
            triggers=frontmatter.get("triggers", []),
            dimensions=frontmatter.get("dimensions", {}),
            references=references,
            body=body.strip(),
            source_path=source_path,
            content_hash=content_hash,
        )

    def parse_file(self, path: Path) -> CSDFDocument:
        if not path.exists():
            raise FileNotFoundError(f"SKILL.md not found: {path}")
        content = path.read_text(encoding="utf-8")
        return self.parse(content, source_path=str(path))

    def validate(self, doc: CSDFDocument) -> list[str]:
        issues: list[str] = []
        if not doc.name:
            issues.append("Missing required field: name")
        if not doc.description:
            issues.append("Missing recommended field: description")
        if not doc.triggers:
            issues.append("Missing recommended field: triggers")
        required_dims = {"completeness", "accuracy", "usability", "maintainability"}
        missing_dims = required_dims - set(doc.dimensions.keys())
        if missing_dims:
            issues.append(f"Missing quality dimensions: {sorted(missing_dims)}")
        if not doc.body:
            issues.append("Missing body content after frontmatter")
        return issues
