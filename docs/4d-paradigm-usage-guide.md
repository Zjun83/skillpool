# 4D Paradigm Usage Guide

> Version: 1.2.0 | Part of SkillPool — independent infrastructure

## What is 4D?

4D = **DocsDD → SDD → BDD → TDD**, a four-phase development paradigm where each phase produces specific artifacts and passes through a gate checkpoint before proceeding.

## Quick Start

### 1. Assess Complexity

```bash
skillpool gate assess --description "Add --output flag to CSV diff tool"
```

This returns a complexity level:

| Level | Keywords | Path | Example |
|-------|----------|------|---------|
| L0 | typo, comment, style | Direct edit | Fix a typo |
| L1 | config, flag, param | SDD → TDD | Add a CLI option |
| L2 | feature, module, refactor | DocsDD → SDD → BDD → TDD | New REST endpoint |
| L3+L2+ | subsystem, architecture, breaking | Full 4D + review | Rewrite auth system |

### 2. Execute Phases

Based on the complexity level, execute phases sequentially:

**L1 (Simple Task)**:
```
SDD → interface contract + error code → TDD → red-green-refactor
```

**L2 (Feature)**:
```
DocsDD → architecture doc → SDD → contract → BDD → scenarios → TDD → tests
```

**L3+L2+ (Breaking Change)**:
```
DocsDD → SDD → BDD → TDD → multi-dim-review checkpoint
```

### 3. Gate Enforcement

Each phase transition is gated. Use `skillpool gate status` to check current state:

```bash
skillpool gate status
# Shows: current_phase, phase_history, review_checkpoint
```

Reset gates for a new task:
```bash
skillpool gate reset
```

### 4. Checkpoint Reviews

After each phase, trigger the appropriate checkpoint:

```bash
skillpool review --checkpoint L1  # After DocsDD (shadow layer, non-blocking)
skillpool review --checkpoint L2  # After SDD (12-dim full + VETO)
skillpool review --checkpoint L3  # After BDD (baseline 5-dim + VETO)
skillpool review --checkpoint L4  # After TDD (baseline regression)
```

## Phase Details

### DocsDD (Documentation-Driven Development)

**Output**: Architecture doc, ops manual, acceptance checklist

**When to skip**: L1 tasks (config/flag/param) skip DocsDD entirely

**Key rule**: "DocsDD" = Documentation-Driven Development, NOT Domain-Driven Design

### SDD (Specification-Driven Development)

**Output**: Interface contracts, data schemas, error codes

**L1 Lightweight Mode**: Just function signature + 1 data schema + error code (skip full state machine)

**L1 Micro-SDD**: For single-function changes (<20 lines), produce just function signature + error code

### BDD (Behavior-Driven Development)

**Output**: Gherkin scenarios, behavioral rules, acceptance criteria

**When to skip**: L1 tasks skip BDD

**Key rule**: "The system should handle errors" is NOT a scenario. Must be: "When X, Then error Y with code SP-NNN"

### TDD (Test-Driven Development)

**Output**: Test files, coverage report ≥90% branch

**L1 Coverage**: 85% branch acceptable (vs 90% for L2+)

**Red-Green-Refactor cycle**:
1. RED: Write failing test
2. GREEN: Write minimum code to pass
3. REFACTOR: Clean up while keeping tests green

## CI Integration

Use `ci-4d-checkpoint.sh` in CI pipelines:

```bash
# In CI pipeline
/root/skillpool/scripts/ci-4d-checkpoint.sh --complexity L2 --state-path ./gate.json
```

Exit codes:
- 0: Validation passed
- 1: Validation failed
- 2: Invalid arguments

## Cost Estimation

Estimate token cost before executing:

```bash
skillpool cost estimate --skill-id dev-4d-orchestrator --skill-length 2000
```

Or via MCP:
```python
cost_estimate(skill_id="dev-4d-orchestrator", skill_length=2000)
```

## MCP Access

All 5 Skills are discoverable via SkillPool MCP:

- `skill://list` — All skills
- `skill://dev-4d-orchestrator/definition` — Orchestrator
- `skill://dev-4d-sdd/definition` — SDD
- `skill://dev-4d-bdd/definition` — BDD
- `skill://dev-4d-tdd/definition` — TDD
- `skill://dev-4d-docsdd/definition` — DocsDD

Tools: `skill_search`, `skill_get`, `cost_estimate`, `gate_check`, `gate_check_with_policy`

## Common Gotchas

1. Gate state persists across sessions — use `reset()` for new tasks
2. Emergency bypass requires `emergency_overrides.json` file, not just `enabled=True`
3. Gate key format: `{from_phase.lower()}_to_{to_phase.lower()}`
4. `review_checkpoint.triggered` auto-populates when entering REVIEW phase
5. File patterns in gate.policy match both full path and basename