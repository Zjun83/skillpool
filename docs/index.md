# SkillPool

**Structured skill management for AI agents.**

SkillPool provides a complete infrastructure for managing AI agent skills — from registration and quality profiling, through gate checks and materialization, to audit logging and telemetry.

## Key Features

- **CSDF Format** — Standardized skill definition with 12 quality dimensions
- **Registry** — JSONL-based skill registry with full CRUD operations
- **Quality Profiler** — Multi-dimensional quality scoring with weighted aggregation
- **Gate** — Configurable pass/fail quality gates
- **Materializer** — Agent-specific skill rendering with version history
- **Audit Log** — Immutable audit trail with correlation ID tracing
- **Telemetry** — Event-based observability with structured logging
- **MCP Server** — 7 Model Context Protocol tools for AI agent integration
- **Bridge** — WAL-based write-ahead logging and maintenance scheduling

## Quick Start

```bash
pip install skillpool
```

```python
from skillpool.registry import Registry, SkillEntry
from skillpool.csdf import CSDFDocument
from skillpool.quality import QualityProfiler
from skillpool.gate import Gate, GateConfig

# Register a skill
registry = Registry(registry_path=".skillpool/registry.jsonl")
entry = SkillEntry(name="my-skill", version="1.0.0", description="A useful skill")
registry.register(entry)

# Quality profile and gate check
doc = CSDFDocument(
    name="my-skill",
    version="1.0.0",
    description="A useful skill",
    dimensions={"completeness": 0.9, "accuracy": 0.85},
)
profile = QualityProfiler().profile(doc)
result = Gate(GateConfig(min_quality_score=0.5)).check(profile)
print(f"Gate: {result.status}")  # PASS
```
