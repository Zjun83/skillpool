# Gate Policy — SDD Interface Contracts

> Phase: SDD | Level: L2 | Date: 2026-06-04
> Prerequisite: DocsDD architecture doc + 16 AC

## 1. Interface Contracts

### 1.1 parser.py

```python
class GatePolicyError(Exception):
    """Base exception for gate policy errors.

    Attributes:
        error_code: One of GP001-GP006
        detail: Human-readable description
    """
    error_code: str
    detail: str


def load_gate_policy(policy_path: Path) -> GatePolicyConfig:
    """Parse gate.policy YAML file into validated config.

    Args:
        policy_path: Path to gate.policy YAML file.

    Returns:
        GatePolicyConfig: Frozen, validated configuration object.

    Raises:
        GatePolicyError: GP001 if file not found.
        GatePolicyError: GP002 if YAML parse or validation error.

    Contract:
        - Same path always returns structurally identical config (B10).
        - Config is frozen after creation (B11).
        - All 6 sections populated or use defaults.
    """


def resolve_level_for_path(
    file_path: str,
    policy: GatePolicyConfig,
) -> LevelResolution:
    """Resolve effective complexity level for a file path.

    Args:
        file_path: Relative file path (e.g., "src/core/engine.py").
        policy: Loaded gate policy configuration.

    Returns:
        LevelResolution with level, skip_phases, skip_all, matched_rules.

    Contract:
        - Applies directory_overrides first (longest-prefix match).
        - Then applies file_patterns (glob match).
        - minimum_level upgrades, maximum_level downgrades.
        - skip_phases merged (union).
        - Deterministic: same inputs → same outputs (B10).
    """
```

### 1.2 state_machine.py

```python
class GateStateMachine:
    """7-state FSM for 4D paradigm phase transitions.

    States: IDLE, ASSESSING, DOCSDD, SDD, BDD, TDD, REVIEW, COMPLETE

    Args:
        state_path: Path to gate.json file for persistence.

    Contract:
        - Loads state from gate.json on init (B04).
        - If gate.json missing/corrupt, starts at IDLE (GP006 logged).
        - All transitions logged to phase_history (B13).
    """

    @property
    def state(self) -> GateStateFile:
        """Current gate state (read from memory, synced to disk)."""

    def assess(
        self,
        task_description: str,
        changed_files: list[str],
        policy: GatePolicyConfig | None = None,
    ) -> str:
        """Assess complexity and set assessed_level.

        Args:
            task_description: Natural language task description.
            changed_files: List of changed file paths.
            policy: Optional policy for path-based level resolution.

        Returns:
            Assessed complexity level string (L0/L1/L2/L3+L2+).

        Side effects:
            - Transitions IDLE → ASSESSING.
            - Sets assessed_level in gate.json.
            - If L0, immediately transitions to COMPLETE.

        Raises:
            GatePolicyError: GP003 if not in IDLE state.
        """

    def transition(self, target_phase: str) -> GateStateFile:
        """Transition to target phase.

        Args:
            target_phase: One of IDLE, ASSESSING, DOCSDD, SDD, BDD, TDD, REVIEW, COMPLETE.

        Returns:
            Updated GateStateFile after transition.

        Raises:
            GatePolicyError: GP003 if transition is illegal from current phase.

        Side effects:
            - Updates gate.json on disk (atomic write).
            - Appends to phase_history (B13).
        """

    def check_gate(
        self,
        from_phase: str,
        to_phase: str,
        artifacts: dict[str, str | None],
        policy: GatePolicyConfig | None = None,
    ) -> GateCheckResult:
        """Check if gate transition is allowed given current artifacts.

        Args:
            from_phase: Current phase name.
            to_phase: Target phase name.
            artifacts: Dict of artifact name → status (None=pending, "done"=complete).
            policy: Optional policy for phase_gate rules.

        Returns:
            GateCheckResult(passed, missing_artifacts, validation_message).

        Note:
            Does NOT modify state. Pure check function.
        """

    def update_artifact(self, name: str, value: str) -> None:
        """Update artifact status in gate.json.

        Args:
            name: Artifact name (e.g., "architecture_doc", "test_files").
            value: Artifact status (e.g., "done", path to artifact).

        Side effects:
            - Updates gate.json artifacts section.
        """
```

### 1.3 incremental.py

```python
class IncrementalAssessor:
    """Detect changed files and assess per-file complexity.

    Args:
        policy: GatePolicyConfig for path-based level resolution.
        git_timeout: Max seconds for git diff command (default: 5).

    Contract:
        - git diff failure returns empty list, never crashes (B18).
        - Timeout enforced via subprocess timeout (B12).
    """

    def detect_changed_files(
        self,
        base_ref: str = "HEAD",
    ) -> list[str]:
        """Detect files changed since base_ref.

        Args:
            base_ref: Git ref to compare against (default: "HEAD").

        Returns:
            List of relative file paths.

        Raises:
            None. On failure, logs warning and returns [].

        Contract:
            - Uses `git diff --name-only <base_ref>`.
            - base_ref validated: alphanumeric, dots, dashes, slashes only.
            - Timeout: git_timeout seconds (B12).
            - Fallback: empty list on any error (B18).
        """

    def assess_complexity(
        self,
        files: list[str],
    ) -> ComplexityAssessment:
        """Assess complexity for a list of changed files.

        Args:
            files: List of relative file paths.

        Returns:
            ComplexityAssessment with level, per_file_levels, override_applied.

        Contract:
            - Empty files list → level=None (AC08).
            - Per-file level via resolve_level_for_path().
            - Aggregated level = highest across all files (AC10).
            - skip_phases = union of all files' skip_phases.
        """
```

### 1.4 gate.py Integration

```python
# Added to existing GateManager class:

def check_with_policy(
    self,
    csdf: dict,
    policy_path: Path | None = None,
    changed_files: list[str] | None = None,
) -> GatePolicyResult:
    """Gate check with policy-based phase enforcement.

    Args:
        csdf: CSDF skill definition dict.
        policy_path: Path to gate.policy file.
        changed_files: Optional list of changed files for incremental mode.

    Returns:
        GatePolicyResult(decision, reason, complexity, conditions,
                         policy_level, skip_phases, state).

    Contract:
        - If policy_path provided, loads and applies policy.
        - If changed_files provided, runs incremental assessment.
        - Creates GateStateMachine, assesses, and checks gate.
        - Does NOT modify existing check() method behavior.
    """
```

---

## 2. Data Schemas (Pydantic v2)

```python
from pydantic import BaseModel, Field
from typing import Literal


# ---- parser.py models ----

class DirectoryOverride(BaseModel):
    """Single directory override rule."""
    path: str
    minimum_level: str | None = None
    maximum_level: str | None = None
    skip_phases: list[str] = Field(default_factory=list)
    skip_all: bool = False
    reason: str = ""


class FilePattern(BaseModel):
    """File pattern override rule."""
    pattern: str
    skip_phases: list[str] = Field(default_factory=list)
    skip_all: bool = False
    maximum_level: str | None = None
    reason: str = ""


class PhaseGate(BaseModel):
    """Gate check rule for a phase transition.

    Note: Gate key format is '{from_phase.lower()}_to_{to_phase.lower()}'
    (e.g., 'sdd_to_bdd', 'docsdd_to_sdd').
    """
    required_artifacts: list[str] = Field(default_factory=list)
    validation: str = ""
    level_condition: str | None = None


class EmergencyBypass(BaseModel):
    """Emergency bypass configuration."""
    enabled: bool = False
    config_file: str = "emergency_overrides.json"
    allowed_phases: list[str] = Field(default_factory=lambda: ["SDD", "TDD"])
    max_duration_hours: int = 24
    require_retrospective: bool = True


class ReviewTrigger(BaseModel):
    """Review checkpoint trigger condition."""
    condition: str
    checkpoint: str = "L4"
    required: bool = True
    reason: str = ""


class EnforcementConfig(BaseModel):
    """Gate enforcement mode configuration."""
    mode: Literal["strict", "permissive", "disabled"] = "strict"
    hook_integration: bool = True
    log_all_transitions: bool = True
    audit_trail: bool = True


class GatePolicyConfig(BaseModel):
    """Complete gate.policy configuration. Frozen after creation (B11)."""
    model_config = {"frozen": True}

    version: str = "1.0"
    default_level: str = "L2"
    phase_gates: dict[str, PhaseGate] = Field(default_factory=dict)
    directory_overrides: list[DirectoryOverride] = Field(default_factory=list)
    file_patterns: list[FilePattern] = Field(default_factory=list)
    emergency_bypass: EmergencyBypass = Field(default_factory=EmergencyBypass)
    review_triggers: list[ReviewTrigger] = Field(default_factory=list)
    enforcement: EnforcementConfig = Field(default_factory=EnforcementConfig)


class LevelResolution(BaseModel):
    """Result of resolving complexity level for a path."""
    level: str
    skip_phases: list[str] = Field(default_factory=list)
    skip_all: bool = False
    matched_rules: list[str] = Field(default_factory=list)


# ---- state_machine.py models ----

class PhaseTransition(BaseModel):
    """Single phase transition record."""
    from_phase: str
    to_phase: str
    timestamp: str
    reason: str = ""


class ReviewCheckpoint(BaseModel):
    """Review checkpoint state."""
    triggered: bool = False
    checkpoint_level: str | None = None
    review_result: str | None = None
    veto_status: str | None = None


class GateMetadata(BaseModel):
    """Gate state metadata."""
    created_at: str | None = None
    updated_at: str | None = None
    session_id: str | None = None
    task_description: str | None = None


class GateStateFile(BaseModel):
    """gate.json runtime state."""
    incremental_mode: bool = True
    current_phase: str = "IDLE"
    assessed_level: str | None = None
    assessed_at: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    phase_history: list[PhaseTransition] = Field(default_factory=list)
    gate_checks: dict[str, str | None] = Field(default_factory=dict)
    artifacts: dict[str, str | None] = Field(default_factory=dict)
    review_checkpoint: ReviewCheckpoint = Field(default_factory=ReviewCheckpoint)
    metadata: GateMetadata = Field(default_factory=GateMetadata)


class GateCheckResult(BaseModel):
    """Result of a gate check between phases."""
    passed: bool
    missing_artifacts: list[str] = Field(default_factory=list)
    validation_message: str = ""


# ---- incremental.py models ----

class ComplexityAssessment(BaseModel):
    """Result of incremental complexity assessment."""
    level: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    per_file_levels: dict[str, str] = Field(default_factory=dict)
    override_applied: str | None = None


# ---- gate.py extension ----

class GatePolicyResult:
    """Extends GateResult with policy information.

    Note: Uses dataclass to match existing GateResult pattern.
    """
    decision: str          # From GateResult
    reason: str            # From GateResult
    complexity: object     # From GateResult (ComplexityScore | None)
    conditions: list       # From GateResult
    policy_level: str | None = None
    skip_phases: list[str] = Field(default_factory=list)
    state: GateStateFile | None = None
```

---

## 3. Error Code Table

| Code | Condition | Module | Recovery |
|------|-----------|--------|----------|
| GP001 | gate.policy file not found at `policy_path` | parser | Provide valid path or create file |
| GP002 | gate.policy YAML syntax error or Pydantic validation failure | parser | Fix YAML syntax or schema |
| GP003 | Illegal phase transition attempted | state_machine | Check current phase and legal transitions |
| GP004 | Required artifact missing for gate check | state_machine | Complete artifact before transition |
| GP005 | `git diff` execution failure (not a repo, timeout, etc.) | incremental | Ensure git repo or provide files manually |
| GP006 | gate.json read/write failure (permissions, disk, corrupt) | state_machine | Check permissions, reset state |

---

## 4. State Machine Definition

### 4.1 States

| State | Description | Entry Condition |
|-------|-------------|-----------------|
| IDLE | Initial state, no task assessed | Default |
| ASSESSING | Complexity assessment in progress | `assess()` called from IDLE |
| DOCSDD | Documentation-Driven Development phase | L2+ path, after ASSESSING |
| SDD | Specification-Driven Development phase | L1+ path, after ASSESSING or DOCSDD |
| BDD | Behavior-Driven Development phase | L2+ path, after SDD |
| TDD | Test-Driven Development phase | All levels, after SDD or BDD |
| REVIEW | Multi-dimension review checkpoint | L3+L2+ only, after TDD |
| COMPLETE | Task finished | After TDD (L0-L2) or REVIEW (L3+L2+) |

### 4.2 Legal Transitions

| From | To | Condition |
|------|----|-----------|
| IDLE | ASSESSING | `assess()` called |
| ASSESSING | COMPLETE | assessed_level == "L0" |
| ASSESSING | DOCSDD | assessed_level in ("L2", "L3+L2+") |
| ASSESSING | SDD | assessed_level == "L1" |
| DOCSDD | SDD | gate_check(docsdd_to_sdd) passed |
| SDD | BDD | assessed_level in ("L2", "L3+L2+") AND gate_check(sdd_to_bdd) passed |
| SDD | TDD | assessed_level == "L1" AND gate_check(sdd_to_bdd) not required |
| BDD | TDD | gate_check(bdd_to_tdd) passed |
| TDD | REVIEW | assessed_level == "L3+L2+" |
| TDD | COMPLETE | assessed_level in ("L0", "L1", "L2") |
| REVIEW | COMPLETE | review_checkpoint.veto_status is None |

### 4.3 Illegal Transitions (any not in above table)

Raise `GatePolicyError(GP003)` with message: `"Illegal transition: {from_phase} → {to_phase}"`

---

## 5. AC-to-Contract Traceability

| AC | Interface Contract | Data Model | Error Code |
|----|-------------------|------------|------------|
| AC01 | `load_gate_policy()` | `GatePolicyConfig` | GP001, GP002 |
| AC02 | `resolve_level_for_path()` | `LevelResolution` | — |
| AC03 | `resolve_level_for_path()` | `LevelResolution` | — |
| AC04 | `resolve_level_for_path()` | `LevelResolution` | — |
| AC05 | `GateStateMachine.transition()` | `GateStateFile` | GP003 |
| AC06 | `GateStateMachine.transition()` | `GateStateFile` | GP003 |
| AC07 | `GateStateMachine.__init__()` | `GateStateFile` | GP006 |
| AC08 | `IncrementalAssessor.assess_complexity()` | `ComplexityAssessment` | — |
| AC09 | `IncrementalAssessor.detect_changed_files()` | — | GP005 |
| AC10 | `IncrementalAssessor.assess_complexity()` | `ComplexityAssessment` | — |
| AC11 | `GateStateMachine.check_gate()` | `GateCheckResult` | GP003 |
| AC12 | `GateStateMachine.transition()` | `GateStateFile` | GP003 |
| AC13 | `GateStateMachine.transition()` | `GateStateFile` | — |
| AC14 | `GateManager.check_with_policy()` | `GatePolicyResult` | — |
| AC15 | (integration test) | — | — |
| AC16 | (coverage metric) | — | — |
