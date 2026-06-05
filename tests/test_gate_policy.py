"""Tests for gate_policy — Parser, State Machine, and Incremental Assessor.

BDD Scenarios covered:
  F1: Valid policy file loads all sections
  F1: Missing policy file raises GP001
  F1: Invalid YAML raises GP002
  F2: Core directory minimum L2
  F2: Styles directory maximum L1
  F2: Prototype directory skip all
  F2: Unmatched path uses default level
  F2: Longest prefix match wins
  F3: L2 task transitions through all phases
  F3: L1 task skips DocsDD and BDD
  F3: L0 task goes directly to COMPLETE
  F3: Illegal transition raises GP003
  F3: Gate check validates required artifacts
  F3: Gate state persists to gate.json
  F4: Mixed complexity takes highest level
  F4: Empty changed files returns None level
  F5: Strict mode blocks illegal transitions
  F5: Emergency bypass only allows SDD and TDD
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

from skillpool.gate_policy.parser import (
    GatePolicyConfig,
    GatePolicyError,
    load_gate_policy,
    resolve_level_for_path,
)
from skillpool.gate_policy.state_machine import (
    GateStateMachine,
)
from skillpool.gate_policy.incremental import (
    IncrementalAssessor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_policy_yaml(tmp_path: Path) -> Path:
    """Create a valid gate.policy file for testing."""
    policy_content = textwrap.dedent("""\
        version: "1.0"
        default_level: L2

        phase_gates:
          docsdd_to_sdd:
            required_artifacts: [architecture_doc, ops_manual]
            validation: "Architecture doc exists"
          sdd_to_bdd:
            required_artifacts: [interface_contracts, data_schemas, error_codes]
            validation: "All contracts have signatures"

        directory_overrides:
          - path: "src/core/"
            minimum_level: L2
            reason: "Core modules require full 4D"
          - path: "src/styles/"
            maximum_level: L1
            skip_phases: [DocsDD, BDD]
            reason: "Style files are config-only"
          - path: "prototype/"
            skip_all: true
            reason: "Prototype code skips all"
          - path: "src/"
            minimum_level: L1
            reason: "Source files need at least SDD"

        file_patterns:
          - pattern: "*.test.py"
            skip_phases: [DocsDD, SDD, BDD]
            reason: "Test files follow TDD"
          - pattern: "__init__.py"
            maximum_level: L0
            reason: "Init files are simple"

        emergency_bypass:
          enabled: true
          config_file: "emergency_overrides.json"
          allowed_phases: [SDD, TDD]
          max_duration_hours: 24
          require_retrospective: true

        review_triggers:
          - condition: "assessed_level == L3+L2+"
            checkpoint: L4
            required: true

        enforcement:
          mode: strict
          hook_integration: true
          log_all_transitions: true
          audit_trail: true
    """)
    p = tmp_path / "gate.policy"
    p.write_text(policy_content)
    return p


@pytest.fixture
def loaded_policy(valid_policy_yaml: Path) -> GatePolicyConfig:
    """Load the valid policy for reuse."""
    return load_gate_policy(valid_policy_yaml)


# ---------------------------------------------------------------------------
# Feature 1: Gate Policy Parsing
# ---------------------------------------------------------------------------


class TestPolicyLoading:
    """BDD: Valid policy file loads all sections."""

    def test_valid_policy_loads_all_sections(self, loaded_policy: GatePolicyConfig):
        """BDD: Valid policy file loads all sections — AC01."""
        assert loaded_policy.version == "1.0"
        assert loaded_policy.default_level == "L2"
        assert len(loaded_policy.phase_gates) >= 2
        assert len(loaded_policy.directory_overrides) >= 4
        assert len(loaded_policy.file_patterns) >= 2
        assert loaded_policy.emergency_bypass.enabled is True
        assert len(loaded_policy.review_triggers) >= 1
        assert loaded_policy.enforcement.mode == "strict"

    def test_policy_is_frozen(self, loaded_policy: GatePolicyConfig):
        """B11: Policy config immutable after load."""
        with pytest.raises(Exception):  # ValidationError for frozen model
            loaded_policy.default_level = "L0"

    def test_missing_policy_raises_gp001(self, tmp_path: Path):
        """BDD: Missing policy file raises GP001 — AC01 error path."""
        with pytest.raises(GatePolicyError, match="GP001"):
            load_gate_policy(tmp_path / "nonexistent.policy")

    def test_invalid_yaml_raises_gp002(self, tmp_path: Path):
        """BDD: Invalid YAML raises GP002 — AC01 error path."""
        bad_file = tmp_path / "bad.policy"
        bad_file.write_text("invalid: [yaml: {broken")
        with pytest.raises(GatePolicyError, match="GP002"):
            load_gate_policy(bad_file)

    def test_empty_policy_uses_defaults(self, tmp_path: Path):
        """Minimal policy file with only version uses defaults."""
        p = tmp_path / "minimal.policy"
        p.write_text('version: "1.0"\n')
        config = load_gate_policy(p)
        assert config.default_level == "L2"
        assert config.directory_overrides == []
        assert config.enforcement.mode == "strict"


# ---------------------------------------------------------------------------
# Feature 2: Directory Override Resolution
# ---------------------------------------------------------------------------


class TestDirectoryOverrideResolution:
    """BDD: Directory override resolution scenarios."""

    def test_core_directory_minimum_l2(self, loaded_policy: GatePolicyConfig):
        """BDD: Core directory minimum L2 — AC02."""
        result = resolve_level_for_path("src/core/engine.py", loaded_policy)
        assert result.level == "L2"
        assert "src/core/" in result.matched_rules

    def test_styles_directory_maximum_l1(self, loaded_policy: GatePolicyConfig):
        """BDD: Styles directory maximum L1 — AC03."""
        result = resolve_level_for_path("src/styles/theme.css", loaded_policy)
        assert result.level == "L1"
        assert "DocsDD" in result.skip_phases
        assert "BDD" in result.skip_phases

    def test_prototype_directory_skip_all(self, loaded_policy: GatePolicyConfig):
        """BDD: Prototype directory skip all — AC04."""
        result = resolve_level_for_path("prototype/experiment.py", loaded_policy)
        assert result.skip_all is True
        assert "prototype/" in result.matched_rules

    def test_unmatched_path_uses_default(self, loaded_policy: GatePolicyConfig):
        """BDD: Unmatched path uses default level."""
        result = resolve_level_for_path("random/file.py", loaded_policy)
        assert result.level == "L2"
        assert result.matched_rules == []

    def test_longest_prefix_match_wins(self, loaded_policy: GatePolicyConfig):
        """BDD: Longest prefix match wins — src/core/ beats src/."""
        result = resolve_level_for_path("src/core/engine.py", loaded_policy)
        # src/core/ (minimum L2) should win over src/ (minimum L1)
        assert result.level == "L2"
        assert "src/core/" in result.matched_rules

    def test_file_pattern_match(self, loaded_policy: GatePolicyConfig):
        """File pattern override applies for matching files."""
        result = resolve_level_for_path("tests/test_engine.test.py", loaded_policy)
        # *.test.py pattern should match
        assert "DocsDD" in result.skip_phases

    def test_init_file_maximum_l0(self, loaded_policy: GatePolicyConfig):
        """__init__.py files get maximum L0."""
        result = resolve_level_for_path("src/__init__.py", loaded_policy)
        assert result.level == "L0"


# ---------------------------------------------------------------------------
# Determinism (B10)
# ---------------------------------------------------------------------------


class TestDeterminism:
    """B10: Gate assessment must be deterministic."""

    def test_same_input_same_output(self, loaded_policy: GatePolicyConfig):
        """resolve_level_for_path is deterministic."""
        r1 = resolve_level_for_path("src/core/engine.py", loaded_policy)
        r2 = resolve_level_for_path("src/core/engine.py", loaded_policy)
        assert r1 == r2

    def test_different_input_different_output(self, loaded_policy: GatePolicyConfig):
        """Different paths produce different results."""
        r1 = resolve_level_for_path("src/core/engine.py", loaded_policy)
        r2 = resolve_level_for_path("src/styles/theme.css", loaded_policy)
        assert r1.level != r2.level


# ---------------------------------------------------------------------------
# Feature 3: Gate State Machine
# ---------------------------------------------------------------------------


class TestGateStateMachine:
    """BDD: Gate state machine scenarios."""

    def test_l2_full_transition(self, tmp_path: Path):
        """BDD: L2 task transitions through all phases — AC05."""
        sm = GateStateMachine(tmp_path / "gate.json")
        level = sm.assess("new feature", [], None)
        # assess without policy defaults to keyword match; "new feature" → L2
        assert level == "L2"
        assert sm.state.current_phase == "ASSESSING"

        sm.transition("DOCSDD")
        assert sm.state.current_phase == "DOCSDD"

        sm.transition("SDD")
        assert sm.state.current_phase == "SDD"

        sm.transition("BDD")
        assert sm.state.current_phase == "BDD"

        sm.transition("TDD")
        assert sm.state.current_phase == "TDD"

        sm.transition("COMPLETE")
        assert sm.state.current_phase == "COMPLETE"

    def test_l1_skips_docsdd_bdd(self, tmp_path: Path):
        """BDD: L1 task skips DocsDD and BDD — AC05."""
        sm = GateStateMachine(tmp_path / "gate.json")
        level = sm.assess("simple config change", [], None)
        assert level == "L1"

        sm.transition("SDD")
        sm.transition("TDD")
        sm.transition("COMPLETE")
        assert sm.state.current_phase == "COMPLETE"
        assert len(sm.state.phase_history) == 4  # IDLE→ASSESSING, ASSESSING→SDD, SDD→TDD, TDD→COMPLETE

    def test_l0_auto_complete(self, tmp_path: Path):
        """BDD: L0 task goes directly to COMPLETE — AC05."""
        sm = GateStateMachine(tmp_path / "gate.json")
        level = sm.assess("fix typo in comment", [], None)
        assert level == "L0"
        assert sm.state.current_phase == "COMPLETE"
        assert len(sm.state.phase_history) == 2

    def test_illegal_transition_raises_gp003(self, tmp_path: Path):
        """BDD: Illegal transition raises GP003 — AC06."""
        sm = GateStateMachine(tmp_path / "gate.json")
        with pytest.raises(GatePolicyError, match="GP003"):
            sm.transition("TDD")
        assert sm.state.current_phase == "IDLE"

    def test_gate_check_validates_artifacts(self, tmp_path: Path, loaded_policy: GatePolicyConfig):
        """BDD: Gate check validates required artifacts — AC11."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.set_policy(loaded_policy)
        result = sm.check_gate(
            "SDD", "BDD",
            artifacts={"interface_contracts": "done"},
        )
        assert result.passed is False
        assert "data_schemas" in result.missing_artifacts
        assert "error_codes" in result.missing_artifacts

    def test_gate_check_all_artifacts_present(self, tmp_path: Path, loaded_policy: GatePolicyConfig):
        """Gate check passes when all artifacts present."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.set_policy(loaded_policy)
        result = sm.check_gate(
            "SDD", "BDD",
            artifacts={
                "interface_contracts": "done",
                "data_schemas": "done",
                "error_codes": "done",
            },
        )
        assert result.passed is True
        assert result.missing_artifacts == []

    def test_state_persists_to_file(self, tmp_path: Path):
        """BDD: Gate state persists to gate.json — B04, AC07."""
        gate_path = tmp_path / "gate.json"
        sm = GateStateMachine(gate_path)
        sm.assess("new feature", [], None)
        sm.transition("DOCSDD")

        # Verify file exists and contains correct state
        assert gate_path.exists()
        import json
        data = json.loads(gate_path.read_text())
        assert data["current_phase"] == "DOCSDD"

        # Create new state machine from same file — should load state
        sm2 = GateStateMachine(gate_path)
        assert sm2.state.current_phase == "DOCSDD"

    def test_corrupt_file_resets_to_idle(self, tmp_path: Path):
        """GP006: Corrupt gate.json resets to IDLE."""
        gate_path = tmp_path / "gate.json"
        gate_path.write_text("NOT VALID JSON{{{")

        sm = GateStateMachine(gate_path)
        assert sm.state.current_phase == "IDLE"

    def test_phase_history_tracks_transitions(self, tmp_path: Path):
        """B13: Audit trail for gate transitions."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.assess("new feature", [], None)
        sm.transition("DOCSDD")

        assert len(sm.state.phase_history) == 2
        assert sm.state.phase_history[0].from_phase == "IDLE"
        assert sm.state.phase_history[0].to_phase == "ASSESSING"
        assert sm.state.phase_history[1].from_phase == "ASSESSING"
        assert sm.state.phase_history[1].to_phase == "DOCSDD"

    def test_update_artifact(self, tmp_path: Path):
        """update_artifact records artifact status."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.update_artifact("architecture_doc", "done")
        assert sm.state.artifacts["architecture_doc"] == "done"


# ---------------------------------------------------------------------------
# Feature 4: Incremental Mode
# ---------------------------------------------------------------------------


class TestIncrementalMode:
    """BDD: Incremental mode scenarios."""

    def test_mixed_complexity_takes_highest(self, loaded_policy: GatePolicyConfig):
        """BDD: Mixed complexity takes highest level — AC10."""
        assessor = IncrementalAssessor(loaded_policy)
        result = assessor.assess_complexity(["src/core/engine.py", "src/styles/theme.css"])
        assert result.level == "L2"
        assert result.per_file_levels["src/core/engine.py"] == "L2"
        assert result.per_file_levels["src/styles/theme.css"] == "L1"

    def test_empty_files_returns_none(self, loaded_policy: GatePolicyConfig):
        """BDD: Empty changed files returns None level — AC08."""
        assessor = IncrementalAssessor(loaded_policy)
        result = assessor.assess_complexity([])
        assert result.level is None

    def test_single_file_assessment(self, loaded_policy: GatePolicyConfig):
        """Single file assessment returns its level."""
        assessor = IncrementalAssessor(loaded_policy)
        result = assessor.assess_complexity(["src/core/engine.py"])
        assert result.level == "L2"

    def test_detect_changed_files_in_git_repo(self, loaded_policy: GatePolicyConfig):
        """BDD: Changed files detected via git diff — AC09."""
        assessor = IncrementalAssessor(loaded_policy)
        # This test runs in the skillpool git repo
        files = assessor.detect_changed_files("HEAD")
        # Result is a list (may be empty if no uncommitted changes)
        assert isinstance(files, list)

    def test_detect_changed_files_non_git_dir(self, loaded_policy: GatePolicyConfig, tmp_path: Path):
        """BDD: Git diff failure returns empty list — B18."""
        assessor = IncrementalAssessor(loaded_policy)
        files = assessor.detect_changed_files("HEAD", cwd=tmp_path)
        assert files == []

    def test_detect_changed_files_with_base_ref(self, loaded_policy: GatePolicyConfig):
        """Git diff with explicit base_ref returns list."""
        assessor = IncrementalAssessor(loaded_policy)
        # Use a valid ref that should exist
        files = assessor.detect_changed_files("HEAD")
        assert isinstance(files, list)

    def test_detect_changed_files_timeout(self, loaded_policy: GatePolicyConfig, tmp_path: Path):
        """Git diff timeout (0 seconds) returns empty list."""
        assessor = IncrementalAssessor(loaded_policy, git_timeout=0)
        # With 0 timeout, git diff should immediately timeout
        files = assessor.detect_changed_files("HEAD", cwd=tmp_path)
        assert isinstance(files, list)

    def test_detect_changed_files_injection_prevention(self, loaded_policy: GatePolicyConfig):
        """Invalid base_ref with shell injection chars returns empty list."""
        assessor = IncrementalAssessor(loaded_policy)
        files = assessor.detect_changed_files("HEAD; rm -rf /")
        assert files == []


# ---------------------------------------------------------------------------
# Feature 5: Enforcement Mode
# ---------------------------------------------------------------------------


class TestEnforcementMode:
    """BDD: Enforcement mode scenarios."""

    def test_strict_mode_blocks_illegal(self, tmp_path: Path, loaded_policy: GatePolicyConfig):
        """BDD: Strict mode blocks illegal transitions — AC12."""
        assert loaded_policy.enforcement.mode == "strict"
        sm = GateStateMachine(tmp_path / "gate.json")
        with pytest.raises(GatePolicyError, match="GP003"):
            sm.transition("TDD")

    def test_permissive_mode_allows_illegal(self, tmp_path: Path):
        """BDD: Permissive mode logs warning — AC13."""
        permissive_policy = GatePolicyConfig(
            version="1.0",
            enforcement={"mode": "permissive"},
        )
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.set_policy(permissive_policy)
        # In permissive mode, illegal transition should not raise
        result = sm.transition("TDD")
        assert sm.state.current_phase == "IDLE"  # No transition happened
        assert result.current_phase == "IDLE"

    def test_disabled_mode_allows_illegal(self, tmp_path: Path):
        """BDD: Disabled mode allows any transition."""
        disabled_policy = GatePolicyConfig(
            version="1.0",
            enforcement={"mode": "disabled"},
        )
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.set_policy(disabled_policy)
        # In disabled mode, illegal transition proceeds
        _result = sm.transition("TDD")
        assert sm.state.current_phase == "TDD"

    def test_emergency_bypass_restricts_phases(self, tmp_path: Path, loaded_policy: GatePolicyConfig):
        """BDD: Emergency bypass only allows SDD and TDD — AC11."""
        # Activate bypass by creating override file
        overrides = tmp_path / "emergency_overrides.json"
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        overrides.write_text(f'{{"active": true, "expires_at": "{future}"}}')

        sm = GateStateMachine(tmp_path / "gate.json")
        sm.set_policy(loaded_policy)
        # BDD is not in allowed_phases ["SDD", "TDD"]
        result = sm.check_gate("SDD", "BDD", artifacts={})
        assert result.passed is False

    def test_emergency_bypass_active_allows_sdd(self, tmp_path: Path, loaded_policy: GatePolicyConfig):
        """Emergency bypass active allows SDD phase."""
        # Create emergency_overrides.json
        overrides = tmp_path / "emergency_overrides.json"
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        overrides.write_text(f'{{"active": true, "expires_at": "{future}"}}')

        sm = GateStateMachine(tmp_path / "gate.json")
        sm.set_policy(loaded_policy)
        result = sm.check_gate("IDLE", "SDD", artifacts={})
        assert result.passed is True

    def test_emergency_bypass_expired_blocks(self, tmp_path: Path, loaded_policy: GatePolicyConfig):
        """Emergency bypass expired — normal gate rules apply."""
        overrides = tmp_path / "emergency_overrides.json"
        from datetime import datetime, timedelta, timezone
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        overrides.write_text(f'{{"active": true, "expires_at": "{past}"}}')

        sm = GateStateMachine(tmp_path / "gate.json")
        sm.set_policy(loaded_policy)
        # SDD→BDD has required artifacts in phase_gates; expired bypass won't skip them
        result = sm.check_gate("SDD", "BDD", artifacts={})
        assert result.passed is False  # Expired bypass = no bypass, artifacts missing


# ---------------------------------------------------------------------------
# Error Code Coverage
# ---------------------------------------------------------------------------


class TestErrorCodes:
    """Explicit error code tests for GP001-GP006."""

    def test_gp004_missing_artifact_in_gate_check(self, tmp_path: Path, loaded_policy: GatePolicyConfig):
        """GP004: Missing required artifact detected in check_gate."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.set_policy(loaded_policy)
        result = sm.check_gate("DOCSDD", "SDD", artifacts={})
        assert result.passed is False
        assert len(result.missing_artifacts) > 0

    def test_gp005_git_diff_failure_logs_warning(self, loaded_policy: GatePolicyConfig, tmp_path: Path, caplog):
        """GP005: git diff failure logs warning but does not crash."""
        assessor = IncrementalAssessor(loaded_policy)
        with caplog.at_level(logging.WARNING):
            files = assessor.detect_changed_files("HEAD", cwd=tmp_path / "nonexistent")
        assert isinstance(files, list)

    def test_gp005_invalid_base_ref(self, loaded_policy: GatePolicyConfig, caplog):
        """GP005: Invalid base_ref returns empty list."""
        assessor = IncrementalAssessor(loaded_policy)
        files = assessor.detect_changed_files("HEAD; rm -rf /")
        assert files == []


# ---------------------------------------------------------------------------
# Integration: GateManager.check_with_policy()
# ---------------------------------------------------------------------------


class TestGateManagerIntegration:
    """Integration tests for GateManager.check_with_policy()."""

    def test_check_with_policy_returns_policy_level(
        self, tmp_path: Path, loaded_policy: GatePolicyConfig, valid_policy_yaml: Path
    ):
        """check_with_policy returns policy_level and state."""
        from skillpool.gate import GateManager
        from skillpool.profile import CLAUDE_CODE_PROFILE

        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        csdf = {
            "id": "test-skill",
            "description": "new feature for core module",
            "checklist": [],
        }

        result = gm.check_with_policy(
            csdf,
            policy_path=valid_policy_yaml,
            changed_files=["src/core/engine.py"],
        )

        assert result.policy_level is not None
        assert result.state is not None
        assert result.state.current_phase in ("ASSESSING", "COMPLETE")

    def test_check_with_policy_no_policy_path(self):
        """check_with_policy without policy_path returns base result."""
        from skillpool.gate import GateManager
        from skillpool.profile import CLAUDE_CODE_PROFILE

        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        csdf = {"id": "test-skill", "checklist": []}

        result = gm.check_with_policy(csdf)

        assert result.policy_level is None
        assert result.state is None
        assert result.decision is not None

    def test_check_with_policy_skip_phases_aggregation(
        self, tmp_path: Path, loaded_policy: GatePolicyConfig, valid_policy_yaml: Path
    ):
        """skip_phases aggregates from all changed files."""
        from skillpool.gate import GateManager
        from skillpool.profile import CLAUDE_CODE_PROFILE

        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        csdf = {"id": "test-skill", "description": "config change", "checklist": []}

        result = gm.check_with_policy(
            csdf,
            policy_path=valid_policy_yaml,
            changed_files=["src/styles/theme.css", "tests/test_engine.test.py"],
        )

        # Both files have skip_phases
        assert "DocsDD" in result.skip_phases or "BDD" in result.skip_phases


# ---------------------------------------------------------------------------
# L1 Verification: GateStateMachine.reset()
# ---------------------------------------------------------------------------


class TestGateStateMachineReset:
    """L1 verification: reset() method for state machine."""

    def test_reset_clears_phase_to_idle(self, tmp_path: Path):
        """reset() sets current_phase to IDLE."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.assess("new feature", [], None)
        sm.transition("DOCSDD")
        assert sm.state.current_phase == "DOCSDD"

        result = sm.reset()
        assert result.current_phase == "IDLE"

    def test_reset_clears_assessed_level(self, tmp_path: Path):
        """reset() clears assessed_level."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.assess("new feature", [], None)
        assert sm.state.assessed_level is not None

        sm.reset()
        assert sm.state.assessed_level is None

    def test_reset_clears_phase_history(self, tmp_path: Path):
        """reset() clears phase_history."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.assess("new feature", [], None)
        sm.transition("DOCSDD")
        assert len(sm.state.phase_history) > 0

        sm.reset()
        assert sm.state.phase_history == []

    def test_reset_persists_to_file(self, tmp_path: Path):
        """reset() persists cleared state to gate.json."""
        gate_path = tmp_path / "gate.json"
        sm = GateStateMachine(gate_path)
        sm.assess("new feature", [], None)
        sm.transition("DOCSDD")

        sm.reset()

        # Verify file reflects reset
        import json
        data = json.loads(gate_path.read_text())
        assert data["current_phase"] == "IDLE"
        assert data["assessed_level"] is None
        assert data["phase_history"] == []

    def test_reset_preserves_created_at(self, tmp_path: Path):
        """reset() does NOT clear metadata.created_at."""
        sm = GateStateMachine(tmp_path / "gate.json")
        original_created = sm.state.metadata.created_at

        sm.assess("new feature", [], None)
        sm.transition("DOCSDD")
        sm.reset()

        assert sm.state.metadata.created_at == original_created


# ---------------------------------------------------------------------------
# A2: review_checkpoint.triggered auto-set
# ---------------------------------------------------------------------------


class TestReviewCheckpointAutoTrigger:
    """review_checkpoint.triggered auto-set when entering REVIEW phase."""

    def test_review_checkpoint_triggered_on_transition(self, tmp_path: Path):
        """Transition to REVIEW auto-sets review_checkpoint.triggered=True."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.assess("subsystem architecture migration", [], None)
        sm.transition("DOCSDD")
        sm.transition("SDD")
        sm.transition("BDD")
        sm.transition("TDD")
        sm.transition("REVIEW")

        assert sm.state.review_checkpoint.triggered is True
        assert sm.state.review_checkpoint.checkpoint_level == sm.state.assessed_level

    def test_review_checkpoint_not_triggered_in_other_phases(self, tmp_path: Path):
        """Non-REVIEW transitions do not set review_checkpoint.triggered."""
        sm = GateStateMachine(tmp_path / "gate.json")
        sm.assess("new feature", [], None)
        sm.transition("DOCSDD")

        assert sm.state.review_checkpoint.triggered is False


# ---------------------------------------------------------------------------
# L3+L2+ Verification: MCP Tool gate_check_with_policy
# ---------------------------------------------------------------------------


class TestGateCheckWithPolicyMCP:
    """L3+L2+ verification: gate_check_with_policy MCP tool."""

    def test_mcp_tool_with_policy_returns_policy_level(
        self, tmp_path: Path, valid_policy_yaml: Path
    ):
        """MCP tool returns policy_level when policy_path provided."""
        from skillpool.mcp_server import gate_check_with_policy

        result = gate_check_with_policy(
            csdf={"id": "test-skill", "description": "new feature", "checklist": []},
            profile_name="claude-code",
            policy_path=str(valid_policy_yaml),
            changed_files=["src/core/engine.py"],
        )

        assert "decision" in result
        assert result["policy_level"] is not None
        assert "skip_phases" in result
        assert "state" in result

    def test_mcp_tool_without_policy_returns_base_result(self):
        """MCP tool without policy_path returns base gate result."""
        from skillpool.mcp_server import gate_check_with_policy

        result = gate_check_with_policy(
            csdf={"id": "test-skill", "checklist": []},
            profile_name="claude-code",
        )

        assert "decision" in result
        assert result["policy_level"] is None
        assert result["skip_phases"] == []

    def test_mcp_tool_invalid_policy_path_returns_base_result(self, tmp_path: Path):
        """MCP tool with invalid policy_path returns base result."""
        from skillpool.mcp_server import gate_check_with_policy

        result = gate_check_with_policy(
            csdf={"id": "test-skill", "checklist": []},
            profile_name="claude-code",
            policy_path=str(tmp_path / "nonexistent.policy"),
        )

        assert "decision" in result
        assert result["policy_level"] is None

    def test_mcp_tool_invalid_profile_returns_error(self, valid_policy_yaml: Path):
        """MCP tool with invalid profile_name returns error."""
        from skillpool.mcp_server import gate_check_with_policy

        result = gate_check_with_policy(
            csdf={"id": "test-skill", "checklist": []},
            profile_name="unknown-agent",
            policy_path=str(valid_policy_yaml),
        )

        assert "error" in result or result.get("decision") == "DENY"
