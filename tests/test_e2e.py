"""Sprint 5: Integration test — end-to-end workflow."""

from skillpool.lifecycle import SkillLifecycleState, validate_transition
from skillpool.profile import CLAUDE_CODE_PROFILE, CODEX_PROFILE, HERMES_PROFILE
from skillpool.materializer import Materializer
from skillpool.materializer.mapper import CSDFMapper
from skillpool.materializer.budget_cropper import BudgetCropper
from skillpool.materializer.lifecycle_filter import LifecycleFilter
from skillpool.telemetry import TelemetryBridge, TelemetryChannel
from skillpool.gate import GateManager, GateDecision
from skillpool.paradigm import ParadigmRegistry, Paradigm


def test_full_pipeline():
    """End-to-end: CSDF → Materialize → Gate → Telemetry."""
    # 1. Create a sample CSDF skill
    csdf = {
        "id": "test-skill",
        "name": "Test Skill",
        "dimension": "D3",
        "weight": 0.12,
        "veto_rule": "score < 7.0 → reject",
        "description": "A test skill for integration",
        "checklist": [{"item": "Check X", "priority": "high"}],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "min_trust_level": 1,
    }

    # 2. Profile check
    profile = CLAUDE_CODE_PROFILE
    can_execute, reason = profile.can_execute(
        {
            "required_capabilities": {"file_system", "python"},
            "min_trust_level": 1,
        }
    )
    assert can_execute, f"Profile should execute: {reason}"

    # 3. Gate check
    gate = GateManager(profile=profile)
    result = gate.check(csdf)
    assert result.decision in (GateDecision.ALLOW, GateDecision.GUARD, GateDecision.ESCALATE)

    # 4. Materialize
    mapper = CSDFMapper()
    lifecycle_filter = LifecycleFilter()
    cropper = BudgetCropper(max_tokens=400)

    mapped = mapper.map(csdf)
    filtered = lifecycle_filter.filter(mapped, csdf)
    _cropped = cropper.crop(filtered)

    # 5. Log telemetry
    bridge = TelemetryBridge()
    bridge.emit("materialize_complete", skill_id=csdf["id"])

    # 6. Check paradigm
    registry = ParadigmRegistry()
    registry.register_defaults()
    paradigm = registry.get(Paradigm.TDD)
    assert paradigm is not None

    print("Integration test passed: CSDF → Materialize → Gate → Telemetry")


def test_lifecycle_transitions():
    """Test state machine lifecycle."""
    state = SkillLifecycleState.DRAFT
    assert state == SkillLifecycleState.DRAFT
    # valid transitions
    assert validate_transition(SkillLifecycleState.DRAFT, SkillLifecycleState.PROPOSED)
    assert validate_transition(SkillLifecycleState.PROPOSED, SkillLifecycleState.UNDER_REVIEW)
    assert validate_transition(SkillLifecycleState.ACTIVE, SkillLifecycleState.DEPRECATED)


def test_end_to_end_materialization():
    """End-to-end: CSDF → MaterializedSkill object."""
    csdf = {
        "id": "S01",
        "name": "Requirement Coverage",
        "dimension": "D1",
        "weight": 0.1,
        "lifecycle_state": "active",
        "description": "Test skill for integration",
        "checklist": [{"item": "Check coverage", "priority": "high"}],
    }
    mat = Materializer(profile=CLAUDE_CODE_PROFILE)
    result = mat.materialize(csdf_dict=csdf)
    assert result.skill is not None
    assert result.skill.name == "Requirement Coverage"
    assert len(result.skill.markdown) > 0


def test_gate_manager_deny():
    """Test GateManager blocks unauthorized profiles."""
    gate = GateManager(HERMES_PROFILE)
    csdf = {
        "id": "test",
        "min_trust_level": 3,
        "required_agent_capabilities": {"bash", "python"},
    }
    result = gate.check(csdf)
    assert result.decision == GateDecision.DENY


def test_paradigm_registry_defaults():
    """Verify paradigm registry loads all 4 default paradigms."""
    registry = ParadigmRegistry()
    registry.register_defaults()
    for p in [Paradigm.DOCS_DD, Paradigm.SDD, Paradigm.BDD, Paradigm.TDD]:
        entry = registry.get(p)
        assert entry is not None
        assert entry.paradigm == p


def test_profile_capabilities():
    """Verify all preset profiles have expected capabilities."""
    assert CLAUDE_CODE_PROFILE.required_capabilities == {"bash", "file_system", "python", "web_search"}
    assert CODEX_PROFILE.required_capabilities == {"bash", "file_system", "python"}
    assert HERMES_PROFILE.required_capabilities == {"file_system", "web_search"}


def test_telemetry_bridge_e2e():
    """Full telemetry round-trip: emit → read."""
    bridge = TelemetryBridge()
    bridge.emit("skill_executed", skill_id="S05a", channel=TelemetryChannel.HOOK)
    events = bridge.read_events(skill_id="S05a", event_type="skill_executed")
    assert len(events) >= 1
    assert events[0].event_type == "skill_executed"
