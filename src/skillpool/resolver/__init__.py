"""SkillResolver — skill chain resolution engine."""
from __future__ import annotations

import time
from typing import Optional

from skillpool.resolver.models import (
    Conflict,
    ConflictSeverity,
    ConflictType,
    DagEdge,
    DagEdgeType,
    Domain,
    ResolveStatus,
    ResolveStrategy,
    ResolvedSkill,
    SkillResolveRequest,
    SkillResolveResponse,
)
from skillpool.resolver.skill_graph import CycleDetected, SkillGraph
from skillpool.resolver.conflict_detector import ConflictDetector
from skillpool.resolver.health_filter import HealthFilter
from skillpool.resolver.cache import LRUCache
from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState
from skillpool.resolver.rate_limiter import RateLimiter


# Simulated skill registry for resolver (production: backed by Registry)
_SKILL_REGISTRY: dict[str, dict] = {}


def register_skill(skill_id: str, data: dict) -> None:
    """Register a skill in the resolver's local registry."""
    _SKILL_REGISTRY[skill_id] = data


def clear_registry() -> None:
    """Clear the resolver's local registry."""
    _SKILL_REGISTRY.clear()


class SkillResolver:
    """Resolve skill chains from CSDF definitions.

    Pipeline:
    1. Fetch skills from registry
    2. Build dependency DAG
    3. Cycle detection
    4. Conflict detection (Jaccard)
    5. Health filter
    6. Topological sort
    7. Apply constraints (max_skills, exclude, require_independent)
    8. Return resolved chain

    When a Registry is provided, skill metadata and lifecycle state are
    sourced from the Registry instead of the in-memory dict. The Registry
    provides proper 9-state lifecycle governance, supply chain evidence
    verification, and persistent storage.

    Usage:
        resolver = SkillResolver()
        response = resolver.resolve(SkillResolveRequest(skill_ids=["S01", "S05a"]))
    """

    def __init__(
        self,
        skill_registry: Optional[dict[str, dict]] = None,
        cache_max_size: int = 128,
        cache_ttl: float = 3600.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 30.0,
        rate_max_requests: int = 100,
        rate_window_seconds: float = 1.0,
        conflict_threshold: float = 0.5,
        min_health_score: float = 0.6,
        registry=None,
    ) -> None:
        self._registry_store = skill_registry if skill_registry is not None else _SKILL_REGISTRY
        self._cache = LRUCache(max_size=cache_max_size, ttl_seconds=cache_ttl)
        self._circuit = CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_timeout,
        )
        self._limiter = RateLimiter(
            max_requests=rate_max_requests,
            window_seconds=rate_window_seconds,
        )
        self._conflict_threshold = conflict_threshold
        self._min_health_score = min_health_score
        self._registry = registry

    @property
    def circuit_state(self) -> CircuitState:
        return self._circuit.state

    def resolve(self, request: SkillResolveRequest) -> SkillResolveResponse:
        """Resolve a skill chain from the request."""
        start = time.monotonic()

        # Rate limit check
        if not self._limiter.allow():
            return SkillResolveResponse(
                error="rate_limit_exceeded",
                degraded=True,
                resolution_time_ms=(time.monotonic() - start) * 1000,
            )

        # Circuit breaker check
        if not self._circuit.allow_request():
            return SkillResolveResponse(
                degraded=True,
                error="circuit_open",
                resolution_time_ms=(time.monotonic() - start) * 1000,
            )

        # Cache check
        cache_key = LRUCache.make_key(
            request.skill_ids,
            strategy=request.strategy.value,
            max_skills=request.max_skills,
            exclude=request.exclude_skills,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            cached.from_cache = True
            cached.resolution_time_ms = (time.monotonic() - start) * 1000
            return cached

        # Resolve
        try:
            response = self._do_resolve(request)
            self._circuit.record_success()
        except CycleDetected as e:
            self._circuit.record_failure()
            return SkillResolveResponse(
                error=str(e),
                resolution_time_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            self._circuit.record_failure()
            return SkillResolveResponse(
                error=str(e),
                degraded=True,
                resolution_time_ms=(time.monotonic() - start) * 1000,
            )

        # Cache result
        self._cache.put(cache_key, response)
        response.resolution_time_ms = (time.monotonic() - start) * 1000
        return response

    def _do_resolve(self, request: SkillResolveRequest) -> SkillResolveResponse:
        """Core resolution logic."""
        # 1. Fetch skills
        fetched = self._fetch_skills(request.skill_ids)
        if not fetched:
            return SkillResolveResponse(
                error="no_skills_found",
                status=ResolveStatus.UNRESOLVED,
            )

        # 2. Build DAG
        graph = self._build_dag(fetched)

        # 3. Cycle detection
        graph.topological_sort()  # raises CycleDetected

        # 4. Conflict detection
        conflict_detector = ConflictDetector(threshold=self._conflict_threshold)
        for sid, sdata in fetched.items():
            conflict_detector.register(
                skill_id=sid,
                name=sdata.get("name", ""),
                dimension=sdata.get("dimension", ""),
                namespaces=sdata.get("namespaces", []),
            )
        raw_conflicts = conflict_detector.detect()

        # 5. Health filter
        skills_list = [
            {"skill_id": sid, **sdata}
            for sid, sdata in fetched.items()
        ]
        hf = HealthFilter(min_score=request.min_health_score)
        passed, excluded = hf.filter(skills_list)

        # 6. Apply exclude filter
        if request.exclude_skills:
            passed = [s for s in passed if s["skill_id"] not in request.exclude_skills]
            excluded.extend(request.exclude_skills)

        # 7. Topological sort
        passed_ids = {s["skill_id"] for s in passed}
        subgraph = graph.subgraph(passed_ids)
        sorted_ids = subgraph.topological_sort()

        # 8. Apply max_skills constraint
        sorted_ids = sorted_ids[: request.max_skills]

        # 9. Build response
        resolved = []
        for sid in sorted_ids:
            sdata = fetched.get(sid, {})
            # Find conflict severity for this skill
            conflict_sev = None
            for c in raw_conflicts:
                if c["skill_a"] == sid or c["skill_b"] == sid:
                    conflict_sev = ConflictSeverity(c["severity"])
                    break

            resolved.append(ResolvedSkill(
                skill_id=sid,
                name=sdata.get("name", ""),
                version=sdata.get("version", "1.0.0"),
                dimension=sdata.get("dimension", ""),
                domain=sdata.get("domain", ""),
                weight=sdata.get("weight", 0.0),
                health_score=sdata.get("health_score", 1.0),
                trust_level=sdata.get("trust_level", 3),
                dependencies=sdata.get("dependencies", []),
                estimated_tokens=sdata.get("estimated_tokens", 0),
                provides=sdata.get("provides", []),
                conflict=conflict_sev,
            ))

        conflicts = [
            Conflict(**c) for c in raw_conflicts
        ]

        dag_edges = [
            DagEdge(source=src, target=tgt, weight=w, type=DagEdgeType.DEPENDS_ON)
            for src, tgt, w in graph.get_edges()
            if src in passed_ids and tgt in passed_ids
        ]

        # Build health_scores mapping
        health_scores = {s.skill_id: s.health_score for s in resolved}

        # Calculate feasibility_score = f(health_scores, conflicts)
        avg_health = sum(health_scores.values()) / len(health_scores) if health_scores else 0.0
        conflict_penalty = len(conflicts) * 0.1  # Each conflict reduces feasibility by 0.1
        feasibility_score = max(0.0, min(1.0, avg_health - conflict_penalty))

        # Determine status
        if len(resolved) == 0:
            status = ResolveStatus.UNRESOLVED
        elif len(resolved) < len(request.skill_ids):
            status = ResolveStatus.PARTIAL
        else:
            status = ResolveStatus.RESOLVED

        return SkillResolveResponse(
            resolved=resolved,
            conflicts=conflicts,
            excluded=excluded,
            dag_edges=dag_edges,
            total_skills=len(resolved),
            status=status,
            health_scores=health_scores,
            feasibility_score=feasibility_score,
        )

    def _fetch_skills(self, skill_ids: list[str]) -> dict[str, dict]:
        """Fetch skills from registry, including transitive dependencies.

        When a Registry is configured, reads skill metadata from the Registry
        (the authoritative source) and skips skills that are not enabled.
        Otherwise falls back to the in-memory dict store.
        """
        fetched: dict[str, dict] = {}
        queue = list(skill_ids)

        while queue:
            sid = queue.pop(0)
            if sid in fetched:
                continue

            # Try Registry first (authoritative source)
            if self._registry is not None:
                record = self._registry.get_skill(sid)
                if record is None:
                    continue
                # Skip non-enabled skills from Registry
                if not self._registry.is_enabled(sid):
                    continue
                meta = record.metadata
                sdata = {
                    "name": meta.name,
                    "version": meta.version,
                    "dimension": "",
                    "namespaces": meta.tags,
                    "dependencies": meta.dependencies,
                    "weight": meta.quality_score,
                    "health_score": 1.0,  # Enabled = healthy
                    "trust_level": 3,
                }
            else:
                sdata = self._registry_store.get(sid)
                if sdata is None:
                    continue

            fetched[sid] = sdata
            # Follow dependencies
            for dep in sdata.get("dependencies", []):
                if dep not in fetched:
                    queue.append(dep)

        return fetched

    def _build_dag(self, skills: dict[str, dict]) -> SkillGraph:
        """Build a SkillGraph from skill definitions."""
        graph = SkillGraph()
        for sid, sdata in skills.items():
            graph.add_node(sid)
            for dep in sdata.get("dependencies", []):
                if dep in skills:
                    graph.add_edge(dep, sid, weight=sdata.get("weight", 1.0))
        return graph
