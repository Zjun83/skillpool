"""Registry models — Skill metadata and lifecycle state."""
from __future__ import annotations

__all__ = [
    "ProblemDetail",
    "RegisterSkillRequest",
    "RegisterSkillResponse",
    "SkillMetadata",
    "SkillStatus",
    "StateTransitionRequest",
    "StateTransitionResponse",
]

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SkillStatus(StrEnum):
    """Skill lifecycle states (9-state model)."""
    DRAFT = "draft"
    IMPORTED = "imported"
    TESTING = "testing"
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


@dataclass
class SkillMetadata:
    """Skill metadata stored in Registry."""
    skill_id: str
    name: str
    version: str
    status: SkillStatus = SkillStatus.DRAFT
    description: str = ""
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    security: dict[str, Any] = field(default_factory=dict)
    quality_score: float = 0.0


@dataclass
class ProblemDetail:
    """RFC 7807 Problem Detail for error responses."""
    type: str
    title: str
    status: int
    detail: str = ""
    instance: str = ""


@dataclass
class RegisterSkillRequest:
    """Request to register a skill candidate."""
    skill_metadata: SkillMetadata
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RegisterSkillResponse:
    """Response from skill registration."""
    context: dict[str, Any] = field(default_factory=dict)
    skill_id: str = ""
    status: str = "testing"
    audit_ref: str = ""


@dataclass
class StateTransitionRequest:
    """Request to transition skill state."""
    from_status: SkillStatus
    to_status: SkillStatus
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class StateTransitionResponse:
    """Response from state transition."""
    context: dict[str, Any] = field(default_factory=dict)
    skill_id: str = ""
    from_status: str = ""
    to_status: str = ""
    audit_ref: str = ""
