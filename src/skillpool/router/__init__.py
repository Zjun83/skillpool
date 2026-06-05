"""IntentRouter — Intent-to-skill routing with 3 layers (L1+L2 in cold start).

Routes agent intents (natural language descriptions) to optimal skill combinations:
  L1: Semantic matching (BGE-M3 embedding via Ollama, fallback to keyword matching)
  L2: Logical routing (DAG dependencies and skill graph topology)
  L3: Causal inference (historical combination data + Thompson Sampling, future)

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from skillpool.config import get_data_dir

logger = logging.getLogger(__name__)

# Ollama embedding endpoint — read from env to handle port conflicts
# (WSL2 mirrored mode can cause Windows iphlpsvc to hold 11434)
_OLLAMA_DEFAULT = "http://127.0.0.1:11434/api/embed"


class SkillCandidate(BaseModel):
    """A skill candidate returned by routing."""

    skill_id: str
    score: float = Field(ge=0.0, le=1.0, description="Match score [0,1]")
    layer: str = Field(description="Which routing layer produced this match: L1/L2/L3")
    reason: str = Field(default="", description="Why this skill matches")
    gain: str = Field(default="", description="Expected combination gain if applicable")


class RoutingResult(BaseModel):
    """Result of intent routing."""

    intent: str = Field(description="Original intent text")
    candidates: list[SkillCandidate] = Field(default_factory=list)
    primary: SkillCandidate | None = None
    enhancers: list[SkillCandidate] = Field(default_factory=list)
    layers_used: list[str] = Field(default_factory=list)


class IntentRouter:
    """Routes agent intents to optimal skill combinations.

    Usage:
        router = IntentRouter(skills_dir=Path("~/.skillpool/skills"))
        result = router.route("I need to do a code review")
        print(f"Primary: {result.primary.skill_id}")
        for e in result.enhancers:
            print(f"Enhancer: {e.skill_id} (+{e.gain})")
    """

    # Ollama embedding endpoint — read from env to handle port conflicts
    OLLAMA_EMBED_URL = os.environ.get("OLLAMA_EMBED_URL", _OLLAMA_DEFAULT)
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "bge-m3")

    def __init__(
        self,
        skills_dir: Path | None = None,
        ollama_url: str = OLLAMA_EMBED_URL,
        ollama_model: str = OLLAMA_MODEL,
    ):
        self.skills_dir = skills_dir or get_data_dir() / "skills"
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self._skill_index: dict[str, dict] = {}
        self._embeddings: dict[str, list[float]] = {}
        self._ollama_available: bool | None = None

    def _check_ollama(self) -> bool:
        """Check if Ollama is available, auto-detecting port if default fails."""
        if self._ollama_available is not None:
            return self._ollama_available

        from urllib.parse import urlparse

        parsed = urlparse(self.ollama_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        # Try configured URL first
        if self._try_ollama_base(base_url):
            self._ollama_available = True
            return True

        # Auto-detect: if default port 11434 failed, try 11435 (WSL2 conflict fallback)
        if ":11434" in base_url:
            alt_base = base_url.replace(":11434", ":11435")
            if self._try_ollama_base(alt_base):
                # Update URL to working port
                self.ollama_url = self.ollama_url.replace(":11434", ":11435")
                logger.info("Ollama auto-detected on port 11435 (11434 unavailable)")
                self._ollama_available = True
                return True

        self._ollama_available = False
        return self._ollama_available

    @staticmethod
    def _try_ollama_base(base_url: str) -> bool:
        """Try connecting to Ollama at the given base URL."""
        try:
            resp = httpx.get(f"{base_url}/api/tags", timeout=3.0)
            return resp.status_code == 200
        except Exception as e:
            logger.debug("Ollama connection failed at %s: %s", base_url, e)
            return False

    def _embed(self, text: str) -> list[float] | None:
        """Get embedding for text via Ollama BGE-M3."""
        if not self._check_ollama():
            return None
        try:
            resp = httpx.post(
                self.ollama_url,
                json={"model": self.ollama_model, "input": text},
                timeout=10.0,
            )
            data = resp.json()
            return data.get("embeddings", [[]])[0]
        except Exception as e:
            logger.debug("Ollama embedding failed, falling back to keyword matching: %s", e)
            return None

    def _build_index(self) -> None:
        """Build skill index from skills directory (subdirectories + flat YAMLs)."""
        if self._skill_index:
            return

        if not self.skills_dir.exists():
            return

        for child in self.skills_dir.iterdir():
            # Directory-based skills (e.g., multi-dim-review/)
            if child.is_dir():
                skill_id = child.name
                desc_parts = []
                skill_md = child / "SKILL.md"
                if skill_md.exists():
                    desc_parts.append(skill_md.read_text()[:500])
                for yaml_file in child.glob("*.yaml"):
                    desc_parts.extend(self._extract_yaml_metadata(yaml_file))
                if desc_parts:
                    self._skill_index[skill_id] = {
                        "description": " ".join(desc_parts),
                        "skill_id": skill_id,
                    }
            # Flat YAML skills (e.g., S09-resilience-degradation.yaml)
            elif child.suffix == ".yaml":
                skill_id = child.stem
                desc_parts = self._extract_yaml_metadata(child)
                if desc_parts:
                    self._skill_index[skill_id] = {
                        "description": " ".join(desc_parts),
                        "skill_id": skill_id,
                    }

    @staticmethod
    def _extract_yaml_metadata(yaml_file: Path) -> list[str]:
        """Extract description, dimension, name from a CSDF YAML file."""
        parts = []
        try:
            import yaml

            data = yaml.safe_load(yaml_file.read_text())
            if isinstance(data, dict):
                if data.get("description"):
                    parts.append(str(data["description"]))
                if data.get("dimension"):
                    parts.append(f"dimension:{data['dimension']}")
                if data.get("name"):
                    parts.append(str(data["name"]))
        except Exception as e:
            logger.debug("Failed to parse YAML metadata from %s: %s", yaml_file, e)
        return parts

    def route(self, intent: str, top_k: int = 5) -> RoutingResult:
        """Route an intent to optimal skill combination.

        Args:
            intent: Natural language description of what the agent wants to do
            top_k: Maximum number of candidates to return

        Returns:
            RoutingResult with primary skill and enhancers
        """
        self._build_index()

        if not self._skill_index:
            return RoutingResult(intent=intent)

        # L1: Semantic routing
        l1_candidates = self._route_l1_semantic(intent, top_k)
        layers_used = ["L1"]

        # L2: Logical routing (DAG dependencies)
        l2_candidates = self._route_l2_logical(l1_candidates)
        if l2_candidates:
            layers_used.append("L2")

        # L3: Causal routing (combination gain data)
        l3_candidates = self._route_l3_causal(l1_candidates)
        if l3_candidates:
            layers_used.append("L3")

        # L4: Predictive routing (collaborative filtering + gain decay)
        l4_candidates = self._route_l4_predictive(l1_candidates)
        if l4_candidates:
            layers_used.append("L4")

        # Merge candidates
        all_candidates = l1_candidates + l2_candidates + l3_candidates + l4_candidates

        # Deduplicate by skill_id, keeping highest score
        seen: dict[str, SkillCandidate] = {}
        for c in all_candidates:
            if c.skill_id not in seen or c.score > seen[c.skill_id].score:
                seen[c.skill_id] = c

        # Sort by score
        sorted_candidates = sorted(seen.values(), key=lambda c: c.score, reverse=True)[:top_k]

        # Split into primary + enhancers
        primary = sorted_candidates[0] if sorted_candidates else None
        enhancers = sorted_candidates[1:] if len(sorted_candidates) > 1 else []

        return RoutingResult(
            intent=intent,
            candidates=sorted_candidates,
            primary=primary,
            enhancers=enhancers,
            layers_used=layers_used,
        )

    def _route_l1_semantic(self, intent: str, top_k: int) -> list[SkillCandidate]:
        """L1: Semantic matching via BGE-M3 or keyword fallback."""
        # Try embedding-based matching
        intent_emb = self._embed(intent)
        if intent_emb and self._skill_index:
            # Compute embeddings for all skills (lazy, cached)
            return self._match_by_embedding(intent_emb, top_k)

        # Fallback: keyword matching
        return self._match_by_keyword(intent, top_k)

    def _match_by_embedding(self, intent_emb: list[float], top_k: int) -> list[SkillCandidate]:
        """Match intent embedding against skill embeddings."""
        candidates: list[SkillCandidate] = []

        for skill_id, meta in self._skill_index.items():
            if skill_id not in self._embeddings:
                emb = self._embed(meta["description"])
                if emb:
                    self._embeddings[skill_id] = emb
                else:
                    continue

            skill_emb = self._embeddings[skill_id]
            score = self._cosine_similarity(intent_emb, skill_emb)
            candidates.append(
                SkillCandidate(
                    skill_id=skill_id,
                    score=round(score, 4),
                    layer="L1",
                    reason=f"Semantic similarity: {score:.3f}",
                )
            )

        return sorted(candidates, key=lambda c: c.score, reverse=True)[:top_k]

    def _match_by_keyword(self, intent: str, top_k: int) -> list[SkillCandidate]:
        """Fallback: keyword-based matching when Ollama unavailable."""
        intent_lower = intent.lower()
        intent_words = set(intent_lower.split())
        candidates: list[SkillCandidate] = []

        for skill_id, meta in self._skill_index.items():
            desc_lower = meta["description"].lower()
            desc_words = set(desc_lower.split())

            # Jaccard-like overlap score
            overlap = len(intent_words & desc_words)
            total = len(intent_words | desc_words)
            score = overlap / total if total > 0 else 0.0

            # Boost if skill_id appears in intent
            if skill_id.lower() in intent_lower:
                score = max(score, 0.7)

            # Boost for dimension match
            if any(f"dimension:{d}" in desc_lower for d in ["d3", "d5", "d7", "d11"]):
                for dim in ["d3", "d5", "d7", "d11"]:
                    if dim in intent_lower and f"dimension:{dim}" in desc_lower:
                        score = min(1.0, score + 0.2)

            if score > 0:
                candidates.append(
                    SkillCandidate(
                        skill_id=skill_id,
                        score=round(score, 4),
                        layer="L1",
                        reason=f"Keyword match: {overlap} words overlap",
                    )
                )

        return sorted(candidates, key=lambda c: c.score, reverse=True)[:top_k]

    def _route_l2_logical(self, l1_candidates: list[SkillCandidate]) -> list[SkillCandidate]:
        """L2: Add skills from DAG dependencies and synergy edges."""
        l2_candidates: list[SkillCandidate] = []
        l1_skill_ids = {c.skill_id for c in l1_candidates}

        for candidate in l1_candidates:
            # Find YAML sources for this skill (directory or flat YAML)
            yaml_sources = self._find_skill_yaml(candidate.skill_id)

            for yaml_file, data in yaml_sources:
                # Add dependencies
                deps = data.get("dependencies", [])
                if isinstance(deps, list):
                    for dep in deps:
                        if isinstance(dep, dict):
                            dep_id = dep.get("skill_id", dep.get("id", ""))
                        else:
                            dep_id = str(dep)
                        if dep_id and dep_id not in l1_skill_ids:
                            l2_candidates.append(
                                SkillCandidate(
                                    skill_id=dep_id,
                                    score=round(candidate.score * 0.7, 4),
                                    layer="L2",
                                    reason=f"Dependency of {candidate.skill_id}",
                                )
                            )

                # Add synergies
                synergies = data.get("synergies", [])
                if isinstance(synergies, list):
                    for syn in synergies:
                        if isinstance(syn, dict):
                            syn_id = syn.get("skill_id", "")
                            gain = syn.get("gain", "")
                            reason = syn.get("reason", "")
                        else:
                            continue
                        if syn_id and syn_id not in l1_skill_ids:
                            l2_candidates.append(
                                SkillCandidate(
                                    skill_id=syn_id,
                                    score=round(candidate.score * 0.8, 4),
                                    layer="L2",
                                    reason=f"Synergy with {candidate.skill_id}: {reason}",
                                    gain=gain,
                                )
                            )
                            if syn_id and syn_id not in l1_skill_ids:
                                l2_candidates.append(
                                    SkillCandidate(
                                        skill_id=syn_id,
                                        score=round(candidate.score * 0.8, 4),
                                        layer="L2",
                                        reason=f"Synergy with {candidate.skill_id}: {reason}",
                                        gain=gain,
                                    )
                                )

        return l2_candidates

    def _find_skill_yaml(self, skill_id: str) -> list[tuple[Path, dict]]:
        """Find YAML sources for a skill (directory or flat YAML)."""
        results = []
        # Directory-based: skills/<skill_id>/*.yaml
        skill_dir = self.skills_dir / skill_id
        if skill_dir.is_dir():
            for yaml_file in skill_dir.glob("*.yaml"):
                try:
                    import yaml

                    data = yaml.safe_load(yaml_file.read_text())
                    if isinstance(data, dict):
                        results.append((yaml_file, data))
                except Exception as e:
                    logger.debug("Failed to load skill YAML %s: %s", yaml_file, e)
                    continue
        # Flat YAML: skills/<skill_id>.yaml
        flat_yaml = self.skills_dir / f"{skill_id}.yaml"
        if flat_yaml.exists():
            try:
                import yaml

                data = yaml.safe_load(flat_yaml.read_text())
                if isinstance(data, dict):
                    results.append((flat_yaml, data))
            except Exception as e:
                logger.debug("Failed to load flat YAML %s: %s", flat_yaml, e)
        return results

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _route_l3_causal(self, l1_candidates: list[SkillCandidate]) -> list[SkillCandidate]:
        """L3: Causal routing — recommend skills from historical combination gain data.

        Uses GainTracker to find skills that have positive combination gain
        with the L1 candidates.
        """
        try:
            from skillpool.gain import GainTracker
        except ImportError:
            return []

        l3_candidates: list[SkillCandidate] = []
        l1_skill_ids = {c.skill_id for c in l1_candidates}

        tracker = GainTracker()
        for candidate in l1_candidates:
            # Check combination gain with other skills
            for other_id in self._skill_index:
                if other_id in l1_skill_ids:
                    continue
                gain = tracker.combination_gain(candidate.skill_id, other_id)
                if gain > 0.5:  # Only include meaningful positive gain
                    l3_candidates.append(
                        SkillCandidate(
                            skill_id=other_id,
                            score=round(min(1.0, candidate.score * 0.6 + gain * 0.04), 4),
                            layer="L3",
                            reason=f"Causal gain with {candidate.skill_id}: +{gain:.1f}",
                            gain=f"+{gain:.1f}",
                        )
                    )

        return sorted(l3_candidates, key=lambda c: c.score, reverse=True)[:5]

    def _route_l4_predictive(self, l1_candidates: list[SkillCandidate]) -> list[SkillCandidate]:
        """L4: Predictive routing — collaborative filtering + gain decay.

        Uses CombinationLifecycleManager to find PROMOTED combinations
        and recommend enhancers with dynamic weight.
        """
        try:
            from skillpool.combiner import CombinationLifecycleManager
        except ImportError:
            return []

        l4_candidates: list[SkillCandidate] = []
        l1_skill_ids = {c.skill_id for c in l1_candidates}

        lifecycle_mgr = CombinationLifecycleManager()
        for candidate in l1_candidates:
            promoted = lifecycle_mgr.get_promoted_combinations(candidate.skill_id)
            for combo in promoted:
                for enhancer in combo.enhancers:
                    if enhancer in l1_skill_ids:
                        continue
                    weight = combo.current_weight()
                    if weight > 0.1:  # Only include meaningful weights
                        l4_candidates.append(
                            SkillCandidate(
                                skill_id=enhancer,
                                score=round(weight, 4),
                                layer="L4",
                                reason=f"Predicted: {combo.combination_id} (weight={weight:.2f})",
                                gain=f"+{combo.gain_avg:.1f}" if combo.gain_avg > 0 else "",
                            )
                        )

        return sorted(l4_candidates, key=lambda c: c.score, reverse=True)[:5]
