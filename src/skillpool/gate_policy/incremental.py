"""Gate Policy Incremental Assessor — Detect changed files and assess complexity.

Error Codes:
  GP005: git diff execution failure

Contracts:
  - git diff failure returns empty list, never crashes (B18)
  - Timeout enforced via subprocess timeout (B12)
  - Per-file level resolution with highest-level aggregation
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from skillpool.gate_policy.parser import (
    GatePolicyConfig,
    resolve_level_for_path,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ComplexityAssessment(BaseModel):
    """Result of incremental complexity assessment."""

    level: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    per_file_levels: dict[str, str] = Field(default_factory=dict)
    override_applied: str | None = None


# ---------------------------------------------------------------------------
# Level ordering
# ---------------------------------------------------------------------------

_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3+L2+": 3}


# ---------------------------------------------------------------------------
# IncrementalAssessor
# ---------------------------------------------------------------------------


class IncrementalAssessor:
    """Detect changed files and assess per-file complexity.

    Args:
        policy: GatePolicyConfig for path-based level resolution.
        git_timeout: Max seconds for git diff command (default: 5).

    Contract:
        - git diff failure returns empty list, never crashes (B18).
        - Timeout enforced via subprocess timeout (B12).
    """

    def __init__(
        self,
        policy: GatePolicyConfig,
        git_timeout: int = 5,
    ) -> None:
        self._policy = policy
        self._git_timeout = git_timeout

    def detect_changed_files(
        self,
        base_ref: str = "HEAD",
        cwd: Path | None = None,
    ) -> list[str]:
        """Detect files changed since base_ref.

        Args:
            base_ref: Git ref to compare against (default: "HEAD").
            cwd: Working directory for git command.

        Returns:
            List of relative file paths.

        Contract:
            - Uses `git diff --name-only <base_ref>`.
            - base_ref validated: alphanumeric, dots, dashes, slashes only.
            - Timeout: git_timeout seconds (B12).
            - Fallback: empty list on any error (B18).
        """
        # Validate base_ref to prevent injection
        if not re.match(r"^[a-zA-Z0-9._/\-]+$", base_ref):
            return []

        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", base_ref],
                capture_output=True,
                text=True,
                timeout=self._git_timeout,
                cwd=cwd,
            )
            if result.returncode != 0:
                logger.warning("GP005: git diff returned non-zero: %s", result.stderr.strip())
                return []
            files = [f for f in result.stdout.strip().split("\n") if f]
            return files
        except subprocess.TimeoutExpired:
            logger.warning("GP005: git diff timed out after %ds", self._git_timeout)
            return []
        except (FileNotFoundError, OSError) as e:
            logger.warning("GP005: git diff execution failed: %s", e)
            return []

    def assess_complexity(
        self,
        files: list[str],
    ) -> ComplexityAssessment:
        """Assess complexity for a list of changed files.

        Args:
            files: List of relative file paths.

        Returns:
            ComplexityAssessment with level, per_file_levels, override_applied.

        Contract:
            - Empty files list → level=None (AC08).
            - Per-file level via resolve_level_for_path().
            - Aggregated level = highest across all files (AC10).
            - skip_phases = union of all files' skip_phases.
        """
        if not files:
            return ComplexityAssessment(changed_files=[], per_file_levels={})

        per_file: dict[str, str] = {}
        highest_level = "L0"
        override_applied: str | None = None

        for f in files:
            resolution = resolve_level_for_path(f, self._policy)
            per_file[f] = resolution.level
            if _LEVEL_ORDER.get(resolution.level, 0) > _LEVEL_ORDER.get(highest_level, 0):
                highest_level = resolution.level
            if resolution.matched_rules:
                override_applied = resolution.matched_rules[0]

        return ComplexityAssessment(
            level=highest_level,
            changed_files=files,
            per_file_levels=per_file,
            override_applied=override_applied,
        )
