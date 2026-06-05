"""Health models — Pydantic schemas for health check."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ServingStatus(StrEnum):
    SERVING = "SERVING"
    NOT_SERVING = "NOT_SERVING"
    DEGRADED = "DEGRADED"


class DegradationLevel(StrEnum):
    L0_FULL = "L0_full"              # Full functionality
    L1_PARTIAL = "L1_partial"        # Partial degradation (non-critical components down)
    L2_BM25_ONLY = "L2_bm25_only"    # BM25-only fallback (vector search down)
    L3_DISABLED = "L3_disabled"      # Minimal/disabled functionality


class ComponentHealth(BaseModel):
    """Health status of a single component."""
    component: str
    status: ServingStatus = ServingStatus.SERVING
    latency_p99_ms: float = 0.0
    message: str = ""
    metadata: dict = Field(default_factory=dict)
    fallback_mode: str = Field(default="", description="Fallback mode: vpls_vector/bm25_keyword/sqlite_fts5")


class HealthCheckResponse(BaseModel):
    """Aggregated health check response."""
    status: ServingStatus = ServingStatus.SERVING
    components: list[ComponentHealth] = Field(default_factory=list)
    timestamp: str = ""
    degradation_level: DegradationLevel = Field(default=DegradationLevel.L0_FULL, description="Current degradation level (L0-L3)")
    vpls_latency_p99_ms: float = Field(default=0.0, description="VPLS P99 latency in ms")
