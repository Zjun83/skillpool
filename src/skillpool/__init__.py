"""SkillPool — Skill lifecycle management system."""

from skillpool.audit import AuditLayer, AuditRecord, AuditUnavailableError, log_event
from skillpool.clawmem_client import ClawMemClient
from skillpool.cost import CostManager
from skillpool.evolver import EvolverLayer, EvolutionProposal, DefectSeverity
from skillpool.gate import GateManager

# graph is lazy-imported via __getattr__ (numpy/scipy are optional)
from skillpool.health import HealthManager
from skillpool.lifecycle import SkillLifecycleState
from skillpool.materializer import Materializer
from skillpool.monitor import MonitorLayer, TelemetryBridge, FiveDimensionEvaluation
from skillpool.paradigm import ParadigmRegistry
from skillpool.profile import AgentCapabilityProfile
from skillpool.registry import Registry, SkillRecord, SkillStatus
from skillpool.resolver import SkillResolver
from skillpool.review import ReviewManager
from skillpool.telemetry import TelemetryBridge as CoreTelemetryBridge


def __getattr__(name: str):
    """Lazy import for graph module (numpy/scipy are optional dependencies)."""
    if name in ("personalized_pagerank", "reverse_ppr"):
        from skillpool.graph import personalized_pagerank, reverse_ppr  # noqa: F401

        return locals().get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Audit
    "AuditLayer",
    "AuditRecord",
    "AuditUnavailableError",
    "log_event",
    # ClawMem
    "ClawMemClient",
    # Cost
    "CostManager",
    # Evolver
    "EvolverLayer",
    "EvolutionProposal",
    "DefectSeverity",
    # Gate
    "GateManager",
    # Graph
    "personalized_pagerank",
    "reverse_ppr",
    # Health
    "HealthManager",
    # Lifecycle
    "SkillLifecycleState",
    # Materializer
    "Materializer",
    # Monitor
    "MonitorLayer",
    "TelemetryBridge",
    "FiveDimensionEvaluation",
    # Paradigm
    "ParadigmRegistry",
    # Profile
    "AgentCapabilityProfile",
    # Registry
    "Registry",
    "SkillRecord",
    "SkillStatus",
    # Resolver
    "SkillResolver",
    # Review
    "ReviewManager",
    # Core telemetry
    "CoreTelemetryBridge",
]
