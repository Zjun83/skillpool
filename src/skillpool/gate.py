"""SkillPool Gate — Quality gate checks with emergency override support."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator

from skillpool.csdf import CSDFDocument
from skillpool.quality import QualityProfile, QualityProfiler


class GateStatus(str, Enum):
    """Status of a gate check."""

    PASS = "pass"
    FAIL = "fail"
    OVERRIDE = "override"
    SKIPPED = "skipped"


class GateResult(BaseModel):
    """Result of a gate check on a skill."""

    skill_name: str
    status: GateStatus
    overall_score: float
    min_required: float
    dimension_results: dict[str, dict[str, Any]] = {}
    override_reason: str = ""
    timestamp: str = ""

    @model_validator(mode="after")
    def _set_timestamp(self) -> GateResult:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        return self


class GateConfig(BaseModel):
    """Configuration for quality gate thresholds."""

    min_quality_score: float = 0.6
    required_dimensions: list[str] = ["completeness", "accuracy"]
    min_dimension_score: float = 0.5
    emergency_overrides: dict[str, str] = {}


class Gate:
    """Quality gate checker for skill registration."""

    def __init__(self, config: GateConfig | None = None) -> None:
        self.config = config or GateConfig()

    @classmethod
    def from_file(cls, path: Path) -> Gate:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(config=GateConfig(**data))

    def check(
        self,
        profile: QualityProfile,
        override_key: str | None = None,
    ) -> GateResult:
        dimension_results: dict[str, dict[str, Any]] = {}
        all_pass = True

        for dim in self.config.required_dimensions:
            score = getattr(profile, dim, 0.0)
            passed = score >= self.config.min_dimension_score
            dimension_results[dim] = {
                "score": score,
                "min": self.config.min_dimension_score,
                "passed": passed,
            }
            if not passed:
                all_pass = False

        overall_pass = profile.overall >= self.config.min_quality_score

        if overall_pass and all_pass:
            return GateResult(
                skill_name=profile.name,
                status=GateStatus.PASS,
                overall_score=profile.overall,
                min_required=self.config.min_quality_score,
                dimension_results=dimension_results,
            )

        if override_key and override_key in self.config.emergency_overrides:
            return GateResult(
                skill_name=profile.name,
                status=GateStatus.OVERRIDE,
                overall_score=profile.overall,
                min_required=self.config.min_quality_score,
                dimension_results=dimension_results,
                override_reason=self.config.emergency_overrides[override_key],
            )

        return GateResult(
            skill_name=profile.name,
            status=GateStatus.FAIL,
            overall_score=profile.overall,
            min_required=self.config.min_quality_score,
            dimension_results=dimension_results,
        )

    def check_document(
        self,
        doc: CSDFDocument,
        profiler: QualityProfiler | None = None,
        override_key: str | None = None,
    ) -> GateResult:
        profiler = profiler or QualityProfiler()
        profile = profiler.profile(doc)
        return self.check(profile, override_key=override_key)
