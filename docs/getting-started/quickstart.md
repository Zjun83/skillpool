# Quick Start

## 1. Create a Registry

```python
from skillpool.registry import Registry, SkillEntry

registry = Registry(registry_path=".skillpool/registry.jsonl")
```

## 2. Define a Skill (CSDF)

```python
from skillpool.csdf import CSDFDocument

doc = CSDFDocument(
    name="python-testing",
    version="1.0.0",
    description="Python testing best practices",
    triggers=["when writing tests", "when testing Python code"],
    dimensions={
        "completeness": 0.9,
        "accuracy": 0.85,
        "usability": 0.8,
        "maintainability": 0.75,
    },
    body="## Instructions\nWrite comprehensive tests.",
)
```

## 3. Register & Quality Check

```python
entry = SkillEntry(name=doc.name, version=doc.version, description=doc.description)
registry.register(entry)

from skillpool.quality import QualityProfiler
profile = QualityProfiler().profile(doc)
print(f"Quality: {profile.overall:.2f}")
```

## 4. Gate Check

```python
from skillpool.gate import Gate, GateConfig

gate = Gate(GateConfig(min_quality_score=0.5))
result = gate.check(profile)
print(f"Gate: {result.status}")  # PASS or FAIL
```

## 5. Materialize

```python
from skillpool.materializer import Materializer

materializer = Materializer(Path(".skillpool"))
mat_result = materializer.materialize(doc, agent_type="codex")
print(f"Materialized: {mat_result.success}")
```
