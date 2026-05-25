---
name: full-skill
version: "2.1.0"
authors:
  - alice
  - bob
tags:
  - testing
  - integration
  - quality
quality_threshold: 0.7
---

# Full Skill

A fully-featured skill for integration testing.

## Description

This skill exercises all CSDF fields including multiple authors,
tags, and a custom quality threshold.

## Instructions

1. Parse the CSDF frontmatter
2. Validate all required fields
3. Run quality checks
4. Register in the skill pool

## Examples

```python
from skillpool import SkillPool

pool = SkillPool()
pool.register("full-skill")
```

## Dependencies

- Python >= 3.10
- pydantic >= 2.0
