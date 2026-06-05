"""SkillPool Quality Profiler — 4-dimension scoring with auto-calculation and calibration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from skillpool.csdf import CSDFDocument

# Default weights for overall score computation
DEFAULT_WEIGHTS: dict[str, float] = {
    "completeness": 0.30,
    "accuracy": 0.30,
    "usability": 0.20,
    "maintainability": 0.20,
}

# Calibration offsets applied to raw dimension scores
CALIBRATION_OFFSETS: dict[str, float] = {
    "completeness": 0.0,
    "accuracy": -0.05,
    "usability": 0.0,
    "maintainability": 0.0,
}


def _compute_overall(
    completeness: float,
    accuracy: float,
    usability: float,
    maintainability: float,
    weights: dict[str, float],
) -> float:
    """Compute weighted overall score from dimension scores."""
    return round(
        completeness * weights.get("completeness", 0.0)
        + accuracy * weights.get("accuracy", 0.0)
        + usability * weights.get("usability", 0.0)
        + maintainability * weights.get("maintainability", 0.0),
        4,
    )


@dataclass
class QualityProfile:
    """Quality profile for a skill, containing 4 dimension scores and an overall score."""

    name: str = ""
    completeness: float = 0.0
    accuracy: float = 0.0
    usability: float = 0.0
    maintainability: float = 0.0
    overall: float = 0.0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def __post_init__(self) -> None:
        """Auto-calculate overall score if not explicitly provided."""
        # If overall is 0.0 and any dimension is non-zero, recalculate
        if self.overall == 0.0 and any([self.completeness, self.accuracy, self.usability, self.maintainability]):
            self.overall = _compute_overall(
                self.completeness,
                self.accuracy,
                self.usability,
                self.maintainability,
                self.weights,
            )

    @classmethod
    def from_document(
        cls,
        doc: CSDFDocument,
        weights: dict[str, float] | None = None,
    ) -> QualityProfile:
        """Create a QualityProfile from a CSDFDocument, using its dimensions dict."""
        w = weights or dict(DEFAULT_WEIGHTS)
        dims = doc.dimensions
        completeness = dims.get("completeness", 0.0)
        accuracy = dims.get("accuracy", 0.0)
        usability = dims.get("usability", 0.0)
        maintainability = dims.get("maintainability", 0.0)
        overall = _compute_overall(completeness, accuracy, usability, maintainability, w)
        return cls(
            name=doc.name,
            completeness=completeness,
            accuracy=accuracy,
            usability=usability,
            maintainability=maintainability,
            overall=overall,
            weights=w,
        )

    @classmethod
    def from_scores(
        cls,
        name: str,
        completeness: float = 0.0,
        accuracy: float = 0.0,
        usability: float = 0.0,
        maintainability: float = 0.0,
        weights: dict[str, float] | None = None,
    ) -> QualityProfile:
        """Create a QualityProfile from explicit dimension scores."""
        w = weights or dict(DEFAULT_WEIGHTS)
        overall = _compute_overall(completeness, accuracy, usability, maintainability, w)
        return cls(
            name=name,
            completeness=completeness,
            accuracy=accuracy,
            usability=usability,
            maintainability=maintainability,
            overall=overall,
            weights=w,
        )

    def compare(self, other: QualityProfile) -> dict[str, float]:
        """Compare this profile with another, returning dimension deltas."""
        return {
            "completeness": round(self.completeness - other.completeness, 4),
            "accuracy": round(self.accuracy - other.accuracy, 4),
            "usability": round(self.usability - other.usability, 4),
            "maintainability": round(self.maintainability - other.maintainability, 4),
            "overall": round(self.overall - other.overall, 4),
        }


class QualityProfiler:
    """Profiles a CSDFDocument to produce a QualityProfile with auto-calculated scores."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        calibration_offsets: dict[str, float] | None = None,
    ) -> None:
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.calibration_offsets = calibration_offsets or dict(CALIBRATION_OFFSETS)

    def profile(self, doc: CSDFDocument) -> QualityProfile:
        """Profile a CSDFDocument and return a QualityProfile with computed scores."""
        # Use document dimensions if present, otherwise auto-calculate
        dims = doc.dimensions
        if dims:
            completeness = dims.get("completeness", _score_completeness(doc))
            accuracy = dims.get("accuracy", _score_accuracy(doc))
            usability = dims.get("usability", _score_usability(doc))
            maintainability = dims.get("maintainability", _score_maintainability(doc))
        else:
            completeness = _score_completeness(doc)
            accuracy = _score_accuracy(doc)
            usability = _score_usability(doc)
            maintainability = _score_maintainability(doc)

        # Apply calibration offsets
        completeness = max(0.0, min(1.0, completeness + self.calibration_offsets.get("completeness", 0.0)))
        accuracy = max(0.0, min(1.0, accuracy + self.calibration_offsets.get("accuracy", 0.0)))
        usability = max(0.0, min(1.0, usability + self.calibration_offsets.get("usability", 0.0)))
        maintainability = max(0.0, min(1.0, maintainability + self.calibration_offsets.get("maintainability", 0.0)))

        overall = _compute_overall(
            completeness,
            accuracy,
            usability,
            maintainability,
            self.weights,
        )

        return QualityProfile(
            name=doc.name,
            completeness=round(completeness, 4),
            accuracy=round(accuracy, 4),
            usability=round(usability, 4),
            maintainability=round(maintainability, 4),
            overall=overall,
            weights=self.weights,
        )


# ---------------------------------------------------------------------------
# Auto-scoring helpers — compute dimension scores from document content
# ---------------------------------------------------------------------------


def _score_completeness(doc: CSDFDocument) -> float:
    """Score completeness based on presence of key fields and content."""
    score = 0.0
    if doc.name:
        score += 0.25
    if doc.description:
        score += 0.25
    if doc.triggers:
        score += 0.25
    if doc.body:
        score += 0.25
    return round(min(score, 1.0), 4)


def _score_accuracy(doc: CSDFDocument) -> float:
    """Score accuracy based on references and content indicators."""
    score = 0.0
    if doc.references:
        score += min(len(doc.references) * 0.25, 0.5)
    if doc.body:
        code_indicators = len(re.findall(r"```", doc.body))
        if code_indicators >= 2:
            score += 0.3
        elif code_indicators >= 1:
            score += 0.15
        tech_terms = len(re.findall(r"\b(API|function|class|method|parameter|return)\b", doc.body, re.IGNORECASE))
        if tech_terms >= 3:
            score += 0.2
        elif tech_terms >= 1:
            score += 0.1
    return round(min(score, 1.0), 4)


def _score_usability(doc: CSDFDocument) -> float:
    """Score usability based on structure and readability indicators."""
    score = 0.0
    if doc.body:
        headers = len(re.findall(r"^#{1,6}\s+", doc.body, re.MULTILINE))
        if headers >= 3:
            score += 0.3
        elif headers >= 1:
            score += 0.15
        lists = len(re.findall(r"^[\s]*[-*+]\s+", doc.body, re.MULTILINE))
        if lists >= 3:
            score += 0.2
        elif lists >= 1:
            score += 0.1
        word_count = len(doc.body.split())
        if 50 <= word_count <= 2000:
            score += 0.3
        elif word_count > 0:
            score += 0.15
    if doc.triggers:
        score += 0.1
    return round(min(score, 1.0), 4)


def _score_maintainability(doc: CSDFDocument) -> float:
    """Score maintainability based on version info and content organization."""
    score = 0.0
    if doc.version and re.match(r"^\d+\.\d+\.\d+", doc.version):
        score += 0.3
    if doc.description:
        score += 0.2
    if doc.body:
        paragraphs = [p for p in doc.body.split("\n\n") if p.strip()]
        if paragraphs:
            avg_len = sum(len(p) for p in paragraphs) / len(paragraphs)
            if avg_len < 200:
                score += 0.20
            elif avg_len < 400:
                score += 0.10
    return round(min(score, 1.0), 4)
