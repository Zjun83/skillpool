"""Pydantic models for Materializer data structures."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillValues(BaseModel):
    """Skill values declaration — shared standard across SKILL/Agent/SkillPool."""

    effectiveness: str = ""  # Task goal achievement degree
    efficiency: str = ""  # Resource consumption reasonableness
    quality: str = ""  # Output sustainability
    gain: str = ""  # Combination marginal contribution


class SynergyEntry(BaseModel):
    """Expert-annotated skill combination with expected gain."""

    skill_id: str
    gain: str = ""  # Expected gain, e.g. "+15%"
    reason: str = ""  # Why this combination helps


class CSDFDocument(BaseModel):
    """CSDF YAML 文档的结构化表示。"""

    id: str = ""
    name: str = ""
    version: str = "0.0.0"
    dimension: str = ""
    weight: float | None = None
    veto_rule: str | None = None
    description: str = ""
    checklist: list[dict] = Field(default_factory=list)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    version_history: list[dict] = Field(default_factory=list)
    # 额外字段
    required_agent_capabilities: set[str] = Field(default_factory=set)
    min_trust_level: int = 0
    paradigm: str | None = None
    # V4.3 Phase 9: Skill Combination Gain Flywheel
    values: SkillValues = Field(default_factory=SkillValues)
    synergies: list[SynergyEntry] = Field(default_factory=list)


class MaterializedSkill(BaseModel):
    """实体化后的 SKILL.md 数据。"""

    id: str
    name: str
    version: str = "0.0.0"
    dimension: str = ""
    markdown: str = ""
    token_count: int = 0

    model_config = {"arbitrary_types_allowed": True}


class MaterializationResult(BaseModel):
    """Materializer 执行结果。"""

    status: str  # "success" | "rejected" | "error"
    skill: MaterializedSkill | None = None
    errors: list[str] = Field(default_factory=list)
