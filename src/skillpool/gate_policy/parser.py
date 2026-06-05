"""Gate Policy Parser — Parse gate.policy YAML and resolve path-based overrides.

Error Codes:
  GP001: gate.policy file not found
  GP002: YAML parse or validation error

Contracts:
  - load_gate_policy(): Parse YAML → frozen GatePolicyConfig
  - resolve_level_for_path(): Path → LevelResolution with overrides applied
  - Deterministic: same inputs → same outputs (B10)
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from typing import Literal


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class GatePolicyError(Exception):
    """Base exception for gate policy errors.

    Attributes:
        error_code: One of GP001-GP006
        detail: Human-readable description
    """

    def __init__(self, error_code: str, detail: str):
        self.error_code = error_code
        self.detail = detail
        super().__init__(f"[{error_code}] {detail}")


# ---------------------------------------------------------------------------
# Pydantic Models (frozen for B11)
# ---------------------------------------------------------------------------


class DirectoryOverride(BaseModel):
    """Single directory override rule."""

    path: str
    minimum_level: str | None = None
    maximum_level: str | None = None
    skip_phases: list[str] = Field(default_factory=list)
    skip_all: bool = False
    reason: str = ""


class FilePattern(BaseModel):
    """File pattern override rule."""

    pattern: str
    skip_phases: list[str] = Field(default_factory=list)
    skip_all: bool = False
    maximum_level: str | None = None
    reason: str = ""


class PhaseGate(BaseModel):
    """Gate check rule for a phase transition."""

    required_artifacts: list[str] = Field(default_factory=list)
    validation: str = ""
    level_condition: str | None = None


class EmergencyBypass(BaseModel):
    """Emergency bypass configuration."""

    enabled: bool = False
    config_file: str = "emergency_overrides.json"
    allowed_phases: list[str] = Field(default_factory=lambda: ["SDD", "TDD"])
    max_duration_hours: int = 24
    require_retrospective: bool = True


class ReviewTrigger(BaseModel):
    """Review checkpoint trigger condition."""

    condition: str
    checkpoint: str = "L4"
    required: bool = True
    reason: str = ""


class EnforcementConfig(BaseModel):
    """Gate enforcement mode configuration."""

    mode: Literal["strict", "permissive", "disabled"] = "strict"
    hook_integration: bool = True
    log_all_transitions: bool = True
    audit_trail: bool = True


class GatePolicyConfig(BaseModel):
    """Complete gate.policy configuration. Frozen after creation (B11)."""

    model_config = {"frozen": True}

    version: str = "1.0"
    default_level: str = "L2"
    phase_gates: dict[str, PhaseGate] = Field(default_factory=dict)
    directory_overrides: list[DirectoryOverride] = Field(default_factory=list)
    file_patterns: list[FilePattern] = Field(default_factory=list)
    emergency_bypass: EmergencyBypass = Field(default_factory=EmergencyBypass)
    review_triggers: list[ReviewTrigger] = Field(default_factory=list)
    enforcement: EnforcementConfig = Field(default_factory=EnforcementConfig)


class LevelResolution(BaseModel):
    """Result of resolving complexity level for a path."""

    level: str
    skip_phases: list[str] = Field(default_factory=list)
    skip_all: bool = False
    matched_rules: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Level ordering for min/max comparisons
# ---------------------------------------------------------------------------

_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3+L2+": 3}


def _level_ge(a: str, b: str) -> bool:
    """Return True if level a >= level b."""
    return _LEVEL_ORDER.get(a, 0) >= _LEVEL_ORDER.get(b, 0)


def _max_level(a: str, b: str) -> str:
    """Return the higher of two levels."""
    return a if _LEVEL_ORDER.get(a, 0) >= _LEVEL_ORDER.get(b, 0) else b


def _min_level(a: str, b: str) -> str:
    """Return the lower of two levels."""
    return a if _LEVEL_ORDER.get(a, 0) <= _LEVEL_ORDER.get(b, 0) else b


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------


def load_gate_policy(policy_path: Path) -> GatePolicyConfig:
    """Parse gate.policy YAML file into validated config.

    Args:
        policy_path: Path to gate.policy YAML file.

    Returns:
        GatePolicyConfig: Frozen, validated configuration object.

    Raises:
        GatePolicyError: GP001 if file not found.
        GatePolicyError: GP002 if YAML parse or validation error.

    Contract:
        - Same path always returns structurally identical config (B10).
        - Config is frozen after creation (B11).
        - All 6 sections populated or use defaults.
    """
    if not policy_path.exists():
        raise GatePolicyError("GP001", f"gate.policy not found: {policy_path}")

    try:
        raw = yaml.safe_load(policy_path.read_text())
        if raw is None:
            raw = {}
        return GatePolicyConfig.model_validate(raw)
    except yaml.YAMLError as e:
        raise GatePolicyError("GP002", f"YAML parse error: {e}") from e
    except Exception as e:
        raise GatePolicyError("GP002", f"Validation error: {e}") from e


def resolve_level_for_path(
    file_path: str,
    policy: GatePolicyConfig,
) -> LevelResolution:
    """Resolve effective complexity level for a file path.

    Args:
        file_path: Relative file path (e.g., "src/core/engine.py").
        policy: Loaded gate policy configuration.

    Returns:
        LevelResolution with level, skip_phases, skip_all, matched_rules.

    Contract:
        - Applies directory_overrides first (longest-prefix match).
        - Then applies file_patterns (glob match).
        - minimum_level upgrades, maximum_level downgrades.
        - skip_phases merged (union).
        - Deterministic: same inputs → same outputs (B10).
    """
    level = policy.default_level
    skip_phases: set[str] = set()
    skip_all = False
    matched_rules: list[str] = []

    # Normalize path (remove leading ./ or /)
    norm_path = file_path.lstrip("./")

    # Step 1: Find longest-prefix matching directory override
    best_dir_match: DirectoryOverride | None = None
    best_dir_len = 0
    for override in policy.directory_overrides:
        opath = override.path.rstrip("/")
        if norm_path.startswith(opath + "/") or norm_path == opath:
            if len(opath) > best_dir_len:
                best_dir_match = override
                best_dir_len = len(opath)

    if best_dir_match:
        matched_rules.append(best_dir_match.path)
        if best_dir_match.minimum_level:
            if _level_ge(best_dir_match.minimum_level, level):
                level = best_dir_match.minimum_level
        if best_dir_match.maximum_level:
            # Cap level at maximum_level (level must not exceed maximum)
            if _LEVEL_ORDER.get(level, 0) > _LEVEL_ORDER.get(best_dir_match.maximum_level, 0):
                level = best_dir_match.maximum_level
        skip_phases.update(best_dir_match.skip_phases)
        if best_dir_match.skip_all:
            skip_all = True

    # Step 2: Apply file pattern matches
    for fp in policy.file_patterns:
        # Match against both full path and basename
        basename = norm_path.rsplit("/", 1)[-1] if "/" in norm_path else norm_path
        if fnmatch(norm_path, fp.pattern) or fnmatch(basename, fp.pattern):
            matched_rules.append(fp.pattern)
            if fp.maximum_level:
                # Cap level at maximum_level (level must not exceed maximum)
                if _LEVEL_ORDER.get(level, 0) > _LEVEL_ORDER.get(fp.maximum_level, 0):
                    level = fp.maximum_level
            skip_phases.update(fp.skip_phases)
            if fp.skip_all:
                skip_all = True

    return LevelResolution(
        level=level,
        skip_phases=sorted(skip_phases),
        skip_all=skip_all,
        matched_rules=matched_rules,
    )
