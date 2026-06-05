"""LazySkillLoader — tiered skill loading for token-efficient context delivery.

Three loading tiers:
  L0 (metadata):  id, name, version, dimension, weight, tags  — ~50 tokens
  L1 (summary):   L0 + description + checklist summary        — ~200 tokens
  L2 (full def):  complete SKILL.md via Materializer           — full token cost

L0 reads YAML frontmatter only (no materialization).
L1 adds the description field from the CSDF dict.
L2 runs the full Materializer.materialize() pipeline.

Uses shared csdf_loader for CSDF loading (eliminates duplication with mcp_server).

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional


from skillpool.config import get_data_dir
from skillpool.materializer import Materializer
from skillpool.materializer.csdf_loader import load_csdf
from skillpool.materializer.models import MaterializationResult
from skillpool.profile import CLAUDE_CODE_PROFILE, AgentCapabilityProfile

_SKILLS_DIR = get_data_dir() / "skills"

_VALID_TIERS = {"L0", "L1", "L2"}

logger = logging.getLogger("skillpool.lazy_loader")


class LazySkillLoader:
    """Tiered skill loader with in-memory cache and thread safety.

    Usage:
        loader = LazySkillLoader()
        meta = loader.load("S09", tier="L0")       # cheap metadata
        summary = loader.upgrade("S09", "L0", "L1") # add description
        full = loader.upgrade("S09", "L1", "L2")    # full materialization
    """

    def __init__(
        self,
        profile: Optional[AgentCapabilityProfile] = None,
        skills_dir: Optional[Path] = None,
    ):
        self._profile = profile or CLAUDE_CODE_PROFILE
        self._skills_dir = skills_dir or _SKILLS_DIR
        # Cache: {skill_id: {"L0": dict, "L1": dict, "L2": dict}}
        self._cache: dict[str, dict[str, dict]] = {}
        # Track file modification times for cache invalidation
        self._mtimes: dict[str, float] = {}
        self._lock = threading.Lock()

    def load(self, skill_id: str, tier: str = "L0") -> dict:
        """Load a skill at the specified tier.

        Args:
            skill_id: Skill identifier (e.g., "S09", "scaffold-docs")
            tier: Loading tier — "L0", "L1", or "L2"

        Returns:
            Dict with skill data at the requested tier.
            Includes a "_tier" key indicating the loaded tier.

        Raises:
            ValueError: If tier is invalid or skill_id not found.
        """
        # Part of SkillPool — independent infrastructure, shared by all agents
        self._validate_tier(tier)

        with self._lock:
            # Check for cache invalidation (file modified)
            self._check_invalidation(skill_id)

            # Return cached if available
            if skill_id in self._cache and tier in self._cache[skill_id]:
                return self._cache[skill_id][tier]

        # Load CSDF outside lock (I/O bound)
        csdf = load_csdf(skill_id, self._skills_dir)
        if csdf is None:
            raise ValueError(f"Skill not found: {skill_id}")

        with self._lock:
            # Ensure cache entry exists
            if skill_id not in self._cache:
                self._cache[skill_id] = {}

            # Build tiers incrementally
            self._ensure_tiers(skill_id, csdf, tier)

            return self._cache[skill_id][tier]

    def preload(self, skill_ids: list[str], tier: str = "L0") -> dict[str, dict]:
        """Batch-load multiple skills at the specified tier.

        Args:
            skill_ids: List of skill identifiers
            tier: Loading tier for all skills

        Returns:
            Dict mapping skill_id to its loaded data. Skills that fail
            to load are omitted from the result.
        """
        # Part of SkillPool — independent infrastructure, shared by all agents
        self._validate_tier(tier)
        results = {}
        for sid in skill_ids:
            try:
                results[sid] = self.load(sid, tier=tier)
            except ValueError:
                logger.debug("preload skipped missing skill: %s", sid)
                continue
        return results

    def upgrade(self, skill_id: str, from_tier: str, to_tier: str) -> dict:
        """Load more detail for an already-loaded skill.

        Args:
            skill_id: Skill identifier
            from_tier: Current tier (must already be loaded)
            to_tier: Target tier (must be higher than from_tier)

        Returns:
            Dict with skill data at the target tier.

        Raises:
            ValueError: If skill not cached, from_tier not loaded,
                        or invalid tier ordering.
        """
        # Part of SkillPool — independent infrastructure, shared by all agents
        self._validate_tier(from_tier)
        self._validate_tier(to_tier)

        tier_order = {"L0": 0, "L1": 1, "L2": 2}
        if tier_order[to_tier] <= tier_order[from_tier]:
            raise ValueError(f"to_tier ({to_tier}) must be higher than from_tier ({from_tier})")

        with self._lock:
            if skill_id not in self._cache:
                raise ValueError(f"Skill {skill_id} not in cache — call load() first")

            if from_tier not in self._cache[skill_id]:
                raise ValueError(f"Skill {skill_id} not loaded at {from_tier} — load it first")

        # Re-load at the higher tier (uses cache for lower tiers)
        return self.load(skill_id, tier=to_tier)

    def clear_cache(self, skill_id: str | None = None) -> None:
        """Clear cached data for a skill, or all skills if skill_id is None."""
        with self._lock:
            if skill_id is None:
                self._cache.clear()
                self._mtimes.clear()
            else:
                self._cache.pop(skill_id, None)
                self._mtimes.pop(skill_id, None)

    # ── Internal helpers ──────────────────────────────────────────

    def _check_invalidation(self, skill_id: str) -> None:
        """Check if cached data is stale (file modified since last load).

        Must be called with self._lock held.
        """
        # Try to find the source file
        yaml_path = self._skills_dir / f"{skill_id}.yaml"
        if not yaml_path.exists():
            for p in self._skills_dir.glob(f"{skill_id}_*.yaml"):
                yaml_path = p
                break

        if not yaml_path.exists():
            # Directory-based skill
            md_path = self._skills_dir / skill_id / "SKILL.md"
            if md_path.exists():
                yaml_path = md_path

        if yaml_path.exists():
            try:
                mtime = yaml_path.stat().st_mtime
                if skill_id in self._mtimes and self._mtimes[skill_id] != mtime:
                    logger.info("Cache invalidated for %s (file modified)", skill_id)
                    self._cache.pop(skill_id, None)
                self._mtimes[skill_id] = mtime
            except OSError:
                pass

    def _ensure_tiers(self, skill_id: str, csdf: dict, target_tier: str) -> None:
        """Build cache entries up to the target tier, starting from L0.

        Must be called with self._lock held.
        """
        cache = self._cache[skill_id]

        # L0: metadata only (~50 tokens)
        if "L0" not in cache:
            cache["L0"] = {
                "id": csdf.get("id", skill_id),
                "name": csdf.get("name", ""),
                "version": csdf.get("version", ""),
                "dimension": csdf.get("dimension", ""),
                "weight": csdf.get("weight", 0),
                "tags": csdf.get("tags", []),
                "_tier": "L0",
            }

        if target_tier == "L0":
            return

        # L1: L0 + description + checklist summary (~200 tokens)
        if "L1" not in cache:
            l0 = cache["L0"]
            checklist_summary = []
            for item in csdf.get("checklist", []):
                if isinstance(item, dict):
                    checklist_summary.append(
                        {
                            "id": item.get("id", ""),
                            "description": item.get("description", ""),
                            "severity": item.get("severity", ""),
                        }
                    )
            cache["L1"] = {
                **l0,
                "description": csdf.get("description", ""),
                "checklist_summary": checklist_summary,
                "_tier": "L1",
            }

        if target_tier == "L1":
            return

        # L2: full materialization via Materializer
        if "L2" not in cache:
            mat = Materializer(profile=self._profile)
            result: MaterializationResult = mat.materialize(csdf_dict=csdf)
            l2_data = {
                **cache["L1"],
                "_tier": "L2",
            }
            # Preserve raw markdown body for directory-based skills
            if "_markdown_body" in csdf:
                l2_data["_markdown_body"] = csdf["_markdown_body"]
            if result.status == "success" and result.skill is not None:
                l2_data["markdown"] = result.skill.markdown
                l2_data["token_count"] = result.skill.token_count
            else:
                logger.warning("L2 materialization failed for %s: %s", skill_id, result.errors)
                l2_data["markdown"] = ""
                l2_data["token_count"] = 0
                l2_data["_materialization_errors"] = result.errors
            cache["L2"] = l2_data

    @staticmethod
    def _validate_tier(tier: str) -> None:
        if tier not in _VALID_TIERS:
            raise ValueError(f"Invalid tier '{tier}'; must be one of {sorted(_VALID_TIERS)}")
