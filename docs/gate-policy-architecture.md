# Gate Policy Architecture — 4D Paradigm Implementation

> Phase: DocsDD | Level: L2 | Date: 2026-06-04

## 1. Overview

This document defines the architecture for implementing `gate.policy` parsing and `incremental mode` in SkillPool. The feature enables the 4D orchestrator to enforce development phase gating based on project-specific policy rules and incremental file-change detection.

## 2. Module Architecture

### 2.1 New Modules

| Module | Path | Responsibility |
|--------|------|---------------|
| `parser.py` | `src/skillpool/gate_policy/parser.py` | Parse gate.policy YAML, resolve directory/file-level overrides |
| `state_machine.py` | `src/skillpool/gate_policy/state_machine.py` | 7-state FSM for phase transitions, gate.json persistence |
| `incremental.py` | `src/skillpool/gate_policy/incremental.py` | Git diff detection, per-file complexity assessment |

### 2.2 Integration Point

| Existing | Change | Type |
|----------|--------|------|
| `gate.py` | Add `check_with_policy()` method to `GateManager` | Extension only |
| `mcp_server.py` | No change (deferred to follow-up) | — |

### 2.3 Data Flow

```
gate.policy (YAML)
     │
     ▼
  parser.py ──→ GatePolicyConfig (frozen Pydantic model)
     │
     ├── resolve_level_for_path() ──→ LevelResolution
     │
     ▼
  incremental.py ──→ detect_changed_files() ──→ list[str]
     │                   │
     │                   ▼
     │              assess_complexity() ──→ ComplexityAssessment
     │
     ▼
  state_machine.py
     │  ├── assess() ──→ set assessed_level in gate.json
     │  ├── transition() ──→ update current_phase in gate.json
     │  ├── check_gate() ──→ validate artifacts before transition
     │  └── update_artifact() ──→ record artifact status
     │
     ▼
  gate.py ──→ check_with_policy() ──→ GatePolicyResult
```

## 3. Component Design

### 3.1 parser.py

**GatePolicyConfig** (frozen Pydantic model):
- Validates all 6 sections of gate.policy
- Immutable after creation (B11: Policy config immutable after load)
- Caches resolved paths for deterministic results (B10)

**resolve_level_for_path()**:
- Input: file path string + GatePolicyConfig
- Process: directory_overrides → file_patterns → minimum/maximum_level
- Output: LevelResolution(level, skip_phases, skip_all, matched_rules)
- Matching: longest-prefix match for directory paths, glob match for file patterns
- Deterministic: same input always produces same output (B10)

### 3.2 state_machine.py

**7 States**: IDLE, ASSESSING, DOCSDD, SDD, BDD, TDD, REVIEW, COMPLETE

**Legal Transitions**:
| From | To | Condition |
|------|----|-----------|
| IDLE | ASSESSING | assess() called |
| ASSESSING | COMPLETE | assessed_level == L0 |
| ASSESSING | DOCSDD | assessed_level >= L2 |
| ASSESSING | SDD | assessed_level == L1 |
| DOCSDD | SDD | gate_check passed |
| SDD | BDD | assessed_level >= L2 AND gate_check passed |
| SDD | TDD | assessed_level == L1 AND gate_check passed |
| BDD | TDD | gate_check passed |
| TDD | REVIEW | assessed_level >= L3+L2+ |
| TDD | COMPLETE | assessed_level <= L2 |
| REVIEW | COMPLETE | review passed |

**gate.json Persistence** (B04):
- Write: atomic write via temp file + os.replace()
- Read: on state_machine init, load from disk
- Corrupt file: reset to IDLE state with warning log

### 3.3 incremental.py

**IncrementalAssessor**:
- `detect_changed_files()`: Run `git diff --name-only <base_ref>`
- Fallback: If git not available or not a git repo, return empty list (B18)
- Timeout: 5 seconds max (B12: must not block critical path)
- `assess_complexity()`: Per-file level resolution, aggregate to highest

**Complexity Aggregation**:
1. Resolve level for each changed file using `resolve_level_for_path()`
2. Take the highest level across all files
3. Merge skip_phases (union of all files' skip_phases)
4. Record per_file_levels in ComplexityAssessment

### 3.4 gate.py Integration

**`check_with_policy()`** on `GateManager`:
- Input: csdf dict + policy_path + changed_files (optional)
- Process:
  1. Load gate.policy → GatePolicyConfig
  2. If changed_files provided → IncrementalAssessor.assess_complexity()
  3. Create GateStateMachine → assess + transition
  4. Return GatePolicyResult (extends GateResult)
- Backward compatible: existing `check()` method unchanged

## 4. Error Handling

| Code | Condition | Recovery |
|------|-----------|----------|
| GP001 | gate.policy not found | Raise GatePolicyError, caller must provide valid path |
| GP002 | YAML parse error | Raise GatePolicyError with line number if available |
| GP003 | Illegal transition | Raise GatePolicyError, state unchanged |
| GP004 | Missing artifact for gate | Return GateCheckResult(passed=False, missing=...) |
| GP005 | git diff failure | Log warning, return empty changed_files list (B18) |
| GP006 | gate.json read/write failure | Log error, reset to IDLE state |

## 5. Constraints

- **No new external dependencies**: Use Pydantic (already in deps), subprocess for git
- **No existing interface breakage**: `GateManager.check()` signature unchanged
- **No MCP endpoint change**: Integration deferred to follow-up
- **Atomic gate.json writes**: Prevent corrupt state on crash
- **Frozen Pydantic models**: GatePolicyConfig immutable after parse

## 6. Security Considerations

- gate.policy path must be within project directory (no path traversal)
- git diff base_ref validated against injection (alphanumeric + dots only)
- gate.json write uses temp file + os.replace() (atomic, no partial writes)
- No dynamic code execution from gate.policy values
