"""CheckpointRunner — runs dimension scoring for each checkpoint level."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Callable, Optional

import yaml

from skillpool.config import get_data_dir
from skillpool.review.models import CheckpointLevel

logger = logging.getLogger(__name__)

# Dimensions per checkpoint level
SHADOW_DIMENSIONS = ("D1", "D2", "D4", "D6", "D8", "D9", "D12")
BASELINE_DIMENSIONS = ("D3", "D5", "D7", "D10", "D11")
ALL_DIMENSIONS = BASELINE_DIMENSIONS + SHADOW_DIMENSIONS

# Dimension → required skills mapping
DIMENSION_SKILLS: dict[str, list[str]] = {
    "D1": ["S01"],
    "D2": ["S02"],
    "D3": ["S05a", "S05b", "S06"],
    "D4": ["S04"],
    "D5": ["S09", "S10"],
    "D6": ["S07", "S08"],
    "D7": ["S13a", "S13b"],
    "D8": ["S11"],
    "D9": ["S12"],
    "D10": ["S19"],
    "D11": ["S20"],
    "D12": ["S21"],
}

# Required fields in CSDF YAML for scoring
REQUIRED_CSDF_FIELDS = {"id", "name", "version", "dimension", "description"}

# Default skills directory
_DEFAULT_SKILLS_DIR = get_data_dir() / "skills"


class CheckpointRunner:
    """Runs dimension scoring for a given checkpoint level.

    Evaluates each dimension by inspecting the corresponding skill YAML files:
    - File existence and YAML parseability
    - Required field completeness
    - Checklist item count and severity distribution

    Falls back to deterministic hash-based scores when skill files are unavailable.
    """

    def __init__(self, seed: Optional[int] = None, skills_dir: Optional[Path] = None):
        self._base_seed = seed
        self._skills_dir = skills_dir or _DEFAULT_SKILLS_DIR

    def run_checkpoint(
        self,
        level: CheckpointLevel,
        skills: list[str],
    ) -> dict[str, float]:
        """Evaluate dimensions for the given checkpoint level.

        Returns a dict of dimension → score (0.0-10.0).
        """
        dimensions = self._dimensions_for_level(level)
        scores: dict[str, float] = {}
        for d in dimensions:
            scores[d] = self._score_dimension(d)
        return scores

    def _dimensions_for_level(self, level: CheckpointLevel) -> tuple[str, ...]:
        """Return the dimensions to evaluate for each checkpoint level."""
        if level == CheckpointLevel.L1:
            return SHADOW_DIMENSIONS
        elif level == CheckpointLevel.L2:
            return ALL_DIMENSIONS
        elif level == CheckpointLevel.L3:
            return BASELINE_DIMENSIONS
        elif level == CheckpointLevel.L4:
            return BASELINE_DIMENSIONS
        return ALL_DIMENSIONS

    def _score_dimension(self, dimension: str) -> float:
        """Score a single dimension by evaluating its associated skill files."""
        skill_ids = DIMENSION_SKILLS.get(dimension, [])
        if not skill_ids:
            return self._fallback_score(dimension)

        scores: list[float] = []
        for sid in skill_ids:
            s = self._score_skill(sid)
            scores.append(s)

        return round(sum(scores) / len(scores), 2) if scores else self._fallback_score(dimension)

    def _score_skill(self, skill_id: str) -> float:
        """Score a single skill based on CSDF file quality."""
        yaml_path = self._find_skill_yaml(skill_id)
        if yaml_path is None:
            return self._fallback_score(skill_id)

        # Parse YAML
        try:
            content = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
        except (yaml.YAMLError, OSError):
            return 3.0  # Unparseable YAML → low score

        if not isinstance(data, dict):
            return 2.0

        # Determine which dimension this skill primarily serves
        primary_dim = self._skill_dimension(skill_id)

        # Use dimension-specific scoring if available
        if primary_dim:
            dim_scorer = self._DIMENSION_SCORERS.get(primary_dim)
            if dim_scorer:
                return dim_scorer(self, data, content)

        # Default: generic quality scoring
        return self._score_generic(data)

    def _skill_dimension(self, skill_id: str) -> Optional[str]:
        """Return the primary dimension for a skill ID."""
        for dim, skills in DIMENSION_SKILLS.items():
            if skill_id in skills:
                return dim
        return None

    # ── Dimension-specific scorers ──

    def _score_d3_security(self, data: dict, raw_content: str) -> float:
        """D3 安全合规性: SecurityScanner scan + CSDF field quality."""
        score = self._score_generic(data)
        # Bonus: SecurityScanner scan passes
        try:
            from skillpool.hooks.security_scanner import SecurityScanner
            scanner = SecurityScanner()
            result = scanner.full_check(raw_content)
            if result.is_safe:
                score += 2.0
            elif result.threat_level.value == "warning":
                score += 0.5
            # CRITICAL means is_safe=False → no bonus
        except Exception as e:
            logger.warning("Security scanner unavailable, skipping scan bonus: %s", e)

        # Bonus: explicit security fields in CSDF
        if data.get("security_scan_required"):
            score += 0.5
        if data.get("veto_rule"):
            score += 0.5

        return min(round(score, 2), 10.0)

    def _score_d5_resilience(self, data: dict, raw_content: str) -> float:
        """D5 弹性容错: Degradation config + recovery strategy."""
        score = self._score_generic(data)

        # Bonus: degradation/fallback declared
        if data.get("fallback") or data.get("degradation"):
            score += 1.5
        # Bonus: recovery/retry declared
        if data.get("recovery") or data.get("retry_strategy"):
            score += 1.0
        # Bonus: circuit breaker or timeout declared
        if data.get("circuit_breaker") or data.get("timeout"):
            score += 0.5

        # Penalty: no resilience fields at all
        resilience_fields = {"fallback", "degradation", "recovery", "retry_strategy",
                             "circuit_breaker", "timeout", "grace_period"}
        if not any(k in data for k in resilience_fields):
            # Check checklist for resilience-related items
            checklist = data.get("checklist", [])
            has_resilience_item = any(
                isinstance(item, dict) and any(
                    kw in str(item.get("description", "")).lower()
                    for kw in ("fallback", "degrad", "recover", "retry", "timeout")
                )
                for item in checklist
            )
            if not has_resilience_item:
                score -= 1.0

        return min(max(round(score, 2), 0.0), 10.0)

    def _score_d7_testability(self, data: dict, raw_content: str) -> float:
        """D7 可测试性: Test coverage + BDD specification."""
        score = self._score_generic(data)

        # Bonus: test_coverage field declared
        coverage = data.get("test_coverage")
        if isinstance(coverage, (int, float)):
            if coverage >= 90:
                score += 2.0
            elif coverage >= 80:
                score += 1.5
            elif coverage >= 70:
                score += 1.0
            else:
                score += 0.5
        elif coverage:
            score += 0.5

        # Bonus: BDD/acceptance criteria in checklist
        checklist = data.get("checklist", [])
        bdd_keywords = {"given", "when", "then", "should", "must", "verify"}
        bdd_count = sum(
            1 for item in checklist
            if isinstance(item, dict)
            and any(kw in str(item.get("description", "")).lower() for kw in bdd_keywords)
        )
        if bdd_count >= 3:
            score += 1.5
        elif bdd_count >= 1:
            score += 0.5

        return min(round(score, 2), 10.0)

    def _score_d10_protocol(self, data: dict, raw_content: str) -> float:
        """D10 协议时效性: Version freshness + deprecation status."""
        score = self._score_generic(data)

        # Bonus: version follows semver
        version = str(data.get("version", ""))
        import re
        if re.match(r"\d+\.\d+\.\d+", version):
            score += 0.5

        # Bonus: last_updated or effective_date declared
        if data.get("last_updated") or data.get("effective_date"):
            score += 0.5

        # Penalty: deprecated without replacement
        if data.get("deprecated"):
            replacement = data.get("replacement")
            if not replacement:
                score -= 1.0

        return min(max(round(score, 2), 0.0), 10.0)

    def _score_d11_feasibility(self, data: dict, raw_content: str) -> float:
        """D11 工程可行性: Dependency completeness + implementation hints."""
        score = self._score_generic(data)

        # Bonus: dependencies declared (even empty = explicitly checked)
        if "dependencies" in data:
            score += 0.5
            deps = data.get("dependencies", [])
            if isinstance(deps, list) and deps:
                score += 0.5  # Has actual dependencies documented

        # Bonus: implementation hints
        if data.get("implementation") or data.get("implementation_notes"):
            score += 1.0

        # Penalty: no dependencies field and no checklist
        if "dependencies" not in data and not data.get("checklist"):
            score -= 1.0

        return min(max(round(score, 2), 0.0), 10.0)

    # Dimension → scorer mapping
    _DIMENSION_SCORERS: dict[str, Callable] = {
        "D3": _score_d3_security,
        "D5": _score_d5_resilience,
        "D7": _score_d7_testability,
        "D10": _score_d10_protocol,
        "D11": _score_d11_feasibility,
    }

    def _score_generic(self, data: dict) -> float:
        """Generic skill quality scoring (field completeness + checklist)."""
        score = 0.0

        # 1. Required field completeness (0-4 points)
        present = REQUIRED_CSDF_FIELDS & set(data.keys())
        field_ratio = len(present) / len(REQUIRED_CSDF_FIELDS) if REQUIRED_CSDF_FIELDS else 1.0
        score += 4.0 * field_ratio

        # 2. Checklist quality (0-3 points)
        checklist = data.get("checklist", [])
        if isinstance(checklist, list) and checklist:
            item_count = len(checklist)
            if item_count >= 8:
                score += 3.0
            elif item_count >= 5:
                score += 2.0
            elif item_count >= 2:
                score += 1.0
            else:
                score += 0.5

            severities = [
                item.get("severity", "") for item in checklist
                if isinstance(item, dict)
            ]
            if "critical" in severities:
                score += 0.5
        else:
            score += 0.3

        # 3. Description quality (0-1.5 points)
        desc = data.get("description", "")
        if desc and len(str(desc).strip()) > 20:
            score += 1.5
        elif desc:
            score += 0.7

        # 4. Weight/veto declaration (0-1 point)
        if "weight" in data:
            score += 0.5
        if "veto_rule" in data:
            score += 0.5

        return min(round(score, 2), 10.0)

    def _find_skill_yaml(self, skill_id: str) -> Optional[Path]:
        """Find the CSDF YAML file for a skill ID."""
        if not self._skills_dir.exists():
            return None
        for p in self._skills_dir.iterdir():
            if p.name.startswith(f"{skill_id}-") and p.suffix == ".yaml":
                return p
        return None

    def _fallback_score(self, key: str) -> float:
        """Generate a deterministic fallback score when skill files are unavailable."""
        seed = self._base_seed or int(
            hashlib.sha256(key.encode()).hexdigest()[:8], 16
        )
        combined = f"{key}:{seed}".encode()
        h = int(hashlib.sha256(combined).hexdigest()[:8], 16)
        return round(5.0 + (h % 5000) / 1000.0, 2)
