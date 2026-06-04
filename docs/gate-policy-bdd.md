# Gate Policy — BDD Gherkin Scenarios

> Phase: BDD | Level: L2 | Date: 2026-06-04
> Prerequisite: SDD interface contracts + 6 error codes

## Feature 1: Gate Policy Parsing

```gherkin
Feature: Gate Policy Parsing
  As a SkillPool agent
  I want to load and parse gate.policy files
  So that I can enforce project-specific development phase rules

  Scenario: Valid policy file loads all sections
    Given a gate.policy file exists at "/path/to/gate.policy"
    And the file contains valid YAML with all 6 sections
    When load_gate_policy is called with that path
    Then the result is a GatePolicyConfig with phase_gates populated
    And directory_overrides contains at least 1 entry
    And file_patterns contains at least 1 entry
    And enforcement.mode is "strict"

  Scenario: Missing policy file raises GP001
    Given no file exists at "/nonexistent/gate.policy"
    When load_gate_policy is called with that path
    Then GatePolicyError is raised with error code "GP001"

  Scenario: Invalid YAML raises GP002
    Given a file exists at "/path/to/bad.policy"
    And the file contains "invalid: [yaml: {broken"
    When load_gate_policy is called with that path
    Then GatePolicyError is raised with error code "GP002"
```

## Feature 2: Directory Override Resolution

```gherkin
Feature: Directory Override Resolution
  As a SkillPool agent
  I want to resolve complexity levels based on file paths
  So that different project areas can have different 4D requirements

  Scenario: Core directory minimum L2
    Given a GatePolicyConfig with directory_override path "src/core/" and minimum_level "L2"
    When resolve_level_for_path is called with "src/core/engine.py"
    Then the result level is "L2"
    And matched_rules contains "src/core/"

  Scenario: Styles directory maximum L1
    Given a GatePolicyConfig with directory_override path "src/styles/" and maximum_level "L1"
    When resolve_level_for_path is called with "src/styles/theme.css"
    Then the result level is "L1"
    And matched_rules contains "src/styles/"

  Scenario: Prototype directory skip all
    Given a GatePolicyConfig with directory_override path "prototype/" and skip_all "true"
    When resolve_level_for_path is called with "prototype/experiment.py"
    Then the result skip_all is True
    And matched_rules contains "prototype/"

  Scenario: Unmatched path uses default level
    Given a GatePolicyConfig with default_level "L2"
    When resolve_level_for_path is called with "random/file.py"
    Then the result level is "L2"
    And matched_rules is empty

  Scenario: Longest prefix match wins
    Given a GatePolicyConfig with directory_override path "src/" minimum_level "L1"
    And directory_override path "src/core/" minimum_level "L2"
    When resolve_level_for_path is called with "src/core/engine.py"
    Then the result level is "L2"
    And matched_rules contains "src/core/"

  Scenario: File pattern matches basename for nested paths
    Given a GatePolicyConfig with file_pattern "__init__.py" skip_phases ["DOCSDD", "BDD"]
    When resolve_level_for_path is called with "src/deep/nested/__init__.py"
    Then the result skip_phases contains "DOCSDD" and "BDD"
    And matched_rules contains "__init__.py"
```

## Feature 3: Gate State Machine

```gherkin
Feature: Gate State Machine
  As a SkillPool agent
  I want to track and enforce 4D phase transitions
  So that development follows the DocsDD→SDD→BDD→TDD sequence

  Scenario: L2 task transitions through all phases
    Given a GateStateMachine in IDLE state
    When assess is called with assessed_level "L2"
    Then current_phase is "ASSESSING"
    When transition is called with target "DOCSDD"
    Then current_phase is "DOCSDD"
    When transition is called with target "SDD"
    Then current_phase is "SDD"
    When transition is called with target "BDD"
    Then current_phase is "BDD"
    When transition is called with target "TDD"
    Then current_phase is "TDD"
    When transition is called with target "COMPLETE"
    Then current_phase is "COMPLETE"

  Scenario: L1 task skips DocsDD and BDD
    Given a GateStateMachine in IDLE state
    When assess is called with assessed_level "L1"
    And transition is called with target "SDD"
    And transition is called with target "TDD"
    And transition is called with target "COMPLETE"
    Then current_phase is "COMPLETE"
    And phase_history contains 4 transitions

  Scenario: L0 task goes directly to COMPLETE
    Given a GateStateMachine in IDLE state
    When assess is called with assessed_level "L0"
    Then current_phase is "COMPLETE"
    And phase_history contains 2 transitions (IDLE→ASSESSING, ASSESSING→COMPLETE)

  Scenario: Illegal transition raises GP003
    Given a GateStateMachine in IDLE state
    When transition is called with target "TDD"
    Then GatePolicyError is raised with error code "GP003"
    And current_phase is still "IDLE"

  Scenario: Gate check validates required artifacts
    Given a GateStateMachine in SDD phase
    And phase_gate "sdd_to_bdd" requires artifacts ["interface_contracts", "data_schemas"]
    When check_gate is called from "SDD" to "BDD" with artifacts {"interface_contracts": "done"}
    Then the result passed is False
    And missing_artifacts contains "data_schemas"

  Scenario: Gate state persists to gate.json
    Given a GateStateMachine with state_path "/tmp/test_gate.json"
    When assess is called with assessed_level "L2"
    And transition is called with target "DOCSDD"
    Then the file "/tmp/test_gate.json" exists
    And its current_phase field is "DOCSDD"
```

## Feature 4: Incremental Mode

```gherkin
Feature: Incremental Mode
  As a SkillPool agent
  I want to detect changed files and assess their complexity
  So that existing codebases can adopt 4D incrementally

  Scenario: Changed files detected via git diff
    Given a git repository with 3 modified files
    When detect_changed_files is called with base_ref "HEAD"
    Then the result contains 3 file paths

  Scenario: Mixed complexity takes highest level
    Given a GatePolicyConfig with src/core/ minimum L2 and src/styles/ maximum L1
    And changed files ["src/core/engine.py", "src/styles/theme.css"]
    When assess_complexity is called
    Then the result level is "L2"
    And per_file_levels contains {"src/core/engine.py": "L2", "src/styles/theme.css": "L1"}

  Scenario: Empty changed files returns None level
    Given an IncrementalAssessor
    When assess_complexity is called with empty files list
    Then the result level is None

  Scenario: Git diff failure returns empty list
    Given a non-git directory
    When detect_changed_files is called
    Then the result is an empty list
    And no exception is raised
```

## Feature 5: Enforcement Mode

```gherkin
Feature: Enforcement Mode
  As a SkillPool operator
  I want to control gate enforcement strictness
  So that I can balance safety with development velocity

  Scenario: Strict mode blocks illegal transitions
    Given a GatePolicyConfig with enforcement mode "strict"
    And a GateStateMachine in IDLE state
    When transition is called with target "TDD"
    Then GatePolicyError is raised with error code "GP003"

  Scenario: Permissive mode logs warning on illegal transition
    Given a GatePolicyConfig with enforcement mode "permissive"
    And a GateStateMachine in IDLE state
    When transition is called with target "TDD"
    Then no exception is raised
    And a warning is logged
    And current_phase is still "IDLE"

  Scenario: Emergency bypass only allows SDD and TDD phases
    Given a GatePolicyConfig with emergency_bypass enabled
    And emergency_bypass allowed_phases ["SDD", "TDD"]
    When check_gate is called for transition to "BDD"
    Then the result passed is False

  Scenario: Emergency bypass requires override file to exist
    Given a GatePolicyConfig with emergency_bypass enabled
    And no emergency_overrides.json file exists
    When check_gate is called for any transition
    Then emergency bypass is NOT active
    And normal gate rules apply

  Scenario: Emergency bypass with expired override file is inactive
    Given a GatePolicyConfig with emergency_bypass enabled
    And emergency_overrides.json exists with expires_at in the past
    When check_gate is called for any transition
    Then emergency bypass is NOT active
    And normal gate rules apply
```

## Feature 6: MCP Tool Integration

```gherkin
Feature: Gate Check With Policy MCP Tool
  As an external Agent
  I want to call gate_check_with_policy via MCP
  So that I can get policy-aware gate decisions without direct filesystem access

  Scenario: Policy-aware gate check returns policy level
    Given a valid gate.policy file exists
    When gate_check_with_policy is called with csdf and policy_path
    Then the result includes policy_level field
    And the result includes skip_phases field
    And the result includes state field with current_phase

  Scenario: Gate check without policy path returns base result
    When gate_check_with_policy is called without policy_path
    Then the result includes decision from base gate_check
    And policy_level is None
    And skip_phases is empty

  Scenario: Invalid policy path returns base result with error info
    Given a nonexistent policy path
    When gate_check_with_policy is called with that path
    Then the result includes decision from base gate_check
    And policy_level is None
```

---

## Behavioral Rules Mapping

| Rule | Description | Scenario Coverage | SDD Contract |
|------|-------------|-------------------|--------------|
| B04 | gate.json persists across process restarts | Feature 3: Gate state persists | GateStateMachine.__init__ |
| B05 | emergency_overrides expire after timeout | Feature 5: Emergency bypass | EmergencyBypass.max_duration_hours |
| B10 | Gate assessment deterministic | Feature 2: Unmatched path, Longest prefix | resolve_level_for_path |
| B11 | Policy config immutable after load | Feature 1: Valid policy loads | GatePolicyConfig (frozen) |
| B12 | Incremental detection must not block | Feature 4: Git diff failure | IncrementalAssessor git_timeout |
| B13 | Audit trail for gate transitions | Feature 3: L2 task transitions | GateStateMachine.phase_history |
| B17 | Feature flags must not bypass gate checks | Feature 5: Strict mode blocks | EnforcementConfig.mode |
| B18 | git diff failure must not crash | Feature 4: Git diff failure | IncrementalAssessor fallback |

---

## Traceability Matrix (AC × Scenario × Contract × Error Code)

| AC | Scenario | SDD Contract | Error Code |
|----|----------|-------------|------------|
| AC01 | F1: Valid policy file loads all sections | load_gate_policy() | GP001, GP002 |
| AC02 | F2: Core directory minimum L2 | resolve_level_for_path() | — |
| AC03 | F2: Styles directory maximum L1 | resolve_level_for_path() | — |
| AC04 | F2: Prototype directory skip all | resolve_level_for_path() | — |
| AC05 | F3: L2 task transitions through all phases | GateStateMachine.transition() | GP003 |
| AC06 | F3: Illegal transition raises GP003 | GateStateMachine.transition() | GP003 |
| AC07 | F3: Gate state persists to gate.json | GateStateMachine.__init__() | GP006 |
| AC08 | F4: Empty changed files returns None level | IncrementalAssessor.assess_complexity() | — |
| AC09 | F4: Changed files detected via git diff | IncrementalAssessor.detect_changed_files() | GP005 |
| AC10 | F4: Mixed complexity takes highest level | IncrementalAssessor.assess_complexity() | — |
| AC11 | F5: Emergency bypass only allows SDD and TDD | GateStateMachine.check_gate() | GP003 |
| AC12 | F5: Strict mode blocks illegal transitions | GateStateMachine.transition() | GP003 |
| AC13 | F5: Permissive mode logs warning | GateStateMachine.transition() | — |
| AC14 | (integration test in TDD) | GateManager.check_with_policy() | — |
| AC15 | (integration test in TDD) | — | — |
| AC16 | (coverage metric in TDD) | — | — |

**Coverage**: 14/16 ACs have direct BDD scenario mapping (AC14-AC16 are integration/coverage, covered in TDD phase)
