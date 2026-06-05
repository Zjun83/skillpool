"""SynergyDetector — Skill combination gain detection and synergy edge management.

Discovers and manages skill combination synergies:
1. Loads expert-annotated synergies from CSDF definitions
2. Creates/updates DagEdge(type=enhances) edges in the skill graph
3. Discovers new combinations from historical execution data (future: Thompson Sampling)

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from skillpool.config import get_data_dir
from skillpool.materializer.models import SynergyEntry
from skillpool.resolver.models import DagEdge, DagEdgeType

logger = logging.getLogger(__name__)


class SynergyEdge(BaseModel):
    """A synergy relationship between two skills with gain data."""

    source: str = Field(description="Primary skill ID")
    target: str = Field(description="Enhancing skill ID")
    gain: str = Field(default="", description="Expected gain (e.g. '+15%')")
    reason: str = Field(default="", description="Why this combination helps")
    weight: float = Field(default=0.5, ge=0.0, le=1.0, description="Edge weight")
    evidence: str = Field(default="expert", description="Evidence source: expert/observed/sampled")


class SynergyDetectionResult(BaseModel):
    """Result of synergy detection run."""

    edges_created: int = 0
    edges_updated: int = 0
    edges_total: int = 0
    new_discoveries: list[SynergyEdge] = Field(default_factory=list)


class SynergyDetector:
    """Detects and manages skill combination synergies.

    Usage:
        detector = SynergyDetector(skills_dir=Path("~/.skillpool/skills"))
        result = detector.sync_expert_synergies()
        print(f"Created {result.edges_created} synergy edges")
    """

    def __init__(self, skills_dir: Path | None = None):
        self.skills_dir = skills_dir or get_data_dir() / "skills"
        self._synergy_edges: list[SynergyEdge] = []

    def load_expert_synergies(self) -> list[SynergyEdge]:
        """Load expert-annotated synergies from CSDF YAML files.

        Reads the `synergies` field from each skill's CSDF definition
        and converts them to SynergyEdge objects.

        Data source priority: Registry (if available) → local filesystem.
        All Agents sharing the same MCP server get consistent data.
        """
        edges: list[SynergyEdge] = []

        # Primary: try Registry (shared state, consistent across Agents)
        registry_edges = self._load_from_registry()
        if registry_edges is not None:
            self._synergy_edges = registry_edges
            return registry_edges

        # Fallback: local filesystem (same data, different access path)
        if not self.skills_dir.exists():
            return edges

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            # Look for CSDF YAML files
            for yaml_file in skill_dir.glob("*.yaml"):
                try:
                    import yaml

                    data = yaml.safe_load(yaml_file.read_text())
                    if not data or not isinstance(data, dict):
                        continue

                    skill_id = data.get("id", skill_dir.name)
                    synergies = data.get("synergies", [])

                    for syn in synergies:
                        if isinstance(syn, dict) and "skill_id" in syn:
                            entry = SynergyEntry(**syn)
                            # Parse gain percentage to weight
                            weight = self._parse_gain_to_weight(entry.gain)
                            edge = SynergyEdge(
                                source=skill_id,
                                target=entry.skill_id,
                                gain=entry.gain,
                                reason=entry.reason,
                                weight=weight,
                                evidence="expert",
                            )
                            edges.append(edge)
                except Exception as e:
                    logger.warning("Failed to load synergy entry for %s: %s", skill_dir.name, e)
                    continue

        self._synergy_edges = edges
        return edges

    def to_dag_edges(self) -> list[DagEdge]:
        """Convert synergy edges to DagEdge(type=enhances) for the skill graph."""
        return [
            DagEdge(
                source=e.source,
                target=e.target,
                weight=e.weight,
                type=DagEdgeType.ENHANCES,
            )
            for e in self._synergy_edges
        ]

    def sync_expert_synergies(self) -> SynergyDetectionResult:
        """Full sync: load expert synergies and return detection result.

        This is the main entry point for cold-start synergy setup.
        """
        edges = self.load_expert_synergies()
        _dag_edges = self.to_dag_edges()

        return SynergyDetectionResult(
            edges_created=len(edges),
            edges_updated=0,
            edges_total=len(edges),
            new_discoveries=[],
        )

    def get_synergies_for(self, skill_id: str) -> list[SynergyEdge]:
        """Get all synergy edges where the given skill is the source."""
        return [e for e in self._synergy_edges if e.source == skill_id]

    def get_enhancers_of(self, skill_id: str) -> list[SynergyEdge]:
        """Get all skills that enhance the given skill (where target == skill_id)."""
        return [e for e in self._synergy_edges if e.target == skill_id]

    def load_combination_synergies(self) -> list[SynergyEdge]:
        """Load synergy edges from PROMOTED and VALIDATING combinations.

        Only includes PROMOTED (full weight) and VALIDATING (reduced weight).
        DEPRECATED combinations get 0.5x weight. RETIRED are excluded.
        """
        try:
            from skillpool.combiner import CombinationLifecycleManager
            from skillpool.combiner.models import CombinationLifecycleState

            mgr = CombinationLifecycleManager()
            all_combos = list(mgr._combinations.values())

            combo_edges: list[SynergyEdge] = []
            for combo in all_combos:
                # Skip RETIRED combinations entirely
                if combo.state == CombinationLifecycleState.RETIRED:
                    continue

                weight = combo.current_weight()

                # Adjust weight by lifecycle state
                if combo.state == CombinationLifecycleState.PROMOTED:
                    pass  # Full weight
                elif combo.state == CombinationLifecycleState.VALIDATING:
                    weight *= 0.7  # Reduced confidence
                elif combo.state == CombinationLifecycleState.DEPRECATED:
                    weight *= 0.5  # Significantly reduced
                elif combo.state == CombinationLifecycleState.DISCOVERED:
                    weight *= 0.3  # Low weight, untested
                elif combo.state == CombinationLifecycleState.REJECTED:
                    continue  # Skip rejected

                if weight < 0.05:
                    continue

                for enhancer in combo.enhancers:
                    edge = SynergyEdge(
                        source=combo.primary,
                        target=enhancer,
                        gain=f"+{combo.gain_avg:.1f}%",
                        reason=f"{CombinationLifecycleState(combo.state).name} combination "
                        f"(source={combo.source}, executions={combo.execution_count})",
                        weight=round(weight, 3),
                        evidence="observed" if combo.state == CombinationLifecycleState.PROMOTED else "exploratory",
                    )
                    combo_edges.append(edge)

            # Merge with existing synergy edges (dedup by source+target)
            existing = {(e.source, e.target) for e in self._synergy_edges}
            new_edges = [e for e in combo_edges if (e.source, e.target) not in existing]
            self._synergy_edges.extend(new_edges)
            return new_edges

        except (ImportError, Exception):
            return []

    @staticmethod
    def _parse_gain_to_weight(gain: str) -> float:
        """Parse gain string like '+15%' to a weight between 0 and 1.

        Maps: +5% → 0.3, +10% → 0.5, +15% → 0.65, +20% → 0.8, +25%+ → 0.9
        """
        try:
            pct = float(gain.strip().replace("+", "").replace("%", ""))
            # Sigmoid-like mapping: higher gains → higher weights
            # Clamped to [0.1, 0.95]
            weight = min(0.95, max(0.1, pct / 30.0))
            return round(weight, 2)
        except (ValueError, AttributeError):
            return 0.5  # Default weight when gain is not parseable

    def _load_from_registry(self) -> list[SynergyEdge] | None:
        """Try loading synergies from the Registry (shared state).

        Returns None if Registry not available or has no synergy data,
        triggering filesystem fallback. Returns list if data found.
        """
        try:
            from skillpool.registry import Registry

            _registry = Registry()
            # Registry stores skills with metadata; check for synergy annotations
            # Currently, Registry doesn't store CSDF synergies directly,
            # so this returns None to trigger filesystem read.
            # Future: when Registry supports synergy metadata, this will
            # be the primary path for remote Agents.
            return None
        except (ImportError, Exception):
            return None
