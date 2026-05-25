"""SkillPool Quality Profiler — 4-dimension scoring with calibration."""

from __future__ import annotations

from dataclasses import dataclass, field

from skillpool.csdf import CSDFDocument


@dataclass
class QualityProfile:
    """Quality profile for a skill, containing 4 dimension scores."""

    name: str
    completeness: float = 0.0
    accuracy: float = 0.0
    usability: float = 0.0
    maintainability: float = 0.0
    overall: float = 0.0
    weights: dict[str, float] = field(default_factory=dict)
    calibration_note: str = ""

    def __post_init__(self) -> None:
        if not self.weights:
            self.weights = {
                "completeness": 0.30,
                "accuracy": 0.30,
                "usability": 0.20,
                "maintainability": 0.20,
            }
        if self.overall == 0.0:
            self.overall = self._compute_overall()

    def _compute_overall(self) -> float:
        total = 0.0
        weight_sum = 0.0
        for dim, weight in self.weights.items():
            score = getattr(self, dim, 0.0)
            total += score * weight
            weight_sum += weight
        if weight_sum == 0:
            return 0.0
        return round(total / weight_sum, 4)


DEFAULT_WEIGHTS: dict[str, float] = {
    "completeness": 0.30,
    "accuracy": 0.30,
    "usability": 0.20,
    "maintainability": 0.20,
}

CALIBRATION_OFFSETS: dict[str, float] = {
    "completeness": 0.0,
    "accuracy": -0.05,
    "usability": 0.0,
    "maintainability": 0.0,
}


class QualityProfiler:
    """Compute and calibrate quality profiles for skills."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        calibration_offsets: dict[str, float] | None = None,
    ) -> None:
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.calibration_offsets = calibration_offsets or CALIBRATION_OFFSETS.copy()

    def profile(self, doc: CSDFDocument) -> QualityProfile:
        raw_dims = doc.dimensions
        calibrated: dict[str, float] = {}
        for dim in ["completeness", "accuracy", "usability", "maintainability"]:
            raw = raw_dims.get(dim, 0.0)
            offset = self.calibration_offsets.get(dim, 0.0)
            calibrated[dim] = max(0.0, min(1.0, raw + offset))
        return QualityProfile(
            name=doc.name,
            completeness=calibrated["completeness"],
            accuracy=calibrated["accuracy"],
            usability=calibrated["usability"],
            maintainability=calibrated["maintainability"],
            weights=self.weights.copy(),
        )

    def score(self, profile: QualityProfile) -> float:
        return profile.overall

    def compare(self, profile_a: QualityProfile, profile_b: QualityProfile) -> dict[str, float]:
        diffs: dict[str, float] = {}
        for dim in ["completeness", "accuracy", "usability", "maintainability"]:
            a_val = getattr(profile_a, dim, 0.0)
            b_val = getattr(profile_b, dim, 0.0)
            diffs[dim] = round(a_val - b_val, 4)
        diffs["overall"] = round(profile_a.overall - profile_b.overall, 4)
        return diffs
