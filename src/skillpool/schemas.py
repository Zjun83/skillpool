"""Pydantic v2 validators for CSDF (Capability Skill Definition Format) skill YAML files."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class SkillDimension(str, Enum):
    """Valid dimension values for CSDF skills."""

    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    D4 = "D4"
    D5 = "D5"
    D6 = "D6"
    D7 = "D7"
    D8 = "D8"
    D9 = "D9"
    D10 = "D10"
    D11 = "D11"
    D12 = "D12"
    ALL = "ALL"


class ChecklistItem(BaseModel):
    """A single checklist entry within a CSDF skill."""

    id: str
    description: str
    severity: str

    @field_validator("severity")
    @classmethod
    def severity_must_be_valid(cls, v: str) -> str:
        allowed = {"critical", "high", "medium", "low"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {sorted(allowed)}, got {v!r}")
        return v


class CSDFSkill(BaseModel):
    """Validated CSDF skill definition loaded from YAML."""

    id: str
    name: str
    version: str
    dimension: SkillDimension
    weight: float | None = None
    veto_rule: str | None = None
    description: str
    checklist: list[ChecklistItem] = Field(default_factory=list)
    dependencies: list[str] | None = None
    conflicts: list[str] | None = None
    # GovernSpec contract fields (arxiv 2605.22634)
    permissions: list[str] = Field(default_factory=list)
    boundaries: list[dict] = Field(default_factory=list)
    verification_steps: list[dict] = Field(default_factory=list)

    def validate_contract(self) -> list[str]:
        """Validate GovernSpec contract fields. Returns list of error strings (empty if valid)."""
        errors: list[str] = []
        for i, p in enumerate(self.permissions):
            if not isinstance(p, str):
                errors.append(f"permissions[{i}]: expected str, got {type(p).__name__}")
        for i, b in enumerate(self.boundaries):
            if not isinstance(b, dict):
                errors.append(f"boundaries[{i}]: expected dict, got {type(b).__name__}")
                continue
            if "type" not in b:
                errors.append(f"boundaries[{i}]: missing 'type' key")
            if "value" not in b:
                errors.append(f"boundaries[{i}]: missing 'value' key")
        for i, v in enumerate(self.verification_steps):
            if not isinstance(v, dict):
                errors.append(f"verification_steps[{i}]: expected dict, got {type(v).__name__}")
                continue
            if "check" not in v:
                errors.append(f"verification_steps[{i}]: missing 'check' key")
        return errors

    @field_validator("version")
    @classmethod
    def version_must_be_semver(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+$", v):
            raise ValueError(f"version must be semver (X.Y.Z), got {v!r}")
        return v

    @field_validator("weight")
    @classmethod
    def weight_must_be_in_range(cls, v: float | None) -> float | None:
        if v is not None and not (0 <= v <= 1):
            raise ValueError(f"weight must be between 0 and 1, got {v}")
        return v


def validate_csdf(data: dict) -> CSDFSkill:
    """Validate a raw dict (from yaml.safe_load) as a CSDFSkill.

    Returns the validated CSDFSkill or raises ValidationError.
    """
    return CSDFSkill.model_validate(data)


def validate_csdf_file(path: Path) -> CSDFSkill:
    """Load and validate a CSDF YAML file.

    Returns the validated CSDFSkill or raises ValidationError / YAML error.
    """
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping, got {type(data).__name__}")
    return validate_csdf(data)
