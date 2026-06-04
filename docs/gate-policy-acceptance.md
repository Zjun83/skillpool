# Gate Policy — Acceptance Checklist

> Phase: DocsDD | Level: L2 | Date: 2026-06-04
> Total: 16 Acceptance Criteria (all quantified)

## Parser

- [ ] **AC01**: `load_gate_policy(valid_path)` returns `GatePolicyConfig` with all 6 sections populated (phase_gates, directory_overrides, file_patterns, emergency_bypass, review_triggers, enforcement)
- [ ] **AC02**: `resolve_level_for_path("src/core/feature.py", policy)` returns `LevelResolution(level="L2")` due to `minimum_level: L2` override
- [ ] **AC03**: `resolve_level_for_path("src/styles/theme.css", policy)` returns `LevelResolution(level="L1")` due to `maximum_level: L1` override
- [ ] **AC04**: `resolve_level_for_path("prototype/experiment.py", policy)` returns `LevelResolution(skip_all=True)`

## State Machine

- [ ] **AC05**: GateStateMachine transitions through all 7 legal paths: IDLE→ASSESSING→{COMPLETE|DOCSDD→SDD→{BDD→TDD|TDD}→{REVIEW→COMPLETE|COMPLETE}}
- [ ] **AC06**: Illegal transition (e.g., IDLE→TDD) raises `GatePolicyError` with error code `GP003`
- [ ] **AC07**: gate.json written atomically — temp file created, then `os.replace()` to final path; concurrent reads never see partial writes

## Incremental Mode

- [ ] **AC08**: When `incremental_mode=True` and `changed_files=[]`, `assess_complexity()` returns level=None (no assessment without changes)
- [ ] **AC09**: `detect_changed_files("HEAD")` returns list of file paths from `git diff --name-only HEAD`
- [ ] **AC10**: `assess_complexity(["src/core/a.py", "src/styles/b.css"], policy)` returns `level="L2"` (highest across files)

## Enforcement

- [ ] **AC11**: `emergency_bypass.allowed_phases` contains only `["SDD", "TDD"]`; attempting other phases during bypass raises GP003
- [ ] **AC12**: When `enforcement.mode="strict"`, illegal transition raises `GatePolicyError(GP003)`
- [ ] **AC13**: When `enforcement.mode="permissive"`, illegal transition logs warning and returns without raising

## Backward Compatibility

- [ ] **AC14**: Existing `GateManager.check(csdf)` method signature and behavior unchanged; `check_with_policy()` is a new separate method
- [ ] **AC15**: `pytest tests/test_gate.py` passes with 0 failures (no regressions)

## Coverage

- [ ] **AC16**: New code achieves `>= 90%` branch coverage as measured by `pytest --cov-branch --cov=skillpool.gate_policy --cov-fail-under=90`
