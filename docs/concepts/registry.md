# Registry

The Registry is the central store for skill metadata.

## Overview

- **Format**: JSONL (one JSON object per line)
- **Operations**: Register, Get, Update, Delete, List, Count
- **Thread-safe**: Uses file-based locking

## Usage

```python
from skillpool.registry import Registry, SkillEntry

registry = Registry(registry_path=".skillpool/registry.jsonl")

# Register
entry = SkillEntry(name="my-skill", version="1.0.0", description="A skill")
registry.register(entry)

# Get
skill = registry.get("my-skill")
print(skill.name, skill.version)

# Update
registry.update("my-skill", {"quality_score": 0.85, "version": "1.1.0"})

# List all
for entry in registry.list_entries():
    print(entry.name, entry.quality_score)

# Count
total = registry.count()

# Delete
registry.delete("my-skill")
```

## SkillEntry Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | str | Yes | Unique identifier |
| version | str | Yes | Semantic version |
| description | str | No | Human-readable summary |
| tags | list[str] | No | Categorization labels |
| quality_score | float | No | Aggregated quality score |
