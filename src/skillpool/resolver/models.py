"""Resolver models — Pydantic schemas for skill resolution.

Aligned with contracts/schemas/skill_resolve_request.v1.json
"""
from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


class ResolveStrategy(StrEnum):
    STRICT = "strict"
    BEST_EFFORT = "best_effort"
    FUZZY = "fuzzy"


class ResolveStatus(StrEnum):
    """Three-state resolution status (per schema)."""
    RESOLVED = "resolved"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"


class ConflictSeverity(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConflictType(StrEnum):
    """Conflict type classification (per schema)."""
    NAMESPACE_OVERLAP = "namespace_overlap"
    SEMANTIC_CONFLICT = "semantic_conflict"
    RESOURCE_CONTENTION = "resource_contention"
    VERSION_MISMATCH = "version_mismatch"
    SECURITY_POLICY = "security_policy"


class DagEdgeType(StrEnum):
    """Edge type classification (per schema)."""
    DEPENDS_ON = "depends_on"
    ENHANCES = "enhances"
    CONFLICTS_WITH = "conflicts_with"
    REPLACES = "replaces"


class Domain(StrEnum):
    """Task domain classification (per schema)."""
    CODE_REFACTOR = "code_refactor"
    SECURITY_FIX = "security_fix"
    CODE_ANALYSIS = "code_analysis"
    ARCHITECTURE_MIGRATION = "architecture_migration"
    DOCUMENTATION = "documentation"
    DEPENDENCY_UPGRADE = "dependency_upgrade"
    TESTING = "testing"
    DATA_MIGRATION = "data_migration"


class DagEdge(BaseModel):
    """Directed edge in the skill dependency graph."""
    source: str = Field(description="Upstream skill ID (schema: 'from')")
    target: str = Field(description="Downstream skill ID (schema: 'to')")
    weight: float = Field(default=1.0, description="Edge weight (0-1)")
    type: DagEdgeType = Field(default=DagEdgeType.DEPENDS_ON, description="Edge type")


class ResolvedSkill(BaseModel):
    """A single resolved skill with metadata."""
    skill_id: str
    name: str = ""
    version: str = Field(default="1.0.0", description="Semantic version")
    dimension: str = ""
    domain: str = Field(default="", description="Task domain")
    weight: float = 0.0
    health_score: float = Field(default=1.0, ge=0.0, le=1.0)
    trust_level: int = Field(default=3, ge=0, le=3)
    dependencies: list[str] = Field(default_factory=list)
    estimated_tokens: int = Field(default=0, description="Estimated token usage")
    provides: list[str] = Field(default_factory=list, description="Capability tags this skill provides")
    conflict: Optional[ConflictSeverity] = None


class Conflict(BaseModel):
    """Detected conflict between skills."""
    skill_a: str
    skill_b: str
    jaccard_score: float = Field(default=0.0, ge=0.0, le=1.0)
    severity: ConflictSeverity
    conflict_type: ConflictType = Field(default=ConflictType.NAMESPACE_OVERLAP)
    overlapping_namespaces: list[str] = Field(default_factory=list)
    recommendation: str = Field(default="", description="Recommended resolution")


class SkillResolveRequest(BaseModel):
    """Request to resolve a skill chain.

    Aligned with contracts/schemas/skill_resolve_request.v1.json:
    - trace_id: W3C TraceContext (32 hex chars)
    - task_description: Natural language task description
    - domain: Task domain classification
    - plan_id: Associated plan ID for audit
    """
    skill_ids: list[str] = Field(min_length=1, description="Root skill IDs to resolve (schema: available_skills)")
    task_description: str = Field(default="", description="Natural language task description")
    domain: Optional[Domain] = Field(default=None, description="Task domain classification")
    trace_id: str = Field(default="", description="W3C TraceContext trace_id (32 hex chars)")
    plan_id: str = Field(default="", description="Associated plan ID for audit tracing")
    strategy: ResolveStrategy = ResolveStrategy.BEST_EFFORT
    max_skills: int = Field(default=50, ge=1, le=200)
    exclude_skills: list[str] = Field(default_factory=list)
    require_independent: bool = False
    min_health_score: float = Field(default=0.6, ge=0.0, le=1.0)
    context: str = Field(default="", description="Resolution context for telemetry")


class SkillResolveResponse(BaseModel):
    """Response from skill resolution.

    Aligned with contracts/schemas/skill_resolve_request.v1.json:
    - status: three-state (resolved/partial/unresolved)
    - health_scores: per-skill health score mapping
    - feasibility_score: composite feasibility rating
    """
    resolved: list[ResolvedSkill] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list, description="Skills excluded by filters")
    dag_edges: list[DagEdge] = Field(default_factory=list)
    total_skills: int = 0
    resolution_time_ms: float = 0.0
    from_cache: bool = False
    degraded: bool = False
    error: Optional[str] = None
    # Schema-aligned fields
    status: ResolveStatus = Field(default=ResolveStatus.RESOLVED, description="Three-state resolution status")
    health_scores: dict[str, float] = Field(default_factory=dict, description="Per-skill health scores {skill_id: score}")
    feasibility_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Composite feasibility = f(health_scores, conflicts)")
