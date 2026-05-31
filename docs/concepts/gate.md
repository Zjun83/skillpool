# Gate

The Gate enforces quality thresholds before skills can be materialized.

## Configuration

```python
from skillpool.gate import Gate, GateConfig

config = GateConfig(min_quality_score=0.5)
gate = Gate(config=config)
```

## Usage

```python
result = gate.check(quality_profile)
print(result.status)   # PASS or FAIL
print(result.overall_score)
print(result.dimension_results)
```

## GateResult Fields

| Field | Type | Description |
|-------|------|-------------|
| status | GateStatus | PASS or FAIL |
| overall_score | float | Weighted quality score |
| dimension_results | dict | Per-dimension pass/fail |
| min_quality_score | float | Configured threshold |
