"""Unit tests for GateManager and ComplexityAssessor."""

from skillpool.gate import (
    ComplexityAssessor,
    ComplexityScore,
    GateDecision,
    GateManager,
)
from skillpool.profile import CLAUDE_CODE_PROFILE, CODEX_PROFILE, HERMES_PROFILE
from skillpool.telemetry import TelemetryBridge


# ---- Fixtures ----


def _sample_csdf(**overrides):
    base = {
        "id": "S05a-security",
        "name": "Security Transport",
        "version": "1.0.0",
        "dimension": "D3",
        "checklist": [
            {"item": "Check TLS config", "priority": "high"},
            {"item": "Verify cert chain", "priority": "high"},
        ],
        "veto_rule": "score < 7.0 -> reject",
        "min_trust_level": 2,
        "required_agent_capabilities": {"bash", "file_system"},
        "paradigm": "review",
    }
    base.update(overrides)
    return base


def _telemetry_bridge(tmp_path):
    return TelemetryBridge(log_dir=tmp_path / "telemetry")


# ---- ComplexityAssessor ----


class TestComplexityAssessor:
    def test_low_complexity(self):
        assessor = ComplexityAssessor()
        csdf = {"checklist": [], "min_trust_level": 0, "veto_rule": None}
        score = assessor.assess(csdf)
        assert score.level == "low"
        assert score.total < 0.3

    def test_high_complexity(self):
        assessor = ComplexityAssessor()
        csdf = {
            "checklist": [{"item": f"Check {i}"} for i in range(18)],
            "min_trust_level": 3,
            "veto_rule": "score < 7.0 -> reject",
            "dependency_depth": 4,
        }
        score = assessor.assess(csdf)
        assert score.level in ("high", "critical")
        assert score.total >= 0.6

    def test_medium_complexity(self):
        assessor = ComplexityAssessor()
        csdf = {
            "checklist": [{"item": f"Check {i}"} for i in range(8)],
            "min_trust_level": 2,
            "veto_rule": None,
        }
        score = assessor.assess(csdf)
        assert score.level in ("low", "medium")

    def test_critical_complexity(self):
        assessor = ComplexityAssessor()
        csdf = {
            "checklist": [{"item": f"Check {i}"} for i in range(20)],
            "min_trust_level": 3,
            "veto_rule": "score < 5.0 -> reject",
            "dependency_depth": 5,
        }
        score = assessor.assess(csdf)
        assert score.level == "critical"
        assert score.total >= 0.8

    def test_veto_risk_scoring(self):
        assessor = ComplexityAssessor()
        with_veto = assessor.assess({"veto_rule": "block"})
        without_veto = assessor.assess({"veto_rule": None})
        assert with_veto.veto_risk == 0.8
        assert without_veto.veto_risk == 0.1

    def test_custom_weights(self):
        assessor = ComplexityAssessor(
            weights={
                "context_size": 0.5,
                "dependency_depth": 0.2,
                "trust_requirement": 0.2,
                "veto_risk": 0.1,
            }
        )
        csdf = {"checklist": [{"item": "x"}] * 10, "min_trust_level": 0, "veto_rule": None}
        score = assessor.assess(csdf)
        assert score.total > 0

    def test_empty_csdf(self):
        assessor = ComplexityAssessor()
        score = assessor.assess({})
        assert score.level == "low"
        assert score.total < 0.3

    def test_complexity_score_level_property(self):
        s = ComplexityScore(total=0.1)
        assert s.level == "low"
        s = ComplexityScore(total=0.4)
        assert s.level == "medium"
        s = ComplexityScore(total=0.7)
        assert s.level == "high"
        s = ComplexityScore(total=0.9)
        assert s.level == "critical"


# ---- GateManager ----


class TestGateManager:
    def test_allow_low_complexity(self):
        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        csdf = _sample_csdf(checklist=[], veto_rule=None, min_trust_level=0)
        result = gm.check(csdf)
        assert result.decision == GateDecision.ALLOW

    def test_guard_medium_complexity(self):
        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        csdf = _sample_csdf(
            checklist=[{"item": f"Check {i}"} for i in range(8)],
            veto_rule=None,
            min_trust_level=2,
        )
        result = gm.check(csdf)
        # Medium complexity → GUARD or ALLOW depending on total score
        assert result.decision in (GateDecision.ALLOW, GateDecision.GUARD)

    def test_escalate_high_complexity(self):
        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        csdf = _sample_csdf(
            checklist=[{"item": f"Check {i}"} for i in range(18)],
            min_trust_level=3,
            veto_rule="score < 7.0",
        )
        result = gm.check(csdf)
        # High complexity + veto → ESCALATE or DENY (depending on total)
        assert result.decision in (GateDecision.ESCALATE, GateDecision.DENY)

    def test_deny_capability_mismatch(self):
        gm = GateManager(profile=HERMES_PROFILE)
        csdf = _sample_csdf(
            required_agent_capabilities={"bash", "python", "network"},
            min_trust_level=3,
        )
        result = gm.check(csdf)
        assert result.decision == GateDecision.DENY
        assert "capability mismatch" in result.reason

    def test_deny_critical_complexity(self):
        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        csdf = _sample_csdf(
            checklist=[{"item": f"Check {i}"} for i in range(20)],
            min_trust_level=3,
            veto_rule="score < 5.0",
            dependency_depth=5,
            required_agent_capabilities={"bash", "file_system"},
        )
        result = gm.check(csdf)
        assert result.decision in (GateDecision.DENY, GateDecision.ESCALATE)

    def test_escalate_with_veto_risk(self):
        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        csdf = _sample_csdf(
            checklist=[{"item": f"Check {i}"} for i in range(14)],
            veto_rule="score < 7.0 -> reject",
            min_trust_level=2,
        )
        result = gm.check(csdf)
        # veto_risk + high enough total → ESCALATE or GUARD
        assert result.decision in (GateDecision.ESCALATE, GateDecision.GUARD)

    def test_gate_result_has_complexity(self):
        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        result = gm.check(_sample_csdf())
        assert result.complexity is not None
        assert result.complexity.level in ("low", "medium", "high", "critical")

    def test_with_telemetry(self, tmp_path):
        bridge = _telemetry_bridge(tmp_path)
        gm = GateManager(profile=CLAUDE_CODE_PROFILE, telemetry=bridge)
        gm.check(_sample_csdf())
        events = bridge.read_events(event_type="gate_check")
        assert len(events) >= 1
        assert events[0].payload["decision"] in ("allow", "guard", "escalate", "deny")

    def test_codex_profile_guard(self):
        gm = GateManager(profile=CODEX_PROFILE)
        csdf = _sample_csdf(
            paradigm="code",
            required_agent_capabilities={"bash", "file_system"},
            min_trust_level=2,
        )
        result = gm.check(csdf)
        assert result.decision in (GateDecision.ALLOW, GateDecision.GUARD, GateDecision.ESCALATE)

    def test_empty_csdf(self):
        gm = GateManager(profile=CLAUDE_CODE_PROFILE)
        result = gm.check({})
        assert result.decision == GateDecision.ALLOW

    def test_gate_decision_enum(self):
        assert GateDecision.ALLOW == "allow"
        assert GateDecision.GUARD == "guard"
        assert GateDecision.DENY == "deny"
        assert GateDecision.ESCALATE == "escalate"
