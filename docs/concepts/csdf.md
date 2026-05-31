# CSDF — Canonical Skill Definition Format

CSDF is the standard format for defining skills in SkillPool.

## Structure

```python
from skillpool.csdf import CSDFDocument

doc = CSDFDocument(
    name="skill-name",          # Required: unique identifier
    version="1.0.0",            # Required: semantic version
    description="What it does", # Optional: human-readable summary
    triggers=["when X"],        # Optional: activation conditions
    dimensions={                # Optional: quality scores (0-1)
        "completeness": 0.9,
        "accuracy": 0.85,
    },
    body="## Instructions\n...", # Optional: skill content
)
```

## 12 Quality Dimensions

| Dimension | Weight | Description |
|-----------|--------|-------------|
| completeness | 0.12 | Coverage of the domain |
| accuracy | 0.12 | Correctness of information |
| usability | 0.10 | Ease of application |
| maintainability | 0.08 | Long-term upkeep cost |
| performance | 0.08 | Runtime efficiency |
| security | 0.10 | Safety considerations |
| reliability | 0.10 | Consistency of results |
| adaptability | 0.07 | Flexibility across contexts |
| documentation | 0.08 | Quality of docs |
| testability | 0.05 | Ease of verification |
| interoperability | 0.05 | Integration capability |
| observability | 0.05 | Monitoring support |

## Serialization

CSDF documents serialize to JSON and round-trip cleanly:

```python
data = doc.model_dump()
json_str = json.dumps(data)
restored = CSDFDocument(**json.loads(json_str))
assert restored.name == doc.name
```
